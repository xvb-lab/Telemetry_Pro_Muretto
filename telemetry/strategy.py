"""
telemetry/strategy.py — Logica strategia stint/pit con verifica di fattibilità.

Differenza chiave rispetto al vecchio calc: il "goal" non è più floor(stint_real)
ciecamente, ma il numero di soste REALMENTE ottenibile dato il margine di
risparmio (lift&coast) espresso in GIRI per stint (default ~2 giri).

Per ciascun vincolo (Virtual Energy e Fuel) calcola separatamente, poi il
vincolo critico è quello che impone più soste / finisce prima.

Modello soste:
  A = autonomia residua (giri) dello stint corrente al passo attuale
  F = giri di uno stint pieno al passo attuale (budget_full / consumo_giro)
  M = margine risparmiabile per stint (giri, lift&coast)        [config]
  L = giri rimasti in gara (tempo_rimasto / tempo_giro)

  soste senza risparmio  k_nosave = min k>=0 :  A + k*F        >= L
  soste con risparmio max k_save   = min k>=0 : (A+M) + k*(F+M) >= L

  - k_save < k_nosave  -> "puoi salvare una sosta" col lift&coast (giallo)
  - k_save == k_nosave -> passo attuale già ok (verde)
  - consumo in salita che fa crescere k_nosave -> rosso

Tutto in unità misurate dal vivo: i moltiplicatori evento (consumo x2 ecc.)
sono già dentro il consumo/giro reale, quindi non vanno letti a parte.
"""
import math
from collections import deque


def _ceil_stops(autonomy, full_stint, laps_rem):
    """min k>=0 intero tale che autonomy + k*full_stint >= laps_rem."""
    if laps_rem is None or autonomy is None or full_stint is None or full_stint <= 0:
        return None
    if autonomy >= laps_rem:
        return 0
    return int(math.ceil((laps_rem - autonomy) / full_stint))


def _constraint_plan(current, budget_full, per_lap, laps_rem, margin):
    """Calcola il piano soste per un singolo vincolo.

    current     : valore residuo ora (VE % o fuel L)
    budget_full : budget di uno stint pieno (100 per VE, fuel_max per fuel)
    per_lap     : consumo per giro misurato (stessa unità)
    laps_rem    : giri rimasti in gara
    margin      : giri risparmiabili per stint (lift&coast)
    Ritorna dict o None se dati insufficienti.
    """
    if not per_lap or per_lap <= 0 or not budget_full or budget_full <= 0:
        return None
    if laps_rem is None or laps_rem <= 0:
        return None
    autonomy = (current / per_lap) if current is not None else None
    full_stint = budget_full / per_lap
    if autonomy is None:
        return None

    k_nosave = _ceil_stops(autonomy, full_stint, laps_rem)
    k_save = _ceil_stops(autonomy + margin, full_stint + margin, laps_rem)
    if k_nosave is None or k_save is None:
        return None

    stops = k_save                      # soste rimanenti (piano ottimo fattibile)
    total_stints = stops + 1            # stint corrente + soste
    save_a_stop = k_save < k_nosave

    # consumo medio/giro necessario per il piano a k_save soste
    # budget totale = residuo ora + k_save rifornimenti pieni
    total_budget = current + k_save * budget_full
    target_per_lap = total_budget / laps_rem if laps_rem > 0 else None

    # finestra prossima sosta (giri assoluti li aggiunge il chiamante):
    # quando si va a secco (col margine se serve risparmiare)
    dry_in = autonomy + (margin if save_a_stop else 0.0)

    return {
        "autonomy": autonomy,
        "full_stint": full_stint,
        "k_nosave": k_nosave,
        "k_save": k_save,
        "stops": stops,
        "total_stints": total_stints,
        "save_a_stop": save_a_stop,
        "target_per_lap": target_per_lap,
        "per_lap": per_lap,
        "dry_in": dry_in,
    }


