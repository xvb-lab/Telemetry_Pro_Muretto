"""
core/corner_learn.py — INTELLIGENZA PER CURVA dalle telemetrie registrate.

Dai giri migliori della sessione (samples a 64Hz: lapdist, speed, brake,
temp superficie gomma e temp freno PER RUOTA) estrae le curve del tracciato:

- APEX: minimi locali di velocita' (curva N in ordine di percorrenza);
- FRENATA: dove inizia (brake > soglia risalendo dall'apex), distanza e
  velocita' d'ingresso -> quanto e' "dura" (drop di velocita', picco freni);
- STRESS GOMMA: quale ruota scalda di piu' in quella curva (picco superficie
  vs mediana del giro).

Il risultato viene fuso su piu' giri (mediane) e salvato nel profilo appreso
per pista+classe. Nessuna dipendenza esterna.
"""

BRAKE_ON = 0.15          # soglia pedale per "sta frenando"
MIN_DROP = 8.0           # m/s di calo minimo per considerare una curva
APEX_MERGE_M = 100.0     # apex piu' vicini di cosi' = stessa curva
SEARCH_BACK_M = 650.0    # quanto indietro cercare l'inizio frenata
MAX_CORNERS = 40


def _smooth(v, k=7):
    if len(v) < k * 2:
        return v[:]
    out = []
    half = k // 2
    for i in range(len(v)):
        a = max(0, i - half); b = min(len(v), i + half + 1)
        out.append(sum(v[a:b]) / (b - a))
    return out


