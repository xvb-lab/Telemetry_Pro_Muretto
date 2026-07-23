"""Entry point del MURETTO — processo separato.

Mette insieme la catena: dati LMU (core.reader + core.strategy) -> cervello
(engineer.brain.Engineer) -> voce (core.voice), coi 3 ruoli/voci
(engineer.roles). Parlato-only.

Uso:
  python -m engineer.run_engineer          # loop live (legge LMU in sessione)
  python -m engineer.run_engineer --demo   # simulazione: fa parlare la
                                            # strategia senza essere in pista
"""
import sys
import threading
import time
from pathlib import Path

from core.reader import TelemetryReader
from core.strategy import StrategyFeed, auto_fuel_target, fetch_weather5
from core.shared_memory import SharedMemory
from core.voice import Voice
from core import engineer_cfg
from engineer.brain import Engineer
from engineer.roles import voice_for, role_for, ROLE_LABEL
from engineer.radio import RadioManager

_AUDIO = Path(__file__).resolve().parent.parent / "assets" / "audio"


def _pick(name):
    """Percorso del tono: preferisce la versione WAV amplificata, fallback mp3."""
    w = _AUDIO / (name + ".wav")
    return w if w.exists() else (_AUDIO / (name + ".mp3"))


_BEEP = _pick("radio")      # tono OPEN (prima della voce)
_END = _pick("end")         # tono OVER (fine messaggio)
_PTT = _pick("push")        # tono push-to-talk (riservato: radio a 2 vie da fare)


def _apply_cfg(vox, cfg):
    """Applica le opzioni (volume voce, beep on/off, ritardo tono) alla voce.
    Chiamata all'avvio e periodicamente, così i cambi dalle Opzioni si sentono
    senza riavviare l'ingegnere."""
    try:
        vox.set_volume(int(cfg.get("voice_vol", 100)))
    except Exception:
        pass
    try:
        vox.set_beep(str(_BEEP) if _BEEP.exists() else None,
                     bool(cfg.get("beep_on", True)))
    except Exception:
        pass
    try:
        vox.set_end(str(_END) if _END.exists() else None,
                    bool(cfg.get("beep_on", True)))
    except Exception:
        pass
    try:
        vox.set_tone_delay(float(cfg.get("beep_delay_s", 2.0)))
    except Exception:
        pass


_AF = {"ts": 0.0, "pct": None}
_WX = {"sig": None, "fc": None, "ts": 0.0}
_TINV = {"inv": None, "ts": 0.0}


def _tyre_inv():
    """Inventario gomme (REST TireManagement), cache 10s: slick nuovi/usati."""
    now = time.monotonic()
    if _TINV["inv"] is not None and (now - _TINV["ts"]) < 10.0:
        return _TINV["inv"]
    if (now - _TINV["ts"]) < 3.0:
        return _TINV["inv"]
    _TINV["ts"] = now
    try:
        import json as _j
        import urllib.request as _u
        req = _u.Request("http://localhost:6397/rest/garage/UIScreen/TireManagement",
                         headers={"Accept": "application/json"})
        with _u.urlopen(req, timeout=0.4) as r:
            d = _j.loads(r.read())
        go = (d or {}).get("tireInvGarageOptions") or {}
        first = (go.get("tireOptions") or [[]])[0]
        sn = su = 0
        for t in first:
            if isinstance(t, dict) and t.get("compoundIndex") == 0:
                su += 1 if t.get("isUsed") else 0
                sn += 0 if t.get("isUsed") else 1
        _TINV["inv"] = {"slick_new": sn, "slick_used": su}
    except Exception:
        _TINV["inv"] = None
    return _TINV["inv"]


def _forecast(d):
    """Forecast pioggia [5 nodi] della sessione, cache per (pista, tipo).
    Ritenta ogni 5s finche' LMU non lo espone (pre-verde puo' arrivare tardi)."""
    sig = (d.get("track"), d.get("session_type"))
    now = time.monotonic()
    if sig != _WX["sig"]:
        _WX["sig"] = sig
        _WX["fc"] = None
        _WX["ts"] = 0.0
    if _WX["fc"] is None and (now - _WX["ts"]) > 5.0:
        _WX["ts"] = now
        try:
            _WX["fc"] = fetch_weather5(d.get("session_type"))
        except Exception:
            _WX["fc"] = None
    return _WX["fc"]


