"""
core/wec_style.py — LIBRERIA STILE WEC 2026 (style guide UFFICIALE).

Dal reveal FIA WEC "Brand New TV Graphics": per ogni squadra colore
base, GRADIENTE a 3 stop e TEXT HIGHLIGHT ufficiali; background fisso
0A0032. I brand non in guida sono adattati nello stesso spirito.
Usata da card onboard/battle 2026 e classifiche Community.
"""
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def card_logo_path(brand):
    """Logo PER LE CARD: prima cardlogo/ (versioni dedicate), poi
    brandlogo/ come ripiego. Gli altri widget NON vengono toccati."""
    if not brand:
        return None
    p = os.path.join(_ROOT, "cardlogo", "%s.svg" % brand)
    if os.path.exists(p):
        return p
    try:
        from core.utils import find_logo_path
        lp = find_logo_path(brand)
        return str(lp) if lp else None
    except Exception:
        return None

BG = "#0A0032"                       # background ufficiale
ROW_BG = "#312C54"                   # navy pannello: colonne dati
                                     # dopo il nome (standings/relative)

# brand: (base, (grad_hi, grad_mid, grad_lo), text_highlight)
BRANDS = {
    "Ferrari":       ("#7A0F14", ("#A0161C", "#7A0F14", "#4A0A0E"), "#FF8A8A"),
    "Porsche":       ("#FFFFFF", ("#E6EAF2", "#FFFFFF", "#5E658F"), "#FFFFFF"),
    "Toyota":        ("#000000", ("#1B1E24", "#000000", "#141830"), "#FFFFFF"),
    "Cadillac":      ("#F3C846", ("#FACE37", "#F3C846", "#D9A300"), "#FFE780"),
    "Alpine":        ("#035AB9", ("#0A6FD6", "#035AB9", "#02386F"), "#88BEFF"),
    "Aston Martin":  ("#00665E", ("#007364", "#00665E", "#0D4D49"), "#75CCBE"),
    "Peugeot":       ("#BFDD0B", ("#D1F71E", "#BFDD0B", "#769400"), "#C4FF5C"),
    "McLaren":       ("#FF8000", ("#FFA908", "#FF8000", "#D15000"), "#F4874A"),
    # adattati (non in guida) nello stesso linguaggio
    "BMW":           ("#16337E", ("#1E43A0", "#16337E", "#0A1E50"), "#7FA8FF"),
    "Genesis":       ("#3C4046", ("#4A4F56", "#3C4046", "#2A2D32"), "#C88A5A"),
    "Lexus":         ("#EDEDE9", ("#F7F7F4", "#EDEDE9", "#D8D8D2"), "#8A8A84"),
    "Ford":          ("#0E1D5B", ("#16307E", "#0E1D5B", "#081238"), "#7FA8FF"),
    "Corvette":      ("#5A5F66", ("#787E88", "#5A5F66", "#3A3E44"), "#FFD24A"),
    "Mercedes-AMG":  ("#0C0C0E", ("#1E1E22", "#0C0C0E", "#060608"), "#7FD4D4"),
    "Lamborghini":   ("#0F4A2E", ("#166B42", "#0F4A2E", "#082A1A"), "#7FE0A8"),
    "Isotta Fraschini": ("#7A0F14", ("#A0161C", "#7A0F14", "#4A0A0E"), "#FF8A8A"),
    "Glickenhaus":   ("#BFDAEF", ("#D5E8F7", "#BFDAEF", "#97BCDC"), "#2E5E8E"),
    "Vanwall":       ("#003C49", ("#0A5461", "#003C49", "#00262E"), "#7FE0E0"),
    "Oreca":         ("#131316", ("#26262A", "#131316", "#0E1013"), "#FF8A3C"),
    "Ligier":        ("#1F6FB5", ("#2A8CD9", "#1F6FB5", "#12466F"), "#88BEFF"),
    "Duqueine":      ("#0E0E10", ("#1C1C20", "#0E0E10", "#060608"), "#32CD32"),
    "Ginetta":       ("#411C52", ("#5A2A73", "#411C52", "#2A1136"), "#B98FE0"),
    "Adess":         ("#411C52", ("#5A2A73", "#411C52", "#2A1136"), "#FFFFFF"),
}

