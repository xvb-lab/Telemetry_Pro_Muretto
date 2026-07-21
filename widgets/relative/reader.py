"""
widgets/relative/reader.py — Lettura dati per il relative.

Mostra N auto davanti + player + N dietro, ordinate per posizione IN PISTA
(non per classifica). Il gap è "circolare": distanza in pista (mLapDist)
convertita in tempo. Traccia anche la velocità max del giro precedente.

Usa i moduli core condivisi (rest_client, shared_memory, brands).
"""
import time
from core.rest_client import RestClient
from core.shared_memory import SharedMemory
from core.brands import brand_from_vehicle

_STANDINGS_PATH = "/rest/watch/standings"

SECTOR_MAP = {"SECTOR1": 0, "SECTOR2": 1, "SECTOR3": 2}
SECTOR_LABEL = {"SECTOR1": "S1", "SECTOR2": "S2", "SECTOR3": "S3"}


def get_status(d: dict) -> str:
    fs = d.get("finish_status", "")
    if fs == "FSTAT_DQ":       return "DQ"
    if fs == "FSTAT_DNF":      return "DNF"
    if fs == "FSTAT_FINISHED": return "FIN"
    # PRIORITA': gialla > penalita' (DT/SG/PEN) > garage/pit/box
    if d.get("under_yellow"):  return d.get("yellow_sector", "S1") or "S1"
    if d.get("num_penalties", 0) > 0:
        # per il PLAYER il TIPO vero dal trace: DT / SG ...
        if d.get("is_player"):
            try:
                from core.race_control import latest_penalty_parts
                _t, _k, _r, _l = latest_penalty_parts()
                if _k == "DRIVE THROUGH":
                    return "DT"
                if _k.startswith("STOP"):
                    return "SG"
                if _k.startswith("+"):
                    return _k[1:-1] + "+"
            except Exception:
                pass
        return "PEN"
    if d.get("in_garage"):     return "GAR"
    if d.get("in_pits"):
        return "PIT"
    if d.get("pit_state", "NONE") not in ("NONE", "", None):
        return "BOX!"
    return ""


