"""
widgets/wecbars/widget.py — WEC Pedals: archi THR / BRK / NRG.

Gemello destro di WEC Revs, replica NATIVA del HUD onboard broadcast
FIA WEC: tre archi concentrici che si riempiono dal basso —
THR (gas, verde, esterno), BRK (freno, rosso, centro), NRG (energia,
segmenti rosso->arancio->lime, interno) — con etichette inclinate in
basso come in regia. NRG sceglie da solo la fonte: virtual energy
(REST) se c'e', altrimenti batteria, altrimenti benzina.
"""
import json
import math
import time
import threading
import urllib.request
from pathlib import Path

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF
from PySide6.QtGui import (QPainter, QColor, QPen, QFont, QPainterPath,
                           QFontMetricsF)

from core.config import get_config
from core.shared_memory import SharedMemory
from core.paths import POSITIONS_FILE

# geometria base (canvas 400x690): specchio di wecrevs, centro a SINISTRA
_BASE_W, _BASE_H = 400, 690
_CX, _CY = -175.0, 330.0
_HALF = 34.5                       # semi-apertura (69 gradi totali)
_A_BOT = -_HALF                    # estremo basso lato destro (Qt)
_SWEEP = 2.0 * _HALF

# bande: (r_esterno, spessore, colore acceso)
_R_THR, _W_THR = 520.0, 34.0
_R_BRK, _W_BRK = 480.0, 26.0
_R_NRG, _W_NRG = 448.0, 24.0
_C_THR = QColor("#57D12F")
_C_BRK = QColor("#E8231A")

_LMU_API = "http://localhost:6397"
_REST_PATH = "/rest/garage/UIScreen/RepairAndRefuel"


class WecBarsOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LMU WEC Pedals")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("overlay")
        self._drag_pos = None
        self._user_enabled = True
        self._mem = SharedMemory.instance()
        self._config = get_config()
        self.cfg = self._config.widget("wecbars")
        self._thr = 0.0
        self._brk = 0.0
        self._nrg = None               # 0-1 o None (fonte assente)
        self._batt = None
        self._fuel_frac = None
        self._ve = None                # da REST, 0-1
        self._lock = threading.Lock()
        self._running = True
        threading.Thread(target=self._loop_rest, daemon=True).start()
        self._apply_scale()
        pos = self._load_position("wecbars")
        self.move(pos[0], pos[1]) if pos else self.move(1400, 200)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update)
        self._timer.start(self.cfg.get("update_ms", 33))

    def _apply_scale(self):
        s = float(self.cfg.scale)
        self.setFixedSize(int(_BASE_W * s), int(_BASE_H * s))

    def reload_config(self):
        self.cfg = self._config.widget("wecbars")
        self._apply_scale()
        self._timer.start(self.cfg.get("update_ms", 33))

    def set_enabled(self, enabled):
        self._user_enabled = enabled
        if enabled:
            self._timer.start(self.cfg.get("update_ms", 33))
            if self._mem.is_on_track():
                super().show()
                self.raise_()
        else:
            self._timer.stop()
            super().hide()

    def open_config(self):
        from gui.config_window import ConfigWindow
        if getattr(self, "_cfg_win", None) is None:
            self._cfg_win = ConfigWindow(self._config, self,
                                         widget_key="wecbars",
                                         title="WEC Pedals")
        self._cfg_win.show()
        self._cfg_win.raise_()

    def closeEvent(self, e):
        self._running = False
        super().closeEvent(e)

    # ── dati ──────────────────────────────────────────────────────────
    def _loop_rest(self):
        """Virtual energy dal REST (1s): unica fonte per la % ufficiale."""
        while self._running:
            ve = None
            try:
                req = urllib.request.Request(
                    _LMU_API + _REST_PATH,
                    headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=1) as r:
                    fi = json.loads(r.read()).get("fuelInfo", {})
                cve = float(fi.get("currentVirtualEnergy", 0) or 0)
                mve = float(fi.get("maxVirtualEnergy", 0) or 0)
                if mve > 0:
                    ve = max(0.0, min(1.0, cve / mve))
            except Exception:
                pass
            with self._lock:
                self._ve = ve
            time.sleep(1)

    def _read(self):
        sim = self._mem._get_sim()
        if not sim or not sim.telemetry:
            return False
        try:
            from pyLMUSharedMemory.lmu_data import MAX_MAPPED_VEHICLES as _MX
            num = int(sim.scoring.scoringInfo.mNumVehicles)
            pidx = -1
            for i in range(min(num, _MX)):
                if sim.scoring.vehScoringInfo[i].mIsPlayer:
                    pidx = i
                    break
            if pidx < 0:
                return False
            pid = int(sim.scoring.vehScoringInfo[pidx].mID)
            t = None
            for i in range(min(num, _MX)):
                ti = sim.telemetry.telemInfo[i]
                if int(ti.mID) == pid:
                    t = ti
                    break
            if t is None:
                return False
            self._thr = max(0.0, min(1.0, float(t.mUnfilteredThrottle)))
            self._brk = max(0.0, min(1.0, float(t.mUnfilteredBrake)))
            try:
                b = float(t.mBatteryChargeFraction)
                self._batt = b if 0.0 < b <= 1.0 else None
            except Exception:
                self._batt = None
            try:
                fm = float(t.mFuelCapacity)
                self._fuel_frac = max(0.0, min(1.0, float(t.mFuel) / fm)) \
                    if fm > 0 else None
            except Exception:
                self._fuel_frac = None
            with self._lock:
                ve = self._ve
            # priorita': virtual energy > batteria > benzina
            self._nrg = ve if ve is not None else \
                (self._batt if self._batt is not None else self._fuel_frac)
            return True
        except Exception:
            return False

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
        self._read()
        self.update()

    # ── disegno ───────────────────────────────────────────────────────
    def _band(self, p, r_out, width, frac, color, segmented=False,
              stoplight=False):
        """Arco che si riempie dal basso: fondo scuro + parte accesa."""
        r_in = r_out - width
        cx, cy = _CX, _CY

        def sector(a_from, sweep):
            path = QPainterPath()
            a = math.radians(a_from)
            path.moveTo(QPointF(cx + r_out * math.cos(a),
                                cy - r_out * math.sin(a)))
            path.arcTo(QRectF(cx - r_out, cy - r_out, r_out * 2, r_out * 2),
                       a_from, sweep)
            ae = math.radians(a_from + sweep)
            path.lineTo(QPointF(cx + r_in * math.cos(ae),
                                cy - r_in * math.sin(ae)))
            path.arcTo(QRectF(cx - r_in, cy - r_in, r_in * 2, r_in * 2),
                       a_from + sweep, -sweep)
            path.closeSubpath()
            return path

        p.setPen(Qt.NoPen)
        # fondo: banda spenta scura (si vede la sagoma, come in regia)
        dark = QColor(color)
        dark.setAlpha(70)
        p.setBrush(dark.darker(300))
        p.drawPath(sector(_A_BOT, _SWEEP))
        if frac <= 0.004:
            return
        lit = _SWEEP * max(0.0, min(1.0, frac))
        if not segmented:
            p.setBrush(color)
            p.drawPath(sector(_A_BOT, lit))
            # bordo vivo in testa
            a_top = math.radians(_A_BOT + lit)
            p.setPen(QPen(QColor(255, 255, 255, 200), 2))
            p.drawLine(QPointF(cx + r_in * math.cos(a_top),
                               cy - r_in * math.sin(a_top)),
                       QPointF(cx + r_out * math.cos(a_top),
                               cy - r_out * math.sin(a_top)))
            return
        # segmentata (NRG): tacchette dal basso, semaforo sul LIVELLO
        seg, gap = 1.9, 1.1
        a = 0.0
        while a + seg <= lit + 0.01:
            pos = (a + seg / 2.0) / _SWEEP
            if stoplight and pos < 0.15:
                p.setBrush(QColor("#E83A2B"))
            elif stoplight and pos < 0.35:
                p.setBrush(QColor("#F5A623"))
            else:
                p.setBrush(QColor("#7ED321"))
            p.drawPath(sector(_A_BOT + a, seg))
            a += seg + gap

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        s = self.width() / float(_BASE_W)
        p.scale(s, s)
        cx, cy = _CX, _CY

        # contorno sottile esterno (sempre)
        r_line = _R_THR + 5.0
        p.setPen(QPen(QColor(255, 255, 255, 230), 2))
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(cx - r_line, cy - r_line, r_line * 2, r_line * 2),
                  int(_A_BOT * 16), int(_SWEEP * 16))

        # scala decorativa a trattini al centro (come in regia)
        p.setPen(QPen(QColor(255, 255, 255, 110), 3))
        r_d = 330.0
        a = -26.0
        while a <= 26.0:
            ar = math.radians(a)
            x1 = cx + (r_d - 8) * math.cos(ar)
            y1 = cy - (r_d - 8) * math.sin(ar)
            ln = 16 if abs(round(a / 13.0) * 13.0 - a) < 1.6 else 8
            x2 = cx + (r_d + ln) * math.cos(ar)
            y2 = cy - (r_d + ln) * math.sin(ar)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            a += 3.25

        # bande
        self._band(p, _R_THR, _W_THR, self._thr, _C_THR)
        self._band(p, _R_BRK, _W_BRK, self._brk, _C_BRK)
        if self._nrg is not None:
            self._band(p, _R_NRG, _W_NRG, self._nrg, QColor("#7ED321"),
                       segmented=True, stoplight=True)

        # etichette inclinate in basso (lungo la tangente dell'arco)
        f = QFont("Google Sans", 15)
        f.setWeight(QFont.Bold)
        p.setFont(f)
        fm = QFontMetricsF(f)
        a_deg = _A_BOT - 5.5                 # poco SOTTO l'estremo basso
        a_lab = math.radians(a_deg)
        tang = -(90.0 + a_deg)               # baseline lungo la tangente
        labels = [("THR", _R_THR - _W_THR / 2.0),
                  ("BRK", _R_BRK - _W_BRK / 2.0)]
        if self._nrg is not None:
            labels.append(("NRG", _R_NRG - _W_NRG / 2.0))
        for txt, rr in labels:
            x = cx + rr * math.cos(a_lab)
            y = cy - rr * math.sin(a_lab)
            p.save()
            p.translate(x, y)
            p.rotate(tang)
            p.setPen(QColor(255, 255, 255, 245))
            p.drawText(QPointF(-fm.horizontalAdvance(txt) / 2.0,
                               fm.ascent() / 2.0 - 1), txt)
            p.restore()
        p.end()

    # ── trascinamento / posizione ─────────────────────────────────────
    def mousePressEvent(self, e):
        from core.utils import overlays_locked
        if overlays_locked():
            return          # overlay BLOCCATI: niente drag
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() \
                - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() == Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        if self._drag_pos is not None:
            self._save_position("wecbars")
        self._drag_pos = None

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
