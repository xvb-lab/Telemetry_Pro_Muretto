"""
widgets/wec26flag/widget.py — WEC 2026 Race Control: banner bandiere.

Banner broadcast 2026: blocco navy "RACE CONTROL" + striscia colorata
(RED FLAG rossa, FULL COURSE YELLOW oliva, GREEN FLAG verde, bandiera
blu, gialla di settore, scacchi). Appare SOLO quando c'e' qualcosa da
dire e sparisce da solo. Niente loghi FIA (marchi). Dati: game phase
+ flags() dalla shared memory.
"""
import glob
import json
import os
import re
import threading
import time

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QFontMetricsF

from pathlib import Path

from core.config import get_config
from core.shared_memory import SharedMemory
from core.paths import POSITIONS_FILE

_ROOT = Path(__file__).parent.parent.parent
# banner ORIGINALI (WEC Graphics Pack): dove esiste il PNG si usa
# quello, gli altri stati (red/yel/pen) restano disegnati
_IMG = {"fcy": "fcy.png", "green": "green.png", "blue": "blue.png",
        "chk": "chequered.png"}

_W, _H = 640, 96
_NAVY = QColor("#1E3A78")             # blocco RACE CONTROL
_PANEL = QColor(244, 245, 248, 228)   # pannello chiaro messaggi
_TXT = QColor("#1B2F6B")              # testo navy sul pannello
_STATES = {
    "red":   "RED FLAG.",
    "fcy":   "FULL COURSE YELLOW.",
    "green": "GREEN FLAG.",
    "blue":  "BLUE FLAG.",
    "yel":   "YELLOW SECTOR.",
    "chk":   "CHEQUERED FLAG.",
    "pen":   "PENALTY",
}


def _kind_words(k):
    """'+20S' -> '+20 SECONDS', 'STOP & GO 10S' -> 'STOP & GO 10
    SECONDS', 'DRIVE THROUGH' invariato."""
    k = re.sub(r"^\+(\d+)S$", r"+\1 SECONDS", k)
    return re.sub(r"STOP & GO (\d+)S$", r"STOP & GO \1 SECONDS", k)


