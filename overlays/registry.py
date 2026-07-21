"""overlays/registry.py — registro overlay: chiave -> (etichetta, classe).

Set WEC (gli overlay che l'utente usa). Usato da run_overlay per istanziare
l'overlay giusto per nome, e dall'app per la lista/lancio. Gli altri folder in
widgets/ sono legacy e non registrati.
"""
from widgets.map.widget import MapOverlay

# (key, etichetta, classe) — si aggiungono man mano che si portano i folder
WIDGETS = [
    ("map", "Map", MapOverlay),
]
