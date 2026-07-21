"""
widgets/standings/reader.py — Lettura e normalizzazione dati standings.

Usa i moduli core condivisi (rest_client, shared_memory, brands).
Logica di filtro/ordinamento/gialle/compound identica all'originale
lmu_standings.py, solo riorganizzata sopra la base condivisa.
"""
import time
from core.rest_client import RestClient
from core.shared_memory import SharedMemory
from core.brands import brand_from_vehicle

_STANDINGS_PATH = "/rest/watch/standings"

SECTOR_MAP = {"SECTOR1": 0, "SECTOR2": 1, "SECTOR3": 2}
SECTOR_LABEL = {"SECTOR1": "S1", "SECTOR2": "S2", "SECTOR3": "S3"}


def _class_rank(cls: str) -> int:
    """Ordine fisso delle classi: HY -> LMP2 -> LMP3 -> GT3 -> GTE."""
    up = (cls or "").upper()
    if "HYPER" in up or "LMH" in up or "LMDH" in up or up == "HYPER":
        return 0
    if "LMP2" in up or "P2" in up:
        return 1
    if "LMP3" in up or "P3" in up:
        return 2
    if "GT3" in up:
        return 3
    if "GTE" in up:
        return 4
    return 5


def get_status(d: dict) -> str:
    fs = d["finish_status"]
    if fs == "FSTAT_DQ":       return "DQ"
    if fs == "FSTAT_DNF":      return "DNF"
    if fs == "FSTAT_FINISHED": return "FIN"
    # PRIORITA': penalita' (DT/SG/PEN) > garage/pit/box > gialla
    # (la gialla di settore ha la MINIMA priorita': qualsiasi altra
    # voce la spegne — se sei in pit o penalizzato conta quello)
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
    if d["in_garage"]:         return "GAR"
    # fisicamente in pit lane (o garage box)
    if d["in_pits"]:
        return "PIT"
    # chiamata pit: ha richiesto i box ma è ancora in pista
    if d["pit_state"] not in ("NONE", "", None):
        return "BOX!"
    if d.get("under_yellow"):
        return d.get("yellow_sector", "S1") or "S1"
    return ""


