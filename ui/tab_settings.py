"""ui/tab_settings.py — scheda estratta 1:1 da window.py."""

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


_SVM_HIDE_KEYS = {"TCSetting", "ABSSetting"}


def _svm_humanize(key):
    if key in _SVM_KEY_NAMES:
        return _SVM_KEY_NAMES[key]
    import re
    k = key[:-7] if key.endswith("Setting") else key
    # split camelCase tenendo uniti gli acronimi (ABS, TC, RW...)
    k = re.sub(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])', ' ', k)
    return k.strip()


def _svm_human_value(comment):
    c = (comment or "").lstrip("/").strip()
    # taglia annotazioni manuali tipo "  // ..."  oppure  "<-- ..."
    for sep in (" //", "<--", "<!--", "//"):
        i = c.find(sep)
        if i > 0:
            c = c[:i].strip()
    return c or "\u2014"


def _svm_full_note(comment):
    """Commento completo (per tooltip), senza lo slash iniziale."""
    return (comment or "").lstrip("/").strip()


def _svm_is_fixed(comment):
    c = (comment or "").lower()
    return any(x in c for x in ("non-adjustable", "n/a", "fixed", "non-adjust"))


_SVM_SECTION_NAMES = {
    "GENERAL": "General", "BASIC": "Basic",
    "FRONTWING": "Front Wing", "REARWING": "Rear Wing", "BODYAERO": "Body / Ducts",
    "LEFTFENDER": "Left Fender", "RIGHTFENDER": "Right Fender",
    "SUSPENSION": "Suspension", "CONTROLS": "Controls / Brakes",
    "ENGINE": "Engine", "DRIVELINE": "Driveline",
    "FRONTLEFT": "Front Left", "FRONTRIGHT": "Front Right",
    "REARLEFT": "Rear Left", "REARRIGHT": "Rear Right",
}


