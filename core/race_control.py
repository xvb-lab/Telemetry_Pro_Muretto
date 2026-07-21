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
        time.sleep(0.5)


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
