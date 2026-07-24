"""
gui/config_window.py — Finestra impostazioni overlay (stile TinyPedal).

Si apre sopra l'overlay (icona ingranaggio in titlebar). Modifichi i valori,
premi Applica (aggiornamento live) o Salva (live + persiste su config.json).
Pensata per crescere: oggi gestisce Standings, domani gli altri widget.
"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                QPushButton, QSpinBox, QFrame,
                                QWidget, QGridLayout, QComboBox)
from PySide6.QtCore import Qt


class ConfigWindow(QDialog):
    """Finestra impostazioni. Riceve il config globale e l'overlay da aggiornare.

    widget_key: chiave nel config ("standings", "relative", ...).
    title: etichetta mostrata (es. "Standings", "Relative").
    """

    def __init__(self, config, overlay, parent=None, widget_key="standings",
                 title="Standings", embedded=False, on_back=None):
        super().__init__(parent)
        self._config = config
        self._overlay = overlay
        self._key = widget_key
        self._title = title
        self._embedded = bool(embedded)
        self._on_back = on_back        # callback freccia indietro (pagina)
        if self._embedded:
            # pannello dentro la tab: niente flag da finestra, sfondo
            # trasparente (eredita la pagina, bg traslucido come le card)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
        else:
            self.setWindowTitle(f"Settings — {title}")
            self.setWindowFlags(Qt.Dialog | Qt.Tool | Qt.WindowStaysOnTopHint)
            self.setModal(False)
        self._build_ui()
        self._load_values()

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        if self._embedded:
            _hdr = QHBoxLayout()
            self.btn_back = QPushButton("\u2039  Back")
            self.btn_back.setObjectName("cfgBack")
            self.btn_back.setCursor(Qt.PointingHandCursor)
            self.btn_back.clicked.connect(lambda: self._on_back and self._on_back())
            _hdr.addWidget(self.btn_back)
            _t = QLabel(self._title.upper()); _t.setObjectName("cfgTitle")
            _hdr.addSpacing(8); _hdr.addWidget(_t); _hdr.addStretch()
            lay.addLayout(_hdr)
        else:
            title = QLabel(self._title.upper())
            title.setObjectName("cfgTitle")
            lay.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(9)
        grid.setContentsMargins(0, 0, 0, 0)

        row_i = 0
        is_standings = self._key == "standings"
        is_relative = self._key == "relative"

        if is_standings:
            # ── Tema grafico ──
            grid.addWidget(QLabel("Theme"), row_i, 0)
            self.cmb_theme = QComboBox()
            self.cmb_theme.addItem("WEC", "wec")
            self.cmb_theme.addItem("ELMS", "elms")
            self.cmb_theme.addItem("IMSA", "imsa")
            grid.addWidget(self.cmb_theme, row_i, 1)
            row_i += 1
            # ── Vista: classe o generale ──
            grid.addWidget(QLabel("View"), row_i, 0)
            view_row = QHBoxLayout()
            view_row.setSpacing(4)
            self.btn_view_class = QPushButton("Class")
            self.btn_view_overall = QPushButton("Overall")
            for b in (self.btn_view_class, self.btn_view_overall):
                b.setCheckable(True)
                b.setCursor(Qt.PointingHandCursor)
                b.setObjectName("viewBtn")
                b.setMinimumHeight(34)
            self.btn_view_class.clicked.connect(lambda: self._set_view("class"))
            self.btn_view_overall.clicked.connect(lambda: self._set_view("overall"))
            view_row.addWidget(self.btn_view_class)
            view_row.addWidget(self.btn_view_overall)
            view_row.addStretch()
            view_w = QWidget()
            view_w.setLayout(view_row)
            grid.addWidget(view_w, row_i, 1)
            row_i += 1

            # ── Numero piloti ──
            grid.addWidget(QLabel("Drivers shown"), row_i, 0)
            self.sp_drivers = QSpinBox()
            self.sp_drivers.setRange(3, 30)
            self.sp_drivers.setFixedWidth(88)
            grid.addWidget(self.sp_drivers, row_i, 1)
            row_i += 1

            # ── Top speed on/off ──
            grid.addWidget(self._toggles_grid([
                ("Top speed", "speed"), ("Track limits", "tl"),
                ("Pit stops", "pit"), ("Stint", "stint"),
                ("Pos gained/lost", "pdelta"),
                ("Short names", "short_names"),
            ]), row_i, 0, 1, 2)
            row_i += 1
        elif is_relative:
            # ── Tema grafico ──
            grid.addWidget(QLabel("Theme"), row_i, 0)
            self.cmb_theme = QComboBox()
            self.cmb_theme.addItem("WEC", "wec")
            self.cmb_theme.addItem("ELMS", "elms")
            self.cmb_theme.addItem("IMSA", "imsa")
            grid.addWidget(self.cmb_theme, row_i, 1)
            row_i += 1
            # ── Relative: auto per lato ──
            grid.addWidget(QLabel("Cars each side"), row_i, 0)
            self.sp_rows = QSpinBox()
            self.sp_rows.setRange(1, 8)
            self.sp_rows.setFixedWidth(88)
            grid.addWidget(self.sp_rows, row_i, 1)
            row_i += 1

            grid.addWidget(self._toggles_grid([
                ("Top speed", "speed"), ("Best lap", "best"),
                ("Track limits", "tl"), ("Pit stops", "pit"),
                ("Sectors", "sectors"), ("Laps", "laps"),
                ("Stint", "stint"), ("Tyre wear", "wear"),
                ("Pos gained/lost", "pdelta"), ("Gap", "gap"),
                ("Last lap", "lap"), ("Tyre", "tyre"),
                ("Energy", "energy"), ("Status", "status"),
                ("Hide garage cars", "hide_garage"),
                ("My class only", "class_only"),
                ("No lapped", "no_lapped"),
                ("Header", "header"),
            ]), row_i, 0, 1, 2)
            row_i += 1
        elif self._key == "hud":
            # ── HUD: blocchi principali ──
            for k, lab in [("gearbox", "Cambio"), ("icons", "HUD icone"),
                           ("carmini", "Macchinina")]:
                grid.addWidget(QLabel(lab), row_i, 0)
                grid.addWidget(self._make_toggle(k), row_i, 1)
                row_i += 1
            # ── Temp gomma mostrata (battistrada / strato / carcassa) ──
            grid.addWidget(QLabel("Tyre temp"), row_i, 0)
            self.cmb_tyre = self._make_tyre_combo()
            grid.addWidget(self.cmb_tyre, row_i, 1)
            row_i += 1
            # ── HUD: ogni icona di stato attivabile/disattivabile ──
            grid.addWidget(QLabel("RPM LEDs"), row_i, 0)
            grid.addWidget(self._make_toggle("rpm_leds"), row_i, 1)
            row_i += 1
            for k, lab in [("light", "Fari"), ("wiper", "Tergi"), ("rain", "Rain LED"),
                           ("pit", "Pit limiter"), ("engine", "Motore"),
                           ("oil", "Olio"), ("water", "Acqua"), ("fuel", "Fuel"),
                           ("tc", "TC"), ("abs", "ABS"), ("battery", "Batteria")]:
                grid.addWidget(QLabel(lab), row_i, 0)
                grid.addWidget(self._make_toggle(k), row_i, 1)
                row_i += 1
        elif self._key == "list":
            # ── List: ogni riga dati attivabile/disattivabile ──
            for k, lab in [("body", "Body"), ("aero", "Aero"),
                           ("tyre", "Tyre Wear"), ("tyretemp", "Tyre Temp"), ("susp", "Susp"), ("brake", "Brake"),
                           ("fuel", "Fuel"), ("energy", "Energy"),
                           ("battery", "Battery"), ("emotor", "E-Motor"),
                                                      ("erpm", "E-RPM"),
                           ("etrqeng", "Eng-Trq"),
                           ("oil", "Oil"), ("water", "Water"), ("engine", "Engine")]:
                grid.addWidget(QLabel(lab), row_i, 0)
                grid.addWidget(self._make_toggle(k), row_i, 1)
                row_i += 1
        elif self._key == "session":
            # ── Session: mostra forecast ──
            grid.addWidget(QLabel("Forecast"), row_i, 0)
            fc_row = QHBoxLayout()
            fc_row.setSpacing(4)
            self.btn_fc_on = QPushButton("On")
            self.btn_fc_off = QPushButton("Off")
            for b in (self.btn_fc_on, self.btn_fc_off):
                b.setCheckable(True)
                b.setCursor(Qt.PointingHandCursor)
                b.setObjectName("viewBtn")
                b.setMinimumHeight(34)
            self.btn_fc_on.clicked.connect(lambda: self._set_forecast(True))
            self.btn_fc_off.clicked.connect(lambda: self._set_forecast(False))
            fc_row.addWidget(self.btn_fc_on)
            fc_row.addWidget(self.btn_fc_off)
            fc_row.addStretch()
            fc_w = QWidget()
            fc_w.setLayout(fc_row)
            grid.addWidget(fc_w, row_i, 1)
            row_i += 1
        elif self._key == "strategy":
            # ── Strategy: giri per media consumo ──
            grid.addWidget(QLabel("Avg laps"), row_i, 0)
            self.sp_window = QSpinBox()
            self.sp_window.setRange(1, 10)
            self.sp_window.setFixedWidth(88)
            grid.addWidget(self.sp_window, row_i, 1)
            row_i += 1
            # ── Save margin: giri risparmiabili per stint (lift&coast) ──
            grid.addWidget(QLabel("Save margin"), row_i, 0)
            self.sp_save = QSpinBox()
            self.sp_save.setRange(0, 6)
            self.sp_save.setFixedWidth(88)
            grid.addWidget(self.sp_save, row_i, 1)
            row_i += 1
            # ── Record telemetry ──
            grid.addWidget(QLabel("Record"), row_i, 0)
            grid.addWidget(self._make_toggle("record"), row_i, 1)
            row_i += 1
        elif self._key == "map":
            # ── MODALITA' = UNA scelta secca (rich. 24/07):
            # Intera / GPS / Adattiva. Poi zoom, gap e dettagli ──
            from PySide6.QtWidgets import (QComboBox as _QCB9,
                                           QDoubleSpinBox as _QDSB9)
            # controlli BILANCIATI (rich. 24/07): stessa altezza degli
            # switch (26px) e carattere medio uniforme, niente bottoni
            # giganti ne' scritte microscopiche
            _CSS9 = ("QComboBox, QDoubleSpinBox"
                     "{font-size:12px; padding:1px 6px;}"
                     "QDoubleSpinBox::up-button,"
                     "QDoubleSpinBox::down-button"
                     "{width:18px;}")
            grid.addWidget(QLabel("Map mode"), row_i, 0)
            self.cb_mmode = _QCB9()
            self.cb_mmode.addItems(["Full", "GPS", "Adaptive"])
            self.cb_mmode.setFixedSize(100, 26)
            self.cb_mmode.setStyleSheet(_CSS9)
            grid.addWidget(self.cb_mmode, row_i, 1)
            row_i += 1
            grid.addWidget(QLabel("GPS zoom"), row_i, 0)
            self.sp_mzoom = _QDSB9()
            self.sp_mzoom.setRange(1.0, 25.0)   # niente limiti stretti
            self.sp_mzoom.setSingleStep(0.5)
            self.sp_mzoom.setValue(5.5)
            self.sp_mzoom.setFixedSize(104, 28)
            self.sp_mzoom.setStyleSheet(_CSS9)
            grid.addWidget(self.sp_mzoom, row_i, 1)
            row_i += 1
            # soglia della battaglia in SECONDI di gap (rich. 24/07)
            grid.addWidget(QLabel("Adaptive gap (s)"), row_i, 0)
            self.sp_again = _QDSB9()
            self.sp_again.setRange(0.5, 10.0)
            self.sp_again.setSingleStep(0.5)
            self.sp_again.setValue(1.0)
            self.sp_again.setFixedSize(104, 28)
            self.sp_again.setStyleSheet(_CSS9)
            grid.addWidget(self.sp_again, row_i, 1)
            row_i += 1
            # nomi piloti (3 lettere stile F1) accanto ai pallini
            grid.addWidget(QLabel("Driver tags"), row_i, 0)
            grid.addWidget(self._make_toggle("names"), row_i, 1)
            row_i += 1
            # macchinine ruotate al posto dei pallini (idea 24/07)
            grid.addWidget(QLabel("Car icons"), row_i, 0)
            grid.addWidget(self._make_toggle("caricons"), row_i, 1)
            row_i += 1
            # dettagli: cordoli, numeri curva, settori
            grid.addWidget(QLabel("Curve details"), row_i, 0)
            grid.addWidget(self._make_toggle("detail"), row_i, 1)
            row_i += 1
            # pista scura (asfalto, default) o bianca
            grid.addWidget(QLabel("Dark track"), row_i, 0)
            grid.addWidget(self._make_toggle("darktrack"), row_i, 1)
            row_i += 1
            # ── GESTORE MAPPE (rich. 24/07): COLONNA a destra stile
            # elenco stint — tutte le piste registrate, cestino per
            # cancellare (si riscrive al giro pulito dopo), scrollabile ──
            from PySide6.QtWidgets import (QVBoxLayout as _QVL9,
                                           QWidget as _QW9,
                                           QScrollArea as _QSA9)
            _side9 = _QW9()
            _sv9 = _QVL9(_side9)
            _sv9.setContentsMargins(16, 0, 0, 0)
            _sv9.setSpacing(4)
            _ttl9 = QLabel("Maps")
            _ttl9.setStyleSheet("font-weight:600; font-size:12px;")
            _sv9.addWidget(_ttl9)
            self._maps_sa9 = _QSA9()
            self._maps_sa9.setWidgetResizable(True)
            self._maps_sa9.setFixedSize(238, 290)   # ~10 righe + scroll
            self._maps_sa9.setStyleSheet(
                "QScrollArea{border:1px solid rgba(255,255,255,0.10);"
                "border-radius:6px; background:transparent;}")
            _sv9.addWidget(self._maps_sa9)
            _sv9.addStretch(1)
            grid.addWidget(_side9, 0, 2, max(row_i + 1, 11), 1)
            self._maps_refresh9()
        # wec26mfd (Dashboard): AUTO PIT (i Mod 1-8 si gestiscono in overlay)
        elif self._key == "wec26mfd":
            # Il muretto scrive la Virtual Energy nel pit menu. Salva SUBITO in
            # engineer_cfg (fuori Apply/Save): il muretto lo rilegge live e lo
            # stesso flag e' anche nel menu Mod 3 del dash.
            from core import engineer_cfg as _ecfg
            grid.addWidget(QLabel("Auto pit"), row_i, 0)
            _ap = QPushButton()
            _ap.setCheckable(True)
            _ap.setCursor(Qt.PointingHandCursor)
            _ap.setObjectName("switchBtn")
            _ap.setFixedSize(52, 26)
            try:
                _on0 = bool(_ecfg.load().get("auto_pit", False))
            except Exception:
                _on0 = False
            _ap.setChecked(_on0)
            _ap.setText("ON" if _on0 else "OFF")

            def _ap_tgl(on, b=_ap):
                b.setText("ON" if on else "OFF")
                try:
                    _ecfg.save(auto_pit=bool(on))
                except Exception:
                    pass
            _ap.toggled.connect(_ap_tgl)
            grid.addWidget(_ap, row_i, 1)
            row_i += 1
            # ── Dash layout: completa / solo cambio / solo header /
            #    senza header (salva SUBITO, la card lo legge live) ──
            from PySide6.QtWidgets import QComboBox
            grid.addWidget(QLabel("Dash layout"), row_i, 0)
            _dlc = QComboBox()
            # etichette in INGLESE: l'app resta EN finche' non e'
            # multilingua (rich. 23/07)
            _dlc.addItems(["Full", "Gear only", "Header only",
                           "No header"])
            try:
                from core.config import get_config as _gc9
                _dlc.setCurrentIndex(int(_gc9().widget("wec26mfd")
                                         .get("dash_layout", 0) or 0))
            except Exception:
                pass

            def _dl_ch(ix):
                try:
                    from core.config import get_config as _gc8
                    _c8 = _gc8()
                    _c8._data.setdefault("wec26mfd", {})["dash_layout"] = \
                        int(ix)
                    _c8.save()
                except Exception:
                    pass
            _dlc.currentIndexChanged.connect(_dl_ch)
            grid.addWidget(_dlc, row_i, 1)
            row_i += 1
        # gli altri overlay WEC: soglia lotta / preview
        elif self._key in ("wec26battle", "wec26battleb", "wec26flag",
                           "wec26radio"):
            # ── WEC 2026: soglia lotta (solo battle) + PREVIEW per
            #    posizionare l'overlay quando non c'e' niente in pista ──
            if self._key in ("wec26battle", "wec26battleb"):
                from PySide6.QtWidgets import QDoubleSpinBox
                grid.addWidget(QLabel("Battle gap (s)"), row_i, 0)
                self.sp_bgap = QDoubleSpinBox()
                self.sp_bgap.setRange(0.5, 10.0)
                self.sp_bgap.setSingleStep(0.5)
                self.sp_bgap.setFixedWidth(88)
                grid.addWidget(self.sp_bgap, row_i, 1)
                row_i += 1
                grid.addWidget(QLabel("Class only"), row_i, 0)
                grid.addWidget(self._make_toggle("class_only"), row_i, 1)
                row_i += 1
                grid.addWidget(QLabel("No lapped"), row_i, 0)
                grid.addWidget(self._make_toggle("pos_only"), row_i, 1)
                row_i += 1
            if self._key == "wec26flag":
                # Race Control: 3 zone indipendenti on/off (default ON)
                for _lab, _k in (("Flag", "show_flags"),
                                 ("Penalità / Track", "show_penalties"),
                                 ("Messaggi gara", "show_messages")):
                    grid.addWidget(QLabel(_lab), row_i, 0)
                    grid.addWidget(self._make_toggle(_k), row_i, 1)
                    row_i += 1
            grid.addWidget(QLabel("Preview"), row_i, 0)
            grid.addWidget(self._make_toggle("preview"), row_i, 1)
            row_i += 1
        elif self._key in ("car", "minicar"):
            # ── Temp gomma mostrata (battistrada / strato / carcassa) ──
            grid.addWidget(QLabel("Tyre temp"), row_i, 0)
            self.cmb_tyre = self._make_tyre_combo()
            grid.addWidget(self.cmb_tyre, row_i, 1)
            row_i += 1
        elif self._key == "dashboard":
            # ── Tyre temperature layer shown around the minicar ──
            grid.addWidget(QLabel("Tyre temp"), row_i, 0)
            self.cmb_tyre = self._make_tyre_combo()
            grid.addWidget(self.cmb_tyre, row_i, 1)
            row_i += 1
            # ── Engineer options (radio/voice/coaching): shared with the
            #    original engineer overlay ──
            row_i = self._add_engineer_opts(grid, row_i)

        # ── Scala (con reset) — comune a tutti ──
        grid.addWidget(QLabel("Scale"), row_i, 0)
        scale_row = QHBoxLayout()
        scale_row.setSpacing(4)
        self.btn_scale_down = QPushButton("−")
        self.btn_scale_up = QPushButton("+")
        self.lbl_scale = QLabel("1.0")
        self.lbl_scale.setAlignment(Qt.AlignCenter)
        self.lbl_scale.setFixedWidth(60)
        self.lbl_scale.setObjectName("scaleValue")
        self.btn_scale_reset = QPushButton("⟲")
        for b in (self.btn_scale_down, self.btn_scale_up, self.btn_scale_reset):
            b.setFixedSize(36, 36)
            b.setCursor(Qt.PointingHandCursor)
        self.btn_scale_down.clicked.connect(lambda: self._step_scale(-0.1))
        self.btn_scale_up.clicked.connect(lambda: self._step_scale(0.1))
        self.btn_scale_reset.clicked.connect(self._reset_scale)
        scale_row.addWidget(self.btn_scale_down)
        scale_row.addWidget(self.lbl_scale)
        scale_row.addWidget(self.btn_scale_up)
        scale_row.addWidget(self.btn_scale_reset)
        scale_row.addStretch()
        scale_w = QWidget()
        scale_w.setLayout(scale_row)
        grid.addWidget(scale_w, row_i, 1)
        row_i += 1

        # ── Opacità sfondo — comune a tutti ──
        grid.addWidget(QLabel("Background"), row_i, 0)
        self.sp_opacity = QSpinBox()
        self.sp_opacity.setRange(0, 100)
        self.sp_opacity.setSuffix(" %")
        self.sp_opacity.setFixedWidth(88)
        grid.addWidget(self.sp_opacity, row_i, 1)

        lay.addLayout(grid)

        # separatore
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("cfgSep")
        lay.addWidget(sep)

        # bottoni
        btns = QHBoxLayout()
        btns.addStretch()
        self.btn_apply = QPushButton("Apply")
        self.btn_save = QPushButton("Save")
        self.btn_close = QPushButton("Close")
        self.btn_apply.setObjectName("btnApply")
        self.btn_save.setObjectName("btnSave")
        self.btn_apply.clicked.connect(self._apply)
        self.btn_save.clicked.connect(self._save)
        self.btn_close.clicked.connect(self.close)
        if self._embedded:
            self.btn_close.hide()
        for b in (self.btn_apply, self.btn_save, self.btn_close):
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumWidth(104); b.setMinimumHeight(34)
            btns.addWidget(b)
        lay.addLayout(btns)

        self.setStyleSheet(_CFG_QSS)

    # ── VALORI ────────────────────────────────────────────────────────
    def _load_values(self):
        cfg = self._config.widget(self._key)
        self._toggle_state = {
            "class": cfg.get("show_class", False),
            "header": cfg.get("show_header", True),
            "short_names": cfg.get("short_names", False),
            "speed": cfg.get("show_speed", True),
            "best": cfg.get("show_best_lap", True),
            "tl": cfg.get("show_track_limits", True),
            "pit": cfg.get("show_pit", True),
            "sectors": cfg.get("show_sectors", True),
            "laps": cfg.get("show_laps", True),
            "stint": cfg.get("show_stint", True),
            "wear": cfg.get("show_wear", True),
            "session_row": cfg.get("show_session_row", True),
            "hide_garage": cfg.get("hide_garage", True),
            "class_only": cfg.get("class_only", False),
            "no_lapped": cfg.get("no_lapped", False),
            "gap": cfg.get("show_gap", True),
            "pdelta": cfg.get("show_pos_delta", True),
            "lap": cfg.get("show_lap", True),
            "status": cfg.get("show_status", True),
        }
        # toggle righe del widget list (default on)
        for _k in ("body", "aero", "tyre", "tyretemp", "susp", "brake",
                   "fuel", "energy", "battery", "emotor",
                   "erpm", "etrqeng", "oil", "water", "engine"):
            self._toggle_state[_k] = cfg.get(f"show_{_k}", True)
        # toggle icone del widget hud (default on)
        for _k in ("light", "wiper", "rain", "pit", "tc", "abs", "rpm_leds"):
            self._toggle_state[_k] = cfg.get(f"show_{_k}", True)
        self._scale = cfg.scale
        self.lbl_scale.setText(f"{self._scale:.1f}")
        self.sp_opacity.setValue(cfg.get("bg_opacity", 100))
        if self._key == "standings":
            self.sp_drivers.setValue(cfg.get("max_drivers", 10))
            self._view = cfg.get("view_mode", "class")
            self._refresh_view_buttons()
            self._set_toggle("speed", cfg.get("show_speed", True))
            self._set_toggle("tl", cfg.get("show_track_limits", True))
            self._set_toggle("pit", cfg.get("show_pit", True))
            self._set_toggle("stint", cfg.get("show_stint", True))
            self._set_toggle("pdelta", cfg.get("show_pos_delta", True))
            self._set_toggle("short_names", cfg.get("short_names", False))
            _ti = self.cmb_theme.findData(cfg.get("theme", "wec"))
            self.cmb_theme.setCurrentIndex(max(0, _ti))
        elif self._key == "relative":
            self.sp_rows.setValue(cfg.get("rows_each_side", 2))
            self._set_toggle("speed", cfg.get("show_speed", True))
            self._set_toggle("best", cfg.get("show_best_lap", True))
            self._set_toggle("tl", cfg.get("show_track_limits", True))
            self._set_toggle("pit", cfg.get("show_pit", True))
            self._set_toggle("sectors", cfg.get("show_sectors", True))
            self._set_toggle("laps", cfg.get("show_laps", True))
            self._set_toggle("stint", cfg.get("show_stint", True))
            self._set_toggle("wear", cfg.get("show_wear", True))
            self._set_toggle("pdelta", cfg.get("show_pos_delta", True))
            self._set_toggle("hide_garage", cfg.get("hide_garage", True))
            self._set_toggle("class_only", cfg.get("class_only", False))
            self._set_toggle("no_lapped", cfg.get("no_lapped", False))
            for _c in ("gap", "lap", "tyre", "energy", "status"):
                self._set_toggle(_c, cfg.get(f"show_{_c}", True))
            _ti = self.cmb_theme.findData(cfg.get("theme", "wec"))
            self.cmb_theme.setCurrentIndex(max(0, _ti))
        elif self._key == "hud":
            for _k in ("gearbox", "icons", "carmini",
                       "rpm_leds", "light", "wiper", "rain", "pit", "engine", "oil", "water",
                       "fuel", "tc", "abs", "battery"):
                self._set_toggle(_k, cfg.get(f"show_{_k}", True))
            _li = self.cmb_tyre.findData(cfg.get("tyre_temp", "carcass"))
            self.cmb_tyre.setCurrentIndex(max(0, _li))
        elif self._key in ("car", "minicar"):
            _li = self.cmb_tyre.findData(cfg.get("tyre_temp", "carcass"))
            self.cmb_tyre.setCurrentIndex(max(0, _li))
        elif self._key == "dashboard":
            _li = self.cmb_tyre.findData(cfg.get("tyre_temp", "surface"))
            self.cmb_tyre.setCurrentIndex(max(0, _li))
        elif self._key == "list":
            for _k in ("body", "aero", "tyre", "tyretemp", "susp", "brake",
                       "fuel", "energy", "battery", "emotor",
                       "erpm", "etrqeng", "oil", "water", "engine"):
                self._set_toggle(_k, cfg.get(f"show_{_k}", True))
        elif self._key == "session":
            self._forecast = cfg.get("show_forecast", True)
            self._refresh_forecast_buttons()
        elif self._key == "strategy":
            self.sp_window.setValue(cfg.get("moving_window", 3))
            self.sp_save.setValue(int(cfg.get("save_margin", 2)))
            self._set_toggle("record", cfg.get("record", True))
        elif self._key == "map":
            if cfg.get("map_layout", 1) == 2:
                self.cb_mmode.setCurrentIndex(1)          # GPS fisso
            elif bool(cfg.get("map_adaptive", True)):
                self.cb_mmode.setCurrentIndex(2)          # adattiva
            else:
                self.cb_mmode.setCurrentIndex(0)          # intera
            self._set_toggle("names", bool(cfg.get("map_names", True)))
            self._set_toggle("caricons",
                             bool(cfg.get("map_car_icons", True)))
            self._set_toggle("detail", bool(cfg.get("map_detail", True)))
            self._set_toggle("darktrack",
                             bool(cfg.get("map_dark_track", True)))
            try:
                self.sp_mzoom.setValue(float(cfg.get("map_zoom", 5.5)))
                self.sp_again.setValue(
                    float(cfg.get("map_adapt_gap", 1.0)))
            except Exception:
                pass
        elif self._key in ("wec26battle", "wec26battleb", "wec26flag",
                           "wec26radio"):
            if self._key in ("wec26battle", "wec26battleb"):
                self.sp_bgap.setValue(float(cfg.get("battle_gap_s", 2.0)))
                self._set_toggle("class_only",
                                 bool(cfg.get("class_only", False)))
                self._set_toggle("pos_only",
                                 bool(cfg.get("pos_only", False)))
            if self._key == "wec26flag":
                for _k in ("show_flags", "show_penalties", "show_messages"):
                    self._set_toggle(_k, bool(cfg.get(_k, True)))
            self._set_toggle("preview", bool(cfg.get("preview", False)))

    def _make_tyre_combo(self):
        """Combo per scegliere lo strato temperatura gomma mostrato."""
        c = QComboBox()
        c.addItem("Surface", "surface")
        c.addItem("Inner", "inner")
        c.addItem("Carcass", "carcass")
        return c

    def _toggles_grid(self, items):
        """items = [(label, key), ...] -> widget a DUE colonne (max 10 righe
        per colonna), ogni cella e' label + switch. Testi non tagliati."""
        wrap = QWidget()
        g = QGridLayout(wrap)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(28)
        g.setVerticalSpacing(9)
        per_col = 10
        for i, (label, key) in enumerate(items):
            col = i // per_col
            row = i % per_col
            lb = QLabel(label)
            g.addWidget(lb, row, col * 2 + 0)
            g.addWidget(self._make_toggle(key), row, col * 2 + 1)
        # spinge le due colonne a sinistra
        g.setColumnStretch(4, 1)
        return wrap

    def _maps_refresh9(self):
        """Colonna mappe registrate: righe nome pista + cestino,
        come l'elenco degli stint."""
        try:
            from core.paths import USER_DIR
            from PySide6.QtWidgets import (QWidget, QVBoxLayout,
                                           QHBoxLayout, QLabel,
                                           QPushButton)
            body = QWidget()
            lay = QVBoxLayout(body)
            lay.setContentsMargins(6, 6, 6, 6)
            lay.setSpacing(2)
            d = USER_DIR / "trackmap_auto"
            files = sorted(d.glob("*.svg")) if d.exists() else []
            if not files:
                _e = QLabel("(no maps yet — drive a clean lap)")
                _e.setStyleSheet("color:#8a8f99; font-size:12px;")
                lay.addWidget(_e)
            for f in files:
                n = f.stem
                if n.endswith("_2026"):
                    n = n[:-5]
                row = QWidget()
                hl = QHBoxLayout(row)
                hl.setContentsMargins(2, 0, 2, 0)
                hl.setSpacing(6)
                _lb = QLabel(n)
                _lb.setStyleSheet("font-size:12px;")
                _lb.setToolTip(n)
                hl.addWidget(_lb, 1)
                _x = QPushButton("✕")
                _x.setFixedSize(24, 22)
                _x.setCursor(Qt.PointingHandCursor)
                _x.setStyleSheet("font-size:12px; padding:0;")
                _x.setToolTip("Cancella: si riscrive al giro pulito dopo")
                _x.clicked.connect(
                    lambda _c=False, _fp=str(f): self._map_delete9(_fp))
                hl.addWidget(_x)
                lay.addWidget(row)
            lay.addStretch(1)
            self._maps_sa9.setWidget(body)
        except Exception:
            pass

    def _map_delete9(self, fp):
        """Cancella la mappa: al giro pulito dopo si riscrive da sola
        (corsia compresa al passaggio in pit)."""
        try:
            from pathlib import Path
            Path(fp).unlink(missing_ok=True)
        except Exception:
            pass
        self._maps_refresh9()

    def _make_toggle(self, name):
        """Switch singolo compatto ON/OFF per una feature."""
        btn = QPushButton("ON")
        btn.setCheckable(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setObjectName("switchBtn")
        btn.setFixedSize(52, 26)
        btn.clicked.connect(lambda: self._set_toggle(name, not self._toggle_state.get(name, True)))
        if not hasattr(self, "_toggles"):
            self._toggles = {}
        self._toggles[name] = btn
        return btn

    def _set_toggle(self, name, on):
        if not hasattr(self, "_toggle_state"):
            self._toggle_state = {}
        self._toggle_state[name] = on
        btn = self._toggles[name]
        btn.setChecked(on)
        btn.setText("ON" if on else "OFF")

    # ── Impostazioni ingegnere condivise (radio/voce/coaching) ──────────
    def _add_engineer_opts(self, grid, row_i):
        """Aggiunge al pannello dashboard le stesse impostazioni dell'overlay
        ingegnere originale (lingua, volumi, ritardo tono, testo messaggi,
        tempo giro). Salvano SUBITO nel config dell'ingegnere (lo stesso file
        che l'ingegnere legge), fuori dal flusso Apply/Save del widget."""
        from PySide6.QtWidgets import QSlider
        try:
            import engineer_overlay as _eng
        except Exception:
            return row_i
        self._eng = _eng
        try:
            _cfg = _eng._load_cfg()
        except Exception:
            _cfg = {}

        # separatore + intestazione sezione
        line = QFrame(); line.setObjectName("cfgSep")
        line.setFrameShape(QFrame.HLine)
        grid.addWidget(line, row_i, 0, 1, 2); row_i += 1
        _hdr = QLabel("RADIO / VOICE"); _hdr.setObjectName("cfgSection")
        grid.addWidget(_hdr, row_i, 0, 1, 2); row_i += 1

        # ── Lingua ──
        grid.addWidget(QLabel("Language"), row_i, 0)
        _lr = QHBoxLayout(); _lr.setSpacing(4)
        self._eng_lang_btns = {}
        try:
            _cur = _eng._load_lang()
        except Exception:
            _cur = "it"
        for _lg in ("it", "en", "es", "fr"):
            b = QPushButton(_lg.upper()); b.setObjectName("viewBtn")
            b.setCheckable(True); b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(30); b.setChecked(_cur == _lg)
            b.clicked.connect(lambda _=False, l=_lg: self._set_eng_lang(l))
            self._eng_lang_btns[_lg] = b
            _lr.addWidget(b)
        _lr.addStretch()
        _lw = QWidget(); _lw.setLayout(_lr)
        grid.addWidget(_lw, row_i, 1); row_i += 1

        # ── Volumi (beep radio + voce) ──
        for _lab, _lf, _sf in (
                ("Beep volume", _eng._load_radio_vol, _eng._save_radio_vol),
                ("Voice volume", _eng._load_voice_vol, _eng._save_voice_vol)):
            grid.addWidget(QLabel(_lab), row_i, 0)
            _r = QHBoxLayout(); _r.setSpacing(8)
            sl = QSlider(Qt.Horizontal); sl.setRange(0, 100)
            try:
                sl.setValue(int(_lf()))
            except Exception:
                sl.setValue(100)
            sl.setFixedWidth(150)
            _v = QLabel("%d%%" % sl.value()); _v.setFixedWidth(40)
            def _mk(save_fn, lbl):
                def _ch(val):
                    lbl.setText("%d%%" % val)
                    try:
                        save_fn(int(val))
                    except Exception:
                        pass
                return _ch
            sl.valueChanged.connect(_mk(_sf, _v))
            _r.addWidget(sl); _r.addWidget(_v); _r.addStretch()
            _w = QWidget(); _w.setLayout(_r)
            grid.addWidget(_w, row_i, 1); row_i += 1

        # ── Ritardo tono radio prima del messaggio (0-5 s) ──
        grid.addWidget(QLabel("Radio tone delay"), row_i, 0)
        sp = QSpinBox(); sp.setRange(0, 5); sp.setSuffix(" s")
        sp.setFixedWidth(72)
        try:
            sp.setValue(max(0, min(5, int(_cfg.get("beep_delay_s", 2)))))
        except Exception:
            sp.setValue(2)
        sp.valueChanged.connect(lambda v: self._eng_save(beep_delay_s=int(v)))
        grid.addWidget(sp, row_i, 1); row_i += 1

        # ── Call lap time every lap ──
        grid.addWidget(QLabel("Call lap time every lap"), row_i, 0)
        grid.addWidget(self._eng_toggle(
            bool(_cfg.get("lap_time_always", False)),
            lambda on: self._eng_save(lap_time_always=bool(on))), row_i, 1)
        row_i += 1
        # ── decimi precisi nel tempo parlato ("1 e 52 e 3") ──
        grid.addWidget(QLabel("Read lap times with tenths"), row_i, 0)
        grid.addWidget(self._eng_toggle(
            bool(_cfg.get("lap_time_tenths", False)),
            lambda on: self._eng_save(lap_time_tenths=bool(on))), row_i, 1)
        row_i += 1
        return row_i

    def _eng_save(self, **kw):
        try:
            self._eng._save_cfg(**kw)
        except Exception:
            pass

    def _set_eng_lang(self, lang):
        for _lg, b in getattr(self, "_eng_lang_btns", {}).items():
            b.setChecked(_lg == lang)
        self._eng_save(lang=lang)

    def _eng_toggle(self, checked, cb):
        """Switch ON/OFF (stile switchBtn) che applica SUBITO la callback."""
        b = QPushButton("ON" if checked else "OFF")
        b.setObjectName("switchBtn"); b.setCheckable(True)
        b.setFixedSize(52, 26); b.setCursor(Qt.PointingHandCursor)
        b.setChecked(bool(checked))
        def _flip(on, _b=b):
            _b.setText("ON" if on else "OFF")
            cb(on)
        b.toggled.connect(_flip)
        return b

    def _set_view(self, mode):
        self._view = mode
        self._refresh_view_buttons()

    def _set_forecast(self, on):
        self._forecast = on
        self._refresh_forecast_buttons()

    def _refresh_forecast_buttons(self):
        self.btn_fc_on.setChecked(self._forecast)
        self.btn_fc_off.setChecked(not self._forecast)

    def _refresh_view_buttons(self):
        self.btn_view_class.setChecked(self._view == "class")
        self.btn_view_overall.setChecked(self._view == "overall")

    def _step_scale(self, delta):
        # nessun tetto superiore: le dash sui display volante hanno bisogno
        # di scale ben oltre 2.5 (prima era min(2.5, ...))
        self._scale = max(0.5, round(self._scale + delta, 3))
        self.lbl_scale.setText(f"{self._scale:.1f}")

    def _reset_scale(self):
        self._scale = 1.0
        self.lbl_scale.setText("1.0")

    # ── APPLICA / SALVA ───────────────────────────────────────────────
    def _write_to_config(self):
        self._config.set_scale(self._key, self._scale)
        self._config.set_value(self._key, "bg_opacity", self.sp_opacity.value())
        if self._key == "standings":
            self._config.set_value(self._key, "max_drivers", self.sp_drivers.value())
            self._config.set_value(self._key, "view_mode", self._view)
            self._config.set_value(self._key, "show_speed", self._toggle_state.get("speed", False))
            self._config.set_value(self._key, "show_track_limits", self._toggle_state.get("tl", True))
            self._config.set_value(self._key, "show_pit", self._toggle_state.get("pit", True))
            self._config.set_value(self._key, "show_stint", self._toggle_state.get("stint", True))
            self._config.set_value(self._key, "show_pos_delta", self._toggle_state.get("pdelta", True))
            # fascia sessione: overlay separato "Session bar", qui sempre off
            self._config.set_value(self._key, "show_session_row", False)
            self._config.set_value(self._key, "short_names", self._toggle_state.get("short_names", False))
            # colonne FISSE senza voce: best/settori/laps/wear/header OFF
            # (laps: flash sul compound; settori: nella cella status)
            for _c in ("best_lap", "sectors", "laps", "wear", "header"):
                self._config.set_value(self._key, f"show_{_c}", False)
            for _c in ("gap", "tyre", "energy", "status"):
                self._config.set_value(self._key, f"show_{_c}", True)
            # colonna LAST rimossa: il last lap lampeggia 10s nel GAP
            self._config.set_value(self._key, "show_lap", False)
            self._config.set_value(self._key, "theme", self.cmb_theme.currentData())
        elif self._key == "relative":
            self._config.set_value(self._key, "rows_each_side", self.sp_rows.value())
            self._config.set_value(self._key, "show_speed", self._toggle_state.get("speed", True))
            self._config.set_value(self._key, "show_best_lap", self._toggle_state.get("best", False))
            self._config.set_value(self._key, "show_track_limits", self._toggle_state.get("tl", True))
            self._config.set_value(self._key, "show_pit", self._toggle_state.get("pit", True))
            self._config.set_value(self._key, "show_sectors", self._toggle_state.get("sectors", True))
            self._config.set_value(self._key, "show_laps", self._toggle_state.get("laps", True))
            self._config.set_value(self._key, "show_stint", self._toggle_state.get("stint", True))
            self._config.set_value(self._key, "show_wear", self._toggle_state.get("wear", True))
            self._config.set_value(self._key, "show_pos_delta", self._toggle_state.get("pdelta", True))
            self._config.set_value(self._key, "hide_garage", self._toggle_state.get("hide_garage", True))
            self._config.set_value(self._key, "class_only", self._toggle_state.get("class_only", False))
            self._config.set_value(self._key, "no_lapped", self._toggle_state.get("no_lapped", False))
            self._config.set_value(self._key, "show_header", self._toggle_state.get("header", True))
            for _c in ("gap", "lap", "tyre", "energy", "status"):
                self._config.set_value(self._key, f"show_{_c}", self._toggle_state.get(_c, True))
            self._config.set_value(self._key, "theme", self.cmb_theme.currentData())
        elif self._key == "hud":
            for _k in ("gearbox", "icons", "carmini",
                       "rpm_leds", "light", "wiper", "rain", "pit", "engine", "oil", "water",
                       "fuel", "tc", "abs", "battery"):
                self._config.set_value(self._key, f"show_{_k}", self._toggle_state.get(_k, True))
            self._config.set_value(self._key, "tyre_temp", self.cmb_tyre.currentData())
        elif self._key in ("car", "minicar"):
            self._config.set_value(self._key, "tyre_temp", self.cmb_tyre.currentData())
        elif self._key == "dashboard":
            self._config.set_value(self._key, "tyre_temp",
                                   self.cmb_tyre.currentData())
        elif self._key == "list":
            for _k in ("fuel", "energy", "battery", "emotor",
                       "erpm", "etrqeng", "oil", "water", "engine"):
                self._config.set_value(self._key, f"show_{_k}", self._toggle_state.get(_k, True))
        elif self._key == "session":
            self._config.set_value(self._key, "show_forecast", self._forecast)
        elif self._key == "strategy":
            self._config.set_value(self._key, "moving_window", self.sp_window.value())
            self._config.set_value(self._key, "save_margin", self.sp_save.value())
            self._config.set_value(self._key, "record", self._toggle_state.get("record", True))
        elif self._key == "map":
            _mi9 = self.cb_mmode.currentIndex()
            self._config.set_value(self._key, "map_layout",
                                   2 if _mi9 == 1 else 1)
            self._config.set_value(self._key, "map_adaptive",
                                   _mi9 == 2)
            self._config.set_value(self._key, "map_names",
                                   bool(self._toggle_state.get("names", True)))
            self._config.set_value(self._key, "map_car_icons",
                                   bool(self._toggle_state.get("caricons", True)))
            self._config.set_value(self._key, "map_detail",
                                   bool(self._toggle_state.get("detail", True)))
            self._config.set_value(self._key, "map_dark_track",
                                   bool(self._toggle_state.get("darktrack", True)))
            try:
                self._config.set_value(self._key, "map_zoom",
                                       float(self.sp_mzoom.value()))
                self._config.set_value(self._key, "map_adapt_gap",
                                       float(self.sp_again.value()))
            except Exception:
                pass
        elif self._key in ("wec26battle", "wec26battleb", "wec26flag",
                           "wec26radio"):
            if self._key in ("wec26battle", "wec26battleb"):
                self._config.set_value(self._key, "battle_gap_s",
                                       float(self.sp_bgap.value()))
                self._config.set_value(self._key, "class_only",
                                       bool(self._toggle_state.get(
                                           "class_only", False)))
                self._config.set_value(self._key, "pos_only",
                                       bool(self._toggle_state.get(
                                           "pos_only", False)))
            if self._key == "wec26flag":
                for _k in ("show_flags", "show_penalties", "show_messages"):
                    self._config.set_value(
                        self._key, _k, bool(self._toggle_state.get(_k, True)))
            self._config.set_value(self._key, "preview",
                                   bool(self._toggle_state.get("preview",
                                                               False)))

    def _apply(self):
        """Aggiornamento live senza scrivere su disco."""
        self._write_to_config()
        self._overlay.reload_config()

    def _save(self):
        """Live + persiste su config.json."""
        self._write_to_config()
        self._config.save()
        self._overlay.reload_config()


_CFG_QSS = """
QDialog { background: transparent; }
#cfgBack { background: rgba(255,255,255,0.06); color: #cfd3da; border: none;
    border-radius: 9px; padding: 9px 18px; font-family: "Archivo SemiExpanded"; font-size: 15px; font-weight: bold; }
#cfgBack:hover { background: rgba(255,255,255,0.12); color: #fff; }
QLabel { color: #dfe3ea; font-family: "Archivo SemiExpanded"; font-size: 15px; }
#cfgTitle { color: #eef1f6; font-family: "Archivo SemiExpanded"; font-size: 20px; font-weight: bold; letter-spacing: 1px; }
#scaleValue { color: #fff; font-size: 17px; font-weight: bold; background: rgba(255,255,255,0.06); border-radius: 6px; padding: 4px 10px; }
#viewBtn { background: rgba(255,255,255,0.06); color: #b8bcc4; border: 1px solid rgba(255,255,255,0.10); border-radius: 8px; padding: 8px 18px; font-size: 14px; font-weight: bold; min-height: 20px; }
#viewBtn:hover { background: #34343a; color: #ccc; }
#switchBtn { background: rgba(255,255,255,0.08); color: #9aa0aa; border: none; border-radius: 13px; font-size: 12px; font-weight: bold; padding: 0 2px; text-align: center; min-height: 24px; }
#switchBtn:checked { background: #00a152; color: #fff; }
#switchBtn:hover { background: #3a3a40; }
#switchBtn:checked:hover { background: #00b85e; }
#viewBtn:checked { background: #00a152; color: #fff; border: 1px solid #00a152; }
#cfgSep { color: #333; max-height: 1px; }
#cfgSection { color: #8f97a3; font-size: 12px; font-weight: bold; letter-spacing: 1px; }
QSlider::groove:horizontal { height: 6px; background: rgba(255,255,255,0.12); border-radius: 3px; }
QSlider::handle:horizontal { background: #45b4ef; width: 16px; margin: -6px 0; border-radius: 8px; }
QSpinBox, QComboBox {
    background: rgba(255,255,255,0.06); color: #fff; border: 1px solid rgba(255,255,255,0.10);
    border-radius: 7px; padding: 6px 12px; font-size: 15px; min-height: 26px;
}
QSpinBox::up-button, QSpinBox::down-button { width: 22px; }
QLineEdit { background: rgba(255,255,255,0.06); color: #fff;
    border: 1px solid rgba(255,255,255,0.10); border-radius: 7px;
    padding: 6px 12px; font-size: 15px; min-height: 26px; }
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background: rgba(255,255,255,0.06); color: #fff; selection-background-color: #00e676;
    selection-color: #000;
}
QPushButton {
    background: rgba(255,255,255,0.06); color: #e6e9ef; border: none;
    border-radius: 8px; padding: 8px 16px; font-family: "Archivo SemiExpanded"; font-size: 15px;
    min-height: 22px;
}
QPushButton:hover { background: #34343a; color: #fff; }
QLabel { font-size: 11px; }
#btnApply { background: #1f6feb; color: #fff; border: none; }
#btnApply:hover { background: #388bfd; }
#btnSave { background: #00a152; color: #fff; border: none; }
#btnSave:hover { background: #00e676; color: #000; }
"""
