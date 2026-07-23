"""
widgets/wec26mfd/car_canvas.py — MACCHININA danni/gomme (dal dashboard V2).

Schema auto vista dall'alto, PORTATO 1:1 dall'HUD v2 ma come DISEGNATORE
PURO: niente QWidget figlio, disegna sul painter della card (gia' scalato),
cosi' vive dentro il MOD 4 senza acrobazie di geometrie.

Overlay: gomme (gradiente 3 zone), sospensioni, 8 zone body, radiatore
acqua/olio, fari (con fascio + lampeggio), LED pioggia posteriore, freni,
pit limiter, alettone con etichetta classe.
"""
import math
import time
from pathlib import Path

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import (QPainter, QPixmap, QColor, QPen, QBrush, QFont,
                           QPainterPath, QLinearGradient, QRadialGradient)

_ROOT = Path(__file__).parent.parent.parent
BASE_PNG = _ROOT / "assets" / "cars" / "car_base.png"

# ── colori (V2 colors.py, 1:1) ─────────────────────────────────────────
C_WHITE = QColor("#e8eef5")
C_YELLOW = QColor("#ffe24d")
C_ORANGE = QColor("#ff9a30")
C_PURPLE = QColor("#b06bff")
C_RED = QColor("#ff3b30")


def _scale_col(pct, w, y, o, pu):
    if pct >= w:
        return C_WHITE
    if pct >= y:
        return C_YELLOW
    if pct >= o:
        return C_ORANGE
    if pct >= pu:
        return C_PURPLE
    return C_RED


def col_susp(pct):
    return _scale_col(pct, 100, 89, 50, 20)


def col_oil(t):
    if t >= 135:
        return C_RED
    if t >= 125:
        return C_ORANGE
    if t >= 110:
        return C_YELLOW
    return C_WHITE


def col_water(t):
    if t >= 120:
        return C_RED
    if t >= 110:
        return C_ORANGE
    if t >= 100:
        return C_YELLOW
    return C_WHITE


