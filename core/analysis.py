"""core/analysis.py — Analisi deterministica di uno stint vs un giro di riferimento.

Niente AI: regole esplicite sui canali telemetria. Confronta il giro di
riferimento (REF, di solito il proprio best) col giro rappresentativo dello
stint, campionati sulla distanza, e produce:
  - le ZONE dove si perde tempo, con fase (Frenata/Percorrenza/Trazione),
    causa e consiglio di guida;
  - i CONSIGLI ASSETTO dedotti dai pattern aggregati (sottosterzo, sovrasterzo
    in trazione, bloccaggi, squilibri temperatura gomme).

Tutto in stdlib; riceve connessioni sqlite già aperte.
"""

CHANNELS = ["t", "speed", "throttle", "brake", "steer", "g_lat", "g_long",
            "tc_active", "abs_active",
            "tyre_t_fl", "tyre_t_fr", "tyre_t_rl", "tyre_t_rr"]

# soglie
_BRAKE_ON = 0.18        # freno "premuto"
_THR_ON = 0.45          # gas "aperto"
_STEER_ON = 0.12        # sterzo significativo (|steer| 0..1)
_LOCK = 0.25            # ABS attivo medio -> bloccaggi
_SPIN = 0.20            # TC attiva media -> pattinamento
_SEG_THR = 0.0008       # perdita per-segmento per essere "in zona" (s)
_MIN_ZONE = 0.04        # perdita minima di una zona per contare (s)


def _load(con, lap):
    sql = "SELECT lapdist," + ",".join(CHANNELS) + \
          " FROM samples WHERE lap=? ORDER BY t"
    try:
        rows = con.execute(sql, (lap,)).fetchall()
    except Exception:
        return None
    series = {}
    for ci, ch in enumerate(CHANNELS):
        s = []; last = None
        for r in rows:
            d = r[0]; v = r[ci + 1]
            if d is None or v is None:
                continue
            d = float(d)
            if last is not None and d <= last + 1e-6:
                continue
            s.append((d, float(v))); last = d
        series[ch] = s
    return series


def _resample(series, grid):
    out = []; j = 0; n = len(series)
    if n == 0:
        return [0.0] * len(grid)
    for x in grid:
        if x <= series[0][0]:
            out.append(series[0][1]); continue
        while j < n - 1 and series[j + 1][0] < x:
            j += 1
        if j >= n - 1:
            out.append(series[-1][1]); continue
        x0, v0 = series[j]; x1, v1 = series[j + 1]
        out.append(v0 if x1 <= x0 else v0 + (v1 - v0) * (x - x0) / (x1 - x0))
    return out


def _smooth(a, w=3):
    n = len(a)
    if n == 0 or w <= 1:
        return list(a)
    h = w // 2
    out = []
    for i in range(n):
        lo = max(0, i - h); hi = min(n, i + h + 1)
        out.append(sum(a[lo:hi]) / (hi - lo))
    return out


def _avg(arr, a, b):
    seg = arr[a:b + 1]
    return sum(seg) / len(seg) if seg else 0.0


def _find_zones(sm):
    n = len(sm)
    raw_zones = []; i = 0
    while i < n:
        if sm[i] > _SEG_THR:
            j = i
            while j < n and sm[j] > _SEG_THR * 0.3:
                j += 1
            raw_zones.append((i, min(j, n - 1)))
            i = j + 1
        else:
            i += 1
    out = []
    for (a, b) in raw_zones:
        lost = sum(max(sm[k], 0.0) for k in range(a, b + 1))
        if lost >= _MIN_ZONE:
            out.append((a, b, lost))
    return out


