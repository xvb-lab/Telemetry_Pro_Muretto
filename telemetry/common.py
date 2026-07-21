"""telemetry/common.py — base condivisa: helper puri, stato/colori, costanti tema,
e widget di basso livello (_SvgBox) usati sia dalla vista (trace_view) sia dall'app.
Estratto 1:1 da window.py (Step 1+2 ricostruzione)."""

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
from PySide6.QtCore import QByteArray
from . import db as _db
from .reader import TelemetryReader
from core.classes import class_tag
try:
    from PySide6.QtSvgWidgets import QSvgWidget
except Exception:
    QSvgWidget = None
try:
    from PySide6.QtSvg import QSvgRenderer
except Exception:
    QSvgRenderer = None

def _rows(con, sql, args=()):
    """Query -> lista di dict. La connessione live e' condivisa tra thread
    (recorder che scrive, UI che legge): un colpo a vuoto transitorio
    (BUSY/uso concorrente) NON deve diventare una mappa/traiettoria vuota.
    Si riprova fino a 3 volte con una pausa breve, poi si rilancia."""
    import time as _t
    last = None
    for _try in range(3):
        try:
            cur = con.execute(sql, args)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
        except (sqlite3.OperationalError, sqlite3.ProgrammingError) as ex:
            last = ex
            _t.sleep(0.06)
    raise last


def _fmt(s):
    if not s or s <= 0:
        return "\u2014"
    m = int(s) // 60; sec = s - m * 60
    return f"{m}:{sec:06.3f}" if m else f"{sec:.3f}"


_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _date_human(s):
    """ISO '2026-06-23T04:25' / '2026-06-23 04:25' -> '23 Jun 2026, 04:25'."""
    s = (s or "")[:16].replace("T", " ")
    try:
        d, t = s.split(" ")
        y, mo, da = d.split("-")
        return "%d %s %s, %s" % (int(da), _MONTHS[int(mo) - 1], y, t)
    except Exception:
        return s


def _f2(v):
    return "\u2014" if v is None else f"{v:.2f}"


def _dur(secs):
    secs = int(secs or 0)
    h = secs // 3600; m = (secs % 3600) // 60
    return f"{h}h{m:02d}min" if h else f"{m}min"


def _fastest_lap(laps):
    valid = [L for L in laps if (L["lap_time"] or 0) > 0 and not L["invalid"]]
    if not valid:
        valid = [L for L in laps if (L["lap_time"] or 0) > 0]
    if not valid:
        return laps[0]["lap"] if laps else None
    return min(valid, key=lambda L: L["lap_time"])["lap"]


def _two_best_laps(laps):
    """Ritorna (miglior_giro, secondo_giro) validi per lap_time crescente."""
    valid = [L for L in laps if (L["lap_time"] or 0) > 0 and not L["invalid"]]
    if len(valid) < 2:
        valid = [L for L in laps if (L["lap_time"] or 0) > 0]
    order = sorted(valid, key=lambda L: L["lap_time"])
    best = order[0]["lap"] if len(order) >= 1 else (laps[0]["lap"] if laps else None)
    second = order[1]["lap"] if len(order) >= 2 else best
    return best, second


def _clear_layout(lay, keep_stretch=False):
    while lay.count():
        it = lay.takeAt(0)
        w = it.widget()
        if w is not None:
            w.hide()                 # evita il flash come finestra top-level
            w.deleteLater()          # NON usare setParent(None) su widget visibili
    if keep_stretch:
        lay.addStretch()


# ── stato/colori + tema + widget base (Step 2) ──

_CLASS_COL = {
    "HY":  "#bd1016", "P2": "#1e3163", "P3": "#411c52",
    "GT3": "#01824d", "GTE": "#ff9100",
}


_BG = "#111114"          # grafite neutro (niente blu)


_FG = "#f5f5f5"


_GRID = "#2c2e33"


_ACCENT = "#1c9fe0"      # blu pista LMU (tab attiva)


_FUCHSIA = "#ff48cf"


