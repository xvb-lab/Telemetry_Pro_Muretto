# -*- coding: utf-8 -*-
"""ui/tab_overlay.py — Tab Overlay dentro LMU Telemetry Pro.

Gli overlay (standings, relative, map, hud, ...) sono MIGRATI qui dal progetto
LMU_DataOverlay ma restano un mondo separato e pulito:
  - il codice vive in widgets/<nome>/ (pacchetto autonomo, invariato)
  - ogni overlay acceso gira nel SUO processo Python (run_overlay.py),
    quindi GIL/event-loop/GC separati: non ruba fluidita' all'app ne'
    agli altri overlay
  - config e posizioni sono le stesse di sempre (core.config / core.paths)

Questo file fa da registro (WIDGETS) e da pannello: lista scrollabile e
compatta di righe [stato] Nome [ON/OFF] [ingranaggio]. La logica di
lancio/stop processi e le righe sono copiate PARI PARI da
LMU_DataOverlay/gui/main_window.py (codice collaudato), tolta solo la
cornice dell'app (header/footer/updater) che qui non serve.
"""
import os
import sys
import subprocess
from pathlib import Path

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                                QPushButton, QScrollArea, QStackedWidget)
from PySide6.QtCore import Qt

from core.config import get_config
from core.icons import ICON
# NB (pulizia 20/07): gli overlay di prima generazione (standings,
# sessionbar, relative, session, flag, hud, car, gear, minicar, list)
# sono FUORI dal menu: cartelle vive in widgets/ + copia di sicurezza
# in backup_overlays/ — le funzioni si recuperano da li' per i nuovi.
from widgets.map.widget import MapOverlay
from widgets.wecrevs.widget import WecRevsOverlay
from widgets.wecbars.widget import WecBarsOverlay
from widgets.weconboard.widget import WecOnboardOverlay  # base di wec26board
from widgets.wec26board.widget import Wec26OnboardOverlay
from widgets.wec26battle.widget import (Wec26BattleOverlay,
                                        Wec26BattleBOverlay)
from widgets.wec26flag.widget import Wec26FlagOverlay
from widgets.wec26mini.widget import Wec26MiniOverlay
from widgets.wec26mfd.widget import Wec26MfdOverlay

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_RUN_OVERLAY = _PROJECT_ROOT / "run_overlay.py"

# Registro widget: (chiave config, etichetta, classe overlay)
WIDGETS = [
    ("map", "Map", MapOverlay),
    ("wecrevs", "WEC 2024 Revs", WecRevsOverlay),
    ("wecbars", "WEC 2024 Pedals", WecBarsOverlay),
    ("wec26board", "WEC 2026 Onboard", Wec26OnboardOverlay),
    ("wec26battle", "WEC 2026 Battle Ahead", Wec26BattleOverlay),
    ("wec26battleb", "WEC 2026 Battle Behind", Wec26BattleBOverlay),
    ("wec26flag", "WEC 2026 Race Control", Wec26FlagOverlay),
    ("wec26mfd", "Dashboard", Wec26MfdOverlay),
    ("wec26mini", "WEC 2026 Mini Telemetry", Wec26MiniOverlay),
]