BRAND_COLORS = {k: v[0] for k, v in BRANDS.items()}

# proporzione VISIVA del logo nel box (1.0 = neutra): i marchi "tight"
# senza aria interna vanno ridotti, quelli con padding compensati
LOGO_SCALE = {"Cadillac": 1.05, "Alpine": 0.60, "Ferrari": 0.85,
              "Porsche": 0.85, "BMW": 0.78, "Toyota": 0.95,
              "Genesis": 1.15, "Mercedes-AMG": 0.88, "Lexus": 0.82,
              "Aston Martin": 1.05, "Peugeot": 0.80, "McLaren": 0.95,
              "Ford": 0.62, "Corvette": 0.92, "Lamborghini": 0.80,
              "Isotta Fraschini": 0.90, "Glickenhaus": 0.90,
              "Vanwall": 0.90, "Oreca": 0.85, "Ligier": 0.90,
              "Duqueine": 0.90, "Ginetta": 0.68, "Adess": 0.90}

CLASS_CHIP = {"HY": ("HYPERCAR", "#C3122A"), "GT3": ("LMGT3", "#169149"),
              "P2": ("LMP2", "#2A6BB5"), "P3": ("LMP3", "#9038D6"),
              "GTE": ("LMGTE", "#168749")}

_NORM = {re.sub(r"[^a-z]", "", k.lower()): k for k in BRANDS}


def brand_color(brand):
    return BRAND_COLORS.get(brand)


def brand_gradient(brand):
    """(hi, mid, lo) ufficiale, o None."""
    v = BRANDS.get(brand)
    return v[1] if v else None


def brand_accent(brand):
    """Colore ACCENTO del brand (text_highlight): la coda destra
    della fascia riga sfuma verso questo (Oreca -> arancione)."""
    v = BRANDS.get(brand)
    return v[2] if v else ""


# override SOLO per le FASCE RIGA (standings/relative): le card
# restano coi colori ufficiali del reveal.
# brand: ((grad_hi, grad_mid, grad_lo), accento_coda)
ROW_BRANDS = {
    "Toyota": (("#8A1428", "#64101F", "#64101F"), "#EDE2E2"),
}


# STRISCE OBLIQUE nell'angolo destro della fascia riga: 2-3 colori
# per team, dettati via via. brand: [colori da sinistra a destra]
ROW_STRIPES = {}


def row_stripes(brand):
    return ROW_STRIPES.get(brand, [])


def row_color(brand):
    """Colore base con override riga/classifiche (Toyota bordeaux)."""
    v = ROW_BRANDS.get(brand)
    return v[0][1] if v else brand_color(brand)


def row_gradient(brand):
    v = ROW_BRANDS.get(brand)
    return v[0] if v else brand_gradient(brand)


def row_accent(brand):
    v = ROW_BRANDS.get(brand)
    return v[1] if v else brand_accent(brand)


# ANGOLI a fine colore: SOLO i team scelti a mano.
# 1 colore = cuneo pieno; 2+ colori = strisce oblique affiancate
# (Alpine: bianco+rosso francese sul blu).
ROW_CORNERS = {"Ginetta": ["#F97C1D"],
               "Adess": ["#C6242A"], "Ligier": ["#F5D400"],
               "Oreca": ["#FF8A3C"],
               "Alpine": ["#FFFFFF", "#E1122C"],
               "Toyota": ["#FFFFFF", "#000000"],
               "Isotta Fraschini": ["#FFFFFF", "#1B4DB0"],
               "Lamborghini": ["#FFFFFF", "#E1122C", "#000000"],
               "Lexus": ["#E1122C", "#000000"],
               "Genesis": ["#F97C1D", "#FFFFFF"],
               "Vanwall": ["#F5D400", "#FFFFFF"]}


