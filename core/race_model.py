# -*- coding: utf-8 -*-
"""RACE MODEL — il quadro di gara che il muretto costruisce SUBITO al via.

Dal forecast a 5 nodi + energia + degrado esce il PIANO BASE:
  1. SEGMENTI: la gara divisa in regimi (dry/wet) su TUTTE le combinazioni
     dei 5 split (all-dry, all-wet, wet/dry/wet, dry/wet/dry, ...).
  2. SOSTE FUSE: le soste METEO sono vincoli fissi (il cambio gomma alla
     transizione si fa comunque); le soste ENERGIA si APPOGGIANO a quelle
     meteo quando sono vicine (|delta| <= merge_window: si allunga o si
     anticipa) e il RABBOCCO di ogni sosta e' dimensionato per arrivare al
     confine successivo (prossima sosta o bandiera) col minimo di soste.
  3. ISTRUZIONE PER STINT: PUSH o MANAGE(pct).
     - gomma che muore a una sosta meteo -> NIENTE gestione gomma (regola:
       "e' inutile gestire, tanto ci fermiamo per le wet").
     - energia: se gestire NON elimina nessuna sosta, lo stint e' STANDARD
       -> PUSH anche sui consumi ("tanto c'e' da fermarsi, si rabbocca").
     - se gestire (lift&coast, ~10%) ELIMINA una sosta -> MANAGE con la
       percentuale che serve.

Il modello e' VOLATILE: rebuild() si richiama a ogni evento (pit fatto,
pilota che resta fuori, forecast cambiato) coi numeri di ADESSO.
Zero dipendenze Qt: testabile a banco.
"""

ECO_GAIN = 0.10          # risparmio realistico in gestione (lift&coast)
WET_ON, DRY_ON = 50.0, 30.0   # isteresi transizioni forecast (come engineer)
MERGE_W = 3              # |giri| entro cui la sosta energia si fonde col meteo


def wx_segments(forecast, race_laps):
    """Forecast 5 nodi -> [(da_giro, a_giro, 'dry'|'wet')]. Isteresi:
    bagnato da >=50, asciutto da <=30, nodi interpolati linearmente."""
    race_laps = int(race_laps or 0)
    if race_laps < 3:
        return []
    try:
        vals = [float(v) for v in (forecast or [])[:5]]
    except (TypeError, ValueError):
        vals = []
    if len(vals) < 5:
        return [(0, race_laps, "dry")]
    fracs = [0.0, 0.25, 0.50, 0.75, 1.0]
    wet = vals[0] >= 40.0
    cur = "wet" if wet else "dry"
    segs = []
    start = 0
    for i in range(1, 5):
        a, b = vals[i - 1], vals[i]
        if not wet and b >= WET_ON:
            t = (WET_ON - a) / (b - a) if b != a else 0.0
            fr = fracs[i - 1] + (fracs[i] - fracs[i - 1]) * max(0.0, min(1.0, t))
            lap = int(round(fr * race_laps))
            if lap > start:
                segs.append((start, lap, cur))
            start, cur, wet = lap, "wet", True
        elif wet and b <= DRY_ON:
            t = (a - DRY_ON) / (a - b) if a != b else 0.0
            fr = fracs[i - 1] + (fracs[i] - fracs[i - 1]) * max(0.0, min(1.0, t))
            lap = int(round(fr * race_laps))
            if lap > start:
                segs.append((start, lap, cur))
            start, cur, wet = lap, "dry", False
    segs.append((start, race_laps, cur))
    return [s for s in segs if s[1] > s[0]]


