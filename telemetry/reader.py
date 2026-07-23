"""
telemetry/reader.py — Lettura completa del player dalla shared memory.

Tutto da shared memory (niente REST): fuel/energia stanno in mFuel /
mFuelCapacity / mVirtualEnergy. Ritorna un dict piatto con TUTTI i canali
usati da recorder e UI: identità/sessione, giro/settore, input, G, posizione,
ibrido, e per-ruota (gomme 3 strati + freno + usura + grip).

Pattern d'accesso identico agli altri reader:
    sim = mem._get_sim(); t = sim.telemetry.telemInfo[pidx]; vp = scoring[pidx]
"""
from core.shared_memory import SharedMemory

_K = 273.15  # Kelvin -> Celsius


def _sigla_from_name(name):
    """Sigla mescola (S/M/H/W) dal NOME del compound — affidabile e stabile,
    a differenza dell'indice intero che su alcune classi (Hypercar) inganna.
    '' se il nome non dice nulla (allora si usa l'indice come fallback)."""
    n = (name or "").strip().lower()
    if not n:
        return ""
    if any(k in n for k in ("wet", "rain", "pioggia", "inter", "full")):
        return "W"          # bagnato / intermedia
    if "hard" in n:
        return "H"
    if "medium" in n or "med" in n:
        return "M"
    if "soft" in n:
        return "S"
    # "Slick" generica (GT3: l'unica dry e' la MEDIA) — va gestita PRIMA
    # della regola prima-lettera, altrimenti "Slick" -> "S" = Soft finta
    # (bug visto in classifica community: GT3 con la soft che non esiste)
    if "slick" in n:
        return "M"
    # nomi a sigla secca (es. "H", "M2", "S9"): prima lettera se e' S/M/H,
    # ma SOLO su codici corti — mai su parole intere
    if len(n) <= 3:
        c = n[0].upper()
        if c in ("S", "M", "H"):
            return c
    return ""


def _c(k):
    try:
        return float(k) - _K
    except Exception:
        return None


