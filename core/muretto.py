"""MURETTO v3 — stratega puro, riscritto da zero (2026-07-19). UNICA fonte
di verita' per il piano gara.

    plan = muretto.plan(snap)

`snap` e' UNA fotografia della gara ADESSO. `plan` e' il piano COMPLETO dei
giri rimanenti:
    - stops:   soste ordinate {lap assoluto, reason, tyre, refuel_pct,
               arrive_pct, target_pct}
    - stints:  {da, a, tyre, drive}
    - verdict: {stops (numero), mode, save_pct}
    - strip_stops: identico a stops (la strip NON calcola)
    - segments: [(da, a, 'dry'|'wet')] in giri ASSOLUTI
    - feasible, why (log leggibile del ragionamento)

Regole ferree:
  1. Serbatoio SEQUENZIALE: refuel = min(necessario, spazio);
     refuel_pct + arrive_pct <= 100 SEMPRE.
  2. Gara a tempo: giri = tempo / passo, MENO il tempo delle soste
     (conto iterativo). mMaxLaps nelle gare a tempo NON e' la durata.
  3. Il piano e' VOLATILE: si ricalcola tutto a ogni chiamata dai dati
     di ADESSO, zero stato nascosto, zero Qt.
  4. Le soste meteo sono MURI (dry->wet): la sosta energia vicina
     (<= MERGE_W giri) ci si fonde sopra. wet->dry NON e' mai un muro.
  5. Dato chiave assente/assurdo -> ok=False con il motivo in why.
  6. Il forecast e' ancorato all'INIZIO GARA (nodi a 0/25/50/75/100%
     della sessione), MAI ai giri rimanenti: il muro pioggia non scivola.
"""

WET_ON, DRY_ON = 50.0, 30.0    # isteresi forecast (probabilita' %)
MERGE_W = 3                    # fusione sosta energia <-> muro meteo (giri)
WEAR_DEAD = 70.0               # sotto: gomma finita (scala LMU, 100=nuova)
RESERVE = 1.02                 # riserva sul fabbisogno (2%)


