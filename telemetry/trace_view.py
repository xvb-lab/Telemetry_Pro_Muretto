"""telemetry/trace_view.py — livello vista/analisi telemetria (grafici, mappa,
pedali, gomme, freni, delta, stint, LiveView). Dipende solo dal DB e da
telemetry.common. Estratto 1:1 da window.py (Step 2)."""

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
_ROOT = Path(__file__).resolve().parent.parent
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
try:
    from widgets.map.widget import MapCanvas as _RealMapCanvas
    from widgets.map.reader import MapReader as _RealMapReader
except Exception:
    _RealMapCanvas = None
    _RealMapReader = None
from telemetry import common as _common
from telemetry.common import (_ACCENT, _BG, _CLASS_COL, _CMP_COL, _CMP_IS_BEST, _FG, _FUCHSIA, _FUX, _GOLD, _GRID, _HYBRID_HINTS, _MONTHS, _SEL_COL, _SEL_IS_BEST, _SVG_RENDERER_CACHE, _SvgBox, _TRK_COL, _best_color, _clear_layout, _cmp_col, _date_human, _draw_lap_legend, _draw_sector_times, _dur, _f2, _faster_colors, _fastest_lap, _fmt, _heat, _is_b, _is_hybrid, _rows, _sel_col, _two_best_laps)


class LineChart(QWidget):
    def __init__(self):
        super().__init__()
        self._xs = []; self._series = []
        self.setMinimumHeight(170)

    def set_data(self, xs, series):
        self._xs = xs or []; self._series = series or []
        self.update()

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(_BG))
        m = 30
        x0, y0, x1, y1 = m, 8, w - 8, h - m
        p.setPen(QPen(QColor(_GRID), 1)); p.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))
        if not self._xs or not self._series:
            p.setPen(QColor("#878a93")); p.drawText(self.rect(), Qt.AlignCenter, "no data"); return
        xmin, xmax = min(self._xs), max(self._xs)
        allv = [v for _, ys, _ in self._series for v in ys if v is not None]
        if not allv or xmax <= xmin:
            return
        vmin, vmax = min(allv), max(allv)
        if vmax <= vmin:
            vmax = vmin + 1
        px = lambda x: x0 + (x - xmin) / (xmax - xmin) * (x1 - x0)
        py = lambda v: y1 - (v - vmin) / (vmax - vmin) * (y1 - y0)
        for name, ys, col in self._series:
            p.setPen(QPen(col, 1.6)); poly = QPolygonF()
            for x, v in zip(self._xs, ys):
                if v is None:
                    continue
                poly.append(QPointF(px(x), py(v)))
            p.drawPolyline(poly)
        lx, ly = x0 + 6, y0 + 12
        for name, ys, col in self._series:
            p.setPen(QPen(col, 2)); p.drawLine(lx, ly, lx + 14, ly)
            p.setPen(QColor(_FG)); p.drawText(lx + 18, ly + 4, name)
            lx += 18 + p.fontMetrics().horizontalAdvance(name) + 18


class TrajectoryView(QWidget):
    """Traiettoria giro (colore = velocita') SOPRA la mappa ufficiale della
    pista (settings/trackmap, stesse coordinate mondo): la mappa c'e' sempre,
    anche quando i punti giro mancano — e in quel caso LO DICE."""

    def __init__(self):
        super().__init__()
        self._pts = []
        self._map = []
        self.setMinimumHeight(260)

    def set_path(self, pts):
        self._pts = pts or []; self.update()

    def set_map(self, pts):
        self._map = pts or []; self.update()

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(_BG))
        base = self._pts if len(self._pts) >= 2 else self._map
        if len(base) < 2:
            p.setPen(QColor("#878a93"))
            p.drawText(self.rect(), Qt.AlignCenter, "no trajectory")
            return
        # inquadratura: sull'unione mappa+traiettoria (stesse coordinate mondo)
        allp = [(q[0], q[1]) for q in self._map] +                [(q[0], q[1]) for q in self._pts]
        xs = [q[0] for q in allp]; zs = [q[1] for q in allp]
        xmin, xmax = min(xs), max(xs); zmin, zmax = min(zs), max(zs)
        sx = (xmax - xmin) or 1; sz = (zmax - zmin) or 1
        m = 16; scale = min((w - 2 * m) / sx, (h - 2 * m) / sz)
        ox = (w - sx * scale) / 2 - xmin * scale
        oz = (h - sz * scale) / 2 - zmin * scale
        P = lambda x, z: QPointF(ox + x * scale, h - (oz + z * scale))
        # strato 1: la mappa ufficiale, grigia e discreta
        if len(self._map) >= 2:
            p.setPen(QPen(QColor(120, 126, 138, 130), 5.0,
                          Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            for i in range(1, len(self._map)):
                p.drawLine(P(self._map[i - 1][0], self._map[i - 1][1]),
                           P(self._map[i][0], self._map[i][1]))
            p.drawLine(P(self._map[-1][0], self._map[-1][1]),
                       P(self._map[0][0], self._map[0][1]))
        # strato 2: la traiettoria heat-colorata
        if len(self._pts) >= 2:
            vs = [pt[2] for pt in self._pts if pt[2] is not None] or [0, 1]
            vmin, vmax = min(vs), max(vs)
            for i in range(1, len(self._pts)):
                x0, z0, _ = self._pts[i - 1]; x1, z1, v1 = self._pts[i]
                p.setPen(QPen(_heat(v1, vmin, vmax), 2.2))
                p.drawLine(P(x0, z0), P(x1, z1))
        elif len(self._map) >= 2:
            p.setPen(QColor("#b8bcc6"))
            p.drawText(self.rect().adjusted(0, 0, 0, -8),
                       Qt.AlignHCenter | Qt.AlignBottom,
                       "lap trajectory data missing (pos not recorded)")


def _wheel_widget(spec):
    """Valori per-ruota in griglia 2x2 (FL FR / RL RR), sfondo trasparente.
    Temperature heat-colorate; usura in bianco."""
    from PySide6.QtWidgets import QGridLayout
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    w.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    g = QGridLayout(w)
    g.setContentsMargins(8, 2, 8, 2)
    g.setHorizontalSpacing(18); g.setVerticalSpacing(1)
    lo, hi, heat, dec = spec["lo"], spec["hi"], spec["heat"], spec["dec"]
    cells = list(zip(spec["wheels"], ("FL", "FR", "RL", "RR")))
    for idx, (val, pos) in enumerate(cells):
        if val is None:
            txt = "\u2014"; col = "#6b6f78"
        else:
            txt = f"{val:.{dec}f}"
            col = _heat(val, lo, hi).name() if heat else _FG
        lbl = QLabel(txt)
        lbl.setStyleSheet(f"color:{col};background:transparent;")
        g.addWidget(lbl, idx // 2, idx % 2)
    return w


class _LapData:
    """Motore dati condiviso fra le tab categoria.
    Calcola i valori di un giro (e i migliori dello stint) una volta sola."""
    def __init__(self):
        self.con = None
        self.car_class = ""
        self.sample_cols = set()
        self.tyre_mode = "t_"       # t_=carcass, ts_=tread, ti_=layer
        self._by_id = {}
        self._first = None
        self._best = {}
        self._stint_total = 0
        self._stint_laps = 0
        self.lap_ids = []
        # reference lap (confrontabile fra sessioni)
        self.ref_con = None
        self.ref_lap = None
        self.ref_on = False
        self.ref_wet = False
        self.ref_label = ""
        self.ref_time = None
        self.ref_secs = [None, None, None]
        self.ref_driver = ""; self.ref_team = ""; self.ref_vehicle = ""
        self.ref_wet_pct = None
        self.ref_started = ""; self.ref_session = None
        self.ref_compounds4 = ""; self.ref_tyre_state = None
        self.ref_load_pct = None; self.ref_load_kind = ""
        self.ref_wear4 = []; self.ref_fuel_l = None
        # confronto ESTERNO (giro di una sessione team, disegnato BLU)
        self.xcmp_con = None; self.xcmp_lap = None
        self.xcmp_label = ""; self.xcmp_time = None
        self.xcmp_secs = [None, None, None]; self.xcmp_file = None

    def set_con(self, con):
        self.con = con
        self.sample_cols = set()
        if con is not None:
            try:
                self.sample_cols = {c[1] for c in con.execute("PRAGMA table_info(samples)")}
            except Exception:
                self.sample_cols = set()

    def set_stint(self, laps):
        self._by_id = {L["lap"]: L for L in laps}
        self._first = laps[0]["lap"] if laps else None
        self.lap_ids = [L["lap"] for L in laps]

        def _minpos(key, valid_only=False):
            vals = [L[key] for L in laps
                    if L[key] and L[key] > 0 and (not valid_only or not L["invalid"])]
            return min(vals) if vals else None
        self._best = {"lap_time": _minpos("lap_time", True),
                      "s1": _minpos("s1", True), "s2": _minpos("s2", True), "s3": _minpos("s3", True)}
        timed = [L["lap_time"] for L in laps if L["lap_time"] and L["lap_time"] > 0]
        self._stint_total = sum(timed)
        self._stint_laps = len(laps)

    def best_dict(self):
        """Best assoluto dello stint dai giri validi (stesso calcolo della lista
        Stint). Unica fonte per Times/grafici/Stint."""
        laps = list(self._by_id.values())

        def _b(key):
            vals = [L.get(key) for L in laps
                    if (L.get(key) or 0) > 0 and not L.get("invalid")]
            return min(vals) if vals else None
        return {"lap_time": _b("lap_time"), "s1": _b("s1"),
                "s2": _b("s2"), "s3": _b("s3")}

    def load_reference(self, path):
        """Apre un file .lmref (un solo giro) come riferimento confrontabile."""
        import os
        self.clear_reference()
        if not path or not os.path.exists(path):
            return False
        try:
            con = sqlite3.connect(path)
            row = con.execute(
                "SELECT lap, lap_time, s1, s2, s3 FROM laps ORDER BY lap LIMIT 1").fetchone()
            if not row:
                con.close(); return False
            self.ref_con = con
            self.ref_lap = row[0]
            self.ref_time = row[1]
            try:
                _wm = con.execute("SELECT wet_max FROM laps WHERE lap=?",
                                  (row[0],)).fetchone()
                self.ref_wet_pct = float(_wm[0]) if (_wm and _wm[0] is not None) else None
            except Exception:
                self.ref_wet_pct = None
            self.ref_secs = [row[2], row[3], row[4]]
            self.ref_label = ("REF " + (_fmt(row[1]) if row[1] else "")).strip()
            try:
                mr = con.execute("SELECT driver, team, vehicle, started_at, "
                                 "session_type FROM session_meta WHERE id=1").fetchone()
                self.ref_driver = (mr[0] if mr else "") or ""
                self.ref_team = (mr[1] if mr else "") or ""
                self.ref_vehicle = (mr[2] if mr else "") or ""
                self.ref_started = (mr[3] if mr else "") or ""
                self.ref_session = (mr[4] if mr else None)
            except Exception:
                self.ref_driver = self.ref_team = self.ref_vehicle = ""
                self.ref_started = ""; self.ref_session = None
            try:
                lr = con.execute(
                    "SELECT w_fl,w_fr,w_rl,w_rr,ve_end,fuel_end,fuel_used FROM laps WHERE lap=?",
                    (self.ref_lap,)).fetchone()
                mr2 = con.execute(
                    "SELECT compounds4, fuel_max FROM session_meta WHERE id=1").fetchone()
                # compound del GIRO (registrato in pista) e' affidabile; il meta e'
                # catturato all'apertura (garage) e cade sul default (es. "W"/"H").
                # Query separata e protetta: i .lmref vecchi senza colonna non si rompono.
                _lap_c4 = None
                try:
                    _c4r = con.execute(
                        "SELECT compounds4 FROM laps WHERE lap=?",
                        (self.ref_lap,)).fetchone()
                    _lap_c4 = (_c4r[0] if _c4r else None)
                except Exception:
                    _lap_c4 = None
                self.ref_compounds4 = (_lap_c4 or (mr2[0] if mr2 else "") or "")
                fmax = (mr2[1] if mr2 else None)
                if lr:
                    self.ref_wear4 = [lr[0], lr[1], lr[2], lr[3]]
                    ws = [x for x in lr[0:4] if x is not None]
                    self.ref_tyre_state = (sum(ws) / len(ws)) if ws else None
                    ve = lr[4]; fu = lr[5]; fuse = lr[6]
                    self.ref_fuel_l = (((fu or 0) + (fuse or 0))
                                       if (fu is not None or fuse is not None) else None)
                    if ve is not None:
                        self.ref_load_pct = ve; self.ref_load_kind = "VE"
                    elif fu is not None and fmax:
                        self.ref_load_pct = fu / fmax * 100.0; self.ref_load_kind = "FUEL"
            except Exception:
                self.ref_compounds4 = ""; self.ref_tyre_state = None
                self.ref_load_pct = None; self.ref_load_kind = ""
                self.ref_wear4 = []; self.ref_fuel_l = None
            return True
        except Exception:
            self.clear_reference(); return False

    def clear_reference(self):
        if self.ref_con is not None:
            try:
                self.ref_con.close()
            except Exception:
                pass
        self.ref_con = None; self.ref_lap = None
        self.ref_time = None; self.ref_secs = [None, None, None]; self.ref_label = ""
        self.ref_driver = ""; self.ref_team = ""; self.ref_vehicle = ""
        self.ref_started = ""; self.ref_session = None
        self.ref_compounds4 = ""; self.ref_tyre_state = None
        self.ref_load_pct = None; self.ref_load_kind = ""
        self.ref_wear4 = []; self.ref_fuel_l = None
        self.ref_on = False
        self.ref_wet = False

    def load_external_compare(self, path, lap):
        """Carica UN giro da un file team come confronto esterno (blu)."""
        import os
        self.clear_external_compare()
        if not path or not os.path.exists(path):
            return False
        try:
            con = sqlite3.connect(path)
            row = con.execute("SELECT lap_time, s1, s2, s3 FROM laps WHERE lap=?",
                              (lap,)).fetchone()
            if not row:
                con.close(); return False
            drv = ""
            try:
                mr = con.execute("SELECT driver FROM session_meta WHERE id=1").fetchone()
                drv = (mr[0] if mr else "") or ""
            except Exception:
                drv = ""
            self.xcmp_con = con; self.xcmp_lap = lap
            self.xcmp_time = row[0]; self.xcmp_secs = [row[1], row[2], row[3]]
            self.xcmp_label = ((drv + " ") if drv else "") + (_fmt(row[0]) if row[0] else "")
            self.xcmp_file = path
            return True
        except Exception:
            self.clear_external_compare(); return False

    def clear_external_compare(self):
        if self.xcmp_con is not None:
            try:
                self.xcmp_con.close()
            except Exception:
                pass
        self.xcmp_con = None; self.xcmp_lap = None
        self.xcmp_label = ""; self.xcmp_time = None
        self.xcmp_secs = [None, None, None]; self.xcmp_file = None

    def cmp_source(self):
        """(con, lap, label, time, secs, gold) del Compare esterno attivo.
        gold=False per il giro team (blu), gold=True per il REF record."""
        if self.xcmp_con is not None and self.xcmp_lap is not None:
            return (self.xcmp_con, self.xcmp_lap, self.xcmp_label or "TEAM",
                    self.xcmp_time, self.xcmp_secs, False)
        if self.ref_on and self.ref_con is not None and self.ref_lap is not None:
            return (self.ref_con, self.ref_lap, self.ref_label or "REF",
                    self.ref_time, self.ref_secs,
                    2 if getattr(self, "ref_wet", False) else True)
        return None

    def _elec_from_samples(self, lap):
        """Totali-giro ibrido integrati dai samples (per file senza colonne energia)."""
        rg = bo = 0.0
        soc0 = soc1 = None
        prev_t = None
        for r in _rows(self.con,
                       "SELECT t, regen_kw, soc FROM samples WHERE lap=? ORDER BY rowid", (lap,)):
            if soc0 is None:
                soc0 = r["soc"]
            soc1 = r["soc"]
            rk = r["regen_kw"] or 0.0
            if prev_t is not None:
                dt = r["t"] - prev_t
                if 0.0 < dt < 0.5:
                    e = abs(rk) * dt / 3600.0
                    if rk > 0:
                        rg += e
                    elif rk < 0:
                        bo += e
            prev_t = r["t"]
        return rg, bo, soc0, soc1

    def values(self, lap):
        L = self._by_id.get(lap)
        if not L:
            return None
        mx = av = None
        if self.con is not None:
            s = _rows(self.con,
                      "SELECT MAX(speed) mx, AVG(speed) av FROM samples WHERE lap=?", (lap,))
            if s:
                mx, av = s[0]["mx"], s[0]["av"]
        hyb = _is_hybrid(self.car_class)
        soc_s, soc_e = L.get("soc_start"), L.get("soc_end")
        rg_gain, bo_kwh = L.get("regen_gain_kwh"), L.get("boost_kwh")
        # file vecchi senza colonne energia: ricava i totali-giro dai samples
        if hyb and rg_gain is None and self.con is not None:
            rg_gain, bo_kwh, soc_s, soc_e = self._elec_from_samples(lap)
        t = L["lap_time"]
        ttxt = _fmt(t) if (t and t > 0) else ("OUT" if lap == self._first else "IN")
        fu, vu = L["fuel_used"], L["ve_used"]
        ftxt = "PIT" if (fu is not None and fu < 0) else _f2(fu)
        vtxt = "PIT" if (vu is not None and vu < 0) else _f2(vu)

        def _is_best(key, val, valid_req=False):
            b = self._best.get(key)
            if b is None or not val or val <= 0:
                return False
            if valid_req and L["invalid"]:
                return False
            return abs(val - b) < 1e-6

        vals = {"Stint": f"{_dur(self._stint_total)}  ({self._stint_laps} laps)",
                "Lap": str(lap), "Time": ttxt,
                "Sector 1": _fmt(L["s1"]), "Sector 2": _fmt(L["s2"]), "Sector 3": _fmt(L["s3"]),
                "Fuel used (L)": ftxt, "VE used (%)": vtxt,
                "SOC start (%)": "\u2014" if (not hyb or soc_s is None) else f"{soc_s:.1f}",
                "SOC end (%)": "\u2014" if (not hyb or soc_e is None) else f"{soc_e:.1f}",
                "Regen gained (kWh)": "\u2014" if (not hyb or rg_gain is None) else f"{rg_gain:.2f}",
                "Boost used (kWh)": "\u2014" if (not hyb or bo_kwh is None) else f"{bo_kwh:.2f}",
                "Top speed (km/h)": "\u2014" if mx is None else f"{mx:.1f}",
                "Avg speed (km/h)": "\u2014" if av is None else f"{av:.1f}",
                "Valid": "no" if L["invalid"] else "yes"}
        best = {"Time": _is_best("lap_time", t, True),
                "Sector 1": _is_best("s1", L["s1"]),
                "Sector 2": _is_best("s2", L["s2"]),
                "Sector 3": _is_best("s3", L["s3"])}

        secs = {}
        if self.con is not None:
            for sr in _rows(self.con, "SELECT * FROM sectors WHERE lap=? ORDER BY sector", (lap,)):
                secs[int(sr["sector"])] = sr

        def _w(sr, prefix):
            return [sr.get(prefix + k) for k in ("fl", "fr", "rl", "rr")]

        # PIT solo se il totale giro è davvero un rifornimento; altrimenti negativo = glitch -> "—"
        lap_fuel_pit = (fu is not None and fu < 0)
        lap_ve_pit = (vu is not None and vu < 0)

        def _sec_consumo(x, lap_pit):
            if x is None:
                return "\u2014"
            if x < 0:
                return "PIT" if lap_pit else "\u2014"
            return f"{x:.2f}"

        for s in (1, 2, 3):
            sr = secs.get(s - 1)
            if sr:
                sa, sm, sf = sr.get("spd_avg"), sr.get("spd_max"), sr.get("fuel_used")
                ve = sr.get("ve_used")
                rgs, bks, scu = sr.get("regen_gain_kwh"), sr.get("boost_kwh"), sr.get("soc_used")
                vals[f"S{s} speed avg (km/h)"] = "\u2014" if sa is None else f"{sa:.1f}"
                vals[f"S{s} speed max (km/h)"] = "\u2014" if sm is None else f"{sm:.1f}"
                vals[f"S{s} speed (km/h)"] = "\u2014" if sa is None else f"{sa:.1f}"
                vals[f"S{s} VE (%)"] = _sec_consumo(ve, lap_ve_pit)
                vals[f"S{s} fuel (L)"] = _sec_consumo(sf, lap_fuel_pit)
                vals[f"S{s} regen (kWh)"] = "\u2014" if (not hyb or rgs is None) else f"{rgs:.2f}"
                vals[f"S{s} boost (kWh)"] = "\u2014" if (not hyb or bks is None) else f"{bks:.2f}"
                vals[f"S{s} SOC \u0394 (%)"] = "\u2014" if (not hyb or scu is None) else f"{-scu:+.1f}"
                vals[f"S{s} tyre \u00b0C"] = {"wheels": _w(sr, self.tyre_mode), "lo": 60, "hi": 120, "heat": True, "dec": 0}
                vals[f"S{s} press kPa"] = {"wheels": _w(sr, "p_"), "lo": 120, "hi": 220, "heat": False, "dec": 0}
                vals[f"S{s} brake \u00b0C"] = {"wheels": _w(sr, "b_"), "lo": 100, "hi": 700, "heat": True, "dec": 0}
                vals[f"S{s} wear %"] = {"wheels": _w(sr, "w_"), "lo": 0, "hi": 100, "heat": False, "dec": 1}
            else:
                vals[f"S{s} speed avg (km/h)"] = "\u2014"
                vals[f"S{s} speed max (km/h)"] = "\u2014"
                vals[f"S{s} speed (km/h)"] = "\u2014"
                vals[f"S{s} VE (%)"] = "\u2014"
                vals[f"S{s} fuel (L)"] = "\u2014"
                vals[f"S{s} regen (kWh)"] = "\u2014"
                vals[f"S{s} boost (kWh)"] = "\u2014"
                vals[f"S{s} SOC \u0394 (%)"] = "\u2014"
                for nm, (lo, hi, ht, dec) in ((f"S{s} tyre \u00b0C", (60, 120, True, 0)),
                                              (f"S{s} press kPa", (120, 220, False, 0)),
                                              (f"S{s} brake \u00b0C", (100, 700, True, 0)),
                                              (f"S{s} wear %", (0, 100, False, 1))):
                    vals[nm] = {"wheels": [None, None, None, None], "lo": lo, "hi": hi, "heat": ht, "dec": dec}
        return vals, best


class _CmpChart(QWidget):
    """Confronto a linee Lap A vs Lap B del valore selezionato.
    Modalità 'trace' (continua sul giro) o 'points' (punti etichettati S1/S2/S3
    o FL/FR/RL/RR) con marker e valori. Colori configurabili dall'utente."""
    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WA_TranslucentBackground, True)  # radiale traspare
        self._title = ""
        self._unit = ""
        self._sa = []          # [(x, y)] giro Selected
        self._sb = []          # [(x, y)] giro Compare
        self._xlabels = None   # se valorizzato -> modalità 'points'
        self._groups = []      # [(label, A, B)] -> modalità 'bars'
        self._mode = "line"
        self._la = "A"
        self._lb = "B"
        self._dot_hit = {}        # {"sel"/"cmp": QRectF} hitbox dei dot legend
        self.color_cb = None      # callback(which) impostata dalla finestra
        self.setMinimumHeight(196)
        self.setMouseTracking(True)

    def mousePressEvent(self, e):
        if self.color_cb is not None:
            for which, rect in self._dot_hit.items():
                if rect.contains(e.position()):
                    self.color_cb(which); return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        on_dot = any(r.contains(e.position()) for r in self._dot_hit.values())
        self.setCursor(Qt.PointingHandCursor if on_dot else Qt.ArrowCursor)
        super().mouseMoveEvent(e)

    def set_data(self, title, unit, sa, sb, la, lb, xlabels=None):
        self._mode = "line"
        self._title = title; self._unit = unit
        self._sa = sa or []; self._sb = sb or []
        self._xlabels = xlabels
        self._la = la; self._lb = lb
        self.update()

    def set_bars(self, title, unit, groups, la, lb):
        self._mode = "bars"
        self._title = title; self._unit = unit
        self._groups = groups or []
        self._la = la; self._lb = lb
        self.update()

    def clear(self):
        self._sa = []; self._sb = []; self._xlabels = None; self._groups = []
        self.update()

    def _legend(self, p, W):
        f = p.font(); f.setBold(False); f.setPointSize(9); p.setFont(f)
        x = W - 12
        self._dot_hit = {}
        for which, label, col in (("cmp", self._lb, QColor(_cmp_col(getattr(self, "_cmp_gold", False)))),
                                  ("sel", self._la, QColor(_sel_col()))):
            tw = p.fontMetrics().horizontalAdvance(label)
            p.setPen(QColor("#dcdddf")); p.drawText(x - tw, 18, label)
            p.setBrush(col); p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(x - tw - 10, 14), 5, 5)
            self._dot_hit[which] = QRectF(x - tw - 18, 4, tw + 24, 20)  # dot+label cliccabile
            x -= tw + 26

    def _paint_bars(self, p, W, H):
        groups = [(l, a, b) for (l, a, b) in self._groups if a is not None or b is not None]
        if not groups:
            p.setPen(QColor("#60636c"))
            p.drawText(self.rect(), Qt.AlignCenter, "select a row")
            return
        ml, mr, mt, mb = 50, 14, 34, 28
        gw, gh = W - ml - mr, H - mt - mb
        allv = [v for _, a, b in groups for v in (a, b) if v is not None]
        vmax = max(allv + [0.0]); vmin = min(allv + [0.0])
        if vmax == vmin:
            vmax = vmin + 1.0
        pad = (vmax - vmin) * 0.12
        vmax += pad
        if vmin < 0:
            vmin -= pad

        def Y(v):
            return mt + gh * (1 - (v - vmin) / (vmax - vmin))

        f = p.font(); f.setBold(False); f.setPointSize(8); p.setFont(f)
        for i in range(5):
            yy = int(mt + gh * i / 4)
            p.setPen(QPen(QColor("#313d5a"), 1)); p.drawLine(ml, yy, W - mr, yy)
            val = vmax - (vmax - vmin) * i / 4
            p.setPen(QColor("#9fb0c8")); p.drawText(6, yy + 4, f"{val:.0f}")
        p.setPen(QColor("#9fb0c8")); p.drawText(6, mt - 8, self._unit)
        n = len(groups)
        slot = gw / n
        barw = min(34.0, slot * 0.32)
        for i, (lab, a, b) in enumerate(groups):
            cx = ml + slot * (i + 0.5)
            for j, (val, col) in enumerate(((a, QColor(_sel_col())), (b, QColor(_cmp_col(getattr(self, "_cmp_gold", False)))))):
                if val is None:
                    continue
                bx = cx + (j - 1) * (barw + 3) + 1.5
                top = Y(max(val, 0.0)); bot = Y(min(val, 0.0))
                p.setBrush(col); p.setPen(Qt.NoPen)
                p.drawRect(QRectF(bx, top, barw, max(1.0, bot - top)))
                p.setPen(QColor("#dcdddf"))
                txt = f"{val:.0f}" if abs(val) >= 10 else f"{val:.1f}"
                tw = p.fontMetrics().horizontalAdvance(txt)
                p.drawText(QPointF(bx + barw / 2 - tw / 2, top - 4), txt)
                p.setPen(Qt.NoPen)
            p.setPen(QColor("#989ba2"))
            tw = p.fontMetrics().horizontalAdvance(lab)
            p.drawText(QPointF(cx - tw / 2, H - 9), lab)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(9, 13, 20, 150))
        W, H = self.width(), self.height()
        f = p.font(); f.setBold(True); f.setPointSize(10); p.setFont(f)
        p.setPen(QColor("#f2f2f3")); p.drawText(12, 18, self._title)
        self._legend(p, W)
        if self._mode == "bars":
            self._paint_bars(p, W, H); p.end(); return
        pts = self._sa + self._sb
        if not pts:
            p.setPen(QColor("#60636c"))
            p.drawText(self.rect(), Qt.AlignCenter, "select a row")
            p.end(); return
        points_mode = self._xlabels is not None
        xmin = min(x for x, _ in pts); xmax = max(x for x, _ in pts)
        ymin = min(y for _, y in pts); ymax = max(y for _, y in pts)
        if xmax <= xmin:
            xmin -= 0.5; xmax += 0.5
        if ymax <= ymin:
            ymax = ymin + 1.0
        pad = (ymax - ymin) * 0.15
        ymax += pad; ymin -= pad
        ml, mr, mt = 50, 14, 34
        mb = 30 if points_mode else 20
        gw, gh = W - ml - mr, H - mt - mb

        def X(x):
            return ml + gw * (x - xmin) / (xmax - xmin)

        def Y(y):
            return mt + gh * (1 - (y - ymin) / (ymax - ymin))

        f.setBold(False); f.setPointSize(8); p.setFont(f)
        for i in range(5):
            yy = int(mt + gh * i / 4)
            p.setPen(QPen(QColor("#313d5a"), 1)); p.drawLine(ml, yy, W - mr, yy)
            val = ymax - (ymax - ymin) * i / 4
            p.setPen(QColor("#9fb0c8")); p.drawText(6, yy + 4, f"{val:.0f}")
        p.setPen(QColor("#9fb0c8")); p.drawText(6, mt - 8, self._unit)
        if ymin < 0 < ymax:
            y0 = int(Y(0.0))
            p.setPen(QPen(QColor("#5d6c94"), 1)); p.drawLine(ml, y0, W - mr, y0)

        for series, col in ((self._sa, QColor(_sel_col())), (self._sb, QColor(_cmp_col(getattr(self, "_cmp_gold", False))))):
            if not series:
                continue
            poly = QPolygonF([QPointF(X(x), Y(y)) for x, y in series])
            p.setPen(QPen(col, 2)); p.setBrush(Qt.NoBrush)
            p.drawPolyline(poly)
            if points_mode:
                p.setBrush(col); p.setPen(Qt.NoPen)
                for x, y in series:
                    p.drawEllipse(QPointF(X(x), Y(y)), 3.2, 3.2)
                    txt = f"{y:.1f}" if abs(y) >= 10 else f"{y:.2f}"
                    p.setPen(QColor("#dcdddf"))
                    p.drawText(QPointF(X(x) + 5, Y(y) - 5), txt)
                    p.setPen(Qt.NoPen)
        if points_mode:
            p.setPen(QColor("#989ba2"))
            for i, lab in enumerate(self._xlabels):
                tw = p.fontMetrics().horizontalAdvance(lab)
                p.drawText(QPointF(X(i) - tw / 2, H - 10), lab)
        p.end()


