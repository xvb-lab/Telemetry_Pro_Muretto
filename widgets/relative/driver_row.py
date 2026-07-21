"""
widgets/relative/driver_row.py — Riga del relative.

Come la riga standings ma con colonna "speed" (velocità max giro precedente)
e gap col segno (+ davanti / - dietro). Dimensioni dal config scalato.
"""
from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout, QGraphicsOpacityEffect
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QSvgWidget

from core.utils import fmt_time, find_logo_path
from .reader import get_status


class RelDriverRow(QWidget):
    def paintEvent(self, e):
        # tinta BRAND fino al nome + navy pannello sulle colonne dopo
        try:
            from core.wec_style import (row_gradient as brand_gradient,
                                        brand_color, ROW_BG)
            from PySide6.QtGui import (QPainter, QLinearGradient,
                                       QColor)
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

        self.lbl_name = lbl("name", cfg.scaled("col_name", 140))
        self.lbl_speed = lbl("speed", cfg.scaled("col_speed", 55), Qt.AlignCenter)
        self.lbl_best = lbl("best_lap", cfg.scaled("col_best", 82), Qt.AlignCenter)
        self.lbl_gap = lbl("gap", cfg.scaled("col_gap", 65), Qt.AlignCenter)
        self.lbl_lap = lbl("lap", cfg.scaled("col_lap", 82), Qt.AlignCenter)
        self.lbl_energy = lbl("energy", cfg.scaled("col_energy", 50), Qt.AlignCenter)
        self.lbl_tl = lbl("tl", cfg.scaled("col_tl", 32), Qt.AlignCenter)
        self.lbl_pit = lbl("pit", cfg.scaled("col_pit", 30), Qt.AlignCenter)
        self.lbl_laps = lbl("laps", cfg.scaled("col_laps", 34), Qt.AlignCenter)
        self.lbl_stint = lbl("stint", cfg.scaled("col_stint", 48), Qt.AlignCenter)
        self.lbl_wear = lbl("wear", cfg.scaled("col_wear", 42), Qt.AlignCenter)
        self.w_sectors = QWidget()
        self.w_sectors.setObjectName("sectorsBox")
        self.w_sectors.setFixedWidth(cfg.scaled("col_sectors", 42))
        _sl = QHBoxLayout(self.w_sectors)
        _sl.setContentsMargins(0, 0, 0, 0)
        _sl.setSpacing(2)
        self.sec_boxes = []
        self._sec_anim = {}
        self._fade_eff = {}
        self._fade_anim = {}
        self._gap_val = None
        _secsz = cfg.scaled("sec_box_size", 10)
        for _ in range(3):
            b = QLabel()
            b.setObjectName("secBox")
            b.setFixedSize(_secsz, _secsz)
            self.sec_boxes.append(b)
            _sl.addWidget(b)
        _sl.addStretch()
        from core.tyre_cell import TyreCell
        self.lbl_tyre = TyreCell(size=cfg.get("base", {}).get("col_tyre", 24), scale=cfg.scale)

        self._col = {
            "status": self.lbl_status, "class": self.lbl_class, "pos": self.lbl_pos, "logo": self.lbl_logo,
            "pdelta": self.lbl_pdelta,
            "name": self.lbl_name, "speed": self.lbl_speed, "gap": self.lbl_gap, "best": self.lbl_best,
            "lap": self.lbl_lap, "energy": self.lbl_energy, "tyre": self.lbl_tyre,
            "tl": self.lbl_tl,
            "pit": self.lbl_pit, "sectors": self.w_sectors,
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

        if not cfg.get("show_speed", True):
            self.lbl_speed.hide()
            self.lbl_speed.setFixedWidth(0)
        if not cfg.get("show_class", False):
            self.lbl_class.hide()
            self.lbl_class.setFixedWidth(0)
        # posizione stile onboard: P18 in Archivo corsivo
        self.lbl_pos.setStyleSheet(
            "font-family:'Druk Wide Cy TT', 'Archivo SemiExpanded';font-style:italic;"
            "font-weight:900;background:transparent;")
        if not cfg.get("show_pos_delta", True):
            self.lbl_pdelta.hide()
            self.lbl_pdelta.setFixedWidth(0)
        if not cfg.get("show_best_lap", True):
            self.lbl_best.hide()
            self.lbl_best.setFixedWidth(0)
        if not cfg.get("show_track_limits", True):
            self.lbl_tl.hide()
            self.lbl_tl.setFixedWidth(0)
        if not cfg.get("show_pit", True):
            self.lbl_pit.hide()
            self.lbl_pit.setFixedWidth(0)
        if not cfg.get("show_sectors", True):
            self.w_sectors.hide()
            self.w_sectors.setFixedWidth(0)
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
        self._logo_w = logo_w
        self._logo_h = logo_h

        thr = cfg.get("energy_thresholds", {})
        self._e_low = thr.get("low", 25)
        self._e_crit = thr.get("critical", 10)

    def _smooth_gap(self, target, alpha=0.35):
        """Avvicina il gap mostrato al target (ease) per un movimento fluido."""
        if target is None:
            self._gap_val = None
            return None
        if self._gap_val is None or abs(target - self._gap_val) > 5.0:
            self._gap_val = float(target)
        else:
            self._gap_val += (target - self._gap_val) * alpha
        return self._gap_val

    def _soft_set(self, lbl, text):
        """setText con fade morbido (opacità 0.35->1.0) solo al cambio valore."""
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
        # trick nomi lunghi: con 3+ parole le prime diventano iniziali
        # ("Alessandro Pier Guidi" -> "A. P. Guidi")
        _parts = _nm.split()
        if len(_parts) >= 3:
            _nm = " ".join(p[0] + "." for p in _parts[:-1]) \
                + " " + _parts[-1]
        _num = str(d.get("car_number") or "").strip()
        if _num:
            # numero gara PRIMA del nome, font onboard (Archivo italic)
            self.lbl_name.setTextFormat(Qt.RichText)
            self.lbl_name.setText(
                "<span style=\"font-family:'Druk Wide Cy TT', 'Archivo SemiExpanded';"
                "font-style:italic;font-weight:900;\">%s</span>"
                "&nbsp; %s" % (_num, _nm))
        else:
            self.lbl_name.setText(_nm)
        # brand per la tinta card (paintEvent) + testo leggibile
        self._row_brand = d.get("brand") or ""
        try:
            from core.wec_style import brand_color, text_on
            if brand_color(self._row_brand):
                self.lbl_name.setStyleSheet(
                    "background:transparent;color:%s;"
                    % text_on(self._row_brand))
            else:
                self.lbl_name.setStyleSheet("")
        except Exception:
            pass
        self.lbl_name.setProperty("lapstatus", d.get("lap_status", "") or "none")
        self.lbl_name.style().unpolish(self.lbl_name)
        self.lbl_name.style().polish(self.lbl_name)

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

        # gap col segno
        gap = d.get("gap_leader", 0)
        laps = d.get("laps_behind", 0)
        # evidenzia in arancione chi è entro 1s (davanti o dietro), non il player
        near = (not d["is_player"]) and (not laps or laps <= 0) and (0 < gap <= 1.0)
        # niente highlight riga: si colora SOLO il testo del gap
        if self.lbl_gap.property("near1s") != ("true" if near else "false"):
            self.lbl_gap.setProperty("near1s", "true" if near else "false")
            self._repol(self.lbl_gap)
        if d["is_player"]:
            self._gap_val = None
            self.lbl_gap.setText("")
        elif laps > 0:
            self._gap_val = None
            self.lbl_gap.setText(f"+{laps}L")
        elif gap > 0:
            sm = self._smooth_gap(gap)
            sign = d.get("_gap_sign", "+")
            self.lbl_gap.setText(f"{sign}{sm:.1f}")
        else:
            self._gap_val = None
            self.lbl_gap.setText("")

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

        # speed
        if self.cfg.get("show_speed", True):
            spd = d.get("speed_kmh", 0)
            self.lbl_speed.setText(f"{int(spd)}" if spd > 0 else "")
            self.lbl_speed.setProperty("topspeed", "true" if d.get("is_top_speed") else "false")
            self._repol(self.lbl_speed)

        # best lap
        if self.cfg.get("show_best_lap", True):
            best = d.get("best_lap", 0)
            self._soft_set(self.lbl_best, fmt_time(best) if best > 0 else "--:--.---")
            self.lbl_best.setProperty("overall", "true" if d.get("is_overall_best") else "false")
            self._repol(self.lbl_best)

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
            count = steps // per_pt
            max_count = per_pen // per_pt if per_pt else 3
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

    def _start_sec_pulse(self, idx, box):
        """Lampeggio fade (opacità 1.0->0.25->1.0) sul settore corrente."""
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
        pair = self._sec_anim.pop(idx, None)
        if pair:
            eff, anim = pair
            anim.stop()
            box.setGraphicsEffect(None)
