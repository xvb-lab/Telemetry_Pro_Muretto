"""
core/race_control.py — RACE CONTROL vero dal trace di LMU.

Il motore scrive nel trace i motivi delle penalita' (Speeding In
Pitlane, Track Limits, Driving Too Slow...) che REST e shared memory
NON espongono. Qui un tail condiviso (un thread solo per processo,
avvio pigro) sul trace piu' recente: latest_penalty() -> (t, motivo,
is_local). Solo eventi NUOVI da quando parte l'app.
"""
import glob
import os
import re
import threading
import time

_LOCK = threading.Lock()
_STATE = {"t": 0.0, "reason": "", "kind": "", "local": True,
          "pending": []}
# TRACK LIMITS dal trace: MACCHINA A STATI del ciclo vero di LMU
# (guida ufficiale + trace verificati):
#   Off Track            -> investigation APERTA ("under review")
#   Back On Track        -> rientrato, LMU valuta per 2-5s (se restituisci)
#   No Track Cut         -> PERDONATO (esito "clear")
#   Warning              -> WARNING assegnato (in prova/quali = giro invalidato)
#   Local penalty "Track Limits" -> DT (dal flusso penalita', gia' gestito)
# La riga 581 porta i numeri: WarnPts (punti warning), Pts (punti evento,
# negativi = tempo perso), PlaceDiff (punti da sorpasso illegale).
_TL = {"state": "idle", "t": 0.0, "warn": 0.0, "pts": 0.0,
       "placediff": 0.0, "outcome": None, "out_t": 0.0}
_RX_TLNUM = re.compile(r"WarnPts:\s*([\-\d.]+)\s+Pts:\s*([\-\d.]+)\s+ET:"
                       r".*?PlaceDiff:\s*([\-\d.]+)", re.I)
_STARTED = False

_DIRS = [
    r"C:\Program Files (x86)\Steam\steamapps\common"
    r"\Le Mans Ultimate\UserData\Log",
    r"C:\SteamLibrary\steamapps\common\Le Mans Ultimate\UserData\Log",
    r"D:\SteamLibrary\steamapps\common\Le Mans Ultimate\UserData\Log",
]
_RX = re.compile(r"(Queued local|Local|Network) penalty"
                 r"\s+et=\s*[\d.]+\s+(.+?)\s*$", re.I)
# pitmod.cpp logga lo SCONTO ("Startinig" = typo del gioco, verificato):
#   Startinig pitstop at X, will run till: Y. Description: Stop and go 10 sec
_RX_SERVE = re.compile(r"Startini?g pitstop .*?Description:\s*(.+?)\s*$",
                       re.I)
# DANNI FISICI dal trace (scoperti 23/07 sull'incidente Ascari):
#   hdvehicle "Bending wheel #N with severity S (toe: T; camber: C)"
#   -> ruota del GIOCATORE piegata (hdvehicle = fisica alta = solo player);
#   0=ant.sx 1=ant.dx 2=post.sx 3=post.dx. severity 0..1, toe/camber = di
#   quanto e' storto l'assetto (la macchina tira da un lato).
_RX_BEND = re.compile(r"Bending wheel #(\d) with severity ([\d.]+)"
                      r" \(toe: ([-\d.]+); camber: ([-\d.]+)\)")
# score.cpp: LocalDNF for driver "Nome" due to Engine/Suspension/Accident
# -> CAUSA del ritiro (il motore morto che REST/shared memory non danno)
_RX_DNF = re.compile(r'LocalDNF for driver "([^"]+)" due to (\w+)')
_DMG = {"bends": [], "dnf_t": 0.0, "dnf_driver": "", "dnf_reason": ""}


def _parse(rest):
    """'1 0 0 0 \"Speeding\"' -> (kind, reason). Dal formato vero:
    primo numero > 0 = DRIVE THROUGH, secondo = secondi aggiunti."""
    qm = re.search(r'"([^"]+)"', rest)
    reason = qm.group(1).strip().upper() if qm else ""
    nums = [int(x) for x in re.findall(r"\b\d+\b",
                                       re.sub(r'"[^"]*"', "", rest))]
    kind = ""
    if nums and nums[0] > 0:
        kind = "DRIVE THROUGH"
    elif len(nums) > 1 and nums[1] > 0:
        kind = "STOP & GO %dS" % nums[1]   # verificato in gioco
    elif len(nums) > 2 and (nums[2] > 0 or (len(nums) > 3
                                            and nums[3] > 0)):
        # campi 3/4: TEMPO AGGIUNTO (+5s/+10s, es. out-of-line alla
        # rolling start) — da confermare con una riga trace reale
        kind = "+%dS" % (nums[2] or nums[3])
    return kind, reason