class _PedalChart(QWidget):
    """Tracce pedali (throttle verde / brake rosso) vs distanza.
    Selected pieno, Compare tratteggiato. Throttle/brake attesi in 0..1."""
    _THR = "#37d67a"
    _BRK = "#ff5b5b"

    def __init__(self, scrub_cb=None):
        super().__init__()
        self.setAttribute(Qt.WA_TranslucentBackground, True)  # radiale traspare
        self._sel = []      # [(lapdist, throttle, brake)]
        self._cmp = []
        self._sec_dist = []
        self._cursor = None     # lapdist del cursore scrub (review)
        self._la = "Selected"
        self._lb = "Compare"
        self._la_time = None; self._lb_time = None
        self._la_secs = []; self._lb_secs = []
        self._best_time = None; self._best_secs = []
        self._scrub_cb = scrub_cb
        self._xmap = None       # (ml, gw, xmin, xmax) per invertire il mouse->lapdist
        self._view = None       # (vx0, vx1) finestra di zoom; None = tutto il giro
        self._pan = None        # (mouse_x, vx0, vx1) durante il pan col tasto destro
        self.setMinimumHeight(150)
        if scrub_cb is not None:
            self.setMouseTracking(True)
            self.setCursor(Qt.CrossCursor)

    def set_laps(self, sel, cmp, la="Selected", lb="Compare", sec_dist=None,
                 la_time=None, lb_time=None, la_secs=None, lb_secs=None,
                 best_time=None, best_secs=None):
        self._sel = sel or []
        self._cmp = cmp or []
        self._sec_dist = [d for d in (sec_dist or []) if d]
        self._la = la; self._lb = lb
        self._la_time = la_time; self._lb_time = lb_time
        self._la_secs = la_secs or []; self._lb_secs = lb_secs or []
        self._best_time = best_time; self._best_secs = best_secs or []
        self.update()

    def set_live(self, pts, sec_dist=None):
        """Live: una sola traccia (giro corrente)."""
        self._sel = pts or []
        self._cmp = []
        self._sec_dist = [d for d in (sec_dist or []) if d]
        self._la = "Lap"; self._lb = ""
        self.update()

    def set_cursor(self, lapdist):
        self._cursor = lapdist
        self.update()

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(9, 13, 20, 150))
        W, H = self.width(), self.height()
        ml, mr, mt, mb = 40, 14, 26, 22
        gw, gh = W - ml - mr, H - mt - mb
        f = p.font(); f.setPointSize(8); p.setFont(f)
        allpts = self._sel + self._cmp
        if len(allpts) < 2:
            p.setPen(QColor("#60636c"))
            p.drawText(self.rect(), Qt.AlignCenter, "select/record a lap")
            p.end(); return
        xs = [pt[0] for pt in allpts]
        xmin, xmax = min(xs), max(xs)
        if xmax <= xmin:
            xmax = xmin + 1.0
        self._data_x = (xmin, xmax)
        if self._view is not None:
            v0, v1 = self._view
            xmin = max(xmin, v0); xmax = min(xmax, v1)
            if xmax <= xmin:
                xmax = xmin + 1.0

        def X(v):
            return ml + gw * (v - xmin) / (xmax - xmin)

        self._xmap = (ml, gw, xmin, xmax)

        def Y(pct):
            return mt + gh * (1.0 - max(0.0, min(1.0, pct)))

        for i in range(5):
            yy = int(mt + gh * i / 4)
            p.setPen(QPen(QColor("#313d5a"), 1)); p.drawLine(ml, yy, W - mr, yy)
            p.setPen(QColor("#9fb0c8")); p.drawText(6, yy + 4, f"{100 - i * 25}")
        p.setPen(QColor("#9fb0c8")); p.drawText(6, mt - 8, "%")

        # marker settori (come nello Speed) + etichette S1/S2/S3
        for d in self._sec_dist:
            if xmin <= d <= xmax:
                xx = int(X(d))
                p.setPen(QPen(QColor("#3a3d43"), 1, Qt.DashLine))
                p.drawLine(xx, mt, xx, mt + gh)
        bounds = [xmin] + list(self._sec_dist) + [xmax]
        p.setPen(QColor("#6d717b"))
        for i, lab in enumerate(("S1", "S2", "S3")):
            if i + 1 < len(bounds):
                cx = (bounds[i] + bounds[i + 1]) / 2.0
                if xmin <= cx <= xmax:
                    tw = p.fontMetrics().horizontalAdvance(lab)
                    p.drawText(QPointF(X(cx) - tw / 2, mt + 11), lab)
        # punti CURVA (T1, T2...): tick + label in basso, stessi della mappa
        _tm = getattr(self, "_turn_marks", [])
        if _tm:
            _ft = p.font(); _ft7 = p.font(); _ft7.setPointSize(7)
            p.setFont(_ft7)
            for _ld, _lab in _tm:
                if xmin <= _ld <= xmax:
                    xx = X(_ld)
                    p.setPen(QPen(QColor(255, 255, 255, 45), 1))
                    p.drawLine(int(xx), mt + gh - 7, int(xx), mt + gh)
                    _twl = p.fontMetrics().horizontalAdvance(_lab)
                    p.setPen(QColor("#8a90a0"))
                    p.drawText(QPointF(xx - _twl / 2.0, mt + gh - 9), _lab)
            p.setFont(_ft)
        f2 = p.font(); f2.setPointSize(7); p.setFont(f2)
        _draw_sector_times(p, X, bounds, self._la_secs, self._lb_secs, self._best_secs, xmin, xmax, mt + 22)
        p.setFont(f)

        def draw(pts, dashed):
            if len(pts) < 2:
                return
            for ch, col in ((1, self._THR), (2, self._BRK)):
                pen = QPen(QColor(col), 2)
                if dashed:
                    pen.setStyle(Qt.DashLine); pen.setWidthF(1.4)
                p.setPen(pen); p.setBrush(Qt.NoBrush)
                poly = QPolygonF([QPointF(X(pt[0]), Y(pt[ch] or 0.0)) for pt in pts])
                p.drawPolyline(poly)

        p.save(); p.setClipRect(QRectF(ml, mt, gw, gh))
        draw(self._cmp, True)
        draw(self._sel, False)
        p.restore()

        # legend giri: linea + 'Lap N' + tempo (più veloce in fuxia), in alto a sx
        cs = _best_color(self._la_time, self._best_time)
        cc = _best_color(self._lb_time, self._best_time)
        items = []
        if self._sel:
            items.append((False, self._la, _fmt(self._la_time) if self._la_time else "", cs))
        if self._cmp and self._lb:
            items.append((True, self._lb, _fmt(self._lb_time) if self._lb_time else "", cc))
        _draw_lap_legend(p, ml + 2, mt - 14, items)

        # cursore scrub (review): linea verticale + valori al punto
        if self._cursor is not None and xmin <= self._cursor <= xmax:
            xx = X(self._cursor)
            p.setPen(QPen(QColor("#f5f5f5"), 1))
            p.drawLine(int(xx), mt, int(xx), mt + gh)
            if self._sel:
                near = min(self._sel, key=lambda pt: abs(pt[0] - self._cursor))
                thr = (near[1] or 0.0) * 100; brk = (near[2] or 0.0) * 100
                p.setPen(QColor(self._THR)); p.drawText(QPointF(xx + 4, mt + 12), f"T {thr:.0f}%")
                p.setPen(QColor(self._BRK)); p.drawText(QPointF(xx + 4, mt + 26), f"B {brk:.0f}%")

        # legenda
        items = [("Brake", self._BRK), ("Throttle", self._THR)]
        x = W - 14
        for label, col in reversed(items):
            tw = p.fontMetrics().horizontalAdvance(label)
            p.setPen(QColor("#dcdddf")); p.drawText(x - tw, 16, label)
            p.setBrush(QColor(col)); p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(x - tw - 9, 12), 4, 4)
            x -= tw + 24
        p.end()

    # ── scrub sul grafico (review): muovi il cursore qui, la mappa segue ──
    def _ld_at(self, mx):
        if not self._xmap:
            return None
        ml, gw, xmin, xmax = self._xmap
        if gw <= 0:
            return None
        frac = max(0.0, min(1.0, (mx - ml) / gw))
        return xmin + frac * (xmax - xmin)

    def _do_scrub(self, pos):
        if self._scrub_cb is None:
            return
        ld = self._ld_at(pos.x())
        if ld is None:
            return
        self.set_cursor(ld)
        self._scrub_cb(ld)

    def wheelEvent(self, e):
        if self._scrub_cb is None or not getattr(self, "_data_x", None):
            return
        dmin, dmax = self._data_x
        v0, v1 = self._view if self._view else (dmin, dmax)
        span = v1 - v0
        if span <= 0:
            return
        ld = self._ld_at(e.position().x())
        if ld is None:
            ld = (v0 + v1) / 2.0
        factor = 0.82 if e.angleDelta().y() > 0 else 1.0 / 0.82
        nspan = max((dmax - dmin) * 0.04, min(dmax - dmin, span * factor))
        frac = (ld - v0) / span
        n0 = ld - frac * nspan
        n1 = n0 + nspan
        if n0 < dmin: n0 = dmin; n1 = n0 + nspan
        if n1 > dmax: n1 = dmax; n0 = n1 - nspan
        self._view = None if nspan >= (dmax - dmin) - 1e-6 else (max(dmin, n0), min(dmax, n1))
        self.update()

    def mouseMoveEvent(self, e):
        if self._pan is not None:
            mx0, v0, v1 = self._pan
            ml, gw, _, _ = self._xmap or (40, max(1, self.width() - 54), 0, 1)
            dmin, dmax = self._data_x
            span = v1 - v0
            dx = (e.position().x() - mx0) / max(1, gw) * span
            n0 = v0 - dx; n1 = v1 - dx
            if n0 < dmin: n0 = dmin; n1 = n0 + span
            if n1 > dmax: n1 = dmax; n0 = n1 - span
            self._view = (n0, n1)
            self.update()
        else:
            self._do_scrub(e.position())
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton and self._view is not None:
            self._pan = (e.position().x(), self._view[0], self._view[1])
        else:
            self._do_scrub(e.position())
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._pan = None
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        self._view = None
        self.update()
        super().mouseDoubleClickEvent(e)


class _FitTable(QTableWidget):
    """Tabella che chiede esattamente l'altezza del suo contenuto: niente scroll,
    così il grafico sotto resta sempre completamente visibile."""
    def _content_h(self):
        h = self.horizontalHeader().height() + self.frameWidth() * 2 + 2
        for r in range(self.rowCount()):
            h += self.rowHeight(r)
        return h

    def sizeHint(self):
        return QSize(super().sizeHint().width(), self._content_h())

    def minimumSizeHint(self):
        return QSize(super().minimumSizeHint().width(), self._content_h())


def _load_track_svg(track):
    """Carica gli STESSI SVG del widget mappa (settings/trackmap): coordinate reali
    mPos (z negata) + indici settore in <desc>. -> (path[(x,z)], secs)."""
    import re
    from pathlib import Path
    if not track:
        return None, []
    base = Path(__file__).resolve().parent.parent / "settings" / "trackmap"
    if not base.exists():
        return None, []
    f = None
    for sv in base.glob("*.svg"):
        name = re.sub(r"#U([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), sv.stem)
        if name == track:
            f = sv; break
    if f is None:
        return None, []
    try:
        txt = f.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r'points="([^"]+)"', txt)
        if not m:
            return None, []
        path = []
        for tok in m.group(1).split():
            if "," in tok:
                a, b = tok.split(",")[:2]
                path.append((float(a), -float(b)))   # z invertita come TinyPedal
        secs = []
        dm = re.search(r"<desc>([\d,\s]+)</desc>", txt)
        if dm:
            secs = [int(x) for x in re.findall(r"\d+", dm.group(1))][:2]
        return (path if len(path) > 10 else None), secs
    except Exception:
        return None, []


