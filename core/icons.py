"""
core/icons.py — Icone Material Symbols Rounded.

Il font (subset leggero) è in fonts/MaterialSymbolsRounded.ttf e viene
caricato da load_custom_fonts(). Per usare un'icona su una QLabel/QPushButton:

    from core.icons import ICON, ICON_FONT
    btn.setText(ICON["settings"])
    btn.setFont(QFont(ICON_FONT, 18))

oppure via QSS:  font-family: "Material Symbols Rounded";
e setText(ICON["settings"]).
"""

ICON_FONT = "Material Symbols Rounded"

# nome -> carattere (codepoint Material Symbols)
ICON = {
    "settings":   "\ue8b8",
    "close":      "\ue5cd",
    "remove":     "\ue15b",   # minus / minimize
    "add":        "\ue145",   # plus
    "power":      "\ue8ac",   # power_settings_new
    "visibility": "\ue8f4",
    "visibility_off": "\ue8f5",
    "refresh":    "\ue5d5",
    "delete":     "\ue872",   # trash
    "check":      "\ue5ca",
    "drag":       "\ue945",   # drag_indicator
    "tune":       "\ue429",   # sliders
    "reset":      "\ue87a",   # restart_alt
    # ── icone righe widget List ──
    "body":       "\ue531",   # directions_car (carrozzeria)
    "aero":       "\uefd8",   # air (aerodinamica)
    "fuel":       "\ue546",   # local_gas_station
    "energy":     "\uea0b",   # bolt (virtual energy)
    "battery":    "\ue1a4",   # battery_full
    "emotor":     "\uefa9",   # electric_bolt (motore elettrico)
    "erpm":       "\ue9e4",   # speed (giri e-motor)
    "engtrq":     "\uf6a6",   # motor / mode
    "oil":        "\uf552",   # oil_barrel
    "water":      "\ue798",   # water_drop
    "engine":     "\uf18a",   # engine
    "tyre":       "\ue9b4",   # tire
    "arrow_up":   "\ue5d8",   # arrow_upward (boost)
    "arrow_down": "\ue5db",   # arrow_downward (regen)
}
