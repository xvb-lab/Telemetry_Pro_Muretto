"""LMU Telemetry Pro — entry point dell'APP (UI completa).

Architettura a processi separati:
  - APP / UI  -> questo processo (telemetry.window.TelemetryWindow: review,
                 overview, community, team, overlay, settings). NON esegue
                 l'ingegnere in-process (era la causa degli scatti).
  - MURETTO   -> processo separato (engineer/run_engineer), lanciato da qui.
  - OVERLAY   -> processi separati, lanciati dal tab Overlay della UI.

Avvio: pythonw main.py  (con python.exe vedi la console per debug).
"""
import sys
import subprocess
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent
_ICON_CANDIDATES = [ROOT / "assets" / "icons" / "icon.ico",
                    ROOT / "assets" / "icon.ico",
                    ROOT / "assets" / "icons" / "icon.png"]

def app_icon() -> QIcon:
    for p in _ICON_CANDIDATES:
        if p.exists():
            return QIcon(str(p))
    return QIcon()


def _set_win_taskbar_id():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "LMU.TelemetryPro")
    except Exception:
        pass


def _start_muretto():
    """All'avvio lancia il muretto se abilitato; poi il toggle Engineer nella
    UI lo gestisce dal vivo (stesso gestore di processo condiviso)."""
    try:
        from core.engineer_cfg import load
        if not load().get("engineer_on", False):
            return
        from core import muretto_proc
        muretto_proc.start()
    except Exception:
        pass


def _stop_muretto():
    try:
        from core import muretto_proc
        muretto_proc.stop()
    except Exception:
        pass


def main():
    _set_win_taskbar_id()
    app = QApplication(sys.argv)
    app.setApplicationName("LMU Telemetry Pro")
    # PALETTE SCURA DI DEFAULT: testo chiaro come fallback per QUALSIASI widget
    # senza colore esplicito. Evita il bug storico "testo nero" quando uno
    # stylesheet non definiva il color. I colori espliciti del QSS vincono.
    try:
        from PySide6.QtGui import QPalette, QColor
        _pal = app.palette()
        _light = QColor("#e8ebf2")
        _dim = QColor("#8a90a0")
        _dark = QColor("#0e1014")
        _panel = QColor("#1b1d20")
        for _r in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText,
                   QPalette.ToolTipText, QPalette.BrightText):
            _pal.setColor(_r, _light)
        _pal.setColor(QPalette.PlaceholderText, _dim)
        _pal.setColor(QPalette.Window, _dark)
        _pal.setColor(QPalette.Base, _panel)
        _pal.setColor(QPalette.Button, _panel)
        _pal.setColor(QPalette.ToolTipBase, _panel)
        app.setPalette(_pal)
    except Exception:
        pass
    try:
        from core.utils import load_custom_fonts
        load_custom_fonts()
    except Exception:
        pass
    ic = app_icon()
    app.setWindowIcon(ic)

    from telemetry.window import TelemetryWindow
    win = TelemetryWindow()
    try:
        win.setWindowIcon(ic)
    except Exception:
        pass
    win.show()
    win.raise_()
    win.activateWindow()

    _start_muretto()                          # muretto separato (se abilitato)
    app.aboutToQuit.connect(_stop_muretto)    # chiudi il muretto con l'app
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