class StandingsReader:
    def __init__(self):
        self._rest = RestClient.instance()
        self._rest.subscribe(_STANDINGS_PATH)
        self._mem = SharedMemory.instance()
        from core.config import get_config
        self._config = get_config()
        # tracking velocità max per slotID (come il relative)
        self._max_speed = {}
        self._last_speed = {}
        self._last_laps = {}
        # validità last lap "congelata": {sid: bool}, aggiornata solo al cambio giro
        self._frozen_valid = {}
        self._frozen_lastlap = {}
        # stint: giri al momento dell'ultimo pit, per slotID
        self._stint_base = {}     # {sid: laps_done all'ultimo pit}
        self._last_pit_count = {} # {sid: num_pit visto}
        self._stint_time_base = {} # {sid: timestamp inizio stint}
        self._last_inpits = {}     # {sid: era in pit l'ultima volta}
        self._seen_in_box = {}
        # ± posizioni: posto in classe al VIA della gara, per pilota
        self._pd_base = {}
        self._pd_sess = None     # {sid: l'ho vista in box durante la sessione}
        self._outlap_base = {}     # {sid: laps all'uscita box, per rilevare outlap}
        self._outlap_inpits = {}   # {sid: era in box l'ultima volta (per outlap)}
        try:
            from core.gap_estimator import GapEstimator
            self._gap_est = GapEstimator()
        except Exception:
            self._gap_est = None
        self._race_gap_cache = {}   # {slot_id: gap} aggiornata 1×/sec
        self._race_gap_t = 0.0
        self._full_cache = None     # risultato completo, ricalcolato 1×/sec
        self._full_cache_t = 0.0

    def _track_speed(self, raw):
        for d in raw:
            sid = d.get("slotID", -1)
            laps = int(d.get("lapsCompleted", 0) or 0)   # intero: il max va congelato 1×/giro
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

    def _view_mode(self) -> str:
        return self._config.widget("standings").get("view_mode", "class")

    def _calc_stint(self, sid, laps_done, num_pit, state=None):
        """Ritorna (giri_stint, tempo_stint_sec) oppure (None, None) se non
        misurabile (auto già in pista al primo avvistamento: non so da quando gira).

        Logica:
        - lo stint parte SOLO da un evento osservato: uscita box->pista, oppure
          aumento del pit count durante l'osservazione.
        - se vedo un'auto già in pista la prima volta (mai vista in box prima),
          NON conto: ritorno None (mostrato vuoto), perché non so da quanto gira.
        - reset a ogni pit stop / rientro box/garage.
        """
        import time as _t
        now = _t.time()
        st = state or {}
        in_pits = st.get("in_pits", False)
        garage = st.get("garage", False)
        moving = st.get("moving", True)
        is_player = st.get("is_player", False)

        prev_pit = self._last_pit_count.get(sid)
        prev_inpits = self._last_inpits.get(sid)
        first_time = sid not in self._last_inpits   # mai vista prima

        on_track = (not in_pits) and (not garage) and moving
        in_box = in_pits or garage

        started = sid in self._stint_time_base

        # RESET su pit stop (cambio gomme) o rientro box/garage
        if prev_pit is not None and num_pit > prev_pit:
            started = False
            self._stint_time_base.pop(sid, None); self._stint_base.pop(sid, None)
        if in_box:
            started = False
            self._stint_time_base.pop(sid, None); self._stint_base.pop(sid, None)
            self._seen_in_box[sid] = True   # ora l'ho vista in box

        # AVVIO solo da evento osservato:
        # 1) l'ho vista in box e ora è uscita (uscita pit/garage affidabile)
        # 2) il suo pit count è aumentato mentre la osservavo
        if not started and on_track:
            seen_box = self._seen_in_box.get(sid, False)
            came_from_box = (prev_inpits is True and not in_pits)
            pit_increased = (prev_pit is not None and num_pit > prev_pit)
            if seen_box or came_from_box or pit_increased or is_player:
                self._stint_time_base[sid] = now
                self._stint_base[sid] = laps_done
            elif first_time:
                # primo avvistamento già in pista (avversario): non so da quanto gira
                pass

        self._last_pit_count[sid] = num_pit
        self._last_inpits[sid] = in_pits

        if sid in self._stint_time_base:
            giri = max(0, laps_done - self._stint_base.get(sid, laps_done))
            secs = max(0, now - self._stint_time_base.get(sid, now))
            return giri, secs
        return None, None

    def read(self):
        """-> (drivers, player_class, session_type, remaining). Il grosso del
        lavoro è calcolato 1×/sec (alleggerisce thread/memoria); la velocità è
        comunque campionata a ogni tick per catturare il picco di top speed."""
        raw = self._rest.get(_STANDINGS_PATH)
        if not raw:
            return [], None, 0, 0.0

        self._track_speed(raw)   # SEMPRE: cattura il picco top speed ad alta frequenza

        now = time.monotonic()
        if self._full_cache is not None and (now - self._full_cache_t) < 0.1:
            return self._full_cache

        # classe del player
        player_class = None
        for d in raw:
            if d.get("player"):
                player_class = d.get("carClass", "")
                break

        # modalità vista: "class" (solo classe player) o "overall" (tutte)
        view_mode = self._view_mode()

        if view_mode == "overall":
            filtered = list(raw)
            # ordina: prima per classe (ordine fisso HY->LMP2->LMP3->GT3->GTE),
            # poi per posizione dentro la classe
            filtered.sort(key=lambda x: (_class_rank(x.get("carClass", "")),
                                         x.get("position", 99)))
        else:
            filtered = [d for d in raw if d.get("carClass") == player_class] if player_class else list(raw)
            filtered.sort(key=lambda x: x.get("position", 99))

        # posizione DENTRO ciascuna classe (contatore per classe)
        class_counter = {}
        place_in_class = []
        for d in filtered:
            cc = d.get("carClass", "")
            class_counter[cc] = class_counter.get(cc, 0) + 1
            place_in_class.append(class_counter[cc])

        # flag colonne: quando una colonna è spenta, NON calcoliamo i suoi dati
        # (risparmio vero, non solo nascondere). Default ON.
        _wc = self._config.widget("standings")
        _show_tyre = _wc.get("show_tyre", True)
        _show_wear = _wc.get("show_wear", True)
        _show_tl = _wc.get("show_track_limits", True)
        _show_sectors = _wc.get("show_sectors", True)
        _show_lap = _wc.get("show_lap", True)
        _show_best = _wc.get("show_best_lap", True)
        _show_gap = _wc.get("show_gap", True)

        yellow_phases = self._mem.get_yellow_phases()   # {mID: bool}
        _all = self._mem.get_all_maps()                  # UNA passata condivisa
        compound_map = _all["compounds"] if _show_tyre else {}
        compound4_map = _all["compounds4"] if _show_tyre else {}
        lap_valid_map = _all["lap_valid"] if _show_lap else {}
        tl_map = _all["track_limits"] if _show_tl else {}
        pit_map = _all["pitstops"]
        car_states = _all["car_states"]
        # settori SEMPRE attivi: vivono nella cella status (riposo)
        sec_map = _all["sectors"]
        wear_map = _all["wear"] if _show_wear else {}
        session_type, remaining, sector_flags = self._mem.read_session()
        # ± posizioni: baseline si azzera al cambio sessione; vale solo in gara
        _pd_race = 10 <= int(session_type or 0) <= 13
        if session_type != self._pd_sess:
            self._pd_sess = session_type
            self._pd_base.clear()

        drivers = []
        for i, d in enumerate(filtered):
            vname_raw = d.get("vehicleName", "")

            name_raw = d.get("driverName", "").upper().split()
            name = (name_raw[0][0] + "." + " ".join(name_raw[1:])) if len(name_raw) >= 2 \
                else d.get("driverName", "").upper()

            ve = d.get("veFraction", None)
            if ve is not None and ve > 0:
                v_energy = round(ve * 100, 1)
                energy_kind = "ve"
            else:
                # P2/P3 e categorie senza Virtual Energy: mostro il carburante %
                ff = d.get("fuelFraction", None)
                v_energy = round(ff * 100, 1) if ff is not None and ff > 0 else None
                energy_kind = "fuel" if v_energy is not None else ""

            flag = d.get("flag", "GREEN")
            sector_str = d.get("sector", "")
            slot_id = d.get("slotID", -1)
            sector_idx = SECTOR_MAP.get(sector_str, -1)
            sector_has_yellow = sector_idx >= 0 and sector_flags[sector_idx] == 1
            vel = d.get("carVelocity", {})
            speed = float(vel.get("velocity", 999)) if isinstance(vel, dict) else 999
            is_slow = speed < 10.0
            under_yellow = (
                flag == "YELLOW"
                or bool(d.get("underYellow", False))
                or yellow_phases.get(slot_id, False)
                or (sector_has_yellow and is_slow)
            )
            yellow_sector = SECTOR_LABEL.get(sector_str, "YEL") if under_yellow else ""

            # top speed = SOLO il massimo dell'ultimo giro completato (fisso).
            # niente fallback "vivo": prima del 1° giro resta vuoto.
            _disp_sp = self._last_speed.get(slot_id, 0)
            last_lap_t = float(d.get("lastLapTime", -1))
            live_valid = lap_valid_map.get(slot_id, True)
            # congelo la validità: aggiorno solo quando il last lap cambia
            prev_ll = self._frozen_lastlap.get(slot_id)
            if prev_ll is None or last_lap_t != prev_ll:
                self._frozen_lastlap[slot_id] = last_lap_t
                self._frozen_valid[slot_id] = live_valid
            frozen_valid = self._frozen_valid.get(slot_id, live_valid)

            _stint_g, _stint_s = self._calc_stint(slot_id, int(d.get("lapsCompleted", 0)), pit_map.get(slot_id, 0), car_states.get(slot_id))
            # OUTLAP: dall'uscita pit/box fino al primo taglio del traguardo
            _laps_now = int(d.get("lapsCompleted", 0))
            _cs = car_states.get(slot_id) or {}
            _inpits_now = bool(_cs.get("in_pits", False)) or bool(_cs.get("garage", False))
            _prev_op = self._outlap_inpits.get(slot_id)
            if _inpits_now:
                # in box: memorizzo i giri, outlap parte appena esce
                self._outlap_base[slot_id] = _laps_now
            elif _prev_op and not _inpits_now:
                # appena uscito dal box: arma l'outlap
                self._outlap_base[slot_id] = _laps_now
            _is_outlap = False
            if slot_id in self._outlap_base:
                if _laps_now <= self._outlap_base[slot_id]:
                    _is_outlap = True   # non ancora completato un giro dall'uscita
                else:
                    self._outlap_base.pop(slot_id, None)  # outlap concluso
            self._outlap_inpits[slot_id] = _inpits_now
            drivers.append({
                "name":           name,
                "car_number":     str(d.get("carNumber", "") or ""),
                "slot_id":        slot_id,
                "brand":          brand_from_vehicle(vname_raw),
                "place_class":    place_in_class[i],
                "pos_delta":      (self._pd_base.setdefault(slot_id, place_in_class[i])
                                   - place_in_class[i]) if _pd_race else None,
                "last_lap":       last_lap_t,
                "best_lap":       float(d.get("bestLapTime", -1)),
                "gap_leader":     float(d.get("timeBehindClassLeader", 0)),
                "laps_behind":    int(d.get("lapsBehindClassLeader", 0)),
                "_tbl":           float(d.get("timeBehindClassLeader", 0)),  # raw per gap relativo
                "is_player":      bool(d.get("player", False)),
                "car_class":      d.get("carClass", ""),
                "in_pits":        d.get("pitting", False),
                "in_garage":      bool(d.get("inGarageStall", False)),
                "pit_state":      d.get("pitState", "NONE"),
                "finish_status":  d.get("finishStatus", "FSTAT_NONE"),
                "num_penalties":  int(d.get("penalties", 0)),
                "under_yellow":   under_yellow,
                "yellow_sector":  yellow_sector,
                "v_energy":       v_energy,
                "energy_kind":    energy_kind,
                "is_overall_best": False,
                "tyre":           compound_map.get(slot_id, ""),
                "tyre4":          compound4_map.get(slot_id, None),
                "speed_kmh":      round(_disp_sp * 3.6),
                "lap_valid":      frozen_valid,
                "track_limits":   tl_map.get(slot_id, None),
                "num_pit":        pit_map.get(slot_id, 0),
                "laps_done":      int(d.get("lapsCompleted", 0)),
                "stint_time":     _stint_s,
                "outlap":         _is_outlap,
                "tyre_wear":      wear_map.get(slot_id, None),
                "sectors":        sec_map.get(slot_id, None),
            })

        # best lap viola (assoluto)
        valid_best = [d["best_lap"] for d in drivers if d["best_lap"] > 0] if _show_best else []
        if valid_best:
            ob = min(valid_best)
            for d in drivers:
                d["is_overall_best"] = d["best_lap"] == ob

        # fastest last lap per CLASSE (fucsia)
        valid_last = [d["last_lap"] for d in drivers if d["last_lap"] > 0]
        if valid_last:
            fl = min(valid_last)
            for d in drivers:
                d["is_fastest_last"] = d["last_lap"] == fl
        else:
            for d in drivers:
                d["is_fastest_last"] = False

        # fastest last per classe
        class_fastest = {}
        for d in drivers:
            if d["last_lap"] > 0 and d.get("lap_valid", True):
                cc = d.get("car_class", "")
                if cc not in class_fastest or d["last_lap"] < class_fastest[cc]:
                    class_fastest[cc] = d["last_lap"]

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

        # best di settore (per i colori): best assoluto per ognuno dei 3
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
        # nel giro CORRENTE (usa 'cur' + 'sector' attuale), non a fine giro.
        # sector: 0=S3 (in S3), 1=S1 (in S1), 2=S2 (in S2)
        def _state_for(last_t, best_t, idx):
            if not last_t or last_t <= 0:
                return ""
            if best_sec[idx] is not None and last_t <= best_sec[idx]:
                return "fastest"   # viola: best assoluto di settore
            if best_t and best_t > 0 and last_t <= best_t:
                return "improved"  # verde: migliorato proprio best
            return "normal"        # giallo/bianco

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
            # S1: chiuso se sei in S2 o S3 (cioè non più in S1)
            if in_sector != 1 and len(cur) > 0 and cur[0] > 0:
                states[0] = _state_for(cur[0], best[0] if len(best) > 0 else -1, 0)
            # S2: chiuso se sei in S3
            if in_sector == 0 and len(cur) > 1 and cur[1] > 0:
                states[1] = _state_for(cur[1], best[1] if len(best) > 1 else -1, 1)
            # quando il giro è appena chiuso (sei tornato in S1), mostra il last completo
            if in_sector == 1:
                for si in range(3):
                    lt = last[si] if si < len(last) else -1
                    bt = best[si] if si < len(best) else -1
                    if lt and lt > 0:
                        states[si] = _state_for(lt, bt, si)
            # settore CORRENTE (dove gira ora): "current" se non già chiuso,
            # così il quadratino lampeggia fade in attesa del risultato.
            cur_idx = {0: 2, 1: 0, 2: 1}.get(in_sector, None)
            if cur_idx is not None and not states[cur_idx]:
                states[cur_idx] = "current"
            d["sector_states"] = states

        # ── GAP secondo sessione ──────────────────────────────────────
        # Gara (session 10-13): per la TUA classe gap relativo a te (davanti +,
        #   dietro -); per le ALTRE classi gap dal leader di classe.
        # Pratica/Qualy: gap sui best lap dal leader di classe.
        is_race = 10 <= int(session_type) <= 13
        player_d = next((dd for dd in drivers if dd.get("is_player")), None)
        my_tbl = player_d.get("_tbl", 0.0) if player_d else 0.0
        my_class = player_d.get("car_class", "") if player_d else ""

        # ── gap LIVE in gara a TEMPO (no elastico), calcolato 1×/sec (alleggerisce
        #    thread e memoria: l'estimator accumula meno storico). ──
        if is_race and player_d is not None and _show_gap:
            now = time.monotonic()
            if (now - self._race_gap_t) >= 0.1 or not self._race_gap_cache:
                race_track_len, race_pos = self._mem.get_positions()
                race_pp = race_pos.get(player_d.get("slot_id"), 0.0)
                _my_last = player_d.get("last_lap", 0) or 0
                race_spd = (race_track_len / _my_last) if (race_track_len > 0 and _my_last > 0) else 50.0
                _tlt, race_totals = self._mem.get_totals()
                if self._gap_est is not None:
                    try:
                        self._gap_est.update(race_totals)
                    except Exception:
                        pass
                p_sid = player_d.get("slot_id")
                race_p_total = race_totals.get(p_sid)
                cache = {}
                for dd in drivers:
                    if dd.get("is_player") or dd.get("car_class", "") != my_class:
                        continue
                    o_sid = dd.get("slot_id")
                    o_total = race_totals.get(o_sid)
                    g = None
                    try:
                        if self._gap_est is not None and race_p_total is not None and o_total is not None:
                            g = self._gap_est.gap(p_sid, o_sid, race_p_total, o_total)
                    except Exception:
                        g = None
                    if g is None and race_track_len > 0:
                        delta = (race_pos.get(o_sid, 0.0) - race_pp) % race_track_len
                        if delta > race_track_len / 2:
                            delta -= race_track_len
                        g = delta / race_spd
                    cache[o_sid] = g
                self._race_gap_cache = cache
                self._race_gap_t = now

        # best lap del leader per ogni classe (per P/Q)
        best_leader = {}
        for dd in drivers:
            cc = dd.get("car_class", "")
            bl = dd.get("best_lap", -1)
            if bl and bl > 0:
                if cc not in best_leader or bl < best_leader[cc]:
                    best_leader[cc] = bl

        for dd in drivers:
            cc = dd.get("car_class", "")
            if is_race:
                if cc == my_class and not dd.get("is_player"):
                    g = self._race_gap_cache.get(dd.get("slot_id"))
                    if g is not None:
                        dd["gap_display"] = g                       # gap a tempo (davanti +, dietro -)
                    else:
                        dd["gap_display"] = my_tbl - dd.get("_tbl", 0.0)
                    dd["gap_mode"] = "rel"
                elif dd.get("is_player"):
                    dd["gap_display"] = 0.0
                    dd["gap_mode"] = "self"
                else:
                    # altre classi: gap dal leader della loro classe
                    dd["gap_display"] = dd.get("gap_leader", 0.0)
                    dd["gap_mode"] = "leader"
            else:
                # pratica/qualy: gap best lap dal leader di classe
                bl = dd.get("best_lap", -1)
                lead = best_leader.get(cc)
                if bl and bl > 0 and lead and lead > 0:
                    dd["gap_display"] = bl - lead
                else:
                    dd["gap_display"] = None
                dd["gap_mode"] = "best"

        self._full_cache = (drivers, player_class, session_type, remaining)
        self._full_cache_t = now
        return self._full_cache