class Wec26FlagOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LMU WEC Race Control")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("overlay")
        self._drag_pos = None
        self._user_enabled = True
        self._mem = SharedMemory.instance()
        self._config = get_config()
        self.cfg = self._config.widget("wec26flag")
        self._state = None
        self._green_t = 0.0
        self._prev_phase = None
        self._pens = None              # {mID: n} per vedere le NUOVE
        self._pen = {"kind": "", "reason": "", "car": ""}
        self._pen_t = 0.0
        self._player_car = ""
        # RACE CONTROL VERO: coda sul trace di LMU (motivi delle
        # penalita' scritti dal motore, non esposti da REST/memoria)
        self._running = True
        threading.Thread(target=self._tail_trace, daemon=True).start()
        s = float(self.cfg.scale)
        self.setFixedSize(int(_W * s), int(_H * s))
        pos = self._load_position("wec26flag")
        self.move(pos[0], pos[1]) if pos else self.move(560, 40)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update)
        self._timer.start(self.cfg.get("update_ms", 300))

    def reload_config(self):
        self.cfg = self._config.widget("wec26flag")
        s = float(self.cfg.scale)
        self.setFixedSize(int(_W * s), int(_H * s))
        self._timer.start(self.cfg.get("update_ms", 300))

    def set_enabled(self, enabled):
        self._user_enabled = enabled
        if enabled:
            self._timer.start(self.cfg.get("update_ms", 300))
        else:
            self._timer.stop()
            super().hide()

    def open_config(self):
        from gui.config_window import ConfigWindow
        if getattr(self, "_cfg_win", None) is None:
            self._cfg_win = ConfigWindow(self._config, self,
                                         widget_key="wec26flag",
                                         title="WEC 2026 Race Control")
        self._cfg_win.show()
        self._cfg_win.raise_()

    def closeEvent(self, e):
        self._running = False
        super().closeEvent(e)

    def _tail_trace(self):
        """Penalita' INTERPRETATE dal modulo condiviso: tipo + motivo
        separati, per il layout broadcast a righe."""
        from core.race_control import latest_penalty_parts
        last = 0.0
        while self._running:
            try:
                t, k, r, loc = latest_penalty_parts()
                if t and t != last and (k or r):
                    last = t
                    car = self._player_car if loc else \
                        self._pen.get("car", "") if \
                        time.monotonic() - self._pen_t < 4.0 else ""
                    self._pen = {"kind": k, "reason": r, "car": car}
                    self._pen_t = time.monotonic()
            except Exception:
                pass
            time.sleep(0.5)

    def _update(self):
        if self._user_enabled and self.cfg.get("preview"):
            # PREVIEW: banner demo per posizionare l'overlay
            self._state = "green"
            if not self.isVisible():
                super().show()
                self.raise_()
            self.update()
            return
        if not self._user_enabled or not self._mem.is_on_track():
            if self.isVisible():
                super().hide()
            return
        st = None
        try:
            sim = self._mem._get_sim()
            phase = int(sim.scoring.scoringInfo.mGamePhase) if sim else 0
            # gialla di SETTORE letta diretta (flags() la esporta solo
            # quando trova l'auto lenta davanti — al banner non basta)
            sec_yel = False
            try:
                sf = sim.scoring.scoringInfo.mSectorFlag
                sec_yel = any(int(sf[k]) == 1 for k in range(3))
            except Exception:
                sec_yel = False
            fl = self._mem.flags() or {}
            # PENALITA' NUOVE (qualsiasi auto): LMU non da' il testo del
            # race control, ma il contatore per auto si' — annuncio vero
            try:
                import re as _re
                from pyLMUSharedMemory.lmu_data import \
                    MAX_MAPPED_VEHICLES as _MX
                nv = int(sim.scoring.scoringInfo.mNumVehicles)
                pens = {}
                for i in range(min(nv, _MX)):
                    v = sim.scoring.vehScoringInfo[i]
                    vn = bytes(v.mVehicleName).split(b"\x00")[0] \
                        .decode("utf-8", "ignore")
                    pens[int(v.mID)] = (int(v.mNumPenalties), vn)
                    if int(getattr(v, "mIsPlayer", 0)):
                        pm = _re.search(r"#\s*(\d+)", vn)
                        if pm:
                            self._player_car = pm.group(1)
                if self._pens:
                    for vid, (n, vn) in pens.items():
                        if n > self._pens.get(vid, (0, ""))[0]:
                            m = _re.search(r"#\s*(\d+)", vn)
                            car = m.group(1) if m else ""
                            if time.monotonic() - self._pen_t < 4.0:
                                # stesso evento del trace: completa
                                # solo il numero auto
                                if not self._pen.get("car"):
                                    self._pen["car"] = car
                            else:
                                self._pen = {"kind": "", "reason": "",
                                             "car": car}
                                self._pen_t = time.monotonic()
                self._pens = pens
            except Exception:
                pass
            if self._prev_phase in (6, 7) and phase == 5:
                self._green_t = time.monotonic()   # ripartenza: verde 5s
            self._prev_phase = phase
            if phase == 7:
                st = "red"
            elif phase == 6:
                st = "fcy"
            elif self._pen_t and time.monotonic() - self._pen_t < 6.0:
                st = "pen"
            elif fl.get("checkered"):
                st = "chk"
            elif fl.get("blue_class"):
                st = "blue"
            elif sec_yel or fl.get("yellow_dist") is not None:
                st = "yel"
            elif time.monotonic() - self._green_t < 5.0:
                st = "green"
        except Exception:
            st = None
        self._state = st
        if st and not self.isVisible():
            super().show()
            self.raise_()
        elif not st and self.isVisible():
            super().hide()
        if st:
            self.update()

    def _msg_lines(self):
        """Righe del pannello, stile decisione FIA broadcast."""
        if self._state != "pen":
            return [_STATES[self._state]]
        k = self._pen.get("kind", "")
        lines = ["PENALTY: %s" % _kind_words(k) if k else "PENALTY"]
        if self._pen.get("car"):
            lines.append("CAR %s" % self._pen["car"])
        if self._pen.get("reason"):
            lines.append("(%s)." % self._pen["reason"])
        return lines

    def _flag_pixmap(self, st):
        fn = _IMG.get(st)
        if not fn:
            return None
        if not hasattr(self, "_pix_cache"):
            self._pix_cache = {}
        if fn not in self._pix_cache:
            from PySide6.QtGui import QPixmap
            path = _ROOT / "assets" / "racecontrol" / fn
            self._pix_cache[fn] = QPixmap(str(path)) \
                if path.exists() else QPixmap()
        px = self._pix_cache[fn]
        return px if not px.isNull() else None

    def paintEvent(self, e):
        if not self._state:
            return
        img = self._flag_pixmap(self._state)
        if img:
            # banner ORIGINALE: scala a larghezza piena, ratio intatta
            p = QPainter(self)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            w = self.width()
            h = round(w * img.height() / img.width())
            y = (self.height() - h) / 2.0
            p.drawPixmap(QRectF(0.0, y, float(w), float(h)), img,
                         QRectF(img.rect()))
            p.end()
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        s = self.width() / float(_W)
        p.scale(s, s)
        LB = 160.0
        # blocco navy RACE CONTROL
        p.setPen(Qt.NoPen)
        p.setBrush(_NAVY)
        p.drawRect(QRectF(0, 0, LB, _H))
        f_rc = QFont("Druk Wide Cy TT", 13)
        f_rc.setWeight(QFont.Black)
        f_rc.setItalic(True)
        p.setFont(f_rc)
        fr = QFontMetricsF(f_rc)
        p.setPen(QColor(255, 255, 255, 240))
        p.drawText(QPointF((LB - fr.horizontalAdvance("RACE")) / 2,
                           _H / 2.0 - 6), "RACE")
        p.drawText(QPointF((LB - fr.horizontalAdvance("CONTROL")) / 2,
                           _H / 2.0 + 16), "CONTROL")
        # pannello chiaro coi messaggi (testo navy corsivo, righe)
        p.setPen(Qt.NoPen)
        p.setBrush(_PANEL)
        p.drawRect(QRectF(LB, 0, _W - LB, _H))
        lines = self._msg_lines()
        f_tx = QFont("Druk Wide Cy TT", 15)
        f_tx.setWeight(QFont.Black)
        f_tx.setItalic(True)
        p.setFont(f_tx)
        ft = QFontMetricsF(f_tx)
        lh = 26.0
        y0 = (_H - lh * len(lines)) / 2.0 + ft.ascent() + 2
        p.setPen(_TXT)
        for i, ln in enumerate(lines):
            p.drawText(QPointF(LB + 24, y0 + i * lh), ln)
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
                data["wec26flag"] = [self.x(), self.y()]
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
