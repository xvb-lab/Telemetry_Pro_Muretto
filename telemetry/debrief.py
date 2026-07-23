"""
telemetry/debrief.py — PAGINA DEBRIEF INGEGNERE (task #6, 23/07).

Il resoconto scritto della sessione, coi numeri veri della scienza:
  - TIME LOSS  : dove perdi (tabella timeloss del db, per curva/fase)
  - EVENTS     : contatti / track limits / bloccaggi registrati
  - DEGRADO    : riferimento calibrato sui Results XML (243k giri)
    per pista+classe, confrontabile col tuo stint
  - SESSIONE   : riepilogo (giri, best, meteo)

Sola LETTURA: la pagina non tocca nulla del collaudato — apre i .lmtel
in read-only e i json della cartella learn. Refresh a ogni apertura.
"""
import json
import os
import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QScrollArea, QFrame, QComboBox, QGridLayout)

_FG = "#e8ebf2"
_DIM = "#8a90a0"
_PANEL = "#16181d"
_EDGE = "#24262c"
_YEL = "#ffed00"
_RED = "#ff5a4d"
_GRN = "#37d67a"
_ORG = "#ff9f2e"


def _learn_dir():
    return Path(os.environ.get("APPDATA", ".")) / "LMU_TelemetryPro" / "learn"


