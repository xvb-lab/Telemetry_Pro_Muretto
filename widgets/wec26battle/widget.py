"""
widgets/wec26battle/widget.py — WEC 2026 Battle: card onboard dei rivali.

DUE card identiche alla WEC 2026 Onboard (stessi template per
costruttore/classe) ma coi dati DEGLI ALTRI: sopra chi ti sta DAVANTI,
sotto chi ti sta DIETRO — numero, pilota, posizione e gap. Ogni card
appare solo quando il distacco e' sotto battle_gap_s (default 2s),
come la regia quando inquadra una lotta. Dati dal RelativeReader.
"""
import json
import re
import time  # rotazione dati card + anti-sfarfallio

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF
from PySide6.QtGui import (QPainter, QColor, QFont, QFontMetricsF,
                           QPixmap)

from core.config import get_config
from core.shared_memory import SharedMemory
from core.classes import class_tag
from core.paths import POSITIONS_FILE
from widgets.relative.reader import RelativeReader
from widgets.wec26board.widget import _tpl_name, _W as _CW, _H as _CH

_GAPY = 8


def _gapval(row):
    """Gap in secondi dal RelativeReader: vive in 'gap_leader' (assoluto,
    segno a parte in '_gap_sign'); 0 = dato assente. In preview arriva
    invece come stringa in 'gap'."""
    if not row:
        return None
    g = row.get("gap_leader")
    if g in (None, 0, 0.0):
        g = row.get("gap")
    try:
        g = abs(float(str(g).replace("+", "").replace(",", ".")))
    except (TypeError, ValueError):
        return None
    return g if g > 0.0 else None