def build(race_laps, forecast, fuel_laps_now, fuel_laps_full,
          laps_done=0, wet_mounted=False, double_worth=None,
          slick_avail=None):
    """Costruisce il piano base. Ritorna dict:
      segments:   [(da, a, regime)]
      stops:      [{lap, reason, tyre, refuel_laps}]  ordinate
      stints:     [{da, a, tyre, drive: 'PUSH'|('MANAGE', pct), note}]
      stops_total, feasible
    double_worth(window_laps) -> bool: il doppio cambio ripaga? (None = si')
    """
    race_laps = int(race_laps or 0)
    segs = wx_segments(forecast, race_laps)
    if not segs:
        return None
    # regime di adesso coerente con la gomma montata (partenza bagnata ecc.)
    # ── 1) SOSTE METEO: una a ogni transizione FUTURA ──
    wx_stops = []
    cur = "W" if wet_mounted else "S"      # gomma DI ADESSO: un cambio verso
    for i in range(1, len(segs)):          # la gomma gia' montata non esiste
        lap = segs[i][0]
        to_wet = segs[i][2] == "wet"
        want = "W" if to_wet else "S"
        if lap <= laps_done:
            continue
        if want == cur:
            continue                       # gia' sulla gomma giusta: si passa
        wx_stops.append({"lap": lap, "reason": "wx", "tyre": want})
        cur = want
    # finestra asciutta corta: il doppio cambio potrebbe non ripagare
    if double_worth is not None and len(wx_stops) >= 2:
        pruned = []
        skip_next = False
        for i, st in enumerate(wx_stops):
            if skip_next:
                skip_next = False
                continue
            if (st["tyre"] == "S" and i + 1 < len(wx_stops)
                    and wx_stops[i + 1]["tyre"] == "W"):
                win = wx_stops[i + 1]["lap"] - st["lap"]
                if not double_worth(win):
                    skip_next = True      # restiamo in wet: niente coppia S->W
                    continue
            pruned.append(st)
        wx_stops = pruned
    # ── 2) SOSTE ENERGIA fuse ──
    stops = list(wx_stops)
    fuel_now = float(fuel_laps_now or 0.0)
    fuel_full = float(fuel_laps_full or fuel_now or 0.0)
    if fuel_full <= 0:
        fuel_full = max(fuel_now, 1.0)
    pos = laps_done
    reach = pos + fuel_now                    # fin dove arrivo col carico
    feasible = True
    guard = 0
    while reach < race_laps - 0.01 and guard < 12:
        guard += 1
        # prossima sosta meteo gia' pianificata raggiungibile?
        nxt = next((s for s in stops
                    if pos < s["lap"] and s["lap"] > pos), None)
        if nxt and nxt["lap"] <= reach + MERGE_W:
            # FUSIONE: la sosta meteo copre anche l'energia. Se il meteo e'
            # PRIMA della portata, ok; se e' fino a MERGE_W DOPO, si allunga
            # in gestione ("si prova ad allungare due giri").
            if nxt["lap"] > reach:
                nxt["stretch"] = int(round(nxt["lap"] - reach))
            nxt["refuel"] = True
            pos = nxt["lap"]
            reach = pos + fuel_full
            continue
        # niente meteo vicino: sosta ENERGIA pura al limite dell'autonomia
        lap = int(reach)
        if lap <= pos:
            feasible = False
            break
        stops.append({"lap": lap, "reason": "energy", "tyre": None,
                      "refuel": True})
        pos = lap
        reach = pos + fuel_full
    stops.sort(key=lambda s: s["lap"])
    # ── FUSIONE COPPIE VICINE: due soste a meno di ~6 giri sono uno spreco
    # (un pit extra costa ~25s). Si fondono in una: se una delle due cambia
    # gomma (wx) si tiene QUELLA (col suo giro e la sua gomma) e si assorbe
    # il rifornimento dell'altra; due energia -> si tiene la prima.
    MERGE_NEAR = 6
    fused = []
    _i = 0
    while _i < len(stops):
        cur = stops[_i]
        if _i + 1 < len(stops) and stops[_i + 1]["lap"] - cur["lap"] <= MERGE_NEAR:
            nxt = stops[_i + 1]
            # il cambio gomma (wx) ha la precedenza: si tiene quello
            if cur["reason"] == "wx" and nxt["reason"] != "wx":
                keep = cur
            elif nxt["reason"] == "wx" and cur["reason"] != "wx":
                keep = nxt
            else:
                keep = cur          # due uguali: la prima
            keep["refuel"] = True   # la sosta unica rifornisce comunque
            fused.append(keep)
            _i += 2                 # saltata la coppia
        else:
            fused.append(cur)
            _i += 1
    stops = fused
    # rabbocchi dimensionati: simulazione SEQUENZIALE del serbatoio, fatta
    # QUI (unica fonte di verita'). Ogni sosta esce col rabbocco gia' in
    # percentuale/litri, CAPATO allo spazio reale: non si carica mai piu' di
    # (cap - livello). Questo elimina alla radice il "+54% con serbatoio a 93%".
    _cap = 100.0                       # ENERGY: 0-100; FUEL: fuel_laps in giri
    _per = 1.0                         # per-giro in unita' "giri di autonomia"
    # lavoro in GIRI di autonomia (fuel_laps_full = giri col pieno):
    #   livello in giri, consumo 1 giro/giro. Semplice e sempre coerente.
    _tank_laps = float(fuel_full) if fuel_full else 1.0
    _lev = float(fuel_laps_now) if fuel_laps_now else _tank_laps
    _prev = laps_done
    for i, st in enumerate(stops):
        if not st.get("refuel"):
            st["refuel"] = True
        nxt_lap = stops[i + 1]["lap"] if i + 1 < len(stops) else race_laps
        st["refuel_laps"] = min(int(_tank_laps),
                                max(1, nxt_lap - st["lap"] + 1))
        # livello stimato all'arrivo ai box (giri di autonomia rimasti)
        _lev = max(0.0, _lev - (st["lap"] - _prev))
        # quanto serve per il tratto successivo, capato allo spazio libero
        _need = nxt_lap - st["lap"]
        _space = _tank_laps - _lev
        _add_laps = max(0.0, min(_space, _need - _lev))
        # in percentuale del serbatoio (o litri se il chiamante lo converte)
        st["refuel_pct"] = int(round(_add_laps / _tank_laps * 100.0)) \
            if _tank_laps else 0
        st["arrive_pct"] = int(round(_lev / _tank_laps * 100.0)) \
            if _tank_laps else 0
        _lev = min(_tank_laps, _lev + _add_laps)
        _prev = st["lap"]
    # ── 3) STINT + istruzioni ──
    bounds = [laps_done] + [s["lap"] for s in stops] + [race_laps]
    stints = []
    cur_tyre = "W" if wet_mounted else "S"
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        if b <= a:
            continue
        ends_wx = (i < len(stops) and stops[i]["reason"] == "wx")
        note = ""
        drive = "PUSH"
        if ends_wx:
            note = "gomma a fine vita programmata: NIENTE gestione gomma"
        # energia: gestire elimina una sosta?
        # confronto soste con e senza ECO_GAIN sul totale rimanente
        if i == 0 and stops:
            import math
            rem = race_laps - laps_done
            def _n_stops(f_now, f_full):
                if f_now >= rem:
                    return 0
                return int(math.ceil((rem - f_now) / max(1.0, f_full)))
            n_std = _n_stops(fuel_now, fuel_full)
            n_eco = _n_stops(fuel_now * (1 + ECO_GAIN),
                             fuel_full * (1 + ECO_GAIN))
            if n_eco < n_std:
                deficit_pct = max(2, int(round(
                    (1.0 - (fuel_now + (n_eco) * fuel_full) / rem)
                    * 100))) if rem > 0 else 5
                drive = ("MANAGE", min(10, max(2, deficit_pct)))
                note = (note + "; " if note else "") + \
                    "gestendo si ELIMINA una sosta"
            else:
                note = (note + "; " if note else "") + \
                    "stint standard: si spinge, tanto si rabbocca"
        st_prev = stops[i - 1] if 0 < i <= len(stops) else None
        tyre = (st_prev.get("tyre") or cur_tyre) if st_prev else cur_tyre
        if st_prev and st_prev.get("tyre"):
            cur_tyre = st_prev["tyre"]
        stints.append({"da": a, "a": b, "tyre": tyre,
                       "drive": drive, "note": note})
    # VINCOLO GOMME: i cambi verso slick nel piano non possono superare i
    # treni slick disponibili (le wet sono illimitate). Se sforano, il piano
    # e' comunque il migliore ma va segnalato: gomme insufficienti.
    slick_needed = sum(1 for st in stops if st.get("tyre") == "S")
    tyre_ok = True
    if slick_avail is not None and slick_needed > int(slick_avail):
        tyre_ok = False
    # ── PACCHETTO STRIP: dati gia' pronti per il display (nessun calcolo a
    # valle). Ogni sosta: giro, gomma, rabbocco %, arrivo %. Lo stato
    # nuovo/usato e la mescola reale li arricchisce engineer (ha il REST).
    strip_stops = [{"lap": st["lap"], "tyre": st.get("tyre"),
                    "reason": st.get("reason"),
                    "refuel_pct": st.get("refuel_pct", 0),
                    "arrive_pct": st.get("arrive_pct", 0)}
                   for st in stops]
    return {"segments": segs, "stops": stops, "stints": stints,
            "slick_needed": slick_needed, "tyre_ok": tyre_ok,
            "strip_stops": strip_stops,
            "stops_total": len(stops), "feasible": feasible,
            "race_laps": race_laps}


