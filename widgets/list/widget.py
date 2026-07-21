"""
widgets/list/widget.py — Overlay lista dati (colonna destra HUD).

Voci: BODY, AERO, tabella ruote (TYRE/SUSP/BRAKE), FUEL, ENERGY, BATTERY,
E-MOTOR, OIL, WATER, ENGINE. Logica di popolamento 1:1 dall'HUD originale.
"""
import json
from pathlib import Path

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PySide6.QtCore import Qt, QTimer
from PySide6.QtSvgWidgets import QSvgWidget

from core.config import get_config
from core.icons import ICON
from core.utils import find_logo_path
from .reader import ListReader
from .components import DataRow, WheelTable
from .colors import (col_susp, col_tyre, col_tyre_temp, col_brake, col_brake_temp, col_energy, col_oil, col_damage,
                     col_water, col_emotor_temp, C_RED, C_YELLOW, C_GREEN,
                     C_WHITE)
from .style import load_qss

_ROOT = Path(__file__).parent.parent.parent
from core.paths import POSITIONS_FILE  # dati utente, fuori dall'app

C_FUCHSIA = "#ff2bd6"


def _crit(col):
    return col in (C_YELLOW.name(), "#ff9a30", "#b06bff", C_RED.name())


class ListOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LMU List")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("overlay")
        self._drag_pos = None
        self._user_enabled = True
        self._blink = False
        self._boost_peak = 0
        self._regen_peak = 0

        from core.shared_memory import SharedMemory
        self._mem = SharedMemory.instance()
        self._reader = ListReader()

        self._config = get_config()
        self.cfg = self._config.widget("list")

        self._build_ui()
        pos = self._load_position("list")
        self.move(pos[0], pos[1]) if pos else self.move(1100, 300)
        self._apply_qss()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update)
        self._timer.start(self.cfg.get("update_ms", 100))

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._container = QWidget()
        self._container.setObjectName("container")
        self._container.setAttribute(Qt.WA_StyledBackground, True)
        rl = QVBoxLayout(self._container)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        # ── HEADER: logo brand (sx) + nome auto (dx) ──
        self._header = QWidget()
        self._header.setObjectName("carHeader")
        self._header.setAttribute(Qt.WA_StyledBackground, True)
        hl = QHBoxLayout(self._header)
        hl.setContentsMargins(12, 5, 12, 5)
        hl.setSpacing(6)
        self._logo_h = 28
        self._logo_w = 80
        self._logo_svg = QSvgWidget()
        self._logo_svg.setStyleSheet("background: transparent; border: none;")
        self._logo_svg.setFixedHeight(self._logo_h)
        self._logo_svg.hide()
        self._car_name = QLabel("")
        self._car_name.setObjectName("carName")
        self._car_name.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hl.addWidget(self._logo_svg, 0)
        hl.addStretch(1)
        hl.addWidget(self._car_name, 0)
        rl.addWidget(self._header)
        self._cur_logo_brand = None
        self._logo_loaded = None

        self._rows = {}
        for key, label in [("body", "BODY"), ("aero", "AERO"),
                           ("stint", "STINT"), ("susp", "SUSP")]:
            r = DataRow(label, scale=self.cfg.scale); self._rows[key] = r; rl.addWidget(r)
            if not self.cfg.get(f"show_{key}", True):
                r.hide()
        for key, label in [("tyre", "TYRE WEAR"), ("tyretemp", "TYRE TEMP"),
                           ("brake", "BRAKE"),
                           ("fuel", "FUEL"), ("energy", "ENERGY"),
                           ("battery", "BATTERY"), ("emotor", "E-MOTOR"),
                           ("erpm", "E-RPM"),
                           ("etrqeng", "ENG-TRQ"),
                           ("oil", "OIL"), ("water", "WATER"), ("engine", "ENGINE")]:
            r = DataRow(label, scale=self.cfg.scale); self._rows[key] = r; rl.addWidget(r)
            # ogni riga disattivabile dalle impostazioni (default on)
            if not self.cfg.get(f"show_{key}", True):
                r.hide()

        outer.addWidget(self._container)
        self.adjustSize()

    def _apply_qss(self):
        self.setStyleSheet(load_qss(self.cfg))

    # ── REBUILD / ENABLE ──────────────────────────────────────────────
    def reload_config(self):
        pos = self.pos()
        self.cfg = self._config.widget("list")
        old = self.layout()
        QWidget().setLayout(old)
        self._build_ui()
        self._apply_qss()
        self.move(pos)
        self._timer.start(self.cfg.get("update_ms", 100))

    def set_enabled(self, enabled: bool):
        self._user_enabled = enabled
        if enabled:
            self._timer.start(self.cfg.get("update_ms", 100))
            if self._mem.is_on_track():
                super().show()
                self.raise_()
        else:
            self._timer.stop()
            super().hide()

    def open_config(self):
        from gui.config_window import ConfigWindow
        from PySide6.QtGui import QGuiApplication
        if getattr(self, "_cfg_win", None) is None:
            self._cfg_win = ConfigWindow(self._config, self, widget_key="list", title="List")
        self._cfg_win.show()
        self._cfg_win.adjustSize()
        screen = QGuiApplication.screenAt(self.pos()) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        w = self._cfg_win.width(); h = self._cfg_win.height()
        x = self.x() + self.width() + 12; y = self.y()
        if x + w > geo.right():
            x = self.x() - w - 12
        if x < geo.left() or x + w > geo.right():
            x = geo.left() + (geo.width() - w) // 2
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
            self._save_position("list")
        self._drag_pos = None

    # ── UPDATE (logica 1:1 dall'HUD originale) ────────────────────────
    def _update_header(self, d):
        # nome auto a destra
        name = d.get("car_name", "") or ""
        self._car_name.setText(name)
        # logo brand a sinistra (SVG vettoriale nitido, ricarica solo se cambia)
        brand = d.get("brand", "") or ""
        if brand != self._cur_logo_brand:
            self._cur_logo_brand = brand
            svg = find_logo_path(brand) if brand else None
            if svg:
                if self._logo_loaded != str(svg):
                    self._logo_svg.load(str(svg))
                    self._logo_loaded = str(svg)
                # dimensiona mantenendo le proporzioni, altezza fissa
                r = self._logo_svg.renderer()
                sz = r.defaultSize() if r else None
                if sz and sz.width() > 0 and sz.height() > 0:
                    w = max(4, int(self._logo_h * sz.width() / sz.height()))
                else:
                    w = self._logo_w
                self._logo_svg.setFixedWidth(min(w, self._logo_w * 2))
                self._logo_svg.show()
            else:
                self._logo_svg.hide()

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

        d = self._reader.read()
        if not d:
            return

        # HEADER: logo brand + nome auto
        self._update_header(d)

        # Componenti elettrici (BATTERY, E-MOTOR, E-RPM) solo su ibride (Hypercar)
        is_hybrid = int(d.get("emotor_state", 0) or 0) > 0
        if is_hybrid != getattr(self, "_was_hybrid", None):
            self._was_hybrid = is_hybrid
            for ek in ("battery", "emotor", "erpm"):
                r = self._rows.get(ek)
                if r is not None:
                    if is_hybrid and self.cfg.get(f"show_{ek}", True):
                        r.show()
                    else:
                        r.hide()
            # ricalcola l'altezza del contenitore (accorcia se righe nascoste)
            self._container.adjustSize()
            self.adjustSize()

        # BODY
        dent = d.get("body_dent", None)
        if dent is not None:
            tot = sum(min(x, 3) for x in dent)
            integ = int(round((1 - tot / 24) * 100))
            if integ >= 100:
                c = C_WHITE.name()      # integro = bianco
            else:
                c = col_damage(integ).name()
            self._rows["body"].set_colored(f"{integ}%", c, c, _crit(c))
        else:
            self._rows["body"].set_value("—", "normal")

        # AERO — integrità aerodinamica reale (wearables.body.aero = DANNO)
        # body.aero è la frazione di DANNO (0 = integro). Può superare 1.0 quando
        # una parte si stacca (es. alettone perso ~1.97) = danno totale.
        # Integrità = (1 - danno) clampato a 0-100.
        aero = d.get("aero", None)
        if aero is not None:
            dmg = max(0.0, min(1.0, aero))   # clamp: >=1.0 = distrutto
            integ = int(round((1.0 - dmg) * 100))
            c = col_damage(integ).name() if integ < 100 else C_WHITE.name()
            self._rows["aero"].set_colored(f"{integ}%", c, c, _crit(c))
        else:
            self._rows["aero"].set_value("—", "normal")

        # STINT — numero stint · LAP corrente/giro di fine carico (dal consumo
        # per giro del pit-menu, benzina o energia a seconda del vincolo)
        ld = d.get("laps_done")
        if ld is not None:
            n = int(d.get("num_pit") or 0) + 1
            lap_now = int(ld) + 1
            per_lap = d.get("strat_per_lap")
            cur = d.get("fuel") if d.get("strat_constraint") == "FUEL" \
                else (d.get("energy") if d.get("energy_kind") == "ve" else None)
            # stima MISURATA (ingegnere) se disponibile; fallback pit-menu (max)
            rem = d.get("laps_left_live")
            if rem is None and per_lap and per_lap > 0 \
                    and cur is not None and cur >= 0:
                rem = float(cur) / float(per_lap)
            if rem is not None:
                self._rows["stint"].set_value(
                    "%d · LAP %d/%.1f" % (n, lap_now, rem), "normal")
            else:
                self._rows["stint"].set_value(
                    "%d · LAP %d" % (n, lap_now), "normal")
        else:
            self._rows["stint"].set_value("—", "normal")

        # SUSP — media integrità sospensioni
        su = d.get("susp", None)
        if su:
            vals = [int(round((1 - x) * 100)) for x in su]
            avg = int(round(sum(vals) / len(vals)))
            c = col_susp(avg).name()
            self._rows["susp"].set_colored(f"{avg}%", c, c, _crit(c))

        # BRAKE — temperatura 4 freni (°C), ognuno col suo colore
        bt = d.get("brake_temp", None)
        if bt:
            cc = d.get("car_class", "")
            parts = []
            crit = False
            worst_v = None
            for x in bt:
                v = int(round(x))
                c = col_brake_temp(v, cc).name()
                if _crit(c):
                    crit = True
                if worst_v is None or v > worst_v:
                    worst_v = v
                parts.append(f'<span style="color:{c}">{v}</span>')
            dot_c = col_brake_temp(worst_v, cc).name() if worst_v is not None else None
            self._rows["brake"].set_html("&#8201;".join(parts), dot_c, crit)

        # TYRE — usura 4 gomme, ognuna col suo colore
        ti = d.get("tires", None)
        if ti:
            flat = d.get("tyre_flat", [False] * 4)
            parts = []
            crit = False
            worst_v = None
            for i, x in enumerate(ti):
                v = 0 if (i < len(flat) and flat[i]) else int(round(x * 100))
                c = col_tyre(v).name()
                if _crit(c):
                    crit = True
                if worst_v is None or v < worst_v:   # usura: più basso = peggiore
                    worst_v = v
                parts.append(f'<span style="color:{c}">{v}</span>')
            dot_c = col_tyre(worst_v).name() if worst_v is not None else None
            self._rows["tyre"].set_html("&#8201;".join(parts), dot_c, crit)

        # TYRE TEMP — temperatura carcassa 4 gomme (°C), ognuna col suo colore
        tc = d.get("tyre_carcass", None)
        if tc:
            cc = d.get("car_class", "")
            parts = []
            crit = False
            worst_v = None
            for x in tc:
                v = int(round(x))
                c = col_tyre_temp(v, cc).name()
                if _crit(c):
                    crit = True
                if worst_v is None or v > worst_v:
                    worst_v = v
                parts.append(f'<span style="color:{c}">{v}</span>')
            dot_c = col_tyre_temp(worst_v, cc).name() if worst_v is not None else None
            self._rows["tyretemp"].set_html("&#8201;".join(parts), dot_c, crit)

        # FUEL
        fuel = d.get("fuel", None)
        if fuel is not None and fuel >= 0:
            self._rows["fuel"].set_value(f"{fuel:.1f}L", "normal", "#ff9ed8")

        # ENERGY
        energy = d.get("energy", None)
        if energy is not None:
            c = col_energy(int(energy)).name()
            self._rows["energy"].set_colored(f"{energy:.1f}%", c, "#4a90e2", _crit(c))
        else:
            self._rows["energy"].set_value("N/A", "normal", "#4a90e2")

        # BATTERY / E-MOTOR (regen kW e boost Nm integrati qui)
        # mElectricBoostMotorState: 0=n/d, 1=inattivo, 2=propulsion(BOOST), 3=regen
        em_state = d.get("emotor_state", 0)
        batt = d.get("battery", None)
        if em_state and em_state > 0:
            bpct = int(round(batt * 100)) if batt is not None else 0
            etemp = d.get("emotor_temp", 0)
            regen = d.get("regen_kw", None)
            etrq = d.get("emotor_torque", None)
            if em_state == 2:
                # BOOST vero: il motore elettrico eroga coppia (propulsion)
                sc = C_FUCHSIA
                _nm = abs(etrq) if etrq is not None else 0
                if _nm >= 10:
                    self._rows["emotor"].set_html(
                        f'<span style="color:{sc}">BOOST</span> '
                        f'<span style="color:#ffffff">{_nm:.0f}Nm</span>',
                        sc)
                else:
                    self._rows["emotor"].set_colored("BOOST", sc, sc)
                self._rows["battery"].set_colored(f"{bpct}%", sc, sc)
            elif em_state == 3:
                # REGEN vero: recupero energia (regeneration)
                gc = C_GREEN.name()
                _kw = abs(regen) if regen is not None else 0
                self._blink = not self._blink
                dot = gc if self._blink else "#0c3a1c"   # verde acceso / spento
                if _kw >= 5:
                    self._rows["emotor"].set_html(
                        f'<span style="color:{gc}">REGEN</span> '
                        f'<span style="color:#ffffff">{_kw:.0f}kW</span>',
                        dot)
                else:
                    self._rows["emotor"].set_colored("REGEN", gc, dot)
                self._rows["battery"].set_colored(f"{bpct}%", gc, gc)
            else:
                ec = col_emotor_temp(etemp).name()
                self._rows["emotor"].set_colored(f"{etemp:.0f}°", ec, ec)
                self._rows["battery"].set_colored(f"{bpct}%", C_WHITE.name(), "#4a90e2")
                self._boost_peak = 0
                self._regen_peak = 0
        else:
            self._rows["battery"].set_value("N/A", "normal", "#4a90e2")
            self._rows["emotor"].set_value("N/A", "normal")

        # E-RPM
        erpm = d.get("emotor_rpm", None)
        if erpm is not None and em_state and em_state > 0 and erpm > 0:
            self._rows["erpm"].set_value(f"{erpm:.0f}", "normal")
        else:
            self._rows["erpm"].set_value("N/A", "normal")

        # ENG-TRQ (torque motore termico)
        engtrq = d.get("engine_torque", None)
        if engtrq is not None:
            self._rows["etrqeng"].set_value(f"{engtrq:.0f} Nm", "normal")
        else:
            self._rows["etrqeng"].set_value("N/A", "normal")

        # OIL
        oil = d.get("oil_temp", None)
        if oil is not None:
            oc = col_oil(oil).name()
            self._rows["oil"].set_colored(f"{oil:.0f}°", oc, oc, oc == C_RED.name())

        # WATER
        water = d.get("water_temp", None)
        if water is not None:
            wc = col_water(water).name()
            self._rows["water"].set_colored(f"{water:.0f}°", wc, wc, wc == C_RED.name())

        # ENGINE
        overheat = d.get("overheating", False)
        rpm = d.get("rpm", None)
        if rpm is not None:
            if overheat:
                self._rows["engine"].set_colored("OVERHEAT", C_RED.name(), C_RED.name(), True)
            elif rpm < 50:
                self._rows["engine"].set_colored("OFF", C_RED.name(), C_RED.name(), True)
            elif (oil and oil >= 125) or (water and water >= 110):
                self._rows["engine"].set_colored("HOT", C_YELLOW.name(), C_YELLOW.name())
            else:
                self._rows["engine"].set_colored("ON", C_GREEN.name(), C_GREEN.name())
        else:
            self._rows["engine"].set_value("—", "normal")

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
        self._save_position("list")
        self._reader.stop()
        super().closeEvent(e)
