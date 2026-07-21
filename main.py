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

_muretto_proc = None


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
    """Avvia il MURETTO in un processo separato, se abilitato nelle opzioni."""
    global _muretto_proc
    try:
        from core.engineer_cfg import load
        if not load().get("engineer_on", False):
            return
        kw = {"cwd": str(ROOT)}
        if sys.platform == "win32":
            kw["creationflags"] = 0x08000000      # niente console
        _muretto_proc = subprocess.Popen(
            [sys.executable, "-m", "engineer.run_engineer"], **kw)
    except Exception:
        pass


def _stop_muretto():
    global _muretto_proc
    p = _muretto_proc
    if p and p.poll() is None:
        try:
            p.terminate()
        except Exception:
            pass
    _muretto_proc = None


def main():
    _set_win_taskbar_id()
    app = QApplication(sys.argv)
    app.setApplicationName("LMU Telemetry Pro")
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
