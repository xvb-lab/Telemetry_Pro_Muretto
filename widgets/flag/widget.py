"""
widgets/flag/widget.py — Overlay bandiere.

Mostra fino a 4 bandiere affiancate con fade morbido:
YELLOW (distanza auto lenta), BLUE (classe doppiatore), PEN (penalità),
FIN (fine gara). Architettura comune: auto-hide fuori pista, scala/opacità,
drag con salvataggio, ⚙ impostazioni.
"""
import json
from pathlib import Path

from PySide6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout,
                                QGraphicsOpacityEffect)
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve

from core.config import get_config
from .reader import FlagReader
from .style import load_qss

_ROOT = Path(__file__).parent.parent.parent
from core.paths import POSITIONS_FILE  # dati utente, fuori dall'app


def _class_label(bc: str) -> str:
    up = (bc or "").upper()
    if "HYPER" in up or "LMH" in up or "LMDH" in up:
        return "HY"
    if "LMP" in up or "P2" in up:
        return "LMP"
    if "GT" in up:
        return "GT"
    return bc[:4].upper() if bc else ""


class FlagOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LMU Flag")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("overlay")
        self._drag_pos = None
        self._user_enabled = True

        from core.shared_memory import SharedMemory
        self._mem = SharedMemory.instance()
        self._reader = FlagReader()

        self._config = get_config()
        self.cfg = self._config.widget("flag")

        self._build_ui()
        pos = self._load_position("flag")
        self.move(pos[0], pos[1]) if pos else self.move(600, 200)
        self._apply_qss()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update)
        self._timer.start(self.cfg.get("update_ms", 200))

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._container = QWidget()
        self._container.setObjectName("container")
        self._container.setAttribute(Qt.WA_StyledBackground, True)
        outer.addWidget(self._container)

        row = QWidget()
        row.setObjectName("flagRow")
        rl = QHBoxLayout(self._container)
        rl.setContentsMargins(8, 4, 8, 4)
        rl.setSpacing(6)

        self.flag_yellow = QLabel(""); self.flag_yellow.setObjectName("flagYellow"); self.flag_yellow.setAlignment(Qt.AlignCenter)
        self.flag_blue = QLabel(""); self.flag_blue.setObjectName("flagBlue"); self.flag_blue.setAlignment(Qt.AlignCenter)
        self.flag_pen = QLabel(""); self.flag_pen.setObjectName("flagPen"); self.flag_pen.setAlignment(Qt.AlignCenter)
        self.flag_fin = QLabel(""); self.flag_fin.setObjectName("flagFin"); self.flag_fin.setAlignment(Qt.AlignCenter)
        self.flag_wet = QLabel("WET"); self.flag_wet.setObjectName("flagWet"); self.flag_wet.setAlignment(Qt.AlignCenter)

        self._flags = (self.flag_yellow, self.flag_blue, self.flag_pen, self.flag_fin, self.flag_wet)
        self._fx = {}
        self._anim = {}
        self._shown = {}
        self._conn = {}
        for fl in self._flags:
            eff = QGraphicsOpacityEffect(fl)
            eff.setOpacity(0.0)
            fl.setGraphicsEffect(eff)
            fl.setVisible(False)
            anim = QPropertyAnimation(eff, b"opacity")
            anim.setDuration(350)
            anim.setEasingCurve(QEasingCurve.InOutSine)
            self._fx[fl] = eff
            self._anim[fl] = anim
            self._shown[fl] = False
            self._conn[fl] = False

        rl.addStretch()
        rl.addWidget(self.flag_wet)
        rl.addWidget(self.flag_yellow)
        rl.addWidget(self.flag_blue)
        rl.addWidget(self.flag_pen)
        rl.addWidget(self.flag_fin)
        rl.addStretch()

        self.setFixedWidth(self.cfg.scaled("widget_width", 320))

    def _apply_qss(self):
        self.setStyleSheet(load_qss(self.cfg))

    def _fade(self, fl, show):
        if show == self._shown[fl]:
            return
        self._shown[fl] = show
        anim = self._anim[fl]
        anim.stop()
        if self._conn.get(fl):
            try:
                anim.finished.disconnect()
            except Exception:
                pass
            self._conn[fl] = False
        if show:
            fl.setVisible(True)
            anim.setStartValue(self._fx[fl].opacity())
            anim.setEndValue(1.0)
            anim.start()
        else:
            anim.setStartValue(self._fx[fl].opacity())
            anim.setEndValue(0.0)
            anim.finished.connect(lambda f=fl: f.setVisible(False))
            self._conn[fl] = True
            anim.start()

    # ── REBUILD / ENABLE ──────────────────────────────────────────────
    def reload_config(self):
        pos = self.pos()
        self.cfg = self._config.widget("flag")
        old = self.layout()
        QWidget().setLayout(old)
        self._build_ui()
        self._apply_qss()
        self.move(pos)
        self._timer.start(self.cfg.get("update_ms", 200))

    def set_enabled(self, enabled: bool):
        self._user_enabled = enabled
        if enabled:
            self._timer.start(self.cfg.get("update_ms", 200))
            if self._mem.is_on_track():
                super().show()
                self.raise_()
        else:
            self._timer.stop()
            super().hide()

    def open_config(self):
        from gui.config_window import ConfigWindow
        from PySide6.QtGui import QGuiApplication
        if getattr(self, "_cfg_win", None) is None:
            self._cfg_win = ConfigWindow(self._config, self, widget_key="flag", title="Flag")
        self._cfg_win.show()
        self._cfg_win.adjustSize()
        screen = QGuiApplication.screenAt(self.pos()) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        w = self._cfg_win.width(); h = self._cfg_win.height()
        x = self.x() + self.width() + 12; y = self.y()
        if x + w > geo.right():
            x = self.x() - w - 12
        if x < geo.left() or x + w > geo.right():
            x = geo.left() + (geo.width() - w) // 2
        if y + h > geo.bottom():
            y = geo.bottom() - h
        if y < geo.top():
            y = geo.top()
        self._cfg_win.move(x, y)
        self._cfg_win.raise_()
        self._cfg_win.activateWindow()

    # ── DRAG ──────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        from core.utils import overlays_locked
        if overlays_locked():
            return          # overlay BLOCCATI: niente drag
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() == Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        if self._drag_pos is not None:
            self._save_position("flag")
        self._drag_pos = None

    # ── UPDATE ────────────────────────────────────────────────────────
    def _update(self):
        if self._user_enabled:
            on_track = self._mem.is_on_track()
            if on_track and not self.isVisible():
                super().show()
            elif not on_track and self.isVisible():
                super().hide()
                return
            if not on_track:
                return

        d = self._reader.read()
        if not d:
            return

        yd = d.get("yellow_dist")
        bc = d.get("blue_class")
        pen = d.get("num_penalties") or 0
        fin = bool(d.get("checkered"))

        if yd is not None:
            self.flag_yellow.setText(f"-{int(round(yd))}m")
            self._fade(self.flag_yellow, True)
        else:
            self._fade(self.flag_yellow, False)

        if bc:
            self.flag_blue.setText(_class_label(bc))
            self._fade(self.flag_blue, True)
        else:
            self._fade(self.flag_blue, False)

        if pen > 0:
            self.flag_pen.setText("PEN" if pen == 1 else f"PEN x{pen}")
            self._fade(self.flag_pen, True)
        else:
            self._fade(self.flag_pen, False)

        if fin:
            self.flag_fin.setText("FIN")
            self._fade(self.flag_fin, True)
        else:
            self._fade(self.flag_fin, False)

        w = self._mem.get_weather()
        if w and w.get("wet"):
            self.flag_wet.setText("WET")
            self._fade(self.flag_wet, True)
        else:
            self._fade(self.flag_wet, False)

        self.adjustSize()

    # ── POSIZIONE ─────────────────────────────────────────────────────
    def _save_position(self, key):
        try:
            data = {}
            if POSITIONS_FILE.exists():
                data = json.loads(POSITIONS_FILE.read_text())
            data[key] = [self.x(), self.y()]
            POSITIONS_FILE.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def _load_position(self, key):
        try:
            if POSITIONS_FILE.exists():
                return json.loads(POSITIONS_FILE.read_text()).get(key)
        except Exception:
            pass
        return None

    def closeEvent(self, e):
        self._save_position("flag")
        super().closeEvent(e)
