"""
core/shared_memory.py — Wrapper sulla shared memory LMU (pyLMUSharedMemory).

Centralizza l'accesso a SimInfo così non viene istanziato in ogni widget.
Espone letture di alto livello: stato sessione, fasi gialle per-driver,
compound gomme. Tollerante agli errori: se LMU non c'è, ritorna default.
"""
import threading
import time

try:
    from pyLMUSharedMemory.lmu_data import (
        SimInfo as _SimInfo,
        MAX_MAPPED_VEHICLES as _MAX_VEH,
    )
    _AVAILABLE = True
except Exception:
    _SimInfo = None
    _MAX_VEH = 104
    _AVAILABLE = False


def _ttl_cache(ttl):
    """Cache a TTL per metodi senza argomenti: chiamanti diversi (standings,
    relative, mappa) entro la finestra riusano lo stesso risultato invece di
    rifare il giro su tutte le auto. Riduce il picco di lavoro per secondo."""
    def deco(fn):
        name = fn.__name__
        def wrapper(self):
            now = time.monotonic()
            ent = self._mcache.get(name)
            if ent is not None and (now - ent[0]) < ttl:
                return ent[1]
            val = fn(self)
            self._mcache[name] = (now, val)
            return val
        wrapper.__name__ = name
        return wrapper
    return deco


