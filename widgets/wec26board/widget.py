"""
widgets/wec26board/widget.py — WEC 2026 Onboard: card animata.

Card broadcast 2026 sui TEMPLATE in assets/Template Onboard HY-LMGT3
(uno per costruttore/classe, niente foto pilota). Parte PIENA con
numero, pilota, posizione e gap; dopo open_delay_s si APRE (dissolvenza)
e mostra i dati: pedali, VIRTUAL ENERGY TANK arcobaleno con %, KMH+MPH.
Click sulla card = apri/chiudi a mano. Dati: telemetria player (base
WecOnboardOverlay) + posizione/gap dallo StandingsReader (1 Hz).
"""
import re
import time
from pathlib import Path

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import (QPainter, QColor, QPen, QFont, QFontMetricsF,
                           QPixmap, QLinearGradient)

from widgets.weconboard.widget import WecOnboardOverlay, _CLS_COL

_W, _H = 620, 131                       # template 2041x431 in scala
_TPL_DIR = Path(__file__).resolve().parents[2] / "assets" \
    / "Template Onboard HY-LMGT3"


from core.wec_style import (BRAND_COLORS as _BRANDCOL,
                            CLASS_CHIP as _CHIP,
                            row_gradient as brand_gradient,
                            row_color, is_light,
                            card_logo_path, LOGO_SCALE)


def text_on(brand):
    """Testo sul colore NUOVO della card (override riga compresi)."""
    c = row_color(brand)
    return "#18181C" if (c and is_light(c)) else "#FFFFFF"


