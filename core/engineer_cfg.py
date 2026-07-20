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
        d = load()
        d.update(kw)
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    except Exception:
        pass
