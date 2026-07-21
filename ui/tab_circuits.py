"""ui/tab_circuits.py — menu circuiti estratto da window.py."""

import os
import sqlite3
import time
import math
from PySide6.QtWidgets import (QWidget, QMainWindow, QTabWidget, QTabBar, QVBoxLayout,
                               QHBoxLayout, QComboBox, QPushButton, QLabel,
                               QTableWidget, QTableWidgetItem, QHeaderView,
                               QAbstractItemView, QStyledItemDelegate, QMessageBox,
                               QColorDialog, QStackedWidget, QGridLayout, QSizePolicy,
                               QLineEdit, QFrame, QCheckBox)
from PySide6.QtCore import Qt, QRectF, QPointF, QTimer, QSize
from pathlib import Path
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QPolygonF, QFont, QPainterPath, QLinearGradient, QPixmap
from telemetry import common as _common
from telemetry.common import (_ACCENT, _BG, _CLASS_COL, _CMP_COL, _CMP_IS_BEST, _FG, _FUCHSIA, _FUX, _GOLD, _GRID, _HYBRID_HINTS, _MONTHS, _SEL_COL, _SEL_IS_BEST, _SVG_RENDERER_CACHE, _SvgBox, _TRK_COL, _best_color, _clear_layout, _cmp_col, _date_human, _draw_lap_legend, _draw_sector_times, _dur, _f2, _faster_colors, _fastest_lap, _fmt, _heat, _is_b, _is_hybrid, _rows, _sel_col, _two_best_laps)
from telemetry.trace_view import (EnergiaView, GommeView, GuidaView, LineChart, LiveView, MappaView, TrajectoryView, _BrakesTab, _CatTable, _CmpChart, _DeltaTab, _FitTable, _GGCanvas, _GGTab, _LapData, _LiveMap, _LiveSpeedChart, _PedalChart, _PedalsTab, _StintTab, _SuspTab, _TraceChart, _TraceTab, _TyreCorner, _TyresTab, _WorksheetTab, _delta_series, _load_track_svg, _resample, _spd_series, _t_series, _wheel_widget)
from telemetry.engineer_tab import _EngineerTab
from data.tracks import (_ALT_LAYOUT_STEMS, _LAYOUT_LABELS, _OV_LOGO_ALIASES, _OV_TRACKLOGO_DIR, _OV_TRACKMAPS_PNG_DIR, _OV_TRACKMAPS_SVG_DIR, _OV_TRACKMAP_DIR, _TRACK_PNG_ALIASES, _TRACK_ROT_JSON, _cmap_layout_key, _decode_stem, _layout_key_for_cmap, _layout_key_for_track, _ov_tracklogo_file, _ov_trackmap_file, _ov_trackmap_idx, _track_is_alt, _track_layout_key, _track_layout_label, _track_logo_stem, _track_png_file, _track_rot, _track_rot_map, _track_short, _track_styled_svg, _trackmap_white_bytes, _trackmap_white_cache)
from ui.widgets import (_CircleCheck, _ClassBadge, _ClassChip, _ClickFrame, _EXPORT_SVG, _ExportButton, _FOLDER_SVG, _Switch, _TRASH_SVG, _XButton, _X_SVG, _abbr_num, _chip, _class_color, _export_icon, _export_icon_cache, _folder_icon, _folder_icon_cache, _mk_check, _svg_icon, _trash_icon, _trash_icon_cache, _x_icon, _x_icon_cache)
from core.profile import _load_profile, _save_profile, get_team
from telemetry.common import _fmt_session_len, _ov_clock, _ov_session_label
from ui.widgets import _LapBoard, _BEST_ROSE, _LapRow, _PACE_LABEL, _comp_four_single, _pace_label
from ui.tab_overview import _OverviewTab
from ui.widgets import _car_logo_into, _fmt_ms, _EMPTY_LOGO_SVG, _brand_from_car_name
from ui.tab_team import _TeamTab
from ui.tab_community import _CommunityTab
from ui.tab_settings import _SettingsTab
try:
    from PySide6.QtSvgWidgets import QSvgWidget
except Exception:
    QSvgWidget = None
try:
    from PySide6.QtSvg import QSvgRenderer
except Exception:
    QSvgRenderer = None
from PySide6.QtCore import QByteArray
from telemetry import db as _db
from telemetry.reader import TelemetryReader
from core.classes import class_tag
from ui.icons import FUEL_WEIGHT_SVG as _FUEL_WEIGHT_SVG
try:
    from core.paths import PROFILE_FILE as _PROFILE_FILE