def draw_card_base(p, brand, tag, model, logo, right_label=None,
                   right_color=None, chip=True):
    """Card 2026 NATIVA (620x131): tinta brand, logo SVG, chip classe,
    striscia modello + blocco ONBOARD. Zero PNG: tutta modificabile."""
    base = QColor(row_color(brand) or _BRANDCOL.get(brand, "#312C54"))
    strip_y = _H * (338.0 / 431.0)
    g = QLinearGradient(0, 0, _W, 0)
    tri = brand_gradient(brand)
    if tri:
        # GRADIENTE UFFICIALE della style guide 2026
        g.setColorAt(0.0, QColor(tri[0]))
        g.setColorAt(0.5, QColor(tri[1]))
        g.setColorAt(1.0, QColor(tri[2]))
    else:
        g.setColorAt(0.0, base.lighter(122))
        g.setColorAt(1.0, base.darker(130))
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawRect(QRectF(0, 0, _W, strip_y))
    # striscia bassa: SEMPRE background ufficiale 0A0032
    p.setBrush(QColor(10, 0, 50, 252))
    p.drawRect(QRectF(0, strip_y, _W, _H - strip_y))
    p.setBrush(QColor(right_color) if right_color
               else QColor(24, 18, 70, 252))
    p.drawRect(QRectF(_W - 150, strip_y, 150, _H - strip_y))
    f = QFont("Archivo SemiExpanded", 12)
    f.setWeight(QFont.ExtraBold)
    f.setItalic(True)
    p.setFont(f)
    fm = QFontMetricsF(f)
    yb = strip_y + (_H - strip_y + fm.ascent()) / 2.0 - 2
    p.setPen(QColor(255, 255, 255, 242))
    p.drawText(QPointF(14, yb), model or "")
    rl = right_label or "ONBOARD"
    p.drawText(QPointF(_W - 150 + (150 - fm.horizontalAdvance(rl))
                       / 2.0, yb), rl)
    if chip:      # chip classe in alto: SOLO Onboard (in Battle la
                  # classe sta gia' nella striscia bassa colorata)
        lab, cc = _CHIP.get(tag, ("HYPERCAR", "#C3122A"))
        f2 = QFont("Archivo SemiExpanded", 10)
        f2.setWeight(QFont.Black)
        f2.setItalic(True)
        fm2 = QFontMetricsF(f2)
        cw = fm2.horizontalAdvance(lab) + 26
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(cc))
        p.drawRect(QRectF(_W - 22 - cw, 10, cw, 24))
        p.setFont(f2)
        p.setPen(QColor(255, 255, 255, 245))
        p.drawText(QPointF(_W - 22 - cw + 13,
                           10 + (24 + fm2.ascent()) / 2.0 - 2), lab)
    if logo:
        try:
            vb = logo.viewBoxF()
            ar = vb.height() / vb.width() if vb.width() > 0 else 1.0
        except Exception:
            ar = 1.0
        # STESSO sistema del MFD: quadrati=BMW, rettangolari=Cadillac,
        # coi ritocchi per marchio condivisi (core.wec_style.logo_box)
        from core.wec_style import logo_box
        bw, bh, dy, _adv, _dx = logo_box(brand, ar, 72.0, rect_w=100.0,
                                         surface="onboard")
        logo.render(p, QRectF(8.0 + (100.0 - bw) / 2.0,
                              10 + (86.0 - bh) / 2.0 + dy, bw, bh))
    p.setPen(QPen(QColor(text_on(brand)), 3,
                  Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(126, 22), QPointF(110, 92))


def _tpl_name(brand, tag):
    b = re.sub(r"[^a-z]", "", (brand or "").lower())
    if b.startswith("mercedes"):
        b = "mercedes"
    if b in ("chevrolet", "corvette"):
        b = "corvette"
    suffix = "hy" if tag in ("HY", "P2", "P3") else "lmgt3"
    return _TPL_DIR / ("WEC_onboard_%s_%s.png" % (b, suffix))


class Wec26OnboardOverlay(WecOnboardOverlay):
    KEY = "wec26board"
    TITLE = "WEC 2026 Onboard"

    def __init__(self):
        self._tpl = None
        self._tpl_key = None
        self._drv = ""
        self._pos = 0
        self._gaptxt = ""
        self._reader = None
        self._slow_t = 0.0
        self._shown_t0 = None
        self._forced = None             # click: True=aperta False=chiusa
        super().__init__()

    def _apply_scale(self):
        s = float(self.cfg.scale)
        # A SCHERMO larga quanto la MFD card (500): il disegno resta
        # su base 620 e scala in proporzione, layout INTATTO
        k = 500.0 / _W
        self.setFixedSize(int(_W * k * s), int(_H * k * s))
        self.setWindowOpacity(
            max(0.15, float(self.cfg.get("bg_opacity", 100)) / 100.0))

    def mouseReleaseEvent(self, e):
        moved = self._drag_pos is not None and \
            (e.globalPosition().toPoint()
             - (self._drag_pos + self.frameGeometry().topLeft())
             ).manhattanLength() > 4
        super().mouseReleaseEvent(e)
        if not moved:
            self._forced = not self._open_now()

    def _open_now(self):
        if self._forced is not None:
            return self._forced
        if self._shown_t0 is None:
            return False
        return (time.monotonic() - self._shown_t0) \
            >= float(self.cfg.get("open_delay_s", 5.0))

    def _update(self):
        vis = self.isVisible()
        super()._update()
        if self.isVisible() and not vis:
            self._shown_t0 = time.monotonic()      # riparte PIENA
            self._forced = None
        if self._shown_t0 is None and self.isVisible():
            self._shown_t0 = time.monotonic()
        now = time.monotonic()
        if now - self._slow_t >= 1.0:
            self._slow_t = now
            try:
                if self._reader is None:
                    from widgets.standings.reader import StandingsReader
                    self._reader = StandingsReader()
                drivers, _pc, sess, _rem = self._reader.read()
                me = next((d for d in drivers or []
                           if d.get("is_player")), None)
                if me:
                    self._drv = str(me.get("name") or "")
                    self._pos = int(me.get("place_class") or 0)
                    lb = int(me.get("laps_behind") or 0)
                    g = float(me.get("gap_leader") or 0.0)
                    if self._pos == 1:
                        self._gaptxt = "LEADER"
                    elif lb > 0:
                        self._gaptxt = "+%d LAPS" % lb
                    elif g > 0:
                        self._gaptxt = "+%.1f" % g
                    else:
                        self._gaptxt = ""
            except Exception:
                pass

    # ── disegno ───────────────────────────────────────────────────────
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        s = self.width() / float(_W)
        p.scale(s, s)

        # card NATIVA: logo nostro (SVG, nitido) + colori brand
        if self._brand and self._brand != getattr(self, "_logo_brand",
                                                  None):
            self._logo_brand = self._brand
            try:
                from PySide6.QtSvg import QSvgRenderer
                lp = card_logo_path(self._brand)
                self._logo = QSvgRenderer(str(lp)) if lp else None
            except Exception:
                self._logo = None
        draw_card_base(p, self._brand, self._tag,
                       getattr(self, "_vmodel", ""),
                       getattr(self, "_logo", None))

        # apertura con dissolvenza morbida (0.5s)
        t0 = self._shown_t0 or time.monotonic()
        if self._forced is not None:
            f = 1.0 if self._forced else 0.0
        else:
            dl = float(self.cfg.get("open_delay_s", 5.0))
            f = max(0.0, min(1.0, (time.monotonic() - t0 - dl) / 0.5))

        # numero auto: sempre, grande corsivo dopo la barra bianca
        f_num = QFont("Archivo SemiExpanded", 42)
        f_num.setWeight(QFont.Black)
        f_num.setItalic(True)
        p.setFont(f_num)
        fn = QFontMetricsF(f_num)
        # numero gara quando la card e' chiusa, POSIZIONE quando il
        # pannello telemetria e' aperto (switchano col pannello)
        num = self._num or self._tag
        alt = ("P%d" % self._pos) if self._pos else None
        shown = alt if (alt and f > 0.5) else num
        p.setPen(QColor(text_on(self._brand)))   # scuro su basi chiare
        p.drawText(QPointF(140, 76), shown)

        # zx STABILE sulla scritta piu' larga: il pannello non balla
        wmax = max(fn.horizontalAdvance(t) for t in (num, alt) if t)
        zx = 162 + wmax                           # bordo pannello
        zw = _W - zx - 155                        # lascia libero il chip

        # ── stato PIENO: pilota, posizione, gap ATTACCATI al numero
        #    VERO mostrato (niente vuoto morto a sinistra del nome) ──
        if f < 1.0:
            zx_txt = 140 + fn.horizontalAdvance(num or "") + 18
            f_dr = QFont("Archivo SemiExpanded", 19)
            f_dr.setWeight(QFont.Black)
            f_dr.setItalic(True)
            p.setFont(f_dr)
            fd = QFontMetricsF(f_dr)
            name = self._drv.upper() or "DRIVER"
            zw_n = _W - zx_txt - 40
            while name and fd.horizontalAdvance(name) > zw_n:
                name = name[:-1]
            p.setPen(QColor(text_on(self._brand)))
            p.drawText(QPointF(zx_txt, 48), name)
            f_pg = QFont("Archivo SemiExpanded", 16)
            f_pg.setWeight(QFont.ExtraBold)
            f_pg.setItalic(True)
            p.setFont(f_pg)
            pg = ("P%d" % self._pos if self._pos else "") \
                + ("   %s" % self._gaptxt if self._gaptxt else "")
            p.drawText(QPointF(zx_txt, 76), pg.strip())

        # ── pannello TELEMETRIA: entra da DESTRA, fondo navy WEC ──────
        if f > 0.0:
            strip_y = _H * (338.0 / 431.0)     # si ferma sulla striscia
            pw = _W - zx
            dx = pw * (1.0 - f)                # scorrimento right->left
            p.save()
            p.setClipRect(QRectF(zx + dx, 0, _W - zx - dx, strip_y))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(49, 44, 84, 248))  # #312C54 broadcast
            p.drawRect(QRectF(zx + dx, 0, _W - zx - dx, strip_y))
            p.translate(dx + 18.0, 8.0)  # telemetria staccata dal bordo
            bx, bw = zx, 150.0
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 60))
            p.drawRect(QRectF(bx, 22, bw, 10))
            half = bw / 2.0
            p.setBrush(QColor(255, 255, 255, 240))
            p.drawRect(QRectF(bx + half - half * self._brk, 22,
                              half * self._brk, 10))
            p.setBrush(QColor("#2BD62B"))
            p.drawRect(QRectF(bx + half, 22, half * self._thr, 10))
            p.setPen(QPen(QColor(255, 255, 255, 220), 1))
            p.setBrush(Qt.NoBrush)
            p.drawLine(QPointF(bx + half, 19), QPointF(bx + half, 35))
            if self._nrg is not None:
                nseg, segw, gap = 14, 5.0, 2.6
                lit = int(round(self._nrg * nseg))
                rain = ("#E33A2B", "#F5731F", "#F5A623", "#F5D90A",
                        "#A8E10C", "#3FE05A", "#2BD6C4", "#2B9AD6",
                        "#4B6BE8", "#7A4BE8", "#A83AE0", "#D63AC4",
                        "#E8398F", "#E8395A")
                p.setPen(Qt.NoPen)
                for i in range(nseg):
                    c = QColor(rain[i]) if i < lit \
                        else QColor(255, 255, 255, 45)
                    p.setBrush(c)
                    p.drawRect(QRectF(bx + i * (segw + gap), 46,
                                      segw, 15))
                f_pct = QFont("Archivo SemiExpanded", 14)
                f_pct.setWeight(QFont.Black)
                f_pct.setItalic(True)
                p.setFont(f_pct)
                p.setPen(QColor(255, 255, 255, 250))
                p.drawText(QPointF(bx + nseg * (segw + gap) + 8, 60),
                           "%d%%" % int(round(self._nrg * 100)))
                f_lab = QFont("Archivo SemiExpanded", 7)
                f_lab.setWeight(QFont.Bold)
                p.setFont(f_lab)
                p.setPen(QColor(255, 255, 255, 210))
                p.drawText(QPointF(bx, 76), self._nrg_kind)
            # velocita' a destra della zona dati
            f_spd = QFont("Archivo SemiExpanded", 27)
            f_spd.setWeight(QFont.Black)
            f_spd.setItalic(True)
            p.setFont(f_spd)
            fs = QFontMetricsF(f_spd)
            kmh = "%d" % int(round(self._speed))
            f_u = QFont("Archivo SemiExpanded", 11)
            f_u.setWeight(QFont.ExtraBold)
            f_u.setItalic(True)
            fu = QFontMetricsF(f_u)
            # ALLINEATO A DESTRA del pannello, come in regia
            right = _W - 44.0
            tot = fs.horizontalAdvance(kmh) + 5 \
                + fu.horizontalAdvance("KMH")
            # mai sovrapposta all'energia: limite sinistro garantito
            sx = max(right - tot, bx + 172.0)
            p.setPen(QColor(255, 255, 255, 250))
            p.drawText(QPointF(sx, 50), kmh)
            p.setFont(f_u)
            p.drawText(QPointF(sx + fs.horizontalAdvance(kmh) + 5, 50),
                       "KMH")
            f_mph = QFont("Archivo SemiExpanded", 12)
            f_mph.setWeight(QFont.DemiBold)
            f_mph.setItalic(True)
            p.setFont(f_mph)
            fmm = QFontMetricsF(f_mph)
            mph = "%d MPH" % int(round(self._speed * 0.621371))
            p.drawText(QPointF(right - fmm.horizontalAdvance(mph), 72),
                       mph)
            p.restore()
        p.end()