class _LiveMap(QWidget):
    """Mini-mappa col tracciato SVG vero (settings/trackmap). Marker posizione
    (live) o scrub (review): muovendo il mouse evidenzia il punto -> scrub_cb(lapdist)."""
    def __init__(self, scrub_cb=None):
        super().__init__()
        self.setAttribute(Qt.WA_TranslucentBackground, True)  # radiale traspare
        self._outline = []      # [(x, z)] tracciato disegnato (SVG preferito)
        self._secs = []         # indici confine settore in _outline
        self._scrub_pts = []    # [(x, z, lapdist)] campioni registrati (review)
        self._marker = None     # (x, z) posizione live
        self._hi = None         # punto evidenziato (scrub)
        self._scrub_cb = scrub_cb
        self._track = ""
        self._drv_col = None     # QColor anello classe del pilota
        self._drv_num = ""       # numero mostrato nel dot
        # ── review/confronto ──
        self._review = False
        self._cmp_pts = []       # [(x,z,lapdist)] traiettoria giro Compare
        self._cur_ld = None      # lapdist corrente dello scrub
        self._la = "Selected"
        self._lb = "Compare"
        self._cmp_gold = False   # Compare = REF -> dot/traiettoria oro
        self._dot_hit = {}       # {"sel"/"cmp": QRectF} legend cliccabile
        self.color_cb = None     # callback(which) per il pick-color
        self._gps = True         # vista GPS (centrata+ruotata) come il widget
        self._zoom_mult = 1.0    # zoom rotella
        self._pan_off = [0.0, 0.0]   # pan tasto destro (px schermo)
        self._pan_start = None       # (pos mouse, pan alla pressione)
        # tastino LOCALIZZA: ricentra pan+zoom se ti perdi
        from PySide6.QtWidgets import QPushButton
        self._locate = QPushButton("my_location", self)
        self._locate.setCursor(Qt.PointingHandCursor)
        self._locate.setFixedSize(28, 28)
        self._locate.setToolTip("Recenter map")
        self._locate.setStyleSheet(
            "QPushButton{font-family:'Material Symbols Rounded';font-size:17px;"
            "color:#ffffff;background:rgba(255,255,255,0.10);border:none;"
            "border-radius:14px;}"
            "QPushButton:hover{background:rgba(255,29,67,0.55);}")
        self._locate.clicked.connect(self._recenter)
        self._locate.raise_()
        self.setMinimumHeight(240)     # mappa piu' GRANDE (rich. 23/07)
        self.setMinimumWidth(120)
        if scrub_cb is not None:
            self.setMouseTracking(True)
            self.setCursor(Qt.CrossCursor)

    def _zoom_step(self, factor):
        self._zoom_mult = max(0.5, min(12.0, self._zoom_mult * factor))
        self.update()

    def set_svg(self, track):
        """Carica l'outline SVG vero per la pista (se disponibile)."""
        track = track or ""
        if track == self._track:
            return
        self._track = track
        path, secs = _load_track_svg(track)
        if path and len(path) > 10:
            self._outline = list(path)
            self._secs = list(secs)
        else:
            self._outline = []   # niente SVG: si usa il path registrato
            self._secs = []
        self.update()

    def _turns(self):
        """[(indice outline, 'Tn')] — curve rilevate dalla CURVATURA dello SVG,
        numerate dalla partenza (inizio outline = start/finish). Cache per pista."""
        key = (id(self._outline), len(self._outline))
        if getattr(self, "_turns_key", None) == key:
            return self._turns_cache
        out = []
        ol = self._outline
        n = len(ol)
        if n > 20:
            hd = []
            for i in range(n):
                a = ol[i]; b = ol[(i + 1) % n]
                hd.append(math.atan2(b[1] - a[1], b[0] - a[0]))
            dh = []
            for i in range(n):
                d = hd[(i + 1) % n] - hd[i]
                while d > math.pi:
                    d -= 2 * math.pi
                while d < -math.pi:
                    d += 2 * math.pi
                dh.append(d)
            sm = [(dh[i - 1] + dh[i] + dh[(i + 1) % n]) / 3.0 for i in range(n)]
            TH = math.radians(2.5)       # curvatura minima per "sto girando"

            def _detect(minang):
                # spezza il tratto quando la curvatura CAMBIA SEGNO: le
                # chicane (dx-sx) contano come due curve, come nella realta'
                i = 0; turns = []
                while i < n:
                    if abs(sm[i]) > TH:
                        j = i; tot = 0.0; apex = i; mx = 0.0
                        sgn0 = 1.0 if sm[i] > 0 else -1.0
                        while (j < n and abs(sm[j]) > TH * 0.6
                               and (sm[j] * sgn0) > 0):
                            tot += sm[j]
                            if abs(sm[j]) > mx:
                                mx = abs(sm[j]); apex = j
                            j += 1
                        if abs(tot) > minang:
                            turns.append(apex)
                        i = j if j > i else i + 1
                    else:
                        i += 1
                return turns

            # numero curve UFFICIALE (data/track_info, dalla carta evento):
            # calibra la soglia finche' il conteggio combacia (o ci va vicino)
            official = None
            try:
                from data.tracks import _track_logo_stem
                from data.track_info import track_info as _ti
                _stem = _track_logo_stem(self._track)
                _info = _ti((_stem or "").lower())
                if _info:
                    official = int(_info[1])
            except Exception:
                official = None
            best = None
            if official:
                for deg in range(40, 5, -1):          # 40 -> 6 gradi
                    t = _detect(math.radians(deg))
                    d = abs(len(t) - official)
                    if best is None or d < best[0]:
                        best = (d, t)
                    if d == 0:
                        break
            turns = best[1] if best else _detect(math.radians(28.0))
            out = [(idx, "T%d" % (k + 1)) for k, idx in enumerate(turns)]
        self._turns_key = key
        self._turns_cache = out
        return out

    def _recenter(self):
        """Ricentra la mappa (pan azzerato, zoom base)."""
        self._pan_off = [0.0, 0.0]
        self._zoom_mult = 1.0
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        try:
            self._locate.move(self.width() - self._locate.width() - 8,
                              self.height() - self._locate.height() - 8)
        except Exception:
            pass

    def turns_lapdist(self):
        """[(lapdist_m, 'Tn')] — distanza delle curve lungo l'outline SVG
        (coordinate reali in metri, start = linea del traguardo)."""
        ts = self._turns()
        ol = self._outline
        if not ts or len(ol) < 2:
            return []
        cum = [0.0]
        for i in range(1, len(ol)):
            a, b = ol[i - 1], ol[i]
            cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        # l'outline (corda della polyline) e' ~5% piu' corto del giro vero:
        # scala sulla lunghezza UFFICIALE cosi' i marker non slittano a fine giro
        k = 1.0
        try:
            from data.tracks import _track_logo_stem
            from data.track_info import track_info as _ti
            _info = _ti((_track_logo_stem(self._track) or "").lower())
            if _info and cum[-1] > 0:
                k = float(_info[0]) / cum[-1]
        except Exception:
            k = 1.0
        return [(cum[i] * k, lab) for i, lab in ts if i < len(ol)]

    def set_scrub_pts(self, pts):
        self._scrub_pts = pts or []
        self._hi = None
        self.update()

    def set_path(self, pts):
        """Fallback outline da posizioni registrate/accumulate (se manca lo SVG)."""
        if not self._outline:
            self._fallback = pts or []
        else:
            self._fallback = []
        self.update()

    def set_marker(self, xz):
        """Marker live ANIMATO: i campioni posizione arrivano a raffiche
        (~0.5s di buco) e il dot saltava; qui insegue il target con un
        ease a 30fps, cosi' il movimento e' fluido anche in acquisizione."""
        self._marker = xz
        if xz is None:
            self._mk_pos = None
            try:
                self._mk_timer.stop()
            except Exception:
                pass
            self.update()
            return
        if getattr(self, "_mk_timer", None) is None:
            from PySide6.QtCore import QTimer as _QT
            self._mk_timer = _QT(self)
            self._mk_timer.setInterval(33)
            self._mk_timer.timeout.connect(self._mk_step)
        if getattr(self, "_mk_pos", None) is None:
            self._mk_pos = (xz[0], xz[1])
        if not self._mk_timer.isActive():
            self._mk_timer.start()

    def _mk_step(self):
        t = self._marker
        if t is None or self._mk_pos is None:
            self._mk_timer.stop()
            return
        px, pz = self._mk_pos
        dx = t[0] - px; dz = t[1] - pz
        d2 = dx * dx + dz * dz
        if d2 > 100.0 ** 2:                 # teleport (reset/giro nuovo): snap
            self._mk_pos = (t[0], t[1])
        elif d2 < 0.01:                     # arrivato
            self._mk_pos = (t[0], t[1])
            self._mk_timer.stop()
        else:
            # ease esponenziale: raggiunge il target in ~mezzo secondo,
            # il passo del campionamento a raffiche del recorder
            self._mk_pos = (px + dx * 0.18, pz + dz * 0.18)
        self.update()

    def set_driver(self, cls_tag, num):
        """Colore classe + numero del pilota per disegnare il dot stile widget."""
        self._drv_col = QColor(_CLASS_COL.get(cls_tag or "", "#a7aaaf"))
        self._drv_num = str(num or "")
        self.update()

    def _off_track_segs(self, pts):
        """Segmenti della traiettoria LONTANI dal tracciato (>12m dalla
        centerline SVG) = corsia PIT percorsa. Calcolato una volta a giro."""
        if not pts or len(self._outline) < 10:
            return []
        ol = self._outline[::max(1, len(self._outline) // 220)]
        segs = []; cur = []
        for q in pts:
            x, z = q[0], q[1]
            dmin = min((x - a) * (x - a) + (z - b) * (z - b) for a, b in ol)
            if dmin > 144.0:                 # oltre 12 m: sei in pit lane
                cur.append((x, z))
            else:
                if len(cur) >= 5:
                    segs.append(cur)
                cur = []
        if len(cur) >= 5:
            segs.append(cur)
        return segs

    def set_review(self, sel_pts, cmp_pts, la="Selected", lb="Compare"):
        """Modalità confronto: due traiettorie + due dot (colori _SEL_COL/_CMP_COL)."""
        self._review = True
        self._scrub_pts = sel_pts or []
        self._cmp_pts = cmp_pts or []
        # viste ORDINATE per lapdist: servono ai dot INTERPOLATI (fluidi)
        self._sel_srt = sorted([(q[2], q[0], q[1]) for q in self._scrub_pts
                                if len(q) > 2 and q[2] is not None])
        self._cmp_srt = sorted([(q[2], q[0], q[1]) for q in self._cmp_pts
                                if len(q) > 2 and q[2] is not None])
        try:
            self._pit_segs = (self._off_track_segs(self._scrub_pts)
                              + self._off_track_segs(self._cmp_pts))
        except Exception:
            self._pit_segs = []
        self._la = la; self._lb = lb
        self._hi = None
        self.setMouseTracking(True)
        self.update()

    def set_hi_by_lapdist(self, ld):
        """Evidenzia il campione più vicino a una lapdist (entrambe le tracce)."""
        self._cur_ld = ld
        self._hi = self._nearest_ld(self._scrub_pts, ld)
        self.update()

    def set_play_pos(self, ld_a, ld_b, gap=None):
        """REPLAY: posizioni INDIPENDENTI dei due giri (il confronto sta dove
        lo porta il SUO tempo, non alla stessa lapdist). None = replay spento,
        si torna al cursore normale. gap = distacco in secondi alla
        posizione della macchinina (rich. 23/07): +dietro / -davanti."""
        self._play_ld = None if ld_a is None else (ld_a, ld_b)
        self._play_gap = gap
        self.update()

    def set_events(self, evts):
        """MARKER EVENTI sulla mappa (cantiere 23/07): [(kind, x, z)]
        con kind in contact|tl|lock — tabella events del recorder.
        Layer accendibili dalla legenda cliccabile."""
        self._events = evts or []
        if not hasattr(self, "_ev_show"):
            self._ev_show = {"contact": True, "tl": False,
                             "lock": True, "slide": True,
                             "tc": False, "abs": False, "lico": True}
        self.update()

    def set_event_segs(self, segs):
        """TRATTI di strada per tipo (rich. 23/07): dict
        {slide|tc|abs: [polilinea, ...]} — il pezzo di pista dove
        succede la cosa (scivolata / TC / ABS al lavoro)."""
        self._event_segs = segs or {}
        self.update()

    @staticmethod
    def _pos_at_ld(arr, ld):
        """(x, z) INTERPOLATO alla lapdist esatta (arr ordinato per ld).
        Il salto sul campione piu' vicino faceva scattare replay e scrub:
        tra due campioni (~0.5s di buco) il dot ora scorre sulla corda."""
        if not arr or ld is None:
            return None
        from bisect import bisect_left
        i = bisect_left(arr, (ld,))
        if i <= 0:
            return (arr[0][1], arr[0][2])
        if i >= len(arr):
            return (arr[-1][1], arr[-1][2])
        l1, x1, z1 = arr[i - 1]; l2, x2, z2 = arr[i]
        f = (ld - l1) / (l2 - l1) if l2 > l1 else 0.0
        return (x1 + (x2 - x1) * f, z1 + (z2 - z1) * f)

    @staticmethod
    def _nearest_ld(pts, ld):
        if ld is None or not pts:
            return None
        best = None; bd = 1e18
        for i, pt in enumerate(pts):
            if len(pt) > 2 and pt[2] is not None:
                dd = abs(pt[2] - ld)
                if dd < bd:
                    bd = dd; best = i
        return best

    def _draw_pts(self):
        if self._outline:
            return self._outline
        if getattr(self, "_fallback", None):
            return [(p[0], p[1]) for p in self._fallback]
        if self._scrub_pts:
            return [(p[0], p[1]) for p in self._scrub_pts]
        return []

    def _xform(self, pts):
        if len(pts) < 2:
            return None
        xs = [p[0] for p in pts]; zs = [p[1] for p in pts]
        xmin, xmax = min(xs), max(xs); zmin, zmax = min(zs), max(zs)
        sx = (xmax - xmin) or 1.0; sz = (zmax - zmin) or 1.0
        w, h = self.width(), self.height()
        m = 14
        scale = min((w - 2 * m) / sx, (h - 2 * m) / sz)
        ox = (w - sx * scale) / 2 - xmin * scale
        oz = (h - sz * scale) / 2 - zmin * scale
        return ox, oz, scale, h

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(9, 13, 20, 150))
        if self._review:
            self._paint_review(p)
        else:
            self._paint_live(p)
        p.end()

    @staticmethod
    def _cr_smooth(pts, step=5.0):
        """Catmull-Rom parametrizzata sul LAPDIST: il recorder campiona la
        posizione a raffiche (3-5 campioni poi ~0.5s di buco) e la polyline
        veniva a corde/zig-zag. Qui si ricostruisce una curva continua
        campionata ogni ~step metri. pts = [(x, z, lapdist)]."""
        if len(pts) < 4:
            return [(q[0], q[1]) for q in pts]
        P = [q for q in pts if q[2] is not None]
        P.sort(key=lambda q: q[2])
        D = []; last = None
        for q in P:
            if last is None or q[2] > last + 1e-6:
                D.append(q); last = q[2]
        if len(D) < 4:
            return [(q[0], q[1]) for q in D]
        out = [(D[0][0], D[0][1])]
        for i in range(len(D) - 1):
            p1 = D[i]; p2 = D[i + 1]
            p0 = D[i - 1] if i > 0 else p1
            p3 = D[i + 2] if i + 2 < len(D) else p2
            t0, t1, t2, t3 = p0[2], p1[2], p2[2], p3[2]
            dt = t2 - t1
            if dt <= 0:
                continue
            m1x = ((p2[0] - p0[0]) / (t2 - t0) if t2 > t0 else 0.0) * dt
            m1y = ((p2[1] - p0[1]) / (t2 - t0) if t2 > t0 else 0.0) * dt
            m2x = ((p3[0] - p1[0]) / (t3 - t1) if t3 > t1 else 0.0) * dt
            m2y = ((p3[1] - p1[1]) / (t3 - t1) if t3 > t1 else 0.0) * dt
            m = max(1, int(dt / step))
            for j in range(1, m + 1):
                t = j / float(m)
                h00 = 2 * t ** 3 - 3 * t ** 2 + 1
                h10 = t ** 3 - 2 * t ** 2 + t
                h01 = -2 * t ** 3 + 3 * t ** 2
                h11 = t ** 3 - t ** 2
                out.append((h00 * p1[0] + h10 * m1x + h01 * p2[0] + h11 * m2x,
                            h00 * p1[1] + h10 * m1y + h01 * p2[1] + h11 * m2y))
        return out

    # ── confronto (review): due traiettorie + due dot, vista GPS ──────────
    def _paint_review(self, p):
        sel = self._scrub_pts
        cmp = self._cmp_pts
        if len(sel) < 2:
            p.setPen(QColor("#60636c"))
            p.drawText(self.rect(), Qt.AlignCenter, "map\nwaiting")
            return
        _pl = getattr(self, "_play_ld", None)
        if _pl is not None:
            # REPLAY attivo: ogni giro alla SUA posizione (tempo reale)
            hi_sel = self._nearest_ld(sel, _pl[0])
            hi_cmp = self._nearest_ld(cmp, _pl[1]) \
                if (cmp and _pl[1] is not None) else None
        else:
            hi_sel = self._hi if self._hi is not None \
                else self._nearest_ld(sel, self._cur_ld)
            hi_cmp = self._nearest_ld(cmp, self._cur_ld) if cmp else None

        w, h = self.width(), self.height()
        allp = [(q[0], q[1]) for q in sel] + [(q[0], q[1]) for q in cmp]
        if self._outline:
            allp += [(q[0], q[1]) for q in self._outline]
        xs = [q[0] for q in allp]; zs = [q[1] for q in allp]
        sx = (max(xs) - min(xs)) or 1.0; sz = (max(zs) - min(zs)) or 1.0
        fit = min((w - 28) / sx, (h - 28) / sz)

        # posizioni INTERPOLATE dei due giri (dot fluidi + camera GPS fluida)
        _pl2 = getattr(self, "_play_ld", None)
        _ld_a = _pl2[0] if _pl2 is not None else self._cur_ld
        _ld_b = _pl2[1] if _pl2 is not None else self._cur_ld
        pa = self._pos_at_ld(getattr(self, "_sel_srt", None), _ld_a)
        pb = self._pos_at_ld(getattr(self, "_cmp_srt", None), _ld_b) \
            if cmp else None

        if self._gps:
            fi = hi_sel if hi_sel is not None else 0
            # camera sull'INTERPOLATO: ancorata al campione piu' vicino
            # scattava a ogni raffica del recorder
            if pa is not None:
                fx, fz = pa
            else:
                fx, fz = sel[fi][0], sel[fi][1]
            k = max(2, len(sel) // 80)
            a0 = sel[max(0, fi - k)]; a1 = sel[min(len(sel) - 1, fi + k)]
            _raw_ang = math.atan2(a1[1] - a0[1], a1[0] - a0[0])
            # rotazione LISCIATA (ease sull'angolo, con wrap ±pi): l'angolo
            # per campioni faceva ruotare la vista a scatti
            _prev = getattr(self, "_gps_ang", None)
            if _prev is None:
                ang = _raw_ang
            else:
                _d = (_raw_ang - _prev + math.pi) % (2 * math.pi) - math.pi
                ang = _prev + _d * 0.15
            self._gps_ang = ang
            zoom = fit * 6.0 * self._zoom_mult
            ca = math.cos(-ang + math.pi / 2.0); sa = math.sin(-ang + math.pi / 2.0)
            cx = w / 2.0 + self._pan_off[0]
            cy = h * 0.62 + self._pan_off[1]

            def P(x, z):
                u = (x - fx); v = (z - fz)
                ru = u * ca - v * sa; rv = u * sa + v * ca
                return QPointF(cx + ru * zoom, cy - rv * zoom)
        else:
            z = fit * self._zoom_mult
            cxm = (min(xs) + max(xs)) / 2.0
            czm = (min(zs) + max(zs)) / 2.0
            cx = w / 2.0 + self._pan_off[0]
            cy = h / 2.0 + self._pan_off[1]

            def P(x, z2=None, _z=z, _cx=cx, _cy=cy, _cxm=cxm, _czm=czm):
                return QPointF(_cx + (x - _cxm) * _z, _cy - (z2 - _czm) * _z)

        def _spath(pts):
            """QPainterPath morbido: quadratiche sui punti medi (niente faccette)."""
            qpts = [P(q[0], q[1]) for q in pts]
            path = QPainterPath(); path.moveTo(qpts[0])
            if len(qpts) == 2:
                path.lineTo(qpts[1])
            else:
                for i in range(1, len(qpts) - 1):
                    mid = QPointF((qpts[i].x() + qpts[i + 1].x()) / 2.0,
                                  (qpts[i].y() + qpts[i + 1].y()) / 2.0)
                    path.quadTo(qpts[i], mid)
                path.lineTo(qpts[-1])
            return path

        def line(pts, col, width):
            if len(pts) < 2:
                return
            p.setBrush(Qt.NoBrush)
            pen = QPen(col, width)
            pen.setJoinStyle(Qt.RoundJoin); pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen); p.drawPath(_spath(pts))

        sel_c = QColor(_sel_col()); cmp_c = QColor(_cmp_col(self._cmp_gold))
        trk_c = QColor(_common._TRK_COL)     # via modulo: segue il pick-color
        zm = self._zoom_mult
        trk_w = max(8.0, min(200.0, 17.0 * zm))
        ln_w = max(1.4, min(16.0, 2.2 * zm))
        # macchinine in SCALA VERA (rich. 23/07: in pista ci stanno 3
        # auto affiancate -> il simbolo e' 1/3 della carreggiata)
        dot_r = max(2.5, trk_w / 6.0)

        # pista larga (colore scuro pickabile) usando il giro Selected come tracciato
        # decima i punti SOLO per il disegno (cursore/dot usano i punti pieni)
        def _decim(pts, maxn=3000):
            n = len(pts)
            if n <= maxn:
                return pts
            st = n // maxn
            d = pts[::st]
            if d[-1] is not pts[-1]:
                d = d + [pts[-1]]
            return d
        # traiettorie LISCE: Catmull-Rom sul lapdist (regge i buchi delle
        # raffiche del recorder); raw restano per dot/scrub
        _full_sel = _decim(self._cr_smooth(sel))
        if _pl2 is not None:
            # REPLAY: la scia si disegna DA DIETRO — solo il percorso gia'
            # fatto fino al punto attuale, chiusa sul dot interpolato.
            # La traiettoria futura non si anticipa.
            _lda = _ld_a if _ld_a is not None else float("inf")
            _sf = [q for q in sel if q[2] is not None and q[2] <= _lda]
            if pa is not None and _ld_a is not None:
                _sf = _sf + [(pa[0], pa[1], _ld_a)]
            sel_draw = _decim(self._cr_smooth(_sf)) if len(_sf) >= 2 else []
            if cmp:
                _ldb = _ld_b if _ld_b is not None else float("inf")
                _cf = [q for q in cmp if q[2] is not None and q[2] <= _ldb]
                if pb is not None and _ld_b is not None:
                    _cf = _cf + [(pb[0], pb[1], _ld_b)]
                cmp_draw = _decim(self._cr_smooth(_cf)) if len(_cf) >= 2 else []
            else:
                cmp_draw = cmp
        else:
            sel_draw = _full_sel
            cmp_draw = _decim(self._cr_smooth(cmp)) if cmp else cmp

        # pista = SVG PRECISO se disponibile (stesso del widget Map),
        # altrimenti il giro Selected INTERO (l'asfalto non si accorcia
        # col replay, si accorcia solo la scia colorata)
        base = _spath(_decim(self._outline)) if self._outline \
            else _spath(_full_sel)
        p.setBrush(Qt.NoBrush)
        _bp = QPen(QColor(0, 0, 0, 180), trk_w + 5)
        _bp.setJoinStyle(Qt.RoundJoin); _bp.setCapStyle(Qt.RoundCap)
        p.setPen(_bp); p.drawPath(base)                                     # bordo
        _ap = QPen(trk_c, trk_w)
        _ap.setJoinStyle(Qt.RoundJoin); _ap.setCapStyle(Qt.RoundCap)
        p.setPen(_ap); p.drawPath(base)                                     # asfalto
        # corsia PIT: asfalto stretto sotto i tratti fuori tracciato.
        # SOLO tratti veri (>=4 punti e >=30 m): i micro-tratti di rumore,
        # col tratto largo a cap tonda, a zoom alto diventavano "cerchi"
        # fantasma sulla pista.
        for _seg in getattr(self, "_pit_segs", []) or []:
            if len(_seg) < 4:
                continue
            _Lm = 0.0
            for _i2 in range(1, len(_seg)):
                _Lm += math.hypot(_seg[_i2][0] - _seg[_i2 - 1][0],
                                  _seg[_i2][1] - _seg[_i2 - 1][1])
            if _Lm < 30.0:
                continue
            _pp2 = _spath(_seg)
            _pb = QPen(QColor(0, 0, 0, 160), trk_w * 0.55 + 4)
            _pb.setJoinStyle(Qt.RoundJoin); _pb.setCapStyle(Qt.RoundCap)
            p.setPen(_pb); p.drawPath(_pp2)
            _pa = QPen(trk_c, trk_w * 0.55)
            _pa.setJoinStyle(Qt.RoundJoin); _pa.setCapStyle(Qt.RoundCap)
            p.setPen(_pa); p.drawPath(_pp2)

        # ── linee SETTORE + numeri CURVA (solo con l'outline SVG) ──
        if self._outline:
            ol = self._outline

            def _scr(i):
                q = ol[i % len(ol)]
                return P(q[0], q[1])

            def _norm(i):
                a = _scr(i - 2); b = _scr(i + 2)
                dx, dy = b.x() - a.x(), b.y() - a.y()
                L = math.hypot(dx, dy) or 1.0
                return (-dy / L, dx / L)

            # CORDOLI bianco-rossi all'interno delle curve (finestra attorno
            # all'apice): bianco pieno sotto + rosso tratteggiato sopra
            _kw = max(3.0, ln_w * 1.6)
            for _ti_idx, _lab in self._turns():
                a = _scr(_ti_idx - 2); b = _scr(_ti_idx + 2); c0 = _scr(_ti_idx)
                if not (-60 <= c0.x() <= w + 60 and -60 <= c0.y() <= h + 60):
                    continue
                ux, uy = c0.x() - a.x(), c0.y() - a.y()
                vx, vy = b.x() - c0.x(), b.y() - c0.y()
                _cr = ux * vy - uy * vx
                _ins = 1.0 if _cr > 0 else -1.0        # lato INTERNO curva
                _off = trk_w / 2.0 + _kw / 2.0 + 1.0
                kpath = QPainterPath(); started = False
                for i in range(_ti_idx - 3, _ti_idx + 4):
                    cc = _scr(i)
                    nx, ny = _norm(i)
                    pt = QPointF(cc.x() + nx * _ins * _off,
                                 cc.y() + ny * _ins * _off)
                    if not started:
                        kpath.moveTo(pt); started = True
                    else:
                        kpath.lineTo(pt)
                p.setBrush(Qt.NoBrush)
                _kp = QPen(QColor(240, 240, 240, 235), _kw)
                _kp.setCapStyle(Qt.FlatCap)
                p.setPen(_kp); p.drawPath(kpath)        # base bianca
                _kr = QPen(QColor(224, 40, 60, 235), _kw)
                _kr.setCapStyle(Qt.FlatCap)
                _kr.setDashPattern([2.0, 2.0])          # strisce rosse
                p.setPen(_kr); p.drawPath(kpath)
            for si in (self._secs or []):
                if not (0 <= si < len(ol)):
                    continue
                nx, ny = _norm(si)
                c = _scr(si)
                hw = trk_w / 2.0 + 4.0
                _sp = QPen(QColor(255, 255, 255, 200), max(1.6, ln_w * 0.9))
                _sp.setCapStyle(Qt.FlatCap)
                p.setPen(_sp)
                p.drawLine(QPointF(c.x() - nx * hw, c.y() - ny * hw),
                           QPointF(c.x() + nx * hw, c.y() + ny * hw))
            # etichette S1/S2/S3 a meta' di ogni settore, fuori dal tracciato
            if self._secs:
                _sb = [0] + [si for si in self._secs if 0 <= si < len(ol)] \
                    + [len(ol) - 1]
                _sf = p.font(); _sf9 = p.font()
                _sf9.setPointSize(9); _sf9.setBold(True)
                p.setFont(_sf9)
                for si in range(min(3, len(_sb) - 1)):
                    mid = (_sb[si] + _sb[si + 1]) // 2
                    c = _scr(mid)
                    if not (-40 <= c.x() <= w + 40 and -40 <= c.y() <= h + 40):
                        continue
                    nx, ny = _norm(mid)
                    off = trk_w / 2.0 + 22.0
                    lab = "S%d" % (si + 1)
                    _tw = p.fontMetrics().horizontalAdvance(lab)
                    lx, ly = c.x() + nx * off, c.y() + ny * off
                    p.setPen(QColor(0, 0, 0, 210))
                    p.drawText(QPointF(lx - _tw / 2.0 + 1, ly + 4), lab)
                    p.setPen(QColor(255, 255, 255, 235))
                    p.drawText(QPointF(lx - _tw / 2.0, ly + 3), lab)
                p.setFont(_sf)
            _tf = p.font(); _tf.setPointSize(8); _tf.setBold(True)
            p.setFont(_tf)
            for idx, lab in self._turns():
                c = _scr(idx)
                if not (-40 <= c.x() <= w + 40 and -40 <= c.y() <= h + 40):
                    continue                      # fuori vista (zoom GPS)
                a = _scr(idx - 2); b = _scr(idx + 2)
                ux, uy = c.x() - a.x(), c.y() - a.y()
                vx, vy = b.x() - c.x(), b.y() - c.y()
                _cr = ux * vy - uy * vx           # senso della curva in schermo
                nx, ny = _norm(idx)
                sgn = -1.0 if _cr > 0 else 1.0    # etichetta ESTERNO curva
                off = trk_w / 2.0 + 13.0
                lx, ly = c.x() + nx * sgn * off, c.y() + ny * sgn * off
                _tw = p.fontMetrics().horizontalAdvance(lab)
                p.setPen(QColor(0, 0, 0, 210))
                p.drawText(QPointF(lx - _tw / 2.0 + 1, ly + 4), lab)
                p.setPen(QColor(230, 235, 245, 235))
                p.drawText(QPointF(lx - _tw / 2.0, ly + 3), lab)

        # traiettorie: linee colorate sopra la pista
        if cmp:
            line(cmp_draw, cmp_c, ln_w)
        line(sel_draw, sel_c, ln_w)

        def _mk_ang(srt, ld):
            """Angolo (schermo) della direzione di marcia alla lapdist ld."""
            if ld is None or not srt:
                return None
            a2 = self._pos_at_ld(srt, max(0.0, ld - 6.0))
            b2 = self._pos_at_ld(srt, ld + 6.0)
            if not a2 or not b2:
                return None
            qa = P(a2[0], a2[1]); qb = P(b2[0], b2[1])
            dx = qb.x() - qa.x(); dy = qb.y() - qa.y()
            if abs(dx) < 1e-6 and abs(dy) < 1e-6:
                return None
            return math.degrees(math.atan2(dy, dx))

        def dot(pt, col, ang=None):
            """Simbolo pilota: dot / freccia GPS / macchinina (scelta utente).
            Senza direzione nota si ripiega sul dot."""
            c = P(pt[0], pt[1])
            st = getattr(self, "_mk_style", "dot")
            p.setPen(QPen(QColor("#09090b"), 1.4)); p.setBrush(col)
            if st == "arrow" and ang is not None:
                L = dot_r * 2.1
                p.save(); p.translate(c); p.rotate(ang)
                path = QPainterPath()
                path.moveTo(L, 0)
                path.lineTo(-L * 0.8, L * 0.72)
                path.lineTo(-L * 0.35, 0)
                path.lineTo(-L * 0.8, -L * 0.72)
                path.closeSubpath()
                p.drawPath(path); p.restore()
            elif st == "car" and ang is not None:
                L = dot_r * 2.2; Wd = dot_r * 1.25
                p.save(); p.translate(c); p.rotate(ang)
                p.drawRoundedRect(QRectF(-L, -Wd, 2 * L, 2 * Wd),
                                  Wd * 0.75, Wd * 0.75)
                # abitacolo scuro verso il muso
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, 130))
                p.drawRoundedRect(QRectF(-L * 0.35, -Wd * 0.62,
                                         L * 0.85, Wd * 1.24),
                                  Wd * 0.4, Wd * 0.4)
                p.restore()
            else:
                p.drawEllipse(c, dot_r, dot_r)

        # ── MARKER EVENTI (contatti/tagli/bloccaggi): sotto i dot,
        # sopra le traiettorie — layer dalla legenda cliccabile ──
        _evs = getattr(self, "_events", None) or []
        _evshow = getattr(self, "_ev_show", None) or {}
        # TRATTI evento (slide/tc/abs) = pezzi di strada colorati
        _allsegs = getattr(self, "_event_segs", None) or {}
        # CORSIE PARALLELE stile cordolo (rich. 23/07): eventi
        # sovrapposti nello stesso punto -> ognuno sulla SUA striscia
        # affiancata alla traiettoria. Slide = sulla linea (e' la linea
        # che scivola), LICO fuori, TC dentro, ABS due fuori.
        _SEGC = {"slide": QColor(255, 138, 30, 220),
                 "tc": QColor(74, 144, 226, 200),
                 "abs": QColor(199, 125, 255, 210),
                 "lico": QColor(138, 63, 251, 205)}
        _LANE = {"slide": 0, "lico": 1, "tc": -1, "abs": 2}
        _segw = max(ln_w + 1.2, 3.0)
        for _sk, _ssegs in _allsegs.items():
            if not _ssegs or not _evshow.get(_sk):
                continue
            p.setPen(QPen(_SEGC.get(_sk, QColor(200, 200, 200, 160)),
                          _segw, Qt.SolidLine, Qt.RoundCap,
                          Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            _offl = _LANE.get(_sk, 0) * (_segw + 1.4)
            for _sg in _ssegs:
                if len(_sg) < 2:
                    continue
                _qs = [P(_x9, _z9) for _x9, _z9 in _sg]
                if _offl:
                    _qo = []
                    _nq = len(_qs)
                    for _i9 in range(_nq):
                        _a9 = _qs[max(0, _i9 - 1)]
                        _b9 = _qs[min(_nq - 1, _i9 + 1)]
                        _dx9 = _b9.x() - _a9.x()
                        _dy9 = _b9.y() - _a9.y()
                        _ln9 = (_dx9 * _dx9 + _dy9 * _dy9) ** 0.5
                        if _ln9 < 1e-6:
                            _qo.append(_qs[_i9])
                            continue
                        _qo.append(QPointF(
                            _qs[_i9].x() - _dy9 / _ln9 * _offl,
                            _qs[_i9].y() + _dx9 / _ln9 * _offl))
                    _qs = _qo
                _pth9 = QPainterPath()
                _pth9.moveTo(_qs[0])
                for _q9 in _qs[1:]:
                    _pth9.lineTo(_q9)
                p.drawPath(_pth9)
        if _evs:
            for _kind, _ex, _ez in _evs:
                if not _evshow.get(_kind):
                    continue
                c9 = P(_ex, _ez)
                if _kind == "contact":
                    p.setPen(QPen(QColor("#ff5a4d"), 2.0))
                    p.setBrush(Qt.NoBrush)
                    p.drawEllipse(c9, 5.0, 5.0)
                    p.drawLine(QPointF(c9.x() - 2.5, c9.y() - 2.5),
                               QPointF(c9.x() + 2.5, c9.y() + 2.5))
                    p.drawLine(QPointF(c9.x() - 2.5, c9.y() + 2.5),
                               QPointF(c9.x() + 2.5, c9.y() - 2.5))
                elif _kind == "tl":
                    from PySide6.QtGui import QPolygonF as _QPFe
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor("#ff9f2e"))
                    p.drawPolygon(_QPFe([
                        QPointF(c9.x(), c9.y() - 5.0),
                        QPointF(c9.x() - 4.5, c9.y() + 3.5),
                        QPointF(c9.x() + 4.5, c9.y() + 3.5)]))
                elif _kind == "lock":
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor("#ffe24d"))
                    p.drawEllipse(c9, 3.0, 3.0)
                else:                                   # slide: rombo viola
                    from PySide6.QtGui import QPolygonF as _QPFs
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor("#c77dff"))
                    p.drawPolygon(_QPFs([
                        QPointF(c9.x(), c9.y() - 4.5),
                        QPointF(c9.x() + 4.5, c9.y()),
                        QPointF(c9.x(), c9.y() + 4.5),
                        QPointF(c9.x() - 4.5, c9.y())]))

        # dot INTERPOLATI (pa/pb calcolati in alto); indice solo di riserva
        if pb is not None:
            dot(pb, cmp_c, _mk_ang(getattr(self, "_cmp_srt", None), _ld_b))
        elif hi_cmp is not None and 0 <= hi_cmp < len(cmp):
            dot(cmp[hi_cmp], cmp_c,
                _mk_ang(getattr(self, "_cmp_srt", None),
                        cmp[hi_cmp][2] if len(cmp[hi_cmp]) > 2 else None))
        if pa is not None:
            dot(pa, sel_c, _mk_ang(getattr(self, "_sel_srt", None), _ld_a))
            # DELTA accanto alla macchinina nel replay (cantiere 23/07):
            # +sei dietro il confronto / -sei davanti, alla stessa posizione
            _pg = getattr(self, "_play_gap", None)
            if _pg is not None and getattr(self, "_play_ld", None):
                c9 = P(pa[0], pa[1])
                f9 = p.font()
                f9.setBold(True)
                f9.setPointSize(9)
                p.setFont(f9)
                _gt = "%+.2f" % _pg
                p.setPen(QColor(0, 0, 0, 220))
                p.drawText(QPointF(c9.x() + 13.0, c9.y() - 9.0), _gt)
                p.setPen(QColor("#ff5a4d") if _pg > 0.02
                         else QColor("#37d67a") if _pg < -0.02
                         else QColor(235, 238, 245))
                p.drawText(QPointF(c9.x() + 12.0, c9.y() - 10.0), _gt)
        elif hi_sel is not None and 0 <= hi_sel < len(sel):
            dot(sel[hi_sel], sel_c,
                _mk_ang(getattr(self, "_sel_srt", None),
                        sel[hi_sel][2] if len(sel[hi_sel]) > 2 else None))

        # legend cliccabile in alto a SINISTRA (pick-color).
        # anello tratteggiato = linea tratteggiata nel grafico (Compare),
        # anello continuo = linea piena (Selected); Track = dot pieno.
        self._dot_hit = {}
        f = p.font(); f.setBold(False); f.setPointSize(8); p.setFont(f)
        x = 12
        items = [("sel", self._la, sel_c)]
        if cmp:
            items.append(("cmp", self._lb, cmp_c))
        items.append(("track", "Track", trk_c))
        # ── LEGENDA EVENTI cliccabile (cantiere 23/07): chip che
        # accendono/spengono i layer contatti/tagli/bloccaggi ──
        self._ev_hit = {}
        _evs9 = getattr(self, "_events", None) or []
        _segd9 = getattr(self, "_event_segs", None) or {}
        _nseg9 = sum(len(v) for v in _segd9.values())
        if _evs9 or _nseg9:
            _evshow9 = getattr(self, "_ev_show", None) or {}
            _cnt9 = {k: len(v) for k, v in _segd9.items()}
            for _k9, _x9, _z9 in _evs9:
                _cnt9[_k9] = _cnt9.get(_k9, 0) + 1
            # etichette in INGLESE (l'app e' EN) — rich. 23/07;
            # verticale dall'ALTO a scendere, sotto la legenda giri
            _EVL = (("contact", "Contacts", "#ff5a4d"),
                    ("tl", "Cuts", "#ff9f2e"),
                    ("lock", "Lock-ups", "#ffe24d"),
                    ("slide", "Slides", "#ff8a1e"),
                    ("tc", "TC", "#4a90e2"),
                    ("abs", "ABS", "#c77dff"),
                    ("lico", "LICO", "#8a3ffb"))
            _ex9 = 12.0
            _ey9 = 34.0
            f9l = p.font()
            f9l.setBold(False)
            f9l.setPointSize(8)
            p.setFont(f9l)
            for _k9, _lab9, _col9 in _EVL:
                # chip SEMPRE visibili, con lo zero smorzato (23/07)
                _n9 = _cnt9.get(_k9, 0)
                _on9 = bool(_evshow9.get(_k9)) and _n9 > 0
                _txt9 = "%s %d" % (_lab9, _n9)
                _tw9 = p.fontMetrics().horizontalAdvance(_txt9)
                _rect9 = QRectF(_ex9, _ey9 - 4.0, 14.0 + _tw9 + 10.0,
                                18.0)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(20, 24, 32, 200 if _on9 else 120))
                p.drawRoundedRect(_rect9, 4, 4)
                p.setBrush(QColor(_col9) if _on9
                           else QColor(120, 126, 138, 140))
                p.drawEllipse(QPointF(_ex9 + 8.0, _ey9 + 5.0), 4.0, 4.0)
                p.setPen(QColor(235, 238, 245, 235 if _on9 else 120))
                p.drawText(QPointF(_ex9 + 16.0, _ey9 + 9.0), _txt9)
                if _n9 > 0:               # zero = non selezionabile
                    self._ev_hit[_k9] = _rect9
                _ey9 += 22.0
        for which, label, col in items:
            cxp, cyp = x + 6, 12
            p.setPen(QPen(QColor("#09090b"), 1)); p.setBrush(col)
            p.drawEllipse(QPointF(cxp, cyp), 5.5, 5.5)
            tw = p.fontMetrics().horizontalAdvance(label)
            p.setPen(QColor("#09090b")); p.drawText(QPointF(x + 15, 17), label)
            p.setPen(QColor("#f5f5f5")); p.drawText(QPointF(x + 14, 16), label)
            self._dot_hit[which] = QRectF(x - 2, 2, tw + 22, 20)
            x += tw + 30

    def _paint_live(self, p):
        pts = self._draw_pts()
        tf = self._xform(pts)
        if tf is None:
            p.setPen(QColor("#60636c"))
            p.drawText(self.rect(), Qt.AlignCenter, "map\nwaiting")
            return
        ox, oz, scale, h = tf

        def P(x, z):
            return QPointF(ox + x * scale, h - (oz + z * scale))

        # ── tracciato stile widget: alone nero + linea chiara, path chiuso ──
        path = QPainterPath()
        path.moveTo(P(*pts[0]))
        for x, z in pts[1:]:
            path.lineTo(P(x, z))
        path.closeSubpath()
        lw = 5.5
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 150), lw + 3.5)); p.drawPath(path)   # alone nero
        p.setPen(QPen(QColor("#f3f4f8"), lw)); p.drawPath(path)            # pista chiara

        # tacche settore (blu) + traguardo (rosso), come nel widget
        def _tick(i, color, length, width):
            n = len(pts)
            if n < 3:
                return
            i = max(1, min(i, n - 2))
            A = P(*pts[i - 1]); B = P(*pts[i + 1])
            dx, dy = B.x() - A.x(), B.y() - A.y()
            ln = (dx * dx + dy * dy) ** 0.5 or 1.0
            nx, ny = -dy / ln, dx / ln
            C = P(*pts[i]); half = length / 2.0
            p.setPen(QPen(color, width))
            p.drawLine(QPointF(C.x() - nx * half, C.y() - ny * half),
                       QPointF(C.x() + nx * half, C.y() + ny * half))

        if self._outline and len(self._secs) >= 2:
            for si in self._secs[:2]:
                _tick(si, QColor("#00aaff"), 11, 2.2)
        _tick(0, QColor("#ff3b30"), 13, 2.6)

        # ── dot pilota: bianco con anello classe (pulito) ──
        dot = None
        if self._hi is not None and 0 <= self._hi < len(self._scrub_pts):
            dot = P(self._scrub_pts[self._hi][0], self._scrub_pts[self._hi][1])
        elif self._marker is not None:
            _mp = getattr(self, "_mk_pos", None) or self._marker
            dot = P(_mp[0], _mp[1])
        if dot is not None:
            fill = QColor(_sel_col()) if _SEL_IS_BEST \
                else (self._drv_col or QColor(_common._SEL_COL))
            rr = 6.5
            p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 110))
            p.drawEllipse(QPointF(dot.x() + 1.2, dot.y() + 1.2), rr + 1.4, rr + 1.4)
            p.setPen(QPen(QColor("#ffffff"), 2.0)); p.setBrush(fill)
            p.drawEllipse(dot, rr, rr)

    def _nearest(self, pos):
        pts = self._scrub_pts
        if len(pts) < 2:
            return None
        tf = self._xform(self._draw_pts())
        if tf is None:
            return None
        ox, oz, scale, h = tf
        mx, my = pos.x(), pos.y()
        best = None; bd = 1e18
        for i, pt in enumerate(pts):
            sxp = ox + pt[0] * scale
            syp = h - (oz + pt[1] * scale)
            dd = (sxp - mx) ** 2 + (syp - my) ** 2
            if dd < bd:
                bd = dd; best = i
        return best

    def _scrub(self, pos):
        if self._scrub_cb is None:
            return
        i = self._nearest(pos)
        if i is None:
            return
        self._hi = i
        self.update()
        ld = self._scrub_pts[i][2] if len(self._scrub_pts[i]) > 2 else None
        self._scrub_cb(ld)

    def wheelEvent(self, e):
        if not self._review:
            return
        self._zoom_mult *= 1.25 if e.angleDelta().y() > 0 else 1.0 / 1.25
        self._zoom_mult = max(0.5, min(12.0, self._zoom_mult))
        self.update()
        e.accept()

    def mouseMoveEvent(self, e):
        if self._pan_start is not None:
            p0, off0 = self._pan_start
            d = e.position() - p0
            self._pan_off = [off0[0] + d.x(), off0[1] + d.y()]
            self.update()
            return
        if self._review and self.color_cb is not None:
            on = any(r.contains(e.position()) for r in self._dot_hit.values())
            self.setCursor(Qt.PointingHandCursor if on else Qt.ArrowCursor)
        self._scrub(e.position()); super().mouseMoveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            # pan libero col tasto destro
            self._pan_start = (e.position(), tuple(self._pan_off))
            self.setCursor(Qt.ClosedHandCursor)
            return
        # legenda EVENTI: click sul chip accende/spegne il layer
        for _k9, rect in (getattr(self, "_ev_hit", None) or {}).items():
            if rect.contains(e.position()):
                _sh = getattr(self, "_ev_show", None) or {}
                _sh[_k9] = not _sh.get(_k9)
                self._ev_show = _sh
                self.update()
                return
        if self._review and self.color_cb is not None:
            for which, rect in self._dot_hit.items():
                if rect.contains(e.position()):
                    self.color_cb(which); return
        self._scrub(e.position()); super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.RightButton and self._pan_start is not None:
            self._pan_start = None
            self.setCursor(Qt.CrossCursor if self._scrub_cb else Qt.ArrowCursor)
            return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.RightButton:
            self._pan_off = [0.0, 0.0]      # doppio destro: ricentra
            self.update()
            return
        super().mouseDoubleClickEvent(e)