# ── CONSIGLIO MESCOLA slick per stint (dalla telemetria vera) ──────────
# In LMU ogni evento porta un SOTTOINSIEME delle mescole (Michelin ne porta
# 2 di 3; ELMS Barcellona usa la Hard). Quindi si sceglie SEMPRE tra quelle
# realmente disponibili nella sessione (dal REST), mai da una tabella fissa.
# Fallback per-classe SOLO se il REST non risponde:
_COMPOUND_ORDER = {          # dalla piu' morbida alla piu' dura
    "hypercar": ["M", "H"], "lmh": ["M", "H"], "lmdh": ["M", "H"],
    "gte": ["S", "M", "H"],
    "lmgt3": ["M", "H"], "gt3": ["M"],       # GT3: solo Medium (+H raro)
    "lmp2": ["M"], "lmp3": ["M"],            # slick unica
}
_COMPOUND_NAME = {"S": "soft", "M": "medium", "H": "hard"}
_TYPE_TO_SIG = {"soft": "S", "medium": "M", "hard": "H"}


def compound_for_stint(car_class, stint_laps, track_temp_c=None,
                       available=None, compounds=None):
    """Mescola slick consigliata per uno stint, dai dati veri.
    available: sigle realmente disponibili nell'evento (dal REST). Prioritaria.
    compounds: [{type, wear_per_lap, optimal_temp}] dal REST per scelta fine.
    Ritorna (sigla, motivo) o None se nessuna slick disponibile.
    """
    cl = (car_class or "").lower()
    # 1) mescole disponibili: REST (available) > compounds > fallback classe
    order = None
    if available:
        order = [c for c in ["S", "M", "H"] if c in available]
    if not order and compounds:
        order = [_TYPE_TO_SIG.get((c.get("type") or "").lower())
                 for c in compounds
                 if _TYPE_TO_SIG.get((c.get("type") or "").lower())]
        order = [c for c in ["S", "M", "H"] if c in order]
    if not order:
        for k, v in _COMPOUND_ORDER.items():
            if k in cl:
                order = list(v)
                break
    if not order:
        order = ["M"]
    # una sola mescola: nessuna scelta, e' quella
    if len(order) == 1:
        return order[0], "unica slick dell'evento"
    # 2) SCELTA FINE dai dati: se ho temp ottimale per mescola, prendo quella
    # piu' vicina alla temp pista attuale (la gomma nel suo range rende meglio)
    if compounds and track_temp_c is not None:
        best = None
        for c in compounds:
            sig = _TYPE_TO_SIG.get((c.get("type") or "").lower())
            ot = c.get("optimal_temp")
            if sig in order and ot is not None:
                # optimal_temp del REST e' in Celsius gia' convertito a monte
                dist = abs(float(ot) - float(track_temp_c))
                if best is None or dist < best[1]:
                    best = (sig, dist)
        if best:
            return best[0], ("miglior finestra a %d\u00b0 pista"
                             % round(track_temp_c))
    # 3) EURISTICA durata+temp: stint lungo/caldo -> piu' dura
    idx = 0
    reason = "piu' grip"
    if stint_laps is not None:
        if stint_laps >= 30:
            idx = len(order) - 1
            reason = "stint lungo (%d giri): la piu' dura tiene" % stint_laps
        elif stint_laps >= 18:
            idx = min(len(order) - 1, 1)
            reason = "stint medio (%d giri)" % stint_laps
        else:
            reason = "stint corto (%d giri): piu' grip" % stint_laps
    if track_temp_c is not None and track_temp_c >= 42:
        idx = min(len(order) - 1, idx + 1)
        reason += ", pista calda (%d\u00b0)" % round(track_temp_c)
    return order[idx], reason
