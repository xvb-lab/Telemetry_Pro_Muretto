"""ui/widgets.py — mattoncini UI riusabili: bottoni, icone, switch, badge.
Estratto 1:1 da window.py (ricostruzione, sezione widget)."""
from telemetry.common import _CMP_COL, _FUX, _GOLD, _SEL_COL, _clear_layout, _fmt, _ov_clock

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
from telemetry.common import _SvgBox
try:
    from core.paths import PROFILE_FILE as _PROFILE_FILE
except Exception:
    _PROFILE_FILE = Path(__file__).resolve().parent.parent / "settings" / "profile.json"


def _class_color(cls):
    """Colore classe come nello standings (HY/P2/P3/GT3/GTE)."""
    try:
        from core.classes import class_tag
        tag = class_tag(cls)
    except Exception:
        tag = (cls or "").upper()[:3]
    return {"HY": "#bd1016", "P2": "#1e3163", "P3": "#411c52",
            "GT3": "#01824d", "GTE": "#ff9100"}.get(tag, "#6e727b")


_TRASH_SVG = (b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'>"
              b"<path fill='%s' d='M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12z"
              b"M19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z'/></svg>")


_trash_icon_cache = {}


_FOLDER_SVG = (b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'>"
               b"<path fill='%s' d='M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16"
               b"c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z'/></svg>")


_folder_icon_cache = {}


def _folder_icon(color="#838790", size=16):
    key = (color, size)
    if key in _folder_icon_cache:
        return _folder_icon_cache[key]
    from PySide6.QtGui import QIcon, QPixmap
    ic = QIcon()
    try:
        if QSvgRenderer is not None:
            r = QSvgRenderer(QByteArray(_FOLDER_SVG % color.encode()))
            pm = QPixmap(size, size); pm.fill(Qt.transparent)
            p = QPainter(pm); r.render(p); p.end()
            ic = QIcon(pm)
    except Exception:
        ic = QIcon()
    _folder_icon_cache[key] = ic
    return ic


def _trash_icon(color="#838790", size=16):
    key = (color, size)
    if key in _trash_icon_cache:
        return _trash_icon_cache[key]
    from PySide6.QtGui import QIcon, QPixmap
    ic = QIcon()
    try:
        if QSvgRenderer is not None:
            r = QSvgRenderer(QByteArray(_TRASH_SVG % color.encode()))
            pm = QPixmap(size, size); pm.fill(Qt.transparent)
            p = QPainter(pm); r.render(p); p.end()
            ic = QIcon(pm)
    except Exception:
        ic = QIcon()
    _trash_icon_cache[key] = ic
    return ic


_X_SVG = (b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='%s'>"
          b"<path d='M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 "
          b"1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 "
          b"0 0 0-1.06-1.06L10 8.94 6.28 5.22Z'/></svg>")


_x_icon_cache = {}


_EXPORT_SVG = (b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
               b"stroke='%s' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'>"
               b"<path d='M12 3 L12 14'/>"
               b"<path d='M8 7 L12 3 L16 7'/>"
               b"<path d='M5 13 L5 20 L19 20 L19 13'/></svg>")


_export_icon_cache = {}


def _svg_icon(svg_tpl, cache, color, size):
    key = (color, size)
    if key in cache:
        return cache[key]
    from PySide6.QtGui import QIcon, QPixmap
    ic = QIcon()
    try:
        if QSvgRenderer is not None:
            r = QSvgRenderer(QByteArray(svg_tpl % color.encode()))
            pm = QPixmap(size, size); pm.fill(Qt.transparent)
            p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing, True)
            r.render(p); p.end()
            ic = QIcon(pm)
    except Exception:
        ic = QIcon()
    cache[key] = ic
    return ic


def _export_icon(color="#9aa0aa", size=16):
    return _svg_icon(_EXPORT_SVG, _export_icon_cache, color, size)


def _x_icon(color="#838790", size=16):
    key = (color, size)
    if key in _x_icon_cache:
        return _x_icon_cache[key]
    from PySide6.QtGui import QIcon, QPixmap
    ic = QIcon()
    try:
        if QSvgRenderer is not None:
            r = QSvgRenderer(QByteArray(_X_SVG % color.encode()))
            pm = QPixmap(size, size); pm.fill(Qt.transparent)
            p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing, True)
            r.render(p); p.end()
            ic = QIcon(pm)
    except Exception:
        ic = QIcon()
    _x_icon_cache[key] = ic
    return ic


class _XButton(QPushButton):
    """X bold che diventa rossa al passaggio del mouse."""
    def __init__(self, size=16):
        super().__init__()
        self._sz = size
        self._n = _x_icon("#ffffff", size)
        self._h = _x_icon("#ff5b5b", size)
        self.setIcon(self._n); self.setIconSize(QSize(size, size))

    def enterEvent(self, e):
        self.setIcon(self._h); super().enterEvent(e)

    def leaveEvent(self, e):
        self.setIcon(self._n); super().leaveEvent(e)


class _ExportButton(QPushButton):
    """Icona export (freccia su da vassoio); schiarisce al passaggio del mouse."""
    def __init__(self, size=16):
        super().__init__()
        self._n = _export_icon("#ffffff", size)
        self._h = _export_icon("#c8ccd4", size)
        self.setIcon(self._n); self.setIconSize(QSize(size, size))

    def enterEvent(self, e):
        self.setIcon(self._h); super().enterEvent(e)

    def leaveEvent(self, e):
        self.setIcon(self._n); super().leaveEvent(e)


