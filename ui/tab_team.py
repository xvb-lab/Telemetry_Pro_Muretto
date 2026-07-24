"""ui/tab_team.py — scheda estratta 1:1 da window.py."""

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


class _TeamTab(QWidget):
    """Tab 'Team': importa sessioni condivise dai compagni (.zip) in una
    cartella ISOLATA. Servono solo al confronto telemetrie: niente learning,
    niente online. Compaiono in Overview sotto la card REF."""
    def __init__(self, win=None):
        super().__init__(win)
        self._win = win
        root = QVBoxLayout(self); root.setContentsMargins(16, 14, 16, 14); root.setSpacing(10)
        title = QLabel("TEAM SESSIONS"); title.setObjectName("engHdr")
        title.setStyleSheet("color:#cfe8ff;font-size:12px;font-weight:800;letter-spacing:2px;")
        root.addWidget(title)
        note = QLabel("Import a session a teammate shared with you (.zip). Imported "
                      "sessions stay local and isolated \u2014 they are only used to "
                      "compare telemetry, never for the engineer or online. "
                      "They appear in Overview under the blue REF card.")
        note.setObjectName("engStatus"); note.setWordWrap(True)
        # colore INLINE: gli stili #engStatus/#engLang sono definiti solo nello
        # stylesheet della tab ingegnere, che NON raggiunge questa tab (widget
        # separato in main_tabs). Senza colore inline il testo cadeva sul nero
        # di default e spariva sullo sfondo scuro.
        note.setStyleSheet("color:#c3c8d2;font-size:12px;background:transparent;")
        root.addWidget(note)

        row = QHBoxLayout()
        self._btn_load = QPushButton("Load session from team\u2026")
        self._btn_load.setObjectName("engLang"); self._btn_load.setFixedHeight(30)
        self._btn_load.setStyleSheet(
            "color:#b8bcc4;background:rgba(255,255,255,0.06);"
            "border:1px solid rgba(255,255,255,0.10);border-radius:8px;"
            "padding:4px 12px;font-weight:800;")
        self._btn_load.setCursor(Qt.PointingHandCursor)
        self._btn_load.clicked.connect(self._load)
        row.addWidget(self._btn_load); row.addStretch()
        root.addLayout(row)
        root.addStretch()
        self._bgphoto9 = None

    # SFONDO come la pagina circuito (rich. utente 24/07 sera): foto
    # della pista a 0.50 sul blu #000833
    _PHOTO_DIR9 = Path(__file__).resolve().parent.parent / "assets" / "trackcards"

    def set_bg(self, bgkey):
        pm = None
        if bgkey:
            for ext in ("jpg", "jpeg", "png", "webp"):
                p = self._PHOTO_DIR9 / ("%s.%s" % (bgkey, ext))
                if p.exists():
                    _pm = QPixmap(str(p))
                    if not _pm.isNull():
                        pm = _pm
                        break
        self._bgphoto9 = pm
        self.update()

    def paintEvent(self, e):
        from PySide6.QtCore import QRect
        p = QPainter(self)
        r = self.rect()
        p.fillRect(r, QColor("#000833"))
        pm = getattr(self, "_bgphoto9", None)
        if pm is not None and not pm.isNull():
            scaled = pm.scaled(r.size(), Qt.KeepAspectRatioByExpanding,
                               Qt.SmoothTransformation)
            sx = max(0, (scaled.width() - r.width()) // 2)
            sy = max(0, (scaled.height() - r.height()) // 2)
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.setOpacity(0.50)
            p.drawPixmap(r, scaled, QRect(sx, sy, r.width(), r.height()))
            p.setOpacity(1.0)
        p.end()
        super().paintEvent(e)

    def _load(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        try:
            from core import team_share as _ts
        except Exception:
            return
        f, _ = QFileDialog.getOpenFileName(self, "Load team session", "",
                                           "Team session (*.zip)")
        if not f:
            return
        p = _ts.import_zip(f)
        if p:
            if self._win is not None:
                try:
                    self._win._reload_team_sessions()   # aggiorna l'elenco team
                except Exception:
                    pass
                try:
                    self._win._reload_sessions()        # overview legacy
                except Exception:
                    pass
                ap = getattr(self._win, "_app_page", None)
                if ap is not None:
                    try:
                        ap._reload_sessions()           # card "team" nella lista nuova
                    except Exception:
                        pass
            QMessageBox.information(self, "Team", "Session imported.")
        else:
            QMessageBox.warning(self, "Team", "Could not import this file.")
