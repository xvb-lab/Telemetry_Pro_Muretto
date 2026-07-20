"""LMU Telemetry Pro — entry point dell'APP (solo UI).

Architettura a processi separati (niente accavallamento di CPU/GIL):
  - APP / UI      -> questo processo (finestre, review, config)
  - MURETTO       -> processo separato (il cervello ingegnere, lanciato da qui)
  - OVERLAY       -> processi separati (uno per overlay, lanciati da qui)

Qui per ora c'e' solo lo scheletro: finestra con l'icona dell'app. I launcher
di muretto e overlay si innestano nei metodi dedicati piu' sotto.
"""
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget
from PySide6.QtCore import Qt

APP_NAME = "LMU Telemetry Pro"
APP_VERSION = "0.3b"
ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
ICONS = ASSETS / "icons"          # icone (app + widget); audio in assets/audio, img in assets/img


def app_icon() -> QIcon:
    """Icona dell'app: .ico su Windows (multi-risoluzione), fallback .png."""
    ico = ICONS / "icon.ico"
    png = ICONS / "icon.png"
    if ico.exists():
        return QIcon(str(ico))
    if png.exists():
        return QIcon(str(png))
    return QIcon()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.setWindowIcon(app_icon())
        self.resize(960, 600)

        central = QWidget(self)
        lay = QVBoxLayout(central)
        lay.setAlignment(Qt.AlignCenter)
        title = QLabel(f"{APP_NAME}\n{APP_VERSION}")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)
        self.setCentralWidget(central)

    # ── launcher processi separati (da implementare) ──────────────────────
    def start_muretto(self):
        """Avvia il MURETTO in un processo dedicato."""
        pass

    def start_overlays(self):
        """Avvia gli OVERLAY, ognuno nel suo processo."""
        pass


def _set_win_taskbar_id():
    """Windows: senza un AppUserModelID esplicito la taskbar usa l'icona di
    python.exe invece di quella della finestra. Va impostato PRIMA di creare
    la finestra. Su altri OS e' un no-op."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "LMU.TelemetryPro")
    except Exception:
        pass


def main():
    _set_win_taskbar_id()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(app_icon())
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
