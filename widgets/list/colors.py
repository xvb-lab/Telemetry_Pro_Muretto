"""
widgets/hud/colors.py — Costanti e funzioni colore per il CarCanvas.
Portate 1:1 dall'HUD originale.
"""
from PySide6.QtGui import QColor

C_WHITE = QColor("#e8eef5")
C_YELLOW = QColor("#ffe24d")
C_ORANGE = QColor("#ff9a30")
C_PURPLE = QColor("#b06bff")
C_RED = QColor("#ff3b30")
C_BLUE = QColor("#4a90e2")
C_GREEN = QColor("#00e676")


def _scale(pct, w, y, o, p):
    if pct >= w:
        return C_WHITE
    if pct >= y:
        return C_YELLOW
    if pct >= o:
        return C_ORANGE
    if pct >= p:
        return C_PURPLE
    return C_RED


def col_susp(pct):
    return _scale(pct, 100, 89, 50, 20)


def col_oil(t):
    if t >= 135:
        return C_RED
    if t >= 125:
        return C_ORANGE
    if t >= 110:
        return C_YELLOW
    return C_WHITE


def col_water(t):
    if t >= 120:
        return C_RED
    if t >= 110:
        return C_ORANGE
    if t >= 100:
        return C_YELLOW
    return C_WHITE


def col_tyre(pct):
    return _scale(pct, 90, 80, 50, 20)


def col_brake(pct):
    return _scale(pct, 90, 80, 50, 20)


def col_energy(pct):
    return _scale(pct, 30, 15, 5, 1)


def col_emotor_temp(t):
    if t >= 110:
        return C_RED
    if t >= 90:
        return C_YELLOW
    return C_WHITE


def col_brake_temp(t, car_class=""):
    """Temperatura freni in °C con scala reale in base al materiale del disco.

    Carbonio (HY/LMP): glazing sotto ~250°C, ottimale ~350-750°C, critico >900.
      Range Brembo 250-850, finestra ideale carbon 350-800 (Autocar).
    Ghisa/acciaio (GT3/GTE): ottimale ~300-700°C, rischio thermoshock da freddo,
      critico >800°C.
    """
    cls = (car_class or "").upper()
    is_carbon = cls in ("HY", "P2", "P3")
    if is_carbon:
        # dischi carbonio
        if t >= 900:
            return C_RED          # critico
        if t >= 750:
            return C_ORANGE       # caldo
        if t >= 350:
            return C_GREEN        # finestra ottimale
        if t >= 250:
            return C_YELLOW       # sotto soglia (rischio glazing)
        return C_BLUE             # freddo
    else:
        # dischi ghisa/acciaio (GT3, GTE)
        if t >= 800:
            return C_RED          # critico
        if t >= 700:
            return C_ORANGE       # caldo
        if t >= 300:
            return C_GREEN        # finestra ottimale
        if t >= 250:
            return C_YELLOW       # sotto soglia / thermoshock
        return C_BLUE             # freddo


def col_damage(pct):
    """Colore danno carrozzeria, coerente col widget car.
    100=grigio, 75-99 giallo, 45-74 arancione, 20-44 rosso, <20 rosso scuro."""
    if pct >= 100:
        return QColor("#5a5f67")
    if pct >= 75:
        return C_YELLOW
    if pct >= 45:
        return C_ORANGE
    if pct >= 20:
        return C_RED
    return QColor("#7a1410")   # quasi perso: rosso scuro


def col_tyre_temp(t, car_class=""):
    """Colore temperatura gomma (carcassa), finestra per classe.
    GT3/GTE: ottimale 70-95°C. Hypercar/LMP: 75-95°C."""
    if t is None:
        return QColor("#3a4450")
    cls = (car_class or "").upper()
    is_proto = cls in ("HY", "P2", "P3")
    if is_proto:
        cold, cool, hot, over = 65, 75, 95, 108
    else:
        cold, cool, hot, over = 60, 70, 95, 105
    if t < cold:
        return QColor("#4a90e2")      # freddo
    elif t < cool:
        return QColor("#00c8e6")      # sotto finestra
    elif t < hot:
        return QColor("#00e676")      # ottimale
    elif t < over:
        return QColor("#ffe24d")      # caldo
    elif t < over + 12:
        return QColor("#ff9a30")      # molto caldo
    else:
        return QColor("#ff3b30")      # surriscaldo


def select_tyre_temp(d, layer):
    """Seleziona lo strato di temperatura gomma da mostrare.

    layer: 'surface' (battistrada), 'inner' (strato interno), 'carcass' (carcassa).
    Ritorna (vals, grads) con 4 elementi:
      vals[i]  = valore singolo per gomma (per numero e colore cella minicar)
      grads[i] = lista 3 punti [sx, centro, dx] (per gradiente car base)
    Fallback a carcassa se lo strato scelto non è disponibile.
    """
    surf = d.get("tyre_surf")      # 4 x [sx,c,dx] o None
    inner = d.get("tyre_inner")    # 4 x [sx,c,dx] o None
    carc = d.get("tyre_carcass")   # 4 o None
    vals = [None, None, None, None]
    grads = [None, None, None, None]
    src = inner if layer == "inner" else (surf if layer == "surface" else None)
    for i in range(4):
        if src is not None and isinstance(src, list) and i < len(src) and src[i]:
            pts = src[i]
            grads[i] = list(pts)
            vals[i] = sum(pts) / len(pts)
        elif isinstance(carc, list) and i < len(carc):
            v = carc[i]
            vals[i] = v
            grads[i] = [v, v, v]
    return vals, grads
