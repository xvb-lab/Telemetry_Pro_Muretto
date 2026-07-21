"""ui/icons.py — fonte unica della grafica a icone (SVG). Tutti i simboli
dell'app si generano qui, così sono SEMPRE identici e allineati ovunque.

Verificato il rendering in Qt (QSvgRenderer): la centratura verticale del testo
NON usa dominant-baseline (Qt lo ignora) ma una baseline fissa y=16.4 sul
viewBox 24x24 con font-size 12 — testato e centrato per S/M/H/W.
"""

TYRE_COLORS = {
    "S": "#ffffff",   # soft   - bianco
    "M": "#ffe24d",   # medium - giallo
    "H": "#ff3b30",   # hard   - rosso
    "W": "#4aa3ff",   # wet    - azzurro
}
_EMPTY = "#555c66"

# gomma NON ANCORA VALUTABILE: il cervello non ha dati (ne' appresi ne' dal
# REST) per stimare mescola/degrado. Meglio un "?" onesto che una stima finta.
TYRE_UNKNOWN_SVG = (
    "<svg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'>"
    "<circle cx='12' cy='12' r='10.2' fill='none' stroke='#8a8f9b' "
    "stroke-width='1.9' stroke-dasharray='2.4 2'/>"
    "<text x='12' y='16.6' text-anchor='middle' font-family='sans-serif' "
    "font-weight='700' font-size='13' fill='#8a8f9b'>?</text></svg>")


# bandierina a scacchi (sostituisce la "L" dei giri) — bianca
FLAG_SVG = (
    "<svg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'>"
    "<rect x='3.6' y='3' width='1.6' height='18' fill='#ffffff'/>"
    "<g fill='#ffffff'>"
    "<rect x='6.4' y='4.2' width='3.6' height='3.6'/>"
    "<rect x='13.6' y='4.2' width='3.6' height='3.6'/>"
    "<rect x='10' y='7.8' width='3.6' height='3.6'/>"
    "<rect x='17.2' y='7.8' width='3.2' height='3.6'/>"
    "<rect x='6.4' y='11.4' width='3.6' height='3.6'/>"
    "<rect x='13.6' y='11.4' width='3.6' height='3.6'/>"
    "</g>"
    "<g fill='#ffffff' opacity='0.32'>"
    "<rect x='10' y='4.2' width='3.6' height='3.6'/>"
    "<rect x='17.2' y='4.2' width='3.2' height='3.6'/>"
    "<rect x='6.4' y='7.8' width='3.6' height='3.6'/>"
    "<rect x='13.6' y='7.8' width='3.6' height='3.6'/>"
    "<rect x='10' y='11.4' width='3.6' height='3.6'/>"
    "<rect x='17.2' y='11.4' width='3.2' height='3.6'/>"
    "</g></svg>")


def softest_color(four):
    """Colore della mescola PIU' MORBIDA tra le quattro (S>M>H, W a parte).
    Es. 2 hard + 2 medium -> giallo del medium."""
    order = ["S", "M", "H", "W"]
    best = None
    for c in (four or []):
        c = (str(c or "").strip().upper()[:1])
        if c in order and (best is None or order.index(c) < order.index(best)):
            best = c
    return TYRE_COLORS.get(best, _EMPTY)


def tyre_chip_svg(sigla, is_new=True):
    """Cerchio mescola con lettera centrata. Bordo pieno=nuova, tratteggiato=usata."""
    s = (sigla or "").strip()
    if not s:
        return ""
    col = TYRE_COLORS.get(s, _EMPTY)
    dash = "" if is_new else " stroke-dasharray='2.4 2'"
    return (
        "<svg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'>"
        f"<circle cx='12' cy='12' r='10.2' fill='none' stroke='{col}' "
        f"stroke-width='1.9'{dash}/>"
        f"<text x='12' y='16.4' text-anchor='middle' font-family='sans-serif' "
        f"font-weight='700' font-size='12' fill='{col}'>{s}</text>"
        "</svg>")


def tyre_mix_svg(four, new4=None):
    """4 dot 2x2 (FL FR / RL RR). Dot pieno=gomma nuova, vuoto (contorno)=usata."""
    if not (isinstance(four, (list, tuple)) and len(four) == 4):
        return ""
    if not (isinstance(new4, (list, tuple)) and len(new4) == 4):
        new4 = [True, True, True, True]
    pos = [(7.2, 7.2), (16.8, 7.2), (7.2, 16.8), (16.8, 16.8)]
    d = []
    for i, (cx, cy) in enumerate(pos):
        col = TYRE_COLORS.get(four[i], _EMPTY)
        if new4[i]:
            d.append(f"<circle cx='{cx}' cy='{cy}' r='3.7' fill='{col}'/>")
        else:
            d.append(f"<circle cx='{cx}' cy='{cy}' r='3.4' fill='none' "
                     f"stroke='{col}' stroke-width='1.4'/>")
    return ("<svg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'>"
            + "".join(d) + "</svg>")


