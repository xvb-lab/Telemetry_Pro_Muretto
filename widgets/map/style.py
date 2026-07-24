"""widgets/map/style.py — carica, scala e applica bg_opacity allo stile della Map."""
import re
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
QSS_FILE = _ROOT / "settings" / "style_map.qss"

_SCALABLE = "font-size|margin|padding|border-radius|max-height|min-height|letter-spacing"
_DECL_RE = re.compile(rf"\b({_SCALABLE})\s*:\s*([^;}}/]*\d+px[^;}}/]*)", re.IGNORECASE)
_PX_RE = re.compile(r"(\d+)px")


def _scale_qss(qss, scale):
    if abs(scale - 1.0) < 1e-6:
        return qss
    def repl(m):
        prop, value = m.group(1), m.group(2)
        scaled = _PX_RE.sub(lambda p: f"{max(1, round(int(p.group(1)) * scale))}px", value)
        return f"{prop}: {scaled}"
    return _DECL_RE.sub(repl, qss)


def _apply_bg_opacity(qss, sel, opacity_pct):
    if opacity_pct is None:
        return qss
    alpha = max(0.0, min(1.0, opacity_pct / 100.0))
    pat = re.compile(rf"({re.escape(sel)})\s*\{{([^}}]*?)background:\s*rgba\(([\d,\s]+?),\s*[\d.]+\);([^}}]*)\}}")
    def repl(m):
        return f"{m.group(1)} {{{m.group(2)}background: rgba({m.group(3)},{alpha:.3f});{m.group(4)}}}"
    new, n = pat.subn(repl, qss)
    return new if n else qss


def load_qss(cfg):
    try:
        qss = QSS_FILE.read_text(encoding="utf-8")
    except Exception:
        return ""
    qss = _scale_qss(qss, cfg.scale)
    # background TRASPARENTE di default (rich. 24/07): la mappa galleggia
    qss = _apply_bg_opacity(qss, "#container", cfg.get("bg_opacity", 0))
    return qss
