"""
core/strategy_sim.py — SIMULATORE DI STRATEGIA.

Proietta la gara rimanente con i numeri REALI (passo, degrado gomma/giro,
consumo, perdita box misurata) e confronta i piani: 0, 1, 2, 3 soste.

Modello:
- ogni giro costa base_lap + penalita' d'usura (piu' la gomma e' consumata,
  piu' il giro e' lento: PACE_PER_WEAR s per punto % sotto il 100);
- sotto WEAR_FLOOR la gomma va "a scogliera": penalita' pesante e piano
  marcato RISCHIOSO; sotto ~8% il piano e' infeasible;
- ogni sosta costa pit_loss (misurato dalle soste vere quando c'e');
- vincolo carburante/energia: uno stint non puo' superare l'autonomia.

Ritorna i piani ordinati per tempo totale. Nessuna dipendenza.
"""

# Scala LMU (GT3): la vita utile sta tra 100 e ~70. MA la verita' e' il
# CRONOMETRO: quando c'e' il passo misurato (pace_per_wear dai giri reali),
# i default qui sotto sono solo il fallback dei primi giri.
# La gomma NON e' obbligata a fermarsi a una percentuale: si pianifica fino
# al morto (70), e il costo del passo decide da solo quante soste convengono.
PACE_PER_WEAR = 0.03      # s/giro per punto % di usura (fallback, zona alta)
CLIFF_PER_WEAR = 0.10     # s/giro extra per punto sotto la scogliera (fallback)
WEAR_FLOOR = 80.0         # sotto: il passo peggiora di piu' (rischioso)
WEAR_DEAD = 70.0          # sotto: stint non guidabile (unico LIMITE vero)


def _stint_time(laps, wear_start, deg, base_lap,
                floor=None, dead=None, ppw=None, cliff=None):
    """Tempo (extra incluso) di uno stint di `laps` giri partendo da wear_start.
    floor/dead: soglie della gomma montata (None = costanti slick).
    ppw: s/giro per punto % di usura MISURATO (None = fallback costante).
    Ritorna (tempo, wear_finale, rischioso, fattibile)."""
    floor = WEAR_FLOOR if floor is None else floor
    dead = WEAR_DEAD if dead is None else dead
    ppw = PACE_PER_WEAR if ppw is None else max(0.0, float(ppw))
    cliff = CLIFF_PER_WEAR if cliff is None else max(0.0, float(cliff))
    t = 0.0
    w = wear_start
    risky = False
    for _ in range(int(laps)):
        pen = ppw * max(0.0, 100.0 - w)
        if w < floor:
            pen += cliff * (floor - w)
            risky = True
        if w < dead:
            return (t, w, True, False)
        t += base_lap + pen
        w -= deg
    return (t, w, risky, True)


