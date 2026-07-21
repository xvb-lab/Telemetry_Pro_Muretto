"""
widgets/wecrevs/widget.py — WEC Revs: arco giri + velocita' + marcia.

Replica NATIVA (QPainter, zero immagini) del HUD onboard broadcast FIA
WEC: arco contagiri verticale a sinistra con gradiente ciano->blu notte,
tacche e numeri = migliaia di giri, velocita' grande in Bebas Neue con
"km/h", marcia in cerchio "GEAR". Geometria dal riferimento (arco 69
gradi centrato sulle 9, banda ~70px su cerchio ~1050px).
Dati diretti dalla shared memory (telemetria player agganciata per mID).
"""
import json
import math
import time
from pathlib import Path

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF
from PySide6.QtGui import (QPainter, QColor, QPen, QFont, QConicalGradient,
                           QPainterPath, QFontMetricsF)

from core.config import get_config
from core.shared_memory import SharedMemory
from core.paths import POSITIONS_FILE

# geometria base (canvas 400x660, scala via config)
_BASE_W, _BASE_H = 400, 660
_CX, _CY = 575.0, 330.0        # centro cerchio (fuori canvas, a destra)
_R_OUT = 520.0                 # raggio esterno banda
_BAND = 68.0                   # spessore banda giri
_HALF = 34.5                   # semi-apertura arco (69 gradi totali)
_A_BOT = 180.0 + _HALF         # angolo Qt estremo basso (0 giri)
_SWEEP = 2.0 * _HALF           # apertura totale

# gradiente lungo l'arco: alto = ciano chiaro, basso = blu notte
_GRAD = ((0.00, QColor("#F2FFFF")), (0.20, QColor("#9FEFF5")),
         (0.45, QColor("#54B9E8")), (0.68, QColor("#2B6BC4")),
         (0.85, QColor("#1A2F7A")), (1.00, QColor("#0C1338")))


class WecRevsOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LMU WEC Revs")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("overlay")
        self._drag_pos = None
        self._user_enabled = True
        self._mem = SharedMemory.instance()
        self._config = get_config()
        self.cfg = self._config.widget("wecrevs")
        self._rpm = 0.0
        self._rpm_max = 0.0
        self._speed = 0.0
        self._gear = 0
        self._gear_old = 0             # marcia prima della cambiata
        self._gear_t0 = 0.0            # istante cambiata
        self._gear_ref = None          # ultima marcia VERA (non folle)
        self._apply_scale()
        pos = self._load_position("wecrevs")
        self.move(pos[0], pos[1]) if pos else self.move(40, 200)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update)
        self._timer.start(self.cfg.get("update_ms", 33))

    def _apply_scale(self):
        s = float(self.cfg.scale)
        self.setFixedSize(int(_BASE_W * s), int(_BASE_H * s))

    def reload_config(self):
        self.cfg = self._config.widget("wecrevs")
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
                                         widget_key="wecrevs",
                                         title="WEC Revs")
        self._cfg_win.show()
        self._cfg_win.raise_()

    # ── dati ──────────────────────────────────────────────────────────
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
            # telemetria per mID (gli array non sono allineati allo scoring)
            pid = int(sim.scoring.vehScoringInfo[pidx].mID)
            t = None
            for i in range(min(num, _MX)):
                ti = sim.telemetry.telemInfo[i]
                if int(ti.mID) == pid:
                    t = ti
                    break
            if t is None:
                return False
            rpm = max(0.0, float(t.mEngineRPM))
            # piccolo filtro: niente sfarfallio della banda
            self._rpm = self._rpm * 0.4 + rpm * 0.6
            mx = float(t.mEngineMaxRPM)
            if mx > 1000:
                self._rpm_max = mx
            v = t.mLocalVel
            self._speed = (v.x * v.x + v.y * v.y + v.z * v.z) ** 0.5 * 3.6
            g = int(t.mGear)
            if g != self._gear:
                # il FOLLE di passaggio (3->N->2 in scalata) non e' una
                # cambiata: niente animazione, e la direzione si giudica
                # sull'ultima marcia VERA (self._gear_ref)
                if g != 0 and self._gear_ref is not None \
                        and g != self._gear_ref:
                    self._gear_old = self._gear_ref
                    self._gear_t0 = time.monotonic()
                self._gear = g
                if g != 0:
                    self._gear_ref = g
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
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        s = self.width() / float(_BASE_W)
        p.scale(s, s)

        mx = self._rpm_max if self._rpm_max > 1000 else 8000.0
        frac = max(0.0, min(1.0, self._rpm / mx))
        cx, cy = _CX, _CY

        def pt(angle_deg, radius):
            a = math.radians(angle_deg)
            return QPointF(cx + radius * math.cos(a),
                           cy - radius * math.sin(a))

        # ── banda giri accesa (settore anulare con gradiente) ─────────
        if frac > 0.005:
            sweep = _SWEEP * frac
            r_in = _R_OUT - _BAND
            path = QPainterPath()
            path.moveTo(pt(_A_BOT, _R_OUT))
            path.arcTo(QRectF(cx - _R_OUT, cy - _R_OUT,
                              _R_OUT * 2, _R_OUT * 2), _A_BOT, -sweep)
            path.lineTo(pt(_A_BOT - sweep, r_in))
            path.arcTo(QRectF(cx - r_in, cy - r_in, r_in * 2, r_in * 2),
                       _A_BOT - sweep, sweep)
            path.closeSubpath()
            grad = QConicalGradient(QPointF(cx, cy), _A_BOT - _SWEEP)
            span = _SWEEP / 360.0
            for off, col in _GRAD:
                grad.setColorAt(off * span, col)
            p.setPen(Qt.NoPen)
            p.setBrush(grad)
            p.drawPath(path)
            # separatori bianchi ogni 1000 giri (solo parte accesa)
            p.setPen(QPen(QColor(255, 255, 255, 210), 2))
            k = 1000
            while k < frac * mx:
                a = _A_BOT - _SWEEP * (k / mx)
                p.drawLine(pt(a, r_in + 1), pt(a, _R_OUT - 1))
                k += 1000
            # bordo vivo in testa alla banda
            a_top = _A_BOT - sweep
            p.setPen(QPen(QColor(255, 255, 255, 235), 3))
            p.drawLine(pt(a_top, r_in), pt(a_top, _R_OUT))

        # ── contorno sottile + tacche + numeri (sempre visibili) ──────
        r_line = _R_OUT + 5.0
        p.setPen(QPen(QColor(255, 255, 255, 230), 2))
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(cx - r_line, cy - r_line, r_line * 2, r_line * 2),
                  int((_A_BOT - _SWEEP) * 16), int(_SWEEP * 16))
        n_k = int(math.ceil(mx / 1000.0))
        f_lab = QFont("Heebo", 20)
        f_lab.setWeight(QFont.DemiBold)
        p.setFont(f_lab)
        fm = QFontMetricsF(f_lab)
        for k in range(n_k + 1):
            rpm_k = min(k * 1000.0, mx)
            a = _A_BOT - _SWEEP * (rpm_k / mx)
            p.setPen(QPen(QColor(255, 255, 255, 230), 2))
            p.drawLine(pt(a, r_line), pt(a, r_line + 12))
            lp = pt(a, r_line + 26)
            txt = str(k)
            w = fm.horizontalAdvance(txt)
            p.setPen(QColor(255, 255, 255, 240))
            p.drawText(QPointF(lp.x() - w / 2.0,
                               lp.y() + fm.ascent() / 2.0 - 2), txt)

        # ── velocita' (Bebas) + km/h ──────────────────────────────────
        f_spd = QFont("Bebas Neue", 76)
        p.setFont(f_spd)
        fs = QFontMetricsF(f_spd)
        spd = "%d" % int(round(self._speed))
        w = fs.horizontalAdvance(spd)
        p.setPen(QColor(255, 255, 255, 245))
        p.drawText(QPointF(232 - w / 2.0, cy + 12), spd)
        f_kmh = QFont("Heebo", 19)
        p.setFont(f_kmh)
        fk = QFontMetricsF(f_kmh)
        p.setPen(QColor(219, 216, 214, 235))
        p.drawText(QPointF(232 - fk.horizontalAdvance("km/h") / 2.0,
                           cy + 52), "km/h")

        # ── marcia in cerchio "GEAR" (con effetto cambiata) ───────────
        gx, gy, gr = 334.0, cy - 4.0, 30.0
        now = time.monotonic()
        t = (now - self._gear_t0) / 0.55 if self._gear_t0 else 2.0
        up = self._gear > self._gear_old
        # anello con TAGLIO in alto: li' vive il segmento flottante
        GAP_C, GAP_W = 90.0, 55.0      # taglio PERFETTAMENTE in alto
        p.setPen(QPen(QColor(255, 255, 255, 235), 2))
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(gx - gr, gy - gr, gr * 2, gr * 2),
                  int((GAP_C + GAP_W / 2.0) * 16),
                  int((360.0 - GAP_W) * 16))
        # cambiata: il segmento fa il giro — ORARIO e VERDE a salire,
        # ANTIORARIO e ROSSO a scalare — e rientra sfumando al bianco
        if t < 1.0:
            ang = GAP_C - 360.0 * t if up else GAP_C + 360.0 * t
            col = QColor("#3FE05A") if up else QColor("#FF3B30")
            span, seg_r, seg_w = 32.0, gr + 5.0, 4.0
            if t > 0.8:
                # rientro: scende al livello dell'anello e sbianca
                k = (t - 0.8) / 0.2
                col = QColor(int(col.red() + (255 - col.red()) * k),
                             int(col.green() + (255 - col.green()) * k),
                             int(col.blue() + (255 - col.blue()) * k))
                seg_r = gr + 5.0 * (1.0 - k)
                seg_w = 4.0 - 1.0 * k
                span = 32.0 + 8.0 * k
        else:
            # riposo: pezzo GIU' sul cerchio ma RICONOSCIBILE
            # (piu' spesso, coi due taglietti visibili ai lati)
            ang, col = GAP_C, QColor(255, 255, 255, 245)
            span, seg_r, seg_w = 40.0, gr, 3.0
        p.setPen(QPen(col, seg_w, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(QRectF(gx - seg_r, gy - seg_r, seg_r * 2, seg_r * 2),
                  int((ang - span / 2.0) * 16), int(span * 16))

        def _gsym(g):
            return "R" if g < 0 else ("N" if g == 0 else str(g))

        f_gear = QFont("Bebas Neue", 34)
        p.setFont(f_gear)
        fg = QFontMetricsF(f_gear)
        ts = (now - self._gear_t0) / 0.25 if self._gear_t0 else 2.0
        p.setPen(QColor(255, 255, 255, 245))
        if ts < 1.0:
            # roll: il numero si schiaccia a striscia e riappare nuovo
            shown = _gsym(self._gear_old if ts < 0.5 else self._gear)
            sy = max(0.08, abs(1.0 - 2.0 * ts))
            p.save()
            p.translate(gx, gy)
            p.scale(1.0, sy)
            p.drawText(QPointF(-fg.horizontalAdvance(shown) / 2.0,
                               fg.ascent() / 2.0 - 4), shown)
            p.restore()
        else:
            gear = _gsym(self._gear)
            p.drawText(QPointF(gx - fg.horizontalAdvance(gear) / 2.0,
                               gy + fg.ascent() / 2.0 - 4), gear)
        f_gl = QFont("Heebo", 13)
        f_gl.setWeight(QFont.DemiBold)
        f_gl.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        p.setFont(f_gl)
        fl = QFontMetricsF(f_gl)
        p.drawText(QPointF(gx - fl.horizontalAdvance("GEAR") / 2.0,
                           gy + gr + 24), "GEAR")
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
            self._save_position("wecrevs")
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
