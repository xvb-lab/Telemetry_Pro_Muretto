"""
widgets/wec26mfd/minicar.py — la MACCHININA del dashboard (TyreBrakeGrid).

Portata 1:1 dal dashboard_overlay del backup v3 (20/07): 4 angoli con
gomma (colore = temperatura carcassa, arancione = foratura), disco freno
a gradiente per classe, dot sospensione, ali/diffusore a 6 segmenti dai
punti body, fiancate, alettone rosso se staccato. Ruota staccata = sparita.
"""
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush


class TyreBrakeGrid(QWidget):
    """Colonna compatta: 4 angoli (FL FR / RL RR), ogni angolo mostra
    temperatura carcassa gomma e temperatura freno."""

    def __init__(self, scale=1.0, rear_ext=0.0):
        super().__init__()
        self._scale = scale
        self._rear_ext = max(0.0, float(rear_ext))
        self._carcass = [0, 0, 0, 0]
        self._brake = [0, 0, 0, 0]
        self._cls = ""
        self._dent = [0] * 8
        self._susp = [None] * 4
        self._aero = 0.0
        self._flat = [False] * 4
        self._detached = [False] * 4
        self._detached_part = False
        self.setFixedSize(round(64 * scale),
                          round(72 * scale * (1.0 + self._rear_ext)))
        self.setAttribute(Qt.WA_TranslucentBackground)

    def set_data(self, carcass, brake, cls, dent=None, susp=None, aero=None,
                 flat=None, detached=None, detached_part=False,
                 headlights=False, light_flash=False):
        self._carcass = carcass or [0, 0, 0, 0]
        self._brake = brake or [0, 0, 0, 0]
        self._cls = cls or ""
        self._dent = dent or [0] * 8
        self._susp = susp or [None] * 4
        self._aero = aero if aero is not None else 0.0
        self._flat = flat or [False] * 4
        self._detached = detached or [False] * 4
        self._detached_part = bool(detached_part)
        self._hl = bool(headlights)
        self._lflash = bool(light_flash)
        self.update()

    def _brake_grad_color(self, t, car_class=""):
        """Identico a car base: gradiente continuo, freddo grigio -> caldo."""
        cls = (car_class or "").upper()
        carbon = cls in ("HY", "P2", "P3")
        # LATO CALDO allineato alle SOGLIE VERE LMU (dati_lmu.md,
        # 23/07): overheating 800 carbon / 700 acciaio — il rosso
        # arrivava a 950/870, troppo tardi. Finestra ottimale doc:
        # 350-650 carbon, 300-550 acciaio.
        if carbon:
            stops = [(40, (90, 95, 102)), (150, (90, 95, 102)),
                     (280, (80, 130, 200)), (350, (0, 180, 130)),
                     (500, (0, 230, 118)), (650, (200, 220, 40)),
                     (725, (255, 200, 0)), (770, (255, 120, 20)),
                     (800, (255, 50, 30)), (900, (255, 235, 225))]
        else:
            stops = [(40, (90, 95, 102)), (120, (90, 95, 102)),
                     (220, (80, 130, 200)), (300, (0, 180, 130)),
                     (430, (0, 230, 118)), (550, (200, 220, 40)),
                     (625, (255, 200, 0)), (670, (255, 120, 20)),
                     (700, (255, 50, 30)), (800, (255, 235, 225))]
        if t <= stops[0][0]:
            r, g, b = stops[0][1]
            return QColor(r, g, b)
        if t >= stops[-1][0]:
            r, g, b = stops[-1][1]
            return QColor(r, g, b)
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            if t0 <= t <= t1:
                fr = (t - t0) / (t1 - t0)
                return QColor(round(c0[0] + (c1[0] - c0[0]) * fr),
                              round(c0[1] + (c1[1] - c0[1]) * fr),
                              round(c0[2] + (c1[2] - c0[2]) * fr))
        r, g, b = stops[-1][1]
        return QColor(r, g, b)

    def paintEvent(self, e):
        from widgets.list.colors import col_tyre_temp, col_susp
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()
        sc = self._scale
        h0 = 72.0 * sc          # altezza BASE (senza allungamento posteriore)
        ty_w = 11 * sc          # larghezza gomma
        ty_h = h0 * 0.30        # altezza gomma
        br_w = 3.5 * sc         # larghezza disco freno
        br_h = ty_h * 0.62      # altezza disco freno
        gap = 2 * sc
        row_y = [h0 * 0.30 - 1 * sc, h - h0 * 0.30 + 1 * sc]

        # ── ali/diffusore: 3 segmenti davanti + 3 dietro (punti body) ──
        line_h = 2.0 * sc
        cxm = w / 2
        seg_out = w * 0.16
        seg_mid = w * 0.24
        seg_gap = 2.5 * sc
        _body_col = {0: QColor("#3a3d44"), 1: QColor(255, 210, 60),
                     2: QColor(255, 60, 50)}

        def _dcol(idx):
            lev = int(min(self._dent[idx] if idx < len(self._dent) else 0, 2))
            return _body_col.get(lev, _body_col[0])

        p.setPen(Qt.NoPen)
        rows = [
            (h0 * 0.05, 1, 0, 7),       # anteriore: fl, fc, fr
            (h - h0 * 0.10, 3, 4, 5),   # posteriore: rl, rc, rr
        ]
        for wy, di_l, di_c, di_r in rows:
            p.setBrush(QBrush(_dcol(di_c)))
            p.drawRoundedRect(QRectF(cxm - seg_mid / 2, wy - line_h / 2,
                                     seg_mid, line_h),
                              line_h / 2, line_h / 2)
            lx = cxm - seg_mid / 2 - seg_gap - seg_out
            p.setBrush(QBrush(_dcol(di_l)))
            p.drawRoundedRect(QRectF(lx, wy - line_h / 2, seg_out, line_h),
                              line_h / 2, line_h / 2)
            rx = cxm + seg_mid / 2 + seg_gap
            p.setBrush(QBrush(_dcol(di_r)))
            p.drawRoundedRect(QRectF(rx, wy - line_h / 2, seg_out, line_h),
                              line_h / 2, line_h / 2)
        # ── alettone posteriore: rosso se una parte e' staccata ──
        wing_full_w = w * 0.62
        wy_wing = h - h0 * 0.035
        p.setBrush(QBrush(QColor(255, 60, 50) if self._detached_part
                          else QColor("#3a3d44")))
        p.drawRoundedRect(QRectF(cxm - wing_full_w / 2, wy_wing - line_h / 2,
                                 wing_full_w, line_h), line_h / 2, line_h / 2)
        margin = 4 * sc
        coords = [
            ('L', margin,            row_y[0]),   # FL
            ('R', w - margin - ty_w, row_y[0]),   # FR
            ('L', margin,            row_y[1]),   # RL
            ('R', w - margin - ty_w, row_y[1]),   # RR
        ]
        for i, (side, gx, gy) in enumerate(coords):
            is_det = i < len(self._detached) and self._detached[i]
            is_flat = i < len(self._flat) and self._flat[i]
            if is_det:
                continue                # ruota staccata: sparita
            tc = int(round(self._carcass[i])) if i < len(self._carcass) else 0
            bk = int(round(self._brake[i])) if i < len(self._brake) else 0
            col_b = self._brake_grad_color(bk, self._cls)
            if is_flat:
                col_t = QColor(255, 140, 30)     # arancione: foratura
            else:
                col_t = col_tyre_temp(tc, self._cls)
            tyre = QRectF(gx, gy - ty_h / 2, ty_w, ty_h)
            p.setPen(QPen(QColor(0, 0, 0, 120), 1.0))
            p.setBrush(QBrush(col_t))
            p.drawRoundedRect(tyre, 2.5 * sc, 2.5 * sc)
            if side == 'L':
                bx = gx + ty_w + gap
            else:
                bx = gx - gap - br_w
            disc = QRectF(bx, gy - br_h / 2, br_w, br_h)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(col_b))
            p.drawRoundedRect(disc, 1.5 * sc, 1.5 * sc)
            sv = self._susp[i] if i < len(self._susp) else None
            if sv is None:
                susp_col = QColor("#3a3d44")
            else:
                si = int(round((1 - sv) * 100))
                susp_col = QColor("#3a3d44") if si >= 100 else col_susp(si)
            dot_r = 2.2 * sc
            dot_gap = 2.0 * sc
            if side == 'L':
                dot_x = bx + br_w + dot_gap + dot_r
            else:
                dot_x = bx - dot_gap - dot_r
            p.setBrush(QBrush(susp_col))
            p.drawEllipse(QPointF(dot_x, gy), dot_r, dot_r)

        # ── 2 punti carrozzeria laterali (cl, cr) tra le gomme ──
        body_w = 2.4 * sc
        body_h = (row_y[1] - row_y[0]) * 0.32
        mid_y = (row_y[0] + row_y[1]) / 2
        for dent_idx, bxp in ((2, margin + ty_w / 2 - body_w / 2),
                              (6, w - margin - ty_w / 2 - body_w / 2)):
            lev = int(min(self._dent[dent_idx]
                          if dent_idx < len(self._dent) else 0, 2))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(_body_col.get(lev, _body_col[0])))
            p.drawRoundedRect(QRectF(bxp, mid_y - body_h / 2, body_w, body_h),
                              body_w / 2, body_w / 2)
        p.end()
