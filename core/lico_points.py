"""
core/lico_points.py — PUNTI DI FRENATA VERI dai log del recorder (23/07).

Il LICO ha bisogno di sapere DOVE si frena per chiamare il rilascio
150-350m prima (come fa LMU). Le curve "apprese" erano sporche
(veleggiate nel traffico lette come frenate); la calibrazione manuale
dall'eco nativo funziona ma va fatta pista per pista. QUESTA e' la via
automatica: il recorder campiona il pedale freno a 100Hz su ogni giro
— la MEDIANA dei punti di frenata sui giri PULITI e' il dato piu'
affidabile che esista, per ogni pista gia' guidata, senza calibrare.

Uso: compute(track, cls_tag) -> lista lapdist ordinata (metri) dei
punti di frenata; compute_and_save scrive la cache che legge il dash.
Sola lettura sui .lmtel (mode=ro), nessun I/O sul collaudato.
"""
import glob
import json
import os
import re
import sqlite3
import statistics
from pathlib import Path

_LOGS = Path(os.environ.get("APPDATA", ".")) / "LMU_TelemetryPro" / "logs"
_OUT = Path(os.environ.get("APPDATA", ".")) / "LMU_TelemetryPro" / "lico_zones"


def _auto_file(track, cls_tag):
    _OUT.mkdir(parents=True, exist_ok=True)
    tr = re.sub(r"[^A-Za-z0-9]+", "_", track or "track")[:40]
    return _OUT / ("%s_%s_auto.json" % (tr, cls_tag or "X"))


def compute(track, cls_tag, max_files=6):
    """Punti di frenata (lapdist, metri) per pista+classe dai log
    recenti: fronti di salita del freno (>=0.35, sostenuto 0.5s,
    oltre 100 km/h) sui giri entro il 6%% dal best, raggruppati a 70m,
    tenuti se visti in almeno 1/3 dei giri. Ritorna lista ordinata."""
    edges = []          # lapdist di ogni inizio frenata
    n_laps = 0
    files = sorted(glob.glob(str(_LOGS / "*.lmtel")),
                   key=os.path.getmtime, reverse=True)
    used = 0
    for f in files:
        if used >= max_files:
            break
        try:
            con = sqlite3.connect(
                "file:%s?mode=ro" % Path(f).as_posix(), uri=True)
        except Exception:
            continue
        try:
            meta = con.execute("SELECT track, car_class FROM session_meta"
                               " LIMIT 1").fetchone()
            if not meta or meta[0] != track:
                continue
            from core.classes import class_tag as _ct
            if (_ct(meta[1] or "") or meta[1]) != cls_tag:
                continue
            laps = con.execute("SELECT lap, lap_time FROM laps WHERE"
                               " lap_time > 30").fetchall()
            if not laps:
                continue
            best = min(t for _l, t in laps)
            clean = [l for l, t in laps if t <= best * 1.06]
            if not clean:
                continue
            used += 1
            for lap in clean:
                rows = con.execute(
                    "SELECT t, lapdist, brake, speed FROM samples"
                    " WHERE lap=? ORDER BY t", (lap,)).fetchall()
                if len(rows) < 50:
                    continue
                n_laps += 1
                prev_b = 0.0
                i = 0
                while i < len(rows):
                    t0, ld, b, spd = rows[i]
                    b = b or 0.0
                    if b >= 0.35 and prev_b < 0.35 \
                            and (spd or 0.0) > 100.0 and (ld or 0) > 0:
                        # sostenuto: media freno nei 0.5s successivi
                        j = i + 1
                        acc, n = 0.0, 0
                        while j < len(rows) and rows[j][0] - t0 <= 0.5:
                            acc += rows[j][2] or 0.0
                            n += 1
                            j += 1
                        if n >= 3 and acc / n >= 0.30:
                            edges.append(float(ld))
                            # salta la frenata: prossimo fronte a freno
                            # mollato da almeno 1s
                            rel = None
                            while j < len(rows):
                                if (rows[j][2] or 0.0) < 0.10:
                                    if rel is None:
                                        rel = rows[j][0]
                                    elif rows[j][0] - rel > 1.0:
                                        break
                                else:
                                    rel = None
                                j += 1
                            i = j
                            prev_b = 0.0
                            continue
                    prev_b = b
                    i += 1
        except Exception:
            pass
        finally:
            con.close()
    if not edges or n_laps == 0:
        return []
    # cluster a 70m
    edges.sort()
    clusters = []          # [ [punti...], ... ]
    for d in edges:
        if clusters and d - clusters[-1][-1] < 70.0:
            clusters[-1].append(d)
        else:
            clusters.append([d])
    keep = max(3, int(round(n_laps / 3.0)))
    return sorted(round(statistics.median(c), 1)
                  for c in clusters if len(c) >= keep)


def compute_and_save(track, cls_tag):
    """Calcola e scrive la cache auto per il dash. Ritorna i punti."""
    pts = compute(track, cls_tag)
    try:
        _auto_file(track, cls_tag).write_text(
            json.dumps({"kind": "brake", "points": pts,
                        "laps_hint": len(pts)}), encoding="utf-8")
    except Exception:
        pass
    return pts


def load_auto(track, cls_tag):
    """Punti di frenata dalla cache auto (o [])."""
    try:
        d = json.loads(_auto_file(track, cls_tag)
                       .read_text(encoding="utf-8"))
        return [float(p) for p in (d.get("points") or [])]
    except Exception:
        return []
