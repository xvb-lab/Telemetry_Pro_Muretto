"""
widgets/weconboard/widget.py — WEC Onboard: barra driver broadcast 2025.

Replica NATIVA della barra onboard della regia FIA WEC 2025: blocco
colore classe con logo costruttore e NUMERO auto, pedali freno/gas,
VIRTUAL ENERGY TANK a tacchette con percentuale, velocita' KMH+MPH,
striscia TELEMETRY. Niente foto piloti ne' loghi sponsor (diritti).
Energia: virtual energy (REST) > batteria > benzina, come WEC Pedals.
"""
import json
import re
import time
import threading
import urllib.request
from pathlib import Path

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QFontMetricsF
from PySide6.QtSvg import QSvgRenderer

from core.config import get_config
from core.shared_memory import SharedMemory
from core.classes import class_tag
from core.brands import brand_from_vehicle
from core.utils import find_logo_path
from core.paths import POSITIONS_FILE

_W, _H = 560, 132
_MAIN = 108                              # altezza barra principale
_CLS_COL = {"HY": QColor("#C3122A"), "P2": QColor("#2A6BB5"),
            "P3": QColor("#9038D6"), "GT3": QColor("#F58021"),
            "GTE": QColor("#168749")}
_NAVY = QColor(16, 12, 66, 245)          # navy blocco centrale
_NAVY_D = QColor(8, 4, 40, 250)

_LMU_API = "http://localhost:6397"
_REST_PATH = "/rest/garage/UIScreen/RepairAndRefuel"