def _feed(line, live):
    """Una riga di trace -> aggiorna lo stato. live=False in preload
    (niente t => banner e ingegnere non annunciano il passato)."""
    # TRACK LIMITS: macchina a stati sul ciclo VERO (vedi commento _TL).
    # In preload gli eventi restano muti (t=0). Distinto da mCountLapFlag
    # (rumoroso: e' 1 anche a out-lap/partenza).
    if "Track Limits:" in line:
        now = time.monotonic() if live else 0.0
        with _LOCK:
            if "No Track Cut" in line:
                _TL["state"] = "idle"
                _TL["outcome"] = "clear"
                _TL["out_t"] = now
            elif "Warning;" in line:              # esito (non 'WarnPts')
                _TL["state"] = "idle"
                _TL["outcome"] = "warning"
                _TL["out_t"] = now
            elif "Off Track" in line:             # anche 'Off Track Again'
                if _TL["state"] != "review":      # episodio NUOVO: numeri
                    _TL["warn"] = _TL["pts"] = _TL["placediff"] = 0.0
                _TL["state"] = "review"
                _TL["t"] = now
                _TL["outcome"] = None
            elif "Back On Track" in line:         # valutazione 2-5s: resta review
                if _TL["state"] == "review":
                    _TL["t"] = now
            else:
                mn = _RX_TLNUM.search(line)
                if mn:                            # riga 581: numeri evento
                    try:
                        _TL["warn"] = float(mn.group(1))
                        _TL["pts"] = float(mn.group(2))
                        _TL["placediff"] = float(mn.group(3))
                    except (TypeError, ValueError):
                        pass
        return
    m = _RX.search(line)
    if m:
        kind, reason = _parse(m.group(2))
        src = m.group(1).lower()
        if src != "local":
            # in CODA il codice puo' essere provvisorio: il tipo lo
            # certifica solo la riga di applicazione "Local"
            kind = ""
        if reason:
            with _LOCK:
                if live:
                    _STATE["t"] = time.monotonic()
                _STATE["reason"] = reason
                _STATE["kind"] = kind
                _STATE["local"] = "local" in src
                if src == "local" and kind:
                    _STATE["pending"].append((kind, reason))
                    del _STATE["pending"][:-6]
        return
    m = _RX_BEND.search(line)
    if m and live:                    # preload muto: solo botte da ADESSO
        with _LOCK:
            _DMG["bends"].append((time.monotonic(), int(m.group(1)),
                                  float(m.group(2)), float(m.group(3)),
                                  float(m.group(4))))
            del _DMG["bends"][:-12]
        return
    m = _RX_DNF.search(line)
    if m and live:
        with _LOCK:
            _DMG["dnf_t"] = time.monotonic()
            _DMG["dnf_driver"] = m.group(1).strip()
            _DMG["dnf_reason"] = m.group(2).strip()
        return
    m = _RX_SERVE.search(line)
    if m:
        desc = m.group(1).lower()
        want = ""
        if "stop" in desc and "go" in desc:
            want = "STOP"                    # verificato nel trace
        elif "drive" in desc:
            want = "DRIVE"                   # atteso, stesso formato
        if want:
            with _LOCK:
                pend = _STATE["pending"]
                for i, (k, _r) in enumerate(pend):
                    if k.startswith(want):
                        del pend[i]
                        break
                # il badge mostra la penalita' che RESTA (o niente)
                if pend:
                    _STATE["kind"], _STATE["reason"] = pend[-1]
                else:
                    _STATE["kind"] = ""
                    _STATE["reason"] = ""
        return
    if "Entered Steward::Restart()" in line:
        with _LOCK:
            del _STATE["pending"][:]         # le penalita' non
                                             # sopravvivono al restart
            del _DMG["bends"][:]             # nuova sessione: danni azzerati
            _DMG["dnf_t"] = 0.0
            _TL.update({"state": "idle", "t": 0.0, "outcome": None,
                        "out_t": 0.0, "warn": 0.0, "pts": 0.0,
                        "placediff": 0.0})