class _Switch(QFrame):
    """Mini interruttore (toggle) al posto della checkbox: pista + pomello.
    checked = on (colore acceso), altrimenti grigio. ghost = sempre on ma
    invisibile, tiene comunque lo spazio della colonna (usato sulla riga REF)."""
    def __init__(self, checked, on_color, on_click=None, ghost=False):
        super().__init__()
        self._checked = bool(checked); self._on = on_color
        self._cb = on_click; self._ghost = ghost
        self.setFixedSize(26, 15)
        if not ghost:
            self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("background:transparent;")

    def setChecked(self, v):
        self._checked = bool(v); self.update()

    def mousePressEvent(self, e):
        if self._cb and not self._ghost:
            self._cb()

    def paintEvent(self, e):
        if self._ghost:
            return                          # invisibile ma occupa spazio
        from PySide6.QtGui import QPainter, QColor
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        track = QColor(self._on if self._checked else "#3a3d43")
        p.setPen(Qt.NoPen); p.setBrush(track)
        p.drawRoundedRect(0, 0, w, h, h / 2, h / 2)
        p.setBrush(QColor("#ffffff"))
        r = h - 4
        x = (w - r - 2) if self._checked else 2
        p.drawEllipse(int(x), 2, int(r), int(r))


def _mk_check(on_click, border, checked, check_col, ghost=False):
    """Check TONDO (cerchio) di selezione del giro da confrontare.
    on = anello + pallino in tinta, off = anello grigio. ghost = riga REF."""
    on_color = check_col if (check_col and check_col != "transparent") else border
    return _CircleCheck(checked, on_color, on_click, ghost=ghost)


class _CircleCheck(QFrame):
    """Checkbox rotonda: anello, con pallino pieno quando selezionata."""
    def __init__(self, checked, on_color, on_click=None, ghost=False):
        super().__init__()
        self._checked = bool(checked); self._on = on_color
        self._cb = on_click; self._ghost = ghost
        self.setFixedSize(20, 20)
        if not ghost:
            self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("background:transparent;")

    def setChecked(self, v):
        self._checked = bool(v); self.update()

    def mousePressEvent(self, e):
        if self._cb and not self._ghost:
            self._cb()

    def paintEvent(self, e):
        if self._ghost:
            return                          # invisibile ma occupa spazio
        from PySide6.QtGui import QPainter, QColor, QPen
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        d = min(w, h) - 4
        x = (w - d) / 2.0; y = (h - d) / 2.0
        col = QColor(self._on if self._checked else "#9aa0aa")
        pen = QPen(col); pen.setWidthF(2.0)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(x, y, d, d))   # anello
        if self._checked:                   # pallino pieno centrale
            r = d * 0.52
            p.setPen(Qt.NoPen); p.setBrush(QColor(self._on))
            p.drawEllipse(QRectF((w - r) / 2.0, (h - r) / 2.0, r, r))


class _ClickFrame(QFrame):
    """QFrame cliccabile (per la riga REF)."""
    def __init__(self, on_click=None):
        super().__init__()
        self._on_click = on_click
        if on_click:
            self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, e):
        if self._on_click:
            self._on_click()


class _CardTab(_ClickFrame):
    """Tab stint della pagina nuova, dipinta a mano (antialiasata, niente QSS):
    selezionata = card blu piena SENZA bordo; deselezionata = trasparente;
    hover = bianca con testo rosso LMU."""
    _TXT_W = ("color:#ffffff;font-size:11px;font-weight:700;"
              "letter-spacing:.5px;background:transparent;border:none;")
    _TXT_R = ("color:#ff1d43;font-size:11px;font-weight:700;"
              "letter-spacing:.5px;background:transparent;border:none;")

    def __init__(self, on_click=None, selected=False):
        super().__init__(on_click)
        self._sel = bool(selected)
        self._hov = False
        self._lbl = None

    def enterEvent(self, e):
        self._hov = True
        if self._lbl is not None:
            self._lbl.setStyleSheet(self._TXT_R)
        self.update()

    def leaveEvent(self, e):
        self._hov = False
        if self._lbl is not None:
            self._lbl.setStyleSheet(self._TXT_W)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.7, 0.7, -0.7, -0.7)
        if self._hov:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 255))
            p.drawRoundedRect(r, 9, 9)
        elif self._sel:
            p.setPen(QPen(QColor(0, 185, 255, 220), 1.4))   # bordo azzurrino
            p.setBrush(QColor(10, 0, 50, 242))
            p.drawRoundedRect(r, 9, 9)
        else:
            # deselezionata: trasparente con bordo bianco
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 165), 1.4))
            p.drawRoundedRect(r, 9, 9)


class _ClassChip(QLabel):
    """Tag classe colorato e cliccabile (come nella scheda sessioni)."""

    def __init__(self, cls, on_click):
        super().__init__(cls or "\u2014")
        self._cls = cls; self._on_click = on_click
        col = _class_color(cls)
        self.setCursor(Qt.PointingHandCursor)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            "QLabel{color:#fff;font-size:10px;font-weight:800;background:%s;"
            "border-radius:4px;padding:3px 9px;}" % col)

    def mousePressEvent(self, e):
        if self._on_click:
            self._on_click(self._cls)