def row_corner(brand):
    return ROW_CORNERS.get(brand, [])


# ── TAGLIE LOGO NORMALIZZATE (quadrati=BMW, rettangolari=Cadillac) ──
# ritocchi per marchio SEPARATI per superficie: la MFD card e
# l'Onboard hanno i loro dizionari (dy in unita': 1.0 = altezza
# dei loghi quadrati)
LOGO_TWEAK = {
    "mfd": ({"Alpine": 0.62, "Genesis": 1.35, "Ginetta": 0.72,
             "Lexus": 0.88, "Corvette": 0.80, "Ford": 0.80,
             "Cadillac": 0.84},
            {"Lexus": -0.125, "McLaren": -0.125, "Ford": -0.125}),
    "onboard": ({"Alpine": 0.87, "Genesis": 1.12, "Ginetta": 0.72,
                 "Lexus": 0.88, "Corvette": 0.92, "Ford": 0.92},
                {"Lexus": -0.125, "McLaren": -0.125}),
}
# avanzamento orizzontale: quota della larghezza logo che "conta"
# (svg con aria a DESTRA dentro il viewBox, es. Genesis)
LOGO_TWEAK_ADV = {"Genesis": 0.90}
# spostamento ORIZZONTALE del logo (in unita': aria a sinistra
# dentro lo svg -> valore negativo lo tira verso il bordo)
LOGO_TWEAK_DX = {"Genesis": -0.12}


def logo_box(brand, ar, unit, rect_w=None, surface="mfd"):
    """(w, h, dy_px, adv_px) per un logo di aspect ar (h/w).
    unit = altezza dei QUADRATI; i rettangolari vanno a larghezza
    fissa rect_w (default 1.9*unit, taglia Cadillac).
    surface: 'mfd' o 'onboard' (ritocchi separati).
    adv_px = di quanto avanzare DOPO il logo (scavalca l'aria a
    destra interna ad alcuni svg)."""
    if rect_w is None:
        rect_w = 1.9 * unit
    if ar >= 0.72:
        h = unit
        w = h / ar
    else:
        w = rect_w
        h = w * ar
        if h > unit:
            h = unit
            w = h / ar
    ks, dys = LOGO_TWEAK.get(surface, LOGO_TWEAK["mfd"])
    k = ks.get(brand, 1.0)
    w *= k
    h *= k
    return (w, h, dys.get(brand, 0.0) * unit,
            w * LOGO_TWEAK_ADV.get(brand, 1.0),
            LOGO_TWEAK_DX.get(brand, 0.0) * unit)


def brand_highlight(brand):
    v = BRANDS.get(brand)
    return v[2] if v else "#FFFFFF"


def is_light(hexcol):
    """True se il colore e' chiaro: sopra ci va testo SCURO (0A0032)."""
    try:
        h = hexcol.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return (0.299 * r + 0.587 * g + 0.114 * b) > 150
    except Exception:
        return False


def text_on(brand_or_hex):
    """Colore testo giusto sopra la tinta brand (bianco o navy)."""
    col = BRAND_COLORS.get(brand_or_hex, brand_or_hex)
    return BG if is_light(col or "") else "#FFFFFF"


def brand_from_text(text):
    """Nome brand ('Peugeot') cercandolo DENTRO un testo libero."""
    blob = re.sub(r"[^a-z]", "", (text or "").lower())
    for k, name in _NORM.items():
        if k in blob:
            return name
    return None


def brand_color_from_text(text):
    """Colore base cercando il brand DENTRO un testo libero."""
    blob = re.sub(r"[^a-z]", "", (text or "").lower())
    for k, name in _NORM.items():
        if k in blob:
            return BRAND_COLORS[name]
    return None
