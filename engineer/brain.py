# -*- coding: utf-8 -*-
"""ENGINEER v3 — il cervello del muretto, riscritto da zero (2026-07-19).

Architettura a RAGNATELA, non ad albero:
  - UN centro: la LEGGE DI STATO nel sanity_filter. Ogni frase di ogni
    modulo passa dallo stato REALE (player in pista / corsia / box /
    pit chiamato, gara / prova) PRIMA di uscire. Nessun modulo puo'
    parlare "da solo".
  - DATI CERTI prima delle stime: regole sessione (/rest/sessions),
    consumi misurati (usage), passo rivali misurato (standings/history),
    pit menu strutturato, forecast ancorato all'inizio gara.
  - Il muretto informa, il pilota DECIDE. Gli unici ORDINI sono le
    chiamate di sicurezza: WET su pista troppo bagnata, ruota persa,
    foratura, danno grave.
  - Ogni modulo e' PICCOLO, one-shot con isteresi, e non puo' rompere
    gli altri: l'orchestratore (engineer_tab) isola gia' le chiamate.

Interfaccia identica alla v2: Engineer(), msg(), sanity_filter(),
race_plan(), advisor *_call(...) -> lista di messaggi. I moduli non
ancora reimplementati rispondono [] (silenzio onesto, mai crash).
"""
import json as _json
import random as _rnd
import re as _re
import time as _time
from pathlib import Path

try:
    from core.classes import class_tag
except Exception:
    def class_tag(s):
        s = str(s or "").upper()
        for t in ("HY", "LMH", "LMDH", "P2", "P3", "GT3", "GTE"):
            if t in s:
                return {"LMH": "HY", "LMDH": "HY"}.get(t, t)
        return ""

_ROOT = Path(__file__).resolve().parent.parent
_MSG_FILE = _ROOT / "settings" / "engineer_msgs.json"
_re_ph = _re.compile(r"\{[a-z_]+\}")
_re_sp = _re.compile(r"  +")


def _load_msgs():
    try:
        d = _json.loads(_MSG_FILE.read_text(encoding="utf-8"))
        return d.get("messages", {}), d.get("_levels", {})
    except Exception:
        return {}, {}


def session_kind(m_session):
    """mSession -> 'practice' | 'qualy' | 'race'. None = 'race' prudente
    ma il chiamante deve gia' guardare on_track."""
    try:
        s = int(m_session)
    except (TypeError, ValueError):
        return "race"
    if 5 <= s <= 8:
        return "qualy"
    if s >= 10:
        return "race"
    return "practice"


