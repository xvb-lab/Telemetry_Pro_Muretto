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
    """Tempo giro PARLATO: '1 e 52 basso/alto'; sotto il minuto '54 e 8'.
    Con l'opzione radio 'lap_time_tenths': preciso, '1 e 52 e 3'."""
    try:
        s = float(s)
    except (TypeError, ValueError):
        return str(s)
    m = int(s // 60)
    sec_f = s - m * 60
    sec = int(sec_f)
    if m == 0:
        dec = int(round((sec_f - sec) * 10))
        if dec >= 10:
            sec += 1
            dec = 0
        return "%d e %d" % (sec, dec)
    try:
        from core.engineer_cfg import load as _plc
        if _plc().get("lap_time_tenths"):
            return "%d e %02d e %d" % (m, sec, int((sec_f - sec) * 10))
    except Exception:
        pass
    qual = "alto" if (sec_f - sec) >= 0.5 else "basso"
    return "%d e %02d %s" % (m, sec, qual)


class Engineer:
    """Il cervello. Stato in self._st (dict namespaced): niente foresta di
    attributi, reset di sessione = un clear."""

    _LANGS = ("it", "en", "es", "fr")
    _PACE_MARGIN = 1.025

    # ── LEGGE CENTRALE DI STATO (il centro della ragnatela) ──────────
    # In corsia/box/garage: le frasi da pista libera non hanno senso.
    _LAW_PIT_MUTE = ("gap_", "pos_", "blue_", "traffic_", "lock_",
                     "sector_", "lap_fast", "lap_slow", "lap_time",
                     "theo_", "quali_", "fast_class", "grip_", "temp_",
                     "on_pace", "under_pace", "over_pace", "pace_")
    # Pit CHIAMATO (stai rientrando): niente famiglia gap/attacco.
    _LAW_INBOUND_MUTE = ("gap_", "pos_attack", "pos_edge")

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

    def msg(self, code, **kw):
        m = self._msgs.get(code)
        if not m:
            return None
        if self.lang != "it":
            variants = m.get("variants_%s" % self.lang)
            text = _rnd.choice(variants) if variants else \
                (m.get(self.lang) or m.get("en") or m.get("it") or code)
        else:
            variants = m.get("variants_it")
            text = _rnd.choice(variants) if variants else \
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
            cond = prof.get("wet" if self._wet_mounted(raw) else "dry") or {}
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
        """PIOGGIA IN DIRETTA — la chiamata SACRA. Tre stati sulla MEDIA
        bagnato (conservativa): dry <0.10, damp 0.10-0.25, wet >0.25.
        dry->wet con slick montate = ORDINE box wet. Isteresi 2 letture."""
        raw = raw or {}
        try:
            w = float(raw.get("wetness") or 0.0)
            rn = float(raw.get("raining") or 0.0)
        except (TypeError, ValueError):
            return []
        state = "wet" if (w > 0.25 or rn >= 0.4) else \
            ("damp" if w > 0.10 or rn >= 0.15 else "dry")
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
        """Danni GRAVI: ruota persa / foratura / carrozzeria seria =
        chiamata di sicurezza. Una volta per danno, riarmo a pulito."""
        raw = raw or {}
        woff = any(bool(x) for x in (raw.get("wheel_off") or []))
        flat = any(bool(x) for x in (raw.get("wheel_flat") or []))
        parts = bool(raw.get("parts_off"))
        dent = any(int(x or 0) >= 2 for x in (raw.get("dent_sev") or []))
        code = ("box_retire" if woff else "box_flat" if flat
                else "box_damage" if (parts or dent) else None)
        if code is None:
            self._st.pop("dmg_code", None)
            return []
        if code == self._st.get("dmg_code"):
            return []
        self._st["dmg_code"] = code
        return [self.msg(code)]

    def aero_call(self, raw):
        """Danno AERO e SOSPENSIONI dai wearables LMU: informazione con
        la conseguenza spiegata, la scelta e' del pilota."""
        raw = raw or {}
        out = []
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
            elif lvl > prev:
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
                if v >= 0.10 and i not in said:
                    said.add(i)
                    out.append(self.msg("susp_damage", ruota=W[i],
                                        pct=int(round(v * 100))))
                elif v < 0.05 and i in said:
                    said.discard(i)
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
            self._st["imp_pend"] = {
                "t": now, "aero": float(raw.get("aero") or 0.0),
                "dent": sum(int(x or 0) for x in (raw.get("dent_sev") or []))}
            return []
        if pend and now - pend["t"] >= 3.0:
            self._st.pop("imp_pend", None)
            if now - self._st.get("imp_said_t", 0.0) < 30.0:
                return []
            clean = (float(raw.get("aero") or 0.0) <= pend["aero"] + 0.005
                     and sum(int(x or 0) for x in (raw.get("dent_sev") or []))
                     <= pend["dent"]
                     and not any(bool(x) for x in (raw.get("wheel_off") or []))
                     and not any(bool(x) for x in (raw.get("wheel_flat") or []))
                     and not raw.get("parts_off"))
            if clean:
                self._st["imp_said_t"] = now
                return [self.msg("contact_ok")]
        return []

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
        if ydist is not None and self._st.get("flag_state") != "yellow":
            self._st["flag_state"] = "yellow"
            if not own:
                out.append(self.msg("local_yellow",
                                    dist=int(round(float(ydist) / 50.0) * 50)))
        elif ydist is None and self._st.get("flag_state") == "yellow":
            self._st["flag_state"] = None
        n_blue = int(fl.get("blue_count")
                     or (1 if fl.get("blue_class") else 0))
        if n_blue > 0 and not self._st.get("blue_on"):
            now = _time.monotonic()
            if now - self._st.get("blue_t", 0.0) >= 20.0:
                self._st["blue_on"] = True
                self._st["blue_t"] = now
                my = (class_tag(raw.get("car_class") or "")
                      or self._cat or "").upper()
                bt = (class_tag(str(fl.get("blue_class") or "")) or "").upper()
                # nome PRONUNCIABILE: "HY" detto dalla voce diventa
                # "acca ipsilon" — si parla per nome classe
                _spk = {"HY": "Hypercar", "P2": "LMP2",
                        "P3": "LMP3", "GTE": "GTE"}.get(bt, bt)
                if n_blue > 1:
                    out.append(self.msg("blue_flag_multi", n=n_blue,
                                        classe=_spk if bt else ""))
                elif bt and bt != my:
                    out.append(self.msg("blue_flag", classe=_spk))
                else:
                    out.append(self.msg("blue_flag_simple"))
        elif n_blue == 0:
            self._st["blue_on"] = False
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
        names = {0: self._L("verde", "green", "verde", "verte"),
                 1: self._L("poco gommata", "low on rubber",
                            "con poca goma", "peu gommee"),
                 2: self._L("mediamente gommata", "medium rubbered",
                            "con goma media", "moyennement gommee"),
                 3: self._L("ben gommata", "well rubbered-in",
                            "bien engomada", "bien gommee"),
                 4: self._L("satura di gomma", "saturated with rubber",
                            "saturada de goma", "saturee de gomme")}
        if prev is None:
            return [self.msg("grip_status", stato=names[g])]
        return [self.msg("grip_up" if g > prev else "grip_down",
                         stato=names[g])]

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
            cond = prof.get("wet" if wet else "dry") or {}
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
            return [self.msg("last_lap")]
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
        """Fine sessione: una volta, al TUO traguardo (gara) o tempo zero."""
        raw = raw or {}
        if self._st.get("end_said"):
            return []
        fl = raw.get("flags") or {}
        phase = int(raw.get("game_phase") or 0)
        is_race = session_kind(raw.get("session_type")) == "race"
        ended = bool(fl.get("finished")) and phase >= 5 if is_race else \
            (bool(fl.get("checkered")) and phase >= 5)
        if not ended:
            return []
        self._st["end_said"] = True
        return [self.msg("session_end")]

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
        said = self._st.get("af_said")
        if said is not None and abs(int(pct) - int(said)) < 5:
            return []
        self._st["af_said"] = int(pct)
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
            if bmax > b_over and not self._st.get("bk_hot"):
                self._st["bk_hot"] = True
                out.append(self.msg("brakes_hot"))
            elif bmax < b_over - 30.0:
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
        alternati). Info budgetate dall'arbitro."""
        raw = raw or {}
        if not laps_done or laps_done - self._st.get("su_lap", -9) < 5:
            return []
        self._st["su_lap"] = laps_done
        flip = self._st["su_flip"] = not self._st.get("su_flip", False)
        if flip:
            tw = raw.get("tyre_wear")
            try:
                worst = min(float(x) for x in (tw or []) if x is not None)
            except (TypeError, ValueError):
                return []
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
        """Posizione di classe: guadagno/perdita, una per cambio."""
        raw = raw or {}
        riv = raw.get("rivals") or {}
        try:
            pos = int(riv.get("class_place") or 0)
        except (TypeError, ValueError):
            return []
        if pos <= 0:
            return []
        prev = self._st.get("pos_prev")
        self._st["pos_prev"] = pos
        if prev is None or pos == prev:
            return []
        now = _time.monotonic()
        if now - self._st.get("pos_t", 0.0) < 8.0:
            return []
        self._st["pos_t"] = now
        _q = session_kind(raw.get("session_type")) == "qualy"
        if pos == 1:
            code = "pos_pole" if _q else "pos_lead"
        elif pos < prev:
            code = "pos_gain"
        else:
            code = "pos_loss"
        return [self.msg(code, pos="P%d" % pos, prev="P%d" % prev)]

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
            cond = prof.get("dry") or {}
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
            return []       # azzerato (penalita' scontata o reset sessione)
        # steps AUMENTATI. pen (mTrackLimitsStepsPerPenalty) e' la SOGLIA:
        # penalita' quando steps >= pen; 'left' = punti che restano.
        if pen > 0:
            left = pen - steps
            if left <= 0:
                return [self.msg("tlimits_pen")]
            if left <= 2:
                return [self.msg("tlimits_warn", left=left)]
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
        # LEGGE CENTRALE DI STATO — prima di ogni logica di modulo
        in_lane = bool(raw.get("in_pits") or raw.get("in_pitlane")
                       or raw.get("garage"))
        if in_lane and code.startswith(self._LAW_PIT_MUTE):
            return False, "legge stato: player in corsia/box"
        try:
            inbound = int(raw.get("pit_state") or 0) != 0
        except (TypeError, ValueError):
            inbound = False
        if inbound and code.startswith(self._LAW_INBOUND_MUTE):
            return False, "legge stato: pit chiamato"
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
                     "plan_prelim")

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
            # budget: max 3 info in 20s (warn/critical passano sempre)
            if lvl <= 1 and sum(1 for e in log
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