# ── SPOTTER COMMUNITY: nome pilota in pista -> suo tempo di rif. su questa
#    pista (dai ref online). Fetch di rete UNA volta per pista+classi, in un
#    thread di sfondo: il loop del muretto non si blocca MAI. Degrada a vuoto
#    se offline / community disattivata.
_COMM = {"sig": None, "loading": False, "times": {}, "known": set()}


def _community_fetch(short_track, class_tags):
    """BG: costruisce times[(nome_lower, tag)] = miglior ms su QUESTA pista
    (online.top per ogni classe, DRY+WET) + known = set globale dei nomi noti
    (all_refs). Tutto difensivo: qualsiasi errore -> parziale/vuoto."""
    from core import online
    known = set()
    try:
        for row in (online.all_refs() or []):
            pn = (row.get("player") or "").strip().lower()
            if pn:
                known.add(pn)
    except Exception:
        pass
    times = {}
    for tag in class_tags:
        for wet in (False, True):
            try:
                key = online.make_key(tag, short_track, wet)
                if not key:
                    continue
                for r in online.top(key, 200):
                    pn = (r.get("player") or "").strip().lower()
                    ms = r.get("lap_ms")
                    if not pn or not ms:
                        continue
                    known.add(pn)
                    k = (pn, tag)
                    if k not in times or int(ms) < times[k]:
                        times[k] = int(ms)
            except Exception:
                pass
    _COMM["times"] = times
    _COMM["known"] = known
    _COMM["loading"] = False


def _community_tick(track, field):
    """Assicura il fetch (1 volta per pista+classi presenti) e ritorna
    (times, known) correnti. Non blocca il loop. Vuoto finche' il bg non
    finisce il primo fetch."""
    try:
        from core.classes import class_tag
        from telemetry.db import _short_track
    except Exception:
        return {}, set()
    tags = set()
    for c in (field or {}).values():
        t = class_tag(c.get("cls") or "")
        if t:
            tags.add(t)
    short = _short_track(track or "")
    sig = (short, frozenset(tags))
    if short and tags and sig != _COMM["sig"] and not _COMM["loading"]:
        _COMM["sig"] = sig
        _COMM["loading"] = True
        threading.Thread(target=_community_fetch, args=(short, tags),
                         name="comm-spotter", daemon=True).start()
    return _COMM["times"], _COMM["known"]


# ── DANNI wearables (aero + sospensione) dal REST RepairAndRefuel: il muretto
#    NON li aveva (raw['aero'] non era mai settato). Valori = FRAZIONE DI DANNO
#    (0 = integro). Fetch in un thread, max 1/s, non blocca il loop.
_WEAR = {"loading": False, "ts": 0.0, "aero": None, "susp": None}


def _wearables_tick():
    now = time.monotonic()
    if _WEAR["loading"] or now - _WEAR["ts"] < 1.0:
        return
    _WEAR["loading"] = True
    _WEAR["ts"] = now

    def _work():
        try:
            import urllib.request as _ur
            import json as _js
            req = _ur.Request(
                "http://localhost:6397/rest/garage/UIScreen/RepairAndRefuel",
                headers={"Accept": "application/json"})
            data = _js.loads(_ur.urlopen(req, timeout=1.0).read())
            w = (data.get("wearables") or {}) if isinstance(data, dict) else {}
            body = w.get("body") or {}
            if isinstance(body, dict) and "aero" in body:
                _WEAR["aero"] = float(body["aero"])
            su = w.get("suspension") or []
            if isinstance(su, list) and len(su) >= 4:
                _WEAR["susp"] = [float(x) for x in su[:4]]
        except Exception:
            pass
        finally:
            _WEAR["loading"] = False

    threading.Thread(target=_work, name="wearables", daemon=True).start()


