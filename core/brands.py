"""
core/brands.py — Lookup costruttore da nome veicolo.

Carica settings/brands.json UNA volta sola (cache in RAM, condivisa).
brand_from_vehicle() restituisce sempre str ("" se sconosciuto, mai None)
per evitare AttributeError a valle.
"""
import json
from pathlib import Path

_CORE_DIR = Path(__file__).parent
_ROOT_DIR = _CORE_DIR.parent
_BRANDS_FILE = _ROOT_DIR / "settings" / "brands.json"

# Normalizza il nome brand grezzo -> nome file logo (SVG/PNG in brandlogo/)
_NORMALIZE = {
    "Ford Mustang":       "Ford",
    "Chevrolet Corvette": "Corvette",
    "Scuderia Ferrari":   "Ferrari",
    "BMW Motorsport":     "BMW",
    "TOYOTA GAZOO Racing": "Toyota",
    "Porsche Multimatic": "Porsche",
    "ADESS":              "Adess",
    "Mercedes-AMG":       "Mercedes-AMG",
    "Mercedes":           "Mercedes-AMG",
}

_BRANDS: dict = {}
try:
    with open(_BRANDS_FILE, encoding="utf-8") as _f:
        _BRANDS = json.load(_f)
except Exception:
    _BRANDS = {}


def brand_from_vehicle(vehicle_name: str) -> str:
    """Nome veicolo LMU -> nome brand normalizzato per il file logo.

    Ritorna "" se sconosciuto (mai None).
    """
    if not vehicle_name or not _BRANDS:
        return ""
    brand = _BRANDS.get(vehicle_name)
    if not brand:
        return ""
    return _NORMALIZE.get(brand, brand)