def compute(measured, margin_laps=2.0):
    """Calcolo strategia completo.

    measured: dict con
      ve, ve_lap, fuel, fuel_max, fuel_lap, lap_time, race_remaining,
      laps_completed
    margin_laps: giri risparmiabili per stint (lift&coast). Si può dare un
      valore distinto per ve/fuel passando un dict {'ve':x,'fuel':y}.
    Ritorna dict pronto per la UI.
    """
    lap_time = measured.get("lap_time")
    race_rem = measured.get("race_remaining")
    laps_done = measured.get("laps_completed", 0) or 0
    pit_loss = measured.get("pit_loss") or 0.0
    try:
        max_laps = int(measured.get("max_laps") or 0)
    except (TypeError, ValueError):
        max_laps = 0

    if isinstance(margin_laps, dict):
        m_ve = float(margin_laps.get("ve", 2.0))
        m_fuel = float(margin_laps.get("fuel", 2.0))
    else:
        m_ve = m_fuel = float(margin_laps)

    def _plans_for(lr):
        pv = _constraint_plan(measured.get("ve"), 100.0,
                              measured.get("ve_lap"), lr, m_ve)
        pf = _constraint_plan(measured.get("fuel"), measured.get("fuel_max"),
                              measured.get("fuel_lap"), lr, m_fuel)
        return pv, pf

    laps_rem = None
    if lap_time and lap_time > 0 and race_rem:
        # gara A TEMPO: +1 (il giro iniziato si finisce) e AI BOX NON SI
        # GIRA: il tempo delle soste va tolto (conto circolare, 3 iterazioni
        # bastano ad assestarlo — stessa regola del muretto)
        laps_rem = max(1, int(race_rem / lap_time) + 1)
        if pit_loss and pit_loss > 0:
            for _ in range(3):
                _pv, _pf = _plans_for(laps_rem)
                _st = max([pl["stops"] for pl in (_pv, _pf) if pl] or [0])
                _new = max(1, int((race_rem - _st * pit_loss) / lap_time) + 1)
                if _new == laps_rem:
                    break
                laps_rem = _new
    elif (not race_rem) and 0 < max_laps < 5000:
        # gara A GIRI (solo SENZA tempo: nelle gare a tempo LMU mette in
        # mMaxLaps l'autonomia, non la distanza — mai fidarsi li')
        laps_rem = max(0, max_laps - int(laps_done)) or None

    plan_ve, plan_fuel = _plans_for(laps_rem)

    # vincolo critico = quello che impone più soste; a parità, autonomia minore
    plans = {"VE": plan_ve, "FUEL": plan_fuel}
    crit = None
    for key, pl in plans.items():
        if pl is None:
            continue
        if crit is None:
            crit = key
            continue
        a, b = plans[crit], pl
        if (pl["stops"] > plans[crit]["stops"] or
                (pl["stops"] == plans[crit]["stops"] and pl["autonomy"] < plans[crit]["autonomy"])):
            crit = key

    out = {
        "laps_rem": laps_rem,
        "constraint": crit,
        "plan_ve": plan_ve,
        "plan_fuel": plan_fuel,
    }

    if crit is None:
        out.update({"stops": None, "total_stints": None, "save_a_stop": False,
                    "pit_lo": None, "pit_hi": None, "target_per_lap": None,
                    "current_per_lap": None, "delta_per_lap": None,
                    "on_target": "wait"})
        return out

    c = plans[crit]
    pit_hi = laps_done + c["dry_in"]
    # finestra CENTRATA sul piano: non fermarti PRIMA del punto da cui le
    # soste rimanenti (a stint pieni) coprono esattamente il traguardo
    if laps_rem is not None and c["stops"] >= 1 and c.get("full_stint"):
        _lo_rel = laps_rem - c["stops"] * c["full_stint"]
        pit_lo = laps_done + max(0.0, _lo_rel)
        pit_lo = max(laps_done, min(pit_lo, pit_hi))
    else:
        pit_lo = max(laps_done, pit_hi - 3.0)

    # TAPPO del MURETTO: se il piano completo (meteo/gomme incluso) ha gia'
    # una sosta prima della finestra carburante, la finestra finisce LI'.
    _nsl = measured.get("next_stop_lap")
    if _nsl:
        try:
            _nsl = float(_nsl)
            if _nsl < pit_hi:
                pit_hi = _nsl
                if pit_lo > pit_hi:
                    pit_lo = max(float(laps_done), pit_hi - 3.0)
        except (TypeError, ValueError):
            pass

    target = c["target_per_lap"]
    cur = c["per_lap"]
    delta = (cur - target) if (target is not None and cur is not None) else None

    # stato on_target
    if c["save_a_stop"]:
        on = "warn"                      # puoi salvare una sosta ma serve risparmiare
    elif target is not None and cur is not None and cur > target * 1.02:
        on = "over"                      # consumi più del budget: rischi una sosta in più
    else:
        on = "ok"

    out.update({
        "stops": c["stops"],
        "total_stints": c["total_stints"],
        "save_a_stop": c["save_a_stop"],
        "pit_lo": int(pit_lo),
        "pit_hi": int(pit_hi),
        "target_per_lap": target,
        "current_per_lap": cur,
        "delta_per_lap": delta,
        "on_target": on,
    })
    return out