except Exception:
    _PROFILE_FILE = Path(__file__).resolve().parent.parent / "settings" / "profile.json"


class _CircuitCard(_ClickFrame):
    """Card grigia cliccabile: logo SVG pista + nome + n. sessioni."""
    def __init__(self, track, count, logo_path, on_pick):
        super().__init__(lambda: on_pick(track))
        has = count > 0
        self.setObjectName("circCardOn" if has else "circCard")
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        v = QVBoxLayout(self); v.setContentsMargins(14, 14, 14, 12); v.setSpacing(6)
        logo = _SvgBox(min_h=64)
        logo.setFixedHeight(72)               # dimensione SVG uniforme tra le card
        if logo_path:
            logo.load(str(logo_path))
        v.addWidget(logo, 1)
        nm = QLabel(track or "\u2014"); nm.setObjectName("circName")
        nm.setAlignment(Qt.AlignCenter); nm.setWordWrap(True)
        v.addWidget(nm)
        cnt = QLabel("%d session%s" % (count, "" if count == 1 else "s"))
        cnt.setObjectName("circCountOn" if has else "circCount")
        cnt.setAlignment(Qt.AlignCenter)
        v.addWidget(cnt)


class _CircuitMenu(QWidget):
    """Menu iniziale: griglia di card, una per circuito con sessioni."""
    _COLS = 4

    def __init__(self, on_pick):
        super().__init__()
        self._on_pick = on_pick
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # ── HEADER: logo + nome app (sinistra), campo Team (destra) ──
        header = QWidget(); header.setObjectName("circHeader")
        hl = QHBoxLayout(header); hl.setContentsMargins(24, 14, 24, 14); hl.setSpacing(10)
        self.app_logo = _SvgBox(); self.app_logo.setFixedSize(34, 34)
        _logo_p = Path(__file__).resolve().parent.parent / "assets" / "app_logo.svg"
        if _logo_p.exists():
            self.app_logo.load(str(_logo_p))
        hl.addWidget(self.app_logo, 0, Qt.AlignVCenter)
        app_name = QLabel("LMU TELEMETRY PRO"); app_name.setObjectName("appName")
        hl.addWidget(app_name, 0, Qt.AlignVCenter)
        hl.addStretch()
        dlb = QLabel("DRIVER"); dlb.setObjectName("hdrTeamLbl")
        hl.addWidget(dlb, 0, Qt.AlignVCenter)
        self.lb_driver = QLabel((_load_profile().get("driver", "") or "\u2014").upper())
        self.lb_driver.setObjectName("hdrDriver")
        hl.addWidget(self.lb_driver, 0, Qt.AlignVCenter)
        hl.addSpacing(18)
        tlb = QLabel("TEAM"); tlb.setObjectName("hdrTeamLbl")
        hl.addWidget(tlb, 0, Qt.AlignVCenter)
        self.ed_team = QLineEdit(); self.ed_team.setObjectName("hdrTeam")
        self.ed_team.setMaxLength(30); self.ed_team.setFixedWidth(220)
        self.ed_team.setPlaceholderText("Your team")
        self.ed_team.setText(_load_profile().get("team", ""))
        self.ed_team.editingFinished.connect(self._save_team)
        hl.addWidget(self.ed_team, 0, Qt.AlignVCenter)
        save_btn = QPushButton("Save"); save_btn.setObjectName("hdrSave")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.clicked.connect(self._save_team)
        hl.addWidget(save_btn, 0, Qt.AlignVCenter)
        root.addWidget(header)

        # ── BANNER: riga messaggi sotto l'header (riusabile) ──
        self.banner = QLabel(""); self.banner.setObjectName("circBanner")
        self.banner.setVisible(False); self.banner.setWordWrap(True)
        root.addWidget(self.banner)

        # ── CONTENUTO: titolo + griglia circuiti ──
        body = QWidget(); body.setObjectName("circBody")
        self._body = body
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        self._body_op = QGraphicsOpacityEffect(body)
        body.setGraphicsEffect(self._body_op)
        bl = QVBoxLayout(body); bl.setContentsMargins(24, 18, 24, 18); bl.setSpacing(16)
        title = QLabel("Select a circuit"); title.setObjectName("circTitle")
        bl.addWidget(title)
        from PySide6.QtWidgets import QScrollArea
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._host = QWidget()
        self._grid = QGridLayout(self._host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(16); self._grid.setVerticalSpacing(16)
        scroll.setWidget(self._host)
        bl.addWidget(scroll, 1)
        self._empty = QLabel("No sessions yet"); self._empty.setObjectName("circCount")
        self._empty.setAlignment(Qt.AlignCenter); self._empty.setVisible(False)
        bl.addWidget(self._empty)
        root.addWidget(body, 1)

        # ── FOOTER: barra riservata (contenuti futuri) ──
        footer = QWidget(); footer.setObjectName("circFooter")
        fl = QHBoxLayout(footer); fl.setContentsMargins(24, 8, 24, 8); fl.setSpacing(8)
        fl.addStretch()
        root.addWidget(footer)

        self.setStyleSheet(
            "#circHeader{background:#16181c;border-bottom:1px solid #23262d;}"
            "#circFooter{background:#16181c;border-top:1px solid #23262d;}"
            "#circBody{background:transparent;}"
            "#appName{color:#f2f4f7;font-size:16px;font-weight:800;"
            "letter-spacing:1px;background:transparent;}"
            "#hdrTeamLbl{color:#6e727b;font-size:11px;font-weight:700;"
            "letter-spacing:2px;background:transparent;}"
            "#hdrTeam{background:#1d1f24;color:#e8eaee;border:1px solid #2c2e33;"
            "border-radius:6px;padding:4px 8px;font-size:12px;}"
            "#hdrTeam:focus{border:1px solid #45b4ef;}"
            "#hdrSave{background:#1c9fe0;color:#0b1f44;border:none;border-radius:6px;"
            "padding:5px 14px;font-size:12px;font-weight:700;}"
            "#hdrSave:hover{background:#45b4ef;}"
            "#hdrDriver{color:#e8eaee;font-size:12px;font-weight:700;background:transparent;}"
            "#circTitle{color:#f2f4f7;font-size:18px;font-weight:700;background:transparent;}"
            "#circCard{background:#1d1f24;border:none;border-radius:10px;}"
            "#circCard:hover{background:#23262d;}"
            "#circCardOn{background:#1d1f24;border-left:2px solid #45b4ef;border-radius:10px;}"
            "#circCardOn:hover{background:#23262d;}"
            "#circName{color:#f2f4f7;font-size:13px;font-weight:600;background:transparent;}"
            "#circCount{color:#f2f4f7;font-size:11px;background:transparent;}"
            "#circCountOn{color:#f2f4f7;font-size:11px;background:transparent;}")
        self._update_gate()

    # ── banner messaggi (riusabile) ───────────────────────────────────
    def set_banner(self, text, level="info"):
        cols = {"info": ("#0e2a3a", "#45b4ef"), "warn": ("#2e2410", "#f0a23a"),
                "error": ("#2e1416", "#ff5b5b")}
        bg, fg = cols.get(level, cols["info"])
        self.banner.setStyleSheet(
            "#circBanner{background:%s;color:%s;font-size:12px;font-weight:600;"
            "padding:8px 24px;border:none;}" % (bg, fg))
        self.banner.setText(text); self.banner.setVisible(True)

    def clear_banner(self):
        self.banner.setVisible(False)

    def set_driver(self, name):
        """Nome pilota (auto dal gioco) mostrato in header."""
        name = (name or "").strip().upper()
        if name and self.lb_driver.text() != name:
            self.lb_driver.setText(name)

    def _update_gate(self):
        """Team obbligatorio: senza team i circuiti sono bloccati e opacizzati."""
        if get_team():
            self.clear_banner(); self._body.setEnabled(True)
            self._body_op.setOpacity(1.0)
        else:
            self.set_banner("Enter your team name above to access the circuits", "warn")
            self._body.setEnabled(False)
            self._body_op.setOpacity(0.25)

    def _save_team(self):
        t = self.ed_team.text().strip()[:30]
        d = _load_profile(); d["team"] = t; _save_profile(d)
        self._update_gate()



    def set_circuits(self, items):
        while self._grid.count():
            it = self._grid.takeAt(0); w = it.widget()
            if w:
                w.deleteLater()
        self._empty.setVisible(not items)
        cols = self._COLS
        for c in range(cols):
            self._grid.setColumnStretch(c, 1)
        for i, (track, count, logo) in enumerate(items):
            self._grid.addWidget(_CircuitCard(track, count, logo, self._on_pick),
                                 i // cols, i % cols)
        self._grid.setRowStretch((len(items) // cols) + 1, 1)
