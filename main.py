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


def _sharp_dpi():
    """Font NITIDI su monitor scalati (125/150%) e multi-monitor: DPI
    per-monitor V2 + scaling Qt passante. Senza, Windows fa lo stretch
    bitmap della finestra -> testo sgranato (segnalato 23/07)."""
    try:
        import ctypes
        # -4 = DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        ctypes.windll.user32.SetProcessDpiAwarenessContext(
            ctypes.c_void_p(-4))
    except Exception:
        pass
    try:
        from PySide6.QtCore import Qt as _Qt
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            _Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass


def _single_instance():
    """UNA sola app: mutex di Windows col nome del prodotto. Se esiste
    gia' (app aperta), la nuova istanza esce in silenzio (rich. 23/07:
    'l'app non deve duplicarsi se e' gia' aperta')."""
    try:
        import ctypes
        ctypes.windll.kernel32.CreateMutexW(
            None, False, "LMU_TelemetryPro_SingleInstance")
        return ctypes.windll.kernel32.GetLastError() != 183  # ALREADY_EXISTS
    except Exception:
        return True


def main():
    if not _single_instance():
        return
    # MODALITA' TEST/ECO: azzerate a OGNI avvio (mai ereditare la
    # sessione precedente); i target +N/minuti restano come preferenze
    try:
        from core import engineer_cfg
        engineer_cfg.save(test_mode=None, eco_free=0)
    except Exception:
        pass
    _set_win_taskbar_id()
    _sharp_dpi()
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
    # WATCHER: engineer_on e' l'UNICA verita' (Options E il dash lo scrivono).
    # Il dash e' un processo a se' e non puo' avviare il muretto: qui il padre
    # riconcilia il PROCESSO col flag ogni 2s, cosi' "RADIO ON" dal dash lo fa
    # ripartire davvero anche se Options l'aveva spento.
    try:
        from PySide6.QtCore import QTimer as _QTimer
        from core.engineer_cfg import load as _eload
        from core import muretto_proc as _mp

        def _reconcile_muretto():
            try:
                want = bool(_eload().get("engineer_on", False))
                if want and not _mp.is_running():
                    _mp.start()
                elif (not want) and _mp.is_running():
                    _mp.stop()
            except Exception:
                pass

        win._muretto_timer = _QTimer()
        win._muretto_timer.timeout.connect(_reconcile_muretto)
        win._muretto_timer.start(2000)
    except Exception:
        pass
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
