"""
telemetry/window.py — Finestra telemetria (review).

Navigazione compatta a menu a cascata, tutto in una barra:
    Sessione ▾ · Stint ▾ · Giro ▾        (+ ↻  🗑)
Sotto: un solo set di tab  Tempi · Gomme · Energia · Guida · Mappa.

Cascata:
  Sessione  -> carica i giri, riempie il menu Stint (Stint 1, 2, ...)
  Stint     -> riempie il menu Giro coi giri dello stint (default: più veloce);
               aggiorna Tempi (tabella stint) ed Energia (consumi stint)
  Giro      -> aggiorna Gomme / Guida / Mappa sul giro scelto;
               Tempi evidenzia la riga del giro.

Grafici in QPainter, nessuna dipendenza esterna.
"""
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
from PySide6.QtCore import Qt, QRectF, QPointF, QTimer, QSize, Signal
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
from ui.tab_circuits import _CircuitMenu
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

from . import db as _db
from .reader import TelemetryReader
from core.classes import class_tag

# colori classe (allineati al widget mappa)


# Link supporto allo sviluppo (modificabili)
_DONATE_URL = "https://paypal.me/Jonathanuk"     # link donazioni
_GITHUB_URL = "https://github.com/xvb-lab/Telemetry_Pro_Muretto"
_DOCS_URL = "https://xvb-lab.github.io/Telemetry_Pro_Docs/"
_APP_VERSION = "v0.3b"
# ── controllo aggiornamenti: ultima release pubblicata su GitHub ──
_GH_LATEST_API = "https://api.github.com/repos/xvb-lab/Telemetry_Pro_Muretto/releases/latest"
_GH_RELEASES_URL = "https://github.com/xvb-lab/Telemetry_Pro_Muretto/releases"


# ogni categoria = una tab a sé (comparazione Selected vs Compare)
_TAB_GROUPS = [
    ("Pedals", []),
    ("Speed",  ["S1 speed (km/h)", "S2 speed (km/h)", "S3 speed (km/h)"]),
    ("VE",     ["VE used (%)"] + [f"S{s} VE (%)" for s in (1, 2, 3)]),
    ("Fuel",   ["Fuel used (L)"] + [f"S{s} fuel (L)" for s in (1, 2, 3)]),
    ("Hybrid", ["SOC start (%)", "SOC end (%)", "Regen gained (kWh)", "Boost used (kWh)"]
               + [f"S{s} regen (kWh)" for s in (1, 2, 3)]
               + [f"S{s} boost (kWh)" for s in (1, 2, 3)]
               + [f"S{s} SOC \u0394 (%)" for s in (1, 2, 3)]),
    ("Tyres",  [f"S{s} tyre \u00b0C" for s in (1, 2, 3)]
               + [f"S{s} press kPa" for s in (1, 2, 3)]
               + [f"S{s} wear %" for s in (1, 2, 3)]),
    ("Brakes", [f"S{s} brake \u00b0C" for s in (1, 2, 3)]),
    ("Suspension", []),
    ("Gear", []),
    ("Steering", []),
    ("RPM", []),
    ("Aids", []),
    ("G-G", []),
]









































# ── grafici ───────────────────────────────────────────────────────────────




# ── viste (persistenti, aggiornate via set_stint / set_lap) ────────────────
























































# ── finestra ──────────────────────────────────────────────────────────────

# ── LIVE: dati stint corrente in tempo reale dal reader ──────────────────────














# Etichetta leggibile del LAYOUT per le descrizioni sessione. Chiavi = stem SVG
# in settings/trackmap (un SVG per layout). "" = layout principale del circuito.


















class _WhiteSvgBox(_SvgBox):
    """Come _SvgBox ma rende l'SVG tutto BIANCO (tinge via SourceIn),
    qualunque sia il colore originale dei tracciati."""
    def paintEvent(self, e):
        if self._r is None:
            return
        W, H = self.width(), self.height()
        if W <= 0 or H <= 0:
            return
        dpr = self.devicePixelRatioF()
        key = (W, H, round(dpr, 3), id(self._r), "white")
        if self._pix is None or self._pix_key != key:
            ds = self._r.defaultSize()
            dw = ds.width() or 1; dh = ds.height() or 1
            s = min(W / dw, H / dh)
            w = dw * s; h = dh * s
            pix = QPixmap(max(1, int(W * dpr)), max(1, int(H * dpr)))
            pix.setDevicePixelRatio(dpr)
            pix.fill(Qt.transparent)
            pp = QPainter(pix); pp.setRenderHint(QPainter.Antialiasing, True)
            self._r.render(pp, QRectF((W - w) / 2.0, (H - h) / 2.0, w, h))
            pp.setCompositionMode(QPainter.CompositionMode_SourceIn)
            pp.fillRect(pix.rect(), QColor("#ffffff"))   # tinta bianca
            pp.end()
            self._pix = pix; self._pix_key = key
        p = QPainter(self)
        p.drawPixmap(0, 0, self._pix)
        p.end()


class _TrackMapBox(_SvgBox):
    """Come _SvgBox ma con rotazione: ruota attorno al centro e adatta alla bbox
    ruotata, così non si stira MAI e non viene tagliato."""
    def __init__(self, rot=0.0, min_h=0):
        super().__init__(min_h)
        self._rot = float(rot or 0.0)

    def paintEvent(self, e):
        if self._r is None:
            return
        W, H = self.width(), self.height()
        if W <= 0 or H <= 0:
            return
        import math
        ds = self._r.defaultSize()
        dw = ds.width() or 1; dh = ds.height() or 1
        a = math.radians(self._rot)
        rw = abs(dw * math.cos(a)) + abs(dh * math.sin(a))
        rh = abs(dw * math.sin(a)) + abs(dh * math.cos(a))
        s = min(W / rw, H / rh) if (rw and rh) else 1.0
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.translate(W / 2.0, H / 2.0)
        p.rotate(self._rot)
        p.scale(s, s)
        self._r.render(p, QRectF(-dw / 2.0, -dh / 2.0, dw, dh))
        p.end()






# Layout "varianti" di un circuito base: descrizione in card con accent arancione.




# alias nome pista -> file PNG (mappe "belle" già orientate). Sottostringa nel
# nome in-gioco. Monza/Sebring non hanno PNG: fallback all'SVG.




class _PngBox(QLabel):
    """Mostra un PNG mantenendo le proporzioni (mai stirato), centrato."""
    _pix_cache = {}

    def __init__(self, path, w, h):
        super().__init__()
        self.setFixedSize(w, h)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background:transparent;")
        key = (str(path), w, h)
        pm = _PngBox._pix_cache.get(key)
        if pm is None:
            try:
                src = QPixmap(str(path))
                pm = src.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            except Exception:
                pm = QPixmap()
            _PngBox._pix_cache[key] = pm
        if not pm.isNull():
            self.setPixmap(pm)












# Traduzione etichette pace (FRONT-END). Cambia qui per rinominare le bande.













# icona EXPORT: freccia in su che esce da un vassoio (condividi/esporta)






















# cerchio (come la gomma) con goccia benzina dentro, viola
from ui.icons import FUEL_WEIGHT_SVG as _FUEL_WEIGHT_SVG















# flag "disponibilità" aiuti: ridondanti con le mappe vere -> nascosti































class _TrackRow_OLD(QFrame):
    """(vecchia versione, non usata)"""

    def __init__(self, track, classes, on_pick):
        super().__init__()
        self.setObjectName("commTrack")
        self.setStyleSheet("#commTrack{background:#16181c;border:none;"
                           "border-radius:8px;}")
        h = QHBoxLayout(self); h.setContentsMargins(12, 8, 14, 8); h.setSpacing(10)
        disp = (track or "").replace("-", " ")
        logo = _SvgBox(); logo.setFixedSize(50, 32)
        f = _ov_tracklogo_file(disp)
        logo.load(str(f) if f else _EMPTY_LOGO_SVG)
        h.addWidget(logo, 0, Qt.AlignVCenter)
        nm = QLabel(_track_short(track))
        nm.setStyleSheet("color:#f2f4f7;font-size:13px;font-weight:700;"
                         "background:transparent;")
        nm.setMinimumWidth(150)
        h.addWidget(nm)
        h.addStretch()
        for c in classes:
            chip = _ClassChip(c, lambda cc=c: on_pick(track, cc))
            h.addWidget(chip); h.addSpacing(5)


_DEMO_RANK = False  # ANTEPRIMA: True riempie la classifica con 10 posizioni finte


def _demo_rank_rows(n=10):
    """Righe finte per vedere la classifica piena (provvisorio)."""
    names = ["Jonathan Sanfilippo", "M. Rossi", "A. Bianchi", "L. Verdi",
             "K. Muller", "P. Dubois", "S. Tanaka", "R. Costa", "D. Novak",
             "T. Olsen", "G. Ferraro", "H. Schmidt"]
    teams = ["Sabelt Sim Racing", "Motul Racing", "Falcon Esports", "Apex GT",
             "Nordschleife", "Sarthe Racing", "Fuji Speed", "Interlagos GP",
             "Praha Race", "Nordic Sim", "Roma Corse", "Berlin RT"]
    base = 112306   # 1:52.306 in ms
    out = []
    for i in range(n):
        ms = base + i * 220 + (i * i) % 90
        s1 = 37100 + i * 40; s2 = 38400 + i * 55; s3 = ms - s1 - s2
        out.append({
            "player": names[i % len(names)],
            "team": teams[i % len(teams)],
            "car": "Porsche 911 GT3 R LMGT3",
            "compounds4": "M,M,M,M", "compound": "M",
            "tyre_state_pct": 86.0,
            "fuel_l": 17.0 + (i % 4),
            "lap_ms": ms, "s1_ms": s1, "s2_ms": s2, "s3_ms": s3,
        })
    return out












def _state_col(p):
    """Colore per lo stato gomme: verde alto, ambra medio, rosso basso."""
    if p is None:
        return "#cfd2d8"
    if p >= 70:
        return "#2ecc71"
    if p >= 40:
        return "#f0a23a"
    return "#ff5b5b"


def _load_info_html(tyre_state, load_pct, load_kind, team):
    """Riga testo: stato gomme % · VE/Fuel residuo % · team (compound a parte,
    via widget TyreCell)."""
    info = []
    if tyre_state is not None:
        info.append("Tyres <b style='color:%s'>%.0f%%</b>"
                    % (_state_col(tyre_state), tyre_state))
    if load_pct is not None and load_kind:
        info.append("%s <b style='color:#cfd2d8'>%.0f%%</b>" % (load_kind, load_pct))
    tm = (team or "").strip()
    if tm:
        info.append("<span style='color:#9aa0aa'>%s</span>" % tm)
    return "  &nbsp;\u00b7&nbsp;  ".join(info)


try:
    from core.paths import PROFILE_FILE as _PROFILE_FILE
except Exception:
    _PROFILE_FILE = Path(__file__).resolve().parent.parent / "settings" / "profile.json"










_UNSET = object()


class _LegacyWindow(QMainWindow):
    # aggiornamenti: (tag, url) emesso dal thread di check -> UI thread
    _sig_update_found = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("LMU Telemetry Pro")
        self.resize(900, 640)
        self._con = None
        self._car_class = ""
        self._groups = {}
        self._stint_keys = []
        self._lap_ids = []
        self._cmp_ids = []
        self._user_enabled = True

        central = QWidget(); self.setCentralWidget(central)
        croot = QVBoxLayout(central); croot.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        croot.addWidget(self.stack, 1)
        # ── footer: supporto allo sviluppo / donazioni ──
        foot = QWidget(); foot.setObjectName("appFooter")
        fl = QHBoxLayout(foot); fl.setContentsMargins(16, 6, 16, 6); fl.setSpacing(12)
        _flab = QLabel("LMU Telemetry Pro  %s  \u00b7  by Jonathan Sanfilippo"
                       % _APP_VERSION)
        _flab.setStyleSheet("color:#6e727b;font-size:11px;background:transparent;")
        fl.addWidget(_flab)
        # ── notifica AGGIORNAMENTO: compare solo se GitHub ha una release
        #    piu' nuova; click -> pagina Releases ──
        self._upd_btn = QPushButton("")
        self._upd_btn.setCursor(Qt.PointingHandCursor)
        self._upd_btn.setVisible(False)
        self._upd_btn.setStyleSheet(
            "QPushButton{color:#37d67a;font-size:11px;font-weight:bold;"
            "background:transparent;border:none;padding:0 6px;}"
            "QPushButton:hover{color:#5ee897;}")
        fl.addWidget(self._upd_btn)
        self._sig_update_found.connect(self._on_update_found)
        QTimer.singleShot(4000, self._check_updates_async)
        fl.addStretch()
        _fsup = QLabel("Support development:")
        _fsup.setStyleSheet("color:#8a8f98;font-size:11px;background:transparent;")
        fl.addWidget(_fsup)
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl, QPropertyAnimation, QEasingCurve
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        self._donate_btn = QPushButton("\u2764  DONATE")
        self._donate_btn.setObjectName("donateBtn")
        self._donate_btn.setCursor(Qt.PointingHandCursor)
        self._donate_btn.setToolTip("Support the development \u2014 grazie!")
        self._donate_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(_DONATE_URL)))
        fl.addWidget(self._donate_btn)
        # animazione "respiro" (pulsa per farsi notare)
        _eff = QGraphicsOpacityEffect(self._donate_btn)
        self._donate_btn.setGraphicsEffect(_eff)
        self._donate_anim = QPropertyAnimation(_eff, b"opacity")
        self._donate_anim.setDuration(1100)
        self._donate_anim.setStartValue(1.0)
        self._donate_anim.setKeyValueAt(0.5, 0.5)
        self._donate_anim.setEndValue(1.0)
        self._donate_anim.setLoopCount(-1)
        self._donate_anim.setEasingCurve(QEasingCurve.InOutSine)
        self._donate_anim.start()
        _gh = QLabel('<a href="%s" style="color:%s;text-decoration:none;">GitHub</a>'
                     % (_GITHUB_URL, _ACCENT))
        _gh.setOpenExternalLinks(True)
        _gh.setStyleSheet("font-size:11px;font-weight:700;background:transparent;")
        fl.addSpacing(4); fl.addWidget(_gh)
        _doc = QLabel('<a href="%s" style="color:%s;text-decoration:none;">Doc</a>'
                      % (_DOCS_URL, _ACCENT))
        _doc.setOpenExternalLinks(True)
        _doc.setStyleSheet("font-size:11px;font-weight:700;background:transparent;")
        fl.addSpacing(10); fl.addWidget(_doc)
        croot.addWidget(foot)

        review_page = QWidget()
        root = QVBoxLayout(review_page)

        top = QHBoxLayout()
        self.btn_menu = QPushButton("\u2039 Circuits"); self.btn_menu.setObjectName("backBtn")
        self.btn_menu.setCursor(Qt.PointingHandCursor)
        self.btn_menu.setToolTip("Back to circuit selection")
        self.btn_menu.clicked.connect(self._show_menu)
        top.addWidget(self.btn_menu)
        top.addSpacing(8)
        self.btn_rec = QPushButton("START"); self.btn_rec.setObjectName("recBtn")
        self.btn_rec.setCursor(Qt.PointingHandCursor)
        self.btn_rec.setToolTip("Start/stop telemetry recording")
        self.btn_rec.setStyleSheet(
            "QPushButton{padding:4px 14px;border-radius:4px;background:transparent;font-weight:bold;}"
            "QPushButton[rec=\"off\"]{color:#22e06a;border:1px solid #22e06a;}"
            "QPushButton[rec=\"on\"]{color:#ff3b30;border:1px solid #ff3b30;}"
            "QPushButton[rec=\"wait\"]{color:#f0a23a;border:1px solid #f0a23a;}")
        self.btn_rec.clicked.connect(self._toggle_rec)
        self.btn_rec.setFixedWidth(96)   # larghezza fissa: START/WAITING/STOP non spostano gli altri
        top.addWidget(self.btn_rec)
        top.addSpacing(8)
        self.learn_status = QLabel(""); self.learn_status.setObjectName("learnStatus")
        self.learn_status.setStyleSheet(
            "#learnStatus{color:#45b4ef;font-weight:bold;font-size:12px;}")
        top.addWidget(self.learn_status)
        top.addSpacing(12)
        self.banner = QLabel(""); self.banner.setObjectName("statusBanner")
        self.banner.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        top.addWidget(self.banner, 1)
        # card di riferimento sempre attive: ref + pace (real lap rimosso)
        self._show_ref = True
        self._show_pace = True
        top.addSpacing(12)
        self.btn_export = QPushButton("Export CSV"); self.btn_export.setObjectName("backBtn")
        self.btn_export.setCursor(Qt.PointingHandCursor)
        self.btn_export.setToolTip("Export the selected lap (all channels) to CSV")
        self.btn_export.clicked.connect(self._export_csv)
        top.addWidget(self.btn_export)
        self.btn_export_ld = QPushButton("Export i2"); self.btn_export_ld.setObjectName("backBtn")
        self.btn_export_ld.setCursor(Qt.PointingHandCursor)
        self.btn_export_ld.setToolTip("Export the current stint to MoTeC i2 (.ld)")
        self.btn_export_ld.clicked.connect(self._export_motec)
        top.addWidget(self.btn_export_ld)
        # combo "motore" (non mostrati): la selezione la guida la board nell'Overview
        from PySide6.QtWidgets import QListView
        self.cmb_stint = QComboBox(self); self.cmb_stint.setVisible(False)
        self.cmb_lap = QComboBox(self); self.cmb_lap.setVisible(False)
        self.cmb_cmp = QComboBox(self); self.cmb_cmp.setVisible(False)
        for _cmb in (self.cmb_stint, self.cmb_lap, self.cmb_cmp):
            _cmb.setMaxVisibleItems(12)
            _lv = QListView(); _cmb.setView(_lv)
        root.addLayout(top)

        # sotto-tab telemetria (tutte le tab attuali, senza Overview)
        self.tabs = QTabWidget()
        # colori grafici salvati dall'utente (pick-color sulla mappa)
        try:
            from telemetry import common as _c
            from core.profile import _load_profile
            _cc = _load_profile().get("chart_colors") or {}
            if _cc.get("sel"):
                _c._SEL_COL = _cc["sel"]; _c._CUSTOM_SEL = True
            if _cc.get("cmp"):
                _c._CMP_COL = _cc["cmp"]; _c._CUSTOM_CMP = True
            if _cc.get("track"):
                _c._TRK_COL = _cc["track"]
        except Exception:
            pass
        self._data = _LapData()
        self._stint_new_cache = {}
        self._cat = []
        self._cat_lap = _UNSET; self._cat_cmp = _UNSET
        self._cat_dirty_lap = set(); self._cat_dirty_cmp = set()
        self._overview = _OverviewTab()
        self._overview.board.set_callbacks(self._board_stint, self._board_pick)
        # Worksheet multi-canale (primo tab): vista a canali impilati
        self._worksheet = _WorksheetTab(self._data)
        self._worksheet.map_w.color_cb = self._pick_color
        self.tabs.addTab(self._worksheet, "Worksheet")
        self._cat.append(self._worksheet)
        _TRACE = {"Speed": ("speed", "km/h"), "VE": ("ve", "%"),
                  "Fuel": ("fuel", "L"), "Hybrid": ("soc", "%"),
                  "Tyres": ("tyre_t", "\u00b0C"), "Brakes": ("brake_t", "\u00b0C"),
                  "Gear": ("gear", ""), "Steering": ("steer", "\u00b0"),
                  "RPM": ("rpm", "rpm")}
        for label, metrics in _TAB_GROUPS:
            if label == "Tyres":
                t = _TyresTab(self._data)
                t.chart.color_cb = self._pick_color
                t.map_w.color_cb = self._pick_color
            elif label == "Pedals":
                t = _PedalsTab(self._data)
                t.map_w.color_cb = self._pick_color
            elif label == "G-G":
                t = _GGTab(self._data)
            elif label == "Aids":
                t = _TraceTab(self._data, "tc_active", "", "Aids",
                              modes=[("TC active", "tc_active"),
                                     ("ABS active", "abs_active"),
                                     ("Brake bias", "brake_bias"),
                                     ("TC map", "tc_map"), ("ABS map", "abs_map")])
                t.chart.color_cb = self._pick_color
                t.map_w.color_cb = self._pick_color
            elif label == "Brakes":
                t = _BrakesTab(self._data)
                t.chart.color_cb = self._pick_color
                t.map_w.color_cb = self._pick_color
            elif label == "Suspension":
                t = _SuspTab(self._data)
                t.chart.color_cb = self._pick_color
                t.map_w.color_cb = self._pick_color
            elif label in _TRACE:
                col, unit = _TRACE[label]
                t = _TraceTab(self._data, col, unit, label)
                t.chart.color_cb = self._pick_color
                t.map_w.color_cb = self._pick_color
            else:
                t = _CatTable(self._data, metrics, show_chart=(label != "Times"),
                              tyre_modes=(label == "Tyres"), pedal=(label == "Times"))
                if t.chart is not None:
                    t.chart.color_cb = self._pick_color
                if t.map_w is not None:
                    t.map_w.color_cb = self._pick_color
            self.tabs.addTab(t, label)
            self._cat.append(t)
        # Delta-T (Compare - Selected) vs distanza
        self._delta_tab = _DeltaTab(self._data)
        self._delta_tab.map_w.color_cb = self._pick_color
        self.tabs.addTab(self._delta_tab, "Delta")
        self._cat.append(self._delta_tab)
        # Engineer: spostata nelle tab principali (in fondo a destra)
        self._engineer = _EngineerTab(self)
        # sincronizzazione zoom + cursori A/B fra tutti i grafici a traccia
        self._charts = []
        for t in self._cat:
            ch = getattr(t, "chart", None)
            if isinstance(ch, _TraceChart):
                self._charts.append(ch)
            for ch2 in getattr(t, "charts", []):     # tab multi-chart (Worksheet)
                if isinstance(ch2, _TraceChart):
                    self._charts.append(ch2)
        for ch in self._charts:
            ch._zoom_cb = lambda v, src=ch: self._broadcast_view(v, src)
            ch._ab_cb = lambda a, b, src=ch: self._broadcast_ab(a, b, src)

        # grafici aggiunti DINAMICAMENTE dal Worksheet (+): stessi sync
        def _reg_ws(ch, _self=self):
            if ch not in _self._charts:
                _self._charts.append(ch)
                ch._zoom_cb = lambda v, src=ch: _self._broadcast_view(v, src)
                ch._ab_cb = lambda a, b, src=ch: _self._broadcast_ab(a, b, src)

        def _unreg_ws(ch, _self=self):
            try:
                _self._charts.remove(ch)
            except ValueError:
                pass
        self._worksheet.register_chart_cb = _reg_ws
        self._worksheet.unregister_chart_cb = _unreg_ws
        # ── sezione Settings (assetto .svm) — placeholder, riempita col .svm ──
        self.settings_page = _SettingsTab(self)
        # ── tab principali: Overview | Telemetry | Settings | Database ──
        self.main_tabs = QTabWidget(); self.main_tabs.setObjectName("mainTabs")
        self.main_tabs.addTab(self._overview, "Overview")
        self.main_tabs.addTab(self.tabs, "Telemetry")
        self.main_tabs.addTab(self.settings_page, "Settings")
        # tab "Database" (CSV pace OhneSpeed) rimossa
        from ui.tab_overlay import _OverlayTab
        self._overlaytab = _OverlayTab(self)
        self.main_tabs.addTab(self._overlaytab, "Overlay")
        self._community = _CommunityTab()
        self.main_tabs.addTab(self._community, "Community")
        self._teamtab = _TeamTab(self)
        self.main_tabs.addTab(self._teamtab, "Team")
        # Engineer NON e' piu' una tab: vive come riga nella tab Overlay.
        # L'oggetto _engineer resta creato (fa da motore dell'overlay).
        root.addWidget(self.main_tabs)
        self._graph_views = []

        self._review_page = review_page
        self.stack.addWidget(review_page)        # index 0: vista Review
        self._track_filter = None
        self._menu = _CircuitMenu(self._enter_circuit)
        self.stack.addWidget(self._menu)         # index 1: menu circuiti
        self.live = None

        self.setStyleSheet(
            f"QMainWindow,QWidget{{background:{_BG};color:{_FG};font-family:'Archivo SemiExpanded';}}"
            f"QComboBox,QPushButton{{background:#1d1f24;color:{_FG};border:none;"
            f"padding:5px 10px;border-radius:6px;}}"
            f"QComboBox:hover,QPushButton:hover{{border-color:#3a3d43;}}"
            f"QComboBox QAbstractItemView{{background:#1b1d20;color:{_FG};"
            f"selection-background-color:#2a2c30;outline:0;}}"
            f"QComboBox QAbstractItemView QScrollBar:vertical{{background:transparent;width:10px;margin:0;}}"
            f"QComboBox QAbstractItemView QScrollBar::handle:vertical{{background:#313338;"
            f"border-radius:5px;min-height:24px;}}"
            f"QComboBox QAbstractItemView QScrollBar::add-line,"
            f"QComboBox QAbstractItemView QScrollBar::sub-line{{height:0;}}"
            f"QLabel#barCap{{color:#6e727b;font-size:10px;font-weight:700;letter-spacing:1px;"
            f"padding:0 7px 0 0;}}"
            f"QComboBox#barCombo{{background:#1d1f24;border:none;"
            f"padding:5px 10px;border-radius:8px;}}"
            f"QComboBox#barCombo:hover{{border-color:#3a3d43;}}"
            f"QPushButton#iconBtn{{font-size:15px;padding:4px 9px;}}"
            f"QPushButton#swatch{{border:none;border-radius:5px;padding:0;}}"
            f"QPushButton#modeBtn{{padding:3px 12px;font-size:12px;}}"
            f"QPushButton#modeBtn:checked{{background:{_ACCENT};color:#09090b;border-color:{_ACCENT};}}"
            f"QPushButton#backBtn{{padding:5px 14px;}}"
            f"QTableWidget{{background:{_BG};alternate-background-color:#191a1d;"
            f"gridline-color:transparent;border:0;}}"
            f"QTableWidget::item{{padding:7px 12px;border:0;}}"
            f"QTableWidget::item:selected{{background:#2a2c30;color:{_FG};}}"
            f"QHeaderView::section{{background:{_BG};color:#a6a9af;border:0;"
            f"border-bottom:1px solid {_GRID};padding:8px 12px;"
            f"font-weight:600;}}"
            f"QTabWidget::pane{{border:0;border-top:0;}}"
            f"QTabBar::tab{{background:transparent;color:#a6a9af;padding:8px 16px;"
            f"border-bottom:2px solid transparent;}}"
            f"QTabBar::tab:hover{{color:{_FG};}}"
            f"QTabBar::tab:selected{{color:{_FG};border-bottom:2px solid {_ACCENT};}}"
            f"QScrollBar:vertical{{background:transparent;width:0px;margin:0;}}"
            f"QScrollBar::handle:vertical{{background:#313338;border-radius:5px;min-height:24px;}}"
            f"QScrollBar::add-line,QScrollBar::sub-line{{height:0;}}"
            f"QScrollBar:horizontal{{height:0;background:transparent;}}"
            f"QWidget#appFooter{{background:#0d0e10;border-top:1px solid #232529;}}"
            f"QPushButton#donateBtn{{background:#ff4d6d;color:#ffffff;border:none;"
            f"border-radius:13px;padding:5px 18px;font-size:12px;font-weight:800;"
            f"letter-spacing:.5px;}}"
            f"QPushButton#donateBtn:hover{{background:#ff6b85;}}")

        self._cur_sess = -1
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.cmb_stint.currentIndexChanged.connect(self._on_stint)
        self.cmb_lap.currentIndexChanged.connect(self._on_lap)
        self.cmb_cmp.currentIndexChanged.connect(self._on_cmp)

        self._sessions = []
        self._ref_available = False
        self._sel_none = False
        self._cmp_none = False
        self._reload_sessions()
        self._show_menu()
        QTimer.singleShot(400, self._start_learn_scan)   # impara sessioni mancanti

        # aggiorna la Review durante la sessione (nuovi giri), preservando la selezione
        self._rev_timer = QTimer(self)
        self._rev_timer.setInterval(8000)
        self._rev_timer.timeout.connect(self._live_refresh)
        self._rev_timer.start()
        # sincronizza il bottone AVVIA/STOP (riflette lo stop automatico)
        self._rec_timer = QTimer(self)
        self._rec_timer.setInterval(700)
        self._rec_timer.timeout.connect(self._sync_rec_btn)
        self._rec_timer.timeout.connect(self._capture_driver)
        self._rec_timer.start()
        # auto-best: quando esce un nuovo best, confronta best vs penultimo best
        self._auto_last_best = None
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(1000)
        self._auto_timer.timeout.connect(self._auto_best_tick)
        self._auto_timer.start()

        # ── recorder telemetria ──────────────────────────────────────────
        # La registrazione su .lmtel è gestita qui (processo telemetry, sempre
        # attivo quando l'app è aperta). Se anche il widget 'strategy' è
        # abilitato lascia a lui la registrazione, per non scrivere due volte
        # sullo stesso file.
        self._recorder = None
        try:
            from core.config import get_config
            _cfg = get_config()
            scfg = _cfg.widget("strategy")
            from .recorder import TelemetryRecorder
            self._recorder = TelemetryRecorder(
                margin_laps=scfg.get("save_margin", 2.0),
                window=scfg.get("moving_window", 3),
                record=scfg.get("record", True),
            )
        except Exception:
            self._recorder = None
        self._sync_rec_btn()

        # ════════════════════════════════════════════════════════════════
        #  SKIN GRAFICA NUOVA sui widget ORIGINALI (solo stile, logica intatta)
        #  Stessi object name dell'overview -> basta sostituire il QSS vecchio
        #  con quello nuovo (_OV_BOARD_QSS, look glass + accenti rossi).
        # ════════════════════════════════════════════════════════════════
        try:
            self.setStyleSheet("QMainWindow{background:#0e0f12;}")
            self._overview.setObjectName("ovRoot")
            self._overview.setStyleSheet("#ovRoot{background:#0e0f12;}" + _OV_BOARD_QSS)
            self._overview.board.setStyleSheet(_OV_BOARD_QSS)
            self._overview.board.tabs_bar.setStyleSheet(_OV_BOARD_QSS)
            self.main_tabs.setStyleSheet(
                "#mainTabs::pane{background:#0e0f12;border:none;}"
                "#mainTabs>QTabBar{background:transparent;}"
                "#mainTabs>QTabBar::tab{background:rgba(255,255,255,0.06);"
                "color:#cfd6e2;padding:7px 16px;margin-right:4px;border:none;"
                "border-radius:9px;font-weight:700;}"
                "#mainTabs>QTabBar::tab:selected{background:rgba(255,255,255,0.20);"
                "color:#ffffff;border-left:2px solid #ff1d43;}"
                "#mainTabs>QTabBar::tab:hover{background:rgba(255,255,255,0.12);}")
            self.tabs.setStyleSheet(
                "QTabWidget::pane{background:#0e0f12;border:none;}"
                "QTabBar{background:transparent;}"
                "QTabBar::tab{background:rgba(255,255,255,0.06);color:#cfd6e2;"
                "padding:5px 11px;margin-right:3px;border:none;border-radius:8px;"
                "font-weight:600;}"
                "QTabBar::tab:selected{background:rgba(255,255,255,0.20);"
                "color:#ffffff;border-left:2px solid #ff1d43;}"
                "QTabBar::tab:hover{background:rgba(255,255,255,0.12);}")
        except Exception:
            pass

    def _toggle_rec(self):
        if not getattr(self, "_recorder", None):
            return
        if self._recorder.is_armed():
            self._recorder.disarm()
        else:
            self._recorder.arm()
        self._sync_rec_btn()

    def _capture_driver(self):
        """Appena c'è una sessione in pista, legge il pilota dal session_meta
        del file in registrazione (una volta per file), lo salva in profilo e
        lo mostra in header accanto al team."""
        rec = getattr(self, "_recorder", None)
        if not (rec and rec.is_armed()):
            return
        try:
            f = rec.current_file()
        except Exception:
            f = None
        if not f or f == getattr(self, "_drv_cap_file", None):
            return
        try:
            con = sqlite3.connect(f)
            r = con.execute("SELECT driver FROM session_meta WHERE id=1").fetchone()
            con.close()
            drv = (r[0] if r else "") or ""
        except Exception:
            drv = ""
        if not drv:
            return                       # meta non ancora scritta: riprova dopo
        self._drv_cap_file = f           # catturato per questo file
        prof = _load_profile()
        if prof.get("driver") != drv:
            prof["driver"] = drv; _save_profile(prof)
        menu = getattr(self, "_menu", None)
        if menu is not None:
            menu.set_driver(drv)

    def _eng_log(self, text):
        eng = getattr(self, "_engineer", None)
        if eng is not None:
            try:
                eng.log(text)
            except Exception:
                pass

    def _start_learn_scan(self):
        """All'avvio: analizza le sessioni di telemetria non ancora imparate
        (marcatore persistente nel file). A pezzi, per non bloccare la UI."""
        try:
            import telemetry.db as _db
            from pathlib import Path
            d = Path(_db.LOGS_DIR)
            self._scan_files = sorted(d.glob("*.lmtel")) if d.exists() else []
        except Exception:
            self._scan_files = []
        self._scan_i = 0
        self._scan_done = 0
        if not self._scan_files:
            return
        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(40)
        self._scan_timer.timeout.connect(self._scan_step)
        self._scan_timer.start()
        ls = getattr(self, "learn_status", None)
        if ls is not None:
            ls.setText("Engineer: analyzing sessions\u2026")
        self._eng_log("Startup: scanning %d session(s) for learning\u2026"
                      % len(self._scan_files))

    def _scan_step(self):
        from core import engineer_learn as EL
        ls = getattr(self, "learn_status", None)
        if self._scan_i >= len(self._scan_files):
            self._scan_timer.stop()
            if ls is not None:
                if self._scan_done:
                    ls.setText("Engineer: learned \u00b7 %d sessions" % self._scan_done)
                    QTimer.singleShot(8000, lambda: ls.setText(""))
                else:
                    ls.setText("")
            self._eng_log("Startup scan done \u00b7 learned %d new session(s)"
                          % self._scan_done if self._scan_done
                          else "Startup scan done \u00b7 already up to date")
            return
        f = self._scan_files[self._scan_i]; self._scan_i += 1
        con = None
        try:
            con = sqlite3.connect(str(f)); con.row_factory = sqlite3.Row
            if not EL.is_learned(con):
                m = con.execute(
                    "SELECT track, car_class, wetness FROM session_meta WHERE id=1").fetchone()
                track = m["track"] if m else None
                cls = (m["car_class"] if m else "") or ""
                wet = bool(m and m["wetness"] is not None and m["wetness"] > 0.15)
                energy = "HYP" in cls.upper() or "LMH" in cls.upper()
                prof = EL.update_from_session(con, track, cls, energy_car=energy, wet=wet)
                EL.mark_learned(con)             # marca anche se 0 giri puliti
                if prof:
                    self._scan_done += 1
                    cnd = "wet" if wet else "dry"
                    self._eng_log("Learned %s \u00b7 %s [%s] from %s"
                                  % (track or "?", cls or "?", cnd, f.name))
        except Exception:
            pass
        finally:
            try:
                if con is not None:
                    con.close()
            except Exception:
                pass

    def _learn_after_session(self):
        """Sessione stoppata: l'ingegnere analizza il file e aggiorna il profilo."""
        f = getattr(self, "_rec_file", None)
        if not f:
            return
        seen = getattr(self, "_learned_files", None)
        if seen is None:
            seen = set(); self._learned_files = seen
        if f in seen:
            return
        ls = getattr(self, "learn_status", None)
        if ls is not None:
            ls.setText("Engineer: analyzing session\u2026")
        self._eng_log("Session stopped \u2014 analyzing\u2026")
        QTimer.singleShot(80, lambda: self._run_learn(f))

    def _run_learn(self, f):
        seen = getattr(self, "_learned_files", set())
        if f in seen:
            return
        seen.add(f); self._learned_files = seen
        ls = getattr(self, "learn_status", None)
        prof = None
        try:
            con = sqlite3.connect(f); con.row_factory = sqlite3.Row
            m = con.execute(
                "SELECT track, car_class, session_type, wetness FROM session_meta WHERE id=1").fetchone()
            track = m["track"] if m else None
            cls = (m["car_class"] if m else "") or getattr(self, "_car_class", "")
            wet = bool(m and m["wetness"] is not None and m["wetness"] > 0.15)
            energy = "HYP" in (cls or "").upper() or "LMH" in (cls or "").upper()
            from core import engineer_learn as EL
            prof = EL.update_from_session(con, track, cls, energy_car=bool(energy), wet=wet)
            con.close()
        except Exception:
            prof = None
        tot = 0
        if prof:
            cnd = prof.get("cond") or {}
            tot = sum(int((cnd.get(k) or {}).get("samples") or 0) for k in ("dry", "wet"))
        if ls is not None:
            if tot:
                ls.setText("Engineer: learned \u00b7 %d laps" % tot)
            else:
                ls.setText("Engineer: no clean laps")
            QTimer.singleShot(8000, lambda: ls.setText(""))
        if prof and tot:
            self._eng_log("Learned %s \u00b7 %s \u00b7 %d total clean laps"
                          % (prof.get("track") or "?", prof.get("car_class") or "?", tot))
        else:
            self._eng_log("Session analyzed \u00b7 no clean laps to learn")

    def _sync_rec_btn(self):
        btn = getattr(self, "btn_rec", None)
        if btn is None:
            return
        rec = getattr(self, "_recorder", None)
        # rileva fine sessione (armato -> disarmato): analizza e impara
        armed_now = bool(rec) and rec.is_armed()
        if armed_now:
            try:
                self._rec_file = rec.current_file()
            except Exception:
                pass
        if getattr(self, "_was_armed_rec", False) and not armed_now:
            self._learn_after_session()
        # (auto-focus live: lo fa _AppPage._live_focus via _live_tick, autorità unica)
        self._was_armed_rec = armed_now
        if rec is None:
            enabled, text, prop = False, "START", "off"
        elif not rec.is_armed():
            enabled, text, prop = True, "START", "off"
        elif rec.is_recording():
            enabled, text, prop = True, "STOP", "on"        # in pista = rosso
        else:
            enabled, text, prop = True, "STOP", "wait"      # armato/box = arancione
        if (enabled, text, prop) != getattr(self, "_rec_btn_cache", None):
            self._rec_btn_cache = (enabled, text, prop)
            btn.setEnabled(enabled)
            btn.setText(text); btn.setProperty("rec", prop)
            btn.style().unpolish(btn); btn.style().polish(btn)
        # banner di stato (testo + colore variabile) — solo se cambia
        bn = getattr(self, "banner", None)
        if bn is not None:
            kind, text = rec.banner() if rec is not None else ("idle", "Telemetry recorder unavailable")
            if (kind, text) != getattr(self, "_banner_cache", None):
                self._banner_cache = (kind, text)
                cols = {
                    "idle": ("#989ba2", "#16171a", "#2a2c30"),
                    "wait": ("#f0a23a", "#241a10", "#8a5a1e"),
                    "rec":  ("#2ecc71", "#122017", "#2e7d52"),
                }.get(kind, ("#989ba2", "#16171a", "#2a2c30"))
                bn.setText(text)
                bn.setStyleSheet(
                    "QLabel#statusBanner{color:%s;background:%s;border:1px solid %s;"
                    "border-radius:8px;padding:7px 14px;font-size:13px;font-weight:600;"
                    "letter-spacing:.3px;}" % cols)
        # Overview: condizioni LIVE solo se stai guardando la sessione ATTIVA
        # (la più recente = index 0). Se hai cliccato un'altra sessione per
        # rivederla, niente override live (altrimenti "saltava" sulla corrente).
        if getattr(self, "_overview", None) is not None:
            live_ok = bool(rec) and rec.is_armed() and (self._cur_sess == 0)
            self._overview.set_live(live_ok)

    def _auto_best_tick(self):
        """Ogni secondo: se nello stint corrente esce un NUOVO best lap, imposta
        in automatico sel = best e cmp = penultimo best. Se il best non è
        cambiato non tocca nulla (così una comparazione manuale ai box resta)."""
        if self.stack.currentIndex() != 0 or self._con is None:
            return
        rec = getattr(self, "_recorder", None)
        if not (rec and rec.is_armed()):
            return                      # a riposo i giri non cambiano: niente scan
        # se stai RIVEDENDO una sessione passata mentre registri, non commentare
        # quella: l'engineer/auto-best resta sulla sessione attiva.
        try:
            live_file = rec.current_file()
        except Exception:
            live_file = None
        cur_file = None
        si = getattr(self, "_cur_sess", -1)
        if 0 <= si < len(getattr(self, "_sessions", [])):
            cur_file = self._sessions[si].get("file")
        if live_file and cur_file and live_file != cur_file:
            return
        sidx = self.cmb_stint.currentIndex()
        if not (0 <= sidx < len(self._stint_keys)):
            return
        try:
            laps_all = _rows(self._con, "SELECT * FROM laps ORDER BY lap")
        except Exception:
            return
        if not laps_all:
            return
        base = min((L["stint"] or 1) for L in laps_all)
        groups = {}
        for L in laps_all:
            groups.setdefault((L["stint"] or 1) - base + 1, []).append(L)
        key = self._stint_keys[sidx]
        stint_laps = groups.get(key, [])
        if not stint_laps:
            return
        n = len(laps_all)
        new_lap = (n != getattr(self, "_last_lap_count", None))
        self._last_lap_count = n
        best, second = _two_best_laps(stint_laps)
        if best is not None and best != self._auto_last_best:
            self._auto_last_best = best
            self._groups = groups
            self._stint_keys = sorted(groups)
            self._data.set_stint(stint_laps)
            self._fill_laps(stint_laps, best)
            self._fill_compare(stint_laps,
                               None if getattr(self, "_ref_available", False) else second)
            return
        if new_lap:
            # nuovo giro chiuso (non best): aggiorna righe/board entro ~1s, tieni la selezione
            self._groups = groups
            self._stint_keys = sorted(groups)
            li = self.cmb_lap.currentIndex()
            keep = self._lap_ids[li] if 0 <= li < len(self._lap_ids) else None
            self._data.set_stint(stint_laps)
            self._fill_laps(stint_laps, keep)
        return

    def _pick_color(self, which):
        # scrive in telemetry.common (la VERA fonte dei colori dei grafici:
        # cambiare la copia importata qui non aggiornava nulla) + persistenza
        from telemetry import common as _c
        cur = {"sel": _c._SEL_COL, "cmp": _c._CMP_COL,
               "track": _c._TRK_COL}.get(which, _c._SEL_COL)
        title = {"sel": "Selected lap color", "cmp": "Compare lap color",
                 "track": "Track color"}.get(which, "Color")
        c = QColorDialog.getColor(QColor(cur), None, title)
        if not c.isValid():
            return
        if which == "sel":
            _c._SEL_COL = c.name(); _c._CUSTOM_SEL = True
        elif which == "cmp":
            _c._CMP_COL = c.name(); _c._CUSTOM_CMP = True
        else:
            _c._TRK_COL = c.name()
        try:
            from core.profile import _load_profile, _save_profile
            d = _load_profile()
            d["chart_colors"] = {"sel": _c._SEL_COL, "cmp": _c._CMP_COL,
                                 "track": _c._TRK_COL}
            _save_profile(d)
        except Exception:
            pass
        for t in self._cat:
            t.recolor()

    # contratto launcher
    def set_enabled(self, enabled):
        self._user_enabled = enabled
        if enabled:
            self.show(); self.raise_(); self.activateWindow()
        else:
            self.hide()

    def reload_config(self):
        pass

    def _close_con(self):
        if self._con is not None:
            try:
                self._con.close()
            except Exception:
                pass
            self._con = None
        self._data.set_con(None)
        for v in self._graph_views:
            v.con = None

    def _broadcast_view(self, view, src):
        """Propaga la finestra di zoom a tutti gli altri grafici a traccia."""
        for ch in getattr(self, "_charts", []):
            if ch is not src:
                ch.set_view(view)

    def _broadcast_ab(self, a, b, src):
        """Propaga i cursori A/B a tutti gli altri grafici a traccia."""
        for ch in getattr(self, "_charts", []):
            if ch is not src:
                ch.set_ab(a, b)

    def _refresh_all_tabs(self):
        for t in self._cat:
            if hasattr(t, "_refresh"):
                try:
                    t._refresh()
                except Exception:
                    pass

    def _autopick_reference(self):
        """Carica il reference (best record) per classe+pista+meteo della sessione."""
        self._ref_available = False
        self._data.clear_reference()
        if self._con is None:
            return
        try:
            mr = _rows(self._con,
                       "SELECT car_class, track, wetness FROM session_meta WHERE id=1")
            m = mr[0] if mr else {}
            # condizione REF = PISTA DICHIARATA (declared_wet), stessa logica del board:
            # maggioranza dei giri validi; fallback wetness media se non disponibile.
            # Così il REF caricato combacia sempre con l'etichetta WET/DRY mostrata.
            try:
                wl = _rows(self._con,
                           "SELECT declared_wet FROM laps "
                           "WHERE declared_wet IS NOT NULL AND invalid=0")
            except Exception:
                wl = []
            if wl:
                _nw = sum(1 for r in wl if float(r["declared_wet"] or 0.0) >= 0.5)
                _condval = 1.0 if (_nw * 2) >= len(wl) else 0.0
            else:
                _condval = m.get("wetness")
            path = None
            self._reload_ref_for_cond(m, _condval)
        except Exception:
            self._ref_available = False

    def _clear_views(self):
        """Svuota TUTTE le tab quando non resta alcuna sessione."""
        self._auto_last_best = None
        self._ref_available = False
        self._data.clear_reference()
        self._data.set_con(None)
        self._data.set_stint([])          # azzera lo stint (Stint tab non ricostruisce vecchi giri)
        for v in self._graph_views:
            v.con = None
        self._fill_stints({})             # combo stint/lap vuoti -> set_lap(None)
        self._fill_compare([])            # azzera anche il Compare -> set_compare(None)
        for ch in getattr(self, "_charts", []):
            ch.set_view(None); ch.clear_ab()
        if getattr(self, "_overview", None) is not None:
            self._overview.set_live(False)
            self._overview.set_meta({})

    def _populate_menu(self):
        # conteggio sessioni per circuito (per stem del logo)
        counts = {}
        for s in _db.list_sessions():
            k = _track_logo_stem(s.get("track")) or "Other"
            counts[k] = counts.get(k, 0) + 1
        # TUTTI i circuiti disponibili dai loghi SVG
        items = []
        try:
            logos = sorted(_OV_TRACKLOGO_DIR.glob("*.svg"), key=lambda p: p.stem.lower())
        except Exception:
            logos = []
        for f in logos:
            items.append((f.stem, counts.get(f.stem, 0), f))
        # sessioni senza logo abbinato
        if counts.get("Other"):
            items.append(("Other", counts["Other"], None))
        self._menu.set_circuits(items)

    def _show_menu(self):
        self._populate_menu()
        self.stack.setCurrentWidget(self._menu)

    def _enter_circuit(self, track):
        self._track_filter = track
        self._layout_filter = None
        self._reload_sessions()
        self.stack.setCurrentWidget(self._review_page)
        if getattr(self, "main_tabs", None) is not None and \
                getattr(self, "_overview", None) is not None:
            self.main_tabs.setCurrentWidget(self._overview)   # sempre su Overview
        if self._sessions:
            self._user_picked_session = True
            self._on_session(0)            # prima sessione selezionata, tutto caricato

    def _reload_sessions(self):
        self._viewing_team = False
        sess = _db.list_sessions()
        tf = getattr(self, "_track_filter", None)
        if tf == "Other":
            sess = [s for s in sess if _track_logo_stem(s.get("track")) is None]
        elif tf:
            sess = [s for s in sess if _track_logo_stem(s.get("track")) == tf]
        # ── tab LAYOUT: layout distinti presenti per questa pista (sessioni tue + team)
        try:
            team_all = []
            from core import team_share as _ts
            team_all = _ts.list_team_sessions()
            if tf == "Other":
                team_all = [s for s in team_all if _track_logo_stem(s.get("track")) is None]
            elif tf:
                team_all = [s for s in team_all if _track_logo_stem(s.get("track")) == tf]
        except Exception:
            team_all = []
        layout_keys = {}
        for s in (sess + team_all):
            k = _track_layout_key(s.get("track"))
            if k not in layout_keys:
                lab = _track_layout_label(s.get("track")) or ("Layout %d" % (len(layout_keys) + 1))
                layout_keys[k] = lab
        lf = getattr(self, "_layout_filter", None)
        # layout scelto (card menu / tab) -> applicato SEMPRE, anche se quel layout
        # non ha sessioni (lista vuota). Solo all'ingresso del circuito (lf None) si
        # parte dal primo layout disponibile. Niente fallback a "mostra tutto",
        # altrimenti la sessione comparirebbe anche sotto i layout sbagliati.
        if lf is None and len(layout_keys) >= 2:
            lf = next(iter(layout_keys))          # default: primo layout
        self._layout_filter = lf
        if getattr(self, "_overview", None) is not None:
            self._overview.set_layout_tabs(list(layout_keys.items()), lf,
                                           self._pick_layout)
        if lf is not None:
            sess = [s for s in sess if _track_layout_key(s.get("track")) == lf]
        self._sessions = sess
        self._cur_sess = -1
        self._user_picked_session = False
        if getattr(self, "_overview", None) is not None:
            self._overview.set_sessions(self._sessions, -1,
                                        self._select_session, self._delete_session,
                                        self._open_session_folder, self._export_session)
            if hasattr(self._overview, "set_empty"):
                self._overview.set_empty(True)
        self._close_con()
        self._clear_views()
        self._reload_team_sessions()

    def _pick_layout(self, key):
        self._layout_filter = key
        self._reload_sessions()

    def _reload_team_sessions(self):
        try:
            from core import team_share as _ts
            sess = _ts.list_team_sessions()
        except Exception:
            sess = []
        tf = getattr(self, "_track_filter", None)
        if tf == "Other":
            sess = [s for s in sess if _track_logo_stem(s.get("track")) is None]
        elif tf:
            sess = [s for s in sess if _track_logo_stem(s.get("track")) == tf]
        lf = getattr(self, "_layout_filter", None)
        if lf is not None:
            sess = [s for s in sess if _track_layout_key(s.get("track")) == lf]
        self._team_sessions = sess
        if getattr(self, "_overview", None) is not None:
            self._overview.set_team_sessions(
                self._team_sessions, self._select_team_session, self._delete_team_session)

    def _select_team_session(self, idx):
        # La sessione team e' una sessione in piu': si apre come una normale
        # (stint + telemetria, scegli un giro e confronti come sempre), ma NON
        # tocca REF / online / engineer (restano congelati su quelli tuoi).
        ts = getattr(self, "_team_sessions", [])
        if not (0 <= idx < len(ts)):
            return
        self._viewing_team = True
        self._user_picked_session = True
        self._cur_sess = -1
        if getattr(self, "_overview", None) is not None:
            try:
                self._overview.highlight_team_session(idx)
            except Exception:
                pass
        self._open_session_file(ts[idx]["file"])

    def _delete_team_session(self, idx):
        ts = getattr(self, "_team_sessions", [])
        if not (0 <= idx < len(ts)):
            return
        s = ts[idx]
        file = s["file"]
        _name = ((s.get("driver") or "") + "  \u00b7  " + (s.get("track") or "")).strip(" \u00b7")
        r = QMessageBox.question(
            self, "Delete team session",
            "Permanently delete this team session?\n\n" + (_name or s.get("name", "")),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        # Se sto VISUALIZZANDO questa sessione team, il suo file e' aperto:
        # su Windows non si puo' cancellare un file con connessione aperta.
        if getattr(self, "_viewing_team", False):
            self._viewing_team = False
            self._close_con()
            self._clear_views()
            self._user_picked_session = False
        try:
            from core import team_share as _ts
            _ts.delete_team_session(file)
        except Exception:
            pass
        self._reload_team_sessions()

    def _select_session(self, idx):
        if 0 <= idx < len(self._sessions):
            self._user_picked_session = True
            self._on_session(idx)

    def _open_logs_folder(self):
        from core.paths import LOGS_DIR
        import subprocess, sys
        try:
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            p = str(LOGS_DIR)
            if sys.platform.startswith("win"):
                os.startfile(p)            # noqa: only on Windows
            elif sys.platform == "darwin":
                subprocess.Popen(["open", p])
            else:
                subprocess.Popen(["xdg-open", p])
        except Exception:
            pass

    def _export_csv(self):
        """Esporta il giro selezionato (tutti i canali dei sample) in CSV."""
        from PySide6.QtWidgets import QFileDialog
        con = getattr(self._data, "con", None)
        if con is None:
            return
        try:
            sel, _ = self._cur_sel_cmp()
        except Exception:
            sel = None
        if sel is None:
            return
        try:
            cur = con.execute("SELECT * FROM samples WHERE lap=? ORDER BY t", (sel,))
            cols = [c[0] for c in cur.description]
            rows = cur.fetchall()
        except Exception:
            return
        fn, _f = QFileDialog.getSaveFileName(self, "Export lap CSV",
                                             f"lap_{sel}.csv", "CSV (*.csv)")
        if not fn:
            return
        import csv
        try:
            with open(fn, "w", newline="") as f:
                wr = csv.writer(f)
                wr.writerow(cols)
                wr.writerows(rows)
        except Exception:
            pass

    def _export_motec(self):
        """Esporta l'intero stint corrente in MoTeC i2 (.ld), giri concatenati
        con tempo e distanza continui, resamplato a 50 Hz."""
        from PySide6.QtWidgets import QFileDialog
        con = getattr(self._data, "con", None)
        if con is None:
            return
        # giri dello stint corrente
        keys = getattr(self, "_stint_keys", [])
        ci = self.cmb_stint.currentIndex()
        cur_key = keys[ci] if 0 <= ci < len(keys) else None
        groups = getattr(self, "_groups", {})
        stint_laps = groups.get(cur_key, []) if cur_key is not None else []
        lap_ids = [L["lap"] for L in stint_laps]
        if not lap_ids:
            try:
                sel, _ = self._cur_sel_cmp()
            except Exception:
                sel = None
            if sel is None:
                return
            lap_ids = [sel]
        # canali: (nome MoTeC, short, unità, colonna sample, fattore)
        spec = [
            ("Speed", "Speed", "km/h", "speed", 1.0),
            ("RPM", "RPM", "rpm", "rpm", 1.0),
            ("Gear", "Gear", "", "gear", 1.0),
            ("Throttle", "Throt", "%", "throttle", 100.0),
            ("Brake", "Brake", "%", "brake", 100.0),
            ("Steering", "Steer", "", "steer", 1.0),
            ("G Force Long", "GLong", "g", "g_long", 1.0),
            ("G Force Lat", "GLat", "g", "g_lat", 1.0),
            ("TC Active", "TCAct", "", "tc_active", 1.0),
            ("ABS Active", "ABSAct", "", "abs_active", 1.0),
            ("Brake Bias", "BBias", "%", "brake_bias", 100.0),
            ("TC Map", "TCMap", "", "tc_map", 1.0),
            ("ABS Map", "ABSMap", "", "abs_map", 1.0),
            ("Fuel Level", "Fuel", "L", "fuel", 1.0),
            ("Virtual Energy", "VE", "%", "ve", 1.0),
            ("Tyre Temp FL", "TtFL", "C", "tyre_t_fl", 1.0),
            ("Tyre Temp FR", "TtFR", "C", "tyre_t_fr", 1.0),
            ("Tyre Temp RL", "TtRL", "C", "tyre_t_rl", 1.0),
            ("Tyre Temp RR", "TtRR", "C", "tyre_t_rr", 1.0),
            ("Tyre Press FL", "TpFL", "kPa", "tyre_p_fl", 1.0),
            ("Tyre Press FR", "TpFR", "kPa", "tyre_p_fr", 1.0),
            ("Tyre Press RL", "TpRL", "kPa", "tyre_p_rl", 1.0),
            ("Tyre Press RR", "TpRR", "kPa", "tyre_p_rr", 1.0),
            ("Tyre Wear FL", "TwFL", "%", "tyre_w_fl", 1.0),
            ("Tyre Wear FR", "TwFR", "%", "tyre_w_fr", 1.0),
            ("Tyre Wear RL", "TwRL", "%", "tyre_w_rl", 1.0),
            ("Tyre Wear RR", "TwRR", "%", "tyre_w_rr", 1.0),
            ("Brake Temp FL", "BtFL", "C", "brake_t_fl", 1.0),
            ("Brake Temp FR", "BtFR", "C", "brake_t_fr", 1.0),
            ("Brake Temp RL", "BtRL", "C", "brake_t_rl", 1.0),
            ("Brake Temp RR", "BtRR", "C", "brake_t_rr", 1.0),
            ("Brake Press FL", "BpFL", "%", "brake_p_fl", 1.0),
            ("Brake Press FR", "BpFR", "%", "brake_p_fr", 1.0),
            ("Brake Press RL", "BpRL", "%", "brake_p_rl", 1.0),
            ("Brake Press RR", "BpRR", "%", "brake_p_rr", 1.0),
            ("Ride Height FL", "RhFL", "mm", "ride_h_fl", 1.0),
            ("Ride Height FR", "RhFR", "mm", "ride_h_fr", 1.0),
            ("Ride Height RL", "RhRL", "mm", "ride_h_rl", 1.0),
            ("Ride Height RR", "RhRR", "mm", "ride_h_rr", 1.0),
            ("Susp Defl FL", "SdFL", "mm", "susp_d_fl", 1.0),
            ("Susp Defl FR", "SdFR", "mm", "susp_d_fr", 1.0),
            ("Susp Defl RL", "SdRL", "mm", "susp_d_rl", 1.0),
            ("Susp Defl RR", "SdRR", "mm", "susp_d_rr", 1.0),
        ]
        read_cols = ["t", "lapdist"] + [s[3] for s in spec]
        # concatena i giri con tempo e distanza continui
        ts = []
        chan_raw = [[] for _ in spec]
        dist = []
        t_off = 0.0; d_off = 0.0
        last = [0.0] * len(spec)
        any_rows = False
        for lid in lap_ids:
            try:
                rs = con.execute(
                    "SELECT %s FROM samples WHERE lap=? ORDER BY t" % ",".join(read_cols),
                    (lid,)).fetchall()
            except Exception:
                continue
            rs = [r for r in rs if r[0] is not None]
            if not rs:
                continue
            any_rows = True
            t0 = float(rs[0][0]); lap_dmax = 0.0
            for r in rs:
                ts.append(t_off + (float(r[0]) - t0))
                ld = r[1] if r[1] is not None else 0.0
                dist.append(d_off + float(ld))
                if ld > lap_dmax:
                    lap_dmax = float(ld)
                for k in range(len(spec)):
                    v = r[2 + k]
                    if v is not None:
                        last[k] = float(v)
                    chan_raw[k].append(last[k])
            t_off = ts[-1] + 1.0 / 50.0
            d_off += lap_dmax
        if not any_rows or len(ts) < 2:
            return
        freq = 50
        t1 = ts[-1]
        ngrid = max(2, int(t1 * freq) + 1)
        grid = [i / float(freq) for i in range(ngrid)]

        def resample(vs):
            res = []; j = 0; nt = len(ts)
            for g in grid:
                while j + 1 < nt and ts[j + 1] < g:
                    j += 1
                if j + 1 >= nt:
                    res.append(vs[-1]); continue
                a, b = ts[j], ts[j + 1]
                if b == a:
                    res.append(vs[j])
                else:
                    res.append(vs[j] + (vs[j + 1] - vs[j]) * (g - a) / (b - a))
            return res

        chans = [("Distance", "Dist", "m", resample(dist))]
        for k, (name, short, unit, _c, fac) in enumerate(spec):
            data = resample(chan_raw[k])
            if fac != 1.0:
                data = [v * fac for v in data]
            chans.append((name, short, unit, data))

        m = getattr(self._overview, "_meta", {}) or {}
        driver = (m.get("driver") or "").strip()
        vehicle = (m.get("vehicle") or "").strip()
        venue = (m.get("track") or "").strip()
        stint_lbl = cur_key if cur_key is not None else "?"
        fn, _f = QFileDialog.getSaveFileName(self, "Export MoTeC i2",
                                             f"stint_{stint_lbl}.ld", "MoTeC i2 (*.ld)")
        if not fn:
            return
        try:
            from core.motec_ld import write_ld
            import datetime as _dt
            write_ld(fn, chans, freq=freq, driver=driver, vehicle=vehicle,
                     venue=venue, comment=f"Stint {stint_lbl}", when=_dt.datetime.now())
        except Exception:
            pass

    def _export_session(self, file_path):
        """Esporta la sessione selezionata in uno zip (cartella <nome>/<file>.lmtel)
        da inviare a un compagno. Chiede dove salvarlo."""
        if not file_path:
            return
        from PySide6.QtWidgets import QFileDialog
        try:
            from core import team_share as _ts
        except Exception:
            return
        d = QFileDialog.getExistingDirectory(self, "Export session \u2014 choose folder")
        if not d:
            return
        z = _ts.export_session(file_path, d)
        from PySide6.QtWidgets import QMessageBox
        if z:
            QMessageBox.information(self, "Export",
                                    "Session exported:\n%s" % z)
        else:
            QMessageBox.warning(self, "Export", "Export failed.")

    def _open_session_folder(self, file_path):
        """Apre la cartella della sessione, evidenziando il file se possibile."""
        import subprocess, sys, os as _os
        try:
            if not file_path:
                return self._open_logs_folder()
            f = str(file_path); folder = _os.path.dirname(f) or "."
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", "/select,", f])   # reveal del file
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", f])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception:
            pass

    def _on_session(self, idx):
        self._viewing_team = False
        self._cur_sess = idx
        self._stint_new_cache = {}
        if getattr(self, "_overview", None) is not None:
            self._overview.highlight_session(idx)
        if not (0 <= idx < len(self._sessions)):
            self._close_con(); self._fill_stints({}); return
        self._open_session_file(self._sessions[idx]["file"])

    def _open_session_file(self, file):
        """Apre un file .lmtel (sessione normale o team) per l'analisi."""
        self._close_con()
        self._auto_last_best = None
        if not file:
            self._fill_stints({}); return
        try:
            self._con = sqlite3.connect(file)
            meta = _rows(self._con, "SELECT car_class FROM session_meta WHERE id=1")
            self._car_class = (meta[0]["car_class"] if meta else "") or ""
        except Exception:
            self._con = None
            self._fill_stints({}); return
        self._data.set_con(self._con)
        self._data.car_class = self._car_class
        if not getattr(self, "_viewing_team", False):
            self._autopick_reference()     # team: NON tocca il REF (resta il tuo)
        for v in self._graph_views:
            v.con = self._con
        laps = _rows(self._con, "SELECT * FROM laps ORDER BY lap")
        groups = {}
        if laps:
            base = min((L["stint"] or 1) for L in laps)
            for L in laps:
                groups.setdefault((L["stint"] or 1) - base + 1, []).append(L)
        if getattr(self, "_overview", None) is not None:
            try:
                mr = _rows(self._con, "SELECT * FROM session_meta WHERE id=1")
                meta_d = dict(mr[0]) if mr else {}
                meta_d["_laps"] = len(laps)
                br = _rows(self._con,
                           "SELECT MIN(lap_time) b FROM laps WHERE lap_time>0 AND invalid=0")
                meta_d["_best"] = br[0]["b"] if br and br[0]["b"] else None
                sr = _rows(self._con,
                           "SELECT MIN(s1) a, MIN(s2) b, MIN(s3) c FROM laps "
                           "WHERE invalid=0 AND s1>0 AND s2>0 AND s3>0")
                if sr and sr[0]["a"] and sr[0]["b"] and sr[0]["c"]:
                    meta_d["_theo"] = sr[0]["a"] + sr[0]["b"] + sr[0]["c"]
                else:
                    meta_d["_theo"] = None
                self._overview.set_meta(meta_d)
                # SVG pista preciso su tutte le mini-mappe (review)
                _trk = meta_d.get("track")
                if _trk:
                    for _t in self._cat:
                        _mw = getattr(_t, "map_w", None)
                        if _mw is not None and hasattr(_mw, "set_svg"):
                            try:
                                _mw.set_svg(_trk)
                            except Exception:
                                pass
            except Exception:
                pass
        self._fill_stints(groups)

    def _fill_stints(self, groups, keep_idx=None, keep_lap_id=None, keep_cmp_id=None):
        self._groups = groups
        self._stint_keys = sorted(groups)
        self.cmb_stint.blockSignals(True)
        self.cmb_stint.clear()
        for s in self._stint_keys:
            self.cmb_stint.addItem(f"Stint {s}")
        sel = 0
        if keep_idx is not None and 0 <= keep_idx < len(self._stint_keys):
            sel = keep_idx
        if self._stint_keys:
            self.cmb_stint.setCurrentIndex(sel)
        self.cmb_stint.blockSignals(False)
        if self._stint_keys:
            self._on_stint(sel, keep_lap_id, keep_cmp_id)
        else:
            self._fill_laps([])

    def _on_stint(self, idx, keep_lap_id=None, keep_cmp_id=None):
        if not (0 <= idx < len(self._stint_keys)):
            self._fill_laps([]); return
        laps = self._groups[self._stint_keys[idx]]
        self._data.set_stint(laps)
        self._fill_laps(laps, keep_lap_id)
        self._fill_compare(laps, keep_cmp_id)

    def _fill_laps(self, laps, keep_lap_id=None):
        self._lap_ids = [L["lap"] for L in laps]
        self.cmb_lap.blockSignals(True)
        self.cmb_lap.clear()
        for L in laps:
            self.cmb_lap.addItem(f"Lap {L['lap']}")
        lap_idx = -1
        if laps:
            fast = _fastest_lap(laps)
            if fast in self._lap_ids:
                fi = self._lap_ids.index(fast)
                self.cmb_lap.setItemData(fi, QColor(_FUCHSIA), Qt.ForegroundRole)
            if keep_lap_id is not None and keep_lap_id in self._lap_ids:
                lap_idx = self._lap_ids.index(keep_lap_id)
            else:
                lap_idx = self._lap_ids.index(fast) if fast in self._lap_ids else 0
            self.cmb_lap.setCurrentIndex(lap_idx)
        self.cmb_lap.blockSignals(False)
        self._on_lap(lap_idx)

    def _visible_cat(self):
        w = self.tabs.currentWidget()
        return w if w in self._cat else None

    def _cur_best_lap(self):
        """Numero del giro più veloce dello stint corrente (None se assente)."""
        keys = getattr(self, "_stint_keys", [])
        ci = self.cmb_stint.currentIndex()
        cur_key = keys[ci] if 0 <= ci < len(keys) else None
        laps = getattr(self, "_groups", {}).get(cur_key, []) if cur_key is not None else []
        return _fastest_lap(laps) if laps else None

    def _set_lap_lazy(self, lap):
        """Aggiorna SUBITO solo il tab visibile; gli altri all'apertura."""
        _common._SEL_IS_BEST = (lap is not None and lap == self._cur_best_lap())
        self._cat_lap = lap
        self._cat_dirty_lap = set(id(t) for t in self._cat)
        vis = self._visible_cat()
        if vis is not None:
            vis.set_lap(lap)
            self._cat_dirty_lap.discard(id(vis))

    def _set_compare_lazy(self, lap):
        _common._CMP_IS_BEST = (lap is not None and lap == self._cur_best_lap())
        self._cat_cmp = lap
        self._cat_dirty_cmp = set(id(t) for t in self._cat)
        vis = self._visible_cat()
        if vis is not None:
            vis.set_compare(lap)
            self._cat_dirty_cmp.discard(id(vis))

    def _on_tab_changed(self, *_):
        """All'apertura di un tab rimasto indietro, applica lo stato corrente."""
        vis = self._visible_cat()
        if vis is None:
            return
        if id(vis) in self._cat_dirty_lap and self._cat_lap is not _UNSET:
            vis.set_lap(self._cat_lap)
            self._cat_dirty_lap.discard(id(vis))
        if id(vis) in self._cat_dirty_cmp and self._cat_cmp is not _UNSET:
            vis.set_compare(self._cat_cmp)
            self._cat_dirty_cmp.discard(id(vis))

    def _on_lap(self, idx):
        self._sel_none = False
        lap = self._lap_ids[idx] if 0 <= idx < len(self._lap_ids) else None
        self._set_lap_lazy(lap)
        self._sync_board()

    def _fill_compare(self, laps, keep_cmp_id=None):
        self._cmp_ids = [L["lap"] for L in laps]
        self.cmb_cmp.blockSignals(True)
        self.cmb_cmp.clear()
        # voce REF sempre in cima (best record classe+pista+meteo)
        ref_ok = getattr(self, "_ref_available", False)
        ref_lab = ("REF  " + _fmt(self._data.ref_time)) if (ref_ok and self._data.ref_time) else "REF \u2014"
        self.cmb_cmp.addItem(ref_lab)
        try:
            self.cmb_cmp.model().item(0).setEnabled(bool(ref_ok))
        except Exception:
            pass
        for L in laps:
            self.cmb_cmp.addItem(f"Lap {L['lap']}")
        if keep_cmp_id is not None and keep_cmp_id in self._cmp_ids:
            cmp_idx = self._cmp_ids.index(keep_cmp_id) + 1
            self._cmp_none = False
            self.cmb_cmp.setCurrentIndex(cmp_idx)
            self.cmb_cmp.blockSignals(False)
            self._on_cmp(cmp_idx)
        elif ref_ok:
            # default: confronto vs REF (gold acceso, disegnato in telemetria)
            self._cmp_none = False
            self.cmb_cmp.setCurrentIndex(0)
            self.cmb_cmp.blockSignals(False)
            self._on_cmp(0)
        else:
            # nessun REF: nessun confronto finche' non accendi uno switch
            self._cmp_none = True
            self.cmb_cmp.setCurrentIndex(0)
            self.cmb_cmp.blockSignals(False)
            self._data.ref_on = False
            self._set_compare_lazy(None)
            self._sync_board()

    def _on_cmp(self, idx):
        self._cmp_none = False
        try:
            self._data.clear_external_compare()   # un compare normale/REF spegne il team
        except Exception:
            pass
        if idx == 0:                         # REF
            self._data.ref_on = getattr(self, "_ref_available", False)
            self._set_compare_lazy(None)
        else:
            self._data.ref_on = False
            lap = self._cmp_ids[idx - 1] if 1 <= idx <= len(self._cmp_ids) else None
            self._set_compare_lazy(lap)
        self._sync_board()

    # ── board Overview (pilota i combo nascosti) ──────────────────────────
    def _board_stint(self, key):
        keys = getattr(self, "_stint_keys", [])
        if key in keys:
            self.cmb_stint.setCurrentIndex(keys.index(key))

    def _cur_sel_cmp(self):
        """(sel_lap_id|None, cmp_spec) attuali, tenendo conto dei flag 'none'."""
        ids = getattr(self, "_lap_ids", [])
        li = self.cmb_lap.currentIndex()
        sel = None if getattr(self, "_sel_none", False) else (ids[li] if 0 <= li < len(ids) else None)
        if getattr(self, "_cmp_none", False):
            cmp = None
        else:
            ci = self.cmb_cmp.currentIndex()
            cids = getattr(self, "_cmp_ids", [])
            if ci == 0:
                cmp = ("ref",) if getattr(self, "_ref_available", False) else None
            else:
                cid = cids[ci - 1] if 1 <= ci <= len(cids) else None
                cmp = ("lap", cid) if cid is not None else None
        return sel, cmp

    def _board_select(self, lap_id):
        ids = getattr(self, "_lap_ids", [])
        if lap_id in ids:
            i = ids.index(lap_id)
            self._sel_none = False
            self.cmb_lap.blockSignals(True); self.cmb_lap.setCurrentIndex(i)
            self.cmb_lap.blockSignals(False)
            self._on_lap(i)

    def _board_select_none(self):
        self._sel_none = True
        self._set_lap_lazy(None)
        self._sync_board()

    def _board_compare(self, lap_id):
        ids = getattr(self, "_cmp_ids", [])
        if lap_id in ids:
            i = ids.index(lap_id) + 1
            self._cmp_none = False
            self.cmb_cmp.blockSignals(True); self.cmb_cmp.setCurrentIndex(i)
            self.cmb_cmp.blockSignals(False)
            self._on_cmp(i)

    def _board_compare_ref(self):
        if getattr(self, "_ref_available", False):
            self._cmp_none = False
            self.cmb_cmp.blockSignals(True); self.cmb_cmp.setCurrentIndex(0)
            self.cmb_cmp.blockSignals(False)
            self._on_cmp(0)

    def _board_compare_none(self):
        self._cmp_none = True
        self._data.ref_on = False
        self._set_compare_lazy(None)
        self._sync_board()

    def _board_pick(self, item):
        """Un solo check per riga: regola sel-sticky.
        item = ('lap', id), ('ref',) oppure ('pace',)."""
        if item and item[0] == "pace":
            self._pace_sel = not getattr(self, "_pace_sel", True)
            self._sync_board()
            return
        sel, cmp = self._cur_sel_cmp()
        if item[0] == "lap":
            lid = item[1]
            if sel == lid:                       # deseleziona il Selected
                if cmp and cmp[0] == "lap":      # promuovi il compare-lap a selected
                    promote = cmp[1]
                    self._board_compare_none()
                    self._board_select(promote)
                else:
                    self._board_select_none()
            elif cmp == ("lap", lid):            # deseleziona il compare
                self._board_compare_none()
            else:
                if sel is None:
                    self._board_select(lid)
                else:
                    self._board_compare(lid)
        else:                                    # REF: sempre come compare
            if cmp == ("ref",):
                self._board_compare_none()
            else:
                self._board_compare_ref()

    def _stint_start_new_from_samples(self, laps):
        """Verità dal DB: integrità a inizio stint = MAX wear tra i sample dello
        stint (il consumo cala, quindi il picco = uscita box). ~100% -> nuova.
        None se non disponibile."""
        if not laps:
            return None
        con = getattr(self._data, "con", None)
        if con is None:
            return None
        ids = [L.get("lap") for L in laps if L.get("lap") is not None]
        if not ids:
            return None
        cache = self.__dict__.setdefault("_stint_new_cache", {})
        ck = tuple(ids)
        if ck in cache:
            return cache[ck]
        qm = ",".join("?" * len(ids))
        try:
            rs = _rows(con, "SELECT MAX((tyre_w_fl+tyre_w_fr+tyre_w_rl+tyre_w_rr)/4.0) AS mw "
                            "FROM samples WHERE lap IN (%s) AND tyre_w_fl IS NOT NULL" % qm, ids)
        except Exception:
            return None
        if not rs or rs[0].get("mw") is None:
            cache[ck] = None
            return None
        res = rs[0]["mw"] >= 99.5
        cache[ck] = res
        return res

    def _stint_start_new4_from_samples(self, laps):
        """Come sopra ma PER GOMMA: [FL,FR,RL,RR] bool (MAX wear per ruota
        >=99.5 -> nuova). None se non disponibile."""
        if not laps:
            return None
        con = getattr(self._data, "con", None)
        if con is None:
            return None
        ids = [L.get("lap") for L in laps if L.get("lap") is not None]
        if not ids:
            return None
        cache = self.__dict__.setdefault("_stint_new4_cache", {})
        ck = tuple(ids)
        if ck in cache:
            return cache[ck]
        qm = ",".join("?" * len(ids))
        try:
            rs = _rows(con, "SELECT MAX(tyre_w_fl) a, MAX(tyre_w_fr) b, "
                            "MAX(tyre_w_rl) c, MAX(tyre_w_rr) d "
                            "FROM samples WHERE lap IN (%s) AND tyre_w_fl IS NOT NULL" % qm, ids)
        except Exception:
            return None
        if not rs or rs[0].get("a") is None:
            cache[ck] = None
            return None
        r0 = rs[0]
        res = [(r0["a"] or 0) >= 99.5, (r0["b"] or 0) >= 99.5,
               (r0["c"] or 0) >= 99.5, (r0["d"] or 0) >= 99.5]
        cache[ck] = res
        return res

    def _maybe_learn(self, ov):
        """A sessione ferma, aggiorna il profilo appreso pista+classe una sola
        volta per file (apprendimento sessione dopo sessione)."""
        rec = getattr(self, "_recorder", None)
        if rec and rec.is_armed():
            return                              # non in registrazione
        con = getattr(self, "_con", None)
        if con is None:
            return
        f = None
        if 0 <= getattr(self, "_cur_sess", -1) < len(getattr(self, "_sessions", [])):
            f = self._sessions[self._cur_sess].get("file")
        if not f:
            return
        seen = getattr(self, "_learned_files", None)
        if seen is None:
            seen = set(); self._learned_files = seen
        if f in seen:
            return
        seen.add(f)
        m = getattr(ov, "_meta", {}) or {}
        cls = getattr(self, "_car_class", "") or m.get("car_class", "")
        try:
            from core import engineer_learn as EL
            EL.update_from_session(con, m.get("track"), cls, energy_car=False)
        except Exception:
            pass

    def _sync_board(self):
        ov = getattr(self, "_overview", None)
        if ov is None or not hasattr(ov, "board"):
            return
        if not getattr(self, "_user_picked_session", False):
            if hasattr(ov, "set_empty"):
                ov.set_empty(True)
            return
        keys = getattr(self, "_stint_keys", [])
        ci = self.cmb_stint.currentIndex()
        cur_key = keys[ci] if 0 <= ci < len(keys) else None
        groups = getattr(self, "_groups", {})
        laps = groups.get(cur_key, []) if cur_key is not None else []
        m0 = getattr(ov, "_meta", {}) or {}
        has_meta = bool(m0.get("track") or m0.get("session_type") or m0.get("driver"))
        if (not keys) and (not laps) and (not has_meta):
            if hasattr(ov, "set_empty"):
                ov.set_empty(True)
            return
        if hasattr(ov, "set_empty"):
            ov.set_empty(False)
        best = _fastest_lap(laps) if laps else None
        sel, cmp_spec = self._cur_sel_cmp()
        ref = None      # costruito DOPO la risoluzione della condizione (vedi sotto)
        theo = None
        valid = [L for L in laps if not L.get("invalid")
                 and L.get("s1") and L.get("s2") and L.get("s3")]
        if valid:
            theo = (min(L["s1"] for L in valid) + min(L["s2"] for L in valid)
                    + min(L["s3"] for L in valid))
        cmp_lap = cmp_spec[1] if (cmp_spec and cmp_spec[0] == "lap") else None
        tyre4 = []
        m = getattr(ov, "_meta", {}) or {}
        c4 = (m.get("compounds4") or "").strip()
        if c4:
            tyre4 = [x.strip() for x in c4.split(",") if x.strip()]
        # condizione di riferimento = quella del GIRO SELEZIONATO (WET/DRY);
        # se nessun giro selezionato, fallback alla condizione media della sessione.
        _sel_L = next((L for L in laps if L["lap"] == sel), None) if sel else None
        _sel_cond = _sel_L.get("declared_wet") if _sel_L else None
        if _sel_cond is not None:
            _cond_wet = float(_sel_cond) >= 0.5
        else:
            # nessun giro selezionato: condizione = maggioranza dei giri VALIDI
            # (stessa logica dello stint). Evita il flicker DRY->WET al click,
            # perché non dipende dalla wetness media ancora non pronta.
            _wl = [L for L in laps
                   if L.get("declared_wet") is not None and not L.get("invalid")]
            if _wl:
                _nw = sum(1 for L in _wl if float(L["declared_wet"]) >= 0.5)
                _cond_wet = (_nw * 2) >= len(_wl)
            else:
                _cond_wet = float(m.get("wetness") or 0.0) > 0.10
        # LOGICA UNICA: il file REF viene (ri)caricato sulla STESSA condizione
        # dell'etichetta (_cond_wet). Se manca il REF di quella condizione la
        # card resta vuota — mai il tempo dell'altra condizione sotto l'etichetta.
        self._reload_ref_for_cond(m, 1.0 if _cond_wet else 0.0)
        if getattr(self, "_ref_available", False):
            _rs = _ov_session_label(self._data.ref_session)
            _rd = _date_human(self._data.ref_started)
            _rwhen = " \u00b7 ".join(p for p in (_rs, _rd)
                                    if p and p != "Session")
            ref = {"driver": self._data.ref_driver, "team": self._data.ref_team,
                   "vehicle": self._data.ref_vehicle, "time": self._data.ref_time,
                   "secs": self._data.ref_secs, "when": _rwhen,
                   "compounds4": self._data.ref_compounds4,
                   "tyre_state": self._data.ref_tyre_state,
                   "load_pct": self._data.ref_load_pct,
                   "load_kind": self._data.ref_load_kind,
                   "wear4": self._data.ref_wear4,
                   "fuel_l": self._data.ref_fuel_l,
                   "wet_pct": getattr(self._data, "ref_wet_pct", None),
                   "wet": bool(_cond_wet)}
        # ONLINE REF: best globale dal Worker (se configurato in settings/online.json).
        # Senza url/dati la card blue resta sui placeholder. Niente pace sul board.
        pace_info = {"kind": None, "sel": getattr(self, "_pace_sel", True)}
        board_pace = None
        try:
            from core import online as _online
            if _online.enabled():
                _online.load_async()
                _wet = _cond_wet
                _okey = _online.make_key(class_tag(m.get("car_class") or ""),
                                         _db._short_track(m.get("track") or ""), _wet)
                _row = _online.get_ref(_okey) if _okey else None
                if _row:
                    _lm = _row.get("lap_ms")
                    _s1 = _row.get("s1_ms"); _s2 = _row.get("s2_ms"); _s3 = _row.get("s3_ms")
                    _ld = _row.get("ve_pct")
                    if _ld is None:
                        _ld = _row.get("fuel_pct")
                    pace_info.update({
                        "online": True,
                        "player": _row.get("player"),
                        "team": _row.get("team"),
                        "car": _row.get("car"),
                        "compound": _row.get("compound"),
                        "compounds4": _row.get("compounds4"),
                        "tyre_state_pct": _row.get("tyre_state_pct"),
                        "load_pct": _ld,
                        "fuel_l": _row.get("fuel_l"),
                        "ref_time": (_lm / 1000.0) if _lm else None,
                        "secs": [(_s1 / 1000.0) if _s1 else None,
                                 (_s2 / 1000.0) if _s2 else None,
                                 (_s3 / 1000.0) if _s3 else None],
                    })
        except Exception:
            pass
        # dedup: se l'ONLINE coincide col LOCAL (stesso tempo + stesso pilota),
        # mostra solo LOCAL (togli la card online).
        if pace_info.get("online") and ref and ref.get("time") and pace_info.get("ref_time"):
            _same_t = abs(float(ref["time"]) - float(pace_info["ref_time"])) < 0.02
            _same_d = (str(pace_info.get("player") or "").strip().lower()
                       == str(ref.get("driver") or "").strip().lower())
            if _same_t and _same_d:
                pace_info.pop("online", None)
        # gap blu sul giro migliore quando la card ONLINE REF e selezionata
        if (pace_info.get("online") and pace_info.get("sel")
                and pace_info.get("ref_time") and best):
            _bL = next((L for L in laps if L["lap"] == best), None)
            _blt = (_bL.get("lap_time") if _bL else None) or 0
            if _blt > 0:
                board_pace = {"kind": "online",
                              "label": pace_info.get("player") or "ONLINE",
                              "gap": _blt - pace_info["ref_time"],
                              "color": "#4aa3df"}
        stint_new = {}
        stint_new4 = {}
        stint_comp4 = {}
        for k in keys:
            lk = groups.get(k, [])
            v = self._stint_start_new_from_samples(lk)
            if v is None and lk:
                v = ov.board._stint_started_new(lk)
            stint_new[k] = True if v is None else bool(v)
            stint_new4[k] = self._stint_start_new4_from_samples(lk)
            # mescola dello stint = quella montata, costante per tutto lo stint:
            # la leggo diretta dal primo giro che ce l'ha.
            stint_comp4[k] = next(
                ((L.get("compounds4") or "").strip() for L in lk
                 if (L.get("compounds4") or "").strip()), "")
        _rec = getattr(self, "_recorder", None)
        # LIVE (auto-scroll + riga in corso + giro corrente bloccato) SOLO quando sei
        # davvero in pista a registrare. Al garage/in attesa (armato ma non scrive) il
        # board torna in review piena: nessun auto-scroll, tutti i giri selezionabili.
        ov.board._live = bool(_rec) and _rec.is_recording()
        _team_view = getattr(self, "_viewing_team", False)
        if not _team_view:
            try:
                self._maybe_learn(ov)        # team: nessun learning
            except Exception:
                pass
        ov.board.update_board(keys, cur_key, laps, best, sel, cmp_lap, tyre4, pace=board_pace, stint_new=stint_new, stint_new4=stint_new4, stint_comp4=stint_comp4, session_type=m.get("session_type"), car_class=m.get("car_class"))
        if not _team_view:
            # team: REF/online congelati sui tuoi (non ricostruire le card)
            ov.set_ref(ref, cmp_spec == ("ref",), theo, self._board_pick,
                       pace=pace_info, wet=_cond_wet)
            self._upload_ref_online(ref, m)        # carica il best personale sul Worker

    def _reload_ref_for_cond(self, m, condval):
        """LOGICA UNICA della condizione REF: file ed etichetta derivano
        SEMPRE dallo stesso valore (quello passato qui, gia' risolto a monte:
        giro selezionato -> maggioranza giri -> wetness). Ricarica il file
        solo se la condizione e' cambiata. Se il REF di quella condizione
        NON esiste, la card resta vuota: MAI il fallback sull'altra
        condizione (era la causa dell'etichetta WET col tempo fatto in dry)."""
        try:
            want = 1.0 if (condval is not None and float(condval) >= 0.5) else 0.0
        except (TypeError, ValueError):
            want = 0.0
        if (getattr(self, "_ref_cond_loaded", None) == want
                and getattr(self, "_ref_available", False)):
            return
        try:
            path = _db.ref_path_for(m.get("car_class"), m.get("track"), want)
            ok = bool(path) and self._data.load_reference(str(path))
        except Exception:
            ok = False
        self._ref_available = ok
        self._ref_cond_loaded = want if ok else None
        try:
            self._data.ref_wet = bool(ok and want >= 0.5)
            if not ok:
                self._data.clear_reference()
        except Exception:
            pass

    def _upload_ref_online(self, ref, m):
        """Manda il best personale alla classifica online (Cloudflare Worker).
        Degrada in modo sicuro se online non è configurato (url/token mancanti).
        Stesso formato chiave della classifica: CLASSE_TRACK_METEO. Dedup per run."""
        try:
            from core import online as _online
            if not (_online.enabled() and ref and ref.get("time")):
                return
            from core.classes import class_tag as _ctag
            # condizione = quella per cui il REF e' stato caricato (la card
            # e la chiave online NON possono divergere). Fallback: wetness.
            _wet = ref.get("wet")
            if _wet is None:
                _wet = float((m or {}).get("wetness") or 0.0) > 0.10
            _wet = bool(_wet)
            key = _online.make_key(_ctag((m or {}).get("car_class") or ""),
                                   _db._short_track((m or {}).get("track") or ""), _wet)
            if not key:
                return
            lap_ms = int(round(ref["time"] * 1000))
            sig = (key, lap_ms)
            up = getattr(self, "_uploaded_online", None)
            if up is None:
                up = self._uploaded_online = set()
            if sig in up:
                return
            secs = ref.get("secs") or [None, None, None]
            def _ms(x): return int(round(x * 1000)) if x else None
            player = (ref.get("driver") or _load_profile().get("driver") or "").strip()
            rec = {
                "key": key, "lap_ms": lap_ms,
                "player": player or "anon",
                "team": get_team() or ref.get("team") or "",
                "car": ref.get("vehicle") or "",
                "s1_ms": _ms(secs[0]), "s2_ms": _ms(secs[1]), "s3_ms": _ms(secs[2]),
                "compounds4": ref.get("compounds4") or "",
                "tyre_state_pct": ref.get("tyre_state"),
                "fuel_l": ref.get("fuel_l"),
                # livrea casco scelta: il Worker la salva col record e le
                # classifiche la mostrano accanto al nome
                "helmet": _load_profile().get("helmet_color", "#fd160e"),
            }
            if (ref.get("load_kind") or "").upper() == "VE":
                rec["ve_pct"] = ref.get("load_pct")
            else:
                rec["fuel_pct"] = ref.get("load_pct")
            _online.submit_async(rec)
            up.add(sig)
        except Exception:
            pass

    def _live_refresh(self):
        """Aggiorna la Review durante la sessione: nuove sessioni/giri appena
        registrati, preservando la selezione (sessione/stint/giro/compare)."""
        if self.stack.currentIndex() != 0:
            return                                   # solo quando la Review è visibile
        # replay mappa in corso: NON interrompere il play con la ricostruzione
        # delle liste (il tick da 8s riprova; appena in pausa il refresh passa)
        _ws = getattr(self, "_worksheet", None)
        _rp = getattr(_ws, "_rp_timer", None) if _ws is not None else None
        if _rp is not None and _rp.isActive():
            return
        rec = getattr(self, "_recorder", None)
        armed_now = bool(rec) and rec.is_armed()
        if armed_now and not getattr(self, "_was_armed_live", False):
            self._live_jump_pending = True         # sessione in pista appena avviata
        if not armed_now:
            self._live_jump_pending = False
        self._was_armed_live = armed_now
        if not armed_now:
            return                       # a riposo la lista sessioni non cambia
        live_file = rec.current_file() if (rec and armed_now) else None
        cur_file = None
        si = self._cur_sess
        if 0 <= si < len(self._sessions):
            cur_file = self._sessions[si]["file"]
        cur_stint = self.cmb_stint.currentIndex()
        li = self.cmb_lap.currentIndex()
        keep_lap = self._lap_ids[li] if 0 <= li < len(self._lap_ids) else None
        ci = self.cmb_cmp.currentIndex()
        keep_cmp = self._cmp_ids[ci - 1] if 1 <= ci <= len(self._cmp_ids) else None

        sessions_all = _db.list_sessions()
        import os as _os
        _lfn = _os.path.basename(live_file) if live_file else None
        live_sess = (next((s for s in sessions_all
                           if _os.path.basename(s.get("file") or "") == _lfn), None)
                     if _lfn else None)
        # la sessione live appena creata può essere letta senza pista (metadati non
        # ancora flushati): prendila dal recorder, così titolo/card/filtro la
        # riconoscono subito invece di mostrare il nome-file.
        if live_sess is not None and not (live_sess.get("track") or "").strip():
            try:
                _lt = rec.current_track()
                if _lt:
                    live_sess["track"] = _lt
            except Exception:
                pass
        # JUMP in sospeso ma la sessione in registrazione non è ancora pronta
        # (file appena creato, non ancora nella lista): NON toccare la Review,
        # altrimenti il focus finisce su una vecchia sessione (e il filtro
        # circuito resta su quella sbagliata). Aspetta il prossimo giro.
        if getattr(self, "_live_jump_pending", False) and live_sess is None:
            return
        # registrazione appena avviata su una pista diversa da quella filtrata:
        # cambia il filtro circuito sulla nuova pista (es. ero su Monza -> nuova)
        if getattr(self, "_live_jump_pending", False) and live_sess is not None:
            live_stem = _track_logo_stem(live_sess.get("track")) or "Other"
            if getattr(self, "_track_filter", None) != live_stem:
                self._track_filter = live_stem
            self._layout_filter = _track_layout_key(live_sess.get("track"))  # layout attivo
        # applica il filtro circuito corrente (coerente con _reload_sessions)
        tf = getattr(self, "_track_filter", None)
        if tf == "Other":
            sessions = [s for s in sessions_all if _track_logo_stem(s.get("track")) is None]
        elif tf:
            sessions = [s for s in sessions_all if _track_logo_stem(s.get("track")) == tf]
        else:
            sessions = sessions_all
        # filtro LAYOUT (coerente con _reload_sessions / menu): durante il live
        # mostra solo il layout della sessione attiva, non entrambi.
        _lf = getattr(self, "_layout_filter", None)
        if _lf:
            sessions = [s for s in sessions
                        if _track_layout_key(s.get("track")) == _lf]
        self._sessions = sessions
        live_idx = (next((i for i, s in enumerate(sessions)
                          if _os.path.basename(s.get("file") or "") == _lfn), None)
                    if _lfn else None)
        if getattr(self, "_live_jump_pending", False) and live_idx is not None:
            sel_idx = live_idx                     # salta sulla sessione in registrazione
            cur_file = live_file
            cur_stint = 0; keep_lap = None; keep_cmp = None   # niente residui
            self._live_jump_pending = False
            self._user_picked_session = True        # in registrazione il pannello si mostra
        else:
            sel_idx = 0
            for i, s in enumerate(sessions):
                if cur_file and s["file"] == cur_file:
                    sel_idx = i
        self._cur_sess = sel_idx if sessions else -1
        if getattr(self, "_overview", None) is not None:
            self._overview.set_sessions(sessions, self._cur_sess,
                                        self._select_session, self._delete_session,
                                        self._open_session_folder, self._export_session)
        if not sessions:
            self._close_con(); self._fill_stints({}); return

        # riapre la connessione per vedere i giri appena committati dal recorder
        self._close_con()
        try:
            self._con = sqlite3.connect(sessions[sel_idx]["file"])
            meta = _rows(self._con, "SELECT car_class FROM session_meta WHERE id=1")
            self._car_class = (meta[0]["car_class"] if meta else "") or ""
        except Exception:
            self._con = None
            self._fill_stints({}); return
        self._data.set_con(self._con)
        self._data.car_class = self._car_class
        self._autopick_reference()
        for v in self._graph_views:
            v.con = self._con
        laps = _rows(self._con, "SELECT * FROM laps ORDER BY lap")
        groups = {}
        if laps:
            base = min((L["stint"] or 1) for L in laps)
            for L in laps:
                groups.setdefault((L["stint"] or 1) - base + 1, []).append(L)
        # follow-stint: se in live (sessione attiva, la più recente) compare un nuovo
        # stint e si stava guardando l'ultimo, passa automaticamente al nuovo.
        keys = sorted(groups)
        auto_idx = cur_stint
        prev_file = getattr(self, "_live_stint_file", None)
        prev_cnt = getattr(self, "_live_stint_count", 0)
        if prev_file != cur_file:
            prev_cnt = 0                              # nuova sessione: reset
        if (sel_idx == 0 and prev_cnt > 0 and len(keys) > prev_cnt
                and cur_stint == prev_cnt - 1):
            auto_idx = len(keys) - 1                  # segui il nuovo stint
        self._live_stint_count = len(keys)
        self._live_stint_file = cur_file
        self._fill_stints(groups, keep_idx=auto_idx,
                          keep_lap_id=keep_lap, keep_cmp_id=keep_cmp)

    def _delete_session(self, idx=None):
        if idx is None or idx is False:
            idx = self._cur_sess
        if not (0 <= idx < len(self._sessions)):
            return
        s = self._sessions[idx]
        r = QMessageBox.question(
            self, "Delete session",
            "Permanently delete this telemetry?\n\n" + s.get("name", ""),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        self._close_con()
        err = None
        for suffix in ("-wal", "-shm", ""):      # sidecar prima, file principale per ultimo
            p = s["file"] + suffix
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError as e:
                if suffix == "":
                    err = e
        if os.path.exists(s["file"]):
            QMessageBox.warning(
                self, "Delete session",
                "Could not delete the file. It is probably in use by an "
                "active recording (stop the on-track session and try again).\n\n"
                + (str(err) if err else s["file"]))
            return
        self._reload_sessions()

    def closeEvent(self, e):
        if getattr(self, "_overlaytab", None) is not None:
            try:
                self._overlaytab.stop_all()
            except Exception:
                pass
        if getattr(self, "_overview", None) is not None:
            try:
                self._overview.stop()
            except Exception:
                pass
        if getattr(self, "_recorder", None) is not None:
            try:
                self._recorder.stop()
            except Exception:
                pass
        eng = getattr(self, "_engineer", None)
        if eng is not None and getattr(eng, "_ov", None) is not None:
            try:
                eng._ov.close()
            except Exception:
                pass
        self._close_con()
        try:
            self._data.clear_reference()
        except Exception:
            pass
        super().closeEvent(e)


# ─────────────────────────────────────────────────────────────────────────────
#  TelemetryWindow — canvas vuoto. Le pagine si montano a mano, un pezzo alla
#  volta. Tutte le funzionalita' esistenti restano disponibili nelle classi
#  widget qui sopra e in _LegacyWindow (riserva pezzi: recorder, timer, wiring
#  telemetria intatti), pronte da rimontare.
# ─────────────────────────────────────────────────────────────────────────────

    # ── controllo aggiornamenti (GitHub Releases) ─────────────────────────
    def _check_updates_async(self):
        """Parte 4s dopo l'avvio, in un thread: la UI non aspetta la rete."""
        import threading
        threading.Thread(target=self._check_updates_worker, daemon=True).start()

    def _check_updates_worker(self):
        try:
            import json as _json, re as _re, urllib.request as _ur
            req = _ur.Request(_GH_LATEST_API,
                              headers={"User-Agent": "LMU-TelemetryPro",
                                       "Accept": "application/vnd.github+json"})
            with _ur.urlopen(req, timeout=6) as r:
                d = _json.load(r)
            tag = str(d.get("tag_name") or "").strip()

            def _nums(s):
                return tuple(int(x) for x in _re.findall(r"\d+", s)) or (0,)

            # confronto SOLO numerico ("v0.2b" -> (0,2)): regge tag misti
            # tipo v0.1-beta / v0.1.1-beta / v0.2b
            if tag and _nums(tag) > _nums(_APP_VERSION):
                url = str(d.get("html_url") or _GH_RELEASES_URL)
                self._sig_update_found.emit(tag, url)
        except Exception:
            pass                    # niente rete/API: silenzio, si riprova al prossimo avvio

    def _on_update_found(self, tag, url):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        self._upd_btn.setText("\u2b06  Update available: %s \u2014 download" % tag)
        if getattr(self, "_upd_wired", False):
            self._upd_btn.clicked.disconnect()
        self._upd_btn.clicked.connect(
            lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
        self._upd_wired = True
        self._upd_btn.setVisible(True)
        # inoltra al footer NUOVO (TelemetryWindow), quello visibile
        hk = getattr(self, "_update_hook", None)
        if hk is not None:
            try:
                hk(tag, url)
            except Exception:
                pass

_TRACKS = [
    # (key base foto/rotazione, key foto dedicata, nome, logo, mappa-svg)
    ("bahrain",     "bahrain",            "Bahrain",            "Bahrain",     "Bahrain International Circuit.svg"),
    ("bahrain",     "bahrain_endurance",  "Bahrain Endurance",  "Bahrain",     "Bahrain Endurance Circuit.svg"),
    ("bahrain",     "bahrain_outer",      "Bahrain Outer",      "Bahrain",     "Bahrain Outer Circuit.svg"),
    ("bahrain",     "bahrain_paddock",    "Bahrain Paddock",    "Bahrain",     "Bahrain Paddock Circuit.svg"),
    ("barcelona",   "barcelona",          "Barcelona",          "Barcelona",   "Circuit de Barcelona.svg"),
    ("cota",        "cota",               "COTA",               "COTA",        "Circuit of the Americas.svg"),
    ("cota",        "cota_national",      "COTA National",      "COTA",        "Circuit of the Americas National.svg"),
    ("fuji",        "fuji",               "Fuji",               "Fuji",        "Fuji Speedway.svg"),
    ("fuji",        "fuji_classic",       "Fuji Classic",       "Fuji",        "Fuji Speedway Classic.svg"),
    ("imola",       "imola",              "Imola",              "Imola",       "Autodromo Enzo e Dino Ferrari.svg"),
    ("interlagos",  "interlagos",         "Interlagos",         "Interlagos",  "Aut#U00f3dromo Jos#U00e9 Carlos Pace.svg"),
    ("lemans",      "lemans",             "Le Mans",            "LeMans",      "Circuit de la Sarthe.svg"),
    ("lemans",      "lemans_mulsanne",    "Le Mans Mulsanne",   "LeMans",      "Circuit de la Sarthe Mulsanne.svg"),
    ("lusail",      "lusail",             "Lusail",             "Lusail",      "Lusail International Circuit.svg"),
    ("lusail",      "lusail_short",       "Lusail Short",       "Lusail",      "Lusail Short Circuit.svg"),
    ("monza",       "monza",              "Monza",              "Monza",       "Autodromo Nazionale Monza.svg"),
    ("monza",       "monza_curva_grande", "Monza Curva Grande", "Monza",       "Monza Curva Grande Circuit.svg"),
    ("paulricard",  "paulricard",         "Paul Ricard",        "PaulRicard",  "Paul Ricard - ELMS.svg"),
    ("paulricard",  "paulricard_1a",      "Paul Ricard 1A",     "PaulRicard",  "Paul Ricard - 1A.svg"),
    ("paulricard",  "paulricard_1a_v2",   "Paul Ricard 1A-V2",  "PaulRicard",  "Paul Ricard - 1A-V2.svg"),
    ("paulricard",  "paulricard_1a_v2_short","Paul Ricard 1A-V2 Short","PaulRicard","Paul Ricard - 1A-V2-Short.svg"),
    ("paulricard",  "paulricard_3a",      "Paul Ricard 3A",     "PaulRicard",  "Paul Ricard - 3A.svg"),
    ("portimao",    "portimao",           "Portim\u00e3o",      "Portimao",    "Algarve International Circuit.svg"),
    ("sebring",     "sebring",            "Sebring",            "Sebring",     "Sebring International Raceway.svg"),
    ("sebring",     "sebring_school",     "Sebring School",     "Sebring",     "Sebring School Circuit.svg"),
    ("silverstone", "silverstone",        "Silverstone",        "Silverstone", "Silverstone Grand Prix Circuit - ELMS.svg"),
    ("silverstone", "silverstone_international","Silverstone International","Silverstone","Silverstone International Circuit.svg"),
    ("silverstone", "silverstone_national","Silverstone National","Silverstone", "Silverstone National Circuit.svg"),
    ("spa",         "spa",                "Spa",                "Spa",         "Circuit de Spa-Francorchamps.svg"),
    ("spa",         "spa_endurance",      "Spa Endurance",      "Spa",         "Circuit de Spa-Francorchamps Endurance.svg"),
    # ── US TRACK PASS (anteprima): Daytona e Laguna Seca confermati con la
    #    1.4; Watkins Glen, Road Atlanta, Indianapolis e Long Beach dal
    #    teaser del 4 luglio. Gli SVG delle mappe arriveranno con le piste;
    #    card, loghi e overview sono gia' pronti. ──
    ("daytona",      "daytona",      "Daytona",       "Daytona",      "Daytona International Speedway.svg"),
    ("lagunaseca",   "lagunaseca",   "Laguna Seca",   "LagunaSeca",   "WeatherTech Raceway Laguna Seca.svg"),
    ("watkinsglen",  "watkinsglen",  "Watkins Glen",  "WatkinsGlen",  "Watkins Glen International.svg"),
    ("roadatlanta",  "roadatlanta",  "Road Atlanta",  "RoadAtlanta",  "Michelin Raceway Road Atlanta.svg"),
    ("indianapolis", "indianapolis", "Indianapolis",  "Indianapolis", "Indianapolis Motor Speedway.svg"),
    ("longbeach",    "longbeach",    "Long Beach",    "LongBeach",    "Long Beach Street Circuit.svg"),
]


_MAP_ROTATION = {   # gradi orari per la mappa-circuito di certe piste
    "fuji": 90,
}

# ROTAZIONI STILIZZATE (rich. 24/07 sera): angoli salvati dall'utente
# col tool tools/gira_stilizzate.py — le card erano "orientate alla
# cazzo". Chiave = stem SVG decodificato; vince sul vecchio
# _MAP_ROTATION. Cache con controllo mtime (il tool scrive a parte).
_STYL_ROT_FP = (Path(__file__).resolve().parent.parent / "settings"
                / "stylized_rotations.json")
_styl_rot_cache = [None, 0.0]     # (dict, mtime)


def _styl_rot9(cmap, base=""):
    try:
        import re as _r
        stem = _r.sub(r"#U([0-9a-fA-F]{4})",
                      lambda m: chr(int(m.group(1), 16)),
                      str(cmap or "").rsplit(".", 1)[0])
        try:
            mt = _STYL_ROT_FP.stat().st_mtime
        except OSError:
            mt = 0.0
        if _styl_rot_cache[0] is None or _styl_rot_cache[1] != mt:
            try:
                import json as _j
                _styl_rot_cache[0] = _j.loads(
                    _STYL_ROT_FP.read_text(encoding="utf-8"))
            except Exception:
                _styl_rot_cache[0] = {}
            _styl_rot_cache[1] = mt
        v = _styl_rot_cache[0].get(stem)
        if v is not None:
            return float(v)
    except Exception:
        pass
    return float(_MAP_ROTATION.get(base or "", 0))




class _Card(QFrame):
    """Carta-pista a forma di carta da gioco. Sfondo da assets/trackcards/<key>.jpg
    (fallback bianco), nome pista in basso, angoli arrotondati. Cliccabile:
    chiama on_click(idx). setSelected() evidenzia la carta a fuoco."""
    RADIUS = 13
    ZOOM_REST = 1.12   # zoom a riposo; in hover scende a 1.0 (zoom out)
    _DIR = Path(__file__).resolve().parent.parent / "assets" / "trackcards"

    def __init__(self, track=None, bgkey=None, name=None, logo=None, cmap=None, idx=-1, parent=None,
                 show_name=True, cat=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        self._idx = idx
        self._name = (name.upper() if name else name) if show_name else None
        self.on_click = None
        self._selected = False
        self._hover = 0.0          # progresso hover 0..1 (per il fade)
        self._hover_t = 0.0        # target hover
        self._htimer = QTimer(self)
        self._htimer.setInterval(16)
        self._htimer.timeout.connect(self._htick)
        self._bg = self._load(bgkey)          # solo foto dedicata, niente fallback
        self._logo = self._load_logo(logo)
        self._cat = cat
        self._locked = (cat == "imsa")   # IMSA chiusa (rich. 24/07)
        self._map = self._load_map(cmap)
        self._map_rot = _styl_rot9(cmap, track)   # angolo salvato dal tool
        self._op = QGraphicsOpacityEffect(self)
        self._op.setOpacity(1.0)
        self.setGraphicsEffect(self._op)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def _load(self, *keys):
        for k in keys:
            if not k:
                continue
            for ext in ("jpg", "jpeg", "png", "webp"):
                p = self._DIR / f"{k}.{ext}"
                if p.exists():
                    pm = QPixmap(str(p))
                    if not pm.isNull():
                        return pm
        return None

    def _load_logo(self, logo):
        if not logo or QSvgRenderer is None:
            return None
        p = _OV_TRACKLOGO_DIR / f"{logo}.svg"
        if not p.exists():
            return None
        r = QSvgRenderer(str(p))
        return r if r.isValid() else None

    def _load_map(self, cmap):
        if not cmap or QSvgRenderer is None:
            return None
        p = _OV_TRACKMAPS_SVG_DIR / cmap
        if not p.exists():
            return None
        r = QSvgRenderer(str(p))
        return r if r.isValid() else None

    def setSelected(self, on):
        if on != self._selected:
            self._selected = on
            self.update()

    def setOpacityF(self, v):
        self._op.setOpacity(max(0.0, min(1.0, v)))

    def mousePressEvent(self, e):
        if getattr(self, "_locked", False):
            e.accept()
            return                       # pista IMSA bloccata: click morto
        if e.button() == Qt.LeftButton and self.on_click and self._idx >= 0:
            self.on_click(self._idx)
            e.accept()

    # ── hover: fade rosso + zoom out ──
    def enterEvent(self, e):
        self._hover_t = 1.0
        if not self._htimer.isActive():
            self._htimer.start()

    def leaveEvent(self, e):
        self._hover_t = 0.0
        if not self._htimer.isActive():
            self._htimer.start()

    def _htick(self):
        self._hover += (self._hover_t - self._hover) * 0.10   # più lento
        if abs(self._hover_t - self._hover) < 0.004:
            self._hover = self._hover_t
            self._htimer.stop()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self.RADIUS, self.RADIUS)
        p.setClipPath(path)
        # sfondo (con zoom: a riposo ingrandito, in hover fa zoom out verso il fill)
        hs = self._hover * self._hover * (3.0 - 2.0 * self._hover)   # smoothstep: morbido
        if self._bg is not None and not self._bg.isNull():
            z = self.ZOOM_REST + (1.0 - self.ZOOM_REST) * hs
            sc = self._bg.scaled(QSize(int(self.width() * z), int(self.height() * z)),
                                 Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            p.drawPixmap(-(sc.width() - self.width()) // 2,
                         -(sc.height() - self.height()) // 2, sc)
        else:
            p.fillRect(self.rect(), QColor(255, 255, 255, 240))
        # velo rosso in dissolvenza sull'hover (sopra la foto)
        if self._hover > 0.0:
            p.fillRect(self.rect(), QColor(255, 29, 67, int(178 * hs)))
        # nome pista su gradiente scuro — svanisce in hover (stesso hs dello zoom)
        if self._name:
            h = self.height()
            band = max(28, int(h * 0.30))
            _nf = 1.0 - hs
            g = QLinearGradient(0, h - band, 0, h)
            g.setColorAt(0.0, QColor(0, 0, 0, 0))
            g.setColorAt(1.0, QColor(0, 0, 0, int(185 * _nf)))
            p.fillRect(0, h - band, self.width(), band, QBrush(g))
            from PySide6.QtGui import QFontMetrics
            f = QFont("Archivo SemiExpanded")
            f.setWeight(QFont.Medium)
            avail = self.width() - 16
            size = max(11, int(self.width() * 0.115))
            while size > 9:
                f.setPixelSize(size)
                if QFontMetrics(f).horizontalAdvance(self._name) <= avail:
                    break
                size -= 1
            p.setFont(f)
            p.setPen(QColor(255, 255, 255, int(255 * _nf)))
            p.drawText(QRectF(8, h - band, self.width() - 16, band - 8),
                       Qt.AlignHCenter | Qt.AlignBottom, self._name)
        # linee nell'angolo basso-destra: fuori a riposo, entrano in hover (stesso hs)
        if hs > 0.001:
            try:
                from PySide6.QtSvg import QSvgRenderer
                _sz = self.width() * 0.5
                _off = _sz * (1.0 - hs)            # offset: fuori -> in posizione
                p.setOpacity(hs)
                QSvgRenderer(QByteArray(_MenuHeader._CORNER_SVG)).render(
                    p, QRectF(self.width() - _sz + _off,
                              self.height() - _sz + _off, _sz, _sz))
                p.setOpacity(1.0)
            except Exception:
                pass
        # overlay hover (sopra a tutto): logo in alto + mappa circuito bianca sotto
        if self._hover > 0.0:
            W, H = self.width(), self.height()
            p.setOpacity(hs)
            # logo, spostato più in alto
            if self._logo is not None:
                ds = self._logo.defaultSize()
                if ds.width() > 0 and ds.height() > 0:
                    ar = ds.width() / ds.height()
                    lw = W * 0.55
                    lh = lw / ar
                    cap = H * 0.24
                    if lh > cap:
                        lh = cap
                        lw = lh * ar
                    self._logo.render(p, QRectF((W - lw) / 2.0, H * 0.09, lw, lh))
            # mappa circuito (colori originali), sotto al logo, con rotazione opzionale
            if self._map is not None:
                ds = self._map.defaultSize()
                if ds.width() > 0 and ds.height() > 0:
                    # angolo LIBERO (tool gira_stilizzate): fit sul
                    # bounding box ruotato, niente piu' scatti 90
                    rot = float(self._map_rot or 0.0)
                    _aw, _ah = float(ds.width()), float(ds.height())
                    _th = math.radians(rot)
                    _bw = abs(_aw * math.cos(_th)) \
                        + abs(_ah * math.sin(_th))
                    _bh = abs(_aw * math.sin(_th)) \
                        + abs(_ah * math.cos(_th))
                    _s = min(W * 0.78 / max(1.0, _bw),
                             H * 0.34 / max(1.0, _bh))
                    _mh = _bh * _s
                    p.save()
                    p.translate(W / 2.0, H * 0.40 + _mh / 2.0)
                    if rot:
                        p.rotate(rot)
                    self._map.render(p, QRectF(-_aw * _s / 2.0,
                                               -_ah * _s / 2.0,
                                               _aw * _s, _ah * _s))
                    p.restore()
            p.setOpacity(1.0)
        # bordo bianco rimosso
        if getattr(self, "_locked", False):
            _draw_card_lock9(p, self.width(), self.height(), self.RADIUS)
        p.setClipping(False)




class _PartnersBar(QWidget):
    """Strip partner (assets/partners.svg) centrata: sotto le card, sopra
    il footer. Solo estetica, nessuna interazione."""
    H = 84

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.H)
        self._r = None
        if QSvgRenderer is not None:
            _p = Path(__file__).resolve().parent.parent / "assets" / "partners.svg"
            if _p.exists():
                r = QSvgRenderer(str(_p))
                self._r = r if r.isValid() else None
        if self._r is None:
            self.hide()

    def paintEvent(self, e):
        if self._r is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        ds = self._r.defaultSize()
        if ds.width() <= 0 or ds.height() <= 0:
            return
        ar = ds.width() / ds.height()
        h = self.height() - 8
        w = h * ar
        maxw = self.width() * 0.96
        if w > maxw:
            w = maxw
            h = w / ar
        self._r.render(p, QRectF((self.width() - w) / 2.0,
                                 (self.height() - h) / 2.0, w, h))


class _CatCard(QFrame):
    """Card di categoria (WEC / ELMS / IMSA): logo serie centrato,
    velo rosso e zoom-out in hover come le card pista."""
    RADIUS = 13

    # colore del velo hover per serie: WEC blu notte, ELMS arancio, IMSA rosso
    _HOVER = {
        "wec":  QColor(10, 0, 50, 215),     # #0a0032 (scuro: alpha piu' alto)
        "elms": QColor(255, 95, 0, 150),    # #ff5f00
        "imsa": QColor(255, 29, 67, 150),   # rosso come le card pista
    }

    def __init__(self, key, on_click=None, parent=None):
        super().__init__(parent)
        self._key = key
        self.on_click = on_click
        self._hover = 0.0
        self._hover_t = 0.0
        self._htimer = QTimer(self)
        self._htimer.setInterval(16)
        self._htimer.timeout.connect(self._htick)
        self._logo = None
        if QSvgRenderer is not None:
            _p = Path(__file__).resolve().parent.parent / "assets" / f"{key}.svg"
            if _p.exists():
                r = QSvgRenderer(str(_p))
                self._logo = r if r.isValid() else None
        # foto card categoria (se presente): assets/catcards/<key>.jpg|png|webp
        self._photo = None
        _cdir = Path(__file__).resolve().parent.parent / "assets" / "catcards"
        for _ext in ("jpg", "jpeg", "png", "webp"):
            _fp = _cdir / f"{key}.{_ext}"
            if _fp.exists():
                _pm = QPixmap(str(_fp))
                if not _pm.isNull():
                    self._photo = _pm
                    break
        # IMSA CHIUSA (rich. 24/07): piste da finire a mano prima
        # dell'update — card bloccata col lucchetto della sessione
        self._locked = (key == "imsa")
        self.setCursor(Qt.ForbiddenCursor if self._locked
                       else Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def enterEvent(self, e):
        self._hover_t = 1.0
        if not self._htimer.isActive():
            self._htimer.start()

    def leaveEvent(self, e):
        self._hover_t = 0.0
        if not self._htimer.isActive():
            self._htimer.start()

    def _htick(self):
        self._hover += (self._hover_t - self._hover) * 0.12
        if abs(self._hover_t - self._hover) < 0.004:
            self._hover = self._hover_t
            self._htimer.stop()
        self.update()

    def mousePressEvent(self, e):
        if getattr(self, "_locked", False):
            e.accept()
            return                       # IMSA bloccata: click morto
        if e.button() == Qt.LeftButton and self.on_click:
            self.on_click(self._key)
            e.accept()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self.RADIUS, self.RADIUS)
        p.setClipPath(path)
        hs = self._hover * self._hover * (3.0 - 2.0 * self._hover)
        # fondo scuro con velo del brand in hover
        p.fillRect(self.rect(), QColor(10, 16, 46, 235))
        # foto categoria (assets/catcards/<key>.*): STESSO taglio delle card
        # pista (crop centrato + zoom a riposo, zoom-out in hover)
        if getattr(self, "_photo", None) is not None:
            _z = 1.12 + (1.0 - 1.12) * hs
            sc = self._photo.scaled(
                QSize(int(self.width() * _z), int(self.height() * _z)),
                Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.drawPixmap(-(sc.width() - self.width()) // 2,
                         -(sc.height() - self.height()) // 2, sc)
        if hs > 0.0:
            _hc = self._HOVER.get(self._key, QColor(255, 29, 67, 150))
            p.fillRect(self.rect(), QColor(_hc.red(), _hc.green(), _hc.blue(),
                                           int(_hc.alpha() * hs)))
        # linee nell'angolo basso-destra: fuori a riposo, entrano in hover
        # (STESSA entrata delle card circuito)
        if hs > 0.001:
            try:
                from PySide6.QtSvg import QSvgRenderer as _QSR
                _sz = self.width() * 0.5
                _off = _sz * (1.0 - hs)
                p.setOpacity(hs)
                _QSR(QByteArray(_MenuHeader._CORNER_SVG)).render(
                    p, QRectF(self.width() - _sz + _off,
                              self.height() - _sz + _off, _sz, _sz))
                p.setOpacity(1.0)
            except Exception:
                pass
        # bordo sottile
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 40 + int(120 * hs)), 1.4))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, self.RADIUS, self.RADIUS)
        p.setClipPath(path)
        # nome serie in basso su gradiente scuro — svanisce in hover (come _Card)
        _nm = (self._key or "").upper()
        if _nm:
            h = self.height()
            band = max(28, int(h * 0.30))
            _nf = 1.0 - hs
            g = QLinearGradient(0, h - band, 0, h)
            g.setColorAt(0.0, QColor(0, 0, 0, 0))
            g.setColorAt(1.0, QColor(0, 0, 0, int(185 * _nf)))
            p.fillRect(0, h - band, self.width(), band, QBrush(g))
            f = QFont("Archivo SemiExpanded")
            f.setWeight(QFont.Medium)
            f.setPixelSize(max(11, int(self.width() * 0.115)))
            p.setFont(f)
            p.setPen(QColor(255, 255, 255, int(255 * _nf)))
            p.drawText(QRectF(8, h - band, self.width() - 16, band - 8),
                       Qt.AlignHCenter | Qt.AlignBottom, _nm)
        # logo serie centrato: COMPARE in hover
        if self._logo is not None and hs > 0.001:
            ds = self._logo.defaultSize()
            if ds.width() > 0 and ds.height() > 0:
                ar = ds.width() / ds.height()
                W, H = self.width(), self.height()
                lw = W * (0.52 + 0.05 * hs)
                lh = lw / ar
                cap = H * 0.42
                if lh > cap:
                    lh = cap
                    lw = lh * ar
                p.setOpacity(hs)
                self._logo.render(p, QRectF((W - lw) / 2.0, (H - lh) / 2.0, lw, lh))
                p.setOpacity(1.0)
        if getattr(self, "_locked", False):
            _draw_card_lock9(p, self.width(), self.height(), self.RADIUS)
        p.setClipping(False)


class _CatRow(QWidget):
    """Le tre card categoria affiancate a PROPORZIONE FISSA (carta da gioco,
    come le card pista): mai stirate, sempre centrate nello spazio."""
    RATIO = 1.4       # altezza / larghezza (stesso delle card pista)
    GAP = 18
    MARGIN = 24

    def __init__(self, keys, on_click=None, parent=None):
        super().__init__(parent)
        self._cards = [_CatCard(k, on_click=on_click, parent=self) for k in keys]

    def resizeEvent(self, e):
        super().resizeEvent(e)
        n = len(self._cards)
        availW = max(1, self.width() - 2 * self.MARGIN - (n - 1) * self.GAP)
        availH = max(1, self.height() - 2 * self.MARGIN)
        cw = availW / n
        ch = cw * self.RATIO
        if ch > availH:
            ch = availH
            cw = ch / self.RATIO
        total = n * cw + (n - 1) * self.GAP
        x0 = (self.width() - total) / 2.0
        y0 = (self.height() - ch) / 2.0
        for i, c in enumerate(self._cards):
            c.setFixedSize(int(cw), int(ch))
            c.move(int(x0 + i * (cw + self.GAP)), int(y0))


class _CategoryMenu(QWidget):
    """Menu a due livelli: 3 card categoria (WEC / ELMS / IMSA); click su una
    -> deck delle card pista FILTRATE per quel campionato, con freccia per
    tornare alle categorie. Calendari 2026."""

    _CATS = ("wec", "elms", "imsa")
    _BASES = {
        # FIA WEC 2026 (8 round) + Monza (storica WEC, tenuta qui per non
        # perdere la pista dal menu)
        "wec": {"imola", "spa", "lemans", "interlagos", "cota", "fuji",
                "lusail", "bahrain", "monza", "sebring"},
        # ELMS 2026 (6 round europei)
        "elms": {"barcelona", "paulricard", "imola", "spa", "silverstone",
                 "portimao"},
        # IMSA 2026 — le tappe presenti in LMU/US Track Pass
        "imsa": {"daytona", "sebring", "longbeach", "lagunaseca",
                 "watkinsglen", "indianapolis", "roadatlanta"},
    }

    def __init__(self, on_open=None, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QStackedLayout
        self._on_open = on_open
        self._stack = QStackedLayout(self)
        # ── pagina 0: le tre categorie, proporzione da carta (mai distorte) ──
        self._stack.addWidget(_CatRow(self._CATS, on_click=self._open_cat))
        # ── pagine 1..3: deck filtrati (creati subito: card leggere) ──
        # UN SOLO deck: tutte le card in ordine WEC -> ELMS -> IMSA, senza
        # doppioni (base sia WEC che ELMS -> resta a ELMS, es. Imola/Spa).
        # Il deck gira in loop; cambia solo il LOGO in alto secondo la card di
        # testa. Dalla card categoria si entra sulla prima pista di quella serie.
        def _cat_of(base):
            # Sebring e COTA sono nel GIOCO BASE (round WEC di LMU):
            # stanno con le WEC e NON sotto il lucchetto IMSA
            # (rich. utente 24/07 sera)
            if base in ("sebring", "cota"):
                return "wec"
            if base in self._BASES["imsa"]:
                return "imsa"
            if base in self._BASES["elms"]:
                return "elms"
            return "wec"
        entries = []
        for k in self._CATS:
            for i, e in enumerate(_TRACKS):
                if e[0] in self._BASES[k] and _cat_of(e[0]) == k:
                    entries.append((i, k))
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)
        deck = _CardDeck(on_open=self._open, entries=entries)
        self._deck = deck
        self._decks = {k: deck for k in self._CATS}    # compat
        self.cards = list(deck.cards)
        self._starts = {}
        for pos, (_i, k) in enumerate(entries):
            self._starts.setdefault(k, pos)
        deck._front_cb = self._front_changed
        self.on_cat_change = None            # lo setta _RootCanvas (logo)
        self._cur_cat = self._CATS[0]
        col.addWidget(deck, 1)
        self._stack.addWidget(page)

    def _open_cat(self, key):
        self._stack.setCurrentIndex(1)
        d = self._deck
        d._sel = d._pos = float(self._starts.get(key, 0))
        d._relayout()
        d._last_front = None
        d._notify_front()

    def _front_changed(self, fi):
        cats = self._deck._cats
        k = cats[fi] if 0 <= fi < len(cats) else None
        if k:
            self._cur_cat = k
            if self.on_cat_change:
                self.on_cat_change(k)

    def _open(self, idx):
        if self._on_open:
            self._on_open(idx)


class _CardDeck(QWidget):
    """Carosello lineare infinito: 4 carte per volta, affiancate (non sovrapposte),
    scorrono in linea e in loop continuo. Rotella per scorrere di una; click su una
    carta la porta in testa (percorso più breve)."""
    RATIO = 1.4        # altezza / larghezza (carta da gioco)
    VISIBLE = 4        # carte visibili per volta
    GAP = 14           # spazio tra le carte
    MARGIN = 16

    def __init__(self, on_open=None, parent=None, bases=None, cat=None,
                 entries=None):
        super().__init__(parent)
        self._on_open = on_open
        self.cards = []
        self._cats = []
        self._front_cb = None
        self._last_front = None
        if entries is not None:
            # ordine FISSO (WEC->ELMS->IMSA): niente riordino per popolazione
            self._fixed_order = True
            for i, k in entries:
                base, bgkey, name, logo, cmap = _TRACKS[i]
                c = _Card(base, bgkey, name, logo, cmap, i, self, cat=k)
                c.on_click = self._clicked
                c._trk = (base, bgkey, name, logo, cmap)
                self.cards.append(c)
                self._cats.append(k)
        else:
            for i, (base, bgkey, name, logo, cmap) in enumerate(_TRACKS):
                if bases is not None and base not in bases:
                    continue
                c = _Card(base, bgkey, name, logo, cmap, i, self, cat=cat)
                c.on_click = self._clicked
                c._trk = (base, bgkey, name, logo, cmap)   # per riordino popolazione
                self.cards.append(c)
        self.reorder()                                  # piste più popolate a sinistra
        self._sel = 0.0    # indice di testa (target, può uscire da [0,N): loop)
        self._pos = 0.0    # posizione animata
        self.setMinimumHeight(240)
        self._anim = QTimer(self)
        self._anim.setInterval(16)
        self._anim.timeout.connect(self._tick)
        # frecce laterali: scorrono di una card (oltre alla rotella)
        self._arr_l = self._mk_arrow("chevron_left", -1)
        self._arr_r = self._mk_arrow("chevron_right", +1)

    def _mk_arrow(self, icon, delta):
        b = QPushButton(icon, self)
        b.setCursor(Qt.PointingHandCursor)
        b.setFixedSize(40, 40)
        # STESSO stile della freccia indietro (coerenza card/elementi)
        b.setStyleSheet(
            "QPushButton{font-family:'Material Symbols Rounded';font-size:26px;"
            "color:#fff;background:rgba(255,255,255,0.08);border:none;"
            "border-radius:8px;}"
            "QPushButton:hover{background:rgba(255,29,67,0.55);}")
        b.clicked.connect(lambda _=False, d=delta: self._scroll(d))
        b.raise_()
        return b

    def _relayout(self):
        n = len(self.cards)
        innerW = max(1.0, self.width() - 2 * self.MARGIN)
        step = innerW / self.VISIBLE
        availh = max(90, self.height() - 2 * self.MARGIN)
        cw = step - self.GAP
        ch = cw * self.RATIO
        if ch > availh:
            ch = availh
            cw = ch / self.RATIO
        total = n * step
        offset = self._pos * step
        y = self.MARGIN + (availh - ch) / 2.0
        pad = (step - cw) / 2.0
        for i, c in enumerate(self.cards):
            base = (i * step - offset) % total
            x = None
            for cand in (base, base - total):   # copia che rientra da sinistra
                if -step < cand < innerW:
                    x = cand
                    break
            if x is None:
                c.setVisible(False)
                continue
            c.setVisible(True)
            c.setOpacityF(1.0)
            c.setFixedSize(int(cw), int(ch))
            c.move(int(self.MARGIN + x + pad), int(y))
        # frecce laterali: centrate in verticale, sopra le carte
        _ay = int(self.MARGIN + (availh - 40) / 2.0)
        if getattr(self, "_arr_l", None) is not None:
            self._arr_l.move(2, _ay); self._arr_l.raise_()
            self._arr_r.move(self.width() - 42, _ay); self._arr_r.raise_()

    # ── scorrimento (infinito) + animazione ──
    def _clicked(self, idx):
        if self._on_open:
            self._on_open(idx)      # entra nella schermata originale

    def select(self, i):
        n = len(self.cards)
        cur = self._sel % n
        d = (i - cur + n) % n
        if d > n / 2:
            d -= n                      # percorso più breve nel loop
        self._sel += d
        if not self._anim.isActive():
            self._anim.start()

    def _scroll(self, delta):
        # TRICK: a fine deck si passa alla categoria successiva (e a inizio
        # deck alla precedente) — giro infinito WEC -> ELMS -> IMSA -> WEC
        n = len(self.cards)
        wrap = getattr(self, "_on_wrap", None)
        if wrap is not None and n:
            cur = int(round(self._sel)) % n
            if delta > 0 and cur == n - 1:
                wrap(+1); return
            if delta < 0 and cur == 0:
                wrap(-1); return
        self._sel += delta
        if not self._anim.isActive():
            self._anim.start()

    def _tick(self):
        self._notify_front()
        self._pos += (self._sel - self._pos) * 0.18
        if abs(self._sel - self._pos) < 0.002:
            n = len(self.cards)
            self._sel = float(int(round(self._sel)) % n)   # normalizza nel loop
            self._pos = self._sel
            self._anim.stop()
        self._relayout()

    def _notify_front(self):
        n = len(self.cards)
        if not n:
            return
        fi = int(round(self._sel)) % n
        if fi != self._last_front:
            self._last_front = fi
            if self._front_cb:
                self._front_cb(fi)

    def resizeEvent(self, e):
        self._relayout()

    def showEvent(self, e):
        super().showEvent(e)
        self.reorder()
        self._relayout()

    def reorder(self):
        """Riordina le card: piste con più sessioni locali a sinistra.
        Con ordine FISSO (deck unico per categorie) non tocca nulla."""
        if getattr(self, "_fixed_order", False):
            return
        """
        Conteggio per logo-circuito (raggruppa le varianti) + variante usata."""
        try:
            sess = _db.list_sessions()
        except Exception:
            sess = []
        by_logo = {}; by_layout = {}
        for s in sess:
            trk = s.get("track") or ""
            st = _track_logo_stem(trk)
            if st:
                by_logo[st] = by_logo.get(st, 0) + 1
            lk = _track_layout_key(trk)
            if lk:
                by_layout[lk] = by_layout.get(lk, 0) + 1

        def _key(c):
            base, bgkey, name, logo, cmap = getattr(c, "_trk", ("", "", "", "", ""))
            cstem = cmap[:-4] if (cmap or "").lower().endswith(".svg") else (cmap or "")
            lay = by_layout.get(cstem, 0)
            lg = by_logo.get(logo or "", 0)
            return (lay, lg)

        order = sorted(range(len(self.cards)),
                       key=lambda i: (-_key(self.cards[i])[0],   # sessioni del layout
                                      -_key(self.cards[i])[1],   # poi totale circuito
                                      i))
        self.cards = [self.cards[i] for i in order]
        self._sel = 0.0; self._pos = 0.0
        self._relayout()

    def wheelEvent(self, e):
        self._scroll(1 if e.angleDelta().y() < 0 else -1)
        e.accept()


_HELMET_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none"'
    b' stroke="#ffffff" stroke-width="3" stroke-linejoin="round" stroke-linecap="round">'
    b'<path d="M12 33 C12 19 20 11 32 11 C44 11 52 19 52 33 L52 40'
    b' C52 45 48 48 43 48 L21 48 C16 48 12 45 12 40 Z"/>'
    b'<path d="M16 32 C22 27 42 27 48 32 L46.5 39 C41 42 23 42 17.5 39 Z"/></svg>')


class _TeamAvatar(QLabel):
    """SVG fisso (assets/helmet.svg). Nessun upload."""
    def __init__(self):
        super().__init__()
        self.setFixedSize(66, 66)
        self.setAlignment(Qt.AlignCenter)
        self.setObjectName("mhAvatar")
        self.setStyleSheet("#mhAvatar{background:transparent;border:none;}")
        self._load()

    def _load(self):
        try:
            from PySide6.QtGui import QPixmap, QPainter
            from PySide6.QtCore import QRectF
            _hp = Path(__file__).resolve().parent.parent / "assets" / "helmet.svg"
            data = _hp.read_bytes() if _hp.exists() else _HELMET_SVG
            if QSvgRenderer is None:
                return
            r = QSvgRenderer(QByteArray(data))
            box = 56
            ds = r.defaultSize()
            dw, dh = ds.width(), ds.height()
            if dw > 0 and dh > 0:
                s = min(box / dw, box / dh)        # fit mantenendo proporzioni
                tw, th = dw * s, dh * s
            else:
                tw = th = box
            pm = QPixmap(box, box); pm.fill(Qt.transparent)
            p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing, True)
            r.render(p, QRectF((box - tw) / 2.0, (box - th) / 2.0, tw, th))
            p.end()
            self.setPixmap(pm)
        except Exception:
            pass




class _GearButton(QPushButton):
    """Ingranaggio settings: bianco, pieno in hover e RUOTA finche' il mouse
    e' sopra (dipinto a mano: QSS non sa ruotare)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._angle = 0.0
        self._filled = False
        self._t = QTimer(self)
        self._t.setInterval(16)
        self._t.timeout.connect(self._tick)
        self.setFixedSize(46, 46)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("background:transparent;border:none;")

    def _tick(self):
        # verso il target (45 in hover, 0 fuori) e stop ad arrivo
        _tgt = 45.0 if self._filled else 0.0
        step = 4.5 if self._filled else -4.5
        self._angle += step
        if (step > 0 and self._angle >= _tgt) or (step < 0 and self._angle <= _tgt):
            self._angle = _tgt
            self._t.stop()
        self.update()

    def enterEvent(self, e):
        self._filled = True
        self._t.start()
        cb = getattr(self, "_hover_cb", None)
        if cb:
            cb(True)
        self.update()

    def leaveEvent(self, e):
        self._filled = False
        self._t.start()          # anima il ritorno a 0
        cb = getattr(self, "_hover_cb", None)
        if cb:
            cb(False)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        f = QFont("Material Icons" if self._filled
                  else "Material Symbols Rounded")
        f.setPixelSize(30)
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        w, h = self.width(), self.height()
        p.translate(w / 2.0, h / 2.0)
        p.rotate(self._angle)
        p.drawText(QRectF(-w / 2.0, -h / 2.0, w, h), Qt.AlignCenter, "settings")


class _MenuHeader(QFrame):
    """Card in alto del menu: pilota, campo TEAM (editabile, salva nel profilo)
    e numero di sessioni locali. Il team salvato qui alimenta get_team() →
    card REF/online."""
    _CORNER_SVG = (b'<svg width="177" height="177" viewBox="0 0 177 177" '
                   b'xmlns="http://www.w3.org/2000/svg"><path d="M95.157 81.8186L177.001 '
                   b'163.662V152.245L100.891 76.135L95.1822 81.8439L95.157 81.8186ZM114.203 '
                   b'62.7722L176.976 125.57V114.152L119.912 57.0886L114.203 62.7975V62.7722ZM133.25 '
                   b'43.7258L177.001 87.4517V76.034L138.984 38.017L133.275 43.7258H133.25ZM152.296 '
                   b'24.6795L177.001 49.3842V37.9665L158.03 18.9959L152.321 24.7047L152.296 '
                   b'24.6795ZM171.343 5.63308L177.001 11.2914V0L171.343 5.65834V5.63308ZM163.663 '
                   b'176.975L81.8195 95.1561L76.1106 100.865L152.22 176.975H163.638H163.663ZM125.571 '
                   b'176.975L62.7983 114.177L57.0895 119.886L114.153 176.949H125.571V176.975ZM87.4778 '
                   b'176.975L43.7267 133.224L38.0178 138.932L76.0348 176.949H87.4525L87.4778 '
                   b'176.975ZM49.385 176.975L24.6803 152.27L18.9714 157.979L37.942 176.949H49.3598L49.385 '
                   b'176.975ZM0.00084639 176.975H11.2923L5.63393 171.316L-0.0244141 176.975H0.00084639Z" '
                   b'fill="white"/></svg>')

    def paintEvent(self, e):
        super().paintEvent(e)
        try:
            from PySide6.QtGui import QPainter, QPainterPath
            from PySide6.QtSvg import QSvgRenderer
            p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
            path = QPainterPath(); path.addRoundedRect(QRectF(self.rect()), 14, 14)
            p.setClipPath(path)                       # resta dentro la card arrotondata
            sz = 116
            x = self.width() - sz; y = self.height() - sz
            p.setOpacity(1.0)
            QSvgRenderer(QByteArray(self._CORNER_SVG)).render(p, QRectF(x, y, sz, sz))
            p.end()
        except Exception:
            pass

    def __init__(self, parent=None, on_community=None):
        super().__init__(parent)
        self._on_community = on_community
        self.setObjectName("menuHdr")
        self.setFixedHeight(126)
        self.setStyleSheet(
            "#menuHdr{background:rgba(255,255,255,0.07);border:none;border-radius:14px;}"
            "#mhCap{color:#9fb0c8;font-family:'Archivo SemiExpanded';font-size:10px;font-weight:700;"
            "letter-spacing:2px;background:transparent;}"
            "#mhVal{color:#ffffff;font-family:'Archivo SemiExpanded';font-size:20px;font-weight:700;"
            "background:transparent;}"
            "#mhTeam{color:#ffffff;font-family:'Archivo SemiExpanded';font-size:18px;font-weight:600;"
            "background:rgba(0,0,0,0.22);border:1px solid rgba(255,255,255,0.18);"
            "border-radius:8px;padding:6px 12px;}"
            "#mhTeam:focus{border:1px solid #ff1d43;}")
        h = QHBoxLayout(self); h.setContentsMargins(24, 12, 24, 12); h.setSpacing(20)

        # AVATAR pilota = CASCO con la livrea scelta (click = menu 20 livree)
        self.avatar = _SvgBox()
        self.avatar.setFixedSize(66, 66)
        try:
            from ui.icons import helmet_svg_bytes
            _hc0 = _load_profile().get("helmet_color", "#fd160e")
            self.avatar.load(helmet_svg_bytes(_hc0))
        except Exception:
            _hp = Path(__file__).resolve().parent.parent / "assets" / "helmet.svg"
            if _hp.exists():
                self.avatar.load(str(_hp))
        self.avatar.setCursor(Qt.PointingHandCursor)
        self.avatar.setToolTip("Choose your helmet livery")
        self.avatar.mousePressEvent = lambda e: self._pick_helmet()
        h.addWidget(self.avatar, 0, Qt.AlignVCenter)

        # PILOTA + TEAM impilati (team SOTTO il nome, campo piu' piccolo)
        c1w = QWidget(); c1w.setStyleSheet("background:transparent;")
        c1 = QVBoxLayout(c1w); c1.setContentsMargins(0, 0, 0, 0); c1.setSpacing(2)
        _d = QLabel("DRIVER"); _d.setObjectName("mhCap"); c1.addWidget(_d)
        self.lb_driver = QLabel("\u2014"); self.lb_driver.setObjectName("mhVal")
        c1.addWidget(self.lb_driver)
        _t = QLabel("TEAM"); _t.setObjectName("mhCap")
        _t.setStyleSheet("margin-top:5px;")
        c1.addWidget(_t)
        # team in SOLA LETTURA (piccolo): si modifica dalle OPTIONS
        self.lb_team = QLabel("—")
        self.lb_team.setStyleSheet(
            "color:#e8ebf2;font-family:'Archivo SemiExpanded';font-size:14px;"
            "font-weight:600;background:transparent;")
        c1.addWidget(self.lb_team)
        h.addWidget(c1w, 0, Qt.AlignVCenter)

        # SESSIONI LOCALI: subito dopo team — numero sopra, "Sessions" sotto (bianco)
        c3w = QWidget(); c3w.setStyleSheet("background:transparent;")
        c3 = QVBoxLayout(c3w); c3.setContentsMargins(0, 0, 0, 0); c3.setSpacing(2)
        self.lb_sess = QLabel("0"); self.lb_sess.setObjectName("mhVal")
        self.lb_sess.setAlignment(Qt.AlignHCenter)
        c3.addWidget(self.lb_sess)
        cap = QLabel("MY SESSIONS")
        cap.setAlignment(Qt.AlignHCenter)
        cap.setStyleSheet("color:#ffffff;font-family:'Archivo SemiExpanded';font-size:13px;"
                          "font-weight:600;letter-spacing:1px;background:transparent;")
        c3.addWidget(cap)
        h.addWidget(c3w, 0, Qt.AlignVCenter)

        # DRIVERS ONLINE: numero di driver unici in classifica (dal Worker)
        c4w = QWidget(); c4w.setStyleSheet("background:transparent;")
        c4 = QVBoxLayout(c4w); c4.setContentsMargins(0, 0, 0, 0); c4.setSpacing(2)
        self.lb_drivers = QLabel("0"); self.lb_drivers.setObjectName("mhVal")
        self.lb_drivers.setAlignment(Qt.AlignHCenter)
        c4.addWidget(self.lb_drivers)
        cap2 = QLabel("DRIVERS")
        cap2.setAlignment(Qt.AlignHCenter)
        cap2.setStyleSheet("color:#ffffff;font-family:'Archivo SemiExpanded';font-size:13px;"
                           "font-weight:600;letter-spacing:1px;background:transparent;")
        c4.addWidget(cap2)

        # REF TIMES: record best attivi in classifica (dal Worker)
        c5w = QWidget(); c5w.setStyleSheet("background:transparent;")
        c5 = QVBoxLayout(c5w); c5.setContentsMargins(0, 0, 0, 0); c5.setSpacing(2)
        self.lb_ctimes = QLabel("0"); self.lb_ctimes.setObjectName("mhVal")
        self.lb_ctimes.setAlignment(Qt.AlignHCenter)
        c5.addWidget(self.lb_ctimes)
        cap3 = QLabel("REF TIMES")
        cap3.setAlignment(Qt.AlignHCenter)
        cap3.setStyleSheet("color:#ffffff;font-family:'Archivo SemiExpanded';font-size:13px;"
                           "font-weight:600;letter-spacing:1px;background:transparent;")
        c5.addWidget(cap3)

        # RISULTATI GARA: gare, vittorie, podi, top5, DNF (dalle sessioni gara)
        def _statcol(attr, cap):
            _w = QWidget(); _w.setStyleSheet("background:transparent;")
            _v = QVBoxLayout(_w)
            _v.setContentsMargins(0, 0, 0, 0); _v.setSpacing(2)
            _lb = QLabel("0"); _lb.setObjectName("mhVal")
            _lb.setAlignment(Qt.AlignHCenter)
            _v.addWidget(_lb)
            _c = QLabel(cap); _c.setAlignment(Qt.AlignHCenter)
            _c.setStyleSheet("color:#ffffff;font-family:'Archivo SemiExpanded';font-size:12px;"
                             "font-weight:600;letter-spacing:1px;"
                             "background:transparent;")
            _v.addWidget(_c)
            setattr(self, attr, _lb)
            h.addWidget(_w, 0, Qt.AlignVCenter)
        _statcol("lb_races", "RACES")
        _statcol("lb_wins", "WINS")
        _statcol("lb_podiums", "PODIUMS")
        _statcol("lb_top5", "TOP 5")
        _statcol("lb_dnf", "DNF")
        # dati COMMUNITY (online) spostati a DESTRA, dopo i risultati gara
        h.addWidget(c4w, 0, Qt.AlignVCenter)
        h.addWidget(c5w, 0, Qt.AlignVCenter)

        # rotella OPTIONS: SPOSTATA nel footer (in basso a destra);
        # l'attributo resta per compatibilita' col wiring esistente
        self._on_settings = None

        # tasto COMMUNITY RIMOSSO: spostato nella barra navigazione sotto
        # l'header (Setups / Overlay / Teams / Community).
        h.addStretch(1)

        self.refresh()

    def _pick_helmet(self):
        """Menu 20 livree casco: icona NITIDA (render 2x) + nome; la scelta
        va nel profilo e ricolora subito l'avatar."""
        try:
            from ui.icons import HELMET_COLORS, helmet_svg_bytes
            from PySide6.QtWidgets import QMenu
            from PySide6.QtSvg import QSvgRenderer
            from PySide6.QtGui import QPixmap, QIcon
            from PySide6.QtCore import QByteArray, QRectF, QSize

            def _icon(col, w=30, hh=24):
                pm = QPixmap(w * 2, hh * 2)          # 2x = niente sgranato
                pm.fill(Qt.transparent)
                pm.setDevicePixelRatio(2.0)
                r = QSvgRenderer(QByteArray(helmet_svg_bytes(col)))
                pp = QPainter(pm); pp.setRenderHint(QPainter.Antialiasing)
                r.render(pp, QRectF(0, 0, w, hh)); pp.end()
                return QIcon(pm)
            m = QMenu(self)
            m.setStyleSheet(
                "QMenu{background:#16181c;color:#f2f4f7;border:1px solid "
                "#2a2c30;font-family:Archivo SemiExpanded;font-size:12px;}"
                "QMenu::item{padding:4px 14px;}"
                "QMenu::item:selected{background:rgba(255,29,67,0.45);}")

            def _set(col):
                try:
                    d = _load_profile(); d["helmet_color"] = col
                    _save_profile(d)
                except Exception:
                    pass
                try:
                    self.avatar.load(helmet_svg_bytes(col))
                except Exception:
                    pass
                # aggiorna la livrea sui TUOI record online (classifiche)
                try:
                    from core import online as _onl
                    _pl = (_load_profile().get("driver") or "").strip()
                    if _pl:
                        _onl.update_helmet_async(_pl, col)
                except Exception:
                    pass
            for name, col in HELMET_COLORS:
                m.addAction(_icon(col), name, lambda c=col: _set(c))
            m.exec(self.avatar.mapToGlobal(self.avatar.rect().bottomLeft()))
        except Exception:
            pass

    def _save_team(self):
        t = self.ed_team.text().strip()[:30]
        try:
            d = _load_profile(); d["team"] = t; _save_profile(d)
        except Exception:
            pass

    def eventFilter(self, obj, e):
        try:
            from PySide6.QtCore import QEvent
            if obj is self.ed_team and e.type() == QEvent.FocusIn:
                self._team_timer.start()      # avvia il conto alla rovescia anche solo al click
        except Exception:
            pass
        return super().eventFilter(obj, e)

    def _team_commit(self):
        self._save_team()
        self.ed_team.clearFocus()             # via il cursore lampeggiante

    def refresh(self):
        try:
            prof = _load_profile()
        except Exception:
            prof = {}
        from core.utils import short_name as _sn
        self.lb_driver.setText((_sn(prof.get("driver") or "") or "\u2014").upper())
        self.lb_team.setText(prof.get("team", "") or "—")
        n = 0
        try:
            from core.paths import LOGS_DIR
            d = Path(LOGS_DIR)
            if d.exists():
                n = len(list(d.glob("*.lmtel")))
        except Exception:
            n = 0
        self.lb_sess.setText(_abbr_num(n))
        # risultati gara: gare, vittorie, podi, top5, DNF (dalle sessioni gara)
        try:
            from core.results import race_stats
            _rs = race_stats()
            # override MANUALE dal profilo (stat_*) per inserire lo storico
            # (es. dati 2024): se il campo e' impostato vince, senno' automatico
            for _k, _lb in (("races", self.lb_races), ("wins", self.lb_wins),
                            ("podiums", self.lb_podiums), ("top5", self.lb_top5),
                            ("dnf", self.lb_dnf)):
                _v = prof.get("stat_" + _k, _rs.get(_k, 0))
                _lb.setText(_abbr_num(int(_v)))
        except Exception:
            pass
        # online: driver unici + ref times (best attivi). Cache + refresh background.
        try:
            from core import online as _online
            self.lb_drivers.setText(_abbr_num(_online.drivers_count()))
            self.lb_ctimes.setText(_abbr_num(_online.refs_count()))
            _online.stats_async()
            QTimer.singleShot(1600, lambda: (
                self.lb_drivers.setText(_abbr_num(_online.drivers_count())),
                self.lb_ctimes.setText(_abbr_num(_online.refs_count()))))
        except Exception:
            pass

    def _go_community(self):
        if self._on_community:
            try:
                self._on_community()
            except Exception:
                pass


class _RootCanvas(QWidget):
    """Sfondo della pagina principale: blu pieno #000833.
    Contiene il banner e il carosello di 13 carte scorrevoli."""

    def __init__(self, on_open=None, parent=None, on_community=None,
                 on_setups=None, on_overlay=None, on_teams=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        # header: niente piu' tasto COMMUNITY (spostato nella barra sotto)
        self.banner = _MenuHeader()                  # pilota / team / stats
        root.addWidget(self.banner)

        # BARRA NAVIGAZIONE: card orizzontale piu' piccola tra header e
        # categorie. Setups (ex Settings) / Overlay / Teams / Community, piu'
        # spazio per opzioni app a destra. Community e' stato spostato qui
        # dalla card in alto.
        root.addWidget(self._build_navbar(on_setups, on_overlay, on_teams,
                                          on_community))

        self.deck = _CategoryMenu(on_open=on_open)   # WEC / ELMS / IMSA
        root.addWidget(self.deck, 1)
        self.cards = self.deck.cards
        # freccia + logo nella barra <-> deck: clic torna alle categorie; freccia
        # e logo visibili solo dentro un deck (pagina > 0), col logo del
        # campionato aperto.
        try:
            self._navback.clicked.connect(
                lambda _=False: self.deck._stack.setCurrentIndex(0))
            self.deck._stack.currentChanged.connect(self._on_deck_page)
            self.deck.on_cat_change = self._set_nav_logo
        except Exception:
            pass
        root.addWidget(_PartnersBar())               # strip partner in basso

    def _on_deck_page(self, i):
        show = i > 0
        self._navback.setVisible(show)
        self._navback_lbl.setVisible(show)
        self._navlogo.setVisible(show)
        if show:
            self._set_nav_logo(getattr(self.deck, "_cur_cat", None))

    def _set_nav_logo(self, k):
        """Logo serie al centro: segue la categoria della card di testa."""
        pm = self._series_pm(k, box_w=150, box_h=44) if k else None
        if pm is not None:
            self._navlogo.setPixmap(pm)

    def _series_pm(self, cat, box_w=64, box_h=22):
        """Logo serie -> pixmap, adattato dentro una SCATOLA fissa (box_w x
        box_h), scalando per stare dentro senza distorcere. Cosi' i tre loghi
        hanno lo stesso ingombro: IMSA (aspect ~4.8, larghissimo) veniva capato
        in altezza e sembrava molto piu' grande; ora e' capato in larghezza."""
        try:
            _p = Path(__file__).resolve().parent.parent / "assets" / ("%s.svg" % cat)
            if _p.exists() and QSvgRenderer is not None:
                _r = QSvgRenderer(str(_p))
                if _r.isValid():
                    ds = _r.defaultSize()
                    w0, h0 = float(ds.width()), float(ds.height())
                    if w0 <= 0 or h0 <= 0:
                        return None
                    scale = min(box_w / w0, box_h / h0)
                    wpx = max(1, int(round(w0 * scale)))
                    hpx = max(1, int(round(h0 * scale)))
                    # DPR-aware: senza, con lo scaling di Windows il logo
                    # veniva upscalato e usciva SGRANATO
                    _dpr = float(self.devicePixelRatioF() or 1.0)
                    pm = QPixmap(int(wpx * _dpr), int(hpx * _dpr))
                    pm.setDevicePixelRatio(_dpr)
                    pm.fill(Qt.transparent)
                    _qp = QPainter(pm)
                    _qp.setRenderHint(QPainter.Antialiasing, True)
                    _qp.setRenderHint(QPainter.SmoothPixmapTransform, True)
                    _r.render(_qp, QRectF(0, 0, wpx, hpx))
                    _qp.end()
                    return pm
        except Exception:
            pass
        return None

    def _build_navbar(self, on_setups, on_overlay, on_teams, on_community):
        bar = QFrame(); bar.setObjectName("navBar")
        bar.setStyleSheet("#navBar{background:transparent;}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(10)

        # freccia "torna alle categorie": PRIMA, poi il logo serie a destra
        # (visibili solo dentro un deck; _on_deck_page li aggiorna).
        self._navback = QPushButton("arrow_back")
        self._navback.setCursor(Qt.PointingHandCursor)
        self._navback.setFixedSize(38, 34)
        self._navback.setStyleSheet(
            "QPushButton{font-family:'Material Symbols Rounded';font-size:22px;"
            "color:#fff;background:rgba(255,255,255,0.08);border:none;"
            "border-radius:8px;}"
            "QPushButton:hover{background:rgba(255,29,67,0.55);}")
        self._navback.setVisible(False)
        lay.addWidget(self._navback)
        # scritta BACK accanto alla freccia
        self._navback_lbl = QLabel("BACK")
        self._navback_lbl.setStyleSheet(
            "color:#ffffff;font-family:'Archivo SemiExpanded';font-size:13px;font-weight:700;"
            "letter-spacing:1px;background:transparent;")
        self._navback_lbl.setVisible(False)
        lay.addWidget(self._navback_lbl, 0, Qt.AlignVCenter)

        # logo serie GRANDE al centro della barra
        lay.addStretch(1)
        self._navlogo = QLabel()
        self._navlogo.setStyleSheet("background:transparent;")
        self._navlogo.setVisible(False)
        lay.addWidget(self._navlogo, 0, Qt.AlignVCenter)

        def _btn(text, cb):
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                "QPushButton{background:transparent;color:#ffffff;"
                "font-family:'Archivo SemiExpanded';font-size:13px;font-weight:700;"
                "letter-spacing:1px;border:1px solid rgba(255,255,255,0.30);"
                "border-radius:6px;padding:7px 18px;}"
                "QPushButton:hover{background:rgba(255,255,255,0.12);"
                "border-color:#ffffff;}")
            if cb is not None:
                b.clicked.connect(lambda _=False, f=cb: f())
            return b

        # COMMUNITY rimosso: le classifiche vivono ora nella pagina pista.
        # nessun bottone: Setups/Teams/Overlay vivono nelle rispettive pagine
        lay.addStretch(1)
        # spazio opzioni app a destra (da riempire con i toggle che vuoi)
        return bar

    def showEvent(self, e):
        super().showEvent(e)
        try:
            self.banner.refresh()
        except Exception:
            pass

    _MENU_BG = "unset"      # cache: assets/overview.jpg (stessa dell'overview)

    @classmethod
    def _menu_photo(cls):
        if cls._MENU_BG == "unset":
            _p = Path(__file__).resolve().parent.parent / "assets" / "overview.jpg"
            _pm = QPixmap(str(_p)) if _p.exists() else None
            cls._MENU_BG = _pm if (_pm is not None and not _pm.isNull()) else None
        return cls._MENU_BG

    def paintEvent(self, e):
        from PySide6.QtGui import QRadialGradient
        from PySide6.QtCore import QRect
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = self.rect()
        w, h = self.width(), self.height()
        photo = self._menu_photo()
        if photo is not None:
            # stesso trattamento dell'overview: foto 20% + blu basso-sx + rosso alto-dx
            p.fillRect(r, QColor("#000833"))
            scaled = photo.scaled(r.size(), Qt.KeepAspectRatioByExpanding,
                                  Qt.SmoothTransformation)
            sx = max(0, (scaled.width() - r.width()) // 2)
            sy = max(0, (scaled.height() - r.height()) // 2)
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.setOpacity(0.20)
            p.drawPixmap(r, scaled, QRect(sx, sy, r.width(), r.height()))
            p.setOpacity(1.0)
            gb = QRadialGradient(0, h, max(w, h) * 0.95)
            gb.setColorAt(0.0, QColor(19, 41, 67, 130))
            gb.setColorAt(0.55, QColor(19, 41, 67, 45))
            gb.setColorAt(1.0, QColor(19, 41, 67, 0))
            p.fillRect(r, QBrush(gb))
        else:
            p.fillRect(r, QColor("#000833"))                 # blu pieno
        g = QRadialGradient(w, 0, max(w, h) * 0.95)          # centro: angolo alto-destra
        g.setColorAt(0.0, QColor(255, 29, 67, 170))
        g.setColorAt(0.55, QColor(255, 29, 67, 60))
        g.setColorAt(1.0, QColor(255, 29, 67, 0))
        p.fillRect(self.rect(), QBrush(g))


class _RadialBg(QWidget):
    """Sfondo blu + radiale rosso. Se gli viene passata una foto (set_photo),
    la disegna come base e i colori la velano. Visibile nella pagina sessione."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._photo = None

    def set_photo(self, pm):
        self._photo = pm if (pm is not None and not pm.isNull()) else None
        self.update()

    def paintEvent(self, e):
        from PySide6.QtGui import QRadialGradient
        from PySide6.QtCore import QRect
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = self.rect()
        w, h = self.width(), self.height()
        if self._photo is not None:
            # stesso trattamento della pagina sessione: foto 20% + blu basso-sx + rosso alto-dx
            p.fillRect(r, QColor("#08080c"))
            scaled = self._photo.scaled(r.size(), Qt.KeepAspectRatioByExpanding,
                                        Qt.SmoothTransformation)
            sx = max(0, (scaled.width() - r.width()) // 2)
            sy = max(0, (scaled.height() - r.height()) // 2)
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.setOpacity(0.20)
            p.drawPixmap(r, scaled, QRect(sx, sy, r.width(), r.height()))
            p.setOpacity(1.0)
            gb = QRadialGradient(0, h, max(w, h) * 0.95)
            gb.setColorAt(0.0, QColor(19, 41, 67, 130))
            gb.setColorAt(0.55, QColor(19, 41, 67, 45))
            gb.setColorAt(1.0, QColor(19, 41, 67, 0))
            p.fillRect(r, QBrush(gb))
            gr = QRadialGradient(w, 0, max(w, h) * 0.55)
            gr.setColorAt(0.0, QColor(255, 29, 67, 80))
            gr.setColorAt(0.5, QColor(255, 29, 67, 22))
            gr.setColorAt(1.0, QColor(255, 29, 67, 0))
            p.fillRect(r, QBrush(gr))
            return
        # menu/back: blu + radiale rosso come prima
        p.fillRect(r, QColor("#000833"))
        g = QRadialGradient(w, 0, max(w, h) * 0.95)
        g.setColorAt(0.0, QColor(255, 29, 67, 170))
        g.setColorAt(0.55, QColor(255, 29, 67, 60))
        g.setColorAt(1.0, QColor(255, 29, 67, 0))
        p.fillRect(r, QBrush(g))


class _IntroPage(QWidget):
    """Riproduce assets/intro.mp4 a tutta finestra dentro una QGraphicsScene, così
    il tasto Skip (overlay nella scena) sta davvero SOPRA il filmato. Skip dopo 3s.
    Chiama on_done() a fine video o al click. Solleva eccezione in __init__ se la
    multimedia non c'è (il chiamante fa fallback al menu)."""
    _VIDEO = Path(__file__).resolve().parent.parent / "assets" / "intro.mp4"
    _MUSIC = (Path(__file__).resolve().parent.parent
              / "assets" / "audio" / "music" / "1.mp3")

    def __init__(self, on_done, parent=None):
        super().__init__(parent)
        from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
        from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
        from PySide6.QtWidgets import QGraphicsScene, QGraphicsView
        from PySide6.QtCore import QUrl, QSizeF
        self._on_done = on_done
        self._done = False
        self._QSizeF = QSizeF

        self.setStyleSheet("background:#000000;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._view = QGraphicsView(self)
        self._view.setFrameShape(QFrame.NoFrame)
        self._view.setStyleSheet("background:#000000; border:none;")
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lay.addWidget(self._view)

        self._scene = QGraphicsScene(self._view)
        self._view.setScene(self._scene)
        self._item = QGraphicsVideoItem()
        self._item.setAspectRatioMode(Qt.KeepAspectRatioByExpanding)   # riempi finestra
        self._scene.addItem(self._item)

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._audio.setMuted(True)            # audio del VIDEO muto: lo sostituisce la musica
        # colonna sonora dell'intro (1.mp3): parte a volume 70%, NON muta
        self._music = None
        self._music_out = None
        if self._MUSIC.exists():
            self._music = QMediaPlayer(self)
            self._music_out = QAudioOutput(self)
            self._music.setAudioOutput(self._music_out)
            try:
                from core.profile import _load_profile as _lp
                _mv = max(0.0, min(1.0, float(_lp().get("music_vol", 40)) / 100.0))
            except Exception:
                _mv = 0.70
            self._music_out.setVolume(_mv)
            self._music.setSource(QUrl.fromLocalFile(str(self._MUSIC)))
        self._player.setVideoOutput(self._item)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.setSource(QUrl.fromLocalFile(str(self._VIDEO)))

        # tasto Skip come overlay nella scena (z sopra al video)
        self._skip = QPushButton("Skip  \u203a")
        self._skip.setCursor(Qt.PointingHandCursor)
        f = QFont("Archivo SemiExpanded")
        f.setPixelSize(15)
        self._skip.setFont(f)
        self._skip.setStyleSheet(
            "QPushButton { color:#ffffff; font-family:'Archivo SemiExpanded'; font-size:15px;"
            " background:transparent;"
            " border:1px solid rgba(255,255,255,0.55); border-radius:18px;"
            " padding:8px 18px; }"
            "QPushButton:hover { background:rgba(255,29,67,0.90);"
            " border-color:rgba(255,29,67,1.0); }"
        )
        self._skip.clicked.connect(self._finish)
        self._proxy = self._scene.addWidget(self._skip)
        self._proxy.setZValue(10)
        self._proxy.setVisible(False)

        # tasto volume/mute (Material Icons via ligatura), visibile da subito
        self._mute = QPushButton("volume_up")
        self._mute.setCursor(Qt.PointingHandCursor)
        self._mute.setStyleSheet(
            "QPushButton { font-family:'Material Icons'; font-size:26px;"
            " color:#ffffff; background:transparent; border:none; padding:4px; }"
            "QPushButton:hover { color:rgba(255,29,67,1.0); }"
        )
        self._mute.clicked.connect(self._toggle_mute)
        self._mute_proxy = self._scene.addWidget(self._mute)
        self._mute_proxy.setZValue(10)

        # bg radiale: entra in dissolvenza 3s prima della fine (sotto titolo/tasti)
        self._bg_widget = _RadialBg()
        self._bg_proxy = self._scene.addWidget(self._bg_widget)
        self._bg_proxy.setZValue(5)
        self._bg_proxy.setOpacity(0.0)
        self._bg_started = False
        from PySide6.QtCore import QPropertyAnimation as _QPA
        self._bg_anim = _QPA(self._bg_proxy, b"opacity", self)
        self._bg_anim.setDuration(2600)
        self._bg_anim.setStartValue(0.0)
        self._bg_anim.setEndValue(1.0)

        # titolo (Archivo SemiExpanded) + tasto ENTRA (Archivo SemiExpanded Regular): appaiono in fade dopo 3s
        self._title = QLabel("LMU Telemetry Pro")
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setStyleSheet(
            "QLabel { font-family:'Archivo SemiExpanded'; font-weight:700; font-size:46px;"
            " color:#ffffff; background:transparent; }"
        )
        self._title_proxy = self._scene.addWidget(self._title)
        self._title_proxy.setZValue(9)
        self._title_proxy.setOpacity(0.0)

        # sottotitolo MURETTO: font Archivo (stile WEC), corsivo, rosso LMU.
        # Appare 2s DOPO il titolo (vedi timer piu' sotto).
        self._subtitle = QLabel("MURETTO")
        self._subtitle.setAlignment(Qt.AlignCenter)
        self._subtitle.setStyleSheet(
            "QLabel { font-family:'Archivo SemiExpanded'; font-style:normal;"
            " font-weight:900; font-size:58px; letter-spacing:4px;"
            " color:#ff2800; background:transparent; }"
        )
        self._subtitle_proxy = self._scene.addWidget(self._subtitle)
        self._subtitle_proxy.setZValue(9)
        self._subtitle_proxy.setOpacity(0.0)

        # versione, piccola, sotto MURETTO
        self._version = QLabel("v.0.3 beta")
        self._version.setAlignment(Qt.AlignCenter)
        self._version.setStyleSheet(
            "QLabel { font-family:'Archivo SemiExpanded'; font-weight:400; font-size:15px;"
            " letter-spacing:2px; color:rgba(255,255,255,0.55);"
            " background:transparent; }"
        )
        self._version_proxy = self._scene.addWidget(self._version)
        self._version_proxy.setZValue(9)
        self._version_proxy.setOpacity(0.0)

        self._enter = QPushButton("ENTER")
        self._enter.setCursor(Qt.PointingHandCursor)
        self._enter.setStyleSheet(
            "QPushButton { font-family:'Archivo SemiExpanded'; font-weight:400; font-size:18px;"
            " color:#ffffff; background:transparent;"
            " border:1px solid rgba(255,255,255,0.70); border-radius:22px;"
            " padding:10px 34px; }"
            "QPushButton:hover { background:rgba(255,29,67,0.90);"
            " border-color:rgba(255,29,67,1.0); }"
        )
        self._enter.clicked.connect(self._finish)
        self._enter_proxy = self._scene.addWidget(self._enter)
        self._enter_proxy.setZValue(9)
        self._enter_proxy.setOpacity(0.0)

        # linee nell'angolo basso-destra: fade-in dopo 3s, poi restano
        self._stripes = _SvgBox()
        self._stripes.load(_MenuHeader._CORNER_SVG)
        self._stripes.setStyleSheet("background:transparent;")
        self._stripes_proxy = self._scene.addWidget(self._stripes)
        self._stripes_proxy.setZValue(8)
        self._stripes_proxy.setOpacity(0.0)

        from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QParallelAnimationGroup
        # simbolo app (tracciato-linee) al centro: bianco. NON nel fade dei 3s:
        # entra ~1.6s dopo il titolo con uno zoom da fuori verso dentro (come le card).
        self._symbol = _WhiteSvgBox()
        _sym_path = Path(__file__).resolve().parent.parent / "assets" / "intro_symbol.svg"
        if _sym_path.exists():
            self._symbol.load(str(_sym_path))
        self._symbol.setStyleSheet("background:transparent;")
        self._symbol_proxy = self._scene.addWidget(self._symbol)
        self._symbol_proxy.setZValue(8)
        self._symbol_proxy.setOpacity(0.0)
        self._symbol_proxy.setScale(1.35)        # parte ingrandito (da "fuori")

        def _mk_fade(proxy, dur=1100):
            a = QPropertyAnimation(proxy, b"opacity", self)
            a.setDuration(dur)
            a.setStartValue(0.0)
            a.setEndValue(1.0)
            a.setEasingCurve(QEasingCurve.InOutCubic)
            return a
        # tre tempi distinti: titolo (+strisce), poi MURETTO, poi ENTRA
        self._fade_title = [_mk_fade(self._title_proxy),
                            _mk_fade(self._stripes_proxy)]
        self._fade_sub = _mk_fade(self._subtitle_proxy)
        self._fade_ver = _mk_fade(self._version_proxy)
        self._fade_enter = _mk_fade(self._enter_proxy)

        # animazione d'ingresso del simbolo: scale 1.35 -> 1.0 + opacity 0 -> 1
        _sa = QPropertyAnimation(self._symbol_proxy, b"scale", self)
        _sa.setDuration(900); _sa.setStartValue(1.35); _sa.setEndValue(1.0)
        _sa.setEasingCurve(QEasingCurve.OutCubic)
        _oa = QPropertyAnimation(self._symbol_proxy, b"opacity", self)
        _oa.setDuration(700); _oa.setStartValue(0.0); _oa.setEndValue(1.0)
        _oa.setEasingCurve(QEasingCurve.OutCubic)
        self._symbol_anim = QParallelAnimationGroup(self)
        self._symbol_anim.addAnimation(_sa)
        self._symbol_anim.addAnimation(_oa)

        # tasto Reload (Material Icons): a fine video prende il posto di Skip
        self._reload = QPushButton("replay")
        self._reload.setCursor(Qt.PointingHandCursor)
        self._reload.setStyleSheet(
            "QPushButton { font-family:'Material Icons'; font-size:28px;"
            " color:#ffffff; background:transparent; border:none; padding:4px; }"
            "QPushButton:hover { color:rgba(255,29,67,1.0); }"
        )
        self._reload.clicked.connect(self._replay)
        self._reload_proxy = self._scene.addWidget(self._reload)
        self._reload_proxy.setZValue(10)
        self._reload_proxy.setVisible(False)

        # pausa sull'ultimo frame
        self._dur = 0
        self._ended = False
        self._player.durationChanged.connect(self._on_duration)
        self._player.positionChanged.connect(self._on_position)

        QTimer.singleShot(3000, self._show_skip)
        QTimer.singleShot(10000, self._reveal_overlays)  # titolo (dopo ~10s)
        QTimer.singleShot(11600, self._reveal_symbol)    # ~1.6s dopo il titolo
        QTimer.singleShot(12000, self._reveal_subtitle)  # +2s: MURETTO + versione
        QTimer.singleShot(15000, self._reveal_enter)     # +3s da MURETTO: ENTRA
        self._player.play()
        if self._music is not None:
            self._music.play()

    def _on_duration(self, d):
        self._dur = d

    def _on_position(self, pos):
        if self._dur <= 0:
            return
        # taglia gli ULTIMI 7s del video (richiesta utente): fine anticipata
        _cut = self._dur - 7000 if self._dur > 9000 else self._dur - 120
        if not self._bg_started and pos >= _cut - 3000:
            self._bg_started = True
            self._bg_anim.start()
        if not self._ended and pos >= _cut:
            self._at_end()

    def _at_end(self):
        if self._ended:
            return
        self._ended = True
        try:
            self._player.pause()
        except Exception:
            pass
        # NON fermo la musica: continua anche dopo il video, fino a fine traccia
        self._bg_started = True
        self._bg_anim.stop()
        self._bg_proxy.setOpacity(1.0)       # radiale pieno sull'ultimo frame
        self._proxy.setVisible(False)        # via Skip
        self._reload_proxy.setVisible(True)  # appare Reload al suo posto
        self._place_reload()

    def _replay(self):
        self._ended = False
        self._bg_started = False
        self._bg_anim.stop()
        self._bg_proxy.setOpacity(0.0)
        self._reload_proxy.setVisible(False)
        try:
            self._player.setPosition(0)
            self._player.play()
        except Exception:
            pass
        if self._music is not None:
            try:
                self._music.setPosition(0)
                self._music.play()
            except Exception:
                pass

    def _fit(self):
        vp = self._view.viewport().size()
        self._scene.setSceneRect(0, 0, vp.width(), vp.height())
        self._item.setPos(0, 0)
        self._item.setSize(self._QSizeF(vp.width(), vp.height()))
        self._bg_widget.resize(vp.width(), vp.height())
        self._bg_proxy.setPos(0, 0)
        self._place_skip()
        self._place_mute()
        self._place_title()
        self._place_subtitle()
        self._place_version()
        self._place_enter()
        self._place_reload()
        self._place_stripes()
        self._place_symbol()

    def _place_symbol(self):
        vp = self._view.viewport().size()
        sz = int(min(vp.width(), vp.height()) * 0.30)
        self._symbol.resize(sz, sz)
        self._symbol_proxy.setTransformOriginPoint(sz / 2.0, sz / 2.0)  # scala dal centro
        # centrato in orizzontale, sopra al titolo (titolo è al 42%)
        self._symbol_proxy.setPos((vp.width() - sz) / 2.0,
                                  vp.height() * 0.42 - sz - 24)

    def _reveal_overlays(self):        # titolo + strisce (a 3s)
        if not self._done:
            for a in self._fade_title:
                a.start()

    def _reveal_subtitle(self):        # MURETTO + versione (2s dopo il titolo)
        if not self._done:
            self._fade_sub.start()
            self._fade_ver.start()

    def _reveal_enter(self):           # ENTRA (3s dopo MURETTO)
        if not self._done:
            self._fade_enter.start()

    def _reveal_symbol(self):
        if not self._done:
            self._symbol_anim.start()

    def _place_subtitle(self):
        self._subtitle.adjustSize()
        sh = self._subtitle.sizeHint()
        ts = self._title.sizeHint()
        vp = self._view.viewport().size()
        title_bottom = vp.height() * 0.42 + ts.height() / 2.0
        self._subtitle_proxy.setPos((vp.width() - sh.width()) / 2.0,
                                    title_bottom + 4)

    def _place_version(self):
        self._version.adjustSize()
        sh = self._version.sizeHint()
        ts = self._title.sizeHint()
        ss = self._subtitle.sizeHint()
        vp = self._view.viewport().size()
        sub_bottom = (vp.height() * 0.42 + ts.height() / 2.0
                      + 4 + ss.height())
        self._version_proxy.setPos((vp.width() - sh.width()) / 2.0,
                                   sub_bottom + 2)

    def _place_enter(self):
        self._enter.adjustSize()
        sh = self._enter.sizeHint()
        ts = self._title.sizeHint()
        ss = self._subtitle.sizeHint()
        vs = self._version.sizeHint()
        vp = self._view.viewport().size()
        ver_bottom = (vp.height() * 0.42 + ts.height() / 2.0
                      + 4 + ss.height() + 2 + vs.height())
        self._enter_proxy.setPos((vp.width() - sh.width()) / 2.0,
                                 ver_bottom + 16)

    def _place_reload(self):
        m = 24
        sh = self._reload.sizeHint()
        msh = self._mute.sizeHint()
        vp = self._view.viewport().size()
        # accanto al volume, in basso a sinistra
        self._reload_proxy.setPos(m + msh.width() + 10, vp.height() - sh.height() - m)

    def _place_stripes(self):
        vp = self._view.viewport().size()
        sz = int(min(vp.width(), vp.height()) * 0.32)
        self._stripes.resize(sz, sz)
        self._stripes_proxy.setPos(vp.width() - sz, vp.height() - sz)  # angolo basso-destra

    def _place_title(self):
        self._title.adjustSize()
        sh = self._title.sizeHint()
        vp = self._view.viewport().size()
        self._title_proxy.setPos((vp.width() - sh.width()) / 2.0,
                                 vp.height() * 0.42 - sh.height() / 2.0)

    def _toggle_mute(self):
        out = self._music_out or self._audio   # ora l'audio udibile e' la musica
        m = not out.isMuted()
        out.setMuted(m)
        self._mute.setText("volume_off" if m else "volume_up")

    def _place_mute(self):
        m = 24
        sh = self._mute.sizeHint()
        vp = self._view.viewport().size()
        self._mute_proxy.setPos(m, vp.height() - sh.height() - m)

    def _place_skip(self):
        m = 24
        sh = self._skip.sizeHint()
        vp = self._view.viewport().size()
        self._proxy.setPos(vp.width() - sh.width() - m, vp.height() - sh.height() - m)

    def _show_skip(self):
        self._proxy.setVisible(False)        # Skip rimosso: si entra con ENTRA

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def showEvent(self, e):
        super().showEvent(e)
        self._fit()

    def _on_status(self, st):
        from PySide6.QtMultimedia import QMediaPlayer
        if st == QMediaPlayer.MediaStatus.EndOfMedia:
            self._at_end()

    def _finish(self):
        if self._done:
            return
        self._done = True
        try:
            self._player.stop()
        except Exception:
            pass
        if getattr(self, "_music", None) is not None:
            try:
                self._music.stop()
            except Exception:
                pass
        self._on_done()












class _SessionCard(QFrame):
    """Card sessione cliccabile: logo auto, pilota, auto, sessione·giri·data.
    Selezionata → sfondo bianco e testo rosso LMU."""
    _NORMAL = ("#sessCard { background:rgba(255,255,255,0.06);"
               " border:none; border-left:2px solid transparent; border-radius:10px; }"
               "#sessCard:hover { background:rgba(255,255,255,0.11); }")
    _SEL = ("#sessCard { background:rgba(255,255,255,0.16);"
            " border:none; border-left:2px solid #ff1d43; border-radius:10px; }")

    def __init__(self, meta, on_export=None, on_delete=None, parent=None):
        super().__init__(parent)
        from core.utils import find_logo_path
        from core.brands import brand_from_vehicle
        self.on_click = None
        self._selected = False
        self._dimmed = False
        self._meta = meta
        self._file = meta.get("file")
        self._on_export = on_export
        self._on_delete = on_delete
        self.setObjectName("sessCard")
        self.setStyleSheet(self._NORMAL)
        self.setCursor(Qt.PointingHandCursor)
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 12, 16, 12)
        h.setSpacing(12)

        # colonna sinistra: logo brand auto + badge classe SOTTO il logo
        brand = (brand_from_vehicle(meta.get("team") or "")
                 or brand_from_vehicle(meta.get("vehicle") or ""))
        p = find_logo_path(brand) if brand else None
        left = QVBoxLayout()
        left.setSpacing(5)
        left.setContentsMargins(0, 0, 0, 0)
        logo = _SvgBox()
        logo.setFixedSize(68, 48)
        logo.setStyleSheet("background:transparent;")
        if p is not None:
            logo.load(str(p))
        left.addWidget(logo, 0, Qt.AlignHCenter)
        try:
            from core.classes import class_tag as _ctag
            _cls = (_ctag(meta.get("car_class") or "") or "").lower()
            _cp = (Path(__file__).resolve().parent.parent
                   / "assets" / "class" / (_cls + ".svg"))
            if _cls and _cp.exists():
                badge = _SvgBox()
                badge.setFixedSize(46, 30)        # aspetto mantenuto da _SvgBox
                badge.load(str(_cp))
                left.addWidget(badge, 0, Qt.AlignHCenter)
        except Exception:
            pass
        h.addLayout(left, 0)

        # centro: nome pilota in evidenza, poi auto, poi sessione·giri·data
        mid = QVBoxLayout()
        mid.setSpacing(3)

        # riga 5 icone meteo previste (forecast), SOPRA il nome del pilota
        fc5 = (meta.get("forecast5") or "").strip()
        if fc5:
            _wdir = Path(__file__).resolve().parent.parent / "assets" / "weather"
            fc_row = QWidget()
            fc_row.setStyleSheet("background:transparent;")
            fcl = QHBoxLayout(fc_row)
            fcl.setContentsMargins(0, 0, 0, 0)
            fcl.setSpacing(7)
            _nic = 0
            for nm in [x.strip() for x in fc5.split(",") if x.strip()][:5]:
                wp = _wdir / ("%s.svg" % nm)
                if not wp.exists():
                    continue
                ic = _SvgBox()
                ic.setFixedSize(44, 44)
                ic.setStyleSheet("background:transparent;")
                ic.load(str(wp))
                fcl.addWidget(ic, 0, Qt.AlignVCenter)
                _nic += 1
            if _nic:
                fcl.addStretch()
                mid.addWidget(fc_row)
            else:
                fc_row.deleteLater()

        driver = meta.get("driver") or meta.get("team") or "\u2014"
        self._lab_drv = QLabel((driver or '').upper())
        mid.addWidget(self._lab_drv)

        self._lab_car = QLabel(meta.get("vehicle") or meta.get("car_class") or "\u2014")
        mid.addWidget(self._lab_car)

        laps = meta.get("laps") or 0
        styp = _ov_session_label(meta.get("session_type"))
        slen = _fmt_session_len(meta.get("session_len"))
        sess = styp + (f" {slen}" if slen else "")
        self._lab_sub = QLabel("   \u00b7   ".join(
            [sess, f"{laps} giri", self._fmt_date(meta.get("started_at"))]))
        mid.addWidget(self._lab_sub)
        h.addLayout(mid, 1)

        # colonna icone a destra: export in alto, X (elimina) in basso (come il vecchio)
        rb = QVBoxLayout()
        rb.setSpacing(4)
        rb.setContentsMargins(0, 0, 0, 0)
        if meta.get("team_session"):
            tlbl = QLabel("team")
            tlbl.setStyleSheet("color:#e8eaee; font-size:10px; font-weight:700;"
                               " letter-spacing:.5px; background:transparent; border:none;")
            rb.addWidget(tlbl, 0, Qt.AlignRight | Qt.AlignTop)
        else:
            self._btn_exp = _ExportButton(16)
            self._btn_exp.setFlat(True)
            self._btn_exp.setCursor(Qt.PointingHandCursor)
            self._btn_exp.setToolTip("Esporta sessione (.zip)")
            self._btn_exp.setFixedSize(24, 24)
            self._btn_exp.setStyleSheet("border:none; background:transparent;")
            self._btn_exp.clicked.connect(self._do_export)
            rb.addWidget(self._btn_exp, 0, Qt.AlignRight | Qt.AlignTop)
        rb.addStretch(1)
        self._btn_del = _XButton(18)
        self._btn_del.setFlat(True)
        self._btn_del.setCursor(Qt.PointingHandCursor)
        self._btn_del.setToolTip("Elimina")
        self._btn_del.setFixedSize(26, 26)
        self._btn_del.setStyleSheet("border:none; background:transparent;")
        self._btn_del.clicked.connect(self._do_del)
        rb.addWidget(self._btn_del, 0, Qt.AlignRight | Qt.AlignBottom)
        h.addLayout(rb, 0)
        self._apply_text()

    def set_dim(self, on):
        """DISABILITATA durante una sessione live: opacita' 40% e non cliccabile
        (ne' apri ne' export/cestino). Mentre registri in pista non puoi aprire
        una sessione precedente."""
        self._dimmed = bool(on)
        try:
            from PySide6.QtWidgets import QGraphicsOpacityEffect
            if on:
                eff = QGraphicsOpacityEffect(self); eff.setOpacity(0.40)
                self.setGraphicsEffect(eff)
                self.setCursor(Qt.ArrowCursor)
            else:
                self.setGraphicsEffect(None)
                self.setCursor(Qt.PointingHandCursor)
        except Exception:
            pass

    def _do_export(self):
        if self._dimmed:
            return
        if self._on_export:
            self._on_export(self._file)

    def _do_del(self):
        if self._dimmed:
            return
        if self._on_delete:
            self._on_delete(self._file)

    def _apply_text(self):
        self._lab_drv.setStyleSheet("color:#ffffff; font-family:'Archivo SemiExpanded';"
                                    " font-weight:700; font-size:15px;"
                                    " background:transparent; border:none;")
        self._lab_car.setStyleSheet("color:#cfd6e2; font-family:'Archivo SemiExpanded';"
                                    " font-size:13px; background:transparent; border:none;")
        self._lab_sub.setStyleSheet("color:#aeb6c4; font-family:'Archivo SemiExpanded';"
                                    " font-size:12px; background:transparent; border:none;")

    def setSelected(self, on):
        self._selected = on
        self.setStyleSheet(self._SEL if on else self._NORMAL)
        self._apply_text()

    def mousePressEvent(self, e):
        if self._dimmed:                     # sessione live: card non cliccabile
            return
        if e.button() == Qt.LeftButton and self.on_click:
            self.on_click(self)
            e.accept()

    @staticmethod
    def _fmt_date(iso):
        if not iso:
            return "\u2014"
        try:
            from datetime import datetime
            return datetime.fromisoformat(iso).strftime("%d/%m/%Y  %H:%M")
        except Exception:
            return str(iso)


_OV_BOARD_QSS = r"""#ovCard{background:transparent;border:none;}#ovNoData{color:#5c5f68;font-size:14px;background:transparent;}#ovTrackBox{background:transparent;border:none;}#ovSessName{color:#f2f4f7;font-size:17px;font-weight:700;background:transparent;}#ovSessClock{color:#45b4ef;font-size:17px;font-weight:700;background:transparent;}#ovCondLine{color:#a7aaaf;font-size:13px;background:transparent;}#ovInfoLine{color:#cfd2d8;font-size:12px;background:transparent;}#ovListCard{background:transparent;border:none;}QScrollBar:horizontal{height:0px;background:transparent;}#ovHead{color:#6e727b;font-size:11px;font-weight:700;letter-spacing:2px;}#ovDriver{background:transparent;border:none;color:#f2f4f7;font-size:16px;font-weight:600;}#ovTeam{background:transparent;border:none;color:#a7aaaf;font-size:12px;}#ovDriver:focus,#ovTeam:focus{border-bottom:1px solid #3a3d43;}#ovCar{color:#6e727b;font-size:12px;}#ovTrack{color:#bdbfc3;font-size:11px;font-weight:600;letter-spacing:1px;}#ovRowA,#ovRowB{background:#1d1f24;border-radius:8px;}#ovRowA:hover,#ovRowB:hover{background:#23262d;}#ovKey{color:#989ba2;font-size:13px;background:transparent;}#ovVal{color:#f2f4f7;font-size:14px;font-weight:600;background:transparent;}#ovRowTitle{color:#f2f4f7;font-size:13px;font-weight:600;background:transparent;}#ovRowSub{color:#989ba2;font-size:11px;background:transparent;}#ovRowDim{color:#61646d;font-size:11px;background:transparent;}#ovSelRow{background:#262a31;border-left:2px solid #45b4ef;border-radius:8px;}#ovRowIcon{background:transparent;border:none;color:#9fb0c8;font-size:14px;}#ovRowIcon:hover{color:#ff5b6e;}#ovIcon{background:transparent;border:none;color:#989ba2;font-size:15px;}#ovIcon:hover{color:#f2f4f7;}#ovBadgeDry{color:#1a1400;background:#f5c542;border-radius:6px;padding:1px 7px;font-size:10px;font-weight:700;}#ovBadgeWet{color:#04222e;background:#4ec3ff;border-radius:6px;padding:1px 7px;font-size:10px;font-weight:700;}#ovStatKey{color:#6e727b;font-size:10px;font-weight:700;letter-spacing:1px;background:transparent;}#ovStatVal{color:#f2f4f7;font-size:14px;font-weight:600;background:transparent;}#ovColCap{color:#9aa3b2;font-size:10px;font-weight:700;letter-spacing:1px;background:transparent;}#ovColCapSel{color:#55ff7f;font-size:9px;font-weight:700;letter-spacing:1px;background:transparent;}#ovColCapCmp{color:#8b7bff;font-size:9px;font-weight:700;letter-spacing:1px;background:transparent;}#ovTheo{color:#45b4ef;font-size:11px;font-weight:700;letter-spacing:.5px;background:transparent;}#ovTabOn{background:rgba(255,255,255,0.22);border:none;border-left:2px solid #ff1d43;border-radius:10px;}#ovTabOff{background:rgba(255,255,255,0.10);border:none;border-radius:10px;}#ovTabOff:hover{background:rgba(255,255,255,0.16);}#ovTabTxt{color:#f2f4f7;font-size:11px;font-weight:700;letter-spacing:.5px;background:transparent;}#ovStintSum{color:#cfd6e2;font-size:12px;background:transparent;}#ovTabOff #ovTabTxt{color:#989ba2;}#ovRefRow{background:rgba(245,197,66,0.13);border:none;border-radius:10px;}#ovRefEmpty{background:#111214;border:1px dashed #2a2c30;border-radius:10px;}#ovRefTag{color:#f5c542;font-size:12px;font-weight:800;letter-spacing:1px;background:transparent;}#ovRefDrv{color:#f5f5f5;font-size:13px;font-weight:600;background:transparent;}#ovRefTime{color:#f5c542;font-size:14px;font-weight:700;background:transparent;}#ovRefSec{color:#9c8a4e;font-size:12px;background:transparent;}#ovRefNone{color:#6e727b;font-size:12px;background:transparent;}#ovRefSub{color:#7c7148;font-size:10px;background:transparent;padding-left:12px;}#ovRefInfo{color:#cfd2d8;font-size:11px;background:transparent;padding-left:12px;}#ovWrRow{background:rgba(57,182,232,0.13);border:none;border-radius:10px;}#ovWrTag{color:#39b6e8;font-size:12px;font-weight:800;letter-spacing:1px;background:transparent;}#ovWrDrv{color:#f5f5f5;font-size:13px;font-weight:600;background:transparent;}#ovWrTime{color:#39b6e8;font-size:14px;font-weight:700;background:transparent;}#ovWrSec{color:#5f93ad;font-size:12px;background:transparent;}#ovWrSub{color:#5f93ad;font-size:10px;background:transparent;padding-left:12px;}#ovLapRow{background:rgba(255,255,255,0.07);border:none;border-radius:6px;}#ovLapRow:hover{background:rgba(255,255,255,0.12);}#ovLapSel{background:rgba(255,255,255,0.17);border:none;border-radius:6px;}#ovLapDis{background:rgba(255,255,255,0.045);border:none;border-radius:6px;}#ovLapBestCard{background:rgba(255,29,67,0.20);border:none;border-radius:6px;}#ovLapNo{color:#ffffff;font-size:13px;font-weight:800;background:#e01a2b;border-radius:6px;}#ovLapInv{color:#aeb2ba;font-size:13px;font-weight:700;background:transparent;}#ovLapTime{color:#ffffff;font-size:16px;font-weight:700;background:transparent;}#ovLapBest{color:#ff5bb0;font-size:16px;font-weight:700;background:transparent;}#ovSec{color:#f2f4f7;font-size:13px;font-weight:600;background:transparent;}#ovSecBest{color:#ff3bd4;font-size:13px;font-weight:700;background:transparent;}#ovSecInv{color:#9aa0a8;font-size:13px;font-weight:600;background:transparent;}#ovTagOut{color:#d2d6dd;font-size:9px;font-weight:700;letter-spacing:1px;background:rgba(255,255,255,0.12);border-radius:4px;padding:1px 5px;margin-left:6px;}#ovTagTL{color:#ffcc33;font-size:9px;font-weight:700;letter-spacing:1px;background:rgba(255,210,58,0.16);border-radius:4px;padding:1px 5px;margin-left:6px;}#ovTagInv{color:#e06a6a;font-size:9px;font-weight:700;letter-spacing:1px;background:rgba(255,91,91,0.16);border-radius:4px;padding:1px 5px;margin-left:6px;}#ovTagPit{color:#f0a23a;font-size:9px;font-weight:700;letter-spacing:1px;background:rgba(255,160,58,0.16);border-radius:4px;padding:1px 5px;margin-left:6px;}#ovCkOff{background:transparent;border:1.5px solid #3a3d43;border-radius:4px;}#ovCkOff:hover{border-color:#60636c;}#ovCkSelOn{background:transparent;border:2px solid #55ff7f;border-radius:4px;}#ovCkCmpOn{background:transparent;border:2px solid #8b7bff;border-radius:4px;}#ovCkRefOn{background:transparent;border:2px solid #f5c542;border-radius:4px;}"""


_OV_BOARD_QSS_NEW = ""


class _AppPage(QWidget):
    """Schermata app (dopo il menu). Header in alto (back + pista | tab analisi |
    tempo sessione), corpo a due colonne (sessioni / board stint-giri), START in
    basso a destra. Sfondo radiale come il menu."""

    _TAB_OFF = ("QPushButton{background:rgba(255,255,255,0.07);color:#aeb6c4;"
                "font-family:'Archivo SemiExpanded';font-weight:700;font-size:11px;letter-spacing:.5px;"
                "border:none;border-radius:8px;padding:6px 13px;}"
                "QPushButton:hover{background:rgba(255,255,255,0.13);color:#e8eaee;}")
    _TAB_ON = ("QPushButton{background:rgba(255,255,255,0.20);color:#ffffff;"
               "font-family:'Archivo SemiExpanded';font-weight:700;font-size:11px;letter-spacing:.5px;"
               "border:none;border-left:2px solid #ff1d43;border-radius:8px;padding:6px 13px;}")
    _SUB_ON = ("QPushButton{background:rgba(255,255,255,0.20);color:#ffffff;"
               "font-family:'Archivo SemiExpanded';font-weight:700;font-size:11px;letter-spacing:.5px;"
               "border:none;border-bottom:2px solid #ff1d43;border-radius:8px;padding:6px 13px;}")
    _CHIP_OFF = ("QPushButton{background:rgba(255,255,255,0.07);color:#aeb6c4;"
                 "font-family:'Archivo SemiExpanded';font-weight:700;font-size:11px;letter-spacing:.5px;"
                 "border:none;border-radius:8px;padding:5px 11px;}"
                 "QPushButton:hover{background:rgba(255,255,255,0.13);color:#e8eaee;}")
    _CHIP_ON = ("QPushButton{background:rgba(255,255,255,0.20);color:#ffffff;"
                "font-family:'Archivo SemiExpanded';font-weight:700;font-size:11px;letter-spacing:.5px;"
                "border:none;border-bottom:2px solid #ff1d43;border-radius:8px;padding:5px 11px;}")
    _BTN_START = ("QPushButton{background:#ff1d43;color:#ffffff;font-family:'Archivo SemiExpanded';"
                  "font-weight:800;font-size:15px;letter-spacing:1px;border:none;"
                  "border-radius:10px;padding:0 24px;}"
                  "QPushButton:hover{background:#ff3b5d;}")
    _BTN_STOP = ("QPushButton{background:rgba(255,255,255,0.16);color:#ffffff;"
                 "font-family:'Archivo SemiExpanded';font-weight:800;font-size:15px;letter-spacing:1px;"
                 "border:none;border-radius:10px;padding:0 24px;}"
                 "QPushButton:hover{background:rgba(255,255,255,0.24);}")

    _PHOTO_DIR = Path(__file__).resolve().parent.parent / "assets" / "trackcards"
    _PHOTO_CACHE = {}

    def _build_guide(self):
        """Tab Guide: documentazione approfondita e scrollabile (IT + EN)."""
        from PySide6.QtWidgets import QScrollArea
        html = '<h1 style="font-family:\'Archivo SemiExpanded\';color:#f5c542;font-size:27px;font-weight:800;margin:0 0 2px;">LMU Telemetry Pro &mdash; Guide</h1><p style="font-family:\'Archivo SemiExpanded\';color:#8a90a0;font-size:14px;margin:0 0 18px;">Guida d\'uso completa &middot; Full user guide</p>\n<h2 style="font-family:\'Archivo SemiExpanded\';color:#f5c542;font-size:20px;font-weight:800;margin:24px 0 8px;border-bottom:1px solid #283246;padding-bottom:4px;">🇮🇹 Guida completa</h2>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">1 · Avvio automatico</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">Avvia <b>Le Mans Ultimate</b> e vai in pista come al solito. Non serve premere niente: l\'app rileva la sessione, la <b>crea e apre da sola</b> e ti porta dentro la sessione live giusta (pista, layout e classe corretti). Lo sfondo mostra la <b>foto del circuito</b> corrente.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">Mentre giri, ogni giro completato compare nel board con tempo, settori e validità. I giri non validi (outlap, rientro box, track limits) non entrano in telemetria.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">2 · Menu circuiti</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">Dalla home scegli <b>pista e layout</b>: ogni card mostra la foto del tracciato. La lista è scrollabile. Se hai già sessioni su quella pista le ritrovi qui.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">3 · Overview — sessioni e board</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">A <b>sinistra</b> le tue <b>sessioni</b>: ogni card ha le <b>5 icone meteo previste</b> (dalla partenza al traguardo), auto, classe e tempo migliore. Le card si filtrano per pista, layout e classe.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">A <b>destra</b> il <b>board</b>: stint, giri e tempi. <b>Clicca il cerchietto di un giro</b> per selezionarlo (SEL): la telemetria si carica su quel giro. Seleziona un <b>secondo giro</b> come confronto (CMP): viene sovrapposto.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Wet/Dry</b>: quando selezioni un giro, i giri di condizione opposta (asciutto↔bagnato) si <b>oscurano</b> e non sono selezionabili, così confronti solo condizioni omogenee.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">4 · Telemetry — i grafici</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">In alto la barra dei <b>sotto-tab</b>: <b>Worksheet</b> (più canali insieme), <b>Speed / Steering / Gear / RPM</b>, <b>Tyres</b>, <b>Brakes</b>, <b>Suspension</b>, <b>Pedals</b>, <b>G-G</b>, <b>Aids</b> (TC/ABS/bias), <b>Delta</b>, e i consumi <b>VE / Fuel / Hybrid</b>.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Scrub</b>: muovi il mouse <b>sopra un grafico</b> (o sulla mappa) → una linea verticale segue il puntatore, la <b>mappa evidenzia il punto</b> e leggi i <b>valori esatti</b> in quel punto del giro.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Cursori A/B (shift-click)</b>: <b>shift-click</b> sul grafico piazza il cursore <span style=\'color:#f0a23a\'><b>A</b></span> (arancione), un secondo shift-click il cursore <span style=\'color:#36c5d0\'><b>B</b></span> (ciano). In alto a destra compaiono <b>ΔX</b> (distanza in metri tra A e B) e <b>Δ valore</b> nel canale (es. Δkm/h, Δ°C). I cursori A/B e lo <b>zoom</b> sono <b>sincronizzati su tutti i grafici</b> contemporaneamente.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Legenda cliccabile</b>: i pallini SEL/CMP/REF in alto al grafico cambiano colore della traccia. Il giro più veloce è evidenziato.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">5 · Tyres — gomme per ruota</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">Scegli la <b>ruota</b> (FL/FR/RL/RR) cliccando l\'angolo, e lo <b>strato</b> con i tab <b>Surface / Carcass / Inner / Press / Wear</b>. Il grafico mostra il canale scelto lungo il giro per quella ruota.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">Sotto trovi i due grafici meteo continui <b>Asfalto °C</b> e <b>Rain %</b> (stessa larghezza e altezza): temperatura pista e pioggia lungo il giro.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">6 · G-G e mappa</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>G-G</b>: il diagramma delle accelerazioni laterali/longitudinali (quanto stai sfruttando il grip). La <b>mappa</b> a destra mostra il tracciato col punto evidenziato dallo scrub e il confronto SEL vs CMP.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">7 · REF — riferimento</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">Confronta il giro selezionato con un <b>riferimento</b>: il tuo miglior giro <b>LOCAL</b> oppure la <b>community ONLINE</b>, abbinato per <b>classe + pista + condizione</b>. Colori: <span style=\'color:#f5c542\'><b>oro = asciutto</b></span>, <span style=\'color:#4aa3df\'><b>blu = bagnato</b></span>. Se l\'online coincide col tuo tempo, la card doppia viene nascosta.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">8 · Community · Team · Engineer</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Community</b>: tempi di riferimento per pista e classe. <b>Team</b>: <b>esporta/importa</b> sessioni in un file zip per condividerle con la squadra. <b>Engineer</b>: ingegnere di pista assistito.</p>\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:18px 0 3px;font-weight:700;">9 · Engineer — l\'ingegnere di gara</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">L\'<b>Engineer</b> e\' un ingegnere di pista a voce: guarda la tua telemetria in tempo reale e ti parla via radio durante la gara, come un vero muretto. Parla in italiano. Funziona in <b>gara</b> (in prova/qualifica ti da i riferimenti sui settori).</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Briefing iniziale</b>: a inizio gara calcola la <b>strategia</b> &mdash; giri totali, stint, numero di soste, autonomia di benzina o energia. Sulle GT3 il consumo lo ricava dal <b>consumo reale</b> della tua macchina, non da stime.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Durante la gara</b>: controllo passo e consumi, <b>dove perdi</b> (settori rispetto al tuo miglior tempo), <b>report di gestione periodico</b> (gomme, carburante), e <b>chiamata box intelligente</b> &mdash; gomme al 65%, foratura, benzina in esaurimento, penalita\', danni.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Pioggia</b> (dove serve davvero): ti avvisa appena inizia, ti chiama dentro per le wet in base a <b>quanto e\' bagnata la pista sotto le ruote</b>, ti dice quanta benzina mettere alla sosta, gestisce la temperatura delle wet, ti segnala il <b>settore piu\' bagnato</b> e la <b>finestra per le slick</b> quando si forma la linea asciutta.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Raccomandazione gomme</b>: costruita dalla superficie sotto le tue ruote &mdash; linea asciutta &rarr; slick, bagnato &rarr; wet. Se decidi di <b>restare fuori</b> con le wet che asciugano, l\'ingegnere prende atto della tua scelta e smette di insistere, passando a supportarti.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Gap e bandiere</b>: distacco su chi e\' davanti e dietro, segnale di <b>undercut</b> quando il rivale rientra ai box, bandiere gialle e full course yellow.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Impara dalle tue sessioni</b>: per ogni pista e classe, separando asciutto e bagnato, memorizza <b>consumo per giro</b>, <b>degrado gomme</b>, <b>miglior tempo e settori</b>. Piu\' giri puliti accumuli, piu\' diventa preciso: sa gia\' come si comporta la pista <i>per te</i>, e affina coi dati della gara in corso.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Ritmo radio</b>: aggiornamenti regolari senza martellare, e le chiamate critiche (box, gialla) hanno sempre la precedenza.</p>\n<hr style="border:none;border-top:1px solid #283246;margin:26px 0;">\n<h2 style="font-family:\'Archivo SemiExpanded\';color:#f5c542;font-size:20px;font-weight:800;margin:24px 0 8px;border-bottom:1px solid #283246;padding-bottom:4px;">🇬🇧 Full guide</h2>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">1 · Auto start</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">Launch <b>Le Mans Ultimate</b> and go on track as usual. No buttons needed: the app detects the session, <b>creates and opens it automatically</b> and focuses the right live session (track, layout and class). The background shows the current <b>circuit photo</b>.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">As you drive, each completed lap appears on the board with time, sectors and validity. Invalid laps (outlap, pit return, track limits) are excluded from telemetry.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">2 · Circuit menu</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">From the home screen pick <b>track and layout</b>: each card shows the circuit photo. The list scrolls. Existing sessions for that track show up here.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">3 · Overview — sessions & board</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Left</b>: your <b>sessions</b>. Each card has the <b>5 forecast icons</b> (start to finish), car, class and best time, filtered by track, layout and class.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Right</b>: the <b>board</b> with stints, laps and times. <b>Click a lap\'s circle</b> to select it (SEL): telemetry loads for that lap. Pick a <b>second lap</b> as compare (CMP) to overlay it.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Wet/Dry</b>: when a lap is selected, laps of the opposite condition (dry↔wet) are <b>dimmed</b> and not selectable, so you only compare like-for-like.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">4 · Telemetry — the charts</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">Top <b>sub-tabs</b>: <b>Worksheet</b> (several channels at once), <b>Speed / Steering / Gear / RPM</b>, <b>Tyres</b>, <b>Brakes</b>, <b>Suspension</b>, <b>Pedals</b>, <b>G-G</b>, <b>Aids</b> (TC/ABS/bias), <b>Delta</b>, plus <b>VE / Fuel / Hybrid</b>.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Scrub</b>: move the mouse <b>over a chart</b> (or the map) → a vertical line follows the pointer, the <b>map highlights the point</b> and you read the <b>exact values</b> at that spot on the lap.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>A/B cursors (shift-click)</b>: <b>shift-click</b> on a chart sets cursor <span style=\'color:#f0a23a\'><b>A</b></span> (orange), a second shift-click sets <span style=\'color:#36c5d0\'><b>B</b></span> (cyan). Top-right shows <b>ΔX</b> (distance in metres between A and B) and the <b>Δ value</b> in the channel (e.g. Δkm/h, Δ°C). A/B cursors and <b>zoom</b> are <b>synced across all charts</b> at once.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Clickable legend</b>: the SEL/CMP/REF dots above the chart recolour the traces. The fastest lap is highlighted.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">5 · Tyres — per wheel</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">Pick the <b>wheel</b> (FL/FR/RL/RR) by clicking its corner, and the <b>layer</b> with the <b>Surface / Carcass / Inner / Press / Wear</b> tabs. The chart shows the chosen channel along the lap for that wheel.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">Below are the two continuous weather charts <b>Track °C</b> and <b>Rain %</b> (same width and height): track temperature and rain along the lap.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">6 · G-G & map</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>G-G</b>: the lateral/longitudinal acceleration diagram (how much grip you\'re using). The <b>map</b> on the right shows the track with the scrub point and SEL vs CMP.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">7 · REF — reference</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">Compare the selected lap with a <b>reference</b>: your best <b>LOCAL</b> lap or the <b>ONLINE community</b>, matched by <b>class + track + condition</b>. Colours: <span style=\'color:#f5c542\'><b>gold = dry</b></span>, <span style=\'color:#4aa3df\'><b>blue = wet</b></span>. If the online time equals yours, the duplicate card is hidden.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">8 · Community · Team · Engineer</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Community</b>: reference times by track and class. <b>Team</b>: <b>export/import</b> sessions as a zip to share with your team. <b>Engineer</b>: assisted race engineer.</p><h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:18px 0 3px;font-weight:700;">9 · Engineer — your race engineer</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">The <b>Engineer</b> is a voice race engineer: it watches your live telemetry and talks to you over the radio during the race, like a real pit wall. Works during the <b>race</b> (in practice/qualifying it gives you sector references).</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Opening briefing</b>: at race start it works out the <b>strategy</b> &mdash; total laps, stints, number of pit stops, fuel or energy range. On GT3s the consumption is taken from your car\'s <b>real fuel burn</b>, not from estimates.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>During the race</b>: pace and consumption checks, <b>where you\'re losing time</b> (sectors vs your best lap), a <b>periodic management report</b> (tyres, fuel), and <b>smart pit calls</b> &mdash; tyres at 65%, puncture, fuel running low, penalties, damage.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Rain</b> (where it really matters): it warns you as it starts, calls you in for wets based on <b>how wet the track is under your wheels</b>, tells you how much fuel to take at the stop, manages wet-tyre temperature, flags the <b>wettest sector</b> and the <b>slick window</b> as the dry line forms.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Tyre recommendation</b>: built from the surface under your wheels &mdash; dry line &rarr; slicks, wet &rarr; wets. If you choose to <b>stay out</b> on drying wets, the engineer acknowledges your call, stops nagging and switches to supporting you.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Gaps and flags</b>: gap to the car ahead and behind, an <b>undercut</b> prompt when a rival pits, yellow flags and full course yellow.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>It learns from your sessions</b>: per track and class, dry and wet kept separate, it stores <b>fuel per lap</b>, <b>tyre degradation</b>, <b>best lap and sectors</b>. The more clean laps you bank, the sharper it gets: it already knows how the track behaves <i>for you</i>, and refines with the current race data.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Radio rhythm</b>: regular updates without spamming, and critical calls (box, yellow) always take priority.</p>\n'
        lab = QLabel(html)
        lab.setFont(QFont("Archivo SemiExpanded"))
        lab.setTextFormat(Qt.RichText)
        lab.setWordWrap(True)
        lab.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        lab.setMaximumWidth(760)
        lab.setStyleSheet("background:#0c1320;border:1px solid #1e2940;"
                          "border-radius:14px;padding:28px 34px;color:#cdd2dc;"
                          "font-family:'Archivo SemiExpanded';")
        host = QWidget(); host.setStyleSheet("background:transparent;")
        hl = QHBoxLayout(host); hl.setContentsMargins(20, 18, 20, 26)
        hl.addStretch(1); hl.addWidget(lab, 0, Qt.AlignTop); hl.addStretch(1)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        sc.setWidget(host)
        return sc


    def _circuit_photo(self):
        """Sfondo dell'app: UNA sola immagine fissa assets/overview.jpg (se presente),
        al posto delle foto per-circuito. Se il file manca, torna alla foto del
        circuito corrente (assets/trackcards/<bgkey>.*)."""
        # 1) immagine unica overview.jpg (cache dedicata)
        if "_overview_bg" not in _AppPage._PHOTO_CACHE:
            _ov = _AppPage._PHOTO_DIR.parent / "overview.jpg"
            _pm = QPixmap(str(_ov)) if _ov.exists() else None
            _AppPage._PHOTO_CACHE["_overview_bg"] = \
                _pm if (_pm is not None and not _pm.isNull()) else None
        if _AppPage._PHOTO_CACHE["_overview_bg"] is not None:
            return _AppPage._PHOTO_CACHE["_overview_bg"]
        # 2) fallback: foto del circuito corrente
        try:
            bgkey = self._track[1] if self._track else None
        except Exception:
            bgkey = None
        if not bgkey:
            return None
        if bgkey in _AppPage._PHOTO_CACHE:
            return _AppPage._PHOTO_CACHE[bgkey]
        pm = None
        for ext in ("jpg", "jpeg", "png", "webp"):
            _p = _AppPage._PHOTO_DIR / ("%s.%s" % (bgkey, ext))
            if _p.exists():
                _pm = QPixmap(str(_p))
                if not _pm.isNull():
                    pm = _pm
                    break
        _AppPage._PHOTO_CACHE[bgkey] = pm
        return pm

    def __init__(self, on_back=None, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QScrollArea
        self._track = None
        self._on_back = on_back
        self._sel_card = None
        self._con = None
        self._groups = {}
        self._stint_keys = []
        self._tyre4 = []
        self._stint_new = {}
        self._stint_new4 = {}
        self._cur_stint = None
        self._sel_lap = None
        self._cmp_lap = None
        self._cur_tab = "Tempi"
        self._armed = False
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 16)
        root.setSpacing(12)

        # legacy nascosto: costruisce data + tutte le tab reali + recorder
        self._legacy = _LegacyWindow()
        self._legacy._app_page = self          # backref: import team aggiorna la lista nuova
        self._legacy.hide()

        # ══ riga 1: back + pista | TOP TAB (centro) | tempo ══
        head = QHBoxLayout()
        head.setSpacing(14)
        self._back = QPushButton("arrow_back")
        self._back.setCursor(Qt.PointingHandCursor)
        self._back.setFixedWidth(34)
        self._BACK_QSS = (
            "QPushButton { font-family:'Material Icons'; font-size:26px; color:#ffffff;"
            " background:transparent; border:none; padding:0; }"
            "QPushButton:hover { color:rgba(255,29,67,1.0); }")
        self._BACK_QSS_LOCK = (
            "QPushButton { font-family:'Material Icons'; font-size:24px;"
            " color:#ff4d5a; background:transparent; border:none; padding:0; }"
            "QPushButton:hover { color:#ff8089; }")
        self._back.setStyleSheet(self._BACK_QSS)
        self._back.clicked.connect(self._back_clicked)
        self._title = QLabel("")
        # titoli pagina in ARCHIVO (font WEC originale), corsivo 900
        self._title.setStyleSheet(
            "color:#ffffff; font-family:'Archivo SemiExpanded';"
            " font-style:italic; font-weight:900;"
            " font-size:26px; background:transparent;")
        head.addWidget(self._back, 0, Qt.AlignVCenter)
        head.addWidget(self._title, 0, Qt.AlignVCenter)
        # nota LUCCHETTO: visibile SOLO a sessione armata (auto-focus attivo)
        self._lock_note = QLabel("")
        self._lock_note.setStyleSheet(
            "color:#ff4d5a; font-family:'Archivo SemiExpanded';"
            " font-weight:700; font-size:12px; background:transparent;")
        self._lock_note.hide()
        head.addWidget(self._lock_note, 0, Qt.AlignVCenter)
        head.addStretch(1)
        # top tab al centro
        self._cur_top = 0
        self._toptabs = []
        _topw = QWidget(); _topw.setStyleSheet("background:transparent;")
        _topl = QHBoxLayout(_topw); _topl.setContentsMargins(0, 0, 0, 0); _topl.setSpacing(8)
        for i, lab in enumerate(("Overview", "Telemetry", "Setups", "Overlay",
                                 "Community", "Team", "Engineer")):
            b = QPushButton(lab.upper())
            b.setCheckable(True); b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, ix=i: self._select_top(ix))
            b.setStyleSheet(self._TAB_OFF)
            _topl.addWidget(b); self._toptabs.append(b)
        # NELLE SESSIONI restano solo Overview / Telemetry / Setups. Overlay(3),
        # Community(4), Team(5) sono ora pagine standalone raggiungibili dalla
        # barra del menu, non tab di sessione. Engineer(6) si apre dal popup.
        # Il contenuto resta creato (raggiungibile via _select_top dal menu),
        # ma il BOTTONE tab e' nascosto.
        for _hid in (3, 4, 5, 6):
            try:
                self._toptabs[_hid].hide()
            except Exception:
                pass
        head.addWidget(_topw, 0, Qt.AlignVCenter)
        head.addStretch(1)
        # tempo sessione a destra
        self._sess_time = QLabel("")
        self._sess_time.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._sess_time.setStyleSheet(
            "color:#ffffff; font-family:'Archivo SemiExpanded'; font-weight:700; font-size:28px;"
            " background:transparent;")
        self._sess_time.setVisible(False)
        head.addWidget(self._sess_time, 0, Qt.AlignVCenter)
        # orologio fluido: la riga sessione si aggiorna OGNI SECONDO
        from PySide6.QtCore import QTimer as _QT
        self._sess_time_timer = _QT(self)
        self._sess_time_timer.timeout.connect(self._set_sess_time)
        self._sess_time_timer.start(1000)
        root.addLayout(head)

        # ══ riga 2: SUB-TAB a tutta larghezza (visibili su Telemetry) ══
        self._real_tabs = self._legacy.tabs
        self._real_tabs.setParent(None)
        self._real_tabs.tabBar().hide()
        self._real_tabs.setStyleSheet("QTabWidget::pane{border:none;background:transparent;}")
        self._subbar = QScrollArea()
        self._subbar.setWidgetResizable(True)
        self._subbar.setFrameShape(QFrame.NoFrame)
        self._subbar.setFixedHeight(44)
        self._subbar.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._subbar.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._subbar.setStyleSheet("QScrollArea{background:transparent;border:none;}"
                                   "QScrollBar:horizontal{height:0px;background:transparent;}"
                                   "QScrollBar::handle:horizontal{background:rgba(255,255,255,0.25);"
                                   "border-radius:3px;}"
                                   "QScrollBar::add-line,QScrollBar::sub-line{width:0;height:0;}")
        _sbw = QWidget(); _sbw.setStyleSheet("background:transparent;")
        _sbl = QHBoxLayout(_sbw); _sbl.setContentsMargins(0, 0, 0, 0); _sbl.setSpacing(8)
        self._subtabs = []
        for i in range(self._real_tabs.count()):
            b = QPushButton(self._real_tabs.tabText(i).upper())
            b.setCheckable(True); b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, ix=i: self._select_sub(ix))
            b.setStyleSheet(self._TAB_OFF)
            _sbl.addWidget(b); self._subtabs.append(b)
        _sbl.addStretch(1)
        self._subbar.setWidget(_sbw)
        root.addWidget(self._subbar)

        # ══ riga 3: stack pagine top-level (tutta pagina) ══
        self._top_stack = QStackedWidget()

        # — pagina OVERVIEW: due colonne (sessioni / board) —
        ov = QWidget(); ov.setStyleSheet("background:transparent;")
        ovl = QHBoxLayout(ov); ovl.setContentsMargins(0, 0, 0, 0); ovl.setSpacing(18)
        left = QVBoxLayout(); left.setSpacing(12)
        # ── filtri classe (pill stile sotto-tab) ──
        self._cls_filter = None          # None=ALL | HY/GT3/P2/P3/GTE | "TEAM"
        self._cls_chips = {}
        _CHIPS = [("ALL", None), ("HYPER", "HY"), ("LMGT3", "GT3"),
                  ("LMP2", "P2"), ("LMP3", "P3"), ("LMGTE", "GTE"), ("TEAM", "TEAM")]
        _chipbar = QWidget(); _chipbar.setStyleSheet("background:transparent;")
        _chl = QHBoxLayout(_chipbar); _chl.setContentsMargins(0, 0, 0, 2); _chl.setSpacing(6)
        for _lab, _tag in _CHIPS:
            cb = QPushButton(_lab); cb.setCursor(Qt.PointingHandCursor)
            cb.clicked.connect(lambda _=False, t=_tag: self._set_cls_filter(t))
            cb.setStyleSheet(self._CHIP_ON if _tag is None else self._CHIP_OFF)
            _chl.addWidget(cb); self._cls_chips[_tag] = cb
        _chl.addStretch(1)
        left.addWidget(_chipbar)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet(
            "QScrollArea { background:transparent; border:none; }"
            "QScrollBar:vertical { width:0px; background:transparent; margin:0; }"
            "QScrollBar::handle:vertical { background:rgba(255,255,255,0.25);"
            " border-radius:4px; min-height:30px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }")
        self._scroll.viewport().setStyleSheet("background:transparent;")
        self._list = QWidget(); self._list.setStyleSheet("background:transparent;")
        self._lv = QVBoxLayout(self._list)
        self._lv.setContentsMargins(0, 0, 6, 0)
        self._lv.setSpacing(10)
        self._lv.addStretch(1)
        self._scroll.setWidget(self._list)
        left.addWidget(self._scroll, 1)
        self._empty = QLabel("Nessuna sessione per questo layout")
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setStyleSheet("color:#aeb6c4; font-family:'Archivo SemiExpanded'; font-size:15px;"
                                  " background:transparent;")
        self._empty.hide()
        left.addWidget(self._empty)
        left_w = QWidget(); left_w.setLayout(left)
        left_w.setStyleSheet("background:transparent;")
        left_w.setMinimumWidth(488)
        ovl.addWidget(left_w, 2)

        self._right = QWidget()
        self._right.setObjectName("apBoardHost")
        self._right.setStyleSheet("#apBoardHost{background:transparent;}" + _OV_BOARD_QSS)
        rl = QVBoxLayout(self._right)
        rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(0)
        self.board = _LapBoard()
        self.board.setStyleSheet(_OV_BOARD_QSS)
        self.board.set_callbacks(self._board_on_stint, self._board_on_pick)
        self.board._scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollBar:vertical{width:0px;background:transparent;margin:0;}"
            "QScrollBar::handle:vertical{background:rgba(255,255,255,0.25);"
            "border-radius:4px;min-height:30px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}")
        from PySide6.QtGui import QPalette
        _vp = self.board._scroll.viewport()
        _vp.setAutoFillBackground(False)
        _pal = _vp.palette(); _pal.setColor(QPalette.Window, Qt.transparent)
        _vp.setPalette(_pal)
        self.board._laps_host.setAutoFillBackground(False)
        self.board.tabs_bar.setStyleSheet(_OV_BOARD_QSS)
        # ── il motore ORIGINALE disegna nel TUO board (collega vecchio a nuovo) ──
        try:
            self._legacy._overview.board = self.board
            self.board.set_callbacks(self._legacy._board_stint,
                                     self._legacy._board_pick)
            # card REF (oro) + ONLINE REF (blu) dal motore: sotto i giri
            _rc = getattr(self._legacy._overview, "ref_card", None)
            if _rc is not None:
                _rc.setMinimumWidth(0); _rc.setMaximumWidth(16777215)
                self.board._ref_slot.addWidget(_rc)
        except Exception:
            pass
        self._board_box = QWidget()
        bcl = QVBoxLayout(self._board_box)
        bcl.setContentsMargins(0, 0, 0, 0); bcl.setSpacing(6)
        bcl.addWidget(self.board.tabs_bar)
        bcl.addWidget(self.board.lb_summary)
        bcl.addWidget(self.board, 1)
        try:
            _dv = self.board.layout().itemAt(0).widget()
            if _dv is not None:
                _dv.hide()
        except Exception:
            pass
        self._board_hint = QLabel("Seleziona una sessione")
        self._board_hint.setAlignment(Qt.AlignCenter)
        self._board_hint.setStyleSheet("color:#aeb6c4; font-family:'Archivo SemiExpanded';"
                                       " font-size:15px; background:transparent;")
        self._board_box.setVisible(False)
        rl.addWidget(self._board_box, 1)
        rl.addWidget(self._board_hint, 1)
        ovl.addWidget(self._right, 3)

        self._top_stack.addWidget(ov)                       # 0 Overview (TUA grafica)
        self._top_stack.addWidget(self._real_tabs)          # 1 Telemetry
        self._top_stack.addWidget(self._legacy.settings_page)   # 2 Settings
        self._top_stack.addWidget(self._legacy._overlaytab)     # 3 Overlay (widget in pista)
        self._top_stack.addWidget(self._legacy._community)      # 4 Community
        self._top_stack.addWidget(self._legacy._teamtab)        # 5 Team
        self._top_stack.addWidget(self._legacy._engineer)       # 6 Engineer
        # ORDINE LOGICO 0..6 per _select_top: le pagine nuove (Telemetry a
        # tutta pagina, OPTIONS) RUBANO widget da questo stack reimparentandoli
        # e gli indici del QStackedWidget scalano — l'indice fisso apriva la
        # pagina sbagliata (TEAMS -> Setup). Si risolve per WIDGET, mai per
        # posizione.
        self._top_pages = [ov, self._real_tabs, self._legacy.settings_page,
                           self._legacy._overlaytab, self._legacy._community,
                           self._legacy._teamtab, self._legacy._engineer]
        root.addWidget(self._top_stack, 1)

        # nessun footer qui: il tasto START/STOP è UNICO (overlay in TelemetryWindow)

        self._select_sub(0)
        self._select_top(0)

        # ── refresh live durante la registrazione (logica dell'originale) ──
        self._was_live = False
        self._live_file = None
        from PySide6.QtCore import QTimer
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(1000)
        self._live_timer.timeout.connect(self._live_tick)
        self._live_timer.start()

    def _title_for_track(self, track):
        """Nome pista+layout come nel menu (es. 'Monza Curva Grande')."""
        lk = _track_layout_key(track)
        for e in _TRACKS:
            if _cmap_layout_key(e[4]) == lk:
                return e[2]
        stem = _track_logo_stem(track) or ""
        lab = _track_layout_label(track)
        return (stem + (" " + lab if lab else "")).strip() or stem

    def go_live(self):
        """Porta sulla sessione attiva (registrazione in corso): forza l'auto-jump
        originale sul circuito in uso e ricostruisce le card + titolo."""
        leg = getattr(self, "_legacy", None)
        if leg is None:
            return
        rec = getattr(leg, "_recorder", None)
        try:
            leg.stack.setCurrentWidget(leg._review_page)   # abilita live refresh
            if bool(rec) and rec.is_armed():
                leg._was_armed_live = False
                leg._live_jump_pending = True
                leg._live_refresh()                        # auto-jump sulla sessione attiva
        except Exception:
            pass
        self._reload_sessions()
        self._select_top(0)
        sessions = getattr(leg, "_sessions", []) or []
        cur = getattr(leg, "_cur_sess", -1)
        if 0 <= cur < len(sessions):
            m = sessions[cur]
            self._title.setText((self._title_for_track(m.get("track"))
                                or m.get("name")
                                or self._title.text()).upper())

    def _entry_for_track(self, track):
        """Card _TRACKS che corrisponde alla pista LMU in uso (layout incluso)."""
        if not track:
            return None
        stem = _track_logo_stem(track)
        lkey = _track_layout_key(track)
        for e in _TRACKS:                       # match esatto pista + layout
            if _cmap_layout_key(e[4]) == lkey and (stem is None or e[3] == stem):
                return e
        for e in _TRACKS:                       # fallback: stessa pista, layout qualunque
            if stem is not None and e[3] == stem:
                return e
        return None

    def show_live_session(self):
        """Wrapper: l'auto-focus live è gestito da _live_focus (autorità unica)."""
        try:
            self._live_focus()
        except Exception:
            pass

    def set_track(self, entry):
        self._track = entry            # (base, bgkey, name, logo, cmap)
        self._title.setText((entry[2] or "").upper() if entry else "")
        leg = getattr(self, "_legacy", None)
        if leg is not None and entry is not None:
            try:
                leg._track_filter = entry[3]                       # pista (stem logo)
                leg._layout_filter = _cmap_layout_key(entry[4])     # LAYOUT scelto (stem grezzo)
                leg._reload_sessions()                            # filtra pista + layout
                leg.stack.setCurrentWidget(leg._review_page)      # live refresh attivo
                if leg._sessions:
                    leg._user_picked_session = True
                    leg._on_session(0)                            # carica sessione 0 nel board
            except Exception:
                pass
        self._reload_sessions()
        self._select_top(0)
        # sfondo pagina sessione = foto del circuito corrente (su central, il
        # widget realmente visibile dietro la pagina)
        cbg = getattr(self, "_central_bg", None)
        if cbg is not None:
            try:
                cbg.set_photo(self._circuit_photo())
            except Exception:
                pass

    def _select_top(self, ix):
        self._cur_top = ix
        for j, b in enumerate(self._toptabs):
            on = (j == ix)
            b.setChecked(on)
            b.setStyleSheet(self._TAB_ON if on else self._TAB_OFF)
        # per WIDGET, non per posizione: lo stack perde pezzi quando le
        # pagine nuove li montano altrove e gli indici scalano
        try:
            _w = self._top_pages[ix]
            _real = self._top_stack.indexOf(_w)
            if _real >= 0:
                self._top_stack.setCurrentIndex(_real)
        except Exception:
            self._top_stack.setCurrentIndex(ix)
        self._subbar.setVisible(ix == 1 and not getattr(self, "_menu_open", False))
        # colonna sonora: la pagina interna e' cambiata (es. Setups)
        _th = getattr(self, "_top_hook", None)
        if _th is not None:
            try:
                _th()
            except Exception:
                pass

    def _menu_mode(self, on):
        """Pagina aperta dalla barra del MENU (Overlay/Teams/Community/Setups):
        on=True nasconde TUTTA la barra tab di sessione (non e' una sessione).
        on=False = sessione normale: tornano Overview/Telemetry/Setups (le altre
        restano nascoste, sono solo dal menu). La freccia indietro resta sempre."""
        self._menu_open = bool(on)
        for j, b in enumerate(self._toptabs):
            try:
                b.setVisible((not on) and j in (0, 1, 2))
            except Exception:
                pass

    def _select_sub(self, ix):
        for j, b in enumerate(self._subtabs):
            on = (j == ix)
            b.setChecked(on)
            b.setStyleSheet(self._SUB_ON if on else self._TAB_OFF)
        try:
            self._real_tabs.setCurrentIndex(ix)
        except Exception:
            pass

    def _refresh_overview(self):
        sel = self._sel_card is not None
        self._board_hint.setVisible(not sel)
        self._board_box.setVisible(sel)

    def _on_start(self):
        # arma/disarma il recorder REALE dell'app originale
        leg = getattr(self, "_legacy", None)
        if leg is not None:
            try:
                leg._toggle_rec()
            except Exception:
                pass
            rec = getattr(leg, "_recorder", None)
            self._armed = bool(rec) and rec.is_armed()
        else:
            self._armed = not self._armed
        self._sync_start_btn(self._armed, force=True)

    def _back_clicked(self):
        """A sessione ARMATA l'uscita e' bloccata (l'auto-focus ti
        riporterebbe comunque qui): il lucchetto lo DICHIARA, invece di
        sembrare un bug. Il click mostra il perche' in rosso.
        REGOLA (23/07): le pagine aperte DALLO stint (Setups) tornano
        allo stint = dentro la sessione -> MAI bloccate."""
        if getattr(self, "_return_stint", False):
            if self._on_back:
                self._on_back()
            return
        if getattr(self, "_armed", False):
            try:
                self._lock_note.setText("SESSION LIVE — STOP TO EXIT")
                QTimer.singleShot(2500, lambda: (
                    self._lock_note.setText("SESSION LIVE")
                    if getattr(self, "_armed", False) else None))
            except Exception:
                pass
            return
        if self._on_back:
            self._on_back()

    def _apply_back_lock(self, armed):
        """Freccia indietro <-> LUCCHETTO con la nota rossa di stato."""
        try:
            if getattr(self, "_return_stint", False):
                armed = False        # pagina interna: freccia libera
            if armed:
                self._back.setText("lock")
                self._back.setStyleSheet(self._BACK_QSS_LOCK)
                self._back.setToolTip("Session live: exit locked (STOP to leave)")
                self._lock_note.setText("SESSION LIVE")
                self._lock_note.show()
            else:
                self._back.setText("arrow_back")
                self._back.setStyleSheet(self._BACK_QSS)
                self._back.setToolTip("")
                self._lock_note.hide()
        except Exception:
            pass

    def _sync_start_btn(self, armed, force=False):
        if (not force) and armed == getattr(self, "_armed", False):
            # stato invariato: aggiorna comunque l'hook (bottone unico) e basta
            hook = getattr(self, "_armed_hook", None)
            if hook is not None:
                try:
                    hook(armed)
                except Exception:
                    pass
            return
        self._armed = armed
        self._apply_back_lock(armed)    # freccia <-> lucchetto (uscita bloccata)
        self._apply_live_dim()          # dim/undim sessioni precedenti
        hook = getattr(self, "_armed_hook", None)
        if hook is not None:
            try:
                hook(armed)
            except Exception:
                pass

    def _live_tick(self):
        """Sync stato recorder (bottone/banner) + UNA SOLA autorità di auto-focus
        sulla sessione live (_live_focus)."""
        leg = getattr(self, "_legacy", None)
        rec = getattr(leg, "_recorder", None) if leg else None
        armed = bool(rec) and rec.is_armed()
        self._sync_start_btn(armed)
        bhook = getattr(self, "_banner_hook", None)
        if bhook is not None and rec is not None:
            try:
                _k, _t = rec.banner(); bhook(_k, _t)
            except Exception:
                pass
        if not armed:
            self._was_live = False
            self._live_focused = None
            return
        self._was_live = True
        self._set_sess_time()                 # timer sessione (rimanente)
        self._live_focus()                    # autorità unica

    def _live_focus(self):
        """AUTORITÀ UNICA dell'auto-focus. Porta e tiene l'app sulla sessione che
        il recorder sta scrivendo: pista + layout + classe + card live caricata.
        Deriva tutto dal recorder (file/pista/classe), non da stati intermedi.
        Idempotente: se è già centrata sulla live, non rifà nulla (lascia che i
        giri si aggiornino)."""
        import os
        leg = getattr(self, "_legacy", None)
        rec = getattr(leg, "_recorder", None) if leg else None
        if not (rec and rec.is_armed()):
            self._live_focused = None
            return
        lf = None
        track = None
        try:
            lf = rec.current_file()
            track = rec.current_track()
        except Exception:
            pass
        lfn = os.path.basename(lf) if lf else None
        if not lfn or not track:
            return                             # sessione non ancora pronta: aspetta
        # pagina stint gia' agganciata a QUESTA live: STOP (senza questo, i
        # filtri+reload rieseguiti ogni tick svuotavano il board e il poll lo
        # riempiva -> giri che apparivano e sparivano a flash)
        if (getattr(self, "_stint_live_hook", None) is not None
                and getattr(self, "_live_focused", None) == lfn):
            return
        # sfondo pagina sessione: imposta la foto del circuito anche in auto-avvio
        # (l'auto-focus non passa da set_track), derivandola dal track del recorder
        try:
            cbg = getattr(self, "_central_bg", None)
            if cbg is not None:
                _lk = _track_layout_key(track)
                _ent = next((e for e in _TRACKS if _cmap_layout_key(e[4]) == _lk), None)
                if _ent is None:
                    _st = _track_logo_stem(track)
                    _ent = next((e for e in _TRACKS if e[3] == _st), None)
                if _ent is not None:
                    self._track = _ent
                    cbg.set_photo(self._circuit_photo())
        except Exception:
            pass
        # già centrata su questa live e card caricata? non rifare
        if (getattr(self, "_live_focused", None) == lfn and self._sel_card is not None
                and os.path.basename((getattr(self._sel_card, "_meta", {}) or {})
                                     .get("file") or "") == lfn):
            return
        try:
            with open(_db.LOGS_DIR / "recorder.log", "a", encoding="utf-8") as f:
                import time as _t
                f.write(_t.strftime("%H:%M:%S ") +
                        "LIVE-FOCUS track=%r file=%r\n" % (track, lfn))
        except Exception:
            pass
        # filtri pista/layout (chiavi canoniche, come il click manuale)
        try:
            leg._track_filter = _track_logo_stem(track)
            leg._layout_filter = _track_layout_key(track)
            leg._reload_sessions()
            leg.stack.setCurrentWidget(leg._review_page)
        except Exception:
            pass
        sessions = list(getattr(leg, "_sessions", []) or [])
        live = next((s for s in sessions
                     if os.path.basename(s.get("file") or "") == lfn), None)
        if live is None:
            return                             # file non ancora in lista: ritenta dopo
        # NUOVA pagina stint: aggancia la live DIRETTAMENTE dal motore
        # (le card _lv dell app vecchia sono vuote senza set_track: il vecchio
        # percorso non partiva mai -> pagina stint restava vuota)
        hk = getattr(self, "_stint_live_hook", None)
        if hk is not None:
            if getattr(self, "_live_focused", None) != lfn:
                try:
                    _idx = sessions.index(live)
                    # meta appena creato: la pista puo' non essere ancora
                    # flushata -> prendila dal recorder (senno' le pagine
                    # del back restavano vuote, aggancio one-shot)
                    if not (live.get("track") or "").strip() and track:
                        live = dict(live)
                        live["track"] = track
                    leg._user_picked_session = True
                    leg._on_session(_idx)      # apre il file live nel board
                    hk(live)                   # titolo/bg/mount pagina stint
                    self._live_focused = lfn
                except Exception:
                    pass
            return                             # pagina nuova = unica autorita
        # filtro classe = classe della live (sennò un chip rimasto la nasconde)
        try:
            self._cls_filter = class_tag(live.get("car_class") or "") or None
        except Exception:
            self._cls_filter = None
        try:
            self._title.setText((self._title_for_track(track)
                                 or track or "").upper())
        except Exception:
            pass
        self._reload_sessions()
        # seleziona la card live ESATTAMENTE come un click manuale -> carica il board
        card = None
        for j in range(self._lv.count() - 1):
            w = self._lv.itemAt(j).widget()
            if isinstance(w, _SessionCard) and \
                    os.path.basename((getattr(w, "_meta", {}) or {}).get("file") or "") == lfn:
                card = w
                break
        if card is not None:
            self._sel_card = None              # forza il caricamento
            try:
                self._select_card(card)
            except Exception:
                pass
            self._live_focused = lfn
            # avvisa la finestra: pagina STINT nuova aggiornata sulla live
            hk = getattr(self, "_stint_live_hook", None)
            if hk is not None:
                try:
                    hk(live)
                except Exception:
                    pass
        self._select_top(0)
        self._apply_live_dim()          # live agganciata: dima le precedenti

    def _focus_active_card(self, f):
        for i in range(self._lv.count()):
            w = self._lv.itemAt(i).widget()
            if isinstance(w, _SessionCard) and w._meta.get("file") == f:
                if self._sel_card is not None and self._sel_card is not w:
                    self._sel_card.setSelected(False)
                w.setSelected(True)
                self._sel_card = w
                self._load_board(w._meta, live=False)
                self._select_top(0)          # mostra l'Overview (board live)
                return

    def _reload_sessions(self):
        # togli le card vecchie (lascia lo stretch finale)
        while self._lv.count() > 1:
            it = self._lv.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        self._sel_card = None
        leg = getattr(self, "_legacy", None)
        self._update_cls_chips()             # mostra solo i tag realmente presenti
        sessions = list(getattr(leg, "_sessions", []) or []) if leg else []
        try:
            from core.classes import class_tag as _ctag
        except Exception:
            _ctag = lambda x: ""
        filt = getattr(self, "_cls_filter", None)
        show_user = filt != "TEAM"
        n_user = 0
        for i, m in enumerate(sessions):
            if not show_user:
                continue
            if filt and filt != "TEAM" and _ctag(m.get("car_class") or "") != filt:
                continue
            card = _SessionCard(m, on_export=self._export_session,
                                on_delete=self._delete_session)
            card._sess_idx = i               # indice ORIGINALE (il filtro non lo sposta)
            card.on_click = self._select_card
            self._lv.insertWidget(self._lv.count() - 1, card)
            n_user += 1
        # ── sessioni TEAM importate (in coda, etichetta "team", cliccabili) ──
        team = list(getattr(leg, "_team_sessions", []) or []) if leg else []
        n_team = 0
        for ti, tm in enumerate(team):
            if filt and filt != "TEAM" and _ctag(tm.get("car_class") or "") != filt:
                continue
            tm = dict(tm); tm["team_session"] = True
            tcard = _SessionCard(tm, on_delete=self._delete_team_card)
            tcard._team_idx = ti
            tcard.on_click = self._select_team_card
            self._lv.insertWidget(self._lv.count() - 1, tcard)
            n_team += 1
        _has = bool(n_user) or bool(n_team)
        self._empty.setVisible(not _has)
        self._scroll.setVisible(_has)
        # rifletti la sessione selezionata dall'originale (es. la 0 dopo enter_circuit)
        cur = getattr(leg, "_cur_sess", -1) if leg else -1
        if cur >= 0 and not getattr(leg, "_viewing_team", False):
            for j in range(self._lv.count() - 1):
                w = self._lv.itemAt(j).widget()
                if isinstance(w, _SessionCard) and getattr(w, "_sess_idx", None) == cur:
                    w.setSelected(True)
                    self._sel_card = w
                    self._set_sess_time(w._meta)
                    break
        self._refresh_overview()
        self._apply_live_dim()          # card nuove: rispettano lo stato live

    def _apply_live_dim(self):
        """Sessione live in corso (recording) -> le card delle sessioni
        PRECEDENTI vanno a opacita' 40% e non cliccabili; la card della sessione
        live resta normale. A registrazione ferma tornano tutte cliccabili."""
        live = bool(getattr(self, "_armed", False))
        lfn = getattr(self, "_live_focused", None)
        sel = getattr(self, "_sel_card", None)
        for i in range(self._lv.count()):
            w = self._lv.itemAt(i).widget()
            if not isinstance(w, _SessionCard):
                continue
            is_live = bool(lfn) and (os.path.basename(
                (getattr(w, "_meta", {}) or {}).get("file") or "") == lfn)
            # la card ATTIVA (selezionata) o quella live restano NORMALI
            keep = is_live or (w is sel)
            try:
                w.set_dim(live and not keep)
            except Exception:
                pass

    def _set_sess_time(self, meta=None):
        try:
            leg = getattr(self, "_legacy", None)
            rec = getattr(leg, "_recorder", None) if leg else None
            m = {}
            if leg is not None and getattr(leg, "_overview", None) is not None:
                m = getattr(leg._overview, "_meta", {}) or {}
            rr = m.get("_race_remaining")
            # il tempo VIVO viene dal raw del recorder (fresco), non dalla
            # meta della board che si aggiorna ogni 2-3 s (orologio a scatti)
            try:
                _raw_live = (rec.latest() or {}).get("raw") or {} if rec else {}
                _rr_live = float(_raw_live.get("race_remaining") or 0.0)
                if _rr_live > 0:
                    rr = _rr_live
            except Exception:
                pass
            if rr and rec and rec.is_armed():       # SOLO sessione live
                styp = _ov_session_label(m.get("session_type")).upper()
                txt = styp + "    " + _ov_clock(rr)
                # LAP fatti/STIMATI + autonomia E(nergia)/F(uel) in giri,
                # dai dati live del recorder (strategy LMU + raw)
                try:
                    lt = rec.latest() or {}
                    raw = lt.get("raw") or {}
                    strat = lt.get("strat") or {}
                    laps_done = int(raw.get("laps_completed") or 0)
                    est = float(raw.get("est_lap") or 0.0)
                    rrs = float(raw.get("race_remaining") or 0.0)
                    if rrs > 0:
                        import math as _m
                        # stima PRECISA: passo del leader (la bandiera e' sua);
                        # fallback: est del gioco sul tuo giro
                        _tot_ldr = raw.get("race_laps_est")
                        if _tot_ldr:
                            tot = int(_tot_ldr)
                        elif est > 0:
                            tot = laps_done + int(_m.ceil(rrs / est))
                        else:
                            tot = 0
                        if tot > 0:
                            txt += "    LAP %d/%d" % (laps_done + 1, tot)
                    aut = strat.get("autonomy")
                    if aut:
                        _c = (strat.get("constraint") or "FUEL").upper()
                        txt += "    %s/%.1f" % ("E" if _c == "ENERGY" else "F",
                                                float(aut))
                except Exception:
                    pass
                self._sess_time.setText(txt)
                self._sess_time.setVisible(True)
            else:
                self._sess_time.setText("")
                self._sess_time.setVisible(False)
        except Exception:
            self._sess_time.setVisible(False)

    def _select_card(self, card):
        if self._sel_card is card:
            return
        if self._sel_card is not None:
            self._sel_card.setSelected(False)
        card.setSelected(True)
        self._sel_card = card
        leg = getattr(self, "_legacy", None)
        idx = getattr(card, "_sess_idx", None)
        if leg is not None and idx is not None:
            leg._user_picked_session = True
            try:
                leg._on_session(idx)     # motore ORIGINALE -> disegna nel TUO board
            except Exception:
                pass
        self._set_sess_time(card._meta)  # dopo on_session: meta completa con session_len
        self._refresh_overview()

    def _update_cls_chips(self):
        """Mostra una pill classe solo se ci sono sessioni di quel tag;
        TEAM solo se esistono sessioni team. ALL sempre. Se il filtro attivo
        sparisce, torna ad ALL."""
        leg = getattr(self, "_legacy", None)
        try:
            from core.classes import class_tag as _ctag
        except Exception:
            _ctag = lambda x: ""
        user = list(getattr(leg, "_sessions", []) or []) if leg else []
        team = list(getattr(leg, "_team_sessions", []) or []) if leg else []
        tags = set()
        for m in (user + team):
            t = _ctag(m.get("car_class") or "")
            if t:
                tags.add(t)
        has_team = bool(team)
        for tag, cb in self._cls_chips.items():
            if tag is None:
                cb.setVisible(True)
            elif tag == "TEAM":
                cb.setVisible(has_team)
            else:
                cb.setVisible(tag in tags)
        cur = getattr(self, "_cls_filter", None)
        if cur is not None:
            ok = (cur == "TEAM" and has_team) or (cur in tags)
            if not ok:
                self._cls_filter = None
                for t, cb in self._cls_chips.items():
                    cb.setStyleSheet(self._CHIP_ON if t is None else self._CHIP_OFF)

    def _set_cls_filter(self, tag):
        self._cls_filter = tag
        for t, cb in self._cls_chips.items():
            cb.setStyleSheet(self._CHIP_ON if t == tag else self._CHIP_OFF)
        self._reload_sessions()

    def _select_team_card(self, card):
        if self._sel_card is card:
            return
        if self._sel_card is not None:
            self._sel_card.setSelected(False)
        card.setSelected(True)
        self._sel_card = card
        leg = getattr(self, "_legacy", None)
        ti = getattr(card, "_team_idx", None)
        if leg is not None and ti is not None:
            try:
                leg._select_team_session(ti)   # apre la sessione team (REF/online congelati)
            except Exception:
                pass
        self._set_sess_time(card._meta)
        self._refresh_overview()

    def _delete_team_card(self, file):
        leg = getattr(self, "_legacy", None)
        team = list(getattr(leg, "_team_sessions", []) or []) if leg else []
        ti = next((i for i, t in enumerate(team) if t.get("file") == file), None)
        if leg is not None and ti is not None:
            try:
                leg._delete_team_session(ti)
            except Exception:
                pass
        self._reload_sessions()

    # ── board stint/giri (stessa funzione del vecchio) ──
    def _close_con(self):
        if self._con is not None:
            try:
                self._con.close()
            except Exception:
                pass
        self._con = None

    def _load_board(self, meta, live=False):
        prev_keys = list(self._stint_keys)
        prev_stint = self._cur_stint
        was_last = (prev_stint is not None and prev_keys
                    and prev_stint == prev_keys[-1])
        self._close_con()
        self._groups = {}
        self._stint_keys = []
        self._tyre4 = []
        if not live:
            self._sel_lap = None
            self._cmp_lap = None
        f = meta.get("file") if meta else None
        if not f:
            self._sess_time.setText("")
            self._refresh_overview()
            return
        _styp = _ov_session_label(meta.get("session_type"))
        _slen = _fmt_session_len(meta.get("session_len"))
        self._sess_time.setText(_styp + ((" " + _slen) if _slen else ""))
        try:
            from . import db
            self._con = db.open_session(f)
            laps = _rows(self._con, "SELECT * FROM laps ORDER BY lap")
        except Exception:
            self._con = None
            laps = []
        groups = {}
        if laps:
            base = min((L["stint"] or 1) for L in laps)
            for L in laps:
                groups.setdefault((L["stint"] or 1) - base + 1, []).append(L)
        try:
            mr = _rows(self._con, "SELECT compounds4 FROM session_meta WHERE id=1")
            comp = (mr[0]["compounds4"] if mr else "") or ""
            self._tyre4 = [x.strip() for x in comp.split(",")] if comp else []
        except Exception:
            self._tyre4 = []
        self._groups = groups
        self._stint_keys = sorted(groups)
        # gomma nuova/usata per stint (dai samples: MAX wear per ruota >=99.5 = nuova)
        self._stint_new = {}
        self._stint_new4 = {}
        for k in self._stint_keys:
            lk = groups.get(k, [])
            v = self._stint_start_new_from_samples(lk)
            self._stint_new[k] = True if v is None else bool(v)
            self._stint_new4[k] = self._stint_start_new4_from_samples(lk)
        if not self._stint_keys:
            self.board.update_board([], None, [], None, None, None, tyre4=self._tyre4)
            self._refresh_overview()
            if not live:
                self._legacy_open(f)
            return
        # scelta stint: live = segui l'ultimo (se stavi sull'ultimo o non valido);
        # manuale = primo stint
        if live:
            if was_last or (prev_stint not in self._stint_keys):
                self._cur_stint = self._stint_keys[-1]
            else:
                self._cur_stint = prev_stint
            cur_laps = [L["lap"] for L in self._groups.get(self._cur_stint, [])]
            if self._sel_lap not in cur_laps:
                self._sel_lap = None
            if self._cmp_lap not in cur_laps:
                self._cmp_lap = None
        else:
            self._cur_stint = self._stint_keys[0]
            self._sel_lap = None
            self._cmp_lap = None
        self._render_stint()
        self._refresh_overview()
        if not live:
            self._legacy_open(f)

    def _legacy_open(self, f):
        """Carica la sessione nell'app originale (alimenta le tab reali)."""
        leg = getattr(self, "_legacy", None)
        if leg is None:
            return
        try:
            leg._open_session_file(f)
        except Exception:
            pass

    def _legacy_stint(self):
        leg = getattr(self, "_legacy", None)
        if leg is None or self._cur_stint is None:
            return
        try:
            idx = self._stint_keys.index(self._cur_stint)
            leg._on_stint(idx)
        except Exception:
            pass

    def _legacy_lap(self, lap):
        leg = getattr(self, "_legacy", None)
        if leg is None or lap is None:
            return
        try:
            leg._set_lap_lazy(lap)
        except Exception:
            pass

    def _render_stint(self):
        laps = self._groups.get(self._cur_stint, [])
        best = _fastest_lap(laps) if laps else None
        sel = self._sel_lap if (self._sel_lap is not None) else best
        self.board.update_board(self._stint_keys, self._cur_stint, laps,
                                best, sel, self._cmp_lap, tyre4=self._tyre4,
                                stint_new=self._stint_new, stint_new4=self._stint_new4,
                                session_type=(getattr(self, "_meta", {}) or {}).get("session_type"),
                                car_class=(getattr(self, "_meta", {}) or {}).get("car_class"))
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._fit_laps_view)


    def _fit_laps_view(self):
        """Mostra max 10 giri, il resto scrollabile; altezza esatta così la board
        resta compatta (giri subito sotto l'header). Lista in cima."""
        lv = self.board._laps_v
        rowh = 0
        rows = 0
        for i in range(lv.count()):
            w = lv.itemAt(i).widget()
            if w is not None:
                rows += 1
                if rowh == 0:
                    rowh = w.sizeHint().height()
        if rowh <= 0:
            rowh = 34
        sp = lv.spacing()
        n = max(1, min(10, rows))
        self.board._scroll.setFixedHeight(n * rowh + (n - 1) * sp + 6)
        self.board._scroll.verticalScrollBar().setValue(0)

    def _stint_start_new_from_samples(self, laps):
        """Verità dal DB: integrità a inizio stint = MAX wear tra i sample dello
        stint (il consumo cala, quindi il picco = uscita box). ~100% -> nuova.
        None se non disponibile."""
        if not laps:
            return None
        con = getattr(self._data, "con", None)
        if con is None:
            return None
        ids = [L.get("lap") for L in laps if L.get("lap") is not None]
        if not ids:
            return None
        cache = self.__dict__.setdefault("_stint_new_cache", {})
        ck = tuple(ids)
        if ck in cache:
            return cache[ck]
        qm = ",".join("?" * len(ids))
        try:
            rs = _rows(con, "SELECT MAX((tyre_w_fl+tyre_w_fr+tyre_w_rl+tyre_w_rr)/4.0) AS mw "
                            "FROM samples WHERE lap IN (%s) AND tyre_w_fl IS NOT NULL" % qm, ids)
        except Exception:
            return None
        if not rs or rs[0].get("mw") is None:
            cache[ck] = None
            return None
        res = rs[0]["mw"] >= 99.5
        cache[ck] = res
        return res

    def _stint_start_new4_from_samples(self, laps):
        """Come sopra ma PER GOMMA: [FL,FR,RL,RR] bool (MAX wear per ruota
        >=99.5 -> nuova). None se non disponibile."""
        if not laps:
            return None
        con = getattr(self._data, "con", None)
        if con is None:
            return None
        ids = [L.get("lap") for L in laps if L.get("lap") is not None]
        if not ids:
            return None
        cache = self.__dict__.setdefault("_stint_new4_cache", {})
        ck = tuple(ids)
        if ck in cache:
            return cache[ck]
        qm = ",".join("?" * len(ids))
        try:
            rs = _rows(con, "SELECT MAX(tyre_w_fl) a, MAX(tyre_w_fr) b, "
                            "MAX(tyre_w_rl) c, MAX(tyre_w_rr) d "
                            "FROM samples WHERE lap IN (%s) AND tyre_w_fl IS NOT NULL" % qm, ids)
        except Exception:
            return None
        if not rs or rs[0].get("a") is None:
            cache[ck] = None
            return None
        r0 = rs[0]
        res = [(r0["a"] or 0) >= 99.5, (r0["b"] or 0) >= 99.5,
               (r0["c"] or 0) >= 99.5, (r0["d"] or 0) >= 99.5]
        cache[ck] = res
        return res

    def _maybe_learn(self, ov):
        """A sessione ferma, aggiorna il profilo appreso pista+classe una sola
        volta per file (apprendimento sessione dopo sessione)."""
        rec = getattr(self, "_recorder", None)
        if rec and rec.is_armed():
            return                              # non in registrazione
        con = getattr(self, "_con", None)
        if con is None:
            return
        f = None
        if 0 <= getattr(self, "_cur_sess", -1) < len(getattr(self, "_sessions", [])):
            f = self._sessions[self._cur_sess].get("file")
        if not f:
            return
        seen = getattr(self, "_learned_files", None)
        if seen is None:
            seen = set(); self._learned_files = seen
        if f in seen:
            return
        seen.add(f)
        m = getattr(ov, "_meta", {}) or {}
        cls = getattr(self, "_car_class", "") or m.get("car_class", "")
        try:
            from core import engineer_learn as EL
            EL.update_from_session(con, m.get("track"), cls, energy_car=False)
        except Exception:
            pass

    def _sync_board(self):
        ov = getattr(self, "_overview", None)
        if ov is None or not hasattr(ov, "board"):
            return
        if not getattr(self, "_user_picked_session", False):
            if hasattr(ov, "set_empty"):
                ov.set_empty(True)
            return
        keys = getattr(self, "_stint_keys", [])
        ci = self.cmb_stint.currentIndex()
        cur_key = keys[ci] if 0 <= ci < len(keys) else None
        groups = getattr(self, "_groups", {})
        laps = groups.get(cur_key, []) if cur_key is not None else []
        m0 = getattr(ov, "_meta", {}) or {}
        has_meta = bool(m0.get("track") or m0.get("session_type") or m0.get("driver"))
        if (not keys) and (not laps) and (not has_meta):
            if hasattr(ov, "set_empty"):
                ov.set_empty(True)
            return
        if hasattr(ov, "set_empty"):
            ov.set_empty(False)
        best = _fastest_lap(laps) if laps else None
        sel, cmp_spec = self._cur_sel_cmp()
        ref = None      # costruito DOPO la risoluzione della condizione (vedi sotto)
        theo = None
        valid = [L for L in laps if not L.get("invalid")
                 and L.get("s1") and L.get("s2") and L.get("s3")]
        if valid:
            theo = (min(L["s1"] for L in valid) + min(L["s2"] for L in valid)
                    + min(L["s3"] for L in valid))
        cmp_lap = cmp_spec[1] if (cmp_spec and cmp_spec[0] == "lap") else None
        tyre4 = []
        m = getattr(ov, "_meta", {}) or {}
        c4 = (m.get("compounds4") or "").strip()
        if c4:
            tyre4 = [x.strip() for x in c4.split(",") if x.strip()]
        # condizione di riferimento = quella del GIRO SELEZIONATO (WET/DRY);
        # se nessun giro selezionato, fallback alla condizione media della sessione.
        _sel_L = next((L for L in laps if L["lap"] == sel), None) if sel else None
        _sel_cond = _sel_L.get("declared_wet") if _sel_L else None
        if _sel_cond is not None:
            _cond_wet = float(_sel_cond) >= 0.5
        else:
            # nessun giro selezionato: condizione = maggioranza dei giri VALIDI
            # (stessa logica dello stint). Evita il flicker DRY->WET al click,
            # perché non dipende dalla wetness media ancora non pronta.
            _wl = [L for L in laps
                   if L.get("declared_wet") is not None and not L.get("invalid")]
            if _wl:
                _nw = sum(1 for L in _wl if float(L["declared_wet"]) >= 0.5)
                _cond_wet = (_nw * 2) >= len(_wl)
            else:
                _cond_wet = float(m.get("wetness") or 0.0) > 0.10
        # LOGICA UNICA: il file REF viene (ri)caricato sulla STESSA condizione
        # dell'etichetta (_cond_wet). Se manca il REF di quella condizione la
        # card resta vuota — mai il tempo dell'altra condizione sotto l'etichetta.
        self._reload_ref_for_cond(m, 1.0 if _cond_wet else 0.0)
        if getattr(self, "_ref_available", False):
            _rs = _ov_session_label(self._data.ref_session)
            _rd = _date_human(self._data.ref_started)
            _rwhen = " \u00b7 ".join(p for p in (_rs, _rd)
                                    if p and p != "Session")
            ref = {"driver": self._data.ref_driver, "team": self._data.ref_team,
                   "vehicle": self._data.ref_vehicle, "time": self._data.ref_time,
                   "secs": self._data.ref_secs, "when": _rwhen,
                   "compounds4": self._data.ref_compounds4,
                   "tyre_state": self._data.ref_tyre_state,
                   "load_pct": self._data.ref_load_pct,
                   "load_kind": self._data.ref_load_kind,
                   "wear4": self._data.ref_wear4,
                   "fuel_l": self._data.ref_fuel_l,
                   "wet_pct": getattr(self._data, "ref_wet_pct", None),
                   "wet": bool(_cond_wet)}
        # ONLINE REF: best globale dal Worker (se configurato in settings/online.json).
        # Senza url/dati la card blue resta sui placeholder. Niente pace sul board.
        pace_info = {"kind": None, "sel": getattr(self, "_pace_sel", True)}
        board_pace = None
        try:
            from core import online as _online
            if _online.enabled():
                _online.load_async()
                _wet = _cond_wet
                _okey = _online.make_key(class_tag(m.get("car_class") or ""),
                                         _db._short_track(m.get("track") or ""), _wet)
                _row = _online.get_ref(_okey) if _okey else None
                if _row:
                    _lm = _row.get("lap_ms")
                    _s1 = _row.get("s1_ms"); _s2 = _row.get("s2_ms"); _s3 = _row.get("s3_ms")
                    _ld = _row.get("ve_pct")
                    if _ld is None:
                        _ld = _row.get("fuel_pct")
                    pace_info.update({
                        "online": True,
                        "player": _row.get("player"),
                        "team": _row.get("team"),
                        "car": _row.get("car"),
                        "compound": _row.get("compound"),
                        "compounds4": _row.get("compounds4"),
                        "tyre_state_pct": _row.get("tyre_state_pct"),
                        "load_pct": _ld,
                        "fuel_l": _row.get("fuel_l"),
                        "ref_time": (_lm / 1000.0) if _lm else None,
                        "secs": [(_s1 / 1000.0) if _s1 else None,
                                 (_s2 / 1000.0) if _s2 else None,
                                 (_s3 / 1000.0) if _s3 else None],
                    })
        except Exception:
            pass
        # dedup: se l'ONLINE coincide col LOCAL (stesso tempo + stesso pilota),
        # mostra solo LOCAL (togli la card online).
        if pace_info.get("online") and ref and ref.get("time") and pace_info.get("ref_time"):
            _same_t = abs(float(ref["time"]) - float(pace_info["ref_time"])) < 0.02
            _same_d = (str(pace_info.get("player") or "").strip().lower()
                       == str(ref.get("driver") or "").strip().lower())
            if _same_t and _same_d:
                pace_info.pop("online", None)
        # gap blu sul giro migliore quando la card ONLINE REF e selezionata
        if (pace_info.get("online") and pace_info.get("sel")
                and pace_info.get("ref_time") and best):
            _bL = next((L for L in laps if L["lap"] == best), None)
            _blt = (_bL.get("lap_time") if _bL else None) or 0
            if _blt > 0:
                board_pace = {"kind": "online",
                              "label": pace_info.get("player") or "ONLINE",
                              "gap": _blt - pace_info["ref_time"],
                              "color": "#4aa3df"}
        stint_new = {}
        stint_new4 = {}
        stint_comp4 = {}
        for k in keys:
            lk = groups.get(k, [])
            v = self._stint_start_new_from_samples(lk)
            if v is None and lk:
                v = ov.board._stint_started_new(lk)
            stint_new[k] = True if v is None else bool(v)
            stint_new4[k] = self._stint_start_new4_from_samples(lk)
            # mescola dello stint = quella montata, costante per tutto lo stint:
            # la leggo diretta dal primo giro che ce l'ha.
            stint_comp4[k] = next(
                ((L.get("compounds4") or "").strip() for L in lk
                 if (L.get("compounds4") or "").strip()), "")
        _rec = getattr(self, "_recorder", None)
        # LIVE (auto-scroll + riga in corso + giro corrente bloccato) SOLO quando sei
        # davvero in pista a registrare. Al garage/in attesa (armato ma non scrive) il
        # board torna in review piena: nessun auto-scroll, tutti i giri selezionabili.
        ov.board._live = bool(_rec) and _rec.is_recording()
        _team_view = getattr(self, "_viewing_team", False)
        if not _team_view:
            try:
                self._maybe_learn(ov)        # team: nessun learning
            except Exception:
                pass
        ov.board.update_board(keys, cur_key, laps, best, sel, cmp_lap, tyre4, pace=board_pace, stint_new=stint_new, stint_new4=stint_new4, stint_comp4=stint_comp4, session_type=m.get("session_type"), car_class=m.get("car_class"))
        if not _team_view:
            # team: REF/online congelati sui tuoi (non ricostruire le card)
            ov.set_ref(ref, cmp_spec == ("ref",), theo, self._board_pick,
                       pace=pace_info, wet=_cond_wet)
            self._upload_ref_online(ref, m)        # carica il best personale sul Worker

    def _reload_ref_for_cond(self, m, condval):
        """LOGICA UNICA della condizione REF: file ed etichetta derivano
        SEMPRE dallo stesso valore (quello passato qui, gia' risolto a monte:
        giro selezionato -> maggioranza giri -> wetness). Ricarica il file
        solo se la condizione e' cambiata. Se il REF di quella condizione
        NON esiste, la card resta vuota: MAI il fallback sull'altra
        condizione (era la causa dell'etichetta WET col tempo fatto in dry)."""
        try:
            want = 1.0 if (condval is not None and float(condval) >= 0.5) else 0.0
        except (TypeError, ValueError):
            want = 0.0
        if (getattr(self, "_ref_cond_loaded", None) == want
                and getattr(self, "_ref_available", False)):
            return
        try:
            path = _db.ref_path_for(m.get("car_class"), m.get("track"), want)
            ok = bool(path) and self._data.load_reference(str(path))
        except Exception:
            ok = False
        self._ref_available = ok
        self._ref_cond_loaded = want if ok else None
        try:
            self._data.ref_wet = bool(ok and want >= 0.5)
            if not ok:
                self._data.clear_reference()
        except Exception:
            pass

    def _upload_ref_online(self, ref, m):
        """Manda il best personale alla classifica online (Cloudflare Worker).
        Degrada in modo sicuro se online non è configurato (url/token mancanti).
        Stesso formato chiave della classifica: CLASSE_TRACK_METEO. Dedup per run."""
        try:
            from core import online as _online
            if not (_online.enabled() and ref and ref.get("time")):
                return
            from core.classes import class_tag as _ctag
            # condizione = quella per cui il REF e' stato caricato (la card
            # e la chiave online NON possono divergere). Fallback: wetness.
            _wet = ref.get("wet")
            if _wet is None:
                _wet = float((m or {}).get("wetness") or 0.0) > 0.10
            _wet = bool(_wet)
            key = _online.make_key(_ctag((m or {}).get("car_class") or ""),
                                   _db._short_track((m or {}).get("track") or ""), _wet)
            if not key:
                return
            lap_ms = int(round(ref["time"] * 1000))
            sig = (key, lap_ms)
            up = getattr(self, "_uploaded_online", None)
            if up is None:
                up = self._uploaded_online = set()
            if sig in up:
                return
            secs = ref.get("secs") or [None, None, None]
            def _ms(x): return int(round(x * 1000)) if x else None
            player = (ref.get("driver") or _load_profile().get("driver") or "").strip()
            rec = {
                "key": key, "lap_ms": lap_ms,
                "player": player or "anon",
                "team": get_team() or ref.get("team") or "",
                "car": ref.get("vehicle") or "",
                "s1_ms": _ms(secs[0]), "s2_ms": _ms(secs[1]), "s3_ms": _ms(secs[2]),
                "compounds4": ref.get("compounds4") or "",
                "tyre_state_pct": ref.get("tyre_state"),
                "fuel_l": ref.get("fuel_l"),
                # livrea casco scelta: il Worker la salva col record e le
                # classifiche la mostrano accanto al nome
                "helmet": _load_profile().get("helmet_color", "#fd160e"),
            }
            if (ref.get("load_kind") or "").upper() == "VE":
                rec["ve_pct"] = ref.get("load_pct")
            else:
                rec["fuel_pct"] = ref.get("load_pct")
            _online.submit_async(rec)
            up.add(sig)
        except Exception:
            pass

    def _live_refresh(self):
        """Aggiorna la Review durante la sessione: nuove sessioni/giri appena
        registrati, preservando la selezione (sessione/stint/giro/compare)."""
        if self.stack.currentIndex() != 0:
            return                                   # solo quando la Review è visibile
        # replay mappa in corso: NON interrompere il play con la ricostruzione
        # delle liste (il tick da 8s riprova; appena in pausa il refresh passa)
        _ws = getattr(self, "_worksheet", None)
        _rp = getattr(_ws, "_rp_timer", None) if _ws is not None else None
        if _rp is not None and _rp.isActive():
            return
        rec = getattr(self, "_recorder", None)
        armed_now = bool(rec) and rec.is_armed()
        if armed_now and not getattr(self, "_was_armed_live", False):
            self._live_jump_pending = True         # sessione in pista appena avviata
        if not armed_now:
            self._live_jump_pending = False
        self._was_armed_live = armed_now
        if not armed_now:
            return                       # a riposo la lista sessioni non cambia
        live_file = rec.current_file() if (rec and armed_now) else None
        cur_file = None
        si = self._cur_sess
        if 0 <= si < len(self._sessions):
            cur_file = self._sessions[si]["file"]
        cur_stint = self.cmb_stint.currentIndex()
        li = self.cmb_lap.currentIndex()
        keep_lap = self._lap_ids[li] if 0 <= li < len(self._lap_ids) else None
        ci = self.cmb_cmp.currentIndex()
        keep_cmp = self._cmp_ids[ci - 1] if 1 <= ci <= len(self._cmp_ids) else None

        sessions_all = _db.list_sessions()
        import os as _os
        _lfn = _os.path.basename(live_file) if live_file else None
        live_sess = (next((s for s in sessions_all
                           if _os.path.basename(s.get("file") or "") == _lfn), None)
                     if _lfn else None)
        # la sessione live appena creata può essere letta senza pista (metadati non
        # ancora flushati): prendila dal recorder, così titolo/card/filtro la
        # riconoscono subito invece di mostrare il nome-file.
        if live_sess is not None and not (live_sess.get("track") or "").strip():
            try:
                _lt = rec.current_track()
                if _lt:
                    live_sess["track"] = _lt
            except Exception:
                pass
        # JUMP in sospeso ma la sessione in registrazione non è ancora pronta
        # (file appena creato, non ancora nella lista): NON toccare la Review,
        # altrimenti il focus finisce su una vecchia sessione (e il filtro
        # circuito resta su quella sbagliata). Aspetta il prossimo giro.
        if getattr(self, "_live_jump_pending", False) and live_sess is None:
            return
        # registrazione appena avviata su una pista diversa da quella filtrata:
        # cambia il filtro circuito sulla nuova pista (es. ero su Monza -> nuova)
        if getattr(self, "_live_jump_pending", False) and live_sess is not None:
            live_stem = _track_logo_stem(live_sess.get("track")) or "Other"
            if getattr(self, "_track_filter", None) != live_stem:
                self._track_filter = live_stem
            self._layout_filter = _track_layout_key(live_sess.get("track"))  # layout attivo
        # applica il filtro circuito corrente (coerente con _reload_sessions)
        tf = getattr(self, "_track_filter", None)
        if tf == "Other":
            sessions = [s for s in sessions_all if _track_logo_stem(s.get("track")) is None]
        elif tf:
            sessions = [s for s in sessions_all if _track_logo_stem(s.get("track")) == tf]
        else:
            sessions = sessions_all
        # filtro LAYOUT (coerente con _reload_sessions / menu): durante il live
        # mostra solo il layout della sessione attiva, non entrambi.
        _lf = getattr(self, "_layout_filter", None)
        if _lf:
            sessions = [s for s in sessions
                        if _track_layout_key(s.get("track")) == _lf]
        self._sessions = sessions
        live_idx = (next((i for i, s in enumerate(sessions)
                          if _os.path.basename(s.get("file") or "") == _lfn), None)
                    if _lfn else None)
        if getattr(self, "_live_jump_pending", False) and live_idx is not None:
            sel_idx = live_idx                     # salta sulla sessione in registrazione
            cur_file = live_file
            cur_stint = 0; keep_lap = None; keep_cmp = None   # niente residui
            self._live_jump_pending = False
            self._user_picked_session = True        # in registrazione il pannello si mostra
        else:
            sel_idx = 0
            for i, s in enumerate(sessions):
                if cur_file and s["file"] == cur_file:
                    sel_idx = i
        self._cur_sess = sel_idx if sessions else -1
        if getattr(self, "_overview", None) is not None:
            self._overview.set_sessions(sessions, self._cur_sess,
                                        self._select_session, self._delete_session,
                                        self._open_session_folder, self._export_session)
        if not sessions:
            self._close_con(); self._fill_stints({}); return

        # riapre la connessione per vedere i giri appena committati dal recorder
        self._close_con()
        try:
            self._con = sqlite3.connect(sessions[sel_idx]["file"])
            meta = _rows(self._con, "SELECT car_class FROM session_meta WHERE id=1")
            self._car_class = (meta[0]["car_class"] if meta else "") or ""
        except Exception:
            self._con = None
            self._fill_stints({}); return
        self._data.set_con(self._con)
        self._data.car_class = self._car_class
        self._autopick_reference()
        for v in self._graph_views:
            v.con = self._con
        laps = _rows(self._con, "SELECT * FROM laps ORDER BY lap")
        groups = {}
        if laps:
            base = min((L["stint"] or 1) for L in laps)
            for L in laps:
                groups.setdefault((L["stint"] or 1) - base + 1, []).append(L)
        # follow-stint: se in live (sessione attiva, la più recente) compare un nuovo
        # stint e si stava guardando l'ultimo, passa automaticamente al nuovo.
        keys = sorted(groups)
        auto_idx = cur_stint
        prev_file = getattr(self, "_live_stint_file", None)
        prev_cnt = getattr(self, "_live_stint_count", 0)
        if prev_file != cur_file:
            prev_cnt = 0                              # nuova sessione: reset
        if (sel_idx == 0 and prev_cnt > 0 and len(keys) > prev_cnt
                and cur_stint == prev_cnt - 1):
            auto_idx = len(keys) - 1                  # segui il nuovo stint
        self._live_stint_count = len(keys)
        self._live_stint_file = cur_file
        self._fill_stints(groups, keep_idx=auto_idx,
                          keep_lap_id=keep_lap, keep_cmp_id=keep_cmp)

    def _delete_session(self, idx=None):
        if idx is None or idx is False:
            idx = self._cur_sess
        if not (0 <= idx < len(self._sessions)):
            return
        s = self._sessions[idx]
        r = QMessageBox.question(
            self, "Delete session",
            "Permanently delete this telemetry?\n\n" + s.get("name", ""),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        self._close_con()
        err = None
        for suffix in ("-wal", "-shm", ""):      # sidecar prima, file principale per ultimo
            p = s["file"] + suffix
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError as e:
                if suffix == "":
                    err = e
        if os.path.exists(s["file"]):
            QMessageBox.warning(
                self, "Delete session",
                "Could not delete the file. It is probably in use by an "
                "active recording (stop the on-track session and try again).\n\n"
                + (str(err) if err else s["file"]))
            return
        self._reload_sessions()

    def closeEvent(self, e):
        if getattr(self, "_overlaytab", None) is not None:
            try:
                self._overlaytab.stop_all()
            except Exception:
                pass
        if getattr(self, "_overview", None) is not None:
            try:
                self._overview.stop()
            except Exception:
                pass
        if getattr(self, "_recorder", None) is not None:
            try:
                self._recorder.stop()
            except Exception:
                pass
        eng = getattr(self, "_engineer", None)
        if eng is not None and getattr(eng, "_ov", None) is not None:
            try:
                eng._ov.close()
            except Exception:
                pass
        self._close_con()
        try:
            self._data.clear_reference()
        except Exception:
            pass
        super().closeEvent(e)


# ─────────────────────────────────────────────────────────────────────────────
#  TelemetryWindow — canvas vuoto. Le pagine si montano a mano, un pezzo alla
#  volta. Tutte le funzionalita' esistenti restano disponibili nelle classi
#  widget qui sopra e in _LegacyWindow (riserva pezzi: recorder, timer, wiring
#  telemetria intatti), pronte da rimontare.
# ─────────────────────────────────────────────────────────────────────────────
_TRACKS = [
    # (key base foto/rotazione, key foto dedicata, nome, logo, mappa-svg)
    ("bahrain",     "bahrain",            "Bahrain",            "Bahrain",     "Bahrain International Circuit.svg"),
    ("bahrain",     "bahrain_endurance",  "Bahrain Endurance",  "Bahrain",     "Bahrain Endurance Circuit.svg"),
    ("bahrain",     "bahrain_outer",      "Bahrain Outer",      "Bahrain",     "Bahrain Outer Circuit.svg"),
    ("bahrain",     "bahrain_paddock",    "Bahrain Paddock",    "Bahrain",     "Bahrain Paddock Circuit.svg"),
    ("barcelona",   "barcelona",          "Barcelona",          "Barcelona",   "Circuit de Barcelona.svg"),
    ("cota",        "cota",               "COTA",               "COTA",        "Circuit of the Americas.svg"),
    ("cota",        "cota_national",      "COTA National",      "COTA",        "Circuit of the Americas National.svg"),
    ("fuji",        "fuji",               "Fuji",               "Fuji",        "Fuji Speedway.svg"),
    ("fuji",        "fuji_classic",       "Fuji Classic",       "Fuji",        "Fuji Speedway Classic.svg"),
    ("imola",       "imola",              "Imola",              "Imola",       "Autodromo Enzo e Dino Ferrari.svg"),
    ("interlagos",  "interlagos",         "Interlagos",         "Interlagos",  "Aut#U00f3dromo Jos#U00e9 Carlos Pace.svg"),
    ("lemans",      "lemans",             "Le Mans",            "LeMans",      "Circuit de la Sarthe.svg"),
    ("lemans",      "lemans_mulsanne",    "Le Mans Mulsanne",   "LeMans",      "Circuit de la Sarthe Mulsanne.svg"),
    ("lusail",      "lusail",             "Lusail",             "Lusail",      "Lusail International Circuit.svg"),
    ("lusail",      "lusail_short",       "Lusail Short",       "Lusail",      "Lusail Short Circuit.svg"),
    ("monza",       "monza",              "Monza",              "Monza",       "Autodromo Nazionale Monza.svg"),
    ("monza",       "monza_curva_grande", "Monza Curva Grande", "Monza",       "Monza Curva Grande Circuit.svg"),
    ("paulricard",  "paulricard",         "Paul Ricard",        "PaulRicard",  "Paul Ricard - ELMS.svg"),
    ("paulricard",  "paulricard_1a",      "Paul Ricard 1A",     "PaulRicard",  "Paul Ricard - 1A.svg"),
    ("paulricard",  "paulricard_1a_v2",   "Paul Ricard 1A-V2",  "PaulRicard",  "Paul Ricard - 1A-V2.svg"),
    ("paulricard",  "paulricard_1a_v2_short","Paul Ricard 1A-V2 Short","PaulRicard","Paul Ricard - 1A-V2-Short.svg"),
    ("paulricard",  "paulricard_3a",      "Paul Ricard 3A",     "PaulRicard",  "Paul Ricard - 3A.svg"),
    ("portimao",    "portimao",           "Portim\u00e3o",      "Portimao",    "Algarve International Circuit.svg"),
    ("sebring",     "sebring",            "Sebring",            "Sebring",     "Sebring International Raceway.svg"),
    ("sebring",     "sebring_school",     "Sebring School",     "Sebring",     "Sebring School Circuit.svg"),
    ("silverstone", "silverstone",        "Silverstone",        "Silverstone", "Silverstone Grand Prix Circuit - ELMS.svg"),
    ("silverstone", "silverstone_international","Silverstone International","Silverstone","Silverstone International Circuit.svg"),
    ("silverstone", "silverstone_national","Silverstone National","Silverstone", "Silverstone National Circuit.svg"),
    ("spa",         "spa",                "Spa",                "Spa",         "Circuit de Spa-Francorchamps.svg"),
    ("spa",         "spa_endurance",      "Spa Endurance",      "Spa",         "Circuit de Spa-Francorchamps Endurance.svg"),
    # ── US TRACK PASS (anteprima): Daytona e Laguna Seca confermati con la
    #    1.4; Watkins Glen, Road Atlanta, Indianapolis e Long Beach dal
    #    teaser del 4 luglio. Gli SVG delle mappe arriveranno con le piste;
    #    card, loghi e overview sono gia' pronti. ──
    ("daytona",      "daytona",      "Daytona",       "Daytona",      "Daytona International Speedway.svg"),
    ("lagunaseca",   "lagunaseca",   "Laguna Seca",   "LagunaSeca",   "WeatherTech Raceway Laguna Seca.svg"),
    ("watkinsglen",  "watkinsglen",  "Watkins Glen",  "WatkinsGlen",  "Watkins Glen International.svg"),
    ("roadatlanta",  "roadatlanta",  "Road Atlanta",  "RoadAtlanta",  "Michelin Raceway Road Atlanta.svg"),
    ("indianapolis", "indianapolis", "Indianapolis",  "Indianapolis", "Indianapolis Motor Speedway.svg"),
    ("longbeach",    "longbeach",    "Long Beach",    "LongBeach",    "Long Beach Street Circuit.svg"),
]


_MAP_ROTATION = {   # gradi orari per la mappa-circuito di certe piste
    "fuji": 90,
}

# ROTAZIONI STILIZZATE (rich. 24/07 sera): angoli salvati dall'utente
# col tool tools/gira_stilizzate.py — le card erano "orientate alla
# cazzo". Chiave = stem SVG decodificato; vince sul vecchio
# _MAP_ROTATION. Cache con controllo mtime (il tool scrive a parte).
_STYL_ROT_FP = (Path(__file__).resolve().parent.parent / "settings"
                / "stylized_rotations.json")
_styl_rot_cache = [None, 0.0]     # (dict, mtime)


def _styl_rot9(cmap, base=""):
    try:
        import re as _r
        stem = _r.sub(r"#U([0-9a-fA-F]{4})",
                      lambda m: chr(int(m.group(1), 16)),
                      str(cmap or "").rsplit(".", 1)[0])
        try:
            mt = _STYL_ROT_FP.stat().st_mtime
        except OSError:
            mt = 0.0
        if _styl_rot_cache[0] is None or _styl_rot_cache[1] != mt:
            try:
                import json as _j
                _styl_rot_cache[0] = _j.loads(
                    _STYL_ROT_FP.read_text(encoding="utf-8"))
            except Exception:
                _styl_rot_cache[0] = {}
            _styl_rot_cache[1] = mt
        v = _styl_rot_cache[0].get(stem)
        if v is not None:
            return float(v)
    except Exception:
        pass
    return float(_MAP_ROTATION.get(base or "", 0))


def _draw_card_lock9(p, w, h, radius=13):
    """Velo scuro + LUCCHETTO rosso (stessa grafica della sessione
    bloccata: glifo 'lock' Material Icons, #ff4d5a) sopra una card —
    piste IMSA chiuse finche' non le finiamo (rich. 24/07)."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QFont, QPainterPath
    r = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
    clip = QPainterPath()
    clip.addRoundedRect(r, radius, radius)
    p.save()
    p.setClipPath(clip)
    p.fillRect(r, QColor(6, 8, 14, 205))          # velo scuro
    f = QFont("Material Icons")
    f.setPixelSize(max(26, int(min(w, h) * 0.26)))
    p.setFont(f)
    p.setPen(QColor(255, 77, 90))                 # #ff4d5a
    p.drawText(r, Qt.AlignCenter, chr(0xE897))    # glifo 'lock'
    p.restore()


class _Card(QFrame):
    """Carta-pista a forma di carta da gioco. Sfondo da assets/trackcards/<key>.jpg
    (fallback bianco), nome pista in basso, angoli arrotondati. Cliccabile:
    chiama on_click(idx). setSelected() evidenzia la carta a fuoco."""
    RADIUS = 13
    ZOOM_REST = 1.12   # zoom a riposo; in hover scende a 1.0 (zoom out)
    _DIR = Path(__file__).resolve().parent.parent / "assets" / "trackcards"

    def __init__(self, track=None, bgkey=None, name=None, logo=None, cmap=None, idx=-1, parent=None,
                 show_name=True, cat=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        self._idx = idx
        self._name = (name.upper() if name else name) if show_name else None
        self.on_click = None
        self._selected = False
        self._hover = 0.0          # progresso hover 0..1 (per il fade)
        self._hover_t = 0.0        # target hover
        self._htimer = QTimer(self)
        self._htimer.setInterval(16)
        self._htimer.timeout.connect(self._htick)
        self._bg = self._load(bgkey)          # solo foto dedicata, niente fallback
        self._logo = self._load_logo(logo)
        self._cat = cat
        self._locked = (cat == "imsa")   # IMSA chiusa (rich. 24/07)
        self._map = self._load_map(cmap)
        self._map_rot = _styl_rot9(cmap, track)   # angolo salvato dal tool
        self._op = QGraphicsOpacityEffect(self)
        self._op.setOpacity(1.0)
        self.setGraphicsEffect(self._op)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def _load(self, *keys):
        for k in keys:
            if not k:
                continue
            for ext in ("jpg", "jpeg", "png", "webp"):
                p = self._DIR / f"{k}.{ext}"
                if p.exists():
                    pm = QPixmap(str(p))
                    if not pm.isNull():
                        return pm
        return None

    def _load_logo(self, logo):
        if not logo or QSvgRenderer is None:
            return None
        p = _OV_TRACKLOGO_DIR / f"{logo}.svg"
        if not p.exists():
            return None
        r = QSvgRenderer(str(p))
        return r if r.isValid() else None

    def _load_map(self, cmap):
        if not cmap or QSvgRenderer is None:
            return None
        p = _OV_TRACKMAPS_SVG_DIR / cmap
        if not p.exists():
            return None
        r = QSvgRenderer(str(p))
        return r if r.isValid() else None

    def setSelected(self, on):
        if on != self._selected:
            self._selected = on
            self.update()

    def setOpacityF(self, v):
        self._op.setOpacity(max(0.0, min(1.0, v)))

    def mousePressEvent(self, e):
        if getattr(self, "_locked", False):
            e.accept()
            return                       # pista IMSA bloccata: click morto
        if e.button() == Qt.LeftButton and self.on_click and self._idx >= 0:
            self.on_click(self._idx)
            e.accept()

    # ── hover: fade rosso + zoom out ──
    def enterEvent(self, e):
        self._hover_t = 1.0
        if not self._htimer.isActive():
            self._htimer.start()

    def leaveEvent(self, e):
        self._hover_t = 0.0
        if not self._htimer.isActive():
            self._htimer.start()

    def _htick(self):
        self._hover += (self._hover_t - self._hover) * 0.10   # più lento
        if abs(self._hover_t - self._hover) < 0.004:
            self._hover = self._hover_t
            self._htimer.stop()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self.RADIUS, self.RADIUS)
        p.setClipPath(path)
        # sfondo (con zoom: a riposo ingrandito, in hover fa zoom out verso il fill)
        hs = self._hover * self._hover * (3.0 - 2.0 * self._hover)   # smoothstep: morbido
        if self._bg is not None and not self._bg.isNull():
            z = self.ZOOM_REST + (1.0 - self.ZOOM_REST) * hs
            sc = self._bg.scaled(QSize(int(self.width() * z), int(self.height() * z)),
                                 Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            p.drawPixmap(-(sc.width() - self.width()) // 2,
                         -(sc.height() - self.height()) // 2, sc)
        else:
            p.fillRect(self.rect(), QColor(255, 255, 255, 240))
        # velo rosso in dissolvenza sull'hover (sopra la foto)
        if self._hover > 0.0:
            p.fillRect(self.rect(), QColor(255, 29, 67, int(178 * hs)))
        # nome pista su gradiente scuro — svanisce in hover (stesso hs dello zoom)
        if self._name:
            h = self.height()
            band = max(28, int(h * 0.30))
            _nf = 1.0 - hs
            g = QLinearGradient(0, h - band, 0, h)
            g.setColorAt(0.0, QColor(0, 0, 0, 0))
            g.setColorAt(1.0, QColor(0, 0, 0, int(185 * _nf)))
            p.fillRect(0, h - band, self.width(), band, QBrush(g))
            from PySide6.QtGui import QFontMetrics
            f = QFont("Archivo SemiExpanded")
            f.setWeight(QFont.Medium)
            avail = self.width() - 16
            size = max(11, int(self.width() * 0.115))
            while size > 9:
                f.setPixelSize(size)
                if QFontMetrics(f).horizontalAdvance(self._name) <= avail:
                    break
                size -= 1
            p.setFont(f)
            p.setPen(QColor(255, 255, 255, int(255 * _nf)))
            p.drawText(QRectF(8, h - band, self.width() - 16, band - 8),
                       Qt.AlignHCenter | Qt.AlignBottom, self._name)
        # linee nell'angolo basso-destra: fuori a riposo, entrano in hover (stesso hs)
        if hs > 0.001:
            try:
                from PySide6.QtSvg import QSvgRenderer
                _sz = self.width() * 0.5
                _off = _sz * (1.0 - hs)            # offset: fuori -> in posizione
                p.setOpacity(hs)
                QSvgRenderer(QByteArray(_MenuHeader._CORNER_SVG)).render(
                    p, QRectF(self.width() - _sz + _off,
                              self.height() - _sz + _off, _sz, _sz))
                p.setOpacity(1.0)
            except Exception:
                pass
        # overlay hover (sopra a tutto): logo in alto + mappa circuito bianca sotto
        if self._hover > 0.0:
            W, H = self.width(), self.height()
            p.setOpacity(hs)
            # logo, spostato più in alto
            if self._logo is not None:
                ds = self._logo.defaultSize()
                if ds.width() > 0 and ds.height() > 0:
                    ar = ds.width() / ds.height()
                    lw = W * 0.55
                    lh = lw / ar
                    cap = H * 0.24
                    if lh > cap:
                        lh = cap
                        lw = lh * ar
                    self._logo.render(p, QRectF((W - lw) / 2.0, H * 0.09, lw, lh))
            # mappa circuito (colori originali), sotto al logo, con rotazione opzionale
            if self._map is not None:
                ds = self._map.defaultSize()
                if ds.width() > 0 and ds.height() > 0:
                    # angolo LIBERO (tool gira_stilizzate): fit sul
                    # bounding box ruotato, niente piu' scatti 90
                    rot = float(self._map_rot or 0.0)
                    _aw, _ah = float(ds.width()), float(ds.height())
                    _th = math.radians(rot)
                    _bw = abs(_aw * math.cos(_th)) \
                        + abs(_ah * math.sin(_th))
                    _bh = abs(_aw * math.sin(_th)) \
                        + abs(_ah * math.cos(_th))
                    _s = min(W * 0.78 / max(1.0, _bw),
                             H * 0.34 / max(1.0, _bh))
                    _mh = _bh * _s
                    p.save()
                    p.translate(W / 2.0, H * 0.40 + _mh / 2.0)
                    if rot:
                        p.rotate(rot)
                    self._map.render(p, QRectF(-_aw * _s / 2.0,
                                               -_ah * _s / 2.0,
                                               _aw * _s, _ah * _s))
                    p.restore()
            p.setOpacity(1.0)
        # bordo bianco rimosso
        if getattr(self, "_locked", False):
            _draw_card_lock9(p, self.width(), self.height(), self.RADIUS)
        p.setClipping(False)




class _PartnersBar(QWidget):
    """Strip partner (assets/partners.svg) centrata: sotto le card, sopra
    il footer. Solo estetica, nessuna interazione."""
    H = 84

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.H)
        self._r = None
        if QSvgRenderer is not None:
            _p = Path(__file__).resolve().parent.parent / "assets" / "partners.svg"
            if _p.exists():
                r = QSvgRenderer(str(_p))
                self._r = r if r.isValid() else None
        if self._r is None:
            self.hide()

    def paintEvent(self, e):
        if self._r is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        ds = self._r.defaultSize()
        if ds.width() <= 0 or ds.height() <= 0:
            return
        ar = ds.width() / ds.height()
        h = self.height() - 8
        w = h * ar
        maxw = self.width() * 0.96
        if w > maxw:
            w = maxw
            h = w / ar
        self._r.render(p, QRectF((self.width() - w) / 2.0,
                                 (self.height() - h) / 2.0, w, h))


class _CatCard(QFrame):
    """Card di categoria (WEC / ELMS / IMSA): logo serie centrato,
    velo rosso e zoom-out in hover come le card pista."""
    RADIUS = 13

    # colore del velo hover per serie: WEC blu notte, ELMS arancio, IMSA rosso
    _HOVER = {
        "wec":  QColor(10, 0, 50, 215),     # #0a0032 (scuro: alpha piu' alto)
        "elms": QColor(255, 95, 0, 150),    # #ff5f00
        "imsa": QColor(255, 29, 67, 150),   # rosso come le card pista
    }

    def __init__(self, key, on_click=None, parent=None):
        super().__init__(parent)
        self._key = key
        self.on_click = on_click
        self._hover = 0.0
        self._hover_t = 0.0
        self._htimer = QTimer(self)
        self._htimer.setInterval(16)
        self._htimer.timeout.connect(self._htick)
        self._logo = None
        if QSvgRenderer is not None:
            _p = Path(__file__).resolve().parent.parent / "assets" / f"{key}.svg"
            if _p.exists():
                r = QSvgRenderer(str(_p))
                self._logo = r if r.isValid() else None
        # foto card categoria (se presente): assets/catcards/<key>.jpg|png|webp
        self._photo = None
        _cdir = Path(__file__).resolve().parent.parent / "assets" / "catcards"
        for _ext in ("jpg", "jpeg", "png", "webp"):
            _fp = _cdir / f"{key}.{_ext}"
            if _fp.exists():
                _pm = QPixmap(str(_fp))
                if not _pm.isNull():
                    self._photo = _pm
                    break
        # IMSA CHIUSA (rich. 24/07): piste da finire a mano prima
        # dell'update — card bloccata col lucchetto della sessione
        self._locked = (key == "imsa")
        self.setCursor(Qt.ForbiddenCursor if self._locked
                       else Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def enterEvent(self, e):
        self._hover_t = 1.0
        if not self._htimer.isActive():
            self._htimer.start()

    def leaveEvent(self, e):
        self._hover_t = 0.0
        if not self._htimer.isActive():
            self._htimer.start()

    def _htick(self):
        self._hover += (self._hover_t - self._hover) * 0.12
        if abs(self._hover_t - self._hover) < 0.004:
            self._hover = self._hover_t
            self._htimer.stop()
        self.update()

    def mousePressEvent(self, e):
        if getattr(self, "_locked", False):
            e.accept()
            return                       # IMSA bloccata: click morto
        if e.button() == Qt.LeftButton and self.on_click:
            self.on_click(self._key)
            e.accept()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self.RADIUS, self.RADIUS)
        p.setClipPath(path)
        hs = self._hover * self._hover * (3.0 - 2.0 * self._hover)
        # fondo scuro con velo del brand in hover
        p.fillRect(self.rect(), QColor(10, 16, 46, 235))
        # foto categoria (assets/catcards/<key>.*): STESSO taglio delle card
        # pista (crop centrato + zoom a riposo, zoom-out in hover)
        if getattr(self, "_photo", None) is not None:
            _z = 1.12 + (1.0 - 1.12) * hs
            sc = self._photo.scaled(
                QSize(int(self.width() * _z), int(self.height() * _z)),
                Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.drawPixmap(-(sc.width() - self.width()) // 2,
                         -(sc.height() - self.height()) // 2, sc)
        if hs > 0.0:
            _hc = self._HOVER.get(self._key, QColor(255, 29, 67, 150))
            p.fillRect(self.rect(), QColor(_hc.red(), _hc.green(), _hc.blue(),
                                           int(_hc.alpha() * hs)))
        # linee nell'angolo basso-destra: fuori a riposo, entrano in hover
        # (STESSA entrata delle card circuito)
        if hs > 0.001:
            try:
                from PySide6.QtSvg import QSvgRenderer as _QSR
                _sz = self.width() * 0.5
                _off = _sz * (1.0 - hs)
                p.setOpacity(hs)
                _QSR(QByteArray(_MenuHeader._CORNER_SVG)).render(
                    p, QRectF(self.width() - _sz + _off,
                              self.height() - _sz + _off, _sz, _sz))
                p.setOpacity(1.0)
            except Exception:
                pass
        # bordo sottile
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 40 + int(120 * hs)), 1.4))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, self.RADIUS, self.RADIUS)
        p.setClipPath(path)
        # nome serie in basso su gradiente scuro — svanisce in hover (come _Card)
        _nm = (self._key or "").upper()
        if _nm:
            h = self.height()
            band = max(28, int(h * 0.30))
            _nf = 1.0 - hs
            g = QLinearGradient(0, h - band, 0, h)
            g.setColorAt(0.0, QColor(0, 0, 0, 0))
            g.setColorAt(1.0, QColor(0, 0, 0, int(185 * _nf)))
            p.fillRect(0, h - band, self.width(), band, QBrush(g))
            f = QFont("Archivo SemiExpanded")
            f.setWeight(QFont.Medium)
            f.setPixelSize(max(11, int(self.width() * 0.115)))
            p.setFont(f)
            p.setPen(QColor(255, 255, 255, int(255 * _nf)))
            p.drawText(QRectF(8, h - band, self.width() - 16, band - 8),
                       Qt.AlignHCenter | Qt.AlignBottom, _nm)
        # logo serie centrato: COMPARE in hover
        if self._logo is not None and hs > 0.001:
            ds = self._logo.defaultSize()
            if ds.width() > 0 and ds.height() > 0:
                ar = ds.width() / ds.height()
                W, H = self.width(), self.height()
                lw = W * (0.52 + 0.05 * hs)
                lh = lw / ar
                cap = H * 0.42
                if lh > cap:
                    lh = cap
                    lw = lh * ar
                p.setOpacity(hs)
                self._logo.render(p, QRectF((W - lw) / 2.0, (H - lh) / 2.0, lw, lh))
                p.setOpacity(1.0)
        if getattr(self, "_locked", False):
            _draw_card_lock9(p, self.width(), self.height(), self.RADIUS)
        p.setClipping(False)


class _CatRow(QWidget):
    """Le tre card categoria affiancate a PROPORZIONE FISSA (carta da gioco,
    come le card pista): mai stirate, sempre centrate nello spazio."""
    RATIO = 1.4       # altezza / larghezza (stesso delle card pista)
    GAP = 18
    MARGIN = 24

    def __init__(self, keys, on_click=None, parent=None):
        super().__init__(parent)
        self._cards = [_CatCard(k, on_click=on_click, parent=self) for k in keys]

    def resizeEvent(self, e):
        super().resizeEvent(e)
        n = len(self._cards)
        availW = max(1, self.width() - 2 * self.MARGIN - (n - 1) * self.GAP)
        availH = max(1, self.height() - 2 * self.MARGIN)
        cw = availW / n
        ch = cw * self.RATIO
        if ch > availH:
            ch = availH
            cw = ch / self.RATIO
        total = n * cw + (n - 1) * self.GAP
        x0 = (self.width() - total) / 2.0
        y0 = (self.height() - ch) / 2.0
        for i, c in enumerate(self._cards):
            c.setFixedSize(int(cw), int(ch))
            c.move(int(x0 + i * (cw + self.GAP)), int(y0))


class _CategoryMenu(QWidget):
    """Menu a due livelli: 3 card categoria (WEC / ELMS / IMSA); click su una
    -> deck delle card pista FILTRATE per quel campionato, con freccia per
    tornare alle categorie. Calendari 2026."""

    _CATS = ("wec", "elms", "imsa")
    _BASES = {
        # FIA WEC 2026 (8 round) + Monza (storica WEC, tenuta qui per non
        # perdere la pista dal menu)
        "wec": {"imola", "spa", "lemans", "interlagos", "cota", "fuji",
                "lusail", "bahrain", "monza", "sebring"},
        # ELMS 2026 (6 round europei)
        "elms": {"barcelona", "paulricard", "imola", "spa", "silverstone",
                 "portimao"},
        # IMSA 2026 — le tappe presenti in LMU/US Track Pass
        "imsa": {"daytona", "sebring", "longbeach", "lagunaseca",
                 "watkinsglen", "indianapolis", "roadatlanta"},
    }

    def __init__(self, on_open=None, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QStackedLayout
        self._on_open = on_open
        self._stack = QStackedLayout(self)
        # ── pagina 0: le tre categorie, proporzione da carta (mai distorte) ──
        self._stack.addWidget(_CatRow(self._CATS, on_click=self._open_cat))
        # ── pagine 1..3: deck filtrati (creati subito: card leggere) ──
        # UN SOLO deck: tutte le card in ordine WEC -> ELMS -> IMSA, senza
        # doppioni (base sia WEC che ELMS -> resta a ELMS, es. Imola/Spa).
        # Il deck gira in loop; cambia solo il LOGO in alto secondo la card di
        # testa. Dalla card categoria si entra sulla prima pista di quella serie.
        def _cat_of(base):
            # Sebring e COTA sono nel GIOCO BASE (round WEC di LMU):
            # stanno con le WEC e NON sotto il lucchetto IMSA
            # (rich. utente 24/07 sera)
            if base in ("sebring", "cota"):
                return "wec"
            if base in self._BASES["imsa"]:
                return "imsa"
            if base in self._BASES["elms"]:
                return "elms"
            return "wec"
        entries = []
        for k in self._CATS:
            for i, e in enumerate(_TRACKS):
                if e[0] in self._BASES[k] and _cat_of(e[0]) == k:
                    entries.append((i, k))
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)
        deck = _CardDeck(on_open=self._open, entries=entries)
        self._deck = deck
        self._decks = {k: deck for k in self._CATS}    # compat
        self.cards = list(deck.cards)
        self._starts = {}
        for pos, (_i, k) in enumerate(entries):
            self._starts.setdefault(k, pos)
        deck._front_cb = self._front_changed
        self.on_cat_change = None            # lo setta _RootCanvas (logo)
        self._cur_cat = self._CATS[0]
        col.addWidget(deck, 1)
        self._stack.addWidget(page)

    def _open_cat(self, key):
        self._stack.setCurrentIndex(1)
        d = self._deck
        d._sel = d._pos = float(self._starts.get(key, 0))
        d._relayout()
        d._last_front = None
        d._notify_front()

    def _front_changed(self, fi):
        cats = self._deck._cats
        k = cats[fi] if 0 <= fi < len(cats) else None
        if k:
            self._cur_cat = k
            if self.on_cat_change:
                self.on_cat_change(k)

    def _open(self, idx):
        if self._on_open:
            self._on_open(idx)


class _CardDeck(QWidget):
    """Carosello lineare infinito: 4 carte per volta, affiancate (non sovrapposte),
    scorrono in linea e in loop continuo. Rotella per scorrere di una; click su una
    carta la porta in testa (percorso più breve)."""
    RATIO = 1.4        # altezza / larghezza (carta da gioco)
    VISIBLE = 4        # carte visibili per volta
    GAP = 14           # spazio tra le carte
    MARGIN = 16

    def __init__(self, on_open=None, parent=None, bases=None, cat=None,
                 entries=None):
        super().__init__(parent)
        self._on_open = on_open
        self.cards = []
        self._cats = []
        self._front_cb = None
        self._last_front = None
        if entries is not None:
            # ordine FISSO (WEC->ELMS->IMSA): niente riordino per popolazione
            self._fixed_order = True
            for i, k in entries:
                base, bgkey, name, logo, cmap = _TRACKS[i]
                c = _Card(base, bgkey, name, logo, cmap, i, self, cat=k)
                c.on_click = self._clicked
                c._trk = (base, bgkey, name, logo, cmap)
                self.cards.append(c)
                self._cats.append(k)
        else:
            for i, (base, bgkey, name, logo, cmap) in enumerate(_TRACKS):
                if bases is not None and base not in bases:
                    continue
                c = _Card(base, bgkey, name, logo, cmap, i, self, cat=cat)
                c.on_click = self._clicked
                c._trk = (base, bgkey, name, logo, cmap)   # per riordino popolazione
                self.cards.append(c)
        self.reorder()                                  # piste più popolate a sinistra
        self._sel = 0.0    # indice di testa (target, può uscire da [0,N): loop)
        self._pos = 0.0    # posizione animata
        self.setMinimumHeight(240)
        self._anim = QTimer(self)
        self._anim.setInterval(16)
        self._anim.timeout.connect(self._tick)
        # frecce laterali: scorrono di una card (oltre alla rotella)
        self._arr_l = self._mk_arrow("chevron_left", -1)
        self._arr_r = self._mk_arrow("chevron_right", +1)

    def _mk_arrow(self, icon, delta):
        b = QPushButton(icon, self)
        b.setCursor(Qt.PointingHandCursor)
        b.setFixedSize(40, 40)
        # STESSO stile della freccia indietro (coerenza card/elementi)
        b.setStyleSheet(
            "QPushButton{font-family:'Material Symbols Rounded';font-size:26px;"
            "color:#fff;background:rgba(255,255,255,0.08);border:none;"
            "border-radius:8px;}"
            "QPushButton:hover{background:rgba(255,29,67,0.55);}")
        b.clicked.connect(lambda _=False, d=delta: self._scroll(d))
        b.raise_()
        return b

    def _relayout(self):
        n = len(self.cards)
        innerW = max(1.0, self.width() - 2 * self.MARGIN)
        step = innerW / self.VISIBLE
        availh = max(90, self.height() - 2 * self.MARGIN)
        cw = step - self.GAP
        ch = cw * self.RATIO
        if ch > availh:
            ch = availh
            cw = ch / self.RATIO
        total = n * step
        offset = self._pos * step
        y = self.MARGIN + (availh - ch) / 2.0
        pad = (step - cw) / 2.0
        for i, c in enumerate(self.cards):
            base = (i * step - offset) % total
            x = None
            for cand in (base, base - total):   # copia che rientra da sinistra
                if -step < cand < innerW:
                    x = cand
                    break
            if x is None:
                c.setVisible(False)
                continue
            c.setVisible(True)
            c.setOpacityF(1.0)
            c.setFixedSize(int(cw), int(ch))
            c.move(int(self.MARGIN + x + pad), int(y))
        # frecce laterali: centrate in verticale, sopra le carte
        _ay = int(self.MARGIN + (availh - 40) / 2.0)
        if getattr(self, "_arr_l", None) is not None:
            self._arr_l.move(2, _ay); self._arr_l.raise_()
            self._arr_r.move(self.width() - 42, _ay); self._arr_r.raise_()

    # ── scorrimento (infinito) + animazione ──
    def _clicked(self, idx):
        if self._on_open:
            self._on_open(idx)      # entra nella schermata originale

    def select(self, i):
        n = len(self.cards)
        cur = self._sel % n
        d = (i - cur + n) % n
        if d > n / 2:
            d -= n                      # percorso più breve nel loop
        self._sel += d
        if not self._anim.isActive():
            self._anim.start()

    def _scroll(self, delta):
        # TRICK: a fine deck si passa alla categoria successiva (e a inizio
        # deck alla precedente) — giro infinito WEC -> ELMS -> IMSA -> WEC
        n = len(self.cards)
        wrap = getattr(self, "_on_wrap", None)
        if wrap is not None and n:
            cur = int(round(self._sel)) % n
            if delta > 0 and cur == n - 1:
                wrap(+1); return
            if delta < 0 and cur == 0:
                wrap(-1); return
        self._sel += delta
        if not self._anim.isActive():
            self._anim.start()

    def _tick(self):
        self._notify_front()
        self._pos += (self._sel - self._pos) * 0.18
        if abs(self._sel - self._pos) < 0.002:
            n = len(self.cards)
            self._sel = float(int(round(self._sel)) % n)   # normalizza nel loop
            self._pos = self._sel
            self._anim.stop()
        self._relayout()

    def _notify_front(self):
        n = len(self.cards)
        if not n:
            return
        fi = int(round(self._sel)) % n
        if fi != self._last_front:
            self._last_front = fi
            if self._front_cb:
                self._front_cb(fi)

    def resizeEvent(self, e):
        self._relayout()

    def showEvent(self, e):
        super().showEvent(e)
        self.reorder()
        self._relayout()

    def reorder(self):
        """Riordina le card: piste con più sessioni locali a sinistra.
        Con ordine FISSO (deck unico per categorie) non tocca nulla."""
        if getattr(self, "_fixed_order", False):
            return
        """
        Conteggio per logo-circuito (raggruppa le varianti) + variante usata."""
        try:
            sess = _db.list_sessions()
        except Exception:
            sess = []
        by_logo = {}; by_layout = {}
        for s in sess:
            trk = s.get("track") or ""
            st = _track_logo_stem(trk)
            if st:
                by_logo[st] = by_logo.get(st, 0) + 1
            lk = _track_layout_key(trk)
            if lk:
                by_layout[lk] = by_layout.get(lk, 0) + 1

        def _key(c):
            base, bgkey, name, logo, cmap = getattr(c, "_trk", ("", "", "", "", ""))
            cstem = cmap[:-4] if (cmap or "").lower().endswith(".svg") else (cmap or "")
            lay = by_layout.get(cstem, 0)
            lg = by_logo.get(logo or "", 0)
            return (lay, lg)

        order = sorted(range(len(self.cards)),
                       key=lambda i: (-_key(self.cards[i])[0],   # sessioni del layout
                                      -_key(self.cards[i])[1],   # poi totale circuito
                                      i))
        self.cards = [self.cards[i] for i in order]
        self._sel = 0.0; self._pos = 0.0
        self._relayout()

    def wheelEvent(self, e):
        self._scroll(1 if e.angleDelta().y() < 0 else -1)
        e.accept()


_HELMET_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none"'
    b' stroke="#ffffff" stroke-width="3" stroke-linejoin="round" stroke-linecap="round">'
    b'<path d="M12 33 C12 19 20 11 32 11 C44 11 52 19 52 33 L52 40'
    b' C52 45 48 48 43 48 L21 48 C16 48 12 45 12 40 Z"/>'
    b'<path d="M16 32 C22 27 42 27 48 32 L46.5 39 C41 42 23 42 17.5 39 Z"/></svg>')


class _TeamAvatar(QLabel):
    """SVG fisso (assets/helmet.svg). Nessun upload."""
    def __init__(self):
        super().__init__()
        self.setFixedSize(66, 66)
        self.setAlignment(Qt.AlignCenter)
        self.setObjectName("mhAvatar")
        self.setStyleSheet("#mhAvatar{background:transparent;border:none;}")
        self._load()

    def _load(self):
        try:
            from PySide6.QtGui import QPixmap, QPainter
            from PySide6.QtCore import QRectF
            _hp = Path(__file__).resolve().parent.parent / "assets" / "helmet.svg"
            data = _hp.read_bytes() if _hp.exists() else _HELMET_SVG
            if QSvgRenderer is None:
                return
            r = QSvgRenderer(QByteArray(data))
            box = 56
            ds = r.defaultSize()
            dw, dh = ds.width(), ds.height()
            if dw > 0 and dh > 0:
                s = min(box / dw, box / dh)        # fit mantenendo proporzioni
                tw, th = dw * s, dh * s
            else:
                tw = th = box
            pm = QPixmap(box, box); pm.fill(Qt.transparent)
            p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing, True)
            r.render(p, QRectF((box - tw) / 2.0, (box - th) / 2.0, tw, th))
            p.end()
            self.setPixmap(pm)
        except Exception:
            pass




class _MenuHeader(QFrame):
    """Card in alto del menu: pilota, campo TEAM (editabile, salva nel profilo)
    e numero di sessioni locali. Il team salvato qui alimenta get_team() →
    card REF/online."""
    _CORNER_SVG = (b'<svg width="177" height="177" viewBox="0 0 177 177" '
                   b'xmlns="http://www.w3.org/2000/svg"><path d="M95.157 81.8186L177.001 '
                   b'163.662V152.245L100.891 76.135L95.1822 81.8439L95.157 81.8186ZM114.203 '
                   b'62.7722L176.976 125.57V114.152L119.912 57.0886L114.203 62.7975V62.7722ZM133.25 '
                   b'43.7258L177.001 87.4517V76.034L138.984 38.017L133.275 43.7258H133.25ZM152.296 '
                   b'24.6795L177.001 49.3842V37.9665L158.03 18.9959L152.321 24.7047L152.296 '
                   b'24.6795ZM171.343 5.63308L177.001 11.2914V0L171.343 5.65834V5.63308ZM163.663 '
                   b'176.975L81.8195 95.1561L76.1106 100.865L152.22 176.975H163.638H163.663ZM125.571 '
                   b'176.975L62.7983 114.177L57.0895 119.886L114.153 176.949H125.571V176.975ZM87.4778 '
                   b'176.975L43.7267 133.224L38.0178 138.932L76.0348 176.949H87.4525L87.4778 '
                   b'176.975ZM49.385 176.975L24.6803 152.27L18.9714 157.979L37.942 176.949H49.3598L49.385 '
                   b'176.975ZM0.00084639 176.975H11.2923L5.63393 171.316L-0.0244141 176.975H0.00084639Z" '
                   b'fill="white"/></svg>')

    def paintEvent(self, e):
        super().paintEvent(e)
        try:
            from PySide6.QtGui import QPainter, QPainterPath
            from PySide6.QtSvg import QSvgRenderer
            p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
            path = QPainterPath(); path.addRoundedRect(QRectF(self.rect()), 14, 14)
            p.setClipPath(path)                       # resta dentro la card arrotondata
            sz = 116
            x = self.width() - sz; y = self.height() - sz
            p.setOpacity(1.0)
            QSvgRenderer(QByteArray(self._CORNER_SVG)).render(p, QRectF(x, y, sz, sz))
            p.end()
        except Exception:
            pass

    def __init__(self, parent=None, on_community=None):
        super().__init__(parent)
        self._on_community = on_community
        self.setObjectName("menuHdr")
        self.setFixedHeight(126)
        self.setStyleSheet(
            "#menuHdr{background:rgba(255,255,255,0.07);border:none;border-radius:14px;}"
            "#mhCap{color:#9fb0c8;font-family:'Archivo SemiExpanded';font-size:10px;font-weight:700;"
            "letter-spacing:2px;background:transparent;}"
            "#mhVal{color:#ffffff;font-family:'Archivo SemiExpanded';font-size:20px;font-weight:700;"
            "background:transparent;}"
            "#mhTeam{color:#ffffff;font-family:'Archivo SemiExpanded';font-size:18px;font-weight:600;"
            "background:rgba(0,0,0,0.22);border:1px solid rgba(255,255,255,0.18);"
            "border-radius:8px;padding:6px 12px;}"
            "#mhTeam:focus{border:1px solid #ff1d43;}")
        h = QHBoxLayout(self); h.setContentsMargins(24, 12, 24, 12); h.setSpacing(20)

        # AVATAR pilota = CASCO con la livrea scelta (click = menu 20 livree)
        self.avatar = _SvgBox()
        self.avatar.setFixedSize(66, 66)
        try:
            from ui.icons import helmet_svg_bytes
            _hc0 = _load_profile().get("helmet_color", "#fd160e")
            self.avatar.load(helmet_svg_bytes(_hc0))
        except Exception:
            _hp = Path(__file__).resolve().parent.parent / "assets" / "helmet.svg"
            if _hp.exists():
                self.avatar.load(str(_hp))
        self.avatar.setCursor(Qt.PointingHandCursor)
        self.avatar.setToolTip("Choose your helmet livery")
        self.avatar.mousePressEvent = lambda e: self._pick_helmet()
        h.addWidget(self.avatar, 0, Qt.AlignVCenter)

        # PILOTA + TEAM impilati (team SOTTO il nome, campo piu' piccolo)
        c1w = QWidget(); c1w.setStyleSheet("background:transparent;")
        c1 = QVBoxLayout(c1w); c1.setContentsMargins(0, 0, 0, 0); c1.setSpacing(2)
        _d = QLabel("DRIVER"); _d.setObjectName("mhCap"); c1.addWidget(_d)
        self.lb_driver = QLabel("\u2014"); self.lb_driver.setObjectName("mhVal")
        c1.addWidget(self.lb_driver)
        _t = QLabel("TEAM"); _t.setObjectName("mhCap")
        _t.setStyleSheet("margin-top:5px;")
        c1.addWidget(_t)
        # team in SOLA LETTURA (piccolo): si modifica dalle OPTIONS
        self.lb_team = QLabel("—")
        self.lb_team.setStyleSheet(
            "color:#e8ebf2;font-family:'Archivo SemiExpanded';font-size:14px;"
            "font-weight:600;background:transparent;")
        c1.addWidget(self.lb_team)
        h.addWidget(c1w, 0, Qt.AlignVCenter)

        # SESSIONI LOCALI: subito dopo team — numero sopra, "Sessions" sotto (bianco)
        c3w = QWidget(); c3w.setStyleSheet("background:transparent;")
        c3 = QVBoxLayout(c3w); c3.setContentsMargins(0, 0, 0, 0); c3.setSpacing(2)
        self.lb_sess = QLabel("0"); self.lb_sess.setObjectName("mhVal")
        self.lb_sess.setAlignment(Qt.AlignHCenter)
        c3.addWidget(self.lb_sess)
        cap = QLabel("MY SESSIONS")
        cap.setAlignment(Qt.AlignHCenter)
        cap.setStyleSheet("color:#ffffff;font-family:'Archivo SemiExpanded';font-size:13px;"
                          "font-weight:600;letter-spacing:1px;background:transparent;")
        c3.addWidget(cap)
        h.addWidget(c3w, 0, Qt.AlignVCenter)

        # DRIVERS ONLINE: numero di driver unici in classifica (dal Worker)
        c4w = QWidget(); c4w.setStyleSheet("background:transparent;")
        c4 = QVBoxLayout(c4w); c4.setContentsMargins(0, 0, 0, 0); c4.setSpacing(2)
        self.lb_drivers = QLabel("0"); self.lb_drivers.setObjectName("mhVal")
        self.lb_drivers.setAlignment(Qt.AlignHCenter)
        c4.addWidget(self.lb_drivers)
        cap2 = QLabel("DRIVERS")
        cap2.setAlignment(Qt.AlignHCenter)
        cap2.setStyleSheet("color:#ffffff;font-family:'Archivo SemiExpanded';font-size:13px;"
                           "font-weight:600;letter-spacing:1px;background:transparent;")
        c4.addWidget(cap2)

        # REF TIMES: record best attivi in classifica (dal Worker)
        c5w = QWidget(); c5w.setStyleSheet("background:transparent;")
        c5 = QVBoxLayout(c5w); c5.setContentsMargins(0, 0, 0, 0); c5.setSpacing(2)
        self.lb_ctimes = QLabel("0"); self.lb_ctimes.setObjectName("mhVal")
        self.lb_ctimes.setAlignment(Qt.AlignHCenter)
        c5.addWidget(self.lb_ctimes)
        cap3 = QLabel("REF TIMES")
        cap3.setAlignment(Qt.AlignHCenter)
        cap3.setStyleSheet("color:#ffffff;font-family:'Archivo SemiExpanded';font-size:13px;"
                           "font-weight:600;letter-spacing:1px;background:transparent;")
        c5.addWidget(cap3)

        # RISULTATI GARA: gare, vittorie, podi, top5, DNF (dalle sessioni gara)
        def _statcol(attr, cap):
            _w = QWidget(); _w.setStyleSheet("background:transparent;")
            _v = QVBoxLayout(_w)
            _v.setContentsMargins(0, 0, 0, 0); _v.setSpacing(2)
            _lb = QLabel("0"); _lb.setObjectName("mhVal")
            _lb.setAlignment(Qt.AlignHCenter)
            _v.addWidget(_lb)
            _c = QLabel(cap); _c.setAlignment(Qt.AlignHCenter)
            _c.setStyleSheet("color:#ffffff;font-family:'Archivo SemiExpanded';font-size:12px;"
                             "font-weight:600;letter-spacing:1px;"
                             "background:transparent;")
            _v.addWidget(_c)
            setattr(self, attr, _lb)
            h.addWidget(_w, 0, Qt.AlignVCenter)
        _statcol("lb_races", "RACES")
        _statcol("lb_wins", "WINS")
        _statcol("lb_podiums", "PODIUMS")
        _statcol("lb_top5", "TOP 5")
        _statcol("lb_dnf", "DNF")
        # dati COMMUNITY (online) spostati a DESTRA, dopo i risultati gara
        h.addWidget(c4w, 0, Qt.AlignVCenter)
        h.addWidget(c5w, 0, Qt.AlignVCenter)

        # rotella OPTIONS: SPOSTATA nel footer (in basso a destra);
        # l'attributo resta per compatibilita' col wiring esistente
        self._on_settings = None

        # tasto COMMUNITY RIMOSSO: spostato nella barra navigazione sotto
        # l'header (Setups / Overlay / Teams / Community).
        h.addStretch(1)

        self.refresh()

    def _pick_helmet(self):
        """Menu 20 livree casco: icona NITIDA (render 2x) + nome; la scelta
        va nel profilo e ricolora subito l'avatar."""
        try:
            from ui.icons import HELMET_COLORS, helmet_svg_bytes
            from PySide6.QtWidgets import QMenu
            from PySide6.QtSvg import QSvgRenderer
            from PySide6.QtGui import QPixmap, QIcon
            from PySide6.QtCore import QByteArray, QRectF, QSize

            def _icon(col, w=30, hh=24):
                pm = QPixmap(w * 2, hh * 2)          # 2x = niente sgranato
                pm.fill(Qt.transparent)
                pm.setDevicePixelRatio(2.0)
                r = QSvgRenderer(QByteArray(helmet_svg_bytes(col)))
                pp = QPainter(pm); pp.setRenderHint(QPainter.Antialiasing)
                r.render(pp, QRectF(0, 0, w, hh)); pp.end()
                return QIcon(pm)
            m = QMenu(self)
            m.setStyleSheet(
                "QMenu{background:#16181c;color:#f2f4f7;border:1px solid "
                "#2a2c30;font-family:Archivo SemiExpanded;font-size:12px;}"
                "QMenu::item{padding:4px 14px;}"
                "QMenu::item:selected{background:rgba(255,29,67,0.45);}")

            def _set(col):
                try:
                    d = _load_profile(); d["helmet_color"] = col
                    _save_profile(d)
                except Exception:
                    pass
                try:
                    self.avatar.load(helmet_svg_bytes(col))
                except Exception:
                    pass
                # aggiorna la livrea sui TUOI record online (classifiche)
                try:
                    from core import online as _onl
                    _pl = (_load_profile().get("driver") or "").strip()
                    if _pl:
                        _onl.update_helmet_async(_pl, col)
                except Exception:
                    pass
            for name, col in HELMET_COLORS:
                m.addAction(_icon(col), name, lambda c=col: _set(c))
            m.exec(self.avatar.mapToGlobal(self.avatar.rect().bottomLeft()))
        except Exception:
            pass

    def _save_team(self):
        t = self.ed_team.text().strip()[:30]
        try:
            d = _load_profile(); d["team"] = t; _save_profile(d)
        except Exception:
            pass

    def eventFilter(self, obj, e):
        try:
            from PySide6.QtCore import QEvent
            if obj is self.ed_team and e.type() == QEvent.FocusIn:
                self._team_timer.start()      # avvia il conto alla rovescia anche solo al click
        except Exception:
            pass
        return super().eventFilter(obj, e)

    def _team_commit(self):
        self._save_team()
        self.ed_team.clearFocus()             # via il cursore lampeggiante

    def refresh(self):
        try:
            prof = _load_profile()
        except Exception:
            prof = {}
        from core.utils import short_name as _sn
        self.lb_driver.setText((_sn(prof.get("driver") or "") or "\u2014").upper())
        self.lb_team.setText(prof.get("team", "") or "—")
        n = 0
        try:
            from core.paths import LOGS_DIR
            d = Path(LOGS_DIR)
            if d.exists():
                n = len(list(d.glob("*.lmtel")))
        except Exception:
            n = 0
        self.lb_sess.setText(_abbr_num(n))
        # risultati gara: gare, vittorie, podi, top5, DNF (dalle sessioni gara)
        try:
            from core.results import race_stats
            _rs = race_stats()
            # override MANUALE dal profilo (stat_*) per inserire lo storico
            # (es. dati 2024): se il campo e' impostato vince, senno' automatico
            for _k, _lb in (("races", self.lb_races), ("wins", self.lb_wins),
                            ("podiums", self.lb_podiums), ("top5", self.lb_top5),
                            ("dnf", self.lb_dnf)):
                _v = prof.get("stat_" + _k, _rs.get(_k, 0))
                _lb.setText(_abbr_num(int(_v)))
        except Exception:
            pass
        # online: driver unici + ref times (best attivi). Cache + refresh background.
        try:
            from core import online as _online
            self.lb_drivers.setText(_abbr_num(_online.drivers_count()))
            self.lb_ctimes.setText(_abbr_num(_online.refs_count()))
            _online.stats_async()
            QTimer.singleShot(1600, lambda: (
                self.lb_drivers.setText(_abbr_num(_online.drivers_count())),
                self.lb_ctimes.setText(_abbr_num(_online.refs_count()))))
        except Exception:
            pass

    def _go_community(self):
        if self._on_community:
            try:
                self._on_community()
            except Exception:
                pass


class _RootCanvas(QWidget):
    """Sfondo della pagina principale: blu pieno #000833.
    Contiene il banner e il carosello di 13 carte scorrevoli."""

    def __init__(self, on_open=None, parent=None, on_community=None,
                 on_setups=None, on_overlay=None, on_teams=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        # header: niente piu' tasto COMMUNITY (spostato nella barra sotto)
        self.banner = _MenuHeader()                  # pilota / team / stats
        root.addWidget(self.banner)

        # BARRA NAVIGAZIONE: card orizzontale piu' piccola tra header e
        # categorie. Setups (ex Settings) / Overlay / Teams / Community, piu'
        # spazio per opzioni app a destra. Community e' stato spostato qui
        # dalla card in alto.
        root.addWidget(self._build_navbar(on_setups, on_overlay, on_teams,
                                          on_community))

        self.deck = _CategoryMenu(on_open=on_open)   # WEC / ELMS / IMSA
        root.addWidget(self.deck, 1)
        self.cards = self.deck.cards
        # freccia + logo nella barra <-> deck: clic torna alle categorie; freccia
        # e logo visibili solo dentro un deck (pagina > 0), col logo del
        # campionato aperto.
        try:
            self._navback.clicked.connect(
                lambda _=False: self.deck._stack.setCurrentIndex(0))
            self.deck._stack.currentChanged.connect(self._on_deck_page)
            self.deck.on_cat_change = self._set_nav_logo
        except Exception:
            pass
        root.addWidget(_PartnersBar())               # strip partner in basso

    def _on_deck_page(self, i):
        show = i > 0
        self._navback.setVisible(show)
        self._navback_lbl.setVisible(show)
        self._navlogo.setVisible(show)
        if show:
            self._set_nav_logo(getattr(self.deck, "_cur_cat", None))

    def _set_nav_logo(self, k):
        """Logo serie al centro: segue la categoria della card di testa."""
        pm = self._series_pm(k, box_w=150, box_h=44) if k else None
        if pm is not None:
            self._navlogo.setPixmap(pm)

    def _series_pm(self, cat, box_w=64, box_h=22):
        """Logo serie -> pixmap, adattato dentro una SCATOLA fissa (box_w x
        box_h), scalando per stare dentro senza distorcere. Cosi' i tre loghi
        hanno lo stesso ingombro: IMSA (aspect ~4.8, larghissimo) veniva capato
        in altezza e sembrava molto piu' grande; ora e' capato in larghezza."""
        try:
            _p = Path(__file__).resolve().parent.parent / "assets" / ("%s.svg" % cat)
            if _p.exists() and QSvgRenderer is not None:
                _r = QSvgRenderer(str(_p))
                if _r.isValid():
                    ds = _r.defaultSize()
                    w0, h0 = float(ds.width()), float(ds.height())
                    if w0 <= 0 or h0 <= 0:
                        return None
                    scale = min(box_w / w0, box_h / h0)
                    wpx = max(1, int(round(w0 * scale)))
                    hpx = max(1, int(round(h0 * scale)))
                    # DPR-aware: senza, con lo scaling di Windows il logo
                    # veniva upscalato e usciva SGRANATO
                    _dpr = float(self.devicePixelRatioF() or 1.0)
                    pm = QPixmap(int(wpx * _dpr), int(hpx * _dpr))
                    pm.setDevicePixelRatio(_dpr)
                    pm.fill(Qt.transparent)
                    _qp = QPainter(pm)
                    _qp.setRenderHint(QPainter.Antialiasing, True)
                    _qp.setRenderHint(QPainter.SmoothPixmapTransform, True)
                    _r.render(_qp, QRectF(0, 0, wpx, hpx))
                    _qp.end()
                    return pm
        except Exception:
            pass
        return None

    def _build_navbar(self, on_setups, on_overlay, on_teams, on_community):
        bar = QFrame(); bar.setObjectName("navBar")
        bar.setStyleSheet("#navBar{background:transparent;}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(10)

        # freccia "torna alle categorie": PRIMA, poi il logo serie a destra
        # (visibili solo dentro un deck; _on_deck_page li aggiorna).
        self._navback = QPushButton("arrow_back")
        self._navback.setCursor(Qt.PointingHandCursor)
        self._navback.setFixedSize(38, 34)
        self._navback.setStyleSheet(
            "QPushButton{font-family:'Material Symbols Rounded';font-size:22px;"
            "color:#fff;background:rgba(255,255,255,0.08);border:none;"
            "border-radius:8px;}"
            "QPushButton:hover{background:rgba(255,29,67,0.55);}")
        self._navback.setVisible(False)
        lay.addWidget(self._navback)
        # scritta BACK accanto alla freccia
        self._navback_lbl = QLabel("BACK")
        self._navback_lbl.setStyleSheet(
            "color:#ffffff;font-family:'Archivo SemiExpanded';font-size:13px;font-weight:700;"
            "letter-spacing:1px;background:transparent;")
        self._navback_lbl.setVisible(False)
        lay.addWidget(self._navback_lbl, 0, Qt.AlignVCenter)

        # logo serie GRANDE al centro della barra
        lay.addStretch(1)
        self._navlogo = QLabel()
        self._navlogo.setStyleSheet("background:transparent;")
        self._navlogo.setVisible(False)
        lay.addWidget(self._navlogo, 0, Qt.AlignVCenter)

        def _btn(text, cb):
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                "QPushButton{background:transparent;color:#ffffff;"
                "font-family:'Archivo SemiExpanded';font-size:13px;font-weight:700;"
                "letter-spacing:1px;border:1px solid rgba(255,255,255,0.30);"
                "border-radius:6px;padding:7px 18px;}"
                "QPushButton:hover{background:rgba(255,255,255,0.12);"
                "border-color:#ffffff;}")
            if cb is not None:
                b.clicked.connect(lambda _=False, f=cb: f())
            return b

        # COMMUNITY rimosso: le classifiche vivono ora nella pagina pista.
        # nessun bottone: Setups/Teams/Overlay vivono nelle rispettive pagine
        lay.addStretch(1)
        # spazio opzioni app a destra (da riempire con i toggle che vuoi)
        return bar

    def showEvent(self, e):
        super().showEvent(e)
        try:
            self.banner.refresh()
        except Exception:
            pass

    _MENU_BG = "unset"      # cache: assets/overview.jpg (stessa dell'overview)

    @classmethod
    def _menu_photo(cls):
        if cls._MENU_BG == "unset":
            _p = Path(__file__).resolve().parent.parent / "assets" / "overview.jpg"
            _pm = QPixmap(str(_p)) if _p.exists() else None
            cls._MENU_BG = _pm if (_pm is not None and not _pm.isNull()) else None
        return cls._MENU_BG

    def paintEvent(self, e):
        from PySide6.QtGui import QRadialGradient
        from PySide6.QtCore import QRect
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = self.rect()
        w, h = self.width(), self.height()
        photo = self._menu_photo()
        if photo is not None:
            # stesso trattamento dell'overview: foto 20% + blu basso-sx + rosso alto-dx
            p.fillRect(r, QColor("#000833"))
            scaled = photo.scaled(r.size(), Qt.KeepAspectRatioByExpanding,
                                  Qt.SmoothTransformation)
            sx = max(0, (scaled.width() - r.width()) // 2)
            sy = max(0, (scaled.height() - r.height()) // 2)
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.setOpacity(0.20)
            p.drawPixmap(r, scaled, QRect(sx, sy, r.width(), r.height()))
            p.setOpacity(1.0)
            gb = QRadialGradient(0, h, max(w, h) * 0.95)
            gb.setColorAt(0.0, QColor(19, 41, 67, 130))
            gb.setColorAt(0.55, QColor(19, 41, 67, 45))
            gb.setColorAt(1.0, QColor(19, 41, 67, 0))
            p.fillRect(r, QBrush(gb))
        else:
            p.fillRect(r, QColor("#000833"))                 # blu pieno
        g = QRadialGradient(w, 0, max(w, h) * 0.95)          # centro: angolo alto-destra
        g.setColorAt(0.0, QColor(255, 29, 67, 170))
        g.setColorAt(0.55, QColor(255, 29, 67, 60))
        g.setColorAt(1.0, QColor(255, 29, 67, 0))
        p.fillRect(self.rect(), QBrush(g))


class _RadialBg(QWidget):
    """Sfondo blu + radiale rosso. Se gli viene passata una foto (set_photo),
    la disegna come base e i colori la velano. Visibile nella pagina sessione."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._photo = None

    def set_photo(self, pm):
        self._photo = pm if (pm is not None and not pm.isNull()) else None
        self.update()

    def paintEvent(self, e):
        from PySide6.QtGui import QRadialGradient
        from PySide6.QtCore import QRect
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = self.rect()
        w, h = self.width(), self.height()
        if self._photo is not None:
            # stesso trattamento della pagina sessione: foto 20% + blu basso-sx + rosso alto-dx
            p.fillRect(r, QColor("#08080c"))
            scaled = self._photo.scaled(r.size(), Qt.KeepAspectRatioByExpanding,
                                        Qt.SmoothTransformation)
            sx = max(0, (scaled.width() - r.width()) // 2)
            sy = max(0, (scaled.height() - r.height()) // 2)
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.setOpacity(0.20)
            p.drawPixmap(r, scaled, QRect(sx, sy, r.width(), r.height()))
            p.setOpacity(1.0)
            gb = QRadialGradient(0, h, max(w, h) * 0.95)
            gb.setColorAt(0.0, QColor(19, 41, 67, 130))
            gb.setColorAt(0.55, QColor(19, 41, 67, 45))
            gb.setColorAt(1.0, QColor(19, 41, 67, 0))
            p.fillRect(r, QBrush(gb))
            gr = QRadialGradient(w, 0, max(w, h) * 0.55)
            gr.setColorAt(0.0, QColor(255, 29, 67, 80))
            gr.setColorAt(0.5, QColor(255, 29, 67, 22))
            gr.setColorAt(1.0, QColor(255, 29, 67, 0))
            p.fillRect(r, QBrush(gr))
            return
        # menu/back: blu + radiale rosso come prima
        p.fillRect(r, QColor("#000833"))
        g = QRadialGradient(w, 0, max(w, h) * 0.95)
        g.setColorAt(0.0, QColor(255, 29, 67, 170))
        g.setColorAt(0.55, QColor(255, 29, 67, 60))
        g.setColorAt(1.0, QColor(255, 29, 67, 0))
        p.fillRect(r, QBrush(g))


class _IntroPage(QWidget):
    """Riproduce assets/intro.mp4 a tutta finestra dentro una QGraphicsScene, così
    il tasto Skip (overlay nella scena) sta davvero SOPRA il filmato. Skip dopo 3s.
    Chiama on_done() a fine video o al click. Solleva eccezione in __init__ se la
    multimedia non c'è (il chiamante fa fallback al menu)."""
    _VIDEO = Path(__file__).resolve().parent.parent / "assets" / "intro.mp4"
    _MUSIC = (Path(__file__).resolve().parent.parent
              / "assets" / "audio" / "music" / "1.mp3")

    def __init__(self, on_done, parent=None):
        super().__init__(parent)
        from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
        from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
        from PySide6.QtWidgets import QGraphicsScene, QGraphicsView
        from PySide6.QtCore import QUrl, QSizeF
        self._on_done = on_done
        self._done = False
        self._QSizeF = QSizeF

        self.setStyleSheet("background:#000000;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._view = QGraphicsView(self)
        self._view.setFrameShape(QFrame.NoFrame)
        self._view.setStyleSheet("background:#000000; border:none;")
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lay.addWidget(self._view)

        self._scene = QGraphicsScene(self._view)
        self._view.setScene(self._scene)
        self._item = QGraphicsVideoItem()
        self._item.setAspectRatioMode(Qt.KeepAspectRatioByExpanding)   # riempi finestra
        self._scene.addItem(self._item)

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._audio.setMuted(True)            # audio del VIDEO muto: lo sostituisce la musica
        # colonna sonora dell'intro (1.mp3): parte a volume 70%, NON muta
        self._music = None
        self._music_out = None
        if self._MUSIC.exists():
            self._music = QMediaPlayer(self)
            self._music_out = QAudioOutput(self)
            self._music.setAudioOutput(self._music_out)
            try:
                from core.profile import _load_profile as _lp
                _mv = max(0.0, min(1.0, float(_lp().get("music_vol", 40)) / 100.0))
            except Exception:
                _mv = 0.70
            self._music_out.setVolume(_mv)
            self._music.setSource(QUrl.fromLocalFile(str(self._MUSIC)))
        self._player.setVideoOutput(self._item)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.setSource(QUrl.fromLocalFile(str(self._VIDEO)))

        # tasto Skip come overlay nella scena (z sopra al video)
        self._skip = QPushButton("Skip  \u203a")
        self._skip.setCursor(Qt.PointingHandCursor)
        f = QFont("Archivo SemiExpanded")
        f.setPixelSize(15)
        self._skip.setFont(f)
        self._skip.setStyleSheet(
            "QPushButton { color:#ffffff; font-family:'Archivo SemiExpanded'; font-size:15px;"
            " background:transparent;"
            " border:1px solid rgba(255,255,255,0.55); border-radius:18px;"
            " padding:8px 18px; }"
            "QPushButton:hover { background:rgba(255,29,67,0.90);"
            " border-color:rgba(255,29,67,1.0); }"
        )
        self._skip.clicked.connect(self._finish)
        self._proxy = self._scene.addWidget(self._skip)
        self._proxy.setZValue(10)
        self._proxy.setVisible(False)

        # tasto volume/mute (Material Icons via ligatura), visibile da subito
        self._mute = QPushButton("volume_up")
        self._mute.setCursor(Qt.PointingHandCursor)
        self._mute.setStyleSheet(
            "QPushButton { font-family:'Material Icons'; font-size:26px;"
            " color:#ffffff; background:transparent; border:none; padding:4px; }"
            "QPushButton:hover { color:rgba(255,29,67,1.0); }"
        )
        self._mute.clicked.connect(self._toggle_mute)
        self._mute_proxy = self._scene.addWidget(self._mute)
        self._mute_proxy.setZValue(10)

        # bg radiale: entra in dissolvenza 3s prima della fine (sotto titolo/tasti)
        self._bg_widget = _RadialBg()
        self._bg_proxy = self._scene.addWidget(self._bg_widget)
        self._bg_proxy.setZValue(5)
        self._bg_proxy.setOpacity(0.0)
        self._bg_started = False
        from PySide6.QtCore import QPropertyAnimation as _QPA
        self._bg_anim = _QPA(self._bg_proxy, b"opacity", self)
        self._bg_anim.setDuration(2600)
        self._bg_anim.setStartValue(0.0)
        self._bg_anim.setEndValue(1.0)

        # titolo (Archivo SemiExpanded) + tasto ENTRA (Archivo SemiExpanded Regular): appaiono in fade dopo 3s
        self._title = QLabel("LMU Telemetry Pro")
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setStyleSheet(
            "QLabel { font-family:'Archivo SemiExpanded'; font-weight:700; font-size:46px;"
            " color:#ffffff; background:transparent; }"
        )
        self._title_proxy = self._scene.addWidget(self._title)
        self._title_proxy.setZValue(9)
        self._title_proxy.setOpacity(0.0)

        # sottotitolo MURETTO: font Archivo (stile WEC), corsivo, rosso LMU.
        # Appare 2s DOPO il titolo (vedi timer piu' sotto).
        self._subtitle = QLabel("MURETTO")
        self._subtitle.setAlignment(Qt.AlignCenter)
        self._subtitle.setStyleSheet(
            "QLabel { font-family:'Archivo SemiExpanded'; font-style:normal;"
            " font-weight:900; font-size:58px; letter-spacing:4px;"
            " color:#ff2800; background:transparent; }"
        )
        self._subtitle_proxy = self._scene.addWidget(self._subtitle)
        self._subtitle_proxy.setZValue(9)
        self._subtitle_proxy.setOpacity(0.0)

        # versione, piccola, sotto MURETTO
        self._version = QLabel("v.0.3 beta")
        self._version.setAlignment(Qt.AlignCenter)
        self._version.setStyleSheet(
            "QLabel { font-family:'Archivo SemiExpanded'; font-weight:400; font-size:15px;"
            " letter-spacing:2px; color:rgba(255,255,255,0.55);"
            " background:transparent; }"
        )
        self._version_proxy = self._scene.addWidget(self._version)
        self._version_proxy.setZValue(9)
        self._version_proxy.setOpacity(0.0)

        self._enter = QPushButton("ENTER")
        self._enter.setCursor(Qt.PointingHandCursor)
        self._enter.setStyleSheet(
            "QPushButton { font-family:'Archivo SemiExpanded'; font-weight:400; font-size:18px;"
            " color:#ffffff; background:transparent;"
            " border:1px solid rgba(255,255,255,0.70); border-radius:22px;"
            " padding:10px 34px; }"
            "QPushButton:hover { background:rgba(255,29,67,0.90);"
            " border-color:rgba(255,29,67,1.0); }"
        )
        self._enter.clicked.connect(self._finish)
        self._enter_proxy = self._scene.addWidget(self._enter)
        self._enter_proxy.setZValue(9)
        self._enter_proxy.setOpacity(0.0)

        # linee nell'angolo basso-destra: fade-in dopo 3s, poi restano
        self._stripes = _SvgBox()
        self._stripes.load(_MenuHeader._CORNER_SVG)
        self._stripes.setStyleSheet("background:transparent;")
        self._stripes_proxy = self._scene.addWidget(self._stripes)
        self._stripes_proxy.setZValue(8)
        self._stripes_proxy.setOpacity(0.0)

        from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QParallelAnimationGroup
        # simbolo app (tracciato-linee) al centro: bianco. NON nel fade dei 3s:
        # entra ~1.6s dopo il titolo con uno zoom da fuori verso dentro (come le card).
        self._symbol = _WhiteSvgBox()
        _sym_path = Path(__file__).resolve().parent.parent / "assets" / "intro_symbol.svg"
        if _sym_path.exists():
            self._symbol.load(str(_sym_path))
        self._symbol.setStyleSheet("background:transparent;")
        self._symbol_proxy = self._scene.addWidget(self._symbol)
        self._symbol_proxy.setZValue(8)
        self._symbol_proxy.setOpacity(0.0)
        self._symbol_proxy.setScale(1.35)        # parte ingrandito (da "fuori")

        def _mk_fade(proxy, dur=1100):
            a = QPropertyAnimation(proxy, b"opacity", self)
            a.setDuration(dur)
            a.setStartValue(0.0)
            a.setEndValue(1.0)
            a.setEasingCurve(QEasingCurve.InOutCubic)
            return a
        # tre tempi distinti: titolo (+strisce), poi MURETTO, poi ENTRA
        self._fade_title = [_mk_fade(self._title_proxy),
                            _mk_fade(self._stripes_proxy)]
        self._fade_sub = _mk_fade(self._subtitle_proxy)
        self._fade_ver = _mk_fade(self._version_proxy)
        self._fade_enter = _mk_fade(self._enter_proxy)

        # animazione d'ingresso del simbolo: scale 1.35 -> 1.0 + opacity 0 -> 1
        _sa = QPropertyAnimation(self._symbol_proxy, b"scale", self)
        _sa.setDuration(900); _sa.setStartValue(1.35); _sa.setEndValue(1.0)
        _sa.setEasingCurve(QEasingCurve.OutCubic)
        _oa = QPropertyAnimation(self._symbol_proxy, b"opacity", self)
        _oa.setDuration(700); _oa.setStartValue(0.0); _oa.setEndValue(1.0)
        _oa.setEasingCurve(QEasingCurve.OutCubic)
        self._symbol_anim = QParallelAnimationGroup(self)
        self._symbol_anim.addAnimation(_sa)
        self._symbol_anim.addAnimation(_oa)

        # tasto Reload (Material Icons): a fine video prende il posto di Skip
        self._reload = QPushButton("replay")
        self._reload.setCursor(Qt.PointingHandCursor)
        self._reload.setStyleSheet(
            "QPushButton { font-family:'Material Icons'; font-size:28px;"
            " color:#ffffff; background:transparent; border:none; padding:4px; }"
            "QPushButton:hover { color:rgba(255,29,67,1.0); }"
        )
        self._reload.clicked.connect(self._replay)
        self._reload_proxy = self._scene.addWidget(self._reload)
        self._reload_proxy.setZValue(10)
        self._reload_proxy.setVisible(False)

        # pausa sull'ultimo frame
        self._dur = 0
        self._ended = False
        self._player.durationChanged.connect(self._on_duration)
        self._player.positionChanged.connect(self._on_position)

        QTimer.singleShot(3000, self._show_skip)
        QTimer.singleShot(10000, self._reveal_overlays)  # titolo (dopo ~10s)
        QTimer.singleShot(11600, self._reveal_symbol)    # ~1.6s dopo il titolo
        QTimer.singleShot(12000, self._reveal_subtitle)  # +2s: MURETTO + versione
        QTimer.singleShot(15000, self._reveal_enter)     # +3s da MURETTO: ENTRA
        self._player.play()
        if self._music is not None:
            self._music.play()

    def _on_duration(self, d):
        self._dur = d

    def _on_position(self, pos):
        if self._dur <= 0:
            return
        # taglia gli ULTIMI 7s del video (richiesta utente): fine anticipata
        _cut = self._dur - 7000 if self._dur > 9000 else self._dur - 120
        if not self._bg_started and pos >= _cut - 3000:
            self._bg_started = True
            self._bg_anim.start()
        if not self._ended and pos >= _cut:
            self._at_end()

    def _at_end(self):
        if self._ended:
            return
        self._ended = True
        try:
            self._player.pause()
        except Exception:
            pass
        # NON fermo la musica: continua anche dopo il video, fino a fine traccia
        self._bg_started = True
        self._bg_anim.stop()
        self._bg_proxy.setOpacity(1.0)       # radiale pieno sull'ultimo frame
        self._proxy.setVisible(False)        # via Skip
        self._reload_proxy.setVisible(True)  # appare Reload al suo posto
        self._place_reload()

    def _replay(self):
        self._ended = False
        self._bg_started = False
        self._bg_anim.stop()
        self._bg_proxy.setOpacity(0.0)
        self._reload_proxy.setVisible(False)
        try:
            self._player.setPosition(0)
            self._player.play()
        except Exception:
            pass
        if self._music is not None:
            try:
                self._music.setPosition(0)
                self._music.play()
            except Exception:
                pass

    def _fit(self):
        vp = self._view.viewport().size()
        self._scene.setSceneRect(0, 0, vp.width(), vp.height())
        self._item.setPos(0, 0)
        self._item.setSize(self._QSizeF(vp.width(), vp.height()))
        self._bg_widget.resize(vp.width(), vp.height())
        self._bg_proxy.setPos(0, 0)
        self._place_skip()
        self._place_mute()
        self._place_title()
        self._place_subtitle()
        self._place_version()
        self._place_enter()
        self._place_reload()
        self._place_stripes()
        self._place_symbol()

    def _place_symbol(self):
        vp = self._view.viewport().size()
        sz = int(min(vp.width(), vp.height()) * 0.30)
        self._symbol.resize(sz, sz)
        self._symbol_proxy.setTransformOriginPoint(sz / 2.0, sz / 2.0)  # scala dal centro
        # centrato in orizzontale, sopra al titolo (titolo è al 42%)
        self._symbol_proxy.setPos((vp.width() - sz) / 2.0,
                                  vp.height() * 0.42 - sz - 24)

    def _reveal_overlays(self):        # titolo + strisce (a 3s)
        if not self._done:
            for a in self._fade_title:
                a.start()

    def _reveal_subtitle(self):        # MURETTO + versione (2s dopo il titolo)
        if not self._done:
            self._fade_sub.start()
            self._fade_ver.start()

    def _reveal_enter(self):           # ENTRA (3s dopo MURETTO)
        if not self._done:
            self._fade_enter.start()

    def _reveal_symbol(self):
        if not self._done:
            self._symbol_anim.start()

    def _place_subtitle(self):
        self._subtitle.adjustSize()
        sh = self._subtitle.sizeHint()
        ts = self._title.sizeHint()
        vp = self._view.viewport().size()
        title_bottom = vp.height() * 0.42 + ts.height() / 2.0
        self._subtitle_proxy.setPos((vp.width() - sh.width()) / 2.0,
                                    title_bottom + 4)

    def _place_version(self):
        self._version.adjustSize()
        sh = self._version.sizeHint()
        ts = self._title.sizeHint()
        ss = self._subtitle.sizeHint()
        vp = self._view.viewport().size()
        sub_bottom = (vp.height() * 0.42 + ts.height() / 2.0
                      + 4 + ss.height())
        self._version_proxy.setPos((vp.width() - sh.width()) / 2.0,
                                   sub_bottom + 2)

    def _place_enter(self):
        self._enter.adjustSize()
        sh = self._enter.sizeHint()
        ts = self._title.sizeHint()
        ss = self._subtitle.sizeHint()
        vs = self._version.sizeHint()
        vp = self._view.viewport().size()
        ver_bottom = (vp.height() * 0.42 + ts.height() / 2.0
                      + 4 + ss.height() + 2 + vs.height())
        self._enter_proxy.setPos((vp.width() - sh.width()) / 2.0,
                                 ver_bottom + 16)

    def _place_reload(self):
        m = 24
        sh = self._reload.sizeHint()
        msh = self._mute.sizeHint()
        vp = self._view.viewport().size()
        # accanto al volume, in basso a sinistra
        self._reload_proxy.setPos(m + msh.width() + 10, vp.height() - sh.height() - m)

    def _place_stripes(self):
        vp = self._view.viewport().size()
        sz = int(min(vp.width(), vp.height()) * 0.32)
        self._stripes.resize(sz, sz)
        self._stripes_proxy.setPos(vp.width() - sz, vp.height() - sz)  # angolo basso-destra

    def _place_title(self):
        self._title.adjustSize()
        sh = self._title.sizeHint()
        vp = self._view.viewport().size()
        self._title_proxy.setPos((vp.width() - sh.width()) / 2.0,
                                 vp.height() * 0.42 - sh.height() / 2.0)

    def _toggle_mute(self):
        out = self._music_out or self._audio   # ora l'audio udibile e' la musica
        m = not out.isMuted()
        out.setMuted(m)
        self._mute.setText("volume_off" if m else "volume_up")

    def _place_mute(self):
        m = 24
        sh = self._mute.sizeHint()
        vp = self._view.viewport().size()
        self._mute_proxy.setPos(m, vp.height() - sh.height() - m)

    def _place_skip(self):
        m = 24
        sh = self._skip.sizeHint()
        vp = self._view.viewport().size()
        self._proxy.setPos(vp.width() - sh.width() - m, vp.height() - sh.height() - m)

    def _show_skip(self):
        self._proxy.setVisible(False)        # Skip rimosso: si entra con ENTRA

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def showEvent(self, e):
        super().showEvent(e)
        self._fit()

    def _on_status(self, st):
        from PySide6.QtMultimedia import QMediaPlayer
        if st == QMediaPlayer.MediaStatus.EndOfMedia:
            self._at_end()

    def _finish(self):
        if self._done:
            return
        self._done = True
        try:
            self._player.stop()
        except Exception:
            pass
        if getattr(self, "_music", None) is not None:
            try:
                self._music.stop()
            except Exception:
                pass
        self._on_done()












class _SessionCard(QFrame):
    """Card sessione cliccabile: logo auto, pilota, auto, sessione·giri·data.
    Selezionata → sfondo bianco e testo rosso LMU."""
    _NORMAL = ("#sessCard { background:rgba(255,255,255,0.06);"
               " border:none; border-left:2px solid transparent; border-radius:10px; }"
               "#sessCard:hover { background:rgba(255,255,255,0.11); }")
    _SEL = ("#sessCard { background:rgba(255,255,255,0.16);"
            " border:none; border-left:2px solid #ff1d43; border-radius:10px; }")

    def __init__(self, meta, on_export=None, on_delete=None, parent=None):
        super().__init__(parent)
        from core.utils import find_logo_path
        from core.brands import brand_from_vehicle
        self.on_click = None
        self._selected = False
        self._dimmed = False
        self._meta = meta
        self._file = meta.get("file")
        self._on_export = on_export
        self._on_delete = on_delete
        self.setObjectName("sessCard")
        self.setStyleSheet(self._NORMAL)
        self.setCursor(Qt.PointingHandCursor)
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 12, 16, 12)
        h.setSpacing(12)

        # colonna sinistra: logo brand auto + badge classe SOTTO il logo
        brand = (brand_from_vehicle(meta.get("team") or "")
                 or brand_from_vehicle(meta.get("vehicle") or ""))
        p = find_logo_path(brand) if brand else None
        left = QVBoxLayout()
        left.setSpacing(5)
        left.setContentsMargins(0, 0, 0, 0)
        logo = _SvgBox()
        logo.setFixedSize(68, 48)
        logo.setStyleSheet("background:transparent;")
        if p is not None:
            logo.load(str(p))
        left.addWidget(logo, 0, Qt.AlignHCenter)
        try:
            from core.classes import class_tag as _ctag
            _cls = (_ctag(meta.get("car_class") or "") or "").lower()
            _cp = (Path(__file__).resolve().parent.parent
                   / "assets" / "class" / (_cls + ".svg"))
            if _cls and _cp.exists():
                badge = _SvgBox()
                badge.setFixedSize(46, 30)        # aspetto mantenuto da _SvgBox
                badge.load(str(_cp))
                left.addWidget(badge, 0, Qt.AlignHCenter)
        except Exception:
            pass
        h.addLayout(left, 0)

        # centro: nome pilota in evidenza, poi auto, poi sessione·giri·data
        mid = QVBoxLayout()
        mid.setSpacing(3)

        # riga 5 icone meteo previste (forecast), SOPRA il nome del pilota
        fc5 = (meta.get("forecast5") or "").strip()
        if fc5:
            _wdir = Path(__file__).resolve().parent.parent / "assets" / "weather"
            fc_row = QWidget()
            fc_row.setStyleSheet("background:transparent;")
            fcl = QHBoxLayout(fc_row)
            fcl.setContentsMargins(0, 0, 0, 0)
            fcl.setSpacing(7)
            _nic = 0
            for nm in [x.strip() for x in fc5.split(",") if x.strip()][:5]:
                wp = _wdir / ("%s.svg" % nm)
                if not wp.exists():
                    continue
                ic = _SvgBox()
                ic.setFixedSize(44, 44)
                ic.setStyleSheet("background:transparent;")
                ic.load(str(wp))
                fcl.addWidget(ic, 0, Qt.AlignVCenter)
                _nic += 1
            if _nic:
                fcl.addStretch()
                mid.addWidget(fc_row)
            else:
                fc_row.deleteLater()

        driver = meta.get("driver") or meta.get("team") or "\u2014"
        self._lab_drv = QLabel((driver or '').upper())
        mid.addWidget(self._lab_drv)

        self._lab_car = QLabel(meta.get("vehicle") or meta.get("car_class") or "\u2014")
        mid.addWidget(self._lab_car)

        laps = meta.get("laps") or 0
        styp = _ov_session_label(meta.get("session_type"))
        slen = _fmt_session_len(meta.get("session_len"))
        sess = styp + (f" {slen}" if slen else "")
        self._lab_sub = QLabel("   \u00b7   ".join(
            [sess, f"{laps} giri", self._fmt_date(meta.get("started_at"))]))
        mid.addWidget(self._lab_sub)
        h.addLayout(mid, 1)

        # colonna icone a destra: export in alto, X (elimina) in basso (come il vecchio)
        rb = QVBoxLayout()
        rb.setSpacing(4)
        rb.setContentsMargins(0, 0, 0, 0)
        if meta.get("team_session"):
            tlbl = QLabel("team")
            tlbl.setStyleSheet("color:#e8eaee; font-size:10px; font-weight:700;"
                               " letter-spacing:.5px; background:transparent; border:none;")
            rb.addWidget(tlbl, 0, Qt.AlignRight | Qt.AlignTop)
        else:
            self._btn_exp = _ExportButton(16)
            self._btn_exp.setFlat(True)
            self._btn_exp.setCursor(Qt.PointingHandCursor)
            self._btn_exp.setToolTip("Esporta sessione (.zip)")
            self._btn_exp.setFixedSize(24, 24)
            self._btn_exp.setStyleSheet("border:none; background:transparent;")
            self._btn_exp.clicked.connect(self._do_export)
            rb.addWidget(self._btn_exp, 0, Qt.AlignRight | Qt.AlignTop)
        rb.addStretch(1)
        self._btn_del = _XButton(18)
        self._btn_del.setFlat(True)
        self._btn_del.setCursor(Qt.PointingHandCursor)
        self._btn_del.setToolTip("Elimina")
        self._btn_del.setFixedSize(26, 26)
        self._btn_del.setStyleSheet("border:none; background:transparent;")
        self._btn_del.clicked.connect(self._do_del)
        rb.addWidget(self._btn_del, 0, Qt.AlignRight | Qt.AlignBottom)
        h.addLayout(rb, 0)
        self._apply_text()

    def set_dim(self, on):
        """DISABILITATA durante una sessione live: opacita' 40% e non cliccabile
        (ne' apri ne' export/cestino). Mentre registri in pista non puoi aprire
        una sessione precedente."""
        self._dimmed = bool(on)
        try:
            from PySide6.QtWidgets import QGraphicsOpacityEffect
            if on:
                eff = QGraphicsOpacityEffect(self); eff.setOpacity(0.40)
                self.setGraphicsEffect(eff)
                self.setCursor(Qt.ArrowCursor)
            else:
                self.setGraphicsEffect(None)
                self.setCursor(Qt.PointingHandCursor)
        except Exception:
            pass

    def _do_export(self):
        if self._dimmed:
            return
        if self._on_export:
            self._on_export(self._file)

    def _do_del(self):
        if self._dimmed:
            return
        if self._on_delete:
            self._on_delete(self._file)

    def _apply_text(self):
        self._lab_drv.setStyleSheet("color:#ffffff; font-family:'Archivo SemiExpanded';"
                                    " font-weight:700; font-size:15px;"
                                    " background:transparent; border:none;")
        self._lab_car.setStyleSheet("color:#cfd6e2; font-family:'Archivo SemiExpanded';"
                                    " font-size:13px; background:transparent; border:none;")
        self._lab_sub.setStyleSheet("color:#aeb6c4; font-family:'Archivo SemiExpanded';"
                                    " font-size:12px; background:transparent; border:none;")

    def setSelected(self, on):
        self._selected = on
        self.setStyleSheet(self._SEL if on else self._NORMAL)
        self._apply_text()

    def mousePressEvent(self, e):
        if self._dimmed:                     # sessione live: card non cliccabile
            return
        if e.button() == Qt.LeftButton and self.on_click:
            self.on_click(self)
            e.accept()

    @staticmethod
    def _fmt_date(iso):
        if not iso:
            return "\u2014"
        try:
            from datetime import datetime
            return datetime.fromisoformat(iso).strftime("%d/%m/%Y  %H:%M")
        except Exception:
            return str(iso)


_OV_BOARD_QSS = r"""#ovCard{background:transparent;border:none;}#ovNoData{color:#5c5f68;font-size:14px;background:transparent;}#ovTrackBox{background:transparent;border:none;}#ovSessName{color:#f2f4f7;font-size:17px;font-weight:700;background:transparent;}#ovSessClock{color:#45b4ef;font-size:17px;font-weight:700;background:transparent;}#ovCondLine{color:#a7aaaf;font-size:13px;background:transparent;}#ovInfoLine{color:#cfd2d8;font-size:12px;background:transparent;}#ovListCard{background:transparent;border:none;}QScrollBar:horizontal{height:0px;background:transparent;}#ovHead{color:#6e727b;font-size:11px;font-weight:700;letter-spacing:2px;}#ovDriver{background:transparent;border:none;color:#f2f4f7;font-size:16px;font-weight:600;}#ovTeam{background:transparent;border:none;color:#a7aaaf;font-size:12px;}#ovDriver:focus,#ovTeam:focus{border-bottom:1px solid #3a3d43;}#ovCar{color:#6e727b;font-size:12px;}#ovTrack{color:#bdbfc3;font-size:11px;font-weight:600;letter-spacing:1px;}#ovRowA,#ovRowB{background:#1d1f24;border-radius:8px;}#ovRowA:hover,#ovRowB:hover{background:#23262d;}#ovKey{color:#989ba2;font-size:13px;background:transparent;}#ovVal{color:#f2f4f7;font-size:14px;font-weight:600;background:transparent;}#ovRowTitle{color:#f2f4f7;font-size:13px;font-weight:600;background:transparent;}#ovRowSub{color:#989ba2;font-size:11px;background:transparent;}#ovRowDim{color:#61646d;font-size:11px;background:transparent;}#ovSelRow{background:#262a31;border-left:2px solid #45b4ef;border-radius:8px;}#ovRowIcon{background:transparent;border:none;color:#9fb0c8;font-size:14px;}#ovRowIcon:hover{color:#ff5b6e;}#ovIcon{background:transparent;border:none;color:#989ba2;font-size:15px;}#ovIcon:hover{color:#f2f4f7;}#ovBadgeDry{color:#1a1400;background:#f5c542;border-radius:6px;padding:1px 7px;font-size:10px;font-weight:700;}#ovBadgeWet{color:#04222e;background:#4ec3ff;border-radius:6px;padding:1px 7px;font-size:10px;font-weight:700;}#ovStatKey{color:#6e727b;font-size:10px;font-weight:700;letter-spacing:1px;background:transparent;}#ovStatVal{color:#f2f4f7;font-size:14px;font-weight:600;background:transparent;}#ovColCap{color:#9aa3b2;font-size:10px;font-weight:700;letter-spacing:1px;background:transparent;}#ovColCapSel{color:#55ff7f;font-size:9px;font-weight:700;letter-spacing:1px;background:transparent;}#ovColCapCmp{color:#8b7bff;font-size:9px;font-weight:700;letter-spacing:1px;background:transparent;}#ovTheo{color:#45b4ef;font-size:11px;font-weight:700;letter-spacing:.5px;background:transparent;}#ovTabOn{background:rgba(255,255,255,0.22);border:none;border-left:2px solid #ff1d43;border-radius:10px;}#ovTabOff{background:rgba(255,255,255,0.10);border:none;border-radius:10px;}#ovTabOff:hover{background:rgba(255,255,255,0.16);}#ovTabTxt{color:#f2f4f7;font-size:11px;font-weight:700;letter-spacing:.5px;background:transparent;}#ovStintSum{color:#cfd6e2;font-size:12px;background:transparent;}#ovTabOff #ovTabTxt{color:#989ba2;}#ovRefRow{background:rgba(245,197,66,0.13);border:none;border-radius:10px;}#ovRefEmpty{background:#111214;border:1px dashed #2a2c30;border-radius:10px;}#ovRefTag{color:#f5c542;font-size:12px;font-weight:800;letter-spacing:1px;background:transparent;}#ovRefDrv{color:#f5f5f5;font-size:13px;font-weight:600;background:transparent;}#ovRefTime{color:#f5c542;font-size:14px;font-weight:700;background:transparent;}#ovRefSec{color:#9c8a4e;font-size:12px;background:transparent;}#ovRefNone{color:#6e727b;font-size:12px;background:transparent;}#ovRefSub{color:#7c7148;font-size:10px;background:transparent;padding-left:12px;}#ovRefInfo{color:#cfd2d8;font-size:11px;background:transparent;padding-left:12px;}#ovWrRow{background:rgba(57,182,232,0.13);border:none;border-radius:10px;}#ovWrTag{color:#39b6e8;font-size:12px;font-weight:800;letter-spacing:1px;background:transparent;}#ovWrDrv{color:#f5f5f5;font-size:13px;font-weight:600;background:transparent;}#ovWrTime{color:#39b6e8;font-size:14px;font-weight:700;background:transparent;}#ovWrSec{color:#5f93ad;font-size:12px;background:transparent;}#ovWrSub{color:#5f93ad;font-size:10px;background:transparent;padding-left:12px;}#ovLapRow{background:rgba(255,255,255,0.07);border:none;border-radius:6px;}#ovLapRow:hover{background:rgba(255,255,255,0.12);}#ovLapSel{background:rgba(255,255,255,0.17);border:none;border-radius:6px;}#ovLapDis{background:rgba(255,255,255,0.045);border:none;border-radius:6px;}#ovLapBestCard{background:rgba(255,29,67,0.20);border:none;border-radius:6px;}#ovLapNo{color:#ffffff;font-size:13px;font-weight:800;background:#e01a2b;border-radius:6px;}#ovLapInv{color:#aeb2ba;font-size:13px;font-weight:700;background:transparent;}#ovLapTime{color:#ffffff;font-size:16px;font-weight:700;background:transparent;}#ovLapBest{color:#ff5bb0;font-size:16px;font-weight:700;background:transparent;}#ovSec{color:#f2f4f7;font-size:13px;font-weight:600;background:transparent;}#ovSecBest{color:#ff3bd4;font-size:13px;font-weight:700;background:transparent;}#ovSecInv{color:#9aa0a8;font-size:13px;font-weight:600;background:transparent;}#ovTagOut{color:#d2d6dd;font-size:9px;font-weight:700;letter-spacing:1px;background:rgba(255,255,255,0.12);border-radius:4px;padding:1px 5px;margin-left:6px;}#ovTagTL{color:#ffcc33;font-size:9px;font-weight:700;letter-spacing:1px;background:rgba(255,210,58,0.16);border-radius:4px;padding:1px 5px;margin-left:6px;}#ovTagInv{color:#e06a6a;font-size:9px;font-weight:700;letter-spacing:1px;background:rgba(255,91,91,0.16);border-radius:4px;padding:1px 5px;margin-left:6px;}#ovTagPit{color:#f0a23a;font-size:9px;font-weight:700;letter-spacing:1px;background:rgba(255,160,58,0.16);border-radius:4px;padding:1px 5px;margin-left:6px;}#ovCkOff{background:transparent;border:1.5px solid #3a3d43;border-radius:4px;}#ovCkOff:hover{border-color:#60636c;}#ovCkSelOn{background:transparent;border:2px solid #55ff7f;border-radius:4px;}#ovCkCmpOn{background:transparent;border:2px solid #8b7bff;border-radius:4px;}#ovCkRefOn{background:transparent;border:2px solid #f5c542;border-radius:4px;}"""


_OV_BOARD_QSS_NEW = ""


class _AppPage(QWidget):
    """Schermata app (dopo il menu). Header in alto (back + pista | tab analisi |
    tempo sessione), corpo a due colonne (sessioni / board stint-giri), START in
    basso a destra. Sfondo radiale come il menu."""

    _TAB_OFF = ("QPushButton{background:rgba(255,255,255,0.07);color:#aeb6c4;"
                "font-family:'Archivo SemiExpanded';font-weight:700;font-size:11px;letter-spacing:.5px;"
                "border:none;border-radius:8px;padding:6px 13px;}"
                "QPushButton:hover{background:rgba(255,255,255,0.13);color:#e8eaee;}")
    _TAB_ON = ("QPushButton{background:rgba(255,255,255,0.20);color:#ffffff;"
               "font-family:'Archivo SemiExpanded';font-weight:700;font-size:11px;letter-spacing:.5px;"
               "border:none;border-left:2px solid #ff1d43;border-radius:8px;padding:6px 13px;}")
    _SUB_ON = ("QPushButton{background:rgba(255,255,255,0.20);color:#ffffff;"
               "font-family:'Archivo SemiExpanded';font-weight:700;font-size:11px;letter-spacing:.5px;"
               "border:none;border-bottom:2px solid #ff1d43;border-radius:8px;padding:6px 13px;}")
    _CHIP_OFF = ("QPushButton{background:rgba(255,255,255,0.07);color:#aeb6c4;"
                 "font-family:'Archivo SemiExpanded';font-weight:700;font-size:11px;letter-spacing:.5px;"
                 "border:none;border-radius:8px;padding:5px 11px;}"
                 "QPushButton:hover{background:rgba(255,255,255,0.13);color:#e8eaee;}")
    _CHIP_ON = ("QPushButton{background:rgba(255,255,255,0.20);color:#ffffff;"
                "font-family:'Archivo SemiExpanded';font-weight:700;font-size:11px;letter-spacing:.5px;"
                "border:none;border-bottom:2px solid #ff1d43;border-radius:8px;padding:5px 11px;}")
    _BTN_START = ("QPushButton{background:#ff1d43;color:#ffffff;font-family:'Archivo SemiExpanded';"
                  "font-weight:800;font-size:15px;letter-spacing:1px;border:none;"
                  "border-radius:10px;padding:0 24px;}"
                  "QPushButton:hover{background:#ff3b5d;}")
    _BTN_STOP = ("QPushButton{background:rgba(255,255,255,0.16);color:#ffffff;"
                 "font-family:'Archivo SemiExpanded';font-weight:800;font-size:15px;letter-spacing:1px;"
                 "border:none;border-radius:10px;padding:0 24px;}"
                 "QPushButton:hover{background:rgba(255,255,255,0.24);}")

    _PHOTO_DIR = Path(__file__).resolve().parent.parent / "assets" / "trackcards"
    _PHOTO_CACHE = {}

    def _build_guide(self):
        """Tab Guide: documentazione approfondita e scrollabile (IT + EN)."""
        from PySide6.QtWidgets import QScrollArea
        html = '<h1 style="font-family:\'Archivo SemiExpanded\';color:#f5c542;font-size:27px;font-weight:800;margin:0 0 2px;">LMU Telemetry Pro &mdash; Guide</h1><p style="font-family:\'Archivo SemiExpanded\';color:#8a90a0;font-size:14px;margin:0 0 18px;">Guida d\'uso completa &middot; Full user guide</p>\n<h2 style="font-family:\'Archivo SemiExpanded\';color:#f5c542;font-size:20px;font-weight:800;margin:24px 0 8px;border-bottom:1px solid #283246;padding-bottom:4px;">🇮🇹 Guida completa</h2>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">1 · Avvio automatico</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">Avvia <b>Le Mans Ultimate</b> e vai in pista come al solito. Non serve premere niente: l\'app rileva la sessione, la <b>crea e apre da sola</b> e ti porta dentro la sessione live giusta (pista, layout e classe corretti). Lo sfondo mostra la <b>foto del circuito</b> corrente.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">Mentre giri, ogni giro completato compare nel board con tempo, settori e validità. I giri non validi (outlap, rientro box, track limits) non entrano in telemetria.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">2 · Menu circuiti</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">Dalla home scegli <b>pista e layout</b>: ogni card mostra la foto del tracciato. La lista è scrollabile. Se hai già sessioni su quella pista le ritrovi qui.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">3 · Overview — sessioni e board</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">A <b>sinistra</b> le tue <b>sessioni</b>: ogni card ha le <b>5 icone meteo previste</b> (dalla partenza al traguardo), auto, classe e tempo migliore. Le card si filtrano per pista, layout e classe.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">A <b>destra</b> il <b>board</b>: stint, giri e tempi. <b>Clicca il cerchietto di un giro</b> per selezionarlo (SEL): la telemetria si carica su quel giro. Seleziona un <b>secondo giro</b> come confronto (CMP): viene sovrapposto.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Wet/Dry</b>: quando selezioni un giro, i giri di condizione opposta (asciutto↔bagnato) si <b>oscurano</b> e non sono selezionabili, così confronti solo condizioni omogenee.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">4 · Telemetry — i grafici</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">In alto la barra dei <b>sotto-tab</b>: <b>Worksheet</b> (più canali insieme), <b>Speed / Steering / Gear / RPM</b>, <b>Tyres</b>, <b>Brakes</b>, <b>Suspension</b>, <b>Pedals</b>, <b>G-G</b>, <b>Aids</b> (TC/ABS/bias), <b>Delta</b>, e i consumi <b>VE / Fuel / Hybrid</b>.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Scrub</b>: muovi il mouse <b>sopra un grafico</b> (o sulla mappa) → una linea verticale segue il puntatore, la <b>mappa evidenzia il punto</b> e leggi i <b>valori esatti</b> in quel punto del giro.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Cursori A/B (shift-click)</b>: <b>shift-click</b> sul grafico piazza il cursore <span style=\'color:#f0a23a\'><b>A</b></span> (arancione), un secondo shift-click il cursore <span style=\'color:#36c5d0\'><b>B</b></span> (ciano). In alto a destra compaiono <b>ΔX</b> (distanza in metri tra A e B) e <b>Δ valore</b> nel canale (es. Δkm/h, Δ°C). I cursori A/B e lo <b>zoom</b> sono <b>sincronizzati su tutti i grafici</b> contemporaneamente.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Legenda cliccabile</b>: i pallini SEL/CMP/REF in alto al grafico cambiano colore della traccia. Il giro più veloce è evidenziato.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">5 · Tyres — gomme per ruota</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">Scegli la <b>ruota</b> (FL/FR/RL/RR) cliccando l\'angolo, e lo <b>strato</b> con i tab <b>Surface / Carcass / Inner / Press / Wear</b>. Il grafico mostra il canale scelto lungo il giro per quella ruota.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">Sotto trovi i due grafici meteo continui <b>Asfalto °C</b> e <b>Rain %</b> (stessa larghezza e altezza): temperatura pista e pioggia lungo il giro.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">6 · G-G e mappa</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>G-G</b>: il diagramma delle accelerazioni laterali/longitudinali (quanto stai sfruttando il grip). La <b>mappa</b> a destra mostra il tracciato col punto evidenziato dallo scrub e il confronto SEL vs CMP.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">7 · REF — riferimento</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">Confronta il giro selezionato con un <b>riferimento</b>: il tuo miglior giro <b>LOCAL</b> oppure la <b>community ONLINE</b>, abbinato per <b>classe + pista + condizione</b>. Colori: <span style=\'color:#f5c542\'><b>oro = asciutto</b></span>, <span style=\'color:#4aa3df\'><b>blu = bagnato</b></span>. Se l\'online coincide col tuo tempo, la card doppia viene nascosta.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">8 · Community · Team · Engineer</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Community</b>: tempi di riferimento per pista e classe. <b>Team</b>: <b>esporta/importa</b> sessioni in un file zip per condividerle con la squadra. <b>Engineer</b>: ingegnere di pista assistito.</p>\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:18px 0 3px;font-weight:700;">9 · Engineer — l\'ingegnere di gara</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">L\'<b>Engineer</b> e\' un ingegnere di pista a voce: guarda la tua telemetria in tempo reale e ti parla via radio durante la gara, come un vero muretto. Parla in italiano. Funziona in <b>gara</b> (in prova/qualifica ti da i riferimenti sui settori).</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Briefing iniziale</b>: a inizio gara calcola la <b>strategia</b> &mdash; giri totali, stint, numero di soste, autonomia di benzina o energia. Sulle GT3 il consumo lo ricava dal <b>consumo reale</b> della tua macchina, non da stime.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Durante la gara</b>: controllo passo e consumi, <b>dove perdi</b> (settori rispetto al tuo miglior tempo), <b>report di gestione periodico</b> (gomme, carburante), e <b>chiamata box intelligente</b> &mdash; gomme al 65%, foratura, benzina in esaurimento, penalita\', danni.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Pioggia</b> (dove serve davvero): ti avvisa appena inizia, ti chiama dentro per le wet in base a <b>quanto e\' bagnata la pista sotto le ruote</b>, ti dice quanta benzina mettere alla sosta, gestisce la temperatura delle wet, ti segnala il <b>settore piu\' bagnato</b> e la <b>finestra per le slick</b> quando si forma la linea asciutta.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Raccomandazione gomme</b>: costruita dalla superficie sotto le tue ruote &mdash; linea asciutta &rarr; slick, bagnato &rarr; wet. Se decidi di <b>restare fuori</b> con le wet che asciugano, l\'ingegnere prende atto della tua scelta e smette di insistere, passando a supportarti.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Gap e bandiere</b>: distacco su chi e\' davanti e dietro, segnale di <b>undercut</b> quando il rivale rientra ai box, bandiere gialle e full course yellow.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Impara dalle tue sessioni</b>: per ogni pista e classe, separando asciutto e bagnato, memorizza <b>consumo per giro</b>, <b>degrado gomme</b>, <b>miglior tempo e settori</b>. Piu\' giri puliti accumuli, piu\' diventa preciso: sa gia\' come si comporta la pista <i>per te</i>, e affina coi dati della gara in corso.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Ritmo radio</b>: aggiornamenti regolari senza martellare, e le chiamate critiche (box, gialla) hanno sempre la precedenza.</p>\n<hr style="border:none;border-top:1px solid #283246;margin:26px 0;">\n<h2 style="font-family:\'Archivo SemiExpanded\';color:#f5c542;font-size:20px;font-weight:800;margin:24px 0 8px;border-bottom:1px solid #283246;padding-bottom:4px;">🇬🇧 Full guide</h2>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">1 · Auto start</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">Launch <b>Le Mans Ultimate</b> and go on track as usual. No buttons needed: the app detects the session, <b>creates and opens it automatically</b> and focuses the right live session (track, layout and class). The background shows the current <b>circuit photo</b>.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">As you drive, each completed lap appears on the board with time, sectors and validity. Invalid laps (outlap, pit return, track limits) are excluded from telemetry.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">2 · Circuit menu</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">From the home screen pick <b>track and layout</b>: each card shows the circuit photo. The list scrolls. Existing sessions for that track show up here.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">3 · Overview — sessions & board</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Left</b>: your <b>sessions</b>. Each card has the <b>5 forecast icons</b> (start to finish), car, class and best time, filtered by track, layout and class.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Right</b>: the <b>board</b> with stints, laps and times. <b>Click a lap\'s circle</b> to select it (SEL): telemetry loads for that lap. Pick a <b>second lap</b> as compare (CMP) to overlay it.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Wet/Dry</b>: when a lap is selected, laps of the opposite condition (dry↔wet) are <b>dimmed</b> and not selectable, so you only compare like-for-like.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">4 · Telemetry — the charts</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">Top <b>sub-tabs</b>: <b>Worksheet</b> (several channels at once), <b>Speed / Steering / Gear / RPM</b>, <b>Tyres</b>, <b>Brakes</b>, <b>Suspension</b>, <b>Pedals</b>, <b>G-G</b>, <b>Aids</b> (TC/ABS/bias), <b>Delta</b>, plus <b>VE / Fuel / Hybrid</b>.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Scrub</b>: move the mouse <b>over a chart</b> (or the map) → a vertical line follows the pointer, the <b>map highlights the point</b> and you read the <b>exact values</b> at that spot on the lap.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>A/B cursors (shift-click)</b>: <b>shift-click</b> on a chart sets cursor <span style=\'color:#f0a23a\'><b>A</b></span> (orange), a second shift-click sets <span style=\'color:#36c5d0\'><b>B</b></span> (cyan). Top-right shows <b>ΔX</b> (distance in metres between A and B) and the <b>Δ value</b> in the channel (e.g. Δkm/h, Δ°C). A/B cursors and <b>zoom</b> are <b>synced across all charts</b> at once.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Clickable legend</b>: the SEL/CMP/REF dots above the chart recolour the traces. The fastest lap is highlighted.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">5 · Tyres — per wheel</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">Pick the <b>wheel</b> (FL/FR/RL/RR) by clicking its corner, and the <b>layer</b> with the <b>Surface / Carcass / Inner / Press / Wear</b> tabs. The chart shows the chosen channel along the lap for that wheel.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">Below are the two continuous weather charts <b>Track °C</b> and <b>Rain %</b> (same width and height): track temperature and rain along the lap.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">6 · G-G & map</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>G-G</b>: the lateral/longitudinal acceleration diagram (how much grip you\'re using). The <b>map</b> on the right shows the track with the scrub point and SEL vs CMP.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">7 · REF — reference</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">Compare the selected lap with a <b>reference</b>: your best <b>LOCAL</b> lap or the <b>ONLINE community</b>, matched by <b>class + track + condition</b>. Colours: <span style=\'color:#f5c542\'><b>gold = dry</b></span>, <span style=\'color:#4aa3df\'><b>blue = wet</b></span>. If the online time equals yours, the duplicate card is hidden.</p>\n\n<h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:16px 0 3px;font-weight:700;">8 · Community · Team · Engineer</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Community</b>: reference times by track and class. <b>Team</b>: <b>export/import</b> sessions as a zip to share with your team. <b>Engineer</b>: assisted race engineer.</p><h3 style="font-family:\'Archivo SemiExpanded\';color:#eef1f6;font-size:16px;margin:18px 0 3px;font-weight:700;">9 · Engineer — your race engineer</h3><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;">The <b>Engineer</b> is a voice race engineer: it watches your live telemetry and talks to you over the radio during the race, like a real pit wall. Works during the <b>race</b> (in practice/qualifying it gives you sector references).</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Opening briefing</b>: at race start it works out the <b>strategy</b> &mdash; total laps, stints, number of pit stops, fuel or energy range. On GT3s the consumption is taken from your car\'s <b>real fuel burn</b>, not from estimates.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>During the race</b>: pace and consumption checks, <b>where you\'re losing time</b> (sectors vs your best lap), a <b>periodic management report</b> (tyres, fuel), and <b>smart pit calls</b> &mdash; tyres at 65%, puncture, fuel running low, penalties, damage.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Rain</b> (where it really matters): it warns you as it starts, calls you in for wets based on <b>how wet the track is under your wheels</b>, tells you how much fuel to take at the stop, manages wet-tyre temperature, flags the <b>wettest sector</b> and the <b>slick window</b> as the dry line forms.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Tyre recommendation</b>: built from the surface under your wheels &mdash; dry line &rarr; slicks, wet &rarr; wets. If you choose to <b>stay out</b> on drying wets, the engineer acknowledges your call, stops nagging and switches to supporting you.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Gaps and flags</b>: gap to the car ahead and behind, an <b>undercut</b> prompt when a rival pits, yellow flags and full course yellow.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>It learns from your sessions</b>: per track and class, dry and wet kept separate, it stores <b>fuel per lap</b>, <b>tyre degradation</b>, <b>best lap and sectors</b>. The more clean laps you bank, the sharper it gets: it already knows how the track behaves <i>for you</i>, and refines with the current race data.</p><p style="font-family:\'Archivo SemiExpanded\';color:#cdd2dc;font-size:15px;line-height:1.6;margin:0 0 9px;"><b>Radio rhythm</b>: regular updates without spamming, and critical calls (box, yellow) always take priority.</p>\n'
        lab = QLabel(html)
        lab.setFont(QFont("Archivo SemiExpanded"))
        lab.setTextFormat(Qt.RichText)
        lab.setWordWrap(True)
        lab.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        lab.setMaximumWidth(760)
        lab.setStyleSheet("background:#0c1320;border:1px solid #1e2940;"
                          "border-radius:14px;padding:28px 34px;color:#cdd2dc;"
                          "font-family:'Archivo SemiExpanded';")
        host = QWidget(); host.setStyleSheet("background:transparent;")
        hl = QHBoxLayout(host); hl.setContentsMargins(20, 18, 20, 26)
        hl.addStretch(1); hl.addWidget(lab, 0, Qt.AlignTop); hl.addStretch(1)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        sc.setWidget(host)
        return sc


    def _circuit_photo(self):
        """Sfondo dell'app: UNA sola immagine fissa assets/overview.jpg (se presente),
        al posto delle foto per-circuito. Se il file manca, torna alla foto del
        circuito corrente (assets/trackcards/<bgkey>.*)."""
        # 1) immagine unica overview.jpg (cache dedicata)
        if "_overview_bg" not in _AppPage._PHOTO_CACHE:
            _ov = _AppPage._PHOTO_DIR.parent / "overview.jpg"
            _pm = QPixmap(str(_ov)) if _ov.exists() else None
            _AppPage._PHOTO_CACHE["_overview_bg"] = \
                _pm if (_pm is not None and not _pm.isNull()) else None
        if _AppPage._PHOTO_CACHE["_overview_bg"] is not None:
            return _AppPage._PHOTO_CACHE["_overview_bg"]
        # 2) fallback: foto del circuito corrente
        try:
            bgkey = self._track[1] if self._track else None
        except Exception:
            bgkey = None
        if not bgkey:
            return None
        if bgkey in _AppPage._PHOTO_CACHE:
            return _AppPage._PHOTO_CACHE[bgkey]
        pm = None
        for ext in ("jpg", "jpeg", "png", "webp"):
            _p = _AppPage._PHOTO_DIR / ("%s.%s" % (bgkey, ext))
            if _p.exists():
                _pm = QPixmap(str(_p))
                if not _pm.isNull():
                    pm = _pm
                    break
        _AppPage._PHOTO_CACHE[bgkey] = pm
        return pm

    def __init__(self, on_back=None, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QScrollArea
        self._track = None
        self._on_back = on_back
        self._sel_card = None
        self._con = None
        self._groups = {}
        self._stint_keys = []
        self._tyre4 = []
        self._stint_new = {}
        self._stint_new4 = {}
        self._cur_stint = None
        self._sel_lap = None
        self._cmp_lap = None
        self._cur_tab = "Tempi"
        self._armed = False
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 16)
        root.setSpacing(12)

        # legacy nascosto: costruisce data + tutte le tab reali + recorder
        self._legacy = _LegacyWindow()
        self._legacy._app_page = self          # backref: import team aggiorna la lista nuova
        self._legacy.hide()

        # ══ riga 1: back + pista | TOP TAB (centro) | tempo ══
        head = QHBoxLayout()
        head.setSpacing(14)
        self._back = QPushButton("arrow_back")
        self._back.setCursor(Qt.PointingHandCursor)
        self._back.setFixedWidth(34)
        self._BACK_QSS = (
            "QPushButton { font-family:'Material Icons'; font-size:26px; color:#ffffff;"
            " background:transparent; border:none; padding:0; }"
            "QPushButton:hover { color:rgba(255,29,67,1.0); }")
        self._BACK_QSS_LOCK = (
            "QPushButton { font-family:'Material Icons'; font-size:24px;"
            " color:#ff4d5a; background:transparent; border:none; padding:0; }"
            "QPushButton:hover { color:#ff8089; }")
        self._back.setStyleSheet(self._BACK_QSS)
        self._back.clicked.connect(self._back_clicked)
        self._title = QLabel("")
        # titoli pagina in ARCHIVO (font WEC originale), corsivo 900
        self._title.setStyleSheet(
            "color:#ffffff; font-family:'Archivo SemiExpanded';"
            " font-style:italic; font-weight:900;"
            " font-size:26px; background:transparent;")
        head.addWidget(self._back, 0, Qt.AlignVCenter)
        head.addWidget(self._title, 0, Qt.AlignVCenter)
        # nota LUCCHETTO: visibile SOLO a sessione armata (auto-focus attivo)
        self._lock_note = QLabel("")
        self._lock_note.setStyleSheet(
            "color:#ff4d5a; font-family:'Archivo SemiExpanded';"
            " font-weight:700; font-size:12px; background:transparent;")
        self._lock_note.hide()
        head.addWidget(self._lock_note, 0, Qt.AlignVCenter)
        head.addStretch(1)
        # top tab al centro
        self._cur_top = 0
        self._toptabs = []
        _topw = QWidget(); _topw.setStyleSheet("background:transparent;")
        _topl = QHBoxLayout(_topw); _topl.setContentsMargins(0, 0, 0, 0); _topl.setSpacing(8)
        for i, lab in enumerate(("Overview", "Telemetry", "Setups", "Overlay",
                                 "Community", "Team", "Engineer", "Debrief")):
            b = QPushButton(lab.upper())
            b.setCheckable(True); b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, ix=i: self._select_top(ix))
            b.setStyleSheet(self._TAB_OFF)
            _topl.addWidget(b); self._toptabs.append(b)
        # NELLE SESSIONI restano solo Overview / Telemetry / Setups. Overlay(3),
        # Community(4), Team(5) sono ora pagine standalone raggiungibili dalla
        # barra del menu, non tab di sessione. Engineer(6) si apre dal popup.
        # Il contenuto resta creato (raggiungibile via _select_top dal menu),
        # ma il BOTTONE tab e' nascosto.
        for _hid in (3, 4, 5, 6):
            try:
                self._toptabs[_hid].hide()
            except Exception:
                pass
        head.addWidget(_topw, 0, Qt.AlignVCenter)
        head.addStretch(1)
        # tempo sessione a destra
        self._sess_time = QLabel("")
        self._sess_time.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._sess_time.setStyleSheet(
            "color:#ffffff; font-family:'Archivo SemiExpanded'; font-weight:700; font-size:28px;"
            " background:transparent;")
        self._sess_time.setVisible(False)
        head.addWidget(self._sess_time, 0, Qt.AlignVCenter)
        # orologio fluido: la riga sessione si aggiorna OGNI SECONDO
        from PySide6.QtCore import QTimer as _QT
        self._sess_time_timer = _QT(self)
        self._sess_time_timer.timeout.connect(self._set_sess_time)
        self._sess_time_timer.start(1000)
        root.addLayout(head)

        # ══ riga 2: SUB-TAB a tutta larghezza (visibili su Telemetry) ══
        self._real_tabs = self._legacy.tabs
        self._real_tabs.setParent(None)
        self._real_tabs.tabBar().hide()
        self._real_tabs.setStyleSheet("QTabWidget::pane{border:none;background:transparent;}")
        self._subbar = QScrollArea()
        self._subbar.setWidgetResizable(True)
        self._subbar.setFrameShape(QFrame.NoFrame)
        self._subbar.setFixedHeight(44)
        self._subbar.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._subbar.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._subbar.setStyleSheet("QScrollArea{background:transparent;border:none;}"
                                   "QScrollBar:horizontal{height:0px;background:transparent;}"
                                   "QScrollBar::handle:horizontal{background:rgba(255,255,255,0.25);"
                                   "border-radius:3px;}"
                                   "QScrollBar::add-line,QScrollBar::sub-line{width:0;height:0;}")
        _sbw = QWidget(); _sbw.setStyleSheet("background:transparent;")
        _sbl = QHBoxLayout(_sbw); _sbl.setContentsMargins(0, 0, 0, 0); _sbl.setSpacing(8)
        self._subtabs = []
        for i in range(self._real_tabs.count()):
            b = QPushButton(self._real_tabs.tabText(i).upper())
            b.setCheckable(True); b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, ix=i: self._select_sub(ix))
            b.setStyleSheet(self._TAB_OFF)
            _sbl.addWidget(b); self._subtabs.append(b)
        _sbl.addStretch(1)
        self._subbar.setWidget(_sbw)
        root.addWidget(self._subbar)

        # ══ riga 3: stack pagine top-level (tutta pagina) ══
        self._top_stack = QStackedWidget()

        # — pagina OVERVIEW: due colonne (sessioni / board) —
        ov = QWidget(); ov.setStyleSheet("background:transparent;")
        ovl = QHBoxLayout(ov); ovl.setContentsMargins(0, 0, 0, 0); ovl.setSpacing(18)
        left = QVBoxLayout(); left.setSpacing(12)
        # ── filtri classe (pill stile sotto-tab) ──
        self._cls_filter = None          # None=ALL | HY/GT3/P2/P3/GTE | "TEAM"
        self._cls_chips = {}
        _CHIPS = [("ALL", None), ("HYPER", "HY"), ("LMGT3", "GT3"),
                  ("LMP2", "P2"), ("LMP3", "P3"), ("LMGTE", "GTE"), ("TEAM", "TEAM")]
        _chipbar = QWidget(); _chipbar.setStyleSheet("background:transparent;")
        _chl = QHBoxLayout(_chipbar); _chl.setContentsMargins(0, 0, 0, 2); _chl.setSpacing(6)
        for _lab, _tag in _CHIPS:
            cb = QPushButton(_lab); cb.setCursor(Qt.PointingHandCursor)
            cb.clicked.connect(lambda _=False, t=_tag: self._set_cls_filter(t))
            cb.setStyleSheet(self._CHIP_ON if _tag is None else self._CHIP_OFF)
            _chl.addWidget(cb); self._cls_chips[_tag] = cb
        _chl.addStretch(1)
        left.addWidget(_chipbar)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet(
            "QScrollArea { background:transparent; border:none; }"
            "QScrollBar:vertical { width:0px; background:transparent; margin:0; }"
            "QScrollBar::handle:vertical { background:rgba(255,255,255,0.25);"
            " border-radius:4px; min-height:30px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }")
        self._scroll.viewport().setStyleSheet("background:transparent;")
        self._list = QWidget(); self._list.setStyleSheet("background:transparent;")
        self._lv = QVBoxLayout(self._list)
        self._lv.setContentsMargins(0, 0, 6, 0)
        self._lv.setSpacing(10)
        self._lv.addStretch(1)
        self._scroll.setWidget(self._list)
        left.addWidget(self._scroll, 1)
        self._empty = QLabel("Nessuna sessione per questo layout")
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setStyleSheet("color:#aeb6c4; font-family:'Archivo SemiExpanded'; font-size:15px;"
                                  " background:transparent;")
        self._empty.hide()
        left.addWidget(self._empty)
        left_w = QWidget(); left_w.setLayout(left)
        left_w.setStyleSheet("background:transparent;")
        left_w.setMinimumWidth(488)
        ovl.addWidget(left_w, 2)

        self._right = QWidget()
        self._right.setObjectName("apBoardHost")
        self._right.setStyleSheet("#apBoardHost{background:transparent;}" + _OV_BOARD_QSS)
        rl = QVBoxLayout(self._right)
        rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(0)
        self.board = _LapBoard()
        self.board.setStyleSheet(_OV_BOARD_QSS)
        self.board.set_callbacks(self._board_on_stint, self._board_on_pick)
        self.board._scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollBar:vertical{width:0px;background:transparent;margin:0;}"
            "QScrollBar::handle:vertical{background:rgba(255,255,255,0.25);"
            "border-radius:4px;min-height:30px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}")
        from PySide6.QtGui import QPalette
        _vp = self.board._scroll.viewport()
        _vp.setAutoFillBackground(False)
        _pal = _vp.palette(); _pal.setColor(QPalette.Window, Qt.transparent)
        _vp.setPalette(_pal)
        self.board._laps_host.setAutoFillBackground(False)
        self.board.tabs_bar.setStyleSheet(_OV_BOARD_QSS)
        # ── il motore ORIGINALE disegna nel TUO board (collega vecchio a nuovo) ──
        try:
            self._legacy._overview.board = self.board
            self.board.set_callbacks(self._legacy._board_stint,
                                     self._legacy._board_pick)
            # card REF (oro) + ONLINE REF (blu) dal motore: sotto i giri
            _rc = getattr(self._legacy._overview, "ref_card", None)
            if _rc is not None:
                _rc.setMinimumWidth(0); _rc.setMaximumWidth(16777215)
                self.board._ref_slot.addWidget(_rc)
        except Exception:
            pass
        self._board_box = QWidget()
        bcl = QVBoxLayout(self._board_box)
        bcl.setContentsMargins(0, 0, 0, 0); bcl.setSpacing(6)
        bcl.addWidget(self.board.tabs_bar)
        bcl.addWidget(self.board.lb_summary)
        bcl.addWidget(self.board, 1)
        try:
            _dv = self.board.layout().itemAt(0).widget()
            if _dv is not None:
                _dv.hide()
        except Exception:
            pass
        self._board_hint = QLabel("Seleziona una sessione")
        self._board_hint.setAlignment(Qt.AlignCenter)
        self._board_hint.setStyleSheet("color:#aeb6c4; font-family:'Archivo SemiExpanded';"
                                       " font-size:15px; background:transparent;")
        self._board_box.setVisible(False)
        rl.addWidget(self._board_box, 1)
        rl.addWidget(self._board_hint, 1)
        ovl.addWidget(self._right, 3)

        self._top_stack.addWidget(ov)                       # 0 Overview (TUA grafica)
        self._top_stack.addWidget(self._real_tabs)          # 1 Telemetry
        self._top_stack.addWidget(self._legacy.settings_page)   # 2 Settings
        self._top_stack.addWidget(self._legacy._overlaytab)     # 3 Overlay (widget in pista)
        self._top_stack.addWidget(self._legacy._community)      # 4 Community
        self._top_stack.addWidget(self._legacy._teamtab)        # 5 Team
        self._top_stack.addWidget(self._legacy._engineer)       # 6 Engineer
        # 7 DEBRIEF (task #6, 23/07): pagina ingegnere read-only accanto a
        # Setups — refresh a ogni apertura del tab
        from telemetry.debrief import DebriefPage
        self._debrief_page = DebriefPage()
        self._top_stack.addWidget(self._debrief_page)
        # ORDINE LOGICO 0..6 per _select_top: le pagine nuove (Telemetry a
        # tutta pagina, OPTIONS) RUBANO widget da questo stack reimparentandoli
        # e gli indici del QStackedWidget scalano — l'indice fisso apriva la
        # pagina sbagliata (TEAMS -> Setup). Si risolve per WIDGET, mai per
        # posizione.
        self._top_pages = [ov, self._real_tabs, self._legacy.settings_page,
                           self._legacy._overlaytab, self._legacy._community,
                           self._legacy._teamtab, self._legacy._engineer,
                           self._debrief_page]
        root.addWidget(self._top_stack, 1)

        # nessun footer qui: il tasto START/STOP è UNICO (overlay in TelemetryWindow)

        self._select_sub(0)
        self._select_top(0)

        # ── refresh live durante la registrazione (logica dell'originale) ──
        self._was_live = False
        self._live_file = None
        from PySide6.QtCore import QTimer
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(1000)
        self._live_timer.timeout.connect(self._live_tick)
        self._live_timer.start()

    def _title_for_track(self, track):
        """Nome pista+layout come nel menu (es. 'Monza Curva Grande')."""
        lk = _track_layout_key(track)
        for e in _TRACKS:
            if _cmap_layout_key(e[4]) == lk:
                return e[2]
        stem = _track_logo_stem(track) or ""
        lab = _track_layout_label(track)
        return (stem + (" " + lab if lab else "")).strip() or stem

    def go_live(self):
        """Porta sulla sessione attiva (registrazione in corso): forza l'auto-jump
        originale sul circuito in uso e ricostruisce le card + titolo."""
        leg = getattr(self, "_legacy", None)
        if leg is None:
            return
        rec = getattr(leg, "_recorder", None)
        try:
            leg.stack.setCurrentWidget(leg._review_page)   # abilita live refresh
            if bool(rec) and rec.is_armed():
                leg._was_armed_live = False
                leg._live_jump_pending = True
                leg._live_refresh()                        # auto-jump sulla sessione attiva
        except Exception:
            pass
        self._reload_sessions()
        self._select_top(0)
        sessions = getattr(leg, "_sessions", []) or []
        cur = getattr(leg, "_cur_sess", -1)
        if 0 <= cur < len(sessions):
            m = sessions[cur]
            self._title.setText((self._title_for_track(m.get("track"))
                                or m.get("name")
                                or self._title.text()).upper())

    def _entry_for_track(self, track):
        """Card _TRACKS che corrisponde alla pista LMU in uso (layout incluso)."""
        if not track:
            return None
        stem = _track_logo_stem(track)
        lkey = _track_layout_key(track)
        for e in _TRACKS:                       # match esatto pista + layout
            if _cmap_layout_key(e[4]) == lkey and (stem is None or e[3] == stem):
                return e
        for e in _TRACKS:                       # fallback: stessa pista, layout qualunque
            if stem is not None and e[3] == stem:
                return e
        return None

    def show_live_session(self):
        """Wrapper: l'auto-focus live è gestito da _live_focus (autorità unica)."""
        try:
            self._live_focus()
        except Exception:
            pass

    def set_track(self, entry):
        self._track = entry            # (base, bgkey, name, logo, cmap)
        self._title.setText((entry[2] or "").upper() if entry else "")
        leg = getattr(self, "_legacy", None)
        if leg is not None and entry is not None:
            try:
                leg._track_filter = entry[3]                       # pista (stem logo)
                leg._layout_filter = _cmap_layout_key(entry[4])     # LAYOUT scelto (stem grezzo)
                leg._reload_sessions()                            # filtra pista + layout
                leg.stack.setCurrentWidget(leg._review_page)      # live refresh attivo
                if leg._sessions:
                    leg._user_picked_session = True
                    leg._on_session(0)                            # carica sessione 0 nel board
            except Exception:
                pass
        self._reload_sessions()
        self._select_top(0)
        # sfondo pagina sessione = foto del circuito corrente (su central, il
        # widget realmente visibile dietro la pagina)
        cbg = getattr(self, "_central_bg", None)
        if cbg is not None:
            try:
                cbg.set_photo(self._circuit_photo())
            except Exception:
                pass

    def _select_top(self, ix):
        self._cur_top = ix
        for j, b in enumerate(self._toptabs):
            on = (j == ix)
            b.setChecked(on)
            b.setStyleSheet(self._TAB_ON if on else self._TAB_OFF)
        if ix == 7:                  # DEBRIEF: dati freschi a ogni apertura
            try:
                self._debrief_page.refresh()
            except Exception:
                pass
        # per WIDGET, non per posizione: lo stack perde pezzi quando le
        # pagine nuove li montano altrove e gli indici scalano
        try:
            _w = self._top_pages[ix]
            _real = self._top_stack.indexOf(_w)
            if _real >= 0:
                self._top_stack.setCurrentIndex(_real)
        except Exception:
            self._top_stack.setCurrentIndex(ix)
        self._subbar.setVisible(ix == 1 and not getattr(self, "_menu_open", False))
        # colonna sonora: la pagina interna e' cambiata (es. Setups)
        _th = getattr(self, "_top_hook", None)
        if _th is not None:
            try:
                _th()
            except Exception:
                pass

    def _menu_mode(self, on):
        """Pagina aperta dalla barra del MENU (Overlay/Teams/Community/Setups):
        on=True nasconde TUTTA la barra tab di sessione (non e' una sessione).
        on=False = sessione normale: tornano Overview/Telemetry/Setups (le altre
        restano nascoste, sono solo dal menu). La freccia indietro resta sempre."""
        self._menu_open = bool(on)
        for j, b in enumerate(self._toptabs):
            try:
                b.setVisible((not on) and j in (0, 1, 2, 7))
            except Exception:
                pass

    def _select_sub(self, ix):
        for j, b in enumerate(self._subtabs):
            on = (j == ix)
            b.setChecked(on)
            b.setStyleSheet(self._SUB_ON if on else self._TAB_OFF)
        try:
            self._real_tabs.setCurrentIndex(ix)
        except Exception:
            pass

    def _refresh_overview(self):
        sel = self._sel_card is not None
        self._board_hint.setVisible(not sel)
        self._board_box.setVisible(sel)

    def _on_start(self):
        # arma/disarma il recorder REALE dell'app originale
        leg = getattr(self, "_legacy", None)
        if leg is not None:
            try:
                leg._toggle_rec()
            except Exception:
                pass
            rec = getattr(leg, "_recorder", None)
            self._armed = bool(rec) and rec.is_armed()
        else:
            self._armed = not self._armed
        self._sync_start_btn(self._armed, force=True)

    def _back_clicked(self):
        """A sessione ARMATA l'uscita e' bloccata (l'auto-focus ti
        riporterebbe comunque qui): il lucchetto lo DICHIARA, invece di
        sembrare un bug. Il click mostra il perche' in rosso.
        REGOLA 23/07: se questa pagina e' stata aperta DALLO stint
        (Setups), il back torna allo stint = DENTRO la sessione ->
        MAI bloccato."""
        if getattr(self, "_return_stint", False):
            if self._on_back:
                self._on_back()
            return
        if getattr(self, "_armed", False):
            try:
                self._lock_note.setText("SESSION LIVE — STOP TO EXIT")
                QTimer.singleShot(2500, lambda: (
                    self._lock_note.setText("SESSION LIVE")
                    if getattr(self, "_armed", False) else None))
            except Exception:
                pass
            return
        if self._on_back:
            self._on_back()

    def _apply_back_lock(self, armed):
        """Freccia indietro <-> LUCCHETTO con la nota rossa di stato."""
        try:
            if getattr(self, "_return_stint", False):
                armed = False        # pagina interna: freccia libera
            if armed:
                self._back.setText("lock")
                self._back.setStyleSheet(self._BACK_QSS_LOCK)
                self._back.setToolTip("Session live: exit locked (STOP to leave)")
                self._lock_note.setText("SESSION LIVE")
                self._lock_note.show()
            else:
                self._back.setText("arrow_back")
                self._back.setStyleSheet(self._BACK_QSS)
                self._back.setToolTip("")
                self._lock_note.hide()
        except Exception:
            pass

    def _sync_start_btn(self, armed, force=False):
        if (not force) and armed == getattr(self, "_armed", False):
            # stato invariato: aggiorna comunque l'hook (bottone unico) e basta
            hook = getattr(self, "_armed_hook", None)
            if hook is not None:
                try:
                    hook(armed)
                except Exception:
                    pass
            return
        self._armed = armed
        self._apply_back_lock(armed)    # freccia <-> lucchetto (uscita bloccata)
        self._apply_live_dim()          # dim/undim sessioni precedenti
        hook = getattr(self, "_armed_hook", None)
        if hook is not None:
            try:
                hook(armed)
            except Exception:
                pass

    def _live_tick(self):
        """Sync stato recorder (bottone/banner) + UNA SOLA autorità di auto-focus
        sulla sessione live (_live_focus)."""
        leg = getattr(self, "_legacy", None)
        rec = getattr(leg, "_recorder", None) if leg else None
        armed = bool(rec) and rec.is_armed()
        self._sync_start_btn(armed)
        bhook = getattr(self, "_banner_hook", None)
        if bhook is not None and rec is not None:
            try:
                _k, _t = rec.banner(); bhook(_k, _t)
            except Exception:
                pass
        if not armed:
            self._was_live = False
            self._live_focused = None
            return
        self._was_live = True
        self._set_sess_time()                 # timer sessione (rimanente)
        self._live_focus()                    # autorità unica

    def _live_focus(self):
        """AUTORITÀ UNICA dell'auto-focus. Porta e tiene l'app sulla sessione che
        il recorder sta scrivendo: pista + layout + classe + card live caricata.
        Deriva tutto dal recorder (file/pista/classe), non da stati intermedi.
        Idempotente: se è già centrata sulla live, non rifà nulla (lascia che i
        giri si aggiornino)."""
        import os
        leg = getattr(self, "_legacy", None)
        rec = getattr(leg, "_recorder", None) if leg else None
        if not (rec and rec.is_armed()):
            self._live_focused = None
            return
        lf = None
        track = None
        try:
            lf = rec.current_file()
            track = rec.current_track()
        except Exception:
            pass
        lfn = os.path.basename(lf) if lf else None
        if not lfn or not track:
            return                             # sessione non ancora pronta: aspetta
        # pagina stint gia' agganciata a QUESTA live: STOP (senza questo, i
        # filtri+reload rieseguiti ogni tick svuotavano il board e il poll lo
        # riempiva -> giri che apparivano e sparivano a flash)
        if (getattr(self, "_stint_live_hook", None) is not None
                and getattr(self, "_live_focused", None) == lfn):
            return
        # sfondo pagina sessione: imposta la foto del circuito anche in auto-avvio
        # (l'auto-focus non passa da set_track), derivandola dal track del recorder
        try:
            cbg = getattr(self, "_central_bg", None)
            if cbg is not None:
                _lk = _track_layout_key(track)
                _ent = next((e for e in _TRACKS if _cmap_layout_key(e[4]) == _lk), None)
                if _ent is None:
                    _st = _track_logo_stem(track)
                    _ent = next((e for e in _TRACKS if e[3] == _st), None)
                if _ent is not None:
                    self._track = _ent
                    cbg.set_photo(self._circuit_photo())
        except Exception:
            pass
        # già centrata su questa live e card caricata? non rifare
        if (getattr(self, "_live_focused", None) == lfn and self._sel_card is not None
                and os.path.basename((getattr(self._sel_card, "_meta", {}) or {})
                                     .get("file") or "") == lfn):
            return
        try:
            with open(_db.LOGS_DIR / "recorder.log", "a", encoding="utf-8") as f:
                import time as _t
                f.write(_t.strftime("%H:%M:%S ") +
                        "LIVE-FOCUS track=%r file=%r\n" % (track, lfn))
        except Exception:
            pass
        # filtri pista/layout (chiavi canoniche, come il click manuale)
        try:
            leg._track_filter = _track_logo_stem(track)
            leg._layout_filter = _track_layout_key(track)
            leg._reload_sessions()
            leg.stack.setCurrentWidget(leg._review_page)
        except Exception:
            pass
        sessions = list(getattr(leg, "_sessions", []) or [])
        live = next((s for s in sessions
                     if os.path.basename(s.get("file") or "") == lfn), None)
        if live is None:
            return                             # file non ancora in lista: ritenta dopo
        # NUOVA pagina stint: aggancia la live DIRETTAMENTE dal motore
        # (le card _lv dell app vecchia sono vuote senza set_track: il vecchio
        # percorso non partiva mai -> pagina stint restava vuota)
        hk = getattr(self, "_stint_live_hook", None)
        if hk is not None:
            if getattr(self, "_live_focused", None) != lfn:
                try:
                    _idx = sessions.index(live)
                    # meta appena creato: la pista puo' non essere ancora
                    # flushata -> prendila dal recorder (senno' le pagine
                    # del back restavano vuote, aggancio one-shot)
                    if not (live.get("track") or "").strip() and track:
                        live = dict(live)
                        live["track"] = track
                    leg._user_picked_session = True
                    leg._on_session(_idx)      # apre il file live nel board
                    hk(live)                   # titolo/bg/mount pagina stint
                    self._live_focused = lfn
                except Exception:
                    pass
            return                             # pagina nuova = unica autorita
        # filtro classe = classe della live (sennò un chip rimasto la nasconde)
        try:
            self._cls_filter = class_tag(live.get("car_class") or "") or None
        except Exception:
            self._cls_filter = None
        try:
            self._title.setText((self._title_for_track(track)
                                 or track or "").upper())
        except Exception:
            pass
        self._reload_sessions()
        # seleziona la card live ESATTAMENTE come un click manuale -> carica il board
        card = None
        for j in range(self._lv.count() - 1):
            w = self._lv.itemAt(j).widget()
            if isinstance(w, _SessionCard) and \
                    os.path.basename((getattr(w, "_meta", {}) or {}).get("file") or "") == lfn:
                card = w
                break
        if card is not None:
            self._sel_card = None              # forza il caricamento
            try:
                self._select_card(card)
            except Exception:
                pass
            self._live_focused = lfn
            # avvisa la finestra: pagina STINT nuova aggiornata sulla live
            hk = getattr(self, "_stint_live_hook", None)
            if hk is not None:
                try:
                    hk(live)
                except Exception:
                    pass
        self._select_top(0)
        self._apply_live_dim()          # live agganciata: dima le precedenti

    def _focus_active_card(self, f):
        for i in range(self._lv.count()):
            w = self._lv.itemAt(i).widget()
            if isinstance(w, _SessionCard) and w._meta.get("file") == f:
                if self._sel_card is not None and self._sel_card is not w:
                    self._sel_card.setSelected(False)
                w.setSelected(True)
                self._sel_card = w
                self._load_board(w._meta, live=False)
                self._select_top(0)          # mostra l'Overview (board live)
                return

    def _reload_sessions(self):
        # togli le card vecchie (lascia lo stretch finale)
        while self._lv.count() > 1:
            it = self._lv.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        self._sel_card = None
        leg = getattr(self, "_legacy", None)
        self._update_cls_chips()             # mostra solo i tag realmente presenti
        sessions = list(getattr(leg, "_sessions", []) or []) if leg else []
        try:
            from core.classes import class_tag as _ctag
        except Exception:
            _ctag = lambda x: ""
        filt = getattr(self, "_cls_filter", None)
        show_user = filt != "TEAM"
        n_user = 0
        for i, m in enumerate(sessions):
            if not show_user:
                continue
            if filt and filt != "TEAM" and _ctag(m.get("car_class") or "") != filt:
                continue
            card = _SessionCard(m, on_export=self._export_session,
                                on_delete=self._delete_session)
            card._sess_idx = i               # indice ORIGINALE (il filtro non lo sposta)
            card.on_click = self._select_card
            self._lv.insertWidget(self._lv.count() - 1, card)
            n_user += 1
        # ── sessioni TEAM importate (in coda, etichetta "team", cliccabili) ──
        team = list(getattr(leg, "_team_sessions", []) or []) if leg else []
        n_team = 0
        for ti, tm in enumerate(team):
            if filt and filt != "TEAM" and _ctag(tm.get("car_class") or "") != filt:
                continue
            tm = dict(tm); tm["team_session"] = True
            tcard = _SessionCard(tm, on_delete=self._delete_team_card)
            tcard._team_idx = ti
            tcard.on_click = self._select_team_card
            self._lv.insertWidget(self._lv.count() - 1, tcard)
            n_team += 1
        _has = bool(n_user) or bool(n_team)
        self._empty.setVisible(not _has)
        self._scroll.setVisible(_has)
        # rifletti la sessione selezionata dall'originale (es. la 0 dopo enter_circuit)
        cur = getattr(leg, "_cur_sess", -1) if leg else -1
        if cur >= 0 and not getattr(leg, "_viewing_team", False):
            for j in range(self._lv.count() - 1):
                w = self._lv.itemAt(j).widget()
                if isinstance(w, _SessionCard) and getattr(w, "_sess_idx", None) == cur:
                    w.setSelected(True)
                    self._sel_card = w
                    self._set_sess_time(w._meta)
                    break
        self._refresh_overview()
        self._apply_live_dim()          # card nuove: rispettano lo stato live

    def _apply_live_dim(self):
        """Sessione live in corso (recording) -> le card delle sessioni
        PRECEDENTI vanno a opacita' 40% e non cliccabili; la card della sessione
        live resta normale. A registrazione ferma tornano tutte cliccabili."""
        live = bool(getattr(self, "_armed", False))
        lfn = getattr(self, "_live_focused", None)
        sel = getattr(self, "_sel_card", None)
        for i in range(self._lv.count()):
            w = self._lv.itemAt(i).widget()
            if not isinstance(w, _SessionCard):
                continue
            is_live = bool(lfn) and (os.path.basename(
                (getattr(w, "_meta", {}) or {}).get("file") or "") == lfn)
            # la card ATTIVA (selezionata) o quella live restano NORMALI
            keep = is_live or (w is sel)
            try:
                w.set_dim(live and not keep)
            except Exception:
                pass

    def _set_sess_time(self, meta=None):
        try:
            leg = getattr(self, "_legacy", None)
            rec = getattr(leg, "_recorder", None) if leg else None
            m = {}
            if leg is not None and getattr(leg, "_overview", None) is not None:
                m = getattr(leg._overview, "_meta", {}) or {}
            rr = m.get("_race_remaining")
            # il tempo VIVO viene dal raw del recorder (fresco), non dalla
            # meta della board che si aggiorna ogni 2-3 s (orologio a scatti)
            try:
                _raw_live = (rec.latest() or {}).get("raw") or {} if rec else {}
                _rr_live = float(_raw_live.get("race_remaining") or 0.0)
                if _rr_live > 0:
                    rr = _rr_live
            except Exception:
                pass
            if rr and rec and rec.is_armed():       # SOLO sessione live
                styp = _ov_session_label(m.get("session_type")).upper()
                txt = styp + "    " + _ov_clock(rr)
                # LAP fatti/STIMATI + autonomia E(nergia)/F(uel) in giri,
                # dai dati live del recorder (strategy LMU + raw)
                try:
                    lt = rec.latest() or {}
                    raw = lt.get("raw") or {}
                    strat = lt.get("strat") or {}
                    laps_done = int(raw.get("laps_completed") or 0)
                    est = float(raw.get("est_lap") or 0.0)
                    rrs = float(raw.get("race_remaining") or 0.0)
                    if rrs > 0:
                        import math as _m
                        # stima PRECISA: passo del leader (la bandiera e' sua);
                        # fallback: est del gioco sul tuo giro
                        _tot_ldr = raw.get("race_laps_est")
                        if _tot_ldr:
                            tot = int(_tot_ldr)
                        elif est > 0:
                            tot = laps_done + int(_m.ceil(rrs / est))
                        else:
                            tot = 0
                        if tot > 0:
                            txt += "    LAP %d/%d" % (laps_done + 1, tot)
                    aut = strat.get("autonomy")
                    if aut:
                        _c = (strat.get("constraint") or "FUEL").upper()
                        txt += "    %s/%.1f" % ("E" if _c == "ENERGY" else "F",
                                                float(aut))
                except Exception:
                    pass
                self._sess_time.setText(txt)
                self._sess_time.setVisible(True)
            else:
                self._sess_time.setText("")
                self._sess_time.setVisible(False)
        except Exception:
            self._sess_time.setVisible(False)

    def _select_card(self, card):
        if self._sel_card is card:
            return
        if self._sel_card is not None:
            self._sel_card.setSelected(False)
        card.setSelected(True)
        self._sel_card = card
        leg = getattr(self, "_legacy", None)
        idx = getattr(card, "_sess_idx", None)
        if leg is not None and idx is not None:
            leg._user_picked_session = True
            try:
                leg._on_session(idx)     # motore ORIGINALE -> disegna nel TUO board
            except Exception:
                pass
        self._set_sess_time(card._meta)  # dopo on_session: meta completa con session_len
        self._refresh_overview()

    def _update_cls_chips(self):
        """Mostra una pill classe solo se ci sono sessioni di quel tag;
        TEAM solo se esistono sessioni team. ALL sempre. Se il filtro attivo
        sparisce, torna ad ALL."""
        leg = getattr(self, "_legacy", None)
        try:
            from core.classes import class_tag as _ctag
        except Exception:
            _ctag = lambda x: ""
        user = list(getattr(leg, "_sessions", []) or []) if leg else []
        team = list(getattr(leg, "_team_sessions", []) or []) if leg else []
        tags = set()
        for m in (user + team):
            t = _ctag(m.get("car_class") or "")
            if t:
                tags.add(t)
        has_team = bool(team)
        for tag, cb in self._cls_chips.items():
            if tag is None:
                cb.setVisible(True)
            elif tag == "TEAM":
                cb.setVisible(has_team)
            else:
                cb.setVisible(tag in tags)
        cur = getattr(self, "_cls_filter", None)
        if cur is not None:
            ok = (cur == "TEAM" and has_team) or (cur in tags)
            if not ok:
                self._cls_filter = None
                for t, cb in self._cls_chips.items():
                    cb.setStyleSheet(self._CHIP_ON if t is None else self._CHIP_OFF)

    def _set_cls_filter(self, tag):
        self._cls_filter = tag
        for t, cb in self._cls_chips.items():
            cb.setStyleSheet(self._CHIP_ON if t == tag else self._CHIP_OFF)
        self._reload_sessions()

    def _select_team_card(self, card):
        if self._sel_card is card:
            return
        if self._sel_card is not None:
            self._sel_card.setSelected(False)
        card.setSelected(True)
        self._sel_card = card
        leg = getattr(self, "_legacy", None)
        ti = getattr(card, "_team_idx", None)
        if leg is not None and ti is not None:
            try:
                leg._select_team_session(ti)   # apre la sessione team (REF/online congelati)
            except Exception:
                pass
        self._set_sess_time(card._meta)
        self._refresh_overview()

    def _delete_team_card(self, file):
        leg = getattr(self, "_legacy", None)
        team = list(getattr(leg, "_team_sessions", []) or []) if leg else []
        ti = next((i for i, t in enumerate(team) if t.get("file") == file), None)
        if leg is not None and ti is not None:
            try:
                leg._delete_team_session(ti)
            except Exception:
                pass
        self._reload_sessions()

    # ── board stint/giri (stessa funzione del vecchio) ──
    def _close_con(self):
        if self._con is not None:
            try:
                self._con.close()
            except Exception:
                pass
        self._con = None

    def _load_board(self, meta, live=False):
        prev_keys = list(self._stint_keys)
        prev_stint = self._cur_stint
        was_last = (prev_stint is not None and prev_keys
                    and prev_stint == prev_keys[-1])
        self._close_con()
        self._groups = {}
        self._stint_keys = []
        self._tyre4 = []
        if not live:
            self._sel_lap = None
            self._cmp_lap = None
        f = meta.get("file") if meta else None
        if not f:
            self._sess_time.setText("")
            self._refresh_overview()
            return
        _styp = _ov_session_label(meta.get("session_type"))
        _slen = _fmt_session_len(meta.get("session_len"))
        self._sess_time.setText(_styp + ((" " + _slen) if _slen else ""))
        try:
            from . import db
            self._con = db.open_session(f)
            laps = _rows(self._con, "SELECT * FROM laps ORDER BY lap")
        except Exception:
            self._con = None
            laps = []
        groups = {}
        if laps:
            base = min((L["stint"] or 1) for L in laps)
            for L in laps:
                groups.setdefault((L["stint"] or 1) - base + 1, []).append(L)
        try:
            mr = _rows(self._con, "SELECT compounds4 FROM session_meta WHERE id=1")
            comp = (mr[0]["compounds4"] if mr else "") or ""
            self._tyre4 = [x.strip() for x in comp.split(",")] if comp else []
        except Exception:
            self._tyre4 = []
        self._groups = groups
        self._stint_keys = sorted(groups)
        # gomma nuova/usata per stint (dai samples: MAX wear per ruota >=99.5 = nuova)
        self._stint_new = {}
        self._stint_new4 = {}
        for k in self._stint_keys:
            lk = groups.get(k, [])
            v = self._stint_start_new_from_samples(lk)
            self._stint_new[k] = True if v is None else bool(v)
            self._stint_new4[k] = self._stint_start_new4_from_samples(lk)
        if not self._stint_keys:
            self.board.update_board([], None, [], None, None, None, tyre4=self._tyre4)
            self._refresh_overview()
            if not live:
                self._legacy_open(f)
            return
        # scelta stint: live = segui l'ultimo (se stavi sull'ultimo o non valido);
        # manuale = primo stint
        if live:
            if was_last or (prev_stint not in self._stint_keys):
                self._cur_stint = self._stint_keys[-1]
            else:
                self._cur_stint = prev_stint
            cur_laps = [L["lap"] for L in self._groups.get(self._cur_stint, [])]
            if self._sel_lap not in cur_laps:
                self._sel_lap = None
            if self._cmp_lap not in cur_laps:
                self._cmp_lap = None
        else:
            self._cur_stint = self._stint_keys[0]
            self._sel_lap = None
            self._cmp_lap = None
        self._render_stint()
        self._refresh_overview()
        if not live:
            self._legacy_open(f)

    def _legacy_open(self, f):
        """Carica la sessione nell'app originale (alimenta le tab reali)."""
        leg = getattr(self, "_legacy", None)
        if leg is None:
            return
        try:
            leg._open_session_file(f)
        except Exception:
            pass

    def _legacy_stint(self):
        leg = getattr(self, "_legacy", None)
        if leg is None or self._cur_stint is None:
            return
        try:
            idx = self._stint_keys.index(self._cur_stint)
            leg._on_stint(idx)
        except Exception:
            pass

    def _legacy_lap(self, lap):
        leg = getattr(self, "_legacy", None)
        if leg is None or lap is None:
            return
        try:
            leg._set_lap_lazy(lap)
        except Exception:
            pass

    def _render_stint(self):
        laps = self._groups.get(self._cur_stint, [])
        best = _fastest_lap(laps) if laps else None
        sel = self._sel_lap if (self._sel_lap is not None) else best
        self.board.update_board(self._stint_keys, self._cur_stint, laps,
                                best, sel, self._cmp_lap, tyre4=self._tyre4,
                                stint_new=self._stint_new, stint_new4=self._stint_new4,
                                session_type=(getattr(self, "_meta", {}) or {}).get("session_type"),
                                car_class=(getattr(self, "_meta", {}) or {}).get("car_class"))
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._fit_laps_view)

    def _fit_laps_view(self):
        """Mostra max 12 giri VISIBILI, il resto scrollabile. 12 = le ~16 di
        prima meno 4, per far entrare ENTRAMBE le card REF sotto (LOCAL oro
        + ONLINE blu). NB: l'altezza va contata sulle righe COME RESE a
        schermo (w.height()), non sul sizeHint: il hint qui e' ~55px contro
        ~36 reali, ed e' il motivo per cui il vecchio tetto "10" mostrava
        in realta' 15-16 righe."""
        lv = self.board._laps_v
        rowh = 0
        rows = 0
        for i in range(lv.count()):
            w = lv.itemAt(i).widget()
            if w is not None:
                rows += 1
                if rowh <= 0:
                    h = w.height()
                    rowh = h if h > 10 else 0
        if rowh <= 0:
            # layout non ancora passato: riprova al giro dopo col dato vero
            for i in range(lv.count()):
                w = lv.itemAt(i).widget()
                if w is not None:
                    rowh = w.sizeHint().height()
                    break
            QTimer.singleShot(60, self._fit_laps_view)
        if rowh <= 0:
            rowh = 34
        sp = lv.spacing()
        n = max(1, min(12, rows))
        self.board._scroll.setFixedHeight(n * rowh + (n - 1) * sp + 6)
        self.board._scroll.verticalScrollBar().setValue(0)

    def _stint_start_new_from_samples(self, laps):
        """Integrità a inizio stint = MAX wear medio tra i sample (>=99.5 = nuova)."""
        if not laps or self._con is None:
            return None
        ids = [L.get("lap") for L in laps if L.get("lap") is not None]
        if not ids:
            return None
        qm = ",".join("?" * len(ids))
        try:
            rs = _rows(self._con,
                       "SELECT MAX((tyre_w_fl+tyre_w_fr+tyre_w_rl+tyre_w_rr)/4.0) AS mw "
                       "FROM samples WHERE lap IN (%s) AND tyre_w_fl IS NOT NULL" % qm, ids)
        except Exception:
            return None
        if not rs or rs[0].get("mw") is None:
            return None
        return rs[0]["mw"] >= 99.5

    def _stint_start_new4_from_samples(self, laps):
        """Per gomma: [FL,FR,RL,RR] bool (MAX wear ruota >=99.5 = nuova)."""
        if not laps or self._con is None:
            return None
        ids = [L.get("lap") for L in laps if L.get("lap") is not None]
        if not ids:
            return None
        qm = ",".join("?" * len(ids))
        try:
            rs = _rows(self._con,
                       "SELECT MAX(tyre_w_fl) a, MAX(tyre_w_fr) b, "
                       "MAX(tyre_w_rl) c, MAX(tyre_w_rr) d "
                       "FROM samples WHERE lap IN (%s) AND tyre_w_fl IS NOT NULL" % qm, ids)
        except Exception:
            return None
        if not rs or rs[0].get("a") is None:
            return None
        r0 = rs[0]
        return [(r0["a"] or 0) >= 99.5, (r0["b"] or 0) >= 99.5,
                (r0["c"] or 0) >= 99.5, (r0["d"] or 0) >= 99.5]

    def _board_on_stint(self, key):
        if key in self._stint_keys:
            self._cur_stint = key
            self._sel_lap = None
            self._cmp_lap = None
            self._render_stint()
            self._legacy_stint()

    def _board_on_pick(self, what):
        # switch sul giro: 1° = selezionato (verde), 2° = confronto (blu);
        # ri-cliccare uno toglie quello slot. Come l'originale.
        try:
            if not (isinstance(what, (tuple, list)) and what and what[0] == "lap"):
                return
            n = what[1]
            if n == self._sel_lap:
                self._sel_lap = None
            elif n == self._cmp_lap:
                self._cmp_lap = None
            elif self._sel_lap is None:
                self._sel_lap = n
            elif self._cmp_lap is None:
                self._cmp_lap = n
            else:
                self._cmp_lap = n
            self._render_stint()
            self._legacy_lap(n)
        except Exception:
            pass

    # ── export / elimina sessione (stessa logica del vecchio) ──
    def _export_session(self, file_path):
        leg = getattr(self, "_legacy", None)
        if leg is None or not file_path:
            return
        try:
            leg._export_session(file_path)   # ORIGINALE
        except Exception:
            pass

    def _delete_session(self, file_path):
        leg = getattr(self, "_legacy", None)
        if leg is None or not file_path:
            return
        idx = next((i for i, s in enumerate(getattr(leg, "_sessions", []) or [])
                    if s.get("file") == file_path), None)
        if idx is None:
            return
        try:
            leg._delete_session(idx)   # ORIGINALE: sgancia, elimina sidecar+file, ricarica
        except Exception:
            pass
        self._reload_sessions()        # rigenera le TUE card dalla lista aggiornata

    def paintEvent(self, e):
        # trasparente: lo sfondo (foto + radiali) lo dipinge SOLO central, così
        # l'immagine è unica e continua dietro pagina e footer.
        pass


class _PillButton(QPushButton):
    """Bottone pill disegnato a mano con ANTIALIASING (i bordi arrotondati via
    QSS in Qt escono sgranati). Stati: normale = bordo bianco; hover = sfondo
    bianco + testo rosso LMU; checked = sfondo rosso + testo bianco."""

    def __init__(self, text="", px=13, parent=None):
        super().__init__(text, parent)
        from PySide6.QtGui import QFont
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False
        f = QFont("Archivo SemiExpanded"); f.setPixelSize(px); f.setBold(True)
        try:
            f.setLetterSpacing(QFont.AbsoluteSpacing, 1.0)
        except Exception:
            pass
        self.setFont(f)
        self.setStyleSheet("background:transparent;border:none;")

    def enterEvent(self, e):
        self._hover = True; self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False; self.update(); super().leaveEvent(e)

    def sizeHint(self):
        fm = self.fontMetrics()
        return QSize(fm.horizontalAdvance(self.text()) + 40, 36)

    def paintEvent(self, e):
        from PySide6.QtGui import QColor, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(1.2, 1.2, -1.2, -1.2)
        rad = 8.0
        checked = self.isCheckable() and self.isChecked()
        if checked:
            p.setPen(Qt.NoPen); p.setBrush(QColor(255, 29, 67, 150))
            p.drawRoundedRect(r, rad, rad); tc = QColor("#ffffff")
        elif self._hover:
            p.setPen(Qt.NoPen); p.setBrush(QColor("#ffffff"))
            p.drawRoundedRect(r, rad, rad); tc = QColor("#ff1d43")
        else:
            p.setPen(QPen(QColor(255, 255, 255, 165), 1.4))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, rad, rad); tc = QColor("#ffffff")
        p.setPen(tc)
        p.drawText(self.rect(), Qt.AlignCenter, self.text())


def _real_map_load(track):
    """Mappa VERA per la pagina pista (rich. 24/07): cerca la _2026
    (ufficiale LMU o registrata) con match STRETTO — uguale, o nome
    file DENTRO il nome pagina; MAI il contrario, se no la National
    comparirebbe sulla pagina del GP. -> (pts, secs, pit, piazzole)."""
    import re
    import json
    from pathlib import Path

    def _nm(s):
        # decodifica #Uxxxx PRIMA del lower (24/07 sera: col lower
        # prima, '#U00f3' diventava '#u00f3' e la regex maiuscola non
        # decodificava piu' -> Jose Carlos Pace non matchava mai)
        s = re.sub(r"#U([0-9a-fA-F]{4})",
                   lambda m: chr(int(m.group(1), 16)), s or "").lower()
        for w in ("grand prix", "circuit", "international",
                  "raceway", "speedway", "the ", "2026"):
            s = s.replace(w, " ")
        return re.sub(r"[^a-z0-9]+", "", s)

    tn = _nm(track)
    if not tn:
        return None, [], [], []
    dirs = []
    try:
        from core.paths import USER_DIR as _UD
        dirs.append((_UD / "trackmap_auto", False))
    except Exception:
        _UD = None
    _setg = Path(__file__).resolve().parent.parent / "settings"
    dirs.append((_setg / "trackmap_auto", False))
    # RISERVA (rich. 24/07 sera): le 40 TinyPedal originali, SOLO per
    # questa pagina e SOLO a match ESATTO (una variante di layout non
    # deve mai comparire sulla pagina di un'altra); appena l'utente
    # gira sulla pista, l'ufficiale nella cartella utente VINCE
    dirs.append((_setg / "trackmap_backup_tinypedal", True))
    f = None
    for d, exact in dirs:
        if not d.exists():
            continue
        best = -1
        for sv in d.glob("*.svg"):
            sn = _nm(sv.stem)
            if not sn:
                continue
            if sn == tn:
                f = sv
                break
            if not exact and sn in tn and len(sn) > best:
                best = len(sn)
                f = sv
        if f is not None:
            break
    if f is None:
        return None, [], [], []
    txt = f.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r'points="([^"]+)"', txt)
    if not m:
        return None, [], [], []
    # coordinate del FILE cosi' come sono (24/07: negare la y qui
    # SPECCHIAVA la pista — senso di marcia ribaltato, utente non la
    # riconosceva; il file e' gia' nella chiralita' della mappa LMU)
    pts = []
    for tok in m.group(1).split():
        if "," in tok:
            a, b = tok.split(",")[:2]
            pts.append((float(a), float(b)))
    if len(pts) < 10:
        return None, [], [], []
    secs = []
    dm = re.search(r"<desc>([\d,\s]+)</desc>", txt)
    if dm:
        secs = [int(x) for x in re.findall(r"\d+", dm.group(1))][:2]
    pit = []
    pm = re.search(r'id="pitlane"[^>]*points="([^"]+)"', txt)
    if pm:
        for tok in pm.group(1).split():
            if "," in tok:
                a, b = tok.split(",")[:2]
                pit.append((float(a), float(b)))
    # PIAZZOLE dal payload GREZZO ufficiale ("piu' roba abbiamo
    # meglio e'"): coppie type>=2 = segmentini box/griglia ~3.9 m
    spots = []
    try:
        if _UD is not None:
            fn = _nm(f.stem)
            for j in (_UD / "trackmap_official").glob("*_lmu_raw.json"):
                if _nm(j.stem.replace("_lmu_raw", "")) == fn:
                    seg = {}
                    # grezzo in coordinate mondo: -z = y del file
                    for q in json.loads(j.read_text(encoding="utf-8")):
                        t = int(q.get("type", 0))
                        if t >= 2:
                            seg.setdefault(t, []).append(
                                (float(q["x"]), -float(q["z"])))
                    for pp in seg.values():
                        for i in range(0, len(pp) - 1, 2):
                            spots.append((pp[i], pp[i + 1]))
                    break
    except Exception:
        spots = []
    return pts, secs, pit, spots


_CENSO_FATTO9 = set()          # piste gia' tentate dall'auto-censimento


class _TrackMapView(QWidget):
    """Trackmap della pagina pista. Se esiste la mappa VERA _2026
    (ufficiale LMU) la disegna in scala reale con cordoli colorati,
    settori, corsia box, piazzole e curve col NOME (rich. 24/07);
    altrimenti la SVG stilizzata della card come prima."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._r = None
        self._rot = 0
        self._real = None
        self.setMinimumHeight(260)

    def set_real(self, track):
        """Prova la mappa VERA. -> True se trovata (niente fallback)."""
        self._real = None
        try:
            pts, secs, pit, spots = _real_map_load(track)
        except Exception:
            pts = None
        if not pts:
            self.update()
            return False
        # AUTO-CENSIMENTO curve (24/07 sera): pista senza censimento ->
        # un giro del rilevatore VERO del widget, che scrive il file
        # _curve.json SOLO se centra il conto ufficiale (guardia);
        # tentato una volta per pista a processo
        global _CENSO_FATTO9
        try:
            if track not in _CENSO_FATTO9:
                _CENSO_FATTO9.add(track)
                from data.track_corners import corners_for_track
                if not corners_for_track(track):
                    from widgets.map.widget import MapCanvas
                    mc = MapCanvas()
                    mc._track = track
                    mc._path = [(q[0], -q[1]) for q in pts]
                    mc._secs, mc._pit9 = secs, []
                    mc._turns_map()
                    mc.deleteLater()
        except Exception:
            pass
        self._r = None
        self._real = (track, pts, secs, pit, spots)
        self.update()
        return True

    def set_map(self, cmap, rot):
        self._r = None
        self._real = None
        try:
            if cmap and QSvgRenderer is not None:
                p = _OV_TRACKMAPS_SVG_DIR / cmap
                if p.exists():
                    rr = QSvgRenderer(str(p))
                    if rr.isValid():
                        self._r = rr
        except Exception:
            self._r = None
        self._rot = float(rot or 0.0)   # angolo libero dal tool
        self.update()

    def paintEvent(self, e):
        if self._real is not None:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing, True)
            try:
                self._paint_real(p)
            except Exception:
                pass
            p.end()
            return
        if self._r is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        W, H = float(self.width()), float(self.height())
        ds = self._r.defaultSize()
        _aw, _ah = float(max(1, ds.width())), float(max(1, ds.height()))
        rot = float(self._rot or 0.0)   # angolo LIBERO dal tool
        _th = math.radians(rot)
        _bw = abs(_aw * math.cos(_th)) + abs(_ah * math.sin(_th))
        _bh = abs(_aw * math.sin(_th)) + abs(_ah * math.cos(_th))
        _s = min(W * 0.95 / max(1.0, _bw), H * 0.95 / max(1.0, _bh))
        p.translate(W / 2.0, H / 2.0)
        if rot:
            p.rotate(rot)
        # colori ORIGINALI della SVG, come sulla card (niente tinta)
        self._r.render(p, QRectF(-_aw * _s / 2.0, -_ah * _s / 2.0,
                                 _aw * _s, _ah * _s))

    def _paint_real(self, p):
        """Stile ORIGINALE LMU (rich. 24/07 sera): linea bianca pulita,
        corsia box bianca spenta, tacche settori BLU + traguardo ROSSO
        (colori identici alla mappa in pista), curve T + nome. Niente
        asfalto disegnato, niente cordoli/piazzole qui."""
        import math
        from bisect import bisect_left
        from PySide6.QtGui import (QColor, QPen, QFont, QFontMetrics,
                                   QPainterPath)
        from PySide6.QtCore import QPointF, QRectF
        track, pts, secs, pit, _spots = self._real
        W, H = float(self.width()), float(self.height())
        mrg = 42.0                       # aria per le etichette nomi

        def _bb(seq):
            xs = [q[0] for q in seq]
            ys = [q[1] for q in seq]
            return min(xs), max(xs), min(ys), max(ys)

        x0, x1, y0, y1 = _bb(pts + pit if pit else pts)
        # ROTAZIONE SALVATA (rich. 24/07 sera): la STESSA che l'utente
        # ha messo sull'overlay (map_rotations.json) — cosi' la pagina
        # classifiche appare orientata come la mappa in pista. NB: qui
        # il piano e' (x, -z), l'overlay (x, z): stesso verso visivo =
        # angolo INVERTITO (-rot); MAI specchiata.
        _rot = 0.0
        try:
            import json as _js
            import re as _re
            from core.paths import USER_DIR as _UDr

            def _nmk(s):
                s = _re.sub(r"#U([0-9a-fA-F]{4})",
                            lambda m: chr(int(m.group(1), 16)),
                            s or "").lower()
                for w in ("grand prix", "circuit", "international",
                          "raceway", "speedway", "the ", "2026"):
                    s = s.replace(w, " ")
                return _re.sub(r"[^a-z0-9]+", "", s)

            _rd = _js.loads((_UDr / "map_rotations.json").read_text(
                encoding="utf-8"))
            # match TOLLERANTE come per la mappa: il nome del menu e la
            # chiave salvata dall'overlay (nome live) differiscono spesso
            # solo per 'Circuit'/'International' — l'esatto le mancava
            _tk = _nmk(track)
            _rv = _rd.get(track)
            if _rv is None and _tk:
                for _k, _v in _rd.items():
                    if _nmk(_k) == _tk:
                        _rv = _v
                        break
            _rot = -float(_rv or 0.0)
        except Exception:
            _rot = 0.0
        if abs(_rot) > 1e-4:
            cxr = (x0 + x1) / 2.0
            cyr = (y0 + y1) / 2.0
            crr = math.cos(_rot)
            srr = math.sin(_rot)

            def _rp(q):
                dx = q[0] - cxr
                dy = q[1] - cyr
                return (cxr + dx * crr - dy * srr,
                        cyr + dx * srr + dy * crr)

            pts = [_rp(q) for q in pts]
            pit = [_rp(q) for q in pit]
            x0, x1, y0, y1 = _bb(pts + pit if pit else pts)
        elif ((x1 - x0) > (y1 - y0)) != ((W - 2 * mrg) > (H - 2 * mrg)):
            # nessun verso salvato: auto-rotazione 90 solo per riempire
            pts = [(-q[1], q[0]) for q in pts]
            pit = [(-q[1], q[0]) for q in pit]
            x0, x1, y0, y1 = _bb(pts + pit if pit else pts)
        bw, bh = max(1.0, x1 - x0), max(1.0, y1 - y0)
        sc = min((W - 2 * mrg) / bw, (H - 2 * mrg) / bh)
        ox = (W - bw * sc) / 2.0 - x0 * sc
        oy = (H - bh * sc) / 2.0 - y0 * sc

        def T(q):
            return QPointF(q[0] * sc + ox, q[1] * sc + oy)

        # spessore: carreggiata reale, con pavimento per leggibilita'
        try:
            from data.track_info import width_for_track
            trk = max(7.0, width_for_track(track) * sc)
        except Exception:
            trk = 9.0
        P = [T(q) for q in pts]
        Pc = P + [P[0]]                  # anello chiuso

        def _pl(pen, seq):
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            path = QPainterPath(seq[0])
            for q in seq[1:]:
                path.lineTo(q)
            p.drawPath(path)

        n = len(pts)
        cum = [0.0]
        for i in range(1, n):
            cum.append(cum[-1] + math.hypot(pts[i][0] - pts[i - 1][0],
                                            pts[i][1] - pts[i - 1][1]))
        L = cum[-1] + math.hypot(pts[0][0] - pts[-1][0],
                                 pts[0][1] - pts[-1][1])

        def _norm(i):
            a = pts[(i - 1) % n]
            b = pts[(i + 1) % n]
            dx, dy = b[0] - a[0], b[1] - a[1]
            m = math.hypot(dx, dy) or 1.0
            return (-dy / m, dx / m)     # perpendicolare unitaria

        # ── pista: ombra leggera, poi corsia box bianca SPENTA
        #    (sopra l'ombra, sotto la pista), poi BIANCA originale ──
        _pl(QPen(QColor(0, 0, 0, 65), trk + 6.0,
                 Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin), Pc)
        if len(pit) > 4:
            _pl(QPen(QColor(255, 255, 255, 115), max(2.0, trk * 0.4),
                     Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin),
                [T(q) for q in pit])
        _pl(QPen(QColor(250, 250, 252, 255), trk,
                 Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin), Pc)

        used = []                        # rettangoli etichette occupati

        def _label(txt, cx, cy, col, small=False, force=False):
            f2 = QFont("Archivo SemiExpanded", 8 if small else 9)
            f2.setBold(True)
            m2 = QFontMetrics(f2)
            w = m2.horizontalAdvance(txt)
            h = m2.height()
            r = QRectF(cx - w / 2.0, cy - h / 2.0, w, h)
            # sempre DENTRO la tela (T6 Woodcote usciva a sinistra)
            if r.left() < 2:
                r.moveLeft(2)
            if r.right() > W - 2:
                r.moveRight(W - 2)
            if r.top() < 2:
                r.moveTop(2)
            if r.bottom() > H - 2:
                r.moveBottom(H - 2)
            if not force:                    # force: disegna comunque
                for u in used:
                    if r.intersects(u):
                        return False
            used.append(r.adjusted(-1, -1, 1, 1))
            p.setFont(f2)
            p.setPen(QColor(10, 12, 16, 200))
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                p.drawText(r.translated(dx, dy), Qt.AlignCenter, txt)
            p.setPen(col)
            p.drawText(r, Qt.AlignCenter, txt)
            return True
            return True

        def _tick(idx, col, ln, wd):
            nx, ny = _norm(idx)
            p.setPen(QPen(col, wd, Qt.SolidLine, Qt.FlatCap))
            p.drawLine(QPointF(P[idx].x() - nx * ln, P[idx].y() - ny * ln),
                       QPointF(P[idx].x() + nx * ln, P[idx].y() + ny * ln))
            return nx, ny

        # ── traguardo ROSSO + settori BLU (colori della mappa in pista) ──
        _tick(0, QColor("#ff3b30"), trk * 0.75, max(2.4, trk * 0.16))
        for si, idx in enumerate(secs[:2]):
            if not (0 < idx < n):
                continue
            nx, ny = _tick(idx, QColor("#00aaff"), trk * 0.7,
                           max(2.0, trk * 0.13))
            _label("S%d" % (si + 2), P[idx].x() + nx * (trk * 0.7 + 10),
                   P[idx].y() + ny * (trk * 0.7 + 10),
                   QColor("#00aaff"), small=True)

        # ── curve censite: SOLO NUMERO T1..Tn (rich. utente 24/07 sera:
        # niente nomi tipo Schumacher/Samsung, "sono solo le curve") ──
        try:
            from data.track_corners import corners_for_track
            mets = corners_for_track(track, L) or []
        except Exception:
            mets = []
        cx0 = sum(q.x() for q in P) / n
        cy0 = sum(q.y() for q in P) / n
        for tn_i, mt in enumerate(mets):
            a = bisect_left(cum, mt % L) % n
            nx, ny = _norm(a)
            # lato ESTERNO = quello che allontana dal baricentro
            if ((P[a].x() + nx) - cx0) ** 2 + ((P[a].y() + ny) - cy0) ** 2 \
                    < ((P[a].x() - nx) - cx0) ** 2 \
                    + ((P[a].y() - ny) - cy0) ** 2:
                nx, ny = -nx, -ny
            base_t = "T%d" % (tn_i + 1)
            # TUTTE le curve devono comparire (rich. 24/07 sera: a Le
            # Mans mancavano T2/T11/T14/T21/T22/T25/T28 perche' i numeri
            # si accavallavano e venivano scartati). Piu' tentativi di
            # posizione; se proprio non c'e' buco -> disegna COMUNQUE
            _pl9 = False
            for dist in (11.0, 18.0, 26.0, 34.0, 44.0):
                if _label(base_t, P[a].x() + nx * (trk / 2 + dist),
                          P[a].y() + ny * (trk / 2 + dist),
                          QColor(242, 244, 247, 245), small=True):
                    _pl9 = True
                    break
            if not _pl9:
                _label(base_t, P[a].x() + nx * (trk / 2 + 11.0),
                       P[a].y() + ny * (trk / 2 + 11.0),
                       QColor(242, 244, 247, 245), small=True,
                       force=True)


class _TrackPage(QWidget):
    """Pagina pista dedicata (dal click su una card layout). SINISTRA: nome +
    layout, trackmap SVG bianca, lunghezza/curve/anno. DESTRA: classifiche tempi
    (riempite nel passo 2b). In alto: back al menu + tasto SESSIONS che apre la
    sessione vera. Tutto in inglese."""

    _rank_ready = Signal(int, object, bool)   # token, rows, want_wet (thread->UI)

    def __init__(self, on_sessions=None, on_back=None, parent=None):
        super().__init__(parent)
        self.setStyleSheet("QWidget{font-family:'Archivo SemiExpanded';}")   # default pagina
        self._idx = None
        self._rank_token = 0
        self._rank_ready.connect(self._render_rank)
        self._on_sessions = on_sessions
        self._on_back = on_back
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(14)

        # ── barra alto: back + titolo | SESSIONS ──
        top = QHBoxLayout(); top.setSpacing(10)
        back = QPushButton("arrow_back")
        back.setCursor(Qt.PointingHandCursor); back.setFixedSize(38, 34)
        self._BKQSS = (
            "QPushButton{font-family:'Material Symbols Rounded';font-size:22px;"
            "color:#fff;background:rgba(255,255,255,0.08);border:none;"
            "border-radius:8px;}"
            "QPushButton:hover{background:rgba(255,29,67,0.55);}")
        self._BKQSS_LOCK = (
            "QPushButton{font-family:'Material Symbols Rounded';font-size:22px;"
            "color:#ff4d5a;background:rgba(255,77,90,0.14);border:none;"
            "border-radius:8px;}")
        back.setStyleSheet(self._BKQSS)
        # LUCCHETTO VERO (rich. 23/07): a sessione ARMATA la freccia
        # DIVENTA un lucchetto e il click e' morto — niente piu'
        # rimbalzo dell'auto-focus che sembrava un bug ai clienti
        self._backbtn = back
        self._back_locked = False
        # scritta rossa SESSION LIVE accanto al lucchetto (stessa
        # grafica della pagina Setups — rich. 23/07 sera)
        self._live_note = QLabel("SESSION LIVE")
        self._live_note.setStyleSheet(
            "color:#ff4d5a;font-family:'Archivo SemiExpanded';"
            "font-size:13px;font-weight:800;letter-spacing:2px;"
            "background:transparent;")
        self._live_note.setVisible(False)

        def _locked_live():
            # SOLO le pagine che ESCONO dalla sessione bloccano; le
            # interne (Telemetria -> stint) restano libere, senno' ci
            # rimani intrappolato (bug 23/07 sera)
            if not getattr(self, "_exit_locks", True):
                return False
            try:
                rec = self.window()._app._legacy._recorder
                return bool(rec and rec.is_armed())
            except Exception:
                return False

        def _back_click():
            if _locked_live():
                return                      # bloccato: non esce e basta
            if self._on_back:
                self._on_back()
        back.clicked.connect(_back_click)

        def _upd_lock():
            _lk = _locked_live()
            if _lk == self._back_locked:
                return
            self._back_locked = _lk
            if _lk:
                back.setText("lock")
                back.setStyleSheet(self._BKQSS_LOCK)
                back.setCursor(Qt.ForbiddenCursor)
                back.setToolTip("Session live — STOP to exit")
                self._live_note.setVisible(True)
            else:
                back.setText("arrow_back")
                back.setStyleSheet(self._BKQSS)
                back.setCursor(Qt.PointingHandCursor)
                back.setToolTip("")
                self._live_note.setVisible(False)
        from PySide6.QtCore import QTimer as _QTbk
        self._back_lock_t = _QTbk(self)
        self._back_lock_t.timeout.connect(_upd_lock)
        self._back_lock_t.start(800)
        top.addWidget(back, 0, Qt.AlignVCenter)
        top.addWidget(self._live_note, 0, Qt.AlignVCenter)
        self._flag = _SvgBox(); self._flag.setFixedSize(34, 24)
        self._flag.setStyleSheet("background:transparent;")
        top.addWidget(self._flag, 0, Qt.AlignVCenter)
        self._title = QLabel("")
        self._title.setStyleSheet("color:#f2f4f7;font-family:'Archivo SemiExpanded';"
                                  "font-size:24px;font-weight:800;"
                                  "background:transparent;")
        top.addWidget(self._title, 0, Qt.AlignVCenter)
        top.addStretch(1)
        root.addLayout(top)

        # ── corpo: sinistra info | destra classifiche ──
        body = QHBoxLayout(); body.setSpacing(16)

        left = QFrame(); left.setObjectName("tpInfo")
        left.setStyleSheet("#tpInfo{background:transparent;border:none;}")
        # niente larghezza fissa: proporzionale (responsive con la finestra)
        lv = QVBoxLayout(left); lv.setContentsMargins(18, 18, 18, 18); lv.setSpacing(10)
        # LOGO circuito SOPRA la mappa (esperimento 24/07 sera) — il
        # DOPPIO (rich.): erano piccolini
        self._clogo = _SvgBox(); self._clogo.setFixedSize(320, 100)
        self._clogo.setStyleSheet("background:transparent;")
        self._clogo.setVisible(False)
        lv.addWidget(self._clogo, 0, Qt.AlignHCenter)
        # nome pista rimosso da qui: resta solo nella barra in alto
        self._map = _TrackMapView()
        self._map.setStyleSheet("background:transparent;")
        lv.addWidget(self._map, 1)
        # tasto SESSIONS: sotto il circuito, prima delle info — con
        # DRY/WET accanto (rich. utente 24/07 sera)
        _sessrow = QHBoxLayout(); _sessrow.setSpacing(8)
        _sessrow.addStretch(1)
        _btn_sess = _PillButton("SESSIONS", px=13)
        _btn_sess.setMinimumSize(120, 38)
        _btn_sess.clicked.connect(self._go_sessions)
        self._btn_sess = _btn_sess
        _sessrow.addWidget(_btn_sess)
        self._dry_btn = self._filter_btn("DRY", lambda: self._set_cond("DRY"))
        self._wet_btn = self._filter_btn("WET", lambda: self._set_cond("WET"))
        _sessrow.addWidget(self._dry_btn)
        _sessrow.addWidget(self._wet_btn)
        _sessrow.addStretch(1)
        lv.addLayout(_sessrow)
        lv.addSpacing(6)
        # righe info
        self._info_len = self._info_row(lv, "LENGTH")
        self._info_trn = self._info_row(lv, "TURNS")
        self._info_yr = self._info_row(lv, "OPENED")
        self._left_panel = left
        body.addWidget(left, 1)          # sinistra ridotta, proporzionale

        right = QFrame(); right.setObjectName("tpRank")
        right.setStyleSheet("#tpRank{background:transparent;border:none;}")
        rv = QVBoxLayout(right); rv.setContentsMargins(16, 8, 16, 16); rv.setSpacing(10)
        # (titolo "LEADERBOARDS" rimosso)
        # UNA riga: badge classi (SVG) a sinistra, DRY/WET a destra
        _fw = QWidget(); _fw.setStyleSheet("background:transparent;")
        self._filt_row = _fw
        self._rv = rv
        filt = QHBoxLayout(_fw); filt.setContentsMargins(0, 0, 0, 0); filt.setSpacing(8)
        self._cls_row = QHBoxLayout(); self._cls_row.setSpacing(1)
        filt.addLayout(self._cls_row)
        filt.addStretch(1)
        # DRY/WET spostati accanto a SESSIONS (rich. utente 24/07 sera):
        # qui resta solo la fila dei badge classe
        rv.addWidget(_fw)
        # lista classifica scrollabile
        from PySide6.QtWidgets import QScrollArea
        self._rank_scroll = QScrollArea(); self._rank_scroll.setWidgetResizable(True)
        self._rank_scroll.setFrameShape(QFrame.NoFrame)
        self._rank_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # scrollbar verticale SLIM e moderna (rich. 24/07 sera: quella
        # di sistema "sembra industriale") — pillola sottile, niente
        # frecce, si accende in hover
        self._rank_scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollBar:vertical{background:transparent;width:8px;"
            "margin:2px 2px 2px 0;}"
            "QScrollBar::handle:vertical{background:rgba(255,255,255,0.20);"
            "border-radius:4px;min-height:36px;}"
            "QScrollBar::handle:vertical:hover{"
            "background:rgba(255,255,255,0.38);}"
            "QScrollBar::add-line:vertical,"
            "QScrollBar::sub-line:vertical{height:0;background:none;}"
            "QScrollBar::add-page:vertical,"
            "QScrollBar::sub-page:vertical{background:none;}")
        self._rank_host = QWidget(); self._rank_host.setStyleSheet("background:transparent;")
        self._rank_v = QVBoxLayout(self._rank_host)
        self._rank_v.setContentsMargins(0, 0, 0, 0); self._rank_v.setSpacing(6)
        self._rank_v.addStretch(1)
        self._rank_scroll.setWidget(self._rank_host)
        rv.addWidget(self._rank_scroll, 1)
        self._sel_cls = None; self._sel_cond = "DRY"; self._trk = ""
        self._avail = {}; self._cls_btns = {}
        body.addWidget(right, 2)         # destra piu' larga: sinistra ~1/3

        root.addLayout(body, 1)

    def _info_row(self, lay, label):
        w = QWidget(); w.setStyleSheet("background:transparent;")
        h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0)
        cap = QLabel(label)
        # etichette BIANCHE (rich. 24/07 sera: erano grigie, poco
        # leggibili) — leggermente meno del valore per gerarchia
        cap.setStyleSheet("color:#e8ebf1;font-family:'Archivo SemiExpanded';font-size:12px;"
                          "font-weight:700;letter-spacing:1px;background:transparent;")
        val = QLabel("—")
        val.setStyleSheet("color:#f2f4f7;font-family:'Archivo SemiExpanded';font-size:16px;"
                          "font-weight:800;background:transparent;")
        h.addWidget(cap); h.addStretch(1); h.addWidget(val)
        lay.addWidget(w)
        return val

    def _go_sessions(self):
        if self._on_sessions is not None and self._idx is not None:
            self._on_sessions(self._idx)

    @staticmethod
    def _is_wet(rec):
        """WET se la GOMMA del giro e' wet (compound 'W...'), a prescindere da
        come la chiave e' stata salvata (vecchi tempi classificati per superficie)."""
        c = rec.get("compound") or ""
        if not c:
            c = (rec.get("compounds4") or "").split(",")[0]
        return str(c).strip().upper().startswith("W")

    @staticmethod
    def _trk_slug(name):
        """Nome pista -> slug delle chiavi online: senza accenti e senza
        separatori ('Le Mans'->'LeMans', 'Portimão'->'Portimao',
        'Paul Ricard 1A-V2 Short'->'PaulRicard1AV2Short')."""
        import unicodedata, re
        s = unicodedata.normalize("NFKD", name or "")
        s = s.encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^A-Za-z0-9]", "", s)

    def _filter_btn(self, text, cb):
        b = _PillButton(text, px=12); b.setCheckable(True)
        b.setMinimumWidth(64)
        b.clicked.connect(lambda _=False, f=cb: f())
        return b

    def _build_filters(self):
        while self._cls_row.count():
            it = self._cls_row.takeAt(0); w = it.widget()
            if w:
                w.deleteLater()
        self._cls_btns = {}
        avail = {}
        try:
            from core import online
            online.load_async()        # carica la cache (disco->RAM) se non c'e'
            for r in (online.cached_refs() or []):
                parts = (r.get("key") or "").split("_")
                if len(parts) < 3:
                    continue
                cls = parts[0]; trk = "_".join(parts[1:-1])
                if trk == self._trk:
                    cnd = "WET" if self._is_wet(r) else "DRY"
                    avail.setdefault(cls, set()).add(cnd)
        except Exception:
            avail = {}
        self._avail = avail          # solo le classi con tempi per questa pista
        order = ["HY", "P2", "P3", "GT3", "GTE"]
        cls_list = [c for c in order if c in avail] \
            + [c for c in avail if c not in order]
        from ui.widgets import _ClassBadge
        _cdir = Path(__file__).resolve().parent.parent / "assets" / "class"
        for c in cls_list:
            _cp = _cdir / (c.lower() + ".svg")
            b = _ClassBadge(c, str(_cp), (lambda cc=c: self._pick_cls(cc)),
                            size=(52, 33))          # SVG un po' piu' grande
            b._qss_on = b._qss_off                  # niente pill: hover = illumina
            b.setStyleSheet(b._qss_off)
            b.installEventFilter(self)
            self._cls_row.addWidget(b); self._cls_btns[c] = b
        if cls_list:
            self._sel_cls = cls_list[0]
            conds = avail.get(self._sel_cls, set())
            self._sel_cond = "DRY" if "DRY" in conds else (
                "WET" if "WET" in conds else "DRY")
        else:
            self._sel_cls = None; self._sel_cond = "DRY"
        self._refresh_rank()

    def _set_badge_opacity(self, b, val):
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        try:
            eff = b.graphicsEffect()
            if not isinstance(eff, QGraphicsOpacityEffect):
                eff = QGraphicsOpacityEffect(b); b.setGraphicsEffect(eff)
            eff.setOpacity(val)
        except Exception:
            pass

    def eventFilter(self, obj, ev):
        # hover sui badge classe: illumina il dimmato (non cambia sfondo)
        from PySide6.QtCore import QEvent
        btns = getattr(self, "_cls_btns", {})
        if obj in btns.values():
            if ev.type() == QEvent.Enter:
                self._set_badge_opacity(obj, 1.0)
            elif ev.type() == QEvent.Leave:
                _sel = btns.get(self._sel_cls)
                self._set_badge_opacity(obj, 1.0 if obj is _sel else 0.40)
        return super().eventFilter(obj, ev)

    def _pick_cls(self, cls):
        self._sel_cls = cls
        conds = self._avail.get(cls, set())
        if self._sel_cond not in conds:
            self._sel_cond = "DRY" if "DRY" in conds else (
                "WET" if "WET" in conds else self._sel_cond)
        self._refresh_rank()

    def _set_cond(self, cond):
        if self._sel_cls and cond in self._avail.get(self._sel_cls, set()):
            self._sel_cond = cond
            self._refresh_rank()

    def _refresh_rank(self):
        # classe selezionata piena, le altre attenuate (i badge SVG non hanno
        # uno stato 'checked': uso l'opacita'; l'hover le illumina)
        for c, b in self._cls_btns.items():
            self._set_badge_opacity(b, 1.0 if c == self._sel_cls else 0.40)
        conds = self._avail.get(self._sel_cls, set()) if self._sel_cls else set()
        self._dry_btn.setChecked(self._sel_cond == "DRY")
        self._wet_btn.setChecked(self._sel_cond == "WET")
        # mostra DRY/WET solo se c'e' davvero un tempo in quella condizione
        self._dry_btn.setVisible("DRY" in conds)
        self._wet_btn.setVisible("WET" in conds)
        # svuota lista (tiene lo stretch finale)
        while self._rank_v.count() > 1:
            it = self._rank_v.takeAt(0); w = it.widget()
            if w:
                w.deleteLater()
        if not (self._sel_cls and self._trk):
            return
        # FETCH ASYNC: online.top e' bloccante (fino a 8s x2). Lo faccio in un
        # thread e riempio la lista via signal, cosi' la UI non si impunta. Un
        # token evita che un risultato vecchio (filtro gia' cambiato) sovrascriva.
        self._rank_token += 1
        tok = self._rank_token
        cls, trk = self._sel_cls, self._trk
        want_wet = (self._sel_cond == "WET")
        import threading

        def _work():
            merged = {}
            try:
                from core import online
                # ENTRAMBE le chiavi: ogni giro poi classificato per la sua
                # GOMMA (wet salvati sotto DRY finiscono comunque in WET).
                for _cnd in ("DRY", "WET"):
                    for r in online.top("%s_%s_%s" % (cls, trk, _cnd), 30):
                        merged[(r.get("player"), r.get("lap_ms"))] = r
            except Exception:
                merged = {}
            rows = [r for r in merged.values() if _TrackPage._is_wet(r) == want_wet]
            rows.sort(key=lambda r: (r.get("lap_ms") or 10 ** 12))
            self._rank_ready.emit(tok, rows[:30], want_wet)

        threading.Thread(target=_work, name="tp-rank", daemon=True).start()

    def _render_rank(self, tok, rows, want_wet):
        """Slot (main thread) chiamato dal thread di fetch via signal."""
        if tok != self._rank_token:          # filtro gia' cambiato: scarta
            return
        while self._rank_v.count() > 1:
            it = self._rank_v.takeAt(0); w = it.widget()
            if w:
                w.deleteLater()
        try:
            from ui.tab_community import _RankRow
        except Exception:
            return
        lead = rows[0].get("lap_ms") if rows else None
        for i, rec in enumerate(rows):
            self._rank_v.insertWidget(self._rank_v.count() - 1,
                                      _RankRow(i + 1, rec, lead, wet=want_wet))

    _PHOTO_DIR = Path(__file__).resolve().parent.parent / "assets" / "trackcards"

    def _photo(self):
        bg = getattr(self, "_bgkey", None)
        if not bg:
            return None
        cache = getattr(self, "_photo_cache", None)
        if cache and cache[0] == bg:
            return cache[1]
        pm = None
        for ext in ("jpg", "jpeg", "png", "webp"):
            p = _TrackPage._PHOTO_DIR / ("%s.%s" % (bg, ext))
            if p.exists():
                _pm = QPixmap(str(p))
                if not _pm.isNull():
                    pm = _pm
                    break
        self._photo_cache = (bg, pm)
        return pm

    _DARK_CORNERS = False    # True (Sessions/Stint): angoli scuri al posto di blu/rosso

    def paintEvent(self, e):
        # sfondo = foto della card di QUESTA pista (foto 20%); poi radiali agli
        # angoli: blu/rosso (track page) o scuri trasparenti (Sessions/Stint)
        from PySide6.QtGui import QRadialGradient
        from PySide6.QtCore import QRect
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = self.rect(); w, h = self.width(), self.height()
        p.fillRect(r, QColor("#000833"))
        photo = self._photo()
        if photo is not None:
            scaled = photo.scaled(r.size(), Qt.KeepAspectRatioByExpanding,
                                  Qt.SmoothTransformation)
            sx = max(0, (scaled.width() - r.width()) // 2)
            sy = max(0, (scaled.height() - r.height()) // 2)
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            # foto sfondo pagina: 0.20 -> 0.35 (rich. utente 24/07 sera,
            # "piu' capacita' allo sfondo immagine")
            p.setOpacity(0.35)
            p.drawPixmap(r, scaled, QRect(sx, sy, r.width(), r.height()))
            p.setOpacity(1.0)
        if self._DARK_CORNERS:
            for cx, cy in ((0, h), (w, 0)):
                g = QRadialGradient(cx, cy, max(w, h) * 0.95)
                g.setColorAt(0.0, QColor(0, 0, 0, 150))
                g.setColorAt(0.55, QColor(0, 0, 0, 55))
                g.setColorAt(1.0, QColor(0, 0, 0, 0))
                p.fillRect(r, QBrush(g))
            return
        # ESPERIMENTO 24/07 sera: radiali blu (basso-sx) e rosso
        # (alto-dx) DISATTIVATI per provare la pagina senza tinte
        if False:
            gb = QRadialGradient(0, h, max(w, h) * 0.95)
            gb.setColorAt(0.0, QColor(19, 41, 67, 130))
            gb.setColorAt(0.55, QColor(19, 41, 67, 45))
            gb.setColorAt(1.0, QColor(19, 41, 67, 0))
            p.fillRect(r, QBrush(gb))
            g = QRadialGradient(w, 0, max(w, h) * 0.95)
            g.setColorAt(0.0, QColor(255, 29, 67, 170))
            g.setColorAt(0.55, QColor(255, 29, 67, 60))
            g.setColorAt(1.0, QColor(255, 29, 67, 0))
            p.fillRect(r, QBrush(g))

    def set_track(self, idx, base, name, mapname, bgkey=None):
        self._idx = idx
        self._bgkey = bgkey              # foto card come sfondo pagina
        _stem9 = ""                      # cmap canonico (fuori dai try)
        try:
            from data.track_info import track_name, track_country
            _full = track_name(base) or name or ""
            # LAYOUT dal CMAP della card (identita' canonica, rich.
            # 24/07 sera): il nome corto ("Bahrain Endurance") non
            # combaciava con la tabella e il titolo restava spoglio
            _stem9 = ""
            _lay = ""
            try:
                import re as _re9
                _stem9 = _re9.sub(
                    r"#U([0-9a-fA-F]{4})",
                    lambda m: chr(int(m.group(1), 16)),
                    str(mapname or "").rsplit(".", 1)[0])
                from data.tracks import _LAYOUT_LABELS as _LL9
                _lay = _LL9.get(_stem9, "")
            except Exception:
                _lay = ""
            if not _lay:
                _lay = _track_layout_label(name) or ""
            self._title.setText((_full + ((" — " + _lay)
                              if _lay else "")).upper())
            _cc = track_country(base)
            _fp = (Path(__file__).resolve().parent.parent / "assets"
                   / "flags" / ("%s.svg" % _cc)) if _cc else None
            self._flag.load(str(_fp) if (_fp and _fp.exists()) else "")
            self._flag.setVisible(bool(_fp and _fp.exists()))
        except Exception:
            self._title.setText((name or "").upper())
        # LOGO circuito sopra la mappa (esperimento 24/07 sera)
        try:
            from data.tracks import _ov_tracklogo_file
            _lf9 = _ov_tracklogo_file(name) or _ov_tracklogo_file(base)
            if _lf9:
                self._clogo.load(str(_lf9))
                self._clogo.setVisible(True)
            else:
                self._clogo.setVisible(False)
        except Exception:
            self._clogo.setVisible(False)
        try:
            # 24/07 sera (2a decisione): ora che le mappe sono girate nel
            # verso giusto e le curve sistemate, la pagina classifiche usa
            # la mappa VERA (bianca pulita, settori, curve, verso salvato);
            # la stilizzata resta il fallback dove la vera non c'e' ancora.
            # Doppio tentativo: nome card ("COTA") poi CMAP canonico
            # ("Circuit of the Americas") = il nome che usa LMU nei file
            if not self._map.set_real(name) \
                    and not (_stem9 and self._map.set_real(_stem9)):
                self._map.set_map(mapname, _styl_rot9(mapname, base))
        except Exception:
            pass
        self._trk = self._trk_slug(name)     # slug per le chiavi online
        try:
            self._build_filters()            # classifiche per questa pista
        except Exception:
            pass
        try:
            # scheda per LAYOUT (rich. 24/07 sera): info_for_track
            # legge PRIMA LAYOUT_INFO per nome (Endurance/Outer/...),
            # poi ripiega sulla base — track_info(base) dava sempre il
            # GP anche sull'Endurance (15 curve invece di 24). Si prova
            # anche col CMAP (nome completo) come per il titolo.
            from data.track_info import (info_for_track, track_info,
                                         LAYOUT_INFO as _LI9)
            info = None
            _nm9 = (name or "").lower()
            _sm9 = (locals().get("_stem9") or "").lower()
            for _k9, _v9 in _LI9.items():
                if _k9 in _nm9 or (_sm9 and _k9 in _sm9):
                    info = _v9
                    break
            if not info:
                info = track_info(base)
        except Exception:
            info = None
        # NUMERO CURVE dal CENSIMENTO che salvi TU (rich. 24/07 sera):
        # il conteggio mostrato = le curve che hai messo sulla mappa
        # (Le Mans 28 tue, non 38 della tabella; la FIA ne conta 33
        # contando punti che non sono curve). Fallback alla scheda se
        # la pista non e' ancora censita.
        _turns9 = None
        try:
            from data.track_corners import corners_for_track as _cft9
            _cc9 = _cft9(name) or (_cft9(_stem9) if _stem9 else None)
            if _cc9:
                _turns9 = len(_cc9)
        except Exception:
            _turns9 = None
        if info:
            _len, _trn, _yr = info
            self._info_len.setText("%.3f km" % (_len / 1000.0))
            self._info_trn.setText(str(_turns9 if _turns9 else _trn))
            self._info_yr.setText(str(_yr))
        elif _turns9:
            self._info_len.setText("—")
            self._info_trn.setText(str(_turns9))
            self._info_yr.setText("—")
        else:
            for v in (self._info_len, self._info_trn, self._info_yr):
                v.setText("—")


def _sess_norm_cls(cc):
    """car_class sessione -> sigla canonica ('HY','GT3','P2','P3','GTE')."""
    u = (cc or "").upper()
    if "GT3" in u:
        return "GT3"
    if "GTE" in u:
        return "GTE"
    if "P2" in u:
        return "P2"
    if "P3" in u:
        return "P3"
    if ("HY" in u) or ("LMH" in u) or ("HYPER" in u):
        return "HY"
    return ""


def _sess_border(cls):
    """Colore bordo/nome per categoria (come le classifiche community)."""
    return {"HY": "#00b9ff", "GT3": "#00b9ff",
            "P2": "#ff5f00", "P3": "#ff5f00", "GTE": "#ff5f00"}.get(cls, "#ffffff")


def _sess_wet(s):
    """Sessione WET dal metadato 'wetness' (scala 0..1 o 0..100)."""
    try:
        w = float(s.get("wetness") or 0)
    except Exception:
        return False
    return (w > 50) if w > 1 else (w > 0.5)


def _sess_fmt_lap(v):
    """best_lap -> 'm:ss.mmm'. Gestisce ms o secondi. '—' se assente."""
    if not v:
        return "—"
    s = (v / 1000.0) if v > 1000 else v      # ms -> s se necessario
    return "%d:%06.3f" % (int(s) // 60, s % 60) if s >= 60 else "%.3f" % s


class _SessionCard(QFrame):
    """Riga sessione, stile classifica community: bg blu, bordo sx per categoria,
    logo auto, pilota (UPPER) + auto + tipo, best lap + n° giri. Click = apre."""

    def __init__(self, s, on_open=None, on_export=None, on_delete=None):
        super().__init__()
        self._s = s
        self._on_open = on_open
        self._on_export = on_export
        self._on_delete = on_delete
        self.setObjectName("sessCard")
        self.setCursor(Qt.PointingHandCursor)
        cls = _sess_norm_cls(s.get("car_class"))
        _team = bool(s.get("team_session"))
        # TEAM (importata dall'amico): card ROSSO LMU (bg scuro + bordo)
        bord = "#ff1d43" if _team else _sess_border(cls)
        _bg = "rgba(84,6,20,0.92)" if _team else "rgba(13,27,42,0.90)"
        self.setStyleSheet(
            "#sessCard{background:%s;border:none;"
            "border-left:3px solid %s;border-radius:9px;}" % (_bg, bord))
        h = QHBoxLayout(self); h.setContentsMargins(13, 10, 14, 10); h.setSpacing(0)
        # data/ora (come la posizione)
        dt = self._fmt_dt(s.get("started_at"))
        dcol = QVBoxLayout(); dcol.setSpacing(1); dcol.setContentsMargins(0, 0, 0, 0)
        d1 = QLabel(dt[0]); d1.setStyleSheet(
            "color:#ffffff;font-family:'Archivo SemiExpanded';font-size:14px;font-weight:800;"
            "background:transparent;")
        d2 = QLabel(dt[1]); d2.setStyleSheet(
            "color:#a79fb0;font-family:'Archivo SemiExpanded';font-size:11px;font-weight:600;"
            "background:transparent;")
        dcol.addWidget(d1); dcol.addWidget(d2)
        dcw = QWidget(); dcw.setLayout(dcol); dcw.setFixedWidth(64)
        dcw.setStyleSheet("background:transparent;")
        h.addWidget(dcw); h.addSpacing(6)
        # logo auto
        box = _SvgBox(); box.setFixedSize(58, 46)
        try:
            from ui.widgets import _car_logo_into, _EMPTY_LOGO_SVG
            _car_logo_into(box, s.get("team"), s.get("vehicle"))
        except Exception:
            pass
        h.addWidget(box, 0, Qt.AlignVCenter); h.addSpacing(12)
        # pilota + auto + tipo
        ncol = QVBoxLayout(); ncol.setSpacing(1); ncol.setContentsMargins(0, 0, 0, 0)
        nm = QLabel((str(s.get("driver") or "—")).upper())
        nm.setStyleSheet("color:#eef0f4;font-family:'Archivo SemiExpanded';font-size:15px;"
                         "font-weight:800;background:transparent;")
        cr = QLabel(str(s.get("vehicle") or "—"))
        cr.setStyleSheet("color:%s;font-family:'Archivo SemiExpanded';font-size:12px;"
                         "font-weight:700;background:transparent;" % bord)
        # nome sessione come nelle card vecchie: tipo + durata (es. "RACE 60m")
        _styp = _ov_session_label(s.get("session_type"))
        _slen = _fmt_session_len(s.get("session_len"))
        ty = QLabel(_styp + ((" " + _slen) if _slen else ""))
        ty.setStyleSheet("color:#a79fb0;font-family:'Archivo SemiExpanded';font-size:12px;"
                         "font-weight:600;background:transparent;")
        ncol.addWidget(nm); ncol.addWidget(cr); ncol.addWidget(ty)
        ncw = QWidget(); ncw.setLayout(ncol); ncw.setMinimumWidth(200)
        ncw.setStyleSheet("background:transparent;")
        h.addWidget(ncw)
        # colonna CASCO accanto al nome: la TUA livrea sulle card personali,
        # tre caschi affiancati (fila piloti) sulle card team
        try:
            from ui.icons import helmet_svg_bytes
            from core.profile import _load_profile as _lp2
            if _team:
                _cols3 = ("#ff1d43", "#e8eaee", "#1d6bff")
            else:
                _cols3 = (_lp2().get("helmet_color", "#ff1d43"),)
            _hrow = QHBoxLayout()
            _hrow.setContentsMargins(0, 0, 0, 0); _hrow.setSpacing(2)
            for _c3 in _cols3:
                _hb = _SvgBox(); _hb.setFixedSize(56, 44)
                _hb.setStyleSheet("background:transparent;")
                _hb.load(helmet_svg_bytes(_c3))
                _hrow.addWidget(_hb)
            _hw = QWidget(); _hw.setLayout(_hrow)
            _hw.setStyleSheet("background:transparent;")
            h.addSpacing(10)
            h.addWidget(_hw, 0, Qt.AlignVCenter)
        except Exception:
            pass
        h.addStretch(1)
        # meteo previsto (5 nodi) come nelle card vecchie
        fc5 = (s.get("forecast5") or "").strip()
        if fc5:
            _wdir = Path(__file__).resolve().parent.parent / "assets" / "weather"
            _fcw = QWidget(); _fcw.setStyleSheet("background:transparent;")
            _fcl = QHBoxLayout(_fcw)
            _fcl.setContentsMargins(0, 0, 0, 0); _fcl.setSpacing(5)
            _nic = 0
            for _nm in [x.strip() for x in fc5.split(",") if x.strip()][:5]:
                _wp = _wdir / ("%s.svg" % _nm)
                if not _wp.exists():
                    continue
                _ic = _SvgBox(); _ic.setFixedSize(30, 30)
                _ic.setStyleSheet("background:transparent;")
                _ic.load(str(_wp))
                _fcl.addWidget(_ic, 0, Qt.AlignVCenter)
                _nic += 1
            if _nic:
                h.addWidget(_fcw, 0, Qt.AlignVCenter); h.addSpacing(16)
            else:
                _fcw.deleteLater()
        # best lap + n giri
        bl = QLabel(_sess_fmt_lap(s.get("best_lap")))
        bl.setStyleSheet("color:#f2f4f7;font-family:'Archivo SemiExpanded';font-size:19px;"
                         "font-weight:800;background:transparent;")
        bl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(bl); h.addSpacing(12)
        lp = QLabel("%d laps" % int(s.get("laps") or 0))
        lp.setStyleSheet("color:#8a90a0;font-family:'Archivo SemiExpanded';font-size:12px;"
                         "font-weight:700;background:transparent;")
        lp.setFixedWidth(64); lp.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(lp)
        # export in alto / X elimina in basso, come nelle card vecchie
        rb = QVBoxLayout(); rb.setSpacing(4); rb.setContentsMargins(0, 0, 0, 0)
        if s.get("team_session"):
            pass                      # niente in alto: la card e' gia' rossa
        elif self._on_export:
            _be = _ExportButton(16)
            _be.setFlat(True); _be.setCursor(Qt.PointingHandCursor)
            _be.setToolTip("Export session (.zip)")
            _be.setFixedSize(24, 24)
            _be.setStyleSheet("border:none;background:transparent;")
            _be.clicked.connect(
                lambda: self._on_export(self._s.get("file")))
            rb.addWidget(_be, 0, Qt.AlignRight | Qt.AlignTop)
        rb.addStretch(1)
        if self._on_delete:
            _bd = _XButton(18)
            _bd.setFlat(True); _bd.setCursor(Qt.PointingHandCursor)
            _bd.setToolTip("Delete")
            _bd.setFixedSize(26, 26)
            _bd.setStyleSheet("border:none;background:transparent;")
            _bd.clicked.connect(
                lambda: self._on_delete(self._s.get("file")))
            rb.addWidget(_bd, 0, Qt.AlignRight | Qt.AlignBottom)
        if self._on_export or self._on_delete or s.get("team_session"):
            h.addSpacing(10); h.addLayout(rb, 0)

    @staticmethod
    def _fmt_dt(iso):
        """ISO started_at -> ('17 Jul', '14:32'). ('—','') se assente."""
        if not iso:
            return ("—", "")
        try:
            from datetime import datetime
            d = datetime.fromisoformat(str(iso)[:19])
            return (d.strftime("%d %b"), d.strftime("%H:%M"))
        except Exception:
            return (str(iso)[:10], str(iso)[11:16])

    def mousePressEvent(self, e):
        if self._on_open:
            self._on_open(self._s)


class _SessionsPage(_TrackPage):
    """Pagina Sessions: stesso guscio della track page (mappa + info a sx, filtri
    classe + DRY/WET in alto), ma la lista sono le SESSIONI registrate della
    pista (filtri dai metadati, nessun fetch online). Click su una card apre la
    sessione. Niente tasto SESSIONS (siamo gia' qui). Tutto in inglese."""

    _DARK_CORNERS = True     # angoli scuri (come la pagina stint)

    def __init__(self, on_open=None, on_back=None, on_teams=None,
                 on_export=None, on_delete=None, parent=None):
        super().__init__(on_sessions=None, on_back=on_back, parent=parent)
        self._on_open = on_open
        self._on_teams = on_teams
        self._on_export = on_export
        self._on_delete = on_delete
        self._sessions = []
        try:
            self._btn_sess.setVisible(False)
            self._left_panel.setVisible(False)   # card sessioni a tutta pagina
            # TEAMS dopo DRY/WET nella riga filtri
            _bt = _PillButton("TEAMS", px=12)
            _bt.setMinimumWidth(80)
            _bt.clicked.connect(lambda: self._on_teams() if self._on_teams else None)
            self._filt_row.layout().addWidget(_bt)
        except Exception:
            pass

    def set_track(self, idx, base, name, mapname, bgkey=None):
        self._load_sessions(idx)          # prima le sessioni, poi il guscio
        super().set_track(idx, base, name, mapname, bgkey)

    def _load_sessions(self, idx):
        try:
            from telemetry import db as _db
            entry = _TRACKS[idx]
            stem = entry[3]
            lkey = _cmap_layout_key(entry[4])
            out = []
            for s in _db.list_sessions():
                if _track_logo_stem(s.get("track")) != stem:
                    continue
                if lkey and _track_layout_key(s.get("track")) != lkey:
                    continue
                out.append(s)
            # sessioni TEAM importate (archivio amico): stessa pista,
            # marcate per la card dedicata (bordo azzurro, tag "team")
            try:
                from core import team_share as _ts2
                for s in _ts2.list_team_sessions():
                    if _track_logo_stem(s.get("track")) != stem:
                        continue
                    if lkey and _track_layout_key(s.get("track")) != lkey:
                        continue
                    s = dict(s); s["team_session"] = True
                    out.append(s)
            except Exception:
                pass
            self._sessions = out
        except Exception:
            self._sessions = []

    def _build_filters(self):
        while self._cls_row.count():
            it = self._cls_row.takeAt(0); w = it.widget()
            if w:
                w.deleteLater()
        self._cls_btns = {}
        avail = {}
        for s in self._sessions:
            cls = _sess_norm_cls(s.get("car_class"))
            if not cls:
                continue
            avail.setdefault(cls, set()).add("WET" if _sess_wet(s) else "DRY")
        self._avail = avail
        order = ["HY", "P2", "P3", "GT3", "GTE"]
        cls_list = [c for c in order if c in avail] \
            + [c for c in avail if c not in order]
        from ui.widgets import _ClassBadge
        _cdir = Path(__file__).resolve().parent.parent / "assets" / "class"
        for c in cls_list:
            _cp = _cdir / (c.lower() + ".svg")
            b = _ClassBadge(c, str(_cp), (lambda cc=c: self._pick_cls(cc)),
                            size=(52, 33))
            b._qss_on = b._qss_off
            b.setStyleSheet(b._qss_off)
            b.installEventFilter(self)
            self._cls_row.addWidget(b); self._cls_btns[c] = b
        if cls_list:
            self._sel_cls = cls_list[0]
            conds = avail.get(self._sel_cls, set())
            self._sel_cond = "DRY" if "DRY" in conds else (
                "WET" if "WET" in conds else "DRY")
        else:
            self._sel_cls = None; self._sel_cond = "DRY"
        self._refresh_rank()

    def _refresh_rank(self):
        for c, b in self._cls_btns.items():
            self._set_badge_opacity(b, 1.0 if c == self._sel_cls else 0.40)
        conds = self._avail.get(self._sel_cls, set()) if self._sel_cls else set()
        self._dry_btn.setChecked(self._sel_cond == "DRY")
        self._wet_btn.setChecked(self._sel_cond == "WET")
        self._dry_btn.setVisible("DRY" in conds)
        self._wet_btn.setVisible("WET" in conds)
        while self._rank_v.count() > 1:
            it = self._rank_v.takeAt(0); w = it.widget()
            if w:
                w.deleteLater()
        if not self._sel_cls:
            return
        want_wet = (self._sel_cond == "WET")
        rows = [s for s in self._sessions
                if _sess_norm_cls(s.get("car_class")) == self._sel_cls
                and _sess_wet(s) == want_wet]
        rows.sort(key=lambda s: (s.get("started_at") or ""), reverse=True)
        for s in rows:
            self._rank_v.insertWidget(self._rank_v.count() - 1,
                                      _SessionCard(s, self._on_open,
                                                   self._on_export,
                                                   self._on_delete))

    def reload(self):
        """Ricarica la lista (dopo un delete) mantenendo pista e filtri."""
        try:
            self._load_sessions(self._idx)
            self._build_filters()
        except Exception:
            pass


class _StintPage(_TrackPage):
    """Pagina stint: stesso guscio di Sessions/community ma SENZA mappa/info a
    sinistra (area vuota, da riempire poi) e SENZA filtri. Riusa gli STESSI
    widget del board (_LapBoard): tab stint + riga riepilogo + giri, montati qui
    quando si apre una sessione. Tutto in inglese."""

    def __init__(self, on_back=None, parent=None):
        super().__init__(on_sessions=None, on_back=on_back, parent=parent)
        try:
            self._btn_sess.setVisible(False)
            self._map.setVisible(False)                 # sinistra vuota
            for v in (self._info_len, self._info_trn, self._info_yr):
                pw = v.parentWidget()
                if pw:
                    pw.setVisible(False)
            self._filt_row.setVisible(False)            # niente filtri classe/cond
            self._rank_scroll.setVisible(False)         # niente lista rank
            self._rv.setSpacing(2)                      # dati attaccati alle tab
            self._left_panel.setVisible(False)          # stint a tutta pagina
        except Exception:
            pass
        # OROLOGIO sessione live: stessa riga del titolo, a destra
        try:
            self._clock = QLabel("")
            self._clock.setStyleSheet(
                "color:#ffffff;font-family:'Archivo SemiExpanded';font-size:24px;"
                "font-weight:800;background:transparent;")
            self._clock.setVisible(False)
            _top = self.layout().itemAt(0).layout()
            _top.addWidget(self._clock, 0, Qt.AlignVCenter)
            _top.addSpacing(26)                  # staccato dal bordo destro
        except Exception:
            pass
        # STESSE funzioni del board, GRAFICA della pagina nuova: righe giro =
        # card blu (come Sessions/community), testi bianchi, accenti invariati.
        self.setStyleSheet(
            "QWidget{font-family:'Archivo SemiExpanded';}"
            "#ovColCap{color:#8a90a0;font-size:10px;font-weight:700;"
            "letter-spacing:1px;background:transparent;}"
            "#ovStintSum{color:#c9cede;font-size:12px;background:transparent;}"
            "#ovTabTxt{color:#ffffff;font-size:11px;font-weight:700;"
            "letter-spacing:.5px;background:transparent;}"
            "#ovLapRow{background:rgba(10,0,50,0.90);border:none;"
            "border-left:3px solid #ffffff;border-radius:9px;}"
            "#ovLapSel{background:rgba(10,0,50,0.95);border:none;"
            "border-left:3px solid #55ff7f;border-radius:9px;}"
            "#ovLapDis{background:rgba(10,0,50,0.50);border:none;"
            "border-left:3px solid rgba(255,255,255,0.35);border-radius:9px;}"
            "#ovLapBestCard{background:rgba(10,0,50,0.95);border:none;"
            "border-left:3px solid #ff5bb0;border-radius:9px;}"
            "#ovLapNo{color:#ffffff;font-size:13px;font-weight:700;background:transparent;}"
            "#ovLapInv{color:#aeb2ba;font-size:13px;font-weight:700;background:transparent;}"
            "#ovLapTime{color:#f5f5f5;font-size:14px;font-weight:600;background:transparent;}"
            "#ovLapBest{color:#ff5bb0;font-size:14px;font-weight:700;background:transparent;}"
            "#ovSec{color:#ffffff;font-size:12px;background:transparent;}"
            "#ovSecBest{color:#ff3bd4;font-size:12px;background:transparent;}"
            "#ovSecInv{color:#ffffff;font-size:12px;background:transparent;}"
            "#ovTagOut{color:#d2d6dd;font-size:9px;font-weight:700;letter-spacing:1px;"
            "background:rgba(255,255,255,0.10);border-radius:4px;padding:1px 5px;margin-left:6px;}"
            "#ovTagTL{color:#ffcc33;font-size:9px;font-weight:700;letter-spacing:1px;"
            "background:rgba(255,204,51,0.12);border-radius:4px;padding:1px 5px;margin-left:6px;}"
            "#ovCkOff{background:transparent;border:1.5px solid #6a6f7a;border-radius:4px;}"
            "#ovCkOff:hover{border-color:#aab0bc;}"
            "#ovCkSelOn{background:transparent;border:2px solid #55ff7f;border-radius:4px;}"
            "#ovCkCmpOn{background:transparent;border:2px solid #8b7bff;border-radius:4px;}"
            "#ovCkRefOn{background:transparent;border:2px solid #f5c542;border-radius:4px;}"
            # card REF personale: lap DORATO in stile card (check = confronto)
            "#ovRefRow{background:rgba(245,197,66,0.14);border:none;"
            "border-left:3px solid #f5c542;border-radius:9px;}"
            "#ovRefTag{color:#f5c542;font-size:12px;font-weight:800;"
            "letter-spacing:1px;background:transparent;}"
            "#ovRefDrv{color:#f5f5f5;font-size:13px;font-weight:700;background:transparent;}"
            "#ovRefTime{color:#f5c542;font-size:16px;font-weight:800;background:transparent;}"
            "#ovRefSec{color:#d8c583;font-size:12px;font-weight:600;background:transparent;}"
            # variante WET (REF in bagnato = azzurro)
            "#ovWrRow{background:rgba(57,182,232,0.14);border:none;"
            "border-left:3px solid #39b6e8;border-radius:9px;}"
            "#ovWrTag{color:#39b6e8;font-size:12px;font-weight:800;"
            "letter-spacing:1px;background:transparent;}"
            "#ovWrDrv{color:#f5f5f5;font-size:13px;font-weight:700;background:transparent;}"
            "#ovWrTime{color:#39b6e8;font-size:16px;font-weight:800;background:transparent;}"
            "#ovWrSec{color:#7fb8d4;font-size:12px;font-weight:600;background:transparent;}")

    def _build_filters(self):
        pass                                            # nessun filtro

    def set_session(self, s):
        # titolo = nome sessione: "Race - 17 Jul 19:55" (tipo + data/ora).
        # NB: session_kind(None) risponde "race" -> senza dati usciva "RACE"
        s = s or {}
        _ty = ""
        if s.get("session_type") is not None:
            try:
                from core.engineer import session_kind
                _ty = {"practice": "Practice", "qualy": "Qualifying",
                       "race": "Race"}.get(session_kind(s.get("session_type")), "")
            except Exception:
                _ty = ""
        if not s:
            self._title.setText("LIVE SESSION")
            try:
                self._flag.setVisible(False)
            except Exception:
                pass
            return
        _d1, _d2 = _SessionCard._fmt_dt(s.get("started_at"))
        _dt = (" - %s %s" % (_d1, _d2)).rstrip() if _d1 != "—" else ""
        # prefisso: BANDIERA + nome circuito completo - layout -
        _pre = ""
        try:
            _trk = s.get("track") or ""
            _lk = _track_layout_key(_trk)
            _ent = next((e for e in _TRACKS
                         if _cmap_layout_key(e[4]) == _lk), None)
            if _ent is None:
                _st = _track_logo_stem(_trk)
                _ent = next((e for e in _TRACKS if e[3] == _st), None)
            if _ent is not None:
                from data.track_info import track_name, track_country
                _full = track_name(_ent[0]) or _ent[2]
                _lay = _track_layout_label(_ent[2]) or ""
                _pre = _full + ((" - " + _lay) if _lay else "")
                _cc = track_country(_ent[0])
                _fp = (Path(__file__).resolve().parent.parent / "assets"
                       / "flags" / ("%s.svg" % _cc)) if _cc else None
                if _fp is not None and _fp.exists():
                    self._flag.load(str(_fp))
                    self._flag.setVisible(True)
                else:
                    self._flag.setVisible(False)
        except Exception:
            _pre = ""
        _tail = ((_ty or "Session") + _dt).upper()
        # col prefisso circuito il tipo/data NON sta nel titolo (il nome
        # sessione vive accanto al tempo live, grande e bianco)
        self._title.setText(_pre.upper() if _pre else _tail)
        if not _pre:
            try:
                self._flag.setVisible(False)
            except Exception:
                pass

    _DARK_CORNERS = True     # stesso sfondo di Sessions: angoli scuri

    def _add_telemetry_btn(self, on_telemetry, on_setups=None):
        """TELEMETRY + SETUPS + messaggio stato recorder: sotto i giri
        (appena sotto l'ultimo lap, allineati alle righe). Vedi mount_board."""
        self._on_telemetry = on_telemetry
        self._on_setups = on_setups
        w = QWidget(); w.setStyleSheet("background:transparent;")
        hl = QHBoxLayout(w); hl.setContentsMargins(0, 2, 0, 0); hl.setSpacing(8)
        b = _PillButton("TELEMETRY", px=13)
        b.setMinimumSize(130, 38)
        b.clicked.connect(lambda: self._on_telemetry() if self._on_telemetry else None)
        hl.addWidget(b, 0, Qt.AlignLeft)
        b2 = _PillButton("SETUPS", px=13)
        b2.setMinimumSize(130, 38)
        b2.clicked.connect(lambda: self._on_setups() if self._on_setups else None)
        hl.addWidget(b2, 0, Qt.AlignLeft)
        # messaggio stato recorder (armed / waiting for stint...), alto come i tasti
        self._status_lbl = QLabel("")
        self._status_lbl.setFixedHeight(38)
        self._status_lbl.setVisible(False)
        hl.addWidget(self._status_lbl, 0, Qt.AlignLeft)
        hl.addStretch(1)
        self._tele_w = w

    def set_status(self, kind, text, cols):
        """Replica del banner recorder del footer, accanto ai tasti."""
        lb = getattr(self, "_status_lbl", None)
        if lb is None:
            return
        if kind == "idle" or not text:
            lb.setVisible(False)
            return
        fg, bg, bd = cols.get(kind, cols.get("idle"))
        lb.setText(text)
        lb.setStyleSheet(
            "QLabel{color:%s;background:%s;border:1px solid %s;"
            "border-radius:8px;padding:0 16px;font-size:12px;font-weight:700;"
            "letter-spacing:.3px;}" % (fg, bg, bd))
        lb.setVisible(True)

    def mount_board(self, tabs_bar, summary_card, board):
        """Sposta nella colonna destra gli STESSI widget del board Overview.
        setVisible(True) esplicito: set_empty(True) li aveva nascosti."""
        try:
            if board is not None:
                board._card_tabs = True          # tab stint in versione card blu
                # card REF LOCALE (oro): visibile sotto i giri, sopra i tasti
                # (la ONLINE resta esclusa via _no_online_ref sull'overview)
                for i in range(board._ref_slot.count()):
                    _w = board._ref_slot.itemAt(i).widget()
                    if _w is not None:
                        _w.setVisible(True)
                # tasto TELEMETRY: appena sotto l'ultimo giro, in linea coi laps
                _tw = getattr(self, "_tele_w", None)
                if _tw is not None and _tw.parentWidget() is not board:
                    board._ref_slot.addWidget(_tw)
                    _tw.setVisible(True)
                # riga dati stint (lb_summary): l'_AppPage l'aveva spostata in
                # un suo box -> rimettila dentro la card sotto le tab.
                # Qui: niente bg scuro (trasparente) e dati attaccati alle tab.
                if summary_card is not None and summary_card.layout() is not None:
                    summary_card.setStyleSheet(
                        "#ovCard{background:transparent;border:none;}")
                    _scl = summary_card.layout()
                    # riga: dati stint a sinistra + LEGENDA condizioni a destra
                    if not hasattr(self, "_sumrow"):
                        self._sumrow = QWidget()
                        self._sumrow.setStyleSheet("background:transparent;")
                        _hl = QHBoxLayout(self._sumrow)
                        _hl.setContentsMargins(0, 0, 0, 0); _hl.setSpacing(10)
                        self._sumrow_l = _hl
                        _lg = QLabel(
                            "<span style='color:#8a90a0;'>TRACK WATER</span>&nbsp;&nbsp;"
                            "<span style='color:#f5c542;'>DRY &le;10%</span>&nbsp;·&nbsp;"
                            "<span style='color:#9fd8ef;'>DAMP 10&ndash;25%</span>&nbsp;·&nbsp;"
                            "<span style='color:#4ec3ff;'>WET &gt;25%</span>")
                        _lg.setTextFormat(Qt.RichText)
                        _lg.setStyleSheet("font-size:11px;font-weight:700;"
                                          "letter-spacing:.5px;background:transparent;")
                        self._legend = _lg
                    if board.lb_summary.parentWidget() is not self._sumrow:
                        self._sumrow_l.addWidget(board.lb_summary)
                        self._sumrow_l.addStretch(1)
                        self._sumrow_l.addWidget(self._legend)
                    _scl.addWidget(self._sumrow)
                    # nella card c'era anche la lb_summary del board VECCHIO
                    # dell'Overview (vuota): via tutto tranne la riga nostra
                    for i in range(_scl.count()):
                        _w2 = _scl.itemAt(i).widget()
                        if _w2 is not None:
                            _w2.setVisible(_w2 is self._sumrow)
                    board.lb_summary.setContentsMargins(12, 0, 14, 0)
                    self._legend.setContentsMargins(0, 0, 14, 0)
            for w, stretch in ((tabs_bar, 0), (summary_card, 0), (board, 1)):
                if w is None:
                    continue
                pw = w.parentWidget()
                if pw is not None and pw.objectName() == "tpRank":
                    w.setVisible(True); continue   # gia' montato qui
                self._rv.addWidget(w, stretch)
                w.setVisible(True)
        except Exception:
            pass


class _TelemetryPage(_TrackPage):
    """Pagina TELEMETRY nuova: guscio come Sessions/Stint, tab in stile pill
    (WORKSHEET / G-FORCE / TYRES / BRAKES / SUSPENSION). Riusa il QTabWidget
    del motore vecchio (stesse funzioni, meno tab esposte: il resto dei canali
    vive nel Worksheet configurabile col "+"). Tutto in inglese."""

    _DARK_CORNERS = True
    # (testo pill, label tab del QTabWidget vecchio)
    _KEEP = [("WORKSHEET", "Worksheet"), ("G-FORCE", "G-G"),
             ("TYRES", "Tyres"), ("BRAKES", "Brakes"),
             ("SUSPENSION", "Suspension")]

    def __init__(self, on_back=None, parent=None):
        super().__init__(on_sessions=None, on_back=on_back, parent=parent)
        self._exit_locks = False      # back -> stint: DENTRO la sessione
        self._tabsw = None
        try:
            self._btn_sess.setVisible(False)
            self._left_panel.setVisible(False)
            self._filt_row.setVisible(False)
            self._rank_scroll.setVisible(False)
            self._flag.setVisible(False)
            self._rv.setSpacing(6)
        except Exception:
            pass
        # riga pill-tab in alto
        self._pillrow = QWidget()
        self._pillrow.setStyleSheet("background:transparent;")
        _pl = QHBoxLayout(self._pillrow)
        _pl.setContentsMargins(0, 0, 0, 0); _pl.setSpacing(8)
        self._pills = {}
        for txt, lab in self._KEEP:
            b = _PillButton(txt, px=12)
            b.setCheckable(True)
            b.setMinimumSize(110, 36)
            b.clicked.connect(lambda _=False, L=lab: self._pick(L))
            _pl.addWidget(b)
            self._pills[lab] = b
        _pl.addStretch(1)
        # pill MAP: mostra/nasconde la mappa del worksheet (grafici espansi)
        self._map_pill = _PillButton("MAP", px=12)
        self._map_pill.setCheckable(True)
        self._map_pill.setMinimumSize(80, 36)
        self._map_pill.clicked.connect(self._toggle_map)
        _pl.addWidget(self._map_pill)
        self._rv.insertWidget(0, self._pillrow)

    def _worksheet(self):
        try:
            from telemetry.trace_view import _WorksheetTab
            ws = self._tabsw.findChildren(_WorksheetTab)
            return ws[0] if ws else None
        except Exception:
            return None

    def _toggle_map(self):
        ws = self._worksheet()
        if ws is not None:
            ws.set_map_visible(self._map_pill.isChecked())

    def set_session(self, s):
        # titolo = stessa forma della pagina stint (tipo + data/ora)
        s = s or {}
        try:
            from core.engineer import session_kind
            _ty = {"practice": "Practice", "qualy": "Qualifying",
                   "race": "Race"}.get(session_kind(s.get("session_type")), "")
        except Exception:
            _ty = ""
        _d1, _d2 = _SessionCard._fmt_dt(s.get("started_at"))
        _dt = (" - %s %s" % (_d1, _d2)).rstrip() if _d1 != "\u2014" else ""
        self._title.setText(((_ty or "Session") + _dt).upper())

    def _idx_of(self, tabs, label):
        for i in range(tabs.count()):
            if tabs.tabText(i) == label:
                return i
        return -1

    def mount_tabs(self, tabs):
        """Prende in prestito il QTabWidget del motore (stesse funzioni)."""
        if tabs is None:
            return
        self._tabsw = tabs
        try:
            tabs.tabBar().hide()
            tabs.setStyleSheet(
                "QTabWidget::pane{border:none;background:transparent;}")
            pw = tabs.parentWidget()
            if pw is None or pw.objectName() != "tpRank":
                self._rv.addWidget(tabs, 1)
            tabs.setVisible(True)
        except Exception:
            pass
        self._pick("Worksheet")
        ws = self._worksheet()
        if ws is not None:
            # isHidden (flag esplicito): isVisible mente se la pagina
            # non e' ancora mostrata
            self._map_pill.setChecked(not ws.map_w.isHidden())

    def _pick(self, label):
        tabs = self._tabsw
        if tabs is None:
            return
        ix = self._idx_of(tabs, label)
        if ix >= 0:
            tabs.setCurrentIndex(ix)
        for lab, b in self._pills.items():
            b.setChecked(lab == label)


class _OptionsPage(_TrackPage):
    """Pagina OPTIONS (dall'ingranaggio del menu): guscio come le altre pagine
    nuove, angoli scuri, corpo vuoto da riempire. Tutto in inglese."""

    _DARK_CORNERS = True

    def __init__(self, on_back=None, parent=None):
        super().__init__(on_sessions=None, on_back=on_back, parent=parent)
        # OPTIONS e' INDIPENDENTE (dal footer): entrare/uscire non
        # tocca la sessione -> MAI lucchetto (rich. 23/07 notte)
        self._exit_locks = False
        try:
            self._btn_sess.setVisible(False)
            self._left_panel.setVisible(False)
            self._filt_row.setVisible(False)
            self._flag.setVisible(False)
            self._title.setText("OPTIONS")
        except Exception:
            pass

    def _build_filters(self):
        pass

    def mount_overlays(self, w):
        """Monta la tab Overlay esistente (STESSO widget/codice) nel corpo."""
        if w is None:
            return
        try:
            self._rank_scroll.setVisible(False)
            pw = w.parentWidget()
            if pw is None or pw.objectName() != "tpRank":
                self._rv.addWidget(w, 1)
            w.setVisible(True)
        except Exception:
            pass


class _DriverPage(_OptionsPage):
    """Pagina DRIVER: nome/team + risultati (editabili a mano)."""

    def __init__(self, on_back=None, parent=None):
        super().__init__(on_back=on_back, parent=parent)
        try:
            self._title.setText("DRIVER")
        except Exception:
            pass

    def mount_rows(self, rows):
        """Mette le righe (team, results) in una colonna di larghezza sana,
        in alto a sinistra: niente campi sparati in fondo a destra."""
        try:
            self._rank_scroll.setVisible(False)
            box = QWidget()
            box.setObjectName("driverCol")
            box.setStyleSheet("background:transparent;")
            box.setFixedWidth(560)
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(10)
            for r in rows:
                if r is not None:
                    v.addWidget(r)
            v.addStretch(1)
            wrap = QWidget()
            wrap.setStyleSheet("background:transparent;")
            wl = QHBoxLayout(wrap)
            wl.setContentsMargins(40, 26, 40, 26)
            wl.addWidget(box, 0, Qt.AlignTop | Qt.AlignLeft)
            wl.addStretch(1)
            self._rv.addWidget(wrap, 1)
        except Exception:
            pass


class TelemetryWindow(QMainWindow):
    _BTN_IDLE = ("QPushButton{background:#ececed;color:#15151a;font-family:'Archivo SemiExpanded';"
                 "font-weight:500;font-size:12px;letter-spacing:1px;border:none;"
                 "border-radius:5px;padding:0 12px;}"
                 "QPushButton:hover{color:#ff1d43;}")
    _BTN_REC = ("QPushButton{background:#ff1d43;color:#ffffff;font-family:'Archivo SemiExpanded';"
                "font-weight:500;font-size:12px;letter-spacing:1px;border:none;"
                "border-radius:5px;padding:0 12px;}"
                "QPushButton:hover{background:#ff3b5d;}")

    def __init__(self):
        super().__init__()
        self.setWindowTitle("LMU Telemetry Pro")
        self.resize(900, 640)
        self._restore_window_pos()
        # contenitore con sfondo radiale (continua anche dietro al footer)
        central = _RadialBg()
        self._central = central
        col = QVBoxLayout(central)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background:transparent;")
        col.addWidget(self._stack, 1)

        self._app = _AppPage(on_back=self._back_to_menu)   # nuova schermata app
        self._app._central_bg = central
        # click su una card -> pagina pista dedicata (non piu' diretta all'app)
        # SESSIONS -> pagina Sessions (card sessioni); da li' una card -> app
        self._trackpage = _TrackPage(on_sessions=self._open_sessions_page,
                                     on_back=self._back_to_menu)
        self._sessions_page = _SessionsPage(on_open=self._open_session,
                                            on_back=self._back_to_trackpage,
                                            on_teams=self._open_teams,
                                            on_export=self._sess_export,
                                            on_delete=self._sess_delete)
        self._stint_page = _StintPage(on_back=self._back_to_sessions)
        self._stint_page._add_telemetry_btn(self._open_telemetry,
                                            self._open_setups_tab)
        self._menu = _RootCanvas(on_open=self._open_track_page,
                                 on_community=self._open_community,
                                 on_setups=self._open_setups,
                                 on_overlay=self._open_overlay,
                                 on_teams=self._open_teams)
        self._stack.addWidget(self._menu)
        self._stack.addWidget(self._trackpage)
        self._stack.addWidget(self._sessions_page)
        self._stack.addWidget(self._stint_page)
        self._stack.addWidget(self._app)
        # pagina OPTIONS (ingranaggio del menu)
        self._options_page = _OptionsPage(on_back=self._back_to_menu)
        self._stack.addWidget(self._options_page)
        # pagina DRIVER (icona nel footer accanto a settings): nome/team/risultati
        self._driver_page = _DriverPage(on_back=self._back_to_menu)
        self._stack.addWidget(self._driver_page)
        # pagina TELEMETRY nuova (dal tasto TELEMETRY della pagina stint)
        self._telemetry_page = _TelemetryPage(on_back=self._back_to_stint)
        self._stack.addWidget(self._telemetry_page)
        try:
            self._menu.banner._on_settings = self._open_options
        except Exception:
            pass

        # ── FOOTER unico (barra in basso, trasparente, occupa spazio) ──
        self._footer = QWidget()
        self._footer.setStyleSheet("background:rgba(9,13,20,0.59);")
        fl = QHBoxLayout(self._footer)
        fl.setContentsMargins(24, 11, 26, 11)   # simmetrici: tutto su UNA riga
        # nome app + versione: a SINISTRA, prima del check intro
        # logo "MURETTO" per PRIMO a sinistra (stile intro: Archivo corsivo, rosso LMU)
        _mlab = QLabel("MURETTO")
        _mlab.setStyleSheet(
            "QLabel{font-family:'Archivo SemiExpanded','Archivo';"
            "font-style:normal;font-weight:800;color:#ff2800;font-size:20px;"
            "letter-spacing:1px;background:transparent;}")
        fl.addWidget(_mlab, 0, Qt.AlignVCenter)
        fl.addSpacing(10)
        _flab = QLabel("LMU Telemetry Pro  %s" % _APP_VERSION)
        _flab.setStyleSheet("color:#aeb6c4;font-size:14px;font-weight:400;"
                            "background:transparent;")
        fl.addWidget(_flab, 0, Qt.AlignVCenter)
        # DOCS: pill blu SUBITO DOPO la versione (richiesta utente). Icona globo
        # spostata un po' a destra e in basso via offset di render.
        def _globe_icon(dx, dy):
            from PySide6.QtGui import QIcon
            from PySide6.QtCore import QRectF
            from ui.icons import GLOBE_SVG as _G
            r = QSvgRenderer(QByteArray(_G.encode("utf-8")))
            pm = QPixmap(32, 32); pm.fill(Qt.transparent)
            pp = QPainter(pm); pp.setRenderHint(QPainter.Antialiasing, True)
            r.render(pp, QRectF(dx, dy, 26.0, 26.0))
            pp.end()
            return QIcon(pm)
        _dc = QPushButton("Docs")
        _dc.setObjectName("ftDocs")
        _dc.setCursor(Qt.PointingHandCursor)
        _dc.setStyleSheet(
            "QPushButton#ftDocs{color:#ffffff;font-size:14px;font-weight:700;"
            "background:transparent;border:none;padding:4px 8px;}"
            "QPushButton#ftDocs:hover{color:#c9ccd3;}")
        try:
            _dc.setIcon(_globe_icon(7, 7))       # 7px a destra e in basso
            _dc.setIconSize(QSize(16, 16))
            _dc.setLayoutDirection(Qt.RightToLeft)
        except Exception:
            pass
        _dc.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(_GITHUB_URL + "#readme")))
        fl.addSpacing(12); fl.addWidget(_dc, 0, Qt.AlignVCenter)
        fl.addSpacing(18)
        # riga "Video intro" (check tondo): vive nella 3a colonna di OPTIONS
        from ui.widgets import _CircleCheck
        try:
            _on0 = bool(_load_profile().get("intro_video", True))
        except Exception:
            _on0 = True
        self._introrow = QWidget()
        self._introrow.setObjectName("widgetRow")
        self._introrow.setFixedHeight(46)
        _irl = QHBoxLayout(self._introrow)
        _irl.setContentsMargins(14, 0, 12, 0)
        self._intro_lbl = QLabel("")
        self._intro_lbl.setTextFormat(Qt.RichText)
        self._intro_lbl.setObjectName("widgetName")
        self._set_intro_lbl(_on0)
        _irl.addWidget(self._intro_lbl, 0, Qt.AlignVCenter)
        _irl.addStretch(1)
        self._intro_chk = _CircleCheck(_on0, "#ff1d43", self._intro_click)
        _irl.addWidget(self._intro_chk, 0, Qt.AlignVCenter)
        # riga "Team" (editabile): scrive il team nel profilo; l'header lo mostra
        self._teamrow = QWidget()
        self._teamrow.setObjectName("widgetRow")
        self._teamrow.setFixedHeight(46)
        _trl = QHBoxLayout(self._teamrow)
        _trl.setContentsMargins(14, 0, 12, 0)
        _tnm = QLabel("Team"); _tnm.setObjectName("widgetName")
        _trl.addWidget(_tnm, 0, Qt.AlignVCenter)
        _trl.addStretch(1)
        self._team_edit = QLineEdit()
        self._team_edit.setMaxLength(30); self._team_edit.setFixedWidth(220)
        self._team_edit.setPlaceholderText("Your team")
        try:
            self._team_edit.setText(_load_profile().get("team", "") or "")
        except Exception:
            pass
        self._team_edit.setStyleSheet(
            "QLineEdit{color:#ffffff;background:rgba(255,255,255,0.08);"
            "border:none;border-radius:8px;padding:5px 10px;font-size:13px;}"
            "QLineEdit:focus{border:1px solid #ff1d43;}")
        self._team_edit.editingFinished.connect(self._save_team_opt)
        _trl.addWidget(self._team_edit, 0, Qt.AlignVCenter)
        # riga "Results" (editabile): correggi gare/vittorie ecc. a mano
        # (es. storico 2024 che LMU non espone). Vuoto -> automatico dalle sessioni.
        from PySide6.QtWidgets import QSpinBox as _QSpin
        self._resultsrow = QWidget()
        self._resultsrow.setObjectName("widgetRow")
        _rrl = QVBoxLayout(self._resultsrow)
        _rrl.setContentsMargins(14, 10, 12, 10); _rrl.setSpacing(7)
        _rnm = QLabel("Results"); _rnm.setObjectName("widgetName")
        _rrl.addWidget(_rnm)
        try:
            from core.results import race_stats as _rstat
            _auto = _rstat()
        except Exception:
            _auto = {}
        try:
            _pf0 = _load_profile()
        except Exception:
            _pf0 = {}
        self._stat_spins = {}
        for _k, _cap in (("races", "Races"), ("wins", "Wins"),
                         ("podiums", "Podiums"), ("top5", "Top 5"),
                         ("dnf", "DNF")):
            _line = QHBoxLayout()
            _line.setContentsMargins(8, 0, 0, 0); _line.setSpacing(6)
            _cl = QLabel(_cap)
            _cl.setStyleSheet("color:#9fb0c8;font-size:13px;font-weight:600;"
                              "background:transparent;")
            _line.addWidget(_cl, 0, Qt.AlignVCenter)
            _line.addStretch(1)
            _sp = _QSpin(); _sp.setRange(0, 9999); _sp.setFixedWidth(92)
            _sp.setValue(int(_pf0.get("stat_" + _k, _auto.get(_k, 0))))
            _sp.setStyleSheet(
                "QSpinBox{color:#fff;background:rgba(255,255,255,0.08);"
                "border:none;border-radius:6px;padding:3px 24px 3px 8px;"
                "font-size:13px;}"
                "QSpinBox::up-button{subcontrol-origin:border;"
                "subcontrol-position:top right;width:20px;border:none;"
                "border-top-right-radius:6px;background:rgba(255,255,255,0.12);}"
                "QSpinBox::down-button{subcontrol-origin:border;"
                "subcontrol-position:bottom right;width:20px;border:none;"
                "border-bottom-right-radius:6px;background:rgba(255,255,255,0.12);}"
                "QSpinBox::up-button:hover,QSpinBox::down-button:hover{"
                "background:#ff1d43;}"
                "QSpinBox::up-arrow{width:0;height:0;image:none;"
                "border-left:4px solid transparent;border-right:4px solid transparent;"
                "border-bottom:5px solid #eef1f6;}"
                "QSpinBox::down-arrow{width:0;height:0;image:none;"
                "border-left:4px solid transparent;border-right:4px solid transparent;"
                "border-top:5px solid #eef1f6;}")
            _sp.valueChanged.connect(lambda v, k=_k: self._save_stat_opt(k, v))
            self._stat_spins[_k] = _sp
            _line.addWidget(_sp, 0, Qt.AlignVCenter)
            _rrl.addLayout(_line)
        # riga "Music" (check tondo): stessa fattura della riga intro
        try:
            _mus0 = bool(_load_profile().get("music_on", True))
        except Exception:
            _mus0 = True
        self._musicrow = QWidget()
        self._musicrow.setObjectName("widgetRow")
        self._musicrow.setFixedHeight(46)
        _mrl = QHBoxLayout(self._musicrow)
        _mrl.setContentsMargins(14, 0, 12, 0)
        self._music_lbl = QLabel("")
        self._music_lbl.setTextFormat(Qt.RichText)
        self._music_lbl.setObjectName("widgetName")
        self._set_music_lbl(_mus0)
        _mrl.addWidget(self._music_lbl, 0, Qt.AlignVCenter)
        _mrl.addStretch(1)
        # cursore VOLUME musica app (0..100): salva su profilo + applica live
        from PySide6.QtWidgets import QSlider
        try:
            _mv0 = int(_load_profile().get("music_vol", 40))
        except Exception:
            _mv0 = 40
        self._music_vol = QSlider(Qt.Horizontal)
        self._music_vol.setRange(0, 100)
        self._music_vol.setValue(max(0, min(100, _mv0)))
        self._music_vol.setFixedWidth(120)
        self._music_vol.setCursor(Qt.PointingHandCursor)
        self._music_vol.setStyleSheet(
            "QSlider::groove:horizontal{height:4px;background:#3a3d47;"
            "border-radius:2px;}"
            "QSlider::sub-page:horizontal{height:4px;background:#ff1d43;"
            "border-radius:2px;}"
            "QSlider::handle:horizontal{width:12px;height:12px;margin:-5px 0;"
            "background:#ffffff;border-radius:6px;}")
        self._music_vol.valueChanged.connect(self._music_vol_changed)
        _mrl.addWidget(self._music_vol, 0, Qt.AlignVCenter)
        _mrl.addSpacing(12)
        self._music_chk = _CircleCheck(_mus0, "#ff1d43", self._music_click)
        _mrl.addWidget(self._music_chk, 0, Qt.AlignVCenter)
        # riga "Lock overlays": BLOCCA il trascinamento degli overlay
        def _lock_get():
            # dal config IN MEMORIA (sempre allineato col file)
            try:
                from core.config import get_config as _gc
                return bool(_gc()._data.get("overlay", {})
                            .get("lock", False))
            except Exception:
                return False

        def _lock_set(v):
            # via config UNICO: memoria + salvataggio atomico, cosi'
            # i salvataggi successivi dell'app non lo sovrascrivono
            try:
                from core.config import get_config as _gc
                _c = _gc()
                _c.set_value("overlay", "lock", bool(v))
                _c.save()
            except Exception:
                pass
        self._lockrow = QWidget()
        self._lockrow.setObjectName("widgetRow")
        self._lockrow.setFixedHeight(46)
        _lrl = QHBoxLayout(self._lockrow)
        _lrl.setContentsMargins(14, 0, 12, 0)
        self._lock_lbl = QLabel("Lock overlays")
        self._lock_lbl.setObjectName("widgetName")
        _lrl.addWidget(self._lock_lbl, 0, Qt.AlignVCenter)
        _lrl.addStretch(1)
        def _lock_click(*_a):
            _v = not _lock_get()
            _lock_set(_v)
            self._lock_chk.setChecked(_v)   # il check NON si
                                            # aggiorna da solo
        self._lock_chk = _CircleCheck(_lock_get(), "#ff1d43",
                                      _lock_click)
        _lrl.addWidget(self._lock_chk, 0, Qt.AlignVCenter)
        # riga "Driver": opzione in Options con rotellina -> apre la pagina Driver
        self._driverrow = QWidget()
        self._driverrow.setObjectName("widgetRow")
        self._driverrow.setFixedHeight(46)
        _dvl = QHBoxLayout(self._driverrow)
        _dvl.setContentsMargins(14, 0, 12, 0)
        _dvnm = QLabel("Driver"); _dvnm.setObjectName("widgetName")
        _dvl.addWidget(_dvnm, 0, Qt.AlignVCenter)
        _dvl.addStretch(1)
        self._driver_gear = QPushButton("⚙")
        self._driver_gear.setCursor(Qt.PointingHandCursor)
        self._driver_gear.setFixedSize(28, 28)
        self._driver_gear.setStyleSheet(
            "QPushButton{background:rgba(255,255,255,0.08);color:#cfd6e2;"
            "border:none;border-radius:14px;font-size:15px;}"
            "QPushButton:hover{color:#ff1d43;background:rgba(255,255,255,0.16);}")
        self._driver_gear.clicked.connect(self._open_driver)
        _dvl.addWidget(self._driver_gear, 0, Qt.AlignVCenter)
        # riga "Team dev": galleria con le CARD di tutti i brand
        # (colori/loghi/angoli dalla libreria, per revisione visiva)
        def _open_teamdev(*_a):
            try:
                if getattr(self, "_teamdev_win", None) is not None:
                    self._teamdev_win.show()
                    self._teamdev_win.raise_()
                    return
                from PySide6.QtWidgets import QScrollArea
                from ui.tab_community import _RankRow
                from core.wec_style import BRANDS
                w = QWidget()
                w.setWindowTitle("TEAM DEV — card brand")
                w.setStyleSheet("background:#0d0d15;")
                w.resize(1180, 820)
                _v = QVBoxLayout(w)
                _v.setContentsMargins(10, 10, 10, 10)
                sc = QScrollArea()
                sc.setWidgetResizable(True)
                sc.setFrameShape(QFrame.NoFrame)
                host = QWidget()
                hv = QVBoxLayout(host)
                hv.setContentsMargins(0, 0, 0, 0)
                hv.setSpacing(8)
                base = 105000
                for i, b in enumerate(sorted(BRANDS.keys()), start=1):
                    rec = {"player": "Team Dev", "car": b,
                           "team": b.upper(),
                           "lap_ms": base + i * 137,
                           "s1_ms": 33000 + i * 41,
                           "s2_ms": 38000 + i * 53,
                           "s3_ms": 34000 + i * 43,
                           "compound": "M", "tyre_state_pct": 97.0,
                           "fuel_l": 12.0, "helmet": "#fd160e",
                           "car_class": "HY"}
                    hv.addWidget(_RankRow(i, rec, base))
                # ── TEST provvisorio: la MFD CARD per ogni brand ──
                try:
                    from widgets.wec26mfd.widget import (
                        Wec26MfdOverlay, _W as _MW, _H as _MH)
                    from PySide6.QtGui import QPixmap as _QPM, \
                        QPainter as _QP
                    for b in sorted(BRANDS.keys()):
                        o = Wec26MfdOverlay.__new__(Wec26MfdOverlay)
                        o._brand = b
                        o._place = 14
                        pm = _QPM(_MW, _MH)
                        pm.fill(Qt.transparent)
                        pp = _QP(pm)
                        pp.setRenderHint(_QP.Antialiasing)
                        pp.setRenderHint(_QP.TextAntialiasing)
                        pp.setRenderHint(_QP.SmoothPixmapTransform)
                        o._paint_frame(pp)
                        pp.end()
                        lb = QLabel()
                        lb.setPixmap(pm)
                        lb.setStyleSheet("background:transparent;")
                        hv.addWidget(lb)
                except Exception:
                    pass
                hv.addStretch(1)
                sc.setWidget(host)
                _v.addWidget(sc)
                self._teamdev_win = w
                w.show()
            except Exception:
                pass
        self._teamdevrow = QWidget()
        self._teamdevrow.setObjectName("widgetRow")
        self._teamdevrow.setFixedHeight(46)
        _tdl = QHBoxLayout(self._teamdevrow)
        _tdl.setContentsMargins(14, 0, 12, 0)
        _td_lbl = QLabel("Team dev")
        _td_lbl.setObjectName("widgetName")
        _tdl.addWidget(_td_lbl, 0, Qt.AlignVCenter)
        _tdl.addStretch(1)
        _td_btn = QPushButton("OPEN")
        _td_btn.setCursor(Qt.PointingHandCursor)
        _td_btn.setFixedHeight(24)
        _td_btn.setStyleSheet(
            "QPushButton{color:#ffffff;background:#2a2a3c;border:none;"
            "border-radius:12px;padding:2px 14px;font-size:11px;"
            "font-weight:700;}"
            "QPushButton:hover{background:#ff1d43;}")
        _td_btn.clicked.connect(_open_teamdev)
        _tdl.addWidget(_td_btn, 0, Qt.AlignVCenter)
        if not _mus0:
            try:
                from core.soundtrack import Soundtrack
                Soundtrack.instance().set_enabled(False)
            except Exception:
                pass
        self._status_banner = QLabel("")
        self._status_banner.setObjectName("statusBanner")
        self._status_banner.setVisible(False)
        fl.addWidget(self._status_banner, 0, Qt.AlignVCenter | Qt.AlignLeft)
        fl.addStretch(1)
        # notifica AGGIORNAMENTO nel footer NUOVO (quella del legacy e' nascosta)
        self._upd_btn = QPushButton("")
        self._upd_btn.setCursor(Qt.PointingHandCursor)
        self._upd_btn.setVisible(False)
        self._upd_btn.setStyleSheet(
            "QPushButton{color:#ffffff;font-size:14px;font-weight:bold;"
            "background:#ff1d43;border:none;border-radius:12px;padding:4px 14px;}"
            "QPushButton:hover{background:#ff3b5d;}")
        fl.addWidget(self._upd_btn, 0, Qt.AlignVCenter)
        fl.addSpacing(14)
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        # Donate + logo PayPal: UN solo bottone (testo bianco medium + svg)
        _dw = QWidget()
        _dw.setObjectName("ftDonateBox")
        _dw.setCursor(Qt.PointingHandCursor)
        # PILLINA blu stile BuyMeACoffee (rich. 23/07): si deve VEDERE
        _dw.setStyleSheet(
            "#ftDonateBox{background:#6f9ceb;border-radius:15px;}"
            "#ftDonateBox:hover{background:#7fa9f2;}")
        # SUPPORT ME con la tazzina col cuore (rich. 23/07, al posto
        # del vecchio Donate/PayPal — il link resta lo stesso)
        _dl = QHBoxLayout(_dw); _dl.setContentsMargins(14, 4, 14, 4)
        _dl.setSpacing(7)
        # tazzina in un contenitore fisso: cosi' puo' SALTELLARE ogni
        # 10 secondi senza spostare il layout (rich. 23/07 notte)
        _ppwrap = QWidget(); _ppwrap.setFixedSize(20, 24)
        _ppwrap.setStyleSheet("background:transparent;")
        _pp = _SvgBox(); _pp.setParent(_ppwrap)
        _pp.setGeometry(0, 1, 20, 20)   # allineata alla scritta (23/07)
        _pp.setStyleSheet("background:transparent;")
        _pp.load(str(Path(__file__).resolve().parent.parent / "assets"
                     / "support_cup.svg"))
        _dl.addWidget(_ppwrap, 0, Qt.AlignVCenter)
        from PySide6.QtCore import (QPropertyAnimation, QPoint,
                                    QEasingCurve, QTimer as _QThop)
        self._cup_anim = QPropertyAnimation(_pp, b"pos", self)
        self._cup_anim.setDuration(700)
        self._cup_anim.setStartValue(QPoint(0, 1))
        self._cup_anim.setKeyValueAt(0.22, QPoint(0, -5))   # hop!
        self._cup_anim.setKeyValueAt(0.45, QPoint(0, 1))
        self._cup_anim.setKeyValueAt(0.62, QPoint(0, -2))   # hop piccolo
        self._cup_anim.setEndValue(QPoint(0, 1))
        self._cup_anim.setEasingCurve(QEasingCurve.OutQuad)
        self._cup_timer = _QThop(self)
        self._cup_timer.timeout.connect(
            lambda: self._cup_anim.start())
        self._cup_timer.start(10000)
        _dn = QLabel("Support me")
        _dn.setStyleSheet("color:#17181c;font-size:14px;font-weight:800;"
                          "background:transparent;")
        _dl.addWidget(_dn, 0, Qt.AlignVCenter)
        _dw.mousePressEvent = (
            lambda e: QDesktopServices.openUrl(QUrl(_DONATE_URL)))
        fl.addWidget(_dw, 0, Qt.AlignVCenter)
        # GitHub: pill nera · Docs: pill blu
        _gh = QPushButton("GitHub ")   # spazio: stacca l'icona dal testo
        _gh.setObjectName("ftGh")
        _gh.setCursor(Qt.PointingHandCursor)
        _gh.setStyleSheet(
            "QPushButton#ftGh{color:#ffffff;font-size:14px;font-weight:700;"
            "background:transparent;border:none;padding:4px 8px;}"
            "QPushButton#ftGh:hover{color:#c9ccd3;}")
        _gh.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(_GITHUB_URL)))
        # icona DOPO il testo: QIcon da SVG + layout RightToLeft
        def _svg_icon(svg):
            from PySide6.QtGui import QIcon
            r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
            pm = QPixmap(32, 32); pm.fill(Qt.transparent)
            pp = QPainter(pm); pp.setRenderHint(QPainter.Antialiasing, True)
            r.render(pp); pp.end()
            return QIcon(pm)
        try:
            from ui.icons import GITHUB_MARK_SVG, GLOBE_SVG
            _gh.setIcon(_svg_icon(GITHUB_MARK_SVG))
            _gh.setIconSize(QSize(15, 15))
            _gh.setLayoutDirection(Qt.RightToLeft)
        except Exception:
            pass
        fl.addSpacing(8); fl.addWidget(_gh, 0, Qt.AlignVCenter)
        # rotella OPTIONS in fondo a DESTRA (spostata dall'header):
        # la scritta esce a SINISTRA della rotella in hover
        _fgw = QWidget(); _fgw.setStyleSheet("background:transparent;")
        _fgv = QHBoxLayout(_fgw); _fgv.setContentsMargins(0, 0, 0, 0)
        _fgv.setSpacing(2)
        _fgcap = QLabel("OPTIONS")
        _fgcap.setStyleSheet(
            "color:#ffffff;font-family:'Archivo SemiExpanded';font-size:13px;"
            "font-weight:600;letter-spacing:1px;background:transparent;")
        _fgcap.setMaximumWidth(0)                # ritratta a riposo
        _fgv.addWidget(_fgcap, 0, Qt.AlignVCenter)
        self._ft_gear = _GearButton()
        self._ft_gear.clicked.connect(self._open_options)
        _fgv.addWidget(self._ft_gear, 0, Qt.AlignVCenter)
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve
        _fanim = QPropertyAnimation(_fgcap, b"maximumWidth", self)
        _fanim.setDuration(180)
        _fanim.setEasingCurve(QEasingCurve.OutCubic)

        def _ft_gear_hover(on, a=_fanim, lb=_fgcap):
            a.stop()
            a.setStartValue(lb.maximumWidth())
            a.setEndValue(lb.sizeHint().width() + 6 if on else 0)
            a.start()
        self._ft_gear._hover_cb = _ft_gear_hover
        fl.addSpacing(12); fl.addWidget(_fgw, 0, Qt.AlignVCenter)
        # START rimosso dal footer (registrazione automatica); oggetto tenuto
        # nascosto così gli aggiornamenti di stato non causano errori
        self._btn_start = QPushButton("START", self._footer)
        self._btn_start.setStyleSheet(self._BTN_IDLE)
        self._btn_start.clicked.connect(self._toggle_start)
        self._btn_start.setVisible(False)
        col.addWidget(self._footer)
        self.setCentralWidget(central)
        # righe Video intro + Music nella 3a colonna della pagina OPTIONS
        try:
            # team + results -> pagina DRIVER (aperta dalla rotellina della riga)
            self._driver_page.mount_rows([self._teamrow, self._resultsrow])
            self._app._legacy._overlaytab._extra_col.insertWidget(0, self._driverrow)
            self._app._legacy._overlaytab._extra_col.insertWidget(1, self._introrow)
            self._app._legacy._overlaytab._extra_col.insertWidget(2, self._musicrow)
            self._app._legacy._overlaytab._extra_col.insertWidget(3, self._lockrow)
            # Team dev NASCOSTO (pulizia 20/07): la galleria brand resta
            # nel codice, riga non inserita — per riaverla basta questa:
            # self._app._legacy._overlaytab._extra_col.insertWidget(3, self._teamdevrow)
            self._teamdevrow.hide()
        except Exception:
            pass

        self._app._armed_hook = self.set_armed             # bottone segue lo stato reale
        self._app._top_hook = self._music_sync             # musica segue la pagina interna
        self._app._banner_hook = self.set_banner           # banner stato recorder nel footer
        # update check del legacy -> notifica nel footer nuovo
        try:
            self._app._legacy._update_hook = self._show_update
        except Exception:
            pass
        # pagina stint: card REF solo LOCALE (niente online), versione COMPATTA
        try:
            self._app._legacy._overview._no_online_ref = True
            self._app._legacy._overview._compact_ref = True
        except Exception:
            pass
        # live agganciata dall'auto-focus -> aggiorna la pagina stint nuova
        self._app._stint_live_hook = self._on_live_ready
        # REFRESH LIVE dei giri sulla pagina stint: il _live_refresh del legacy
        # e' gated su "review visibile" e nel flusso nuovo restava muto fino a
        # fine sessione. Qui lo forziamo noi ogni 4s finche' sei armato.
        self._live_poll = QTimer(self)
        self._live_poll.setInterval(4000)
        self._live_poll.timeout.connect(self._live_poll_tick)
        self._live_poll.start()
        # orologio sessione live sulla pagina stint (specchia app._sess_time)
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._sync_stint_clock)
        self._clock_timer.start()
        self._stack.currentChanged.connect(lambda *_: self._update_footer())
        # colonna sonora: traccia scelta dalla pagina corrente
        self._stack.currentChanged.connect(lambda *_: self._music_sync())
        self._stack.currentChanged.connect(
            lambda *_: self._update_footer())

        intro = self._make_intro()
        self._intro_page = intro
        if intro is not None:
            self._stack.addWidget(intro)
            self._stack.setCurrentWidget(intro)
        else:
            self._stack.setCurrentWidget(self._menu)
        self._update_footer()
        # kick iniziale: se il menu era gia' il widget corrente il segnale
        # currentChanged non scatta e la musica non partirebbe mai
        self._music_sync()

    # ---- footer / bottone unico ----
    def set_armed(self, armed):
        was = getattr(self, "_armed_state", False)
        self._armed_state = armed
        if armed:
            self._btn_start.setText("STOP")
            self._btn_start.setStyleSheet(self._BTN_REC)
        else:
            self._btn_start.setText("START")
            self._btn_start.setStyleSheet(self._BTN_IDLE)
        # appena armato: mostra la pagina app (esci dal menu). La SELEZIONE della
        # sessione live la fa show_live_session() quando il file è pronto: NON
        # navigare qui (in garage la sessione non è ancora selezionabile -> finiva
        # su una sessione vecchia col nome-file).
        if armed and not was:
            self._goto_stint_live()              # live -> pagina stint nuova
            self._update_footer()

    def _update_footer(self):
        """Footer FISSO su TUTTE le pagine (rich. 23/07: era sparito
        fuori dalla home) — via solo durante il video intro."""
        _w9 = self._stack.currentWidget()
        self._footer.setVisible(
            _w9 is not getattr(self, "_intro_page", None))

    _BANNER_COLS = {
        "idle": ("#989ba2", "#16171a", "#2a2c30"),
        "wait": ("#f0a23a", "#241a10", "#8a5a1e"),
        "rec":  ("#2ecc71", "#122017", "#2e7d52"),
    }

    def set_banner(self, kind, text):
        """Banner di stato del recorder nel footer (testo + colore)."""
        bn = getattr(self, "_status_banner", None)
        if bn is None:
            return
        # (niente replica accanto ai tasti della pagina stint: basta il footer)
        if kind == "idle":                      # auto-start: niente messaggio a riposo
            self._banner_cache = None
            bn.setVisible(False)
            return
        if (kind, text) == getattr(self, "_banner_cache", None):
            return
        self._banner_cache = (kind, text)
        fg, bg, bd = self._BANNER_COLS.get(kind, self._BANNER_COLS["idle"])
        bn.setText(text)
        bn.setStyleSheet(
            "QLabel#statusBanner{color:%s;background:%s;border:1px solid %s;"
            "border-radius:8px;padding:5px 12px;font-size:12px;font-weight:600;"
            "letter-spacing:.3px;}" % (fg, bg, bd))
        bn.setVisible(True)

    def _toggle_start(self):
        """START/STOP unico: se fermo arma e porta sulla sessione attiva; se in
        registrazione ferma."""
        app = self._app
        leg = getattr(app, "_legacy", None)
        rec = getattr(leg, "_recorder", None) if leg else None
        armed = bool(rec) and rec.is_armed()
        if leg is None:
            return
        try:
            leg._toggle_rec()
        except Exception:
            pass
        if not armed:                  # ora armato: vai alla sessione attiva
            app.show_live_session()
            self._goto_stint_live()    # live -> pagina stint nuova
        self.set_armed(bool(rec) and rec.is_armed())

    def _open_track_page(self, idx):
        """Click su una card layout → pagina pista dedicata (info + classifiche).
        Da li' il tasto SESSIONS apre la sessione vera (_open_app)."""
        try:
            base, bgkey, name, logo, cmap = _TRACKS[idx]
            self._trackpage.set_track(idx, base, name, cmap, bgkey)
        except Exception:
            pass
        self._stack.setCurrentWidget(self._trackpage)

    def _open_sessions_page(self, idx):
        """Tasto SESSIONS della track page -> pagina Sessions (card sessioni)."""
        try:
            base, bgkey, name, logo, cmap = _TRACKS[idx]
            self._sessions_page.set_track(idx, base, name, cmap, bgkey)
        except Exception:
            pass
        self._stack.setCurrentWidget(self._sessions_page)

    def _back_to_trackpage(self):
        """Back dalla pagina Sessions -> track page (o menu se mai aperta)."""
        if getattr(self._trackpage, "_idx", None) is None:
            self._back_to_menu()
            return
        self._stack.setCurrentWidget(self._trackpage)

    def _set_overview_left(self, on):
        """Mostra/nasconde la colonna sinistra (lista sessioni) dell'Overview."""
        try:
            self._app._legacy._overview.set_left_visible(on)
        except Exception:
            pass

    def _resolve_track_entry(self, trk):
        """Nome pista LMU -> entry _TRACKS (layout esatto, fallback base)."""
        try:
            _lk = _track_layout_key(trk)
            _ent = next((e for e in _TRACKS
                         if _cmap_layout_key(e[4]) == _lk), None)
            if _ent is None:
                _st = _track_logo_stem(trk)
                _ent = next((e for e in _TRACKS if e[3] == _st), None)
            return _ent
        except Exception:
            return None

    def _back_to_sessions(self):
        """Back dalla pagina stint -> pagina Sessions, lista rinfrescata.
        Se la pagina non era mai stata inizializzata (live partito prima dei
        metadati), la ricostruisce dalla sessione corrente."""
        sp = self._sessions_page
        try:
            if sp._idx is None:
                _trk = (getattr(self, "_last_sess", None) or {}).get("track") or ""
                _ent = self._resolve_track_entry(_trk)
                if _ent is not None:
                    sp._idx = _TRACKS.index(_ent)
            if sp._idx is not None:
                e = _TRACKS[sp._idx]
                sp.set_track(sp._idx, e[0], e[2], e[4], e[1])
                self._trackpage.set_track(sp._idx, e[0], e[2], e[4], e[1])
        except Exception:
            pass
        if sp._idx is None:
            self._back_to_menu()           # niente pista nota: meglio il menu
            return
        self._stack.setCurrentWidget(sp)

    def _open_options(self):
        """Ingranaggio del menu -> pagina OPTIONS (con gli overlay dentro)."""
        try:
            self._options_page.mount_overlays(self._app._legacy._overlaytab)
        except Exception:
            pass
        self._stack.setCurrentWidget(self._options_page)

    def _open_driver(self):
        """Icona DRIVER del footer -> pagina Driver (nome/team/risultati)."""
        self._stack.setCurrentWidget(self._driver_page)

    def _back_to_stint(self):
        """Back dalla pagina Telemetry -> torna alla pagina stint."""
        self._stack.setCurrentWidget(self._stint_page)

    def _open_telemetry(self):
        """Tasto TELEMETRY della pagina stint -> pagina TELEMETRY nuova
        (stesso motore: worksheet configurabile + G-Force/Tyres/Brakes/Susp)."""
        try:
            leg = self._app._legacy
            self._telemetry_page._bgkey = getattr(self._stint_page, "_bgkey", None)
            self._telemetry_page.set_session(getattr(self, "_last_sess", None))
            self._telemetry_page.mount_tabs(leg.tabs)
        except Exception:
            pass
        self._stack.setCurrentWidget(self._telemetry_page)

    def _open_setups_tab(self):
        """Tasto SETUPS della pagina stint -> tab Setups dell'app."""
        try:
            self._app._menu_mode(False)
            self._app._select_top(2)          # 2 = Setups
            self._central.set_photo(self._app._circuit_photo())   # bg overview.jpg
            for _b in self._app._toptabs:     # niente vecchie tab: si naviga
                _b.setVisible(False)          # dai tasti della pagina stint
        except Exception:
            pass
        self._app_return_stint = True         # back -> pagina stint
        try:
            self._app._return_stint = True     # flag SULLA pagina
            self._app._apply_back_lock(getattr(self._app, "_armed",
                                               False))
        except Exception:
            pass
        self._stack.setCurrentWidget(self._app)
        self._music_sync()                    # forza la traccia setups (stato ora completo)

    def _restore_board(self):
        """Rimette il board nell'Overview (se era stato prestato alla pagina stint)."""
        try:
            leg = self._app._legacy
            leg._overview.board._card_tabs = False   # tab tornano allo stile Overview
            leg._overview.remount_board()
            leg._sync_board()
        except Exception:
            pass

    def _sync_stint_clock(self):
        """Tempo sessione in corso sulla riga titolo della pagina stint."""
        try:
            lb = getattr(self._app, "_sess_time", None)
            ck = getattr(self._stint_page, "_clock", None)
            if lb is None or ck is None:
                return
            txt = lb.text() if not lb.isHidden() else ""
            rec = getattr(self._app._legacy, "_recorder", None)
            on = bool(txt) and bool(rec) and rec.is_armed()
            ck.setText(txt if on else "")
            ck.setVisible(on)
        except Exception:
            pass

    def _music_sync(self):
        """Colonna sonora: telemetria = traccia telemetry, resto = home;
        durante l'intro (widget non riconosciuto) niente musica."""
        try:
            from core.soundtrack import Soundtrack
            w = self._stack.currentWidget()
            if w is getattr(self, "_app", None):
                # dentro l'app: Setups (top 2) ha la SUA traccia, il resto
                # e' mondo telemetria
                t = "setups" if getattr(self._app, "_cur_top", 0) == 2 \
                    else "telemetry"
            elif w is getattr(self, "_telemetry_page", None):
                t = "telemetry"
            elif w in (getattr(self, "_trackpage", None),
                       getattr(self, "_sessions_page", None),
                       getattr(self, "_stint_page", None)):
                t = "community"            # circuiti -> sessioni -> stint: persiste
            elif w in (getattr(self, "_menu", None),
                       getattr(self, "_options_page", None)):
                t = "home"
            else:
                t = None
            Soundtrack.instance().set_screen(t)
        except Exception:
            pass

    def _live_poll_tick(self):
        """Ogni 4s in registrazione: sblocca il gate del legacy (review
        visibile) e fa girare il suo _live_refresh -> giri nuovi nel board
        della pagina stint IN TEMPO REALE."""
        # colonna sonora: sessione armata = musica sfumata e ferma,
        # disarmo (sessione chiusa) = riprende. Va PRIMA del gate qui sotto.
        try:
            from core.soundtrack import Soundtrack
            _rec0 = getattr(self._app._legacy, "_recorder", None)
            Soundtrack.instance().set_live(bool(_rec0 and _rec0.is_armed()))
        except Exception:
            pass
        try:
            leg = self._app._legacy
            rec = getattr(leg, "_recorder", None)
            if not (rec and rec.is_armed()):
                return
            leg._user_picked_session = True
            leg.stack.setCurrentWidget(leg._review_page)
            leg._live_refresh()
        except Exception:
            pass

    def _on_live_ready(self, s):
        """Chiamato dall'auto-focus quando la sessione LIVE e' agganciata:
        aggiorna titolo/sfondo della pagina stint, monta il board e sincronizza.
        (Fix: all'arm il file non esiste ancora -> pagina restava vuota.)"""
        try:
            leg = self._app._legacy
            ov = leg._overview
            leg._user_picked_session = True
            if s:
                self._last_sess = s
                try:
                    # foto del LAYOUT esatto (es. silverstone_national), non
                    # della base: come fa il focus per lo sfondo dell'app
                    _trk = s.get("track") or ""
                    _lk = _track_layout_key(_trk)
                    _ent = next((e for e in _TRACKS
                                 if _cmap_layout_key(e[4]) == _lk), None)
                    if _ent is None:
                        _st = _track_logo_stem(_trk)
                        _ent = next((e for e in _TRACKS if e[3] == _st), None)
                    if _ent is not None:
                        self._stint_page._bgkey = _ent[1]
                        _i = _TRACKS.index(_ent)
                        _b, _bg, _n, _lg, _cm = _ent
                        self._trackpage.set_track(_i, _b, _n, _cm, _bg)
                        self._sessions_page.set_track(_i, _b, _n, _cm, _bg)
                except Exception:
                    pass
                self._stint_page.set_session(s)
            self._stint_page.mount_board(ov.board.tabs_bar, ov.stint_card, ov.board)
            leg._sync_board()
        except Exception:
            pass
        # resta/vai sulla pagina stint (se non sei entrato manualmente altrove)
        if self._stack.currentWidget() in (self._stint_page, self._sessions_page,
                                           self._menu, self._trackpage):
            self._stack.setCurrentWidget(self._stint_page)

    def _goto_stint_live(self):
        """Sessione LIVE -> pagina stint nuova col board montato (autofocus:
        stesso board, stessa logica live di prima)."""
        try:
            leg = self._app._legacy
            ov = leg._overview
            s = {}                 # titolo neutro: quello vero lo mette l hook
            leg._user_picked_session = True
            # sfondo = foto della pista della sessione live corrente
            try:
                tr = getattr(self._app, "_track", None)
                self._stint_page._bgkey = tr[1] if tr else None
            except Exception:
                pass
            self._stint_page.set_session(s)
            self._stint_page.mount_board(ov.board.tabs_bar, ov.stint_card, ov.board)
            leg._sync_board()
        except Exception:
            pass
        self._stack.setCurrentWidget(self._stint_page)

    def _open_session(self, s):
        """Click su una card sessione -> pagina stint: apre la sessione col codice
        esistente (popola il board) e monta gli STESSI widget del board qui."""
        leg = getattr(self._app, "_legacy", None)
        if leg is not None and s and s.get("file"):
            try:
                leg._user_picked_session = True            # _sync_board vuole il pick
                leg._open_session_file(s.get("file"))      # popola _overview.board
                ov = leg._overview
                # stesso sfondo foto della pagina Sessions da cui arrivi
                self._stint_page._bgkey = getattr(self._sessions_page, "_bgkey", None)
                self._stint_page.set_session(s)
                self._last_sess = s
                self._stint_page.mount_board(ov.board.tabs_bar, ov.stint_card, ov.board)
                leg._sync_board()                          # ricostruisce tab in stile card
            except Exception:
                pass
        self._stack.setCurrentWidget(self._stint_page)

    def _open_app(self, idx):
        """Apertura sessione vera diretta: tab Overview/Telemetry/Setups."""
        self._app.set_track(_TRACKS[idx])
        try:
            self._app._menu_mode(False)          # sessione: mostra le tab
        except Exception:
            pass
        self._restore_board()                    # board di nuovo nell'Overview
        self._stack.setCurrentWidget(self._app)

    def _open_community(self):
        """COMMUNITY dalla barra menu → pagina standalone (niente circuito)."""
        if getattr(self._app, "_track", None) is None:   # init minimo solo la 1ª volta
            try:
                self._app.set_track(_TRACKS[0])
            except Exception:
                pass
        self._stack.setCurrentWidget(self._app)
        try:
            self._app._select_top(4)                      # 4 = Community
            self._app._title.setText("")                  # niente circuito in testa
            self._app._menu_mode(True)                    # nasconde le tab sessione
            self._app._legacy._community.reload()
        except Exception:
            pass

    def _open_tab(self, ix):
        """Apre una pagina dalla barra del MENU. Non e' una sessione: niente
        circuito in testa (titolo vuoto, non "Bahrain") e le tab di sessione
        (Overview/Telemetry/Setups) restano nascoste. Resta solo la freccia
        indietro, che torna al menu.
        Indici top: 2=Setups, 3=Overlay, 4=Community, 5=Team."""
        if getattr(self._app, "_track", None) is None:   # init minimo la 1a volta
            try:
                self._app.set_track(_TRACKS[0])
            except Exception:
                pass
        self._stack.setCurrentWidget(self._app)
        try:
            self._app._select_top(ix)
            self._app._title.setText("")                 # niente circuito in testa
            self._app._menu_mode(True)                   # nasconde le tab sessione
        except Exception:
            pass
        self._music_sync()                    # traccia della tab aperta (es. setups)

    def _open_setups(self):
        self._open_tab(2)      # ex tab Settings

    def _open_overlay(self):
        # gli overlay ora vivono nella pagina OPTIONS
        self._open_options()

    def _open_teams(self):
        # aperta dalla pill TEAMS della pagina Sessions: il back deve
        # tornare LI', non alle card piste
        self._app_return_sessions = \
            self._stack.currentWidget() is self._sessions_page
        self._open_tab(5)

    def _sess_export(self, file):
        """Export .zip dalla card Sessions: stessa via del legacy."""
        try:
            self._app._export_session(file)
        except Exception:
            pass

    def _sess_delete(self, file):
        """Delete dalla card Sessions (con conferma). Le sessioni TEAM
        (file in TEAM_DIR) passano dal cancellatore team."""
        try:
            from core.paths import TEAM_DIR
            if str(file).startswith(str(TEAM_DIR)):
                r = QMessageBox.question(
                    self, "Delete team session",
                    "Permanently delete this team session?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if r == QMessageBox.Yes:
                    # SGANCIA il file se e' la sessione aperta: la connessione
                    # sqlite lo teneva bloccato (delete falliva fino al riavvio)
                    try:
                        self._app._legacy._close_con()
                        self._app._legacy._viewing_team = False
                    except Exception:
                        pass
                    from core import team_share as _ts
                    _ts.delete_team_session(file)
                    try:
                        self._app._legacy._reload_team_sessions()
                    except Exception:
                        pass
            else:
                self._app._delete_session(file)
        except Exception:
            pass
        try:
            self._sessions_page.reload()
        except Exception:
            pass

    def _win_pos_file(self):
        from core.paths import USER_DIR
        return USER_DIR / "window_pos.json"

    def _restore_window_pos(self):
        """Ripristina posizione e dimensione salvate; se la posizione cade
        fuori da ogni schermo (monitor scollegato), ricentra sul primario."""
        import json
        try:
            with open(self._win_pos_file(), encoding="utf-8") as f:
                g = json.load(f)
            w, h = int(g.get("w", 900)), int(g.get("h", 640))
            x, y = g.get("x"), g.get("y")
            self.resize(max(600, w), max(400, h))
            from PySide6.QtGui import QGuiApplication
            if x is not None and y is not None:
                for scr in QGuiApplication.screens():
                    if scr.availableGeometry().contains(int(x) + 60, int(y) + 60):
                        self.move(int(x), int(y))
                        return
            sg = QGuiApplication.primaryScreen().availableGeometry()
            self.move(sg.x() + (sg.width() - self.width()) // 2,
                      sg.y() + (sg.height() - self.height()) // 2)
        except Exception:
            pass

    def _save_window_pos(self):
        import json
        try:
            with open(self._win_pos_file(), "w", encoding="utf-8") as f:
                json.dump({"x": self.x(), "y": self.y(),
                           "w": self.width(), "h": self.height()}, f)
        except Exception:
            pass

    def closeEvent(self, e):
        # la pulizia vera (overlay, recorder, ingegnere) sta nel closeEvent del
        # legacy, che pero' e' nascosto e non viene mai chiuso come finestra:
        # propaga la chiusura, cosi' i processi overlay muoiono con l'app.
        self._save_window_pos()
        try:
            self._app._legacy.close()
        except Exception:
            pass
        super().closeEvent(e)

    def _back_to_menu(self):
        # se l'app e' stata aperta DALLA pagina stint (Telemetry/Setups),
        # il back torna alla pagina stint, non al menu
        if getattr(self, "_app_return_stint", False):
            self._app_return_stint = False
            try:
                self._app._return_stint = False
                self._app._apply_back_lock(getattr(self._app, "_armed",
                                                   False))
            except Exception:
                pass
            self._stack.setCurrentWidget(self._stint_page)
            return
        # Teams aperto dalla pagina Sessions: back -> Sessions (ricaricata,
        # cosi' un archivio appena importato appare subito)
        if getattr(self, "_app_return_sessions", False):
            self._app_return_sessions = False
            try:
                self._sessions_page.reload()
            except Exception:
                pass
            self._stack.setCurrentWidget(self._sessions_page)
            return
        try:
            self._central.set_photo(None)        # menu: solo colori
        except Exception:
            pass
        self._stack.setCurrentWidget(self._menu)

    def _set_intro_lbl(self, on):
        """Testo: 'Video intro YES' (rosso LMU) / 'Video intro OFF' (grigio)."""
        self._intro_lbl.setText(
            "Video intro <b style='color:%s;'>%s</b>"
            % (("#ff1d43", "YES") if on else ("#aeb6c4", "OFF")))

    def _show_update(self, tag, url):
        """Notifica release nuova nel footer (rosso LMU, click -> download)."""
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        self._upd_btn.setText(("UPDATE AVAILABLE: %s — DOWNLOAD" % tag).upper())
        if getattr(self, "_upd_wired", False):
            self._upd_btn.clicked.disconnect()
        self._upd_btn.clicked.connect(
            lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
        self._upd_wired = True
        self._upd_btn.setVisible(True)

    def _intro_click(self):
        """Click sul check tondo: inverte e salva."""
        on = not self._intro_chk._checked
        self._intro_chk.setChecked(on)
        self._set_intro_lbl(on)
        self._toggle_intro(on)

    def _set_music_lbl(self, on):
        """Testo: 'Music YES' (rosso LMU) / 'Music OFF' (grigio)."""
        self._music_lbl.setText(
            "Music <b style='color:%s;'>%s</b>"
            % (("#ff1d43", "YES") if on else ("#aeb6c4", "OFF")))

    def _music_click(self):
        """Click sul check tondo: inverte, salva e applica subito."""
        on = not self._music_chk._checked
        self._music_chk.setChecked(on)
        self._set_music_lbl(on)
        try:
            d = _load_profile(); d["music_on"] = bool(on); _save_profile(d)
        except Exception:
            pass
        try:
            from core.soundtrack import Soundtrack
            Soundtrack.instance().set_enabled(on)
        except Exception:
            pass

    def _save_stat_opt(self, key, val):
        """Salva un risultato corretto a mano (stat_*) nel profilo e aggiorna
        l'header. Per lo storico che LMU non espone (es. 2024)."""
        try:
            d = _load_profile(); d["stat_" + key] = int(val); _save_profile(d)
        except Exception:
            pass
        try:
            self._menu.banner.refresh()
        except Exception:
            pass

    def _save_team_opt(self):
        """Salva il team (dalle Options) nel profilo e aggiorna l'header."""
        try:
            t = self._team_edit.text().strip()[:30]
            d = _load_profile(); d["team"] = t; _save_profile(d)
        except Exception:
            pass
        try:
            self._menu.banner.refresh()
        except Exception:
            pass

    def _music_vol_changed(self, v):
        """Cursore volume musica app: salva su profilo e applica dal vivo."""
        try:
            d = _load_profile(); d["music_vol"] = int(v); _save_profile(d)
        except Exception:
            pass
        try:
            from core.soundtrack import Soundtrack
            Soundtrack.instance().set_volume(int(v))
        except Exception:
            pass

    def _toggle_intro(self, on):
        """Salva la preferenza del video intro (footer)."""
        try:
            d = _load_profile(); d["intro_video"] = bool(on); _save_profile(d)
        except Exception:
            pass

    def _make_intro(self):
        try:
            if not _load_profile().get("intro_video", True):
                return None                    # intro disabilitata: salta subito
        except Exception:
            pass
        video = Path(__file__).resolve().parent.parent / "assets" / "intro.mp4"
        if not video.exists():
            return None
        try:
            return _IntroPage(self._show_menu, self)
        except Exception:
            return None      # multimedia non disponibile → vai al menu

    def _show_menu(self):
        self._stack.setCurrentWidget(self._menu)
