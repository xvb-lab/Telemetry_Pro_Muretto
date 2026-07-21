"""
widgets/wec26mini/widget.py — WEC 2026 Mini Telemetry.

Il "pod" quadrato della regia 2026: WEC TELEMETRY, velocita' KPH
grande, barra freno/gas, marcia con le tacche, MPH, VIRTUAL ENERGY
TANK con %. Sfondo nel COLORE del costruttore del player (ogni
squadra il suo), fallback viola broadcast. Dati: base WecOnboard
(telemetria player) + marcia letta qui.
"""
import math

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import (QPainter, QColor, QPen, QFont, QFontMetricsF,
                           QPainterPath, QLinearGradient)

from widgets.weconboard.widget import WecOnboardOverlay

_W, _H = 200, 252
_BRANDCOL = {"Ferrari": "#9E111E", "Porsche": "#A50F1E",
             "BMW": "#16337E", "Toyota": "#131316",
             "Cadillac": "#6E5A10", "Alpine": "#0E4B9E",
             "Peugeot": "#17181C", "Aston Martin": "#00584F",
             "McLaren": "#C2601A", "Mercedes-AMG": "#0C0C0E",
             "Lexus": "#1A1A1E", "Ford": "#0E1D5B",
             "Corvette": "#5A5F66", "Genesis": "#141416",
             "Lamborghini": "#0F4A2E"}


