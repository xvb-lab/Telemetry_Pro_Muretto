"""
widgets/wec26flag/widget.py — WEC 2026 Race Control (stile FIA).

Un solo overlay con DUE zone INDIPENDENTI (non si coprono mai), impilate:
- ZONA BANDIERE (stati): green/blue/chequered/black/red/PITS CLOSED/
  yellow sector + WET (persistente, priorita' piu' bassa). green/blue/
  chequered/black usano i PNG FIA; le altre sono disegnate (head + striscia).
- ZONA MESSAGGI (coda 10s): penalita' del player (box rosso, frase stile
  direttore di gara "... FOR ...") + track limits UNDER REVIEW (dal segnale
  VERO del trace) + messaggi gara.

3 toggle in config (default ON): show_flags / show_penalties / show_messages.
Le due zone sono a se': la gialla e la DT convivono, una sopra e una sotto.
In LMU la FCY NON esiste. Dati: game phase + mSectorFlag + flags() + track
limits (trace race_control) + penalita' (trace) + meteo (get_weather).
"""
import json
import re
import threading
import time

from pathlib import Path

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF
from PySide6.QtGui import (QPainter, QColor, QFont, QFontMetricsF, QPixmap)

from core.config import get_config
from core.shared_memory import SharedMemory
from core.paths import POSITIONS_FILE

_ROOT = Path(__file__).parent.parent.parent
_IMG = {"green": "green.png", "blue": "blue.png",
        "chk": "chequered.png", "black": "black.png"}

_W, _H = 640, 96
_HC = round(_W * 331.0 / 2503.0)           # altezza contenuto (~85)
_Y0 = (_H - _HC) / 2.0
_HW = _HC * 603.0 / 331.0                   # larghezza head FIA (~155)

_WHITE = QColor(244, 245, 248)
_TXT = QColor("#0F2A5E")                    # navy testo su bianco
_RED = QColor("#d0021b")
_YEL = QColor("#ffd200")
_WET = QColor("#0C4A6E")                    # blu scuro WET (come il dash)

# colori livello track limits (LMU color-coding)
_LV_GREEN = "#22b24c"
_LV_YEL = "#ffd200"
_LV_ORANGE = "#ff7a00"
_LV_RED = "#d0021b"
_LV_PURPLE = "#8a3ffb"

_MSG_TTL = 10.0          # durata messaggio in coda
_GREEN_TTL = 5.0         # durata GREEN alla partenza

# font FISSI (grandi, leggibili): la STRISCIA si allunga sul testo
_F_FLAG = 26
_F_MSG = 24
_F_CHIP = 20
_CHIP_PADX = 14.0        # margine interno testo chip
_CHIP_GAP = 6.0          # spazio tra chip
_CHIP_PAD0 = 16.0        # margine strip sinistra/destra
_BLUE = QColor("#1e63c8")
_PAD_L = 22.0
_PAD_R = 44.0
_SQ = _HC * 0.40
_SQ_GAP = 8.0
_SQ_TXT = 18.0


def _font(px):
    f = QFont("Archivo SemiExpanded", int(px))
    f.setWeight(QFont.Black)
    f.setItalic(True)
    return f