class WecOnboardOverlay(QWidget):
    KEY = "weconboard"
    TITLE = "WEC 2024 Onboard"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("LMU WEC Onboard")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("overlay")
        self._drag_pos = None
        self._user_enabled = True
        self._mem = SharedMemory.instance()
        self._config = get_config()
        self.cfg = self._config.widget(self.KEY)
        self._thr = 0.0
        self._brk = 0.0
        self._speed = 0.0
        self._num = ""
        self._brand = ""
        self._tag = "HY"
        self._nrg = None
        self._nrg_kind = "NRG"
        self._ve = None
        self._logo = None                # QSvgRenderer cache
        self._logo_brand = None
        self._lock = threading.Lock()
        self._running = True
        threading.Thread(target=self._loop_rest, daemon=True).start()
        self._apply_scale()
        pos = self._load_position(self.KEY)
        self.move(pos[0], pos[1]) if pos else self.move(600, 60)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update)
        self._timer.start(self.cfg.get("update_ms", 50))

    def _apply_scale(self):
        s = float(self.cfg.scale)
        self.setFixedSize(int(_W * s), int(_H * s))
        self.setWindowOpacity(
            max(0.15, float(self.cfg.get("bg_opacity", 100)) / 100.0))

    def reload_config(self):
        self.cfg = self._config.widget(self.KEY)
        self._apply_scale()
        self._timer.start(self.cfg.get("update_ms", 50))

    def set_enabled(self, enabled):
        self._user_enabled = enabled
        if enabled:
            self._timer.start(self.cfg.get("update_ms", 50))
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
                                         widget_key=self.KEY,
                                         title=self.TITLE)
        self._cfg_win.show()
        self._cfg_win.raise_()

    def closeEvent(self, e):
        self._running = False
        super().closeEvent(e)

    # ── dati ──────────────────────────────────────────────────────────
    def _loop_rest(self):
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
            vp = sim.scoring.vehScoringInfo[pidx]
            vname = bytes(vp.mVehicleName).split(b"\x00")[0] \
                .decode("utf-8", "ignore")
            m = re.search(r"#\s*(\d{1,3})", vname)
            self._num = m.group(1) if m else ""
            self._brand = brand_from_vehicle(vname)
            _vm = re.sub(r"#\s*\d+", "", vname)
            _vm = re.sub(r"\s*(19|20)\d{2}.*$", "", _vm)  # via anno+:WEC
            self._vmodel = _vm.split(":")[0].strip().upper()
            # "CUSTOM TEAM" di LMU -> il TUO team dal profilo app
            # (se nel profilo non c'e', resta com'e')
            if "CUSTOM TEAM" in self._vmodel:
                if not hasattr(self, "_profile_team"):
                    try:
                        import json as _js
                        from core.paths import USER_DIR as _UD
                        self._profile_team = str(_js.loads(
                            (_UD / "profile.json")
                            .read_text(encoding="utf-8"))
                            .get("team") or "").strip()
                    except Exception:
                        self._profile_team = ""
                if self._profile_team:
                    self._vmodel = self._profile_team.upper()
            self._tag = class_tag(bytes(vp.mVehicleClass).split(b"\x00")[0]
                                  .decode("utf-8", "ignore")) or self._tag
            pid = int(vp.mID)
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
            v = t.mLocalVel
            self._speed = (v.x * v.x + v.y * v.y + v.z * v.z) ** 0.5 * 3.6
            with self._lock:
                ve = self._ve
            if ve is not None:
                self._nrg, self._nrg_kind = ve, "VIRTUAL ENERGY TANK"
            else:
                try:
                    b = float(t.mBatteryChargeFraction)
                except Exception:
                    b = 0.0
                if 0.0 < b <= 1.0:
                    self._nrg, self._nrg_kind = b, "BATTERY"
                else:
                    try:
                        fm = float(t.mFuelCapacity)
                        self._nrg = max(0.0, min(1.0, float(t.mFuel) / fm)) \
                            if fm > 0 else None
                    except Exception:
                        self._nrg = None
                    self._nrg_kind = "FUEL TANK"
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
        s = self.width() / float(_W)
        p.scale(s, s)

        # blocco sinistro: colore classe + logo + numero
        LB = 150.0
        p.setPen(Qt.NoPen)
        p.setBrush(_CLS_COL.get(self._tag, QColor("#666666")))
        p.drawRect(QRectF(0, 0, LB, _MAIN))
        if self._brand and self._brand != self._logo_brand:
            self._logo_brand = self._brand
            try:
                lp = find_logo_path(self._brand)
                self._logo = QSvgRenderer(str(lp)) if lp else None
            except Exception:
                self._logo = None
        if self._logo:
            self._logo.render(p, QRectF(10, (_MAIN - 44) / 2.0, 44, 44))
        f_num = QFont("Archivo SemiExpanded", 40)
        f_num.setWeight(QFont.Black)
        p.setFont(f_num)
        fn = QFontMetricsF(f_num)
        numtxt = self._num or self._tag
        p.setPen(QColor(255, 255, 255, 250))
        p.drawText(QPointF(62 + (LB - 62 - fn.horizontalAdvance(numtxt))
                           / 2.0, (_MAIN + fn.ascent()) / 2.0 - 4), numtxt)

        # blocco centrale: pedali + energia
        MB = 230.0
        p.setPen(Qt.NoPen)
        p.setBrush(_NAVY)
        p.drawRect(QRectF(LB, 0, MB, _MAIN))
        bx, bw = LB + 18, MB - 36
        # pedali: meta' sinistra FRENO (bianco), meta' destra GAS (verde)
        by, bh = 16.0, 13.0
        p.setBrush(QColor(255, 255, 255, 40))
        p.drawRect(QRectF(bx, by, bw, bh))
        half = bw / 2.0
        p.setBrush(QColor(255, 255, 255, 240))
        p.drawRect(QRectF(bx + half - half * self._brk, by,
                          half * self._brk, bh))
        p.setBrush(QColor("#2BD62B"))
        p.drawRect(QRectF(bx + half, by, half * self._thr, bh))
        p.setPen(QPen(QColor(255, 255, 255, 220), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(bx, by, bw, bh))
        p.drawLine(QPointF(bx + half, by - 2),
                   QPointF(bx + half, by + bh + 2))
        # energia: tacchette (rosse in riserva) + percentuale
        if self._nrg is not None:
            ey, eh = 48.0, 16.0
            nseg = 22
            segw, gap = 4.0, 2.5
            lit = int(round(self._nrg * nseg))
            p.setPen(Qt.NoPen)
            for i in range(nseg):
                if i < lit:
                    col = QColor("#E33A2B") if i < nseg * 0.2 \
                        else QColor(255, 255, 255, 240)
                else:
                    col = QColor(255, 255, 255, 45)
                p.setBrush(col)
                p.drawRect(QRectF(bx + i * (segw + gap), ey, segw, eh))
            f_pct = QFont("Archivo SemiExpanded", 15)
            f_pct.setWeight(QFont.Black)
            f_pct.setItalic(True)
            p.setFont(f_pct)
            fp = QFontMetricsF(f_pct)
            pct = "%d%%" % int(round(self._nrg * 100))
            p.setPen(QColor(255, 255, 255, 250))
            p.drawText(QPointF(bx + bw - fp.horizontalAdvance(pct),
                               ey + (eh + fp.ascent()) / 2.0 - 2), pct)
            f_lab = QFont("Archivo SemiExpanded", 8)
            f_lab.setWeight(QFont.Bold)
            f_lab.setLetterSpacing(QFont.AbsoluteSpacing, 1.0)
            p.setFont(f_lab)
            p.setPen(QColor(255, 255, 255, 200))
            p.drawText(QPointF(bx, ey + eh + 18), self._nrg_kind)

        # blocco destro: velocita'
        RB = _W - LB - MB
        p.setPen(Qt.NoPen)
        p.setBrush(_NAVY)
        p.drawRect(QRectF(LB + MB, 0, RB, _MAIN))
        f_spd = QFont("Archivo SemiExpanded", 34)
        f_spd.setWeight(QFont.Black)
        p.setFont(f_spd)
        fs = QFontMetricsF(f_spd)
        kmh = "%d" % int(round(self._speed))
        f_u = QFont("Archivo SemiExpanded", 12)
        f_u.setWeight(QFont.ExtraBold)
        fu = QFontMetricsF(f_u)
        tot = fs.horizontalAdvance(kmh) + 6 + fu.horizontalAdvance("KMH")
        x0 = LB + MB + (RB - tot) / 2.0
        p.setPen(QColor(255, 255, 255, 250))
        p.drawText(QPointF(x0, 56), kmh)
        p.setFont(f_u)
        p.drawText(QPointF(x0 + fs.horizontalAdvance(kmh) + 6, 56), "KMH")
        f_mph = QFont("Archivo SemiExpanded", 13)
        f_mph.setWeight(QFont.DemiBold)
        p.setFont(f_mph)
        fm2 = QFontMetricsF(f_mph)
        mph = "%d MPH" % int(round(self._speed * 0.621371))
        p.drawText(QPointF(LB + MB + (RB - fm2.horizontalAdvance(mph))
                           / 2.0, 82), mph)

        # striscia bassa: TELEMETRY
        p.setPen(Qt.NoPen)
        p.setBrush(_NAVY_D)
        p.drawRect(QRectF(0, _MAIN, _W, _H - _MAIN))
        f_t = QFont("Archivo SemiExpanded", 10)
        f_t.setWeight(QFont.Black)
        f_t.setLetterSpacing(QFont.AbsoluteSpacing, 3.0)
        p.setFont(f_t)
        ft = QFontMetricsF(f_t)
        txt = "LMU TELEMETRY PRO"
        p.setPen(QColor(255, 255, 255, 235))
        p.drawText(QPointF((_W - ft.horizontalAdvance(txt)) / 2.0,
                           _MAIN + (_H - _MAIN + ft.ascent()) / 2.0 - 2),
                   txt)
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
            self._save_position(self.KEY)
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