class _TraceChart(QWidget):
    """Traccia di una singola metrica vs distanza giro. Selected pieno,
    Compare tratteggiato. Scrub (cursore), zoom rotella, pan tasto destro,
    doppio click reset. Legend cliccabile -> pick-color."""
    def __init__(self, scrub_cb=None):
        super().__init__()
        self.setAttribute(Qt.WA_TranslucentBackground, True)  # radiale traspare
        self._sel = []      # [(lapdist, val)]
        self._cmp = []
        self._sec_dist = []
        self._cursor = None
        self._cur_a = None; self._cur_b = None   # cursori A/B (shift-click)
        self._ab_cb = None                        # callback per sincronizzare A/B (1b)
        self._zoom_cb = None                      # callback per sincronizzare lo zoom (1b)
        self._cmp_gold = False                    # Compare = REF -> linea/legenda oro
        self._la = "Selected"; self._lb = "Compare"
        self._unit = ""
        self._la_time = None; self._lb_time = None
        self._la_secs = []; self._lb_secs = []
        self._best_time = None; self._best_secs = []
        self._scrub_cb = scrub_cb
        self._xmap = None
        self.baseline = None          # se valorizzata, disegna una linea di riferimento (es. 0)
        self.yfmt = "{:.0f}"          # formato etichette asse Y (Delta usa secondi)
        self._view = None
        self._pan = None
        self._data_x = None
        self._dot_hit = {}
        self.color_cb = None
        self.setMinimumHeight(180)
        if scrub_cb is not None:
            self.setMouseTracking(True)
            self.setCursor(Qt.CrossCursor)

    def set_laps(self, sel, cmp, la, lb, unit, sec_dist=None,
                 la_time=None, lb_time=None, la_secs=None, lb_secs=None,
                 best_time=None, best_secs=None):
        self._sel = sel or []; self._cmp = cmp or []
        self._la = la; self._lb = lb; self._unit = unit
        self._sec_dist = [d for d in (sec_dist or []) if d]
        self._la_time = la_time; self._lb_time = lb_time
        self._la_secs = la_secs or []; self._lb_secs = lb_secs or []
        self._best_time = best_time; self._best_secs = best_secs or []
        self.update()

    def set_cursor(self, ld):
        self._cursor = ld; self.update()

    def set_ab(self, a, b):
        self._cur_a = a; self._cur_b = b; self.update()

    def set_view(self, view):
        """Imposta la finestra di zoom SENZA richiamare il callback (anti-echo)."""
        self._view = view; self.update()

    def clear_ab(self):
        self._cur_a = None; self._cur_b = None; self.update()

    @staticmethod
    def _val_at(series, ld):
        if not series or ld is None:
            return None
        return min(series, key=lambda q: abs(q[0] - ld))[1]

    def _ld_at(self, mx):
        if not self._xmap:
            return None
        ml, gw, xmin, xmax = self._xmap
        if gw <= 0:
            return None
        frac = max(0.0, min(1.0, (mx - ml) / gw))
        return xmin + frac * (xmax - xmin)

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(9, 13, 20, 150))
        W, H = self.width(), self.height()
        ml, mr, mt, mb = 46, 14, 28, 22
        gw, gh = W - ml - mr, H - mt - mb
        f = p.font(); f.setPointSize(8); p.setFont(f)
        allp = self._sel + self._cmp
        if len(allp) < 2:
            p.setPen(QColor("#60636c"))
            p.drawText(self.rect(), Qt.AlignCenter, "select a lap")
            p.end(); return
        xs = [q[0] for q in allp]
        xmin, xmax = min(xs), max(xs)
        if xmax <= xmin:
            xmax = xmin + 1.0
        self._data_x = (xmin, xmax)
        if self._view:
            v0, v1 = self._view
            xmin = max(xmin, v0); xmax = min(xmax, v1)
            if xmax <= xmin:
                xmax = xmin + 1.0
        ys = [q[1] for q in allp if q[1] is not None]
        if not ys:
            ys = [0.0, 1.0]
        ymin, ymax = min(ys), max(ys)
        if ymax <= ymin:
            ymax = ymin + 1.0
        pad = (ymax - ymin) * 0.08; ymin -= pad; ymax += pad

        def X(v):
            return ml + gw * (v - xmin) / (xmax - xmin)

        def Y(v):
            return mt + gh * (1.0 - (v - ymin) / (ymax - ymin))

        self._xmap = (ml, gw, xmin, xmax)
        for i in range(5):
            yy = mt + gh * i / 4
            p.setPen(QPen(QColor("#313d5a"), 1)); p.drawLine(ml, int(yy), W - mr, int(yy))
            val = ymax - (ymax - ymin) * i / 4
            p.setPen(QColor("#9fb0c8")); p.drawText(4, int(yy) + 4, self.yfmt.format(val))
        if self.baseline is not None and ymin <= self.baseline <= ymax:
            yb = Y(self.baseline)
            p.setPen(QPen(QColor("#60636c"), 1, Qt.DashLine))
            p.drawLine(ml, int(yb), W - mr, int(yb))
        p.setPen(QColor("#9fb0c8")); p.drawText(4, mt - 8, self._unit)
        for d in self._sec_dist:
            if xmin <= d <= xmax:
                xx = int(X(d))
                p.setPen(QPen(QColor("#3a3d43"), 1, Qt.DashLine)); p.drawLine(xx, mt, xx, mt + gh)
        bounds = [xmin] + list(self._sec_dist) + [xmax]
        p.setPen(QColor("#6d717b"))
        for i, lab in enumerate(("S1", "S2", "S3")):
            if i + 1 < len(bounds):
                cx = (bounds[i] + bounds[i + 1]) / 2.0
                if xmin <= cx <= xmax:
                    tw = p.fontMetrics().horizontalAdvance(lab)
                    p.drawText(QPointF(X(cx) - tw / 2, mt + 11), lab)
        # punti CURVA (T1, T2...): tick + label in basso, stessi della mappa
        _tm = getattr(self, "_turn_marks", [])
        if _tm:
            _ft = p.font(); _ft7 = p.font(); _ft7.setPointSize(7)
            p.setFont(_ft7)
            for _ld, _lab in _tm:
                if xmin <= _ld <= xmax:
                    xx = X(_ld)
                    p.setPen(QPen(QColor(255, 255, 255, 45), 1))
                    p.drawLine(int(xx), mt + gh - 7, int(xx), mt + gh)
                    _twl = p.fontMetrics().horizontalAdvance(_lab)
                    p.setPen(QColor("#8a90a0"))
                    p.drawText(QPointF(xx - _twl / 2.0, mt + gh - 9), _lab)
            p.setFont(_ft)
        f2 = p.font(); f2.setPointSize(7); p.setFont(f2)
        _draw_sector_times(p, X, bounds, self._la_secs, self._lb_secs, self._best_secs, xmin, xmax, mt + 22)
        p.setFont(f)

        p.save(); p.setClipRect(QRectF(ml, mt, gw, gh))

        def draw(pts, col, dashed):
            if len(pts) < 2:
                return
            pen = QPen(QColor(col), 2)
            if dashed:
                pen.setStyle(Qt.DashLine); pen.setWidthF(1.6)
            p.setPen(pen); p.setBrush(Qt.NoBrush)
            p.drawPolyline(QPolygonF([QPointF(X(x), Y(v)) for x, v in pts if v is not None]))

        if self.baseline is not None and len([1 for _, v in self._sel if v is not None]) >= 2:
            base = self.baseline; yb = Y(base)
            red = QLinearGradient(0, mt, 0, yb)           # rosso: intenso in alto, sfuma allo zero
            red.setColorAt(0.0, QColor(255, 76, 76, 135))
            red.setColorAt(1.0, QColor(255, 76, 76, 18))
            grn = QLinearGradient(0, yb, 0, mt + gh)       # verde: sfuma dallo zero, intenso in basso
            grn.setColorAt(0.0, QColor(40, 224, 120, 18))
            grn.setColorAt(1.0, QColor(40, 224, 120, 135))
            pts = [(x, v) for x, v in self._sel if v is not None]
            p.setPen(Qt.NoPen)
            for i in range(len(pts) - 1):
                x0, v0 = pts[i]; x1, v1 = pts[i + 1]
                if (v0 - base) * (v1 - base) < 0:        # attraversa lo zero: spezza
                    t = (base - v0) / (v1 - v0)
                    xc = x0 + t * (x1 - x0)
                    segs = [(x0, v0, xc, base), (xc, base, x1, v1)]
                else:
                    segs = [(x0, v0, x1, v1)]
                for sx0, sv0, sx1, sv1 in segs:
                    p.setBrush(red if (sv0 + sv1) * 0.5 > base else grn)
                    p.drawPolygon(QPolygonF([
                        QPointF(X(sx0), Y(sv0)), QPointF(X(sx1), Y(sv1)),
                        QPointF(X(sx1), yb), QPointF(X(sx0), yb)]))

        _cmpc = _cmp_col(self._cmp_gold)
        draw(self._cmp, _cmpc, True)
        draw(self._sel, _sel_col(), False)
        p.restore()

        if self._cursor is not None and xmin <= self._cursor <= xmax:
            xx = X(self._cursor)
            p.setPen(QPen(QColor("#f5f5f5"), 1)); p.drawLine(int(xx), mt, int(xx), mt + gh)
            yv = mt + 12
            if self._sel:
                ns = min(self._sel, key=lambda q: abs(q[0] - self._cursor))
                p.setPen(QColor(_sel_col())); p.drawText(QPointF(xx + 4, yv), f"{ns[1]:.1f}"); yv += 14
            if self._cmp:
                nc = min(self._cmp, key=lambda q: abs(q[0] - self._cursor))
                p.setPen(QColor(_cmpc)); p.drawText(QPointF(xx + 4, yv), f"{nc[1]:.1f}")

        # cursori A/B (shift-click): linee + readout del delta tra A e B
        def _ab_line(ld, col, tag):
            if ld is None or not (xmin <= ld <= xmax):
                return
            xx2 = X(ld)
            p.setPen(QPen(QColor(col), 1, Qt.DashLine))
            p.drawLine(int(xx2), mt, int(xx2), mt + gh)
            p.setPen(QColor(col)); p.drawText(QPointF(xx2 + 3, mt + gh - 5), tag)
        _ab_line(self._cur_a, "#f0a23a", "A")
        _ab_line(self._cur_b, "#36c5d0", "B")
        if self._cur_a is not None and self._cur_b is not None:
            va = self._val_at(self._sel, self._cur_a)
            vb = self._val_at(self._sel, self._cur_b)
            txt = f"\u0394X {self._cur_b - self._cur_a:+.0f} m"
            if va is not None and vb is not None:
                u = (" " + self._unit) if self._unit else ""
                txt += f"   \u0394{u.strip()} {vb - va:+.2f}"
            p.setPen(QColor("#f5f5f5"))
            tw = p.fontMetrics().horizontalAdvance(txt)
            p.drawText(QPointF(W - mr - tw, mt - 8), txt)
        elif self._cur_a is None and self._cur_b is None:
            p.setPen(QColor("#60636c"))
            p.drawText(QPointF(ml + 2, mt + gh + 16), "shift-click: A/B")

        # legend cliccabile (pick-color) + tempo giro (più veloce in fuxia)
        self._dot_hit = {}
        x = ml + 2
        cs = _best_color(self._la_time, self._best_time)
        cc = _best_color(self._lb_time, self._best_time)
        items = [("sel", self._la, QColor(_sel_col()), False,
                  _fmt(self._la_time) if self._la_time else "", cs)]
        if self._cmp:
            items.append(("cmp", self._lb, QColor(_cmpc), True,
                          _fmt(self._lb_time) if self._lb_time else "", cc))
        for which, label, col, dashed, tstr, tcol in items:
            pen = QPen(col, 2)
            if dashed:
                pen.setStyle(Qt.DashLine)
            p.setPen(pen); p.drawLine(int(x), 12, int(x) + 16, 12)
            xx = x + 21
            p.setPen(QColor("#dcdddf")); p.drawText(QPointF(xx, 16), label)
            xx += p.fontMetrics().horizontalAdvance(label) + 7
            if tstr:
                p.setPen(QColor(tcol)); p.drawText(QPointF(xx, 16), tstr)
                xx += p.fontMetrics().horizontalAdvance(tstr)
            self._dot_hit[which] = QRectF(x - 2, 2, (xx - x) + 6, 18)
            x = xx + 22
        p.end()

    def wheelEvent(self, e):
        if self._scrub_cb is None or not self._data_x:
            return
        dmin, dmax = self._data_x
        v0, v1 = self._view if self._view else (dmin, dmax)
        span = v1 - v0
        if span <= 0:
            return
        ld = self._ld_at(e.position().x())
        if ld is None:
            ld = (v0 + v1) / 2.0
        factor = 0.82 if e.angleDelta().y() > 0 else 1.0 / 0.82
        nspan = max((dmax - dmin) * 0.04, min(dmax - dmin, span * factor))
        frac = (ld - v0) / span
        n0 = ld - frac * nspan; n1 = n0 + nspan
        if n0 < dmin: n0 = dmin; n1 = n0 + nspan
        if n1 > dmax: n1 = dmax; n0 = n1 - nspan
        self._view = None if nspan >= (dmax - dmin) - 1e-6 else (max(dmin, n0), min(dmax, n1))
        if self._zoom_cb:
            self._zoom_cb(self._view)
        self.update()

    def _do_scrub(self, pos):
        if self._scrub_cb is None:
            return
        ld = self._ld_at(pos.x())
        if ld is None:
            return
        self.set_cursor(ld); self._scrub_cb(ld)

    def mouseMoveEvent(self, e):
        if self.color_cb is not None:
            on = any(r.contains(e.position()) for r in self._dot_hit.values())
            self.setCursor(Qt.PointingHandCursor if on else Qt.CrossCursor)
        if self._pan is not None:
            mx0, v0, v1 = self._pan
            ml, gw, _, _ = self._xmap or (46, max(1, self.width() - 60), 0, 1)
            dmin, dmax = self._data_x; span = v1 - v0
            dx = (e.position().x() - mx0) / max(1, gw) * span
            n0 = v0 - dx; n1 = v1 - dx
            if n0 < dmin: n0 = dmin; n1 = n0 + span
            if n1 > dmax: n1 = dmax; n0 = n1 - span
            self._view = (n0, n1)
            if self._zoom_cb:
                self._zoom_cb(self._view)
            self.update()
        else:
            self._do_scrub(e.position())
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):
        if self.color_cb is not None:
            for which, rect in self._dot_hit.items():
                if rect.contains(e.position()):
                    self.color_cb(which); return
        if e.button() == Qt.LeftButton and (e.modifiers() & Qt.ShiftModifier):
            ld = self._ld_at(e.position().x())
            if ld is not None:
                if self._cur_a is None:
                    self._cur_a = ld
                elif self._cur_b is None:
                    self._cur_b = ld
                else:
                    self._cur_a = ld; self._cur_b = None
                if self._ab_cb:
                    self._ab_cb(self._cur_a, self._cur_b)
                self.update()
            return
        if e.button() == Qt.RightButton and self._view is not None:
            self._pan = (e.position().x(), self._view[0], self._view[1])
        else:
            self._do_scrub(e.position())
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._pan = None; super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        self._view = None
        if self._zoom_cb:
            self._zoom_cb(None)
        self.update(); super().mouseDoubleClickEvent(e)

    def recolor(self):
        self.update()


def _spd_series(con, lap):
    """[(lapdist, speed_kmh)] crescente per distanza, deduplicato."""
    if lap is None or con is None:
        return []
    try:
        rs = _rows(con, "SELECT lapdist, speed FROM samples WHERE lap=? ORDER BY rowid", (lap,))
    except Exception:
        return []
    xy = [(r["lapdist"], r["speed"]) for r in rs
          if r["lapdist"] is not None and r["speed"] is not None]
    xy.sort(key=lambda q: q[0])
    out = []; last = None
    for x, v in xy:
        if last is None or x > last + 1e-6:
            out.append((x, v)); last = x
    return out


def _resample(series, grid):
    """Interpola linearmente i valori di `series` (ordinata per x) sui punti `grid`."""
    out = []; j = 0; n = len(series)
    for x in grid:
        if x <= series[0][0]:
            out.append(series[0][1]); continue
        while j < n - 1 and series[j + 1][0] < x:
            j += 1
        if j >= n - 1:
            out.append(series[-1][1]); continue
        x0, v0 = series[j]; x1, v1 = series[j + 1]
        out.append(v0 if x1 <= x0 else v0 + (v1 - v0) * (x - x0) / (x1 - x0))
    return out


def _t_series(con, lap):
    """[(lapdist, t_dall_inizio_giro)] crescente per distanza, deduplicato."""
    if lap is None or con is None:
        return []
    try:
        rs = _rows(con, "SELECT lapdist, t FROM samples WHERE lap=? ORDER BY rowid", (lap,))
    except Exception:
        return []
    xy = [(r["lapdist"], r["t"]) for r in rs
          if r["lapdist"] is not None and r["t"] is not None]
    xy.sort(key=lambda q: q[0])
    out = []; last = None
    for x, t in xy:
        if last is None or x > last + 1e-6:
            out.append((x, t)); last = x
    return out


def _delta_series(con, sel, cmp, step=2.0, con_cmp=None):
    """Delta-T cumulato vs distanza fra Compare e Selected.
    Usa il TEMPO REALE per campione (colonna t). Se con_cmp è dato, il giro
    Compare è letto da QUEL database (reference cross-session)."""
    a = _t_series(con, sel); b = _t_series(con_cmp or con, cmp)
    if len(a) < 2 or len(b) < 2:
        return []
    d0 = max(a[0][0], b[0][0], 0.0)
    d1 = min(a[-1][0], b[-1][0])
    if d1 <= d0:
        return []
    grid = []; x = d0
    while x <= d1:
        grid.append(x); x += step
    if len(grid) < 2:
        return []
    ta = _resample(a, grid); tb = _resample(b, grid)
    a0 = ta[0]; b0 = tb[0]
    # Δ = Selected - Compare (TUO giro - REF): >0 = stai perdendo sul REF.
    return [(grid[i], (ta[i] - a0) - (tb[i] - b0)) for i in range(len(grid))]


class _DeltaTab(QWidget):
    """Delta-T vs distanza: curva singola (Compare - Selected) con linea zero,
    riusa _TraceChart per scrub/zoom/pan. La mappa mostra le due traiettorie."""
    def __init__(self, data):
        super().__init__()
        self.data = data
        self._sel = None; self._cmp = None
        self._la = "Selected"; self._lb = "Compare"
        root = QVBoxLayout(self)
        self._read = QLabel(""); self._read.setStyleSheet("color:#dcdddf;padding:4px 10px;")
        root.addWidget(self._read)
        self._info = QLabel(""); self._info.setTextFormat(Qt.RichText)
        self._info.setStyleSheet("padding:0 10px 4px 10px;font-size:13px;")
        root.addWidget(self._info)
        roww = QWidget(); rowl = QHBoxLayout(roww); rowl.setContentsMargins(0, 0, 0, 0)
        self.chart = _TraceChart(scrub_cb=self._on_scrub)
        self.chart.baseline = 0.0
        self.chart.yfmt = "{:+.2f}"
        self.map_w = _LiveMap()
        rowl.addWidget(self.chart, 2)
        rowl.addWidget(self.map_w, 1)
        root.addWidget(roww, 1)

    def _xz(self, lap, con=None):
        con = con or self.data.con
        if lap is None or con is None:
            return []
        try:
            rs = _rows(con,
                       "SELECT pos_x, pos_z, lapdist FROM samples WHERE lap=? ORDER BY rowid", (lap,))
        except Exception:
            return []
        return [(r["pos_x"], r["pos_z"], r["lapdist"]) for r in rs
                if r["pos_x"] is not None and r["pos_z"] is not None]

    def _sec_dist(self, lap):
        if lap is None or self.data.con is None:
            return []
        L = self.data._by_id.get(lap, {})
        s1 = L.get("s1") or 0.0; s2 = L.get("s2") or 0.0
        if not s1:
            return []
        try:
            rs = _rows(self.data.con,
                       "SELECT t, lapdist FROM samples WHERE lap=? ORDER BY rowid", (lap,))
        except Exception:
            return []
        b1 = b2 = None
        for r in rs:
            if r["t"] is None or r["lapdist"] is None:
                continue
            if b1 is None and r["t"] >= s1:
                b1 = r["lapdist"]
            if b2 is None and s2 and r["t"] >= s1 + s2:
                b2 = r["lapdist"]; break
        return [d for d in (b1, b2) if d is not None]

    def _lap_info(self, lap, con=None):
        """(lap_time, [s1, s2, s3]) per un giro. None se assente."""
        con = con or self.data.con
        if lap is None or con is None:
            return (None, [None, None, None])
        try:
            r = _rows(con, "SELECT lap_time, s1, s2, s3 FROM laps WHERE lap=?", (lap,))
        except Exception:
            return (None, [None, None, None])
        if not r:
            return (None, [None, None, None])
        return (r[0]["lap_time"], [r[0]["s1"], r[0]["s2"], r[0]["s3"]])

    def _set_info(self, sel_t, sel_s, cmp_t, cmp_s, cmp_name):
        def fmt_t(v):
            return _fmt(v) if v else "\u2014"

        def fmt_d(v):
            if v is None:
                return "<span style='color:#838790'>\u2014</span>"
            col = "#ff6b6b" if v > 0.0005 else ("#55ff7f" if v < -0.0005 else "#dcdddf")
            return "<span style='color:%s'>%+.2f</span>" % (col, v)

        ds = []
        for i in range(3):
            a = sel_s[i] if i < len(sel_s) else None
            b = cmp_s[i] if i < len(cmp_s) else None
            ds.append((a - b) if (a is not None and b is not None) else None)
        dtot = (sel_t - cmp_t) if (sel_t and cmp_t) else None
        html = (
            "<span style='color:#8fe9c0'>%s</span> <b style='color:#f5f5f5'>%s</b>"
            "&nbsp;&nbsp;\u00b7&nbsp;&nbsp;"
            "<span style='color:#c9a23a'>%s</span> <b style='color:#f5f5f5'>%s</b>"
            "&nbsp;&nbsp;&nbsp;&nbsp;"
            "S1 %s&nbsp;&nbsp; S2 %s&nbsp;&nbsp; S3 %s"
            "&nbsp;&nbsp;&nbsp;&nbsp;\u0394 %s"
            % (self._la, fmt_t(sel_t), cmp_name, fmt_t(cmp_t),
               fmt_d(ds[0]), fmt_d(ds[1]), fmt_d(ds[2]), fmt_d(dtot)))
        self._info.setText(html)

    def _refresh(self):
        self._la = f"Lap {self._sel}" if self._sel is not None else "Selected"
        self.chart.set_cursor(None)
        ref = self.data.cmp_source()
        self.map_w._cmp_gold = (ref[5] if ref else False)
        if ref:
            rcon, rlap, rlabel, rtime, rsecs, gold = ref
            self._lb = rlabel
            delta = _delta_series(self.data.con, self._sel, rlap, con_cmp=rcon) \
                if self._sel is not None else []
            cmp_xz = self._xz(rlap, con=rcon)
            cmp_t = rtime; cmp_s = list(rsecs or [None, None, None])
        else:
            self._lb = f"Lap {self._cmp}" if self._cmp is not None else "Compare"
            delta = _delta_series(self.data.con, self._sel, self._cmp) \
                if (self._sel is not None and self._cmp is not None) else []
            cmp_xz = self._xz(self._cmp)
            cmp_t, cmp_s = self._lap_info(self._cmp)
        sel_t, sel_s = self._lap_info(self._sel)
        self.chart.set_laps(delta, [], "\u0394t (You \u2212 Compare)", "", "s",
                            sec_dist=self._sec_dist(self._sel))
        self.map_w.set_review(self._xz(self._sel), cmp_xz, self._la, self._lb)
        if delta:
            self._set_info(sel_t, sel_s, cmp_t, cmp_s, self._lb)
        else:
            self._info.setText("")
        self._update_read(None)

    def _update_read(self, ld):
        d = self.chart._sel
        parts = ["\u0394t  (You \u2212 Compare)   >0 = you are slower (losing)"]
        if d:
            parts.append(f"final {d[-1][1]:+.3f}s")
            if ld is not None:
                cur = min(d, key=lambda q: abs(q[0] - ld))[1]
                parts.append(f"@cursor {cur:+.3f}s")
        self._read.setText("        ".join(parts))

    def _on_scrub(self, ld):
        self.chart.set_cursor(ld)
        for _ch, _wc, _un in getattr(self, "_wx_charts", []):
            _ch.set_cursor(ld)          # asfalto/rain seguono il cursore come nel Worksheet
        self.map_w.set_hi_by_lapdist(ld)
        self._update_read(ld)

    def set_lap(self, lap):
        self._sel = lap; self._refresh()

    def set_compare(self, lap):
        self._cmp = lap; self._refresh()

    def recolor(self):
        self.chart.update(); self.map_w.update()