class _SettingsTab(QWidget):
    """Sezione Settings: carica, visualizza, modifica e salva un assetto LMU
    (.svm), organizzato in tab (Aero, Suspension, Corners, Brakes, Drivetrain,
    General). Salvataggio round-trip: tocca solo le righe modificate."""
    _GROUPS = [
        ("Aero", ["FRONTWING", "REARWING", "BODYAERO", "LEFTFENDER", "RIGHTFENDER"]),
        ("Suspension", ["SUSPENSION"]),
        ("Corners", ["FRONTLEFT", "FRONTRIGHT", "REARLEFT", "REARRIGHT"]),
        ("Brakes & Controls", ["CONTROLS"]),
        ("Drivetrain", ["DRIVELINE", "ENGINE"]),
        ("General", ["GENERAL", "BASIC"]),
    ]

    def __init__(self, win=None):
        super().__init__()
        self._win = win
        self._svm = None
        self._path = None
        root = QVBoxLayout(self); root.setContentsMargins(12, 10, 12, 12); root.setSpacing(8)
        bar = QHBoxLayout()
        self.btn_load = QPushButton("Load .svm"); self.btn_load.setObjectName("backBtn")
        self.btn_load.setCursor(Qt.PointingHandCursor)
        self.btn_load.clicked.connect(self._load)
        self.lb_file = QLabel("No setup loaded"); self.lb_file.setObjectName("ovRowSub")
        self.btn_save = QPushButton("Save"); self.btn_save.setObjectName("backBtn")
        self.btn_save.setCursor(Qt.PointingHandCursor); self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self._save)
        self.btn_saveas = QPushButton("Save As\u2026"); self.btn_saveas.setObjectName("backBtn")
        self.btn_saveas.setCursor(Qt.PointingHandCursor); self.btn_saveas.setEnabled(False)
        self.btn_saveas.clicked.connect(self._save_as)
        bar.addWidget(self.btn_load); bar.addWidget(self.lb_file, 1)
        bar.addWidget(self.btn_save); bar.addWidget(self.btn_saveas)
        root.addLayout(bar)
        # CONSIGLI GARAGE dell'ingegnere (rich. 24/07 sera): quello che
        # il muretto dice a voce ("rivedi il camber") appare QUI scritto
        # con la regolazione consigliata e il motivo — leggi, regoli, provi
        self._adv_card = QFrame(); self._adv_card.setObjectName("svmCard")
        _avl = QVBoxLayout(self._adv_card)
        _avl.setContentsMargins(12, 8, 12, 10); _avl.setSpacing(4)
        _ah = QHBoxLayout()
        _at = QLabel("CONSIGLI GARAGE — INGEGNERE")
        _at.setObjectName("svmHdr")
        self._adv_clear = QPushButton("Pulisci")
        self._adv_clear.setObjectName("backBtn")
        self._adv_clear.setCursor(Qt.PointingHandCursor)
        self._adv_clear.clicked.connect(self._adv_wipe)
        _ah.addWidget(_at); _ah.addStretch(1)
        _ah.addWidget(self._adv_clear)
        _avl.addLayout(_ah)
        _l9 = QFrame(); _l9.setObjectName("svmHdrLine"); _avl.addWidget(_l9)
        self._adv_rows = QVBoxLayout(); self._adv_rows.setSpacing(2)
        _avl.addLayout(self._adv_rows)
        self._adv_card.setVisible(False)
        root.addWidget(self._adv_card)
        self.sub = QTabWidget(); root.addWidget(self.sub, 1)
        self.setStyleSheet(
            "#svmCard{background:#16181c;border:none;border-radius:10px;}"
            "#svmHdr{color:#eeeeef;font-size:12px;font-weight:700;letter-spacing:1.2px;}"
            "#svmHdrLine{background:#2c2e33;max-height:1px;min-height:1px;}"
            "#svmRowA{background:transparent;border-radius:6px;}"
            "#svmRowB{background:#212327;border-radius:6px;}"
            "#svmName{color:#d1d2d4;font-size:12px;}"
            "#svmNameOff{color:#60646d;font-size:12px;}"
            "#svmVal{color:#94979f;font-size:12px;}"
            "#svmSpin{background:#1d1f24;color:#ffffff;border:none;"
            "border-radius:7px;font-size:14px;font-weight:700;}"
            "#svmSpin:disabled{background:#111114;color:#4b4e55;border-color:#212327;}"
            "#svmStep{background:#2a2d33;color:%s;border:none;"
            "border-radius:7px;font-size:18px;font-weight:700;}"
            "#svmStep:hover{background:#494c53;}"
            "#svmStep:pressed{background:%s;color:#09090b;border-color:%s;}"
            "#svmStep:disabled{background:#17191c;color:#4b4e55;"
            "border-color:#212327;}" % (_ACCENT, _ACCENT, _ACCENT))
        self._placeholder()

    def _placeholder(self):
        self.sub.clear()
        w = QWidget(); l = QVBoxLayout(w)
        lbl = QLabel("Load an LMU .svm setup to view and edit.")
        lbl.setStyleSheet("color:#989ba2;font-size:14px;"); lbl.setAlignment(Qt.AlignCenter)
        l.addStretch(); l.addWidget(lbl); l.addStretch()
        self.sub.addTab(w, "Setup")

    def _adv_wipe(self):
        try:
            from core.garage_advice import clear
            clear()
        except Exception:
            pass
        self._adv_refresh()

    def _adv_refresh(self):
        """Ricarica i consigli garage (a ogni apertura della pagina)."""
        while self._adv_rows.count():
            _it = self._adv_rows.takeAt(0)
            _w = _it.widget()
            if _w:
                _w.deleteLater()
        try:
            from core.garage_advice import list_all
            rows = list_all()[:8]
        except Exception:
            rows = []
        self._adv_card.setVisible(bool(rows))
        for r in rows:
            head = " · ".join(x for x in (r.get("data"), r.get("track"),
                                          r.get("car"), r.get("sezione"))
                              if x)
            t1 = QLabel("%s — %s" % (r.get("voce", ""),
                                     r.get("consiglio", "")))
            t1.setWordWrap(True)
            t1.setStyleSheet("color:#e8eaef;font-size:12px;"
                             "font-weight:600;background:transparent;")
            t2 = QLabel(head + ((" — " + r.get("motivo", ""))
                                if r.get("motivo") else ""))
            t2.setWordWrap(True)
            t2.setStyleSheet("color:#8a90a0;font-size:11px;"
                             "background:transparent;")
            self._adv_rows.addWidget(t1)
            self._adv_rows.addWidget(t2)

    def showEvent(self, e):
        super().showEvent(e)
        try:
            self._adv_refresh()
        except Exception:
            pass

    def load_path(self, path):
        try:
            txt = open(path, encoding="utf-8", errors="replace").read()
            from core.svm import SVM
            self._svm = SVM.parse(txt); self._path = path
        except Exception:
            return False
        self.lb_file.setText(os.path.basename(path))
        self.btn_save.setEnabled(True); self.btn_saveas.setEnabled(True)
        self._build(); return True

    def _load(self):
        from PySide6.QtWidgets import QFileDialog
        start = ""
        if self._path:
            start = os.path.dirname(self._path)
        else:
            try:
                from core.lmu_paths import lmu_settings_dir
                start = lmu_settings_dir() or ""
            except Exception:
                start = ""
        fn, _f = QFileDialog.getOpenFileName(self, "Open LMU setup", start,
                                             "LMU setup (*.svm)")
        if fn:
            self.load_path(fn)

    def _build(self):
        from PySide6.QtWidgets import QScrollArea, QSpinBox
        self.sub.clear()
        secmap = dict(self._svm.sections())
        for gname, secs in self._GROUPS:
            scroll = QScrollArea(); scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            host = QWidget(); host.setStyleSheet("background:transparent;")
            hl = QVBoxLayout(host)
            hl.setContentsMargins(10, 10, 10, 10); hl.setSpacing(12)
            has_any = False
            for sname in secs:
                entries = secmap.get(sname)
                if not entries:
                    continue
                # solo voci regolabili e non ridondanti
                adj = [e for e in entries
                       if not _svm_is_fixed(e["comment"])
                       and e["key"] not in _SVM_HIDE_KEYS]
                if not adj:
                    continue
                has_any = True
                card = QFrame(); card.setObjectName("svmCard")
                cv = QVBoxLayout(card)
                cv.setContentsMargins(14, 12, 14, 14); cv.setSpacing(5)
                hdr = QLabel(_SVM_SECTION_NAMES.get(sname, sname).upper())
                hdr.setObjectName("svmHdr")
                cv.addWidget(hdr)
                line = QFrame(); line.setObjectName("svmHdrLine")
                line.setFixedHeight(1)
                cv.addWidget(line)
                cv.addSpacing(4)
                r = 0
                for e in adj:
                    name = _svm_humanize(e["key"])
                    hv = _svm_human_value(e["comment"])
                    note = _svm_full_note(e["comment"])
                    row = QFrame()
                    row.setObjectName("svmRowB" if r % 2 else "svmRowA")
                    rh = QHBoxLayout(row)
                    rh.setContentsMargins(12, 7, 10, 7); rh.setSpacing(12)
                    lbl = QLabel(name)
                    lbl.setObjectName("svmName")
                    if note and note != hv:
                        lbl.setToolTip(note)
                    # stepper:  [ - ][ valore ][ + ]
                    stepw = QWidget(); stepw.setStyleSheet("background:transparent;")
                    sh = QHBoxLayout(stepw)
                    sh.setContentsMargins(0, 0, 0, 0); sh.setSpacing(4)
                    minus = QPushButton("\u2212"); minus.setObjectName("svmStep")
                    minus.setFixedSize(28, 28); minus.setCursor(Qt.PointingHandCursor)
                    sp = QSpinBox(); sp.setObjectName("svmSpin")
                    sp.setRange(0, 9999); sp.setValue(int(e["value"]))
                    sp.setFixedSize(56, 28); sp.setAlignment(Qt.AlignCenter)
                    sp.setButtonSymbols(QSpinBox.NoButtons)
                    plus = QPushButton("+"); plus.setObjectName("svmStep")
                    plus.setFixedSize(28, 28); plus.setCursor(Qt.PointingHandCursor)
                    minus.clicked.connect(sp.stepDown)
                    plus.clicked.connect(sp.stepUp)
                    sh.addWidget(minus); sh.addWidget(sp); sh.addWidget(plus)
                    vlb = QLabel(hv); vlb.setObjectName("svmVal")
                    vlb.setMinimumWidth(150)
                    vlb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    if note and note != hv:
                        vlb.setToolTip(note)
                    rh.addWidget(lbl, 1)
                    rh.addWidget(stepw)
                    rh.addWidget(vlb)
                    ix = e["idx"]
                    sp.valueChanged.connect(
                        lambda v, i=ix, w=vlb: self._on_change(i, v, w))
                    cv.addWidget(row)
                    r += 1
                hl.addWidget(card)
            hl.addStretch()
            scroll.setWidget(host)
            if has_any:
                self.sub.addTab(scroll, gname)

    def _on_change(self, idx, value, vlabel):
        if self._svm is None:
            return
        self._svm.set_value(idx, value)
        vlabel.setText("edited \u2192 reload in LMU")
        vlabel.setStyleSheet("color:#f5c542;font-size:12px;")

    def _save(self):
        if not (self._svm and self._path):
            return
        try:
            with open(self._path, "w", encoding="utf-8", newline="") as f:
                f.write(self._svm.to_text())
        except Exception:
            pass

    def _save_as(self):
        from PySide6.QtWidgets import QFileDialog
        if self._svm is None:
            return
        start = self._path
        if not start:
            try:
                from core.lmu_paths import lmu_settings_dir
                sd = lmu_settings_dir()
                start = os.path.join(sd, "setup.svm") if sd else "setup.svm"
            except Exception:
                start = "setup.svm"
        fn, _f = QFileDialog.getSaveFileName(self, "Save LMU setup",
                                             start, "LMU setup (*.svm)")
        if not fn:
            return
        try:
            with open(fn, "w", encoding="utf-8", newline="") as f:
                f.write(self._svm.to_text())
            self._path = fn; self.lb_file.setText(os.path.basename(fn))
        except Exception:
            pass