def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    return xs[len(xs) // 2] if xs else None


def corners_from_lap(rows):
    """rows: iterabile di dict con lapdist, speed, brake, tyre_ts_*, brake_t_*.
    Ritorna [{d, vmin, ventry, drop, brake_d, brake_peak, hot_wheel, spike}]."""
    pts = [r for r in rows
           if r["lapdist"] is not None and r["speed"] is not None]
    if len(pts) < 200:
        return []
    pts.sort(key=lambda r: r["lapdist"])
    d = [float(r["lapdist"]) for r in pts]
    v = _smooth([float(r["speed"]) for r in pts])
    br = [float(r["brake"] or 0.0) for r in pts]
    vmax = max(v)
    n = len(pts)
    # mediane del giro per lo spike gomma
    wheels = ("fl", "fr", "rl", "rr")
    ts_med = [_median([r.get("tyre_ts_" + w) for r in pts]) for w in wheels]

    # minimi locali di velocita'
    win = max(10, n // 300)                 # ~mezzo secondo a 64Hz
    apexes = []
    i = win
    while i < n - win:
        seg = v[i - win:i + win + 1]
        if v[i] <= min(seg) + 1e-9 and v[i] < 0.85 * vmax:
            apexes.append(i)
            i += win
        else:
            i += 1
    # fondi apex vicini (tieni il piu' lento)
    merged = []
    for i in apexes:
        if merged and d[i] - d[merged[-1]] < APEX_MERGE_M:
            if v[i] < v[merged[-1]]:
                merged[-1] = i
        else:
            merged.append(i)

    out = []
    for i in merged:
        # inizio frenata: risali fino a SEARCH_BACK_M cercando il primo brake>soglia
        # della staccata che porta a questo apex
        j = i
        brake_start = None
        while j > 0 and d[i] - d[j] < SEARCH_BACK_M:
            if br[j] > BRAKE_ON:
                brake_start = j
            elif brake_start is not None and br[j] <= 0.05:
                break                        # pedale rilasciato prima: fine ricerca
            j -= 1
        ventry = v[brake_start] if brake_start is not None else max(
            v[max(0, i - win * 4):i + 1])
        drop = ventry - v[i]
        if drop < MIN_DROP and brake_start is None:
            continue                          # curvone pieno: non e' una staccata
        k0 = brake_start if brake_start is not None else max(0, i - win * 4)
        k1 = min(n - 1, i + win * 2)
        seg = pts[k0:k1 + 1]
        brake_peak = max((max(r.get("brake_t_" + w) or 0 for w in wheels)
                          for r in seg), default=0)
        # spike gomma per ruota nella curva
        spikes = []
        for wi, w in enumerate(wheels):
            mx = max((r.get("tyre_ts_" + w) or 0) for r in seg)
            spikes.append(mx - ts_med[wi] if ts_med[wi] else 0.0)
        hot = max(range(4), key=lambda x: spikes[x])
        out.append({"d": round(d[i], 1), "vmin": round(v[i], 1),
                    "ventry": round(ventry, 1), "drop": round(drop, 1),
                    "brake_d": round(d[i] - d[brake_start], 1) if brake_start else None,
                    "brake_peak": round(brake_peak, 1),
                    "hot_wheel": hot if spikes[hot] >= 3.0 else None,
                    "spike": round(spikes[hot], 1)})
        if len(out) >= MAX_CORNERS:
            break
    return out


def merge_laps(per_lap):
    """Fonde le curve di piu' giri (match per distanza, mediane dei valori)."""
    per_lap = [c for c in per_lap if c]
    if not per_lap:
        return []
    base = per_lap[0]
    merged = []
    for c in base:
        group = [c]
        for other in per_lap[1:]:
            near = [o for o in other if abs(o["d"] - c["d"]) < 80.0]
            if near:
                group.append(min(near, key=lambda o: abs(o["d"] - c["d"])))
        m = {"d": _median([g["d"] for g in group]),
             "vmin": _median([g["vmin"] for g in group]),
             "ventry": _median([g["ventry"] for g in group]),
             "drop": _median([g["drop"] for g in group]),
             "brake_d": _median([g["brake_d"] for g in group if g["brake_d"]]),
             "brake_peak": _median([g["brake_peak"] for g in group]),
             "spike": _median([g["spike"] for g in group])}
        hw = [g["hot_wheel"] for g in group if g["hot_wheel"] is not None]
        m["hot_wheel"] = max(set(hw), key=hw.count) if hw else None
        merged.append(m)
    for idx, m in enumerate(merged, 1):     # curva N in ordine di percorrenza
        m["n"] = idx
    return merged


def analyze(con, best_laps=3):
    """Estrae le curve dai `best_laps` giri validi piu' veloci della sessione."""
    rows = con.execute(
        "SELECT lap, lap_time FROM laps WHERE lap_time>0 AND invalid=0 "
        "ORDER BY lap_time LIMIT ?", (best_laps,)).fetchall()
    per_lap = []
    for r in rows:
        samp = con.execute(
            "SELECT lapdist, speed, brake, "
            "tyre_ts_fl, tyre_ts_fr, tyre_ts_rl, tyre_ts_rr, "
            "brake_t_fl, brake_t_fr, brake_t_rl, brake_t_rr "
            "FROM samples WHERE lap=? AND lapdist IS NOT NULL "
            "ORDER BY lapdist", (r["lap"],)).fetchall()
        per_lap.append(corners_from_lap([dict(x) for x in samp]))
    return merge_laps(per_lap)


# ── self-test con un giro sintetico (3 curve) ──
if __name__ == "__main__":
    import math
    rows = []
    for i in range(6400):                    # ~100s a 64Hz, giro 5000m
        dd = i / 6400.0 * 5000.0
        v = 80.0
        for (cd, vmin) in ((900, 30.0), (2500, 45.0), (4100, 22.0)):
            if abs(dd - cd) < 260:
                v = min(v, vmin + (abs(dd - cd) / 260.0) ** 2 * (80 - vmin))
        braking = v < 79 and dd < 5000 and any(
            0 < (cd - dd) < 220 for cd, _ in ((900, 0), (2500, 0), (4100, 0)))
        hot = 95 + (12 if abs(dd - 4100) < 200 else 0)
        rows.append({"lapdist": dd, "speed": v, "brake": 0.8 if braking else 0.0,
                     "tyre_ts_fl": hot, "tyre_ts_fr": 95, "tyre_ts_rl": 95,
                     "tyre_ts_rr": 95, "brake_t_fl": 300 + (400 if braking else 0),
                     "brake_t_fr": 300, "brake_t_rl": 250, "brake_t_rr": 250})
    cs = merge_laps([corners_from_lap(rows)])
    for c in cs:
        print(c)
