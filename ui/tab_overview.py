"""ui/tab_overview.py — scheda Overview estratta da window.py."""
from core.profile import get_team
from telemetry.common import _fmt_session_len, _ov_clock, _ov_session_label
from ui.widgets import _LapBoard, _comp_four_single

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


_OV_WEATHER_DIR = Path(__file__).resolve().parent.parent / "assets" / "weather"


def _fmt_when(started_at, name=""):
    """ISO datetime -> 'DD Mon YYYY · HH:MM'. Fallback dal nome file (MM-DD_HH-MM)."""
    import time as _t
    if started_at:
        try:
            tm = _t.strptime(started_at[:19], "%Y-%m-%dT%H:%M:%S")
            return _t.strftime("%d %b %Y \u00b7 %H:%M", tm)
        except Exception:
            pass
    try:
        import re as _re
        m = _re.search(r"(\d{2})-(\d{2})_(\d{2})-(\d{2})", name or "")
        if m:
            mo, da, hh, mm = m.groups()
            return f"{da}/{mo} \u00b7 {hh}:{mm}"
    except Exception:
        pass
    return ""



# QSS condiviso del pannello Overview (board stint/giri). Usato anche
# dalla pagina stint dedicata (telemetry/window.py) per avere lo stesso look.
_OV_QSS = (
    "#ovCard{background:#16181c;border:none;border-radius:10px;}"
            "#ovNoData{color:#5c5f68;font-size:14px;background:transparent;}"
            "#ovTrackBox{background:transparent;border:none;}"
            "#ovSessName{color:#f2f4f7;font-size:17px;font-weight:700;background:transparent;}"
            "#ovSessClock{color:#45b4ef;font-size:17px;font-weight:700;background:transparent;}"
            "#ovCondLine{color:#a7aaaf;font-size:13px;background:transparent;}"
            "#ovInfoLine{color:#cfd2d8;font-size:12px;background:transparent;}"
            "#ovListCard{background:#191b1f;border:none;border-radius:0;}"
            "QScrollBar:horizontal{height:0px;background:transparent;}"
            "#ovHead{color:#6e727b;font-size:11px;font-weight:700;letter-spacing:2px;}"
            "#ovDriver{background:transparent;border:none;color:#f2f4f7;font-size:16px;font-weight:600;}"
            "#ovTeam{background:transparent;border:none;color:#a7aaaf;font-size:12px;}"
            "#ovDriver:focus,#ovTeam:focus{border-bottom:1px solid #3a3d43;}"
            "#ovCar{color:#6e727b;font-size:12px;}"
            "#ovTrack{color:#bdbfc3;font-size:11px;font-weight:600;letter-spacing:1px;}"
            "#ovRowA,#ovRowB{background:#1d1f24;border-radius:8px;}"
            "#ovRowA:hover,#ovRowB:hover{background:#23262d;}"
            "#ovKey{color:#989ba2;font-size:13px;background:transparent;}"
            "#ovVal{color:#f2f4f7;font-size:14px;font-weight:600;background:transparent;}"
            "#ovRowTitle{color:#f2f4f7;font-size:13px;font-weight:600;background:transparent;}"
            "#ovRowSub{color:#989ba2;font-size:11px;background:transparent;}"
            "#ovRowDim{color:#61646d;font-size:11px;background:transparent;}"
            "#ovSelRow{background:#262a31;border-left:2px solid #45b4ef;border-radius:8px;}"
            "#ovRowIcon{background:transparent;border:none;color:#9fb0c8;font-size:14px;}"
            "#ovRowIcon:hover{color:#ff5b6e;}"
            "#ovIcon{background:transparent;border:none;color:#989ba2;font-size:15px;}"
            "#ovIcon:hover{color:#f2f4f7;}"
            "#ovBadgeDry{color:#1a1400;background:#f5c542;border-radius:6px;"
            "padding:1px 7px;font-size:10px;font-weight:700;}"
            "#ovBadgeWet{color:#04222e;background:#4ec3ff;border-radius:6px;"
            "padding:1px 7px;font-size:10px;font-weight:700;}"
            # striscia condizioni compatta
            "#ovStatKey{color:#6e727b;font-size:10px;font-weight:700;letter-spacing:1px;background:transparent;}"
            "#ovStatVal{color:#f2f4f7;font-size:14px;font-weight:600;background:transparent;}"
            # board tempi
            "#ovColCap{color:#5c5f68;font-size:10px;font-weight:700;letter-spacing:1px;background:transparent;}"
            "#ovColCapSel{color:#55ff7f;font-size:9px;font-weight:700;letter-spacing:1px;background:transparent;}"
            "#ovColCapCmp{color:#8b7bff;font-size:9px;font-weight:700;letter-spacing:1px;background:transparent;}"
            "#ovTheo{color:#45b4ef;font-size:11px;font-weight:700;letter-spacing:.5px;background:transparent;}"
            "#ovTabOn{background:#262a31;border:none;border-left:2px solid #45b4ef;border-radius:8px;}"
            "#ovTabOff{background:#1d1f24;border:none;border-radius:8px;}"
            "#ovTabOff:hover{border-color:#3a3d43;}"
            "#ovTabTxt{color:#f2f4f7;font-size:11px;font-weight:700;letter-spacing:.5px;background:transparent;}"
            "#ovStintSum{color:#838790;font-size:12px;background:transparent;}"
            "#ovTabOff #ovTabTxt{color:#989ba2;}"
            # riga REF (oro)
            "#ovRefRow{background:rgba(245,197,66,0.13);border:none;border-radius:10px;}"
            "#ovRefEmpty{background:#111214;border:1px dashed #2a2c30;border-radius:10px;}"
            "#ovRefTag{color:#f5c542;font-size:12px;font-weight:800;letter-spacing:1px;background:transparent;}"
            "#ovRefDrv{color:#f5f5f5;font-size:13px;font-weight:600;background:transparent;}"
            "#ovRefTime{color:#f5c542;font-size:14px;font-weight:700;background:transparent;}"
            "#ovRefSec{color:#9c8a4e;font-size:12px;background:transparent;}"
            "#ovRefNone{color:#6e727b;font-size:12px;background:transparent;}"
            "#ovRefSub{color:#7c7148;font-size:10px;background:transparent;padding-left:12px;}"
            "#ovRefInfo{color:#cfd2d8;font-size:11px;background:transparent;padding-left:12px;}"
            "#ovWrRow{background:rgba(57,182,232,0.13);border:none;border-radius:10px;}"
            "#ovWrTag{color:#39b6e8;font-size:12px;font-weight:800;letter-spacing:1px;background:transparent;}"
            "#ovWrDrv{color:#f5f5f5;font-size:13px;font-weight:600;background:transparent;}"
            "#ovWrTime{color:#39b6e8;font-size:14px;font-weight:700;background:transparent;}"
            "#ovWrSec{color:#5f93ad;font-size:12px;background:transparent;}"
            "#ovWrSub{color:#5f93ad;font-size:10px;background:transparent;padding-left:12px;}"
            # righe giro — ogni giro è una card
            "#ovLapRow{background:#181a1e;border:none;border-radius:10px;}"
            "#ovLapRow:hover{background:#1a1b1f;border-color:#2a2c30;}"
            "#ovLapSel{background:#23262c;border:none;border-radius:10px;}"
            "#ovLapDis{background:#1b1d22;border:none;border-radius:12px;}"
            "#ovLapBestCard{background:#241420;border:none;border-radius:10px;}"
            "#ovLapNo{color:#ffffff;font-size:13px;font-weight:700;background:transparent;}"
            "#ovLapInv{color:#aeb2ba;font-size:13px;font-weight:700;background:transparent;}"
            "#ovLapTime{color:#f5f5f5;font-size:14px;font-weight:600;background:transparent;}"
            "#ovLapBest{color:#ff5bb0;font-size:14px;font-weight:700;background:transparent;}"
            "#ovSec{color:#ffffff;font-size:12px;background:transparent;}"
            "#ovSecBest{color:#ff3bd4;font-size:12px;background:transparent;}"
            "#ovSecInv{color:#ffffff;font-size:12px;background:transparent;}"
            "#ovTagOut{color:#d2d6dd;font-size:9px;font-weight:700;letter-spacing:1px;"
            "background:#202225;border-radius:4px;padding:1px 5px;margin-left:6px;}"
            "#ovTagTL{color:#ffcc33;font-size:9px;font-weight:700;letter-spacing:1px;"
            "background:#2a2410;border-radius:4px;padding:1px 5px;margin-left:6px;}"
            "#ovTagInv{color:#e06a6a;font-size:9px;font-weight:700;letter-spacing:1px;"
            "background:#2a1618;border-radius:4px;padding:1px 5px;margin-left:6px;}"
            "#ovTagPit{color:#f0a23a;font-size:9px;font-weight:700;letter-spacing:1px;"
            "background:#241a10;border-radius:4px;padding:1px 5px;margin-left:6px;}"
            # checkbox
            "#ovCkOff{background:transparent;border:1.5px solid #3a3d43;border-radius:4px;}"
            "#ovCkOff:hover{border-color:#60636c;}"
            "#ovCkSelOn{background:transparent;border:2px solid #55ff7f;border-radius:4px;}"
            "#ovCkCmpOn{background:transparent;border:2px solid #8b7bff;border-radius:4px;}"
            "#ovCkRefOn{background:transparent;border:2px solid #f5c542;border-radius:4px;}")

