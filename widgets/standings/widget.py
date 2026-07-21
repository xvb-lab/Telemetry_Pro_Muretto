"""
widgets/standings/widget.py — Overlay standings.

Titlebar VUOTA: serve solo a trascinare l'overlay. Tutte le impostazioni
(scala, piloti, font) si fanno dalla finestra principale via il pannello ⚙.
La posizione viene salvata automaticamente al rilascio del drag.
"""
import json
import time as _time
import threading
import urllib.request
from pathlib import Path

from PySide6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout,
                                QFrame, QPushButton)
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontMetrics

from core.config import get_config
from .reader import StandingsReader
from .driver_row import DriverRow
from .style import load_qss, QSS_FILE
from widgets.session.reader import (LMU_API, FORECAST_SLOTS, SLOT_PCT,
                                    SESSION_FORECAST_KEY, get_weather_condition)
from widgets.session.widget import _weather_icon_path

_ROOT = Path(__file__).parent.parent.parent
from core.paths import POSITIONS_FILE  # dati utente, fuori dall'app
TRACKLOGO_DIR = _ROOT / "assets" / "tracklogos"
TRACKS_JSON = _ROOT / "settings" / "tracks.json"
MAX_ROWS = 64

_TRACKS_MAP = None


def _load_tracks_map():
    global _TRACKS_MAP
    if _TRACKS_MAP is None:
        try:
            with open(TRACKS_JSON, encoding="utf-8") as f:
                _TRACKS_MAP = json.load(f)
        except Exception:
            _TRACKS_MAP = {}
    return _TRACKS_MAP


def _track_logo_path(name):
    """Risolve il logo SVG del circuito.
    1) tracks.json: mTrackName -> nome logo -> assets/tracklogos/<logo>.svg
    2) fallback: file con lo stesso nome del circuito."""
    if not name:
        return None
    logo = _load_tracks_map().get(name)
    cands = []
    if logo:
        cands.append(logo)
    cands += [name, name.lower(),
              name.replace(" ", "_"), name.lower().replace(" ", "_")]
    seen = set()
    for c in cands:
        if c in seen:
            continue
        seen.add(c)
        p = TRACKLOGO_DIR / f"{c}.svg"
        if p.exists():
            return p
    return None


class StandingsOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LMU Standings")
        # Qt.Tool come gli altri overlay: niente icona in taskbar
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("overlay")
        self._drag_pos = None
        self._reader = StandingsReader()
        self._rows = []
        self._user_enabled = True   # acceso dallo switch; l'auto-hide non lo cambia

        from core.shared_memory import SharedMemory
        self._mem = SharedMemory.instance()

        self._config = get_config()
        self.cfg = self._config.widget("standings")
        # colonne fisse (non più opzionali): sempre ON
        for _k in ("show_gap", "show_tyre", "show_energy",
                   "show_status"):
            self._config.set_value("standings", _k, True)
        # colonna LAST rimossa: il last lap appare 10s nel GAP al traguardo
        self._config.set_value("standings", "show_lap", False)
        # fascia sessione STACCATA: ora e' l'overlay "Session bar"
        self._config.set_value("standings", "show_session_row", False)
        # colonne senza voce nel pannello: sempre OFF come COLONNE
        # (laps -> flash L<tot> sul compound; settori -> cella status)
        for _k in ("show_best_lap", "show_sectors", "show_laps",
                   "show_wear", "show_header"):
            self._config.set_value("standings", _k, False)

        # forecast (REST /rest/sessions/weather), aggiornato in background ogni 30s
        self._forecast = None
        self._forecast_t = 0.0
        self._fc_stop = False
        threading.Thread(target=self._forecast_loop, daemon=True).start()

        self._build_ui()

        pos = self._load_position("standings")
        self.move(pos[0], pos[1]) if pos else self.move(20, 80)

        self._apply_qss()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update)
        self._timer.start(self.cfg.get("update_ms", 100))

    # ── FORECAST (REST in background) ─────────────────────────────────
    def _forecast_loop(self):
        while not self._fc_stop:
            try:
                req = urllib.request.Request(
                    f"{LMU_API}/rest/sessions/weather",
                    headers={"User-Agent": "LMU_DataOverlay"})
                with urllib.request.urlopen(req, timeout=4) as resp:
                    self._forecast = json.loads(resp.read())
                self._forecast_t = _time.time()
            except Exception:
                pass
            _time.sleep(30)

    # ── COSTRUZIONE UI ────────────────────────────────────────────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # container
        self._container = QWidget()
        self._container.setObjectName("container")
        outer.addWidget(self._container)

        self._inner = QVBoxLayout(self._container)
        self._inner.setContentsMargins(0, 0, 0, 0)
        self._inner.setSpacing(self.cfg.scaled("row_spacing", 0))

        # ── HEADER SESSIONE (fascia unica) ──────────────────────────────
        #   [logo] PRACTICE / AIR·TRACK   ·   forecast icone+%   ·   tempo / DRY
        _ics = max(20, self.cfg.scaled("forecast_icon_size", 40))
        _gap = self.cfg.scaled("forecast_gap", 10)
        _logo_sz = max(28, self.cfg.scaled("track_logo_size", 44))
        _ph0 = self.cfg.scaled("row_padding_h", 4)

        sess_row = QWidget()
        sess_row.setObjectName("sessionRow")
        sess_row.setAttribute(Qt.WA_StyledBackground, True)
        srl = QHBoxLayout(sess_row)
        srl.setContentsMargins(_ph0 + 6, 0, 0, 0)
        srl.setSpacing(10)

        # logo header fisso (SVG da assets/<header_logo>, default 'wec.svg') — proporzioni mantenute
        self._logo_svg = QSvgWidget()
        self._logo_h = _logo_sz
        self._logo_svg.setFixedSize(_logo_sz, _logo_sz)
        self._logo_svg.setStyleSheet("background:transparent;")
        self._logo_loaded = None
        _theme = (self.cfg.get("theme", "wec") or "wec").lower()
        if _theme == "gtwc":
            _theme = "imsa"            # tema rinominato: le config vecchie seguono
        _logos = {"wec": "wec.svg", "elms": "elms.svg", "imsa": "imsa.svg"}
        _default_logo = _logos.get(_theme, "wec.svg")
        # SCALA del logo header per tema: il logo IMSA e' larghissimo
        # (ratio ~4.8) e a piena altezza mangiava la titlebar — al 50%.
        # Override manuale con "header_logo_scale" in config.
        _lscales = {"imsa": 0.5}
        try:
            _lscale = float(self.cfg.get("header_logo_scale")
                            or _lscales.get(_theme, 1.0))
        except (TypeError, ValueError):
            _lscale = _lscales.get(_theme, 1.0)
        _hlp = _ROOT / "assets" / (self.cfg.get("header_logo") or _default_logo)
        if _hlp.exists():
            try:
                self._logo_svg.load(str(_hlp))
                self._logo_svg.renderer().setAspectRatioMode(Qt.KeepAspectRatio)
                ds = self._logo_svg.renderer().defaultSize()
                if ds.height() > 0:
                    h = max(1, round(self._logo_h * _lscale))
                    w = max(1, round(h * ds.width() / ds.height()))
                    self._logo_svg.setFixedSize(w, h)
                self._logo_loaded = str(_hlp)
            except Exception:
                pass
        else:
            self._logo_svg.hide()

        # blocco sinistra: PRACTICE 1 (grande) / AIR..TRACK.. (piccolo)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)
        self.lbl_sess_name = QLabel("")
        self.lbl_sess_name.setObjectName("sessName")
        self.lbl_sess_name.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.lbl_wx = QLabel("")
        self.lbl_wx.setObjectName("weatherInfo")
        self.lbl_wx.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.lbl_wx_cond = QLabel("")
        self.lbl_wx_cond.setObjectName("weatherCond")
        self.lbl_wx_cond.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        wx_line = QWidget()
        wxll = QHBoxLayout(wx_line)
        wxll.setContentsMargins(0, 0, 0, 0)
        wxll.setSpacing(8)
        wxll.addWidget(self.lbl_wx)
        wxll.addWidget(self.lbl_wx_cond)
        wxll.addStretch()
        ll.addWidget(self.lbl_sess_name)
        ll.addWidget(wx_line)

        # blocco centro: forecast — per colonna icona + % sotto
        self._fc_icons = QWidget()
        self._fc_icons.setObjectName("standForecastRow")
        self._fc_icons.setAttribute(Qt.WA_StyledBackground, True)
        self._fc_icons.setStyleSheet("background: transparent;")
        icl = QHBoxLayout(self._fc_icons)
        icl.setContentsMargins(8, 2, 8, 2)
        icl.setSpacing(_gap)
        self._fc_slots = []
        _fcf = max(8, self.cfg.scaled("forecast_font", 13))
        for _ in FORECAST_SLOTS:
            col = QWidget()
            cl = QVBoxLayout(col)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(0)
            icon_cont = QWidget(); icon_cont.setFixedSize(_ics, _ics)
            icon_cont.setAttribute(Qt.WA_StyledBackground, True)
            icon_cont.setStyleSheet("background:transparent;")
            icon_svg = QSvgWidget(icon_cont)
            icon_svg.setStyleSheet("background:transparent;")
            icon_svg.setGeometry(0, 0, _ics, _ics)
            icon_svg.hide()
            lbl_rain = QLabel(""); lbl_rain.setObjectName("standFcRain")
            lbl_rain.setAlignment(Qt.AlignCenter)
            lbl_rain.setStyleSheet(f"color:#cdd2d8; font-size:{_fcf}px; background:transparent;")
            cl.addWidget(icon_cont, 0, Qt.AlignCenter)
            cl.addWidget(lbl_rain, 0, Qt.AlignCenter)
            col.hide()
            icl.addWidget(col)
            self._fc_slots.append({"col": col, "icon_svg": icon_svg,
                                   "lbl_rain": lbl_rain, "icon_sz": _ics, "icon_loaded": None})

        # blocco destra: colonna verde piena (no radius) a tutta altezza, orologio centrato
        right = QWidget()
        right.setObjectName("sessTimeBox")
        right.setAttribute(Qt.WA_StyledBackground, True)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(10, 2, 10, 2)
        rl.setSpacing(2)
        rl.addStretch()
        # logo SVG dentro il verde, sopra l'orologio (assets/<clock_logo>)
        self._clock_logo = QSvgWidget()
        _cls = max(12, self.cfg.scaled("clock_logo_size", 18))
        self._clock_logo.setFixedSize(_cls, _cls)
        self._clock_logo.setStyleSheet("background:transparent;")
        _clp = _ROOT / "assets" / self.cfg.get("clock_logo", "clocklogo.svg")
        if _clp.exists():
            try:
                self._clock_logo.load(str(_clp))
                self._clock_logo.renderer().setAspectRatioMode(Qt.KeepAspectRatio)
                ds = self._clock_logo.renderer().defaultSize()
                if ds.height() > 0:
                    w = max(1, round(_cls * ds.width() / ds.height()))
                    self._clock_logo.setFixedSize(w, _cls)
            except Exception:
                pass
            rl.addWidget(self._clock_logo, 0, Qt.AlignCenter)
        else:
            self._clock_logo.hide()
        self.lbl_sess_time = QLabel("--:--")
        self.lbl_sess_time.setObjectName("sessTime")
        self.lbl_sess_time.setAlignment(Qt.AlignCenter)
        _tf = QFont(); _tf.setPixelSize(max(8, round(22 * self.cfg.scale)))
        self.lbl_sess_time.setFixedWidth(QFontMetrics(_tf).horizontalAdvance("12:00:00") + 6)
        rl.addWidget(self.lbl_sess_time, 0, Qt.AlignCenter)
        rl.addStretch()

        # contenitori laterali a PESO UGUALE: il forecast resta ancorato al centro
        # e il tempo (secondi) cresce verso il bordo senza spingere il meteo.
        left_wrap = QWidget()
        lwl = QHBoxLayout(left_wrap)
        lwl.setContentsMargins(0, 0, 0, 0)
        lwl.setSpacing(0)
        lwl.addWidget(self._logo_svg, 0, Qt.AlignVCenter)
        lwl.addSpacing(self.cfg.scaled("logo_pad", 14))
        lwl.addWidget(left, 0, Qt.AlignVCenter)
        lwl.addStretch()

        right_wrap = QWidget()
        rwl = QHBoxLayout(right_wrap)
        rwl.setContentsMargins(0, 0, 0, 0)
        rwl.setSpacing(0)
        rwl.addStretch()
        rwl.addWidget(right)

        srl.addWidget(left_wrap, 1)
        srl.addWidget(self._fc_icons, 0, Qt.AlignVCenter)
        srl.addWidget(right_wrap, 1)

        self._inner.addWidget(sess_row)
        self._sess_row = sess_row
        self._wx_row = sess_row     # compat: un'unica fascia

        self._fc_icons.setVisible(self.cfg.get("forecast", True))
        _show_sess = self.cfg.get("show_session_row", True)
        sess_row.setVisible(_show_sess)

        # ── RIGA SESSIONE SLIM sopra il leader: nome sx | tempo dx ──
        sline = QWidget()
        sline.setObjectName("sessLine")
        sline.setAttribute(Qt.WA_StyledBackground, True)
        sll = QHBoxLayout(sline)
        sll.setContentsMargins(10, 2, 10, 2)
        sll.setSpacing(8)
        self.lbl_line_sess = QLabel("")
        self.lbl_line_sess.setObjectName("sessLineName")
        self.lbl_line_time = QLabel("--:--")
        self.lbl_line_time.setObjectName("sessLineTime")
        sll.addWidget(self.lbl_line_sess)
        sll.addStretch()
        sll.addWidget(self.lbl_line_time)
        self._inner.addWidget(sline)
        self._sess_line = sline

        # header
        hdr = QWidget()
        hdr.setObjectName("header")
        hdr.setFixedHeight(self.cfg.scaled("header_height", 22))
        hl = QHBoxLayout(hdr)
        ph = self.cfg.scaled("row_padding_h", 4)
        hl.setContentsMargins(ph, 2, ph, 2)
        hl.setSpacing(self.cfg.scaled("row_col_spacing", 5))

        def hlbl(t, w, align=Qt.AlignLeft):
            l = QLabel(t)
            l.setObjectName("headerLabel")
            if w:
                l.setFixedWidth(w)
            l.setAlignment(align | Qt.AlignVCenter)
            return l

        HDR = {
            "status": ("", self.cfg.scaled("col_status", 50), Qt.AlignCenter),
            "class":  ("CL", self.cfg.scaled("col_class", 34), Qt.AlignCenter),
            "pos":    ("POS", self.cfg.scaled("col_pos", 30), Qt.AlignCenter),
            "pdelta": ("+/-", self.cfg.scaled("col_pdelta", 30), Qt.AlignCenter),
            "logo":   ("", self.cfg.scaled("logo_width", 30), Qt.AlignCenter),
            "name":   ("DRIVER", self._name_col_w(), Qt.AlignLeft),
            "speed":  ("SPEED", self.cfg.scaled("col_speed", 55), Qt.AlignCenter),
            "gap":    ("GAP", self.cfg.scaled("col_gap", 80), Qt.AlignCenter),
            "lap":    ("LAST", self.cfg.scaled("col_lap", 82), Qt.AlignCenter),
            "best":   ("BEST", self.cfg.scaled("col_best", 82), Qt.AlignCenter),
            "tyre":   ("TYRE", round(self.cfg.get("base", {}).get("col_tyre", 34) * self.cfg.scale), Qt.AlignCenter),
            "energy": ("NRG", self.cfg.scaled("col_energy", 50), Qt.AlignCenter),
            "tl":     ("TL", self.cfg.scaled("col_tl", 38), Qt.AlignCenter),
            "pit":    ("PIT", self.cfg.scaled("col_pit", 30), Qt.AlignCenter),
            "sectors":("SECT", self.cfg.scaled("col_sectors", 42), Qt.AlignCenter),
            "laps":   ("LAPS", self.cfg.scaled("col_laps", 34), Qt.AlignCenter),
            "stint":  ("STINT", self.cfg.scaled("col_stint", 48), Qt.AlignCenter),
            "wear":   ("WEAR", self.cfg.scaled("col_wear", 42), Qt.AlignCenter),
        }
        left_cols = {"status", "class", "pos", "logo", "name"}
        stretch_added = False
        _ord = self.cfg.get("column_order", [])
        if "pdelta" not in _ord:
            _ord = list(_ord); _ord.insert(_ord.index("gap") if "gap" in _ord else len(_ord), "pdelta")
        for col in _ord:
            if col not in HDR:
                continue
            # rispetta i toggle: niente intestazione se la colonna è spenta
            if col == "pdelta" and not self.cfg.get("show_pos_delta", True):
                continue
            if col == "speed" and not self.cfg.get("show_speed", True):
                continue
            if col == "best" and not self.cfg.get("show_best_lap", True):
                continue
            if col == "tl" and not self.cfg.get("show_track_limits", True):
                continue
            if col == "pit" and not self.cfg.get("show_pit", True):
                continue
            if col == "sectors" and not self.cfg.get("show_sectors", True):
                continue
            if col == "laps" and not self.cfg.get("show_laps", True):
                continue
            if col == "stint" and not self.cfg.get("show_stint", True):
                continue
            if col == "wear" and not self.cfg.get("show_wear", True):
                continue
            if col == "gap" and not self.cfg.get("show_gap", True):
                continue
            if col == "lap" and not self.cfg.get("show_lap", True):
                continue
            if col == "tyre" and not self.cfg.get("show_tyre", True):
                continue
            if col == "energy" and not self.cfg.get("show_energy", True):
                continue
            if col == "status" and not self.cfg.get("show_status", True):
                continue
            txt, w, align = HDR[col]
            if col not in left_cols and not stretch_added:
                hl.addStretch()
                stretch_added = True
            hl.addWidget(hlbl(txt, w, align))
        if not stretch_added:
            hl.addStretch()
        self._inner.addWidget(hdr)
        if not self.cfg.get("show_header", True):
            hdr.hide()
            hdr.setFixedHeight(0)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("separator")
        self._inner.addWidget(sep)

        # righe
        self._rows = []
        for _ in range(MAX_ROWS):
            r = DriverRow(self.cfg)
            r.hide()
            self._inner.addWidget(r)
            self._rows.append(r)

        # attesa
        self._wait = QLabel("● In attesa di LMU...")
        self._wait.setObjectName("status")
        self._wait.setAlignment(Qt.AlignCenter)
        self._inner.addWidget(self._wait)

        self.setFixedWidth(self._compute_width())

    def _name_col_w(self):
        """Colonna nome: stretta se i nomi sono abbreviati a 3 lettere."""
        if self.cfg.get("short_names", False):
            return self.cfg.scaled("col_name_short", 96)
        return self.cfg.scaled("col_name", 160)

    def _compute_width(self):
        """Larghezza dinamica = somma colonne attive + spacing + padding."""
        col_w = {
            "status": self.cfg.scaled("col_status", 50),
            "class":  self.cfg.scaled("col_class", 34),
            "pos":    self.cfg.scaled("col_pos", 30),
            "pdelta": self.cfg.scaled("col_pdelta", 30),
            "logo":   self.cfg.scaled("logo_width", 30),
            "name":   self._name_col_w(),
            "speed":  self.cfg.scaled("col_speed", 55),
            "gap":    self.cfg.scaled("col_gap", 80),
            "best":   self.cfg.scaled("col_best", 82),
            "lap":    self.cfg.scaled("col_lap", 82),
            "tl":     self.cfg.scaled("col_tl", 38),
            "pit":    self.cfg.scaled("col_pit", 30),
            "sectors": self.cfg.scaled("col_sectors", 42),
            "laps":   self.cfg.scaled("col_laps", 34),
            "stint":  self.cfg.scaled("col_stint", 48),
            "wear":   self.cfg.scaled("col_wear", 42),
            "tyre":   round(self.cfg.get("base", {}).get("col_tyre", 34) * self.cfg.scale),
            "energy": self.cfg.scaled("col_energy", 50),
        }
        order = self.cfg.get("column_order", [])
        if "pdelta" not in order:
            order = list(order); order.insert(order.index("gap") if "gap" in order else len(order), "pdelta")
        spacing = self.cfg.scaled("row_col_spacing", 5)
        pad = self.cfg.scaled("row_padding_h", 4)
        total = pad * 2
        n = 0
        for c in order:
            if c not in col_w:
                continue
            if c == "pdelta" and not self.cfg.get("show_pos_delta", True):
                continue
            if c == "class" and not self.cfg.get("show_class", False):
                continue
            if c == "speed" and not self.cfg.get("show_speed", True):
                continue
            if c == "best" and not self.cfg.get("show_best_lap", True):
                continue
            if c == "tl" and not self.cfg.get("show_track_limits", True):
                continue
            if c == "pit" and not self.cfg.get("show_pit", True):
                continue
            if c == "sectors" and not self.cfg.get("show_sectors", True):
                continue
            if c == "laps" and not self.cfg.get("show_laps", True):
                continue
            if c == "stint" and not self.cfg.get("show_stint", True):
                continue
            if c == "wear" and not self.cfg.get("show_wear", True):
                continue
            if c == "gap" and not self.cfg.get("show_gap", True):
                continue
            if c == "lap" and not self.cfg.get("show_lap", True):
                continue
            if c == "tyre" and not self.cfg.get("show_tyre", True):
                continue
            if c == "energy" and not self.cfg.get("show_energy", True):
                continue
            if c == "status" and not self.cfg.get("show_status", True):
                continue
            total += col_w[c]
            n += 1
        total += spacing * max(0, n - 1)
        total += 24   # margine respiro (stretch interno)
        return total

    def _apply_qss(self):
        self.setStyleSheet(load_qss(self.cfg))

    # ── REBUILD / RELOAD ──────────────────────────────────────────────
    def reload_config(self):
        """Rilegge la config e ricostruisce la UI mantenendo la posizione.

        Chiamato dalla finestra impostazioni su Applica/Salva (live update).
        """
        pos = self.pos()
        self.cfg = self._config.widget("standings")

        # detach vecchio layout e ricostruisci
        old = self.layout()
        QWidget().setLayout(old)
        self._build_ui()
        self._apply_qss()
        self.move(pos)
        # aggiorna intervallo timer se cambiato
        self._timer.start(self.cfg.get("update_ms", 100))

    def set_enabled(self, enabled: bool):
        """Acceso/spento dallo switch. Da spento resta sempre nascosto;
        da acceso, l'auto-hide fuori pista gestisce la visibilità in _update."""
        self._user_enabled = enabled
        if enabled:
            self._timer.start(self.cfg.get("update_ms", 100))
            # mostra subito solo se sei in pista, altrimenti ci pensa _update
            if self._mem.is_on_track():
                super().show()
                self.raise_()
        else:
            self._timer.stop()
            super().hide()

    def open_config(self):
        """Apre la finestra impostazioni di questo widget, centrata e in primo piano."""
        from gui.config_window import ConfigWindow
        from PySide6.QtGui import QGuiApplication
        if getattr(self, "_cfg_win", None) is None:
            self._cfg_win = ConfigWindow(self._config, self)

        self._cfg_win.show()           # mostra prima per avere la size reale
        self._cfg_win.adjustSize()

        # posiziona accanto all'overlay, ma se esce dallo schermo, centra
        screen = QGuiApplication.screenAt(self.pos()) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        w = self._cfg_win.width()
        h = self._cfg_win.height()

        x = self.x() + self.width() + 12
        y = self.y()
        # se sfora a destra, prova a sinistra; se ancora fuori, centra
        if x + w > geo.right():
            x = self.x() - w - 12
        if x < geo.left() or x + w > geo.right():
            x = geo.left() + (geo.width() - w) // 2
        # clamp verticale
        if y + h > geo.bottom():
            y = geo.bottom() - h
        if y < geo.top():
            y = geo.top()

        self._cfg_win.move(x, y)
        self._cfg_win.raise_()
        self._cfg_win.activateWindow()

    # ── DRAG ──────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        from core.utils import overlays_locked
        if overlays_locked():
            return          # overlay BLOCCATI: niente drag
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() == Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        if self._drag_pos is not None:
            # salva la posizione automaticamente al rilascio del drag
            self._save_position("standings")
        self._drag_pos = None

    # ── UPDATE FORECAST ───────────────────────────────────────────────
    def _update_forecast(self, session_type):
        if not self.cfg.get("forecast", True):
            if self._fc_icons.isVisible():
                self._fc_icons.hide()
            return
        if not self._fc_icons.isVisible():
            self._fc_icons.show()
        forecast = self._forecast
        if not forecast:
            for s in self._fc_slots:
                s["col"].hide()
            return
        sess_key = SESSION_FORECAST_KEY.get(session_type, "RACE")
        sess_fc = forecast.get(sess_key, {}) if isinstance(forecast, dict) else {}
        total_et, current_et, tod = self._mem.get_session_clock()
        elapsed = current_et
        slot_secs = {k: (total_et * SLOT_PCT[k] / 100 if total_et > 0 else 0)
                     for k in FORECAST_SLOTS}
        # mostra SEMPRE tutti e 5 gli step (START..FINISH)
        for i, slot in enumerate(self._fc_slots):
            key = FORECAST_SLOTS[i]
            slot["col"].show()
            sd = sess_fc.get(key, {}) if isinstance(sess_fc, dict) else {}
            rain = sd.get("WNV_RAIN_CHANCE", {}).get("currentValue", 0)
            sky_v = sd.get("WNV_SKY", {}).get("currentValue", 0)
            secs_to = slot_secs[key] - elapsed
            if secs_to <= 60:
                label = "NOW"
            elif secs_to < 3600:
                label = f"{int(secs_to / 60)}m"
            else:
                label = f"{secs_to / 3600:.1f}h"
            slot["lbl_rain"].setText(f"<b>{label}</b>")
            cond = get_weather_condition(rain, sky_v, tod)
            ipath = _weather_icon_path(cond)
            if ipath and str(ipath) != slot["icon_loaded"]:
                sz = slot["icon_sz"]
                slot["icon_svg"].setGeometry(0, 0, sz, sz)
                slot["icon_svg"].load(str(ipath))
                slot["icon_loaded"] = str(ipath)
            slot["icon_svg"].show()

    def _update_track_logo(self):
        name = self._mem.get_track_name()
        path = _track_logo_path(name)
        if path is None:
            if self._logo_svg.isVisible():
                self._logo_svg.hide()
            self._logo_loaded = None
            return
        if str(path) != self._logo_loaded:
            self._logo_svg.load(str(path))
            self._logo_loaded = str(path)
            try:
                self._logo_svg.renderer().setAspectRatioMode(Qt.KeepAspectRatio)
                ds = self._logo_svg.renderer().defaultSize()
                if ds.height() > 0:
                    w = max(1, round(self._logo_h * ds.width() / ds.height()))
                    self._logo_svg.setFixedSize(w, self._logo_h)
            except Exception:
                pass
        if not self._logo_svg.isVisible():
            self._logo_svg.show()

    # ── UPDATE ────────────────────────────────────────────────────────
    def _update(self):
        # auto-hide fuori pista (menu/pausa/replay): nascondi se non in pista
        if self._user_enabled:
            on_track = self._mem.is_on_track()
            if on_track and not self.isVisible():
                super().show()
            elif not on_track and self.isVisible():
                super().hide()
                return
            if not on_track:
                return

        drivers, player_class, session_type, remaining = self._reader.read()
        if not drivers:
            self._wait.show()
            for r in self._rows:
                r.hide()
            self.setFixedHeight(60)
            return
        # il reader ricalcola 1×/sec e tra una volta e l'altra restituisce lo
        # STESSO oggetto: se non è cambiato, non ridisegno (niente re-polish).
        if drivers is getattr(self, "_prev_drivers", None):
            return
        self._prev_drivers = drivers

        self._wait.hide()
        # aggiorno riga sessione: tempo (sinistra) + nome (destra)
        _sess_names = {0:"TEST", 1:"PRACTICE 1", 2:"PRACTICE 2", 3:"PRACTICE 3",
                       4:"PRACTICE 4", 5:"QUALIFY 1", 6:"QUALIFY 2", 7:"QUALIFY 3",
                       8:"QUALIFY 4", 9:"WARMUP", 10:"RACE", 11:"RACE 2",
                       12:"RACE 3", 13:"RACE"}
        self.lbl_sess_name.setText(_sess_names.get(int(session_type), ""))
        if remaining and remaining > 0:
            _rm = int(remaining)
            _h, _m, _s = _rm // 3600, (_rm % 3600) // 60, _rm % 60
            if _h > 0:
                self.lbl_sess_time.setText(f"{_h}:{_m:02d}:{_s:02d}")
            else:
                self.lbl_sess_time.setText(f"{_m:02d}:{_s:02d}")
        else:
            self.lbl_sess_time.setText("--:--")
        # riga meteo
        _wx = self._mem.get_weather()
        if _wx:
            self.lbl_wx.setText(f"AIR {_wx['air']:.0f}°  TRACK {_wx['track']:.0f}°")
            self.lbl_wx_cond.setText("WET" if _wx["wet"] else "DRY")
            self.lbl_wx_cond.setProperty("cond", "wet" if _wx["wet"] else "dry")
            self.lbl_wx_cond.style().unpolish(self.lbl_wx_cond)
            self.lbl_wx_cond.style().polish(self.lbl_wx_cond)
        else:
            self.lbl_wx.setText("")
            self.lbl_wx_cond.setText("")
        # riga slim sopra il leader: stessi valori gia' calcolati;
        # le cifre nel nome (PRACTICE 1) in Archivo corsivo "onboard"
        import re as _re_sl
        self.lbl_line_sess.setTextFormat(Qt.RichText)
        self.lbl_line_sess.setText(_re_sl.sub(
            r"(\d+)",
            "<span style=\"font-family:'Druk Wide Cy TT', 'Archivo SemiExpanded';"
            "font-style:italic;font-weight:900;\">\\1</span>",
            self.lbl_sess_name.text()))
        self.lbl_line_time.setText(self.lbl_sess_time.text())
        self._update_forecast(int(session_type))
        mx = self.cfg.get("max_drivers", 10)
        view_mode = self.cfg.get("view_mode", "class")

        if view_mode == "overall":
            visible = self._select_overall(drivers, player_class, mx)
        else:
            visible = self._select_centered(drivers, mx)

        for i, row in enumerate(self._rows):
            if i < len(visible):
                row.update_data(visible[i])
                # ultima riga: property per togliere il border-bottom via QSS
                is_last = (i == len(visible) - 1)
                row.setProperty("lastrow", "true" if is_last else "false")
                row.style().unpolish(row)
                row.style().polish(row)
                row.show()
            else:
                row.hide()

        rh = self.cfg.scaled("row_height", 30)
        # header nascosto = niente altezza fantasma
        hh = self.cfg.scaled("header_height", 22) \
            if self.cfg.get("show_header", True) else 0
        # altezza extra per la fascia header sessione (se visibile)
        extra = self._sess_line.sizeHint().height()
        if self.cfg.get("show_session_row", True):
            extra += self._sess_row.sizeHint().height() + 2
        h = extra + hh + 1 + len(visible) * (rh + 1) + 2
        self.setFixedHeight(h)

    # ── SELEZIONE PILOTI ──────────────────────────────────────────────
    def _select_centered(self, drivers, mx):
        """Mostra mx piloti centrati sul player (leader sempre visibile)."""
        if len(drivers) <= mx:
            return drivers
        player_idx = next((i for i, d in enumerate(drivers) if d["is_player"]), 0)
        if player_idx == 0:
            return drivers[:mx]
        leader = drivers[0]
        rest = drivers[1:]
        rest_mx = mx - 1
        p_idx = player_idx - 1
        half = rest_mx // 2
        start = p_idx - half
        end = start + rest_mx
        if start < 0:
            start, end = 0, rest_mx
        if end > len(rest):
            end = len(rest)
            start = max(0, end - rest_mx)
        return [leader] + rest[start:end]

    def _select_overall(self, drivers, player_class, mx):
        """Per ogni classe: mx piloti. Classe player centrata sul player,
        altre classi dal 1° fino a mx. Ordine classi preservato (già nel reader)."""
        # raggruppa mantenendo l'ordine di apparizione (reader ordina per classe)
        groups = {}
        order = []
        for d in drivers:
            cc = d.get("car_class", "")
            if cc not in groups:
                groups[cc] = []
                order.append(cc)
            groups[cc].append(d)

        out = []
        for cc in order:
            grp = groups[cc]
            if cc == player_class:
                out.extend(self._select_centered(grp, mx))
            else:
                out.extend(grp[:mx])
        return out

    # ── POSIZIONE ─────────────────────────────────────────────────────
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

    def closeEvent(self, e):
        self._save_position("standings")
        super().closeEvent(e)
