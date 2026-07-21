"""core/tyre_cell.py — cella gomme: disegna la mescola come SVG (via ui.icons),
così lettera mescola e dot del mix sono SEMPRE centrati e allineati.

API invariata: TyreCircle(set_sigla/set_new), TyreCell(set_tyre/set_new).
"""
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PySide6.QtCore import Qt, QRectF, QByteArray
from PySide6.QtGui import QPainter
from PySide6.QtSvg import QSvgRenderer

from ui.icons import TYRE_COLORS, tyre_chip_svg, tyre_mix_svg


class _SvgLabel(QLabel):
    """Disegna una stringa SVG scalata e centrata sul widget."""
    def __init__(self, side):
        super().__init__()
        self._svg = ""
        self.setFixedSize(side, side)
        self.setStyleSheet("background:transparent;")

    def set_svg(self, svg):
        self._svg = svg or ""
        self.update()

    def paintEvent(self, ev):
        if not self._svg:
            return
        r = QSvgRenderer(QByteArray(self._svg.encode()))
        if not r.isValid():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r.render(p, QRectF(0, 0, self.width(), self.height()))
        p.end()


class TyreCircle(_SvgLabel):
    """Cerchio mescola con lettera centrata (SVG). API: set_sigla, set_new."""
    def __init__(self, diam):
        super().__init__(diam)
        self._sigla = ""
        self._new = True

    def set_sigla(self, sigla):
        self._sigla = sigla or ""
        self._refresh()

    def set_new(self, is_new):
        self._new = bool(is_new)
        self._refresh()

    def _refresh(self):
        self.set_svg(tyre_chip_svg(self._sigla, self._new) if self._sigla else "")


class TyreCell(QWidget):
    """Mostra la mescola: cerchio unico, o 4 dot se mix. Tutto SVG."""
    def __init__(self, size=24, scale=1.0):
        super().__init__()
        self.setObjectName("tyreCell")
        self._w = round(size * scale)
        self._diam = max(16, round(28 * scale))
        self.setFixedWidth(self._w)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.circle = TyreCircle(self._diam)
        lay.addWidget(self.circle, 0, Qt.AlignCenter)
        self._mix = _SvgLabel(self._diam)
        lay.addWidget(self._mix, 0, Qt.AlignCenter)
        self._mix.hide()

    def set_new(self, is_new):
        self.circle.set_new(is_new)

    def set_tyre(self, single, four, new4=None, single_new=True):
        """single: sigla principale (fallback). four: lista 4 ruote o None.
        new4: lista 4 bool (True=gomma nuova, False=usata->dot vuoto).
        single_new: cerchio unico pieno se nuova, tratteggiato se usata."""
        valid4 = isinstance(four, (list, tuple)) and len(four) == 4 and all(four)
        mix = valid4 and len(set(four)) > 1
        if not (isinstance(new4, (list, tuple)) and len(new4) == 4):
            new4 = [True, True, True, True]
        if mix:
            self.circle.hide()
            self._mix.set_svg(tyre_mix_svg(list(four), list(new4)))
            self._mix.show()
        else:
            self._mix.hide()
            sigla = (four[0] if valid4 else single) or ""
            self.circle.set_sigla(sigla)
            self.circle.set_new(bool(single_new))
            self.circle.show()
