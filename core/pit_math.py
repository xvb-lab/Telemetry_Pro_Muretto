"""core/pit_math.py — calcolatore strategico PURO (deterministico, niente I/O).

Trasforma i numeri di `docs/numeri_strategia.md` in risposte: undercut/overcut,
giri al "cliff" gomme, verdetto double-stint, risparmio sosta sotto FCY, scelta
mescola. Sta SOPRA `lmu_live`; non tocca il cervello collaudato.

REGOLA: in gara si preferisce SEMPRE il dato VIVO di LMU (usura reale, per_lap
misurato, pitstop-estimate del gioco). Queste costanti sono
riferimento/fallback/calibrazione quando il dato live manca.
"""

# ── normalizzazione classe -> {HY, GT3, LMP2, LMP3} ──────────────────────
def norm_class(car_class):
    c = str(car_class or "").upper()
    if any(k in c for k in ("HYPERCAR", "HYPER", "LMH", "LMDH", "HY")):
        return "HY"
    if "GT3" in c or "GTE" in c or "GT " in c:
        return "GT3"          # GTE trattata come GT3 lato gomme/freni
    if "LMP2" in c or c == "P2":
        return "LMP2"
    if "LMP3" in c or c == "P3":
        return "LMP3"
    return None


def norm_track(track):
    t = str(track or "").lower().replace(" ", "").replace("-", "").replace("_", "")
    for key in ("lemans", "sarthe", "monza", "imola", "fuji", "spa",
                "francorchamps"):
        if key in t:
            if key in ("sarthe",):
                return "lemans"
            if key in ("francorchamps",):
                return "spa"
            return key
    return None


# ── costanti (da docs/numeri_strategia.md) ───────────────────────────────
# pit delta = perdita netta per attraversare la corsia box (s)
PIT_DELTA = {"monza": 21.5, "imola": 24.0, "fuji": 26.5, "spa": 29.0,
             "lemans": 34.5}

# usura % per giro (asfalto ~28°C) per classe/mescola
TYRE_WEAR_PL = {
    "HY":   {"soft": 1.1, "medium": 0.8, "hard": 0.5},
    "LMP2": {"soft": 0.9, "medium": 0.9, "hard": 0.9},
    "LMP3": {"soft": 0.9, "medium": 0.9, "hard": 0.9},
    "GT3":  {"soft": 1.4, "medium": 1.0, "hard": 0.6},
}

# vantaggio gomme nuove vs set a fine stint (s/giro) — (min, max)
TYRE_DELTA_NEW = {"HY": (1.2, 1.6), "LMP2": (1.5, 1.8), "GT3": (1.8, 2.3),
                  "LMP3": (1.5, 1.8)}

# penalità out-lap gomme fredde (s) — (min, max)
OUT_LAP_PENALTY = {"HY": (2.5, 3.5), "LMP2": (2.0, 3.0), "GT3": (3.0, 4.2),
                   "LMP3": (2.0, 3.0)}

# consumo/giro di riferimento (pieno regime, mappa gara 1)
CONSUMPTION = {   # track -> {HY: MJ, GT3: MJ, LMP2: litri}
    "lemans": {"HY": 22.5, "GT3": 9.2, "LMP2": 3.45},
    "spa":    {"HY": 14.8, "GT3": 6.1, "LMP2": 2.20},
    "monza":  {"HY": 13.2, "GT3": 5.4, "LMP2": 1.95},
    "fuji":   {"HY": 12.8, "GT3": 5.2, "LMP2": 1.85},
    "imola":  {"HY": 11.5, "GT3": 4.7, "LMP2": 1.65},
}

CLIFF_WARN = 35.0        # % usura: inizia drop ~0.3 s/giro
CLIFF = 45.0             # % usura: crollo +3/4 s/giro, spiattellamento
LC_SAVE_MIN, LC_SAVE_MAX = 0.06, 0.08   # risparmio VE/benzina con Lift&Coast
LC_LAP_COST = (0.15, 0.25)              # costo cronometrico L&C (s/giro)
FCY_PIT_FACTOR = 0.65    # sotto FCY il pit delta si abbatte del ~65%


def _mid(rng):
    return (rng[0] + rng[1]) / 2.0


# ── funzioni ─────────────────────────────────────────────────────────────
def pit_delta(track):
    """Perdita netta in corsia box (s) per il circuito. None se sconosciuto."""
    return PIT_DELTA.get(norm_track(track))


def fcy_pit_saving(track):
    """Secondi risparmiati fermandosi sotto FCY vs sosta in verde (~65% del
    pit delta). None se il circuito non è noto."""
    pd = pit_delta(track)
    return round(pd * FCY_PIT_FACTOR, 1) if pd else None


def tyre_wear_per_lap(car_class, compound="medium"):
    """Usura % per giro di riferimento. None se classe sconosciuta."""
    cl = norm_class(car_class)
    return (TYRE_WEAR_PL.get(cl) or {}).get(str(compound or "medium").lower())


def laps_to_cliff(wear_pct, wear_per_lap):
    """Giri residui prima del cliff (45% usura), dato il consumo/giro.
    <=0 = sei già oltre. None se il consumo non è valido."""
    try:
        wpl = float(wear_per_lap)
        if wpl <= 0:
            return None
        return (CLIFF - float(wear_pct)) / wpl
    except (TypeError, ValueError):
        return None


def double_stint_verdict(wear_end_stint_pct):
    """Verdetto sul tenere le gomme un 2° stint, dall'usura a fine 1° stint:
    <35% 'ok' · 35-45% 'marginal' · >45% 'no'. None se dato mancante."""
    try:
        w = float(wear_end_stint_pct)
    except (TypeError, ValueError):
        return None
    if w < CLIFF_WARN:
        return "ok"
    if w <= CLIFF:
        return "marginal"
    return "no"


def undercut_gain(car_class, laps=3):
    """Guadagno NETTO (s) dell'undercut: montare gomme nuove ORA e spingere per
    `laps` giri contro un rivale su gomme vecchie. = vantaggio_gomme_nuove*laps
    - penalità_out_lap. >0 = l'undercut conviene. (Il pit delta si elide: nel
    duello si fermano entrambi.) None se classe sconosciuta."""
    cl = norm_class(car_class)
    if cl not in TYRE_DELTA_NEW:
        return None
    adv = _mid(TYRE_DELTA_NEW[cl])
    pen = _mid(OUT_LAP_PENALTY[cl])
    return round(adv * float(laps) - pen, 2)


def consumption_per_lap(track, car_class):
    """Consumo/giro di riferimento (MJ per HY/GT3, litri per LMP2). None se
    combinazione non nota."""
    tk = norm_track(track)
    cl = norm_class(car_class)
    if cl == "LMP3":
        cl = "LMP2"       # riferimento litri simile
    return (CONSUMPTION.get(tk) or {}).get(cl)


def compound_for_asphalt(temp_c):
    """Mescola consigliata dalla temp ASFALTO: <19 soft · 20-36 medium ·
    >=37 hard. None se temp non valida."""
    try:
        t = float(temp_c)
    except (TypeError, ValueError):
        return None
    if t < 19.0:
        return "soft"
    if t < 37.0:
        return "medium"
    return "hard"