class _SessionRow(QFrame):
    """Riga della lista telemetrie: barra colore-classe, logo auto, classe·pilota,
    circuito, data/ora, cestino. Clic sulla riga = seleziona."""
    def __init__(self, idx, s, selected, on_select, on_delete, empty_svg, on_open=None,
                 on_export=None):
        super().__init__()
        self._idx = idx; self._sel_cb = on_select; self._del_cb = on_delete
        self._open_cb = on_open; self._file = s.get("file")
        self._export_cb = on_export
        self._selected = selected
        self._dimmed = False
        self.setObjectName("ovSelRow" if selected else ("ovRowB" if idx % 2 else "ovRowA"))
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(82)
        h = QHBoxLayout(self); h.setContentsMargins(10, 5, 8, 5); h.setSpacing(9)
        logo = _SvgBox(); logo.setFixedSize(54, 38)
        try:
            from core.brands import brand_from_vehicle
            from core.utils import find_logo_path
            brand = (brand_from_vehicle(s.get("team") or "")
                     or brand_from_vehicle(s.get("vehicle") or ""))
            p = find_logo_path(brand) if brand else None
            logo.load(str(p) if p else empty_svg)
        except Exception:
            logo.load(empty_svg)
        h.addWidget(logo, 0, Qt.AlignVCenter)
        tb = QVBoxLayout(); tb.setSpacing(0); tb.setContentsMargins(0, 0, 0, 0)
        cls = (s.get("car_class") or "").strip()
        drv = (s.get("driver") or "").strip()
        if cls:
            try:
                from core.classes import class_tag
                tag = class_tag(cls) or cls
            except Exception:
                tag = cls
        else:
            tag = ""
        top = QWidget(); tl = QHBoxLayout(top); tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(7)
        top.setFixedHeight(22); top.setStyleSheet("background:transparent;")
        if cls:
            pill = QLabel(tag); pill.setObjectName("ovClsPill")
            pill.setAlignment(Qt.AlignCenter); pill.setFixedHeight(16)
            pill.setStyleSheet(
                "#ovClsPill{background:%s;color:#fff;font-weight:700;font-size:11px;"
                "border-radius:3px;padding:0 5px;}" % _class_color(cls))
            tl.addWidget(pill, 0, Qt.AlignVCenter)
        dlb = QLabel((drv or (s.get("name") or "\u2014")).upper()); dlb.setObjectName("ovRowTitle")
        tl.addWidget(dlb, 0, Qt.AlignVCenter); tl.addStretch()
        l2 = QLabel((s.get("track") or "\u2014")); l2.setObjectName("ovRowSub")
        l2.setStyleSheet("color:#ff8a18;" if _track_is_alt(s.get("track")) else "color:#1c9fe0;")
        l2.setWordWrap(False); l2.setFixedHeight(16)
        is_wet = (s.get("wetness") or 0.0) > 0.10
        mcol = "#4ec3ff" if is_wet else "#f5c542"
        mtxt = "WET" if is_wet else "DRY"
        styp = _ov_session_label(s.get("session_type"))
        slen = _fmt_session_len(s.get("session_len"))
        meta_bits = styp + ((" \u00b7 " + slen) if slen else "")
        l3 = QLabel("%s &nbsp;<span style='color:%s;font-weight:700'>%s</span>"
                    % (meta_bits, mcol, mtxt))
        l3.setObjectName("ovRowSub"); l3.setTextFormat(Qt.RichText); l3.setFixedHeight(16)
        l4 = QLabel(_fmt_when(s.get("started_at"), s.get("name")))
        l4.setObjectName("ovRowDim"); l4.setFixedHeight(16)
        # riga 5 icone meteo previste (sopra il nome), se la sessione le ha
        fc5 = (s.get("forecast5") or "").strip()
        if fc5:
            fc_row = QWidget(); fc_row.setStyleSheet("background:transparent;")
            fcl = QHBoxLayout(fc_row); fcl.setContentsMargins(0, 0, 0, 0); fcl.setSpacing(6)
            fc_row.setFixedHeight(30)
            _n_ic = 0
            for nm in [x.strip() for x in fc5.split(",") if x.strip()][:5]:
                wp = _OV_WEATHER_DIR / ("%s.svg" % nm)
                if not wp.exists():
                    continue
                ic = _SvgBox(); ic.setFixedSize(28, 28)
                ic.setStyleSheet("background:transparent;")
                ic.load(str(wp))
                fcl.addWidget(ic, 0, Qt.AlignVCenter)
                _n_ic += 1
            if _n_ic:                         # spazio solo se ci sono icone vere
                fcl.addStretch()
                tb.addWidget(fc_row)
                self.setFixedHeight(116)
            else:
                fc_row.deleteLater()
        tb.addWidget(top); tb.addSpacing(3)
        tb.addWidget(l2); tb.addWidget(l3); tb.addWidget(l4)
        h.addLayout(tb, 1)
        # tracciato della pista in bianco, a destra della scheda
        # mappa pista a destra: SVG in stile (gradiente + linea centrale), per layout
        sp = _track_styled_svg(s.get("track"))
        if sp is not None:
            mapbox = _SvgBox(); mapbox.setFixedSize(118, 66)
            mapbox.setStyleSheet("background:transparent;")
            mapbox.load(str(sp))
            h.addWidget(mapbox, 0, Qt.AlignVCenter)
        rb = QVBoxLayout(); rb.setSpacing(4); rb.setContentsMargins(0, 0, 0, 0)
        rb.addStretch()
        # icona EXPORT (o etichetta "team" se e' una sessione importata)
        top_icons = QHBoxLayout(); top_icons.setSpacing(6)
        top_icons.setContentsMargins(0, 0, 0, 0); top_icons.addStretch()
        if s.get("team_session"):
            tlbl = QLabel("team"); tlbl.setObjectName("ovRowDim")
            tlbl.setStyleSheet("color:#e8eaee;font-size:10px;font-weight:700;"
                               "letter-spacing:.5px;background:transparent;")
            tlbl.setFixedHeight(22)
            top_icons.addWidget(tlbl, 0, Qt.AlignVCenter)
        else:
            btn_exp = _ExportButton(16); btn_exp.setObjectName("ovRowIcon")
            btn_exp.setFlat(True); btn_exp.setCursor(Qt.PointingHandCursor)
            btn_exp.setToolTip("Export session (.zip)"); btn_exp.setFixedSize(22, 22)
            btn_exp.setStyleSheet("QPushButton#ovRowIcon{border:none;background:transparent;}")
            btn_exp.clicked.connect(self._on_export)
            top_icons.addWidget(btn_exp)
        rb.addLayout(top_icons)
        icons = QHBoxLayout(); icons.setSpacing(6); icons.setContentsMargins(0, 0, 0, 0)
        btn_del = _XButton(18); btn_del.setObjectName("ovRowIcon")
        btn_del.setFlat(True); btn_del.setCursor(Qt.PointingHandCursor)
        btn_del.setToolTip("Delete"); btn_del.setFixedSize(30, 30)
        btn_del.clicked.connect(self._on_del)
        icons.addStretch(); icons.addWidget(btn_del)
        rb.addLayout(icons)
        h.addLayout(rb, 0)

    def set_selected(self, on):
        self._selected = on
        self.setObjectName("ovSelRow" if on else ("ovRowB" if self._idx % 2 else "ovRowA"))
        self.style().unpolish(self); self.style().polish(self)

    def set_dim(self, on):
        """DISABILITATA durante una sessione live: opacita' 40% e non cliccabile
        (ne' selezione ne' bottoni). Mentre registri in pista non puoi aprire una
        sessione precedente."""
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

    def _on_del(self):
        if self._dimmed:
            return
        if self._del_cb:
            self._del_cb(self._idx)

    def _on_export(self):
        if self._dimmed:
            return
        if self._export_cb:
            self._export_cb(self._file)

    def _on_open(self):
        if self._dimmed:
            return
        if self._open_cb:
            self._open_cb(self._file)

    def mousePressEvent(self, e):
        if self._dimmed:                     # sessione live: card non cliccabile
            return
        if self._sel_cb:
            self._sel_cb(self._idx)
        super().mousePressEvent(e)


