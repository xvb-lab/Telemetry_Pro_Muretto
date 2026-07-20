"""
core/utils.py — Helper condivisi da tutti gli overlay.

Deduplica le funzioni che prima erano copiate in ogni widget:
formattazione tempi/gap, caricamento font, caricamento loghi con cache.
"""
from pathlib import Path

from PySide6.QtGui import QFontDatabase, QPixmap, QPainter
from PySide6.QtCore import Qt, QRectF

_CORE_DIR = Path(__file__).parent
_ROOT_DIR = _CORE_DIR.parent
FONT_DIR = _ROOT_DIR / "fonts"
LOGO_DIR = _ROOT_DIR / "brandlogo"


# ── FONT ──────────────────────────────────────────────────────────────
_fonts_loaded = False

def overlays_locked():
    """True se l'utente ha BLOCCATO gli overlay (niente drag).
    Legge il flag fresco dal config utente: vale subito anche nei
    processi overlay separati (costo: una lettura per click)."""
    try:
        import json
        from core.paths import USER_DIR
        d = json.loads((USER_DIR / "config.json")
                       .read_text(encoding="utf-8"))
        return bool(d.get("overlay", {}).get("lock", False))
    except Exception:
        return False


def load_custom_fonts():
    """Registra tutti i .ttf/.otf in fonts/. Idempotente."""
    global _fonts_loaded
    if _fonts_loaded:
        return
    if FONT_DIR.exists():
        for f in FONT_DIR.glob("*.[ot]tf"):
            QFontDatabase.addApplicationFont(str(f))
    _fonts_loaded = True


# ── FORMATTAZIONE TEMPI ───────────────────────────────────────────────
def fmt_time(s) -> str:
    """Secondi -> 'M:SS.mmm'. '--:--.---' se non valido."""
    if not s or s <= 0:
        return "--:--.---"
    m = int(s) // 60
    return f"{m}:{s - m * 60:06.3f}"


def fmt_session_remaining(secs: float) -> str:
    """Secondi -> 'H:MM:SS' o 'M:SS'. '--:--' se <= 0."""
    if secs <= 0:
        return "--:--"
    h = int(secs) // 3600
    m = (int(secs) % 3600) // 60
    s = int(secs) % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def fmt_gap(gap, place_class, laps_behind=0) -> str:
    """Gap dal leader di classe -> 'LEADER' / '+N LAP' / '+S.s' / '--'."""
    if place_class == 1:
        return "LEADER"
    if laps_behind > 0:
        return f"+{laps_behind} LAP"
    if gap <= 0:
        return "--"
    return f"+{gap:.1f}"


# ── LOGHI (cache condivisa) ───────────────────────────────────────────
_logo_path_cache: dict = {}   # brand -> Path | None


def find_logo_path(brand: str):
    """Trova il file SVG del brand in brandlogo/. Cache. None se assente."""
    if not brand:
        return None
    if brand in _logo_path_cache:
        return _logo_path_cache[brand]
    result = None
    if LOGO_DIR.exists():
        for ext in (".svg", ".SVG"):
            for name in (f"{brand}{ext}", f"{brand.lower()}{ext}"):
                p = LOGO_DIR / name
                if p.exists():
                    result = p
                    break
            if result:
                break
    _logo_path_cache[brand] = result
    return result