class Wec26MiniOverlay(WecOnboardOverlay):
    KEY = "wec26mini"
    TITLE = "WEC 2026 Mini Telemetry"

    def __init__(self):
        self._gear = 0
        self._rpm_frac = 0.0
        super().__init__()

    def _apply_scale(self):
        s = float(self.cfg.scale)
        self.setFixedSize(int(_W * s), int(_H * s))
        self.setWindowOpacity(
            max(0.15, float(self.cfg.get("bg_opacity", 100)) / 100.0))

    def _read(self):
        ok = super()._read()
        if ok:
            try:
                sim = self._mem._get_sim()
                from pyLMUSharedMemory.lmu_data import \
                    MAX_MAPPED_VEHICLES as _MX
                num = int(sim.scoring.scoringInfo.mNumVehicles)
                pid = None
                for i in range(min(num, _MX)):
                    if sim.scoring.vehScoringInfo[i].mIsPlayer:
                        pid = int(sim.scoring.vehScoringInfo[i].mID)
                        break
                for i in range(min(num, _MX)):
                    t = sim.telemetry.telemInfo[i]
                    if pid is not None and int(t.mID) == pid:
                        self._gear = int(t.mGear)
                        try:
                            mx = float(t.mEngineMaxRPM)
                            self._rpm_frac = max(0.0, min(1.0,
                                float(t.mEngineRPM) / mx)) if mx > 0 \
                                else 0.0
                        except Exception:
                            self._rpm_frac = 0.0
                        break
            except Exception:
                pass
        return ok

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        s = self.width() / float(_W)
        p.scale(s, s)
        base = QColor(_BRANDCOL.get(self._brand, "#312C54"))
        path = QPainterPath()
        path.addRoundedRect(QRectF(2, 2, _W - 4, _H - 4), 14, 14)
        g = QLinearGradient(0, 0, 0, _H)
        g.setColorAt(0.0, base.lighter(126))
        g.setColorAt(1.0, base.darker(126))
        p.setPen(Qt.NoPen)
        p.fillPath(path, g)
        p.setClipPath(path)
        W = QColor(255, 255, 255, 245)
        GX = 26.0                    # spazio del gauge meter a sinistra
        CX = GX + (_W - GX) / 2.0    # centro della zona contenuti

        # header a fascia (tema = colore squadra piu' chiaro)
        p.setBrush(QColor(255, 255, 255, 34))
        p.drawRect(QRectF(2, 2, _W - 4, 30))
        f_h = QFont("Druk Wide", 9)
        f_h.setWeight(QFont.ExtraBold)
        f_h.setItalic(True)
        f_h.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        p.setFont(f_h)
        p.setPen(QColor(222, 230, 248, 210))
        p.drawText(QPointF(16, 23), "WEC TELEMETRY")

        # GAUGE METER: segmenti RPM sul bordo sinistro (verde->rosso)
        _segs = ["#2BD62B", "#2BD62B", "#7ED62B", "#C9D62B",
                 "#F5C21B", "#F58B1B", "#F0521B", "#E22323"]
        n = len(_segs)
        lit = int(round(self._rpm_frac * n))
        top, bot = 42.0, _H - 14.0
        sh = (bot - top - (n - 1) * 4.0) / n
        for i, cc in enumerate(_segs):
            # indice 0 = segmento in BASSO (verde), n-1 in alto (rosso)
            yy = bot - (i + 1) * sh - i * 4.0
            col = QColor(cc)
            if i >= lit:
                col.setAlpha(55)
            p.setBrush(col)
            p.drawRect(QRectF(8.0, yy, 10.0, sh))

        # velocita' KMH grande
        f_s = QFont("Druk Wide", 30)
        f_s.setWeight(QFont.Black)
        f_s.setItalic(True)
        p.setFont(f_s)
        fs = QFontMetricsF(f_s)
        kph = "%d" % int(round(self._speed))
        f_u = QFont("Druk Wide", 11)
        f_u.setWeight(QFont.ExtraBold)
        f_u.setItalic(True)
        fu = QFontMetricsF(f_u)
        tot = fs.horizontalAdvance(kph) + 4 + fu.horizontalAdvance("KMH")
        x0 = CX - tot / 2.0
        p.setPen(W)
        p.drawText(QPointF(x0, 74), kph)
        p.setFont(f_u)
        p.drawText(QPointF(x0 + fs.horizontalAdvance(kph) + 4, 74), "KMH")

        # barra: pista grigia, FRENO rosso a sinistra, GAS verde a destra
        bx, bw, by, bh = GX + 8.0, _W - GX - 30.0, 88.0, 11.0
        half = bw / 2.0
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(175, 178, 186, 150))
        p.drawRect(QRectF(bx, by, bw, bh))
        p.setBrush(QColor("#E22323"))
        p.drawRect(QRectF(bx + half - half * self._brk, by,
                          half * self._brk, bh))
        p.setBrush(QColor("#2BD62B"))
        p.drawRect(QRectF(bx + half, by, half * self._thr, bh))

        # marcia con le TACCHE ai lati (come in regia)
        gear = "R" if self._gear < 0 else \
            ("N" if self._gear == 0 else str(self._gear))
        f_g = QFont("Druk Wide", 27)
        f_g.setWeight(QFont.Black)
        f_g.setItalic(True)
        p.setFont(f_g)
        fg = QFontMetricsF(f_g)
        gy = 144.0
        gw = fg.horizontalAdvance(gear)
        p.setPen(W)
        p.drawText(QPointF(CX - gw / 2.0, gy), gear)
        p.setPen(QPen(QColor(255, 255, 255, 220), 2, Qt.SolidLine,
                      Qt.RoundCap))
        for sgn in (-1, 1):
            cx = CX + sgn * (gw / 2.0 + 14)
            p.drawLine(QPointF(cx - 12 * sgn, gy - 9),
                       QPointF(cx + 16 * sgn, gy - 9))
            for k in (0, 10):
                xx = cx + sgn * k
                p.drawLine(QPointF(xx, gy - 16), QPointF(xx, gy - 2))

        # MPH in grigio (imperiale, come da mockup)
        f_m = QFont("Druk Wide", 13)
        f_m.setWeight(QFont.Black)
        f_m.setItalic(True)
        p.setFont(f_m)
        fmm = QFontMetricsF(f_m)
        mph = "%dMPH" % int(round(self._speed * 0.621371))
        p.setPen(QColor(215, 220, 232, 135))
        p.drawText(QPointF(CX - fmm.horizontalAdvance(mph) / 2.0, 176),
                   mph)

        # VIRTUAL ENERGY TANK + % (percentuale grande, simbolo piccolo)
        if self._nrg is not None:
            f_l = QFont("Druk Wide", 9)
            f_l.setWeight(QFont.ExtraBold)
            f_l.setItalic(True)
            p.setFont(f_l)
            p.setPen(W)
            p.drawText(QPointF(GX + 6, _H - 40), "VIRTUAL")
            p.drawText(QPointF(GX + 6, _H - 24), "ENERGY TANK")
            f_p = QFont("Druk Wide", 17)
            f_p.setWeight(QFont.Black)
            f_p.setItalic(True)
            f_pp = QFont("Druk Wide", 10)
            f_pp.setWeight(QFont.Black)
            f_pp.setItalic(True)
            num = "%d" % int(round(self._nrg * 100))
            fp = QFontMetricsF(f_p)
            fpp = QFontMetricsF(f_pp)
            xr = _W - 14 - fpp.horizontalAdvance("%")
            p.setFont(f_p)
            p.drawText(QPointF(xr - fp.horizontalAdvance(num), _H - 26),
                       num)
            p.setFont(f_pp)
            p.drawText(QPointF(xr, _H - 34), "%")
        p.end()