def _pen_phrase(kind, reason):
    """Frase penalita' stile direttore di gara FIA (solo player):
    '<PENALITA'> FOR <MOTIVO LMU verbatim>'. reason gia' MAIUSCOLO."""
    reason = (reason or "").strip()
    k = (kind or "").upper()
    if k == "DRIVE THROUGH":
        pen = "DRIVE-THROUGH"
    elif k.startswith("STOP & GO"):
        m = re.search(r"(\d+)", k)
        pen = "%ss STOP & GO" % m.group(1) if m else "STOP & GO"
    elif k.startswith("+"):
        m = re.search(r"(\d+)", k)
        pen = "%ss TIME PENALTY" % m.group(1) if m else "TIME PENALTY"
    else:
        pen = "PENALTY"
    if reason:
        return "%s FOR %s" % (pen, reason)
    return pen


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
        # motore
        self._prev_phase = None
        self._green_t = 0.0
        self._queue = []             # messaggi penalita' in coda
        self._cur = None             # messaggio corrente
        self._cur_start = None
        self._pix_cache = {}
        self._zones = []             # [(disp, native_w), ...] zone attive
        # penalita' dal trace (thread)
        self._pen_lock = threading.Lock()
        self._pen_new = None
        self._pen_seen_t = 0.0
        self._running = True
        threading.Thread(target=self._tail_trace, daemon=True).start()
        s = float(self.cfg.scale)
        self.setFixedSize(int(_W * s), int(_H * s))
        pos = self._load_position("wec26flag")
        self.move(pos[0], pos[1]) if pos else self.move(560, 40)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update)
        self._timer.start(self.cfg.get("update_ms", 300))

    # ── ciclo di vita / config ──────────────────────────────────────
    def reload_config(self):
        self.cfg = self._config.widget("wec26flag")
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

    # ── trace penalita' (solo player) ───────────────────────────────
    def _tail_trace(self):
        from core.race_control import latest_penalty_parts
        last = 0.0
        while self._running:
            try:
                t, k, r, loc = latest_penalty_parts()
                if t and t != last and loc and (k or r):
                    last = t
                    with self._pen_lock:
                        self._pen_new = (t, k, r)
            except Exception:
                pass
            time.sleep(0.5)

    # ── ZONA BANDIERE ───────────────────────────────────────────────
    def _compute_flag(self, sim, phase):
        """Bandiera-stato attiva (o None), per priorita' decrescente.
        WET e' l'ULTIMA: persistente finche' la gara e' bagnata."""
        fl = self._mem.flags() or {}
        pits_closed = False
        try:
            pits_closed = int(sim.scoring.scoringInfo.mYellowFlagState) == 2
        except Exception:
            pits_closed = False
        # ESCLUSIVE: occupano tutta la zona (stato dominante)
        if phase == 7:
            return ("flag", _RED, "RED FLAG", False)
        if pits_closed:
            return ("flag", _RED, "PITS CLOSED", False)
        if fl.get("checkered") or phase == 8:
            return ("png", "chk")
        if time.monotonic() - self._green_t < _GREEN_TTL:
            return ("png", "green")
        # COESISTENTI: giallo / blu / wet -> chip AFFIANCATE (come la V2).
        # GIALLA: SOLO ed ESCLUSIVAMENTE i 500m davanti (yellow_dist),
        # come e' sempre stato — MAI i settori. (richiesta utente)
        chips = []
        # SEMAFORO PIT (alla TinyPedal: pit aperta = mGamePhase > 0 in
        # prova/quali; in gara chiusa fino al verde): ROSSO fisso finche'
        # sei in area box a pit chiusa, VERDE 6s all'apertura.
        try:
            _inpit = False
            from pyLMUSharedMemory.lmu_data import MAX_MAPPED_VEHICLES as _MXV
            _num = int(sim.scoring.scoringInfo.mNumVehicles)
            for _i in range(min(_num, _MXV)):
                _v = sim.scoring.vehScoringInfo[_i]
                if int(_v.mIsPlayer) == 1:
                    _inpit = bool(_v.mInPits) or bool(
                        getattr(_v, "mInGarageStall", False))
                    break
            _sess = int(sim.scoring.scoringInfo.mSession)
            _closed = (phase == 0) if _sess < 10 else phase in (1, 2, 3, 4)
            _pc_prev = getattr(self, "_pit_closed_prev", None)
            self._pit_closed_prev = _closed
            if _pc_prev and not _closed:
                self._pit_open_t = time.monotonic()   # APPENA aperta
            if _inpit:
                if _closed:
                    chips.append((_RED, "PIT CLOSED", False))
                elif time.monotonic() - getattr(self, "_pit_open_t",
                                                -99.0) < 6.0:
                    chips.append((QColor("#1e9e4a"), "PIT OPEN", False))
        except Exception:
            pass
        if fl.get("yellow_dist") is not None:
            chips.append((_YEL, "YELLOW", True))
        if fl.get("blue_class"):
            chips.append((_BLUE, "BLUE", False))
        try:
            if bool((self._mem.get_weather() or {}).get("wet")):
                chips.append((_WET, "WET", False))   # persistente finche' bagnato
        except Exception:
            pass
        if chips:
            return ("chips", chips)
        return None

    # ── ZONA MESSAGGI ───────────────────────────────────────────────
    def _pump_queue(self):
        """Avanza la coda messaggi (10s l'uno). Indipendente dalle
        bandiere (zone separate): un flag NON mette in pausa i messaggi."""
        now = time.monotonic()
        with self._pen_lock:
            pn = self._pen_new
            self._pen_new = None
        if pn:
            t, k, r = pn
            if t != self._pen_seen_t:
                self._pen_seen_t = t
                self._queue.append({"box": _RED, "fg": _WHITE,
                                    "text": _pen_phrase(k, r),
                                    "squares": None})
        if self._cur is not None and self._cur_start is not None \
                and now - self._cur_start >= _MSG_TTL:
            self._cur = None
        if self._cur is None and self._queue:
            self._cur = self._queue.pop(0)
            self._cur_start = now
        return self._cur

    def _tl_message(self, phase):
        """Track limits: CICLO COMPLETO dal trace (macchina a stati vera di
        LMU). REVIEW mentre l'investigation e' aperta (colore = gravita'
        dell'evento: Pts>=3 rosso = DT automatico, >=1 arancio, sennò giallo);
        poi l'ESITO: 'NO FURTHER ACTION' verde (perdonato) o 'WARNING'.
        La penalita' DT arriva dal flusso penalita'. Niente mCountLapFlag."""
        try:
            from core.race_control import track_limits_state
            st = track_limits_state()
        except Exception:
            return None
        # WARNING dagli STEPS (shared memory, ISTANTANEI — il trace arriva
        # a blocchi in ritardo): quando il conto sale, banner col colore
        # del tally per 6s. Il review lo mostra gia' l'HUD di LMU.
        try:
            tl = self._mem.player_track_limits() or {}
            steps = int(tl.get("steps", 0))
            pp = int(tl.get("per_penalty", 0))
            pt = int(tl.get("per_point", 0))
        except Exception:
            return None
        prev = getattr(self, "_tl_steps_prev", None)
        self._tl_steps_prev = steps
        nowm = time.monotonic()
        if prev is not None and steps > prev:
            self._tl_warn_t = nowm            # track PRESO adesso
        if nowm - getattr(self, "_tl_warn_t", -99.0) < 6.0:
            # in PROVA/QUALI la penalita' NON esiste (regola LMU): la
            # sanzione e' il giro cancellato -> niente conto X/MAX
            _race = True
            try:
                _sim = self._mem._get_sim()
                _race = int(_sim.scoring.scoringInfo.mSession) >= 10
            except Exception:
                _race = True
            if not _race:
                return ("msg", _WHITE, _TXT,
                        "TRACK LIMITS - LAP INVALID", _LV_YEL)
            color = _LV_YEL
            if pp > 0 and steps >= pp:
                color = _LV_RED
            elif pt > 0 and steps >= pt * 2:
                color = _LV_ORANGE
            txt = "TRACK LIMITS WARNING"
            if pt > 0 and pp > 0:
                txt = "TRACK LIMITS WARNING  %s/%s" % (
                    ("%.2g" % (steps / float(pt))).replace(".", ","),
                    int(round(pp / float(pt))))
            return ("msg", _WHITE, _TXT, txt, color)
        return None

    # ── update: calcola le due zone (indipendenti) ──────────────────
    def _update(self):
        if not self._user_enabled:
            if self.isVisible():
                super().hide()
            return
        show_flags = bool(self.cfg.get("show_flags", True))
        show_pen = bool(self.cfg.get("show_penalties", True))
        show_msg = bool(self.cfg.get("show_messages", True))
        if self.cfg.get("preview"):
            flag = ("png", "green") if show_flags else None
            msg = (("msg", _RED, QColor("#ffffff"),
                    "DRIVE-THROUGH FOR OUT OF POSITION", None)
                   if show_pen else None)
            self._set_zones(flag, msg)
            return
        if not self._mem.is_on_track():
            if self.isVisible():
                super().hide()
            return
        flag_disp = None
        msg_disp = None
        try:
            sim = self._mem._get_sim()
            phase = int(sim.scoring.scoringInfo.mGamePhase) if sim else 0
            # VERDE al via da QUALSIASI fase pre-gara (rolling start: 3->5
            # senza countdown!) o da gialla/stop (ripartenza)
            if self._prev_phase in (1, 2, 3, 4, 6, 7) and phase == 5:
                self._green_t = time.monotonic()
            self._prev_phase = phase
            if show_flags:
                flag_disp = self._compute_flag(sim, phase)
            # ZONA MESSAGGI: penalita' + track limits (show_penalties),
            # messaggi gara (show_messages)
            pen = self._pump_queue()               # avanza sempre la coda
            if show_pen and pen is not None:
                msg_disp = ("msg", pen["box"], pen["fg"], pen["text"],
                            pen["squares"])
            elif show_pen:
                tl = self._tl_message(phase)
                if tl is not None:
                    msg_disp = tl
            if msg_disp is None and show_msg:
                pass                               # messaggi gara: TODO
        except Exception:
            flag_disp = msg_disp = None
        self._set_zones(flag_disp, msg_disp)

    # ── dimensionamento due zone ────────────────────────────────────
    def _native_width(self, disp):
        """Larghezza NATIVA di una zona: bandiere variabili sul testo,
        messaggi con la striscia che si allunga (font fisso)."""
        kind = disp[0]
        if kind == "png":
            return float(_W)
        if kind == "flag":
            fm = QFontMetricsF(_font(_F_FLAG))
            return _HW + fm.horizontalAdvance(disp[2]) + 120.0
        if kind == "chips":
            fm = QFontMetricsF(_font(_F_CHIP))
            w = _HW + _CHIP_PAD0
            for _c, lab, _d in disp[1]:
                w += fm.horizontalAdvance(lab) + 2 * _CHIP_PADX + _CHIP_GAP
            return w - _CHIP_GAP + _CHIP_PAD0
        _, box, fg, txt, sq = disp
        w = _HW + _PAD_L
        if sq:
            w += _SQ * 2 + _SQ_GAP + _SQ_TXT
        w += QFontMetricsF(_font(_F_MSG)).horizontalAdvance(txt) + _PAD_R
        return w

    def _set_zones(self, flag_disp, msg_disp):
        """Impila le zone attive (bandiere sopra, messaggi sotto),
        ridimensiona al contenuto, mostra/nasconde."""
        zones = []
        for d in (flag_disp, msg_disp):
            if d:
                zones.append((d, self._native_width(d)))
        self._zones = zones
        if not zones:
            if self.isVisible():
                super().hide()
            return
        max_w = max(w for _, w in zones)
        s = float(self.cfg.scale)
        self.setFixedSize(int(round(max_w * s)),
                          int(round(_H * len(zones) * s)))
        if not self.isVisible():
            super().show()
            self.raise_()
        self.update()

    # ── disegno ─────────────────────────────────────────────────────
    def _pixmap(self, fn):
        if fn not in self._pix_cache:
            path = _ROOT / "assets" / "racecontrol" / fn
            self._pix_cache[fn] = QPixmap(str(path)) \
                if path.exists() else QPixmap()
        px = self._pix_cache[fn]
        return px if not px.isNull() else None

    def _draw_head(self, p, y0):
        head = self._pixmap("rc_head.png")
        if head:
            p.drawPixmap(QRectF(0.0, y0, _HW, _HC), head,
                         QRectF(head.rect()))

    def _paint_zone(self, p, disp, zone_w, y_off):
        """Disegna una zona (banner) nella banda verticale a y_off."""
        y0 = y_off + _Y0
        kind = disp[0]
        if kind == "png":
            img = self._pixmap(_IMG[disp[1]])
            if img:
                h = zone_w * img.height() / float(img.width())
                y = y_off + (_H - h) / 2.0
                p.drawPixmap(QRectF(0.0, y, float(zone_w), h), img,
                             QRectF(img.rect()))
            return
        if kind == "chips":
            # head FIA + strip chiara + chip colorate AFFIANCATE (V2-style)
            self._draw_head(p, y0)
            p.setPen(Qt.NoPen)
            p.setBrush(_WHITE)
            p.drawRect(QRectF(_HW, y0, zone_w - _HW, _HC))
            fm = QFontMetricsF(_font(_F_CHIP))
            p.setFont(_font(_F_CHIP))
            ch = _HC * 0.82
            cyy = y0 + (_HC - ch) / 2.0
            cx = _HW + _CHIP_PAD0
            for color, lab, dark in disp[1]:
                cw = fm.horizontalAdvance(lab) + 2 * _CHIP_PADX
                p.setPen(Qt.NoPen)
                p.setBrush(color)
                p.drawRect(QRectF(cx, cyy, cw, ch))
                p.setPen(QColor("#111111") if dark else QColor("#ffffff"))
                p.drawText(QPointF(cx + _CHIP_PADX,
                                   cyy + (ch + fm.ascent()) / 2.0 - 3), lab)
                cx += cw + _CHIP_GAP
            return
        self._draw_head(p, y0)
        p.setPen(Qt.NoPen)
        if kind == "flag":
            _, color, txt, dark = disp
            p.setBrush(color)
            p.drawRect(QRectF(_HW, y0, zone_w - _HW, _HC))
            p.setFont(_font(_F_FLAG))
            fm = QFontMetricsF(_font(_F_FLAG))
            p.setPen(QColor("#111111") if dark else QColor("#ffffff"))
            tx = _HW + (zone_w - _HW - fm.horizontalAdvance(txt)) / 2.0
            p.drawText(QPointF(tx, y0 + (_HC + fm.ascent()) / 2.0 - 4), txt)
            return
        # kind == "msg"
        _, box, fg, txt, sq = disp
        p.setBrush(box)
        p.drawRect(QRectF(_HW, y0, zone_w - _HW, _HC))
        cx = _HW + _PAD_L
        if sq:
            iy = y0 + (_HC - _SQ) / 2.0
            p.setBrush(QColor(sq))
            p.drawRect(QRectF(cx, iy, _SQ, _SQ))
            p.drawRect(QRectF(cx + _SQ + _SQ_GAP, iy, _SQ, _SQ))
            cx += _SQ * 2 + _SQ_GAP + _SQ_TXT
        p.setFont(_font(_F_MSG))
        fm = QFontMetricsF(_font(_F_MSG))
        p.setPen(fg)
        p.drawText(QPointF(cx, y0 + (_HC + fm.ascent()) / 2.0 - 4), txt)

    def paintEvent(self, e):
        zones = self._zones
        if not zones:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.TextAntialiasing)
        n = len(zones)
        s = self.height() / float(_H * n)          # scala uniforme
        p.scale(s, s)
        for i, (disp, w) in enumerate(zones):
            self._paint_zone(p, disp, w, i * _H)
        p.end()

    # ── drag / posizione ────────────────────────────────────────────
    def mousePressEvent(self, e):
        from core.utils import overlays_locked
        if overlays_locked():
            return
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
