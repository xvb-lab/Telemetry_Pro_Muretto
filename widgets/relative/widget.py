"""
widgets/relative/widget.py — Overlay relative.

Mostra N auto davanti + player + N dietro per posizione in pista.
Stessa architettura dello standings: titlebar vuota (drag), save-on-drag,
auto-hide fuori pista, scala da config, finestra impostazioni via ⚙.
"""
import json
from pathlib import Path

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
from PySide6.QtCore import Qt, QTimer

from core.config import get_config
from .reader import RelativeReader
from .driver_row import RelDriverRow
from .style import load_qss

_ROOT = Path(__file__).parent.parent.parent
from core.paths import POSITIONS_FILE  # dati utente, fuori dall'app


class RelativeOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LMU Relative")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("overlay")
        self._drag_pos = None
        self._reader = RelativeReader()
        self._rows = []
        self._user_enabled = True

        from core.shared_memory import SharedMemory
        self._mem = SharedMemory.instance()

        self._config = get_config()
        self.cfg = self._config.widget("relative")

        self._build_ui()

        pos = self._load_position("relative")
        self.move(pos[0], pos[1]) if pos else self.move(20, 400)

        self._apply_qss()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update)
        self._timer.start(self.cfg.get("update_ms", 100))

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._container = QWidget()
        self._container.setObjectName("container")
        self._container.setAttribute(Qt.WA_StyledBackground, True)
        outer.addWidget(self._container)

        cl = QVBoxLayout(self._container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(self.cfg.scaled("row_spacing", 0))

        # ── header colonne ──
        from PySide6.QtCore import Qt as _Qt
        hdr = QWidget()
        hdr.setObjectName("header")
        hdr.setFixedHeight(self.cfg.scaled("header_height", 22))
        hl = QHBoxLayout(hdr)
        ph = self.cfg.scaled("row_padding_h", 4)
        hl.setContentsMargins(ph, 2, ph, 2)
        hl.setSpacing(self.cfg.scaled("row_col_spacing", 5))

        def hlbl(txt, w, align):
            l = QLabel(txt)
            l.setObjectName("headerLabel")
            if w:
                l.setFixedWidth(w)
            l.setAlignment(align | _Qt.AlignVCenter)
            return l

        HDR = {
            "status": ("", self.cfg.scaled("col_status", 50), _Qt.AlignCenter),
            "class":  ("CL", self.cfg.scaled("col_class", 34), _Qt.AlignCenter),
            "pos":    ("POS", self.cfg.scaled("col_pos", 30), _Qt.AlignCenter),
            "pdelta": ("+/-", self.cfg.scaled("col_pdelta", 30), _Qt.AlignCenter),
            "logo":   ("", self.cfg.scaled("logo_width", 30), _Qt.AlignCenter),
            "name":   ("DRIVER", self.cfg.scaled("col_name", 140), _Qt.AlignLeft),
            "speed":  ("SPEED", self.cfg.scaled("col_speed", 55), _Qt.AlignCenter),
            "gap":    ("GAP", self.cfg.scaled("col_gap", 65), _Qt.AlignCenter),
            "best":   ("BEST", self.cfg.scaled("col_best", 82), _Qt.AlignCenter),
            "lap":    ("LAST", self.cfg.scaled("col_lap", 82), _Qt.AlignCenter),
            "tyre":   ("TYRE", self.cfg.get("base", {}).get("col_tyre", 34), _Qt.AlignCenter),
            "energy": ("NRG", self.cfg.scaled("col_energy", 50), _Qt.AlignCenter),
            "tl":     ("TL", self.cfg.scaled("col_tl", 38), _Qt.AlignCenter),
            "pit":    ("PIT", self.cfg.scaled("col_pit", 30), _Qt.AlignCenter),
            "sectors":("SECT", self.cfg.scaled("col_sectors", 42), _Qt.AlignCenter),
            "laps":   ("LAPS", self.cfg.scaled("col_laps", 34), _Qt.AlignCenter),
            "stint":  ("STINT", self.cfg.scaled("col_stint", 48), _Qt.AlignCenter),
            "wear":   ("WEAR", self.cfg.scaled("col_wear", 42), _Qt.AlignCenter),
        }
        left_cols = {"status", "class", "pos", "logo", "name"}
        stretch_added = False
        _ord = self.cfg.get("column_order", [])
        if "pdelta" not in _ord:
            _ord = list(_ord); _ord.insert(_ord.index("gap") if "gap" in _ord else len(_ord), "pdelta")
        for col in _ord:
            if col not in HDR:
                continue
            if col == "pdelta" and not self.cfg.get("show_pos_delta", True):
                continue
            if col == "speed" and not self.cfg.get("show_speed", True):
                continue
            if col == "best" and not self.cfg.get("show_best_lap", True):
                continue
            if col == "tl" and not self.cfg.get("show_track_limits", True):
                continue
            if col == "pit" and not self.cfg.get("show_pit", True):
                continue
            if col == "sectors" and not self.cfg.get("show_sectors", True):
                continue
            if col == "laps" and not self.cfg.get("show_laps", True):
                continue
            if col == "stint" and not self.cfg.get("show_stint", True):
                continue
            if col == "wear" and not self.cfg.get("show_wear", True):
                continue
            if col == "gap" and not self.cfg.get("show_gap", True):
                continue
            if col == "lap" and not self.cfg.get("show_lap", True):
                continue
            if col == "tyre" and not self.cfg.get("show_tyre", True):
                continue
            if col == "energy" and not self.cfg.get("show_energy", True):
                continue
            if col == "status" and not self.cfg.get("show_status", True):
                continue
            txt, w, align = HDR[col]
            if col not in left_cols and not stretch_added:
                hl.addStretch()
                stretch_added = True
            hl.addWidget(hlbl(txt, w, align))
        if not stretch_added:
            hl.addStretch()
        cl.addWidget(hdr)
        if not self.cfg.get("show_header", True):
            hdr.hide()
            hdr.setFixedHeight(0)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("separator")
        cl.addWidget(sep)

        n = self.cfg.get("rows_each_side", 2)
        total = 2 * n + 1
        self._rows = []
        for _ in range(total):
            r = RelDriverRow(self.cfg)
            r.hide()
            cl.addWidget(r)
            self._rows.append(r)

        self.setFixedWidth(self._compute_width())

    def _compute_width(self):
        """Larghezza dinamica = somma colonne attive + spacing + padding."""
        col_w = {
            "status": self.cfg.scaled("col_status", 50),
            "class":  self.cfg.scaled("col_class", 34),
            "pos":    self.cfg.scaled("col_pos", 30),
            "pdelta": self.cfg.scaled("col_pdelta", 30),
            "logo":   self.cfg.scaled("logo_width", 30),
            "name":   self.cfg.scaled("col_name", 140),
            "speed":  self.cfg.scaled("col_speed", 55),
            "gap":    self.cfg.scaled("col_gap", 65),
            "best":   self.cfg.scaled("col_best", 82),
            "lap":    self.cfg.scaled("col_lap", 82),
            "tl":     self.cfg.scaled("col_tl", 38),
            "pit":    self.cfg.scaled("col_pit", 30),
            "sectors": self.cfg.scaled("col_sectors", 42),
            "laps":   self.cfg.scaled("col_laps", 34),
            "stint":  self.cfg.scaled("col_stint", 48),
            "wear":   self.cfg.scaled("col_wear", 42),
            "tyre":   self.cfg.get("base", {}).get("col_tyre", 34),
            "energy": self.cfg.scaled("col_energy", 50),
        }
        order = self.cfg.get("column_order", [])
        if "pdelta" not in order:
            order = list(order); order.insert(order.index("gap") if "gap" in order else len(order), "pdelta")
        spacing = self.cfg.scaled("row_col_spacing", 5)
        pad = self.cfg.scaled("row_padding_h", 4)
        total = pad * 2
        n = 0
        for c in order:
            if c not in col_w:
                continue
            if c == "pdelta" and not self.cfg.get("show_pos_delta", True):
                continue
            if c == "class" and not self.cfg.get("show_class", False):
                continue
            if c == "speed" and not self.cfg.get("show_speed", True):
                continue
            if c == "best" and not self.cfg.get("show_best_lap", True):
                continue
            if c == "tl" and not self.cfg.get("show_track_limits", True):
                continue
            if c == "pit" and not self.cfg.get("show_pit", True):
                continue
            if c == "sectors" and not self.cfg.get("show_sectors", True):
                continue
            if c == "laps" and not self.cfg.get("show_laps", True):
                continue
            if c == "stint" and not self.cfg.get("show_stint", True):
                continue
            if c == "wear" and not self.cfg.get("show_wear", True):
                continue
            if c == "gap" and not self.cfg.get("show_gap", True):
                continue
            if c == "lap" and not self.cfg.get("show_lap", True):
                continue
            if c == "tyre" and not self.cfg.get("show_tyre", True):
                continue
            if c == "energy" and not self.cfg.get("show_energy", True):
                continue
            if c == "status" and not self.cfg.get("show_status", True):
                continue
            total += col_w[c]
            n += 1
        total += spacing * max(0, n - 1)
        total += 24
        return total

    def _apply_qss(self):
        self.setStyleSheet(load_qss(self.cfg))

    # ── REBUILD / ENABLE ──────────────────────────────────────────────
    def reload_config(self):
        pos = self.pos()
        self.cfg = self._config.widget("relative")
        old = self.layout()
        QWidget().setLayout(old)
        self._build_ui()
        self._apply_qss()
        self.move(pos)
        self._timer.start(self.cfg.get("update_ms", 100))

    def set_enabled(self, enabled: bool):
        self._user_enabled = enabled
        if enabled:
            self._timer.start(self.cfg.get("update_ms", 100))
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
            self._cfg_win = ConfigWindow(self._config, self, widget_key="relative", title="Relative")
        self._cfg_win.show()
        self._cfg_win.adjustSize()
        screen = QGuiApplication.screenAt(self.pos()) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        w = self._cfg_win.width()
        h = self._cfg_win.height()
        x = self.x() + self.width() + 12
        y = self.y()
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
            self._save_position("relative")
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

        n = self.cfg.get("rows_each_side", 2)
        rows = self._reader.read(rows_each_side=n)
        if not rows:
            return
        # reader ricalcola 1×/sec e restituisce lo stesso oggetto: se invariato,
        # non ridisegno (niente re-polish a vuoto).
        if rows is getattr(self, "_prev_rows", None):
            return
        self._prev_rows = rows

        for row, d in zip(self._rows, rows):
            if d is None:
                row.hide()
            else:
                row.update_data(d)
                row.show()
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
        self._save_position("relative")
        super().closeEvent(e)
