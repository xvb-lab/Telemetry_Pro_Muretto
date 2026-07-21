"""core/soundtrack.py — Colonna sonora dell'app.

Due tracce (audio degli mp4 in assets, riprodotti direttamente da Qt):
  home       assets/home_sd.mp4    -> tutte le schermate
  telemetry  assets/telemetry.mp4  -> schermate telemetria

Regole:
  - cambio schermata = cambio traccia con DISSOLVENZA (mai a strappo);
  - sessione LIVE armata = la musica sfuma e SI FERMA; riprende (in
    dissolvenza) quando la sessione si chiude e il recorder si disarma;
  - durante l'intro video niente musica (l'intro ha il suo audio);
  - file mancante/vuoto (es. traccia ancora da scaricare) -> si ripiega
    sulla home senza errori; multimedia non disponibile -> silenzio e basta.
"""
from pathlib import Path

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_FILES = {"home": [_ASSETS / "home_sd.mp4",
                   _ASSETS / "home_sd_2.mp4",
                   _ASSETS / "home_sd_3.mp4"],
          "telemetry": _ASSETS / "telemetry.mp4",
          "setups": _ASSETS / "SETUPS.m4a"}
_VOL = 0.30          # volume di crociera (0..1)
_FADE_MS = 1200      # durata dissolvenza
_STEP_MS = 60        # passo del timer di fade


def _cands(name):
    """File ESISTENTI e non vuoti per una traccia (lista = rotazione)."""
    v = _FILES.get(name)
    lst = v if isinstance(v, list) else ([v] if v else [])
    return [p for p in lst if p and p.exists() and p.stat().st_size > 1024]


class Soundtrack:
    _inst = None

    @classmethod
    def instance(cls):
        if cls._inst is None:
            cls._inst = cls()
        return cls._inst

    def __init__(self):
        self._player = None
        self._out = None
        self._fade = None
        self._loaded = None      # traccia caricata nel player
        self._track = None       # traccia richiesta dalla schermata corrente
        self._live = False       # True = sessione armata: silenzio
        self._enabled = True     # check "Music" nelle OPTIONS
        self._pending = None     # traccia da caricare quando il fade-out finisce
        self._target = 0.0

    # ── API ───────────────────────────────────────────────────────────
    def set_screen(self, name):
        """name: 'home' | 'telemetry' | None (nessuna musica, es. intro)."""
        if name == self._track:
            return
        self._track = name
        if self._ensure():
            self._apply()

    def set_live(self, on):
        """Sessione live armata: sfuma e ferma; alla chiusura riprende."""
        on = bool(on)
        if on == self._live:
            return
        self._live = on
        if self._ensure():
            self._apply()

    def set_enabled(self, on):
        """Check 'Music' nelle OPTIONS: off = niente musica, mai."""
        on = bool(on)
        if on == self._enabled:
            return
        self._enabled = on
        if self._player is None and not on:
            return                 # mai partita: basta il flag
        if self._ensure():
            self._apply()

    # ── interni ───────────────────────────────────────────────────────
    def _ensure(self):
        if self._player is not None:
            return True
        try:
            from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
            from PySide6.QtCore import QTimer
            self._out = QAudioOutput()
            self._out.setVolume(0.0)
            self._player = QMediaPlayer()
            self._player.setAudioOutput(self._out)
            # loop deciso per traccia in _load (rotazione = 1, singola = inf)
            self._player.mediaStatusChanged.connect(self._on_status)
            self._fade = QTimer()
            self._fade.setInterval(_STEP_MS)
            self._fade.timeout.connect(self._tick)
            return True
        except Exception:
            self._player = None
            return False

    def _want(self):
        """Traccia che DEVE suonare adesso (None = silenzio)."""
        if self._live or not self._enabled or self._track is None:
            return None
        name = self._track
        if not _cands(name):
            name = "home"                      # traccia assente: ripiega
            if not _cands("home"):
                return None
        return name

    def _apply(self):
        want = self._want()
        if want is None:
            self._pending = None
            self._fade_to(0.0)
            return
        if self._loaded != want:
            if self._loaded is None:
                self._load(want)               # primo avvio: parte da zero
                self._player.play()
                self._fade_to(_VOL)
            else:
                self._pending = want           # cambio: giu', swap, su
                self._fade_to(0.0)
        else:
            try:
                from PySide6.QtMultimedia import QMediaPlayer
                if self._player.playbackState() != \
                        QMediaPlayer.PlaybackState.PlayingState:
                    self._player.play()
            except Exception:
                pass
            self._fade_to(_VOL)

    def _load(self, name):
        """Carica un file della traccia: con piu' candidati (home) sceglie a
        CASO evitando di ripetere quello appena sentito, e loops=1 cosi' a
        fine pezzo _on_status passa al prossimo. Traccia singola = loop inf."""
        from PySide6.QtCore import QUrl
        import random
        cands = _cands(name)
        if not cands:
            return
        pick = cands[0]
        if len(cands) > 1:
            pool = [p for p in cands if str(p) != getattr(self, "_cur_file", "")]
            pick = random.choice(pool or cands)
        self._cur_file = str(pick)
        try:
            from PySide6.QtMultimedia import QMediaPlayer
            self._player.setLoops(1 if len(cands) > 1
                                  else QMediaPlayer.Loops.Infinite)
        except Exception:
            pass
        self._player.setSource(QUrl.fromLocalFile(self._cur_file))
        self._loaded = name

    def _on_status(self, st):
        """Fine pezzo (solo tracce a rotazione, loops=1): avanti col
        prossimo file casuale della stessa schermata, senza dissolvenza."""
        try:
            from PySide6.QtMultimedia import QMediaPlayer
            if st != QMediaPlayer.MediaStatus.EndOfMedia:
                return
        except Exception:
            return
        want = self._want()
        if want is None or want != self._loaded:
            return
        self._load(want)
        self._player.play()

    def _fade_to(self, target):
        self._target = float(target)
        if self._fade is not None and not self._fade.isActive():
            self._fade.start()

    def _tick(self):
        try:
            v = float(self._out.volume())
            step = _VOL * _STEP_MS / float(_FADE_MS)
            if abs(v - self._target) <= step:
                self._out.setVolume(self._target)
                self._fade.stop()
                if self._target <= 0.0:
                    if self._pending is not None and not self._live:
                        # fade-out finito: cambia traccia e risali
                        self._load(self._pending)
                        self._pending = None
                        self._player.play()
                        self._fade_to(_VOL)
                    else:
                        self._player.pause()   # silenzio: ferma davvero
            else:
                self._out.setVolume(v + (step if self._target > v else -step))
        except Exception:
            try:
                self._fade.stop()
            except Exception:
                pass