def _fmt_lap_round(s):
    """Tempo giro PARLATO con TUTTI i decimali (millesimi): '1 e 52 e 323',
    sotto il minuto '54 e 823'."""
    try:
        s = float(s)
    except (TypeError, ValueError):
        return str(s)
    m = int(s // 60)
    sec_f = s - m * 60
    sec = int(sec_f)
    ms = int(round((sec_f - sec) * 1000))
    if ms >= 1000:
        sec += 1
        ms = 0
    if m == 0:
        return "%d e %03d" % (sec, ms)
    return "%d e %02d e %03d" % (m, sec, ms)


# nome classe pronunciabile (dal tag) — per traffico/blu (portato da v2)
_CLASS_READABLE = {"HY": "Hypercar", "LMH": "Hypercar", "LMDH": "Hypercar",
                   "GT3": "GT3", "LMGT3": "GT3", "GTE": "GTE",
                   "LMP2": "LMP2", "LMP3": "LMP3"}


def _class_readable(tag):
    return _CLASS_READABLE.get((tag or "").upper(), tag)


class Engineer:
    """Il cervello. Stato in self._st (dict namespaced): niente foresta di
    attributi, reset di sessione = un clear."""

    _LANGS = ("it", "en", "es", "fr")
    _PACE_MARGIN = 1.025

    # ── LEGGE CENTRALE DI STATO (il centro della ragnatela) ──────────
    # In corsia/box/garage e a pit CHIAMATO: WHITELIST — passano SOLO i
    # messaggi pit/box, la sicurezza (bandiere, danni, ritiro) e il
    # debrief. Tutto il resto (gap, meteo, strategia, coaching, tempi)
    # in quel momento e' rumore. Richiesta utente 22/07.
    _LAW_PIT_KEEP = ("pit_", "box_", "garage_", "autofuel", "yellow",
                     "local_yellow", "blue_", "retire_", "driver_check",
                     "contact_", "aero_", "susp_", "damage", "tyre_flat",
                     "wheel_", "fuel_short", "engine_", "brakes_over",
                     "tyres_over", "limits_", "tlimits_", "debrief_",
                     "race_start", "green_restart", "session_end",
                     "longrun_", "racesim_", "hotlap_", "test_", "eco_")
    # QUALIFICA (sei da solo): lo spotter NON da' bandiere ne' traffico.
    # Restano tempi/settori/passo/gomme/grip: servono in quali.
    _LAW_QUALI_MUTE = ("blue_", "yellow", "local_yellow", "traffic_",
                       "fast_class", "gap_", "opp_", "pit_exit",
                       "pit_release")
    # PROVA (privata): niente riferimenti agli ALTRI (passo/penalita' rivali,
    # gap, traffico). Restano i TUOI tempi/settori/gomme e il miglior tempo.
    # Bandiere/safe-release NON mutate (se la prova fosse condivisa = sicurezza;
    # se e' privata non scattano comunque).
    _LAW_PRACTICE_MUTE = ("opp_", "fast_class", "gap_", "traffic_")
    # FOCUS QUALI/GARA (rich. 23/07: "in q e race il muretto osserva e poi
    # dice le stesse cose ma senza quelle cose dei test"): le ROUTINE da
    # prove — modalita' test, coach assetto, briefing garage — non escono.
    # Restano tempi, gomme, strategia, sicurezza (le "stesse cose").
    # eco_/LICO NON e' qui: il risparmio serve anche in gara.
    _LAW_FOCUS_MUTE = ("test_", "longrun_", "racesim_", "hotlap_",
                       "setup_", "garage_brief", "garage_prep")
    # INCIDENTE (finestra crisi dopo botta forte) e GIALLA ATTIVA: passano
    # SOLO questi prefissi (sicurezza, danni, stato pilota, bandiere).
    _LAW_CRISIS_KEEP = ("contact_", "aero_", "susp_", "box_", "retire_",
                        "driver_check", "tyre_flat", "damage", "yellow",
                        "local_yellow", "blue_", "brakes_over", "tyres_over",
                        "engine_", "wheel_", "pit_", "fuel_short",
                        "green_restart", "race_start", "limits_", "tlimits_",
                        "stopped_")

    def __init__(self, lang="it"):
        self.lang = lang if lang in self._LANGS else "it"
        self._msgs, self._levels = _load_msgs()
        self._cat = ""
        self.baseline = None
        self._st = {}                 # stato per-modulo (one-shot, isteresi)
        self._plan = None             # {constraint, race_laps, stops(n), ...}
        self._race_model = None       # {segments, stops[], stints, ...}
        self._planned = False
        self._plan_sig = None
        self._plan_laps = None        # giri visti l'ultima volta (restart)
        self._plan_rewind = 0         # conferme di giri tornati indietro
        self._ctx = {}
        self._tyre_unknown = True
        self._sane_events = []

    # ── compatibilita': ogni advisor non implementato = silenzio ─────
    def __getattr__(self, name):
        if name.endswith("_call") or name in (
                "memory_review", "update_ctx", "wet_sector_map",
                "diary_lines", "sector_panel_data", "update_situation",
                # coperti altrove: consiglio gomme in wet_tyre/rain_live,
                # strat_plan fuso in race_plan
                "tyre_advice", "strat_plan"):
            return lambda *a, **k: []
        raise AttributeError(name)

    # ── infrastruttura lingua/messaggi ───────────────────────────────
    def set_lang(self, lang):
        _l = str(lang).lower()[:2]
        self.lang = _l if _l in self._LANGS else "it"

    def _L(self, it, en, es=None, fr=None):
        return {"en": en, "es": es or en, "fr": fr or en}.get(self.lang, it)

    def _pick_variant(self, code, variants):
        """Scelta CASUALE della frase, evitando di ripetere l'ultima usata per
        QUESTO annuncio (cosi' non esce due volte di fila la stessa)."""
        if not variants:
            return ""
        if len(variants) == 1:
            return variants[0]
        lv = getattr(self, "_last_variant", None)
        if lv is None:
            lv = self._last_variant = {}
        last = lv.get(code)
        pool = [v for v in variants if v != last] or variants
        ch = _rnd.choice(pool)
        lv[code] = ch
        return ch

    def msg(self, code, **kw):
        m = self._msgs.get(code)
        if not m:
            return None
        if self.lang != "it":
            variants = m.get("variants_%s" % self.lang)
            text = self._pick_variant(code, variants) if variants else \
                (m.get(self.lang) or m.get("en") or m.get("it") or code)
        else:
            variants = m.get("variants_it")
            text = self._pick_variant(code, variants) if variants else \
                (m.get("it") or m.get("en") or code)
        for k, v in kw.items():
            text = text.replace("{%s}" % k, str(v))
        if "{" in text:
            text = _re_ph.sub("", text)
            text = text.replace(" ,", ",").replace(" .", ".")
            text = _re_sp.sub(" ", text).strip(" ,.;:-")
            text = text[0].upper() + text[1:] if text else text
        lvl = m.get("level", "info")
        return {"code": code, "text": text, "level": lvl,
                "color": self._levels.get(lvl, "#1c9fe0"),
                "beep": bool(m.get("beep"))}

    # ── lifecycle ────────────────────────────────────────────────────
    def set_class(self, car_class):
        self._cat = class_tag(car_class) or self._cat

    def set_baseline(self, bl):
        self.baseline = bl

    def reset(self):
        self.new_session()

    def new_session(self):
        """Reset COMPLETO: nulla della sessione vecchia sopravvive."""
        self._st.clear()
        self._plan = None
        self._race_model = None
        self._planned = False
        self._plan_sig = None
        self._ctx = {}
        self._sane_events = []
        self._sec_best = None            # riferimento settori: riparte pulito

    # ── filtro letture strappate ─────────────────────────────────────
    def glitch(self, raw):
        """Tick a meta' scrittura (niente version counter): usura che
        RISALE o carico che salta su senza pit = scarto, max 2 di fila."""
        try:
            if raw.get("in_pits") or raw.get("garage"):
                self._st.pop("gl_wear", None)
                self._st.pop("gl_load", None)
                self._st["gl_n"] = 0
                return False
            tw = raw.get("tyre_wear")
            wear = min(float(x) for x in tw if x is not None) \
                if isinstance(tw, (list, tuple)) and tw else None
            load = float(raw.get("ve") or raw.get("fuel") or 0.0)
            pw = self._st.get("gl_wear")
            pl = self._st.get("gl_load")
            bad = ((pw is not None and wear is not None and wear > pw + 2.0)
                   or (pl is not None and load > pl + 5.0))
            if bad and self._st.get("gl_n", 0) < 2:
                self._st["gl_n"] = self._st.get("gl_n", 0) + 1
                return True
            self._st["gl_n"] = 0
            if wear is not None:
                self._st["gl_wear"] = wear
            if load:
                self._st["gl_load"] = load
        except Exception:
            pass
        return False

    # ── letture di base ──────────────────────────────────────────────
    @staticmethod
    def _wet_mounted(raw):
        c4 = raw.get("tyre_compound4") or []
        if isinstance(c4, (list, tuple)) and c4:
            return any(str(c or "").upper().startswith("W") for c in c4)
        cf = str(raw.get("compound_f") or "").lower()
        return "wet" in cf or "rain" in cf

    def _cur_load(self, raw, constraint):
        """Carico attuale nell'unita' del vincolo (VE% o litri).
        FONTE PRIMA: raw['lmu_live'] (blocco strategia dedicato, dati
        diretti di LMU); ripiego sulle chiavi sciolte del raw."""
        live = (raw or {}).get("lmu_live") or {}
        try:
            if str(constraint).upper() == "ENERGY":
                v = live.get("ve_pct")
                if v is None:
                    v = raw.get("ve")
                if v is None:
                    v = raw.get("ve_pct")
                v = float(v or 0.0)
                return v if v > 0 else None
            v = live.get("fuel_l")
            if v is None:
                v = raw.get("fuel")
            v = float(v or 0.0)
            return v if v > 0 else None
        except (TypeError, ValueError):
            return None

    def _lap_estimate(self, raw):
        """Tempo giro per i conti: est del gioco -> best -> last -> classe."""
        for k in ("est_lap", "best_lap", "last_lap"):
            try:
                v = float(raw.get(k) or 0.0)
            except (TypeError, ValueError):
                v = 0.0
            if 20.0 < v < 1200.0:
                return v
        cat = (self._cat or "").upper()
        return 95.0 if cat in ("HY", "P2") else 110.0

    def _race_laps(self, raw):
        """Giri gara totali. A TEMPO: durata/passo (mMaxLaps li' e'
        autonomia, non distanza). A GIRI: prima il dato CERTO dalle
        regole sessione, poi mMaxLaps."""
        total = float(raw.get("race_total") or 0.0)
        rem = float(raw.get("race_remaining") or 0.0)
        best = self._st.get("race_secs_best", 0.0)
        dur = max(total, rem, best)
        if dur > 0:
            self._st["race_secs_best"] = dur
            if dur < 360000:
                return int(dur / self._lap_estimate(raw)) + 1
            return None
        try:
            _set = int((raw.get("session_rules") or {})
                       .get("race_laps_set") or 0)
        except (TypeError, ValueError):
            _set = 0
        if 0 < _set <= 5000:
            return _set
        laps = int(raw.get("max_laps") or 0)
        return laps if 0 < laps <= 5000 else None

    def _pit_stop_seconds(self, raw):
        """Perdita sosta: stima del GIOCO (pitstop-estimate) + corsia.
        Fallback prudente 30s fermo + 20s corsia."""
        est = raw.get("pit_est")
        if not isinstance(est, dict):
            est = {}
        stat = 0.0
        for k in ("fuel", "ve", "tires", "driverSwap", "penalties"):
            try:
                stat += max(0.0, float(est.get(k) or 0.0))
            except (TypeError, ValueError):
                pass
        if stat <= 0:
            try:
                stat = max(0.0, float(est.get("total") or 0.0))
            except (TypeError, ValueError):
                stat = 0.0
        if stat <= 0:
            stat = 30.0
        return stat + 22.0

    def _pace_vs_ahead(self, riv):
        """Nota di passo MISURATO vs rivale davanti (storico giri REST)."""
        try:
            ap = float((riv or {}).get("ahead_pace") or 0.0)
            mp = float((riv or {}).get("my_pace") or 0.0)
            if ap <= 20.0 or mp <= 20.0:
                return ""
            d = ap - mp
            if abs(d) < 0.15:
                return self._L(", passo pari", ", equal pace",
                               ", ritmo igual", ", rythme egal")
            _v = ("%.1f" % abs(d)).replace(".", ",")
            if d > 0:
                return self._L(", sei piu' veloce di %s al giro" % _v,
                               ", you are %s a lap faster" % _v,
                               ", eres %s mas rapido por vuelta" % _v,
                               ", tu es %s plus rapide au tour" % _v)
            return self._L(", occhio: e' piu' veloce di %s al giro" % _v,
                           ", careful: he is %s a lap faster" % _v,
                           ", cuidado: es %s mas rapido por vuelta" % _v,
                           ", attention: il est %s plus rapide au tour" % _v)
        except Exception:
            return ""

    # ── PIANO GARA (delega al muretto puro) ──────────────────────────
    def race_plan(self, raw):
        raw = raw or {}
        if session_kind(raw.get("session_type")) != "race":
            return []
        sig = (raw.get("track"), raw.get("session_type"))
        try:
            ld = int(raw.get("laps_completed") or 0)
        except (TypeError, ValueError):
            ld = 0
        # GARA RIAVVIATA: i giri completati non arretrano MAI dentro la
        # stessa gara. Conferma su 2 letture (una lettura strappata non
        # deve azzerare il cervello).
        restart = False
        if self._plan_laps is not None and ld < self._plan_laps:
            self._plan_rewind += 1
            restart = self._plan_rewind >= 2
        else:
            self._plan_rewind = 0
            self._plan_laps = ld
        if sig != self._plan_sig or restart:
            # SESSIONE NUOVA (o RESTART) = cervello NUOVO: niente
            # contatori/flag ereditati dalla sessione prima (es.
            # "penalita'" al via dai track limits delle prove, piano
            # soste della gara riavviata) + warm-up di ascolto
            self.new_session()
            self._plan_sig = sig
            self._plan_laps = ld
        out = self._build_plan(raw, revise=self._planned)
        # BRIEFING PRE-VERDE GARANTITO: in griglia/formazione (fase 1-4),
        # se il piano completo non e' ancora calcolabile (serve il consumo),
        # di' ALMENO la durata gara + "stima di partenza": il briefing va
        # dato PRIMA del release, non al 2° giro (immersione).
        if not out and not self._planned and not self._st.get("prelim_said"):
            try:
                ph = int(raw.get("game_phase") or 0)
            except (TypeError, ValueError):
                ph = 0
            if ph in (1, 2, 3, 4):
                laps = self._race_laps(raw)
                if laps:
                    self._st["prelim_said"] = True
                    return [self.msg("briefing_laps", laps=int(laps)),
                            self.msg("plan_prelim")]
        return out

    def _build_plan(self, raw, revise=False):
        try:
            from core import muretto as _mur
        except ImportError:
            import muretto as _mur

        constraint = ((raw.get("lmu_strat") or {}).get("constraint")
                      or "FUEL").upper()
        per_lap = None
        try:
            per_lap = float(raw.get("lmu_per_lap") or 0.0) \
                or float((raw.get("lmu_strat") or {}).get("per_lap") or 0.0)
        except (TypeError, ValueError):
            per_lap = 0.0
        if not per_lap or per_lap <= 0.2:
            return []                       # niente consumo MISURATO: attendo
        tank = 100.0
        if constraint != "ENERGY":
            try:
                tank = float((raw.get("lmu_strat") or {}).get("fuel_max")
                             or raw.get("fuel_max") or 0.0)
            except (TypeError, ValueError):
                tank = 0.0
            if tank <= 0:
                return []
        load = self._cur_load(raw, constraint)
        laps_done = int(raw.get("laps_completed") or 0)
        laptime = self._lap_estimate(raw)
        race_secs = float(raw.get("race_remaining") or 0.0)
        race_laps_abs = 0
        if race_secs <= 1.0:
            rl = self._race_laps(raw)
            race_laps_abs = max(0, (rl or 0) - laps_done)
            if not race_laps_abs:
                return []

        # gomma: usura peggiore + degrado (appreso o dal pit-menu)
        wear_now = None
        tw = raw.get("tyre_wear")
        if isinstance(tw, (list, tuple)) and tw:
            try:
                wear_now = min(float(x) for x in tw if x is not None)
            except (TypeError, ValueError):
                wear_now = None
        # degrado: prima quello APPRESO dai TUOI giri (misura), poi la
        # stima del pit-menu del gioco
        deg = None
        learned = False
        try:
            from core.engineer_learn import load as _learn_load
            prof = _learn_load(raw.get("track") or "",
                               class_tag(raw.get("car_class") or "")) or {}
            cond = (prof.get("cond") or {}).get(
                "wet" if self._wet_mounted(raw) else "dry") or {}
            dv = [v for v in (cond.get("deg_front"), cond.get("deg_rear"))
                  if v]
            if dv:
                deg = max(float(x) for x in dv)
                learned = True
        except Exception:
            deg = None
        if not deg:
            try:
                for cw in ((raw.get("tyre_inventory") or {})
                           .get("compounds") or []):
                    if cw.get("wear_per_lap"):
                        deg = float(cw["wear_per_lap"])
                        break
            except (TypeError, ValueError):
                deg = None
        self._tyre_unknown = not learned

        wetm = self._wet_mounted(raw)
        # pista bagnata ADESSO: MEDIA (conservativa) — la sicurezza non
        # si giudica sulla scia
        try:
            twet = (float(raw.get("wetness") or 0.0) > 0.25
                    or float(raw.get("raining") or 0.0) >= 0.4)
        except (TypeError, ValueError):
            twet = None

        snap = {
            "constraint": constraint, "tank": tank, "load_now": load,
            "per_lap": per_lap, "base_lap": laptime * self._PACE_MARGIN,
            "race_seconds_left": race_secs,
            "race_laps_left": race_laps_abs if race_secs <= 1.0 else 0,
            "laps_done": laps_done,
            "pit_loss": self._pit_stop_seconds(raw),
            "forecast5": raw.get("forecast_rain"),
            "raining_now": raw.get("raining"),
            "wet_mounted": wetm, "track_wet_now": twet,
            "wear_now": wear_now, "deg_per_lap": deg,
            "wear_dead": 78.0 if wetm else 70.0,
        }
        self._deg = deg                       # per manage_briefing (gestisci/spingi)
        self._wear_dead = snap["wear_dead"]
        mp = _mur.plan(snap)
        if not mp.get("ok"):
            return []
        if mp["race_laps"] < 3 or mp["race_laps"] > 2000 \
                or mp["autonomy_full"] > 2000:
            return []
        self._planned = True

        stops_list = mp["stops"]
        # ── modello per strip/voce/live_strategy (contratto v2) ──
        _TY = {"WET": "W", "SLICK": "S"}
        mstops = [{"lap": s["lap"], "reason": s["reason"],
                   "tyre": _TY.get(s.get("tyre")),
                   "refuel_pct": s["refuel_pct"],
                   "arrive_pct": s["arrive_pct"]} for s in stops_list]
        strips = []
        for s in mstops:
            tg = min(100.0, s["refuel_pct"] + s["arrive_pct"])
            if constraint == "ENERGY":
                ftxt = "%d" % round(tg)
            else:
                ftxt = "%dL" % round(tg * tank / 100.0)
            strips.append({"lap": s["lap"], "tyre": s["tyre"],
                           "reason": s["reason"],
                           "refuel_pct": int(round(s["refuel_pct"])),
                           "arrive_pct": s["arrive_pct"],
                           "fuel_txt": ftxt})
        model = {
            "segments": mp["segments"], "stops": mstops,
            "stints": [{"da": st["da"], "a": st["a"],
                        "tyre": _TY.get(st["tyre"], st["tyre"]),
                        "drive": "PUSH", "note": ""}
                       for st in mp["stints"]],
            "strip_stops": strips, "stops_total": len(mstops),
            "slick_needed": sum(1 for s in mstops if s["tyre"] == "S"),
            "tyre_ok": True, "feasible": True,
            "race_laps": mp["race_laps"],
        }
        self._race_model = model
        # ctx per i display del tab (autonomia/vincolo, fonte unica)
        self._ctx = {"autonomy": round((load or 0.0) / per_lap, 1)
                     if load else None,
                     "constraint": constraint}
        self._plan = {"constraint": constraint,
                      "race_laps": mp["race_laps"],
                      "stint_laps": int(round(mp["autonomy_full"])),
                      "start_stint": int(round(mp["autonomy_now"])),
                      "mode": "normal", "stops": len(stops_list),
                      "target_pl": per_lap}

        # ── VOCE: annuncio SOLO su piano nuovo o soste cambiate stabili ──
        def _laps_of(ss):
            if not isinstance(ss, (list, tuple)):
                return None
            return tuple(s.get("lap") for s in ss)

        out = []
        ann = self._st.get("ann_stops")
        if revise:
            if _laps_of(ann) == _laps_of(mstops) and ann is not None:
                self._st.pop("cand_stops", None)
            else:
                cand = self._st.get("cand_stops")
                if _laps_of(cand) != _laps_of(mstops):
                    self._st["cand_stops"] = list(mstops)
                    self._st["cand_lap"] = laps_done
                elif laps_done - self._st.get("cand_lap", laps_done) >= 5:
                    self._st.pop("cand_stops", None)
                    self._st["ann_stops"] = list(mstops)
                    out += self._say_plan(mstops, model, laps_done,
                                          laptime, constraint, tank,
                                          revise=True)
        else:
            self._st["ann_stops"] = list(mstops)
            out += self._say_plan(mstops, model, laps_done, laptime,
                                  constraint, tank, revise=False)
        return [m for m in out if m]

    def _say_plan(self, mstops, model, laps_done, laptime, constraint,
                  tank, revise):
        out = []
        fonte = self._L("energia", "energy", "energia", "energie") \
            if constraint == "ENERGY" else \
            self._L("benzina", "fuel", "gasolina", "essence")
        out.append(self.msg("briefing_plan", laps=model["race_laps"],
                            autonomy=self._plan["start_stint"],
                            stints=len(mstops) + 1, stops=len(mstops),
                            fonte=fonte))
        # arco meteo: al briefing E a ogni CAMBIO vero (mai piu' inchiodato)
        arc_sig = tuple((sg[2], int(round(sg[0] / 2.0)))
                        for sg in model["segments"]) \
            if len(model["segments"]) > 1 else None
        if arc_sig and ((not revise)
                        or arc_sig != self._st.get("arc_sig")):
            self._st["arc_sig"] = arc_sig
            DRY = self._L("asciutto", "dry", "seco", "sec")
            WET = self._L("bagnato", "wet", "mojado", "mouille")
            fsegs = [sg for sg in model["segments"] if sg[1] > laps_done]
            parts = []
            for i, sg in enumerate(fsegs):
                nm = WET if sg[2] == "wet" else DRY
                if i == len(fsegs) - 1:
                    parts.append(self._L("poi %s fino alla fine",
                                         "then %s to the end",
                                         "luego %s hasta el final",
                                         "puis %s jusqu'au bout") % nm)
                else:
                    mins = int(round(max(0, sg[1] - laps_done)
                                     * laptime / 60.0))
                    parts.append(self._L("%s fino al giro %d (~%d min)",
                                         "%s until lap %d (~%d min)",
                                         "%s hasta la vuelta %d (~%d min)",
                                         "%s jusqu'au tour %d (~%d min)")
                                 % (nm, sg[1], mins))
            out.append(self.msg("plan_wx_arc", arc=", ".join(parts)))
        if mstops:
            TY = {"W": self._L("wet", "wets", "wet", "pluie"),
                  "S": self._L("slick", "slicks", "slick", "slick"),
                  None: self._L("solo rabbocco", "fuel only",
                                "solo carga", "carburant")}
            pcw = self._L("per cento", "percent", "por ciento", "pour cent")
            ltw = self._L("litri", "liters", "litros", "litres")

            def _tgt(st):
                t = min(100.0, (st.get("refuel_pct") or 0)
                        + (st.get("arrive_pct") or 0))
                if t <= 0:
                    return ""
                if constraint == "ENERGY":
                    return ", %d %s" % (round(t), pcw)
                return ", %d %s" % (round(t * tank / 100.0), ltw)
            st_txt = "; ".join(
                self._L("giro %d %s", "lap %d %s", "vuelta %d %s",
                        "tour %d %s") % (st["lap"], TY.get(st["tyre"]))
                + _tgt(st) for st in mstops)
            out.append(self.msg("plan_model_stops", n=len(mstops),
                                stops=st_txt))
        return out

    # ── ADVISOR: sicurezza e informazione ────────────────────────────
    def rain_live(self, raw, laps_done):
        """PIOGGIA IN DIRETTA — la chiamata SACRA. Stati sulla TRAIETTORIA IDEALE
        (`wetness_min` = la linea che guidi; l'acqua fuori-linea la gestisce
        wet_patches). Soglie del crossover REALE S397: asciutto <0.15, umido
        0.15-0.20 (zona grigia), **bagnato >0.20** -> con slick = ORDINE box wet.
        Isteresi 2 letture. (Prima era 0.25 sulla media = mia interpretazione;
        ora la soglia vera S397.)"""
        raw = raw or {}
        try:
            _wl = raw.get("wetness_min")     # traiettoria ideale (la linea)
            w = float(_wl if _wl is not None else (raw.get("wetness") or 0.0))
            rn = float(raw.get("raining") or 0.0)
        except (TypeError, ValueError):
            return []
        state = "wet" if (w > 0.20 or rn >= 0.4) else \
            ("damp" if (w > 0.15 or rn >= 0.15) else "dry")
        pend = self._st.get("rain_pend")
        if state != self._st.get("rain_state"):
            if pend == state:
                self._st["rain_n"] = self._st.get("rain_n", 0) + 1
            else:
                self._st["rain_pend"] = state
                self._st["rain_n"] = 1
                return []
            if self._st["rain_n"] < 2:
                return []
            prev = self._st.get("rain_state")
            self._st["rain_state"] = state
            self._st.pop("rain_pend", None)
            wetm = self._wet_mounted(raw)
            if state == "wet" and not wetm:
                # SICUREZZA: slick sull'acqua non si guida — ordine
                return [self.msg("rain_box_now")]
            if state == "damp" and prev == "dry" and not wetm:
                return [self.msg("rain_starting")]
            if state == "dry" and prev in ("damp", "wet") and wetm:
                return [self.msg("rain_dryline")]
        return []

    def wet_tyre(self, raw):
        """Gomma vs pista (consiglio, MAI a gomma gia' giusta)."""
        raw = raw or {}
        try:
            w = float(raw.get("wetness") or 0.0)
        except (TypeError, ValueError):
            return []
        wetm = self._wet_mounted(raw)
        if wetm and w < 0.05 and not self._st.get("wt_slick_said"):
            self._st["wt_slick_said"] = True
            return [self.msg("advise_slick")]
        if w >= 0.05:
            self._st.pop("wt_slick_said", None)
        return []

    def damage_call(self, raw):
        """Danni GRAVI: ruota persa / foratura / carrozzeria con PERDITA VERA
        di carico (aero) o piu' pannelli sfondati = chiamata di sicurezza.
        Uno SFIORO (un pezzetto staccato, un solo bozzo) NON basta piu'.
        Una volta per danno, riarmo a pulito."""
        raw = raw or {}
        woff = any(bool(x) for x in (raw.get("wheel_off") or []))
        flat = any(bool(x) for x in (raw.get("wheel_flat") or []))
        # GRAVITA' come il widget LIST: integrita' carrozzeria (dent, su 24) e
        # integrita' aero (1 - danno). box solo in ZONA ROSSA (<45% = grave),
        # non per uno sfioro (che resta giallo, 90%+).
        dent = raw.get("dent_sev") or []
        body_integ = 100 - int(round(
            sum(min(int(x or 0), 3) for x in dent) / 24.0 * 100)) \
            if dent else 100
        try:
            aero = max(0.0, min(1.0, float(raw.get("aero") or 0.0)))
        except (TypeError, ValueError):
            aero = 0.0
        aero_integ = int(round((1.0 - aero) * 100))
        body_bad = body_integ < 45 or aero_integ < 45   # rosso = danno grave
        code = ("box_retire" if woff else "box_flat" if flat
                else "box_damage" if body_bad else None)
        if code is None:
            self._st.pop("dmg_code", None)
            return []
        if code == self._st.get("dmg_code"):
            return []
        self._st["dmg_code"] = code
        return [self.msg(code)]

    def terminal_damage(self, raw):
        """DANNO TERMINALE: combo contatto + danno + motore SPENTO (per le HY
        ibride anche l'e-motore spento, senno' e' un falso). Se non riparte
        entro 10s -> ritiro (frase per tipo sessione) e da qui SILENZIA i
        messaggi inutili. Una volta per sessione."""
        raw = raw or {}
        if self._st.get("term_said"):
            # RECUPERO: se la macchina e' chiaramente viva (motore sotto carico)
            # era un FALSO ritiro -> sblocca e torna a parlare.
            try:
                if float(raw.get("rpm") or 0.0) > 3000.0:
                    self._st.pop("term_said", None)
                    self._st.pop("terminal", None)
                    self._st.pop("term_t0", None)
                else:
                    return []
            except (TypeError, ValueError):
                return []
        now = _time.monotonic()
        try:
            rpm = float(raw.get("rpm") or 0.0)
            imag = float(raw.get("impact_mag") or 0.0)
        except (TypeError, ValueError):
            return []
        # DANNO presente
        dmg = (any(raw.get("wheel_off") or []) or any(raw.get("wheel_flat") or [])
               or bool(raw.get("parts_off"))
               or any(int(x or 0) >= 2 for x in (raw.get("dent_sev") or [])))
        try:
            dmg = dmg or float(raw.get("aero") or 0.0) >= 0.15
        except (TypeError, ValueError):
            pass
        # MOTORE MORTO (per le HY ibride anche l'e-motore, senno' e' un falso)
        dead = rpm < 50.0
        my = (class_tag(raw.get("car_class") or "") or self._cat or "").upper()
        if my in ("HY", "LMH", "LMDH"):
            try:
                dead = dead and float(raw.get("emotor_rpm") or 0.0) < 50.0
            except (TypeError, ValueError):
                pass
        # CONTATTO registrato (botta vera)
        if imag >= 250.0:
            self._st["term_hit_t"] = now
        hit = (now - self._st.get("term_hit_t", -1e9)) < 60.0
        if not (dmg and dead and hit):
            self._st.pop("term_t0", None)       # riparte / non piu' combo
            return []
        t0 = self._st.get("term_t0")
        if t0 is None:
            self._st["term_t0"] = now            # parte il conto dei 10s
            return []
        if now - t0 < 10.0:
            return []
        # TERMINALE: la macchina e' andata
        self._st["term_said"] = True
        self._st["terminal"] = True              # silenzia il resto (sanity)
        kind = session_kind(raw.get("session_type"))
        code = ("retire_practice" if kind == "practice"
                else "retire_quali" if kind == "qualy" else "retire_race")
        return [self.msg(code)]

    def aero_call(self, raw):
        """MODULO DANNI (unico): CHECK CONTATTO ('contatto con X' all'urto) +
        CHECK DANNO (aero % e sospensioni dai wearables LMU). Informazione, la
        scelta e' del pilota. Il vecchio contact_call e' stato tolto: qui non
        ci sono voci che si contraddicono."""
        raw = raw or {}
        out = []
        # ── CHECK CONTATTO: chi hai toccato (una volta per urto, se accanto) ──
        _et = float(raw.get("impact_et") or 0.0)
        _mag = float(raw.get("impact_mag") or 0.0)
        _prev_et = self._st.get("aero_imp_et")
        self._st["aero_imp_et"] = _et
        if _prev_et is not None and _et > _prev_et and _mag >= 200.0:
            # CHI: auto piu' vicina lungo la pista, soglia stretta 6m (a 20m
            # incolpava un pilota anche contro un muro). Il metodo 3D via
            # mLastImpactPos e' piu' preciso ma il punto e' in coord LOCALI
            # dell'auto: serve la matrice mOri per portarlo in mondo (TODO).
            _nc = raw.get("nearest_car") or {}
            try:
                _near = abs(float(_nc.get("gap_m"))) <= 6.0
            except (TypeError, ValueError):
                _near = False
            _who = (_nc.get("name") or None) if _near else None
            _nowc = _time.monotonic()
            # CORDOLO, NON CONTATTO: LMU conta il bump del cordolo come
            # "urto" (verificato in variante). Se una ruota e' sul cordolo
            # e nessuna auto e' accanto -> niente crisi/verdetto: e' un
            # bump, ci pensa kerb_call.
            try:
                _srf = raw.get("surface_type") or []
                _onk = any(int(s) == 5 for s in _srf if s is not None)
            except (TypeError, ValueError):
                _onk = False
            if _onk and not _who and _mag < 700.0:
                _prev_et = None            # classificato cordolo: ignora
        if _prev_et is not None and _et > _prev_et and _mag >= 200.0:
            if _mag >= 400.0:
                # BOTTA FORTE: apre la finestra-incidente (sanity: per 12s
                # passano solo sicurezza/danni, niente meteo/gap/coaching)
                self._st["crisis_t"] = _nowc
            # NIENTE annuncio immediato "contatto con X": parlava DUE volte
            # (subito + verdetto). Ora parla SOLO il verdetto (~6s), che
            # nomina il pilota e dice subito se ci sono danni o no.
            if _mag >= 600.0 and not _who \
                    and _nowc - self._st.get("drv_chk_t", 0.0) > 20.0:
                # botta SERIA contro MURO/barriera o da solo (nessun pilota
                # nell'urto): il muretto chiede come stai. Per i contatti di
                # pista con un'altra auto NON ha senso — resta la frase contatto.
                self._st["drv_chk_t"] = _nowc
                out.append(self.msg("driver_check"))
            # VALUTAZIONE DANNI post-impatto: fotografa lo stato attuale;
            # tra ~6s (dati wearables aggiornati) arriva UN verdetto umano:
            # "nessun danno" oppure "danno a X, vedi se riesci a continuare".
            if not self._st.get("dmg_eval"):
                try:
                    _a0 = float(raw.get("aero") or 0.0)
                except (TypeError, ValueError):
                    _a0 = 0.0
                _su = raw.get("susp")
                _s0 = tuple(float(x or 0.0) for x in _su[:4]) \
                    if isinstance(_su, (list, tuple)) and len(_su) >= 4 \
                    else (0.0, 0.0, 0.0, 0.0)
                self._st["dmg_eval"] = {"t": _nowc, "who": _who,
                                        "aero": _a0, "susp": _s0}
            elif _who and not self._st["dmg_eval"].get("who"):
                self._st["dmg_eval"]["who"] = _who
        # ── CHECK DANNO ──
        a = raw.get("aero")
        try:
            a = float(a) if a is not None else None
        except (TypeError, ValueError):
            a = None
        if a is not None:
            lvl = 3 if a >= 0.30 else 2 if a >= 0.15 else 1 if a >= 0.05 else 0
            prev = self._st.get("aero_lvl", 0)
            if lvl == 0:
                self._st["aero_lvl"] = 0
            elif lvl > prev and not self._st.get("dmg_eval"):
                # (durante la valutazione post-impatto tace: il verdetto
                # unico copre il danno, niente doppio annuncio)
                self._st["aero_lvl"] = lvl
                code = ("aero_heavy" if lvl == 3
                        else "aero_mid" if lvl == 2 else "aero_light")
                out.append(self.msg(code, pct=int(round(a * 100))))
        su = raw.get("susp")
        if isinstance(su, (list, tuple)) and len(su) >= 4:
            said = self._st.setdefault("susp_said", set())
            W = (self._L("anteriore sinistra", "front left",
                         "delantera izquierda", "avant gauche"),
                 self._L("anteriore destra", "front right",
                         "delantera derecha", "avant droite"),
                 self._L("posteriore sinistra", "rear left",
                         "trasera izquierda", "arriere gauche"),
                 self._L("posteriore destra", "rear right",
                         "trasera derecha", "arriere droite"))
            for i in range(4):
                try:
                    v = float(su[i] or 0.0)
                except (TypeError, ValueError):
                    continue
                if v >= 0.10 and i not in said \
                        and not self._st.get("dmg_eval"):
                    said.add(i)
                    out.append(self.msg("susp_damage", ruota=W[i],
                                        pct=int(round(v * 100))))
                elif v < 0.05 and i in said:
                    said.discard(i)
        # ── VERDETTO post-impatto (UN report umano, ~6s dopo la botta) ──
        ev = self._st.get("dmg_eval")
        if ev and _time.monotonic() - ev["t"] >= 6.0:
            self._st.pop("dmg_eval", None)
            try:
                a1 = float(raw.get("aero") or 0.0)
            except (TypeError, ValueError):
                a1 = 0.0
            _su1 = raw.get("susp")
            s1 = tuple(float(x or 0.0) for x in _su1[:4]) \
                if isinstance(_su1, (list, tuple)) and len(_su1) >= 4 \
                else ev["susp"]
            _WN = (self._L("la sospensione anteriore sinistra",
                           "front left suspension",
                           "la suspension delantera izquierda",
                           "la suspension avant gauche"),
                   self._L("la sospensione anteriore destra",
                           "front right suspension",
                           "la suspension delantera derecha",
                           "la suspension avant droite"),
                   self._L("la sospensione posteriore sinistra",
                           "rear left suspension",
                           "la suspension trasera izquierda",
                           "la suspension arriere gauche"),
                   self._L("la sospensione posteriore destra",
                           "rear right suspension",
                           "la suspension trasera derecha",
                           "la suspension arriere droite"))
            parts = []
            if a1 - ev["aero"] >= 0.03:
                parts.append(self._L("l'aerodinamica", "the aero",
                                     "la aerodinamica", "l'aero"))
                lvl1 = 3 if a1 >= 0.30 else 2 if a1 >= 0.15 \
                    else 1 if a1 >= 0.05 else 0
                self._st["aero_lvl"] = max(self._st.get("aero_lvl", 0), lvl1)
            _sd = self._st.setdefault("susp_said", set())
            for i in range(4):
                if s1[i] - ev["susp"][i] >= 0.08:
                    parts.append(_WN[i])
                    _sd.add(i)                   # niente doppio annuncio
            who = ev.get("who")
            if parts:
                _e = self._L(" e ", " and ", " y ", " et ")
                _pl = _e.join(parts) if len(parts) <= 2 else \
                    ", ".join(parts[:-1]) + _e + parts[-1]
                code = "contact_damage_who" if who else "contact_damage"
                out.append(self.msg(code, name=who or "", parts=_pl))
            else:
                out.append(self.msg("contact_ok_who", name=who)
                           if who else self.msg("contact_ok"))
        return [m for m in out if m]

    def wheel_bend_call(self, raw):
        """DANNI FISICI dal trace (scoperta 23/07, incidente Ascari):
        1) RUOTA PIEGATA — hdvehicle 'Bending wheel #N severity (toe/
           camber)': fisica alta = SOLO il giocatore. La piega NON e' la
           rottura: suspensionDamage puo' restare 0 ma la convergenza e'
           storta e la macchina tira da un lato. Wearables non la vedono:
           questa e' l'unica fonte.
        2) CAUSA RITIRO — 'LocalDNF due to Engine/Suspension/Accident':
           la conferma ufficiale del motore/telaio morto che REST e
           shared memory non danno.
        Aspetta che il verdetto contatto (~6s) abbia parlato; per ruota
        ri-annuncia solo se la piega PEGGIORA (mai ripetersi)."""
        raw = raw or {}
        out = []
        try:
            from core.race_control import recent_wheel_bends, latest_dnf
        except Exception:
            return []
        # ── RUOTE PIEGATE (dopo il verdetto danni, mai in contemporanea)
        try:
            bends = recent_wheel_bends(window=10.0)
        except Exception:
            bends = []
        if bends and not self._st.get("dmg_eval"):
            W = (self._L("anteriore sinistra", "front left",
                         "delantera izquierda", "avant gauche"),
                 self._L("anteriore destra", "front right",
                         "delantera derecha", "avant droite"),
                 self._L("posteriore sinistra", "rear left",
                         "trasera izquierda", "arriere gauche"),
                 self._L("posteriore destra", "rear right",
                         "trasera derecha", "arriere droite"))
            said = self._st.setdefault("bend_said", {})
            w, sev, _toe, _cam = max(bends, key=lambda b: b[1])
            # sotto 0.20 e' il rumore dei cordoli (visto 0.03 nei trace)
            if 0 <= w <= 3 and sev >= 0.20 \
                    and sev > said.get(w, 0.0) + 0.10:
                said[w] = sev
                out.append(self.msg("wheel_bent_bad" if sev >= 0.5
                                    else "wheel_bent", ruota=W[w]))
        # ── CAUSA RITIRO (solo il giocatore, una volta per evento)
        try:
            t, drv, why = latest_dnf()
        except Exception:
            t = 0.0
        # SOLO in gara: in prova/quali il rientro al monitor con danni
        # genera la stessa riga ma non e' un ritiro (visto nei trace)
        if t and t != self._st.get("dnf_said_t") \
                and session_kind(raw.get("session_type")) == "race":
            pl = (raw.get("driver") or "").strip().lower()
            if pl and pl == (drv or "").strip().lower():
                self._st["dnf_said_t"] = t
                code = {"Engine": "retire_engine",
                        "Suspension": "retire_susp",
                        "Accident": "retire_accident"}.get(why)
                if code:
                    out.append(self.msg(code))
        return [m for m in out if m]

    def contact_call(self, raw):
        """SPOTTER contatti: alla botta fotografa i danni; se dopo ~3s
        sono invariati -> 'toccato, tutto ok'. Cooldown 30s."""
        raw = raw or {}
        et = float(raw.get("impact_et") or 0.0)
        mag = float(raw.get("impact_mag") or 0.0)
        prev = self._st.get("imp_prev")
        self._st["imp_prev"] = et
        now = _time.monotonic()
        pend = self._st.get("imp_pend")
        if prev is not None and et > prev and mag >= 200.0:
            # CHI: l'auto piu' vicina all'istante dell'urto, solo se davvero
            # accanto (<=20 m) -> un pilota, non un muro/cordolo.
            _nc = raw.get("nearest_car") or {}
            try:
                _near = abs(float(_nc.get("gap_m"))) <= 20.0
            except (TypeError, ValueError):
                _near = False
            self._st["imp_pend"] = {
                "t": now, "aero": float(raw.get("aero") or 0.0),
                "dent": sum(int(x or 0) for x in (raw.get("dent_sev") or [])),
                "susp": max([float(x) for x in (raw.get("susp") or [0.0])]
                            or [0.0]),
                "who": (_nc.get("name") or None) if _near else None,
                "zone": self._impact_zone(raw)}     # QUALE parte tocca
            return []
        if pend and now - pend["t"] >= 3.0:
            self._st.pop("imp_pend", None)
            if now - self._st.get("imp_said_t", 0.0) < 30.0:
                return []
            # COMPONENTI danneggiati (info, separati dalla chiamata box):
            # aero, sospensione, carrozzeria, ruota. Confronto pre/post urto.
            _aero = float(raw.get("aero") or 0.0)
            _dent = sum(int(x or 0) for x in (raw.get("dent_sev") or []))
            _susp = max([float(x) for x in (raw.get("susp") or [0.0])] or [0.0])
            _woff = any(bool(x) for x in (raw.get("wheel_off") or []))
            _wflat = any(bool(x) for x in (raw.get("wheel_flat") or []))
            parts = []
            if _woff:
                parts.append(self._L("ruota", "wheel", "rueda", "roue"))
            elif _wflat:
                parts.append(self._L("gomma", "tyre", "neumatico", "pneu"))
            if _susp > pend.get("susp", 0.0) + 0.02:
                parts.append(self._L("sospensione", "suspension",
                                     "suspension", "suspension"))
            if _aero > pend["aero"] + 0.02:
                parts.append(self._L("aerodinamica", "aero", "aero", "aero"))
            if _dent > pend["dent"] or raw.get("parts_off"):
                parts.append(self._L("carrozzeria", "bodywork",
                                     "carroceria", "carrosserie"))
            who = pend.get("who")
            self._st["imp_said_t"] = now
            if not parts:                        # nessun componente peggiorato
                return [self.msg("contact_ok_who", name=who) if who
                        else self.msg("contact_ok")]
            _pt = ", ".join(parts)
            if who:
                return [self.msg("contact_damage_who", parts=_pt, name=who)]
            return [self.msg("contact_damage", parts=_pt)]
        return []

    _IMPACT_FRONT_SIGN = 1     # se in pista davanti/dietro risulta invertito -> -1
    _IMPACT_RIGHT_SIGN = 1     # se sinistra/destra risulta invertito -> -1

    def _impact_zone(self, raw):
        """Parte della macchina colpita dall'ultimo urto, da mLastImpactPos.
        Convenzione TinyPedal: lato = -impact_x, longitudinale = impact_z.
        Assunta: davanti = z>0, destra = x(neg)>0. Se in pista risulta
        specchiato, invertire _IMPACT_FRONT_SIGN / _IMPACT_RIGHT_SIGN."""
        try:
            lx = -float(raw.get("impact_x") or 0.0) * self._IMPACT_RIGHT_SIGN
            lz = float(raw.get("impact_z") or 0.0) * self._IMPACT_FRONT_SIGN
        except (TypeError, ValueError):
            return None
        if abs(lx) < 0.05 and abs(lz) < 0.05:
            return None
        fb = lr = None
        if abs(lz) >= abs(lx) * 0.5:
            fb = "front" if lz > 0 else "rear"
        if abs(lx) >= abs(lz) * 0.5:
            lr = "right" if lx > 0 else "left"
        _F = self._L("davanti", "at the front", "delante", "a l'avant")
        _B = self._L("dietro", "at the rear", "detras", "a l'arriere")
        _R = self._L("a destra", "on the right", "a la derecha", "a droite")
        _Lt = self._L("a sinistra", "on the left", "a la izquierda", "a gauche")
        _Rs = self._L("sulla fiancata destra", "on the right side",
                      "en el lado derecho", "sur le flanc droit")
        _Ls = self._L("sulla fiancata sinistra", "on the left side",
                      "en el lado izquierdo", "sur le flanc gauche")
        if fb and lr:
            return "%s %s" % (_F if fb == "front" else _B,
                              _R if lr == "right" else _Lt)
        if fb:
            return _F if fb == "front" else _B
        if lr:
            return _Rs if lr == "right" else _Ls
        return None

    def flags_call(self, raw):
        """Gialla LOCALE davanti + BLU a gruppo vero (dati da
        shared_memory.flags: finestra 300m, treno <=1s)."""
        raw = raw or {}
        fl = raw.get("flags") or {}
        out = []
        ydist = fl.get("yellow_dist")
        if fl.get("self_slow"):
            self._st["self_yellow_t"] = _time.monotonic()
        own = (_time.monotonic()
               - self._st.get("self_yellow_t", -999.0)) < 20.0
        # VOCE gialla: SOLO i 500 metri davanti (ydist), MAI i settori
        # (richiesta utente 23/07: la chiamata settore resta solo nel
        # banner Race Control; la legge anti-chiacchiera sotto gialla resta).
        if ydist is not None and self._st.get("flag_state") != "yellow":
            self._st["flag_state"] = "yellow"
            if not own:
                out.append(self.msg("local_yellow",
                                    dist=int(round(float(ydist) / 50.0) * 50)))
        elif ydist is None and self._st.get("flag_state") == "yellow":
            self._st["flag_state"] = None
        n_blue = int(fl.get("blue_count")
                     or (1 if fl.get("blue_class") else 0))
        if n_blue > 0:
            now = _time.monotonic()
            if n_blue < int(self._st.get("blue_n", 0)):
                self._st["blue_n"] = n_blue      # auto USCITE: abbassa la base
            _new = not self._st.get("blue_on")               # gruppo nuovo
            _grew = n_blue > int(self._st.get("blue_n", 0))  # ARRIVANO altre auto
            # SAFETY: annuncia il gruppo nuovo O l'arrivo di ALTRE auto dietro
            # (non aspettare che il gruppo si svuoti: chi ti doppia va detto
            # subito). Cooldown breve 5s; blue_on evita di ridire il gruppo
            # stabile che non cambia.
            if (_new or _grew) and now - self._st.get("blue_t", 0.0) >= 5.0:
                self._st["blue_on"] = True
                self._st["blue_t"] = now
                self._st["blue_n"] = n_blue      # base = conteggio ANNUNCIATO
                my = (class_tag(raw.get("car_class") or "")
                      or self._cat or "").upper()
                bt = (class_tag(str(fl.get("blue_class") or "")) or "").upper()
                # nome PRONUNCIABILE: "HY" detto dalla voce diventa
                # "acca ipsilon" — si parla per nome classe
                _NAME = {"HY": "Hypercar", "P2": "LMP2", "P3": "LMP3",
                         "GTE": "GTE", "GT3": "GT3", "GT": "GT"}
                _spk = _NAME.get(bt, bt)
                _bcl = fl.get("blue_classes") or []
                if n_blue > 1 and _bcl:
                    # ripartizione VERA per classe: "2 Hypercar, 1 GT"
                    _lista = ", ".join("%d %s" % (cnt, _NAME.get(tg, tg))
                                       for tg, cnt in _bcl)
                    out.append(self.msg("blue_flag_train", lista=_lista))
                elif n_blue > 1:
                    out.append(self.msg("blue_flag_multi", n=n_blue,
                                        classe=_spk if bt else ""))
                elif bt and bt != my:
                    out.append(self.msg("blue_flag", classe=_spk))
                else:
                    out.append(self.msg("blue_flag_simple"))
        elif n_blue == 0:
            self._st["blue_on"] = False
            self._st["blue_n"] = 0
        return [m for m in out if m]

    def gap_call(self, raw, laps_done):
        """Rivali: undercut a 2 STADI (chiamata box -> sosta vera) col
        PASSO MISURATO nella frase; poi trend/gap ogni 3 giri."""
        raw = raw or {}
        riv = raw.get("rivals") or {}
        try:
            ga = float(riv.get("gap_ahead"))
        except (TypeError, ValueError):
            ga = None
        try:
            gb = float(riv.get("gap_behind"))
        except (TypeError, ValueError):
            gb = None
        na = riv.get("name_ahead") or ""
        nb = riv.get("name_behind") or ""

        def _fg(g):
            return ("%.1f" % g).replace(".", ",")

        a_req = bool(riv.get("ahead_pit_req"))
        a_in = bool(riv.get("ahead_pit"))
        stt = self._st.get("gap_pit")
        if ga is not None and 0 < ga <= 28.0 and a_in and stt != "ahead":
            self._st["gap_pit"] = "ahead"
            return [self.msg("gap_undercut", gap=_fg(ga), name=na,
                             passo=self._pace_vs_ahead(riv) or "")]
        if ga is not None and 0 < ga <= 28.0 and a_req and not a_in \
                and stt is None:
            self._st["gap_pit"] = "called"
            return [self.msg("gap_pit_called", gap=_fg(ga), name=na,
                             passo=self._pace_vs_ahead(riv) or "")]
        if not (a_req or a_in):
            self._st["gap_pit"] = None

        # trend misurato dal passo (storico REST) o dal gap
        if laps_done and laps_done - self._st.get("gap_lap", -9) >= 3:
            if ga is None and gb is None:
                return []
            self._st["gap_lap"] = laps_done
            try:
                ap = float(riv.get("ahead_pace") or 0.0)
                mp = float(riv.get("my_pace") or 0.0)
            except (TypeError, ValueError):
                ap = mp = 0.0
            rate = (ap - mp) if (ap > 20 and mp > 20) else None
            if rate is not None and rate >= 0.12 and ga is not None:
                catch = ga / rate
                if 0 < catch <= 25:
                    return [self.msg("gap_closing", name=na,
                                     rate=("%.1f" % rate).replace(".", ","),
                                     laps=max(1, int(round(catch))),
                                     gap=_fg(ga))]
            if rate is not None and rate <= -0.12 and ga is not None:
                return [self.msg("gap_losing", name=na,
                                 rate=("%.1f" % abs(rate)).replace(".", ","),
                                 gap=_fg(ga))]
            if ga is not None and gb is not None:
                return [self.msg("gap_both", ahead=_fg(ga), behind=_fg(gb),
                                 na=na, nb=nb)]
            if ga is not None:
                return [self.msg("gap_ahead", gap=_fg(ga), name=na)]
            if gb is not None:
                return [self.msg("gap_behind", gap=_fg(gb), name=nb)]
        return []

    def traffic_ahead_call(self, raw):
        """Spotter gruppi di doppiati davanti (3+, dal reader)."""
        riv = (raw or {}).get("rivals") or {}
        ta = riv.get("traffic_ahead") or {}
        n = int(ta.get("count") or 0)
        near = ta.get("near")
        lap = int((raw or {}).get("laps_completed") or 0)
        if n >= 3 and not self._st.get("ta_on"):
            self._st["ta_on"] = True
            m = int(round((near or 300) / 100.0) * 100)
            sig = (min(n, 6), max(100, m))
            if lap - self._st.get("ta_lap", -9) < 2 \
                    and sig == self._st.get("ta_sig"):
                return []
            self._st["ta_lap"] = lap
            self._st["ta_sig"] = sig
            return [self.msg("traffic_ahead", n=n, m=max(100, m))]
        if n <= 1:
            self._st["ta_on"] = False
        return []

    def lap_time_call(self, raw):
        """Tempo a OGNI giro completato (opzione radio)."""
        raw = raw or {}
        lt = float(raw.get("last_lap") or 0.0)
        ld = int(raw.get("laps_completed") or 0)
        if lt <= 20.0 or ld <= 0:
            return []
        if ld == self._st.get("lt_lap"):
            return []
        self._st["lt_lap"] = ld
        return [self.msg("lap_time_call", tempo=_fmt_lap_round(lt))]

    def lap_feedback(self, raw, laps_done):
        """Debrief fine giro: best personale nuovo, oppure dove perdi."""
        raw = raw or {}
        lt = float(raw.get("last_lap") or 0.0)
        if lt <= 20.0 or not laps_done:
            return []
        if laps_done == self._st.get("lf_lap"):
            return []
        self._st["lf_lap"] = laps_done
        best = self._st.get("lf_best")
        if best is None or lt < best - 0.005:
            self._st["lf_best"] = lt
            if best is not None:
                return [self.msg("best_lap_new",
                                 tempo=_fmt_lap_round(lt))]
            return []
        # settore peggiore vs il TUO best di settore
        secs = (raw.get("last_s1"), raw.get("last_s2"))
        sb = self._st.setdefault("lf_secbest", [None, None, None])
        try:
            s1 = float(secs[0] or 0.0)
            s2 = float(secs[1] or 0.0) - s1
            s3 = lt - s1 - s2
            cur = [s1, s2, s3]
        except (TypeError, ValueError):
            return []
        self._st["lf_lastsec"] = list(cur)
        worst, wloss = None, 0.0
        for i, v in enumerate(cur):
            if v <= 0:
                continue
            if sb[i] is None or v < sb[i]:
                sb[i] = v
            elif v - sb[i] > wloss:
                worst, wloss = i, v - sb[i]
        if worst is not None and wloss >= 0.4 \
                and laps_done - self._st.get("lf_said", -9) >= 3:
            self._st["lf_said"] = laps_done
            return [self.msg("sector_loss", settore=worst + 1,
                             perdita=("%.1f" % wloss).replace(".", ","))]
        return []

    def tyre_life(self, raw, laps_done):
        """Degrado: soglia d'attenzione e gomma finita, una volta."""
        raw = raw or {}
        tw = raw.get("tyre_wear")
        if not (isinstance(tw, (list, tuple)) and tw):
            return []
        try:
            worst = min(float(x) for x in tw if x is not None)
        except (TypeError, ValueError):
            return []
        dead = 78.0 if self._wet_mounted(raw) else 70.0
        if worst <= dead and not self._st.get("tl_dead"):
            self._st["tl_dead"] = True
            return [self.msg("box_tyre_dead")]
        if worst <= dead + 8 and not self._st.get("tl_warn"):
            self._st["tl_warn"] = True
            return [self.msg("tyre_worn_info", pct=int(round(worst)))]
        if worst > dead + 12:
            self._st.pop("tl_warn", None)
            self._st.pop("tl_dead", None)
        return []

    def grip_call(self, raw, laps_done):
        """Gommatura pista 0-4, parla su livello NUOVO stabile (5 letture)."""
        raw = raw or {}
        g = raw.get("track_grip")
        try:
            g = int(g)
        except (TypeError, ValueError):
            return []
        if not (0 <= g <= 4):
            return []
        if g != self._st.get("grip_cand"):
            self._st["grip_cand"] = g
            self._st["grip_n"] = 1
            return []
        self._st["grip_n"] = self._st.get("grip_n", 0) + 1
        if self._st["grip_n"] < 5 or self._st.get("grip_said") == g:
            return []
        prev = self._st.get("grip_said")
        self._st["grip_said"] = g
        # in PAROLE SEMPLICI: il pilota deve capire subito cosa cambia
        names = {0: self._L("verde, cioè senza gomma a terra: aderenza bassa",
                            "green, no rubber down: low grip",
                            "verde, sin goma: poco agarre",
                            "verte, sans gomme : peu de grip"),
                 1: self._L("con poca gomma: aderenza ancora scarsa",
                            "low on rubber: still poor grip",
                            "con poca goma: agarre escaso",
                            "peu gommee : grip encore faible"),
                 2: self._L("mediamente gommata: aderenza normale",
                            "medium rubbered: normal grip",
                            "con goma media: agarre normal",
                            "moyennement gommee : grip normal"),
                 3: self._L("ben gommata: tanta aderenza sulla traiettoria",
                            "well rubbered-in: strong grip on the line",
                            "bien engomada: mucho agarre en la trazada",
                            "bien gommee : beaucoup de grip sur la ligne"),
                 4: self._L("satura di gomma: massima aderenza sulla linea, "
                            "ma fuori traiettoria è sporco di biglie",
                            "saturated: maximum grip on line, marbles off it",
                            "saturada: agarre maximo en la linea, canicas "
                            "fuera",
                            "saturee : grip maximum sur la ligne, billes "
                            "en dehors")}
        if prev is None:
            return [self.msg("grip_status", stato=names[g])]
        return [self.msg("grip_up" if g > prev else "grip_down",
                         stato=names[g])]

    def _seed_sectors(self, raw):
        """Riferimento settori dal 1o giro: i migliori settori APPRESI su questa
        pista/classe (se ci sono), senno' [None,None,None] (parte dai tuoi)."""
        try:
            from core.engineer_learn import load as _ll
            prof = _ll(raw.get("track") or "",
                       class_tag(raw.get("car_class") or "")) or {}
            secs = (((prof.get("cond") or {}).get("dry") or {})
                    .get("sectors")) or []
            if isinstance(secs, list) and len(secs) == 3 \
                    and all(isinstance(x, (int, float)) and x > 0 for x in secs):
                return [float(secs[0]), float(secs[1]), float(secs[2])]
        except Exception:
            pass
        return [None, None, None]

    def sector_delta(self, raw, laps_done):
        """DOVE PERDI: a fine giro confronta i 3 settori col tuo MIGLIORE e, se
        perdi in modo netto (>=0.18s), te lo dice. Solo all'asciutto (sul bagnato
        il passo e' grip-limited). Cadenza min ~2 giri, niente martellamento.
        Portato dalla v2 (seeding dai settori appresi omesso in 0.3b: parte dai
        settori reali)."""
        raw = raw or {}
        if not laps_done:
            return []
        rn = float(raw.get("raining") or 0.0)
        if rn >= 0.15 or self._wet_mounted(raw):     # bagnato: niente, azzera
            self._sec_best = [None, None, None]
            return []
        try:
            s1 = float(raw.get("last_s1"))
            s2c = float(raw.get("last_s2"))
            lt = float(raw.get("lap_time"))
        except (TypeError, ValueError):
            return []
        if s1 <= 0 or s2c <= s1 or lt <= s2c:         # giro/settori non validi
            return []
        if laps_done == getattr(self, "_sec_last_lap", None):
            return []
        self._sec_last_lap = laps_done
        secs = [s1, s2c - s1, lt - s2c]
        best = getattr(self, "_sec_best", None)
        if not isinstance(best, list):
            # SEED dal 1o giro: se la pista e' appresa uso i settori migliori
            # storici come riferimento -> "dove perdi" gia' dal primo giro.
            best = self._sec_best = self._seed_sectors(raw)
        deltas = []
        for i in range(3):
            if best[i] is None or secs[i] < best[i]:
                best[i] = secs[i]
                deltas.append(0.0)
            else:
                deltas.append(secs[i] - best[i])
        worst = max(range(3), key=lambda i: deltas[i])
        loss = deltas[worst]
        if loss < 0.18:                               # perdita non significativa
            return []
        if getattr(self, "_sec_rep_lap", None) is not None \
                and (laps_done - self._sec_rep_lap) < 2:
            return []
        self._sec_rep_lap = laps_done
        d = int(round(loss * 10))
        perdita = ("%d decimi" % d) if d < 10 else ("%d e %d" % (d // 10, d % 10))
        return [self.msg("sector_loss", settore=worst + 1, perdita=perdita)]

    def _fmt_gap(self, g):
        return ("%.1f" % g).replace(".", ",")

    def fast_class_call(self, raw):
        """PRE-BLU: classe piu' veloce in ARRIVO (gap in secondi) PRIMA che il
        gioco sventoli la blu — qualche secondo in piu' per decidere dove farla
        passare. Una per vettura, solo se sta CHIUDENDO; riarmo a >8s. (v2)"""
        raw = raw or {}
        # AL VIA il campo e' ammassato e i gap non sono affidabili: niente
        # pre-blu nel primo giro (evita chiamate a vuoto tipo "hyper dietro"
        # quando le classi veloci sono in realta' tutte davanti).
        if int(raw.get("laps_completed") or 0) < 1:
            return []
        riv = raw.get("rivals") or {}
        traffic = riv.get("traffic_behind") or []
        _RK = {"HY": 4, "LMH": 4, "LMDH": 4, "P2": 3, "LMP2": 3,
               "P3": 2, "LMP3": 2, "GT3": 1, "LMGT3": 1, "GTE": 1}
        my_rank = _RK.get(class_tag(raw.get("car_class") or "").upper(), 0)
        if my_rank >= 4:
            return []                    # la classe veloce sei tu
        now = _time.monotonic()
        prev = getattr(self, "_fc_prev", {}) or {}
        said = getattr(self, "_fc_said", None)
        if said is None:
            said = self._fc_said = set()
        cur, out = {}, []
        for t in traffic:
            cls = class_tag(t.get("cls") or "").upper()
            if _RK.get(cls, 0) <= my_rank:
                continue
            try:
                g = float(t.get("gap") or 0.0)
            except (TypeError, ValueError):
                continue
            nm = t.get("name") or cls
            cur[nm] = g
            if nm in said:
                if g > 8.0:
                    said.discard(nm)     # si e' staccata: riarma
                continue
            pg = prev.get(nm)
            closing = (pg is not None and (pg - g) >= 0.2)
            if (g <= 4.5 and closing and not out
                    and now - getattr(self, "_fc_t", 0.0) >= 12.0):
                said.add(nm)
                self._fc_t = now
                out.append(self.msg("fast_class_close",
                                    classe=_class_readable(cls),
                                    s=max(1, int(round(g)))))
        for nm in list(said):
            if nm not in cur:
                said.discard(nm)
        self._fc_prev = cur
        return out

    def pit_exit_traffic(self, raw):
        """SIMULAZIONE RIENTRO: proietta il traffico (tutte le classi) alla tua
        uscita dai box. Chi ti sta dietro entro ~pit_loss+3s ti sara' attorno al
        rientro. Dice quante auto, quante di classe piu' veloce, se c'e' un buco. (v2)"""
        raw = raw or {}
        # SOLO quando stai davvero per fermarti (pit chiamato / in corsia / box):
        # non ha senso "proiettare il rientro" a ogni giro in pista normale.
        try:
            if int(raw.get("pit_state") or 0) == 0:
                self._st.pop("pex_said", None)     # riarma alla prossima richiesta
                return []
        except (TypeError, ValueError):
            return []
        # UNA VOLTA per richiesta pit: senno' "aria pulita" si ripeteva in loop
        # (ogni 25s) restando fermo in corsia/box.
        if self._st.get("pex_said"):
            return []
        riv = raw.get("rivals") or {}
        traffic = riv.get("traffic_behind") or []
        pit_loss = self._pit_stop_seconds(raw)
        if not pit_loss:
            return []
        window = pit_loss + 3.0
        _RANK = {"HY": 4, "LMH": 4, "LMDH": 4, "P2": 3, "LMP2": 3,
                 "P3": 2, "LMP3": 2, "GT3": 1, "LMGT3": 1, "GTE": 1}
        my_rank = _RANK.get(class_tag((raw or {}).get("car_class") or "").upper(), 0)
        try:
            inside = [t for t in traffic if float(t.get("gap") or 0) <= window]
        except (TypeError, ValueError):
            return []
        self._st["pex_said"] = True            # detto: non ripetere fino a nuova richiesta
        if not inside:
            return [self.msg("pit_exit_clean", pit=self._fmt_gap(pit_loss))]
        faster = sum(1 for t in inside
                     if _RANK.get(class_tag(t.get("cls") or "").upper(), 0) > my_rank)
        after = [float(t["gap"]) for t in traffic if float(t.get("gap") or 0) > window]
        hole = (after[0] - window) if after else 99.0
        n = len(inside)
        if faster > 0:
            return [self.msg("pit_exit_fast", n=n, fast=faster,
                             pit=self._fmt_gap(pit_loss))]
        if hole >= 5.0:
            return [self.msg("pit_exit_hole", n=n, hole=self._fmt_gap(hole))]
        return [self.msg("pit_exit_traffic", n=n)]

    def garage_briefing(self, raw):
        """MOTORE ACCESO / prima di uscire dal box: briefing UNA volta —
        gommatura pista, temp asfalto, gomme montate (nuove o usate + mescola).
        Se piove e hai le slick: AVVISO forte 'non uscire, treno sbagliato'.
        Riarma solo dopo un vero giro in pista (torni al garage -> nuovo brief)."""
        raw = raw or {}
        in_box = bool(raw.get("garage") or raw.get("in_pits")
                      or raw.get("in_pitlane"))
        try:
            rpm = float(raw.get("rpm") or 0.0)
            spd = float(raw.get("speed") or 0.0)
        except (TypeError, ValueError):
            return []
        # riarmo: se sei uscito davvero in pista (fuori box, in movimento)
        if (not in_box) and spd > 60.0:
            self._st.pop("gb_said", None)
            self._st.pop("gb_wrong", None)
        # ── ROUTINE PRE-USCITA (prova lunga, motore SPENTO in garage):
        # come un muretto vero — "dammi due minuti, controllo la macchina
        # e decidiamo il programma". Se accendi subito: "ok, te lo dico
        # per strada". Una volta per visita al garage.
        try:
            _rem = float(raw.get("race_remaining") or 0.0)
        except (TypeError, ValueError):
            _rem = 0.0
        if in_box and session_kind(raw.get("session_type")) == "practice" \
                and _rem > 600.0:
            _nowg = _time.monotonic()
            if rpm < 300.0 and not self._st.get("gp_said") \
                    and spd < 2.0:
                self._st["gp_said"] = True
                self._st["gp_t"] = _nowg
                return [self.msg("garage_prep")]
            if rpm >= 300.0 and self._st.get("gp_said") \
                    and not self._st.get("gp_go") \
                    and _nowg - self._st.get("gp_t", 0.0) < 180.0:
                self._st["gp_go"] = True
                # motore acceso prima del check: si fa per strada
                if _nowg - self._st.get("gp_t", 0.0) < 100.0:
                    return [self.msg("garage_prep_go")]
        if not in_box:
            self._st.pop("gp_said", None)
            self._st.pop("gp_go", None)
        if not in_box or rpm < 300.0 or spd > 25.0:
            return []
        out = []
        # ── AVVISO SLICK SOTTO LA PIOGGIA (sicurezza, prima di tutto) ──
        try:
            w = float(raw.get("wetness_min") if raw.get("wetness_min") is not None
                      else (raw.get("wetness") or 0.0))
            rn = float(raw.get("raining") or 0.0)
        except (TypeError, ValueError):
            w = rn = 0.0
        wet_track = (w > 0.20 or rn >= 0.4)
        if wet_track and not self._wet_mounted(raw):
            if not self._st.get("gb_wrong"):
                self._st["gb_wrong"] = True
                out.append(self.msg("garage_wrong_tyre"))
        elif not wet_track:
            self._st.pop("gb_wrong", None)
        # ── BRIEFING INFO (una volta, dopo il warm-up per non perderlo) ──
        born = self._st.get("born")
        if born is None:                       # come il warm-up del sanity_filter
            born = self._st["born"] = _time.monotonic()
        if not self._st.get("gb_said") \
                and _time.monotonic() - born >= 5.5:
            self._st["gb_said"] = True
            gomme = self._tyre_word(raw)
            try:
                tt = int(round(float(raw.get("track_temp") or 0.0)))
            except (TypeError, ValueError):
                tt = 0
            # SITUAZIONE VERA del treno: nuova/usata (usura) e
            # fredda/calda (carcassa) -> frase umana col consiglio giusto
            new = None
            try:
                tw = [float(x) for x in (raw.get("tyre_wear") or [])
                      if x is not None]
                if tw:
                    new = min(tw) >= 97.0
            except (TypeError, ValueError):
                new = None
            warm = None
            try:
                tc = [float(x) for x in (raw.get("tyre_carcass") or [])
                      if x is not None]
                if tc:
                    warm = (sum(tc) / len(tc)) >= 55.0
            except (TypeError, ValueError):
                warm = None
            if gomme and tt > 0 and new is not None and warm is not None:
                code = "garage_out_%s_%s" % (
                    "new" if new else "used",
                    "warm" if warm else "cold")
                out.append(self.msg(code, gomme=gomme, temp=tt))
            elif gomme and tt > 0:
                grip = self._grip_word(raw)
                if grip:
                    out.append(self.msg("garage_brief", grip=grip,
                                        temp=tt, gomme=gomme))
        return [m for m in out if m]

    def _grip_word(self, raw):
        """Gommatura pista 0-4 -> parola (o None se dato assente)."""
        try:
            g = int(raw.get("track_grip"))
        except (TypeError, ValueError):
            return None
        if not (0 <= g <= 4):
            return None
        return {0: self._L("verde", "green", "verde", "verte"),
                1: self._L("poco gommata", "low on rubber",
                           "con poca goma", "peu gommee"),
                2: self._L("mediamente gommata", "medium rubbered",
                           "con goma media", "moyennement gommee"),
                3: self._L("ben gommata", "well rubbered-in",
                           "bien engomada", "bien gommee"),
                4: self._L("satura di gomma", "saturated with rubber",
                           "saturada de goma", "saturee de gomme")}[g]

    def _tyre_word(self, raw):
        """Gomme montate: nuove o usate al X percento + mescola (o None)."""
        tw = raw.get("tyre_wear")
        c4 = raw.get("tyre_compound4") or []
        comp = ""
        if isinstance(c4, (list, tuple)) and c4:
            s = str(c4[0] or "").upper()[:1]
            comp = {"S": self._L("morbide", "softs", "blandas", "tendres"),
                    "M": self._L("medie", "mediums", "medias", "medium"),
                    "H": self._L("dure", "hards", "duras", "dures"),
                    "W": self._L("da bagnato", "wets", "de lluvia",
                                 "pluie")}.get(s, "")
        if not (isinstance(tw, (list, tuple)) and tw):
            return comp or None
        try:
            worst = min(float(x) for x in tw if x is not None)
        except (TypeError, ValueError):
            return comp or None
        if worst >= 97.0:
            base = self._L("nuove", "fresh", "nuevas", "neuves")
            return ("%s %s" % (base, comp)).strip() if comp else base
        pct = int(round(worst))
        used = self._L("usate al %d percento" % pct,
                       "used, %d percent left" % pct,
                       "usadas al %d por ciento" % pct,
                       "usees a %d pour cent" % pct)
        return ("%s %s" % (comp, used)).strip() if comp else used

    def pit_lane_release(self, raw):
        """USCITA DAL GARAGE (box) IN SICUREZZA. Sei DENTRO il box (garage=True),
        motore acceso, muso verso l'uscita: prima di uscire, se un'auto sta
        percorrendo la CORSIA e ti arriva vicino -> "aspetta"; quando e' libera
        -> "vai". SOLO dal garage (NON l'immissione in pista dalla corsia).
        Dati come la mappa: chi e' nel proprio box e' a parte (garage), chi
        percorre la corsia ha i dot arancioni (in_pits)."""
        raw = raw or {}
        try:
            rpm = float(raw.get("rpm") or 0.0)
        except (TypeError, ValueError):
            rpm = 0.0
        # SOLO dentro il box, motore acceso
        if not raw.get("garage") or rpm < 300.0:
            self._st.pop("pl_state", None)
            self._st.pop("pl_dist", None)
            return []
        tm = raw.get("traffic_map") or {}
        pl = tm.get("player") or {}
        px, pz = pl.get("x"), pl.get("z")
        if px is None or pz is None:
            return []
        prevd = self._st.get("pl_dist") or {}
        curd = {}
        threat = False
        # auto che PERCORRONO la corsia (in_pits, in movimento) vicine a te
        for c in (tm.get("cars") or []):
            if c.get("is_player") or c.get("garage"):
                continue                              # nel proprio box: a parte
            if not (c.get("in_pits") or c.get("in_pitlane")):
                continue                              # solo auto NELLA corsia
            if float(c.get("speed") or 0.0) < 4.0:
                continue                              # ferma: non un rischio
            cx, cz = c.get("x"), c.get("z")
            if cx is None or cz is None:
                continue
            d = ((float(cx) - float(px)) ** 2
                 + (float(cz) - float(pz)) ** 2) ** 0.5
            cid = c.get("id")
            curd[cid] = d
            if d > 200.0:
                continue
            pd = prevd.get(cid)
            if pd is not None and d < pd - 0.15:      # in avvicinamento (conferma)
                threat = True
        self._st["pl_dist"] = curd

        prev = self._st.get("pl_state")
        if threat:
            if prev != "wait":
                self._st["pl_state"] = "wait"
                return [self.msg("pit_release_wait")]
            return []
        if prev == "wait":
            self._st["pl_state"] = "clear"
            return [self.msg("pit_release_clear")]
        self._st["pl_state"] = "clear"
        return []

    def pit_ready(self, raw):
        """Alla TUA chiamata pit (pit_state>=1), dopo ~3s: 'pronti per il pit
        stop'. In tutte le sessioni. Una volta per richiesta, riarma a pit_state 0."""
        raw = raw or {}
        try:
            ps = int(raw.get("pit_state") or 0)
        except (TypeError, ValueError):
            ps = 0
        # SOLO in pista con la RICHIESTA attiva (ps==1). In garage/corsia
        # pit_state risulta >=1 (sei fermo in piazzola!) e diceva "pronti
        # per la sosta" dal garage: nonsense.
        if ps != 1 or raw.get("garage") or raw.get("in_pits") \
                or raw.get("in_pitlane"):
            self._st.pop("pr_t0", None)
            if ps == 0:
                self._st.pop("pr_said", None)      # richiesta chiusa: riarma
            return []
        now = _time.monotonic()
        t0 = self._st.get("pr_t0")
        if t0 is None:
            self._st["pr_t0"] = now
            return []
        if self._st.get("pr_said") or (now - t0) < 3.0:
            return []
        self._st["pr_said"] = True
        return [self.msg("pit_ready")]

    def pit_light(self, raw):
        """SEMAFORO PIT (prova/quali): la corsia box e' CHIUSA finche'
        game_phase == 0; appena passa a > 0 la pit APRE (verde). Fonte: shared
        memory (come TinyPedal: pit_open = mGamePhase > 0). Solo nell'area box,
        motore acceso, e non in gara (li' il via e' un'altra procedura).
        Col rosso, uscire = Stop&Go."""
        raw = raw or {}
        if session_kind(raw.get("session_type")) == "race":
            self._st.pop("pl_light", None)
            return []
        in_area = bool(raw.get("garage") or raw.get("in_pits")
                       or raw.get("in_pitlane"))
        try:
            rpm = float(raw.get("rpm") or 0.0)
        except (TypeError, ValueError):
            rpm = 0.0
        if (not in_area) or rpm < 300.0:
            self._st.pop("pl_light", None)
            return []
        try:
            ph = int(raw.get("game_phase"))
        except (TypeError, ValueError):
            return []
        st = self._st.get("pl_light")
        if ph <= 0:                       # pit CHIUSA (semaforo rosso)
            if st != "closed":
                self._st["pl_light"] = "closed"
                return [self.msg("pit_closed")]
            return []
        if st == "closed":                # era chiusa -> ora VERDE
            self._st["pl_light"] = "open"
            return [self.msg("pit_open")]
        self._st["pl_light"] = "open"     # gia' aperta all'arrivo: muto
        return []

    def _ord_word(self, n):
        """Ordinale a parole nella lingua giusta (1..10), senno' '{n}°'."""
        it = {1: "primo", 2: "secondo", 3: "terzo", 4: "quarto", 5: "quinto",
              6: "sesto", 7: "settimo", 8: "ottavo", 9: "nono", 10: "decimo"}
        en = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth",
              6: "sixth", 7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth"}
        es = {1: "primero", 2: "segundo", 3: "tercero", 4: "cuarto", 5: "quinto",
              6: "sexto", 7: "septimo", 8: "octavo", 9: "noveno", 10: "decimo"}
        fr = {1: "premier", 2: "deuxieme", 3: "troisieme", 4: "quatrieme",
              5: "cinquieme", 6: "sixieme", 7: "septieme", 8: "huitieme",
              9: "neuvieme", 10: "dixieme"}
        return self._L(it.get(n, "%d" % n), en.get(n, "%d" % n),
                       es.get(n, "%d" % n), fr.get(n, "%d" % n))

    def quali_pole(self, raw, laps_done):
        """QUALI (solo info): a fine giro, in base alla CLASSIFICA di classe per
        best lap -> pole (complimenti), oppure top-5 (posizione + gap al rivale
        davanti a te), oppure gap dalla pole. Anti-spam: solo se cambia stato."""
        if session_kind(raw.get("session_type")) != "qualy":
            return []
        if laps_done == self._st.get("qp_lap"):
            return []
        self._st["qp_lap"] = laps_done
        try:
            mine = float(raw.get("best_lap") or 0.0)
        except (TypeError, ValueError):
            return []
        if mine <= 0:
            return []
        my_cls = (class_tag(raw.get("car_class") or "") or self._cat or "").upper()
        field = [(mine, None)]            # (best, nome); nome None = TU
        for c in (raw.get("cars") or {}).values():
            if (class_tag(str(c.get("cls") or "")) or "").upper() != my_cls:
                continue
            try:
                b = float(c.get("best") or -1)
            except (TypeError, ValueError):
                continue
            if b > 0:
                field.append((b, c.get("name")))
        if len(field) < 2:
            return []                     # solo tu con un tempo: niente
        field.sort(key=lambda x: x[0])
        rank = next(i for i, (b, nm) in enumerate(field) if nm is None) + 1
        # POLE
        if rank == 1:
            if self._st.get("qp_state") == ("lead", 0):
                return []
            self._st["qp_state"] = ("lead", 0)
            return [self.msg("quali_pole_lead", mytime=_fmt_lap_round(mine))]
        # TOP-5: posizione + gap al rivale UNA POSIZIONE davanti a te
        if rank <= 5:
            ahead = field[rank - 2]
            g = max(0.0, mine - ahead[0])
            state = ("top5", rank, round(g, 1))
            if state == self._st.get("qp_state"):
                return []
            self._st["qp_state"] = state
            return [self.msg("quali_top5", ord=self._ord_word(rank),
                             gap=("%.3f" % g).replace(".", ","),
                             name=self._rival_name(ahead[1]))]
        # FUORI dai 5: gap dalla pole
        pole = field[0]
        g = mine - pole[0]
        state = ("gap", round(g, 1))
        if state == self._st.get("qp_state"):
            return []
        self._st["qp_state"] = state
        return [self.msg("quali_pole_gap",
                         gap=("%.3f" % g).replace(".", ","),
                         name=self._rival_name(pole[1]),
                         ptime=_fmt_lap_round(pole[0]))]

    def overtake_call(self, raw, laps_done):
        """Complimenti per un SORPASSO fatto: la posizione DI CLASSE migliora
        (non conta doppiati / altre classi). Solo in gara, in pista, dopo il
        via. Tanti modi diversi. Il sorpasso subito non si commenta."""
        if session_kind(raw.get("session_type")) != "race":
            return []
        if laps_done < 1 or raw.get("in_pits") or raw.get("garage"):
            return []
        riv = raw.get("rivals") or {}
        try:
            cp = int(riv.get("class_place"))
        except (TypeError, ValueError):
            return []
        if cp <= 0:
            return []
        prev = self._st.get("ot_place")
        self._st["ot_place"] = cp
        now = _time.monotonic()
        # SOLO 1-vs-1 PULITO: complimenti quando il superato e' ad almeno
        # 1s dietro. In un gruppo la posizione balla -> rischio complimento
        # sbagliato: il guadagno resta in sospeso (15s) finche' il gap non
        # si apre; se la posizione si riperde, si scarta in silenzio.
        if prev is not None and cp < prev:
            self._st["ot_pend"] = {"cp": cp, "t": now}
        pend = self._st.get("ot_pend")
        if not pend:
            return []
        if cp > pend["cp"] or now - pend["t"] > 15.0:
            self._st.pop("ot_pend", None)
            return []
        try:
            gb = float(riv.get("gap_behind"))
        except (TypeError, ValueError):
            return []
        if gb < 1.0:
            return []                       # ancora in lotta/gruppo: aspetta
        self._st.pop("ot_pend", None)
        if now - self._st.get("ot_t", 0.0) < 8.0:
            return []
        self._st["ot_t"] = now
        return [self.msg("overtake_done", pos=cp)]

    def attack_defend_call(self, raw, laps_done):
        """LOTTA A TIRO (gara): davanti sotto il secondo -> "lo stai
        prendendo, prova l'attacco"; dietro sotto il secondo -> "ti
        attacca, difenditi". Una volta per avvicinamento; si riarma
        quando il gap risale sopra 2.5s."""
        raw = raw or {}
        if session_kind(raw.get("session_type")) != "race" \
                or (laps_done or 0) < 1:
            return []
        if raw.get("in_pits") or raw.get("garage"):
            return []
        riv = raw.get("rivals") or {}
        out = []
        try:
            ga = float(riv.get("gap_ahead"))
        except (TypeError, ValueError):
            ga = None
        if ga is None or ga > 2.5:
            self._st.pop("atk_on", None)
        elif ga <= 1.0 and not self._st.get("atk_on"):
            self._st["atk_on"] = True
            nm = self._rival_name(riv.get("name_ahead") or "")
            out.append(self.msg("gap_attack", name=nm) if nm
                       else self.msg("gap_attack_simple"))
        try:
            gb = float(riv.get("gap_behind"))
        except (TypeError, ValueError):
            gb = None
        if gb is None or gb > 2.5:
            self._st.pop("dfd_on", None)
        elif gb <= 1.0 and not self._st.get("dfd_on"):
            self._st["dfd_on"] = True
            nm = self._rival_name(riv.get("name_behind") or "")
            out.append(self.msg("gap_defend", name=nm) if nm
                       else self.msg("gap_defend_simple"))
        return out

    def slide_call(self, raw, laps_done):
        """'STAI SCIVOLANDO': slide laterale SOSTENUTO (slip_lat medio alto
        su piu' letture consecutive), non il singolo scodata. Un avviso,
        poi 60s di silenzio. Muto sul bagnato (li' scivolare e' normale
        e ci pensano i moduli pioggia)."""
        raw = raw or {}
        try:
            if float(raw.get("raining") or 0.0) >= 0.15 \
                    or self._wet_mounted(raw):
                self._st["slide_n"] = 0
                return []
            spd = float(raw.get("speed") or 0.0)
        except (TypeError, ValueError):
            return []
        sl = raw.get("slip_lat")
        if not isinstance(sl, (list, tuple)) or len(sl) < 4 or spd < 45.0:
            self._st["slide_n"] = 0
            return []
        try:
            m = sum(abs(float(x or 0.0)) for x in sl) / len(sl)
        except (TypeError, ValueError):
            return []
        if m >= 3.5:
            self._st["slide_n"] = self._st.get("slide_n", 0) + 1
        else:
            self._st["slide_n"] = 0
        now = _time.monotonic()
        if self._st.get("slide_n", 0) >= 5 \
                and now - self._st.get("slide_t", 0.0) > 60.0:
            self._st["slide_t"] = now
            self._st["slide_n"] = 0
            return [self.msg("car_sliding")]
        return []

    def stopped_check_call(self, raw, laps_done):
        """FERMO IN PISTA (>=5s, non box, non pre-via): il muretto
        controlla — motore spento? danni? — e conferma la ripartenza.
        + SPIA MOTORE (mOverheating, quella vera di LMU): sostenuta 3s
        -> avviso critico (dopo la spia il motore puo' MORIRE)."""
        raw = raw or {}
        try:
            spd = float(raw.get("speed") or 0.0)
            rpm = float(raw.get("rpm") or 0.0)
            ph = int(raw.get("game_phase") or 0)
        except (TypeError, ValueError):
            return []
        _race = session_kind(raw.get("session_type")) == "race"
        in_box = bool(raw.get("garage") or raw.get("in_pits")
                      or raw.get("in_pitlane"))
        now = _time.monotonic()
        out = []
        # ── SPIA MOTORE ──
        if bool(raw.get("overheating")) and not in_box:
            t0 = self._st.get("ov_t0")
            if t0 is None:
                self._st["ov_t0"] = now
            elif now - t0 >= 3.0 \
                    and now - self._st.get("ov_said_t", 0.0) > 45.0:
                self._st["ov_said_t"] = now
                out.append(self.msg("engine_over"))
        else:
            self._st.pop("ov_t0", None)
        # ── RIPARTENZA dopo stallo ──
        if self._st.get("stall_said") and rpm > 3000.0:
            self._st.pop("stall_said", None)
            out.append(self.msg("engine_restart"))
        # ── FERMO IN PISTA ──
        if in_box or (_race and ph in (1, 2, 3, 4)):
            self._st.pop("stop_t0", None)
            self._st.pop("stop_said", None)
            return out
        if spd < 1.0:
            t0 = self._st.get("stop_t0")
            if t0 is None:
                self._st["stop_t0"] = now
            elif now - t0 >= 5.0 and not self._st.get("stop_said"):
                self._st["stop_said"] = True
                if rpm < 200.0:
                    self._st["stall_said"] = True
                    out.append(self.msg("engine_stall"))
                else:
                    dmg = False
                    try:
                        a = float(raw.get("aero") or 0.0)
                        su = raw.get("susp") or []
                        dmg = a >= 0.05 or any(
                            float(x or 0.0) >= 0.10
                            for x in list(su)[:4])
                    except (TypeError, ValueError):
                        dmg = False
                    out.append(self.msg("stopped_check_dmg" if dmg
                                        else "stopped_check"))
        elif spd > 5.0:
            self._st.pop("stop_t0", None)
            self._st.pop("stop_said", None)
        return out

    def outlap_tech_call(self, raw, laps_done):
        """OUT-LAP TECNICO PER CLASSE (prova E GARA, rich. 23/07: "in
        gara mi manca l'informazione della pratica"): all'uscita dai box
        la procedura vera da muretto — GT3 dischi in acciaio, Hypercar
        carbonio + gestione SOC, P2/P3 carbonio e gomma che vuole due
        giri. Una volta per stint (in gara = dopo ogni sosta)."""
        raw = raw or {}
        if session_kind(raw.get("session_type")) not in ("practice",
                                                         "race"):
            return []
        in_box = bool(raw.get("garage") or raw.get("in_pits")
                      or raw.get("in_pitlane"))
        if in_box:
            self._st["ol_armed"] = True      # prossima uscita = out-lap
            return []
        if not self._st.get("ol_armed"):
            return []
        try:
            spd = float(raw.get("speed") or 0.0)
        except (TypeError, ValueError):
            return []
        if spd < 30.0:
            return []
        self._st["ol_armed"] = False
        tag = class_tag(raw.get("car_class") or "")
        code = {"GT3": "outlap_gt3", "GTE": "outlap_gt3",
                "HY": "outlap_hy", "P2": "outlap_p2",
                "P3": "outlap_p3"}.get(tag)
        return [self.msg(code)] if code else []

    def stint_findings_call(self, raw, laps_done):
        """ANALISI STINT (docs/ingegneria_telemetria.md): in pista campiona
        il bilancio sotto/sovrasterzo PER CURVA e l'usura per ruota; al
        rientro in garage dice i FINDINGS tecnici da ingegnere:
        "in curva 2 c'è troppo sottosterzo", "abbiamo consumato soprattutto
        la posteriore destra". + FLAT SPOT confermato dal gioco (mFlat)."""
        raw = raw or {}
        st = self._st
        out = []
        # FLAT SPOT dal gioco (conferma vera, non inferenza)
        wf = raw.get("wheel_flat")
        if isinstance(wf, (list, tuple)) and len(wf) >= 4:
            W = (self._L("anteriore sinistra", "front left",
                         "delantera izquierda", "avant gauche"),
                 self._L("anteriore destra", "front right",
                         "delantera derecha", "avant droite"),
                 self._L("posteriore sinistra", "rear left",
                         "trasera izquierda", "arriere gauche"),
                 self._L("posteriore destra", "rear right",
                         "trasera derecha", "arriere droite"))
            fsaid = st.setdefault("flat_conf", set())
            for i in range(4):
                if bool(wf[i]) and i not in fsaid:
                    fsaid.add(i)
                    out.append(self.msg("flatspot_confirmed", ruota=W[i]))
                elif not wf[i]:
                    fsaid.discard(i)
        in_box = bool(raw.get("garage") or raw.get("in_pits")
                      or raw.get("in_pitlane"))
        if not in_box:
            try:
                spd = float(raw.get("speed") or 0.0)
                ld = float(raw.get("lapdist") or -1.0)
            except (TypeError, ValueError):
                return out
            if spd < 40.0 or ld < 0:
                return out
            st["an_on"] = True
            if "an_w0" not in st:
                tw = raw.get("tyre_wear")
                if isinstance(tw, (list, tuple)) and len(tw) >= 4:
                    try:
                        st["an_w0"] = [float(x) for x in tw[:4]]
                    except (TypeError, ValueError):
                        pass
            sl = raw.get("slip_lat")
            if isinstance(sl, (list, tuple)) and len(sl) >= 4:
                try:
                    fa = (abs(float(sl[0] or 0))
                          + abs(float(sl[1] or 0))) / 2.0
                    ra = (abs(float(sl[2] or 0))
                          + abs(float(sl[3] or 0))) / 2.0
                except (TypeError, ValueError):
                    return out
                if fa > 0.4 or ra > 0.4:
                    near, ndd = None, 70.0
                    for c in self._learned_corners(raw):
                        try:
                            cd = float(c.get("d"))
                        except (TypeError, ValueError):
                            continue
                        if c.get("n") is None:
                            continue
                        gap = abs(cd - ld)
                        if gap < ndd:
                            near, ndd = c.get("n"), gap
                    if near is not None:
                        acc = st.setdefault("an_c", {}) \
                            .setdefault(near, [0.0, 0.0, 0])
                        acc[0] += fa
                        acc[1] += ra
                        acc[2] += 1
                        # slip PER RUOTA per curva: per attribuire l'usura
                        # ("consumi la posteriore destra all'uscita di 9")
                        try:
                            wc = st.setdefault("an_wc", {}) \
                                .setdefault(near, [0.0, 0.0, 0.0, 0.0])
                            for _wi in range(4):
                                wc[_wi] += abs(float(sl[_wi] or 0.0))
                        except (TypeError, ValueError):
                            pass
                # 3 ZONE gomma (strato interno) in appoggio: per camber
                # e pressioni a fine stint (docs/ingegneria 2.1-2.2)
                if fa > 0.4 or ra > 0.4:
                    tin = raw.get("tyre_inner") or []
                    if len(tin) >= 4:
                        tz = st.setdefault("an_t",
                                           [[0.0, 0.0, 0.0, 0]
                                            for _ in range(4)])
                        for wi in range(4):
                            z = tin[wi]
                            if isinstance(z, (list, tuple)) and len(z) >= 3:
                                try:
                                    tz[wi][0] += float(z[0] or 0.0)
                                    tz[wi][1] += float(z[1] or 0.0)
                                    tz[wi][2] += float(z[2] or 0.0)
                                    tz[wi][3] += 1
                                except (TypeError, ValueError):
                                    pass
            # FRENI per assale in staccata (squilibrio bias/ducts) +
            # SURRISCALDO attribuito alla STACCATA (curva davanti <250m)
            try:
                if float(raw.get("brake") or 0.0) > 0.4:
                    bk = raw.get("brake_temp") or []
                    if len(bk) >= 4:
                        ab = st.setdefault("an_bk", [0.0, 0.0, 0])
                        ab[0] += (float(bk[0] or 0) + float(bk[1] or 0)) / 2.0
                        ab[1] += (float(bk[2] or 0) + float(bk[3] or 0)) / 2.0
                        ab[2] += 1
                        _gt = class_tag(raw.get("car_class") or "") \
                            in ("GT3", "GTE")
                        _lim = 650.0 if _gt else 750.0
                        if max(float(x or 0) for x in bk[:4]) > _lim:
                            for c in self._learned_corners(raw):
                                try:
                                    cd = float(c.get("d"))
                                except (TypeError, ValueError):
                                    continue
                                if c.get("n") is not None \
                                        and 0.0 <= cd - ld <= 250.0:
                                    bc = st.setdefault("an_bkc", {})
                                    bc[c["n"]] = bc.get(c["n"], 0) + 1
                                    break
            except (TypeError, ValueError):
                pass
            # BOTTOMING: ride height a terra in velocita'
            try:
                rh = raw.get("ride_h") or []
                if spd > 90.0 and any(
                        x is not None and float(x) < 2.0 for x in rh[:4]):
                    st["an_bot"] = st.get("an_bot", 0) + 1
            except (TypeError, ValueError):
                pass
            # BILANCIO AERO nei tratti veloci
            try:
                dff = float(raw.get("df_front") or 0.0)
                dfr = float(raw.get("df_rear") or 0.0)
                if spd > 150.0 and (dff + dfr) > 500.0:
                    ad = st.setdefault("an_df", [0.0, 0])
                    ad[0] += dff / (dff + dfr)
                    ad[1] += 1
            except (TypeError, ValueError, ZeroDivisionError):
                pass
            return out
        # ── IN GARAGE: findings, una volta per stint analizzato ──
        if not st.pop("an_on", None):
            return out
        data = st.pop("an_c", {}) or {}
        cand = []
        for n, (fs, rs, c) in data.items():
            if c < 8:
                continue
            fm, rm = fs / c, rs / c
            if fm >= 0.8 and rm > 0.05 and fm / rm >= 1.4:
                cand.append((fm / rm, n, "u"))
            elif rm >= 0.8 and fm > 0.05 and rm / fm >= 1.4:
                cand.append((rm / fm, n, "o"))
        if cand:
            cand.sort(reverse=True)
            _, n, kind = cand[0]
            out.append(self.msg("debrief_balance_us" if kind == "u"
                                else "debrief_balance_os", turn=n))
        w0 = st.pop("an_w0", None)
        tw = raw.get("tyre_wear")
        if w0 and isinstance(tw, (list, tuple)) and len(tw) >= 4:
            try:
                dw = [max(0.0, w0[i] - float(tw[i])) for i in range(4)]
            except (TypeError, ValueError):
                dw = None
            if dw and max(dw) > 0.8 \
                    and max(dw) - min(dw) >= 0.35 * max(dw):
                W = (self._L("anteriore sinistra", "front left",
                             "delantera izquierda", "avant gauche"),
                     self._L("anteriore destra", "front right",
                             "delantera derecha", "avant droite"),
                     self._L("posteriore sinistra", "rear left",
                             "trasera izquierda", "arriere gauche"),
                     self._L("posteriore destra", "rear right",
                             "trasera derecha", "arriere droite"))
                mi = max(range(4), key=lambda i: dw[i])
                # ATTRIBUZIONE: la curva dove QUELLA ruota slitta di piu'
                wc = st.pop("an_wc", {}) or {}
                topn, tops = None, 0.0
                for n2, ws in wc.items():
                    try:
                        if ws[mi] > tops and ws[mi] >= 25.0:
                            topn, tops = n2, ws[mi]
                    except (TypeError, IndexError):
                        continue
                if topn is not None:
                    out.append(self.msg("debrief_wear_wheel_corner",
                                        ruota=W[mi], turn=topn))
                else:
                    out.append(self.msg("debrief_wear_wheel", ruota=W[mi]))
        # ── INGEGNERIA v2: pressioni/camber (3 zone), freni, fondo, aero ──
        extras = []
        _AX = (self._L("anteriore", "front", "delantero", "avant"),
               self._L("posteriore", "rear", "trasero", "arriere"))
        tz = st.pop("an_t", None)
        if tz:
            zm = []
            for wi in range(4):
                s0, s1, s2, c = tz[wi]
                zm.append(None if c < 20 else (s0 / c, s1 / c, s2 / c))
            # indice zona INTERNA (verso l'auto): sx=2 per ruote sinistre
            _IN = (2, 0, 2, 0)
            for ax, wids in ((0, (0, 1)), (1, (2, 3))):
                zz = [zm[w] for w in wids if zm[w]]
                if len(zz) < 2:
                    continue
                crown = sum(z[1] - (z[0] + z[2]) / 2.0 for z in zz) / 2.0
                spread = sum(zm[w][_IN[w]] - zm[w][2 - _IN[w]]
                             for w in wids if zm[w]) / 2.0
                if crown > 5.0:
                    extras.append(self.msg("debrief_press_hi", asse=_AX[ax]))
                elif crown < -5.0:
                    extras.append(self.msg("debrief_press_lo", asse=_AX[ax]))
                elif spread > 12.0:
                    extras.append(self.msg("debrief_camber_much",
                                           asse=_AX[ax]))
                elif spread < 2.0:
                    extras.append(self.msg("debrief_camber_little",
                                           asse=_AX[ax]))
        st.pop("an_wc", None)
        bc = st.pop("an_bkc", None) or {}
        if bc:
            nb = max(bc, key=bc.get)
            if bc[nb] >= 3:
                extras.append(self.msg("debrief_brake_corner", turn=nb))
        ab = st.pop("an_bk", None)
        if ab and ab[2] >= 20:
            d = ab[0] / ab[2] - ab[1] / ab[2]
            if d > 150.0:
                extras.append(self.msg("debrief_brake_front"))
            elif d < -150.0:
                extras.append(self.msg("debrief_brake_rear"))
        if st.pop("an_bot", 0) >= 5:
            extras.append(self.msg("debrief_bottoming"))
        ad = st.pop("an_df", None)
        if ad and ad[1] >= 20:
            extras.append(self.msg("debrief_aero_bal",
                                   pct=int(round(100.0 * ad[0] / ad[1]))))
        # tetto: massimo 3 findings totali (il muretto non fa la lista spesa)
        room = max(0, 3 - len(out))
        out.extend([m for m in extras if m][:room])
        return out

    def corner_coach_call(self, raw, laps_done):
        """COACH PER CURVA (solo PROVA, pista appresa):
        - STACCATE: confronta il tuo punto di frenata col riferimento
          appreso (brake_d per curva). Se stacchi >=15m PRIMA del tuo
          best per 2 volte nella stessa curva -> "puoi frenare più tardi
          in curva X di N metri". Una volta per curva a sessione.
        - PATTINAMENTO: slide posteriore col gas aperto in uscita curva
          ripetuto -> "dosa il gas in uscita dalla curva X"."""
        raw = raw or {}
        if session_kind(raw.get("session_type")) != "practice":
            return []
        corners = self._learned_corners(raw)
        if not corners:
            return []
        out = []
        # ── STACCATE vs riferimento ──
        evs = raw.get("brake_events") or []
        last_t = self._st.get("cc_t", 0.0)
        said = self._st.setdefault("cc_said", set())
        cnt = self._st.setdefault("cc_cnt", {})
        for ev in evs:
            try:
                t, ld = float(ev[0]), float(ev[1])
            except (TypeError, ValueError, IndexError):
                continue
            if t <= last_t:
                continue
            self._st["cc_t"] = t
            best, bd = None, 1e9
            for c in corners:
                try:
                    cd = float(c.get("d")); bk = float(c.get("brake_d") or 0)
                except (TypeError, ValueError):
                    continue
                if bk <= 0 or c.get("n") is None:
                    continue
                ref = cd - bk               # dove stacca il tuo best
                gap = ld - ref
                if -120.0 <= gap <= 120.0 and abs(gap) < abs(bd):
                    best, bd = c, gap
            if best is None:
                continue
            n = best.get("n")
            if bd <= -15.0 and n not in said:
                cnt[n] = cnt.get(n, 0) + 1
                if cnt[n] >= 2:
                    said.add(n)
                    out.append(self.msg("brake_later", turn=n,
                                        meters=int(round(-bd / 5.0) * 5)))
            elif bd >= 12.0 and n not in said:
                # stacchi PIU' TARDI del tuo best E in quella zona blocchi:
                # stai overdriving la staccata -> frena prima
                try:
                    _cd = float(best.get("d"))
                    _bk2 = float(best.get("brake_d") or 0.0)
                except (TypeError, ValueError):
                    _cd = _bk2 = 0.0
                _locked = any(
                    isinstance(le, (list, tuple)) and le
                    and (_cd - _bk2 - 120.0) <= float(le[0]) <= _cd
                    for le in (raw.get("lock_events") or []))
                if _locked:
                    c2 = self._st.setdefault("cc2", {})
                    c2[n] = c2.get(n, 0) + 1
                    if c2[n] >= 2:
                        said.add(n)
                        out.append(self.msg("brake_earlier", turn=n,
                                            meters=int(round(bd / 5.0) * 5)))
        # ── COASTING per curva (Bentley "lazy throttle"): tempo morto
        # tra rilascio freno e prima apertura gas > 0.45s, 2 volte nella
        # stessa curva -> "raccorda freno e gas in curva X" ──
        try:
            _b = float(raw.get("brake") or 0.0)
            _th = float(raw.get("throttle") or 0.0)
            _ld2 = float(raw.get("lapdist") or -1.0)
        except (TypeError, ValueError):
            _b = _th = 0.0; _ld2 = -1.0
        _nowc = _time.monotonic()
        _bprev = self._st.get("co_b", 0.0)
        _tprev = self._st.get("co_t", 0.0)
        self._st["co_b"] = _b
        self._st["co_t"] = _th
        if _bprev > 0.3 and _b < 0.1 and _th < 0.2:
            self._st["co_off_t"] = _nowc          # freno mollato, gas chiuso
            self._st["co_off_d"] = _ld2
        if _th > 0.2 and _tprev <= 0.2 and "co_off_t" in self._st:
            _dt = _nowc - self._st.pop("co_off_t")
            _od = self._st.pop("co_off_d", -1.0)
            if _dt > 0.45 and _od >= 0:
                _cn, _cd = None, 150.0
                for c in corners:
                    try:
                        _g = abs(float(c.get("d")) - _od)
                    except (TypeError, ValueError):
                        continue
                    if c.get("n") is not None and _g < _cd:
                        _cn, _cd = c.get("n"), _g
                if _cn is not None:
                    _cs = self._st.setdefault("co_cnt", {})
                    _csaid = self._st.setdefault("co_said", set())
                    _cs[_cn] = _cs.get(_cn, 0) + 1
                    if _cs[_cn] >= 2 and _cn not in _csaid:
                        _csaid.add(_cn)
                        out.append(self.msg("coast_corner", turn=_cn))
        # ── PATTINAMENTO in uscita ──
        try:
            thr = float(raw.get("throttle") or 0.0)
            sl = raw.get("slip_lat") or []
            spd = float(raw.get("speed") or 0.0)
            ld = float(raw.get("lapdist") or -1.0)
            rear = (abs(float(sl[2] or 0)) + abs(float(sl[3] or 0))) / 2.0 \
                if len(sl) >= 4 else 0.0
        except (TypeError, ValueError):
            return out
        if thr > 0.7 and rear >= 2.0 and 30.0 < spd < 160.0 and ld >= 0:
            wsc = self._st.setdefault("ws_cnt", {})
            wsaid = self._st.setdefault("ws_said", set())
            for c in corners:
                try:
                    cd = float(c.get("d"))
                except (TypeError, ValueError):
                    continue
                n = c.get("n")
                if n is None or n in wsaid:
                    continue
                if cd <= ld <= cd + 200.0:
                    wsc[n] = wsc.get(n, 0) + 1
                    if wsc[n] >= 3:
                        wsaid.add(n)
                        out.append(self.msg("wheelspin", turn=n))
                    break
        return out

    def kerb_call(self, raw, laps_done):
        """CORDOLI VIOLENTI: colpi secchi ripetuti nella stessa zona (dal
        rilevatore 5Hz: ruota sul cordolo + botta di sospensione). Avviso
        tecnico: scomponi la macchina e stressi le sospensioni. Cluster
        +-60m, >=3 colpi, una zona per sessione."""
        raw = raw or {}
        evs = raw.get("kerb_events") or []
        if len(evs) < 3:
            return []
        pts = []
        for e in evs:
            try:
                pts.append(float(e))
            except (TypeError, ValueError):
                continue
        pts.sort()
        clusters = []
        for ld in pts:
            if clusters and abs(ld - clusters[-1]["d"]) <= 60.0:
                c = clusters[-1]
                c["d"] = (c["d"] * c["n"] + ld) / (c["n"] + 1)
                c["n"] += 1
            else:
                clusters.append({"d": ld, "n": 1})
        said = self._st.setdefault("kerb_zones", set())
        corners = self._learned_corners(raw)
        for c in clusters:
            if c["n"] < 3:
                continue
            zid = int(c["d"] // 120)
            if zid in said:
                continue
            said.add(zid)
            cn = self._corner_name(corners, c["d"])
            if cn:
                return [self.msg("kerb_zone_corner", n=cn)]
            return [self.msg("kerb_zone")]
        return []

    def setup_coach(self, raw, laps_done):
        """SOLO PROVA: consigli d'ASSETTO dalla telemetria dei giri —
        pressioni sotto la finestra vera (docs/dati_lmu.md), squilibrio
        termico tra assali (sottosterzo/sovrasterzo in arrivo), gomma
        singola troppo calda. Un consiglio ogni 4 giri, mai in gara
        (li' si toccano solo elettronica e bias, gia' coperti)."""
        raw = raw or {}
        if session_kind(raw.get("session_type")) != "practice":
            return []
        # CAMPIONA sempre l'equilibrio di slide davanti/dietro (in curva):
        # e' la base del giudizio "fai fatica a inserire" (sottosterzo)
        # vs "il posteriore scappa" (sovrasterzo).
        sl = raw.get("slip_lat")
        try:
            spd = float(raw.get("speed") or 0.0)
        except (TypeError, ValueError):
            spd = 0.0
        if isinstance(sl, (list, tuple)) and len(sl) >= 4 and spd > 15.0 \
                and not raw.get("in_pits") and not raw.get("garage"):
            try:
                fa_s = (abs(float(sl[0] or 0)) + abs(float(sl[1] or 0))) / 2.0
                ra_s = (abs(float(sl[2] or 0)) + abs(float(sl[3] or 0))) / 2.0
                if fa_s > 0.4 or ra_s > 0.4:          # solo in appoggio
                    self._st["sc_fa"] = self._st.get("sc_fa", 0.0) + fa_s
                    self._st["sc_ra"] = self._st.get("sc_ra", 0.0) + ra_s
                    self._st["sc_ns"] = self._st.get("sc_ns", 0) + 1
            except (TypeError, ValueError):
                pass
        if (laps_done or 0) < 4 or raw.get("in_pits") or raw.get("garage"):
            return []
        if laps_done - self._st.get("sc_lap", -9) < 4:
            return []
        W = (self._L("anteriore sinistra", "front left",
                     "delantera izquierda", "avant gauche"),
             self._L("anteriore destra", "front right",
                     "delantera derecha", "avant droite"),
             self._L("posteriore sinistra", "rear left",
                     "trasera izquierda", "arriere gauche"),
             self._L("posteriore destra", "rear right",
                     "trasera derecha", "arriere droite"))
        # pressione minima A CALDO (kPa) dalle finestre vere per classe
        gt = class_tag(raw.get("car_class") or "") in ("GT3", "GTE")
        pmin = 190.0 if gt else 180.0
        try:
            plist = [float(x or 0.0) for x in (raw.get("tyre_press")
                                               or [])[:4]]
        except (TypeError, ValueError):
            plist = []
        for i, p in enumerate(plist):
            if 50.0 < p < pmin:
                self._st["sc_lap"] = laps_done
                return [self.msg("tyre_press_lo", tyre=W[i])]
        ti = []
        for x in (raw.get("tyre_inner") or [])[:4]:
            try:
                # ogni ruota = [3 zone]: media; retrocompatibile col singolo
                if isinstance(x, (list, tuple)):
                    ti.append(sum(float(v or 0.0) for v in x) / len(x))
                else:
                    ti.append(float(x or 0.0))
            except (TypeError, ValueError, ZeroDivisionError):
                ti = []
                break
        if len(ti) == 4 and all(t > 30.0 for t in ti):
            fa = (ti[0] + ti[1]) / 2.0
            ra = (ti[2] + ti[3]) / 2.0
            d = fa - ra
            if abs(d) >= 8.0:
                self._st["sc_lap"] = laps_done
                return [self.msg("tyres_axle_front" if d > 0
                                 else "tyres_axle_rear",
                                 d=int(round(abs(d))))]
            mx = max(range(4), key=lambda k: ti[k])
            if ti[mx] - min(ti) >= 12.0:
                self._st["sc_lap"] = laps_done
                return [self.msg("tyre_imbalance", tyre=W[mx])]
        # EQUILIBRIO INSERIMENTO dai campioni di slide (40+ letture):
        # davanti che scivola molto piu' del dietro = sottosterzo (fai
        # fatica a inserire) -> consiglio d'assetto; viceversa sovrasterzo.
        ns = self._st.get("sc_ns", 0)
        if ns >= 40:
            fa_m = self._st.pop("sc_fa", 0.0) / ns
            ra_m = self._st.pop("sc_ra", 0.0) / ns
            self._st["sc_ns"] = 0
            if fa_m > ra_m * 1.5 and fa_m >= 0.8:
                self._st["sc_lap"] = laps_done
                return [self.msg("setup_understeer")]
            if ra_m > fa_m * 1.5 and ra_m >= 0.8:
                self._st["sc_lap"] = laps_done
                return [self.msg("setup_oversteer")]
        return []

    def stint_debrief(self, raw, laps_done):
        """DEBRIEF di stint (a voce, in garage a fine stint): giri, miglior giro,
        gomme a fine stint, consumo a giro, e dove migliorare. Accumula mentre
        giri; quando ti fermi in box con >=2 giri fatti, lo dice. Poi ri-arma."""
        raw = raw or {}
        in_box = bool(raw.get("garage") or raw.get("in_pits")
                      or raw.get("in_pitlane"))
        try:
            spd = float(raw.get("speed") or 0.0)
        except (TypeError, ValueError):
            spd = 0.0
        d = self._st.setdefault("dbr", {})
        # ── ACCUMULA in pista (non in box) ──
        if not in_box:
            d["active"] = True
            if d.get("lap_start") is None:
                d["lap_start"] = laps_done
            d["laps"] = max(0, laps_done - d["lap_start"])
            try:
                ll = float(raw.get("last_lap") or 0.0)
            except (TypeError, ValueError):
                ll = 0.0
            if ll > 0 and (d.get("best") is None or ll < d["best"]):
                d["best"] = ll
            # migliori settori dello stint (last_s1/last_s2 cumulativi + giro)
            try:
                _s1 = float(raw.get("last_s1") or 0.0)
                _s2c = float(raw.get("last_s2") or 0.0)
                if _s1 > 0 and _s2c > _s1 and ll > _s2c:
                    _secs = [_s1, _s2c - _s1, ll - _s2c]
                    _bs = d.get("bs") or [None, None, None]
                    for _i in range(3):
                        if _bs[_i] is None or _secs[_i] < _bs[_i]:
                            _bs[_i] = _secs[_i]
                    d["bs"] = _bs
            except (TypeError, ValueError):
                pass
            tw = raw.get("tyre_wear")
            if isinstance(tw, (list, tuple)) and tw:
                try:
                    d["wear"] = min(float(x) for x in tw if x is not None)
                except (TypeError, ValueError):
                    pass
            live = raw.get("lmu_live") or {}
            if live.get("per_lap"):
                d["per_lap"] = live.get("per_lap")
                d["constraint"] = live.get("constraint")
            return []
        # ── IN BOX: debrief se avevi uno stint vero (>=2 giri) e sei fermo ──
        if not d.get("active") or d.get("laps", 0) < 2 or spd > 5.0:
            if d.get("laps", 0) < 2:
                d["active"] = False
            return []
        d["active"] = False
        out = []
        if d.get("best"):
            out.append(self.msg("debrief_stint", laps=int(d["laps"]),
                                best=_fmt_lap_round(d["best"])))
        _bs = d.get("bs")
        if _bs and all(x is not None for x in _bs):
            out.append(self.msg("debrief_sectors",
                                s1=_fmt_lap_round(_bs[0]),
                                s2=_fmt_lap_round(_bs[1]),
                                s3=_fmt_lap_round(_bs[2])))
        if d.get("wear") is not None:
            cons = ""
            if d.get("per_lap"):
                unit = (self._L("per cento", "percent", "por ciento", "pour cent")
                        if str(d.get("constraint")).upper() == "ENERGY"
                        else self._L("litri", "liters", "litros", "litres"))
                val = ("%.1f " % float(d["per_lap"])).replace(".", ",") + unit
                cons = self._L("Consumo %s a giro." % val,
                               "Used %s per lap." % val,
                               "Consumo %s por vuelta." % val,
                               "Conso %s au tour." % val)
            out.append(self.msg("debrief_tyre",
                                wear=int(round(d["wear"])), cons=cons))
        cn = self._st.get("dbr_corner")
        if cn:
            out.append(self.msg("debrief_improve", turn=cn))
        self._st["dbr"] = {}                    # ri-arma per il prossimo stint
        self._st.pop("dbr_corner", None)
        return [m for m in out if m]

    def tyre_stock(self, raw):
        """INVENTARIO GOMME (una volta): treni slick nuovi/usati rimasti. Detto
        in box (garage/corsia), utile prima di uscire. Dato REST dotazione."""
        if self._st.get("ts_said"):
            return []
        if not (raw.get("garage") or raw.get("in_pits")
                or raw.get("in_pitlane")):
            return []
        inv = raw.get("tyre_inventory") or {}
        try:
            new = int(inv.get("slick_new"))
            used = int(inv.get("slick_used"))
        except (TypeError, ValueError):
            return []
        if new + used <= 0:
            return []
        self._st["ts_said"] = True
        return [self.msg("tyre_stock", new=new, used=used)]

    def wet_sector_map(self, raw, laps_done):
        """MAPPA BAGNATO PER SETTORE: accumula asciutto/bagnato (surface_type)
        per settore mentre giri; a fine giro, se un settore e' nettamente piu'
        bagnato degli altri, te lo dice. (v2)"""
        raw = raw or {}
        # PISTA ASCIUTTA E NIENTE PIOGGIA: la mappa NON parla (i codici
        # superficie da soli davano "settore piu' bagnato" sull'asciutto)
        try:
            if float(raw.get("raining") or 0.0) < 0.05 \
                    and float(raw.get("wetness") or 0.0) < 0.10:
                self._sec_wet = [[0, 0], [0, 0], [0, 0]]
                return []
        except (TypeError, ValueError):
            return []
        sw = getattr(self, "_sec_wet", None)
        if not isinstance(sw, list):
            sw = self._sec_wet = [[0, 0], [0, 0], [0, 0]]
        st = raw.get("surface_type") or []
        valid = [s for s in st if s in (0, 1)]
        try:
            sec = int(raw.get("sector"))
        except (TypeError, ValueError):
            sec = None
        if valid and sec in (0, 1, 2):
            sw[sec][0] += sum(1 for s in valid if s == 1)
            sw[sec][1] += len(valid)
        if laps_done == getattr(self, "_secmap_lap", None):
            return []
        prev = getattr(self, "_secmap_lap", None)
        self._secmap_lap = laps_done
        if prev is None:
            return []
        fr = [(w / n) if n > 0 else None for w, n in sw]
        self._sec_wet = [[0, 0], [0, 0], [0, 0]]      # azzera per il giro nuovo
        known = [(i, f) for i, f in enumerate(fr) if f is not None]
        if len(known) < 2:
            return []
        wettest = max(known, key=lambda x: x[1])
        driest = min(known, key=lambda x: x[1])
        if wettest[1] >= 0.30 and (wettest[1] - driest[1]) >= 0.35:
            if getattr(self, "_secmap_rep", None) != wettest[0]:
                self._secmap_rep = wettest[0]
                return [self.msg("wet_sector", settore=wettest[0] + 1)]
        elif wettest[1] < 0.15:
            self._secmap_rep = None                   # tutto asciutto: riarma
        return []

    def _learned_corners(self, raw):
        """Curve apprese per questa pista/classe (dal profilo learn):
        [{d: metri, n: numero}]. Cache di sessione, [] se non c'e'."""
        key = (raw.get("track"), raw.get("car_class"))
        if self._st.get("lc_key") == key:
            return self._st.get("lc_corners") or []
        corners = []
        try:
            from core.engineer_learn import load as _learn_load
            prof = _learn_load(raw.get("track") or "",
                               class_tag(raw.get("car_class") or "")) or {}
            wet = False
            try:
                wet = float(raw.get("wetness") or 0.0) > 0.25
            except (TypeError, ValueError):
                pass
            cond = (prof.get("cond") or {}).get("wet" if wet else "dry") or {}
            corners = cond.get("corners") or []
            if not corners:
                # la geometria non cambia con la pioggia: se solo
                # l'altra condizione ha curve apprese, valgono quelle
                other = prof.get("dry" if wet else "wet") or {}
                corners = other.get("corners") or []
        except Exception:
            corners = []
        self._st["lc_key"] = key
        self._st["lc_corners"] = corners
        return corners

    @staticmethod
    def _corner_name(corners, d):
        """Numero della curva agganciata alla staccata in d: l'apex sta
        A VALLE del punto di frenata (fino a 250m), tolleranza 60m a
        monte. None se nessuna curva appresa li' vicino."""
        best, bd = None, 1e9
        for k in corners or []:
            try:
                gap = float(k.get("d")) - float(d)
            except (TypeError, ValueError):
                continue
            if -60.0 <= gap <= 250.0 and abs(gap) < bd:
                best, bd = k.get("n"), abs(gap)
        return best

    def lock_pattern_call(self, raw, laps_done):
        """Coach bloccaggi: cluster +-80m, >=3 eventi = zona (col NOME
        della curva se appresa, entro 150m); bias ruota >=60% su 5+
        eventi. Una zona per giro, senza ripetersi."""
        raw = raw or {}
        evs = raw.get("lock_events") or []
        if len(evs) < 3:
            return []
        out = []
        pts = []
        for e in evs:
            try:
                pts.append((float(e[0]), int(e[1])))
            except (TypeError, ValueError, IndexError):
                continue
        pts.sort()
        clusters = []
        for ld, wi in pts:
            if clusters and abs(ld - clusters[-1]["d"]) <= 80.0:
                c = clusters[-1]
                c["d"] = (c["d"] * c["n"] + ld) / (c["n"] + 1)
                c["n"] += 1
                c["w"][wi] = c["w"].get(wi, 0) + 1
            else:
                clusters.append({"d": ld, "n": 1, "w": {wi: 1}})
        said = self._st.setdefault("lock_zones", set())
        dwn = (self._L("anteriore sinistra", "front left", None, None),
               self._L("anteriore destra", "front right", None, None),
               self._L("posteriore sinistra", "rear left", None, None),
               self._L("posteriore destra", "rear right", None, None))
        corners = self._learned_corners(raw)
        for c in clusters:
            if c["n"] < 3:
                continue
            zid = int(c["d"] // 120)
            if zid in said:
                continue
            said.add(zid)
            wi = max(c["w"], key=c["w"].get)
            # NUMERO della curva se appresa (apex a valle della staccata)
            cn = self._corner_name(corners, c["d"])
            if cn:
                out.append(self.msg("lock_zone_corner", gomma=dwn[wi % 4],
                                    n=cn))
            else:
                # niente numero curva appreso: NIENTE metri/km a voce,
                # solo il consiglio sulla gomma che blocca
                out.append(self.msg("lock_wheel_bias",
                                    gomma=dwn[wi % 4]))
            # SPIATTELLAMENTO (LMU lo modella e RESTA sul treno): dopo
            # bloccaggi ripetuti, invita a sentire la vibrazione
            if not self._st.get("flat_said"):
                self._st["flat_said"] = True
                out.append(self.msg("flatspot_check"))
            break
        if not self._st.get("lock_bias") and len(pts) >= 5:
            cnt = {}
            for _ld, wi in pts:
                cnt[wi] = cnt.get(wi, 0) + 1
            wi = max(cnt, key=cnt.get)
            if cnt[wi] / float(len(pts)) >= 0.6:
                self._st["lock_bias"] = True
                out.append(self.msg("lock_wheel_bias", gomma=dwn[wi % 4]))
        return [m for m in out if m]

    def pace_notes_call(self, raw, laps_done):
        """PACE NOTES PERSONALI (in prova): quando ti AVVICINI a una zona
        dove blocchi ripetutamente, la voce ti avvisa PRIMA della curva
        ('curva 3, occhio all'anteriore sinistra'). Zone dai TUOI
        bloccaggi di sessione, nome curva dal profilo appreso.
        Max una nota ogni 20s, stessa zona non prima di 2 giri."""
        raw = raw or {}
        try:
            ld = float(raw.get("lapdist") or -1.0)
        except (TypeError, ValueError):
            return []
        if ld < 0:
            return []
        evs = raw.get("lock_events") or []
        if len(evs) < 3:
            return []
        # cluster (stessa logica del coach): centri delle zone problema
        pts = []
        for ev in evs:
            try:
                pts.append((float(ev[0]), int(ev[1])))
            except (TypeError, ValueError, IndexError):
                continue
        pts.sort()
        zones = []
        for d, wi in pts:
            if zones and abs(d - zones[-1]["d"]) <= 80.0:
                z = zones[-1]
                z["d"] = (z["d"] * z["n"] + d) / (z["n"] + 1)
                z["n"] += 1
                z["w"][wi] = z["w"].get(wi, 0) + 1
            else:
                zones.append({"d": d, "n": 1, "w": {wi: 1}})
        now = _time.monotonic()
        if now - self._st.get("pn_t", 0.0) < 20.0:
            return []
        corners = self._learned_corners(raw)
        dwn = (self._L("anteriore sinistra", "front left", None, None),
               self._L("anteriore destra", "front right", None, None),
               self._L("posteriore sinistra", "rear left", None, None),
               self._L("posteriore destra", "rear right", None, None))
        for z in zones:
            if z["n"] < 3:
                continue
            dist_to = z["d"] - ld
            if not (60.0 <= dist_to <= 220.0):
                continue
            zid = int(z["d"] // 120)
            last = self._st.get("pn_zone_%d" % zid, -9)
            if laps_done - last < 2:
                continue
            self._st["pn_zone_%d" % zid] = laps_done
            self._st["pn_t"] = now
            wi = max(z["w"], key=z["w"].get)
            cn = self._corner_name(corners, z["d"])
            if cn:
                return [self.msg("lock_zone_corner", gomma=dwn[wi % 4],
                                 n=cn)]
            # zona senza nome curva: pace note generica, MAI metri/km
            return [self.msg("lock_wheel_bias", gomma=dwn[wi % 4])]
        return []

    def engine_check(self, raw):
        """Motore: surriscaldamento acqua/olio, una volta con isteresi."""
        raw = raw or {}
        try:
            wt = float(raw.get("water_temp") or 0.0)
            ot = float(raw.get("oil_temp") or 0.0)
        except (TypeError, ValueError):
            return []
        hot = bool(raw.get("overheating")) or wt >= 105.0 or ot >= 135.0
        if hot and not self._st.get("eng_hot"):
            self._st["eng_hot"] = True
            return [self.msg("engine_hot")]
        if not hot and wt < 100.0:
            self._st.pop("eng_hot", None)
        return []

    def compound_practice(self, raw, laps_done):
        """Prova: mescola consigliata vs pista — MAI quella gia' montata."""
        raw = raw or {}
        if self._st.get("cp_said"):
            return []
        try:
            w = float(raw.get("wetness") or 0.0)
            tt = float(raw.get("track_temp") or 0.0)
        except (TypeError, ValueError):
            return []
        if laps_done < 2:
            return []
        if w > 0.25:
            want = "W"
        elif not (5.0 <= tt <= 60.0):
            return []      # temp asfalto assente/assurda (es. 0): muto
        elif tt < 22.0:
            want = "S"
        elif tt > 38.0:
            want = "H"
        else:
            want = "M"
        c4 = raw.get("tyre_compound4") or []
        cur = str(c4[0] if c4 else "").upper()[:1]
        if cur == want:
            return []                # state-aware: gia' montata, muto
        self._st["cp_said"] = True
        names = {"W": "wet", "S": "soft", "M": "media", "H": "dura"}
        return [self.msg("compound_reco", mescola=names.get(want, want),
                         temp=int(round(tt)))]

    def countdown(self, raw, laps_done):
        """Tempo che manca (30' lunghe / 10' sprint, 5', 1') + ultimo giro."""
        raw = raw or {}
        out = []
        rem = raw.get("race_remaining")
        if rem is None:
            return out
        rem = float(rem)
        total = float(raw.get("race_total") or 0.0)
        if total <= 0 or rem <= 0:
            return out
        # ultimo giro: al taglio con residuo < un tuo giro
        prev = self._st.get("cd_prev_lap")
        new_lap = bool(laps_done and prev is not None and laps_done > prev)
        self._st["cd_prev_lap"] = laps_done
        lt = self._lap_estimate(raw)
        if new_lap and not self._st.get("cd_lastlap") \
                and rem <= lt * 0.98 and (total - rem) > total * 0.3:
            self._st["cd_lastlap"] = True
            # "ultimo giro" SOLO in gara; in prova/quali il tempo scade e basta
            if session_kind(raw.get("session_type")) == "race":
                return [self.msg("last_lap")]
            return [self.msg("session_time_up")]
        step = 600 if total <= 2700 else 1800
        mark = int(rem // step)
        if mark != self._st.get("cd_mark") and rem > 90:
            self._st["cd_mark"] = mark
            mins = int(round(rem / 60.0))
            if mins >= 2 and abs(rem - mark * step) < 20:
                out.append(self.msg("time_left", minutes=mins))
        for thr, key in ((300, "cd_5"), (60, "cd_1")):
            if rem <= thr and not self._st.get(key):
                self._st[key] = True
                _mn = max(1, int(round(rem / 60.0)))
                # singolare corretto: 1 -> "un minuto" (msg dedicato)
                out.append(self.msg("last_min") if _mn <= 1
                           else self.msg("time_left", minutes=_mn))
                break
        return [m for m in out if m]

    def session_end(self, raw):
        """Fine sessione, una volta. In GARA il muretto saluta col
        PIAZZAMENTO a tre voci (ingegnere, stratega, spotter — v2);
        in QUALI la POLE se e' tua; altrimenti il saluto semplice."""
        raw = raw or {}
        if self._st.get("end_said"):
            return []
        fl = raw.get("flags") or {}
        phase = int(raw.get("game_phase") or 0)
        kind = session_kind(raw.get("session_type"))
        is_race = kind == "race"
        ended = bool(fl.get("finished")) and phase >= 5 if is_race else \
            (bool(fl.get("checkered")) and phase >= 5)
        if not ended:
            return []
        self._st["end_said"] = True
        riv = raw.get("rivals") or {}
        try:
            pos = int(riv.get("class_place") or 0)
        except (TypeError, ValueError):
            pos = 0
        if is_race and pos > 0:
            good = pos <= 3
            p = "P%d" % pos
            return [self.msg("fin_eng_good" if good else "fin_eng_ok",
                             pos=p),
                    self.msg("fin_strat_good" if good else "fin_strat_ok",
                             pos=p),
                    self.msg("fin_spot_good" if good else "fin_spot_ok",
                             pos=p)]
        if kind == "qualy" and pos == 1:
            return [self.msg("pole_pos"), self.msg("session_end")]
        return [self.msg("session_end")]

    def welcome_call(self, raw):
        """BENVENUTO in pista (una volta per sessione, v2): canali radio
        aperti, siamo con te. Parte alla prima uscita vera."""
        raw = raw or {}
        sig = (raw.get("track"), raw.get("session_type"))
        if self._st.get("wc_sig") == sig:
            return []
        try:
            spd = float(raw.get("speed") or 0.0)
        except (TypeError, ValueError):
            return []
        if spd < 10.0 or raw.get("garage") or raw.get("in_pits"):
            return []
        self._st["wc_sig"] = sig
        try:
            from telemetry.db import _short_track
            pista = _short_track(raw.get("track") or "") or "pista"
        except Exception:
            pista = str(raw.get("track") or "pista")
        nome = self._rival_name(raw.get("driver") or "") or ""
        return [self.msg("brief_spot", nome=nome, pista=pista)]

    def pit_ack(self, raw, laps_done):
        """Sosta FATTA: presa d'atto + ricalibrazione (una per sosta)."""
        raw = raw or {}
        np = raw.get("num_pit")
        if np is None or np == self._st.get("ack_np"):
            return []
        if self._st.get("ack_np") is None:
            self._st["ack_np"] = np          # baseline, non e' una sosta
            return []
        if laps_done - self._st.get("ack_lap", -9) < 3:
            return []
        self._st["ack_np"] = np
        self._st["ack_lap"] = laps_done
        # ricalibra: gomme nuove = warmup, degrado e assi ripartono puliti
        for k in ("tl_warn", "tl_dead", "rain_pend", "lf_secbest",
                  "tw_st", "tw_hot", "bk_st", "bk_hot", "fs_said",
                  "ax_cand", "ax_said", "bat_low", "bat_full"):
            self._st.pop(k, None)
        comp = None
        c4 = raw.get("compounds4") or raw.get("tyre_compound4") or []
        if self._wet_mounted(raw):
            comp = "W"
        elif c4 and c4[0]:
            comp = str(c4[0])[:1].upper()
        CMP = {"it": ({"W": "wet", "H": "dure", "M": "medie", "S": "morbide"},
                      "nuove"),
               "en": ({"W": "wets", "H": "hards", "M": "mediums",
                       "S": "softs"}, "fresh")}
        cm, cf = CMP.get(self.lang, CMP["it"])
        lbl = cm.get(comp, cf)
        per = float(raw.get("lmu_per_lap") or 0.0)
        cur = self._cur_load(raw, (self._plan or {}).get("constraint")
                             or "FUEL") or 0.0
        giri = int(cur / per) if per > 0 and cur > 0 else None
        out = [self.msg("pit_ack_fuel", gomma=lbl, giri=giri) if giri
               else self.msg("pit_ack", gomma=lbl)]
        if self._planned:
            try:
                out.extend(self._build_plan(raw, revise=True) or [])
            except Exception:
                pass
        return [m for m in out if m]

    def autofuel_call(self, raw, laps_done):
        """AUTO FUEL (opt-in): annuncia il target che il muretto tiene
        scritto nel pit menu. Al primo arm e ai cambi VERI (>=5 punti):
        i ritocchi da 1% mentre la gara si accorcia restano muti."""
        raw = raw or {}
        pct = (raw.get("lmu_live") or {}).get("auto_fuel_pct")
        if pct is None:
            self._st.pop("af_said", None)    # opzione spenta: riarma
            return []
        # UNA VOLTA SOLA: il ritocco benzina non va ripetuto (dava fastidio,
        # lo diceva a raffica mentre il target scendeva a gara che si accorcia).
        if self._st.get("af_said"):
            return []
        self._st["af_said"] = True
        return [self.msg("autofuel_set", pct=int(pct))]

    def box_call(self, raw, laps_done):
        """VOCE della strategia: finestra pit in avvicinamento (3 giri
        prima) e BOX al giro della sosta pianificata, col target dal
        piano. Una volta per sosta; ultima sosta = box_last.
        PRIMA di tutto la RETE DI SICUREZZA (dalla v2): autonomia
        MISURATA <= 1.2 giri e la bandiera non copre -> fuel_short,
        indipendente dal piano (che puo' essere stantio o muto)."""
        raw = raw or {}
        if raw.get("in_pits") or raw.get("in_pitlane") or raw.get("garage"):
            return []
        out = []
        live = raw.get("lmu_live") or {}
        lmu = raw.get("lmu_strat") or {}
        cstr = (live.get("constraint")
                or (self._plan or {}).get("constraint")
                or lmu.get("constraint") or "ENERGY")
        try:
            per = float(live.get("per_lap") or 0.0) \
                or float(raw.get("lmu_per_lap") or 0.0) \
                or float(lmu.get("per_lap") or 0.0) \
                or float((self._plan or {}).get("target_pl") or 0.0)
        except (TypeError, ValueError):
            per = 0.0
        cur = float(self._cur_load(raw, cstr) or 0.0)
        # autonomia: quella del blocco LMU LIVE se c'e' (dati e conto
        # diretti del gioco), senno' carico/consumo
        auto = live.get("autonomy_laps")
        if auto is None:
            auto = (cur / per) if per > 0 else None
        # giri alla BANDIERA: se la risorsa copre la fine niente allarme
        # (all'ultimo giro l'autonomia scende sotto 1.2 per definizione)
        rem = None
        try:
            rem_s = float(raw.get("race_remaining") or 0.0)
            timed = rem_s > 0.0 \
                or float(raw.get("race_total") or 0.0) > 120.0
            est = self._lap_estimate(raw)
            if timed:
                rem = (rem_s / est + 1.0) if est and est > 20.0 else None
                if rem_s <= 1.0:
                    rem = min(1.0, rem) if rem is not None else 1.0
            else:
                mx = int(raw.get("max_laps") or 0)
                if 0 < mx < 9999:
                    rem = float(mx - int(raw.get("laps_completed") or 0))
        except (TypeError, ValueError):
            rem = None
        last_lap = (rem is not None and rem <= 1.5)
        if auto is not None and 0 < auto <= 1.2 and not last_lap \
                and (rem is None or auto + 0.15 < rem):
            if not self._st.get("fs_said"):
                self._st["fs_said"] = True
                fonte = self._L("energia", "energy", "energia",
                                "energie") if cstr == "ENERGY" else \
                    self._L("benzina", "fuel", "gasolina", "essence")
                out.append(self.msg("fuel_short", fonte=fonte))
        elif auto is not None and auto > 3.0:
            self._st.pop("fs_said", None)     # rifornito: riarma
        # ── voce del piano ──
        # a gara FINITA / ultimo giro NON si chiama piu' il box: la
        # sosta non cambia l'esito (bug: "box" all'ultima curva)
        if last_lap or bool(raw.get("checkered")):
            return [m for m in out if m]
        md = self._race_model or {}
        fut = [s for s in (md.get("stops") or [])
               if int(s.get("lap") or 0) > int(laps_done or 0)]
        if not fut:
            return [m for m in out if m]
        nxt = fut[0]
        lap = int(nxt.get("lap") or 0)
        togo = lap - int(laps_done or 0)
        # preavviso finestra: 3 giri prima, una volta per sosta
        if togo == 3 and self._st.get("bx_warn") != lap:
            self._st["bx_warn"] = lap
            out.append(self.msg("pit_window", lap=lap, giri=togo))
        # chiamata: il giro PRIMA della sosta (entri a fine giro)
        if togo == 1 and self._st.get("bx_call") != lap:
            self._st["bx_call"] = lap
            tgt = min(100.0, float(nxt.get("refuel_pct") or 0.0)
                      + float(nxt.get("arrive_pct") or 0.0))
            cstr = (self._plan or {}).get("constraint") or "ENERGY"
            if cstr == "ENERGY":
                carico = "%d%%" % round(tgt)
            else:
                try:
                    tank = float(raw.get("fuel_max") or 0.0)
                except (TypeError, ValueError):
                    tank = 0.0
                carico = "%dL" % round(tgt * tank / 100.0) if tank > 0 \
                    else "%d%%" % round(tgt)
            code = "box_last" if len(fut) == 1 else "box_now"
            m = self.msg(code)
            if isinstance(m, dict) and m.get("text") and carico:
                m = dict(m)
                m["text"] = "%s %s" % (m["text"],
                                       self._L("Carico %s.", "Fuel load %s.",
                                               "Carga %s.", "Charge %s.")
                                       % carico)
            out.append(m)
        return [m for m in out if m]

    def _thermal_windows(self, comp=None):
        """Soglie termiche PER CLASSE (parametri WEC/ELMS reali, dalla
        v2 collaudata). Ritorna (gomma_fredda, gomma_over, freni_freddi,
        freni_over) in gradi C. Sulle Hypercar la soglia gomma dipende
        dalla mescola (S/M/H)."""
        # NB: self._cat e' il TAG di class_tag ("HY"/"P2"/"P3"/"GT3"/
        # "GTE"), non la stringa lunga: il confronto "HYP in HY"
        # falliva e TUTTE le classi cadevano sul default GT3 800
        # (cantilena freni caldi in Hypercar, 20/07)
        cat = (self._cat or "").upper()
        if cat == "HY" or any(k in cat for k in ("HYP", "LMH",
                                                 "LMDH")):
            t_cold = {"S": 60.0, "M": 85.0, "H": 105.0}.get(comp, 85.0)
            return (t_cold, 125.0, 250.0, 1050.0)
        if cat == "P2" or "LMP2" in cat:
            return (80.0, 105.0, 250.0, 950.0)
        if cat == "P3" or "LMP3" in cat:
            return (75.0, 100.0, 100.0, 750.0)
        if "GTE" in cat:
            return (70.0, 110.0, 200.0, 900.0)
        return (70.0, 105.0, 150.0, 800.0)      # GT3/LMGT3 e default

    def temp_call(self, raw, laps_done):
        """Temperature CARCASSA con soglie PER CLASSE (logica v2):
        freddi a inizio stint -> una volta; in temperatura -> una volta;
        sovratemperatura una volta, riarmo SOTTO soglia (-10 gomme,
        -30 freni: il disco oscilla staccata/rettilineo per natura).
        Muto sul bagnato. + SQUILIBRIO ASSI (persistente 3 letture).
        Riarmato dalla sosta (pit_ack)."""
        raw = raw or {}
        try:
            rn = float(raw.get("raining") or 0.0)
        except (TypeError, ValueError):
            rn = 0.0
        if rn >= 0.15 or self._wet_mounted(raw):
            return []
        comp = None
        for c in (raw.get("compounds4") or raw.get("tyre_compound4")
                  or []):
            cc = str(c)[:1].upper()
            if cc in ("S", "M", "H"):
                comp = cc
                break
        t_cold, t_over, b_cold, b_over = self._thermal_windows(comp)
        out = []
        carc = [float(t) for t in (raw.get("tyre_temp") or [])
                if t is not None]
        if carc:
            tmin, tmax = min(carc), max(carc)
            st = self._st.get("tw_st")
            if st is None:
                self._st["tw_st"] = "cold" if tmin < t_cold else "ok"
                if self._st["tw_st"] == "cold":
                    out.append(self.msg("tyres_cold"))
            elif st == "cold" and tmin >= t_cold:
                self._st["tw_st"] = "ok"
                out.append(self.msg("tyres_warm"))
            if tmax > t_over and not self._st.get("tw_hot"):
                self._st["tw_hot"] = True
                out.append(self.msg("tyres_hot"))
            elif tmax < t_over - 10.0:
                self._st.pop("tw_hot", None)
            # squilibrio ASSI: davanti vs dietro +-12 gradi, 3 letture
            if len(carc) == 4:
                d = (carc[0] + carc[1]) / 2.0 - (carc[2] + carc[3]) / 2.0
                side = "front" if d >= 12.0 else \
                    ("rear" if d <= -12.0 else None)
                if side and side == self._st.get("ax_cand"):
                    self._st["ax_n"] = self._st.get("ax_n", 0) + 1
                elif side:
                    self._st["ax_cand"] = side
                    self._st["ax_n"] = 1
                else:
                    if abs(d) < 8.0:
                        self._st.pop("ax_cand", None)
                        self._st.pop("ax_said", None)
                if side and self._st.get("ax_n", 0) >= 3 \
                        and self._st.get("ax_said") != side:
                    self._st["ax_said"] = side
                    out.append(self.msg("tyres_axle_%s" % side,
                                        delta=int(round(abs(d)))))
        brk = [float(t) for t in (raw.get("brake_temp") or [])
               if t is not None]
        if brk:
            bmin, bmax = min(brk), max(brk)
            if self._st.get("bk_st") is None:
                self._st["bk_st"] = "cold" if bmin < b_cold else "ok"
                if self._st["bk_st"] == "cold":
                    out.append(self.msg("brakes_cold"))
            # SOSTENUTO: "freni caldi" solo se restano sopra soglia per >= 4s
            # DI FILA (un picco di staccata non basta; se si raffreddano tra le
            # curve il timer riparte). Surriscaldamento VERO, non il picco.
            if bmax > b_over:
                _t0 = self._st.get("bk_over_t0")
                if _t0 is None:
                    self._st["bk_over_t0"] = _time.monotonic()
                elif _time.monotonic() - _t0 >= 4.0 \
                        and not self._st.get("bk_hot"):
                    self._st["bk_hot"] = True
                    out.append(self.msg("brakes_hot"))
            else:
                self._st.pop("bk_over_t0", None)      # sceso: riparte il timer
                if bmax < b_over - 30.0:
                    self._st.pop("bk_hot", None)
        return [m for m in out if m]

    def battery_check(self, raw, laps_done):
        """Ibrido: SOC basso/pieno, una volta con riarmo (solo se il dato
        esiste — auto non ibride restano mute)."""
        raw = raw or {}
        soc = raw.get("soc")
        try:
            soc = float(soc)
        except (TypeError, ValueError):
            return []
        if soc <= 0:
            return []
        if soc < 10.0 and not self._st.get("bat_low"):
            self._st["bat_low"] = True
            return [self.msg("batt_low", soc=int(round(soc)))]
        if soc > 95.0 and not self._st.get("bat_full"):
            self._st["bat_full"] = True
            return [self.msg("batt_full", soc=int(round(soc)))]
        if 20.0 < soc < 90.0:
            self._st.pop("bat_low", None)
            self._st.pop("bat_full", None)
        return []

    def fuel_practice(self, raw, laps_done):
        """PROVA: consumo MISURATO da LMU, detto una volta dopo 3 giri."""
        raw = raw or {}
        if self._st.get("fp_said") or (laps_done or 0) < 3:
            return []
        per = 0.0
        try:
            per = float(raw.get("lmu_per_lap") or 0.0)
        except (TypeError, ValueError):
            per = 0.0
        if per <= 0.2:
            return []
        self._st["fp_said"] = True
        cstr = ((raw.get("lmu_strat") or {}).get("constraint")
                or "FUEL").upper()
        if cstr == "ENERGY":
            giri = int(100.0 / per)
            cons = ("%.1f%%" % per).replace(".", ",")
        else:
            try:
                tank = float(raw.get("fuel_max") or 0.0)
            except (TypeError, ValueError):
                tank = 0.0
            giri = int(tank / per) if tank > 0 else 0
            cons = ("%.1fL" % per).replace(".", ",")
        return [self.msg("fuel_practice", cons=cons, giri=giri)]

    def status_update(self, raw, laps_done):
        """GARA: quadro periodico ogni 5 giri (gomme o carburante,
        alternati). Il PRIMO report arriva dopo 5 giri VERI (al giro 1
        un "check gomme" non ha senso) e le gomme si commentano solo
        quando c'e' usura da commentare."""
        raw = raw or {}
        if not laps_done:
            return []
        if self._st.get("su_lap") is None:
            self._st["su_lap"] = laps_done       # ancora: conta da QUI
            return []
        if laps_done - self._st["su_lap"] < 5:
            return []
        self._st["su_lap"] = laps_done
        flip = self._st["su_flip"] = not self._st.get("su_flip", False)
        if flip:
            tw = raw.get("tyre_wear")
            try:
                worst = min(float(x) for x in (tw or []) if x is not None)
            except (TypeError, ValueError):
                return []
            if worst > 93.0:
                return []                        # gomme fresche: nulla da dire
            return [self.msg("status_tyre", gomme=int(round(worst)))]
        per = 0.0
        try:
            per = float(raw.get("lmu_per_lap") or 0.0)
        except (TypeError, ValueError):
            per = 0.0
        cstr = (self._plan or {}).get("constraint") or "ENERGY"
        cur = self._cur_load(raw, cstr)
        if per > 0.2 and cur:
            fonte = self._L("energia", "energy", "energia", "energie") \
                if cstr == "ENERGY" else \
                self._L("benzina", "fuel", "gasolina", "essence")
            return [self.msg("status_fuel", giri=int(cur / per),
                             fonte=fonte)]
        return []

    def theo_lap(self, raw, laps_done):
        """Giro TEORICO dai tuoi settori migliori (quando batte il best
        di almeno 3 decimi): dove lasci tempo."""
        raw = raw or {}
        sb = self._st.get("lf_secbest")
        best = self._st.get("lf_best")
        if not sb or best is None or None in sb:
            return []
        theo = sum(sb)
        if theo <= 20.0 or best - theo < 0.3:
            return []
        if abs(theo - self._st.get("th_said", 0.0)) < 0.15:
            return []
        last = self._st.get("lf_lastsec")
        if not last or len(last) != 3:
            return []
        diffs = [(last[i] - sb[i]) if (last[i] and sb[i]) else -9.0
                 for i in range(3)]
        self._st["th_said"] = theo
        return [self.msg("theo_lap", tempo=_fmt_lap_round(theo),
                         gap=("%.1f" % (best - theo)).replace(".", ","),
                         settore=diffs.index(max(diffs)) + 1)]

    def quali_prep(self, raw, laps_done):
        """QUALIFICA: gomme fredde in out-lap -> prepara; una volta."""
        raw = raw or {}
        if self._st.get("qp_said"):
            return []
        tt = raw.get("tyre_temp")
        try:
            ta = sum(float(x) for x in (tt or []) if x is not None) \
                / max(1, len([x for x in (tt or []) if x is not None]))
        except (TypeError, ValueError):
            return []
        if (laps_done or 0) == 0 and ta and ta < 60.0:
            self._st["qp_said"] = True
            return [self.msg("quali_warmup")]
        return []

    def quali_sector_live(self, raw, laps_done):
        """QUALIFICA live: S1 chiuso -> su/giu' vs il tuo best; oltre
        8 decimi persi -> abort consigliato."""
        raw = raw or {}
        try:
            s1 = float(raw.get("cur_s1") or 0.0)
        except (TypeError, ValueError):
            return []
        if s1 <= 5.0 or s1 == self._st.get("qs_s1"):
            return []
        self._st["qs_s1"] = s1
        b = self._st.get("qs_best_s1")
        if b is None or s1 < b:
            self._st["qs_best_s1"] = s1
            if b is not None:
                return [self.msg("quali_sector_up", settore=1,
                                 gap=("%.1f" % (b - s1)).replace(".", ","))]
            return []
        d = s1 - b
        if d > 0.8:
            return [self.msg("quali_abort", settore=1,
                             perdita=("%.1f" % d).replace(".", ","))]
        if d > 0.25:
            return [self.msg("quali_sector_down", settore=1,
                             gap=("%.1f" % d).replace(".", ","))]
        return []

    def quali_evolution(self, raw, laps_done):
        """QUALIFICA: ultimo run quando restano ~3 minuti (pista al top)."""
        raw = raw or {}
        try:
            rem = float(raw.get("race_remaining") or 0.0)
        except (TypeError, ValueError):
            return []
        if 0 < rem <= 240.0 and not self._st.get("qe_last"):
            self._st["qe_last"] = True
            return [self.msg("quali_last_run")]
        return []

    def wet_patches(self, raw):
        """STATO DELLA SCIA: min = traiettoria, max = fuori scia.
        - scia che si ASCIUGA con pista ancora bagnata -> 'drying'
        - bagnato molto disuniforme (chiazze) -> 'wet_patchy'."""
        raw = raw or {}
        try:
            wmin = float(raw.get("wetness_min") or 0.0)
            wmax = float(raw.get("wetness_max") or 0.0)
            wavg = float(raw.get("wetness") or 0.0)
        except (TypeError, ValueError):
            return []
        out = []
        # scia asciutta, esterno ancora bagnato: informazione chiave
        if wmin < 0.12 and wavg > 0.18 and not self._st.get("wp_dryline"):
            self._st["wp_dryline"] = True
            out.append(self.msg("drying"))
        elif wmin > 0.20:
            self._st.pop("wp_dryline", None)
        spread = wmax - wmin
        if spread >= 0.35 and not self._st.get("wp_on"):
            self._st["wp_on"] = True
            out.append(self.msg("wet_patchy"))
        if spread < 0.20:
            self._st.pop("wp_on", None)
        return [m for m in out if m]

    def pos_call(self, raw):
        """Posizione di classe, valutata SOLO al traguardo (una volta per giro):
        la posizione e' ufficiale al passaggio sulla linea, non a meta' giro
        mentre i gap ballano. Confronta la posizione di QUESTO giro con quella
        del giro precedente e annuncia guadagno/perdita/comando."""
        raw = raw or {}
        riv = raw.get("rivals") or {}
        try:
            pos = int(riv.get("class_place") or 0)
        except (TypeError, ValueError):
            return []
        if pos <= 0:
            return []
        try:
            lap = int(raw.get("laps_completed") or 0)
            dist = float(raw.get("lapdist") or 0.0)
        except (TypeError, ValueError):
            return []
        # NUOVO GIRO: NON leggere la posizione sulla linea (lo scoring e' ancora
        # quello del giro appena tagliato -> annunciava P2 mentre eri P1). Segna
        # 'da controllare' e leggi PIU' AVANTI, dentro il giro nuovo.
        if lap != self._st.get("pos_lap"):
            self._st["pos_lap"] = lap
            self._st["pos_check"] = True
            return []
        if not self._st.get("pos_check") or dist < 150.0:
            return []
        self._st["pos_check"] = False
        prev = self._st.get("pos_prev")
        self._st["pos_prev"] = pos
        if prev is None or pos == prev:
            return []
        _kind = session_kind(raw.get("session_type"))
        if _kind != "race":
            # PROVA/QUALI: mai "guadagno/ti hanno passato", solo posizione attuale
            if _kind == "qualy" and pos == 1:
                return [self.msg("pos_pole", pos="P%d" % pos)]
            return [self.msg("pos_now", pos="P%d" % pos)]
        if pos == 1:
            code = "pos_lead"
        elif pos < prev:
            code = "pos_gain"
        else:
            code = "pos_loss"
        return [self.msg(code, pos="P%d" % pos, prev="P%d" % prev)]

    def run_abort_call(self, raw):
        """PROVA/QUALI: annuncia 'ok run abortito, raffredda' NEL MOMENTO in cui
        sul dash appare ABORTED (delta > soglia a meta' giro), non a giro chiuso.
        Il dash scrive l'evento in dash_abort.json; qui lo leggo. Una volta per
        evento; muto in pit/garage."""
        raw = raw or {}
        if session_kind(raw.get("session_type")) == "race":
            return []
        try:
            from core.paths import USER_DIR
            p = USER_DIR / "dash_abort.json"
            if not p.exists():
                return []
            ev = _json.loads(p.read_text(encoding="utf-8"))
            t = float(ev.get("t") or 0.0)
        except Exception:
            return []
        if t <= self._st.get("ab_dash_t", 0.0):  # gia' annunciato questo abort
            return []
        self._st["ab_dash_t"] = t
        if raw.get("in_pits") or raw.get("in_pitlane") or raw.get("garage"):
            return []
        return [self.msg("run_aborted")]

    def strategy_check(self, raw, pace=None, laps_done=0):
        """COACHING CONSUMO vs TARGET (il cuore endurance): ogni 4 giri
        confronta il consumo MISURATO col target del piano.
        Sopra target -> gestisci; sotto -> puoi spingere; in linea -> ok."""
        raw = raw or {}
        if not self._plan:
            return []
        try:
            ld = int(laps_done or raw.get("laps_completed") or 0)
        except (TypeError, ValueError):
            ld = 0
        if ld < 3 or ld - self._st.get("sc_lap", -9) < 4:
            return []
        self._st["sc_lap"] = ld
        try:
            per = float(raw.get("lmu_per_lap") or 0.0)
            tgt = float(self._plan.get("target_pl") or 0.0)
        except (TypeError, ValueError):
            return []
        if per <= 0.2 or tgt <= 0.2:
            return []
        dev = (per - tgt) / tgt              # +5% = consumi troppo
        lt = _fmt_lap_round(self._lap_estimate(raw))
        prev = self._st.get("sc_state")
        if dev > 0.05:
            state = "over"
        elif dev < -0.05:
            state = "push"
        else:
            state = "ok"
        if state == prev and state == "ok":
            return []                         # l'ok non si ripete
        self._st["sc_state"] = state
        if state == "over":
            return [self.msg("chk_over", lap_time=lt,
                             delta=("%.0f" % (dev * 100)))]
        if state == "push":
            return [self.msg("chk_push", lap_time=lt)]
        if prev in ("over", "push"):
            return [self.msg("chk_ok", lap_time=lt)]
        return []

    def weather_check(self, raw, laps_done=0):
        """DECISIONI HOLD/GO sulle finestre di pioggia del piano: pioggia
        BREVE (non ripaga due soste) -> tieni le slick e galleggia;
        pioggia LUNGA -> il muro del piano vale; bagnato fino alla fine
        -> wet e basta. Una volta per cambio d'arco."""
        raw = raw or {}
        md = self._race_model or {}
        segs = md.get("segments") or []
        if len(segs) < 2:
            self._st.pop("wx_case", None)    # tutto asciutto: riarma
            return []
        try:
            ld = int(laps_done or raw.get("laps_completed") or 0)
        except (TypeError, ValueError):
            ld = 0
        wet_segs = [s for s in segs if s[2] == "wet" and s[1] > ld]
        if not wet_segs:
            self._st.pop("wx_case", None)    # arco chiuso: riarma
            return []
        nxt = wet_segs[0]
        dur = nxt[1] - max(nxt[0], ld)
        # soglia: sotto ~2 soste di perdita non ripaga il doppio cambio
        laptime = self._lap_estimate(raw)
        hold_thr = max(2, int(round(2.0 * self._pit_stop_seconds(raw)
                                    / max(30.0, laptime))))
        wet_to_end = nxt[1] >= (md.get("race_laps") or 0)
        code, kw = None, {}
        if nxt[0] <= ld:
            # siamo GIA' dentro il bagnato: conta quanto manca alla fine
            if wet_to_end:
                code = "wet_stay_end"
            else:
                code = "rain_fc_wet_end"
                kw["min"] = max(1, int(round((nxt[1] - ld)
                                             * laptime / 60.0)))
        else:
            mins = max(1, int(round((nxt[0] - ld) * laptime / 60.0)))
            if wet_to_end:
                if self._wet_mounted(raw):
                    code = "wet_stay_end"
                else:
                    code, kw = "rain_in", {"minutes": mins}
            elif dur <= hold_thr and not self._wet_mounted(raw):
                code = "wx_rain_window_hold"
                kw = {"lap": int(nxt[0]), "dry": int(nxt[1]),
                      "win": int(dur)}
            else:
                # pioggia lunga: se cade su una sosta gia' pianificata,
                # una sola fermata (rifornimento + wet insieme);
                # altrimenti solo preavviso
                stops = [s for s in (md.get("stops") or [])
                         if isinstance(s, dict)]
                if any(abs(int(s.get("lap") or -99) - int(nxt[0])) <= 2
                       for s in stops):
                    code, kw = "rain_window", {"lap": int(nxt[0]),
                                               "mins": mins}
                else:
                    code, kw = "rain_in", {"minutes": mins}
        # parla SOLO quando la CONCLUSIONE cambia (schema v2): i giri
        # del forecast ballano a ogni ricalcolo, il caso no
        if not code or code == self._st.get("wx_case"):
            return []
        self._st["wx_case"] = code
        return [self.msg(code, **kw)]

    def corner_loss(self, raw, laps_done):
        """CURVE DOVE PERDO TEMPO: traccia la Vmin per curva sul giro e la
        confronta con la tua Vmin di RIFERIMENTO appresa; a fine giro segnala
        la curva dove sei piu' lento (perdi). Asciutto, pista appresa.
        Cooldown 3 giri per curva (niente martellamento)."""
        raw = raw or {}
        try:
            if float(raw.get("raining") or 0.0) >= 0.15 or self._wet_mounted(raw):
                self._st["cl_trk"] = {}
                return []
            d = float(raw.get("lapdist") or -1.0)
            spd = float(raw.get("speed") or 0.0)
        except (TypeError, ValueError):
            return []
        corners = self._learned_corners(raw)
        if not corners or d < 0 or spd <= 0:
            return []
        trk = self._st.setdefault("cl_trk", {})
        near, nd = None, 1e9
        for c in corners:
            try:
                cd = float(c.get("d"))
            except (TypeError, ValueError):
                continue
            if c.get("n") is None:
                continue
            gap = abs(cd - d)
            if gap < 50.0 and gap < nd:
                near, nd = c, gap
        if near is not None:
            n = near.get("n")
            cur = trk.get(n)
            if cur is None or spd < cur:
                trk[n] = spd                  # Vmin del giro per questa curva
        out = []
        prev = self._st.get("cl_lap")
        self._st["cl_lap"] = laps_done
        if prev is not None and laps_done > prev and trk:
            said = self._st.setdefault("cl_said", {})
            ref = {c.get("n"): float(c.get("vmin")) for c in corners
                   if c.get("n") is not None and c.get("vmin")}
            worst_n, worst_def = None, 0.0
            for n, myv in trk.items():
                rv = ref.get(n)
                if rv and (rv - myv) > worst_def \
                        and (laps_done - said.get(n, -99)) >= 3:
                    worst_def, worst_n = rv - myv, n
            self._st["cl_trk"] = {}           # reset per il prossimo giro
            if worst_n is not None and worst_def >= 6.0:   # >= 6 km/h piu' lento
                said[worst_n] = laps_done
                self._st["dbr_corner"] = worst_n      # per il debrief di stint
                _myv = ref.get(worst_n, 0.0) - worst_def
                out = [self.msg("carry_speed", turn=worst_n,
                                v=int(round(_myv)),
                                vref=int(round(ref.get(worst_n, 0.0))))]
        return out

    def _rival_name(self, name):
        """Nome rivale per la VOCE: SOLO il cognome. L'iniziale abbreviata
        ('A. Fuoco') la TTS la legge male ('a fuoco') -> uso l'ultimo token."""
        parts = str(name or "").strip().split()
        return parts[-1] if parts else ""

    def _same_class(self, raw, cls):
        """True se la classe del rivale e' la MIA (info rivali solo di classe)."""
        my = (class_tag(raw.get("car_class") or "") or self._cat or "").upper()
        return bool(my) and (class_tag(str(cls or "")) or "").upper() == my

    def opp_penalty(self, raw):
        """RIVALE DI CLASSE che prende una penalita' NUOVA. LMU da' il CONTATORE
        (non il tipo): diciamo chi, non quale. Solo stessa classe. Voce spotter."""
        raw = raw or {}
        cars = raw.get("cars") or {}
        prev = self._st.get("cars_pen")
        out = []
        if prev:
            for cid, c in cars.items():
                if not self._same_class(raw, c.get("cls")):
                    continue
                pp = prev.get(cid)
                nm = self._rival_name(c.get("name", ""))
                if pp is not None and int(c.get("pen", 0)) > int(pp) and nm:
                    out.append(self.msg("opp_penalty", name=nm))
                    break
        self._st["cars_pen"] = {cid: int(c.get("pen", 0)) for cid, c in cars.items()}
        return out

    def opp_pace_drop(self, raw):
        """RIVALE DI CLASSE che perde passo di colpo: ultimo giro oltre +3s sul
        suo miglior recente. Solo stessa classe. Una volta per calo. Spotter."""
        raw = raw or {}
        cars = raw.get("cars") or {}
        best = self._st.setdefault("cars_best", {})
        said = self._st.setdefault("cars_slow_said", {})
        out = []
        for cid, c in cars.items():
            if not self._same_class(raw, c.get("cls")):
                continue
            try:
                last = float(c.get("last", -1))
            except (TypeError, ValueError):
                continue
            if last <= 20.0:
                continue
            b = best.get(cid)
            nm = self._rival_name(c.get("name", ""))
            if b and last > b + 3.0 and nm and not out:
                if said.get(cid) != int(last):
                    said[cid] = int(last)
                    out.append(self.msg("opp_slow", name=nm))
            if b is None or last < b:
                best[cid] = last
        return out

    def limits_review_call(self, raw):
        """TRACK LIMITS, ciclo VERO dal trace (race_control, non piu'
        mCountLapFlag rumoroso): annuncia l'apertura dell'esame ("taglio
        sotto esame, restituisci"), poi l'ESITO — perdonato (limits_clear),
        warning in gara (limits_warning) o giro cancellato in prova/quali
        (tlimits_lap). La penalita' DT arriva dal flusso penalita'."""
        raw = raw or {}
        try:
            from core.race_control import track_limits_state
            st = track_limits_state()
        except Exception:
            return []
        # SOLO la POSIZIONE DA RIDARE (sorpasso tagliando, dal trace: e'
        # l'unico dato che la shared memory non ha). Tutto il resto —
        # "track preso", conto punti, giro cancellato — lo annuncia
        # tlimits_call dagli STEPS (istantanei). Niente doppioni.
        if st.get("review"):
            try:
                _pd = float(st.get("placediff") or 0.0)
            except (TypeError, ValueError):
                _pd = 0.0
            if session_kind(raw.get("session_type")) == "race" \
                    and _pd > 0 and not self._st.get("lim_pos_said"):
                self._st["lim_pos_said"] = True
                return [self.msg("limits_review_pos")]
            return []
        self._st.pop("lim_pos_said", None)
        return []

    def community_spotter(self, raw):
        """SPOTTER COMMUNITY: quando in pista c'e' un pilota noto ai ref online
        lo annuncia UNA volta a sessione, col suo tempo di riferimento su
        QUESTA pista (classe che sta guidando) oppure 'non ha ancora un tempo
        qui'. Chi e' stato detto viene congelato; i nuovi che arrivano vengono
        annunciati a loro volta. Uno per tick (niente raffiche). Per ORA non
        esclude il giocatore (serve a verificarne il funzionamento da soli)."""
        raw = raw or {}
        field = raw.get("field") or {}
        comm = raw.get("comm") or {}
        times = comm.get("times") or {}
        known = comm.get("known") or set()
        if not field or (not times and not known):
            return []                       # dati community non pronti: aspetta
        sig = (raw.get("track"), raw.get("session_type"))
        if self._st.get("comm_sig") != sig:  # nuova sessione: ri-annuncia tutti
            self._st["comm_sig"] = sig
            self._st["comm_said"] = set()
        said = self._st.setdefault("comm_said", set())
        for _cid, c in field.items():
            nm = (c.get("name") or "").strip()
            if not nm:
                continue
            low = nm.lower()
            if low in said:
                continue                    # gia' annunciato: congelato
            tag = class_tag(c.get("cls") or "")
            ms = times.get((low, tag))
            if not (low in known or ms is not None):
                continue                    # non e' un pilota community: salta
            said.add(low)                   # freeze: una sola volta a sessione
            if ms:
                return [self.msg("community_seen", name=nm,
                                 time=_fmt_lap_round(ms / 1000.0))]
            return [self.msg("community_seen_notime", name=nm)]
        return []

    def rain_pace_loss(self, raw, laps_done):
        """SU SLICK COL BAGNATO: tiene il tuo passo ASCIUTTO come riferimento;
        se ora il giro crolla oltre soglia (stai scivolando) suggerisce le wet.
        Non e' un ordine: consiglio. Una volta (riarma a gomma cambiata)."""
        raw = raw or {}
        if self._wet_mounted(raw):
            self._st.pop("rpl_said", None)        # gia' su wet: riarma, muto
            return []
        try:
            wet = float(raw.get("wetness") or 0.0)
            rn = float(raw.get("raining") or 0.0)
            lt = float(raw.get("lap_time") or 0.0)
        except (TypeError, ValueError):
            return []
        if lt <= 20.0:
            return []
        # ASCIUTTO -> aggiorna il riferimento (giro valido)
        if wet < 0.10 and rn < 0.10:
            if not raw.get("invalid"):
                b = self._st.get("dry_ref")
                if b is None or lt < b:
                    self._st["dry_ref"] = lt
            return []
        # BAGNATO su slick: confronto col riferimento asciutto
        dry = self._st.get("dry_ref")
        if not dry:
            return []
        loss = lt - float(dry)
        if loss >= 3.0 and not self._st.get("rpl_said"):
            self._st["rpl_said"] = True
            return [self.msg("rain_box_pace", perdita=int(round(loss)))]
        return []

    def race_briefing(self, raw):
        """BRIEFING METEO al rolling start (PRE-VERDE): quadro pioggia della
        gara dal forecast LMU (nodi START..FINISH), gia' esposto prima del via.
        Una volta per sessione. Asciutto = sereno; pioggia = avvisa."""
        raw = raw or {}
        if self._st.get("rb_said"):
            return []
        try:
            styp = int(raw.get("session_type") or 0)
            phase = int(raw.get("game_phase") or 0)
            ld = int(raw.get("laps_completed") or 0)
        except (TypeError, ValueError):
            return []
        if styp < 10:                        # solo GARA
            return []
        if phase >= 5 and ld >= 1:           # verde passato da un pezzo: niente briefing tardivo
            return []
        fc = raw.get("forecast_rain")
        if not fc or len(fc) < 2:
            return []                        # forecast non ancora pronto: riprova
        try:
            vals = [float(x) for x in fc]
        except (TypeError, ValueError):
            return []
        self._st["rb_said"] = True
        pista = str(raw.get("track") or "").strip()
        if max(vals) < 30.0:                 # gara prevista asciutta
            return [self.msg("weather_dry", pista=pista)]
        return [self.msg("weather_wet", pista=pista)]

    def green_call(self, raw):
        """VIA / RIPARTENZA in gara. Al passaggio a bandiera verde
        (mGamePhase -> 5): dalla formazione/countdown = 'Verde, vai!'
        (race_start); da gialla/stop = 'Verde, si riparte.' (green_restart).
        Una volta per transizione (solo GARA)."""
        raw = raw or {}
        try:
            styp = int(raw.get("session_type") or 0)
            phase = int(raw.get("game_phase") or 0)
        except (TypeError, ValueError):
            return []
        prev = self._st.get("grn_prev")
        self._st["grn_prev"] = phase
        if styp < 10:                        # solo GARA
            return []
        if prev is None or phase != 5 or prev == 5:
            return []                        # nessuna transizione VERSO il verde
        if prev in (0, 1, 2, 3, 4):          # da formazione/countdown = VIA
            return [self.msg("race_start")]
        if prev in (6, 7):                   # da gialla/stop = RIPARTENZA
            return [self.msg("green_restart")]
        return []

    def briefing(self, raw):
        """PROVA: briefing APPRESO — se conosco gia' la pista dai tuoi
        giri passati, lo dico (best, curve mappate). Una volta."""
        raw = raw or {}
        if self._st.get("bf_said"):
            return []
        try:
            from core.engineer_learn import load as _learn_load
            prof = _learn_load(raw.get("track") or "",
                               class_tag(raw.get("car_class") or "")) or {}
            cond = (prof.get("cond") or {}).get("dry") or {}
            best = cond.get("best_lap")
            n = int(cond.get("samples") or 0)
            fpl = cond.get("fuel_per_lap")
            epl = cond.get("energy_per_lap")
            pista = str(raw.get("track") or "").strip()
            if not best or n <= 0 or not pista:
                return []
            if fpl:
                perlap = ("%.1f " % float(fpl)).replace(".", ",") \
                    + self._L("litri", "liters", "litros", "litres")
            elif epl:
                perlap = ("%.1f " % float(epl)).replace(".", ",") \
                    + self._L("per cento", "percent",
                              "por ciento", "pour cent")
            else:
                return []
            self._st["bf_said"] = True
            return [self.msg("brief_eng_data", pista=pista, n=n,
                             perlap=perlap, best=_fmt_lap_round(best))]
        except Exception:
            return []

    def tlimits_call(self, raw, laps_done):
        """TRACK LIMITS: accumulo avvisi e penalita' (dai contatori LMU)."""
        raw = raw or {}
        try:
            steps = int(raw.get("tl_steps") or 0)
            pen = int(raw.get("tl_pen") or 0)
        except (TypeError, ValueError):
            return []
        ps = self._st.get("tl_steps")
        if ps is None:
            # PRIMA lettura = BASELINE muta: un contatore gia' alto
            # (ereditato/ripreso a meta') non e' un'infrazione NUOVA
            self._st["tl_steps"] = steps
            return []
        if steps == ps:
            return []
        self._st["tl_steps"] = steps
        if steps < ps:
            self._st.pop("tl_half", None)    # conto azzerato: riarma
            self._st.pop("tl_corners", None)
            return []       # azzerato (penalita' scontata o reset sessione)
        # steps AUMENTATI = TRACK PRESO, ADESSO (la shared memory scatta
        # all'istante, verificato col log di calibrazione — il trace invece
        # arriva a blocchi in ritardo e perdeva gli esiti). Mappa verificata:
        # 1 punto = per_point steps (4), penalita' a per_penalty steps (20).
        turn = self._corner_at(raw)          # curva ESATTA (siamo sul posto)
        try:
            _pp = int(raw.get("tl_point") or 0)
        except (TypeError, ValueError):
            _pp = 0
        out = []
        _race = session_kind(raw.get("session_type")) == "race"
        if not _race:
            # prova/quali: niente punti, il taglio costa il GIRO
            out.append(self.msg("tlimits_lap"))
        elif _pp > 0 and pen > 0:
            _q, _r = divmod(steps, _pp)
            _half = _r != 0 and abs(_r * 2 - _pp) <= 1
            if _r == 0:
                _tot = self._L("un punto", "one point", "un punto",
                               "un point") if _q == 1 \
                    else self._L("%d punti" % _q, "%d points" % _q,
                                 "%d puntos" % _q, "%d points" % _q)
            elif _half and _q == 0:
                _tot = self._L("mezzo punto", "half a point",
                               "medio punto", "un demi-point")
            elif _half and _q == 1:
                _tot = self._L("un punto e mezzo", "one and a half points",
                               "un punto y medio", "un point et demi")
            elif _half:
                _tot = self._L("%d punti e mezzo" % _q,
                               "%d and a half points" % _q,
                               "%d puntos y medio" % _q,
                               "%d points et demi" % _q)
            else:
                _tot = self._L(
                    ("%.1f punti" % (steps / float(_pp))).replace(".", ","),
                    "%.1f points" % (steps / float(_pp)),
                    ("%.1f puntos" % (steps / float(_pp))).replace(".", ","),
                    ("%.1f points" % (steps / float(_pp))).replace(".", ","))
            out.append(self.msg("limits_warning_n", tot=_tot,
                                max=int(round(pen / float(_pp)))))
        else:
            out.append(self.msg("limits_warning"))
        # conto PER CURVA: dal 2° taglio nella stessa curva
        if turn is not None:
            tc = self._st.setdefault("tl_corners", {})
            tc[turn] = tc.get(turn, 0) + 1
            if tc[turn] >= 2:
                out.append(self.msg("tlimits_repeat", turn=turn,
                                    count=tc[turn]))
        if pen > 0 and _race:
            left = pen - steps
            left_say = max(1, int(round(left / float(_pp)))) if _pp > 0 \
                else left
            if left <= 0:
                out.append(self.msg("tlimits_pen_where", turn=turn)
                           if turn else self.msg("tlimits_pen"))
            elif (left <= _pp * 1.5 if _pp > 0 else left <= 2):
                out.append(self.msg("tlimits_warn_where", left=left_say,
                                    turn=turn)
                           if turn else self.msg("tlimits_warn",
                                                 left=left_say))
            elif steps >= pen * 0.5 and not self._st.get("tl_half"):
                self._st["tl_half"] = True
                out.append(self.msg("tlimits_warn", left=left_say))
        return out

    def _corner_at(self, raw):
        """Numero della curva APPRESA piu' vicina alla posizione attuale, o
        None se non affidabile (pista non appresa / troppo lontano)."""
        corners = self._learned_corners(raw)
        if not corners:
            return None
        try:
            d = float(raw.get("lapdist") or -1.0)
        except (TypeError, ValueError):
            return None
        if d < 0:
            return None
        near = None
        for c in corners:
            try:
                cd = float(c.get("d"))
            except (TypeError, ValueError):
                continue
            if near is None or abs(cd - d) < abs(float(near.get("d")) - d):
                near = c
        if near is None or abs(float(near.get("d")) - d) > 150.0:
            return None
        return near.get("n")

    def manage_briefing(self, raw):
        """GESTISCI o SPINGI (nel briefing): se lo stint e' limitato dall'usura
        gomma (arriverebbe morta tirando) -> gestisci; senno' via libera. Una
        volta, quando il piano c'e'."""
        if self._st.get("mng_said"):
            return []
        plan = self._plan or {}
        try:
            stint = float(plan.get("stint_laps") or 0.0)
        except (TypeError, ValueError):
            return []
        if stint <= 0:
            return []
        self._st["mng_said"] = True
        deg = getattr(self, "_deg", None)
        dead = float(getattr(self, "_wear_dead", 70.0) or 70.0)
        budget = max(5.0, 100.0 - dead)
        try:
            if deg and float(deg) * stint >= budget * 0.85:
                return [self.msg("briefing_manage")]
        except (TypeError, ValueError):
            pass
        return [self.msg("briefing_push")]

    def fuel_save_option(self, raw, laps_done):
        """MARGINE PER UNA SOSTA IN MENO: se allungando ogni stint di pochi
        giri (risparmiando VE/benzina) copri la gara con una sosta in meno,
        lo segnala. Consiglio, una volta per piano."""
        md = self._race_model or {}
        plan = self._plan or {}
        try:
            stops = int(plan.get("stops") or 0)
            autonomy = float(plan.get("stint_laps") or 0.0)
            race_laps = float(md.get("race_laps") or 0.0)
        except (TypeError, ValueError):
            return []
        if stops < 1 or autonomy <= 0 or race_laps <= 0:
            return []
        # con UNA sosta in meno: `stops` stint invece di stops+1
        need_per_stint = race_laps / float(stops)
        extra = need_per_stint - autonomy          # giri extra da coprire/stint
        if 0.4 < extra <= 3.0 and not self._st.get("save_said"):
            self._st["save_said"] = True
            return [self.msg("briefing_save")]
        return []

    def strat_extra_stop(self, raw, laps_done):
        """SOSTA GRATIS: se il gap dal rivale dietro copre la perdita
        sosta, una fermata extra (gomme fresche) non costa posizione."""
        raw = raw or {}
        riv = raw.get("rivals") or {}
        try:
            gb = float(riv.get("gap_behind"))
        except (TypeError, ValueError):
            return []
        md = self._race_model or {}
        left = (md.get("race_laps") or 0) - int(laps_done or 0)
        if left < 8 or not self._plan:
            return []
        tw = raw.get("tyre_wear")
        try:
            worst = min(float(x) for x in (tw or []) if x is not None)
        except (TypeError, ValueError):
            return []
        if worst > 82.0:
            return []            # gomme ancora buone: non serve dirlo
        loss = self._pit_stop_seconds(raw)
        free = gb > loss + 5.0
        if free and not self._st.get("xs_free"):
            self._st["xs_free"] = True
            return [self.msg("strat_extra_free", wear=int(round(worst)),
                             gap=("%.0f" % gb), loss=("%.0f" % loss))]
        if not free and gb < loss - 5.0:
            self._st.pop("xs_free", None)
        return []

    def position_strategy(self, raw, laps_done):
        """FINALE DI GARA (ultimi 10 giri): attacco possibile davanti /
        difesa dietro, una volta per condizione."""
        raw = raw or {}
        md = self._race_model or {}
        left = (md.get("race_laps") or 0) - int(laps_done or 0)
        if not (0 < left <= 12):
            return []
        pit = self._pit_stop_seconds(raw)
        if not pit or pit <= 5.0:
            return []
        stops_left = any(int(s.get("lap") or 0) > int(laps_done or 0)
                         for s in (md.get("stops") or [])
                         if isinstance(s, dict))
        riv = raw.get("rivals") or {}
        out = []
        try:
            ga = float(riv.get("gap_ahead"))
        except (TypeError, ValueError):
            ga = None
        try:
            gb = float(riv.get("gap_behind"))
        except (TypeError, ValueError):
            gb = None
        pf = "%.0f" % pit
        # ATTACCO: lui davanti DENTRO il costo sosta, io a posto di soste
        if ga is not None and 3.0 < ga < pit - 2.0 and not stops_left \
                and not self._st.get("ps_atk"):
            self._st["ps_atk"] = True
            out.append(self.msg("pos_attack",
                                gap=("%.1f" % ga).replace(".", ","),
                                name=riv.get("name_ahead") or "", pit=pf))
        # SCOPERTO: devo ancora fermarmi e il margine dietro non copre
        if gb is not None and 0 < gb < pit - 2.0 and stops_left \
                and not self._st.get("ps_def"):
            self._st["ps_def"] = True
            out.append(self.msg("pos_expose",
                                gap=("%.1f" % gb).replace(".", ","),
                                name=riv.get("name_behind") or "", pit=pf,
                                need=max(1, int(round(pit - gb)))))
        return [m for m in out if m]

    def _must_box(self, raw):
        """BOX OBBLIGATO adesso (per la pill UI): wet emergency con slick,
        danno grave attivo, o sosta pianificata a questo giro."""
        raw = raw or {}
        if self._st.get("rain_state") == "wet" \
                and not self._wet_mounted(raw):
            return True
        if self._st.get("dmg_code") in ("box_retire", "box_flat"):
            return True
        try:
            ld = int(raw.get("laps_completed") or 0)
        except (TypeError, ValueError):
            return False
        md = self._race_model or {}
        for s in (md.get("stops") or []):
            if int(s.get("lap") or 0) - ld == 1:
                return True
        return False

    # ── SANITY: legge di stato + coerenza per-frase + arbitro ────────
    def sanity_filter(self, msgs, raw):
        if not msgs:
            return msgs
        raw = raw or {}
        out = []
        for m in msgs:
            if not m:
                continue
            ok, why = True, ""
            try:
                ok, why = self._sane_one(m, raw)
            except Exception:
                ok = True
            if ok:
                out.append(m)
            else:
                self._sane_log(m, why)
        try:
            return self._arbiter(out)
        except Exception:
            return out

    # ── MODALITA' TEST dal dash (mod 3): long run / race sim / hotlap ──
    @staticmethod
    def _fnum(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _last_timeloss(self):
        """last_timeloss.json scritto dal recorder (processo UI) a fine
        giro: curva peggiore e totale. None se vecchio o assente."""
        try:
            import json as _js
            from core.paths import USER_DIR as _UD
            d = _js.loads((_UD / "last_timeloss.json")
                          .read_text(encoding="utf-8"))
            if _time.time() - float(d.get("ts") or 0) > 150.0:
                return None
            return d
        except Exception:
            return None

    def test_mode_call(self, raw, laps_done):
        """Selettore TEST dal dash (engineer_cfg): il muretto cambia
        registro. longrun = allunga lo stint di +N giri (target consumo
        e check ogni giro); racesim = simulazione gara di N minuti
        (piano + consumo al nominale); hotlap = giro secco (dopo ogni
        giro la curva peggiore dalla Time-Loss). Le mute di registro
        stanno in _sane_one."""
        raw = raw or {}
        mode = raw.get("test_mode") or None
        # ECO FREE (mod 3): risparmio LIBERO fuori dai test — il pilota
        # in gara lo attiva a mano (+N) e ha lo stesso registro gestione
        eco = int(self._fnum(raw.get("eco_free")) or 0)
        if not mode and eco > 0:
            mode = "ecofree"
        st = self._st
        # firma = modalita' + parametro: cambiare il +N RIannuncia il target
        if mode == "longrun":
            sig = (mode, int(self._fnum(raw.get("test_extra")) or 2))
        elif mode == "ecofree":
            sig = (mode, eco)
        elif mode == "racesim":
            sig = (mode, int(self._fnum(raw.get("test_race_min")) or 60))
        else:
            sig = (mode, None)
        prev_sig = st.get("tm_sig", ("__boot__", None))
        prev = prev_sig[0]
        out = []
        if sig != prev_sig:
            st["tm_sig"] = sig
            st["tm_mode"] = mode
            st["tm_lap"] = int(raw.get("laps_completed") or 0)
            st["tm_hl_lap"] = None
            st["tm_ok"] = 0
            if mode in ("longrun", "ecofree"):
                extra = sig[1]
                # consumo stimato DI LMU (stessa fonte del pannello
                # Carburante): il target combacia coi numeri del gioco,
                # cosi' il pilota imposta lo stesso +N sul volante e i
                # LED eco di LMU dicono la stessa cosa del muretto
                per = self._fnum(raw.get("lmu_per_lap"))
                ve = self._fnum(raw.get("ve_pct"))
                # SOLO BENZINA (P2/P3/GTE, bug 23/07): niente VE ->
                # stessi conti sui LITRI (il target esce in L/giro,
                # le frasi sono neutre sull'unita')
                if not (ve and ve > 1.0):
                    ve = self._fnum(raw.get("fuel"))
                tgt = laps_t = None
                if per and per > 0 and ve and ve > 1.0:
                    laps_t = ve / per + extra          # come LMU: stimati+N
                    tgt = ve / laps_t
                st["tm_target"] = tgt
                st["tm_ve_prev"] = ve
                _code_on = "eco_on" if mode == "ecofree" else "longrun_on"
                if tgt:
                    out.append(self.msg(_code_on, extra=extra,
                                        laps="%.0f" % laps_t,
                                        target="%.1f" % tgt,
                                        cur="%.1f" % per))
                else:
                    out.append(self.msg(
                        "eco_on_nodata" if mode == "ecofree"
                        else "longrun_on_nodata", extra=extra))
            elif mode == "racesim":
                mins = int(self._fnum(raw.get("test_race_min")) or 60)
                est = self._fnum(raw.get("est_lap")) \
                    or self._fnum(raw.get("best_lap"))
                per = self._fnum(raw.get("lmu_per_lap"))
                giri = int(mins * 60.0 / est) if est and est > 20.0 else None
                stops = None
                if giri and per and per > 0:
                    stops = max(0, int((giri - 1) // max(1.0, 100.0 / per)))
                st["tm_ve_prev"] = self._fnum(raw.get("ve_pct"))
                if giri is not None and stops is not None:
                    out.append(self.msg("racesim_on", minuti=mins,
                                        giri=giri, soste=stops))
                else:
                    out.append(self.msg("racesim_on_nodata", minuti=mins))
            elif mode == "hotlap":
                out.append(self.msg("hotlap_on"))
            elif prev and prev != "__boot__":
                out.append(self.msg("eco_off" if prev == "ecofree"
                                    else "test_off"))
            return [x for x in out if x]
        if not mode:
            return []
        # ── check al CAMBIO GIRO (mai in corsia/garage) ──
        ld = int(raw.get("laps_completed") or 0)
        if ld <= int(st.get("tm_lap") or 0):
            return []
        st["tm_lap"] = ld
        if raw.get("in_pits") or raw.get("garage"):
            return []
        if mode in ("longrun", "ecofree", "racesim"):
            ve = self._fnum(raw.get("ve_pct"))
            if not (ve and ve > 1.0):          # solo benzina: litri
                ve = self._fnum(raw.get("fuel"))
            prev_ve = st.get("tm_ve_prev")
            st["tm_ve_prev"] = ve
            tgt = st.get("tm_target") if mode in ("longrun", "ecofree") \
                else self._fnum(raw.get("lmu_per_lap"))
            if ve is None or prev_ve is None or not tgt:
                return []
            used = prev_ve - ve
            if used <= 0 or used > tgt * 3.0:
                return []          # rifornimento/reset: giro sporco
            # stato per i LED lico del dash (margine adattivo)
            try:
                import json as _js
                from core.paths import USER_DIR as _UD
                (_UD / "eco_state.json").write_text(
                    _js.dumps({"ts": _time.time(),
                               "target": tgt, "used": used}),
                    encoding="utf-8")
            except Exception:
                pass
            k = used / tgt
            if k > 1.06:
                return [x for x in [self.msg("test_over",
                                             used="%.1f" % used,
                                             target="%.1f" % tgt)] if x]
            if k < 0.94:
                return [x for x in [self.msg("test_margin",
                                             used="%.1f" % used,
                                             target="%.1f" % tgt)] if x]
            st["tm_ok"] = int(st.get("tm_ok") or 0) + 1
            if st["tm_ok"] % 3 == 0:
                return [x for x in [self.msg("test_good")] if x]
            return []
        if mode == "hotlap":
            data = self._last_timeloss()
            if not data:
                return []
            lap_f = data.get("lap")
            if lap_f is None or lap_f == st.get("tm_hl_lap"):
                return []
            st["tm_hl_lap"] = lap_f
            tot = self._fnum(data.get("total_s"))
            worst = data.get("worst") or []
            if tot is not None and tot <= 0.15:
                return [x for x in [self.msg("hotlap_clean")] if x]
            if worst:
                w = worst[0] or {}
                dsec = self._fnum(w.get("total_s")) or 0.0
                if dsec < 0.1:
                    return []
                fase = "in ingresso" \
                    if abs(self._fnum(w.get("entry_s")) or 0.0) >= \
                    abs(self._fnum(w.get("exit_s")) or 0.0) else "in uscita"
                num = str(w.get("corner") or "?").lstrip("T")
                return [x for x in [self.msg(
                    "hotlap_loss", curva=num,
                    dec="%.0f" % (dsec * 10.0), fase=fase)] if x]
        return []

    def _sane_one(self, m, raw):
        code = (m or {}).get("code") or ""
        # WARM-UP: appena acceso (o a sessione nuova) il muretto ASCOLTA
        # per 5 secondi prima di parlare — niente raffica d'apertura sullo
        # stato ereditato (es. app aperta a sessione gia' in corso).
        # Passa solo la sicurezza (critical: wet, danni gravi).
        born = self._st.get("born")
        if born is None:
            born = self._st["born"] = _time.monotonic()
        if (m or {}).get("level") != "critical" \
                and code not in self._ARB_BRIEFING \
                and _time.monotonic() - born < 5.0:
            return False, "warm-up: primi 5s di ascolto"
        # MACCHINA ANDATA (ritiro dichiarato): silenzio tutto tranne il ritiro
        if self._st.get("terminal") and not code.startswith("retire_"):
            return False, "terminale: silenzio (macchina andata)"
        # LEGGE INCIDENTE: dopo una botta forte, per 12s la radio parla SOLO
        # di sicurezza/danni/stato pilota — meteo, gap e coaching in quel
        # momento suonano scollegati dalla realta' (immersione).
        _cri = self._st.get("crisis_t")
        if _cri and _time.monotonic() - _cri < 12.0 \
                and (m or {}).get("level") != "critical" \
                and not code.startswith(self._LAW_CRISIS_KEEP):
            return False, "incidente in corso: solo sicurezza/danni (12s)"
        # GIALLA ATTIVA (SOLO i 500m davanti, mai i settori): niente
        # small-talk di strategia/meteo/coaching finche' il pericolo
        # e' davanti — la radio parla di sicurezza, come un muretto vero.
        _flw = raw.get("flags") or {}
        if _flw.get("yellow_dist") is not None \
                and (m or {}).get("level") != "critical" \
                and not code.startswith(self._LAW_CRISIS_KEEP):
            return False, "gialla attiva: solo sicurezza/bandiere"
        # MODALITA' TEST (dal dash): il muretto cambia REGISTRO.
        # In gestione (long run / race sim) il veleggiare e' VOLUTO:
        # mai rimproveri sul coasting. In hotlap niente consumi/strategia:
        # conta solo il giro secco.
        _tm9 = raw.get("test_mode")
        _eco9 = bool(self._fnum(raw.get("eco_free")) or 0)
        # in GESTIONE ogni critica di passo e' anti-guida: alzare prima,
        # frenare prima, portare meno velocita' E' la tecnica richiesta
        # (i LED eco di LMU dicono proprio quello). Vale per i test E per
        # l'ECO FREE in gara. Restano le sicurezze: bloccaggi, pattinamenti.
        if (_tm9 in ("longrun", "racesim") or _eco9) and code.startswith((
                "coast_corner", "brake_later", "carry_speed", "turn_slow",
                "sector_loss", "lap_slow", "debrief_improve")):
            return False, "gestione attiva: guida da risparmio, niente critiche di passo"
        if _tm9 == "hotlap" and (m or {}).get("level") != "critical" \
                and code.startswith(("fuel_", "energy_", "strat", "plan",
                                     "manage", "status_", "chk_",
                                     "tyre_manage")):
            return False, "hotlap: niente gestione, solo giro secco"
        # LEGGE CENTRALE DI STATO — prima di ogni logica di modulo
        in_lane = bool(raw.get("in_pits") or raw.get("in_pitlane")
                       or raw.get("garage"))
        if in_lane and (m or {}).get("level") != "critical" \
                and not code.startswith(self._LAW_PIT_KEEP):
            return False, "in corsia/box: solo pit, sicurezza e debrief"
        try:
            inbound = int(raw.get("pit_state") or 0) != 0
        except (TypeError, ValueError):
            inbound = False
        if inbound and (m or {}).get("level") != "critical" \
                and not code.startswith(self._LAW_PIT_KEEP):
            return False, "pit chiamato: solo pit e sicurezza"
        # TIPO SESSIONE: in quali sei solo (niente bandiere/traffico dallo
        # spotter); il traffico di rientro pit ha senso SOLO in gara.
        _kind = session_kind(raw.get("session_type"))
        if _kind == "qualy" and code.startswith(self._LAW_QUALI_MUTE):
            return False, "quali: niente bandiere/traffico (sei solo)"
        if _kind == "practice" and code.startswith(self._LAW_PRACTICE_MUTE):
            return False, "prova privata: niente riferimenti agli altri"
        # FOCUS: in quali e gara niente routine da prove/test (il muretto
        # osserva e dice l'essenziale); il debrief garage resta fuori
        # dalla GARA (li' il garage = qualcosa e' andato storto)
        if _kind in ("qualy", "race") \
                and code.startswith(self._LAW_FOCUS_MUTE):
            return False, "focus quali/gara: niente routine da prove"
        if _kind == "race" and code.startswith("debrief_"):
            return False, "gara: niente debrief da garage"
        if _kind != "race" and code.startswith(("pit_exit",)):
            return False, "pit-exit traffic: solo in gara"
        # BRIEFING SOLO PRE-VIA (gara): i briefing si dicono nella rolling
        # start; dal 1° giro completato in poi non escono piu' (distraggono).
        if _kind == "race" and code in self._ARB_BRIEFING:
            try:
                if int(raw.get("game_phase") or 0) >= 5 \
                        and int(raw.get("laps_completed") or 0) >= 1:
                    return False, "briefing: solo alla rolling start (pre-verde)"
            except (TypeError, ValueError):
                pass
        riv = raw.get("rivals") or {}

        def _gok(v):
            try:
                g = float(v)
            except (TypeError, ValueError):
                return False
            return 0.0 <= g <= 180.0
        if code in ("gap_behind", "gap_threat") \
                and not _gok(riv.get("gap_behind")):
            return False, "rivale dietro inesistente"
        if code in ("gap_ahead", "gap_undercut", "gap_pit_called",
                    "gap_closing", "gap_losing") \
                and not _gok(riv.get("gap_ahead")):
            return False, "rivale davanti inesistente"
        # frasi pro-pioggia con le wet GIA' montate: mai
        if self._wet_mounted(raw) and code in ("rain_box_now", "advise_wet"):
            return False, "wet gia' montate"
        # consiglio slick mentre piove: mai
        try:
            raining = float(raw.get("raining") or 0.0) >= 0.15
        except (TypeError, ValueError):
            raining = False
        if raining and code in ("advise_slick", "rain_dryline"):
            return False, "slick mentre piove"
        return True, ""

    _ARB_LVL = {"critical": 3, "warn": 2, "info": 1}
    _ARB_BRIEFING = ("briefing_plan", "plan_wx_arc", "plan_model_stops",
                     "plan_prelim", "briefing_laps", "briefing_strat",
                     "briefing_manage", "briefing_push", "briefing_save")

    def _arbiter(self, msgs):
        """Coerenza TRA frasi: budget sui periodici, briefing atomico."""
        if not msgs:
            return msgs
        now = _time.time()
        log = [e for e in self._st.get("emit_log", []) if now - e[0] <= 90.0]
        out = []
        for m in msgs:
            code = (m or {}).get("code") or ""
            lv = (m or {}).get("level")
            lvl = self._ARB_LVL.get(lv, 1) if not isinstance(lv, (int, float)) \
                else max(1, min(3, int(lv)))
            if code in self._ARB_BRIEFING:
                lvl = max(lvl, 2)
            if any(e[1] == code and now - e[0] < 0.5 for e in log):
                out.append(m)
                continue
            # stesso codice ripetuto entro 25s: silenzio (anti-mitraglia)
            if lvl < 3 and any(e[1] == code and now - e[0] < 25.0
                               for e in log):
                self._sane_log(m, "arbitro: ripetizione entro 25s")
                continue
            # budget: max 3 info in 20s (warn/critical passano sempre). Il tempo
            # giro e' un periodico VOLUTO ad ogni giro -> esente dal budget.
            if lvl <= 1 and code != "lap_time_call" and sum(1 for e in log
                                if e[2] <= 1 and now - e[0] <= 20.0) >= 3:
                self._sane_log(m, "arbitro: budget info esaurito")
                continue
            log.append((now, code, lvl))
            out.append(m)
        self._st["emit_log"] = log
        return out

    def _sane_log(self, m, why):
        try:
            from core import paths as _pp
            line = "[%s] SCARTATO %s: %s\n" % (
                _time.strftime("%H:%M:%S"), (m or {}).get("code"), why)
            with open(_pp.USER_DIR / "engineer_sanity.log", "a",
                      encoding="utf-8") as fh:
                fh.write(line)
        except Exception:
            pass