class _ClassBadge(QFrame):
    """Badge classe come SVG (assets/class/) cliccabile, per la lista piste.
    Hover: pill translucido dietro al badge (evidenzia senza spostare il layout)."""
    def __init__(self, cls, svg_path, on_click, size=(42, 27)):
        super().__init__()
        self._cls = cls; self._on = on_click
        self.setObjectName("clsBadge")
        self.setCursor(Qt.PointingHandCursor)
        # bordo presente anche da spento (trasparente): così l'hover NON sposta le righe.
        # radius proporzionato all'altezza del badge (~0.18) come il simbolo.
        self._qss_off = ("#clsBadge{background:transparent;"
                         "border:1px solid transparent;border-radius:7px;}")
        self._qss_on = ("#clsBadge{background:rgba(255,255,255,0.16);"
                        "border:1px solid rgba(255,255,255,0.30);border-radius:7px;}")
        self.setStyleSheet(self._qss_off)
        lay = QHBoxLayout(self); lay.setContentsMargins(2, 3, 2, 3); lay.setSpacing(0)
        box = _SvgBox(); box.setFixedSize(int(size[0]), int(size[1])); box.load(svg_path)
        lay.addWidget(box)

    def enterEvent(self, e):
        self.setStyleSheet(self._qss_on)

    def leaveEvent(self, e):
        self.setStyleSheet(self._qss_off)

    def mousePressEvent(self, e):
        if self._on:
            self._on(self._cls)


def _abbr_num(n):
    """123 -> '123', 1000 -> '1k', 1200 -> '1.2k', 1_000_000 -> '1M'."""
    try:
        n = int(n)
    except Exception:
        return "0"
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        s = ("%.1f" % (n / 1000.0)).rstrip("0").rstrip(".")
        return s + "k"
    s = ("%.1f" % (n / 1_000_000.0)).rstrip("0").rstrip(".")
    return s + "M"


def _chip(text, bg, fg="#ffffff"):
    lab = QLabel(text)
    lab.setStyleSheet(
        f"QLabel {{ background:{bg}; color:{fg}; font-family:'Heebo';"
        f" font-weight:700; font-size:10px; border-radius:7px; padding:2px 8px; }}"
    )
    return lab


# ── helper logo auto/format (condivisi) ──

_EMPTY_LOGO_SVG = b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'/>"


def _brand_from_car_name(car):
    """Manifattura dal nome auto (es. 'Porsche 911 GT3 R' -> 'Porsche'),
    matchando i file in brandlogo/. Per i record online di altri team, dove
    il team non è nel brands.json locale. None se nessuno."""
    if not car:
        return None
    try:
        from core.utils import LOGO_DIR
        if not LOGO_DIR.exists():
            return None
        cl = car.lower()
        best = None
        for f in LOGO_DIR.glob("*.svg"):
            nm = f.stem
            if nm and nm.lower() in cl and (best is None or len(nm) > len(best)):
                best = nm
        return best
    except Exception:
        return None


def _car_logo_into(box, team, vehicle):
    try:
        from core.brands import brand_from_vehicle
        from core.utils import find_logo_path
        brand = brand_from_vehicle(team or "") or brand_from_vehicle(vehicle or "")
        if not brand:                       # online: team sconosciuto -> dal nome auto
            brand = _brand_from_car_name(vehicle)
        p = find_logo_path(brand) if brand else None
        box.load(str(p) if p else _EMPTY_LOGO_SVG)
    except Exception:
        box.load(_EMPTY_LOGO_SVG)


