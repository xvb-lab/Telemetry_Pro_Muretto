"""
telemetry/results_xml.py — la MINIERA dei Results XML di LMU (offline).

LMU scrive in UserData/Log/Results un XML per ogni sessione OFFLINE
(ConnectionType=Custom) con, per OGNI pilota (player e AI, stessa fisica):
per-giro tempo, settori s1-s3, topspeed, benzina/VE usati, USURA GOMMA
PER RUOTA (twfl/twfr/twrl/twrr, frazione residua), compound e pit.

Da qui si CALIBRA il degrado vero pista/classe/mescola:
  - wear_pct_lap    : usura media (4 ruote) per giro, in %
  - pace_drift_s_lap: deriva del passo per giro DENTRO lo stint (netto
                      benzina: e' il numero che serve alla strategia)
  - fuel_frac_lap / ve_frac_lap : consumo per giro (frazione serbatoio/VE)
  - stint_laps_med  : lunghezza tipica dello stint osservata
Metodo: mediane filtrate (niente regressioni: dentro lo stint usura e
benzina sono collineari e il fit a 2 variabili e' mal posto — la deriva
netta mediana e' robusta a traffico, gialle ed errori).

Output: %APPDATA%/LMU_TelemetryPro/learn/degradation.json
Uso a mano:  python -m telemetry.results_xml  [--limit N]
"""
import glob
import json
import os
import re
import time
import xml.etree.ElementTree as ET

_SECT = re.compile(r"^(TestDay|Practice|Qualify|Warmup|Race)\d*$", re.I)
_DOCTYPE = re.compile(r"<!DOCTYPE.*?\]\s*>|<!DOCTYPE[^>]*>", re.S)
_ENTITY = re.compile(r"&(?!amp;|lt;|gt;|quot;|apos;|#)\w+;")

RESULTS_DIRS = [
    r"C:\Program Files (x86)\Steam\steamapps\common"
    r"\Le Mans Ultimate\UserData\Log\Results",
    r"C:\SteamLibrary\steamapps\common\Le Mans Ultimate\UserData\Log\Results",
    r"D:\SteamLibrary\steamapps\common\Le Mans Ultimate\UserData\Log\Results",
]


def results_dir():
    for d in RESULTS_DIRS:
        if os.path.isdir(d):
            return d
    return None


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _load_root(path):
    """ET.fromstring con bonifica: via il DOCTYPE (entita' interne che
    ElementTree non risolve) e le entita' ignote."""
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        txt = f.read()
    txt = _DOCTYPE.sub("", txt)
    txt = _ENTITY.sub("", txt)
    return ET.fromstring(txt)


def parse_file(path):
    """-> {track, sessions:[{type, drivers:[{name, cls, car, player,
    laps:[{num,t,s1,s2,s3,top,fuel,fuel_used,ve,ve_used,tw,comp,pit}]}]}]}
    oppure None se il file non e' leggibile."""
    try:
        root = _load_root(path)
    except Exception:
        return None
    rr = root.find("RaceResults")
    if rr is None:
        return None
    track = (rr.findtext("TrackVenue") or rr.findtext("TrackCourse") or "").strip()
    out = {"file": os.path.basename(path), "track": track, "sessions": []}
    for sect in rr:
        if not _SECT.match(sect.tag or ""):
            continue
        sess = {"type": sect.tag, "drivers": []}
        for drv in sect.findall("Driver"):
            laps = []
            for lp in drv.findall("Lap"):
                a = lp.attrib
                tws = [_num(a.get(k)) for k in ("twfl", "twfr", "twrl", "twrr")]
                tws = [v for v in tws if v is not None]
                comp = (a.get("fcompound") or "").split(",")[-1].strip()
                laps.append({
                    "num": int(_num(a.get("num")) or 0),
                    "t": _num((lp.text or "").strip()),
                    "s1": _num(a.get("s1")), "s2": _num(a.get("s2")),
                    "s3": _num(a.get("s3")),
                    "top": _num(a.get("topspeed")),
                    "fuel": _num(a.get("fuel")),
                    "fuel_used": _num(a.get("fuelUsed")),
                    "ve": _num(a.get("ve")),
                    "ve_used": _num(a.get("veUsed")),
                    "tw": (sum(tws) / len(tws)) if tws else None,
                    "comp": comp,
                    "pit": a.get("pit") == "1",
                })
            if laps:
                sess["drivers"].append({
                    "name": (drv.findtext("Name") or "").strip(),
                    "cls": (drv.findtext("CarClass") or "").strip(),
                    "car": (drv.findtext("CarType") or "").strip(),
                    "player": (drv.findtext("isPlayer") or "0").strip() == "1",
                    "laps": laps,
                })
        if sess["drivers"]:
            out["sessions"].append(sess)
    return out if out["sessions"] else None


def _stints(laps):
    """Spezza i giri di un pilota in stint: pit, gomme nuove (usura che
    RISALE) o cambio mescola aprono uno stint nuovo."""
    stints = []
    cur = []
    prev = None
    for lp in sorted(laps, key=lambda q: q["num"]):
        fresh = (prev is not None and lp["tw"] is not None
                 and prev.get("tw") is not None and lp["tw"] > prev["tw"] + 0.005)
        comp_chg = (prev is not None and lp["comp"] and prev.get("comp")
                    and lp["comp"] != prev["comp"])
        if cur and (prev and prev.get("pit") or fresh or comp_chg):
            stints.append(cur)
            cur = []
        cur.append(lp)
        prev = lp
    if cur:
        stints.append(cur)
    return stints


