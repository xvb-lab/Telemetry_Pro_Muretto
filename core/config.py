"""
core/config.py — Configurazione centralizzata di tutti gli overlay.

Una sola fonte di verità: settings/config.json.
Ogni widget ha una sezione. I valori "base" (dimensioni a scale=1.0) vengono
moltiplicati per `scale` al volo, così il widget chiede `cfg.row_height` e
riceve già il valore scalato. Cambiare `scale` (stepper +/-) ridimensiona
font, righe e colonne mantenendo le proporzioni.

Caricato UNA volta sola e condiviso fra tutti i widget (risparmio RAM/CPU).
"""
import json
import threading
from pathlib import Path

from core.paths import CONFIG_FILE, DEFAULT_CONFIG, POSITIONS_FILE


# Cartella settings accanto a questo package (../settings dalla root progetto)
_CORE_DIR = Path(__file__).parent
_ROOT_DIR = _CORE_DIR.parent


def _deep_merge(base: dict, over: dict) -> dict:
    """Unisce `over` (utente) sopra `base` (default). I dict si fondono in
    profondità; gli altri valori (liste, scalari) vengono sostituiti."""
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class WidgetConfig:
    """Vista su una sezione del config con scaling applicato.

    - I valori dentro `base` vengono restituiti × scale (arrotondati a int).
    - Tutto il resto (colori, flag, liste) è restituito così com'è.
    """

    def __init__(self, section: dict):
        self._d = section

    # ── accesso grezzo ────────────────────────────────────────────────
    @property
    def raw(self) -> dict:
        return self._d

    @property
    def scale(self) -> float:
        return float(self._d.get("scale", 1.0))

    def get(self, key, default=None):
        return self._d.get(key, default)

    # ── valori scalati (da `base`) ────────────────────────────────────
    def scaled(self, key: str, default: int = 0) -> int:
        """Valore base × scale, arrotondato a int (minimo 0)."""
        base = self._d.get("base", {}).get(key, default)
        return max(0, round(base * self.scale))

    def base(self, key: str, default: int = 0) -> int:
        """Valore base senza scaling."""
        return self._d.get("base", {}).get(key, default)

    # ── colori e nested ───────────────────────────────────────────────
    def color(self, key: str, default: str = "#000000") -> str:
        return self._d.get("colors", {}).get(key, default)

    @property
    def colors(self) -> dict:
        return self._d.get("colors", {})


class Config:
    """Contenitore globale. Carica/salva config.json, espone le sezioni."""

    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self._data: dict = {}
        self.load()

    # singleton — un solo Config per processo
    @classmethod
    def instance(cls) -> "Config":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def load(self):
        # default di fabbrica (nell'app) + override utente (cartella per-utente).
        # Così le voci nuove di una release compaiono senza azzerare le tue.
        data = {}
        try:
            with open(DEFAULT_CONFIG, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
        # LE MISURE DEI LOGHI SONO DI FABBRICA: viaggiano con gli SVG in
        # brandlogo/, non sono una preferenza. save() fotografava l'intera
        # config in AppData e da li' in poi la copia VECCHIA di logo_sizes
        # oscurava per sempre ogni fix interno. Qui il default vince sempre.
        _fab_ls = {s: (data.get(s) or {}).get("logo_sizes")
                   for s in ("standings", "relative")}
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                user = json.load(f)
            data = _deep_merge(data, user)
            for _s, _ls in _fab_ls.items():
                if _ls is not None and isinstance(data.get(_s), dict):
                    data[_s]["logo_sizes"] = _ls
        except Exception:
            pass
        self._data = data

    def save(self):
        try:
            import os as _os
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            # ATOMICO: scrivi su file temporaneo e poi sostituisci. Un crash
            # a meta' scrittura non puo' piu' corrompere la config.
            tmp = CONFIG_FILE.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            _os.replace(str(tmp), str(CONFIG_FILE))
        except Exception:
            pass

    def widget(self, name: str) -> WidgetConfig:
        return WidgetConfig(self._data.get(name, {}))

    # ── modifica valori (usato dalla GUI di config) ───────────────────
    def set_scale(self, widget: str, value: float):
        self._data.setdefault(widget, {})["scale"] = round(value, 3)

    def step_scale(self, widget: str, delta: float, lo: float = 0.5, hi: float = None):
        # hi=None: NESSUN tetto (le dash sui display volante servono anche
        # oltre 2.5). Il default storico era hi=2.5.
        cur = float(self._data.get(widget, {}).get("scale", 1.0))
        new = max(lo, round(cur + delta, 3))
        if hi is not None:
            new = min(hi, new)
        self._data.setdefault(widget, {})["scale"] = new
        return new

    def set_value(self, widget: str, key: str, value):
        self._data.setdefault(widget, {})[key] = value

    def reset_all(self):
        """Azzera le configurazioni utente riportandole ai DEFAULT di fabbrica
        (config.default.json), preservando la struttura (colonne, righe, basi).
        Cancella le posizioni overlay. brands.json NON viene toccato."""
        import os, shutil
        try:
            if DEFAULT_CONFIG.exists():
                # ripristina config utente dai default di fabbrica
                CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(DEFAULT_CONFIG, CONFIG_FILE)
            self.load()
        except Exception:
            pass
        # cancella le posizioni overlay (tornano ai default)
        try:
            if POSITIONS_FILE.exists():
                os.remove(POSITIONS_FILE)
        except Exception:
            pass


# comodo accessor a livello di modulo
def get_config() -> Config:
    return Config.instance()