def _auto_fuel_tick(feed, live, cfg, brain, laps_done):
    """AUTO PIT (opt-in, flag `auto_pit`): scrive nel pit menu la VIRTUAL
    ENERGY *minima* che copre lo STINT DOPO LA PROSSIMA SOSTA (+2), dalla
    tabella %->giri DEL GIOCO. Ciclo 5s, solo in gara (>2 min). Espone
    `live['auto_fuel_pct']` per l'annuncio dell'ingegnere.
      - confronto col currentSetting ATTUALE (LMU azzera dopo la sosta)
      - POST /loadPitMenu solo se il valore nel gioco e' diverso."""
    if not cfg.get("auto_pit", False):
        _AF["pct"] = None                       # opzione spenta: annuncio si ri-arma
        if live is not None:
            live["auto_fuel_pct"] = None
        return
    if live is None:
        return
    # porta SEMPRE l'ultimo target nel live (anche nei tick tra un calcolo e
    # l'altro): senza questo l'annuncio vedrebbe None e ri-annuncerebbe ogni 5s
    live["auto_fuel_pct"] = _AF.get("pct")
    now = time.monotonic()
    if now - _AF["ts"] < 5.0:
        return
    _AF["ts"] = now
    menu_raw = feed.pit_menu_raw()
    if not menu_raw:
        return
    changed = False
    # ── AUTO WET (INDIPENDENTE dal fuel): se piove e sei su slick, monta le WET
    # nel pit menu da solo. Prima era gated dietro il calcolo benzina -> non
    # scattava mai (fine gara / need assente). Ora gira sempre.
    try:
        wet_cond = (float(live.get("wetness") or 0.0) > 0.25
                    or float(live.get("raining") or 0.0) >= 0.4)
        comp = live.get("compound4") or []
        on_slick = bool(comp) and not any("W" in str(c).upper() for c in comp)
        if wet_cond and on_slick and _set_wet_tyres(menu_raw):
            changed = True
    except Exception:
        pass
    # ── FUEL: VE minima che copre i giri rimanenti (+2). Solo se il dato c'e'
    # e non a fine gara. La sosta e' opzionale (gomme) -> NON dividere per stint.
    need = live.get("laps_needed")
    if need is not None and float(live.get("race_remaining") or 0.0) >= 120.0:
        best = auto_fuel_target(menu_raw, need)
        if best is not None:
            idx, pct = best
            _AF["pct"] = pct                    # cache: usata nei tick intermedi
            live["auto_fuel_pct"] = pct         # -> l'ingegnere annuncia il target
            item = next((it for it in menu_raw
                         if str((it or {}).get("name") or "")
                         .startswith("VIRTUAL ENERGY")), None)
            if item is not None:
                try:
                    cur_ix = int(item.get("currentSetting") or 0)
                except (TypeError, ValueError):
                    cur_ix = 0
                if idx != cur_ix:
                    item["currentSetting"] = idx
                    changed = True
    if not changed:
        return
    try:
        import json as _js
        import urllib.request as _ur
        req = _ur.Request(
            "http://localhost:6397/rest/garage/PitMenu/loadPitMenu",
            data=_js.dumps(menu_raw).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        _ur.urlopen(req, timeout=1.5)
    except Exception:
        pass


_TYRE_PFX = ("TIRES", "FL TIRE", "FR TIRE", "RL TIRE", "RR TIRE")


def _set_wet_tyres(menu_raw):
    """Imposta le WET nel pit menu (master TIRES + le 4 ruote). Riconosce i nomi
    VERI di LMU come la dash, ANCHE in italiano ('Bagnata') — prima cercava solo
    'WET'/'RAIN' e in gioco italiano non le trovava mai. Preferisce la wet NUOVA.
    True se ha cambiato qualcosa."""
    changed = False
    for it in menu_raw or []:
        nm = str((it or {}).get("name") or "").upper()
        if not nm.startswith(_TYRE_PFX):
            continue
        opts = it.get("settings") or []
        wet_new = wet_any = None
        for ix, op in enumerate(opts):
            t = str((op or {}).get("text") or "").upper()
            if "BAGNAT" in t or "WET" in t or "RAIN" in t or "PLUIE" in t \
                    or "LLUVIA" in t:
                if wet_any is None:
                    wet_any = ix
                if wet_new is None and not ("USAT" in t or "USED" in t):
                    wet_new = ix
        pick = wet_new if wet_new is not None else wet_any
        if pick is not None and int(it.get("currentSetting") or 0) != pick:
            it["currentSetting"] = pick
            changed = True
    return changed


def _speak(vox, msgs, lang, seen):
    """Manda i messaggi alla voce col voce-per-ruolo. Salta vuoti e ripetizioni
    immediate identiche (l'anti-ripetizione vera e' nel cervello)."""
    for m in msgs or []:
        if not isinstance(m, dict):
            continue
        code = m.get("code")
        text = (m.get("text") or "").strip()
        if not text:
            continue
        if seen.get("last") == (code, text):
            continue
        seen["last"] = (code, text)
        role = role_for(code)
        print("[%s] %s" % (ROLE_LABEL.get(role, role), text))
        vox.speak(text, voice=voice_for(code, lang), beep=bool(m.get("beep")))


def _collect(brain, raw, ld, pace):
    """Chiama TUTTI i moduli-voce del cervello, passa ogni output dal
    sanity_filter (warm-up, leggi di stato, budget) e RITORNA la lista dei
    messaggi validi. NON parla: la scelta di cosa/quando dire è del
    RadioManager. Ogni modulo è difensivo (torna [] se manca il dato)."""
    mods = (
        # 🟠 RACE ENGINEER — sicurezza / auto
        (brain.flags_call, (raw,)),
        (brain.damage_call, (raw,)),
        (brain.wheel_bend_call, (raw,)),          # ruota piegata + causa ritiro (dal trace)
        (brain.terminal_damage, (raw,)),          # combo contatto+danno+motore morto -> ritiro
        (brain.aero_call, (raw,)),        # UNICO modulo danni: contatto + danno
        (brain.engine_check, (raw,)),
        (brain.battery_check, (raw, ld)),
        (brain.wet_tyre, (raw,)),
        (brain.pit_ack, (raw, ld)),
        (brain.pit_ready, (raw,)),                # "pronti per il pit stop" alla chiamata
        (brain.pit_light, (raw,)),                # semaforo pit chiusa/aperta (prova/quali)
        (brain.tyre_stock, (raw,)),               # inventario gomme (treni nuovi/usati)
        (brain.quali_pole, (raw, ld)),            # quali: gap dalla pola di classe
        (brain.overtake_call, (raw, ld)),         # complimenti sorpasso (gara)
        (brain.attack_defend_call, (raw, ld)),    # a tiro: attacca / difenditi
        (brain.slide_call, (raw, ld)),            # stai scivolando (sostenuto)
        (brain.setup_coach, (raw, ld)),           # consigli assetto (SOLO prova)
        (brain.kerb_call, (raw, ld)),             # cordoli violenti per zona
        (brain.outlap_tech_call, (raw, ld)),      # out-lap tecnico per classe (prova)
        (brain.stopped_check_call, (raw, ld)),    # fermo in pista + spia motore
        (brain.corner_coach_call, (raw, ld)),     # coach staccate/trazione per curva (prova)
        (brain.stint_findings_call, (raw, ld)),   # ingegneria stint: findings in garage
        # (brain.welcome_call TOLTO: il benvenuto aveva rotto, 23/07)
        (brain.stint_debrief, (raw, ld)),         # debrief a voce a fine stint (garage)
        # 🔵 STRATEGY
        (brain.race_briefing, (raw,)),           # briefing meteo al rolling start
        (brain.green_call, (raw,)),              # VIA / ripartenza: verde in gara
        (brain.race_plan, (raw,)),
        (brain.box_call, (raw, ld)),
        (brain.strategy_check, (raw, pace, ld)),
        (brain.weather_check, (raw, ld)),
        (brain.strat_extra_stop, (raw, ld)),
        (brain.fuel_save_option, (raw, ld)),      # margine per una sosta in meno
        (brain.manage_briefing, (raw,)),          # gestisci / spingi nel briefing
        (brain.test_mode_call, (raw, ld)),        # modalita' TEST dal dash (long run/sim/hotlap)
        (brain.pit_exit_traffic, (raw,)),         # traffico al rientro box (v2)
        (brain.garage_briefing, (raw,)),          # motore acceso: grip/temp/gomme + no-slick-in-pioggia
        (brain.pit_lane_release, (raw,)),         # safe release: uscita corsia box
        (brain.status_update, (raw, ld)),
        (brain.autofuel_call, (raw, ld)),
        (brain.position_strategy, (raw, ld)),
        (brain.pos_call, (raw,)),
        (brain.run_abort_call, (raw,)),           # prova/quali: giro buttato -> raffredda
        (brain.countdown, (raw, ld)),
        # 🟢 PERFORMANCE / spotter
        (brain.lap_time_call, (raw,)),
        (brain.lap_feedback, (raw, ld)),
        (brain.sector_delta, (raw, ld)),          # dove perdi nei settori (v2)
        (brain.corner_loss, (raw, ld)),           # curve dove perdi tempo
        (brain.tyre_life, (raw, ld)),
        (brain.grip_call, (raw, ld)),
        (brain.temp_call, (raw, ld)),
        (brain.gap_call, (raw, ld)),
        (brain.traffic_ahead_call, (raw,)),
        (brain.fast_class_call, (raw,)),          # pre-blu classe veloce (v2)
        (brain.opp_penalty, (raw,)),              # rivale penalizzato
        (brain.opp_pace_drop, (raw,)),            # rivale che perde passo
        (brain.community_spotter, (raw,)),        # pilota community in pista -> tempo rif.
        (brain.lock_pattern_call, (raw, ld)),
        (brain.pace_notes_call, (raw, ld)),
        (brain.tlimits_call, (raw, ld)),
        (brain.limits_review_call, (raw,)),       # taglio sotto esame -> restituisci
        (brain.rain_live, (raw, ld)),
        (brain.rain_pace_loss, (raw, ld)),        # crollo passo su slick bagnato -> wet
        (brain.wet_patches, (raw,)),
        (brain.wet_sector_map, (raw, ld)),        # settore piu' bagnato (v2)
    )
    # OGNI output passa dal MURO DI SANITÀ (come la v2): warm-up 5s, leggi di
    # stato (muta in corsia / pit chiamato), anti-ripetizione 25s, budget info.
    out = []
    for fn, args in mods:
        try:
            ms = brain.sanity_filter(fn(*args), raw)
            if ms:
                out.extend(m for m in ms if m)
        except Exception:
            pass
    return out


def _lang():
    return (engineer_cfg.load().get("lang") or "it")


# ─────────────────────────────────────────────────────────────────────────
#  LOOP LIVE
# ─────────────────────────────────────────────────────────────────────────
def run():
    lang = _lang()
    reader = TelemetryReader()
    feed = StrategyFeed()
    feed.start()
    mem = SharedMemory.instance()
    vox = Voice(lang=lang)
    _cfg = engineer_cfg.load()
    _apply_cfg(vox, _cfg)                     # volume/beep/ritardo dalle Opzioni
    brain = Engineer(lang=lang)
    brain.new_session()
    radio = RadioManager()
    print("[muretto] loop live avviato (lang=%s). In attesa di una sessione LMU..."
          % lang)
    _last_class = None
    _cfg_ts = 0.0
    _off = False
    _radio_off = False
    # rilevatori 5Hz nel PROCESSO muretto (il recorder e' nell'altro processo
    # e i suoi lock_events non arrivano qui): bloccaggi + cordoli violenti
    _lock_ev = []; _kerb_ev = []
    _lock_last = {}; _kerb_last = 0.0; _prev_sdf = []
    _tl_prev_steps = 0
    _brake_ev = []; _brk_prev = 0.0    # inizio staccata (fronte di salita)
    _grr_prev = 1e12                   # sessione viva in garage (ET che scorre)
    try:
        while True:
            _now = time.monotonic()
            if _now - _cfg_ts > 2.0:         # opzioni live (volume/beep/ritardo/auto_pit)
                _cfg = engineer_cfg.load()
                _apply_cfg(vox, _cfg)
                _cfg_ts = _now
            d = reader.read()
            if not d:
                time.sleep(0.5)              # LMU chiuso / shared memory vuota
                continue
            # SOLO in pista viva: nei menu / pausa / replay / fuori sessione la
            # shared memory resta piena di dati STANTII -> il muretto DEVE tacere.
            # ECCEZIONE: in GARAGE a sessione VIVA (il tempo scorre, es. monitor)
            # il muretto parla — briefing/debrief da box come un team vero.
            _garage_live = False
            try:
                _rr = float(d.get("race_remaining") or 0.0)
                if bool(d.get("garage")) and _rr > 0.0 \
                        and _rr < _grr_prev - 0.05:
                    _garage_live = True
                _grr_prev = _rr
            except Exception:
                pass
            if not mem.is_on_track() and not _garage_live:
                if not _off:                 # appena entrati in pausa/menu:
                    _off = True
                    try:
                        vox.interrupt()      # taglia la frase in corso
                    except Exception:
                        pass
                    try:
                        radio.reset()        # svuota la coda (niente "1 minuto" in pausa)
                    except Exception:
                        pass
                time.sleep(0.25)
                continue
            _off = False
            # RADIO OFF (flag engineer_on, stesso della riga Radio nelle Options,
            # commutabile anche dal MOD3 del dash): muretto muto come in pausa
            if not _cfg.get("engineer_on", True):
                if not _radio_off:
                    _radio_off = True
                    try:
                        vox.interrupt()
                    except Exception:
                        pass
                    try:
                        radio.reset()
                    except Exception:
                        pass
                time.sleep(0.25)
                continue
            _radio_off = False
            drv = d.get("driver") or ""
            ld = int(d.get("laps_completed") or 0)
            feed.set_context(drv, ld)
            cls = d.get("car_class")
            if cls and cls != _last_class:
                _last_class = cls
                brain.set_class(cls)
            est = float(d.get("est_lap") or d.get("best_lap") or 0.0)
            live = feed.lmu_live(d, est)
            _auto_fuel_tick(feed, live, _cfg, brain, ld)   # AUTO PIT: VE stint + annuncia
            # raw per il cervello: fisica + blocco strategia
            raw = dict(d)
            # MODALITA' TEST dal dash (engineer_cfg, riletta ogni 2s)
            raw["test_mode"] = _cfg.get("test_mode") or None
            raw["test_extra"] = _cfg.get("test_extra_laps")
            raw["test_race_min"] = _cfg.get("test_race_min")
            raw["eco_free"] = _cfg.get("eco_free")   # risparmio LIBERO (anche gara)
            raw["ts"] = time.monotonic()
            raw["on_track"] = True
            raw["lap_time"] = d.get("last_lap")       # per sector_delta / feedback
            raw["lmu_live"] = live
            # ── EVENTI ad alta frequenza: BLOCCAGGI (ruota quasi ferma in
            # frenata) e CORDOLI VIOLENTI (ruota sul cordolo + colpo secco di
            # sospensione). Alimentano lock_pattern_call e kerb_call.
            try:
                _spd = float(d.get("speed") or 0.0)
                _brk = float(d.get("brake") or 0.0)
                _ldm = float(d.get("lapdist") or -1.0)
                _rot = d.get("wheel_rot") or []
                _sdf = d.get("susp_defl") or []
                _srf = d.get("surface_type") or []
                if _spd > 8.0 and _ldm >= 0:
                    _spd_ms = _spd / 3.6      # 'speed' e' in KM/H nel reader
                    if len(_rot) >= 4 and _spd > 40.0:
                        for _wi in range(4):
                            try:
                                _ws = abs(float(_rot[_wi] or 0.0)) * 0.33
                            except (TypeError, ValueError):
                                continue
                            _ratio = _ws / _spd_ms
                            # bloccaggio = TRANSIZIONE: la ruota GIRAVA
                            # (ratio>0.7 da <0.8s) e ora e' quasi ferma in
                            # frenata DECISA. Se il campo rot e' morto/zero
                            # fisso non scatta mai (niente falsi in GT3).
                            if _ratio > 0.7:
                                _lock_last[("ok", _wi)] = _now
                            elif _brk > 0.4 and _spd > 40.0 \
                                    and _ratio < 0.3 \
                                    and _now - _lock_last.get(("ok", _wi),
                                                              0.0) < 0.8 \
                                    and _now - _lock_last.get(_wi, 0.0) > 1.0:
                                _lock_last[_wi] = _now
                                _lock_ev.append((_ldm, _wi))
                    if len(_sdf) >= 4 and len(_prev_sdf) >= 4:
                        for _wi in range(4):
                            try:
                                _dd = abs(float(_sdf[_wi] or 0.0)
                                          - float(_prev_sdf[_wi] or 0.0))
                            except (TypeError, ValueError):
                                continue
                            try:
                                _onk = int(_srf[_wi]) == 5   # 5 = cordolo
                            except (TypeError, ValueError, IndexError):
                                _onk = False
                            if _dd > (18.0 if _onk else 32.0) \
                                    and _now - _kerb_last > 1.0:
                                _kerb_last = _now
                                _kerb_ev.append(_ldm)
                                break
                    _prev_sdf = list(_sdf)
                # INIZIO STACCATA (fronte di salita del freno): per il
                # coach frenate ("puoi staccare N metri dopo in curva X")
                if _spd > 60.0 and _ldm >= 0 \
                        and _brk > 0.35 and _brk_prev <= 0.35:
                    _brake_ev.append((_now, _ldm))
                _brk_prev = _brk
                del _lock_ev[:-40]
                del _kerb_ev[:-40]
                del _brake_ev[:-24]
                raw["lock_events"] = list(_lock_ev)
                raw["kerb_events"] = list(_kerb_ev)
                raw["brake_events"] = list(_brake_ev)
            except Exception:
                pass
            # TRACK LIMITS: conto e soglie VERI al cervello (prima tl_steps
            # non arrivava MAI -> gli avvisi "a rischio penalita'" erano
            # morti) + LOG di calibrazione su ogni variazione del conto.
            try:
                _tl = mem.player_track_limits() or {}
                raw["tl_steps"] = int(_tl.get("steps") or 0)
                raw["tl_pen"] = int(_tl.get("per_penalty") or 0)
                raw["tl_point"] = int(_tl.get("per_point") or 0)
                if raw["tl_steps"] != _tl_prev_steps:
                    try:
                        from core.race_control import track_limits_state
                        from core.paths import USER_DIR
                        _st_tl = track_limits_state()
                        with open(USER_DIR / "tl_calib.log", "a",
                                  encoding="utf-8") as _fh:
                            _fh.write("[%s] steps %s -> %s (perpoint=%s "
                                      "perpen=%s) | evento: warn=%s pts=%s "
                                      "placediff=%s\n" % (
                                          time.strftime("%H:%M:%S"),
                                          _tl_prev_steps, raw["tl_steps"],
                                          raw["tl_point"], raw["tl_pen"],
                                          _st_tl.get("warn_pts"),
                                          _st_tl.get("pts"),
                                          _st_tl.get("placediff")))
                    except Exception:
                        pass
                    _tl_prev_steps = raw["tl_steps"]
            except Exception:
                pass
            raw["forecast_rain"] = _forecast(d)       # meteo gara (briefing al via)
            if live:
                raw["lmu_per_lap"] = live.get("per_lap")
                raw["lmu_strat"] = {
                    "constraint": live.get("constraint"),
                    "fuel_max": live.get("fuel_max"),
                    "fuel_cur": live.get("fuel_l"),
                    "per_lap": live.get("per_lap"),
                    "pit_target": live.get("pit_target"),
                    "autonomy": live.get("autonomy_laps"),
                }
            # SCORING dalla shared memory -> attiva bandiere/gap/traffico/posizioni
            try:
                _fl = mem.flags()
                if _fl:
                    raw["flags"] = _fl
                    raw["checkered"] = _fl.get("checkered")
                    raw["penalties"] = _fl.get("num_penalties")
                _rv = mem.rivals()
                if _rv:
                    raw["rivals"] = _rv
                _nc = mem.nearest_car()
                if _nc:
                    raw["nearest_car"] = _nc
                # CHI ho toccato dal punto d'urto 3D (muro -> None)
                raw["contact_who"] = mem.contact_driver()
                raw["cars"] = mem.car_states()    # penalità / passo rivali
                # SPOTTER COMMUNITY: tutti i piloti (io incluso, per ora) +
                # mappa tempi community su questa pista (fetch bg, non blocca)
                raw["limits_review"] = mem.player_limits_review()   # taglio sotto esame
                raw["field"] = mem.field_drivers()
                _ctimes, _cknown = _community_tick(d.get("track"), raw["field"])
                raw["comm"] = {"times": _ctimes, "known": _cknown}
                # DANNI aero + sospensione (REST wearables): il muretto
                # ora li vede (prima raw['aero'] era sempre None)
                _wearables_tick()
                if _WEAR["aero"] is not None:
                    raw["aero"] = _WEAR["aero"]
                if _WEAR["susp"] is not None:
                    raw["susp"] = _WEAR["susp"]
                # SAFE RELEASE / briefing box: la mappa-traffico (tutte le auto
                # con lapdist+velocità) serve SOLO in corsia/box -> economico.
                if raw.get("in_pits") or raw.get("in_pitlane") or raw.get("garage"):
                    raw["traffic_map"] = mem.pit_scan()
                    raw["tyre_inventory"] = _tyre_inv()
            except Exception:
                pass
            # tick strappato (dato incoerente) -> salta
            try:
                if brain.glitch(raw):
                    time.sleep(0.2)
                    continue
            except Exception:
                pass
            # fotografia stato PRIMA di tutto (state-aware), poi tutti i moduli
            try:
                brain.update_situation(raw)
            except Exception:
                pass
            radio.push(_collect(brain, raw, ld, est or None))
            radio.tick(vox, lang)
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        feed.stop()
        reader.stop()


# ─────────────────────────────────────────────────────────────────────────
#  DEMO — fa parlare la strategia senza pista (valida tutta la catena)
# ─────────────────────────────────────────────────────────────────────────
def demo():
    lang = _lang()
    vox = Voice(lang=lang)
    brain = Engineer(lang=lang)
    brain.new_session()
    brain.set_class("LMGT3")
    seen = {}
    # GT3: serbatoio 119, carico 98, 1.74 L/giro, giro 54.8s, gara ~96 giri
    raw0 = {"session_type": 10, "track": "TEST SIM", "driver": "Jona",
            "max_laps": 2147483647, "est_lap": 54.8, "best_lap": 54.8,
            "race_total": 5260.0, "race_remaining": 5260.0,
            "lmu_per_lap": 1.74,
            "lmu_strat": {"constraint": "FUEL", "fuel_max": 119.0,
                          "fuel_cur": 98.0, "per_lap": 1.74,
                          "autonomy": 56, "fulltank": 68},
            "forecast_rain": [0, 0, 10, 90, 100], "raining": 0.0}
    print("[muretto] DEMO — briefing di gara:")
    try:
        brain.update_situation(raw0)
    except Exception:
        pass
    _speak(vox, brain.race_plan(raw0), lang, seen)
    time.sleep(7)
    fuel = 98.0
    for lap in range(1, 13):
        per = 1.95 if lap <= 4 else (1.74 if lap <= 8 else 1.55)
        fuel -= per
        raw = dict(raw0, laps_completed=lap, lmu_per_lap=per)
        raw["race_remaining"] = max(0.0, 5260.0 - lap * 54.8)
        raw["lmu_strat"] = dict(raw0["lmu_strat"], fuel_cur=fuel)
        _speak(vox, brain.strategy_check(raw, 54.8, lap), lang, seen)
        time.sleep(3)
    print("[muretto] DEMO finita")


def _parent_watchdog():
    """Se muore l'app padre (LMU_PARENT_PID), il muretto si chiude DA SOLO —
    niente processi orfani che continuano a parlare / si sovrappongono."""
    import os
    ppid = os.environ.get("LMU_PARENT_PID")
    if not ppid:
        return
    import threading

    def _watch(pid):
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            return
        if os.name == "nt":
            try:
                import ctypes
                h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
                if h:
                    ctypes.windll.kernel32.WaitForSingleObject(h, -1)
                    os._exit(0)
            except Exception:
                pass
        import time as _tw
        while True:
            _tw.sleep(2.0)
            try:
                os.kill(pid, 0)
            except OSError:
                os._exit(0)

    threading.Thread(target=_watch, args=(ppid,), daemon=True).start()


def main():
    _parent_watchdog()               # muore con l'app padre
    if "--demo" in sys.argv:
        demo()
    else:
        run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
