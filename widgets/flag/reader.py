"""
widgets/flag/reader.py — Rilevamento bandiere dalla shared memory.

Calcola:
- yellow_dist: distanza (m) dell'auto lenta più vicina davanti sotto yellow
               (0 se sei tu fermo sotto yellow), None se nessuna yellow.
- blue_class:  classe dell'auto dietro che ti sta doppiando (mFlag==6), o None.
- num_penalties: penalità in sospeso del player.
- checkered:   bandiera a scacchi quando TU tagli il traguardo
               (mFinishStatus==1 del player, non mGamePhase==8 che scatta
               col leader / allo scadere del tempo, cioe' PRIMA della linea).
"""
from core.shared_memory import SharedMemory


class FlagReader:
    def __init__(self):
        self._mem = SharedMemory.instance()

    def read(self):
        sim = self._mem._get_sim()
        if not sim:
            return {}
        try:
            from pyLMUSharedMemory.lmu_data import MAX_MAPPED_VEHICLES as _MAX
            si = sim.scoring.scoringInfo
            num = int(si.mNumVehicles)
            track_len = float(si.mLapDist)

            # trova il player
            pidx = -1
            for i in range(min(num, _MAX)):
                if int(sim.scoring.vehScoringInfo[i].mIsPlayer) == 1:
                    pidx = i
                    break
            if pidx < 0:
                return {}

            vp = sim.scoring.vehScoringInfo[pidx]
            my_dist = float(vp.mLapDist)
            my_laps = int(vp.mTotalLaps)
            my_cls_raw = bytes(vp.mVehicleClass).split(b"\x00")[0].decode("utf-8", "ignore")

            # gerarchia velocità classi (più alto = più veloce)
            from core.classes import class_tag
            _SPEED_RANK = {"HY": 4, "P2": 3, "P3": 2, "GT3": 1, "GTE": 1}
            my_tag = class_tag(my_cls_raw)
            my_rank = _SPEED_RANK.get(my_tag, 0)

            # PIT CLOSED: prova/quali (non gara) con game_phase == 0 (come
            # TinyPedal: pit_open = mGamePhase > 0). Rosso al semaforo uscita box.
            _sess = int(getattr(si, "mSession", 0) or 0)
            _phase = int(getattr(si, "mGamePhase", 0) or 0)
            out = {
                "num_penalties": int(vp.mNumPenalties),
                "checkered": (int(getattr(vp, "mFinishStatus", 0) or 0) == 1),
                "yellow_dist": None,
                "blue_class": None,
                "pit_closed": (_sess < 10 and _phase == 0),
            }

            # yellow attiva = qualsiasi settore == 1
            sf = si.mSectorFlag
            yellow_active = any(int(sf[k]) == 1 for k in range(3))
            under_blue = (int(vp.mFlag) == 6)

            def car_speed(v):
                vv = v.mLocalVel
                return (vv.x * vv.x + vv.y * vv.y + vv.z * vv.z) ** 0.5

            def rel_dist(opt_dist):
                r = opt_dist - my_dist
                if abs(r) > track_len * 0.5:
                    r += -track_len if opt_dist > my_dist else track_len
                return r

            nearest_yellow = None
            nearest_blue_class = None
            nearest_blue_dist = None

            if yellow_active and car_speed(vp) < 8.0:
                nearest_yellow = 0.0

            for i in range(min(num, _MAX)):
                if i == pidx:
                    continue
                v = sim.scoring.vehScoringInfo[i]
                if bool(v.mInPits):
                    continue
                spd = car_speed(v)
                rd = rel_dist(float(v.mLapDist))
                if yellow_active and spd < 8.0 and 0 <= rd <= 500.0:
                    if nearest_yellow is None or rd < nearest_yellow:
                        nearest_yellow = rd
                if under_blue and -300.0 <= rd < 0:
                    # chi ti sta DOPPIANDO: classe più veloce, oppure più giri di te
                    v_cls_raw = bytes(v.mVehicleClass).split(b"\x00")[0].decode("utf-8", "ignore")
                    v_tag = class_tag(v_cls_raw)
                    v_rank = _SPEED_RANK.get(v_tag, 0)
                    v_laps = int(v.mTotalLaps)
                    is_lapping = (v_rank > my_rank) or (v_laps > my_laps)
                    if not is_lapping:
                        continue   # auto della tua classe e stesso giro: non ti doppia
                    if nearest_blue_dist is None or rd > nearest_blue_dist:
                        nearest_blue_dist = rd
                        nearest_blue_class = v_cls_raw

            out["yellow_dist"] = nearest_yellow
            out["blue_class"] = nearest_blue_class
            return out
        except Exception:
            return {}