# goccia peso benzina (viola) — già SVG, ora vive qui con gli altri simboli
# GITHUB mark (bianco) per la pill del footer
GITHUB_MARK_SVG = (
    "<svg viewBox='0 0 16 16' xmlns='http://www.w3.org/2000/svg'>"
    "<path fill='#ffffff' d='M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 "
    "7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94"
    "-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82"
    ".72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95"
    " 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18"
    " 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 "
    "1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73"
    ".54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8"
    "c0-4.42-3.58-8-8-8Z'/></svg>")


# GLOBO (bianco) per la pill Docs
GLOBE_SVG = (
    "<svg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg' fill='none' "
    "stroke='#ffffff' stroke-width='1.7'>"
    "<circle cx='12' cy='12' r='9'/>"
    "<path d='M3 12h18'/>"
    "<path d='M12 3c2.7 2.6 4 5.7 4 9s-1.3 6.4-4 9c-2.7-2.6-4-5.7-4-9s1.3-6.4 4-9Z'/>"
    "</svg>")


# CUORE "Support": oro -> giallo in fade (gradiente verticale)
HEART_GOLD_SVG = (
    "<svg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'>"
    "<defs><linearGradient id='hg' x1='0' y1='0' x2='0' y2='1'>"
    "<stop offset='0' stop-color='#f5c542'/>"
    "<stop offset='1' stop-color='#ffe98a'/></linearGradient></defs>"
    "<path fill='url(#hg)' d='M12 21 C6.4 16.6 2.8 13.2 2.8 9.4 "
    "A4.9 4.9 0 0 1 7.7 4.5 C9.4 4.5 11 5.4 12 6.9 "
    "C13 5.4 14.6 4.5 16.3 4.5 A4.9 4.9 0 0 1 21.2 9.4 "
    "C21.2 13.2 17.6 16.6 12 21 Z'/></svg>")


FUEL_WEIGHT_SVG = (
    "<svg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'>"
    "<circle cx='12' cy='12' r='10.2' fill='none' stroke='#9d6bff' stroke-width='1.9'/>"
    "<path fill='#9d6bff' d='M12 6.6 C9.4 9.7 8.3 11.5 8.3 13.3 "
    "a3.7 3.7 0 0 0 7.4 0 C15.7 11.5 14.6 9.7 12 6.6 Z'/></svg>")


# ── CASCO LIVREA (assets/helmet.svg) ricolorabile ────────────────────
# L'SVG originale ha la livrea BLU (#4991db e famiglia): qui si sostituisce
# la famiglia blu col colore scelto (+ tono chiaro e scuro derivati).
from pathlib import Path as _Path

_HELMET_FILE = _Path(__file__).resolve().parent.parent / "assets" / "helmet.svg"
_HELMET_CACHE = {}

# 20 combinazioni (nome, colore primario)
HELMET_COLORS = [
    ("LMU Red", "#ff1d43"), ("Racing Blue", "#1d6bff"),
    ("Sun Yellow", "#ffd21d"), ("Petrol Green", "#26c95d"),
    ("Papaya", "#ff7a1d"), ("Violet", "#8a3ce8"),
    ("Cyan", "#17c3d8"), ("Rose", "#ff4fd0"),
    ("White", "#e8eaee"), ("Carbon", "#23262d"),
    ("Gold", "#d8a521"), ("Lime", "#a4e022"),
    ("Teal", "#1d9e8f"), ("Navy", "#1a2f7a"),
    ("Bronze", "#8a5a2b"), ("Silver", "#b8bec8"),
    ("Magenta", "#d40fa2"), ("Sky", "#6fc1ff"),
    ("Army", "#6b7a3a"), ("Bordeaux", "#7a1024"),
]


def _mix(hexc, other, f):
    a = int(hexc.lstrip("#"), 16); b = int(other.lstrip("#"), 16)
    out = 0
    for sh in (16, 8, 0):
        ca = (a >> sh) & 255; cb = (b >> sh) & 255
        out |= int(ca + (cb - ca) * f) << sh
    return "#%06x" % out


def helmet_svg_bytes(color):
    """assets/helmet.svg ricolorato (bytes pronti per _SvgBox/QSvgRenderer)."""
    b = _HELMET_CACHE.get(color)
    if b is not None:
        return b
    try:
        txt = _HELMET_FILE.read_text(encoding="utf-8")
    except Exception:
        return b""
    light = _mix(color, "#ffffff", 0.45)
    dark = _mix(color, "#000000", 0.30)
    # PRIMARIO = la famiglia ROSSA della livrea originale (dominante);
    # i blu (accenti) seguono col tono scuro, i celesti col chiaro.
    for old, new in (("#fd160e", color), ("#ef1515", color),
                     ("#fc6d5d", light), ("#b70000", dark),
                     ("#4991db", dark), ("#498bae", dark),
                     ("#4471d8", dark), ("#3d83e3", dark),
                     ("#51aacc", dark), ("#4fa5c1", dark),
                     ("#a9dff9", light), ("#c3d3dd", light),
                     ("#cbdbe5", light), ("#5a829c", dark),
                     ("#42515b", dark)):
        txt = txt.replace(old, new)
    b = txt.encode("utf-8")
    _HELMET_CACHE[color] = b
    return b


