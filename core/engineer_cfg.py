"""core/engineer_cfg.py — opzioni del MURETTO (lingua, voci, volumi, ritardi
radio, lap_time_always, ecc.), lette da settings/engineer_cfg.json.

Sostituisce il vecchio `engineer_overlay._load_cfg` (0.3b: il muretto e' un
processo a se', staccato dagli overlay). Ritorna {} se il file non esiste.
"""
import json
from pathlib import Path

_FILE = Path(__file__).resolve().parent.parent / "settings" / "engineer_cfg.json"


def load() -> dict:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def save(**kw):
    try:
        # SPIA (24/07): engineer_on spariva a False senza colpevole —
        # ogni scrittura della chiave viene loggata con lo stack
        if "engineer_on" in kw:
            try:
                import time as _t
                import traceback as _tb
                from core.paths import USER_DIR as _UD
                _st = "".join(_tb.format_stack(limit=6)[:-1])
                with open(_UD / "engineer_on_writes.log", "a",
                          encoding="utf-8") as _fh:
                    _fh.write("[%s] engineer_on=%s\n%s\n" % (
                        _t.strftime("%H:%M:%S"), kw["engineer_on"], _st))
            except Exception:
                pass
        d = load()
        d.update(kw)
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    except Exception:
        pass
