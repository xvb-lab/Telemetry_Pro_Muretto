"""
widgets/relative/style.py — Carica e scala il QSS del relative.

Stesso meccanismo dello standings: legge settings/style_relative.qss e
scala i px delle proprietà tipografiche/spaziatura secondo cfg.scale.
"""
import re
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
QSS_FILE = _ROOT / "settings" / "style_relative.qss"

_SCALABLE_PROPS = "font-size|margin|margin-top|margin-bottom|margin-left|margin-right|padding|padding-top|padding-bottom|padding-left|padding-right|border-radius|max-height|min-height|letter-spacing"
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
    new_qss, n = pattern.subn(repl, qss)
    return new_qss if n else qss


def _qss_path(cfg):
    theme = (cfg.get("theme", "wec") or "wec").lower()
    if theme == "gtwc":
        theme = "imsa"                 # tema rinominato: le config vecchie seguono
    if theme and theme != "wec":
        cand = _ROOT / "settings" / f"style_relative_{theme}.qss"
        if cand.exists():
            return cand
    return QSS_FILE


def load_qss(cfg) -> str:
    try:
        qss = _qss_path(cfg).read_text(encoding="utf-8")
    except Exception:
        return ""
    qss = _scale_qss(qss, cfg.scale)
    qss = _apply_bg_opacity(qss, cfg.get("bg_opacity", None))
    return qss