class _WorksheetTab(QWidget):
    """Worksheet multi-canale: piu' canali impilati (Speed/Throttle/Brake/
    Steering/Gear) con asse distanza condiviso e UN cursore unico che li scorre
    tutti. Zoom e cursori A/B sincronizzati col resto via _charts del parent."""
    # (label, colonna, unita', scala, yfmt)
    _CHANS = [
        ("Speed",    "speed",    "km/h", 1.0,   "{:.0f}"),
        ("Throttle", "throttle", "%",    100.0, "{:.0f}"),
        ("Brake",    "brake",    "%",    100.0, "{:.0f}"),
        ("Steering", "steer",    "\u00b0", 1.0, "{:.0f}"),
        ("Gear",     "gear",     "",     1.0,   "{:.0f}"),
    ]

    # CATALOGO dei canali aggiungibili col "+" (label, col, unita, scala, yfmt).
    # I per-ruota restano nelle tab dedicate (Tyres/Brakes/Suspension).
    _CATALOG = [
        ("Speed",      "speed",      "km/h",   1.0,   "{:.0f}"),
        # DELTA-T: differenza tempo vs giro di confronto lungo la distanza
        # (calcolato da t+lapdist dei due giri, non e' una colonna DB).
        # Positivo = piu' lento del confronto in quel punto.
        ("Delta",      "__delta",    "s",      1.0,   "{:+.2f}"),
        ("G Lat",      "g_lat",      "G",      1.0,   "{:+.2f}"),
        ("G Long",     "g_long",     "G",      1.0,   "{:+.2f}"),
        ("Throttle",   "throttle",   "%",      100.0, "{:.0f}"),
        ("Brake",      "brake",      "%",      100.0, "{:.0f}"),
        ("Steering",   "steer",      "\u00b0",  1.0,   "{:.0f}"),
        ("Gear",       "gear",       "",       1.0,   "{:.0f}"),
        ("RPM",        "rpm",        "rpm",    1.0,   "{:.0f}"),
        ("Brake Bias", "brake_bias", "%",      100.0, "{:.1f}"),
        ("TC Active",  "tc_active",  "",       1.0,   "{:.0f}"),
        ("ABS Active", "abs_active", "",       1.0,   "{:.0f}"),
        ("SOC",        "soc",        "%",      1.0,   "{:.1f}"),
        ("Regen",      "regen_kw",   "kW",     1.0,   "{:.0f}"),
        ("Fuel",       "fuel",       "L",      1.0,   "{:.1f}"),
        ("VE",         "ve",         "%",      1.0,   "{:.1f}"),
        ("TC Map",     "tc_map",     "",       1.0,   "{:.0f}"),
        ("ABS Map",    "abs_map",    "",       1.0,   "{:.0f}"),
        ("TC Slip",    "tc_slip",    "",       1.0,   "{:.0f}"),
        ("TC Cut",     "tc_cut",     "",       1.0,   "{:.0f}"),
        ("Boost State", "boost_state", "",     1.0,   "{:.0f}"),
        ("Elevation",  "pos_y",      "m",      1.0,   "{:.0f}"),
        ("Track Temp", "track_temp", "\u00b0C", 1.0,   "{:.1f}"),
        ("Rain",       "rain_pct",   "%",      1.0,   "{:.0f}"),
    ]
    _DEFAULT = ("Speed", "Throttle", "Brake", "Steering", "Gear")

    def __init__(self, data):
        super().__init__()
        self.data = data
        self._sel = None; self._cmp = None
        self._la = "Selected"; self._lb = "Compare"
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        self._read = QLabel(""); self._read.setTextFormat(Qt.RichText)
        self._read.setStyleSheet("color:#dcdddf;padding:5px 10px;font-size:12px;")
        root.addWidget(self._read)
        from PySide6.QtWidgets import QScrollArea
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # scrollbar VISIBILE e a SINISTRA (trucco RightToLeft sul solo scroll;
        # il contenuto resta LTR). Il QSS globale la nasconde: override qui.
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setLayoutDirection(Qt.RightToLeft)
        scroll.setStyleSheet(
            "QScrollArea{background:transparent;}"
            "QScrollBar:vertical{width:8px;background:transparent;margin:0;}"
            "QScrollBar::handle:vertical{background:rgba(255,255,255,0.25);"
            "border-radius:4px;min-height:30px;}"
            "QScrollBar::handle:vertical:hover{background:rgba(255,255,255,0.45);}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{"
            "background:transparent;}")
        host = QWidget(); col = QVBoxLayout(host)
        host.setLayoutDirection(Qt.LeftToRight)
        col.setContentsMargins(8, 2, 8, 8); col.setSpacing(6)
        self._col = col
        self.charts = []
        self._items = []                     # (name, container, chart)
        # "+" SEMPRE in alto (fuori dallo scroll): non sparisce scorrendo
        _prow = QWidget(); _pl = QHBoxLayout(_prow)
        _pl.setContentsMargins(8, 2, 8, 0); _pl.setSpacing(8)
        self._plus = QPushButton("+")
        self._plus.setCursor(Qt.PointingHandCursor)
        self._plus.setFixedSize(28, 28)
        self._plus.setToolTip("Add chart")
        self._plus.setStyleSheet(
            "QPushButton{color:#ffffff;font-size:18px;font-weight:700;"
            "background:rgba(255,255,255,0.08);border:none;border-radius:14px;}"
            "QPushButton:hover{background:rgba(255,29,67,0.55);}")
        self._plus.clicked.connect(self._plus_menu)
        _pl.addWidget(self._plus, 0, Qt.AlignVCenter)
        _phint = QLabel("ADD CHART")
        _phint.setStyleSheet("color:#8a90a0;font-size:11px;font-weight:700;"
                             "letter-spacing:1px;background:transparent;")
        _pl.addWidget(_phint, 0, Qt.AlignVCenter)
        # PLAY: replay dei due giri sulla mappa in TEMPO REALE (ognuno alla
        # sua velocita': si vede dove il confronto guadagna/perde)
        _pl.addSpacing(14)
        # INDIETRO: riparte dall'inizio (o da A se il loop A-B e' attivo)
        self._rw = QPushButton("skip_previous")    # Material Icons (ligature)
        self._rw.setCursor(Qt.PointingHandCursor)
        self._rw.setFixedSize(28, 28)
        self._rw.setToolTip("Restart replay (from A if A/B loop)")
        self._rw.setStyleSheet(
            "QPushButton{font-family:'Material Icons';color:#ffffff;"
            "font-size:18px;"
            "background:rgba(255,255,255,0.08);border:none;border-radius:14px;}"
            "QPushButton:hover{background:rgba(255,29,67,0.55);}")
        self._rw.clicked.connect(self._rp_restart)
        _pl.addWidget(self._rw, 0, Qt.AlignVCenter)
        # REVERSE: replay all'indietro (toggle)
        self._REV_OFF = (
            "QPushButton{font-family:'Material Icons';color:#ffffff;"
            "font-size:18px;"
            "background:rgba(255,255,255,0.08);border:none;border-radius:14px;}"
            "QPushButton:hover{background:rgba(255,29,67,0.55);}")
        self._REV_ON = (
            "QPushButton{font-family:'Material Icons';color:#ffffff;"
            "font-size:18px;"
            "background:rgba(255,29,67,0.75);border:none;border-radius:14px;}")
        self._rp_dir = 1
        self._rev = QPushButton("fast_rewind")     # Material Icons (ligature)
        self._rev.setCursor(Qt.PointingHandCursor)
        self._rev.setFixedSize(28, 28)
        self._rev.setToolTip("Reverse playback")
        self._rev.setStyleSheet(self._REV_OFF)
        self._rev.clicked.connect(self._toggle_rev)
        _pl.addWidget(self._rev, 0, Qt.AlignVCenter)
        self._play = QPushButton("play_arrow")     # Material Icons (ligature)
        self._play.setCursor(Qt.PointingHandCursor)
        self._play.setFixedSize(28, 28)
        self._play.setToolTip("Replay both laps on the map (real time)")
        self._play.setStyleSheet(
            "QPushButton{font-family:'Material Icons';color:#ffffff;"
            "font-size:18px;"
            "background:rgba(255,255,255,0.08);border:none;border-radius:14px;}"
            "QPushButton:hover{background:rgba(255,29,67,0.55);}")
        self._play.clicked.connect(self._toggle_play)
        _pl.addWidget(self._play, 0, Qt.AlignVCenter)
        _phint2 = QLabel("REPLAY")
        _phint2.setStyleSheet("color:#8a90a0;font-size:11px;font-weight:700;"
                              "letter-spacing:1px;background:transparent;")
        _pl.addWidget(_phint2, 0, Qt.AlignVCenter)
        # velocita' replay: cicla 1x -> 2x -> 4x -> 0.5x
        self._rp_speed = 1.0
        self._spd = QPushButton("1×")
        self._spd.setCursor(Qt.PointingHandCursor)
        self._spd.setFixedSize(40, 28)
        self._spd.setToolTip("Replay speed")
        self._spd.setStyleSheet(
            "QPushButton{color:#ffffff;font-size:12px;font-weight:700;"
            "background:rgba(255,255,255,0.08);border:none;border-radius:14px;}"
            "QPushButton:hover{background:rgba(255,29,67,0.55);}")
        self._spd.clicked.connect(self._cycle_speed)
        _pl.addWidget(self._spd, 0, Qt.AlignVCenter)
        # cancella i cursori A/B (loop) su tutti i grafici
        self._abx = QPushButton("AB✕")
        self._abx.setCursor(Qt.PointingHandCursor)
        self._abx.setFixedSize(44, 28)
        self._abx.setToolTip("Clear A/B cursors (loop)")
        self._abx.setStyleSheet(
            "QPushButton{color:#ffffff;font-size:11px;font-weight:700;"
            "background:rgba(255,255,255,0.08);border:none;border-radius:14px;}"
            "QPushButton:hover{background:rgba(255,29,67,0.55);}")
        self._abx.clicked.connect(self._clear_ab)
        _pl.addWidget(self._abx, 0, Qt.AlignVCenter)
        # simbolo pilota sulla mappa: dot / macchinina / freccia GPS
        self._mkbtn = QPushButton("navigation")    # Material Icons (ligature)
        self._mkbtn.setCursor(Qt.PointingHandCursor)
        self._mkbtn.setFixedSize(28, 28)
        self._mkbtn.setToolTip("Map symbol: dot / car / GPS arrow")
        self._mkbtn.setStyleSheet(
            "QPushButton{font-family:'Material Icons';color:#ffffff;"
            "font-size:16px;"
            "background:rgba(255,255,255,0.08);border:none;border-radius:14px;}"
            "QPushButton:hover{background:rgba(255,29,67,0.55);}")
        self._mkbtn.clicked.connect(self._marker_menu)
        _pl.addWidget(self._mkbtn, 0, Qt.AlignVCenter)
        _pl.addStretch(1)
        root.addWidget(_prow)                # fisso, sopra lo scroll
        from PySide6.QtCore import QTimer as _QT
        self._rp_timer = _QT(self)
        self._rp_timer.setInterval(16)               # ~60 fps: replay fluido
        self._rp_timer.timeout.connect(self._rp_tick)
        self._rp_t = 0.0
        self._rp_ta = []; self._rp_tb = []           # (t_rel, lapdist)
        self._rp_ia = 0; self._rp_ib = 0
        self._rp_ab = None                           # loop A-B attivo (lo, hi)
        self._rp_off = 0.0                           # offset tempo del confronto
        # VUOTO all'avvio: si caricano solo i canali scelti dall'utente
        try:
            from core.profile import _load_profile
            names = _load_profile().get("ws_chans")
        except Exception:
            names = None
        for nm in (names if isinstance(names, list) else []):
            self._add_chan(nm, save=False)
        col.addStretch()
        scroll.setWidget(host)
        self.map_w = _LiveMap()
        row = QWidget(); rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(8)
        # mappa a 1/3 (era 1/4): piu' respiro per leggere le traiettorie
        rl.addWidget(scroll, 2)
        rl.addWidget(self.map_w, 1)
        root.addWidget(row, 1)
        # stato mappa salvato (default visibile); il toggle e' la pill MAP
        # in alto nella pagina Telemetry
        try:
            from core.profile import _load_profile
            _mon = bool(_load_profile().get("ws_map", True))
            # simbolo pilota scelto (dot/car/arrow), persistito
            self.map_w._mk_style = _load_profile().get("ws_marker", "car")
        except Exception:
            _mon = True
        self.map_w.setVisible(_mon)

    def _spec(self, name):
        for sp in self._CATALOG:
            if sp[0] == name:
                return sp
        return None

    def _add_chan(self, name, save=True):
        sp = self._spec(name)
        if sp is None or any(nm == name for nm, _w, _c in self._items):
            return
        name, c, unit, scale, yf = sp
        box = QWidget(); bv = QVBoxLayout(box)
        bv.setContentsMargins(0, 0, 0, 0); bv.setSpacing(0)
        top = QWidget(); tl = QHBoxLayout(top)
        tl.setContentsMargins(2, 2, 2, 0); tl.setSpacing(6)
        lab = QLabel(name); lab.setObjectName("wsChanLbl")
        lab.setStyleSheet("color:#989ba2;font-size:11px;font-weight:700;"
                          "background:transparent;")
        tl.addWidget(lab); tl.addStretch(1)
        rm = QPushButton("\u00d7")
        rm.setCursor(Qt.PointingHandCursor)
        rm.setFixedSize(18, 18)
        rm.setToolTip("Remove chart")
        rm.setStyleSheet(
            "QPushButton{color:#9aa0aa;font-size:13px;font-weight:700;"
            "background:transparent;border:none;}"
            "QPushButton:hover{color:#ff1d43;}")
        rm.clicked.connect(lambda _=False, nm=name: self._remove_chan(nm))
        tl.addWidget(rm)
        bv.addWidget(top)
        ch = _TraceChart(scrub_cb=self._on_scrub)
        ch.setMinimumHeight(118); ch.setMaximumHeight(160)   # piu' respiro
        ch.yfmt = yf
        ch._ws = (name, c, unit, scale)        # metadati canale sul chart
        bv.addWidget(ch)
        self.charts.append(ch)
        self._items.append((name, box, ch))
        _reg = getattr(self, "register_chart_cb", None)
        if _reg:
            _reg(ch)                           # sync zoom + cursori A/B
        # inserisci PRIMA dello stretch finale (se gia presente)
        _n = self._col.count()
        self._col.insertWidget(_n - 1 if _n else 0, box)
        if save:
            self._save_chans()
            try:
                self._refresh()
            except Exception:
                pass

    def _remove_chan(self, name):
        for i, (nm, box, ch) in enumerate(self._items):
            if nm == name:
                self._items.pop(i)
                if ch in self.charts:
                    self.charts.remove(ch)
                _unreg = getattr(self, "unregister_chart_cb", None)
                if _unreg:
                    _unreg(ch)
                box.setParent(None); box.deleteLater()
                self._save_chans()
                return

    def _save_chans(self):
        try:
            from core.profile import _load_profile, _save_profile
            d = _load_profile()
            d["ws_chans"] = [nm for nm, _w, _c in self._items]
            _save_profile(d)
        except Exception:
            pass

    def set_map_visible(self, on):
        """Mostra/nasconde la mappa (pill MAP della pagina Telemetry)."""
        self.map_w.setVisible(bool(on))
        try:
            from core.profile import _load_profile, _save_profile
            d = _load_profile(); d["ws_map"] = bool(on); _save_profile(d)
        except Exception:
            pass

    def _marker_menu(self):
        """Scelta del simbolo pilota sulla mappa (persistita nel profilo)."""
        from PySide6.QtWidgets import QMenu
        cur = getattr(self.map_w, "_mk_style", "dot")
        m = QMenu(self)
        m.setStyleSheet(
            "QMenu{background:#16181c;color:#f2f4f7;border:1px solid #2a2c30;"
            "font-family:Archivo SemiExpanded;font-size:12px;}"
            "QMenu::item{padding:5px 18px;}"
            "QMenu::item:selected{background:rgba(255,29,67,0.45);}")
        for lab, key in (("Dot", "dot"), ("Car", "car"),
                         ("GPS arrow", "arrow")):
            a = m.addAction(("● " if key == cur else "   ") + lab,
                            lambda k=key: self._set_marker(k))
        m.exec(self._mkbtn.mapToGlobal(self._mkbtn.rect().bottomLeft()))

    def _set_marker(self, key):
        self.map_w._mk_style = key
        self.map_w.update()
        try:
            from core.profile import _load_profile, _save_profile
            d = _load_profile(); d["ws_marker"] = key; _save_profile(d)
        except Exception:
            pass

    def _plus_menu(self):
        from PySide6.QtWidgets import QMenu
        have = {nm for nm, _w, _c in self._items}
        m = QMenu(self)
        m.setStyleSheet(
            "QMenu{background:#16181c;color:#f2f4f7;border:1px solid #2a2c30;"
            "font-family:Archivo SemiExpanded;font-size:12px;}"
            "QMenu::item{padding:5px 18px;}"
            "QMenu::item:selected{background:rgba(255,29,67,0.45);}")
        for sp in self._CATALOG:
            if sp[0] in have:
                continue
            m.addAction(sp[0], lambda nm=sp[0]: self._add_chan(nm))
        # menu lungo -> scrollabile (frecce di scroll native di QMenu)
        m.setMaximumHeight(420)
        if not m.isEmpty():
            m.exec(self._plus.mapToGlobal(self._plus.rect().bottomLeft()))

    def _series(self, lap, col, scale, con=None):
        con = con or self.data.con
        if lap is None or con is None:
            return []
        try:
            rs = _rows(con, f"SELECT lapdist, {col} v FROM samples "
                            "WHERE lap=? ORDER BY rowid", (lap,))
        except Exception:
            return []
        xy = [(r["lapdist"], r["v"] * scale) for r in rs
              if r["lapdist"] is not None and r["v"] is not None]
        xy.sort(key=lambda q: q[0])
        out = []; last = None
        for x, v in xy:
            if last is None or x > last + 1e-6:
                out.append((x, v)); last = x
        return out

    # ── REPLAY sulla mappa: due giri in tempo reale ───────────────────
    def _t2ld(self, lap, con=None):
        """Serie (t_rel, lapdist) di un giro, per il replay a tempo."""
        s = self._series(lap, "t", 1.0, con=con)     # [(lapdist, t)]
        if len(s) < 2:
            return []
        t0 = min(t for _ld, t in s)
        out = [(t - t0, ld) for ld, t in s]
        out.sort(key=lambda q: q[0])
        return out

    @staticmethod
    def _ld_at_t(tl, t, i0=0):
        """lapdist al tempo t (interpolato). Ritorna (ld|None, indice).
        Pointer BIDIREZIONALE: serve anche al reverse."""
        n = len(tl)
        if not n:
            return None, 0
        i = max(0, min(i0, n - 1))
        while i + 1 < n and tl[i + 1][0] <= t:
            i += 1
        while i > 0 and tl[i][0] > t:
            i -= 1
        if i + 1 >= n:
            return None, i                            # giro finito
        t1, d1 = tl[i]; t2, d2 = tl[i + 1]
        if t < t1:
            return d1, i
        f = (t - t1) / (t2 - t1) if t2 > t1 else 0.0
        return d1 + (d2 - d1) * f, i

    def _toggle_rev(self):
        """Direzione replay: avanti <-> indietro."""
        self._rp_dir = -1 if getattr(self, "_rp_dir", 1) > 0 else 1
        self._rev.setStyleSheet(self._REV_ON if self._rp_dir < 0
                                else self._REV_OFF)

    def _clear_ab(self):
        """Toglie i cursori A/B da tutti i grafici (fine del loop)."""
        for ch in self.charts:
            try:
                ch.set_ab(None, None)
            except Exception:
                pass
        self._rp_ab = None

    def _toggle_play(self):
        if self._rp_timer.isActive():                 # pausa
            self._rp_timer.stop()
            self._play.setText("play_arrow")
            return
        if self._sel is None:
            return
        # confronto risolto come in _refresh (REF esterno compreso)
        ref = self.data.cmp_source()
        if ref:
            _rcon, _rlap = ref[0], ref[1]
            cmp_lap, cmp_con = _rlap, _rcon
        else:
            cmp_lap, cmp_con = self._cmp, None
        if not self._rp_ta or self._rp_t <= 0.0:
            self._rp_ta = self._t2ld(self._sel)
            self._rp_tb = self._t2ld(cmp_lap, con=cmp_con) \
                if cmp_lap is not None else []
            self._rp_t = 0.0; self._rp_ia = 0; self._rp_ib = 0
        # confronto scelto DOPO l'ultimo play: caricalo anche in ripresa
        if not self._rp_tb and cmp_lap is not None:
            self._rp_tb = self._t2ld(cmp_lap, con=cmp_con)
        if not self._rp_ta:
            return
        self._play.setText("pause")
        self._rp_timer.start()

    def _stop_play(self):
        self._rp_timer.stop()
        self._rp_t = 0.0
        self._rp_ta = []; self._rp_tb = []
        self._rp_ab = None; self._rp_off = 0.0
        self._play.setText("play_arrow")
        try:
            self.map_w.set_play_pos(None, None)
        except Exception:
            pass

    def _ab_range(self):
        """Cursori A/B (shift-click sui grafici, sincronizzati): se ci sono
        entrambi il replay LOOPA sul segmento [A, B]."""
        for ch in self.charts:
            a = getattr(ch, "_cur_a", None)
            b = getattr(ch, "_cur_b", None)
            if a is not None and b is not None:
                return (min(a, b), max(a, b))
        return None

    @staticmethod
    def _t_at_ld(tl, ld):
        """Tempo (relativo) a cui il giro passa dalla lapdist ld."""
        if not tl or ld is None:
            return None
        prev = tl[0]
        for cur in tl[1:]:
            if cur[1] >= ld:
                t1, d1 = prev; t2, d2 = cur
                if d2 <= d1:
                    return t2
                f = max(0.0, min(1.0, (ld - d1) / (d2 - d1)))
                return t1 + (t2 - t1) * f
            prev = cur
        return tl[-1][0]

    def _rp_restart(self):
        """INDIETRO: torna all'inizio del giro (o ad A col loop attivo).
        Da fermo carica i dati come il play, ma resta in pausa sul via."""
        if not self._rp_ta:
            self._toggle_play()                  # carica e parte
            if self._rp_timer.isActive():
                self._rp_timer.stop()
                self._play.setText("play_arrow")
        _ab = self._ab_range()
        if _ab and self._rp_ta:
            self._rp_enter_ab(*_ab)
        else:
            self._rp_t = 0.0
            self._rp_ia = 0; self._rp_ib = 0
            self._rp_off = 0.0; self._rp_ab = None
        # aggiorna subito mappa/cursori anche in pausa (un frame)
        if self._rp_ta:
            self._rp_tick()

    def _rp_enter_ab(self, lo, hi):
        """(Ri)aggancia il loop A-B: entrambe le auto ripartono da A nello
        stesso istante, ognuna col SUO tempo (l'offset riallinea il confronto)."""
        self._rp_ab = (lo, hi)
        _ta = self._t_at_ld(self._rp_ta, lo)
        self._rp_t = _ta if _ta is not None else 0.0
        _tb = self._t_at_ld(self._rp_tb, lo) if self._rp_tb else None
        self._rp_off = (self._rp_t - _tb) if _tb is not None else 0.0
        self._rp_ia = 0; self._rp_ib = 0

    def _cycle_speed(self):
        _seq = [1.0, 2.0, 4.0, 8.0, 0.5]     # +8x (rich. 23/07)
        try:
            i = _seq.index(self._rp_speed)
        except ValueError:
            i = 0
        self._rp_speed = _seq[(i + 1) % len(_seq)]
        self._spd.setText("%g×" % self._rp_speed)

    def _rp_tick(self):
        _dir = getattr(self, "_rp_dir", 1)
        # dt REALE misurato (non fisso): a 60fps il passo fisso 0.033
        # correva al doppio e a scatti — ora e' fluido e in tempo vero
        import time as _tm
        _nowr = _tm.monotonic()
        _dtr = _nowr - getattr(self, "_rp_last_t", _nowr)
        self._rp_last_t = _nowr
        if not (0.0 < _dtr < 0.25):
            _dtr = 0.016
        self._rp_t += _dtr * self._rp_speed * _dir
        if self._rp_t < 0.0:
            self._rp_t = 0.0
        # loop A-B: aggancia/riaggancia quando i cursori cambiano
        _ab = self._ab_range()
        if _ab and self._rp_ta:
            if getattr(self, "_rp_ab", None) != _ab:
                self._rp_enter_ab(*_ab)
        else:
            self._rp_ab = None
        _off = getattr(self, "_rp_off", 0.0)
        ld_a, self._rp_ia = self._ld_at_t(self._rp_ta, self._rp_t, self._rp_ia)
        ld_b, self._rp_ib = self._ld_at_t(self._rp_tb, self._rp_t - _off,
                                          self._rp_ib) \
            if self._rp_tb else (None, 0)
        if _ab and self._rp_ta:
            lo, hi = _ab
            if _dir > 0 and (ld_a is None or ld_a >= hi):
                self._rp_enter_ab(lo, hi)              # B raggiunto: da A
                return
            if _dir < 0 and (ld_a is None or ld_a <= lo):
                self._rp_enter_ab(lo, hi)              # A raggiunto: da B
                _tb2 = self._t_at_ld(self._rp_ta, hi)
                if _tb2 is not None:
                    self._rp_t = _tb2
                return
        if _dir < 0 and self._rp_t <= 0.0:
            # inizio giro raggiunto in reverse: pausa sul via
            self._rp_timer.stop()
            self._play.setText("play_arrow")
            return
        if ld_a is None and ld_b is None:              # entrambi al traguardo
            self._stop_play()
            return
        # DELTA accanto alla macchinina (cantiere 23/07): quando il
        # confronto passa dalla STESSA posizione, il distacco e'
        # (tempo mio qui) - (tempo suo qui): + = sono dietro
        _gap9 = None
        if ld_a is not None and self._rp_tb:
            # serie MONOTONA senza il transitorio del traguardo (bug
            # 23/07: i giri partono a lapdist ~5779 PRIMA della linea
            # -> la ricerca inciampava e il gap mostrava 77-102s)
            if getattr(self, "_rp_tb_src", None) != id(self._rp_tb):
                self._rp_tb_src = id(self._rp_tb)
                _mn9, _last9, _st9 = [], -1e9, False
                for _t9, _d9 in self._rp_tb:
                    if not _st9:
                        if _d9 < 200.0:
                            _st9 = True
                        else:
                            continue
                    if _d9 > _last9:
                        _mn9.append((_t9, _d9))
                        _last9 = _d9
                self._rp_tb_mono = _mn9
            _tbl9 = getattr(self, "_rp_tb_mono", None) or []
            _tb9 = self._t_at_ld(_tbl9, ld_a) if len(_tbl9) > 10 else None
            if _tb9 is not None:
                _gap9 = (self._rp_t - _off) - _tb9
                if abs(_gap9) > 30.0:
                    _gap9 = None       # fuori scala: meglio niente
        self.map_w.set_play_pos(ld_a if ld_a is not None else ld_b,
                                ld_b, _gap9)
        # i grafici seguono il giro SELEZIONATO (cursore + readout)
        if ld_a is not None:
            for ch in self.charts:
                ch.set_cursor(ld_a)
            self._update_read(ld_a)
            # SPIA REPLAY: stato del confronto (diagnostica visibile —
            # "B: no data" = serie tempo vuota, "B: end" = giro finito)
            try:
                if not self._rp_tb:
                    _bs = "B: no data"
                elif ld_b is None:
                    _bs = "B: end"
                else:
                    _bs = "B %.0f m" % ld_b
                self._read.setText(
                    self._read.text()
                    + "&nbsp;&nbsp;·&nbsp;&nbsp;"
                      "<b style='color:#f0a23a'>REPLAY · %s</b>" % _bs)
            except Exception:
                pass

    def _delta_series(self, sel_lap, cmp_lap, cmp_con=None):
        """DELTA-T (s) lungo la distanza: (t_sel - t_cmp) con t azzerato a
        inizio giro. Positivo = il giro selezionato PERDE li'. Il confronto
        viene interpolato sulla distanza del selezionato."""
        a = self._series(sel_lap, "t", 1.0)
        b = self._series(cmp_lap, "t", 1.0, con=cmp_con)
        if len(a) < 2 or len(b) < 2:
            return []
        a0 = a[0][1]; b0 = b[0][1]
        out = []
        j = 0
        for x, ta in a:
            while j + 1 < len(b) and b[j + 1][0] <= x:
                j += 1
            if j + 1 >= len(b):
                break
            x1, t1 = b[j]; x2, t2 = b[j + 1]
            if x < x1:
                continue
            tb = t1 + (t2 - t1) * ((x - x1) / (x2 - x1)) if x2 > x1 else t1
            out.append((x, (ta - a0) - (tb - b0)))
        return out

    def _sec_dist(self, lap):
        if lap is None or self.data.con is None:
            return []
        L = self.data._by_id.get(lap, {})
        s1 = L.get("s1") or 0.0; s2 = L.get("s2") or 0.0
        if not s1:
            return []
        try:
            rs = _rows(self.data.con, "SELECT t, lapdist FROM samples "
                                      "WHERE lap=? ORDER BY rowid", (lap,))
        except Exception:
            return []
        b1 = b2 = None
        for r in rs:
            if r["t"] is None or r["lapdist"] is None:
                continue
            if b1 is None and r["t"] >= s1:
                b1 = r["lapdist"]
            if b2 is None and s2 and r["t"] >= s1 + s2:
                b2 = r["lapdist"]; break
        return [d for d in (b1, b2) if d is not None]

    def _xz(self, lap, con=None):
        con = con or self.data.con
        if lap is None or con is None:
            return []
        try:
            rs = _rows(con,
                       "SELECT pos_x, pos_z, lapdist FROM samples WHERE lap=? ORDER BY rowid", (lap,))
        except Exception:
            return []
        return [(r["pos_x"], r["pos_z"], r["lapdist"]) for r in rs
                if r["pos_x"] is not None and r["pos_z"] is not None]

    def set_lap(self, lap):
        self._sel = lap
        self._stop_play()                  # replay legato al giro vecchio
        self._refresh()

    def set_compare(self, lap):
        self._cmp = lap
        self._stop_play()
        self._refresh()

    def _refresh(self):
        self._la = f"Lap {self._sel}" if self._sel is not None else "Selected"
        ref = self.data.cmp_source()
        if ref:
            rcon, rlap, rlabel, rtime, rsecs, gold = ref
            self._lb = rlabel; cmp_lap = rlap; cmp_con = rcon
        else:
            self._lb = f"Lap {self._cmp}" if self._cmp is not None else "Compare"
            cmp_lap = self._cmp; cmp_con = None; gold = False
        secd = self._sec_dist(self._sel)
        _turns = self.map_w.turns_lapdist()      # punti curva sui grafici
        for ch in self.charts:
            ch._turn_marks = _turns
            name, c, unit, scale = ch._ws
            ch._cmp_gold = gold
            if c == "__delta":
                # DELTA-T: curva unica sel-vs-confronto (serve il confronto)
                sel = self._delta_series(self._sel, cmp_lap, cmp_con) \
                    if cmp_lap is not None else []
                cmp = []
            else:
                sel = self._series(self._sel, c, scale)
                cmp = self._series(cmp_lap, c, scale, con=cmp_con) \
                    if cmp_lap is not None else []
            ch.set_laps(sel, cmp, self._la, self._lb, unit, sec_dist=secd)
        self.map_w._cmp_gold = gold
        self.map_w.set_review(self._xz(self._sel),
                              self._xz(cmp_lap, con=cmp_con) if cmp_lap is not None else [],
                              self._la, self._lb)
        # MARKER EVENTI sulla mappa (cantiere 23/07): contatti/tagli/
        # bloccaggi di TUTTA la sessione, layer dalla legenda cliccabile
        try:
            _con9 = getattr(self.data, "con", None)
            if _con9 is not None:
                _ev9 = _con9.execute(
                    "SELECT kind, x, z FROM events"
                    " WHERE x IS NOT NULL AND z IS NOT NULL").fetchall()
                _out9 = [(str(k), float(x), float(z)) for k, x, z in _ev9]
                # SLIDES (perdite di aderenza) DERIVATE dai samples,
                # come TRATTI di strada (rich. 23/07): slip laterale
                # medio >= 3.5 sostenuto -> il PEZZO di pista scivolato
                _segs9 = {"slide": [], "tc": [], "abs": [],
                          "lico": []}
                try:
                    _rows9 = _con9.execute(
                        "SELECT pos_x, pos_z,"
                        " (ABS(slat_fl)+ABS(slat_fr)+ABS(slat_rl)"
                        "  +ABS(slat_rr))/4.0, speed, tc_active,"
                        " abs_active, throttle, brake FROM samples"
                        " WHERE rowid % 3 = 0 ORDER BY rowid").fetchall()
                    _cur9 = {"slide": [], "tc": [], "abs": [],
                             "lico": []}

                    def _push9(k):
                        if len(_cur9[k]) >= 4:      # ~0.5s sostenuto
                            _segs9[k].append(_cur9[k])
                        _cur9[k] = []
                    for _px9, _pz9, _sl9, _sp9, _tc9, _ab9,                             _th9, _br9 in _rows9:
                        _pt9 = (float(_px9), float(_pz9))
                        if (_sl9 or 0.0) >= 3.5 and (_sp9 or 0) > 60.0:
                            _cur9["slide"].append(_pt9)
                        elif (_sl9 or 0.0) < 2.0:
                            _push9("slide")
                        if _tc9:
                            _cur9["tc"].append(_pt9)
                        else:
                            _push9("tc")
                        if _ab9:
                            _cur9["abs"].append(_pt9)
                        else:
                            _push9("abs")
                        # LICO/veleggio: gas e freno a ZERO in velocita'
                        if (_th9 or 0.0) < 0.06 and (_br9 or 0.0) < 0.05                                 and (_sp9 or 0.0) > 80.0:
                            _cur9["lico"].append(_pt9)
                        else:
                            _push9("lico")
                    for _k9 in ("slide", "tc", "abs", "lico"):
                        _push9(_k9)
                except Exception:
                    pass
                self.map_w.set_events(_out9)
                self.map_w.set_event_segs(_segs9)
        except Exception:
            pass
        self._update_read(None)

    def _on_scrub(self, ld):
        if self._rp_timer.isActive():
            return                        # replay attivo: comanda lui
        if getattr(self.map_w, "_play_ld", None) is not None:
            # replay in PAUSA: lo scrub manuale riprende il comando della
            # mappa (il flag play latchato la teneva congelata — il bug)
            self.map_w.set_play_pos(None, None)
        for ch in self.charts:
            ch.set_cursor(ld)
        self.map_w.set_hi_by_lapdist(ld)
        self._update_read(ld)

    def recolor(self):
        for ch in self.charts:
            ch.update()
        self.map_w.update()

    def _update_read(self, ld):
        if ld is None:
            self._read.setText(
                "<span style='color:#838790'>Hover a chart \u2014 one cursor "
                "scrubs all channels</span>")
            return
        parts = ["<b style='color:#f5f5f5'>%.0f m</b>" % ld]
        for ch in self.charts:
            name, c, unit, scale = ch._ws
            v = _TraceChart._val_at(ch._sel, ld)
            if v is not None:
                # formato del canale (Delta/G vogliono i decimali e il segno)
                try:
                    _vt = (ch.yfmt or "{:.0f}").format(v)
                except Exception:
                    _vt = "%.0f" % v
                parts.append("%s <b style='color:#f5f5f5'>%s%s</b>"
                             % (name, _vt, unit))
        self._read.setText("&nbsp;&nbsp;\u00b7&nbsp;&nbsp;".join(parts))

    def recolor(self):
        for ch in self.charts:
            ch.update()