def _med(v):
    s = sorted(v)
    n = len(s)
    if not n:
        return None
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def calibrate(files, progress=None):
    """Aggrega tutti i file -> profili degrado per pista/classe/mescola."""
    acc = {}     # (track, cls, comp) -> dict di liste
    n_files = n_laps = 0
    for i, path in enumerate(files):
        data = parse_file(path)
        if progress and i % 200 == 0:
            progress(i, len(files))
        if not data:
            continue
        n_files += 1
        for sess in data["sessions"]:
            # la DERIVA del passo e' pulita solo in GARA: in prova il pilota
            # migliora giro dopo giro e maschera il degrado vero
            _is_race = sess["type"].lower().startswith("race")
            for drv in sess["drivers"]:
                for st in _stints(drv["laps"]):
                    # giri VALIDI dello stint (tempo presente), senza
                    # il primo (out-lap / partenza)
                    clean = [q for q in st[1:] if q["t"] and q["t"] > 20.0]
                    if len(clean) < 4:
                        continue
                    med_t = _med([q["t"] for q in clean])
                    # filtro traffico/gialle/errori: entro l'8% della mediana
                    clean = [q for q in clean if q["t"] <= med_t * 1.08]
                    if len(clean) < 4:
                        continue
                    comp = clean[0]["comp"] or "?"
                    key = (data["track"], drv["cls"] or "?", comp)
                    b = acc.setdefault(key, {
                        "wear": [], "drift": [], "fuel": [], "ve": [],
                        "stint_len": [], "best": [], "top": [],
                        "n": 0, "n_player": 0, "n_stints": 0})
                    b["n_stints"] += 1
                    b["stint_len"].append(len(st))
                    b["best"].append(min(q["t"] for q in clean))
                    tops = [q["top"] for q in clean if q["top"]]
                    if tops:
                        b["top"].append(_med(tops))
                    prev = None
                    for q in clean:
                        b["n"] += 1
                        n_laps += 1
                        if drv["player"]:
                            b["n_player"] += 1
                        if q["fuel_used"]:
                            b["fuel"].append(q["fuel_used"])
                        if q["ve_used"]:
                            b["ve"].append(q["ve_used"])
                        if prev is not None:
                            if (q["tw"] is not None
                                    and prev.get("tw") is not None
                                    and q["num"] == prev["num"] + 1):
                                dw = (prev["tw"] - q["tw"]) * 100.0
                                if 0.0 <= dw < 5.0:
                                    b["wear"].append(dw)
                            if (_is_race and q["t"] and prev.get("t")
                                    and q["num"] == prev["num"] + 1):
                                b["drift"].append(q["t"] - prev["t"])
                        prev = q
    # riduzione a profili
    tracks = {}
    for (track, cls, comp), b in acc.items():
        if b["n"] < 8:
            continue          # campione troppo piccolo: fuori
        prof = {
            "wear_pct_lap": round(_med(b["wear"]), 4) if b["wear"] else None,
            "pace_drift_s_lap": round(_med(b["drift"]), 4) if b["drift"] else None,
            "fuel_frac_lap": round(_med(b["fuel"]), 5) if b["fuel"] else None,
            "ve_frac_lap": round(_med(b["ve"]), 5) if b["ve"] else None,
            "stint_laps_med": _med(b["stint_len"]),
            "best": round(min(b["best"]), 3) if b["best"] else None,
            "topspeed_med": round(_med(b["top"]), 1) if b["top"] else None,
            "n_laps": b["n"], "n_player_laps": b["n_player"],
            "n_stints": b["n_stints"],
        }
        tracks.setdefault(track, {}).setdefault(cls, {})[comp] = prof
    return {"generated": time.strftime("%Y-%m-%d %H:%M"),
            "files_read": n_files, "laps_used": n_laps, "tracks": tracks}


def out_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "LMU_TelemetryPro", "learn")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "degradation.json")


def load_profiles():
    """Profili gia' calibrati (per muretto/strategia). {} se mai girato."""
    try:
        with open(out_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def run(limit=None, progress=None):
    d = results_dir()
    if not d:
        return None
    files = sorted(glob.glob(os.path.join(d, "*.xml")), key=os.path.getmtime)
    if limit:
        files = files[-int(limit):]
    prof = calibrate(files, progress=progress)
    with open(out_path(), "w", encoding="utf-8") as f:
        json.dump(prof, f, ensure_ascii=False, indent=1)
    return prof


if __name__ == "__main__":
    import sys
    lim = None
    if "--limit" in sys.argv:
        lim = int(sys.argv[sys.argv.index("--limit") + 1])
    t0 = time.time()
    prof = run(limit=lim, progress=lambda i, n: print(f"  {i}/{n}...", flush=True))
    if not prof:
        print("cartella Results non trovata")
        sys.exit(1)
    print(f"\nfile letti: {prof['files_read']}  giri usati: {prof['laps_used']}"
          f"  ({time.time()-t0:.0f}s)")
    for track, clss in sorted(prof["tracks"].items()):
        for cls, comps in sorted(clss.items()):
            for comp, p in sorted(comps.items()):
                print(f"{track[:28]:28} {cls:6} {comp:12} "
                      f"usura {p['wear_pct_lap']}%/giro  "
                      f"deriva {p['pace_drift_s_lap']}s/giro  "
                      f"stint ~{p['stint_laps_med']} giri  "
                      f"(n={p['n_laps']})")