def _f(v, lo=None, hi=None):
    """Float validato in [lo, hi]; None se assente o fuori scala."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if lo is not None and x < lo:
        return None
    if hi is not None and x > hi:
        return None
    return x


def wx_segments(forecast5, laps, wet_now=None, laps_done=0, rain_now=False):
    """Forecast 5 nodi -> [(da, a, 'dry'|'wet')] in giri RELATIVI 0..laps.

    I nodi LMU sono a 0/25/50/75/100% della DURATA SESSIONE: si ancorano
    all'inizio gara (laps_done + laps = totale). Il regime del PRIMO
    segmento viene dalla PISTA (wet_now), non dal forecast.
    Transizione dry->wet gia' SCADUTA: muro a start+1 se piove davvero,
    a start+2 (rivalutato ogni giro) se la pioggia e' in ritardo.
    """
    laps = int(laps or 0)
    if laps <= 0:
        return []
    laps_done = max(0, int(laps_done or 0))
    total = laps + laps_done
    try:
        vals = [float(v) for v in (forecast5 or [])[:5]]
    except (TypeError, ValueError):
        vals = []
    if len(vals) < 5:
        return [(0, laps, "wet" if wet_now else "dry")]
    fr = [0.0, 0.25, 0.50, 0.75, 1.0]
    wet = bool(wet_now) if wet_now is not None else (vals[0] >= 40.0)
    cur, start, segs = ("wet" if wet else "dry"), 0, []
    for i in range(1, 5):
        a, b = vals[i - 1], vals[i]
        hit = None
        if not wet and b >= WET_ON:
            t = (WET_ON - a) / (b - a) if b != a else 0.0
            hit = "wet"
        elif wet and b <= DRY_ON:
            t = (a - DRY_ON) / (a - b) if a != b else 0.0
            hit = "dry"
        if hit:
            f = fr[i - 1] + (fr[i] - fr[i - 1]) * max(0.0, min(1.0, t))
            lap = int(round(f * total)) - laps_done
            if lap <= start:
                lap = start + (2 if (hit == "wet" and not rain_now) else 1)
            if lap < laps:
                segs.append((start, lap, cur))
                start = lap
                cur, wet = hit, (hit == "wet")
    segs.append((start, laps, cur))
    return [s for s in segs if s[1] > s[0]]


def plan(snap):
    """Costruisce il piano. Campi di snap:

      constraint       "FUEL" | "ENERGY"
      tank             capacita' (litri; ENERGY: tank=100)
      load_now         carico ATTUALE (litri o VE%)
      per_lap          consumo/giro (litri o %/giro)
      base_lap         passo di riferimento (s)
      race_seconds_left  secondi rimanenti (gare a tempo; 0 se a giri)
      race_laps_left   giri rimanenti (gare a giri; 0 se a tempo)
      laps_done        giri completati (per uscire in giri ASSOLUTI)
      pit_loss         perdita sosta (s)
      forecast5        [5 x rain%] o None
      raining_now      pioggia in corso 0..1 (per il muro scaduto)
      wet_mounted      bool
      track_wet_now    bool|None (pista bagnata ADESSO, sulla MEDIA)
      wear_now         gomma peggiore % (None = ignora vincolo)
      deg_per_lap      usura %/giro (None/0 = ignora vincolo)
      wear_dead        soglia gomma morta (default WEAR_DEAD)
    """
    why = []
    out = {"ok": False, "why": why}

    constraint = "ENERGY" if str(snap.get("constraint")).upper() == "ENERGY" \
        else "FUEL"
    tank = 100.0 if constraint == "ENERGY" else (_f(snap.get("tank"), 1.0) or 0.0)
    pl_hi = 40.0 if constraint == "ENERGY" else 15.0
    per_lap = _f(snap.get("per_lap"), 0.2, pl_hi)
    base_lap = _f(snap.get("base_lap"), 20.0, 1200.0)
    if not tank:
        why.append("no tank")
        return out
    if per_lap is None:
        why.append("per_lap missing/absurd")
        return out
    load = _f(snap.get("load_now"), 0.0, tank)
    if load is None:
        load = tank
        why.append("load_now missing -> assume full")

    # ── giri rimanenti: gara a giri = dato CERTO; a tempo = tempo/passo
    #    meno il tempo delle soste (iterativo, ai box non si gira) ──
    laps_left = int(_f(snap.get("race_laps_left"), 1, 5000) or 0)
    if not laps_left:
        secs = _f(snap.get("race_seconds_left"), 120.0, 86400.0)
        if not secs or not base_lap:
            why.append("no race length (laps or time+pace)")
            return out
        laps_left = max(1, int(secs / base_lap) + 1)
        ploss = _f(snap.get("pit_loss"), 1.0, 600.0) or 0.0
        lfull = tank / per_lap
        lnow = load / per_lap
        if ploss > 0 and lfull > 0:
            stops_n = 0
            for _ in range(6):
                need = laps_left - lnow
                stops_n = 0
                if need > 0:
                    stops_n = int(need / lfull)
                    if need > stops_n * lfull:
                        stops_n += 1
                new = max(1, int((secs - stops_n * ploss) / base_lap) + 1)
                if new == laps_left:
                    break
                laps_left = new
            if stops_n:
                why.append("pit loss %.0fs x %d stops" % (ploss, stops_n))
        why.append("timed race: %d laps from %.0fs / %.1fs"
                   % (laps_left, secs, base_lap))
    laps_done = int(_f(snap.get("laps_done"), 0, 100000) or 0)

    laps_now = load / per_lap
    laps_full = tank / per_lap
    why.append("autonomy now %.1f, full %.1f laps" % (laps_now, laps_full))

    # vita gomma in giri (None = nessun vincolo)
    dead = _f(snap.get("wear_dead")) or WEAR_DEAD
    deg = _f(snap.get("deg_per_lap"), 0.01, 20.0)
    wear = _f(snap.get("wear_now"), 0.0, 100.0)
    tyre_now = ((wear - dead) / deg) if (deg and wear is not None) else None
    tyre_full = ((100.0 - dead) / deg) if deg else None
    if tyre_now is not None:
        why.append("tyre now %.1f, new %.1f laps" % (tyre_now, tyre_full))

    # ── segmenti meteo (relativi) e MURI dry->wet ──
    wet_now = snap.get("track_wet_now")
    rain_now = bool((_f(snap.get("raining_now"), 0.0, 1.0) or 0.0) >= 0.05)
    segs = wx_segments(snap.get("forecast5"), laps_left, wet_now=wet_now,
                       laps_done=laps_done, rain_now=rain_now)
    wet0 = bool(snap.get("wet_mounted"))
    walls = []                       # [(lap_rel, 'WET'|'SLICK')]
    on_wet = wet0
    for i, (a, b, reg) in enumerate(segs):
        if reg == "wet":
            if i == 0 and not on_wet:
                walls.append((max(1, min(1, laps_left - 1)), "WET"))
                on_wet = True
            elif not on_wet:
                walls.append((a, "WET"))
                on_wet = True
        # wet->dry non e' MAI un muro: resta la scelta del pilota
    if walls:
        why.append("weather walls at rel %s" % [w[0] for w in walls])

    # ── SIMULAZIONE SEQUENZIALE del serbatoio ─────────────────────────
    def need_to(lap_from, lap_to):
        return max(0.0, (lap_to - lap_from) * per_lap * RESERVE)

    stops = []
    pos = 0.0
    fuel_laps = laps_now
    t_laps = tyre_now if tyre_now is not None else float("inf")
    wall_i = 0
    guard = 0
    while pos < laps_left and guard < 40:
        guard += 1
        wall = walls[wall_i] if wall_i < len(walls) else None
        goal = float(wall[0]) if wall else float(laps_left)
        reach = pos + min(fuel_laps, t_laps)
        if reach >= goal - 1e-9:
            if wall is None:
                break                          # bandiera raggiunta
            # MURO METEO: ci si arriva e si cambia; rabbocco per la FINE
            # (sei gia' fermo per le gomme, il pieno e' in parallelo)
            arrive = max(0.0, (fuel_laps - (goal - pos)) * per_lap)
            refuel = min(max(0.0, need_to(goal, laps_left) - arrive),
                         tank - arrive)
            stops.append({"lap": goal, "reason": "weather", "tyre": wall[1],
                          "refuel_pct": refuel / tank * 100.0,
                          "arrive_pct": arrive / tank * 100.0})
            pos = goal
            fuel_laps = (arrive + refuel) / per_lap
            t_laps = tyre_full if tyre_full is not None else float("inf")
            wall_i += 1
            continue
        # sosta FORZATA prima del muro/fine (energia o gomma)
        limit = "tyre" if t_laps < fuel_laps else "energy"
        stop_lap = int(reach)
        if stop_lap <= int(pos):
            stop_lap = int(pos) + 1
        # FUSIONE: se il muro e' vicino (<= MERGE_W), anticipa AL muro? No:
        # il muro sta DOPO reach — se la distanza e' piccola non si arriva.
        # Se invece la sosta cade a <= MERGE_W dal muro, la si fa DIVENTARE
        # il muro solo quando raggiungibile; altrimenti resta qui.
        arrive = max(0.0, (fuel_laps - (stop_lap - pos)) * per_lap)
        refuel = min(max(0.0, need_to(stop_lap, laps_left) - arrive),
                     tank - arrive)
        changed = (limit == "tyre")
        stype = None
        if changed:
            stype = "WET" if (wall_i < len(walls) and wet0) else "SLICK"
            if wall and (wall[0] - stop_lap) <= MERGE_W:
                stype = wall[1]                # fusione: monta gia' la gomma
        stops.append({"lap": float(stop_lap), "reason": limit, "tyre": stype,
                      "refuel_pct": refuel / tank * 100.0,
                      "arrive_pct": arrive / tank * 100.0})
        pos = float(stop_lap)
        fuel_laps = (arrive + refuel) / per_lap
        t_laps = (tyre_full if changed else t_laps - (stop_lap - pos)) \
            if tyre_full is not None else float("inf")
        if changed and wall and (wall[0] - stop_lap) <= MERGE_W:
            wall_i += 1                        # muro assorbito dalla fusione

    # ── stints + uscita in giri ASSOLUTI ──
    stints = []
    prev = 0.0
    cur_tyre = "WET" if wet0 else "SLICK"
    for s in stops + [{"lap": float(laps_left), "tyre": None}]:
        lap = float(s["lap"])
        if lap > prev:
            stints.append({"da": int(prev) + laps_done,
                           "a": int(lap) + laps_done,
                           "tyre": cur_tyre, "drive": ("PUSH", 0)})
        prev = lap
        if s.get("tyre"):
            cur_tyre = s["tyre"]

    for s in stops:
        if s["refuel_pct"] + s["arrive_pct"] > 100.0 + 1e-6:
            why.append("SANITY FAIL refuel+arrive>100")
            return out
        s["lap"] = int(round(s["lap"])) + laps_done
        s["target_pct"] = round(min(100.0, s["refuel_pct"] + s["arrive_pct"]), 1)
        s["refuel_pct"] = round(s["refuel_pct"], 1)
        s["arrive_pct"] = round(s["arrive_pct"], 1)

    out.update({
        "ok": True, "feasible": True, "constraint": constraint,
        "laps_left": laps_left, "race_laps": laps_left + laps_done,
        "tank": tank, "per_lap": per_lap,
        "autonomy_now": round(laps_now, 1),
        "autonomy_full": round(laps_full, 1),
        "segments": [(a + laps_done, b + laps_done, r) for a, b, r in segs],
        "stops": stops, "strip_stops": stops, "stints": stints,
        "verdict": {"stops": len(stops), "mode": "normal", "save_pct": 0},
    })
    return out