class _TraceTab(QWidget):
    """Tab metrica giro-intero: readout dati + grafico traccia + mappa (confronto).
    Stesso layout/funzioni per Speed/VE/Fuel/Hybrid: cambia solo metrica e dati."""
    def __init__(self, data, col, unit, label, modes=None):
        super().__init__()
        self.data = data
        self._col = col; self._unit = unit; self._label = label
        self._modes = modes or []          # [(testo, col)]
        self._sel = None; self._cmp = None
        self._la = "Selected"; self._lb = "Compare"
        root = QVBoxLayout(self)
        if self._modes:
            from PySide6.QtWidgets import QPushButton as _QPB
            bar = QHBoxLayout(); bar.setSpacing(6)
            lbl = QLabel("Layer:"); lbl.setStyleSheet("color:#989ba2;")
            bar.addWidget(lbl)
            self._mode_btns = {}
            for txt, mc in self._modes:
                b = _QPB(txt); b.setObjectName("modeBtn"); b.setCheckable(True)
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _=False, c=mc: self._set_mode(c))
                self._mode_btns[mc] = b; bar.addWidget(b)
            bar.addStretch()
            self._mode_btns[self._col].setChecked(True)
            root.addLayout(bar)
        self._read = QLabel(""); self._read.setStyleSheet("color:#dcdddf;padding:4px 10px;")
        root.addWidget(self._read)
        roww = QWidget(); rowl = QHBoxLayout(roww); rowl.setContentsMargins(0, 0, 0, 0)
        self.chart = _TraceChart(scrub_cb=self._on_scrub)
        self.map_w = _LiveMap()
        rowl.addWidget(self.chart, 2)
        rowl.addWidget(self.map_w, 1)
        root.addWidget(roww, 1)

    def _set_mode(self, col):
        self._col = col
        for c, b in self._mode_btns.items():
            b.setChecked(c == col)
        self._refresh()

    def _series(self, lap, con=None):
        con = con or self.data.con
        if lap is None or con is None:
            return []
        try:
            rs = _rows(con,
                       f"SELECT lapdist, {self._col} v FROM samples WHERE lap=? ORDER BY rowid", (lap,))
        except Exception:
            return []
        xy = [(r["lapdist"], r["v"]) for r in rs
              if r["lapdist"] is not None and r["v"] is not None]
        xy.sort(key=lambda q: q[0])
        out = []; last = None
        for x, v in xy:
            if last is None or x > last + 1e-6:
                out.append((x, v)); last = x
        return out

    def _xz(self, lap, con=None):
        con = con or self.data.con
        if lap is None or con is None:
            return []
        try:
            rs = _rows(con,
                       "SELECT pos_x, pos_z, lapdist FROM samples WHERE lap=? ORDER BY rowid", (lap,))
        except Exception:
            return []
        return [(r["pos_x"], r["pos_z"], r["lapdist"]) for r in rs
                if r["pos_x"] is not None and r["pos_z"] is not None]

    def _sec_dist(self, lap):
        """Distanze (lapdist) ai confini settore del giro Selected, dai tempi s1/s2."""
        if lap is None or self.data.con is None:
            return []
        L = self.data._by_id.get(lap, {})
        s1 = L.get("s1") or 0.0
        s2 = L.get("s2") or 0.0
        if not s1:
            return []
        try:
            rs = _rows(self.data.con,
                       "SELECT t, lapdist FROM samples WHERE lap=? ORDER BY rowid", (lap,))
        except Exception:
            return []
        b1 = b2 = None
        for r in rs:
            if r["t"] is None or r["lapdist"] is None:
                continue
            if b1 is None and r["t"] >= s1:
                b1 = r["lapdist"]
            if b2 is None and s2 and r["t"] >= s1 + s2:
                b2 = r["lapdist"]; break
        return [d for d in (b1, b2) if d is not None]

    def _refresh(self):
        self._la = f"Lap {self._sel}" if self._sel is not None else "Selected"
        self.chart.set_cursor(None)
        Ls = self.data._by_id.get(self._sel, {}) if self._sel is not None else {}
        ref = self.data.cmp_source()
        self.chart._cmp_gold = (ref[5] if ref else False)
        self.map_w._cmp_gold = (ref[5] if ref else False)
        if ref:
            rcon, rlap, rlabel, rtime, rsecs, gold = ref
            cmp_series = self._series(rlap, con=rcon)
            cmp_xz = self._xz(rlap, con=rcon)
            self._lb = rlabel; lb_time = rtime; lb_secs = rsecs
        else:
            self._lb = f"Lap {self._cmp}" if self._cmp is not None else "Compare"
            Lc = self.data._by_id.get(self._cmp, {}) if self._cmp is not None else {}
            cmp_series = self._series(self._cmp)
            cmp_xz = self._xz(self._cmp)
            lb_time = Lc.get("lap_time")
            lb_secs = [Lc.get("s1"), Lc.get("s2"), Lc.get("s3")]
        self.chart.set_laps(self._series(self._sel), cmp_series,
                            self._la, self._lb, self._unit, sec_dist=self._sec_dist(self._sel),
                            la_time=Ls.get("lap_time"), lb_time=lb_time,
                            la_secs=[Ls.get("s1"), Ls.get("s2"), Ls.get("s3")],
                            lb_secs=lb_secs,
                            best_time=self.data.best_dict().get("lap_time"),
                            best_secs=[self.data.best_dict().get(k) for k in ("s1", "s2", "s3")])
        self.map_w.set_review(self._xz(self._sel), cmp_xz, self._la, self._lb)
        self._update_read(None)

    def _update_read(self, ld):
        def at(series):
            if not series or ld is None:
                return None
            return min(series, key=lambda q: abs(q[0] - ld))[1]
        sa = at(self.chart._sel); sb = at(self.chart._cmp)
        parts = [f"{self._label}  ({self._unit})"]
        if sa is not None:
            parts.append(f"{self._la}: {sa:.1f}")
        if sb is not None:
            parts.append(f"{self._lb}: {sb:.1f}")
            if sa is not None:
                parts.append(f"\u0394 {sa - sb:+.1f}")
        self._read.setText("      ".join(parts))

    def _on_scrub(self, ld):
        self.chart.set_cursor(ld)
        for _ch, _wc, _un in getattr(self, "_wx_charts", []):
            _ch.set_cursor(ld)          # asfalto/rain seguono il cursore come nel Worksheet
        self.map_w.set_hi_by_lapdist(ld)
        self._update_read(ld)

    def set_lap(self, lap):
        self._sel = lap; self._refresh()

    def set_compare(self, lap):
        self._cmp = lap; self._refresh()

    def recolor(self):
        self.chart.update(); self.map_w.update()


class _TyreCorner(QWidget):
    """Simbolo mescola (cerchio S/M/H/W come standings/relative) cliccabile,
    con il valore medio del giro sotto. Evidenziato quando selezionato.
    kind: 'tyre' = mescola; 'brake' = disco freno; 'susp' = sospensione."""
    _BRAKE_SVG = (b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'>"
                  b"<circle cx='12' cy='12' r='9' fill='none' stroke='%s' stroke-width='1.6'/>"
                  b"<circle cx='12' cy='12' r='3.2' fill='none' stroke='%s' stroke-width='1.6'/>"
                  b"<g fill='%s'>"
                  b"<circle cx='12' cy='6.2' r='.8'/><circle cx='16.6' cy='9' r='.8'/>"
                  b"<circle cx='16.6' cy='15' r='.8'/><circle cx='12' cy='17.8' r='.8'/>"
                  b"<circle cx='7.4' cy='15' r='.8'/><circle cx='7.4' cy='9' r='.8'/></g>"
                  b"<rect x='15' y='9.4' width='4' height='5.2' rx='1' fill='%s'/></svg>")
    _SUSP_SVG = (b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'>"
                 b"<g fill='none' stroke='%s' stroke-width='1.6' stroke-linecap='round'"
                 b" stroke-linejoin='round'>"
                 b"<line x1='12' y1='3' x2='12' y2='5'/>"
                 b"<path d='M8 6 H16 L8 9 H16 L8 12 H16 L8 15 H16'/>"
                 b"<line x1='12' y1='16' x2='12' y2='21'/>"
                 b"<line x1='9' y1='21' x2='15' y2='21'/></g></svg>")

    def __init__(self, wheel, on_click, kind="tyre"):
        super().__init__()
        self._wheel = wheel; self._on_click = on_click; self._kind = kind
        self.setObjectName("tyreCorner")
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self); lay.setContentsMargins(6, 4, 6, 4); lay.setSpacing(1)
        self.name = QLabel(wheel.upper()); self.name.setAlignment(Qt.AlignCenter)
        self.name.setObjectName("tyreCornerName")
        lay.addWidget(self.name)
        if kind == "tyre":
            from core.tyre_cell import TyreCircle
            self.circle = TyreCircle(30); self._icon = None
            lay.addWidget(self.circle, 0, Qt.AlignCenter)
        else:
            self.circle = None
            self._icon = _SvgBox(); self._icon.setFixedSize(30, 30)
            lay.addWidget(self._icon, 0, Qt.AlignCenter)
        self.val = QLabel("\u2014"); self.val.setAlignment(Qt.AlignCenter)
        self.val.setObjectName("tyreCornerVal")
        lay.addWidget(self.val)
        self.setFixedSize(60, 72)
        self.set_selected(False)

    def _icon_svg(self, col):
        if self._kind == "brake":
            return self._BRAKE_SVG % (col, col, col, col)
        if self._kind == "susp":
            return self._SUSP_SVG % col
        return b""

    def set_sigla(self, s):
        if self.circle is not None:
            self.circle.set_sigla(s)

    def set_new(self, is_new):
        if self.circle is not None:
            self.circle.set_new(bool(is_new))

    def set_val(self, v):
        self.val.setText(f"{v:.0f}" if v is not None else "\u2014")

    def set_selected(self, on):
        self.setStyleSheet(
            "#tyreCorner{border:none;border-radius:8px;background:#16242a;}"
            "#tyreCornerName{color:#f6f6f6;font-size:11px;font-weight:700;}"
            "#tyreCornerVal{color:#f6f6f6;font-size:11px;font-weight:600;}"
            if on else
            "#tyreCorner{border:none;border-radius:8px;background:transparent;}"
            "#tyreCornerName{color:#a7aaaf;font-size:11px;font-weight:700;}"
            "#tyreCornerVal{color:#a7aaaf;font-size:11px;}")
        if self._icon is not None:
            col = _ACCENT if on else "#a7aaaf"
            self._icon.load(self._icon_svg(col.encode()))

    def mousePressEvent(self, e):
        self._on_click(self._wheel)


class _PedalsTab(QWidget):
    """Pedali (throttle/brake) vs distanza + mappa. Selected vs Compare/REF.
    Sostituisce la vecchia tab Times (i tempi/settori stanno nell'Overview)."""
    def __init__(self, data):
        super().__init__()
        self.data = data
        self._sel = None; self._cmp = None
        self._la = "Selected"; self._lb = "Compare"
        self.chart = None                     # escluso dalla sincro zoom/AB
        root = QVBoxLayout(self)
        self._read = QLabel(""); self._read.setStyleSheet("color:#dcdddf;padding:4px 10px;")
        root.addWidget(self._read)
        roww = QWidget(); rowl = QHBoxLayout(roww); rowl.setContentsMargins(0, 0, 0, 0)
        self.pedal = _PedalChart(scrub_cb=self._on_scrub)
        self.map_w = _LiveMap()
        rowl.addWidget(self.pedal, 2)
        rowl.addWidget(self.map_w, 1)
        root.addWidget(roww, 1)

    def _pts(self, lap, con=None):
        con = con or self.data.con
        if lap is None or con is None:
            return []
        try:
            rs = _rows(con, "SELECT lapdist, throttle, brake FROM samples "
                            "WHERE lap=? ORDER BY rowid", (lap,))
        except Exception:
            return []
        xy = [(r["lapdist"], r["throttle"], r["brake"]) for r in rs
              if r["lapdist"] is not None]
        xy.sort(key=lambda p: p[0]); out = []; last = None
        for x, t, b in xy:
            if last is None or x > last + 1e-6:
                out.append((x, t, b)); last = x
        return out

    def _xz(self, lap, con=None):
        con = con or self.data.con
        if lap is None or con is None:
            return []
        try:
            rs = _rows(con, "SELECT pos_x, pos_z, lapdist FROM samples "
                            "WHERE lap=? ORDER BY rowid", (lap,))
        except Exception:
            return []
        return [(r["pos_x"], r["pos_z"], r["lapdist"]) for r in rs
                if r["pos_x"] is not None and r["pos_z"] is not None]

    def _sec_dist(self, lap):
        if lap is None or self.data.con is None:
            return []
        L = self.data._by_id.get(lap, {})
        s1 = L.get("s1") or 0.0; s2 = L.get("s2") or 0.0
        if not s1:
            return []
        try:
            rs = _rows(self.data.con, "SELECT t, lapdist FROM samples "
                                      "WHERE lap=? ORDER BY rowid", (lap,))
        except Exception:
            return []
        b1 = b2 = None
        for r in rs:
            if r["t"] is None or r["lapdist"] is None:
                continue
            if b1 is None and r["t"] >= s1:
                b1 = r["lapdist"]
            if b2 is None and s2 and r["t"] >= s1 + s2:
                b2 = r["lapdist"]; break
        return [d for d in (b1, b2) if d is not None]

    def _refresh(self):
        self._la = f"Lap {self._sel}" if self._sel is not None else "Selected"
        self.pedal.set_cursor(None)
        Ls = self.data._by_id.get(self._sel, {}) if self._sel is not None else {}
        ref = self.data.cmp_source()
        self.map_w._cmp_gold = (ref[5] if ref else False)
        if ref:
            rcon, rlap, rlabel, rtime, rsecs, gold = ref
            cmp_pts = self._pts(rlap, con=rcon); cmp_xz = self._xz(rlap, con=rcon)
            self._lb = rlabel; lb_time = rtime; lb_secs = rsecs
        else:
            self._lb = f"Lap {self._cmp}" if self._cmp is not None else "Compare"
            Lc = self.data._by_id.get(self._cmp, {}) if self._cmp is not None else {}
            cmp_pts = self._pts(self._cmp); cmp_xz = self._xz(self._cmp)
            lb_time = Lc.get("lap_time")
            lb_secs = [Lc.get("s1"), Lc.get("s2"), Lc.get("s3")]
        self.pedal.set_laps(self._pts(self._sel), cmp_pts, self._la, self._lb,
                            sec_dist=self._sec_dist(self._sel),
                            la_time=Ls.get("lap_time"), lb_time=lb_time,
                            la_secs=[Ls.get("s1"), Ls.get("s2"), Ls.get("s3")],
                            lb_secs=lb_secs,
                            best_time=self.data.best_dict().get("lap_time"),
                            best_secs=[self.data.best_dict().get(k) for k in ("s1", "s2", "s3")])
        self.map_w.set_review(self._xz(self._sel), cmp_xz, self._la, self._lb)
        self._update_read(None)

    def _update_read(self, ld):
        def at(series):
            if not series or ld is None:
                return None
            return min(series, key=lambda q: abs(q[0] - ld))
        sa = at(self.pedal._sel); sb = at(self.pedal._cmp)
        parts = ["Pedals  (throttle / brake %)"]
        if sa is not None:
            parts.append(f"{self._la}: T {sa[1]*100:.0f}  B {sa[2]*100:.0f}")
        if sb is not None:
            parts.append(f"{self._lb}: T {sb[1]*100:.0f}  B {sb[2]*100:.0f}")
        self._read.setText("      ".join(parts))

    def _on_scrub(self, ld):
        self.pedal.set_cursor(ld)
        self.map_w.set_hi_by_lapdist(ld)
        self._update_read(ld)

    def set_lap(self, lap):
        self._sel = lap; self._refresh()

    def set_compare(self, lap):
        self._cmp = lap; self._refresh()

    def recolor(self):
        self.pedal.update(); self.map_w.update()


class _TyresTab(QWidget):
    """Vista gomme PER RUOTA: 4 angoli (FL/FR/RL/RR) cliccabili, ognuno col suo
    grafico. Selettore strato (Surface/Carcass/Inner/Press). Confronto sel/cmp."""
    _LAYERS = [("Surface", "ts"), ("Carcass", "t"), ("Inner", "ti"),
               ("Press", "p"), ("Wear", "w")]
    _WHEELS = [("FL", "fl"), ("FR", "fr"), ("RL", "rl"), ("RR", "rr")]

    def __init__(self, data):
        super().__init__()
        self.data = data
        self._sel = None; self._cmp = None
        self._wheel = "fl"; self._layer = "ts"
        root = QVBoxLayout(self)
        self.chart = _TraceChart(scrub_cb=self._on_scrub)
        self.map_w = _LiveMap()
        top = QHBoxLayout(); top.setSpacing(10)
        ch = QHBoxLayout(); ch.setSpacing(8)
        self._corner = {}
        for lab, w in self._WHEELS:
            cc = _TyreCorner(w, self._set_wheel, getattr(self, "_CORNER_KIND", "tyre"))
            ch.addWidget(cc); self._corner[w] = cc
        self._corner["fl"].set_selected(True)
        cwrap = QWidget(); cwrap.setLayout(ch); top.addWidget(cwrap)
        top.addStretch()
        self._read = QLabel(""); self._read.setObjectName("tyreRead")
        self._read.setStyleSheet("color:#dcdddf;padding:2px 4px;")
        self._read.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self._read)
        root.addLayout(top)
        # selettore strato come TAB eleganti sopra il grafico
        self._lbar = QTabBar(); self._lbar.setObjectName("layerTabs")
        self._lbar.setExpanding(False); self._lbar.setDrawBase(False)
        self._lbar.setCursor(Qt.PointingHandCursor)
        for lab, ly in self._LAYERS:
            self._lbar.addTab(lab)
        self._lbar.setStyleSheet(
            "QTabBar#layerTabs{qproperty-drawBase:0;}"
            "QTabBar#layerTabs::tab{background:transparent;color:#a6a9af;"
            "padding:4px 12px;margin-right:2px;border:0;font-size:12px;"
            "border-bottom:2px solid transparent;font-weight:400;}"
            "QTabBar#layerTabs::tab:hover{color:%s;}"
            "QTabBar#layerTabs::tab:selected{color:%s;border-bottom:2px solid %s;}"
            % (_FG, _FG, _ACCENT))
        self._lbar.currentChanged.connect(self._on_layer_idx)
        root.addWidget(self._lbar)
        roww = QWidget(); rowl = QHBoxLayout(roww)
        rowl.setContentsMargins(0, 0, 0, 0); rowl.setSpacing(8)
        _wlss = ("color:#989ba2;font-size:11px;font-weight:700;"
                 "padding:2px 0 0 2px;background:transparent;")
        _leftcol = QVBoxLayout(); _leftcol.setContentsMargins(0, 0, 0, 0); _leftcol.setSpacing(8)
        self._wx_charts = []

        def _stack(_lab_txt, _chart):
            _w = QWidget(); _v = QVBoxLayout(_w)
            _v.setContentsMargins(0, 0, 0, 0); _v.setSpacing(2)
            _l = QLabel(_lab_txt); _l.setStyleSheet(_wlss)
            _chart.setMinimumHeight(110); _chart.setMaximumHeight(16777215)
            _v.addWidget(_l); _v.addWidget(_chart, 1)
            _leftcol.addWidget(_w, 1)

        _stack("Gomma", self.chart)
        for _nm, _wcol_name, _un in (("Asfalto", "track_temp", "\u00b0C"),
                                     ("Rain", "rain_pct", "%")):
            _ch = _TraceChart(scrub_cb=self._on_scrub); _ch.yfmt = "{:.0f}"
            _stack(f"{_nm} {_un}", _ch)
            self._wx_charts.append((_ch, _wcol_name, _un))

        _lwrap = QWidget(); _lwrap.setLayout(_leftcol)
        rowl.addWidget(_lwrap, 3); rowl.addWidget(self.map_w, 1)
        root.addWidget(roww, 1)
        self._lbar.setCurrentIndex(0)

    @property
    def _col(self):
        return f"tyre_{self._layer}_{self._wheel}"

    @property
    def _unit(self):
        return {"p": "kPa", "w": "%"}.get(self._layer, "\u00b0C")

    def _set_wheel(self, w):
        self._wheel = w
        for k, cc in self._corner.items():
            cc.set_selected(k == w)
        self._refresh()

    def _on_layer_idx(self, i):
        if 0 <= i < len(self._LAYERS):
            self._layer = self._LAYERS[i][1]
            self._refresh()

    def _series(self, lap, con=None):
        con = con or self.data.con
        if lap is None or con is None:
            return []
        try:
            rs = _rows(con,
                       f"SELECT lapdist, {self._col} v FROM samples WHERE lap=? ORDER BY rowid", (lap,))
        except Exception:
            return []                       # file vecchio senza canali per ruota
        xy = [(r["lapdist"], r["v"]) for r in rs
              if r["lapdist"] is not None and r["v"] is not None]
        xy.sort(key=lambda q: q[0])
        out = []; last = None
        for x, v in xy:
            if last is None or x > last + 1e-6:
                out.append((x, v)); last = x
        return out

    def _series_col(self, lap, col, con=None):
        con = con or self.data.con
        if lap is None or con is None:
            return []
        try:
            rs = _rows(con,
                       f"SELECT lapdist, {col} v FROM samples WHERE lap=? ORDER BY rowid", (lap,))
        except Exception:
            return []                       # file vecchio senza il canale meteo
        xy = [(r["lapdist"], r["v"]) for r in rs
              if r["lapdist"] is not None and r["v"] is not None]
        xy.sort(key=lambda q: q[0])
        out = []; last = None
        for x, v in xy:
            if last is None or x > last + 1e-6:
                out.append((x, v)); last = x
        return out

    def _xz(self, lap, con=None):
        con = con or self.data.con
        if lap is None or con is None:
            return []
        try:
            rs = _rows(con,
                       "SELECT pos_x, pos_z, lapdist FROM samples WHERE lap=? ORDER BY rowid", (lap,))
        except Exception:
            return []
        return [(r["pos_x"], r["pos_z"], r["lapdist"]) for r in rs
                if r["pos_x"] is not None and r["pos_z"] is not None]

    def _sec_dist(self, lap):
        if lap is None or self.data.con is None:
            return []
        L = self.data._by_id.get(lap, {})
        s1 = L.get("s1") or 0.0; s2 = L.get("s2") or 0.0
        if not s1:
            return []
        try:
            rs = _rows(self.data.con,
                       "SELECT t, lapdist FROM samples WHERE lap=? ORDER BY rowid", (lap,))
        except Exception:
            return []
        b1 = b2 = None
        for r in rs:
            if r["t"] is None or r["lapdist"] is None:
                continue
            if b1 is None and r["t"] >= s1:
                b1 = r["lapdist"]
            if b2 is None and s2 and r["t"] >= s1 + s2:
                b2 = r["lapdist"]; break
        return [d for d in (b1, b2) if d is not None]

    def _refresh(self):
        la = f"Lap {self._sel}" if self._sel is not None else "Selected"
        self.chart.set_cursor(None)
        self.chart.baseline = None; self.chart.yfmt = "{:.0f}"
        ref = self.data.cmp_source()
        self.chart._cmp_gold = (ref[5] if ref else False)
        self.map_w._cmp_gold = (ref[5] if ref else False)
        if ref:
            rcon, rlap, rlabel, rtime, rsecs, gold = ref
            lb = rlabel
            cmp_series = self._series(rlap, con=rcon)
            cmp_xz = self._xz(rlap, con=rcon)
        else:
            lb = f"Lap {self._cmp}" if self._cmp is not None else "Compare"
            cmp_series = self._series(self._cmp)
            cmp_xz = self._xz(self._cmp)
        self.chart.set_laps(self._series(self._sel), cmp_series,
                            la, lb, self._unit, sec_dist=self._sec_dist(self._sel))
        self.map_w.set_review(self._xz(self._sel), cmp_xz, la, lb)
        _cmp_lap = rlap if ref else self._cmp
        _cmp_con = rcon if ref else self.data.con
        for _ch, _wc, _un in getattr(self, "_wx_charts", []):
            _ch._cmp_gold = (ref[5] if ref else False)   # dry=oro, wet=azzurro
            _ch.set_laps(self._series_col(self._sel, _wc),
                         self._series_col(_cmp_lap, _wc, con=_cmp_con),
                         la, lb, _un)
        self._update_corners()
        self._update_read(None)

    def _compounds4(self):
        out = {"fl": "", "fr": "", "rl": "", "rr": ""}
        if self.data.con is None:
            return out
        try:
            rs = _rows(self.data.con, "SELECT compounds4 FROM session_meta WHERE id=1")
            parts = [x.strip() for x in ((rs[0]["compounds4"] if rs else "") or "").split(",")]
            for i, w in enumerate(("fl", "fr", "rl", "rr")):
                if i < len(parts):
                    out[w] = parts[i]
        except Exception:
            pass
        return out

    def _update_corners(self):
        comp = self._compounds4()              # fallback: metadati sessione (file vecchi)
        # treno NUOVO/USATO a inizio stint (>=97 al primo giro registrato)
        wstate = {"fl": None, "fr": None, "rl": None, "rr": None}
        lap_comp = None
        if self._sel is not None and self.data.con is not None:
            try:
                # NUOVA/USATA = stato MIGLIORE del treno nello stint (MAX
                # usura). Il primo giro puo' essere la formazione/allineamento
                # al via, gia' consumato di qualche punto: un treno montato
                # nuovo lo si riconosce dal picco, non dal giro sporco iniziale.
                rr = _rows(self.data.con,
                           "SELECT MAX(w_fl) w_fl, MAX(w_fr) w_fr, "
                           "MAX(w_rl) w_rl, MAX(w_rr) w_rr FROM laps "
                           "WHERE stint=(SELECT stint FROM laps WHERE lap=?) "
                           "AND w_fl IS NOT NULL",
                           (self._sel,))
                if not rr or rr[0]["w_fl"] is None:
                    rr = _rows(self.data.con,
                               "SELECT w_fl,w_fr,w_rl,w_rr FROM laps WHERE lap=?",
                               (self._sel,))
                if rr:
                    r0 = rr[0]
                    for w in ("fl", "fr", "rl", "rr"):
                        wstate[w] = r0[f"w_{w}"]
            except Exception:
                pass
            # mescola del giro selezionato (per-stint). Isolata: se la colonna non
            # c'è (file vecchio) si ripiega sui metadati di sessione.
            try:
                cr = _rows(self.data.con,
                           "SELECT compounds4 FROM laps WHERE lap=?", (self._sel,))
                _c4 = (cr[0]["compounds4"] or "").strip() if cr else ""
                if _c4:
                    parts = [x.strip() for x in _c4.split(",")]
                    lap_comp = {w: (parts[i] if i < len(parts) else "")
                                for i, w in enumerate(("fl", "fr", "rl", "rr"))}
            except Exception:
                lap_comp = None
        use_comp = lap_comp if lap_comp else comp
        for lab, w in self._WHEELS:
            self._corner[w].set_sigla(use_comp.get(w, ""))
            _ws = wstate.get(w)
            self._corner[w].set_new(_ws is None or _ws >= 90.0)
            val = None
            if self._sel is not None and self.data.con is not None:
                try:
                    rs = _rows(self.data.con,
                               f"SELECT AVG(tyre_{self._layer}_{w}) a FROM samples WHERE lap=?",
                               (self._sel,))
                    val = rs[0]["a"] if rs else None
                except Exception:
                    val = None
            self._corner[w].set_val(val)
            self._corner[w].set_selected(w == self._wheel)

    def _update_read(self, ld):
        def at(series):
            if not series or ld is None:
                return None
            return min(series, key=lambda q: abs(q[0] - ld))[1]
        sa = at(self.chart._sel); sb = at(self.chart._cmp)
        name = dict(self._WHEELS)[self._wheel] if self._wheel in dict(self._WHEELS) else self._wheel.upper()
        lyr = dict((v, k) for k, v in self._LAYERS).get(self._layer, self._layer)
        parts = [f"{self._wheel.upper()} {lyr}  ({self._unit})"]
        if sa is not None:
            parts.append(f"Selected: {sa:.1f}")
        if sb is not None:
            parts.append(f"Compare: {sb:.1f}")
            if sa is not None:
                parts.append(f"\u0394 {sa - sb:+.1f}")
        self._read.setText("      ".join(parts))

    def _on_scrub(self, ld):
        self.chart.set_cursor(ld)
        for _ch, _wc, _un in getattr(self, "_wx_charts", []):
            _ch.set_cursor(ld)          # asfalto/rain seguono il cursore come nel Worksheet
        self.map_w.set_hi_by_lapdist(ld)
        self._update_read(ld)

    def set_lap(self, lap):
        self._sel = lap; self._refresh()

    def set_compare(self, lap):
        self._cmp = lap; self._refresh()

    def recolor(self):
        ref = self.data.cmp_source()
        _g = (ref[5] if ref else False)
        self.chart._cmp_gold = _g
        self.map_w._cmp_gold = _g
        self.chart.update(); self.map_w.update()
        for _ch, _wc, _un in getattr(self, "_wx_charts", []):
            _ch._cmp_gold = _g          # asfalto/rain seguono il REF (dry oro / wet azzurro)
            _ch.update()