# ── tracker consumo (media mobile) + rilevamento stint/giro ───────────────
class StintTracker:
    """Mantiene media mobile su N giri di consumo VE/giro, fuel/giro, tempo
    giro, e i contatori dello stint corrente. Da alimentare ad ogni read()."""

    def __init__(self, window=3):
        self.window = window
        self.reset_all()

    def reset_all(self):
        self.stint_index = 1
        self._started = False
        self._reset_stint()
        self._was_in_pits = False
        self._was_garage = False
        self._last_num_pit = None

    def _reset_stint(self):
        self.stint_start_et = None
        self.stint_start_laps = None
        self._ve = deque(maxlen=self.window)
        self._fuel = deque(maxlen=self.window)
        self._lt = deque(maxlen=self.window)
        self._prev_ve = None
        self._prev_fuel = None
        self._last_laps = None
        self._lap_dirty = False       # giro passato dai box: fuori dalle medie

    @staticmethod
    def _avg(dq):
        return sum(dq) / len(dq) if dq else None

    def update(self, d):
        in_pits = bool(d.get("in_pits", False))
        garage = bool(d.get("garage", False))
        num_pit = int(d.get("num_pit", 0) or 0)
        laps = int(d.get("laps_completed", 0) or 0)
        cur_et = float(d.get("race_total", 0) or 0) - float(d.get("race_remaining", 0) or 0)
        ve = d.get("ve")
        fuel = d.get("fuel")
        last_lap = d.get("last_lap", -1)

        new_stint = False
        if self._started:
            if self._was_in_pits and not in_pits:
                new_stint = True
            if self._last_num_pit is not None and num_pit > self._last_num_pit:
                new_stint = True
            if garage and not self._was_garage:
                new_stint = True
        if new_stint:
            self.stint_index += 1
            self._reset_stint()
        self._was_in_pits = in_pits
        self._was_garage = garage
        self._last_num_pit = num_pit

        # il giro corrente ha toccato pit/garage? le sue medie sono sporche
        if in_pits or garage or bool(d.get("in_pitlane", False)):
            self._lap_dirty = True

        if self.stint_start_et is None and not in_pits and not garage:
            if not self._started:
                self._started = True
                self.stint_index = 1
            self.stint_start_et = cur_et
            self.stint_start_laps = laps
            self._last_laps = laps
            self._prev_ve = ve
            self._prev_fuel = fuel

        if self._last_laps is not None and laps > self._last_laps:
            _clean = not getattr(self, "_lap_dirty", False)
            if _clean and self._prev_ve is not None and ve is not None:
                dv = self._prev_ve - ve
                if dv > 0:
                    self._ve.append(dv)
            if _clean and self._prev_fuel is not None and fuel is not None:
                df = self._prev_fuel - fuel
                if df > 0:
                    self._fuel.append(df)
            if _clean and last_lap and last_lap > 0:
                self._lt.append(float(last_lap))
            self._prev_ve = ve
            self._prev_fuel = fuel
            self._last_laps = laps
            self._lap_dirty = False       # nuovo giro: riparte pulito

    def measured(self, d):
        """Compone il dict per compute() unendo medie e stato corrente."""
        return {
            "ve": d.get("ve"),
            "ve_lap": self._avg(self._ve),
            "fuel": d.get("fuel"),
            "fuel_max": d.get("fuel_max"),
            "fuel_lap": self._avg(self._fuel),
            "lap_time": self._avg(self._lt),
            "race_remaining": d.get("race_remaining"),
            "laps_completed": d.get("laps_completed", 0),
        }

    def stint_info(self, d):
        cur_et = float(d.get("race_total", 0) or 0) - float(d.get("race_remaining", 0) or 0)
        laps = int(d.get("laps_completed", 0) or 0)
        return {
            "stint_index": self.stint_index,
            "stint_time": (cur_et - self.stint_start_et) if self.stint_start_et is not None else 0,
            "stint_laps": (laps - self.stint_start_laps) if self.stint_start_laps is not None else 0,
        }
