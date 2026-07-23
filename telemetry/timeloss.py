"""
telemetry/timeloss.py — TIME-LOSS MATRIX per curva e fase.

Confronta due giri della stessa sessione sui samples (lapdist -> tempo):
il gap cumulato viene ripartito sulle curve APPRESE (engineer_learn) e
sulle fasi — INGRESSO (inizio frenata -> apice) e USCITA (apice ->
trazione) — piu' i rettilinei. E' il "dove perdo e in quale fase" chiesto
dal capo: "in curva 2 lasci 3 decimi, tutti in ingresso".

Puro Python (1 punto al metro, ~6000 punti = millisecondi di calcolo).
Convenzione segni: positivo = il giro A PERDE tempo li' rispetto al B.
"""
import bisect

from core import engineer_learn as _learn


def lap_series(con, lap):
    """[(lapdist, t, speed)] MONOTONO in lapdist per il giro richiesto."""
    rows = con.execute(
        "SELECT lapdist, t, speed FROM samples"
        " WHERE lap=? AND lapdist IS NOT NULL AND t IS NOT NULL ORDER BY t",
        (lap,)).fetchall()
    # i primi campioni del giro portano ancora la lapdist di FINE giro
    # precedente (il traguardo arriva dopo qualche tick): si parte dal
    # RESET (caduta > 1000 m), se c'e'
    start = 0
    for i in range(1, len(rows)):
        if float(rows[i][0]) < float(rows[i - 1][0]) - 1000.0:
            start = i
            break
    out = []
    last = -1.0
    for ld, t, sp in rows[start:]:
        ld = float(ld)
        if ld > last + 1e-6:
            out.append((ld, float(t), float(sp or 0.0)))
            last = ld
    return out


def _t_at(series, lds, d):
    """Tempo interpolato alla lapdist d (lds = lista lapdist della serie)."""
    i = bisect.bisect_left(lds, d)
    if i <= 0:
        return series[0][1]
    if i >= len(series):
        return series[-1][1]
    d0, t0, _ = series[i - 1]
    d1, t1, _ = series[i]
    f = (d - d0) / (d1 - d0) if d1 > d0 else 0.0
    return t0 + (t1 - t0) * f


def _vmin_in(series, lds, d0, d1):
    """Velocita' minima (km/h) nella finestra [d0, d1]."""
    i = bisect.bisect_left(lds, d0)
    j = bisect.bisect_right(lds, d1)
    seg = [series[k][2] for k in range(i, min(j, len(series)))
           if series[k][2] > 0]
    return min(seg) if seg else None


def corners_for(track, car_class, wet=False, track_len=None):
    """Curve per la matrice: PRIMA la GEOMETRIA della mappa SVG
    (numerazione VERA da cartello: 6 curve al National = T1..T6);
    le curve APPRESE solo come fallback (23/07 notte: al National
    'curva 7/9/10' — erano segmenti appresi sporchi)."""
    if track and track_len:
        try:
            from core.lico_points import map_turns
            mt = map_turns(track, float(track_len))
            if len(mt) >= 3:
                return [{"d": float(e), "end": float(x),
                         "brake_d": 60.0} for e, _lab, x in mt]
        except Exception:
            pass
    prof = _learn.load(track, car_class)
    cond = (prof.get("cond") or {}).get("wet" if wet else "dry") or {}
    cs = [c for c in (cond.get("corners") or []) if c.get("d") is not None]
    return sorted(cs, key=lambda c: c["d"])


def compute(con, lap, ref, track=None, car_class=None, corners=None,
            wet=False):
    """Matrice time-loss del giro `lap` contro il giro `ref`.

    -> {lap, ref, total_s, straights_s, corners: [{corner, d, entry_s,
        exit_s, total_s, vmin, vmin_ref}]}  oppure None se dati scarsi."""
    A = lap_series(con, lap)
    B = lap_series(con, ref)
    if len(A) < 100 or len(B) < 100:
        return None
    ldsA = [q[0] for q in A]
    ldsB = [q[0] for q in B]
    if corners is None:
        # la lunghezza pista serve alla geometria mappa: la lapdist
        # massima del giro E' la lunghezza (a un metro)
        corners = corners_for(track, car_class, wet,
                              track_len=max(ldsA[-1], ldsB[-1]))
    if not corners:
        return None
    lo = max(ldsA[0], ldsB[0])
    hi = min(ldsA[-1], ldsB[-1])
    if hi - lo < 500.0:
        return None

    def gap(d):
        return _t_at(A, ldsA, d) - _t_at(B, ldsB, d)

    total = gap(hi) - gap(lo)
    rows = []
    prev_end = lo
    straights = 0.0
    for i, c in enumerate(corners):
        d = c["d"]
        if d < lo + 30.0 or d > hi - 30.0:
            continue
        # ingresso: dall'inizio frenata (appresa) con margine, all'apice
        bd = min(max(float(c.get("brake_d") or 60.0), 30.0), 300.0)
        e0 = max(prev_end, d - bd - 30.0)
        # uscita: dall'apice alla trazione (capata a meta' strada dalla
        # curva successiva)
        x1 = d + 150.0
        if i + 1 < len(corners):
            x1 = min(x1, (d + corners[i + 1]["d"]) / 2.0)
        x1 = min(x1, hi)
        if x1 <= e0:
            continue
        entry = gap(d) - gap(e0)
        exit_ = gap(x1) - gap(d)
        va = _vmin_in(A, ldsA, d - 60.0, d + 60.0)
        vb = _vmin_in(B, ldsB, d - 60.0, d + 60.0)
        rows.append({
            "corner": "T%d" % (i + 1),
            "d": round(d, 1),
            "entry_s": round(entry, 3),
            "exit_s": round(exit_, 3),
            "total_s": round(entry + exit_, 3),
            "vmin": round(va, 1) if va is not None else None,
            "vmin_ref": round(vb, 1) if vb is not None else None,
        })
        straights += gap(e0) - gap(prev_end)
        prev_end = x1
    straights += gap(hi) - gap(prev_end)
    if not rows:
        return None
    return {"lap": int(lap), "ref": int(ref),
            "total_s": round(total, 3),
            "straights_s": round(straights, 3),
            "corners": rows}


def worst(res, k=3):
    """Le k curve dove si perde di piu' (per il debrief del muretto)."""
    if not res:
        return []
    return sorted(res["corners"], key=lambda r: -r["total_s"])[:k]
