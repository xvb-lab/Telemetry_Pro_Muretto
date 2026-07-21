"""
widgets/standings/driver_row.py — Singola riga pilota.

Tutte le dimensioni (altezza riga, larghezze colonne, logo) derivano dal
config scalato: cfg.scaled(...). Cambiando lo scale, la riga si ridimensiona.
"""
from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout, QGraphicsOpacityEffect
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QSvgWidget

from core.utils import fmt_time, fmt_gap, find_logo_path
from .reader import get_status


def _short3(name):
    """'J Sanfilippo' -> 'SAN': tre lettere del cognome, stile TV."""
    import re
    parts = [p for p in re.split(r"[^A-Za-zÀ-ɏ]+", name or "")
             if len(p) > 1]
    base = parts[-1] if parts else (name or "")
    return base[:3].upper()


class DriverRow(QWidget):
    def paintEvent(self, e):
        # tinta BRAND fino al nome + navy pannello sulle colonne dopo
        try:
            from core.wec_style import (row_gradient as brand_gradient,
                                        brand_color, ROW_BG)
            from PySide6.QtGui import (QPainter, QLinearGradient,
                                       QColor)
            # nomi corti: colore accorciato, muore subito dopo le lettere
            if self.cfg.get("short_names", False):
                x1 = self.lbl_name.geometry().right() + 6
            else:
                x1 = self.lbl_name.geometry().right() + 8
            p = QPainter(self)
            # navy pannello SOLO sulla riga del player
            if str(self.property("player")).lower() == "true" \
                    and 0 < x1 < self.width():
                p.fillRect(int(x1), 0, self.width() - int(x1),
                           self.height(), QColor(ROW_BG))
            b = getattr(self, "_row_brand", "")
            tri = brand_gradient(b) if b else None
            base = brand_color(b) if b else ""
            if tri or base:
                # dalla colonna LOGO (pos e classe restano puliti)
                x0 = min(self.lbl_logo.geometry().left(),
                         self.lbl_name.geometry().left()) - 2
                g = QLinearGradient(float(x0), 0.0, float(x1), 0.0)
                if tri:
                    g.setColorAt(0.0, QColor(tri[0]))
                    g.setColorAt(1.0, QColor(tri[1]))
                else:
                    g.setColorAt(0.0, QColor(base))
                    g.setColorAt(1.0, QColor(base))
                p.fillRect(int(x0), 0, int(x1 - x0),
                           self.height(), g)
                # NIENTE strisce/angoli sulle righe overlay: le strisce
                # vivono solo sulle card dell'app
                # strisce oblique livrea nell'angolo destro (per team)
                from core.wec_style import row_stripes
                _sts = row_stripes(b)
                if _sts:
                    from PySide6.QtGui import QPolygonF
                    from PySide6.QtCore import QPointF
                    p.setRenderHint(QPainter.Antialiasing, True)
                    _h = float(self.height())
                    _sw, _gp, _sl = 7.0, 5.0, 9.0
                    _xr = float(x1) - 3.0
                    _n = len(_sts)
                    for _ci, _cc in enumerate(_sts):
                        _xa = _xr - (_n - _ci) * (_sw + _gp) + _gp
                        p.setBrush(QColor(_cc))
                        p.drawPolygon(QPolygonF([
                            QPointF(_xa + _sl, 0.0),
                            QPointF(_xa + _sl + _sw, 0.0),
                            QPointF(_xa + _sw, _h),
                            QPointF(_xa, _h)]))
            p.end()
        except Exception:
            pass
        super().paintEvent(e)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.setFixedHeight(cfg.scaled("row_height", 30))
        self.setObjectName("driverRow")
        self.setAttribute(Qt.WA_StyledBackground, True)

        lay = QHBoxLayout(self)
        ph = cfg.scaled("row_padding_h", 4)
        lay.setContentsMargins(ph, 0, ph, 0)
        lay.setSpacing(cfg.scaled("row_col_spacing", 5))

        def lbl(obj, w=None, align=Qt.AlignLeft | Qt.AlignVCenter):
            l = QLabel()
            l.setObjectName(obj)
            if w:
                l.setFixedWidth(w)
            l.setAlignment(align)
            return l

        logo_w = cfg.scaled("logo_width", 30)
        logo_h = cfg.scaled("logo_height", 22)

        self.lbl_status = lbl("status_col", cfg.scaled("col_status", 50), Qt.AlignCenter)
        self.lbl_class = lbl("class_col", cfg.scaled("col_class", 34), Qt.AlignCenter)
        self.lbl_pos = lbl("pos", cfg.scaled("col_pos", 30), Qt.AlignCenter)
        # ± POSIZIONI (stile TinyPedal): guadagnate/perse dal via della gara
        self.lbl_pdelta = lbl("pdelta", cfg.scaled("col_pdelta", 30), Qt.AlignCenter)

        self._logo_container = QWidget()
        self._logo_container.setObjectName("logo")
        self._logo_container.setFixedSize(logo_w, logo_h)
        self._logo_container.setAttribute(Qt.WA_StyledBackground, True)
        self._logo_svg = QSvgWidget(self._logo_container)
        self._logo_svg.setStyleSheet("background: transparent; border: none;")
        self._logo_svg.hide()
        self._logo_loaded = None
        self.lbl_logo = self._logo_container

        if cfg.get("short_names", False):
            _name_w = cfg.scaled("col_name_short", 96)
        else:
            _name_w = cfg.scaled("col_name", 160)
        self.lbl_name = lbl("name", _name_w)
        self.lbl_gap = lbl("gap", cfg.scaled("col_gap", 80), Qt.AlignCenter)
        self.lbl_speed = lbl("speed", cfg.scaled("col_speed", 55), Qt.AlignCenter)
        self.lbl_best = lbl("best_lap", cfg.scaled("col_best", 82), Qt.AlignCenter)
        self.lbl_lap = lbl("lap", cfg.scaled("col_lap", 82), Qt.AlignCenter)
        self.lbl_energy = lbl("energy", cfg.scaled("col_energy", 50), Qt.AlignCenter)
        self.lbl_tl = lbl("tl", cfg.scaled("col_tl", 32), Qt.AlignCenter)
        self.lbl_pit = lbl("pit", cfg.scaled("col_pit", 30), Qt.AlignCenter)
        self.lbl_laps = lbl("laps", cfg.scaled("col_laps", 34), Qt.AlignCenter)
        self.lbl_stint = lbl("stint", cfg.scaled("col_stint", 48), Qt.AlignCenter)
        self.lbl_wear = lbl("wear", cfg.scaled("col_wear", 42), Qt.AlignCenter)
        # settori: 3 quadratini in un mini-widget
        self.w_sectors = QWidget()
        self.w_sectors.setObjectName("sectorsBox")
        self.w_sectors.setFixedWidth(cfg.scaled("col_sectors", 42))
        _sl = QHBoxLayout(self.w_sectors)
        _sl.setContentsMargins(0, 0, 0, 0)
        _sl.setSpacing(2)
        self.sec_boxes = []
        self._sec_anim = {}      # {indice box: (effect, animation)} per il fade del settore corrente
        self._fade_eff = {}      # {label: QGraphicsOpacityEffect} fade morbido al cambio valore
        self._fade_anim = {}     # {label: QPropertyAnimation}
        self._gap_val = None     # gap mostrato (smussato) per evitare scatti
        _secsz = cfg.scaled("sec_box_size", 10)
        for _ in range(3):
            b = QLabel()
            b.setObjectName("secBox")
            b.setFixedSize(_secsz, _secsz)
            self.sec_boxes.append(b)
            _sl.addWidget(b)
        _sl.addStretch()
        # cella STATUS: badge + quadratini settore nello stesso posto
        # (i settori sono il "riposo": qualsiasi status li rimpiazza)
        self._status_cell = QWidget()
        self._status_cell.setObjectName("statusCell")
        self._status_cell.setFixedWidth(cfg.scaled("col_status", 50))
        _scl = QHBoxLayout(self._status_cell)
        _scl.setContentsMargins(0, 0, 0, 0)
        _scl.setSpacing(0)
        _scl.addWidget(self.lbl_status, 0, Qt.AlignCenter)
        _scl.addWidget(self.w_sectors, 0, Qt.AlignCenter)
        self.w_sectors.hide()
        from core.tyre_cell import TyreCell
        self.lbl_tyre = TyreCell(size=cfg.get("base", {}).get("col_tyre", 24), scale=cfg.scale)
        # flash L<giri totali> sul compound al taglio del traguardo
        self.lbl_tyre_fl = QLabel(self.lbl_tyre)
        self.lbl_tyre_fl.setObjectName("tyreLaps")
        self.lbl_tyre_fl.setAlignment(Qt.AlignCenter)
        self.lbl_tyre_fl.setStyleSheet(
            "font-size:%dpx;font-weight:bold;color:#ffffff;"
            "background:transparent;" % max(10, cfg.scaled("tyre_laps_font", 18)))
        self.lbl_tyre_fl.hide()

        self._col = {
            "status": self._status_cell, "class": self.lbl_class, "pos": self.lbl_pos, "logo": self.lbl_logo,
            "pdelta": self.lbl_pdelta,
            "name": self.lbl_name, "speed": self.lbl_speed, "gap": self.lbl_gap, "best": self.lbl_best,
            "lap": self.lbl_lap, "energy": self.lbl_energy, "tyre": self.lbl_tyre,
            "tl": self.lbl_tl,
            "pit": self.lbl_pit,
            "laps": self.lbl_laps,
            "stint": self.lbl_stint,
            "wear": self.lbl_wear,
        }

        left_cols = {"status", "class", "pos", "logo", "name"}
        order = cfg.get("column_order", ["class", "pos", "logo", "name", "speed", "gap", "best", "lap", "tyre", "energy", "status"])
        # config utente salvate PRIMA della colonna: la infilo dopo "pos"
        if "pdelta" not in order:
            order = list(order); order.insert(order.index("gap") if "gap" in order else len(order), "pdelta")
        stretch_added = False
        for c in order:
            w = self._col.get(c)
            if w is None:
                continue
            if c not in left_cols and not stretch_added:
                lay.addStretch()
                stretch_added = True
            lay.addWidget(w)
        if not stretch_added:
            lay.addStretch()

        self._logo_sizes = cfg.get("logo_sizes", {})
        # lookup CASE-INSENSITIVE: 'ginetta' vs 'Ginetta', 'ADESS' vs 'Adess',
        # 'Mclaren' vs 'McLaren' — una maiuscola diversa mandava il logo in
        # fit auto in silenzio, con l'arte larga stirata nella scatola.
        self._logo_sizes_ci = {str(k).lower(): v
                               for k, v in self._logo_sizes.items()}
        self._logo_w = logo_w
        self._logo_h = logo_h

        if not cfg.get("show_class", False):
            self.lbl_class.hide()
            self.lbl_class.setFixedWidth(0)
        # posizione stile onboard: P18 in Archivo corsivo
        self.lbl_pos.setStyleSheet(
            "font-family:'Druk Wide', 'Archivo SemiExpanded';font-style:italic;"
            "font-weight:900;background:transparent;")
        if not cfg.get("show_pos_delta", True):
            self.lbl_pdelta.hide()
            self.lbl_pdelta.setFixedWidth(0)
        if not cfg.get("show_best_lap", True):
            self.lbl_best.hide()
            self.lbl_best.setFixedWidth(0)
        if not cfg.get("show_speed", True):
            self.lbl_speed.hide()
            self.lbl_speed.setFixedWidth(0)
        if not cfg.get("show_track_limits", True):
            self.lbl_tl.hide()
            self.lbl_tl.setFixedWidth(0)
        if not cfg.get("show_pit", True):
            self.lbl_pit.hide()
            self.lbl_pit.setFixedWidth(0)
        if not cfg.get("show_laps", True):
            self.lbl_laps.hide()
            self.lbl_laps.setFixedWidth(0)
        if not cfg.get("show_stint", True):
            self.lbl_stint.hide()
            self.lbl_stint.setFixedWidth(0)
        if not cfg.get("show_wear", True):
            self.lbl_wear.hide()
            self.lbl_wear.setFixedWidth(0)
        if not cfg.get("show_gap", True):
            self.lbl_gap.hide()
            self.lbl_gap.setFixedWidth(0)
        if not cfg.get("show_lap", True):
            self.lbl_lap.hide()
            self.lbl_lap.setFixedWidth(0)
        if not cfg.get("show_tyre", True):
            self.lbl_tyre.hide()
            self.lbl_tyre.setFixedWidth(0)
        if not cfg.get("show_energy", True):
            self.lbl_energy.hide()
            self.lbl_energy.setFixedWidth(0)
        if not cfg.get("show_status", True):
            self.lbl_status.hide()
            self.lbl_status.setFixedWidth(0)

        thr = cfg.get("energy_thresholds", {})
        self._e_low = thr.get("low", 25)
        self._e_crit = thr.get("critical", 10)

    def _smooth_gap(self, target, alpha=0.35):
        """Avvicina il gap mostrato al target (ease) per un movimento fluido.
        Salti grandi (cambio riferimento/reset) agganciano subito."""
        if target is None:
            self._gap_val = None
            return None
        if self._gap_val is None or abs(target - self._gap_val) > 5.0:
            self._gap_val = float(target)
        else:
            self._gap_val += (target - self._gap_val) * alpha
        return self._gap_val

    def _soft_set(self, lbl, text):
        """setText con fade morbido (opacità 0.35->1.0) solo quando il valore
        cambia: i dati a gradini transitano fluidi come il gap."""
        if lbl.text() == text:
            return
        lbl.setText(text)
        anim = self._fade_anim.get(lbl)
        if anim is None:
            eff = QGraphicsOpacityEffect(lbl)
            lbl.setGraphicsEffect(eff)
            anim = QPropertyAnimation(eff, b"opacity")
            anim.setDuration(240)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            self._fade_eff[lbl] = eff
            self._fade_anim[lbl] = anim
        anim.stop()
        anim.setStartValue(0.35)
        anim.setEndValue(1.0)
        anim.start()

    def _repol(self, w):
        w.style().unpolish(w)
        w.style().polish(w)

    def update_data(self, d):
        self.setProperty("player", "true" if d["is_player"] else "false")
        self.setProperty("car_class", d.get("car_class", ""))
        self._repol(self)

        self._soft_set(self.lbl_pos, "P%s" % d["place_class"])
        # ± posizioni dal via: verde guadagno, rosso perdita, grigio pari
        _pd = d.get("pos_delta")
        if _pd is None:
            self._soft_set(self.lbl_pdelta, "")
        else:
            if _pd > 0:
                _pt, _pc = "\u25b2%d" % _pd, "#37d67a"
            elif _pd < 0:
                _pt, _pc = "\u25bc%d" % (-_pd), "#ff5a5a"
            else:
                _pt, _pc = "\u2013", "#6e727b"
            self._soft_set(self.lbl_pdelta, _pt)
            self.lbl_pdelta.setStyleSheet(
                "color:%s;font-weight:800;background:transparent;" % _pc)
        self.lbl_pos.setProperty("car_class", d.get("car_class", ""))
        self._repol(self.lbl_pos)

        from core.classes import class_tag
        tag = class_tag(d.get("car_class", ""))
        self.lbl_class.setText(tag)
        self.lbl_class.setProperty("cls", tag)
        self._repol(self.lbl_class)

        _nm = d["name"]
        _short = self.cfg.get("short_names", False)
        if _short:
            _nm = _short3(_nm)
        _num = str(d.get("car_number") or "").strip()
        if _num and _short:
            # slot numero a 3 cifre (figure space): lettere allineate
            _num = "&#8199;" * max(0, 3 - len(_num)) + _num
        if _num:
            # numero gara PRIMA del nome, font onboard (Archivo italic)
            self.lbl_name.setTextFormat(Qt.RichText)
            self.lbl_name.setText(
                "<span style=\"font-family:'Druk Wide', 'Archivo SemiExpanded';"
                "font-style:italic;font-weight:900;\">%s</span>"
                "&nbsp; %s" % (_num, _nm))
        else:
            self.lbl_name.setText(_nm)
        # brand per la tinta card (paintEvent) + testo leggibile
        self._row_brand = d.get("brand") or ""
        try:
            from core.wec_style import brand_color, text_on
            # in modalita' corta il padding-right del tema (16px)
            # mangerebbe la terza lettera: dentro lo slot niente padding
            _pad = "padding-right:0px;" if _short else ""
            if brand_color(self._row_brand):
                self.lbl_name.setStyleSheet(
                    "background:transparent;color:%s;%s"
                    % (text_on(self._row_brand), _pad))
            else:
                self.lbl_name.setStyleSheet(_pad)
        except Exception:
            pass

        # logo SVG
        brand = d.get("brand", "") or ""
        # loghi CARD (cardlogo/) con ripiego su brandlogo/
        try:
            from core.wec_style import card_logo_path
            svg_path = card_logo_path(brand)
        except Exception:
            svg_path = find_logo_path(brand)
        if svg_path:
            _msz = self._logo_sizes_ci.get(str(brand).lower())
            if _msz:
                sw, sh = _msz
                # scala anche i logo_sizes manuali
                ratio = self.cfg.scale
                sw, sh = round(sw * ratio), round(sh * ratio)
            else:
                r = QSvgRenderer(str(svg_path))
                sz = r.defaultSize()
                if sz.width() > 0 and sz.height() > 0:
                    rt = sz.width() / sz.height()
                    if rt >= 1:
                        sw = self._logo_w
                        sh = max(4, int(sw / rt))
                    else:
                        sh = self._logo_h
                        sw = max(4, int(sh * rt))
                else:
                    sw, sh = self._logo_w, self._logo_h
            sx = (self._logo_w - sw) // 2
            sy = (self._logo_h - sh) // 2
            self._logo_svg.setGeometry(sx, sy, sw, sh)
            if self._logo_loaded != str(svg_path):
                self._logo_svg.load(str(svg_path))
                self._logo_loaded = str(svg_path)
            self._logo_svg.show()
        else:
            self._logo_svg.hide()

        status = get_status(d)
        self._soft_set(self.lbl_status, status)
        self.lbl_status.setProperty("status", status if status else "none")
        self._repol(self.lbl_status)
        # settori nella cella status a priorita' MINIMA:
        # qualsiasi badge (PEN/DT/PIT/GAR/S1...) li rimpiazza
        if status:
            self.w_sectors.hide()
            self.lbl_status.show()
        else:
            self.lbl_status.hide()
            self.w_sectors.show()

        # LAST LAP nel GAP per 10s al taglio del traguardo (per auto:
        # se la riga cambia macchina il flash non si trascina dietro)
        import time as _ft
        _cid = str(d.get("car_number") or d.get("name") or "")
        _ld = int(d.get("laps_done", 0) or 0)
        if getattr(self, "_fl_cid", None) != _cid or \
                _ld < getattr(self, "_fl_laps", 0):
            self._fl_cid = _cid
            self._fl_laps = _ld
            self._fl_until = 0.0
            self._ty_until = 0.0
        elif _ld > self._fl_laps:
            self._fl_laps = _ld
            # sul compound: L<giri totali> per 5s (OGNI taglio conta)
            self._ty_until = _ft.time() + 5.0
            self._ty_laps = _ld
            if (d.get("last_lap", 0) or 0) > 0 and \
                    d.get("last_state", "") != "invalid" and \
                    not d.get("outlap"):
                self._fl_until = _ft.time() + 10.0
                # VERDE se migliora il proprio best, GIALLO se no
                _bst = d.get("best_lap", 0) or 0
                self._fl_css = (
                    "color:#27d962;background:transparent;"
                    if _bst > 0 and d["last_lap"] <= _bst + 0.001
                    else "color:#ffd12b;background:transparent;")

        _gap_css = ""
        _gmode = d.get("gap_mode", "leader")
        _gval = d.get("gap_display")
        if _gmode == "self":
            self._gap_val = 0.0
            self.lbl_gap.setText("0.0")
        elif _gmode == "rel":
            sm = self._smooth_gap(_gval)
            self.lbl_gap.setText("--" if sm is None else f"{sm:+.1f}")
        elif _gmode == "best":
            # niente smussatore in P\Q: e' cronometraggio, non un gap
            # che oscilla — al millesimo si mostra il valore VERO
            sm = _gval
            if sm is None:
                self.lbl_gap.setText("--")
            elif sm <= 0:
                # P1 in prova/qualifica: il SUO best, stile torre TV
                _bst = d.get("best_lap", 0)
                self.lbl_gap.setText(
                    fmt_time(_bst) if _bst and _bst > 0 else "--")
                _gap_css = "color:#ff33cc;background:transparent;"
            else:
                # P\Q: distacchi al millesimo, come il cronometraggio
                self.lbl_gap.setText(f"+{sm:.3f}")
        else:
            # leader: smussa solo i secondi (non i distacchi a giri)
            lb = d.get("laps_behind", 0)
            if lb and lb > 0:
                self._gap_val = None
                self.lbl_gap.setText(fmt_gap(d.get("gap_leader", 0), d["place_class"], lb))
            else:
                sm = self._smooth_gap(d.get("gap_leader", 0))
                self.lbl_gap.setText(fmt_gap(sm if sm is not None else 0, d["place_class"], 0))
        _flash = getattr(self, "_fl_until", 0.0) > _ft.time()
        if _flash:
            self.lbl_gap.setText(fmt_time(d["last_lap"]))
            # last: VERDE migliorato / GIALLO no
            _gap_css = getattr(self, "_fl_css", "")
        if _gap_css != getattr(self, "_gap_css", None):
            self._gap_css = _gap_css
            self.lbl_gap.setStyleSheet(_gap_css)
        self.lbl_gap.setProperty("leader", "true" if d["place_class"] == 1 else "false")
        self.lbl_gap.setProperty("lapflash", "true" if _flash else "false")
        self._repol(self.lbl_gap)

        last_state = d.get("last_state", "")
        if d.get("outlap"):
            self._soft_set(self.lbl_lap, "OUT")
            last_state = "outlap"
        elif last_state == "invalid":
            self._soft_set(self.lbl_lap, "Invalid")
        else:
            self._soft_set(self.lbl_lap, fmt_time(d["last_lap"]))
        self.lbl_lap.setProperty("fastest", "true" if d.get("is_fastest_last") else "false")
        self.lbl_lap.setProperty("laptime", last_state)
        self._repol(self.lbl_lap)

        if self.cfg.get("show_best_lap", True):
            best = d.get("best_lap", 0)
            self._soft_set(self.lbl_best, fmt_time(best) if best > 0 else "--:--.---")
            self.lbl_best.setProperty("overall", "true" if d.get("is_overall_best") else "false")
            self._repol(self.lbl_best)

        if self.cfg.get("show_speed", True):
            spd = d.get("speed_kmh", 0)
            self.lbl_speed.setText(f"{int(spd)}" if spd > 0 else "")
            self.lbl_speed.setProperty("topspeed", "true" if d.get("is_top_speed") else "false")
            self._repol(self.lbl_speed)

        v_e = d.get("v_energy")
        if v_e is not None:
            if v_e < self._e_crit:
                self._soft_set(self.lbl_energy, f"{v_e:.1f}%")   # decimali solo se critica
                lvl = "critical"
            elif v_e < self._e_low:
                self._soft_set(self.lbl_energy, f"{round(v_e)}%")
                lvl = "low"
            else:
                self._soft_set(self.lbl_energy, f"{round(v_e)}%")
                lvl = "high"
        else:
            self._soft_set(self.lbl_energy, "—")
            lvl = "na"
        self.lbl_energy.setProperty("energy_level", lvl)
        self._repol(self.lbl_energy)

        # track limits
        tl = d.get("track_limits")
        if tl and tl.get("per_point", 0) > 0:
            steps = tl.get("steps", 0)
            per_pen = tl.get("per_penalty", 12)
            per_pt = tl.get("per_point", 4)
            count = steps // per_pt           # track limit "pieni"
            max_count = per_pen // per_pt if per_pt else 3   # quanti prima della penalità
            self._soft_set(self.lbl_tl, f"{count}/{max_count}")
            ratio = steps / per_pen if per_pen else 0
            if ratio >= 0.99:
                tl_lvl = "penalty"
            elif ratio >= 0.66:
                tl_lvl = "high"
            elif ratio >= 0.33:
                tl_lvl = "mid"
            elif steps > 0:
                tl_lvl = "low"
            else:
                tl_lvl = "none"
            self.lbl_tl.setProperty("tl_level", tl_lvl)
        else:
            self._soft_set(self.lbl_tl, "0/3")
            self.lbl_tl.setProperty("tl_level", "none")
        self._repol(self.lbl_tl)

        # numero pit
        np = d.get("num_pit", 0)
        self._soft_set(self.lbl_pit, str(np) if np > 0 else "0")
        self._soft_set(self.lbl_laps, str(d.get("laps_done", 0)))
        _st = d.get("stint_time", None)
        if _st is None:
            self._soft_set(self.lbl_stint, "—")
        elif _st < 60:
            self._soft_set(self.lbl_stint, f"{int(_st)}s")
        else:
            _st = int(_st)
            _h, _m = _st // 3600, (_st % 3600) // 60
            self._soft_set(self.lbl_stint, f"{_h}h{_m}m" if _h > 0 else f"{_m}m")

        # usura gomme (reale, per tutti)
        tw = d.get("tyre_wear")
        if tw is not None:
            self._soft_set(self.lbl_wear, f"{int(tw)}%")
            if tw >= 70:
                wlvl = "fresh"
            elif tw >= 40:
                wlvl = "mid"
            elif tw >= 20:
                wlvl = "low"
            else:
                wlvl = "worn"
            self.lbl_wear.setProperty("wear_level", wlvl)
        else:
            self._soft_set(self.lbl_wear, "—")
            self.lbl_wear.setProperty("wear_level", "na")
        self._repol(self.lbl_wear)

        # settori (3 quadratini colorati). Il settore CORRENTE lampeggia fade grigio.
        states = d.get("sector_states", ["", "", ""])
        for bi, b in enumerate(self.sec_boxes):
            st = states[bi] if bi < len(states) else ""
            b.setProperty("secstate", st or "none")
            b.style().unpolish(b)
            b.style().polish(b)
            if st == "current":
                self._start_sec_pulse(bi, b)
            else:
                self._stop_sec_pulse(bi, b)

        tyre = d.get("tyre", "")
        self.lbl_tyre.set_tyre(tyre, d.get("tyre4"))
        # flash L<giri>: per 5s il compound lascia il posto ai giri fatti
        if getattr(self, "_ty_until", 0.0) > _ft.time():
            self.lbl_tyre_fl.setText("L%d" % getattr(self, "_ty_laps", 0))
            self.lbl_tyre_fl.setGeometry(self.lbl_tyre.rect())
            self.lbl_tyre.circle.hide()
            self.lbl_tyre._mix.hide()
            self.lbl_tyre_fl.show()
        elif self.lbl_tyre_fl.isVisible():
            self.lbl_tyre_fl.hide()

    def _start_sec_pulse(self, idx, box):
        """Avvia il lampeggio fade (opacità 1.0->0.25->1.0) sul quadratino del
        settore corrente. Idempotente: non riavvia se già attivo."""
        if idx in self._sec_anim:
            return
        eff = QGraphicsOpacityEffect(box)
        box.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity")
        anim.setDuration(1000)
        anim.setStartValue(1.0)
        anim.setKeyValueAt(0.5, 0.25)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.InOutSine)
        anim.setLoopCount(-1)
        anim.start()
        self._sec_anim[idx] = (eff, anim)

    def _stop_sec_pulse(self, idx, box):
        """Ferma il lampeggio e ripristina opacità piena."""
        pair = self._sec_anim.pop(idx, None)
        if pair:
            eff, anim = pair
            anim.stop()
            box.setGraphicsEffect(None)
