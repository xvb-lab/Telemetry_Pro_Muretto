"""
widgets/list/components.py — DataRow e WheelTable (lista dati colonna destra).
Portati 1:1 dall'HUD originale.
"""
from PySide6.QtWidgets import (QWidget, QLabel, QHBoxLayout, QGridLayout,
                                QGraphicsOpacityEffect)
from PySide6.QtCore import Qt, QPropertyAnimation


class DataRow(QWidget):
    def __init__(self, label, scale=1.0):
        super().__init__()
        self._scale = scale
        self.setObjectName("dataRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(round(26 * scale))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(round(10 * scale), 0, round(10 * scale), 0)
        lay.setSpacing(round(6 * scale))
        self.dot = QLabel("●"); self.dot.setObjectName("dataDot")
        from core.icons import ICON_FONT
        from PySide6.QtGui import QFont
        self._icon_font = QFont(ICON_FONT, round(13 * scale))
        self._icon_set = False
        self.lbl = QLabel(label); self.lbl.setObjectName("dataLabel")
        self.val = QLabel("—"); self.val.setObjectName("dataValue")
        self.val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        # font scalati (sovrascrivono il QSS fisso)
        _fl = self.lbl.font(); _fl.setPixelSize(max(8, round(12 * scale)))
        self.lbl.setFont(_fl)
        _fv = self.val.font(); _fv.setPixelSize(max(8, round(12 * scale))); _fv.setBold(True)
        self.val.setFont(_fv)
        _fd = self.dot.font(); _fd.setPixelSize(max(6, round(9 * scale)))
        self.dot.setFont(_fd)
        lay.addWidget(self.dot)
        lay.addWidget(self.lbl)
        lay.addStretch()
        lay.addWidget(self.val)
        self._eff = QGraphicsOpacityEffect(self.dot)
        self._eff.setOpacity(1.0)
        self.dot.setGraphicsEffect(self._eff)
        self._anim = QPropertyAnimation(self._eff, b"opacity")
        self._anim.setDuration(700)
        self._anim.setStartValue(1.0)
        self._anim.setKeyValueAt(0.5, 0.25)
        self._anim.setEndValue(1.0)
        self._anim.setLoopCount(-1)
        self._pulsing = False

    def _set_pulse(self, on):
        if on and not self._pulsing:
            self._anim.start(); self._pulsing = True
        elif not on and self._pulsing:
            self._anim.stop(); self._eff.setOpacity(1.0); self._pulsing = False

    def set_icon(self, glyph, color=None):
        """Imposta un'icona Material come 'dot' della riga."""
        self.dot.setFont(self._icon_font)
        self.dot.setText(glyph)
        self._icon_set = True
        if color:
            self.dot.setStyleSheet(f"color: {color};")
        else:
            self.dot.setStyleSheet("color: #6a7480;")

    def set_icon_color(self, color):
        """Cambia solo il colore dell'icona già impostata."""
        if color:
            self.dot.setStyleSheet(f"color: {color};")

    def _dot_style(self, dot_color, pulse=False):
        if self._icon_set:
            # riga con icona: cambia solo il colore, mantiene il glifo
            if dot_color:
                self.dot.setStyleSheet(f"color: {dot_color};")
            self._set_pulse(pulse)
            return
        if dot_color:
            self.dot.setStyleSheet(f"color: {dot_color}; font-size: {max(6, round(9*self._scale))}px;")
        else:
            self.dot.setStyleSheet(f"color: #333b45; font-size: {max(6, round(9*self._scale))}px;")
        self._set_pulse(pulse)

    def set_value(self, text, level="normal", dot_color=None, pulse=False):
        self.val.setText(text)
        self.val.setProperty("level", level)
        self.val.style().unpolish(self.val); self.val.style().polish(self.val)
        self._dot_style(dot_color, pulse)

    def set_colored(self, text, hexcolor, dot_color=None, pulse=False):
        self.val.setProperty("level", "normal")
        self.val.style().unpolish(self.val); self.val.style().polish(self.val)
        self.val.setText(f'<span style="color:{hexcolor}">{text}</span>')
        self._dot_style(dot_color, pulse)

    def set_html(self, html, dot_color=None, pulse=False):
        """Imposta HTML grezzo (per testo multi-colore già formattato)."""
        self.val.setProperty("level", "normal")
        self.val.style().unpolish(self.val); self.val.style().polish(self.val)
        self.val.setText(html)
        self._dot_style(dot_color, pulse)


class WheelTable(QWidget):
    ROWS = [("tyres", "TYRE"), ("susp", "SUSP"), ("brakes", "BRAKE")]
    COLS = ["FL", "FR", "RL", "RR"]

    def __init__(self):
        super().__init__()
        self.setObjectName("wheelTable")
        self.setAttribute(Qt.WA_StyledBackground, True)
        g = QGridLayout(self)
        g.setContentsMargins(10, 4, 10, 4)
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(2)
        corner = QLabel(""); corner.setObjectName("wtCorner")
        g.addWidget(corner, 0, 0)
        for c, name in enumerate(self.COLS):
            h = QLabel(name); h.setObjectName("wtHeader")
            h.setAlignment(Qt.AlignCenter)
            g.addWidget(h, 0, c + 1)
        self._cells = {}
        for ri, (key, label) in enumerate(self.ROWS):
            lab = QLabel(label); lab.setObjectName("wtRowLabel")
            g.addWidget(lab, ri + 1, 0)
            cells = []
            for c in range(4):
                cell = QLabel("—"); cell.setObjectName("wtCell")
                cell.setAlignment(Qt.AlignCenter)
                g.addWidget(cell, ri + 1, c + 1)
                cells.append(cell)
            self._cells[key] = cells
        for c in range(1, 5):
            g.setColumnStretch(c, 1)

    def set_row(self, key, vals, colors):
        cells = self._cells.get(key)
        if not cells:
            return
        for i, cell in enumerate(cells):
            if i < len(vals):
                cell.setText(str(vals[i]))
                cell.setStyleSheet(f"color: {colors[i]};")
