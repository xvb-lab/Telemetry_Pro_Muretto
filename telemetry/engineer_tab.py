"""telemetry/engineer_tab.py — pannello Ingegnere nella UI (0.3b).

Nella 0.3b il cervello ingegnere e' un PROCESSO SEPARATO
(`engineer/run_engineer.py`): questo tab NON esegue l'engine in-process (era la
causa degli scatti). Qui c'e':
  - l'API che tab_overlay/window si aspettano (is_enabled/set_enabled/…);
  - `set_enabled()` che AVVIA/FERMA il processo muretto dal vivo;
  - `settings_panel()` = le OPZIONI vere (lingua, volume voce, beep radio,
    ritardo tono, 3 tasti prova toni), che scrivono in `settings/engineer_cfg.json`
    — lo stesso file che il muretto rilegge ogni 2s.
"""
from pathlib import Path

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QSlider, QSpinBox, QFrame)
from PySide6.QtCore import Qt

_ROOT = Path(__file__).resolve().parent.parent
_RED = "#ff1d43"
_LANGS = (("it", "IT"), ("en", "EN"), ("es", "ES"), ("fr", "FR"))


class _EngineerTab(QWidget):
    """Pannello ingegnere + API attesa da tab_overlay/window (difensiva)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._app = parent
        self._ov = None                      # niente overlay in-process qui
        self._tone_player = None
        self._tone_out = None
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        title = QLabel("Engineer")
        title.setStyleSheet("font-size:15px; font-weight:600;")
        title.setAlignment(Qt.AlignCenter)
        sub = QLabel("Voice (separate process). Settings from the gear icon.")
        sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)
        lay.addWidget(sub)

    # ── API attesa da tab_overlay / window ────────────────────────────────
    def is_enabled(self):
        try:
            from core.engineer_cfg import load
            return bool(load().get("engineer_on", False))
        except Exception:
            return False

    def set_enabled(self, on):
        """Salva engineer_on E avvia/ferma il PROCESSO muretto dal vivo."""
        on = bool(on)
        try:
            from core.engineer_cfg import save
            save(engineer_on=on)
        except Exception:
            pass
        try:
            from core import muretto_proc
            muretto_proc.start() if on else muretto_proc.stop()
        except Exception:
            pass

    def is_radio_only(self):
        return True                          # il muretto e' voce-only

    def set_radio_only(self, on):
        pass

    def add_mirror(self, *a, **k):
        pass

    def remove_mirror(self, *a, **k):
        pass

    def log(self, text):
        """No-op: il muretto e' un processo separato con la sua console."""
        pass

    # ── OPZIONI (FASE 4) ──────────────────────────────────────────────────
    def _save(self, **kw):
        try:
            from core.engineer_cfg import save
            save(**kw)
        except Exception:
            pass

    def _play_tone(self, name):
        """Anteprima di un tono radio (assets/audio/<name>.wav|mp3)."""
        p = None
        for ext in ("wav", "mp3"):
            cand = _ROOT / "assets" / "audio" / ("%s.%s" % (name, ext))
            if cand.exists():
                p = cand
                break
        if p is None:
            return
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
            if self._tone_player is None:
                self._tone_out = QAudioOutput()
                self._tone_player = QMediaPlayer()
                self._tone_player.setAudioOutput(self._tone_out)
            self._tone_out.setVolume(1.0)
            self._tone_player.setSource(QUrl.fromLocalFile(str(p)))
            self._tone_player.play()
        except Exception:
            pass

    def _row(self, label):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        lb = QLabel(label)
        lb.setStyleSheet("color:#e8ebf2; font-size:13px;")
        h.addWidget(lb)
        h.addStretch(1)
        return w, h

    def _toggle(self, on, cb):
        b = QPushButton("ON" if on else "OFF")
        b.setObjectName("switchBtn")
        b.setCheckable(True)
        b.setChecked(bool(on))
        b.setFixedSize(52, 26)
        b.setCursor(Qt.PointingHandCursor)

        def _flip(v, _b=b):
            _b.setText("ON" if v else "OFF")
            cb(bool(v))
        b.toggled.connect(_flip)
        return b

    def settings_panel(self):
        """Pannello OPZIONI del muretto (scrive in engineer_cfg, letto live)."""
        try:
            from core.engineer_cfg import load
            cfg = load()
        except Exception:
            cfg = {}

        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)

        hdr = QLabel("ENGINEER — RADIO / VOICE")
        hdr.setStyleSheet("color:#aeb6c4; font-size:12px; font-weight:700;"
                          " letter-spacing:2px;")
        root.addWidget(hdr)

        # ── Lingua ──
        lw, lh = self._row("Language")
        self._lang_btns = {}
        cur = (cfg.get("lang") or "it")
        for code, lbl in _LANGS:
            b = QPushButton(lbl)
            b.setCheckable(True)
            b.setChecked(cur == code)
            b.setFixedHeight(28)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                "QPushButton{color:#fff;background:#2a2d38;border:none;"
                "border-radius:8px;padding:2px 12px;font-weight:700;}"
                "QPushButton:checked{background:%s;}" % _RED)
            b.clicked.connect(lambda _=False, c=code: self._set_lang(c))
            self._lang_btns[code] = b
            lh.addWidget(b)
        root.addWidget(lw)

        # ── Volume voce ──
        vw, vh = self._row("Voice volume")
        sl = QSlider(Qt.Horizontal)
        sl.setRange(0, 100)
        try:
            sl.setValue(int(cfg.get("voice_vol", 100)))
        except Exception:
            sl.setValue(100)
        sl.setFixedWidth(150)
        sl.setCursor(Qt.PointingHandCursor)
        sl.setStyleSheet(
            "QSlider::groove:horizontal{height:4px;background:#3a3d47;"
            "border-radius:2px;}"
            "QSlider::sub-page:horizontal{height:4px;background:%s;"
            "border-radius:2px;}"
            "QSlider::handle:horizontal{width:12px;height:12px;margin:-5px 0;"
            "background:#fff;border-radius:6px;}" % _RED)
        vlb = QLabel("%d%%" % sl.value())
        vlb.setFixedWidth(42)
        vlb.setStyleSheet("color:#e8ebf2;")
        sl.valueChanged.connect(
            lambda v: (vlb.setText("%d%%" % v), self._save(voice_vol=int(v))))
        vh.addWidget(sl)
        vh.addWidget(vlb)
        root.addWidget(vw)

        # ── Beep radio on/off ──
        bw, bh = self._row("Radio beep")
        bh.addWidget(self._toggle(bool(cfg.get("beep_on", True)),
                                  lambda on: self._save(beep_on=on)))
        root.addWidget(bw)

        # ── Ritardo tono radio (0-5 s) ──
        dw, dh = self._row("Radio tone delay")
        sp = QSpinBox()
        sp.setRange(0, 5)
        sp.setSuffix(" s")
        sp.setFixedWidth(76)
        try:
            sp.setValue(max(0, min(5, int(cfg.get("beep_delay_s", 2)))))
        except Exception:
            sp.setValue(2)
        sp.valueChanged.connect(lambda v: self._save(beep_delay_s=int(v)))
        dh.addWidget(sp)
        root.addWidget(dw)

        # ── Prova toni ──
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:#2a2d38;")
        root.addWidget(line)
        tw, th = self._row("Test tones")
        for lbl, tone in (("Radio", "radio"), ("Over", "end"),
                          ("Push", "push")):
            tb = QPushButton(lbl)
            tb.setFixedHeight(28)
            tb.setCursor(Qt.PointingHandCursor)
            tb.setStyleSheet(
                "QPushButton{color:#fff;background:#2a2d38;border:none;"
                "border-radius:8px;padding:2px 14px;}"
                "QPushButton:hover{background:%s;}" % _RED)
            tb.clicked.connect(lambda _=False, t=tone: self._play_tone(t))
            th.addWidget(tb)
        root.addWidget(tw)

        root.addStretch(1)
        note = QLabel("Changes take effect within 2 seconds — no restart.")
        note.setStyleSheet("color:#7f8796; font-size:11px;")
        note.setWordWrap(True)
        root.addWidget(note)
        return w

    def _set_lang(self, code):
        for c, b in getattr(self, "_lang_btns", {}).items():
            b.setChecked(c == code)
        self._save(lang=code)