class SharedMemory:
    """Accesso condiviso alla shared memory LMU. Singleton."""

    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self._sim = None
        self._last_et = None          # ultimo mCurrentET letto (per rilevare pausa)
        self._et_frozen_since = None  # da quando il tempo è fermo (monotonic)
        self._sim_cache = None        # copia condivisa entro un frame (anti-scatto)
        self._sim_cache_t = 0.0
        self._sim_ttl = 0.012         # 12ms: i widget nello stesso frame riusano 1 copia
        self._mcache = {}             # cache TTL per i get_* pesanti (condivisa tra widget)

    @classmethod
    def instance(cls) -> "SharedMemory":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _get_sim(self):
        # _SimInfo copia tutta la shared memory alla creazione. Ricrearlo per OGNI
        # lettura di OGNI widget = molte copie pesanti per frame -> scatti.
        # Cache a TTL brevissimo: i widget che leggono nello stesso frame riusano
        # la stessa copia; i dati restano comunque freschi (sim ~50-90Hz).
        if not _AVAILABLE:
            return None
        now = time.monotonic()
        if self._sim_cache is not None and (now - self._sim_cache_t) < self._sim_ttl:
            return self._sim_cache
        try:
            self._sim_cache = _SimInfo()
            self._sim_cache_t = now
            return self._sim_cache
        except Exception:
            self._sim_cache = None
            return None

    # ── SESSIONE ──────────────────────────────────────────────────────
    def is_on_track(self) -> bool:
        """True se sei in pista (realtime) e il gioco NON è in pausa.
        False nei menu, in pausa e nei replay.

        Rilevazione pausa: quando il gioco è in pausa il tempo di sessione
        (mCurrentET) si congela. Se resta fermo per oltre 0.5s consideriamo
        il gioco in pausa e nascondiamo gli overlay.

        In dubbio (shared memory non disponibile) ritorna True per non
        nascondere i widget per errore.
        """
        try:
            sim = self._get_sim()
            if not sim:
                self._last_et = None
                self._et_frozen_since = None
                return True
            si = sim.scoring.scoringInfo
            if not bool(si.mInRealtime):
                # DEBOUNCE: la shared memory non ha version counter e una
                # lettura strappata da' mInRealtime=0 per UN tick -> overlay
                # a sfarfallio in pista. Il "fuori pista" deve CONFERMARSI
                # per 0.7s prima di spegnere; il ritorno acceso e' immediato.
                _nrt = time.monotonic()
                _fs = getattr(self, "_rt_false_since", None)
                if _fs is None:
                    self._rt_false_since = _nrt
                    return True
                if (_nrt - _fs) < 0.7:
                    return True
                self._last_et = None
                self._et_frozen_since = None
                return False
            self._rt_false_since = None
            # ── rilevazione pausa: il tempo di sessione si ferma ──
            et = float(si.mCurrentET)
            now = time.monotonic()
            if self._last_et is not None and et == self._last_et:
                if self._et_frozen_since is None:
                    self._et_frozen_since = now
                elif (now - self._et_frozen_since) > 0.5:
                    # SCORING fermo: prima di dichiarare "pausa" chiedi alla
                    # TELEMETRIA (50-90Hz). Lo scoring aggiorna a raffiche e
                    # un hiccup >0.5s sembrava pausa: overlay/dash/strategia
                    # sparivano a caso in pista ("dash nera"). Se il tempo
                    # della telemetria avanza, il gioco e' VIVO.
                    try:
                        _pi = int(sim.telemetry.playerVehicleIdx or 0)
                        _tel = float(sim.telemetry.telemInfo[_pi].mElapsedTime)
                        if _tel != getattr(self, "_last_tel_et", None):
                            self._last_tel_et = _tel
                            self._tel_seen = now
                            return True   # telemetria viva: NON e' pausa
                        # STESSO valore: puo' essere la COPIA in cache
                        # (due letture nello stesso frame) — e' "ferma"
                        # solo se invariata da >0.5s di OROLOGIO (il blink
                        # ogni ~5s degli overlay veniva da qui)
                        if (now - getattr(self, "_tel_seen", 0.0)) < 0.5:
                            return True
                    except Exception:
                        pass
                    return False          # anche telemetria ferma = pausa vera
            else:
                self._et_frozen_since = None
            self._last_et = et
            return True
        except Exception:
            self._sim = None
            return True

    def frozen_secs(self):
        """Da quanti secondi il tempo di sessione (mCurrentET) e' FERMO.
        0 = vivo. Oltre la pausa normale (minuti) = plugin shared memory
        del gioco congelato: serve riavviare la sessione LMU."""
        try:
            if self._et_frozen_since is None:
                return 0.0
            return max(0.0, time.monotonic() - self._et_frozen_since)
        except Exception:
            return 0.0

    def in_realtime(self):
        """True se sei in pista (mInRealtime), anche in pausa. False nei menu,
        garage e replay. Usato per auto-chiudere la registrazione al rientro
        al menu (la pausa NON conta come uscita)."""
        try:
            sim = self._get_sim()
            if not sim:
                return None
            return bool(sim.scoring.scoringInfo.mInRealtime)
        except Exception:
            return None

    def game_phase(self):
        """mGamePhase corrente (0 garage,1 warmup,2 gridwalk,3 formation,
        4 countdown,5 green,6 FCY,7 stopped,8 over,9 paused) o None."""
        try:
            sim = self._get_sim()
            if not sim:
                return None
            return int(sim.scoring.scoringInfo.mGamePhase)
        except Exception:
            return None

    def session_et(self):
        """Tempo di sessione corrente (mCurrentET). AVANZA finché la sessione è
        viva — anche in garage e nel menu setup — e si FERMA ai menu / a sessione
        finita. Serve a chiudere la registrazione solo al menu vero, non in box."""
        try:
            sim = self._get_sim()
            if not sim:
                return None
            return float(sim.scoring.scoringInfo.mCurrentET)
        except Exception:
            return None

    def read_session(self):
        """(session_type, remaining_secs, [s1,s2,s3]). Default se non disponibile."""
        try:
            sim = self._get_sim()
            if not sim:
                return 0, 0.0, [11, 11, 11]
            si = sim.scoring.scoringInfo
            session_type = int(si.mSession)
            remaining = max(0.0, float(si.mEndET) - float(si.mCurrentET)) if si.mEndET > 0 else 0.0
            sector_flags = [int(si.mSectorFlag[i]) for i in range(3)]
            return session_type, remaining, sector_flags
        except Exception:
            self._sim = None
            return 0, 0.0, [11, 11, 11]

    # ── FASI GIALLE per-driver ────────────────────────────────────────
    def get_car_states(self) -> dict:
        """{mID: {'in_pits':bool, 'garage':bool, 'moving':bool, 'is_player':bool}}
        per ogni auto. Usato per la logica dello stint:
        - in pista e in movimento = stint attivo
        - in garage / fermo in box = stint non ancora partito."""
        try:
            sim = self._get_sim()
            if not sim:
                return {}
            out = {}
            num = int(sim.scoring.scoringInfo.mNumVehicles)
            for i in range(min(num, _MAX_VEH)):
                v = sim.scoring.vehScoringInfo[i]
                vv = v.mLocalVel
                speed = (vv.x * vv.x + vv.y * vv.y + vv.z * vv.z) ** 0.5
                try:
                    garage = bool(v.mInGarageStall)
                except Exception:
                    garage = False
                out[int(v.mID)] = {
                    "in_pits": bool(v.mInPits),
                    "garage": garage,
                    "moving": speed > 3.0,
                    "is_player": bool(v.mIsPlayer),
                }
            return out
        except Exception:
            self._sim = None
            return {}

    def nearest_car(self):
        """Auto (di QUALSIASI classe) piu' vicina al player lungo la pista, per
        identificare un contatto/doppiaggio. Ritorna {name, cls, gap_m (con
        segno: + davanti / - dietro), ahead}. None se sola in pista. Esclude box/
        garage."""
        try:
            sim = self._get_sim()
            if not sim:
                return None
            si = sim.scoring.scoringInfo
            num = int(si.mNumVehicles)
            track_len = float(si.mLapDist) or 1.0
            pl = None
            for i in range(min(num, _MAX_VEH)):
                if int(sim.scoring.vehScoringInfo[i].mIsPlayer) == 1:
                    pl = sim.scoring.vehScoringInfo[i]
                    break
            if pl is None:
                return None
            pd = float(pl.mLapDist)
            best = None
            for i in range(min(num, _MAX_VEH)):
                v = sim.scoring.vehScoringInfo[i]
                if int(v.mIsPlayer) == 1 or bool(v.mInPits):
                    continue
                try:
                    if bool(v.mInGarageStall):
                        continue
                except Exception:
                    pass
                d = float(v.mLapDist) - pd
                if d > track_len / 2:
                    d -= track_len
                elif d < -track_len / 2:
                    d += track_len
                if best is None or abs(d) < abs(best[0]):
                    try:
                        nm = v.mDriverName.decode("utf-8", "ignore").strip("\x00 ").strip()
                    except Exception:
                        nm = ""
                    try:
                        cl = v.mVehicleClass.decode("utf-8", "ignore").strip("\x00 ").strip()
                    except Exception:
                        cl = ""
                    best = (d, nm, cl)
            if best is None:
                return None
            return {"name": best[1], "cls": best[2],
                    "gap_m": round(best[0], 1), "ahead": best[0] > 0}
        except Exception:
            return None

    def rivals(self):
        """Dati rivali IN CLASSE, robusti in multiclass: posizione di classe e
        davanti/dietro dall'ORDINE DI MARCIA reale (giri completati + distanza
        percorsa), NON da mTimeBehindLeader (che con i doppiati salta). Gap a
        tempo: differenza behind_leader se sullo stesso giro, altrimenti stima
        distanza/velocita'."""
        try:
            sim = self._get_sim()
            if not sim:
                return None
            si = sim.scoring.scoringInfo
            num = int(si.mNumVehicles)
            track_len = float(si.mLapDist) or 1.0
            cars = []
            pl = None
            best_sess = None
            best_name = ""
            cls_best = {}              # best lap di sessione PER CLASSE
            for i in range(min(num, _MAX_VEH)):
                v = sim.scoring.vehScoringInfo[i]
                try:
                    name = v.mDriverName.decode("utf-8", "ignore").strip()
                except Exception:
                    name = ""
                try:
                    cls = v.mVehicleClass.decode("utf-8", "ignore").strip()
                except Exception:
                    cls = ""
                bl = float(v.mBestLapTime or 0)
                if bl > 0:
                    if best_sess is None or bl < best_sess:
                        best_sess = bl
                        best_name = name
                    cb = cls_best.get(cls)
                    if cb is None or bl < cb:
                        cls_best[cls] = bl
                laps = int(v.mTotalLaps)
                ld = float(v.mLapDist)
                vv = v.mLocalVel
                spd = (vv.x * vv.x + vv.y * vv.y + vv.z * vv.z) ** 0.5
                c = {"name": name, "cls": cls, "laps": laps,
                     "progress": laps * track_len + ld,
                     "behind_leader": float(v.mTimeBehindLeader or 0),
                     "pit": int(v.mPitState), "is_player": bool(v.mIsPlayer),
                     "in_pits": bool(v.mInPits),
                     "stops": int(getattr(v, "mNumPitstops", 0) or 0),
                     "place": int(getattr(v, "mPlace", 0) or 0), "speed": spd}
                cars.append(c)
                if c["place"] == 1:
                    # leader ASSOLUTO: serve alla stima dei giri totali gara
                    _ldr = {"laps": laps,
                            "last": float(getattr(v, "mLastLapTime", 0) or 0),
                            "best": bl, "in_pits": c["in_pits"]}
                if c["is_player"]:
                    pl = c
            out = {"best_in_session": best_sess, "best_name": best_name,
                   "cls_best": cls_best,
                   "leader": locals().get("_ldr"),
                   "gap_ahead": None, "name_ahead": "", "ahead_pit": False,
                   "gap_behind": None, "name_behind": "", "place": None,
                   "class_place": None, "class_count": None, "yellow": False}
            if pl is not None:
                out["place"] = pl.get("place")
                # ORDINE DI MARCIA di classe: chi ha percorso piu' strada e' davanti
                mates = [c for c in cars if c["cls"] == pl["cls"]]
                out["class_count"] = len(mates)
                # POSIZIONE di classe dalla CLASSIFICA UFFICIALE (mPlace):
                # il progress mente — un ritirato fermo in garage con piu'
                # strada percorsa risultava "davanti" (overlay 16/19 con il
                # gioco che diceva 15/19). Il gioco classifica, noi contiamo.
                myp = int(pl.get("place") or 0)
                if myp > 0:
                    out["class_place"] = 1 + sum(
                        1 for c in mates
                        if c is not pl and 0 < int(c.get("place") or 0) < myp)
                else:                       # fallback: ordine di marcia
                    out["class_place"] = 1 + sum(
                        1 for c in mates
                        if c is not pl and c["progress"] > pl["progress"] + 1e-6)
                # davanti/dietro = i piu' vicini nell'ordine di marcia di classe
                ahead = None
                behind = None
                for c in mates:
                    if c is pl:
                        continue
                    # fermo in pit/garage = non e' un rivale in pista (ma chi
                    # ATTRAVERSA la corsia box resta: serve all'undercut)
                    if c["in_pits"] and (c["speed"] or 0.0) < 3.0:
                        continue
                    if c["progress"] > pl["progress"] + 1e-6:
                        if ahead is None or c["progress"] < ahead["progress"]:
                            ahead = c
                    elif c["progress"] < pl["progress"] - 1e-6:
                        if behind is None or c["progress"] > behind["progress"]:
                            behind = c

                lead_laps = max((c["laps"] for c in cars), default=0)

                def _gap_s(a, b):
                    """gap a tempo tra a (davanti) e b (dietro). behind_leader e'
                    affidabile SOLO se nessuno dei due e' doppiato dal leader
                    (per i doppiati LMU riporta valori sballati): in quel caso
                    stima distanza / velocita' media dei due (clampata)."""
                    if (a["laps"] == b["laps"] == lead_laps):
                        g = b["behind_leader"] - a["behind_leader"]
                        if 0.0 <= g <= 600.0:
                            return g
                    spd = 0.5 * ((a["speed"] or 0.0) + (b["speed"] or 0.0))
                    spd = max(25.0, min(100.0, spd))
                    return max(0.0, (a["progress"] - b["progress"]) / spd)

                out["my_stops"] = pl.get("stops")
                if ahead is not None:
                    out["gap_ahead"] = _gap_s(ahead, pl)
                    out["name_ahead"] = ahead["name"]
                    out["ahead_stops"] = ahead.get("stops")
                    # DUE stati distinti: la CHIAMATA pit (state 1, si vede
                    # in TV ma l'auto e' ancora in pista) NON e' "ai box".
                    out["ahead_pit_req"] = (ahead["pit"] == 1
                                            and not ahead["in_pits"])
                    out["ahead_pit"] = (ahead["in_pits"]
                                        or ahead["pit"] in (2, 3))
                if behind is not None:
                    out["gap_behind"] = _gap_s(pl, behind)
                    out["name_behind"] = behind["name"]
                    out["behind_stops"] = behind.get("stops")
                # TRAFFICO TOTALE dietro (TUTTE le classi): serve per simulare il
                # rientro dai box (chi ti ritroverai davanti/attorno all'uscita).
                traffic = []
                for c in cars:
                    # IN PIT = fuori dal traffico: flag FISICO (corsia box o
                    # garage, anche con pit-state 0). La sola RICHIESTA di pit
                    # (state 1) non toglie l'auto dalla pista: e' traffico.
                    if c is pl or c["in_pits"] or c["pit"] in (2, 3):
                        continue
                    if c["progress"] < pl["progress"] - 1e-6:
                        g = _gap_s(pl, c)
                        if 0.0 < g <= 90.0:
                            traffic.append({"gap": round(g, 1), "cls": c["cls"],
                                            "name": c["name"]})
                traffic.sort(key=lambda t: t["gap"])
                out["traffic_behind"] = traffic[:14]
                # TRAFFICO DAVANTI per lo spotter: DOPPIATI (meno giri) o DA
                # DOPPIARE (classe piu' lenta) nei prossimi 500 m, e conta solo
                # il GRUPPO vero: auto a <=1 secondo l'una dall'altra in fila.
                # Tre auto sparse su 1,5 km non sono traffico.
                def _cls_rank(cs):
                    cu = (cs or "").upper()
                    if "HY" in cu or "LMH" in cu or "LMDH" in cu:
                        return 0
                    if "P2" in cu:
                        return 1
                    if "P3" in cu:
                        return 2
                    if "GT3" in cu:
                        return 3
                    if "GTE" in cu:
                        return 4
                    return 9
                my_rank = _cls_rank(pl["cls"])
                my_ld = pl["progress"] - pl["laps"] * track_len
                cand = []
                for c in cars:
                    if c is pl or c["in_pits"] or c["pit"] in (2, 3):
                        continue
                    lapped = c["laps"] < pl["laps"]
                    slower = (c["laps"] == pl["laps"]
                              and _cls_rank(c["cls"]) > my_rank)
                    if not (lapped or slower):
                        continue
                    c_ld = c["progress"] - c["laps"] * track_len
                    dr = (c_ld - my_ld) % track_len
                    if 0.0 < dr <= 500.0:
                        cand.append((dr, c))
                cand.sort(key=lambda x: x[0])
                # catena piu' lunga con gap <=1 s tra auto CONSECUTIVE.
                # Il secondo si misura sulla DISTANZA FISICA in pista (dr):
                # il progress include i giri, e due doppiati incollati ma su
                # giri diversi non risulterebbero MAI in fila.
                def _dt_fila(a, b):
                    spd = 0.5 * ((a[1]["speed"] or 0.0) + (b[1]["speed"] or 0.0))
                    spd = max(25.0, min(100.0, spd))
                    return (b[0] - a[0]) / spd
                ta_n = 0
                ta_near = None
                i = 0
                while i < len(cand):
                    j = i
                    while (j + 1 < len(cand)
                           and _dt_fila(cand[j], cand[j + 1]) <= 1.0):
                        j += 1
                    size = j - i + 1
                    if size > ta_n:
                        ta_n = size
                        ta_near = cand[i][0]
                    i = j + 1
                out["traffic_ahead"] = {"count": ta_n,
                                        "near": round(ta_near) if ta_near else None}
            try:
                sf = si.mSectorFlag
                out["yellow"] = any(int(sf[k]) for k in range(3))
            except Exception:
                pass
            try:
                ys = si.mYellowFlagState
                yv = ys if isinstance(ys, int) else int.from_bytes(ys, "little")
                if yv not in (0,):
                    out["yellow"] = True
            except Exception:
                pass
            return out
        except Exception:
            self._sim = None
            return None

    def car_states(self):
        """Snapshot per-auto (rivali): {id: {name, cls, pen, last, place}}.
        Serve a rilevare penalita' NUOVE e cali di passo dei rivali. {} se non
        disponibile. LMU espone il CONTATORE penalita' (non il tipo)."""
        try:
            sim = self._get_sim()
            if not sim:
                return {}
            from pyLMUSharedMemory.lmu_data import MAX_MAPPED_VEHICLES as _MX
            si = sim.scoring.scoringInfo
            num = int(si.mNumVehicles)
            out = {}
            for i in range(min(num, _MX)):
                v = sim.scoring.vehScoringInfo[i]
                if int(getattr(v, "mIsPlayer", 0)):
                    continue
                nm = bytes(v.mDriverName).split(b"\x00")[0].decode("utf-8", "ignore")
                cls = bytes(v.mVehicleClass).split(b"\x00")[0]\
                    .decode("utf-8", "ignore")
                out[int(v.mID)] = {
                    "name": nm, "cls": cls,
                    "pen": int(getattr(v, "mNumPenalties", 0) or 0),
                    "last": float(getattr(v, "mLastLapTime", -1) or -1),
                    "place": int(getattr(v, "mPlace", 0) or 0),
                }
            return out
        except Exception:
            return {}

    def flags(self):
        """Bandiere: distanza (m) auto lenta più vicina davanti sotto gialla e
        sua classe; classe dell'auto che ti doppia (blu); penalità; scacchi.
        Logica copiata dal flag reader dell'overlay."""
        try:
            sim = self._get_sim()
            if not sim:
                return None
            from pyLMUSharedMemory.lmu_data import MAX_MAPPED_VEHICLES as _MX
            from core.classes import class_tag
            si = sim.scoring.scoringInfo
            num = int(si.mNumVehicles)
            track_len = float(si.mLapDist)
            pidx = -1
            for i in range(min(num, _MX)):
                if int(sim.scoring.vehScoringInfo[i].mIsPlayer) == 1:
                    pidx = i
                    break
            if pidx < 0:
                return None
            vp = sim.scoring.vehScoringInfo[pidx]
            my_dist = float(vp.mLapDist)
            my_laps = int(vp.mTotalLaps)
            my_cls = bytes(vp.mVehicleClass).split(b"\x00")[0].decode("utf-8", "ignore")
            _RANK = {"HY": 4, "P2": 3, "P3": 2, "GT3": 1, "GTE": 1}
            my_rank = _RANK.get(class_tag(my_cls), 0)
            out = {"num_penalties": int(vp.mNumPenalties),
                   "checkered": (int(si.mGamePhase) == 8),
                   "finished": (int(getattr(vp, "mFinishStatus", 0) or 0) == 1),
                   "yellow_dist": None, "yellow_class": None, "blue_class": None}
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

            ny = None
            ny_cls = None
            nb_cls = None
            nb_dist = None
            nb_count = 0
            nb_name = ""
            nb_car = ""
            nb_cand = []            # (rd, spd, classe, vettura) nei 300 m
            # NON auto-segnalarti: se sei TU quello lento sotto gialla
            # (testacoda/fermo), il pericolo sei tu e non serve dirtelo.
            # Esporto il flag: l'ingegnere lo usa per tacere anche subito dopo.
            out["self_slow"] = bool(yellow_active and car_speed(vp) < 8.0)
            for i in range(min(num, _MX)):
                if i == pidx:
                    continue
                v = sim.scoring.vehScoringInfo[i]
                if bool(v.mInPits):
                    continue
                spd = car_speed(v)
                rd = rel_dist(float(v.mLapDist))
                vcls = bytes(v.mVehicleClass).split(b"\x00")[0].decode("utf-8", "ignore")
                if yellow_active and spd < 8.0 and 0 <= rd <= 500.0:
                    if ny is None or rd < ny:
                        ny = rd
                        ny_cls = vcls
                # BLU come la espone IL GIOCO (under_blue), finestra 300 m:
                # qui si RACCOLGONO le candidate; il conteggio a GRUPPO e'
                # dopo il ciclo (catena <=1 s, come il traffico davanti).
                if under_blue and -300.0 <= rd < 0:
                    vrank = _RANK.get(class_tag(vcls), 0)
                    if (vrank > my_rank) or (int(v.mTotalLaps) > my_laps):
                        nb_cand.append((rd, spd, vcls, v))
            # BLU a GRUPPO VERO: "N auto in arrivo" solo se sono in FILA —
            # catena dalla piu' vicina, gap <=1 s tra auto CONSECUTIVE
            # (stessa regola di traffic_ahead per i doppiati davanti).
            # Prima contava TUTTO il finestrone dei 300 m: "4 auto" con due
            # vere e due sgranate a 4-5 secondi non e' un gruppo.
            if nb_cand:
                nb_cand.sort(key=lambda c: -c[0])   # rd 0- : piu' vicina prima
                nb_dist, _spd0, nb_cls, _v0 = nb_cand[0]
                nb_count = 1
                try:
                    nb_name = bytes(_v0.mDriverName).split(b"\x00")[0]\
                        .decode("utf-8", "ignore").strip()
                except Exception:
                    nb_name = ""
                try:
                    nb_car = bytes(_v0.mVehicleName).split(b"\x00")[0]\
                        .decode("utf-8", "ignore").strip()
                except Exception:
                    nb_car = ""
                _prev = nb_cand[0]
                for _c in nb_cand[1:]:
                    _sp = 0.5 * ((_prev[1] or 0.0) + (_c[1] or 0.0))
                    _sp = max(25.0, min(100.0, _sp))
                    if (_prev[0] - _c[0]) / _sp <= 1.0:
                        nb_count += 1
                        _prev = _c
                    else:
                        break
            out["yellow_dist"] = ny
            out["yellow_class"] = ny_cls
            out["blue_class"] = nb_cls
            out["blue_count"] = nb_count
            out["blue_dist"] = (round(-nb_dist) if nb_dist is not None else None)
            out["blue_name"] = nb_name
            out["blue_car"] = nb_car
            return out
        except Exception:
            return None

    def tyre_damage(self):
        """Danni del pilota: {'flat':[4],'detached':[4],'dent':0..2}.
        flat = gomma a terra/flat-spot, detached = ruota staccata,
        dent = severita' massima ammaccature carrozzeria (0 nessuna..2 grave)."""
        try:
            sim = self._get_sim()
            if not sim or not sim.telemetry:
                return None
            num = int(sim.scoring.scoringInfo.mNumVehicles)
            pid = None
            for i in range(min(num, _MAX_VEH)):
                v = sim.scoring.vehScoringInfo[i]
                if bool(v.mIsPlayer):
                    pid = int(v.mID); break
            if pid is None:
                return None
            t = None
            for i in range(min(num, _MAX_VEH)):
                ti = sim.telemetry.telemInfo[i]
                if int(ti.mID) == pid:
                    t = ti; break
            if t is None:
                return None
            flat = [bool(t.mWheels[w].mFlat) for w in range(4)]
            det = [bool(t.mWheels[w].mDetached) for w in range(4)]
            try:
                dent = max(int(t.mDentSeverity[k]) for k in range(8))
            except Exception:
                dent = 0
            return {"flat": flat, "detached": det, "dent": dent}
        except Exception:
            return None

    def get_weather(self):
        """{'air':°C, 'track':°C, 'wet':bool, 'raining':0-1, 'wetness':0-1}.
        wet=True se pista bagnata (wetness o pioggia significativa)."""
        try:
            sim = self._get_sim()
            if not sim:
                return None
            si = sim.scoring.scoringInfo
            air = float(si.mAmbientTemp)
            track = float(si.mTrackTemp)
            raining = float(si.mRaining)
            wetness = float(si.mAvgPathWetness)
            wet = (wetness > 0.10) or (raining > 0.10)
            return {"air": air, "track": track, "wet": wet,
                    "raining": raining, "wetness": wetness}
        except Exception:
            self._sim = None
            return None

    def get_session_time(self):
        """Tempo di gara trascorso in secondi (mCurrentET). Parte da 0 al via,
        anche online. None se non disponibile."""
        try:
            sim = self._get_sim()
            if not sim:
                return None
            return float(sim.scoring.scoringInfo.mCurrentET)
        except Exception:
            self._sim = None
            return None

    def get_track_name(self):
        """Nome circuito corrente (mTrackName), stringa. '' se non disponibile."""
        try:
            sim = self._get_sim()
            if not sim:
                return ""
            raw = bytes(sim.scoring.scoringInfo.mTrackName)
            return raw.split(b"\x00")[0].decode("utf-8", "ignore").strip()
        except Exception:
            self._sim = None
            return ""

    def get_session_clock(self):
        """(total_et, current_et, time_of_day) in secondi.
        total_et = durata sessione (mEndET), 0 se non disponibile."""
        try:
            sim = self._get_sim()
            if not sim:
                return 0.0, 0.0, 43200.0
            si = sim.scoring.scoringInfo
            total = float(si.mEndET) if si.mEndET > 0 else 0.0
            cur = float(si.mCurrentET)
            tod = float(si.mTimeOfDay)
            return total, cur, tod
        except Exception:
            self._sim = None
            return 0.0, 0.0, 43200.0

    def get_positions(self):
        """(track_len, {mID: mLapDist}) — distanza sul giro di ogni auto.

        Usato per il gap LIVE in gara (come il Relative): la differenza di
        distanza in pista convertita in tempo si aggiorna a ogni frame, non
        solo ai punti di cronometraggio.
        """
        try:
            sim = self._get_sim()
            if not sim:
                return 0.0, {}
            si = sim.scoring.scoringInfo
            track_len = float(si.mLapDist)
            out = {}
            num = int(si.mNumVehicles)
            for i in range(min(num, _MAX_VEH)):
                v = sim.scoring.vehScoringInfo[i]
                out[int(v.mID)] = float(v.mLapDist)
            return track_len, out
        except Exception:
            return 0.0, {}

    def get_totals(self):
        """(track_len, {mID: distanza_totale}) — distanza monotona crescente
        (giri completati * lunghezza pista + mLapDist). Serve al gap a TEMPO
        (confronto dell'istante in cui due auto passano lo stesso punto)."""
        try:
            sim = self._get_sim()
            if not sim:
                return 0.0, {}
            si = sim.scoring.scoringInfo
            track_len = float(si.mLapDist)
            out = {}
            num = int(si.mNumVehicles)
            for i in range(min(num, _MAX_VEH)):
                v = sim.scoring.vehScoringInfo[i]
                laps = max(0, int(v.mTotalLaps))
                out[int(v.mID)] = laps * track_len + float(v.mLapDist)
            return track_len, out
        except Exception:
            return 0.0, {}

    def get_yellow_phases(self) -> dict:
        """{mID: bool} — mIndividualPhase==10 oppure mUnderYellow."""
        try:
            sim = self._get_sim()
            if not sim:
                return {}
            num = int(sim.scoring.scoringInfo.mNumVehicles)
            out = {}
            for i in range(min(num, _MAX_VEH)):
                v = sim.scoring.vehScoringInfo[i]
                out[int(v.mID)] = (int(v.mIndividualPhase) == 10 or bool(v.mUnderYellow))
            return out
        except Exception:
            self._sim = None
            return {}

    # ── COMPOUND GOMME per-driver ─────────────────────────────────────
    @_ttl_cache(0.5)
    def get_compounds(self) -> dict:
        """{mID: 'S'|'M'|'H'|'W'|...} per ogni veicolo nello scoring."""
        try:
            sim = self._get_sim()
            if not sim:
                return {}
            out = {}
            num = int(sim.scoring.scoringInfo.mNumVehicles)
            for i in range(min(num, _MAX_VEH)):
                vid = int(sim.scoring.vehScoringInfo[i].mID)
                out[vid] = sim.get_compound_name(i)
            return out
        except Exception:
            self._sim = None
            return {}

    @_ttl_cache(0.5)
    def get_pitstops(self) -> dict:
        """{mID: num_pitstops} per ogni auto (mNumPitstops nello scoring)."""
        try:
            sim = self._get_sim()
            if not sim:
                return {}
            out = {}
            num = int(sim.scoring.scoringInfo.mNumVehicles)
            for i in range(min(num, _MAX_VEH)):
                v = sim.scoring.vehScoringInfo[i]
                out[int(v.mID)] = int(v.mNumPitstops)
            return out
        except Exception:
            return {}

    @_ttl_cache(0.5)
    def get_sectors(self) -> dict:
        """{mID: {'last': [s1,s2,s3], 'best': [s1,s2,s3], 'cur': [s1,s2]}} per ogni auto.

        I campi scoring danno sector2 CUMULATIVO (s1+s2), quindi ricavo i singoli.
        s3 si ricava: lastLap - lastSector2. -1 se non disponibile.
        """
        try:
            sim = self._get_sim()
            if not sim:
                return {}
            out = {}
            num = int(sim.scoring.scoringInfo.mNumVehicles)
            for i in range(min(num, _MAX_VEH)):
                v = sim.scoring.vehScoringInfo[i]
                mid = int(v.mID)
                # last
                ls1 = float(v.mLastSector1)
                ls2c = float(v.mLastSector2)   # cumulativo s1+s2
                llap = float(v.mLastLapTime)
                ls2 = (ls2c - ls1) if (ls1 > 0 and ls2c > 0) else -1
                ls3 = (llap - ls2c) if (llap > 0 and ls2c > 0) else -1
                # best (settori del best lap)
                bs1 = float(v.mBestLapSector1)
                bs2c = float(v.mBestLapSector2)
                blap = float(v.mBestLapTime)
                bs2 = (bs2c - bs1) if (bs1 > 0 and bs2c > 0) else -1
                bs3 = (blap - bs2c) if (blap > 0 and bs2c > 0) else -1
                # cur (settori in corso)
                cs1 = float(v.mCurSector1)
                cs2c = float(v.mCurSector2)
                cs2 = (cs2c - cs1) if (cs1 > 0 and cs2c > 0) else -1
                out[mid] = {
                    "last": [ls1 if ls1 > 0 else -1, ls2, ls3],
                    "best": [bs1 if bs1 > 0 else -1, bs2, bs3],
                    "cur":  [cs1 if cs1 > 0 else -1, cs2],
                    "sector": int(v.mSector),  # 0=S3,1=S1,2=S2
                }
            return out
        except Exception:
            return {}

    def get_pit_count(self) -> dict:
        return self.get_pitstops()

    @_ttl_cache(0.5)
    def get_tyre_wear(self) -> dict:
        """{mID: wear_pct} usura gomme per ogni auto (0-100, 100=nuova).

        mWear è 'fraction of maximum' rimanente: 1.0=nuova, 0.0=finita.
        Faccio la media delle 4 ruote. Disponibile per TUTTI i piloti.
        """
        try:
            sim = self._get_sim()
            if not sim or not sim.telemetry:
                return {}
            out = {}
            num = int(sim.scoring.scoringInfo.mNumVehicles)
            for i in range(min(num, _MAX_VEH)):
                t = sim.telemetry.telemInfo[i]
                tid = int(t.mID)
                try:
                    ws = [float(t.mWheels[w].mWear) for w in range(4)]
                    avg = sum(ws) / 4.0
                    out[tid] = round(avg * 100, 0)
                except Exception:
                    out[tid] = None
            return out
        except Exception:
            return {}

    @_ttl_cache(0.5)
    def get_track_limits(self) -> dict:
        """{mID: {'steps': int, 'per_penalty': int, 'per_point': int}} per ogni auto.

        mTrackLimitsSteps (telemetry per veicolo) = punti accumulati.
        mTrackLimitsStepsPerPenalty / PerPoint (scoring globale) = soglie.
        Penalità quando steps >= per_penalty. Track limit "pieno" = per_point.
        """
        try:
            sim = self._get_sim()
            if not sim or not sim.telemetry:
                return {}
            si = sim.scoring.scoringInfo
            try:
                per_penalty = int(si.mTrackLimitsStepsPerPenalty)
            except Exception:
                per_penalty = 0
            try:
                per_point = int(si.mTrackLimitsStepsPerPoint)
            except Exception:
                per_point = 0
            out = {}
            from pyLMUSharedMemory.lmu_data import MAX_MAPPED_VEHICLES as _MM
            num = int(si.mNumVehicles)
            for i in range(min(num, _MM)):
                t = sim.telemetry.telemInfo[i]
                tid = int(t.mID)
                try:
                    steps = int(t.mTrackLimitsSteps)
                except Exception:
                    steps = 0
                out[tid] = {"steps": steps, "per_penalty": per_penalty, "per_point": per_point}
            return out
        except Exception:
            return {}

    def player_track_limits(self):
        """{'steps','per_penalty','per_point'} del solo giocatore, o None."""
        try:
            states = self.get_car_states()
            pid = next((mid for mid, s in states.items() if s.get("is_player")), None)
            if pid is None:
                return None
            return self.get_track_limits().get(pid)
        except Exception:
            return None

    def get_lap_valid(self) -> dict:
        """{mID: bool} — True se l'ultimo giro è valido (conta il tempo).

        mCountLapFlag: 0=non contare, 1=conta giro ma NON il tempo (invalido
        per track limits), 2=conta giro e tempo (valido). Disponibile per
        ogni auto nello scoring (come TinyPedal).
        """
        try:
            sim = self._get_sim()
            if not sim:
                return {}
            out = {}
            num = int(sim.scoring.scoringInfo.mNumVehicles)
            for i in range(min(num, _MAX_VEH)):
                v = sim.scoring.vehScoringInfo[i]
                out[int(v.mID)] = (int(v.mCountLapFlag) >= 2)
            return out
        except Exception:
            return {}

    @_ttl_cache(0.5)
    def get_compounds_4(self) -> dict:
        """{mID: ['S','M','H','W'(x4 ruote FL,FR,RL,RR)]} per ogni veicolo.

        Legge mWheels[].mCompoundType dal telemetry di OGNI veicolo
        (come TinyPedal), indicizzato dal proprio mID.
        """
        _CT = {0: "S", 1: "M", 2: "H", 3: "W"}
        try:
            sim = self._get_sim()
            if not sim or not sim.telemetry:
                return {}
            out = {}
            from pyLMUSharedMemory.lmu_data import MAX_MAPPED_VEHICLES as _MM
            num = int(sim.scoring.scoringInfo.mNumVehicles)
            for i in range(min(max(num, 0), _MM)):
                t = sim.telemetry.telemInfo[i]
                tid = int(t.mID)
                try:
                    four = [_CT.get(int(t.mWheels[w].mCompoundType), "") for w in range(4)]
                except Exception:
                    four = ["", "", "", ""]
                # il tipo intero in garage cade sul default (2=H): se il NOME del
                # compound e' valido (mFrontTireCompoundName, affidabile anche ai
                # box) usa quello come fonte autorevole (mescola singola).
                try:
                    nm = sim.get_compound_name(i)
                    if nm:
                        four = [nm, nm, nm, nm]
                except Exception:
                    pass
                out[tid] = four
            return out
        except Exception:
            return {}

    @_ttl_cache(0.5)
    def get_all_maps(self) -> dict:
        """Tutte le mappe per-auto in UNA passata scoring + UNA telemetry,
        invece di 6-8 giri separati. Riduce drasticamente il picco di lavoro
        quando standings/relative ricalcolano (1×/sec). Cacheato e condiviso.

        Ritorna: compounds, compounds4, sectors, wear, track_limits,
        pitstops, car_states, lap_valid (stessa struttura dei get_* singoli).
        """
        empty = {"compounds": {}, "compounds4": {}, "sectors": {}, "wear": {},
                 "track_limits": {}, "pitstops": {}, "car_states": {}, "lap_valid": {}}
        try:
            sim = self._get_sim()
            if not sim:
                return empty
            compounds = {}; sectors = {}; pitstops = {}; car_states = {}; lap_valid = {}
            num = int(sim.scoring.scoringInfo.mNumVehicles)
            n = min(num, _MAX_VEH)
            # ── UNA passata su scoring ──
            for i in range(n):
                v = sim.scoring.vehScoringInfo[i]
                mid = int(v.mID)
                # compound (gomma attuale)
                try:
                    compounds[mid] = sim.get_compound_name(i)
                except Exception:
                    compounds[mid] = ""
                # settori
                ls1 = float(v.mLastSector1); ls2c = float(v.mLastSector2); llap = float(v.mLastLapTime)
                ls2 = (ls2c - ls1) if (ls1 > 0 and ls2c > 0) else -1
                ls3 = (llap - ls2c) if (llap > 0 and ls2c > 0) else -1
                bs1 = float(v.mBestLapSector1); bs2c = float(v.mBestLapSector2); blap = float(v.mBestLapTime)
                bs2 = (bs2c - bs1) if (bs1 > 0 and bs2c > 0) else -1
                bs3 = (blap - bs2c) if (blap > 0 and bs2c > 0) else -1
                cs1 = float(v.mCurSector1); cs2c = float(v.mCurSector2)
                cs2 = (cs2c - cs1) if (cs1 > 0 and cs2c > 0) else -1
                sectors[mid] = {
                    "last": [ls1 if ls1 > 0 else -1, ls2, ls3],
                    "best": [bs1 if bs1 > 0 else -1, bs2, bs3],
                    "cur":  [cs1 if cs1 > 0 else -1, cs2],
                    "sector": int(v.mSector),
                }
                # pitstops
                pitstops[mid] = int(v.mNumPitstops)
                # stato auto
                vv = v.mLocalVel
                speed = (vv.x * vv.x + vv.y * vv.y + vv.z * vv.z) ** 0.5
                try:
                    garage = bool(v.mInGarageStall)
                except Exception:
                    garage = False
                car_states[mid] = {
                    "in_pits": bool(v.mInPits),
                    "garage": garage,
                    "moving": speed > 3.0,
                    "is_player": bool(v.mIsPlayer),
                }
                # lap valid
                lap_valid[mid] = (int(v.mCountLapFlag) >= 2)

            # ── UNA passata su telemetry (gomme×4, usura, track limits) ──
            compounds4 = {}; wear = {}; track_limits = {}
            _CT = {0: "S", 1: "M", 2: "H", 3: "W"}
            tel = getattr(sim, "telemetry", None)
            if tel:
                si = sim.scoring.scoringInfo
                try:
                    per_penalty = int(si.mTrackLimitsStepsPerPenalty)
                except Exception:
                    per_penalty = 0
                try:
                    per_point = int(si.mTrackLimitsStepsPerPoint)
                except Exception:
                    per_point = 0
                for i in range(n):
                    t = tel.telemInfo[i]
                    tid = int(t.mID)
                    try:
                        compounds4[tid] = [_CT.get(int(t.mWheels[w].mCompoundType), "") for w in range(4)]
                    except Exception:
                        compounds4[tid] = ["", "", "", ""]
                    # nome compound (affidabile ai box) prevale sul tipo intero
                    # che in garage cade sul default (2=H)
                    try:
                        nm = sim.get_compound_name(i)
                        if nm:
                            compounds4[tid] = [nm, nm, nm, nm]
                    except Exception:
                        pass
                    try:
                        ws = [float(t.mWheels[w].mWear) for w in range(4)]
                        wear[tid] = round(sum(ws) / 4.0 * 100, 0)
                    except Exception:
                        wear[tid] = None
                    try:
                        steps = int(t.mTrackLimitsSteps)
                    except Exception:
                        steps = 0
                    track_limits[tid] = {"steps": steps, "per_penalty": per_penalty, "per_point": per_point}

            return {"compounds": compounds, "compounds4": compounds4, "sectors": sectors,
                    "wear": wear, "track_limits": track_limits, "pitstops": pitstops,
                    "car_states": car_states, "lap_valid": lap_valid}
        except Exception:
            self._sim = None
            return empty