class TelemetryReader:
    def __init__(self):
        self._mem = SharedMemory.instance()

    def stop(self):
        pass

    def read(self):
        sim = self._mem._get_sim()
        if not sim or not sim.telemetry:
            return {}
        try:
            from pyLMUSharedMemory.lmu_data import MAX_MAPPED_VEHICLES as _MAX
            si = sim.scoring.scoringInfo
            num = int(si.mNumVehicles)
            pidx = -1
            for i in range(min(num, _MAX)):
                if sim.scoring.vehScoringInfo[i].mIsPlayer:
                    pidx = i
                    break
            if pidx < 0:
                return {}
            t = sim.telemetry.telemInfo[pidx]
            vp = sim.scoring.vehScoringInfo[pidx]

            end_et = float(si.mEndET)
            cur_et = float(si.mCurrentET)

            # settore corrente (bit di segno = pit lane)
            raw_sec = int(t.mCurrentSector)
            in_pitlane = raw_sec < 0
            sector = abs(raw_sec) & 0x7FFFFFFF  # 0,1,2

            # velocità da velocità locale
            lv = t.mLocalVel
            speed_ms = (lv.x ** 2 + lv.y ** 2 + lv.z ** 2) ** 0.5
            la = t.mLocalAccel

            def _track_name():
                for src in (t.mTrackName, getattr(si, "mTrackName", b"")):
                    try:
                        s = bytes(src).split(b"\x00")[0].decode("utf-8", "ignore")
                        if s:
                            return s
                    except Exception:
                        pass
                return ""

            def _txt(v):
                try:
                    return bytes(v).split(b"\x00")[0].decode("utf-8", "ignore")
                except Exception:
                    return ""

            ve_frac = float(t.mVirtualEnergy)            # 0..1
            ve_pct = ve_frac * 100.0

            out = {
                # ── sessione / identità ──
                "track": _track_name(),
                "driver": _txt(vp.mDriverName),
                "team": _txt(vp.mVehicleName),
                "vehicle": _txt(t.mVehicleModel) or _txt(t.mVehicleName),
                "car_class": _txt(vp.mVehicleClass),
                "session_type": int(si.mSession),
                "max_laps": int(getattr(si, "mMaxLaps", 0) or 0),
                "game_phase": int(getattr(si, "mGamePhase", 0) or 0),
                # stima del GIOCO: vive nello SCORING (vp), non nella
                # telemetria — letta da t con default era SEMPRE 0
                "est_lap": float(getattr(vp, "mEstimatedLapTime", 0.0)
                                 or 0.0),
                "race_total": end_et if end_et > 0 else 0.0,
                "race_remaining": max(0.0, end_et - cur_et) if end_et > 0 else 0.0,
                "cur_et": cur_et,
                # ── giro / settore ──
                "laps_completed": int(vp.mTotalLaps),
                "lap_number": int(t.mLapNumber),
                "lap_start_et": float(t.mLapStartET),
                "elapsed": float(t.mElapsedTime),
                "lapdist": float(vp.mLapDist),
                "sector": sector,
                "in_pitlane": in_pitlane,
                "in_pits": bool(vp.mInPits),
                "pit_state": int(vp.mPitState),
                "num_pit": int(vp.mNumPitstops),
                "garage": bool(getattr(vp, "mInGarageStall", False)),
                "last_lap": float(vp.mLastLapTime),
                "best_lap": float(getattr(vp, "mBestLapTime", 0.0) or 0.0),
                "cur_s1": float(vp.mCurSector1),
                "cur_s2": float(vp.mCurSector2),
                "last_s1": float(vp.mLastSector1),
                "last_s2": float(vp.mLastSector2),
                "lap_invalid": bool(getattr(t, "mLapInvalidated", False)),
                # ── consumi ──
                "fuel": float(t.mFuel),
                "fuel_max": float(t.mFuelCapacity),
                "ve": ve_pct,
                "ve_pct": ve_pct,
                # ── input / dinamica ──
                "throttle": float(t.mUnfilteredThrottle),
                "brake": float(t.mUnfilteredBrake),
                "steer": float(t.mUnfilteredSteering),
                "gear": int(t.mGear),
                "rpm": float(t.mEngineRPM),
                "max_rpm": float(t.mEngineMaxRPM),
                "overheating": bool(t.mOverheating),
                "compound_f": bytes(t.mFrontTireCompoundName).split(b'\x00')[0].decode('utf-8', 'ignore'),
                "compound_r": bytes(t.mRearTireCompoundName).split(b'\x00')[0].decode('utf-8', 'ignore'),
                "emotor_rpm": float(t.mElectricBoostMotorRPM),
                "emotor_tq": float(t.mElectricBoostMotorTorque),
                "water_temp": float(t.mEngineWaterTemp),
                "oil_temp": float(t.mEngineOilTemp),
                # ultimo IMPATTO (contatti/botte): tempo e intensita'
                "impact_et": float(getattr(t, "mLastImpactET", 0.0) or 0.0),
                "impact_mag": float(getattr(t, "mLastImpactMagnitude", 0.0) or 0.0),
                "speed": speed_ms * 3.6,
                "g_long": float(la.z) / 9.81,
                "g_lat": float(la.x) / 9.81,
                "brake_bias": float(t.mRearBrakeBias),
                "tc_active": (1.0 if bool(getattr(t, "mTCActive", 0)) else 0.0),
                "abs_active": (1.0 if bool(getattr(t, "mABSActive", 0)) else 0.0),
                "tc_map": float(getattr(t, "mTC", 0) or 0),
                "abs_map": float(getattr(t, "mABS", 0) or 0),
                "tc_slip": float(getattr(t, "mTCSlip", 0) or 0),
                "tc_cut": float(getattr(t, "mTCCut", 0) or 0),
                # ── posizione (traiettoria) ──
                "pos_x": float(t.mPos.x),
                "pos_y": float(t.mPos.y),
                "pos_z": float(t.mPos.z),
                # ── ibrido ──
                "soc": float(getattr(t, "mStateOfCharge", 0.0)),
                "battery": float(getattr(t, "mBatteryChargeFraction", 0.0)),
                "regen_kw": float(getattr(t, "mRegen", 0.0)),
                "boost_state": int(getattr(t, "mElectricBoostMotorState", 0)),
                "boost_torque": float(getattr(t, "mElectricBoostMotorTorque", 0.0)),
                "motor_map": int(getattr(t, "mMotorMap", 0)),
                "lift_coast": int(getattr(t, "mLiftAndCoastProgress", 0)),
            }

            # ── per-ruota: gomme 3 strati + freno + usura + grip ──
            surf = []; inner = []; carc = []; brk = []; wear = []; grip = []; press = []
            sdefl = []; rideh = []; bpress = []; surftype = []
            wflat = []; woff = []
            sforce = []; slat = []; wrot = []
            for i in range(4):
                w = t.mWheels[i]
                surf.append([_c(w.mTemperature[j]) for j in range(3)])
                inner.append([_c(w.mTireInnerLayerTemperature[j]) for j in range(3)])
                carc.append(_c(w.mTireCarcassTemperature))
                brk.append(_c(w.mBrakeTemp))
                wear.append(float(w.mWear) * 100.0)        # %
                grip.append(float(w.mGripFract))
                press.append(float(w.mPressure))
                try:
                    wflat.append(bool(w.mFlat))
                except Exception:
                    wflat.append(False)
                try:
                    woff.append(bool(w.mDetached))
                except Exception:
                    woff.append(False)
                try:
                    sdefl.append(float(w.mSuspensionDeflection) * 1000.0)   # m -> mm
                except Exception:
                    sdefl.append(None)
                try:
                    rideh.append(float(w.mRideHeight) * 1000.0)            # m -> mm
                except Exception:
                    rideh.append(None)
                try:
                    bpress.append(float(w.mBrakePressure) * 100.0)         # 0..1 -> %
                except Exception:
                    bpress.append(None)
                try:
                    surftype.append(int(w.mSurfaceType))   # 0=dry,1=wet,2-6=offtrack
                except Exception:
                    surftype.append(None)
                try:
                    sforce.append(float(w.mSuspForce))     # carico pushrod (N)
                except Exception:
                    sforce.append(None)
                try:
                    slat.append(float(w.mLateralPatchVel)) # scrub laterale (m/s)
                except Exception:
                    slat.append(None)
                try:
                    wrot.append(abs(float(w.mRotation)))   # rad/s (bloccaggi)
                except Exception:
                    wrot.append(None)
            out["tyre_surf"] = surf
            out["tyre_inner"] = inner
            out["tyre_carcass"] = carc
            out["brake_temp"] = brk
            out["tyre_wear"] = wear
            out["tyre_grip"] = grip
            out["tyre_press"] = press
            out["susp_defl"] = sdefl
            out["ride_h"] = rideh
            out["brake_press"] = bpress
            out["surface_type"] = surftype     # dichiarazione netta DRY/WET (per ruota)
            out["susp_force"] = sforce         # carico sospensione per ruota (N)
            out["slip_lat"] = slat             # velocita' laterale al contatto (slide)
            out["wheel_rot"] = wrot            # rotazione ruota (bloccaggi)
            # carico aerodinamico (N): bilancio e perdita in scia
            try:
                out["df_front"] = float(t.mFrontDownforce)
                out["df_rear"] = float(t.mRearDownforce)
            except Exception:
                out["df_front"] = out["df_rear"] = None
            # ── DANNI (dalla telemetria) ──
            try:
                dents = [int(t.mDentSeverity[i]) for i in range(8)]   # 0/1/2 x8
            except Exception:
                dents = None
            out["dent_sev"] = dents
            try:
                out["parts_off"] = bool(t.mDetached)   # pezzi (non ruote) staccati
            except Exception:
                out["parts_off"] = False
            out["wheel_flat"] = wflat                  # 4 bool
            out["wheel_off"] = woff                    # 4 bool
            # ── MOTORE ──
            try:
                out["eng_water"] = float(t.mEngineWaterTemp)   # °C
            except Exception:
                out["eng_water"] = None
            try:
                out["eng_oil"] = float(t.mEngineOilTemp)       # °C
                # MESCOLA MONTATA nel raw dell'ingegnere (il builder vero:
                # prima viaggiava solo nell'altro dict, mai qui -> cieco)
                try:
                    out["compound_f"] = bytes(t.mFrontTireCompoundName).split(b"\x00")[0].decode("utf-8", "ignore")
                    out["compound_r"] = bytes(t.mRearTireCompoundName).split(b"\x00")[0].decode("utf-8", "ignore")
                except Exception:
                    pass
            except Exception:
                out["eng_oil"] = None
            try:
                out["overheating"] = bool(t.mOverheating)
            except Exception:
                out["overheating"] = False
            # ── condizioni pista / meteo / mescola ──
            out["air_temp"] = float(si.mAmbientTemp)
            out["track_temp"] = float(si.mTrackTemp)
            out["raining"] = float(si.mRaining)
            try:
                out["track_len"] = float(si.mLapDist)
            except Exception:
                out["track_len"] = 0.0
            # assetto-consapevole (23/07): sterzo e imbardata per
            # understeer angle / attitude velocity (Segers cap.7)
            try:
                out["steer"] = float(t.mUnfilteredSteering)
            except Exception:
                out["steer"] = None
            try:
                out["yaw_rate"] = float(t.mLocalRot.y)
            except Exception:
                out["yaw_rate"] = None
            out["wetness"] = float(si.mAvgPathWetness)
            try:
                out["wetness_min"] = float(si.mMinPathWetness)
                out["wetness_max"] = float(si.mMaxPathWetness)
            except Exception:
                out["wetness_min"] = out["wetness_max"] = out["wetness"]
            try:
                out["track_grip"] = int(getattr(si, "mTrackGripLevel", 0))
            except Exception:
                out["track_grip"] = None
            out["compound_front"] = _txt(t.mFrontTireCompoundName)
            out["compound_rear"] = _txt(t.mRearTireCompoundName)
            # SIGLA MESCOLA dal NOME (stabile e vero: es. Hypercar Michelin
            # "Hard"), l'indice intero mCompoundType resta solo come ultima spiaggia
            # perche' su alcune classi (Hypercar) e' instabile/ingannevole.
            _CT = {0: "S", 1: "M", 2: "H", 3: "W"}
            _nf = _sigla_from_name(out.get("compound_front"))
            _nr = _sigla_from_name(out.get("compound_rear"))
            try:
                _ints = [_CT.get(int(t.mWheels[w].mCompoundType), "")
                         for w in range(4)]
            except Exception:
                _ints = ["", "", "", ""]
            out["tyre_compound4"] = [_nf or _ints[0], _nf or _ints[1],
                                     _nr or _ints[2], _nr or _ints[3]]
            return out
        except Exception:
            return {}