_SVM_KEY_NAMES = {
    # electronics / brakes
    "TractionControlMapSetting": "Onboard TC",
    "TCPowerCutMapSetting": "TC Power Cut",
    "TCSlipAngleMapSetting": "TC Slip Angle",
    "AntilockBrakeSystemMapSetting": "ABS",
    "RearBrakeSetting": "Brake Bias",
    "BrakePressureSetting": "Brake Pressure",
    "BrakeMigrationSetting": "Brake Migration",
    "SteerLockSetting": "Steering Lock",
    # aero / body
    "FWSetting": "Front Wing",
    "RWSetting": "Rear Wing",
    "WaterRadiatorSetting": "Water Radiator",
    "OilRadiatorSetting": "Oil Radiator",
    "BrakeDuctSetting": "Front Brake Duct",
    "BrakeDuctRearSetting": "Rear Brake Duct",
    "FenderFlareSetting": "Fender Flare",
    # suspension
    "FrontAntiSwaySetting": "Front Anti-Roll Bar",
    "RearAntiSwaySetting": "Rear Anti-Roll Bar",
    "FrontToeInSetting": "Front Toe",
    "RearToeInSetting": "Rear Toe",
    "FrontToeOffsetSetting": "Front Toe Offset",
    "RearToeOffsetSetting": "Rear Toe Offset",
    "Front3rdSpringSetting": "Front 3rd Spring",
    "Front3rdPackerSetting": "Front 3rd Packer",
    "Front3rdTenderSpringSetting": "Front 3rd Tender Spring",
    "Front3rdTenderTravelSetting": "Front 3rd Tender Travel",
    "Rear3rdTenderSpringSetting": "Rear 3rd Tender Spring",
    "Rear3rdTenderTravelSetting": "Rear 3rd Tender Travel",
    "Front3rdSlowBumpSetting": "Front 3rd Slow Bump",
    "Front3rdFastBumpSetting": "Front 3rd Fast Bump",
    "Front3rdSlowReboundSetting": "Front 3rd Slow Rebound",
    "Front3rdFastReboundSetting": "Front 3rd Fast Rebound",
    "Rear3rdSpringSetting": "Rear 3rd Spring",
    "Rear3rdPackerSetting": "Rear 3rd Packer",
    "Rear3rdSlowBumpSetting": "Rear 3rd Slow Bump",
    "Rear3rdFastBumpSetting": "Rear 3rd Fast Bump",
    "Rear3rdSlowReboundSetting": "Rear 3rd Slow Rebound",
    "Rear3rdFastReboundSetting": "Rear 3rd Fast Rebound",
    # corners
    "CamberSetting": "Camber",
    "PressureSetting": "Tyre Pressure",
    "PackerSetting": "Packer",
    "SpringSetting": "Spring Rate",
    "SpringRubberSetting": "Spring Rubber",
    "TenderSpringSetting": "Tender Spring",
    "TenderTravelSetting": "Tender Travel",
    "RideHeightSetting": "Ride Height",
    "SlowBumpSetting": "Slow Bump",
    "FastBumpSetting": "Fast Bump",
    "SlowReboundSetting": "Slow Rebound",
    "FastReboundSetting": "Fast Rebound",
    "BrakeDiscSetting": "Brake Disc",
    "BrakePadSetting": "Brake Pad",
    "CompoundSetting": "Tyre Compound",
    # drivetrain
    "DiffPreloadSetting": "Diff Preload",
    "DiffPowerSetting": "Diff Power",
    "DiffCoastSetting": "Diff Coast",
    "DiffPumpSetting": "Diff Pump",
    "FrontDiffPreloadSetting": "Front Diff Preload",
    "FrontDiffPowerSetting": "Front Diff Power",
    "FrontDiffCoastSetting": "Front Diff Coast",
    "FrontDiffPumpSetting": "Front Diff Pump",
    "RatioSetSetting": "Gear Ratio Set",
    "RearSplitSetting": "Rear Split",
    "GearAutoUpShiftSetting": "Auto Upshift",
    "GearAutoDownShiftSetting": "Auto Downshift",
    # engine
    "RevLimitSetting": "Rev Limit",
    "EngineMixtureSetting": "Engine Mixture",
    "EngineBoostSetting": "Engine Boost",
    "RegenerationMapSetting": "Regeneration Map",
    "ElectricMotorMapSetting": "Electric Motor Map",
    "EngineBrakingMapSetting": "Engine Braking Map",
    # general
    "FuelSetting": "Fuel",
    "FuelCapacitySetting": "Fuel Capacity",
    "VirtualEnergySetting": "Virtual Energy",
    "NumPitstopsSetting": "Pit Stops",
    "Pitstop1Setting": "Pitstop 1",
    "Pitstop2Setting": "Pitstop 2",
    "Pitstop3Setting": "Pitstop 3",
}