def _classify(grid, i0, i1, lost, R, Rr):
    steer_abs = [abs(x) for x in R["steer"]]
    brake = _avg(R["brake"], i0, i1)
    thr = _avg(R["throttle"], i0, i1)
    thr_ref = _avg(Rr["throttle"], i0, i1)
    steer = _avg(steer_abs, i0, i1)
    abs_a = _avg(R["abs_active"], i0, i1)
    tc = _avg(R["tc_active"], i0, i1)
    sp = R["speed"]; spr = Rr["speed"]
    sel_min = min(sp[i0:i1 + 1]) if sp[i0:i1 + 1] else 0.0
    ref_min = min(spr[i0:i1 + 1]) if spr[i0:i1 + 1] else 0.0
    entry_sel = sp[i0]; entry_ref = spr[i0]

    if brake > _BRAKE_ON:
        phase = "Braking"
        if abs_a > _LOCK:
            cause = "Locking up under braking (ABS engaging)"
            tip = "Brake a touch lighter, or shift brake bias to cut lockups."
        elif sel_min < ref_min - 2:
            cause = "Over-slowing into the corner"
            tip = "Carry more speed: brake a little less hard / later."
        elif entry_sel < entry_ref - 3:
            cause = "Arriving slower than the reference"
            tip = "Release the brake earlier and trail off smoothly."
        else:
            cause = "Small loss on the brakes"
            tip = "Smooth the brake release toward the apex."
    elif thr > _THR_ON and brake < 0.08:
        phase = "Traction"
        if tc > _SPIN:
            cause = "Wheelspin on exit (TC cutting in)"
            tip = "Feed the throttle in more progressively."
        elif thr < thr_ref - 0.08:
            cause = "Throttle applied late on exit"
            tip = "Get to power earlier where there is grip."
        else:
            cause = "Traction phase can be improved"
            tip = "Be more committed to throttle once the car is straight."
    else:
        phase = "Mid-corner"
        if sel_min < ref_min - 1.5:
            cause = "Low mid-corner speed"
            tip = "Smoother entry, less brake, open the throttle earlier."
        elif steer > _STEER_ON and entry_sel < entry_ref - 1.5:
            cause = "Losing minimum speed through the corner"
            tip = "Keep the car loaded, avoid scrubbing speed."
        else:
            cause = "Line / cornering"
            tip = "Try a more open line to keep momentum."

    return {
        "d0": grid[i0], "d1": grid[min(i1, len(grid) - 1)],
        "lost": lost, "phase": phase, "cause": cause, "tip": tip,
        "sel_min": sel_min, "ref_min": ref_min,
        "brake": brake, "thr": thr, "steer": steer, "tc": tc, "abs": abs_a,
        "brk_m": _brake_onset_delta(grid, i0, i1, R["brake"], Rr["brake"]),
    }


def _brake_onset_delta(grid, i0, i1, b_sel, b_ref):
    """Differenza (m) del punto di frenata: + = sel frena DOPO (piu' avanti),
    - = sel frena PRIMA. None se non si trova un punto di frenata netto."""
    lo = max(0, i0 - 30)                 # cerca fino a ~120 m prima della zona
    hi = min(i1, len(grid) - 1)

    def onset(arr):
        for k in range(lo, hi + 1):
            if k < len(arr) and arr[k] >= _BRAKE_ON:
                return grid[k]
        return None
    os, orf = onset(b_sel), onset(b_ref)
    if os is None or orf is None:
        return None
    return os - orf


