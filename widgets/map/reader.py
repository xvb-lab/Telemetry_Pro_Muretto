"""
widgets/map/reader.py — Posizioni auto + nome pista + bandiere dalla shared memory.

Legge mPos (x,z = piano top-down) di OGNI veicolo, classe, box, distanza sul
giro, più: flag di settore (giallo), fase gialla per-auto e settore del player
(per mappare i confini dei settori durante la registrazione).
"""
from core.shared_memory import SharedMemory
from core.classes import class_tag
from core.rest_client import RestClient

_STANDINGS_PATH = "/rest/watch/standings"
_SECTOR_MAP = {"SECTOR1": 0, "SECTOR2": 1, "SECTOR3": 2}


class MapReader:
    def __init__(self):
        self._mem = SharedMemory.instance()
        self._rest = RestClient.instance()
        self._rest.subscribe(_STANDINGS_PATH)

    def _rest_info(self):
        """{slotID: {'num': pos in classe, 'sector_idx': 0/1/2|-1, 'speed': m/s}}.
        {} se la REST non è disponibile."""
        try:
            data = self._rest.get(_STANDINGS_PATH)
            if not isinstance(data, list):
                return {}
            rows = [d for d in data if d.get("slotID", -1) != -1]
            rows.sort(key=lambda d: d.get("position", 999))
            counter = {}
            out = {}
            for d in rows:
                cc = d.get("carClass", "")
                counter[cc] = counter.get(cc, 0) + 1
                vel = d.get("carVelocity", {})
                spd = float(vel.get("velocity", 999)) if isinstance(vel, dict) else 999.0
                out[int(d.get("slotID"))] = {
                    "num": str(counter[cc]),
                    "sector_idx": _SECTOR_MAP.get(d.get("sector", ""), -1),
                    "speed": spd,
                }
            return out
        except Exception:
            return {}

    def read(self):
        sim = self._mem._get_sim()
        if not sim:
            return None
        try:
            from pyLMUSharedMemory.lmu_data import MAX_MAPPED_VEHICLES as _MAX
            si = sim.scoring.scoringInfo
            try:
                track = bytes(si.mTrackName).split(b"\x00")[0].decode("utf-8", "ignore")
            except Exception:
                track = ""
            num = int(si.mNumVehicles)
            # yellow attiva = un qualsiasi settore a 1 (identica logica del widget Flag)
            try:
                sf = si.mSectorFlag
                yellow_active = any(int(sf[k]) == 1 for k in range(3))
            except Exception:
                yellow_active = False

            # posizioni fresche dalla telemetria (~50Hz) per movimento fluido;
            # lo scoring (~5Hz) fa scattare il movimento.
            tele_pos = {}
            try:
                if sim.telemetry:
                    for i in range(min(num, _MAX)):
                        t = sim.telemetry.telemInfo[i]
                        tele_pos[int(t.mID)] = (float(t.mPos.x), float(t.mPos.z))
            except Exception:
                tele_pos = {}

            cars = []
            player = None
            rinfo = self._rest_info()
            for i in range(min(num, _MAX)):
                v = sim.scoring.vehScoringInfo[i]
                try:
                    cls = bytes(v.mVehicleClass).split(b"\x00")[0].decode("utf-8", "ignore")
                except Exception:
                    cls = ""
                vid = int(v.mID)
                px, pz = tele_pos.get(vid, (float(v.mPos.x), float(v.mPos.z)))
                in_pits = bool(v.mInPits)
                garage = bool(v.mInGarageStall)
                vv = v.mLocalVel
                mem_speed = (vv.x * vv.x + vv.y * vv.y + vv.z * vv.z) ** 0.5
                info = rinfo.get(vid, {})
                try:
                    _nm9 = bytes(v.mDriverName).split(b"\x00")[0] \
                        .decode("utf-8", "ignore").strip()
                except Exception:
                    _nm9 = ""
                car = {
                    "id": vid,
                    "x": px,
                    "z": pz,
                    "cls": class_tag(cls),
                    "name": _nm9,
                    "num": info.get("num", ""),
                    "is_player": bool(v.mIsPlayer),
                    "in_pits": in_pits,
                    "garage": garage,
                    "lapdist": float(v.mLapDist),
                    "speed": info.get("speed", mem_speed),
                    "sector_idx": info.get("sector_idx", -1),
                    "yellow": False,
                }
                cars.append(car)
                if car["is_player"]:
                    player = car

            # ── confini/flag settori ──
            try:
                _, _, sector_flags = self._mem.read_session()
            except Exception:
                sector_flags = [0, 0, 0]

            # ── chi provoca la gialla: auto LENTA in un settore GIALLO (come standings) ──
            # per ogni colpevole coloriamo la pista da lui a 500m DIETRO di lui,
            # per TUTTE le gialle in pista (non solo la zona vicino a noi).
            track_len = float(si.mLapDist)
            my_dist = player["lapdist"] if player else 0.0
            yellow_bands = []
            for c in cars:
                if c["in_pits"]:
                    continue
                sidx = c["sector_idx"]
                sec_yellow = (0 <= sidx < len(sector_flags) and int(sector_flags[sidx]) == 1)
                if not sec_yellow:
                    # fallback se la REST non dà il settore: usa yellow globale
                    if not (sidx == -1 and yellow_active):
                        continue
                if c["speed"] < 10.0:                      # lenta = sta provocando la gialla
                    c["yellow"] = True
                    yellow_bands.append((c["lapdist"] - 500.0, c["lapdist"]))  # 500m dietro di lei

            # settore del player (0=S3, 1=S1, 2=S2) per i confini dei settori
            player_sector = None
            if player is not None:
                try:
                    ps = self._mem.get_sectors().get(player["id"])
                    if ps:
                        player_sector = ps.get("sector")
                except Exception:
                    pass

            return {"track": track, "cars": cars, "player": player,
                    "sector_flags": sector_flags, "player_sector": player_sector,
                    "yellow_active": yellow_active, "my_dist": my_dist,
                    "yellow_bands": yellow_bands,
                    "track_len": track_len}
        except Exception:
            return None