class Wec26BattleOverlay(QWidget):
    KEY = "wec26battle"
    TITLE = "WEC 2026 Battle Ahead"
    SIDE = "A"                # "A" = rivale davanti, "B" = dietro

    def __init__(self):
        super().__init__()
        self.setWindowTitle("LMU WEC Battle")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("overlay")
        self._drag_pos = None
        self._user_enabled = True
        self._mem = SharedMemory.instance()
        self._config = get_config()
        self.cfg = self._config.widget(self.KEY)
        self._reader = RelativeReader()
        self._cards = []               # [(row, "A"|"ME"|"B")]
        self._tpls = {}
        self._last_in = {}             # anti-sfarfallio: ultimo ok per lato
        self._me_thr = 0.0             # pedali del player (per il pannello)
        self._me_brk = 0.0
        self._laps = {}                # giri visti per slot (flash lap)
        self._flash = {}               # {slot: (t0, last_lap)} 10s
        self._apply_scale()
        pos = self._load_position(self.KEY)
        self.move(pos[0], pos[1]) if pos else self.move(700, 260)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update)
        self._timer.start(min(int(self.cfg.get("update_ms", 50)), 50))

    def _apply_scale(self):
        s = float(self.cfg.scale)
        self.setFixedSize(int(_CW * s), int(_CH * s))   # UNA card
        self.setWindowOpacity(
            max(0.15, float(self.cfg.get("bg_opacity", 100)) / 100.0))

    def reload_config(self):
        self.cfg = self._config.widget(self.KEY)
        self._apply_scale()
        self._timer.start(min(int(self.cfg.get("update_ms", 50)), 50))

    def set_enabled(self, enabled):
        self._user_enabled = enabled
        if enabled:
            self._timer.start(min(int(self.cfg.get("update_ms", 50)), 50))
        else:
            self._timer.stop()
            super().hide()

    def open_config(self):
        from gui.config_window import ConfigWindow
        if getattr(self, "_cfg_win", None) is None:
            self._cfg_win = ConfigWindow(self._config, self,
                                         widget_key=self.KEY,
                                         title=self.TITLE)
        self._cfg_win.show()
        self._cfg_win.raise_()

    def _update(self):
        if self._user_enabled and self.cfg.get("preview"):
            # PREVIEW: card demo per posizionare l'overlay
            if self.SIDE == "A":
                self._cards = [({"place_class": 2, "brand": "Ferrari",
                                 "car_number": "50",
                                 "name": "Rivale Davanti", "gap": "1.2",
                                 "car_class": "HY", "in_pits": False},
                                "A")]
            else:
                self._cards = [({"place_class": 4, "brand": "Porsche",
                                 "car_number": "6",
                                 "name": "Rivale Dietro", "gap": "0.8",
                                 "car_class": "HY", "in_pits": False},
                                "B")]
            if not self.isVisible():
                super().show()
                self.raise_()
            self.update()
            return
        if not self._user_enabled or not self._mem.is_on_track():
            if self.isVisible():
                super().hide()
            return
        cards = []
        try:
            data = self._reader.read(rows_each_side=3) or []
            if isinstance(data, tuple):
                data = data[0] or []
            me_i = next((i for i, r in enumerate(data)
                         if r and r.get("is_player")), None)
            if me_i is not None:
                thr = float(self.cfg.get("battle_gap_s", 2.0))
                hold = float(self.cfg.get("hold_s", 3.0))
                now = __import__("time").monotonic()
                # filtri: solo la mia classe / solo lotta di posizione
                me = data[me_i]
                from core.classes import class_tag as _ct
                myc = _ct(me.get("car_class") or "")
                myl = int(me.get("laps_done") or 0)

                def _skip(r):
                    if not r or r.get("in_garage"):
                        return True
                    if self.cfg.get("class_only") \
                            and _ct(r.get("car_class") or "") != myc:
                        return True
                    if self.cfg.get("pos_only") \
                            and abs(int(r.get("laps_done") or 0)
                                    - myl) >= 1:
                        return True
                    return False
                if self.SIDE == "A":
                    sides = ((range(me_i - 1, -1, -1), "A"),)
                else:
                    sides = ((range(me_i + 1, len(data)), "B"),)
                for rng, kind in sides:
                    idx = next((j for j in rng
                                if not _skip(data[j])), None)
                    if idx is not None:
                        r = data[idx]
                        g = _gapval(r)
                        ok = bool(r and g is not None and g <= thr
                                  and not r.get("in_garage"))
                        if ok:
                            self._last_in[kind] = now
                        # anti-sfarfallio: la card resta hold_s secondi
                        # dopo essere uscita dalla soglia (mai a scatti)
                        if r and not r.get("in_garage") and (
                                ok or now - self._last_in.get(kind, -9e9)
                                <= hold):
                            cards.append((r, kind))
                # niente card player: c'e' gia' la sua Onboard
        except Exception:
            cards = []
        # FLASH LAST LAP: al taglio del traguardo memorizza il tempo
        # (mostrato al posto del gap per 10 secondi)
        nowf = time.monotonic()
        for r, _k in cards:
            sid = r.get("slot_id")
            if sid is None:
                continue
            ld = int(r.get("laps_done") or 0)
            prev = self._laps.get(sid)
            self._laps[sid] = ld
            ll = float(r.get("last_lap") or 0.0)
            if prev is not None and ld > prev and ll > 20.0:
                self._flash[sid] = (nowf, ll)
        # pedali del PLAYER dalla shared memory (per il pannello ME)
        try:
            sim = self._mem._get_sim()
            from pyLMUSharedMemory.lmu_data import \
                MAX_MAPPED_VEHICLES as _MX
            nv = int(sim.scoring.scoringInfo.mNumVehicles)
            pid = None
            for i in range(min(nv, _MX)):
                if sim.scoring.vehScoringInfo[i].mIsPlayer:
                    pid = int(sim.scoring.vehScoringInfo[i].mID)
                    break
            for i in range(min(nv, _MX)):
                t = sim.telemetry.telemInfo[i]
                if pid is not None and int(t.mID) == pid:
                    self._me_thr = max(0.0, min(1.0, float(
                        t.mUnfilteredThrottle)))
                    self._me_brk = max(0.0, min(1.0, float(
                        t.mUnfilteredBrake)))
                    break
        except Exception:
            pass
        self._cards = cards
        if cards and not self.isVisible():
            super().show()
            self.raise_()
        elif not cards and self.isVisible():
            super().hide()
        if cards:
            self.update()

    def _logo_r(self, brand):
        """QSvgRenderer del logo CARD (cardlogo/ > brandlogo/), cache."""
        if brand not in self._tpls:
            try:
                from PySide6.QtSvg import QSvgRenderer
                from core.wec_style import card_logo_path
                lp = card_logo_path(brand)
                self._tpls[brand] = QSvgRenderer(str(lp)) if lp else None
            except Exception:
                self._tpls[brand] = None
        return self._tpls[brand]

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        s = self.width() / float(_CW)
        p.scale(s, s)
        # UNA card per widget: ognuna si posiziona dove vuoi
        slot = {self.SIDE: 0.0}
        for row, kind in self._cards:
            y = slot[kind]
            p.save()
            p.translate(0, y)
            tag = class_tag(row.get("car_class") or "") or "HY"
            brand = row.get("brand") or ""
            model = re.sub(r"#\s*\d+", "",
                           str(row.get("veh_name") or ""))
            model = re.sub(r"\s*(19|20)\d{2}.*$", "", model)
            model = model.split(":")[0].strip().upper()
            from widgets.wec26board.widget import draw_card_base
            from core.wec_style import text_on, CLASS_CHIP
            # in Battle: CLASSE al posto di ONBOARD, col SUO colore
            _cl, _cc = CLASS_CHIP.get(tag, ("HYPERCAR", "#C3122A"))
            draw_card_base(p, brand, tag, model, self._logo_r(brand),
                           right_label=_cl, right_color=_cc, chip=False)
            txc = QColor(text_on(brand))
            num = row.get("car_number") or ""
            if not num:
                m = re.search(r"#\s*(\d{1,3})",
                              str(row.get("veh_name") or ""))
                num = m.group(1) if m else tag
            f_num = QFont("Archivo SemiExpanded", 42)
            f_num.setWeight(QFont.Black)
            f_num.setItalic(True)
            p.setFont(f_num)
            fn = QFontMetricsF(f_num)
            p.setPen(txc)                     # scuro su basi chiare
            p.drawText(QPointF(140, 76), str(num))
            zx = 162 + fn.horizontalAdvance(str(num))
            f_dr = QFont("Archivo SemiExpanded", 19)
            f_dr.setWeight(QFont.Black)
            f_dr.setItalic(True)
            p.setFont(f_dr)
            fd = QFontMetricsF(f_dr)
            name = str(row.get("name") or "").upper()
            while name and fd.horizontalAdvance(name) > _CW - zx - 40:
                name = name[:-1]
            p.drawText(QPointF(zx, 48), name)
            f_pg = QFont("Archivo SemiExpanded", 20)
            f_pg.setWeight(QFont.Black)
            f_pg.setItalic(True)
            p.setFont(f_pg)
            if kind == "ME":
                gtx = ""                       # la tua card: solo P
            else:
                gv = _gapval(row)
                gtx = "PIT" if row.get("in_pits") else (
                    ("%.1f" % gv) if gv is not None else "")
                if gtx and gtx != "PIT":
                    gtx = ("-" + gtx) if kind == "A" else ("+" + gtx)
            # al taglio del traguardo: LAST LAP al posto del gap (10s)
            fl = self._flash.get(row.get("slot_id"))
            if fl and time.monotonic() - fl[0] < 10.0:
                _t = fl[1]
                _m = int(_t // 60)
                gtx = "%d:%06.3f" % (_m, _t - _m * 60)
            pos = row.get("place_class") or 0
            pg = ("P%d" % pos if pos else "") + \
                ("   %s" % gtx if gtx else "")
            p.drawText(QPointF(zx, 76), pg.strip())
            # PERCENTUALE ENERGIA a destra (dato vero di quest'auto)
            _ve = row.get("v_energy")
            if _ve is not None:
                f_ve = QFont("Archivo SemiExpanded", 15)
                f_ve.setWeight(QFont.Black)
                f_ve.setItalic(True)
                p.setFont(f_ve)
                fv = QFontMetricsF(f_ve)
                vt = "%d%%" % round(float(_ve))
                p.drawText(QPointF(_CW - 36 - fv.horizontalAdvance(vt),
                                   78), vt)
            # TELEMETRIA a rotazione (rotate_s): pannello navy #0A0032
            # che SCORRE da destra come la card Onboard, coi dati VERI
            # di quest'auto (velocita', energia, gomma) — se ci sono
            rot = float(self.cfg.get("rotate_s", 10.0))
            spd = row.get("speed_kmh")
            ve = row.get("v_energy")
            # telemetria in Battle: DISATTIVATA (card sempre pulite,
            # la telemetria vive nella Onboard) — scelta del pilota
            if False and (spd or ve is not None):
                ph = time.monotonic() / max(3.0, rot)
                k = ph - int(ph)
                sl = min(1.0, k / 0.12)        # slide in testa al ciclo
                ft = sl if int(ph) % 2 else 1.0 - sl
                if ft > 0.01:
                    strip_y = _CH * (338.0 / 431.0)
                    pw = _CW - zx
                    dx = pw * (1.0 - ft)
                    p.save()
                    p.setClipRect(QRectF(zx + dx, 0, _CW - zx - dx,
                                         strip_y))
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(49, 44, 84, 248))  # #312C54
                    p.drawRect(QRectF(zx + dx, 0, _CW - zx - dx,
                                      strip_y))
                    p.translate(dx, 0)
                    # pedali del player: freno bianco / gas verde
                    pbx, pbw = zx, 150.0
                    ph2 = pbw / 2.0
                    p.setBrush(QColor(255, 255, 255, 55))
                    p.drawRect(QRectF(pbx, 18, pbw, 9))
                    p.setBrush(QColor(255, 255, 255, 240))
                    p.drawRect(QRectF(pbx + ph2 - ph2 * self._me_brk,
                                      18, ph2 * self._me_brk, 9))
                    p.setBrush(QColor("#2BD62B"))
                    p.drawRect(QRectF(pbx + ph2, 18,
                                      ph2 * self._me_thr, 9))
                    p.setPen(QPen(QColor(255, 255, 255, 220), 1))
                    p.setBrush(Qt.NoBrush)
                    p.drawLine(QPointF(pbx + ph2, 15),
                               QPointF(pbx + ph2, 29))
                    p.setPen(Qt.NoPen)
                    if ve is not None:
                        rain = ("#E33A2B", "#F5731F", "#F5A623",
                                "#F5D90A", "#A8E10C", "#3FE05A",
                                "#2BD6C4", "#2B9AD6", "#4B6BE8",
                                "#7A4BE8", "#A83AE0", "#D63AC4",
                                "#E8398F", "#E8395A")
                        lit = int(round(float(ve) / 100.0 * 14))
                        for i in range(14):
                            c = QColor(rain[i]) if i < lit \
                                else QColor(255, 255, 255, 45)
                            p.setBrush(c)
                            p.drawRect(QRectF(zx + i * 7.6, 44, 5.0, 14))
                        f_pc = QFont("Archivo SemiExpanded", 13)
                        f_pc.setWeight(QFont.Black)
                        f_pc.setItalic(True)
                        p.setFont(f_pc)
                        p.setPen(QColor(255, 255, 255, 250))
                        p.drawText(QPointF(zx + 14 * 7.6 + 8, 58),
                                   "%d%%" % round(float(ve)))
                        f_lb = QFont("Archivo SemiExpanded", 7)
                        f_lb.setWeight(QFont.Bold)
                        p.setFont(f_lb)
                        p.setPen(QColor(255, 255, 255, 200))
                        p.drawText(QPointF(zx, 74),
                                   "VIRTUAL ENERGY TANK")
                    if spd:
                        f_sp = QFont("Archivo SemiExpanded", 24)
                        f_sp.setWeight(QFont.Black)
                        f_sp.setItalic(True)
                        p.setFont(f_sp)
                        fsp = QFontMetricsF(f_sp)
                        kmh = "%d" % int(spd)
                        sx = _CW - 185.0
                        p.setPen(QColor(255, 255, 255, 250))
                        p.drawText(QPointF(sx, 56), kmh)
                        f_su = QFont("Archivo SemiExpanded", 10)
                        f_su.setWeight(QFont.ExtraBold)
                        f_su.setItalic(True)
                        p.setFont(f_su)
                        p.drawText(QPointF(
                            sx + fsp.horizontalAdvance(kmh) + 5, 56),
                            "KMH")
                        f_sm = QFont("Archivo SemiExpanded", 11)
                        f_sm.setWeight(QFont.DemiBold)
                        f_sm.setItalic(True)
                        p.setFont(f_sm)
                        p.drawText(QPointF(sx, 76), "%d MPH"
                                   % int(round(spd * 0.621371)))
                    p.restore()
            p.restore()
        p.end()

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
            try:
                data = {}
                if POSITIONS_FILE.exists():
                    data = json.loads(POSITIONS_FILE.read_text())
                data[self.KEY] = [self.x(), self.y()]
                POSITIONS_FILE.write_text(json.dumps(data, indent=2))
            except Exception:
                pass
        self._drag_pos = None

    def _load_position(self, key):
        try:
            if POSITIONS_FILE.exists():
                return json.loads(POSITIONS_FILE.read_text()).get(key)
        except Exception:
            pass
        return None


class Wec26BattleBOverlay(Wec26BattleOverlay):
    """Card del rivale DIETRO: posizionabile per conto suo."""
    KEY = "wec26battleb"
    TITLE = "WEC 2026 Battle Behind"
    SIDE = "B"