def _tail():
    logdir = next((d for d in _DIRS if os.path.isdir(d)), None)
    if not logdir:
        return
    cur, fh = None, None
    while True:
        try:
            traces = glob.glob(os.path.join(logdir, "trace*.txt"))
            if traces:
                newest = max(traces, key=os.path.getmtime)
                if newest != cur:
                    if fh:
                        fh.close()
                    cur = newest
                    fh = open(cur, encoding="utf-8", errors="ignore")
                    # PRELOAD: ultimo TIPO gia' in archivio (badge DT/SG
                    # corretto anche per penalita' prese prima dell'avvio;
                    # t resta 0 => banner e ingegnere NON annunciano)
                    try:
                        fh.seek(0, 2)
                        _sz = fh.tell()
                        fh.seek(max(0, _sz - 400000))
                        for line in fh.readlines():
                            _feed(line, live=False)
                    except Exception:
                        pass
                    fh.seek(0, 2)          # annunci solo da ADESSO
            if fh:
                for line in fh.readlines():
                    _feed(line, live=True)
        except Exception:
            pass
        time.sleep(0.2)     # reattivo: LMU scrive a blocchi, meno latenza


def latest_penalty():
    """(t_monotonic, motivo, is_local) dell'ULTIMA penalita' vista.
    t=0 se non ce ne sono ancora. Avvia il tail alla prima chiamata."""
    global _STARTED
    if not _STARTED:
        _STARTED = True
        threading.Thread(target=_tail, daemon=True).start()
    with _LOCK:
        txt = _STATE["reason"]
        if _STATE["kind"]:
            txt = "%s — %s" % (_STATE["kind"], txt)
        return _STATE["t"], txt, _STATE["local"]


def latest_penalty_parts():
    """(t, kind, reason, is_local) separati (per la voce ingegnere)."""
    latest_penalty()               # assicura il tail avviato
    with _LOCK:
        return (_STATE["t"], _STATE["kind"], _STATE["reason"],
                _STATE["local"])


def recent_wheel_bends(window=8.0):
    """Ruote piegate del giocatore negli ultimi `window` secondi:
    [(wheel 0..3, severity, toe, camber)] con la PEGGIORE per ruota.
    Vuoto se nessuna botta recente. Avvia il tail alla prima chiamata."""
    latest_penalty()               # assicura il tail avviato
    now = time.monotonic()
    worst = {}
    with _LOCK:
        for t, w, sev, toe, cam in _DMG["bends"]:
            if now - t <= window and sev > worst.get(w, (0.0,))[0]:
                worst[w] = (sev, toe, cam)
    return [(w, s[0], s[1], s[2]) for w, s in sorted(worst.items())]


def latest_dnf():
    """(t_monotonic, driver, causa) dell'ultimo ritiro visto nel trace.
    Cause vere di LMU: Engine, Suspension, Accident, Unknown. t=0 se
    nessuno da quando l'app e' partita."""
    latest_penalty()               # assicura il tail avviato
    with _LOCK:
        return _DMG["dnf_t"], _DMG["dnf_driver"], _DMG["dnf_reason"]


def track_limits_state(review_min=2.5, outcome_ttl=6.0, review_max=10.0):
    """Stato track-limits VERO dal trace (macchina a stati).

    Ritorna {'review': bool, 'outcome': 'clear'|'warning'|None,
             'warn_pts', 'pts', 'placediff'}.
    - review resta True per almeno `review_min` (i tagli lampo non si
      perdono nel blocco 0.5s del tail) e si spegne da solo dopo
      `review_max` senza esito (fail-safe).
    - outcome e' esposto per `outcome_ttl` secondi dall'esito, poi None.
    Preload (t=0) => mai attivo all'avvio. Niente mCountLapFlag."""
    latest_penalty()               # assicura il tail avviato
    now = time.monotonic()
    with _LOCK:
        t = _TL["t"]
        # OGNI taglio mostra SEMPRE almeno `review_min` di UNDER REVIEW,
        # anche se l'esito arriva nello stesso blocco di trace (LMU scrive
        # a blocchi: i tagli leggeri "verdi" si chiudevano in un colpo solo
        # e il review non si vedeva mai). Poi tocca all'esito.
        rev = bool(t) and (
            (_TL["state"] == "review" and (now - t) < review_max)
            or (now - t) < review_min)
        out = _TL["outcome"]
        if out and (not _TL["out_t"] or (now - _TL["out_t"]) > outcome_ttl):
            out = None
        return {"review": rev, "outcome": out,
                "warn_pts": _TL["warn"], "pts": _TL["pts"],
                "placediff": _TL["placediff"]}