def _setup_advice(grid, R, Rr, findings):
    n = len(grid)
    steer_abs = [abs(x) for x in R["steer"]]
    steer_ref = [abs(x) for x in Rr["steer"]]
    # statistiche per fase su tutto il giro
    us_pts = us_hit = 0          # sottosterzo in percorrenza
    spin = spin_pts = 0.0        # pattinamento in trazione
    lock = lock_pts = 0.0        # bloccaggi in frenata
    for i in range(n):
        b = R["brake"][i]; th = R["throttle"][i]; stp = steer_abs[i]
        if b < 0.1 and th < 0.5 and stp > _STEER_ON:      # percorrenza
            us_pts += 1
            if R["speed"][i] < Rr["speed"][i] - 1.5 and stp >= steer_ref[i] - 0.02:
                us_hit += 1
        if th > 0.4 and stp > 0.05:                        # trazione in curva
            spin_pts += 1; spin += R["tc_active"][i]
        if b > 0.3:                                        # frenata
            lock_pts += 1; lock += R["abs_active"][i]
    us_ratio = (us_hit / us_pts) if us_pts else 0.0
    spin_ratio = (spin / spin_pts) if spin_pts else 0.0
    lock_ratio = (lock / lock_pts) if lock_pts else 0.0

    # temperature gomme medie
    def mean(ch):
        a = R[ch]
        return sum(a) / len(a) if a else 0.0
    front_t = (mean("tyre_t_fl") + mean("tyre_t_fr")) / 2.0
    rear_t = (mean("tyre_t_rl") + mean("tyre_t_rr")) / 2.0

    out = []
    if us_ratio > 0.25:
        out.append({
            "area": "Understeer (mid-corner)",
            "obs": "The car carries less mid-corner speed than the reference "
                   "while you hold more steering — front grip is the limit.",
            "change": "Soften Front Anti-Roll Bar (lower number) and/or stiffen "
                      "Rear Anti-Roll Bar. If adjustable, add Front Wing. "
                      "Try lowering front tyre pressures slightly."})
    if spin_ratio > _SPIN:
        out.append({
            "area": "Power oversteer / traction",
            "obs": "TC is cutting in often on corner exit — the rear is "
                   "stepping out under power.",
            "change": "Soften Rear Anti-Roll Bar, raise Diff Coast/Preload for "
                      "stability, and add Rear Wing if available."})
    if lock_ratio > _LOCK:
        out.append({
            "area": "Braking stability",
            "obs": "ABS is working hard under braking — wheels are close to "
                   "locking.",
            "change": "Reduce Brake Pressure a little, or move Brake Bias "
                      "rearward if the fronts lock first."})
    if front_t - rear_t > 12:
        out.append({
            "area": "Tyre balance (front hot)",
            "obs": "Front tyres run notably hotter than rears — consistent with "
                   "front overload / understeer.",
            "change": "Lower front tyre pressures and/or add front camber to "
                      "spread the load."})
    elif rear_t - front_t > 12:
        out.append({
            "area": "Tyre balance (rear hot)",
            "obs": "Rear tyres run notably hotter than fronts — rear is working "
                   "too hard.",
            "change": "Lower rear pressures, ease diff settings, or soften the "
                      "rear to reduce rear load."})
    return out, {"understeer": us_ratio, "spin": spin_ratio,
                 "lock": lock_ratio, "front_t": front_t, "rear_t": rear_t}


def analyze(con, sel_lap, ref_con, ref_lap, step=4.0):
    """Analizza sel_lap vs ref_lap. Ritorna dict o None se dati insufficienti."""
    sel = _load(con, sel_lap)
    ref = _load(ref_con, ref_lap)
    if not sel or not ref or len(sel["t"]) < 5 or len(ref["t"]) < 5:
        return None
    d0 = max(sel["t"][0][0], ref["t"][0][0], 0.0)
    d1 = min(sel["t"][-1][0], ref["t"][-1][0])
    if d1 - d0 < 50:
        return None
    grid = []; x = d0
    while x <= d1:
        grid.append(x); x += step
    if len(grid) < 5:
        return None
    R = {ch: _resample(sel[ch], grid) for ch in CHANNELS}
    Rr = {ch: _resample(ref[ch], grid) for ch in CHANNELS}
    st = R["t"]; rt = Rr["t"]
    seg = [(st[i + 1] - st[i]) - (rt[i + 1] - rt[i]) for i in range(len(grid) - 1)]
    sm = _smooth(seg, 3)
    zones = _find_zones(sm)
    findings = [_classify(grid, a, b, lost, R, Rr) for (a, b, lost) in zones]
    findings.sort(key=lambda z: -z["lost"])
    setup, stats = _setup_advice(grid, R, Rr, findings)
    sel_time = st[-1] - st[0]
    ref_time = rt[-1] - rt[0]
    return {
        "sel_lap": sel_lap, "ref_lap": ref_lap,
        "sel_time": sel_time, "ref_time": ref_time,
        "gap": sel_time - ref_time,
        "lost_total": sum(z["lost"] for z in findings),
        "zones": findings[:8],
        "setup": setup, "stats": stats,
        "dist": d1 - d0,
    }