def simulate(rem_laps, base_lap, wear_now, deg, pit_loss,
             fuel_laps_now=None, fuel_laps_full=None, max_stops=3,
             wear_floor=None, wear_dead=None, pace_per_wear=None,
             forced_stop_rel=None):
    """Confronta i piani 0..max_stops soste per i giri rimanenti.

    fuel_laps_now: giri di autonomia col carico ATTUALE (None = niente vincolo)
    fuel_laps_full: giri di autonomia a pieno (per gli stint dopo la sosta)
    wear_floor/wear_dead: soglie gomma alternative (WET: scala spostata in su);
    None = costanti di modulo (slick)
    pace_per_wear: perdita di passo MISURATA (s/giro per punto % di usura):
    quando c'e', il cronometro reale decide i piani, non le costanti
    forced_stop_rel: giro (relativo) di una sosta OBBLIGATA dal meteo (cambio
    gomma alla pioggia/asciugatura): ogni piano deve avere una sosta nella
    finestra [forced-3, forced+1]; lo zero-soste diventa infeasible. Il piano
    non puo' piu' essere "ottimo" su un futuro senza pioggia.

    Ritorna lista di piani ordinata per tempo:
    {stops, time, delta, stint_laps[], first_pit_lap_rel, risky, feasible}
    (first_pit_lap_rel = tra quanti giri conviene la prima sosta)"""
    rem_laps = int(rem_laps)
    if rem_laps <= 0 or base_lap <= 0 or deg <= 0:
        return []
    _floor = WEAR_FLOOR if wear_floor is None else float(wear_floor)
    _dead = WEAR_DEAD if wear_dead is None else float(wear_dead)
    plans = []
    for stops in range(0, max_stops + 1):
        stints = stops + 1
        # sosta OBBLIGATA dal meteo: senza soste il piano e' falso
        if forced_stop_rel is not None and stops == 0 \
                and forced_stop_rel <= rem_laps - 1:
            plans.append({"stops": 0, "feasible": False})
            continue
        # capacita' gomma: fino al MORTO (70), non alla scogliera (80). La
        # zona 80-70 e' guidabile e il suo costo lo decide il modello tempo:
        # tagliare all'80 vietava piani legittimi (bug: proponeva 3 soste).
        cap_first_tyre = max(0, int((wear_now - _dead) / deg))
        cap_new_tyre = max(1, int((100.0 - _dead) / deg))
        # capacita' carburante
        cap_first = cap_first_tyre
        cap_next = cap_new_tyre
        if fuel_laps_now is not None:
            cap_first = min(cap_first, int(fuel_laps_now))
        if fuel_laps_full is not None:
            cap_next = min(cap_next, int(fuel_laps_full))
        # riparto: primo stint il piu' lungo possibile (entro capacita'), il
        # resto diviso equamente sugli stint con gomma nuova
        best_split = None
        if stints == 1:
            splits = [[rem_laps]]
        else:
            rest = stints - 1
            splits = []
            lo = max(0, rem_laps - rest * cap_next)
            hi = min(cap_first, rem_laps - rest)   # almeno 1 giro a stint dopo
            for first in range(max(0, lo), max(0, hi) + 1):
                left = rem_laps - first
                per = left // rest
                extra = left % rest
                sp = [first] + [per + (1 if i < extra else 0) for i in range(rest)]
                if all(x >= 1 for x in sp[1:]):
                    splits.append(sp)
            # prova anche il "primo stint pieno" se non incluso
        for sp in splits or []:
            # vincoli capacita' (gomma a scogliera gestita dal modello tempo)
            if fuel_laps_now is not None and sp[0] > int(fuel_laps_now):
                continue
            if fuel_laps_full is not None and any(x > int(fuel_laps_full) for x in sp[1:]):
                continue
            # una delle soste deve cadere nella FINESTRA METEO
            if forced_stop_rel is not None and stops >= 1 \
                    and forced_stop_rel <= rem_laps - 1:
                cum = 0
                okf = False
                for _laps in sp[:-1]:
                    cum += _laps
                    if forced_stop_rel - 3 <= cum <= forced_stop_rel + 1:
                        okf = True
                        break
                if not okf:
                    continue
            t_tot = stops * float(pit_loss)
            w = wear_now
            risky = False
            ok = True
            for i, laps in enumerate(sp):
                st, w_end, r, f = _stint_time(laps, w if i == 0 else 100.0,
                                              deg, base_lap,
                                              floor=_floor, dead=_dead,
                                              ppw=pace_per_wear)
                t_tot += st
                risky = risky or r
                ok = ok and f
                if not ok:
                    break
            if not ok:
                continue
            if best_split is None or t_tot < best_split[0]:
                best_split = (t_tot, sp, risky)
        if best_split is None:
            plans.append({"stops": stops, "feasible": False})
            continue
        t_tot, sp, risky = best_split
        plans.append({"stops": stops, "time": round(t_tot, 1),
                      "stint_laps": sp, "first_pit_lap_rel": sp[0],
                      "risky": risky, "feasible": True})
    ok = [p for p in plans if p.get("feasible")]
    ok.sort(key=lambda p: p["time"])
    if ok:
        t0 = ok[0]["time"]
        for p in ok:
            p["delta"] = round(p["time"] - t0, 1)
    return ok


# ── self-test ──
if __name__ == "__main__":
    # gara: 30 giri restanti, base 100s, gomme 78%, degrado 1.5%/giro, box 24s
    for p in simulate(30, 100.0, 78.0, 1.5, 24.0,
                      fuel_laps_now=22, fuel_laps_full=28):
        print(p)
