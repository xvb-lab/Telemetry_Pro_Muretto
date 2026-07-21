"""
widgets/standings/style.py — Carica il QSS grafico dell'utente e lo scala.

La grafica vive in settings/style_standings.qss (file modificabile liberamente,
con gradienti, bandiere gialle, badge ecc.). Qui NON si reinventa lo stile:
si legge quel file e si moltiplicano i valori in px delle proprieta tipografiche
e di spaziatura (font-size, margin, padding, border-radius, max/min-height) per
lo scale del config, cosi premendo +/- tutta la grafica cresce in proporzione.
I gradienti rgba e i loro stop NON vengono toccati.
"""
import re
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
QSS_FILE = _ROOT / "settings" / "style_standings.qss"

# proprieta i cui valori in px vanno scalati
_SCALABLE_PROPS = "font-size|margin|margin-top|margin-bottom|margin-left|margin-right|padding|padding-top|padding-bottom|padding-left|padding-right|border-radius|max-height|min-height|letter-spacing"

# cattura "prop: valore" dove valore contiene px, fermandosi a ; } o commento.
# Cosi scala anche dichiarazioni inline multiple sulla stessa riga.
_DECL_RE = re.compile(
    rf"\b({_SCALABLE_PROPS})\s*:\s*([^;}}/]*\d+px[^;}}/]*)",
    re.IGNORECASE,
)
_PX_RE = re.compile(r"(\d+)px")


def _scale_qss(qss: str, scale: float) -> str:
    if abs(scale - 1.0) < 1e-6:
        return qss

    def repl_decl(m):
        prop, value = m.group(1), m.group(2)
        scaled_value = _PX_RE.sub(lambda p: f"{max(1, round(int(p.group(1)) * scale))}px", value)
        return f"{prop}: {scaled_value}"

    return _DECL_RE.sub(repl_decl, qss)


def _apply_bg_opacity(qss: str, opacity_pct) -> str:
    """Sostituisce l'alpha dello sfondo #container con bg_opacity (0-100)."""
    if opacity_pct is None:
        return qss
    alpha = max(0.0, min(1.0, opacity_pct / 100.0))

    def repl(m):
        # m.group(1) = blocco prima del background, m.group(2) = resto
        return f"#container {{{m.group(1)}background: rgba({m.group(2)},{alpha:.3f});{m.group(3)}}}"

    # sostituisce l'intero blocco #container preservando border-radius ecc.
    pattern = re.compile(r"#container\s*\{([^}]*?)background:\s*rgba\(([\d,\s]+?),\s*[\d.]+\);([^}]*)\}")
    new_qss, n = pattern.subn(repl, qss)
    return new_qss if n else qss


def _qss_path(cfg):
    """Sceglie il file QSS in base al tema (cfg['theme']).
    'wec' (default) usa style_standings.qss; gli altri usano
    style_standings_<theme>.qss se esiste, con fallback al base."""
    theme = (cfg.get("theme", "wec") or "wec").lower()
    if theme == "gtwc":
        theme = "imsa"                 # tema rinominato: le config vecchie seguono
    if theme and theme != "wec":
        cand = _ROOT / "settings" / f"style_standings_{theme}.qss"
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
