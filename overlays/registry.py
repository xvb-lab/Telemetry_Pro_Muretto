"""overlays/registry.py — registro overlay: chiave -> (etichetta, classe).

Set WEC (gli overlay che l'utente usa). Usato da run_overlay per istanziare
l'overlay giusto per nome, e dall'app per la lista/lancio. Gli altri folder in
widgets/ sono legacy e non registrati.
"""
from widgets.map.widget import MapOverlay
from widgets.wec26board.widget import Wec26OnboardOverlay
from widgets.wec26battle.widget import Wec26BattleOverlay, Wec26BattleBOverlay
from widgets.wec26flag.widget import Wec26FlagOverlay
from widgets.wec26mfd.widget import Wec26MfdOverlay
from widgets.wec26mini.widget import Wec26MiniOverlay

# (key, etichetta, classe)
WIDGETS = [
    ("map", "Map", MapOverlay),
    ("wec26board", "WEC 2026 Onboard", Wec26OnboardOverlay),
    ("wec26battle", "WEC 2026 Battle Ahead", Wec26BattleOverlay),
    ("wec26battleb", "WEC 2026 Battle Behind", Wec26BattleBOverlay),
    ("wec26flag", "WEC 2026 Race Control", Wec26FlagOverlay),
    ("wec26mfd", "Dashboard", Wec26MfdOverlay),
    ("wec26mini", "WEC 2026 Mini Telemetry", Wec26MiniOverlay),
]