class _BrakesTab(_TyresTab):
    """Freni PER RUOTA (FL/FR/RL/RR): temperatura disco o pressione freno."""
    _LAYERS = [("Temp", "t"), ("Pressure", "p")]
    _COLMAP = {"t": "brake_t", "p": "brake_p"}
    _CORNER_KIND = "brake"

    def __init__(self, data):
        super().__init__(data)
        self._layer = "t"
        try:
            self._lbar.setCurrentIndex(0)
        except Exception:
            pass
        self._refresh()

    @property
    def _col(self):
        return f"{self._COLMAP.get(self._layer, 'brake_t')}_{self._wheel}"

    @property
    def _unit(self):
        return "%" if self._layer == "p" else "\u00b0C"

    def _update_corners(self):
        pref = self._COLMAP.get(self._layer, "brake_t")
        for lab, w in self._WHEELS:
            self._corner[w].set_sigla("")          # i freni non hanno mescola
            val = None
            if self._sel is not None and self.data.con is not None:
                try:
                    rs = _rows(self.data.con,
                               f"SELECT AVG({pref}_{w}) a FROM samples WHERE lap=?",
                               (self._sel,))
                    val = rs[0]["a"] if rs else None
                except Exception:
                    val = None
            self._corner[w].set_val(val)
            self._corner[w].set_selected(w == self._wheel)


class _SuspTab(_TyresTab):
    """Sospensioni PER RUOTA: altezza da terra (ride height) o deflessione (mm).
    In piu' gli ASSI: FRONT/REAR = media delle due ruote (espressione SQL,
    stessi dati per campione), per leggere pitch/rake e appoggi per asse."""
    _LAYERS = [("Ride height", "rh"), ("Deflection", "sd")]
    _COLMAP = {"rh": "ride_h", "sd": "susp_d"}
    _CORNER_KIND = "susp"
    _AX_OFF = ("QPushButton{color:#a6a9af;background:rgba(255,255,255,0.07);"
               "border:none;border-radius:12px;padding:3px 12px;"
               "font-size:11px;font-weight:700;}"
               "QPushButton:hover{color:#ffffff;}")
    _AX_ON = ("QPushButton{color:#ffffff;background:rgba(255,29,67,0.55);"
              "border:none;border-radius:12px;padding:3px 12px;"
              "font-size:11px;font-weight:700;}")

    def __init__(self, data):
        super().__init__(data)
        self._layer = "rh"
        # bottoni ASSE accanto ai 4 angoli ruota
        self._ax_btns = {}
        try:
            _chl = self._corner["rr"].parentWidget().layout()
            for lab, key in (("FRONT", "front"), ("REAR", "rear")):
                b = QPushButton(lab)
                b.setCursor(Qt.PointingHandCursor)
                b.setFixedHeight(24)
                b.setStyleSheet(self._AX_OFF)
                b.clicked.connect(lambda _=False, k=key: self._set_wheel(k))
                _chl.addWidget(b)
                self._ax_btns[key] = b
        except Exception:
            self._ax_btns = {}
        try:
            self._lbar.setCurrentIndex(0)
        except Exception:
            pass
        self._refresh()

    def _set_wheel(self, w):
        self._wheel = w
        for k, cc in self._corner.items():
            cc.set_selected(k == w)
        for k, b in self._ax_btns.items():
            b.setStyleSheet(self._AX_ON if k == w else self._AX_OFF)
        self._refresh()

    @property
    def _col(self):
        pref = self._COLMAP.get(self._layer, "ride_h")
        if self._wheel == "front":
            return f"(({pref}_fl+{pref}_fr)/2.0)"
        if self._wheel == "rear":
            return f"(({pref}_rl+{pref}_rr)/2.0)"
        return f"{pref}_{self._wheel}"

    @property
    def _unit(self):
        return "mm"

    def _update_corners(self):
        pref = self._COLMAP.get(self._layer, "ride_h")
        for lab, w in self._WHEELS:
            self._corner[w].set_sigla("")
            val = None
            if self._sel is not None and self.data.con is not None:
                try:
                    rs = _rows(self.data.con,
                               f"SELECT AVG({pref}_{w}) a FROM samples WHERE lap=?",
                               (self._sel,))
                    val = rs[0]["a"] if rs else None
                except Exception:
                    val = None
            self._corner[w].set_val(val)
            self._corner[w].set_selected(w == self._wheel)


class _GGCanvas(QWidget):
    """Diagramma G-G: g laterale (x) vs g longitudinale (y)."""
    def __init__(self):
        super().__init__()
        self._sel = []; self._cmp = []; self._cmp_gold = False
        self.setMinimumHeight(220)

    def set_points(self, sel, cmp, cmp_gold=False):
        self._sel = sel or []; self._cmp = cmp or []
        self._cmp_gold = bool(cmp_gold); self.update()

    def paintEvent(self, ev):
        from PySide6.QtCore import QPointF
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        w = self.width(); h = self.height()
        p.fillRect(self.rect(), QColor(9, 13, 20, 150))
        cx = w / 2.0; cy = h / 2.0
        R = min(w, h) / 2.0 - 22
        if R <= 0:
            p.end(); return
        gmax = 4.0
        p.setPen(QPen(QColor("#282a2e"), 1))
        for g in (1, 2, 3, 4):
            r = R * g / gmax
            p.drawEllipse(QPointF(cx, cy), r, r)
        p.drawLine(int(cx - R), int(cy), int(cx + R), int(cy))
        p.drawLine(int(cx), int(cy - R), int(cx), int(cy + R))
        p.setPen(QColor("#6e727b"))
        p.drawText(int(cx + R - 8), int(cy - 4), "Lat")
        p.drawText(int(cx + 4), int(cy - R + 12), "Accel")
        p.drawText(int(cx + 4), int(cy + R - 2), "Brake")
        for g in (1, 2, 3, 4):
            p.drawText(int(cx + R * g / gmax - 6), int(cy + 12), f"{g}")

        def plot(pts, col):
            p.setPen(Qt.NoPen); p.setBrush(QColor(col))
            for glat, glong in pts:
                x = cx + R * max(-gmax, min(gmax, glat)) / gmax
                y = cy - R * max(-gmax, min(gmax, glong)) / gmax
                p.drawEllipse(QPointF(x, y), 1.7, 1.7)
        plot(self._cmp, _cmp_col(self._cmp_gold))
        plot(self._sel, _sel_col())
        p.end()


class _GGTab(QWidget):
    """Diagramma G-G (accelerazioni). Selected vs Compare/REF."""
    def __init__(self, data):
        super().__init__()
        self.data = data
        self._sel = None; self._cmp = None
        self.chart = None; self.map_w = None
        root = QVBoxLayout(self)
        self._read = QLabel("G-G  \u00b7  lateral vs longitudinal (g)")
        self._read.setStyleSheet("color:#989ba2;padding:4px 10px;")
        root.addWidget(self._read)
        self.canvas = _GGCanvas()
        root.addWidget(self.canvas, 1)

    def _pts(self, lap, con=None):
        con = con or self.data.con
        if lap is None or con is None:
            return []
        try:
            rs = _rows(con, "SELECT g_lat, g_long FROM samples "
                            "WHERE lap=? ORDER BY rowid", (lap,))
        except Exception:
            return []
        return [(r["g_lat"], r["g_long"]) for r in rs
                if r["g_lat"] is not None and r["g_long"] is not None]

    def _refresh(self):
        ref = self.data.cmp_source()
        if ref:
            rcon, rlap = ref[0], ref[1]
            cmp = self._pts(rlap, con=rcon); gold = ref[5]
        else:
            cmp = self._pts(self._cmp); gold = False
        self.canvas.set_points(self._pts(self._sel), cmp, gold)

    def set_lap(self, lap):
        self._sel = lap; self._refresh()

    def set_compare(self, lap):
        self._cmp = lap; self._refresh()

    def recolor(self):
        self.canvas.update()


class _StintTab(QWidget):
    """Lista giri dello stint (come nella live): Lap/Time/S1/S2/S3/VE/Fuel.
    La riga Selected/Compare è evidenziata."""
    def __init__(self, data):
        super().__init__()
        self.data = data
        self._sel = None; self._cmp = None
        root = QVBoxLayout(self)
        self.tbl = QTableWidget(); self.tbl.setColumnCount(7)
        self.tbl.setHorizontalHeaderLabels(["Lap", "Time", "S1", "S2", "S3", "VE %", "Fuel L"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setFocusPolicy(Qt.NoFocus)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl.setShowGrid(False); self.tbl.setAlternatingRowColors(True)
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        root.addWidget(self.tbl)
        self.theo = QLabel("Theoretical best  \u2014")
        self.theo.setObjectName("stintTheo")
        self.theo.setStyleSheet(
            "#stintTheo{color:#dcdddf;font-size:13px;font-weight:600;padding:8px 4px 2px;}")
        root.addWidget(self.theo)

    def _rebuild(self):
        ids = list(self.data.lap_ids or [])
        self.tbl.setRowCount(len(ids))

        def it(txt):
            w = QTableWidgetItem(txt); w.setTextAlignment(Qt.AlignCenter); return w

        for r, lap in enumerate(ids):
            L = self.data._by_id.get(lap, {})
            lt = L.get("lap_time") or 0
            self.tbl.setItem(r, 0, it(str(lap)))
            self.tbl.setItem(r, 1, it(_fmt(lt) if lt > 0 else "\u2014"))
            self.tbl.setItem(r, 2, it(_fmt(L.get("s1"))))
            self.tbl.setItem(r, 3, it(_fmt(L.get("s2"))))
            self.tbl.setItem(r, 4, it(_fmt(L.get("s3"))))
            self.tbl.setItem(r, 5, it(_f2(L.get("ve_used"))))
            self.tbl.setItem(r, 6, it(_f2(L.get("fuel_used"))))
        # best tempo e best settori in fuxia
        valid = [self.data._by_id.get(l, {}) for l in ids]

        def _best(key):
            vals = [L.get(key) for L in valid
                    if (L.get(key) or 0) > 0 and not L.get("invalid")]
            return min(vals) if vals else None
        bt = _best("lap_time"); b1 = _best("s1"); b2 = _best("s2"); b3 = _best("s3")
        if b1 and b2 and b3:
            theo = b1 + b2 + b3
            extra = ""
            if bt and theo < bt:
                extra = f"   ( -{_fmt(bt - theo)} vs best )"
            self.theo.setText(
                f"Theoretical best  {_fmt(theo)}   "
                f"=  {_fmt(b1)} + {_fmt(b2)} + {_fmt(b3)}{extra}")
        else:
            self.theo.setText("Theoretical best  \u2014")
        for r, lap in enumerate(ids):
            L = self.data._by_id.get(lap, {})
            for c, key, b in ((1, "lap_time", bt), (2, "s1", b1), (3, "s2", b2), (4, "s3", b3)):
                itm = self.tbl.item(r, c)
                if itm is not None and b is not None and (L.get(key) or 0) == b:
                    itm.setForeground(QBrush(QColor(_FUX)))
        self._highlight()

    def _highlight(self):
        ids = list(self.data.lap_ids or [])
        _best_id = None; _best_t = None
        for lap in ids:
            t = (self.data._by_id.get(lap, {}) or {}).get("lap_time")
            if t and (_best_t is None or t < _best_t):
                _best_t = t; _best_id = lap
        for r, lap in enumerate(ids):
            bg = None
            if lap == self._sel or lap == self._cmp:
                bg = QColor(_FUX if lap == _best_id else _SEL_COL)
            for c in range(self.tbl.columnCount()):
                itm = self.tbl.item(r, c)
                if itm is None:
                    continue
                if bg is not None:
                    b = QColor(bg); b.setAlpha(55); itm.setBackground(b)
                else:
                    itm.setBackground(QColor(0, 0, 0, 0))

    def set_lap(self, lap):
        self._sel = lap; self._rebuild()

    def set_compare(self, lap):
        self._cmp = lap; self._highlight()

    def recolor(self):
        self._highlight()


class _CatTable(QWidget):
    """Tab di una sola categoria: caption | Selected | Compare.
    Sfondo pulito, testo bianco; temperature heat; best stint in fuxia.
    Sotto la tabella un grafico di confronto Selected (rosso) vs Compare (viola):
    selezionando una riga si traccia quel dato (continuo sul giro per i canali
    campionati, 3 punti S1/S2/S3 per i dati per-settore)."""
    def __init__(self, data, metrics, show_chart=True, tyre_modes=False, pedal=False):
        super().__init__()
        self.data = data
        self.metrics = metrics
        root = QVBoxLayout(self)

        self._mode_btns = {}
        if tyre_modes:
            bar = QHBoxLayout(); bar.setSpacing(6)
            lbl = QLabel("Temp:"); lbl.setStyleSheet("color:#989ba2;")
            bar.addWidget(lbl)
            for key, txt in (("t_", "Carcass"), ("ti_", "Layer"), ("ts_", "Tread")):
                b = QPushButton(txt); b.setObjectName("modeBtn"); b.setCheckable(True)
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _=False, k=key: self._set_tyre_mode(k))
                self._mode_btns[key] = b; bar.addWidget(b)
            bar.addStretch()
            self._mode_btns[self.data.tyre_mode].setChecked(True)
            root.addLayout(bar)

        self.tbl = _FitTable() if pedal else QTableWidget()
        self.tbl.setColumnCount(3)
        self.tbl.setShowGrid(False)
        self.tbl.setHorizontalHeaderLabels(["", "Selected", "Compare"])
        self.tbl.verticalHeader().setVisible(False)
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setFocusPolicy(Qt.NoFocus)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setRowCount(len(metrics))
        for r, name in enumerate(metrics):
            ki = QTableWidgetItem(name)
            ki.setForeground(QBrush(QColor("#dcdddf")))
            if name in ("Stint", "Lap", "Valid"):
                ki.setFlags(ki.flags() & ~Qt.ItemIsSelectable)
            self.tbl.setItem(r, 0, ki)
        root.addWidget(self.tbl)

        # grafico di confronto sempre presente: selezionando una riga si traccia
        self.tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.itemSelectionChanged.connect(self._on_row)
        if show_chart:
            self.chart = _CmpChart()
            root.addWidget(self.chart)
            root.setStretch(0, 3); root.setStretch(1, 2)
        else:
            self.chart = None
            # niente selezione riga nella tab Times: l'evidenziazione di Qt
            # sovrascriverebbe il colore della cella (il fuxia del best).
            self.tbl.setSelectionMode(QAbstractItemView.NoSelection)
        self.pedal = None
        self.map_w = None
        if pedal:
            self.tbl.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.tbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            cap = QLabel("Pedals (scrub on map)  ·  selected lap")
            cap.setStyleSheet("color:#989ba2;padding:6px 2px 0;")
            root.addWidget(cap)
            roww = QWidget(); rowl = QHBoxLayout(roww); rowl.setContentsMargins(0, 0, 0, 0)
            self.pedal = _PedalChart(scrub_cb=self._on_scrub)
            self.map_w = _LiveMap()              # solo display: dot guidato dal grafico
            rowl.addWidget(self.pedal, 2)        # pedali 2/3
            rowl.addWidget(self.map_w, 1)        # mappa 1/3
            root.addWidget(roww, 1)
        # riga di default = prima riga con un valore (non Stint/Lap/Valid)
        self._def_row = next((i for i, m in enumerate(metrics)
                              if m not in ("Stint", "Lap", "Valid")), -1)

        self._sel = None
        self._cmp = None

    def _pedal_pts(self, lap):
        if lap is None or self.data.con is None:
            return []
        try:
            rs = _rows(self.data.con,
                       "SELECT lapdist, throttle, brake FROM samples WHERE lap=? ORDER BY rowid", (lap,))
        except Exception:
            return []
        xy = [(r["lapdist"], r["throttle"], r["brake"]) for r in rs if r["lapdist"] is not None]
        xy.sort(key=lambda p: p[0])
        clean = []; last = None
        for x, t, b in xy:
            if last is None or x > last + 1e-6:
                clean.append((x, t, b)); last = x
        return clean

    def _sec_dist_for(self, lap):
        """Distanze (lapdist) ai confini settore del giro, dai tempi s1/s2."""
        if lap is None or self.data.con is None:
            return []
        L = self.data._by_id.get(lap, {})
        s1 = L.get("s1") or 0.0
        s2 = L.get("s2") or 0.0
        if not s1:
            return []
        try:
            rs = _rows(self.data.con,
                       "SELECT t, lapdist FROM samples WHERE lap=? ORDER BY rowid", (lap,))
        except Exception:
            return []
        b1 = b2 = None
        for r in rs:
            if r["t"] is None or r["lapdist"] is None:
                continue
            if b1 is None and r["t"] >= s1:
                b1 = r["lapdist"]
            if b2 is None and s2 and r["t"] >= s1 + s2:
                b2 = r["lapdist"]; break
        return [d for d in (b1, b2) if d is not None]

    def _on_scrub(self, lapdist):
        if self.pedal is not None:
            self.pedal.set_cursor(lapdist)
        if self.map_w is not None:
            self.map_w.set_hi_by_lapdist(lapdist)

    def _track_xz(self, lap):
        if lap is None or self.data.con is None:
            return []
        try:
            rs = _rows(self.data.con,
                       "SELECT pos_x, pos_z, lapdist FROM samples WHERE lap=? ORDER BY rowid", (lap,))
        except Exception:
            return []
        return [(r["pos_x"], r["pos_z"], r["lapdist"]) for r in rs
                if r["pos_x"] is not None and r["pos_z"] is not None]

    def _refresh_pedal(self):
        if self.pedal is None:
            return
        self.tbl.updateGeometry()
        la = f"Lap {self._sel}" if self._sel is not None else "Selected"
        lb = f"Lap {self._cmp}" if self._cmp is not None else "Compare"
        self.pedal.set_cursor(None)
        Ls = self.data._by_id.get(self._sel, {}) if self._sel is not None else {}
        Lc = self.data._by_id.get(self._cmp, {}) if self._cmp is not None else {}
        self.pedal.set_laps(self._pedal_pts(self._sel), self._pedal_pts(self._cmp),
                            la, lb, sec_dist=self._sec_dist_for(self._sel),
                            la_time=Ls.get("lap_time"), lb_time=Lc.get("lap_time"),
                            la_secs=[Ls.get("s1"), Ls.get("s2"), Ls.get("s3")],
                            lb_secs=[Lc.get("s1"), Lc.get("s2"), Lc.get("s3")],
                            best_time=self.data.best_dict().get("lap_time"),
                            best_secs=[self.data.best_dict().get(k) for k in ("s1", "s2", "s3")])
        if self.map_w is not None:
            sel_pts = self._track_xz(self._sel)
            cmp_pts = self._track_xz(self._cmp) if self._cmp is not None else []
            self.map_w.set_review(sel_pts, cmp_pts, la, lb)

    def _driver_meta(self):
        """(class_tag, num) del pilota dai metadati sessione, per il dot."""
        if self.data.con is None:
            return "", ""
        try:
            r = _rows(self.data.con,
                      "SELECT car_class, car_num FROM session_meta WHERE id=1")
            if r:
                return class_tag(r[0]["car_class"] or ""), (r[0]["car_num"] or "")
        except Exception:
            pass
        return "", ""

    def _drv_color(self):
        tag, _ = self._driver_meta()
        return _CLASS_COL.get(tag, "#ff3bd4")

    def _track_name(self):
        if self.data.con is None:
            return ""
        try:
            r = _rows(self.data.con, "SELECT track FROM session_meta WHERE id=1")
            return (r[0]["track"] if r else "") or ""
        except Exception:
            return ""

    def set_lap(self, lap):
        self._sel = lap
        h = QTableWidgetItem(f"Lap {lap}" if lap is not None else "Selected")
        h.setForeground(QBrush(QColor(_sel_col())))
        self.tbl.setHorizontalHeaderItem(1, h)
        self._fill(1, lap)
        self._mark_fastest()
        self._refresh_pedal()
        if self.chart is not None:
            if self.tbl.currentRow() < 0 and self._def_row >= 0:
                self.tbl.selectRow(self._def_row)
            else:
                self._refresh_chart()

    def set_compare(self, lap):
        self._cmp = lap
        h = QTableWidgetItem(f"Lap {lap}" if lap is not None else "Compare")
        h.setForeground(QBrush(QColor(_cmp_col(getattr(self, "_cmp_gold", False)))))
        self.tbl.setHorizontalHeaderItem(2, h)
        self._fill(2, lap)
        self._mark_fastest()
        self._refresh_pedal()
        self._refresh_chart()

    def _set_tyre_mode(self, key):
        self.data.tyre_mode = key
        for k, b in self._mode_btns.items():
            b.setChecked(k == key)
        self._fill(1, self._sel)
        self._fill(2, self._cmp)
        self._refresh_chart()

    def _on_row(self):
        self._refresh_chart()

    def _cur_metric(self):
        rws = self.tbl.selectionModel().selectedRows()
        if rws:
            m = self.metrics[rws[0].row()]
            if m not in ("Stint", "Lap", "Valid"):
                return m
        return self.metrics[self._def_row] if self._def_row >= 0 else None

    def _sec_row(self, lap, sidx):
        rs = _rows(self.data.con,
                   "SELECT * FROM sectors WHERE lap=? AND sector=?", (lap, sidx))
        return rs[0] if rs else None

    @staticmethod
    def _wheels(sr, pre):
        if sr is None:
            return [(p.upper(), None) for p in ("fl", "fr", "rl", "rr")]
        return [(p.upper(), sr.get(pre + p)) for p in ("fl", "fr", "rl", "rr")]

    def _metric_vals(self, lap, metric):
        """(unit, [(label, value)]) sempre multi-punto: 4 ruote per gomme/freni/usura,
        profilo 3 settori per gli scalari. Le metriche a traccia continua sono gestite
        in _refresh_chart e non passano di qui."""
        if lap is None or self.data.con is None:
            return "", []
        m = metric.lower()
        sidx = int(metric[1]) - 1 if (metric[:1] == "S" and metric[1:2].isdigit()) else 0

        # per-ruota: 4 punti FL/FR/RL/RR del settore scelto (gomme, freni, usura -> torri)
        if "tyre" in m:
            return "\u00b0C", self._wheels(self._sec_row(lap, sidx), "t_")
        if "brake" in m:
            return "\u00b0C", self._wheels(self._sec_row(lap, sidx), "b_")
        if "wear" in m:
            return "%", self._wheels(self._sec_row(lap, sidx), "w_")

        # scalari: profilo sui 3 settori (linea S1·S2·S3)
        def secvals(col, nz=False):
            out = []
            for s in (1, 2, 3):
                sr = self._sec_row(lap, s - 1)
                v = sr.get(col) if sr else None
                if nz and v is not None and v < 0:
                    v = None
                out.append((f"S{s}", v))
            return out

        if "speed avg" in m:
            return "km/h", secvals("spd_avg")
        if "speed max" in m:
            return "km/h", secvals("spd_max")
        if "fuel" in m:
            return "L", secvals("fuel_used", nz=True)
        if m.startswith("ve ") or " ve " in m or m.startswith("ve("):
            return "%", secvals("ve_used", nz=True)
        if "regen" in m:
            return "kWh", secvals("regen_gain_kwh")
        if "boost" in m:
            return "kWh", secvals("boost_kwh")
        if "soc" in m:
            out = []
            for s in (1, 2, 3):
                sr = self._sec_row(lap, s - 1)
                v = sr.get("soc_used") if sr else None
                out.append((f"S{s}", (-v if v is not None else None)))
            return "%", out

        # tempi: profilo dei tempi settore
        L = self.data._by_id.get(lap, {})
        if metric in ("Time", "Sector 1", "Sector 2", "Sector 3"):
            return "s", [("S1", L.get("s1")), ("S2", L.get("s2")), ("S3", L.get("s3"))]
        return "", []

    def _trace(self, lap, col, sidx):
        """Traccia continua del canale 'col' vs distanza. Se sidx è 0/1/2 ritaglia
        al settore usando i tempi settore del giro (s1/s2/s3)."""
        if lap is None or self.data.con is None or col not in self.data.sample_cols:
            return []
        rs = _rows(self.data.con,
                   f"SELECT t, lapdist, {col} v FROM samples WHERE lap=? ORDER BY rowid", (lap,))
        if sidx is not None:
            L = self.data._by_id.get(lap, {})
            s1 = L.get("s1") or 0.0
            s2 = L.get("s2") or 0.0
            if sidx == 0:
                lo, hi = -1e9, s1
            elif sidx == 1:
                lo, hi = s1, s1 + s2
            else:
                lo, hi = s1 + s2, 1e9
            rs = [r for r in rs if r["t"] is not None and lo <= r["t"] < hi]
        xy = [(r["lapdist"], r["v"]) for r in rs
              if r["lapdist"] is not None and r["v"] is not None]
        # pulizia: ordina per distanza e scarta i campioni con lapdist che torna
        # indietro (leak dal bordo giro) -> niente più righe orizzontali spurie
        xy.sort(key=lambda p: p[0])
        clean = []
        last = None
        for x, v in xy:
            if last is None or x > last + 1e-6:
                clean.append((x, v)); last = x
        xy = clean
        if col in ("fuel", "ve") and xy:
            base = xy[0][1]                       # consumo progressivo: parte da 0 e sale
            xy = [(x, base - v) for x, v in xy]
        return xy

    @staticmethod
    def _chan(metric):
        """Canale campionato + scope settore per la traccia continua, o None."""
        m = metric.lower()
        sidx = int(metric[1]) - 1 if (metric[:1] == "S" and metric[1:2].isdigit()) else None
        if "tyre" in m or "brake" in m or "wear" in m or "press" in m:
            return None                       # -> torri (barre per-ruota)
        if "speed" in m:
            return ("speed", "km/h", sidx)
        if "fuel" in m:
            return ("fuel", "L", sidx)
        if m.startswith("ve ") or " ve " in m or m.startswith("ve("):
            return ("ve", "%", sidx)
        if "soc" in m:
            return ("soc", "%", sidx)
        if "regen" in m or "boost" in m:
            return ("regen_kw", "kW", sidx)
        return None                           # tempi -> linea settori

    def recolor(self):
        if self.tbl.horizontalHeaderItem(1):
            self.tbl.horizontalHeaderItem(1).setForeground(QBrush(QColor(_sel_col())))
        if self.tbl.horizontalHeaderItem(2):
            self.tbl.horizontalHeaderItem(2).setForeground(QBrush(QColor(_cmp_col(getattr(self, "_cmp_gold", False)))))
        if self.chart is not None:
            self.chart.update()
        if getattr(self, "map_w", None) is not None:
            self.map_w.update()

    def _bars_groups(self, metric):
        ua, ga = self._metric_vals(self._sel, metric)
        ub, gb = self._metric_vals(self._cmp, metric)
        unit = ua or ub
        labels = [l for l, _ in ga] or [l for l, _ in gb]
        am = dict(ga); bm = dict(gb)
        return unit, labels, [(l, am.get(l), bm.get(l)) for l in labels]

    def _refresh_chart(self):
        if self.chart is None:
            return
        metric = self._cur_metric()
        if metric is None:
            self.chart.clear(); return
        la = f"Lap {self._sel}" if self._sel is not None else "Selected"
        lb = f"Lap {self._cmp}" if self._cmp is not None else "Compare"
        m = metric.lower()
        # gomme / freni / usura / pressione -> torri (barre per-ruota)
        if "tyre" in m or "brake" in m or "wear" in m or "press" in m:
            unit, _, groups = self._bars_groups(metric)
            self.chart.set_bars(metric, unit, groups, la, lb)
            return
        # tutto il resto -> traccia continua (ritagliata al settore se per-settore)
        spec = self._chan(metric)
        if spec is not None:
            col, unit, sidx = spec
            sa = self._trace(self._sel, col, sidx)
            sb = self._trace(self._cmp, col, sidx)
            if sa or sb:
                self.chart.set_data(metric, unit, sa, sb, la, lb, xlabels=None)
                return
        # fallback (canale non campionato nel file) / tempi -> linea sui settori
        unit, labels, groups = self._bars_groups(metric)
        am = {l: a for l, a, _ in groups}; bm = {l: b for l, _, b in groups}
        sa = [(i, am[l]) for i, l in enumerate(labels) if am.get(l) is not None]
        sb = [(i, bm[l]) for i, l in enumerate(labels) if bm.get(l) is not None]
        self.chart.set_data(metric, unit, sa, sb, la, lb, xlabels=labels)

    def _mark_fastest(self):
        """Best assoluto dello stint in fuxia (identico alla lista Stint): miglior
        tempo e migliori settori, su qualunque colonna li mostri."""
        best = self.data.best_dict()
        keymap = {"Time": "lap_time", "Sector 1": "s1", "Sector 2": "s2", "Sector 3": "s3"}
        for r, name in enumerate(self.metrics):
            key = keymap.get(name)
            if not key:
                continue
            bv = best.get(key)
            for col, lap in ((1, self._sel), (2, self._cmp)):
                it = self.tbl.item(r, col)
                if it is None:
                    continue
                v = (self.data._by_id.get(lap, {}) or {}).get(key)
                it.setForeground(QBrush(QColor(_FUX if _is_b(v, bv) else "#ffffff")))

    def _fill(self, col, lap):
        res = self.data.values(lap)
        for r, name in enumerate(self.metrics):
            v = None if res is None else res[0].get(name)
            if isinstance(v, dict):                       # riga per-ruota
                self.tbl.setItem(r, col, QTableWidgetItem(""))
                self.tbl.setCellWidget(r, col, _wheel_widget(v))
                continue
            self.tbl.removeCellWidget(r, col)
            if res is None:
                it = QTableWidgetItem("")
            else:
                _, best = res
                text = "" if (name == "Stint" and col == 2) else v
                it = QTableWidgetItem(text if text is not None else "")
                it.setForeground(QBrush(QColor(_FUCHSIA if best.get(name) else "#ffffff")))
            if name in ("Stint", "Lap", "Valid"):
                it.setFlags(it.flags() & ~Qt.ItemIsSelectable)
            self.tbl.setItem(r, col, it)
        self.tbl.resizeRowsToContents()


class EnergiaView(QWidget):
    def __init__(self):
        super().__init__()
        self.con = None
        lay = QVBoxLayout(self)
        self.lbl = QLabel(""); lay.addWidget(self.lbl)
        self.ch = LineChart(); lay.addWidget(self.ch)

    def set_stint(self, laps, car_class):
        xs = [L["lap"] for L in laps]
        series = [("Fuel/lap (L)", [L["fuel_used"] for L in laps], QColor("#ffb74d")),
                  ("VE/lap (%)", [L["ve_used"] for L in laps], QColor("#4fc3f7"))]
        if _is_hybrid(car_class) and laps and self.con is not None:
            lo, hi = laps[0]["lap"], laps[-1]["lap"]
            regs = _rows(self.con, "SELECT lap, AVG(regen_kwh) g FROM sectors "
                                   "WHERE lap BETWEEN ? AND ? GROUP BY lap", (lo, hi))
            rmap = {r["lap"]: r["g"] for r in regs}
            series.append(("Regen (kW)", [rmap.get(x) for x in xs], QColor("#00e676")))
            self.lbl.setText("Classe ibrida: incluso regen.")
        else:
            self.lbl.setText("Solo fuel/VE.")
        self.ch.set_data(xs, series)


class GommeView(QWidget):
    def __init__(self):
        super().__init__()
        self.con = None
        lay = QVBoxLayout(self)
        self.tbl = QTableWidget()
        self.tbl.setColumnCount(5)
        self.tbl.setHorizontalHeaderLabels(["", "FL", "FR", "RL", "RR"])
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setSelectionMode(QAbstractItemView.NoSelection)
        self.tbl.setFocusPolicy(Qt.NoFocus)
        lay.addWidget(self.tbl)

    def set_lap(self, lap):
        if lap is None or self.con is None:
            self.tbl.setRowCount(0); return
        secs = _rows(self.con, "SELECT * FROM sectors WHERE lap=? ORDER BY sector", (lap,))
        rows = []
        for s in secs:
            rows.append((f"S{s['sector']+1} temp", [s["t_fl"], s["t_fr"], s["t_rl"], s["t_rr"]], 60, 120, True))
            rows.append((f"S{s['sector']+1} freno", [s["b_fl"], s["b_fr"], s["b_rl"], s["b_rr"]], 100, 700, True))
            rows.append((f"S{s['sector']+1} usura", [s["w_fl"], s["w_fr"], s["w_rl"], s["w_rr"]], 0, 100, False))
        self.tbl.setRowCount(len(rows))
        for r, (lbl, vals, lo, hi, color) in enumerate(rows):
            self.tbl.setItem(r, 0, QTableWidgetItem(lbl))
            for c, v in enumerate(vals):
                it = QTableWidgetItem("\u2014" if v is None else f"{v:.1f}")
                if v is not None and color:
                    it.setForeground(QBrush(_heat(v, lo, hi)))
                self.tbl.setItem(r, c + 1, it)


class GuidaView(QWidget):
    def __init__(self):
        super().__init__()
        self.con = None
        lay = QVBoxLayout(self)
        self.c_in = LineChart(); self.c_sp = LineChart()
        lay.addWidget(self.c_in); lay.addWidget(self.c_sp)

    def set_lap(self, lap):
        if lap is None or self.con is None:
            self.c_in.set_data([], []); self.c_sp.set_data([], []); return
        s = _rows(self.con, "SELECT lapdist, throttle, brake, steer, speed "
                            "FROM samples WHERE lap=? ORDER BY rowid", (lap,))
        xs = [r["lapdist"] for r in s]
        self.c_in.set_data(xs, [
            ("Throttle", [r["throttle"] for r in s], QColor("#00e676")),
            ("Brake", [r["brake"] for r in s], QColor("#ff3b30")),
            ("Steer", [r["steer"] for r in s], QColor("#a7aaaf"))])
        self.c_sp.set_data(xs, [("Speed (km/h)", [r["speed"] for r in s], QColor(_ACCENT))])


class MappaView(QWidget):
    def __init__(self):
        super().__init__()
        self.con = None
        self._map_track = None      # cache: pista di cui ho gia' la mappa
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Color = speed"))
        self.view = TrajectoryView()
        lay.addWidget(self.view)

    def _load_official_map(self):
        """Mappa ufficiale (settings/trackmap/<pista>.svg, coordinate mondo:
        le stesse dei samples) come base sotto la traiettoria."""
        import re as _re
        try:
            rr = _rows(self.con, "SELECT track FROM session_meta LIMIT 1")
            track = (rr[0]["track"] or "").strip() if rr else ""
        except Exception:
            track = ""
        if not track or track == self._map_track:
            return
        self._map_track = track
        pts = []
        try:
            base = _ROOT / "settings" / "trackmap"
            cand = base / (track + ".svg")
            if not cand.exists():
                low = track.lower()
                for f in base.glob("*.svg"):
                    st = f.stem.lower()
                    if st in low or low in st:
                        cand = f
                        break
            if cand.exists():
                txt = cand.read_text(encoding="utf-8", errors="ignore")
                mm = _re.search(r'points="([^"]+)"', txt)
                if mm:
                    for tok in mm.group(1).split():
                        x, z = tok.split(",")[:2]
                        # STESSA convenzione di _load_track_svg: gli SVG
                        # trackmap hanno la z INVERTITA (TinyPedal). Senza
                        # il meno la mappa esce specchiata e l'inquadratura
                        # (unione mappa+giro) schiaccia tutto: il bug
                        # "mappe e traiettorie non disegnate".
                        pts.append((float(x), -float(z)))
        except Exception:
            pts = []
        if pts or not getattr(self, "_map_ok", False):
            # transitorio a vuoto: NON cancellare la mappa gia' disegnata
            self.view.set_map(pts)
            self._map_ok = bool(pts)

    def set_lap(self, lap):
        if self.con is not None:
            self._load_official_map()
        if lap is None or self.con is None:
            self.view.set_path([]); return
        try:
            s = _rows(self.con, "SELECT pos_x, pos_z, speed FROM samples "
                                "WHERE lap=? ORDER BY rowid", (lap,))
        except Exception:
            return          # colpo a vuoto concorrente: tieni l'ultima buona
        pts = [(r["pos_x"], r["pos_z"], r["speed"]) for r in s
               if r["pos_x"] is not None and r["pos_z"] is not None]
        if pts or lap != getattr(self, "_last_path_lap", None):
            self.view.set_path(pts)
            self._last_path_lap = lap


class _LiveSpeedChart(QWidget):
    """Velocità live del giro corrente vs distanza, marker settori + top/sett."""
    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WA_TranslucentBackground, True)  # radiale traspare
        self._pts = []           # [(lapdist, speed)]
        self._sec_dist = []      # confini settore [d1, d2]
        self._tops = [0.0, 0.0, 0.0]
        self.setMinimumHeight(280)

    def set(self, pts, sec_dist, tops):
        self._pts = pts or []
        self._sec_dist = [d for d in (sec_dist or []) if d]
        self._tops = tops or [0.0, 0.0, 0.0]
        self.update()

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(9, 13, 20, 150))
        W, H = self.width(), self.height()
        ml, mr, mt, mb = 46, 14, 30, 24
        gw, gh = W - ml - mr, H - mt - mb
        f = p.font(); f.setPointSize(8); p.setFont(f)
        if len(self._pts) < 2:
            p.setPen(QColor("#60636c"))
            p.drawText(self.rect(), Qt.AlignCenter, "in attesa dei dati\u2026")
            p.end(); return
        xs = [x for x, _ in self._pts]; ys = [y for _, y in self._pts]
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        if xmax <= xmin:
            xmax = xmin + 1.0
        ymin = max(0.0, ymin - 8.0); ymax = ymax + 8.0
        if ymax <= ymin:
            ymax = ymin + 1.0

        def X(v):
            return ml + gw * (v - xmin) / (xmax - xmin)

        def Y(v):
            return mt + gh * (1.0 - (v - ymin) / (ymax - ymin))

        for i in range(5):
            yy = int(mt + gh * i / 4)
            p.setPen(QPen(QColor("#313d5a"), 1)); p.drawLine(ml, yy, W - mr, yy)
            val = ymax - (ymax - ymin) * i / 4
            p.setPen(QColor("#9fb0c8")); p.drawText(6, yy + 4, f"{val:.0f}")
        p.setPen(QColor("#9fb0c8")); p.drawText(6, mt - 8, "km/h")

        for d in self._sec_dist:
            if xmin <= d <= xmax:
                xx = int(X(d))
                p.setPen(QPen(QColor("#3a3d43"), 1, Qt.DashLine))
                p.drawLine(xx, mt, xx, mt + gh)

        labels = ["S1", "S2", "S3"]
        bounds = [xmin] + list(self._sec_dist) + [xmax]
        p.setPen(QColor("#a6a9af"))
        for i in range(3):
            if i + 1 < len(bounds):
                cx = (bounds[i] + bounds[i + 1]) / 2.0
                top = self._tops[i] if i < len(self._tops) else 0.0
                txt = f"{labels[i]}  {top:.0f}" if top else labels[i]
                tw = p.fontMetrics().horizontalAdvance(txt)
                if xmin <= cx <= xmax:
                    p.drawText(QPointF(X(cx) - tw / 2, mt + 12), txt)

        poly = QPolygonF([QPointF(X(x), Y(y)) for x, y in self._pts])
        p.setPen(QPen(QColor(_SEL_COL), 2)); p.setBrush(Qt.NoBrush)
        p.drawPolyline(poly)
        cx, cy = self._pts[-1]
        p.setBrush(QColor(_SEL_COL)); p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(X(cx), Y(cy)), 4, 4)
        p.end()


