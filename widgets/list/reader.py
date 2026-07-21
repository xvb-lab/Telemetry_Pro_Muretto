"""
widgets/list/reader.py — Telemetria per la lista dati (colonna destra HUD).

mmap: body_dent, detached, tyre_flat/detached, compound, tyre_temp,
      oil/water temp, rpm, overheating, battery, emotor_state/temp.
REST /rest/garage/UIScreen/RepairAndRefuel: fuel, energy, tires, susp, brakes.
"""
import json
import time
import threading
import urllib.request

from core.shared_memory import SharedMemory

LMU_API = "http://localhost:6397"
REST_PATH = "/rest/garage/UIScreen/RepairAndRefuel"


class ListReader:
    def __init__(self):
        self._mem = SharedMemory.instance()
        self._rest = {}
        self._lock = threading.Lock()
        self._running = False
        self.start()

    def start(self):
        if self._running:
            return
        self._running = True
        threading.Thread(target=self._loop_rest, daemon=True).start()

    def stop(self):
        self._running = False

    def _loop_rest(self):
        while self._running:
            out = {}
            try:
                url = f"{LMU_API}{REST_PATH}"
                req = urllib.request.Request(url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=1) as r:
                    data = json.loads(r.read())
                fi = data.get("fuelInfo", {})
                cur_fuel = float(fi.get("currentFuel", -1))
                max_fuel = float(fi.get("maxFuel", -1))
                out["fuel"] = cur_fuel
                cve = fi.get("currentVirtualEnergy", 0)
                mve = fi.get("maxVirtualEnergy", 0)
                if mve > 0:
                    out["energy"] = round(cve / mve * 100, 1)
                    out["energy_kind"] = "ve"
                elif max_fuel > 0 and cur_fuel >= 0:
                    # P2/P3 senza Virtual Energy: percentuale serbatoio
                    out["energy"] = round(cur_fuel / max_fuel * 100, 1)
                    out["energy_kind"] = "fuel"
                else:
                    out["energy"] = None
                    out["energy_kind"] = ""
                w = data.get("wearables", {})
                br = w.get("brakes", [])
                if isinstance(br, list) and len(br) >= 4:
                    out["brakes"] = [float(x) for x in br[:4]]
                su = w.get("suspension", [])
                if isinstance(su, list) and len(su) >= 4:
                    out["susp"] = [float(x) for x in su[:4]]
                ti = w.get("tires", [])
                if isinstance(ti, list) and len(ti) >= 4:
                    out["tires"] = [float(x) for x in ti[:4]]
                # integrità aerodinamica carrozzeria (wearables.body.aero)
                body = w.get("body", {})
                if isinstance(body, dict) and "aero" in body:
                    out["aero"] = float(body["aero"])
                # ── consumo per giro dal PIT-MENU (stesso pattern del recorder):
                # serve alla riga STINT (LAP n/X, X = giro di fine carico) ──
                import re as _re
                def _rate(txt):
                    mm = _re.search(r"(\d+(?:\.\d+)?)\s*[l%]?\s*[/ ]+\s*(\d+)\s*(?:laps?|giri)",
                                    txt or "", _re.I)
                    if mm and int(mm.group(2)) > 0:
                        return float(mm.group(1)) / int(mm.group(2))
                    return None
                pm = (data.get("pitMenu", {}) or {}).get("pitMenu", []) or []
                _has_energy = any("ENERG" in ((it.get("name") or "").upper()) for it in pm)
                constraint = "ENERGY" if (_has_energy or float(fi.get("maxBattery") or 0.0) > 0) else "FUEL"
                per_lap = None
                for it in pm:
                    nm = (it.get("name") or "").upper()
                    ss = it.get("settings", []) or []
                    cs = int(it.get("currentSetting", 0) or 0)
                    cur_txt = ss[cs]["text"] if 0 <= cs < len(ss) else ""
                    full_txt = ss[-1]["text"] if ss else ""
                    is_nrg = ("ENERG" in nm)
                    is_fuel = ("FUEL" in nm) or ("CARBUR" in nm) or ("BENZ" in nm)
                    if (constraint == "ENERGY" and is_nrg) or \
                       (constraint == "FUEL" and is_fuel):
                        per_lap = _rate(cur_txt) or _rate(full_txt)
                # col verde il pit-menu può sparire: tieni l'ultimo valido
                if per_lap:
                    self._strat_last = (constraint, per_lap)
                elif getattr(self, "_strat_last", None):
                    constraint, per_lap = self._strat_last
                out["strat_constraint"] = constraint
                out["strat_per_lap"] = per_lap
                # stima MISURATA dall'ingegnere (equivale allo "stimato" LMU):
                # se fresca (<15s) vince sul massimo del pit-menu
                try:
                    from core.paths import USER_DIR as _UD
                    _ls = json.loads((_UD / "live_strategy.json")
                                     .read_text(encoding="utf-8"))
                    if time.time() - float(_ls.get("ts", 0)) < 15.0:
                        out["laps_left_live"] = float(_ls.get("laps_left"))
                except Exception:
                    pass
            except Exception:
                pass
            with self._lock:
                self._rest = out
            time.sleep(2)

    def read(self):
        sim = self._mem._get_sim()
        if not sim or not sim.telemetry:
            return {}
        try:
            from pyLMUSharedMemory.lmu_data import MAX_MAPPED_VEHICLES as _MAX
            num = int(sim.scoring.scoringInfo.mNumVehicles)
            pidx = -1
            for i in range(min(num, _MAX)):
                if sim.scoring.vehScoringInfo[i].mIsPlayer:
                    pidx = i
                    break
            if pidx < 0:
                return {}
            # telemetria agganciata per mID, NON per posizione: gli array
            # scoring/telemetry non sono allineati e l'ordine puo' cambiare
            # in corsa (pit/ritiri) -> senza, dopo un po' leggi un'ALTRA auto
            _pid = int(sim.scoring.vehScoringInfo[pidx].mID)
            t = None
            for _i in range(min(num, _MAX)):
                _ti = sim.telemetry.telemInfo[_i]
                if int(_ti.mID) == _pid:
                    t = _ti
                    break
            if t is None:
                t = sim.telemetry.telemInfo[pidx]   # fallback: vecchio modo

            out = {}
            # classe della propria auto (per scale colore brake-temp)
            try:
                from core.classes import class_tag
                vcls = sim.scoring.vehScoringInfo[pidx].mVehicleClass.decode("utf-8", "ignore")
                out["car_class"] = class_tag(vcls)
            except Exception:
                out["car_class"] = ""
            # nome modello pulito (es. "Porsche 911 GT3 R") + brand
            try:
                from core.brands import brand_from_vehicle
                vmodel = t.mVehicleModel.decode("utf-8", "ignore").strip()
                vname = sim.scoring.vehScoringInfo[pidx].mVehicleName.decode("utf-8", "ignore")
                out["car_name"] = vmodel or vname
                out["brand"] = brand_from_vehicle(vname)
            except Exception:
                out["car_name"] = ""; out["brand"] = ""
            out["water_temp"] = float(t.mEngineWaterTemp)
            out["oil_temp"] = float(t.mEngineOilTemp)
            out["rpm"] = float(t.mEngineRPM)
            out["overheating"] = bool(t.mOverheating)
            out["battery"] = float(t.mBatteryChargeFraction)
            out["emotor_state"] = int(t.mElectricBoostMotorState)
            out["emotor_temp"] = float(t.mElectricBoostMotorTemperature)
            out["throttle"] = float(t.mFilteredThrottle)
            out["brake"] = float(t.mFilteredBrake)
            # campi extra motore: ognuno isolato, se manca non rompe il resto
            def _safe(name, conv=float):
                try:
                    return conv(getattr(t, name))
                except Exception:
                    return None
            out["max_rpm"] = _safe("mEngineMaxRPM")
            out["engine_torque"] = _safe("mEngineTorque")
            out["emotor_rpm"] = _safe("mElectricBoostMotorRPM")
            out["emotor_torque"] = _safe("mElectricBoostMotorTorque")
            out["regen_kw"] = _safe("mRegen")
            v = t.mLocalVel
            out["speed"] = (v.x * v.x + v.y * v.y + v.z * v.z) ** 0.5 * 3.6
            out["body_dent"] = [int(x) for x in t.mDentSeverity]
            out["detached"] = bool(t.mDetached)
            # giri e soste per la riga STINT
            try:
                vp = sim.scoring.vehScoringInfo[pidx]
                out["laps_done"] = int(vp.mTotalLaps)
                out["num_pit"] = int(vp.mNumPitstops)
            except Exception:
                pass
            try:
                out["tyre_flat"] = [bool(t.mWheels[i].mFlat) for i in range(4)]
            except Exception:
                pass
            # temperature freni per ruota (°C) dal telemetry
            try:
                out["brake_temp"] = [float(t.mWheels[i].mBrakeTemp) - 273.15 for i in range(4)]
            except Exception:
                pass
            # temperatura carcassa gomme (°C) dal telemetry
            try:
                out["tyre_carcass"] = [float(t.mWheels[i].mTireCarcassTemperature) - 273.15 for i in range(4)]
            except Exception:
                pass
            with self._lock:
                out.update(self._rest)
            return out
        except Exception:
            return {}