class CarDiagram:
    """Disegna la macchinina in (ox, oy) con fattore k (1.0 = 96x197)."""

    POS = {
        'tyre_fl': (0.090, 0.232), 'tyre_fr': (0.910, 0.232),
        'tyre_rl': (0.105, 0.730), 'tyre_rr': (0.895, 0.730),
        'susp_fl': (0.304, 0.229), 'susp_fr': (0.700, 0.229),
        'susp_rl': (0.322, 0.739), 'susp_rr': (0.685, 0.738),
        'body_fc': (0.499, 0.005), 'body_fl': (0.075, 0.060),
        'body_fr': (0.925, 0.060),
        'body_cl': (0.035, 0.461), 'body_cr': (0.965, 0.461),
        'body_rl': (0.075, 0.900), 'body_rr': (0.925, 0.900),
        'body_rc': (0.499, 0.870),
        'rad_water': (0.470, 0.108), 'rad_oil': (0.546, 0.108),
        'light_l': (0.280, 0.045), 'light_r': (0.720, 0.045),
        'light_l2': (0.220, 0.080), 'light_r2': (0.780, 0.080),
        'brake_l': (0.230, 0.880), 'brake_r': (0.770, 0.880),
        'pit_fl': (0.130, 0.090), 'pit_fr': (0.870, 0.090),
        'pit_rl': (0.130, 0.880), 'pit_rr': (0.870, 0.880),
        'aero_rear': (0.505, 0.975),
        'rain_rear': (0.505, 0.820),
    }

    def __init__(self):
        self._base = QPixmap(str(BASE_PNG)) if BASE_PNG.exists() else None

    # pulse condiviso (la card ripittura di continuo coi suoi timer)
    @staticmethod
    def _alpha():
        return 0.35 + 0.65 * abs(math.sin(time.monotonic() * 2.25))

    @staticmethod
    def _alpha_rain():
        phase = (time.time() % 1.0)
        s = math.sin(phase * 2 * math.pi - math.pi / 2)
        return 0.2 + 0.8 * (s + 1) / 2

    @staticmethod
    def _dent_integ(v):
        return int(round((1 - min(v, 3) / 3) * 100))

    @staticmethod
    def _temp_color(t):
        if t is None:
            return QColor("#3a4450")
        if t < 70:
            return QColor("#4a90e2")
        elif t < 79:
            return QColor("#00c8e6")
        elif t < 100:
            return QColor("#00e676")
        elif t < 110:
            return QColor("#ffe24d")
        elif t < 120:
            return QColor("#ff9a30")
        return QColor("#ff3b30")

    def draw(self, p, d, ox, oy, k=1.0):
        CW = 96.0 * k
        CH = 197.0 * k

        def px(key):
            nx, ny = self.POS[key]
            return ox + nx * CW, oy + ny * CH

        def ring(key, color, r, glow=False, width=2.0):
            x, y = px(key)
            if glow:
                g = QColor(color)
                g.setAlpha(int(120 * self._alpha()))
                p.setPen(QPen(g, (width + 2.0) * k))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(x, y), r * k, r * k)
            p.setPen(QPen(QColor(color), width * k))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(x, y), r * k, r * k)

        def dot(key, color, r, glow=False):
            x, y = px(key)
            if glow:
                g = QColor(color)
                g.setAlpha(int(150 * self._alpha()))
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(g))
                p.drawEllipse(QPointF(x, y), (r + 2.5) * k, (r + 2.5) * k)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(color))
            p.drawEllipse(QPointF(x, y), r * k, r * k)

        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if self._base:
            p.drawPixmap(QRectF(ox, oy, CW, CH),
                         self._base, QRectF(self._base.rect()))

        tyre = d.get('tires', [None] * 4)
        flat = d.get('tyre_flat', [False] * 4)
        susp = d.get('susp', [None] * 4)
        dent = d.get('body_dent', [0] * 8)
        oil = d.get('oil_temp', None)
        water = d.get('water_temp', None)
        keys4 = ['fl', 'fr', 'rl', 'rr']

        # GOMME
        TYRE_NEUTRAL = QColor("#3a4450")
        detached = d.get('tyre_detached', [False] * 4)
        for i, kk in enumerate(keys4):
            if tyre[i] is None:
                continue
            if i < len(detached) and detached[i]:
                continue
            is_flat = i < len(flat) and flat[i]
            x, y = px('tyre_' + kk)
            tw = CW * 0.175
            th = CH * 0.17
            path = QPainterPath()
            path.addRoundedRect(QRectF(x - tw / 2, y - th / 2, tw, th), 3, 3)
            if is_flat:
                a = self._alpha()
                col = QColor(int(C_ORANGE.red() * a + C_PURPLE.red() * (1 - a)),
                             int(C_ORANGE.green() * a + C_PURPLE.green() * (1 - a)),
                             int(C_ORANGE.blue() * a + C_PURPLE.blue() * (1 - a)))
                col.setAlpha(int(120 + 135 * a))
                p.setPen(QPen(QColor(0, 0, 0, 90), 0.8))
                p.setBrush(QBrush(col))
                p.drawPath(path)
            else:
                surf = d.get('tyre_surf')
                if isinstance(surf, list) and i < len(surf) and surf[i]:
                    tl, tc, tr = surf[i][0], surf[i][1], surf[i][2]
                    grad = QLinearGradient(x - tw / 2, y, x + tw / 2, y)
                    grad.setColorAt(0.0, self._temp_color(tl))
                    grad.setColorAt(0.5, self._temp_color(tc))
                    grad.setColorAt(1.0, self._temp_color(tr))
                    p.setPen(QPen(QColor(0, 0, 0, 90), 0.8))
                    p.setBrush(QBrush(grad))
                    p.drawPath(path)
                else:
                    p.setPen(QPen(QColor(0, 0, 0, 90), 0.8))
                    p.setBrush(QBrush(TYRE_NEUTRAL))
                    p.drawPath(path)

        # SOSPENSIONI
        for i, kk in enumerate(keys4):
            if susp[i] is None:
                continue
            si = int(round((1 - susp[i]) * 100))
            if si >= 100:
                continue
            ring('susp_' + kk, col_susp(si), 5, glow=True, width=2.0)

        # 8 ZONE BODY
        zmap = {'fl': dent[1], 'fc': dent[0], 'fr': dent[7],
                'cl': dent[2], 'cr': dent[6],
                'rl': dent[3], 'rc': dent[4], 'rr': dent[5]}
        for kk, dval in zmap.items():
            integ = self._dent_integ(dval)
            if integ >= 100:
                continue
            ring('body_' + kk, col_susp(integ), 3, glow=True, width=1.6)

        # RADIATORE
        if water is not None and water >= 100:
            dot('rad_water', col_water(water), 4, glow=water >= 110)
        if oil is not None and oil >= 110:
            dot('rad_oil', col_oil(oil), 4, glow=oil >= 135)

        # FARI (con fascio); lampeggio = intensita' pulsante
        hl = d.get('headlights', False)
        lflash = d.get('light_flash', False)

        def _light(lk, inten, beam=False):
            core = QColor("#e8f7ff")
            halo = QColor("#7fdcff")
            lx, ly = px(lk)
            if beam:
                beam_len = CH * 0.14
                beam_w = 11 * k
                bgrad = QLinearGradient(lx, ly, lx, ly - beam_len)
                b0 = QColor(halo)
                b0.setAlpha(int(110 * inten))
                bgrad.setColorAt(0.0, b0)
                b1 = QColor(halo)
                b1.setAlpha(0)
                bgrad.setColorAt(1.0, b1)
                bp = QPainterPath()
                bp.moveTo(lx - 2 * k, ly)
                bp.lineTo(lx + 2 * k, ly)
                bp.lineTo(lx + beam_w, ly - beam_len)
                bp.lineTo(lx - beam_w, ly - beam_len)
                bp.closeSubpath()
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(bgrad))
                p.drawPath(bp)
            rad = 9 * k
            grad = QRadialGradient(lx, ly, rad)
            hc = QColor(halo)
            hc.setAlpha(int(160 * inten))
            grad.setColorAt(0.0, hc)
            hm = QColor(halo)
            hm.setAlpha(int(65 * inten))
            grad.setColorAt(0.5, hm)
            he = QColor(halo)
            he.setAlpha(0)
            grad.setColorAt(1.0, he)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(grad))
            p.drawEllipse(QPointF(lx, ly), rad, rad)
            cc = QColor(core)
            cc.setAlpha(int(255 * inten))
            p.setBrush(QBrush(cc))
            p.drawEllipse(QPointF(lx, ly), 2.4 * k, 2.4 * k)

        if hl or lflash:
            inten = self._alpha() if lflash else 0.9
            _light('light_l', inten, beam=True)
            _light('light_r', inten, beam=True)
        if hl:
            _light('light_l2', 0.9, beam=True)
            _light('light_r2', 0.9, beam=True)

        # LED PIOGGIA POSTERIORE (anche col limiter, come in LMU)
        if d.get('is_wet') or d.get('pit_limiter'):
            rx, ry = px('rain_rear')
            rw = CW * 0.10
            rh = CH * 0.022
            a = self._alpha_rain()
            beam_len = CH * 0.10
            beam_w = rw * 3.5
            bgrad = QLinearGradient(rx, ry, rx, ry + beam_len)
            b0 = QColor("#ff4d4d")
            b0.setAlpha(int(170 * a))
            bgrad.setColorAt(0.0, b0)
            bm = QColor("#ff4d4d")
            bm.setAlpha(int(60 * a))
            bgrad.setColorAt(0.35, bm)
            b1 = QColor("#ff4d4d")
            b1.setAlpha(0)
            bgrad.setColorAt(0.8, b1)
            bp = QPainterPath()
            bp.moveTo(rx - rw / 2, ry)
            bp.lineTo(rx + rw / 2, ry)
            bp.lineTo(rx + beam_w / 2, ry + beam_len)
            bp.lineTo(rx - beam_w / 2, ry + beam_len)
            bp.closeSubpath()
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(bgrad))
            p.drawPath(bp)
            led = QColor("#ff6b6b")
            led.setAlpha(int(130 + 125 * a))
            lpath = QPainterPath()
            lpath.addRoundedRect(QRectF(rx - rw / 2, ry - rh / 2, rw, rh), 2, 2)
            p.setPen(QPen(QColor(0, 0, 0, 90), 0.8))
            p.setBrush(QBrush(led))
            p.drawPath(lpath)
            core = QColor("#ffd0d0")
            core.setAlpha(int(180 * a))
            cpath = QPainterPath()
            cpath.addRoundedRect(QRectF(rx - rw / 4, ry - rh / 4,
                                        rw / 2, rh / 2), 1, 1)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(core))
            p.drawPath(cpath)

        # FRENI (bagliore rosso proporzionale al pedale)
        brk = d.get('brake', 0) or 0
        if brk > 0.05:
            inten = min(1.0, brk)
            for bk in ('brake_l', 'brake_r'):
                bx, by = px(bk)
                rad = 15 * k
                p.save()
                clip = QPainterPath()
                clip.addRect(QRectF(bx - rad, by - 3 * k, rad * 2, rad + 3 * k))
                p.setClipPath(clip)
                grad = QRadialGradient(bx, by, rad)
                g0 = QColor("#ff2020")
                g0.setAlpha(int(255 * inten))
                grad.setColorAt(0.0, g0)
                gm = QColor("#ff2020")
                gm.setAlpha(int(130 * inten))
                grad.setColorAt(0.45, gm)
                ge = QColor("#ff2020")
                ge.setAlpha(0)
                grad.setColorAt(1.0, ge)
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(grad))
                p.drawEllipse(QPointF(bx, by), rad, rad)
                p.restore()
                core = QColor("#ff3030")
                core.setAlpha(int(255 * inten))
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(core))
                p.drawEllipse(QPointF(bx, by), 5 * k, 5 * k)
                hot = QColor("#ffe0e0")
                hot.setAlpha(int(255 * inten))
                p.setBrush(QBrush(hot))
                p.drawEllipse(QPointF(bx, by), 2.2 * k, 2.2 * k)

        # PIT LIMITER: 4 luci arancio lampeggianti
        if d.get('pit_limiter'):
            if (time.time() % 0.7) < 0.35:
                for pk in ('pit_fl', 'pit_fr', 'pit_rl', 'pit_rr'):
                    px2, py2 = px(pk)
                    rad = 8 * k
                    grad = QRadialGradient(px2, py2, rad)
                    g0 = QColor("#ffb84d")
                    g0.setAlpha(180)
                    grad.setColorAt(0.0, g0)
                    gm = QColor("#ff9a30")
                    gm.setAlpha(70)
                    grad.setColorAt(0.5, gm)
                    ge = QColor("#ff9a30")
                    ge.setAlpha(0)
                    grad.setColorAt(1.0, ge)
                    p.setPen(Qt.NoPen)
                    p.setBrush(QBrush(grad))
                    p.drawEllipse(QPointF(px2, py2), rad, rad)
                    p.setBrush(QBrush(QColor("#ffaa3a")))
                    p.drawEllipse(QPointF(px2, py2), 2.6 * k, 2.6 * k)
                    p.setBrush(QBrush(QColor("#fff4e0")))
                    p.drawEllipse(QPointF(px2, py2), 1.3 * k, 1.3 * k)

        # ALETTONE + etichetta classe
        if not d.get('detached'):
            x, y = px('aero_rear')
            aw = CW * 0.833
            ah = CH * 0.096
            apath = QPainterPath()
            apath.addRoundedRect(QRectF(x - aw / 2, y - ah / 2, aw, ah), 2, 2)
            p.setPen(QPen(QColor(0, 0, 0, 90), 0.8))
            p.setBrush(QBrush(QColor("#3a4450")))
            p.drawPath(apath)
            cls = (d.get('car_class') or '').upper()
            if 'HYPER' in cls or 'LMH' in cls or 'LMDH' in cls:
                clabel = "HYPER"
            elif 'GT3' in cls or cls == 'GT':
                clabel = "GT3"
            elif 'LMP2' in cls or 'P2' in cls:
                clabel = "LMP2"
            elif 'LMP3' in cls or 'P3' in cls:
                clabel = "LMP3"
            else:
                clabel = cls[:5]
            if clabel:
                f = QFont("Archivo SemiExpanded")
                f.setPointSize(max(6, round(10 * k)))
                f.setBold(True)
                p.setFont(f)
                p.setPen(QPen(QColor("#080b10")))
                p.drawText(QRectF(x - aw / 2, y - ah / 2, aw, ah),
                           Qt.AlignCenter, clabel)
        p.restore()