# CASCHI IN FILA stile LMU (card sessioni team): casco davanti con
# visiera scura + due sagome-eco dietro (la fila di piloti del team).
HELMET_SVG = (
    "<svg viewBox='0 0 28 24' xmlns='http://www.w3.org/2000/svg'>"
    "<path fill='none' stroke='#5f646e' stroke-width='1.7' "
    "stroke-linecap='round' d='M20.4 5.6 C23.6 7.0 25.4 9.4 25.4 12.0 "
    "C25.4 14.6 23.9 16.9 21.2 17.9'/>"
    "<path fill='none' stroke='#8b909a' stroke-width='1.7' "
    "stroke-linecap='round' d='M17.2 4.9 C20.8 6.2 22.8 8.8 22.8 11.9 "
    "C22.8 15.0 21.0 17.7 17.8 18.8'/>"
    "<path fill='#e8eaee' d='M11.5 3.6 C6.4 3.6 2.6 7.5 2.6 12.4 "
    "L2.6 16.6 C2.6 18.2 3.9 19.4 5.5 19.4 L14.5 19.4 "
    "C18.9 19.4 21.4 16.6 21.4 11.9 C21.4 7.1 17 3.6 11.5 3.6 Z'/>"
    "<path fill='#131820' d='M4.6 10.4 L11.2 10.4 "
    "C11.9 10.4 12.4 10.9 12.4 11.6 L12.4 14.4 "
    "C12.4 15.1 11.9 15.6 11.2 15.6 L5.6 15.6 "
    "C4.6 15.6 4.1 14.9 4.2 13.9 C4.25 12.7 4.35 11.5 4.6 10.4 Z'/>"
    "</svg>")


# CHIAVE INGLESE: sosta ai box (verde). Testa a bocca aperta classica
# (stile Material "build"), diagonale — leggibile anche piccola. Verde
# #37d67a = lo stesso verde "tutto ok" di best personale e temperature ok.
WRENCH_SVG = (
    "<svg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'>"
    "<path fill='#37d67a' d='M22.7 19l-9.1-9.1c.9-2.3.4-5-1.5-6.9"
    "-2-2-5-2.4-7.4-1.3L9 6 6 9 1.6 4.7C.4 7.1.9 10.1 2.9 12.1"
    "c1.9 1.9 4.6 2.4 6.9 1.5l9.1 9.1c.4.4 1 .4 1.4 0l2.3-2.3"
    "c.5-.4.5-1.1.1-1.4z'/></svg>")


# ── temperature motore ──
# ACQUA / liquido di raffreddamento: tre onde (azzurro).
WATER_SVG = (
    "<svg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'>"
    "<g fill='none' stroke='#45b4ef' stroke-width='1.9' "
    "stroke-linecap='round'>"
    "<path d='M3 7 q3 -3 6 0 t6 0 t6 0'/>"
    "<path d='M3 12 q3 -3 6 0 t6 0 t6 0'/>"
    "<path d='M3 17 q3 -3 6 0 t6 0 t6 0'/>"
    "</g></svg>")

# OLIO motore: latta con beccuccio e goccia (ambra), come il simbolo cruscotto.
OIL_SVG = (
    "<svg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'>"
    "<path fill='#e3b341' d='M2.5 11.5 h8.6 c1.5 0 2.8 -1 3.2 -2.4 "
    "l0.3 -1.1 l6.4 -2.1 v2.1 l-5.2 1.7 c-.1 2.7 -2 4.3 -4.4 4.3 "
    "H6 c-1.9 0 -3.5 -1.6 -3.5 -3.5 z'/>"
    "<path fill='#e3b341' d='M20 12 c-1.2 1.6 -1.8 2.6 -1.8 3.4 "
    "a1.8 1.8 0 0 0 3.6 0 c0 -.8 -.6 -1.8 -1.8 -3.4 z'/>"
    "</svg>")


def energy_bolt_svg(color="#50a0eb"):
    """Cerchio + fulmine (energia elettrica). Il colore segue lo stato e-motor
    come il SoC batteria dell'HUD: verde=regen, fucsia=boost, blu=neutro.
    Bordo spesso (stroke 2.6): rimpicciolito a ~15px resta come i cerchi gomma."""
    return (
        "<svg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'>"
        f"<circle cx='12' cy='12' r='10.0' fill='none' stroke='{color}' "
        "stroke-width='2.6'/>"
        f"<path fill='{color}' d='M13.4 3.6 L6.5 13.2 h4.3 l-1.6 7.2 "
        "L17.5 10.4 h-4.4 z'/>"
        "</svg>")