_SEL_COL = "#9b6dff"     # giro Selected (viola)


_CMP_COL = "#55ff7f"     # giro Compare (verde)


_GOLD = "#f5c542"        # Compare = REF (record): oro


_TRK_COL = "#5e5e5e"     # pista (grigio asfalto, pickabile)


_HYBRID_HINTS = ("HY", "HYPER", "LMH", "LMDH", "LMP1")


def _is_hybrid(car_class):
    c = (car_class or "").upper()
    return any(h in c for h in _HYBRID_HINTS)


def _heat(v, lo, hi):
    if v is None:
        return QColor("#3d4046")
    f = max(0.0, min(1.0, (v - lo) / (hi - lo))) if hi > lo else 0.0
    stops = [(0.0, (74, 144, 226)), (0.5, (0, 230, 118)),
             (0.8, (255, 226, 77)), (1.0, (255, 59, 48))]
    for i in range(len(stops) - 1):
        f0, c0 = stops[i]; f1, c1 = stops[i + 1]
        if f0 <= f <= f1:
            t = (f - f0) / (f1 - f0) if f1 > f0 else 0
            return QColor(int(c0[0] + (c1[0] - c0[0]) * t),
                          int(c0[1] + (c1[1] - c0[1]) * t),
                          int(c0[2] + (c1[2] - c0[2]) * t))
    return QColor("#3d4046")


_FUX = "#ff3bd4"   # fuxia: migliore (tempo/settore)


_SEL_IS_BEST = False   # True quando il giro selezionato è il best -> fuxia


_CUSTOM_SEL = False    # True = l'utente ha scelto un colore (pick-color):
_CUSTOM_CMP = False    # il SUO colore vince sul forcing fuxia/oro del "best"


def _sel_col():
    """Colore del giro SELEZIONATO: fuxia se è il best, altrimenti verde.
    Se l'utente ha scelto un colore custom, vince quello (niente blocco)."""
    if _CUSTOM_SEL:
        return _SEL_COL
    return _FUX if _SEL_IS_BEST else _SEL_COL


_CMP_IS_BEST = False   # True quando il giro di CONFRONTO è il best


def _cmp_col(gold=False):
    """Colore del giro di CONFRONTO: oro se REF (asciutto), azzurro se REF in
    WET, fuxia se è il best, altrimenti blu. Custom dell'utente vince."""
    if _CUSTOM_CMP:
        return _CMP_COL
    if gold == 2:
        return "#4ec3ff"          # REF in condizione WET -> azzurro
    if gold:
        return _GOLD
    return _FUX if _CMP_IS_BEST else _CMP_COL


def _is_b(v, b):
    return b is not None and v is not None and abs(v - b) < 1e-6


def _best_color(v, best, normal="#ffffff"):
    """Fuxia se v è il migliore di stint, altrimenti colore normale."""
    return _FUX if _is_b(v, best) else normal


def _faster_colors(la, lb):
    """Colore (Selected, Compare): il più veloce dei due in fuxia."""
    if la and lb:
        return (_FUX, "#979aa1") if la <= lb else ("#979aa1", _FUX)
    if la:
        return (_FUX, "#979aa1")
    if lb:
        return ("#979aa1", _FUX)
    return ("#dcdddf", "#dcdddf")


def _draw_lap_legend(p, x0, y, items):
    """items: (dashed, label, time_str, time_color). Linea + 'Lap N' + tempo."""
    x = float(x0)
    for dashed, label, tstr, tcol in items:
        pen = QPen(QColor("#dcdddf"), 2)
        if dashed:
            pen.setStyle(Qt.DashLine)
        p.setPen(pen); p.drawLine(int(x), y, int(x) + 18, y)
        x += 24
        p.setPen(QColor("#dcdddf")); p.drawText(QPointF(x, y + 4), label)
        x += p.fontMetrics().horizontalAdvance(label) + 7
        if tstr:
            p.setPen(QColor(tcol)); p.drawText(QPointF(x, y + 4), tstr)
            x += p.fontMetrics().horizontalAdvance(tstr) + 18
        else:
            x += 14


