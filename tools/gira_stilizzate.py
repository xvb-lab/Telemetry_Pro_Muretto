# -*- coding: utf-8 -*-
"""GIRA-STILIZZATE (rich. utente 24/07 sera, tool developer):
le mappe stilizzate delle card sono "orientate alla cazzo" — questo
tool le carica TUTTE, le ruoti col mouse (trascina = gira, come il
ROT dell'overlay) e SALVA l'angolo in settings/stylized_rotations.json,
che card e pagina classifiche rispettano.

Uso:  python tools/gira_stilizzate.py
Comandi: trascina col mouse = ruota | frecce SX/DX = pista prec/succ
         +90 = scatto esatto | 0 = azzera | S o INVIO = salva
         (il passaggio pista salva da solo)
"""
import json
import math
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from PySide6.QtWidgets import (QApplication, QWidget, QHBoxLayout,
                               QVBoxLayout, QLabel, QPushButton)
from PySide6.QtGui import QPainter, QColor, QFont
from PySide6.QtCore import Qt, QRectF
from PySide6.QtSvg import QSvgRenderer

SVG_DIR = REPO / "assets" / "trackmaps_svg"
OUT = REPO / "settings" / "stylized_rotations.json"


def _dec(stem):
    return re.sub(r"#U([0-9a-fA-F]{4})",
                  lambda m: chr(int(m.group(1), 16)), stem)


class _Canvas(QWidget):
    def __init__(self, owner):
        super().__init__()
        self._o = owner
        self._drag = None
        self.setMinimumSize(560, 560)

    def _ang(self, pos):
        return math.degrees(math.atan2(pos.y() - self.height() / 2.0,
                                       pos.x() - self.width() / 2.0))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = self._ang(e.position())

    def mouseMoveEvent(self, e):
        if self._drag is not None and (e.buttons() & Qt.LeftButton):
            a = self._ang(e.position())
            self._o.rot = (self._o.rot + (a - self._drag)) % 360.0
            self._drag = a
            self._o.refresh()

    def mouseReleaseEvent(self, e):
        self._drag = None

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(14, 16, 22))
        r = self._o.renderer
        if r is None or not r.isValid():
            p.setPen(QColor(220, 220, 220))
            p.drawText(self.rect(), Qt.AlignCenter, "SVG non valido")
            return
        ds = r.defaultSize()
        w, h = max(1, ds.width()), max(1, ds.height())
        th = math.radians(self._o.rot)
        bw = abs(w * math.cos(th)) + abs(h * math.sin(th))
        bh = abs(w * math.sin(th)) + abs(h * math.cos(th))
        s = min(self.width() * 0.86 / bw, self.height() * 0.86 / bh)
        p.translate(self.width() / 2.0, self.height() / 2.0)
        p.rotate(self._o.rot)
        r.render(p, QRectF(-w * s / 2.0, -h * s / 2.0, w * s, h * s))


class Tool(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gira stilizzate — tool developer")
        self.files = sorted(SVG_DIR.glob("*.svg"),
                            key=lambda f: _dec(f.stem).lower())
        try:
            self.saved = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            self.saved = {}
        self.i = 0
        self.rot = 0.0
        self.renderer = None
        v = QVBoxLayout(self)
        self.lab = QLabel("")
        self.lab.setStyleSheet("color:#f2f4f7;font-size:15px;"
                               "font-weight:700;")
        v.addWidget(self.lab)
        self.canvas = _Canvas(self)
        v.addWidget(self.canvas, 1)
        row = QHBoxLayout()
        for txt, fn in (("<<  prec", self.prev), ("+90", self.p90),
                        ("0", self.zero), ("SALVA", self.save),
                        ("succ  >>", self.next)):
            b = QPushButton(txt)
            b.setMinimumHeight(34)
            b.clicked.connect(fn)
            row.addWidget(b)
        v.addLayout(row)
        self.setStyleSheet("background:#0e1016; QPushButton{color:#fff;"
                           "background:#232733;border:none;"
                           "border-radius:8px;font-weight:700;}")
        self.load()

    def load(self):
        f = self.files[self.i]
        self.renderer = QSvgRenderer(str(f))
        self.rot = float(self.saved.get(_dec(f.stem), 0.0))
        self.refresh()

    def refresh(self):
        f = self.files[self.i]
        self.lab.setText("%d/%d   %s      angolo: %d°%s" % (
            self.i + 1, len(self.files), _dec(f.stem),
            round(self.rot) % 360,
            "   (salvato)" if _dec(f.stem) in self.saved else ""))
        self.canvas.update()

    def save(self):
        f = self.files[self.i]
        k = _dec(f.stem)
        if abs(self.rot % 360.0) < 0.5:
            self.saved.pop(k, None)      # 0 = niente voce
        else:
            self.saved[k] = round(self.rot % 360.0, 1)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(self.saved, ensure_ascii=False,
                                  indent=1, sort_keys=True),
                       encoding="utf-8")
        self.refresh()

    def prev(self):
        self.save()
        self.i = (self.i - 1) % len(self.files)
        self.load()

    def next(self):
        self.save()
        self.i = (self.i + 1) % len(self.files)
        self.load()

    def p90(self):
        self.rot = (round(self.rot / 90.0) * 90.0 + 90.0) % 360.0
        self.refresh()

    def zero(self):
        self.rot = 0.0
        self.refresh()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Left:
            self.prev()
        elif e.key() == Qt.Key_Right:
            self.next()
        elif e.key() in (Qt.Key_S, Qt.Key_Return, Qt.Key_Enter):
            self.save()
        else:
            super().keyPressEvent(e)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    t = Tool()
    t.resize(680, 720)
    t.show()
    sys.exit(app.exec())
