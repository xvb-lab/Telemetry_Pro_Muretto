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


def _spy9(track, fonte, ts):
    """SPIA curve ingegnere (rich. 24/07: "devo sapere COSA legge"):
    ogni lettura finisce in engineer_curve_debug.txt con fonte e
    posizioni — mai piu' dubbi su un "curva 13"."""
    try:
        import time as _t
        from core.paths import USER_DIR
        with open(USER_DIR / "engineer_curve_debug.txt", "a",
                  encoding="utf-8") as fh:
            fh.write("[%s] %s: fonte=%s curve=%d  %s\n" % (
                _t.strftime("%H:%M:%S"), track, fonte, len(ts),
                " ".join("%s@%dm" % (q[1], q[0]) for q in ts[:14])))
    except Exception:
        pass


def map_turns(track, track_len):
    """[(lapdist, 'Tn')] — CURVE dal CENSIMENTO condiviso e basta.

    DOTTRINA (utente, 24/07 sera): LMU le curve non le ha, la
    numerazione "ufficiale" e' soggettiva (FIA/F1/SBK contano
    diverso) — il riferimento lo creiamo NOI e l'unica cosa sacra
    e' la COERENZA: stesso numero sulla mappa, in telemetria e
    nella bocca dell'ingegnere. Quindi UN SOLO cervello numera
    (il rilevatore calibrato del widget mappa, che scrive il
    censimento al primo caricamento) e qui si LEGGE soltanto:
    niente rilevatore privato (era la fonte del "curva 17" mai
    vista sulla mappa). Censimento assente = si aspetta in
    silenzio il primo giro."""
    try:
        from data.track_corners import corners_for_track as _cf9
        _db9 = _cf9(track, track_len)
    except Exception:
        _db9 = None
    if _db9:
        out = [(max(0.0, round(p - 40.0, 1)), "T%d" % (i + 1),
                round(p + 40.0, 1)) for i, p in enumerate(_db9)]
        _spy9(track, "CENSIMENTO", out)
        return out
    _spy9(track, "IN ATTESA DEL CENSIMENTO", [])
    return []


def map_corner_lifts(track, track_len):
    """IDEA UTENTE (23/07, la definitiva): l'INIZIO di ogni curva dalla
    mappa, deduplicato — il lico chiama a (inizio - 200/250/300m per
    livello) SU OGNI CIRCUITO, senza tarare niente. Come i 500m della
    bandiera gialla: la distanza in pista e' geometria, non taratura."""
    ts = map_turns(track, track_len)
    if not ts:
        return []
    ts = sorted(ts, key=lambda q: q[0])
    ded = [ts[0]]
    for q in ts[1:]:
        if q[0] - ded[-1][0] >= 250.0:  # chicane/complessi = UNA chiamata
            ded.append(q)
        else:                            # assorbi: la FINE si estende
            ded[-1] = (ded[-1][0], ded[-1][1], max(ded[-1][2], q[2]))
    # (entry, floor): il rilascio non puo' cadere DENTRO o subito dopo
    # la curva PRIMA (collaudo 23/07: Lesmo2 suonava sull'uscita di
    # Lesmo1) -> pavimento = fine curva precedente + 60m
    out = []
    for ix, (entry, _lab, end) in enumerate(ded):
        prev_end = ded[ix - 1][2] if ix > 0 else ded[-1][2] - track_len
        out.append((entry, round(prev_end + 60.0, 1)))
    return out


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
    # lunghezza pista (dal max lapdist visto) per la mappa
    tlen = max(edges) if edges else 0.0
    try:
        f0 = files[0]
        con = sqlite3.connect("file:%s?mode=ro" % Path(f0).as_posix(),
                              uri=True)
        r = con.execute("SELECT MAX(lapdist) FROM samples").fetchone()
        con.close()
        if r and r[0]:
            tlen = float(r[0])
    except Exception:
        pass
    # cluster a 70m
    edges.sort()
    clusters = []          # [ [punti...], ... ]
    for d in edges:
        if clusters and d - clusters[-1][-1] < 70.0:
            clusters[-1].append(d)
        else:
            clusters.append([d])
    keep = max(3, int(round(n_laps / 3.0)))
    pts = sorted(round(statistics.median(c), 1)
                 for c in clusters if len(c) >= keep)
    # FUSIONE CON LA MAPPA (idea utente 23/07): un punto-freno vero ha
    # una CURVA della mappa SVG davanti entro ~320m; senza, e' una
    # frenata da traffico e si butta. Se lo SVG manca, si tiene tutto.
    turns = map_turns(track, tlen)
    if turns and tlen > 500.0:
        good = []
        for p in pts:
            for td, _lab in turns:
                ahead = (td - p) % tlen
                if ahead <= 320.0:
                    good.append(p)
                    break
        if len(good) >= 3:            # mappa affidabile: filtra
            pts = good
    return pts


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