def _draw_sector_times(p, Xf, bounds, sel_secs, cmp_secs, best_secs, xmin, xmax, y):
    """Per ogni settore: tempo Selected (sopra) e Compare (sotto). Il più veloce
    dei due settori mostrati è in fuxia."""
    for i in range(3):
        if i + 1 >= len(bounds):
            break
        cx = (bounds[i] + bounds[i + 1]) / 2.0
        if not (xmin <= cx <= xmax):
            continue
        sv = sel_secs[i] if i < len(sel_secs) else None
        cv = cmp_secs[i] if i < len(cmp_secs) else None
        bv = best_secs[i] if i < len(best_secs) else None
        sx = Xf(cx); yy = y
        if sv:
            col = _FUX if _is_b(sv, bv) else "#ffffff"
            s = _fmt(sv); tw = p.fontMetrics().horizontalAdvance(s)
            p.setPen(QColor(col)); p.drawText(QPointF(sx - tw / 2, yy), s); yy += 11
        if cv:
            col = _FUX if _is_b(cv, bv) else "#ffffff"
            s = _fmt(cv); tw = p.fontMetrics().horizontalAdvance(s)
            p.setPen(QColor(col)); p.drawText(QPointF(sx - tw / 2, yy), s)


_SVG_RENDERER_CACHE = {}


class _SvgBox(QWidget):
    """Render di un SVG mantenendo le proporzioni (centrato).
    Renderer condiviso per sorgente + render messo in cache come QPixmap
    (ri-renderizza solo quando cambia sorgente o dimensione)."""
    def __init__(self, min_h=0):
        super().__init__()
        self._r = None
        self._pix = None
        self._pix_key = None
        if min_h:
            self.setMinimumHeight(min_h)

    def load(self, src):
        if QSvgRenderer is None:
            return
        if not src or (not isinstance(src, (bytes, bytearray)) and not str(src).strip()):
            self.clear(); return        # niente percorso -> evita "filename is empty"
        key = bytes(src) if isinstance(src, (bytes, bytearray)) else str(src)
        r = _SVG_RENDERER_CACHE.get(key)
        if r is None:
            try:
                r = QSvgRenderer(QByteArray(bytes(src))) if isinstance(src, (bytes, bytearray)) \
                    else QSvgRenderer(str(src))
                if not r.isValid():
                    r = None
            except Exception:
                r = None
            if r is not None:
                _SVG_RENDERER_CACHE[key] = r
        self._r = r
        self._pix = None; self._pix_key = None
        self.update()

    def clear(self):
        self._r = None
        self._pix = None; self._pix_key = None
        self.update()

    def paintEvent(self, e):
        if self._r is None:
            return
        W, H = self.width(), self.height()
        if W <= 0 or H <= 0:
            return
        dpr = self.devicePixelRatioF()
        key = (W, H, round(dpr, 3), id(self._r))
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
            pp.end()
            self._pix = pix; self._pix_key = key
        p = QPainter(self)
        p.drawPixmap(0, 0, self._pix)
        p.end()


# ── formati sessione (condivisi) ──

def _ov_session_label(st):
    try:
        st = int(st)
    except Exception:
        return "Session"
    if st <= 0:
        return "Test Day"
    if 1 <= st <= 4:
        return "Practice"
    if 5 <= st <= 8:
        return "Qualify"
    if st == 9:
        return "Warmup"
    return "Race"


def _ov_clock(s):
    s = int(s); h = s // 3600; m = (s % 3600) // 60; sec = s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def _fmt_session_len(s):
    """Durata impostata della sessione: '6h', '10m', '1h30m'."""
    if not s or s <= 0:
        return ""
    s = int(round(s)); h = s // 3600; m = (s % 3600) // 60
    if h:
        return f"{h}h{m:02d}m" if m else f"{h}h"
    if m:
        return f"{m}m"
    return f"{s}s"