class ToggleButton(QPushButton):
    """Bottone on/off con testo ON/OFF e colore (verde/grigio)."""
    def __init__(self):
        super().__init__()
        self.setObjectName("toggleBtn")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(48, 24)
        self.toggled.connect(self._refresh)
        self._refresh(False)

    def _refresh(self, checked):
        self.setText("ON" if checked else "OFF")
        self.setProperty("on", "true" if checked else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class WidgetRow(QWidget):
    """Riga della lista: [stato] Nome ........ [ON/OFF] [ingranaggio]."""

    def __init__(self, key, label, overlay_cls, app):
        super().__init__()
        self.setObjectName("widgetRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._key = key
        self._label = label
        self._overlay_cls = overlay_cls
        self._app = app
        self._cfg_win = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 9, 16, 9)
        lay.setSpacing(10)

        # pallino di stato (verde acceso / grigio spento)
        self.dot = QLabel("\u25CF")
        self.dot.setObjectName("statusDot")
        self.dot.setProperty("on", "false")
        lay.addWidget(self.dot)

        name = QLabel(label)
        name.setObjectName("widgetName")
        lay.addWidget(name)
        lay.addStretch()

        self.sw = ToggleButton()
        self.sw.toggled.connect(self._on_toggle)
        lay.addWidget(self.sw)

        self.btn_cfg = QPushButton(ICON["settings"])
        self.btn_cfg.setObjectName("btnGear")
        self.btn_cfg.setFixedSize(32, 32)
        self.btn_cfg.setCursor(Qt.PointingHandCursor)
        self.btn_cfg.clicked.connect(self._open_config)
        lay.addWidget(self.btn_cfg)

    def _set_dot(self, on):
        self.dot.setProperty("on", "true" if on else "false")
        self.dot.style().unpolish(self.dot)
        self.dot.style().polish(self.dot)

    # ── stato iniziale dal config ─────────────────────────────────────
    def restore(self):
        cfg = self._app.config.widget(self._key)
        enabled = bool(cfg.get("enabled", False))   # default SEMPRE off
        self.sw.blockSignals(True)
        self.sw.setChecked(enabled)
        self.sw._refresh(enabled)
        self.sw.blockSignals(False)
        self._set_dot(enabled)
        if enabled:
            self._app.start_proc(self._key)

    def _on_toggle(self, checked):
        if checked:
            self._app.start_proc(self._key)
        else:
            self._app.stop_proc(self._key)
        self._set_dot(checked)
        self._app.config.set_value(self._key, "enabled", checked)
        self._app.config.save()

    def _open_config(self):
        # accendi se spento, così vedi subito le modifiche
        if not self.sw.isChecked():
            self.sw.setChecked(True)
        proxy = self._app.config_proxy(self._key)
        # apre DENTRO la tab (pagina con freccia indietro), non in finestra
        self._app.open_settings_page(self._key, self._label, proxy)


class DashboardRow(QWidget):
    """Riga Dashboard Engineer: apre/chiude l'overlay cruscotto in-process."""

    def __init__(self, app):
        super().__init__()
        self.setObjectName("widgetRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._app = app
        self._ov = None
        lay = QHBoxLayout(self); lay.setContentsMargins(16, 9, 16, 9)
        lay.setSpacing(10)
        self.dot = QLabel("\u25CF"); self.dot.setObjectName("statusDot")
        self.dot.setProperty("on", "false"); lay.addWidget(self.dot)
        name = QLabel("Dashboard Engineer"); name.setObjectName("widgetName")
        lay.addWidget(name); lay.addStretch()
        self.sw = ToggleButton(); self.sw.toggled.connect(self._on_toggle)
        lay.addWidget(self.sw)
        self.btn_cfg = QPushButton(ICON["settings"])
        self.btn_cfg.setObjectName("btnGear"); self.btn_cfg.setFixedSize(32, 32)
        self.btn_cfg.setCursor(Qt.PointingHandCursor)
        self.btn_cfg.clicked.connect(self._open_config)
        lay.addWidget(self.btn_cfg)

    def _set_dot(self, on):
        self.dot.setProperty("on", "true" if on else "false")
        self.dot.style().unpolish(self.dot); self.dot.style().polish(self.dot)

    def restore(self):
        on = bool(self._app.config.widget("dashboard").get("enabled", False))
        self.sw.blockSignals(True); self.sw.setChecked(on)
        self.sw._refresh(on); self.sw.blockSignals(False)
        self._set_dot(on)
        if on:
            self._show(True)

    def _ensure(self):
        if self._ov is None:
            try:
                from dashboard_overlay import DashboardEngineerOverlay
                self._ov = DashboardEngineerOverlay(standalone=False)
            except Exception:
                self._ov = None
        return self._ov

    def _open_config(self):
        ov = self._ensure()
        if ov is None:
            return
        # accendi se spento, così vedi subito le modifiche
        if not self.sw.isChecked():
            self.sw.setChecked(True)
        # apre DENTRO la tab (pagina con freccia indietro), come gli altri.
        # ov ha reload_config(): la ConfigWindow embedded lo richiama su
        # Apply/Save e l'overlay in-process si aggiorna live.
        self._app.open_settings_page("dashboard", "Dashboard Engineer", ov)

    def _eng(self):
        win = getattr(self._app, "win", None)
        return getattr(win, "_engineer", None) if win else None

    def _show(self, on):
        ov = self._ensure()
        if ov is None:
            return
        eng = self._eng()
        if on:
            # AGGANCIA il cruscotto al motore: da qui arrivano radio (EQ),
            # dati sessione e show/hide in pista. Senza questo il cruscotto
            # mostra solo gear/LED (che legge da solo).
            if eng is not None and hasattr(eng, "add_mirror"):
                eng.add_mirror(ov)
            ov.show(); ov.raise_()
        else:
            if eng is not None and hasattr(eng, "remove_mirror"):
                eng.remove_mirror(ov)
            ov.hide()

    def _on_toggle(self, checked):
        self._show(checked)
        self._set_dot(checked)
        try:
            self._app.config.set_value("dashboard", "enabled", checked)
            self._app.config.save()
        except Exception:
            pass


class EngineerRow(QWidget):
    """Riga Engineer: stesso look dei widget, ma pilota l'overlay in-process
    (motore nella EngineerTab, non un subprocess)."""

    def __init__(self, app):
        super().__init__()
        self.setObjectName("widgetRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._app = app
        self._cfg_win = None
        lay = QHBoxLayout(self); lay.setContentsMargins(16, 9, 16, 9)
        lay.setSpacing(10)
        self.dot = QLabel("\u25CF"); self.dot.setObjectName("statusDot")
        self.dot.setProperty("on", "false"); lay.addWidget(self.dot)
        name = QLabel("Engineer"); name.setObjectName("widgetName")
        lay.addWidget(name); lay.addStretch()
        self.sw = ToggleButton(); self.sw.toggled.connect(self._on_toggle)
        lay.addWidget(self.sw)
        self.btn_cfg = QPushButton(ICON["settings"])
        self.btn_cfg.setObjectName("btnGear"); self.btn_cfg.setFixedSize(32, 32)
        self.btn_cfg.setCursor(Qt.PointingHandCursor)
        self.btn_cfg.clicked.connect(self._open_config)
        lay.addWidget(self.btn_cfg)

    def _eng(self):
        win = getattr(self._app, "win", None)
        return getattr(win, "_engineer", None) if win else None

    def _set_dot(self, on):
        self.dot.setProperty("on", "true" if on else "false")
        self.dot.style().unpolish(self.dot); self.dot.style().polish(self.dot)

    def restore(self):
        eng = self._eng()
        on = bool(eng.is_enabled()) if eng else False
        self.sw.blockSignals(True); self.sw.setChecked(on)
        self.sw._refresh(on); self.sw.blockSignals(False)
        self._set_dot(on)

    def _on_toggle(self, checked):
        # l'ingegnere e' SOLO RADIO: qui si accende/spegne il motore, stop
        eng = self._eng()
        if eng is not None:
            eng.set_enabled(checked)
        self._set_dot(checked)

    def _open_config(self):
        # SOLO apre le impostazioni: niente auto-accensione (accendeva la
        # riga e spegneva l'altra per l'esclusiva — sembrava un bug)
        eng = self._eng()
        if eng is None:
            return
        panel = eng.settings_panel() if hasattr(eng, "settings_panel") else None
        if panel is not None:
            self._app.open_settings_page("engineer", "Engineer", panel=panel)


class RadioRow(QWidget):
    """Riga Radio (in fondo alla lista): SOLO la voce dell'ingegnere, nessun
    overlay a schermo. Stesso motore della riga Engineer, card soppressa.
    L'ingranaggio apre le impostazioni audio/lingua (pannello Engineer)."""

    def __init__(self, app):
        super().__init__()
        self.setObjectName("widgetRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._app = app
        lay = QHBoxLayout(self); lay.setContentsMargins(16, 9, 16, 9)
        lay.setSpacing(10)
        self.dot = QLabel("●"); self.dot.setObjectName("statusDot")
        self.dot.setProperty("on", "false"); lay.addWidget(self.dot)
        name = QLabel("Radio"); name.setObjectName("widgetName")
        lay.addWidget(name); lay.addStretch()
        self.sw = ToggleButton(); self.sw.toggled.connect(self._on_toggle)
        lay.addWidget(self.sw)
        self.btn_cfg = QPushButton(ICON["settings"])
        self.btn_cfg.setObjectName("btnGear"); self.btn_cfg.setFixedSize(32, 32)
        self.btn_cfg.setCursor(Qt.PointingHandCursor)
        self.btn_cfg.clicked.connect(self._open_config)
        lay.addWidget(self.btn_cfg)

    def _eng(self):
        win = getattr(self._app, "win", None)
        return getattr(win, "_engineer", None) if win else None

    def _set_dot(self, on):
        self.dot.setProperty("on", "true" if on else "false")
        self.dot.style().unpolish(self.dot); self.dot.style().polish(self.dot)

    def _uncheck_silent(self):
        self.sw.blockSignals(True); self.sw.setChecked(False)
        self.sw._refresh(False); self.sw.blockSignals(False)
        self._set_dot(False)

    def restore(self):
        eng = self._eng()
        on = bool(eng.is_enabled() and eng.is_radio_only()) if eng else False
        self.sw.blockSignals(True); self.sw.setChecked(on)
        self.sw._refresh(on); self.sw.blockSignals(False)
        self._set_dot(on)

    def _on_toggle(self, checked):
        eng = self._eng()
        if eng is not None:
            if checked:
                # esclusiva con la riga Engineer: qui la card non si mostra
                _e = getattr(self._app, "_eng_row", None)
                if _e is not None and _e.sw.isChecked():
                    _e._uncheck_silent()
                eng.set_radio_only(True)
                eng.set_enabled(True)
            else:
                eng.set_radio_only(False)
                _e = getattr(self._app, "_eng_row", None)
                if _e is None or not _e.sw.isChecked():
                    eng.set_enabled(False)
        self._set_dot(checked)

    def _open_config(self):
        # SOLO apre le impostazioni audio: niente auto-accensione della riga
        try:
            eng = self._eng()
            if eng is None:
                return
            panel = eng.settings_panel() \
                if hasattr(eng, "settings_panel") else None
            if panel is not None:
                self._app.open_settings_page("engineer", "Radio", panel=panel)
        except Exception as _e:
            try:
                eng.log("radio settings: %r" % (_e,))
            except Exception:
                pass


class _OverlayTab(QWidget):
    """Pannello overlay: lista scrollabile compatta + gestione processi."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.win = parent          # main window (per raggiungere _engineer)
        self.config = get_config()
        self._procs = {}          # key -> subprocess.Popen (un processo per overlay)
        self._build_ui()
        self._restore_all()

    # ── GESTIONE PROCESSI (un overlay = un processo Python) ───────────
    def _spawn_cmd(self, key):
        if getattr(sys, "frozen", False):
            # eseguibile PyInstaller: rilancia se stesso con --overlay
            return [sys.executable, "--overlay", key]
        # 0.3b: overlay come modulo (overlays/run_overlay.py + overlays/registry)
        return [sys.executable, "-m", "overlays.run_overlay", key]

    def start_proc(self, key):
        p = self._procs.get(key)
        if p is not None and p.poll() is None:
            return                      # già attivo
        try:
            kw = {}
            if os.name == "nt":         # Windows: niente finestra console
                kw["creationflags"] = subprocess.CREATE_NO_WINDOW
            env = dict(os.environ)
            env["LMU_PARENT_PID"] = str(os.getpid())   # watchdog nel figlio
            env["LMU_OVERLAY_CHILD"] = "1"             # anti fork-bomb
            self._procs[key] = subprocess.Popen(self._spawn_cmd(key),
                                                 cwd=str(_PROJECT_ROOT),
                                                 env=env, **kw)
        except Exception:
            self._procs.pop(key, None)

    def stop_proc(self, key):
        p = self._procs.get(key)
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass
        self._procs.pop(key, None)

    def stop_all(self):
        """Spegne tutti i processi overlay (chiamata alla chiusura dell'app)."""
        for key, _label, _cls in WIDGETS:
            self.stop_proc(key)

    def restart_proc(self, key):
        # riavvia solo se era attivo (per applicare la nuova config)
        if self._procs.get(key) is not None:
            self.stop_proc(key)
            self.start_proc(key)

    def config_proxy(self, key):
        """Oggetto passato alla ConfigWindow: su Apply/Save salva la config su
        disco e riavvia il processo dell'overlay così rilegge le impostazioni."""
        app = self

        class _Proxy:
            def reload_config(self_inner):
                try:
                    app.config.save()
                except Exception:
                    pass
                # la MFD card si aggiorna LIVE (watcher sul config):
                # niente riavvio processo, niente sparisci/riappari
                if key != "wec26mfd":
                    app.restart_proc(key)
        return _Proxy()

    # ── UI ─────────────────────────────────────────────────────────────
    def _restore_all(self):
        for row in self._rows:
            row.restore()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── corpo: lista CENTRATA a larghezza contenuta (senza, su schermi
        #    larghi nome e toggle finiscono ai bordi opposti) ──
        body = QWidget()
        body.setObjectName("body")
        _outer = QVBoxLayout(body)
        _outer.setContentsMargins(0, 18, 0, 18)
        # TRE colonne: primi 10 widget nella 1a, il resto nella 2a, 3a libera
        _hband = QHBoxLayout()
        _hband.setSpacing(14)
        _hband.addStretch(1)
        _cols = []
        for _ in range(3):
            _c = QWidget(); _c.setObjectName("listCol")
            _c.setMaximumWidth(480); _c.setMinimumWidth(360)
            _l = QVBoxLayout(_c)
            _l.setContentsMargins(8, 8, 8, 8)
            _l.setSpacing(4)
            _cols.append(_l)
            _hband.addWidget(_c, 0, Qt.AlignTop)
        _hband.addStretch(1)
        _outer.addLayout(_hband)
        _outer.addStretch(1)

        self._rows = []
        _all = []
        for key, label, cls in WIDGETS:
            row = WidgetRow(key, label, cls, self)
            self._rows.append(row)
            _all.append(row)
        # Engineer: SOLO RADIO (deciso 20/07) — una riga unica, il motore
        # parla e basta. La vecchia riga "Radio" e' RIMOSSA (classe tenuta,
        # come Dashboard Engineer): stessa cosa con due nomi.
        self._eng_row = EngineerRow(self)
        self._rows.append(self._eng_row)
        _all.append(self._eng_row)
        for i, row in enumerate(_all):
            _cols[0 if i < 10 else 1].addWidget(row)
        for _l in _cols:
            _l.addStretch(1)
        self._extra_col = _cols[2]      # 3a colonna: opzioni app (video intro...)

        scroll = QScrollArea()
        scroll.setObjectName("scrollArea")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(body)

        # STACK: pagina 0 = lista widget, pagina 1 = settings del widget
        self._stack = QStackedWidget()
        self._stack.addWidget(scroll)              # 0
        self._settings_inner = QWidget()
        self._settings_inner.setObjectName("body")
        self._settings_lay = QVBoxLayout(self._settings_inner)
        self._settings_lay.setContentsMargins(0, 0, 0, 0)
        self._settings_host = QScrollArea()
        self._settings_host.setObjectName("scrollArea")
        self._settings_host.setWidgetResizable(True)
        self._settings_host.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._settings_host.setWidget(self._settings_inner)
        self._stack.addWidget(self._settings_host)  # 1
        root.addWidget(self._stack)
        self._cur_cfg = None

        self.setStyleSheet(_TAB_QSS)

    def open_settings_page(self, key, title, overlay_proxy=None, panel=None):
        """Apre le impostazioni DENTRO la tab (pagina con freccia indietro).
        panel: widget gia' pronto (es. pannello Engineer); altrimenti costruisce
        la ConfigWindow embedded del widget `key`."""
        # il pannello Engineer e' CACHATO (settings_panel): va STACCATO
        # prima di buttare il contenitore vecchio, altrimenti il GC lo
        # distrugge insieme al wrap e al giro dopo la rotella monta un
        # widget morto (RuntimeError silenzioso = "il bottone non va piu'")
        _keep = getattr(self, "_cur_cfg", None)
        if _keep is not None:
            try:
                _keep.setParent(None)
            except Exception:
                pass
        while self._settings_lay.count():
            it = self._settings_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        band = QHBoxLayout(); band.addStretch(1)
        col = QWidget(); col.setObjectName("listCol")
        col.setMaximumWidth(760); col.setMinimumWidth(520)
        cl = QVBoxLayout(col); cl.setContentsMargins(8, 14, 8, 8)
        # freccia indietro (uguale per widget ed engineer)
        _back = QPushButton("\u2039  Back"); _back.setObjectName("cfgBack")
        _back.setCursor(Qt.PointingHandCursor)
        _back.clicked.connect(self.close_settings_page)
        _hb = QHBoxLayout(); _hb.addWidget(_back)
        _t = QLabel((title or "").upper()); _t.setObjectName("cfgTitle")
        _hb.addSpacing(8); _hb.addWidget(_t); _hb.addStretch()
        cl.addLayout(_hb)
        if panel is not None:
            cl.addWidget(panel)
            self._cur_cfg = panel
        else:
            from gui.config_window import ConfigWindow
            cfg = ConfigWindow(self.config, overlay_proxy, parent=self,
                               widget_key=key, title=title, embedded=True,
                               on_back=self.close_settings_page)
            # header proprio della ConfigWindow nascosto: usiamo il nostro
            try:
                cfg.btn_back.hide()
            except Exception:
                pass
            cl.addWidget(cfg)
            self._cur_cfg = cfg
        band.addWidget(col, 0); band.addStretch(1)
        wrap = QWidget(); wl = QVBoxLayout(wrap)
        wl.setContentsMargins(0, 18, 0, 18); wl.addLayout(band); wl.addStretch(1)
        self._settings_lay.addWidget(wrap)
        self._stack.setCurrentIndex(1)

    def close_settings_page(self):
        self._stack.setCurrentIndex(0)


_TAB_QSS = """
#body { background: transparent; }
#scrollArea { background: transparent; border: none; }
QScrollBar:vertical {
    background: transparent; width: 8px; margin: 2px;
}
QScrollBar::handle:vertical {
    background: #3a3a3e; border-radius: 4px; min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #4a4a50; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

#widgetRow { background: rgba(255,255,255,0.04); border: none; border-radius: 9px; }
#widgetRow:hover { background: rgba(255,255,255,0.08); }
#listCol { background: transparent; }

#statusDot { font-size: 14px; background: transparent; }
#statusDot[on="true"]  { color: #00e676; }
#statusDot[on="false"] { color: #4a4a4e; }

#widgetName { color: #f2f2f2; font-family:'Heebo'; font-size: 15px; font-weight: bold; background: transparent; }

#toggleBtn { border-radius: 10px; font-family:'Heebo'; font-size: 12px; font-weight: bold; border: none; letter-spacing: 0.3px; }
QPushButton[on="false"] { background: #2e2e33; color: #8a8a90; }
QPushButton[on="false"]:hover { background: #3a3a40; color: #b0b0b6; }
QPushButton[on="true"]  { background: #00a152; color: #ffffff; }
QPushButton[on="true"]:hover { background: #00e676; color: #06120b; }

#btnGear { background: rgba(255,255,255,0.06); border-radius: 8px; color: #9a9aa0; border: none; font-family: "Material Symbols Rounded"; font-size: 20px; }
#btnGear:hover { background: rgba(255,255,255,0.12); }
"""
