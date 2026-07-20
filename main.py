"""LMU Telemetry Pro — entry point dell'APP (solo UI).

Architettura a processi separati (niente accavallamento di CPU/GIL):
  - APP / UI      -> questo processo (finestre, config, launcher)
  - MURETTO       -> processo separato (il cervello ingegnere, lanciato da qui)
  - OVERLAY       -> processi separati (uno per overlay, lanciati da qui)

Pagina Opzioni: interruttore ingegnere ON/OFF + impostazioni (lingua, volume
voce, beep radio, ritardo tono, opzioni tempi). Le scelte finiscono in
settings/engineer_cfg.json (le legge il processo muretto).
"""
import sys
import subprocess
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QMainWindow, QLabel, QVBoxLayout,
                               QWidget, QFormLayout, QCheckBox, QComboBox,
                               QSlider, QDoubleSpinBox, QHBoxLayout)
from PySide6.QtCore import Qt

from core import engineer_cfg

APP_NAME = "LMU Telemetry Pro"
APP_VERSION = "0.3b"
ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
ICONS = ASSETS / "icons"

_LANGS = [("Italiano", "it"), ("English", "en"),
          ("Español", "es"), ("Français", "fr")]


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
        self.resize(520, 420)
        self._muretto_proc = None
        cfg = engineer_cfg.load()

        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel(f"{APP_NAME} · {APP_VERSION}")
        title.setStyleSheet("font-size:16px; font-weight:600;")
        root.addWidget(title)
        root.addWidget(QLabel("Opzioni ingegnere / muretto"))

        # interruttore ingegnere ON/OFF
        self.chk_on = QCheckBox("Ingegnere attivo")
        self.chk_on.setChecked(bool(cfg.get("engineer_on", False)))
        self.chk_on.toggled.connect(self._on_toggle)
        root.addWidget(self.chk_on)

        self._status = QLabel("")
        root.addWidget(self._status)

        form = QFormLayout()
        form.setSpacing(10)

        # lingua
        self.cmb_lang = QComboBox()
        for label, code in _LANGS:
            self.cmb_lang.addItem(label, code)
        _cur = cfg.get("lang", "it")
        self.cmb_lang.setCurrentIndex(
            max(0, next((i for i, (_, c) in enumerate(_LANGS) if c == _cur), 0)))
        self.cmb_lang.currentIndexChanged.connect(self._save)
        form.addRow("Lingua", self.cmb_lang)

        # volume voce
        self.sld_vol = QSlider(Qt.Horizontal)
        self.sld_vol.setRange(0, 100)
        self.sld_vol.setValue(int(cfg.get("voice_vol", 100)))
        self.lbl_vol = QLabel("%d%%" % self.sld_vol.value())
        self.sld_vol.valueChanged.connect(
            lambda v: (self.lbl_vol.setText("%d%%" % v), self._save()))
        _volrow = QHBoxLayout()
        _volrow.addWidget(self.sld_vol)
        _volrow.addWidget(self.lbl_vol)
        _volw = QWidget()
        _volw.setLayout(_volrow)
        form.addRow("Volume voce", _volw)

        # beep radio
        self.chk_beep = QCheckBox("Beep radio prima della voce")
        self.chk_beep.setChecked(bool(cfg.get("beep_on", True)))
        self.chk_beep.toggled.connect(self._save)
        form.addRow("Beep", self.chk_beep)

        # ritardo tono (s)
        self.spn_delay = QDoubleSpinBox()
        self.spn_delay.setRange(0.0, 5.0)
        self.spn_delay.setSingleStep(0.5)
        self.spn_delay.setSuffix(" s")
        self.spn_delay.setValue(float(cfg.get("beep_delay_s", 2.0)))
        self.spn_delay.valueChanged.connect(self._save)
        form.addRow("Ritardo tono radio", self.spn_delay)

        # opzioni tempi
        self.chk_lt = QCheckBox("Chiama i tempi ogni giro")
        self.chk_lt.setChecked(bool(cfg.get("lap_time_always", True)))
        self.chk_lt.toggled.connect(self._save)
        form.addRow("Tempi", self.chk_lt)

        self.chk_tenths = QCheckBox("Leggi i tempi con i decimi")
        self.chk_tenths.setChecked(bool(cfg.get("lap_time_tenths", False)))
        self.chk_tenths.toggled.connect(self._save)
        form.addRow("", self.chk_tenths)

        root.addLayout(form)
        root.addStretch(1)
        self.setCentralWidget(central)

        # ricorda lo stato: se era acceso, riparte
        if self.chk_on.isChecked():
            self.start_muretto()
        else:
            self._status.setText("Muretto: spento")

    # ── persistenza opzioni ───────────────────────────────────────────────
    def _save(self, *a):
        engineer_cfg.save(
            engineer_on=self.chk_on.isChecked(),
            lang=self.cmb_lang.currentData(),
            voice_vol=self.sld_vol.value(),
            beep_on=self.chk_beep.isChecked(),
            beep_delay_s=round(self.spn_delay.value(), 2),
            lap_time_always=self.chk_lt.isChecked(),
            lap_time_tenths=self.chk_tenths.isChecked(),
        )

    def _on_toggle(self, on):
        self._save()
        if on:
            self.start_muretto()
        else:
            self.stop_muretto()
            self._status.setText("Muretto: spento")

    # ── launcher processi separati ────────────────────────────────────────
    def _spawn(self, args):
        kwargs = {"cwd": str(ROOT)}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x08000000     # CREATE_NO_WINDOW
        return subprocess.Popen([sys.executable] + list(args), **kwargs)

    def start_muretto(self):
        if self._muretto_proc and self._muretto_proc.poll() is None:
            return
        try:
            self._muretto_proc = self._spawn(["-m", "engineer.run_engineer"])
            self._status.setText("Muretto: attivo")
        except Exception:
            self._status.setText("Muretto: errore all'avvio")

    def stop_muretto(self):
        p = self._muretto_proc
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass
        self._muretto_proc = None

    def start_overlays(self):
        """Avvia gli OVERLAY, ognuno nel suo processo (da fare)."""
        pass

    def closeEvent(self, ev):
        self.stop_muretto()
        super().closeEvent(ev)


def _set_win_taskbar_id():
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