class _OverviewTab(QWidget):
    """Tab d'apertura: identita pilota/team (modificabile), logo team, logo
    circuito, condizioni della sessione (striscia compatta) e la board tempi
    (tab stint + riga REF + giri con checkbox)."""
    _EMPTY_SVG = b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'/>"

    def __init__(self):
        super().__init__()
        self._meta = {}
        self._live = False
        self._reader = None
        self._load_overrides()
        self._build()
        self._refresh_display()
        self._timer = QTimer(self); self._timer.setInterval(1000)
        self._timer.timeout.connect(self._live_tick); self._timer.start()

    def set_empty(self, flag):
        """Mostra solo 'No data yet' e nasconde card condizioni / REF / board."""
        for w in (self._cond_card, self.ref_card, self.board, self.board.tabs_bar, self.stint_card):
            w.setVisible(not flag)
        # (la card REF ora VIVE anche nella pagina stint: niente hide forzato)
        self._empty_state.setVisible(False)

    def set_live(self, on):
        """Attiva la lettura LIVE delle condizioni mentre si registra (START).
        Durante una sessione live le card delle sessioni PRECEDENTI vanno
        disabilitate (opacita' 40%, non cliccabili)."""
        self._live = bool(on)
        if self._live and self._reader is None:
            try:
                self._reader = TelemetryReader()
            except Exception:
                self._reader = None
        self._apply_live_dim()

    def _apply_live_dim(self):
        """Riflette lo stato live sulle card sessioni (dim quando live)."""
        for row in list(getattr(self, "_rows_w", [])) \
                + list(getattr(self, "_team_rows_w", [])):
            try:
                row.set_dim(self._live)
            except Exception:
                pass

    def _live_tick(self):
        if not self._live or self._reader is None:
            return
        try:
            d = self._reader.read()
        except Exception:
            d = {}
        if not d:
            return
        self.set_meta({
            "driver": d.get("driver"), "team": d.get("team"),
            "vehicle": d.get("vehicle"), "car_class": d.get("car_class"),
            "track": d.get("track"), "session_type": d.get("session_type"),
            "air_temp": d.get("air_temp"), "track_temp": d.get("track_temp"),
            "wetness": d.get("wetness"),
            "compound_f": d.get("compound_front"), "compound_r": d.get("compound_rear"),
            "compounds4": ",".join(d.get("tyre_compound4") or []),
            "fuel_start": d.get("fuel"),
            "_laps": d.get("laps_completed"), "_best": None,
            "_race_remaining": d.get("race_remaining"),
            "_race_total": d.get("race_total"),
        })

    # ── persistenza override pilota/team ──
    def _ovr_file(self):
        from core.paths import USER_DIR
        return USER_DIR / "overview.json"

    def _load_overrides(self):
        import json
        try:
            self._ovr = json.loads(self._ovr_file().read_text(encoding="utf-8"))
        except Exception:
            self._ovr = {}

    def _save_overrides(self):
        import json
        try:
            self._ovr_file().write_text(json.dumps(self._ovr, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
        except Exception:
            pass

    def _build(self):
        outer = QHBoxLayout(self); outer.setContentsMargins(16, 14, 16, 14); outer.setSpacing(14)
        self._build_session_list(outer)
        right = QWidget()
        root = QVBoxLayout(right); root.setContentsMargins(4, 0, 4, 4); root.setSpacing(10)
        self._board_root = root
        # ── card CONDIZIONI: logo circuito a sinistra + condizioni sessione ──
        # (driver/auto/classe stanno già nella lista sessioni a sinistra)
        card = QFrame(); card.setObjectName("ovCard"); self._cond_card = card
        cl = QHBoxLayout(card); cl.setContentsMargins(16, 10, 18, 10); cl.setSpacing(18)
        tboxf = QFrame(); tboxf.setObjectName("ovTrackBox")
        tl = QVBoxLayout(tboxf); tl.setContentsMargins(0, 0, 0, 0); tl.setSpacing(4)
        self.track_logo = _SvgBox(); self.track_logo.setFixedSize(82, 48)
        self.lb_track = QLabel("\u2014"); self.lb_track.setObjectName("ovTrack")
        self.lb_track.setVisible(False)
        tl.addWidget(self.track_logo, 0, Qt.AlignCenter)
        cl.addWidget(tboxf, 0)
        # condizioni sessione
        cond = QVBoxLayout(); cond.setSpacing(3)
        cond.addStretch()
        self.lb_sess = QLabel("\u2014"); self.lb_sess.setObjectName("ovSessName")
        self.lb_clock = QLabel(""); self.lb_clock.setObjectName("ovSessClock")
        self.lb_cond = QLabel("\u2014"); self.lb_cond.setObjectName("ovCondLine")
        self.lb_cond.setTextFormat(Qt.RichText)
        cond.addWidget(self.lb_sess)
        cond.addWidget(self.lb_cond)
        cond.addStretch()
        cl.addLayout(cond, 1)
        cl.addWidget(self.lb_clock, 0, Qt.AlignRight | Qt.AlignVCenter)
        # widget identità tenuti staccati (info nella lista sessioni); servono a
        # _refresh_display / _on_edit ma non sono mostrati in questa card.
        self.logo = _SvgBox(); self.logo.setFixedSize(1, 1)
        self.ed_driver = QLineEdit(); self.ed_driver.setObjectName("ovDriver")
        self.ed_team = QLineEdit(); self.ed_team.setObjectName("ovTeam")
        self.lb_car = QLabel(""); self.lb_car.setObjectName("ovCar")
        self.ed_driver.editingFinished.connect(self._on_edit)
        self.ed_team.editingFinished.connect(self._on_edit)
        root.addWidget(card)
        # ── riga REF (record): spostata nella colonna SINISTRA sotto le sessioni ──
        self.ref_card = QWidget()
        self.ref_card.setFixedWidth(600)        # stessa misura delle card sessioni
        self._refcard_l = QVBoxLayout(self.ref_card)
        self._refcard_l.setContentsMargins(0, 0, 0, 0); self._refcard_l.setSpacing(6)
        self._left_col.addWidget(self.ref_card, 0, Qt.AlignTop)
        # ── sessioni TEAM importate: sotto la card REF, max 3 scrollabili ──
        from PySide6.QtWidgets import QScrollArea
        self._team_scroll = QScrollArea(); self._team_scroll.setWidgetResizable(True)
        self._team_scroll.setFrameShape(QFrame.NoFrame)
        self._team_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._team_scroll.setFixedWidth(600)
        self._team_scroll.setFixedHeight(82 * 3 + 6 * 2)
        self._team_host = QWidget(); self._team_host.setStyleSheet("background:transparent;")
        self._team_v = QVBoxLayout(self._team_host)
        self._team_v.setContentsMargins(0, 0, 0, 0); self._team_v.setSpacing(6)
        self._team_v.addStretch()
        self._team_scroll.setWidget(self._team_host)
        self._team_scroll.setVisible(False)        # nascosto se nessuna team session
        self._left_col.addWidget(self._team_scroll, 0, Qt.AlignTop)
        self._left_col.addStretch()
        self._vals = {}
        for name in ("Session", "Weather", "Air temp", "Track temp", "Track wetness",
                     "Fuel (start)", "Compound", "Laps", "Best lap", "Theoretical"):
            self._vals[name] = QLabel()
        # ── board tempi/stint (giri) ──
        self.board = _LapBoard()
        root.addWidget(self.board.tabs_bar)   # tab stint sopra la card
        self.stint_card = QFrame(); self.stint_card.setObjectName("ovCard")
        self.stint_card.setStyleSheet("#ovCard{background:#16181c;border:none;border-radius:5px;}")
        self.stint_card.setMinimumHeight(20)
        self.stint_card_l = QVBoxLayout(self.stint_card)
        self.stint_card_l.setContentsMargins(0, 0, 0, 0); self.stint_card_l.setSpacing(0)
        root.addWidget(self.stint_card)       # card #16181c sotto stint (da riempire)
        self.stint_card_l.addWidget(self.board.lb_summary)  # riga dati stint
        root.addWidget(self.board, 1)
        # stato "nessun dato": nasconde card/REF/board al primo avvio
        self._empty_state = QLabel("No data yet"); self._empty_state.setObjectName("ovNoData")
        self._empty_state.setAlignment(Qt.AlignCenter); self._empty_state.setVisible(False)
        root.addWidget(self._empty_state, 1)
        outer.addWidget(right, 1)
        self.setStyleSheet(_OV_QSS)
        if self._ovr.get("driver"):
            self.ed_driver.setText(self._ovr["driver"])
        if self._ovr.get("team"):
            self.ed_team.setText(self._ovr["team"])

    def _on_edit(self):
        self._ovr["driver"] = self.ed_driver.text().strip()
        self._ovr["team"] = self.ed_team.text().strip()
        self._save_overrides()

    def _ref_src_header(self, wet, source, wet_pct=None):
        """Riga compatta in cima alla card REF: etichetta DRY/WET (colore
        condizione, con % di bagnato SOTTO LE RUOTE del giro se disponibile)
        + tag sorgente (LOCAL/ONLINE). Colore card gestito a parte."""
        w = QWidget(); w.setStyleSheet("background:transparent;")
        hl = QHBoxLayout(w); hl.setContentsMargins(0, 0, 0, 2); hl.setSpacing(6)
        cond_col = "#4aa3df" if wet else _GOLD            # blu WET / oro DRY
        _txt = "WET" if wet else "DRY"
        if wet_pct is not None:
            _p = int(round(float(wet_pct) * 100))
            _txt = ("WET %d%%" % _p) if _p > 0 else "DRY"
        cond = QLabel(_txt)
        cond.setStyleSheet("color:%s;font-size:11px;font-weight:800;letter-spacing:1px;"
                           "background:transparent;" % cond_col)
        hl.addWidget(cond, 0, Qt.AlignVCenter)
        tag = QLabel(source)
        tag.setStyleSheet("color:#e8eaee;font-size:9px;font-weight:800;letter-spacing:1px;"
                          "background:rgba(255,255,255,0.10);border-radius:4px;"
                          "padding:1px 6px;")
        hl.addWidget(tag, 0, Qt.AlignVCenter)
        hl.addStretch()
        return w

    def _sector_row(self, secs, wet):
        """Sotto-riga coi 3 tempi settore (S1/S2/S3) della card REF (oro) /
        ONLINE REF (blu), allineata a destra sotto il tempo. None se assenti."""
        if not secs or not any(secs[:3]):
            return None
        row = QWidget(); row.setStyleSheet("background:transparent;")
        hl = QHBoxLayout(row); hl.setContentsMargins(12, 0, 16, 2)
        hl.setSpacing(16)
        hl.addStretch()
        name = "ovWrSec" if wet else "ovRefSec"
        for i in range(3):
            v = secs[i] if i < len(secs) else None
            lb = QLabel("S%d  %s" % (i + 1, _fmt(v) if v else "—"))
            lb.setObjectName(name)
            hl.addWidget(lb, 0, Qt.AlignVCenter)
        return row

    def set_ref(self, ref, ref_is_cmp, theo, on_pick, pace=None, wet=False):
        """Card REF (record personale) + card PACE (riferimento dal CSV).
        Real lap (record reale) rimosso."""
        _clear_layout(self._refcard_l)
        if not ref:
            pass                              # REF vuota: niente card, pulito
        elif getattr(self, "_compact_ref", False):
            # versione COMPATTA (pagina stint): UNA riga alta come i lap,
            # stesse colonne (cond 64 / time 102 / 3x72 / check 20)
            card = _ClickFrame(lambda: on_pick(("ref",)))
            _cond = "#4aa3df" if wet else _GOLD
            card.setObjectName("ovWrRow" if wet else "ovRefRow")
            card.setFixedHeight(38)
            h = QHBoxLayout(card); h.setContentsMargins(12, 2, 16, 2)
            h.setSpacing(0)
            tag = QLabel("REF")
            tag.setObjectName("ovWrTag" if wet else "ovRefTag")
            h.addWidget(tag, 0, Qt.AlignVCenter); h.addSpacing(10)
            drv = QLabel(((ref.get("driver") or "").strip() or "record").upper())
            drv.setObjectName("ovRefDrv")
            h.addWidget(drv, 0, Qt.AlignVCenter)
            h.addSpacing(12)
            cnd = QLabel("WET" if wet else "DRY")
            cnd.setStyleSheet("color:%s;font-size:11px;font-weight:700;"
                              "letter-spacing:1px;background:transparent;" % _cond)
            h.addWidget(cnd, 0, Qt.AlignVCenter)
            h.addStretch()
            t = QLabel(_fmt(ref.get("time")) if ref.get("time") else "—")
            t.setObjectName("ovWrTime" if wet else "ovRefTime")
            t.setFixedWidth(102)
            t.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            h.addWidget(t, 0, Qt.AlignVCenter)
            _secs = ref.get("secs") or []
            for i in range(3):
                v = _secs[i] if i < len(_secs) else None
                sl = QLabel(_fmt(v) if v else "—")
                sl.setObjectName("ovWrSec" if wet else "ovRefSec")
                sl.setFixedWidth(72)
                sl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                h.addWidget(sl, 0, Qt.AlignVCenter)
            ckc = _mk_check(lambda: on_pick(("ref",)), _cond,
                            bool(ref_is_cmp), _cond)
            ckc.setToolTip("Compare vs REF")
            h.addSpacing(12); h.addWidget(ckc, 0, Qt.AlignVCenter)
            self._refcard_l.addWidget(card)
        else:
            card = _ClickFrame(lambda: on_pick(("ref",)))
            _cond = "#4aa3df" if wet else _GOLD            # blu WET / oro DRY
            card.setObjectName("ovWrRow" if wet else "ovRefRow")
            cv = QVBoxLayout(card); cv.setContentsMargins(0, 4, 0, 8); cv.setSpacing(2)
            rw = QWidget(); rw.setStyleSheet("background:transparent;")
            h = QHBoxLayout(rw); h.setContentsMargins(12, 6, 16, 4); h.setSpacing(0)
            ckc = _mk_check(lambda: on_pick(("ref",)), _cond, bool(ref_is_cmp), _cond)
            ckc.setToolTip("Compare vs REF")
            logo = _SvgBox(); logo.setFixedSize(54, 38)
            _car_logo_into(logo, ref.get("team"), ref.get("vehicle"))
            h.addWidget(logo, 0, Qt.AlignVCenter); h.addSpacing(10)
            col = QWidget(); col.setStyleSheet("background:transparent;")
            col.setFixedWidth(200)
            coll = QVBoxLayout(col); coll.setContentsMargins(0, 0, 0, 0); coll.setSpacing(0)
            coll.addWidget(self._ref_src_header(wet, "LOCAL", ref.get("wet_pct")))
            r1 = QLabel(((ref.get("driver") or "").strip() or "record").upper())
            r1.setObjectName("ovRefDrv")
            r2 = QLabel(get_team() or "\u2014")
            r2.setStyleSheet("color:%s;font-size:12px;background:transparent;"
                             % ("#5f93ad" if wet else "#b9ad84"))
            r3 = QLabel((ref.get("vehicle") or "").strip() or "\u2014")
            r3.setStyleSheet("color:%s;font-size:12px;font-weight:600;background:transparent;"
                             % ("#7bbde8" if wet else "#e8c87a"))
            coll.addWidget(r1); coll.addWidget(r2); coll.addWidget(r3)
            h.addWidget(col, 0, Qt.AlignVCenter); h.addSpacing(40)
            from core.tyre_cell import TyreCell
            _four, _single = _comp_four_single(ref.get("compounds4"))
            _w4 = ref.get("wear4") or []
            _new4 = ([(w is not None and w >= 99) for w in _w4]
                     if len(_w4) == 4 else None)
            _snew = all(_new4) if _new4 else True
            col2 = QWidget(); c2 = QVBoxLayout(col2)
            c2.setContentsMargins(0, 0, 0, 0); c2.setSpacing(0)
            tc = TyreCell(size=24); tc.set_tyre(_single, _four, new4=_new4, single_new=_snew)
            tc.setFixedHeight(24)
            c2.addWidget(tc, 0, Qt.AlignHCenter)
            _ts = ref.get("tyre_state")
            pclose = QLabel(("%.0f%%" % _ts) if _ts is not None else "\u2014")
            pclose.setStyleSheet("color:#e8eaee;font-size:12px;font-weight:700;background:transparent;")
            pclose.setAlignment(Qt.AlignHCenter)
            c2.addWidget(pclose, 0, Qt.AlignHCenter)
            h.addWidget(col2, 0, Qt.AlignVCenter); h.addSpacing(26)
            # colonna carico benzina: simbolo + kg (litri x 0.75)
            _fl = ref.get("fuel_l")
            _kg = (_fl * 0.75) if _fl is not None else None
            col3 = QWidget(); c3 = QVBoxLayout(col3)
            c3.setContentsMargins(0, 0, 0, 0); c3.setSpacing(0)
            fsym = _SvgBox(); fsym.setFixedSize(24, 24)
            fsym.load(_FUEL_WEIGHT_SVG.encode())
            c3.addWidget(fsym, 0, Qt.AlignHCenter)
            fkg = QLabel(("+%.0f kg" % _kg) if _kg is not None else "\u2014")
            fkg.setStyleSheet("color:#e8eaee;font-size:12px;font-weight:700;background:transparent;")
            fkg.setAlignment(Qt.AlignHCenter)
            c3.addWidget(fkg, 0, Qt.AlignHCenter)
            h.addWidget(col3, 0, Qt.AlignVCenter)
            h.addStretch()
            t = QLabel(_fmt(ref.get("time")) if ref.get("time") else "\u2014")
            t.setObjectName("ovWrTime" if wet else "ovRefTime"); t.setFixedWidth(84)
            t.setAlignment(Qt.AlignRight | Qt.AlignVCenter); h.addWidget(t)
            h.addSpacing(12); h.addWidget(ckc, 0, Qt.AlignVCenter)
            cv.addWidget(rw)
            _sr = self._sector_row(ref.get("secs"), wet)
            if _sr is not None:
                cv.addWidget(_sr)
            self._refcard_l.addWidget(card)
        if pace is not None and not getattr(self, "_no_online_ref", False):
            _pc = self._build_pace_card(pace, on_pick, wet=wet)
            if _pc is not None:
                self._refcard_l.addWidget(_pc)

    def _build_pace_card(self, pace, on_pick=None, wet=False):
        """Card 'ONLINE REF': riferimento esterno dal foglio laptimes (Ohne Speed).
        Check azzurro (default ON): se attivo, sul giro migliore compaiono
        dicitura e gap. Riga: check + logo auto + ONLINE REF + 'Peter - OhneSpeed'
        + tempo. Sotto: pace/hotlap + data del documento aggiornato."""
        # nessun dato online -> niente card (resta nascosta finché non c'è un tempo)
        if not (pace and pace.get("online")):
            return None
        _cond = "#4aa3df" if wet else _GOLD            # blu WET / oro DRY
        card = QFrame(); card.setObjectName("ovWrRow" if wet else "ovRefRow")
        cv = QVBoxLayout(card); cv.setContentsMargins(0, 4, 0, 8); cv.setSpacing(2)
        rw = QWidget(); rw.setStyleSheet("background:transparent;")
        h = QHBoxLayout(rw); h.setContentsMargins(12, 6, 16, 4); h.setSpacing(0)
        sel = bool(pace.get("sel", True))
        ck = _mk_check(lambda: on_pick(("pace",)) if on_pick else None,
                       _cond, True, _cond, ghost=True)
        ck.setToolTip("Show pace label & gap on best lap")
        car_nm = pace.get("car")
        box = _SvgBox(); box.setFixedSize(54, 38)
        _car_logo_into(box, pace.get("team"), car_nm)
        h.addWidget(box, 0, Qt.AlignVCenter); h.addSpacing(10)
        col = QWidget(); col.setStyleSheet("background:transparent;")
        col.setFixedWidth(200)
        coll = QVBoxLayout(col); coll.setContentsMargins(0, 0, 0, 0); coll.setSpacing(0)
        coll.addWidget(self._ref_src_header(wet, "ONLINE"))
        _drv = pace.get("player") or "\u2014"
        _tm = get_team() or pace.get("team") or "\u2014"
        _car = car_nm or "\u2014"
        r1 = QLabel((_drv or "").upper()); r1.setObjectName("ovRefDrv")
        r2 = QLabel(_tm)
        r2.setStyleSheet("color:%s;font-size:12px;background:transparent;"
                         % ("#5f93ad" if wet else "#b9ad84"))
        r3 = QLabel(_car)
        r3.setStyleSheet("color:%s;font-size:12px;font-weight:600;background:transparent;"
                         % ("#7bbde8" if wet else "#e8c87a"))
        coll.addWidget(r1); coll.addWidget(r2); coll.addWidget(r3)
        h.addWidget(col, 0, Qt.AlignVCenter); h.addSpacing(40)
        # colonna gomma (placeholder finché non arriva il Worker)
        from core.tyre_cell import TyreCell
        col2 = QWidget(); c2 = QVBoxLayout(col2)
        c2.setContentsMargins(0, 0, 0, 0); c2.setSpacing(0)
        tc = TyreCell(size=24)
        _c4 = pace.get("compounds4") or ""
        _four = [x.strip() for x in _c4.split(",") if x.strip()]
        _single = pace.get("compound") or (_four[0] if _four else "M")
        _tsv = pace.get("tyre_state_pct")
        _newv = (_tsv is None) or (_tsv >= 99.0)
        if len(_four) == 4:
            tc.set_tyre(_single, _four, new4=[_newv, _newv, _newv, _newv],
                        single_new=_newv)
        else:
            tc.set_tyre(_single, None, single_new=_newv)
        tc.setFixedHeight(24)
        c2.addWidget(tc, 0, Qt.AlignHCenter)
        _ts = pace.get("tyre_state_pct")
        pcl = QLabel(("%.0f%%" % _ts) if _ts is not None else "\u2014")
        pcl.setStyleSheet("color:#e8eaee;font-size:12px;font-weight:700;background:transparent;")
        pcl.setAlignment(Qt.AlignHCenter)
        c2.addWidget(pcl, 0, Qt.AlignHCenter)
        h.addWidget(col2, 0, Qt.AlignVCenter); h.addSpacing(26)
        # colonna carico benzina (placeholder finché non arriva il Worker)
        col3 = QWidget(); c3 = QVBoxLayout(col3)
        c3.setContentsMargins(0, 0, 0, 0); c3.setSpacing(0)
        fsym = _SvgBox(); fsym.setFixedSize(24, 24)
        fsym.load(_FUEL_WEIGHT_SVG.encode())
        c3.addWidget(fsym, 0, Qt.AlignHCenter)
        _fl = pace.get("fuel_l")
        _kg = (_fl * 0.75) if _fl is not None else None
        fkg = QLabel(("+%.0f kg" % _kg) if _kg is not None else "\u2014")
        fkg.setStyleSheet("color:#e8eaee;font-size:12px;font-weight:700;background:transparent;")
        fkg.setAlignment(Qt.AlignHCenter)
        c3.addWidget(fkg, 0, Qt.AlignHCenter)
        h.addWidget(col3, 0, Qt.AlignVCenter)
        h.addStretch()
        t = QLabel(_fmt(pace.get("ref_time")) if (pace and pace.get("ref_time")) else "\u2014")
        t.setObjectName("ovWrTime" if wet else "ovRefTime"); t.setFixedWidth(84)
        t.setAlignment(Qt.AlignRight | Qt.AlignVCenter); h.addWidget(t)
        h.addSpacing(12); h.addWidget(ck, 0, Qt.AlignVCenter)
        cv.addWidget(rw)
        _sr = self._sector_row(pace.get("secs"), wet)
        if _sr is not None:
            cv.addWidget(_sr)
        return card

    def _build_session_list(self, outer):
        self._sel_cb = None; self._del_cb = None; self._open_cb = None
        panel = QFrame(); panel.setObjectName("ovListCard"); panel.setFixedWidth(600)
        pl = QVBoxLayout(panel); pl.setContentsMargins(0, 0, 0, 0); pl.setSpacing(0)
        # ── tab LAYOUT (stile tab stint): mostrate solo se la pista ha piu' layout
        self._layout_bar = QWidget()
        _lbl = QHBoxLayout(self._layout_bar); _lbl.setContentsMargins(12, 6, 14, 6)
        _lbl.setSpacing(6)
        self._layout_tabs_l = QHBoxLayout(); self._layout_tabs_l.setSpacing(6)
        self._layout_tabs_l.setContentsMargins(0, 0, 0, 0)
        _lbl.addLayout(self._layout_tabs_l); _lbl.addStretch()
        self._layout_bar.setVisible(False)
        pl.addWidget(self._layout_bar)
        from PySide6.QtWidgets import QScrollArea
        self._list_scroll = QScrollArea(); self._list_scroll.setWidgetResizable(True)
        self._list_scroll.setFrameShape(QFrame.NoFrame)
        self._list_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list_host = QWidget()
        self._list_v = QVBoxLayout(self._list_host)
        self._list_v.setContentsMargins(0, 0, 0, 0); self._list_v.setSpacing(6)
        self._list_v.addStretch()
        self._list_scroll.setWidget(self._list_host)
        self._list_scroll.setFixedHeight(82 * 3 + 6 * 2)   # sempre 3 card, poi scroll
        pl.addWidget(self._list_scroll, 1)
        # colonna sinistra verticale: lista sessioni (3 card) + card REF sotto
        leftw = QWidget()
        self._leftw = leftw
        self._left_col = QVBoxLayout(leftw)
        self._left_col.setContentsMargins(0, 0, 0, 0); self._left_col.setSpacing(10)
        self._left_col.addWidget(panel, 0, Qt.AlignTop)
        outer.addWidget(leftw, 0, Qt.AlignTop)
        self._rows_w = []

    def set_left_visible(self, on):
        """Mostra/nasconde la colonna sinistra (lista sessioni + REF + team).
        Nascosta quando si arriva dalla pagina Sessions -> Overview = pagina stint."""
        w = getattr(self, "_leftw", None)
        if w is not None:
            w.setVisible(bool(on))

    def remount_board(self):
        """Rimette tabs stint + card riepilogo + board giri nella colonna destra
        dell'Overview (nell'ordine originale). Usato quando la pagina stint li ha
        'presi in prestito' e si riapre l'app diretta/live."""
        r = getattr(self, "_board_root", None)
        if r is None:
            return
        try:
            r.insertWidget(1, self.board.tabs_bar)
            r.insertWidget(2, self.stint_card)
            r.insertWidget(3, self.board, 1)
        except Exception:
            pass

    def set_layout_tabs(self, tabs, current, on_pick):
        """tabs = lista (key, label). Mostra le tab layout stile stint; nascoste
        se 0/1 layout. current = key selezionata."""
        _clear_layout(self._layout_tabs_l)
        if not tabs or len(tabs) < 2:
            self._layout_bar.setVisible(False)
            return
        for key, label in tabs:
            b = _ClickFrame(lambda kk=key: on_pick(kk) if on_pick else None)
            b.setObjectName("ovTabOn" if key == current else "ovTabOff")
            bl = QHBoxLayout(b); bl.setContentsMargins(10, 4, 10, 4); bl.setSpacing(0)
            short = label if len(label) <= 14 else (label[:13].rstrip() + "\u2026")
            lb = QLabel(short); lb.setObjectName("ovTabTxt")
            if short != label:
                b.setToolTip(label)
            bl.addWidget(lb, 0, Qt.AlignVCenter)
            self._layout_tabs_l.addWidget(b)
        self._layout_bar.setVisible(True)

    def set_team_sessions(self, sessions, on_select, on_delete):
        """Card delle sessioni team importate: INSIEME alle sessioni nella lista
        (dopo le tue). Etichetta 'team', X per eliminare."""
        # rimuovi eventuali righe team gia' presenti nella lista
        for w in list(getattr(self, "_team_rows_w", [])):
            try:
                w.setParent(None); w.deleteLater()
            except Exception:
                pass
        self._team_rows_w = []
        try:
            self._team_scroll.setVisible(False)     # vecchia area sotto la REF: spenta
        except Exception:
            pass
        for i, s in enumerate(sessions):
            s = dict(s); s["team_session"] = True
            row = _SessionRow(i, s, False, on_select, on_delete,
                              _OverviewTab._EMPTY_SVG, None, None)
            row.setStyleSheet("#ovRowA,#ovRowB{background:#1d1f24;border-radius:8px;}"
                              "#ovRowA:hover,#ovRowB:hover{background:#23262d;}"
                              "#ovSelRow{background:#262a31;border-left:2px solid #45b4ef;"
                              "border-radius:8px;}")
            self._list_v.insertWidget(self._list_v.count() - 1, row)  # dopo le tue, prima dello stretch
            self._team_rows_w.append(row)

    def set_sessions(self, sessions, current_idx, on_select, on_delete, on_open,
                     on_export=None):
        self._sel_cb = on_select; self._del_cb = on_delete; self._open_cb = on_open
        self._export_cb = on_export
        while self._list_v.count() > 1:                  # rimuovi righe (tiene lo stretch finale)
            it = self._list_v.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        self._rows_w = []
        self._team_rows_w = []          # le righe team verranno riaggiunte da set_team_sessions
        for i, s in enumerate(sessions):
            row = _SessionRow(i, s, i == current_idx, on_select, on_delete,
                              _OverviewTab._EMPTY_SVG, on_open, on_export)
            self._list_v.insertWidget(self._list_v.count() - 1, row)
            self._rows_w.append(row)
        # se la lista si ricostruisce MENTRE sei live, le card nuove nascono
        # gia' disabilitate (opacita' 40%, non cliccabili)
        if getattr(self, "_live", False):
            self._apply_live_dim()
        # porta in vista la sessione selezionata (lista alta 3 card)
        if 0 <= current_idx < len(self._rows_w):
            from PySide6.QtCore import QTimer
            _row = self._rows_w[current_idx]
            QTimer.singleShot(0, lambda: self._list_scroll.ensureWidgetVisible(_row))

    def highlight_session(self, idx):
        for i, row in enumerate(getattr(self, "_rows_w", [])):
            row.set_selected(i == idx)
        for row in getattr(self, "_team_rows_w", []):
            row.set_selected(False)

    def highlight_team_session(self, idx):
        for row in getattr(self, "_rows_w", []):
            row.set_selected(False)
        for i, row in enumerate(getattr(self, "_team_rows_w", [])):
            row.set_selected(i == idx)

    def set_meta(self, meta):
        self._meta = meta or {}
        self._refresh_display()

    def _refresh_display(self):
        m = self._meta
        team = m.get("team") or ""
        veh = m.get("vehicle") or ""
        cls = m.get("car_class") or ""
        trk = m.get("track") or ""
        # logo team/auto: prova prima il team (brands.json e indicizzato sul team)
        try:
            from core.brands import brand_from_vehicle
            from core.utils import find_logo_path
            brand = brand_from_vehicle(team) or brand_from_vehicle(veh)
            p = find_logo_path(brand) if brand else None
            self.logo.load(str(p) if p else self._EMPTY_SVG)
        except Exception:
            self.logo.load(self._EMPTY_SVG)
        # tracklogo (mantiene proporzioni)
        f = _ov_tracklogo_file(trk)
        self.track_logo.load(str(f) if f else self._EMPTY_SVG)
        self.lb_track.setText(trk or "\u2014")
        self.ed_driver.setPlaceholderText((m.get("driver") or "") or "Driver")
        self.ed_team.setPlaceholderText((team or "") or "Team")
        self.lb_car.setText(veh + (("   \u00b7   " + cls) if cls else ""))
        # condizioni
        wet = float(m.get("wetness") or 0.0)
        is_wet = wet > 0.10
        wlab = "WET" if is_wet else "DRY"
        at = m.get("air_temp"); tt = m.get("track_temp")
        cf = m.get("compound_f") or ""; cr = m.get("compound_r") or ""
        comp = cf if cf == cr else ((cf + " / " + cr) if (cf or cr) else "")
        if not comp:
            comp = (m.get("compounds4") or "").strip()
        fs = m.get("fuel_start")
        self._vals["Session"].setText(_ov_session_label(m.get("session_type")))
        self._vals["Weather"].setText(wlab)
        self._vals["Weather"].setStyleSheet(
            "background:transparent;font-size:14px;font-weight:700;color:%s;"
            % ("#4ec3ff" if is_wet else "#f5c542"))
        self._vals["Air temp"].setText(f"{at:.0f} \u00b0C" if at is not None else "\u2014")
        self._vals["Track temp"].setText(f"{tt:.0f} \u00b0C" if tt is not None else "\u2014")
        self._vals["Track wetness"].setText(f"{wet * 100:.0f}%")
        self._vals["Fuel (start)"].setText(f"{fs:.1f} L" if fs else "\u2014")
        self._vals["Compound"].setText(comp or "\u2014")
        laps = m.get("_laps")
        self._vals["Laps"].setText(str(laps) if laps is not None else "\u2014")
        best = m.get("_best")
        self._vals["Best lap"].setText(_fmt(best) if best else "\u2014")
        theo = m.get("_theo")
        self._vals["Theoretical"].setText(_fmt(theo) if theo else "\u2014")
        # ── card condizioni (nuova) ──
        styp = _ov_session_label(m.get("session_type"))
        slen = _fmt_session_len(m.get("session_len"))
        self.lb_sess.setText(styp + ((" \u00b7 " + slen) if slen else ""))
        air = f"{at:.0f}\u00b0C" if at is not None else "\u2014"
        trk_t = f"{tt:.0f}\u00b0C" if tt is not None else "\u2014"
        wcol = "#4ec3ff" if is_wet else "#f5c542"
        self.lb_cond.setText(
            "Air %s &nbsp;\u00b7&nbsp; Track %s &nbsp;\u00b7&nbsp; "
            "<span style='color:%s;font-weight:700'>%s</span>" % (air, trk_t, wcol, wlab))
        rr = m.get("_race_remaining")
        if self._live and rr:
            self.lb_clock.setText("Remaining  " + _ov_clock(rr))
            self.lb_clock.setVisible(True)
        else:
            self.lb_clock.setVisible(False)

    def stop(self):
        try:
            self._timer.stop()
        except Exception:
            pass
        try:
            if self._reader:
                self._reader.stop()
        except Exception:
            pass
