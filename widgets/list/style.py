"""widgets/list/style.py — Carica e scala il QSS della lista dati."""
import re
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
QSS_FILE = _ROOT / "settings" / "style_list.qss"

_SCALABLE_PROPS = "font-size|margin|padding|border-radius|max-height|min-height|max-width|min-width|letter-spacing"
_DECL_RE = re.compile(rf"\b({_SCALABLE_PROPS})\s*:\s*([^;}}/]*\d+px[^;}}/]*)", re.IGNORECASE)
_PX_RE = re.compile(r"(\d+)px")


def _scale_qss(qss: str, scale: float) -> str:
    if abs(scale - 1.0) < 1e-6:
        return qss

    def repl_decl(m):
        prop, value = m.group(1), m.group(2)
        scaled = _PX_RE.sub(lambda p: f"{max(1, round(int(p.group(1)) * scale))}px", value)
        return f"{prop}: {scaled}"

    return _DECL_RE.sub(repl_decl, qss)


def _apply_bg_opacity(qss: str, opacity_pct) -> str:
    if opacity_pct is None:
        return qss
    alpha = max(0.0, min(1.0, opacity_pct / 100.0))

    def repl(m):
        return f"#container {{{m.group(1)}background: rgba({m.group(2)},{alpha:.3f});{m.group(3)}}}"

    pattern = re.compile(r"#container\s*\{([^}]*?)background:\s*rgba\(([\d,\s]+?),\s*[\d.]+\);([^}]*)\}")
    new, n = pattern.subn(repl, qss)
    return new if n else qss


def load_qss(cfg) -> str:
    try:
        qss = QSS_FILE.read_text(encoding="utf-8")
    except Exception:
        return ""
    qss = _scale_qss(qss, cfg.scale)
    qss = _apply_bg_opacity(qss, cfg.get("bg_opacity", None))
    return qss
