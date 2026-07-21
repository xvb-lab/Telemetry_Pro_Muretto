"""ui/icons_preview.py — visore icone (DEV). Mostra tutte le icone SVG generate
da ui/icons.py così le vedi facili senza andare in-sim.

Avvio:  python ui/icons_preview.py
Quando ricostruiremo la UI, questo diventa una vera tab DEV nell'app.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # root progetto

from PySide6.QtWidgets import (QApplication, QWidget, QLabel, QVBoxLayout,
                               QHBoxLayout, QGridLayout, QScrollArea)
from PySide6.QtCore import Qt, QRectF, QByteArray
from PySide6.QtGui import QPainter
from PySide6.QtSvg import QSvgRenderer

from core.tyre_cell import TyreCell, TyreCircle
from ui.icons import FUEL_WEIGHT_SVG, tyre_mix_svg


class _SvgBox(QLabel):
    """Disegna una stringa SVG centrata (per la goccia benzina)."""
    def __init__(self, svg, side):
        super().__init__()
        self._svg = svg
        self.setFixedSize(side, side)
        self.setStyleSheet("background:transparent;")

    def paintEvent(self, ev):
        r = QSvgRenderer(QByteArray(self._svg.encode()))
        if not r.isValid():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r.render(p, QRectF(0, 0, self.width(), self.height()))
        p.end()


def _cap(text):
    l = QLabel(text)
    l.setAlignment(Qt.AlignCenter)
    l.setStyleSheet("color:#9aa0aa;font-size:11px;background:transparent;")
    return l


def _cell_under(widget, caption):
    box = QWidget()
    box.setStyleSheet("background:transparent;")
    v = QVBoxLayout(box)
    v.setContentsMargins(6, 6, 6, 6)
    v.setSpacing(4)
    v.addWidget(widget, 0, Qt.AlignCenter)
    v.addWidget(_cap(caption))
    return box


def _section(title):
    l = QLabel(title)
    l.setStyleSheet("color:#e8eaee;font-size:13px;font-weight:700;"
                    "letter-spacing:.5px;background:transparent;")
    return l


def build_gallery():
    page = QWidget()
    page.setStyleSheet("background:#171a21;")
    root = QVBoxLayout(page)
    root.setContentsMargins(20, 20, 20, 20)
    root.setSpacing(14)

    SIZE = 42

    # mescola nuova
    root.addWidget(_section("MESCOLA · NUOVA"))
    row = QHBoxLayout(); row.setSpacing(16); row.setAlignment(Qt.AlignLeft)
    for s in ("S", "M", "H", "W"):
        c = TyreCircle(SIZE); c.set_sigla(s); c.set_new(True)
        row.addWidget(_cell_under(c, s))
    w = QWidget(); w.setLayout(row); w.setStyleSheet("background:transparent;")
    root.addWidget(w)

    # mescola usata
    root.addWidget(_section("MESCOLA · USATA (bordo tratteggiato)"))
    row = QHBoxLayout(); row.setSpacing(16); row.setAlignment(Qt.AlignLeft)
    for s in ("S", "M", "H", "W"):
        c = TyreCircle(SIZE); c.set_sigla(s); c.set_new(False)
        row.addWidget(_cell_under(c, s))
    w = QWidget(); w.setLayout(row); w.setStyleSheet("background:transparent;")
    root.addWidget(w)

    # mix
    root.addWidget(_section("MIX 4 DOT (pieno=nuova · vuoto=usata)"))
    row = QHBoxLayout(); row.setSpacing(16); row.setAlignment(Qt.AlignLeft)
    examples = [
        (["M", "M", "H", "H"], [True, True, True, True],   "M·M / H·H"),
        (["M", "M", "H", "H"], [False, False, False, False], "usate"),
        (["S", "M", "H", "W"], [True, True, False, False],   "mista"),
    ]
    for four, new4, lab in examples:
        box = _SvgBox(tyre_mix_svg(four, new4), SIZE)   # stessa misura dei cerchi
        row.addWidget(_cell_under(box, lab))
    w = QWidget(); w.setLayout(row); w.setStyleSheet("background:transparent;")
    root.addWidget(w)

    # benzina
    root.addWidget(_section("PESO BENZINA"))
    row = QHBoxLayout(); row.setSpacing(16); row.setAlignment(Qt.AlignLeft)
    row.addWidget(_cell_under(_SvgBox(FUEL_WEIGHT_SVG, SIZE), "+kg"))
    w = QWidget(); w.setLayout(row); w.setStyleSheet("background:transparent;")
    root.addWidget(w)

    root.addStretch(1)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(page)
    scroll.setStyleSheet("QScrollArea{border:none;background:#171a21;}")
    return scroll


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = build_gallery()
    w.setWindowTitle("LMU Telemetry Pro — Visore icone (DEV)")
    w.resize(560, 620)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