class RelativeReader:
    def __init__(self):
        self._rest = RestClient.instance()
        self._rest.subscribe(_STANDINGS_PATH)
        self._mem = SharedMemory.instance()
        # tracking velocità per slotID
        self._max_speed = {}
        # ± posizioni: posto in classe al VIA della gara, per pilota
        self._pd_base = {}
        self._pd_sess = None
        self._last_speed = {}
        self._last_laps = {}
        self._frozen_valid = {}
        self._frozen_lastlap = {}
        self._stint_base = {}
        self._last_pit_count = {}
        self._stint_time_base = {}
        self._last_inpits = {}
        self._seen_in_box = {}
        self._outlap_base = {}
        self._outlap_inpits = {}
        try:
            from core.gap_estimator import GapEstimator
            self._gap_est = GapEstimator()
        except Exception:
            self._gap_est = None
        self._gap_cache = {}        # {slot_id: gap} aggiornata 1×/sec (alleggerisce)
        self._gap_cache_t = 0.0
        self._full_cache = None     # risultato completo, ricalcolato 1×/sec
        self._full_cache_rows = None
        self._full_cache_t = 0.0

    def _read_positions(self):
        """Legge posizioni in pista (mLapDist), track_len, gialle, settori."""
        sim = self._mem._get_sim()
        if not sim:
            return {}
        try:
            si = sim.scoring.scoringInfo
            track_len = float(si.mLapDist)
            num = int(si.mNumVehicles)
            positions = {}
            yellow_phases = {}
            from pyLMUSharedMemory.lmu_data import MAX_MAPPED_VEHICLES as _MAX
            for i in range(min(num, _MAX)):
                v = sim.scoring.vehScoringInfo[i]
                positions[int(v.mID)] = float(v.mLapDist)
                yellow_phases[int(v.mID)] = (int(v.mIndividualPhase) == 10 or bool(v.mUnderYellow))
            sector_flags = [int(si.mSectorFlag[i]) for i in range(3)]
            from core.config import get_config
            _wc = get_config().widget("relative")
            _show_tyre = _wc.get("show_tyre", True)
            _show_wear = _wc.get("show_wear", True)
            _show_tl = _wc.get("show_track_limits", True)
            _show_sectors = _wc.get("show_sectors", True)
            _show_lap = _wc.get("show_lap", True)
            _all = self._mem.get_all_maps()                  # UNA passata condivisa
            compounds = _all["compounds"] if _show_tyre else {}
            compounds4 = _all["compounds4"] if _show_tyre else {}
            lap_valid = _all["lap_valid"] if _show_lap else {}
            track_limits = _all["track_limits"] if _show_tl else {}
            pitstops = _all["pitstops"]
            car_states = _all["car_states"]
            sectors = _all["sectors"] if _show_sectors else {}
            tyre_wear = _all["wear"] if _show_wear else {}
            return {
                "track_len": track_len,
                "positions": positions,
                "yellow_phases": yellow_phases,
                "sector_flags": sector_flags,
                "compounds": compounds,
                "compounds4": compounds4,
                "lap_valid": lap_valid,
                "track_limits": track_limits,
                "pitstops": pitstops,
                "car_states": car_states,
                "sectors": sectors,
                "tyre_wear": tyre_wear,
            }
        except Exception:
            return {}

    def _track_speed(self, raw):
        """Aggiorna max speed e last-lap max speed per slotID."""
        for d in raw:
            sid = d.get("slotID", -1)
            laps = int(d.get("lapsCompleted", 0) or 0)   # intero: max congelato 1×/giro
            vel = d.get("carVelocity", {})
            spd = float(vel.get("velocity", 0)) if isinstance(vel, dict) else 0
            if sid not in self._last_laps:
                self._last_laps[sid] = laps
                self._max_speed[sid] = spd
                self._last_speed[sid] = 0
            elif laps > self._last_laps[sid]:
                self._last_speed[sid] = self._max_speed[sid]
                self._max_speed[sid] = spd
                self._last_laps[sid] = laps
            else:
                if spd > self._max_speed.get(sid, 0):
                    self._max_speed[sid] = spd

    def _calc_stint(self, sid, laps_done, num_pit, state=None):
        """Stint affidabile: parte solo da evento osservato (uscita box o pit).
        Se l'auto era già in pista al primo avvistamento -> None (non misurabile)."""
        import time as _t
        now = _t.time()
        st = state or {}
        in_pits = st.get("in_pits", False)
        garage = st.get("garage", False)
        moving = st.get("moving", True)
        is_player = st.get("is_player", False)

        prev_pit = self._last_pit_count.get(sid)
        prev_inpits = self._last_inpits.get(sid)
        first_time = sid not in self._last_inpits
        on_track = (not in_pits) and (not garage) and moving
        in_box = in_pits or garage
        started = sid in self._stint_time_base

        if prev_pit is not None and num_pit > prev_pit:
            started = False
            self._stint_time_base.pop(sid, None); self._stint_base.pop(sid, None)
        if in_box:
            started = False
            self._stint_time_base.pop(sid, None); self._stint_base.pop(sid, None)
            self._seen_in_box[sid] = True

        if not started and on_track:
            seen_box = self._seen_in_box.get(sid, False)
            came_from_box = (prev_inpits is True and not in_pits)
            pit_increased = (prev_pit is not None and num_pit > prev_pit)
            if seen_box or came_from_box or pit_increased or is_player:
                self._stint_time_base[sid] = now
                self._stint_base[sid] = laps_done

        self._last_pit_count[sid] = num_pit
        self._last_inpits[sid] = in_pits

        if sid in self._stint_time_base:
            giri = max(0, laps_done - self._stint_base.get(sid, laps_done))
            secs = max(0, now - self._stint_time_base.get(sid, now))
            return giri, secs
        return None, None

    def read(self, rows_each_side=2):
        """-> lista di righe (alcune None per slot vuoti) lunga 2*rows+1.
        Il grosso del lavoro è calcolato 1×/sec; la velocità è comunque
        campionata a ogni tick per il picco di top speed."""
        raw = self._rest.get(_STANDINGS_PATH)
        if not raw:
            return []

        self._track_speed(raw)   # SEMPRE: cattura il picco top speed

        now = time.monotonic()
        if (self._full_cache is not None and self._full_cache_rows == rows_each_side
                and (now - self._full_cache_t) < 0.1):
            return self._full_cache

        mmap = self._read_positions()
        track_len = mmap.get("track_len", 0)
        positions = mmap.get("positions", {})
        compounds = mmap.get("compounds", {})
        compounds4 = mmap.get("compounds4", {})
        lap_valid_map = mmap.get("lap_valid", {})
        tl_map = mmap.get("track_limits", {})
        pit_map = mmap.get("pitstops", {})
        cs_map = mmap.get("car_states", {})
        sec_map = mmap.get("sectors", {})
        wear_map = mmap.get("tyre_wear", {})
        yellow_phases = mmap.get("yellow_phases", {})
        sector_flags = mmap.get("sector_flags", [11, 11, 11])

        def fmt_name(s):
            parts = s.upper().split()
            return (parts[0][0] + "." + " ".join(parts[1:])) if len(parts) >= 2 else s.upper()

        def is_yellow(d):
            sid = d.get("slotID", -1)
            flag = d.get("flag", "GREEN")
            si = SECTOR_MAP.get(d.get("sector", ""), -1)
            sec_y = si >= 0 and sector_flags[si] == 1
            vel = d.get("carVelocity", {})
            spd = float(vel.get("velocity", 999)) if isinstance(vel, dict) else 999
            return (flag == "YELLOW" or bool(d.get("underYellow"))
                    or yellow_phases.get(sid, False) or (sec_y and spd < 10))

        def make_driver(d):
            vname = d.get("vehicleName", "")
            ve = d.get("veFraction", None)
            if ve is not None and ve > 0:
                v_energy = round(ve * 100, 1)
                energy_kind = "ve"
            else:
                ff = d.get("fuelFraction", None)
                v_energy = round(ff * 100, 1) if ff is not None and ff > 0 else None
                energy_kind = "fuel" if v_energy is not None else ""
            yel = is_yellow(d)
            sid = d.get("slotID", -1)
            _stint_g, _stint_s = self._calc_stint(int(sid), int(d.get("lapsCompleted", 0)), pit_map.get(int(sid), 0), cs_map.get(int(sid)))
            # OUTLAP: dall'uscita pit/box fino al primo taglio del traguardo
            _laps_now = int(d.get("lapsCompleted", 0))
            _cs = cs_map.get(int(sid)) or {}
            _inpits_now = bool(_cs.get("in_pits", False)) or bool(_cs.get("garage", False))
            _prev_op = self._outlap_inpits.get(int(sid))
            if _inpits_now:
                self._outlap_base[int(sid)] = _laps_now
            elif _prev_op and not _inpits_now:
                self._outlap_base[int(sid)] = _laps_now
            _is_outlap = False
            if int(sid) in self._outlap_base:
                if _laps_now <= self._outlap_base[int(sid)]:
                    _is_outlap = True
                else:
                    self._outlap_base.pop(int(sid), None)
            self._outlap_inpits[int(sid)] = _inpits_now
            last_lap_t = float(d.get("lastLapTime", -1))
            live_valid = lap_valid_map.get(int(sid), True)
            prev_ll = self._frozen_lastlap.get(sid)
            if prev_ll is None or last_lap_t != prev_ll:
                self._frozen_lastlap[sid] = last_lap_t
                self._frozen_valid[sid] = live_valid
            frozen_valid = self._frozen_valid.get(sid, live_valid)
            return {
                "name":          fmt_name(d.get("driverName", "")),
                "car_number":    str(d.get("carNumber", "") or ""),
                "veh_name":      vname,
                "brand":         brand_from_vehicle(vname),
                "place_class":   d.get("carPosition", d.get("position", 0)),
                "last_lap":      last_lap_t,
                "best_lap":      float(d.get("bestLapTime", -1)),
                "gap_leader":    0.0,
                "laps_behind":   0,
                "is_player":     bool(d.get("player", False)),
                "in_pits":       d.get("pitting", False),
                "in_garage":     bool(d.get("inGarageStall", False)),
                "pit_state":     d.get("pitState", "NONE"),
                "finish_status": d.get("finishStatus", "FSTAT_NONE"),
                "num_penalties": int(d.get("penalties", 0) or 0),
                "under_yellow":  yel,
                "yellow_sector": (SECTOR_LABEL.get(d.get("sector", ""), "S1") if yel else ""),
                "v_energy":      v_energy,
                "energy_kind":   energy_kind,
                "is_overall_best": False,
                "is_fastest_last": False,
                "tyre":          compounds.get(int(sid), ""),
                "tyre4":         compounds4.get(int(sid), None),
                "lap_valid":     frozen_valid,
                "track_limits":  tl_map.get(int(sid), None),
                "num_pit":       pit_map.get(int(sid), 0),
                "laps_done":     int(d.get("lapsCompleted", 0)),
                "stint_time":    _stint_s,
                "outlap":        _is_outlap,
                "tyre_wear":     wear_map.get(int(sid), None),
                "sectors":       sec_map.get(int(sid), None),
                "car_class":     d.get("carClass", ""),
                "slot_id":       sid,
                "speed_kmh":     round(self._last_speed.get(sid, 0) * 3.6),
            }

        drivers = [make_driver(d) for d in raw]

        # posizione di classe
        from collections import defaultdict
        by_class = defaultdict(list)
        for d_raw in raw:
            by_class[d_raw.get("carClass", "")].append(d_raw)
        class_pos = {}
        for cls, members in by_class.items():
            for i, m in enumerate(sorted(members, key=lambda x: x.get("position", 99))):
                class_pos[m.get("slotID", -1)] = i + 1
        for d in drivers:
            d["place_class"] = class_pos.get(d["slot_id"], d["place_class"])
        # ± posizioni dal via (stile TinyPedal): baseline azzerata al cambio
        # sessione, delta solo in GARA
        try:
            _pd_st, _, _ = self._mem.read_session()
        except Exception:
            _pd_st = None
        if _pd_st != self._pd_sess:
            self._pd_sess = _pd_st
            self._pd_base.clear()
        _pd_race = 10 <= int(_pd_st or 0) <= 13
        for d in drivers:
            d["pos_delta"] = ((self._pd_base.setdefault(d["slot_id"], d["place_class"])
                               - d["place_class"]) if _pd_race else None)

        # fastest last lap viola
        valid = [d["last_lap"] for d in drivers if d["last_lap"] > 0]
        if valid:
            fl = min(valid)
            for d in drivers:
                d["is_fastest_last"] = d["last_lap"] == fl

        valid_best = [d["best_lap"] for d in drivers if d["best_lap"] > 0]
        if valid_best:
            ob = min(valid_best)
            for d in drivers:
                d["is_overall_best"] = d["best_lap"] == ob

        # fastest last per classe
        class_fastest = {}
        for d in drivers:
            if d["last_lap"] > 0 and d.get("lap_valid", True):
                cc = d.get("car_class", "")
                if cc not in class_fastest or d["last_lap"] < class_fastest[cc]:
                    class_fastest[cc] = d["last_lap"]

        # doppiaggio (solo GARA, solo stessa classe del player, confronto giri):
        #  - BLU  = l'ho doppiato io (ha meno giri di me)
        #  - ROSA = mi ha doppiato (ha più giri di me)
        try:
            _stype, _, _ = self._mem.read_session()
            _is_race = 10 <= int(_stype) <= 13
        except Exception:
            _is_race = False
        _pl = next((d for d in drivers if d.get("is_player")), None)
        my_laps = _pl.get("laps_done", 0) if _pl else 0
        my_cls = _pl.get("car_class", "") if _pl else ""
        for d in drivers:
            d["lap_status"] = ""
            if not _is_race:
                continue
            if d.get("is_player"):
                continue
            if d.get("car_class", "") != my_cls:
                continue
            dl = d.get("laps_done", 0)
            if dl < my_laps:
                d["lap_status"] = "lapped"      # blu: l'ho doppiato
            elif dl > my_laps:
                d["lap_status"] = "lapping"     # rosa: mi ha doppiato

        # stato colore last lap:
        # rosso=invalido > fucsia=fastest classe > verde=migliorato > giallo=piu lento
        for d in drivers:
            last = d["last_lap"]
            best = d["best_lap"]
            cc = d.get("car_class", "")
            if last <= 0:
                d["last_state"] = ""
            elif not d.get("lap_valid", True):
                d["last_state"] = "invalid"
            elif cc in class_fastest and last == class_fastest[cc]:
                d["last_state"] = "fastclass"
            elif best > 0 and last <= best:
                d["last_state"] = "improved"
            else:
                d["last_state"] = "slower"

        # top speed più alta (fucsia)
        speeds = [d.get("speed_kmh", 0) for d in drivers if d.get("speed_kmh", 0) > 0]
        if speeds:
            top = max(speeds)
            for d in drivers:
                d["is_top_speed"] = d.get("speed_kmh", 0) == top
        else:
            for d in drivers:
                d["is_top_speed"] = False

        # best di settore (colori)
        best_sec = [None, None, None]
        for d in drivers:
            sec = d.get("sectors")
            if not sec:
                continue
            for si in range(3):
                t = sec["last"][si] if si < len(sec["last"]) else -1
                if t and t > 0:
                    if best_sec[si] is None or t < best_sec[si]:
                        best_sec[si] = t

        # stato settori LIVE: accende ogni quadratino appena il settore è chiuso
        # nel giro CORRENTE (usa 'cur' + 'sector'), non a fine giro.
        # sector: 0=S3 (in S3), 1=S1 (in S1), 2=S2 (in S2)
        def _state_for(last_t, best_t, idx):
            if not last_t or last_t <= 0:
                return ""
            if best_sec[idx] is not None and last_t <= best_sec[idx]:
                return "fastest"
            if best_t and best_t > 0 and last_t <= best_t:
                return "improved"
            return "normal"

        for d in drivers:
            sec = d.get("sectors")
            if not sec:
                d["sector_states"] = ["", "", ""]
                continue
            cur = sec.get("cur", [-1, -1])
            last = sec.get("last", [-1, -1, -1])
            best = sec.get("best", [-1, -1, -1])
            in_sector = sec.get("sector", 1)   # 0=S3,1=S1,2=S2
            states = ["", "", ""]
            if in_sector != 1 and len(cur) > 0 and cur[0] > 0:
                states[0] = _state_for(cur[0], best[0] if len(best) > 0 else -1, 0)
            if in_sector == 0 and len(cur) > 1 and cur[1] > 0:
                states[1] = _state_for(cur[1], best[1] if len(best) > 1 else -1, 1)
            if in_sector == 1:
                for si in range(3):
                    lt = last[si] if si < len(last) else -1
                    bt = best[si] if si < len(best) else -1
                    if lt and lt > 0:
                        states[si] = _state_for(lt, bt, si)
            cur_idx = {0: 2, 1: 0, 2: 1}.get(in_sector, None)
            if cur_idx is not None and not states[cur_idx]:
                states[cur_idx] = "current"
            d["sector_states"] = states

        player_d = next((d for d in drivers if d["is_player"]), None)
        if not player_d:
            return []

        n = rows_each_side
        # gap circolare per posizione in pista — calcolato 1×/sec (alleggerisce il
        # thread; il gap a tempo cambia lentamente, l'aggiornamento a 1s è impercettibile)
        if track_len > 0:
            now = time.monotonic()
            if (now - self._gap_cache_t) >= 0.1 or not self._gap_cache:
                pp = positions.get(player_d["slot_id"], 0)
                lt = player_d["last_lap"]
                spd = (track_len / lt) if lt > 0 else 50.0

                # gap a TEMPO (no elastico): confronta l'istante in cui le due auto
                # passano lo stesso punto. Fallback spaziale finché lo storico si riempie.
                tl_t, totals = self._mem.get_totals()
                if self._gap_est is not None:
                    try:
                        self._gap_est.update(totals)
                    except Exception:
                        pass
                p_sid = player_d["slot_id"]
                p_total = totals.get(p_sid)

                def circ(d):
                    # Gap RELATIVE = posizione IN PISTA (mLapDist), avvolta a
                    # ±mezzo giro. Indipendente da classe e doppiaggi: un'auto
                    # fisicamente accanto a te è ~0 anche se è a ±1 giro.
                    # (Niente distanza cumulativa: altrimenti i doppiati/doppiatori
                    #  vicini risultavano lontani ~un giro e sparivano.)
                    o_sid = d["slot_id"]
                    delta = (positions.get(o_sid, 0) - pp) % track_len
                    if delta > track_len / 2:
                        delta -= track_len
                    # gap a TEMPO (no elastico): istante in cui l'altra auto passa
                    # lo STESSO punto (come standings). Argomenti riportati entro
                    # ±mezzo giro per conservare la semantica RELATIVE qui sopra.
                    if self._gap_est is not None and p_total is not None:
                        o_total = totals.get(o_sid)
                        if o_total is not None:
                            try:
                                if delta >= 0:      # altro DAVANTI di `delta` metri
                                    g = self._gap_est.gap(
                                        p_sid, o_sid, o_total - delta, o_total)
                                else:               # altro DIETRO di |delta| metri
                                    g = self._gap_est.gap(
                                        p_sid, o_sid, p_total, p_total + delta)
                            except Exception:
                                g = None
                            if g is not None:
                                return g
                    # fallback spaziale finché lo storico si riempie
                    return delta / spd

                self._gap_cache = {d["slot_id"]: circ(d)
                                   for d in drivers if not d["is_player"]}
                self._gap_cache_t = now

            gc = self._gap_cache
            others = [(d, gc[d["slot_id"]]) for d in drivers
                      if not d["is_player"] and d["slot_id"] in gc]
            # opzione: nascondi auto in garage (default ON)
            try:
                from core.config import get_config
                _wc2 = get_config().widget("relative")
                _hide_gar = _wc2.get("hide_garage", True)
                _cls_only = _wc2.get("class_only", False)
                _no_lap = _wc2.get("no_lapped", False)
            except Exception:
                _hide_gar = True
                _cls_only = False
                _no_lap = False
            if _hide_gar:
                others = [(d, g) for d, g in others if not d.get("in_garage", False)]
            # opzione: solo la MIA classe (esclude le altre dal relative)
            if _cls_only:
                _mycls = player_d.get("car_class", "")
                others = [(d, g) for d, g in others
                          if d.get("car_class", "") == _mycls]
            # opzione: NIENTE doppiati (solo chi e' nel mio stesso giro)
            if _no_lap:
                _myl = int(player_d.get("laps_done", 0) or 0)
                others = [(d, g) for d, g in others
                          if abs(int(d.get("laps_done", 0) or 0)
                                 - _myl) < 1]
            ahead = sorted([(d, g) for d, g in others if g > 0], key=lambda x: x[1])[:n][::-1]
            behind = sorted([(d, g) for d, g in others if g <= 0], key=lambda x: -x[1])[:n]
        else:
            ahead = []
            behind = []

        while len(ahead) < n:
            ahead.insert(0, (None, None))
        while len(behind) < n:
            behind.append((None, None))

        slots = [a[0] for a in ahead] + [player_d] + [b[0] for b in behind]
        gaps = [a[1] for a in ahead] + [None] + [b[1] for b in behind]

        out = []
        for d, gap in zip(slots, gaps):
            if d is None:
                out.append(None)
                continue
            if gap is not None:
                d["gap_leader"] = abs(gap)
                d["_gap_sign"] = "+" if gap > 0 else "-"
                d["laps_behind"] = 0
            else:
                d["gap_leader"] = 0
            out.append(d)
        self._full_cache = out
        self._full_cache_rows = rows_each_side
        self._full_cache_t = now
        return out