def _fmt_ms(ms):
    """ms -> 'm:ss.mmm' o 'ss.mmm'. '—' se assente."""
    if not ms:
        return "\u2014"
    s = ms / 1000.0
    return "%d:%06.3f" % (int(s) // 60, s % 60) if s >= 60 else "%.3f" % s


# ── board giri (condiviso) ──

_PACE_LABEL = {
    "Alien":       "Pro",
    "Competitive": "Competitive",
    "Good":        "Good",
    "Midpack":     "Midpack",
    "Tail-ender":  "Tail-ender",
    "Offline":     "Non competitive",
    "Hotlap":      "Hotlap",
}


def _pace_label(internal):
    return _PACE_LABEL.get(internal, internal)


class _LapRow(QFrame):
    """Riga giro: UN check (verde=Selected, viola=Compare) + numero + tempo +
    settori. Out-lap e giri invalidi non sono selezionabili (nessun check)."""
    def __init__(self, lap, time_s, secs, is_best, invalid, is_out, is_sel, is_cmp,
                 on_pick, best_secs=None, pace_label=None, pace_gap=None, pace_color=None,
                 is_in=False, e_delta=None, w_delta=None, cond_locked=False,
                 big=False, pick_off=False, wet=None, cls_color=None, cls_svg=None, pos=None,
                 trk_temp=None, e_used=None, e_unit="%", soc_used=None):
        super().__init__()
        self._lap = lap
        selectable = (not invalid and not is_out and not is_in
                      and not cond_locked and not pick_off)
        self._on_pick = on_pick if selectable else None
        if selectable:
            self.setCursor(Qt.PointingHandCursor)
        if is_out or invalid or is_in:
            self.setObjectName("ovLapDis")
        elif is_best:
            self.setObjectName("ovLapBestCard")
        else:
            self.setObjectName("ovLapSel" if (is_sel and selectable) else "ovLapRow")
        h = QHBoxLayout(self); h.setContentsMargins(12, 2, 16, 2); h.setSpacing(0)
        ck = None
        if selectable:
            border = _BEST_ROSE if is_best else "#3a3d43"
            if is_sel or is_cmp:
                if is_best:
                    check_col = _FUX           # fast = sempre fuxia
                elif is_sel:
                    check_col = _SEL_COL        # primo selezionato = verde
                else:
                    check_col = _CMP_COL        # secondo (confronto) = blu
            else:
                check_col = "transparent"
            ck = _mk_check(lambda: on_pick(("lap", lap)), border,
                           is_sel or is_cmp, check_col)
        # OGNI giro ha le stesse info/stili: l'invalido perde SOLO il check
        _pos_txt = str(int(pos)) if pos else "\u2013"
        no = QLabel(_pos_txt); no.setObjectName("ovLapNo")
        no.setFixedSize(28, 28)                  # chip quadrato, non schiacciato
        no.setAlignment(Qt.AlignCenter)
        if cls_color:
            no.setStyleSheet("background:transparent;color:#ffffff;font-size:13px;"
                             "font-weight:800;border:2px solid %s;"
                             "border-radius:6px;" % cls_color)
        lapw = QLabel("LAP %d" % lap)
        lapw.setFixedWidth(70)               # colonna fissa: i tag non ballano
        lapw.setStyleSheet("color:#ffffff;font-size:13px;font-weight:800;"
                           "letter-spacing:.5px;background:transparent;")
        h.addWidget(lapw, 0, Qt.AlignVCenter)
        h.addSpacing(8)
        # colonna TAG fissa (OUT LAP / TRACK LIMITS / PIT LINE) + POS subito dopo
        _tagw = QWidget(); _tagw.setFixedWidth(112)
        _tl2 = QHBoxLayout(_tagw)
        _tl2.setContentsMargins(0, 0, 0, 0); _tl2.setSpacing(0)
        if is_out:
            tag = QLabel("OUT LAP"); tag.setObjectName("ovTagOut")
            _tl2.addWidget(tag, 0, Qt.AlignVCenter)
        elif invalid:
            tag = QLabel("TRACK LIMITS"); tag.setObjectName("ovTagTL")
            _tl2.addWidget(tag, 0, Qt.AlignVCenter)
        elif is_in:
            tag = QLabel("PIT LINE"); tag.setObjectName("ovTagOut")
            _tl2.addWidget(tag, 0, Qt.AlignVCenter)
        _tl2.addStretch(1)
        h.addWidget(_tagw, 0, Qt.AlignVCenter)
        h.addWidget(no, 0, Qt.AlignVCenter)      # POS dopo la colonna tag
        h.addSpacing(10)
        # COND + TRACK temp + ENERGIA usata + SOC usata: colonne fisse
        _pct = int(round(float(wet) * 100)) if wet is not None else None
        if _pct is None:
            _ctx, _ccol = "", "#f5c542"
        elif _pct > 25:
            _ctx, _ccol = "WET", "#4ec3ff"
        elif _pct >= 10:
            _ctx, _ccol = "DAMP", "#9fd8ef"
        else:
            _ctx, _ccol = "DRY", "#f5c542"
        _cnd = QLabel(_ctx); _cnd.setFixedWidth(58)
        _cnd.setStyleSheet("color:%s;font-size:11px;font-weight:700;"
                           "letter-spacing:1px;background:transparent;" % _ccol)
        h.addWidget(_cnd, 0, Qt.AlignVCenter)
        _ttl = QLabel(("%d\u00b0" % round(trk_temp)) if trk_temp is not None else "\u2014")
        _ttl.setFixedWidth(46)
        _ttl.setStyleSheet("color:#cfd6e2;font-size:12px;font-weight:600;"
                           "background:transparent;")
        h.addWidget(_ttl, 0, Qt.AlignVCenter)
        _enl = QLabel((("%.1f" % e_used) + e_unit) if e_used else "\u2014")
        _enl.setFixedWidth(56)
        _enl.setStyleSheet("color:#9d6bff;font-size:12px;font-weight:700;"
                           "background:transparent;")
        h.addWidget(_enl, 0, Qt.AlignVCenter)
        _socl = QLabel(("%.1f" % soc_used) if soc_used is not None else "\u2014")
        _socl.setFixedWidth(50)
        _socl.setStyleSheet("color:#45b4ef;font-size:12px;font-weight:700;"
                            "background:transparent;")
        h.addWidget(_socl, 0, Qt.AlignVCenter)
        if not (is_out or invalid or is_in) and is_best and pace_label:
            h.addSpacing(4)
            pl = QLabel(pace_label)
            pl.setStyleSheet("color:#f5f5f5;font-size:11px;background:transparent;")
            h.addWidget(pl, 0, Qt.AlignVCenter)
            if pace_gap is not None:
                h.addSpacing(8)
                sign = "+" if pace_gap >= 0 else "\u2212"
                g = QLabel("%s%.2f" % (sign, abs(pace_gap)))
                _gc = pace_color or "#f5f5f5"
                g.setStyleSheet("color:%s;font-size:11px;font-weight:600;"
                                "background:transparent;" % _gc)
                h.addWidget(g, 0, Qt.AlignVCenter)
        h.addStretch()
        t = QLabel(_fmt(time_s) if time_s else "\u2014"); t.setFixedWidth(102)
        t.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        t.setObjectName("ovLapBest" if is_best else "ovLapTime")
        h.addWidget(t, 0, Qt.AlignVCenter)
        bs = best_secs or [None, None, None]
        for i, s in enumerate(secs):
            sl = QLabel(_fmt(s) if (s and s > 0) else "\u2014"); sl.setFixedWidth(72)
            sl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if s and bs[i] and abs(s - bs[i]) < 1e-6:
                sl.setObjectName("ovSecBest")       # miglior settore dello stint = fuxia
            else:
                sl.setObjectName("ovSec")
            h.addWidget(sl, 0, Qt.AlignVCenter)
        if ck is not None:
            h.addSpacing(12); h.addWidget(ck, 0, Qt.AlignVCenter)
        else:
            h.addSpacing(12 + 20)                  # riserva ESATTA del check (20px)
        if cond_locked:                            # giro condizione opposta: opaco
            from PySide6.QtWidgets import QGraphicsOpacityEffect
            _eff = QGraphicsOpacityEffect(self); _eff.setOpacity(0.32)
            self.setGraphicsEffect(_eff)
            self.setCursor(Qt.ArrowCursor)
        if big:                                    # giro IN CORSO (live): riga doppia,
            h.setContentsMargins(12, 13, 16, 13)   # grande, centrata, IN FOCUS
            self.setMinimumHeight(54)
            no.setStyleSheet(no.styleSheet() + "font-size:18px;font-weight:800;")
            no.setFixedSize(36, 26)
            lapw.setStyleSheet(lapw.styleSheet() + "font-size:16px;")
            t.setStyleSheet(t.styleSheet() + "font-size:20px;font-weight:800;")
            # stile SOLO sul frame (objectName dedicato): niente bordi che colano
            # su settori/tempi. Solo un fondo morbido per il focus.
            self.setObjectName("ovLapFocus")
            self.setStyleSheet(
                "#ovLapFocus{background:rgba(255,255,255,0.06);border-radius:6px;}")

    def mousePressEvent(self, e):
        if self._on_pick:
            self._on_pick(("lap", self._lap))


class _LapBoard(QFrame):
    """Pannello destro Overview: tab per stint + tabella tempi con riga REF in
    cima (logo auto + pilota + tempo, oro) e checkbox per scegliere il giro da
    confrontare; il confronto è SEMPRE vs REF (automatico)."""
    _EMPTY_SVG = b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'/>"

    def __init__(self):
        super().__init__()
        self.setObjectName("ovCard")
        self._on_stint = None; self._on_pick = None
        self._live = False        # auto-scroll all'ultimo giro solo in registrazione
        self._tyre4 = []
        v = QVBoxLayout(self); v.setContentsMargins(0, 6, 0, 6); v.setSpacing(0)
        # tab stint (niente scritta TIMES)
        head = QWidget(); hl = QHBoxLayout(head); hl.setContentsMargins(12, 6, 14, 6)
        hl.setSpacing(8)
        self._tabs_host = QWidget(); self._tabs_l = QHBoxLayout(self._tabs_host)
        self._tabs_l.setContentsMargins(0, 0, 0, 0); self._tabs_l.setSpacing(6)
        hl.addWidget(self._tabs_host); hl.addStretch()
        self.tabs_bar = head            # esposta: il parent la mette SOPRA la card
        # riga riassunto dello stint (durata effettiva, consumo gomma, energia)
        self.lb_summary = QLabel(""); self.lb_summary.setObjectName("ovStintSum")
        self.lb_summary.setTextFormat(Qt.RichText)
        self.lb_summary.setContentsMargins(20, 5, 24, 5)
        # (spostata nella stint_card del parent)
        # separatore + spazio tra riassunto e intestazione colonne
        dvw = QWidget(); dvl = QHBoxLayout(dvw); dvl.setContentsMargins(20, 6, 24, 6)
        dvl.setSpacing(0)
        div = QFrame(); div.setFixedHeight(1); div.setStyleSheet("background:#26282e;")
        dvl.addWidget(div)
        v.addWidget(dvw)
        # intestazione colonne (allineata alle righe: num a sx, check riservata a dx)
        # intestazione: STESSI margini e larghezze fisse delle righe giro
        # (riga: ...stretch | chip POS 28+12 | cond 64 | time 102 | 3x72 | 12+26)
        colh = QWidget(); cl = QHBoxLayout(colh); cl.setContentsMargins(24, 0, 28, 4)
        cl.setSpacing(0)
        cl.addSpacing(190)                # LAP(70) + 8 + colonna tag(112)
        c0 = QLabel("POS"); c0.setObjectName("ovColCap")
        c0.setFixedWidth(38); c0.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        cl.addWidget(c0)
        for cap, w in (("COND", 58), ("TRACK", 46), ("ENERGY", 56), ("SOC", 50)):
            lb = QLabel(cap); lb.setObjectName("ovColCap"); lb.setFixedWidth(w)
            lb.setAlignment(Qt.AlignLeft | Qt.AlignVCenter); cl.addWidget(lb)
        cl.addStretch()
        for cap, w in (("TIME", 102), ("S1", 72), ("S2", 72), ("S3", 72)):
            lb = QLabel(cap); lb.setObjectName("ovColCap"); lb.setFixedWidth(w)
            lb.setAlignment(Qt.AlignRight | Qt.AlignVCenter); cl.addWidget(lb)
        cl.addSpacing(12 + 20)            # colonna check riservata (20px, esatta)
        v.addWidget(colh)
        # giri (scroll) — ogni giro è una card
        from PySide6.QtWidgets import QScrollArea
        self._scroll = QScrollArea(); self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._laps_host = QWidget(); self._laps_v = QVBoxLayout(self._laps_host)
        self._laps_v.setContentsMargins(12, 0, 12, 0); self._laps_v.setSpacing(3)
        self._laps_v.addStretch()
        self._scroll.setWidget(self._laps_host)
        v.addWidget(self._scroll, 100)       # prende lo spazio per primo (cap in _build_laps)
        # slot per le card REF (oro) / ONLINE REF (blu) sotto i giri — riempito dal parent
        self._ref_slot = QVBoxLayout()
        self._ref_slot.setContentsMargins(12, 6, 12, 4)
        self._ref_slot.setSpacing(6)
        v.addLayout(self._ref_slot)
        v.addStretch(1)                      # vuoto in fondo: lista ancorata in alto

    def set_callbacks(self, on_stint, on_pick):
        self._on_stint = on_stint; self._on_pick = on_pick

    def update_board(self, keys, cur_key, laps, best_id, sel_id, cmp_lap, tyre4=None, pace=None, stint_new=None, stint_new4=None, stint_comp4=None, session_type=None, car_class=None):
        self._tyre4 = tyre4 or []
        self._session_type = session_type
        if car_class:
            self._car_class = car_class
        self._cur_is_last_stint = bool(keys) and cur_key == keys[-1]   # stint vivo = l'ultimo
        self._pace = pace if (pace and pace.get("kind")) else None
        self._stint_new_map = stint_new if isinstance(stint_new, dict) else {}
        self._stint_new4_map = stint_new4 if isinstance(stint_new4, dict) else {}
        self._stint_comp4_map = stint_comp4 if isinstance(stint_comp4, dict) else {}
        self._build_tabs(keys, cur_key)
        self._set_summary(laps)
        self._build_laps(laps, best_id, sel_id, cmp_lap)

    def _stint_started_new(self, laps):
        """Integrità gomma a INIZIO stint, scontando l'out-lap.

        Il 1° giro dello stint è l'out-lap: il wear registrato è già di FINE
        out-lap, quindi una gomma NUOVA legge <100%. Ricostruisco il valore di
        partenza ri-sommando il consumo medio di un giro (stimato dai giri
        successivi). ~100% -> nuova (pieno); inferiore -> usata (tratteggiata).
        Non dipende dal consumo successivo. Dato assente -> nuova."""
        seq = []
        for L in laps:
            ws = [L.get(k) for k in ("w_fl", "w_fr", "w_rl", "w_rr")]
            ws = [x for x in ws if x is not None]
            if ws:
                seq.append(sum(ws) / len(ws))
        if not seq:
            return True
        end_outlap = seq[0]                      # wear a fine out-lap
        drops = [seq[i - 1] - seq[i] for i in range(1, len(seq))
                 if seq[i - 1] - seq[i] > 0]
        per_lap = (sum(drops) / len(drops)) if drops else 0.0
        est_start = end_outlap + per_lap         # integrità prima dell'out-lap
        return est_start >= 99.0

    def _set_summary(self, laps):
        """Riassunto dello stint: durata effettiva, consumo gomma, energia/fuel."""
        valid_t = [L.get("lap_time") for L in laps if (L.get("lap_time") or 0) > 0]
        dur = sum(valid_t) if valid_t else 0
        fuel = sum((L.get("fuel_used") or 0.0) for L in laps)
        ve = sum((L.get("ve_used") or 0.0) for L in laps)
        w_first = w_last = None
        for L in laps:
            ws = [L.get(k) for k in ("w_fl", "w_fr", "w_rl", "w_rr")]
            ws = [x for x in ws if x is not None]
            if ws:
                avg = sum(ws) / len(ws)
                if w_first is None:
                    w_first = avg
                w_last = avg
        tyre_used = (w_first - w_last) if (w_first is not None and w_last is not None) else None
        parts = ["Duration <b style='color:#f5f5f5'>%s</b>"
                 % (_ov_clock(dur) if dur else "\u2014")]
        parts.append("Laps <b style='color:#f5f5f5'>%d</b>" % len(laps))
        # NIENTE etichetta DRY/WET sullo stint: la condizione non e' dello
        # stint ma dei SINGOLI GIRI (dichiarazione pista per giro, vedi righe).
        if tyre_used is not None and tyre_used > 0:
            parts.append("Tyre <b style='color:#f5f5f5'>-%.1f%%</b>" % tyre_used)
        if fuel > 0:
            parts.append("Fuel <b style='color:#f5f5f5'>%.1f L</b>" % fuel)
        if ve > 0:
            parts.append("Energy <b style='color:#f5f5f5'>%.0f%%</b>" % ve)
        self.lb_summary.setText("&nbsp;&nbsp;\u00b7&nbsp;&nbsp;".join(parts))

    def _build_tabs(self, keys, cur_key):
        from core.tyre_cell import TyreCell
        _clear_layout(self._tabs_l)
        four = self._tyre4 if (len(self._tyre4) == 4 and all(self._tyre4)) else None
        single = (four[0] if four else (self._tyre4[0] if self._tyre4 else ""))
        comp_map = getattr(self, "_stint_comp4_map", {}) or {}
        for k in keys:
            # mescola di QUESTO stint (per-stint); fallback alla globale (file vecchi)
            _c4k = (comp_map.get(k) or "").strip()
            if _c4k:
                fourk, singlek = _comp_four_single(_c4k)
            else:
                fourk, singlek = four, single
            _card = bool(getattr(self, "_card_tabs", False))   # pagina stint: tab blu
            if _card:
                # dipinta a mano; objectName NEUTRO (fuori dalle regole QSS
                # ovTabOn/ovTabOff dell'app che colorano lo sfondo)
                b = _CardTab(lambda kk=k: self._on_stint and self._on_stint(kk),
                             selected=(k == cur_key))
                b.setObjectName("cardTab")
            else:
                b = _ClickFrame(lambda kk=k: self._on_stint and self._on_stint(kk))
                b.setObjectName("ovTabOn" if k == cur_key else "ovTabOff")
                b.setAttribute(Qt.WA_StyledBackground, True)
                if k == cur_key:
                    b.setStyleSheet("#ovTabOn{background:rgba(255,255,255,0.22);border:none;"
                                    "border-left:3px solid #ff1d43;border-radius:10px;}")
                else:
                    b.setStyleSheet("#ovTabOff{background:rgba(255,255,255,0.10);border:none;"
                                    "border-radius:10px;}")
            bl = QHBoxLayout(b); bl.setContentsMargins(12, 5, 10, 5); bl.setSpacing(7)
            lbl = QLabel(f"STINT {k}"); lbl.setObjectName("ovTabTxt")
            lbl.setStyleSheet("color:#ffffff;font-size:11px;font-weight:700;"
                              "letter-spacing:.5px;background:transparent;border:none;")
            if _card:
                b._lbl = lbl               # hover: testo rosso LMU
            bl.addWidget(lbl, 0, Qt.AlignVCenter)
            if singlek or fourk:
                tc = TyreCell(size=26, scale=0.9)
                tc.setStyleSheet("background:transparent;")
                tc.set_tyre(singlek, fourk,
                            new4=self._stint_new4_map.get(k),
                            single_new=self._stint_new_map.get(k, True))
                bl.addWidget(tc, 0, Qt.AlignVCenter)
            self._tabs_l.addWidget(b)
        self._tabs_l.addStretch()

    def _build_laps(self, laps, best_id, sel_id, cmp_id):
        _clear_layout(self._laps_v, keep_stretch=True)
        self._focus_row = None              # riga in focus (ricalcolata a ogni rebuild)
        valid = [L for L in laps if not L.get("invalid")]

        def _bs(k):
            vals = [L.get(k) for L in valid if (L.get(k) or 0) > 0]
            return min(vals) if vals else None
        best_secs = [_bs("s1"), _bs("s2"), _bs("s3")]
        pace = getattr(self, "_pace", None)

        # --- gestione per giro: delta energia/gomma vs giro di spinta (best) ---
        def _energy(L):
            v = L.get("ve_used") or 0
            return v if v > 0 else (L.get("fuel_used") or 0)

        def _avgw(L):
            ws = [L.get(k) for k in ("w_fl", "w_fr", "w_rl", "w_rr") if L.get(k) is not None]
            return (sum(ws) / len(ws)) if ws else None

        wear_used = {}
        _prev_w = None
        for L in laps:
            a = _avgw(L)
            if _prev_w is not None and a is not None and (_prev_w - a) >= 0:
                wear_used[L["lap"]] = _prev_w - a
            if a is not None:
                _prev_w = a
        best_L = next((L for L in laps if L["lap"] == best_id), None)
        base_e = _energy(best_L) if best_L else 0
        base_w = wear_used.get(best_id) if best_id else None

        # --- condizione pista del giro selezionato (WET/DRY): blocca i giri
        # della condizione opposta (mutua esclusione nella selezione) ---
        sel_L = next((L for L in laps if L["lap"] == sel_id), None) if sel_id else None
        sel_cond = sel_L.get("declared_wet") if sel_L else None

        # classe della sessione: colore chip + icona svg (assets/class)
        _cls = getattr(self, "_car_class", "") or ""
        _cls_color = _class_color(_cls) if _cls else None
        _cls_svg = None
        if _cls:
            try:
                from core.classes import class_tag as _ct
                _tag = _ct(_cls)
            except Exception:
                _tag = (_cls or "").upper()[:3]
            _fn = {"HY": "hy", "P2": "p2", "P3": "p3",
                   "GT3": "gt3", "GTE": "gte"}.get(_tag)
            if _fn:
                from pathlib import Path as _P
                _fp = _P(__file__).resolve().parent.parent / "assets" / "class" / (_fn + ".svg")
                if _fp.exists():
                    _cls_svg = str(_fp)

        for i, L in enumerate(laps):
            secs = [L.get("s1"), L.get("s2"), L.get("s3")]
            is_best = L["lap"] == best_id
            lt = L.get("lap_time") or 0
            s1 = L.get("s1") or 0; s2 = L.get("s2") or 0; s3 = L.get("s3") or 0
            # in-lap (rientro box): e' SEMPRE l'ultimo giro dello stint (il pit
            # chiude lo stint). Settori 1-2 presenti, s3/tempo assenti, non invalid.
            # MA: sull'ULTIMO giro dello stint VIVO (in registrazione) e' il giro IN
            # CORSO, non un rientro -> niente "PIT" finche' lo stint non si chiude.
            _live_last = (getattr(self, "_live", False)
                          and getattr(self, "_cur_is_last_stint", True)
                          and i == len(laps) - 1)
            is_in = (i != 0) and (i == len(laps) - 1) and (not L.get("invalid")) \
                and (lt <= 0) and (s1 > 0) and (s2 > 0) and (s3 <= 0) \
                and (not _live_last)
            # giro senza tempo a meta' stint = invalidato (track limits/abortito).
            # Il giro IN CORSO (live, ultimo) non e' invalido: e' solo non finito.
            inval = bool(L.get("invalid")) or ((i != 0) and (lt <= 0)
                                               and (not is_in) and (not _live_last))
            usable = (i != 0) and (not is_in) and (not inval) and (not _live_last)
            e_delta = w_delta = None
            if usable:
                e = _energy(L)
                if base_e > 0 and e > 0:
                    e_delta = (e / base_e - 1.0) * 100.0
                wu = wear_used.get(L["lap"])
                if base_w and base_w > 0 and wu is not None:
                    w_delta = (wu / base_w - 1.0) * 100.0
            p_lab = p_gap = p_col = None
            if is_best and pace:
                p_lab = _pace_label(pace.get("label"))
                p_gap = pace.get("gap"); p_col = pace.get("color")
            lap_cond = L.get("declared_wet")
            # etichetta condizione: ACQUA nel punto piu' bagnato (wet_max),
            # fallback wetness media, poi dichiarazione binaria (file vecchi)
            # condizione giro = ACQUA SULLA PISTA ('wetness', la % dell'evento
            # che scende asciugando), NON meteo pioggia ne' wet_max (surface
            # sotto le gomme, a volte resta 0 su pista bagnata).
            _wm = L.get("wetness")
            if _wm is None:
                _wm = L.get("wet_max")
            if _wm is None:
                _wm = lap_cond
            lap_wet_pct = float(_wm) if _wm is not None else None
            cond_locked = False and (usable and sel_cond is not None and lap_cond is not None
                           and float(lap_cond) != float(sel_cond)
                           and L["lap"] != sel_id)
            # OUT-LAP = 1° giro dello stint (esci dai box). ECCEZIONE: in GARA il
            # 1° giro del 1° stint è il via dalla griglia, è un giro VERO non un outlap.
            _styp = getattr(self, "_session_type", None)
            _is_race = (_styp is not None and int(_styp) >= 10)   # mSession >=10 = gara
            _grid_lap = (i == 0) and _is_race and (L.get("stint") == 1)
            _is_out = (i == 0) and not _grid_lap
            # IN PISTA (live): l'ULTIMO giro (quello IN CORSO) diventa riga doppia e
            # centrata e non e' selezionabile (incompleto); tutti gli altri giri
            # COMPLETATI restano selezionabili, cosi' puoi confrontarli mentre giri.
            _live_active = (getattr(self, "_live", False)
                            and getattr(self, "_cur_is_last_stint", True))
            _big = _live_active and (i == len(laps) - 1)
            _pick_off = _big                    # in pista: solo il giro in corso e' bloccato
            _card = bool(getattr(self, "_card_tabs", False))
            _tt_lap = L.get("track_temp")
            _veu = L.get("ve_used"); _fuu = L.get("fuel_used")
            if _veu is not None and _veu > 0:
                _eu, _eun = _veu, "%"
            elif _fuu is not None and _fuu > 0:
                _eu, _eun = _fuu, "L"
            else:
                _eu, _eun = None, ""
            _ss = L.get("soc_start"); _se = L.get("soc_end")
            _socu = None
            if _ss is not None and _se is not None:
                _socu = max(0.0, (float(_ss) - float(_se)) * 100.0)
            r = _LapRow(L["lap"], L.get("lap_time"), secs,
                        is_best, inval, _is_out,
                        L["lap"] == sel_id, L["lap"] == cmp_id, self._on_pick,
                        best_secs, p_lab, p_gap, p_col, is_in=is_in,
                        e_delta=e_delta, w_delta=w_delta, cond_locked=cond_locked,
                        big=(_big and not _card),   # pagina stint: focus regolare
                        pick_off=_pick_off, wet=lap_wet_pct,
                        cls_color=_cls_color, cls_svg=_cls_svg,
                        pos=L.get("pos"),
                        trk_temp=_tt_lap, e_used=_eu, e_unit=_eun,
                        soc_used=_socu)
            if _card:
                r.setMinimumHeight(38)           # pagina stint: righe +1/3
            self._laps_v.insertWidget(self._laps_v.count() - 1, r)
            if _big:
                self._focus_row = r              # riga in focus (auto-scroll garantito)
        # altezza lista giri: max ~11 righe (erano 15: -4 per far entrare
        # ENTRAMBE le card REF sotto, LOCAL oro + ONLINE blu), poi scroll.
        _ROW = 42 if getattr(self, "_card_tabs", False) else 32   # righe +1/3 in pagina stint
        _n = self._laps_v.count() - 1            # esclude lo stretch finale
        _vis = min(max(_n, 8), 11)               # spazio per ALMENO 8 righe
        _extra = 46 if getattr(self, "_live", False) else 0   # riga grande live
        self._scroll.setMaximumHeight(_vis * _ROW + 6 + _extra)
        self._scroll.setMinimumHeight(8 * _ROW + 6)
        # focus sull'ultimo giro: scrolla dopo il layout (0ms) e ritenta a layout
        # assestato (la geometria della riga grande non e' pronta a 0ms)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._scroll_laps_bottom)
        QTimer.singleShot(50, self._scroll_laps_bottom)

    def _scroll_laps_bottom(self):
        if not getattr(self, "_live", False):
            return                       # solo in registrazione (in pista)
        sb = self._scroll.verticalScrollBar()
        fr = getattr(self, "_focus_row", None)
        if fr is not None:
            try:
                self._scroll.ensureWidgetVisible(fr, 0, 40)
            except Exception:
                pass
        # garanzia: la riga grande e' l'ultima -> il fondo la mostra sempre intera
        sb.setValue(sb.maximum())


_BEST_ROSE = "#ff5bb0"   # bordo check del giro più veloce (rosa)


def _comp_four_single(c4, fallback=""):
    """compounds4 'FL,FR,RL,RR' -> (four|None, single). four valido solo se 4
    sigle presenti; single = sigla principale o fallback."""
    four = [x.strip() for x in (c4 or "").split(",")][:4]
    four = four if (len(four) == 4 and all(four)) else None
    single = (four[0] if four else fallback) or fallback
    return four, single