class LiveView(QWidget):
    """Vista live: legge il reader e mostra lo stint corrente in tempo reale."""
    _WH = ("FL", "FR", "RL", "RR")

    def __init__(self, on_back):
        super().__init__()
        self._on_back = on_back
        try:
            self._reader = TelemetryReader()
        except Exception:
            self._reader = None
        self._map_reader = None
        if _RealMapReader is not None:
            try:
                self._map_reader = _RealMapReader()
            except Exception:
                self._map_reader = None
        self._timer = QTimer(self); self._timer.setInterval(250)
        self._timer.timeout.connect(self._poll)
        self._reset_state()

        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self.btn_back = QPushButton("\u2039 Review"); self.btn_back.setObjectName("backBtn")
        self.btn_back.setCursor(Qt.PointingHandCursor)
        self.btn_back.clicked.connect(self._on_back)
        top.addWidget(self.btn_back)
        self.lbl_state = QLabel("\u25cf  LIVE")
        self.lbl_state.setStyleSheet("color:#ff5b6e;font-weight:600;")
        top.addSpacing(10); top.addWidget(self.lbl_state)
        self.lbl_info = QLabel(""); self.lbl_info.setStyleSheet("color:#989ba2;")
        top.addSpacing(14); top.addWidget(self.lbl_info)
        top.addStretch()
        self.btn_clear = QPushButton("Reset stint"); self.btn_clear.setObjectName("backBtn")
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.clicked.connect(self._reset_ui)
        top.addWidget(self.btn_clear)
        root.addLayout(top)

        self.tabs = QTabWidget()
        self._build_times()
        self._build_speed()
        self._build_ve()
        self._build_energy()
        self._build_tyres()
        self._build_stint()
        root.addWidget(self.tabs)

    # ── ciclo ──
    def start(self):
        self._timer.start(); self._poll()

    def stop(self):
        self._timer.stop()

    # ── stato ──
    def _reset_state(self):
        self._laps_done = None
        self._lapno = None
        self._sector = None
        self._spd_pts = []
        self._ped_pts = []
        self._pos_pts = []
        self._sec_top = [0.0, 0.0, 0.0]
        self._sec_dist = [None, None]
        self._lap_ve0 = None
        self._lap_fuel0 = None
        self._sec_ve = [None, None, None]
        self._sec_fuel = [None, None, None]
        self._cur_sec_ve0 = None
        self._cur_sec_fuel0 = None
        self._sec_regen = [0.0, 0.0, 0.0]
        self._sec_boost = [0.0, 0.0, 0.0]
        self._cur_regen = 0.0
        self._cur_boost = 0.0
        self._lap_regen = 0.0
        self._lap_boost = 0.0
        self._prev_et = None
        self._garage_seen = False
        self._laps = []
        self._track_pts = []

    def _reset_ui(self):
        self._reset_state()
        self._tbl_stint.setRowCount(0)
        self._poll()

    # ── costruzione tab ──
    def _grid(self, rows, cols):
        """rows: lista nomi riga. cols: header colonne. Ritorna (widget, cells dict)."""
        w = QWidget(); g = QGridLayout(w)
        g.setContentsMargins(16, 14, 16, 14); g.setHorizontalSpacing(28); g.setVerticalSpacing(12)
        for c, h in enumerate(cols):
            lab = QLabel(h); lab.setStyleSheet("color:#989ba2;font-weight:600;")
            g.addWidget(lab, 0, c + 1)
        cells = {}
        for r, name in enumerate(rows):
            rl = QLabel(name); rl.setStyleSheet("color:#dcdddf;")
            g.addWidget(rl, r + 1, 0)
            for c in range(len(cols)):
                v = QLabel("\u2014"); v.setStyleSheet(f"color:{_FG};font-size:18px;")
                g.addWidget(v, r + 1, c + 1)
                cells[(r, c)] = v
        g.setRowStretch(len(rows) + 1, 1)
        return w, cells

    def _build_times(self):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(0, 0, 0, 0)
        grid, self._c_times = self._grid(
            ["Last", "Best", "Average", "Current"],
            ["Lap", "S1", "S2", "S3"])
        v.addWidget(grid)
        cap = QLabel("Pedals + position  ·  current lap"); cap.setStyleSheet("color:#989ba2;padding:4px 16px 0;")
        v.addWidget(cap)
        roww = QWidget(); rowl = QHBoxLayout(roww); rowl.setContentsMargins(0, 0, 0, 0)
        self.chart_ped = _PedalChart()
        self.chart_map = _LiveMap()          # mappa normale (tracciato registrato)
        self._real_map = False
        rowl.addWidget(self.chart_ped, 2)        # pedali 2/3
        rowl.addWidget(self.chart_map, 1)        # mappa 1/3
        v.addWidget(roww, 1)
        self.tabs.addTab(w, "Times")

    def _build_speed(self):
        w = QWidget(); v = QVBoxLayout(w)
        self.chart_speed = _LiveSpeedChart()
        v.addWidget(self.chart_speed)
        row = QHBoxLayout()
        self._spd_top = {}
        for i, s in enumerate(("S1", "S2", "S3")):
            cap = QLabel(f"Top {s}:"); cap.setStyleSheet("color:#989ba2;")
            val = QLabel("\u2014"); val.setStyleSheet(f"color:{_FG};font-weight:600;")
            row.addWidget(cap); row.addWidget(val); row.addSpacing(18)
            self._spd_top[i] = val
        row.addStretch()
        v.addLayout(row)
        self.tabs.addTab(w, "Speed")

    def _build_ve(self):
        w, self._c_ve = self._grid(["VE used (%)", "Fuel used (L)"],
                                   ["Lap", "S1", "S2", "S3"])
        self.tabs.addTab(w, "VE / Fuel")

    def _build_energy(self):
        w, self._c_en = self._grid(["SOC (%)", "Regen (kWh)", "Boost (kWh)"],
                                   ["Now/Lap", "S1", "S2", "S3"])
        self.tabs.addTab(w, "Energy")

    def _build_tyres(self):
        w, self._c_tyre = self._grid(
            ["Carcass \u00b0C", "Tread \u00b0C", "Layer \u00b0C", "Pressure kPa",
             "Brake \u00b0C", "Wear %"],
            list(self._WH))
        self.tabs.addTab(w, "Tyres")

    def _build_stint(self):
        w = QWidget(); v = QVBoxLayout(w)
        self._tbl_stint = QTableWidget(); self._tbl_stint.setColumnCount(7)
        self._tbl_stint.setHorizontalHeaderLabels(
            ["Lap", "Time", "S1", "S2", "S3", "VE %", "Fuel L"])
        self._tbl_stint.verticalHeader().setVisible(False)
        self._tbl_stint.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tbl_stint.setSelectionMode(QAbstractItemView.NoSelection)
        self._tbl_stint.setFocusPolicy(Qt.NoFocus)
        self._tbl_stint.setShowGrid(False); self._tbl_stint.setAlternatingRowColors(True)
        hh = self._tbl_stint.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Stretch)
        v.addWidget(self._tbl_stint)
        self.tabs.addTab(w, "Stint")

    # ── poll ──
    def _poll(self):
        if self._reader is None:
            self.lbl_info.setText("reader non disponibile")
            return
        try:
            d = self._reader.read()
        except Exception:
            d = None
        if not d:
            self.lbl_info.setText("no telemetry (game not running)")
            return
        garage = bool(d.get("garage"))
        if garage:
            self._garage_seen = True
        elif self._garage_seen:
            self._garage_seen = False
            self._reset_state()
            self._tbl_stint.setRowCount(0)

        lapno = int(d.get("lap_number", 0) or 0)
        laps_done = int(d.get("laps_completed", 0) or 0)
        sector = int(d.get("sector", 0) or 0)
        lapdist = d.get("lapdist")
        speed = d.get("speed") or 0.0
        ve = d.get("ve_pct")
        fuel = d.get("fuel")
        et = d.get("elapsed")

        if self._laps_done is None:
            self._laps_done = laps_done
        if self._lapno is None:
            self._lapno = lapno
            self._init_lap(ve, fuel, sector)

        si = min(max(sector, 0), 2)

        # cambio settore -> salva consumi/energia settore chiuso
        if sector != self._sector:
            ps = min(max(self._sector or 0, 0), 2)
            if self._cur_sec_ve0 is not None and ve is not None:
                self._sec_ve[ps] = self._cur_sec_ve0 - ve
            if self._cur_sec_fuel0 is not None and fuel is not None:
                self._sec_fuel[ps] = self._cur_sec_fuel0 - fuel
            self._sec_regen[ps] = self._cur_regen
            self._sec_boost[ps] = self._cur_boost
            if self._sector == 0:
                self._sec_dist[0] = lapdist
            elif self._sector == 1:
                self._sec_dist[1] = lapdist
            self._cur_sec_ve0 = ve
            self._cur_sec_fuel0 = fuel
            self._cur_regen = 0.0
            self._cur_boost = 0.0
            self._sector = sector

        # accumula
        if lapdist is not None:
            self._spd_pts.append((lapdist, speed))
            self._ped_pts.append((lapdist, d.get("throttle") or 0.0, d.get("brake") or 0.0))
        px, pz = d.get("pos_x"), d.get("pos_z")
        if px is not None and pz is not None:
            self._pos_pts.append((px, pz))
        self._sec_top[si] = max(self._sec_top[si], speed)
        if et is not None and self._prev_et is not None:
            dt = et - self._prev_et
            if 0.0 < dt < 0.5:
                rk = float(d.get("regen_kw", 0.0) or 0.0)
                e = abs(rk) * dt / 3600.0
                if rk > 0:
                    self._cur_regen += e; self._lap_regen += e
                elif rk < 0:
                    self._cur_boost += e; self._lap_boost += e
        self._prev_et = et

        # giro completato (laps_completed sale) -> chiudi giro POI reset buffer
        if laps_done > self._laps_done:
            self._finish_lap(d)
            self._laps_done = laps_done
            self._lapno = lapno
            self._init_lap(ve, fuel, sector)

        self._refresh(d)

    def _init_lap(self, ve, fuel, sector):
        if len(self._pos_pts) > 10:        # conserva il tracciato del giro appena chiuso
            self._track_pts = list(self._pos_pts)
        self._spd_pts = []
        self._ped_pts = []
        self._pos_pts = []
        self._sec_top = [0.0, 0.0, 0.0]
        self._sec_dist = [None, None]
        self._lap_ve0 = ve
        self._lap_fuel0 = fuel
        self._sec_ve = [None, None, None]
        self._sec_fuel = [None, None, None]
        self._cur_sec_ve0 = ve
        self._cur_sec_fuel0 = fuel
        self._sec_regen = [0.0, 0.0, 0.0]
        self._sec_boost = [0.0, 0.0, 0.0]
        self._cur_regen = 0.0
        self._cur_boost = 0.0
        self._lap_regen = 0.0
        self._lap_boost = 0.0
        self._prev_et = None
        self._sector = sector

    def _finish_lap(self, d):
        lt = d.get("last_lap") or 0.0
        s1 = d.get("last_s1") or 0.0
        s2c = d.get("last_s2") or 0.0
        sec1 = s1 if s1 else None
        sec2 = (s2c - s1) if (s2c and s1) else None
        sec3 = (lt - s2c) if (lt and s2c) else None
        ve_used = (self._lap_ve0 - d.get("ve_pct")) if (self._lap_ve0 is not None and d.get("ve_pct") is not None) else None
        fuel_used = (self._lap_fuel0 - d.get("fuel")) if (self._lap_fuel0 is not None and d.get("fuel") is not None) else None
        rec = {"lap": int(d.get("laps_completed", 0) or 0), "time": lt,
               "s1": sec1, "s2": sec2, "s3": sec3,
               "ve": ve_used, "fuel": fuel_used}
        self._laps.append(rec)
        self._append_stint_row(rec)

    def _append_stint_row(self, rec):
        t = self._tbl_stint
        r = t.rowCount(); t.insertRow(r)
        vals = [str(rec["lap"]), _fmt(rec["time"]),
                _fmt(rec["s1"]), _fmt(rec["s2"]), _fmt(rec["s3"]),
                ("\u2014" if rec["ve"] is None else f"{rec['ve']:.2f}"),
                ("\u2014" if rec["fuel"] is None else f"{rec['fuel']:.2f}")]
        for c, v in enumerate(vals):
            it = QTableWidgetItem(v)
            if c == 0:
                it.setForeground(QBrush(QColor(_ACCENT)))
            t.setItem(r, c, it)
        t.scrollToBottom()

    # ── refresh display ──
    def _refresh(self, d):
        track = d.get("track", "") or ""
        self.lbl_info.setText(f"{track}   ·   Lap {self._lapno}   ·   S{min(max((self._sector or 0)+1,1),3)}")

        # Times
        valid = [L for L in self._laps if (L["time"] or 0) > 0]
        best = min((L["time"] for L in valid), default=None)
        avg = (sum(L["time"] for L in valid) / len(valid)) if valid else None
        last = self._laps[-1] if self._laps else None
        cur_t = None
        if d.get("elapsed") is not None and d.get("lap_start_et"):
            cur_t = d["elapsed"] - d["lap_start_et"]
        rowdata = {
            0: [last["time"] if last else None, last["s1"] if last else None,
                last["s2"] if last else None, last["s3"] if last else None],   # Last
            1: [best, None, None, None],                                       # Best
            2: [avg, None, None, None],                                        # Average
            3: [cur_t, d.get("cur_s1") or None, None, None],                   # Current
        }
        for r in range(4):
            for c in range(4):
                v = rowdata[r][c]
                self._c_times[(r, c)].setText(_fmt(v) if v else "\u2014")

        # Speed
        self.chart_speed.set(self._spd_pts, self._sec_dist, self._sec_top)
        self.chart_ped.set_live(self._ped_pts, self._sec_dist)
        if self._real_map:
            md = None
            if self._map_reader is not None:
                try:
                    md = self._map_reader.read()
                except Exception:
                    md = None
            if md:
                self.chart_map.set_data(
                    md.get("track", ""), md.get("cars"), md.get("player"),
                    md.get("sector_flags"), md.get("player_sector"),
                    md.get("yellow_active", False), md.get("my_dist", 0.0),
                    md.get("track_len", 0.0), md.get("yellow_bands"))
        else:
            self.chart_map.set_svg(d.get("track"))
            self.chart_map.set_driver(class_tag(d.get("car_class") or ""), "")
            self.chart_map.set_path(self._track_pts if self._track_pts else self._pos_pts)
            px, pz = d.get("pos_x"), d.get("pos_z")
            if px is not None and pz is not None:
                self.chart_map.set_marker((px, pz))
        for i in range(3):
            tp = self._sec_top[i]
            self._spd_top[i].setText(f"{tp:.0f} km/h" if tp else "\u2014")

        # VE / Fuel (lap progressivo + settori)
        ve = d.get("ve_pct"); fuel = d.get("fuel")
        lap_ve = (self._lap_ve0 - ve) if (self._lap_ve0 is not None and ve is not None) else None
        lap_fuel = (self._lap_fuel0 - fuel) if (self._lap_fuel0 is not None and fuel is not None) else None
        sec_ve = list(self._sec_ve)
        sec_fuel = list(self._sec_fuel)
        cs = min(max(self._sector or 0, 0), 2)
        if self._cur_sec_ve0 is not None and ve is not None:
            sec_ve[cs] = self._cur_sec_ve0 - ve
        if self._cur_sec_fuel0 is not None and fuel is not None:
            sec_fuel[cs] = self._cur_sec_fuel0 - fuel
        self._c_ve[(0, 0)].setText(self._f2(lap_ve))
        self._c_ve[(1, 0)].setText(self._f2(lap_fuel))
        for i in range(3):
            self._c_ve[(0, i + 1)].setText(self._f2(sec_ve[i]))
            self._c_ve[(1, i + 1)].setText(self._f2(sec_fuel[i]))

        # Energy
        soc = d.get("soc")
        sec_regen = list(self._sec_regen); sec_regen[cs] = self._cur_regen
        sec_boost = list(self._sec_boost); sec_boost[cs] = self._cur_boost
        self._c_en[(0, 0)].setText(self._f1(soc))
        self._c_en[(1, 0)].setText(self._f2(self._lap_regen))
        self._c_en[(2, 0)].setText(self._f2(self._lap_boost))
        for i in range(3):
            self._c_en[(0, i + 1)].setText("\u2014")
            self._c_en[(1, i + 1)].setText(self._f2(sec_regen[i]))
            self._c_en[(2, i + 1)].setText(self._f2(sec_boost[i]))

        # Tyres (valori correnti per ruota)
        carc = d.get("tyre_carcass") or [None] * 4
        surf = d.get("tyre_surf") or [None] * 4
        inner = d.get("tyre_inner") or [None] * 4
        press = d.get("tyre_press") or [None] * 4
        brk = d.get("brake_temp") or [None] * 4
        wear = d.get("tyre_wear") or [None] * 4

        def m3(v):
            if not v:
                return None
            xs = [x for x in v if x is not None]
            return sum(xs) / len(xs) if xs else None
        for c in range(4):
            self._c_tyre[(0, c)].setText(self._f0(carc[c] if c < len(carc) else None))
            self._c_tyre[(1, c)].setText(self._f0(m3(surf[c]) if c < len(surf) else None))
            self._c_tyre[(2, c)].setText(self._f0(m3(inner[c]) if c < len(inner) else None))
            self._c_tyre[(3, c)].setText(self._f0(press[c] if c < len(press) else None))
            self._c_tyre[(4, c)].setText(self._f0(brk[c] if c < len(brk) else None))
            self._c_tyre[(5, c)].setText(self._f1(wear[c] if c < len(wear) else None))

    @staticmethod
    def _f0(v):
        return "\u2014" if v is None else f"{v:.0f}"

    @staticmethod
    def _f1(v):
        return "\u2014" if v is None else f"{v:.1f}"

    @staticmethod
    def _f2(v):
        return "\u2014" if v is None else f"{v:.2f}"