def _fmt_t(s):
    try:
        s = float(s)
    except (TypeError, ValueError):
        return "-"
    if s <= 0:
        return "-"
    m = int(s // 60)
    return "%d:%06.3f" % (m, s - m * 60) if m else "%.3f" % s


class _Card(QFrame):
    """Pannello scuro con titolo giallo, stile app."""

    def __init__(self, title):
        super().__init__()
        self.setStyleSheet(
            "QFrame{background:%s;border:1px solid %s;border-radius:8px;}"
            % (_PANEL, _EDGE))
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(16, 12, 16, 14)
        self._lay.setSpacing(6)
        t = QLabel(title)
        t.setStyleSheet("color:%s;font-family:'Archivo SemiExpanded';"
                        "font-weight:800;font-size:13px;border:none;" % _YEL)
        self._lay.addWidget(t)

    def add_row(self, left, right="", lcol=_FG, rcol=_FG, bold=False):
        row = QWidget()
        row.setStyleSheet("background:transparent;border:none;")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        _w = "700" if bold else "400"
        a = QLabel(left)
        a.setStyleSheet("color:%s;font-size:12px;font-weight:%s;"
                        "border:none;" % (lcol, _w))
        h.addWidget(a)
        h.addStretch(1)
        if right:
            b = QLabel(right)
            b.setStyleSheet("color:%s;font-size:12px;font-weight:%s;"
                            "border:none;" % (rcol, _w))
            h.addWidget(b)
        self._lay.addWidget(row)

    def add_note(self, txt, col=_DIM):
        a = QLabel(txt)
        a.setWordWrap(True)
        a.setStyleSheet("color:%s;font-size:11px;border:none;" % col)
        self._lay.addWidget(a)


class DebriefPage(QWidget):
    """Pagina DEBRIEF: tab accanto a Setups, refresh a ogni apertura."""

    def __init__(self):
        super().__init__()
        self.setStyleSheet("background:#0e1014;")
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 18, 28, 18)
        root.setSpacing(10)
        # ── testata: titolo + scelta sessione ──
        head = QHBoxLayout()
        t = QLabel("ENGINEER DEBRIEF")
        t.setStyleSheet("color:%s;font-family:'Archivo SemiExpanded';"
                        "font-weight:800;font-size:20px;" % _FG)
        head.addWidget(t)
        head.addStretch(1)
        self._pick = QComboBox()
        self._pick.setMinimumWidth(360)
        self._pick.setStyleSheet(
            "QComboBox{background:%s;color:%s;border:1px solid %s;"
            "border-radius:4px;padding:4px 10px;font-size:12px;}"
            "QComboBox QAbstractItemView{background:%s;color:%s;}"
            % (_PANEL, _FG, _EDGE, _PANEL, _FG))
        self._pick.currentIndexChanged.connect(self._render)
        head.addWidget(self._pick)
        root.addLayout(head)
        # ── corpo scrollabile a card ──
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet("background:transparent;")
        root.addWidget(self._scroll, 1)
        self._sessions = []

    # ── API: chiamata dal window quando apri il tab ──
    def refresh(self):
        try:
            from telemetry import db
            self._sessions = (db.list_sessions() or [])[:20]
        except Exception:
            self._sessions = []
        self._pick.blockSignals(True)
        self._pick.clear()
        for s in self._sessions:
            _st = {0: "P", 1: "P", 2: "P", 3: "P", 4: "P",
                   5: "Q", 6: "Q", 7: "Q", 8: "Q"}.get(
                       int(s.get("session_type") or 0),
                       "R" if int(s.get("session_type") or 0) >= 10 else "P")
            self._pick.addItem("%s — %s (%s, %s)" % (
                (s.get("started_at") or "")[:16].replace("T", " "),
                s.get("track") or "?", s.get("car_class") or "?", _st))
        self._pick.blockSignals(False)
        self._render()

    # ── letture (read-only, mai crash) ──
    def _q(self, path, sql, args=()):
        try:
            con = sqlite3.connect("file:%s?mode=ro" % Path(path).as_posix(),
                                  uri=True)
            try:
                return con.execute(sql, args).fetchall()
            finally:
                con.close()
        except Exception:
            return []

    def _render(self, *_a):
        ix = max(0, self._pick.currentIndex())
        body = QWidget()
        body.setStyleSheet("background:transparent;")
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        if not self._sessions:
            e = QLabel("No sessions recorded yet.")
            e.setStyleSheet("color:%s;font-size:13px;" % _DIM)
            grid.addWidget(e, 0, 0)
            self._scroll.setWidget(body)
            return
        s = self._sessions[min(ix, len(self._sessions) - 1)]
        f = s.get("file")
        # ── card SESSIONE ──
        c0 = _Card("SESSION")
        c0.add_row(str(s.get("track") or "?"),
                   str(s.get("car_class") or ""), bold=True)
        c0.add_row("Vehicle", str(s.get("vehicle") or "-"), _DIM)
        _laps = self._q(f, "SELECT COUNT(*), MIN(lap_time) FROM laps "
                           "WHERE lap_time>10")
        _nl, _bst = (_laps[0] if _laps else (0, None))
        c0.add_row("Laps timed", str(_nl or 0), _DIM)
        c0.add_row("Best lap", _fmt_t(_bst), _DIM,
                   _GRN if _bst else _FG, bold=bool(_bst))
        try:
            _wet = float(s.get("wetness") or 0.0)
        except (TypeError, ValueError):
            _wet = 0.0
        c0.add_row("Track", "WET %d%%" % round(_wet * 100)
                   if _wet > 0.05 else "DRY", _DIM,
                   _ORG if _wet > 0.05 else _FG)
        grid.addWidget(c0, 0, 0)
        # ── card TIME LOSS (aggregato sessione, curve peggiori) ──
        c1 = _Card("TIME LOSS — WHERE YOU LOSE")
        tl = self._q(f, "SELECT corner, COUNT(*), AVG(total_s), MAX(total_s),"
                        " AVG(vmin), AVG(vmin_ref), AVG(entry_s), AVG(exit_s)"
                        " FROM timeloss WHERE total_s > 0.05"
                        " GROUP BY corner ORDER BY AVG(total_s) DESC LIMIT 6")
        if tl:
            for corner, n, avg_s, mx, vm, vr, en, ex in tl:
                _ph = ("entry" if (en or 0) > (ex or 0) else "exit")
                c1.add_row(
                    "%s  (%dx, worst %+.2fs, lose on %s)"
                    % (corner, n, mx or 0, _ph),
                    "%+.3fs   vmin %.0f vs %.0f"
                    % (avg_s or 0, vm or 0, vr or 0),
                    _FG, _RED if (avg_s or 0) >= 0.3 else _ORG)
            c1.add_note("Average loss vs your session best, per corner. "
                        "vmin = your min speed vs reference lap (km/h).")
        else:
            c1.add_note("No time-loss data in this session "
                        "(needs a reference lap + completed laps).")
        grid.addWidget(c1, 0, 1)
        # ── card EVENTS ──
        c2 = _Card("EVENTS")
        ev = self._q(f, "SELECT kind, COUNT(*) FROM events GROUP BY kind")
        _map = {"contact": "Contacts", "tl": "Track limits", "lock": "Lock-ups"}
        if ev:
            for kind, n in sorted(ev):
                c2.add_row(_map.get(kind, kind), str(n), _FG,
                           _RED if kind == "contact" and n else _FG,
                           bold=(kind == "contact"))
            wl = self._q(f, "SELECT lap, lapdist, val FROM events "
                            "WHERE kind='contact' ORDER BY val DESC LIMIT 3")
            for lap, ld, val in wl:
                c2.add_row("   worst: lap %d @ %dm" % (lap or 0, ld or 0),
                           "impact %.0f" % (val or 0), _DIM, _DIM)
            lk = self._q(f, "SELECT val, COUNT(*) FROM events "
                            "WHERE kind='lock' GROUP BY val")
            if lk:
                _W = ("FL", "FR", "RL", "RR")
                c2.add_row("   lock-ups by wheel",
                           "  ".join("%s %d" % (_W[int(v)], n)
                                     for v, n in lk if 0 <= int(v) <= 3),
                           _DIM, _DIM)
        else:
            c2.add_note("No events recorded (clean session).", _GRN)
        grid.addWidget(c2, 1, 0)
        # ── card DEGRADO (riferimento calibrato Results XML) ──
        c3 = _Card("DEGRADATION REFERENCE — %s"
                   % (s.get("car_class") or "?"))
        try:
            _dj = json.load(open(_learn_dir() / "degradation.json",
                                 encoding="utf-8"))
            prof = ((_dj.get("tracks") or {})
                    .get(str(s.get("track") or "")) or {}) \
                .get(str(s.get("car_class") or "")) or {}
        except Exception:
            prof = {}
        shown = 0
        for comp in ("Soft", "Medium", "Hard", "Wet"):
            v = prof.get(comp)
            if not v:
                continue
            try:
                c3.add_row(
                    "%s — %.2f%%/lap, drift %+.0fms/lap"
                    % (comp, float(v.get("wear_pct_lap") or 0.0),
                       1000.0 * float(v.get("pace_drift_s_lap") or 0.0)),
                    "stint ~%d laps, best %s"
                    % (int(v.get("stint_laps_med") or 0),
                       _fmt_t(v.get("best"))),
                    _FG, _DIM)
                shown += 1
            except (TypeError, ValueError):
                continue
        if shown:
            c3.add_note("Calibrated on the community Results archive "
                        "(243k laps): median wear, pace drift and stint "
                        "length for this track and class.")
        else:
            c3.add_note("No calibrated profile for this track/class yet.")
        grid.addWidget(c3, 1, 1)
        grid.setRowStretch(2, 1)
        self._scroll.setWidget(body)
