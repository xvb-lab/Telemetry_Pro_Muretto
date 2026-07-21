"""core/soundtrack.py — Colonna sonora dell'app.

Tracce lette dalle cartelle in assets/audio/music/ (mp3):
  home       hometrack/   -> menu e schermate generali (rotazione CASUALE)
  community  community/   -> area circuiti/sessioni/stint (persiste)
  setups     setups/      -> pagina setup
  telemetry  telemetry/   -> pagina telemetria

Regole:
  - cambio schermata = cambio traccia con DISSOLVENZA (mai a strappo);
    restare nella STESSA zona non riavvia la traccia (persiste);
  - sessione LIVE armata = la musica sfuma e SI FERMA; riprende (in
    dissolvenza) quando la sessione si chiude e il recorder si disarma;
  - durante l'intro video niente musica (l'intro ha il suo audio);
  - volume regolabile dalle OPTIONS (profilo 'music_vol', 0..100);
  - cartella/file mancante -> si ripiega sulla home senza errori; multimedia
    non disponibile -> silenzio e basta.
"""
from pathlib import Path

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_MUSIC = _ASSETS / "audio" / "music"


def _folder(name):
    """mp3 ESISTENTI in assets/audio/music/<name> (lista = rotazione)."""
    d = _MUSIC / name
    if not d.exists():
        return []
    return sorted(p for p in d.glob("*.mp3")
                  if p.exists() and p.stat().st_size > 1024)


# ricalcolate a ogni avvio: aggiungere/togliere mp3 nelle cartelle basta
_FILES = {
    "home": _folder("hometrack"),
    "community": _folder("community"),
    "setups": _folder("setups"),
    "telemetry": _folder("telemetry"),
}
_FADE_MS = 1200      # durata dissolvenza
_STEP_MS = 60        # passo del timer di fade
_FADE_REF = 1.0      # riferimento per la velocita' di fade (indip. dal volume)


def _load_vol():
    try:
        from core.profile import _load_profile
        v = float(_load_profile().get("music_vol", 40))
    except Exception:
        v = 40.0
    return max(0.0, min(1.0, v / 100.0))


def _cands(name):
    v = _FILES.get(name)
    return list(v) if isinstance(v, list) else ([v] if v else [])


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
        self._vol = _load_vol()  # volume di crociera (0..1), dalle OPTIONS

    # ── API ───────────────────────────────────────────────────────────
    def set_screen(self, name):
        """name: 'home'|'community'|'setups'|'telemetry'|None (intro)."""
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
            return
        if self._ensure():
            self._apply()

    def set_volume(self, pct):
        """Volume musica app 0..100 (dal cursore OPTIONS). Applica dal vivo."""
        try:
            self._vol = max(0.0, min(1.0, float(pct) / 100.0))
        except (TypeError, ValueError):
            return
        # se sta suonando (target > 0), risali/scendi al nuovo livello dolce
        if self._player is not None and self._target > 0.0:
            self._fade_to(self._vol)

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
                self._fade_to(self._vol)
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
            self._fade_to(self._vol)

    def _load(self, name):
        """Carica un file: con piu' candidati (home) sceglie a CASO evitando di
        ripetere l'ultimo, loops=1 cosi' a fine pezzo _on_status passa al
        prossimo. Traccia singola = loop infinito."""
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
        """Fine pezzo (tracce a rotazione, loops=1): prossimo file casuale."""
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
            step = _FADE_REF * _STEP_MS / float(_FADE_MS)
            if abs(v - self._target) <= step:
                self._out.setVolume(self._target)
                self._fade.stop()
                if self._target <= 0.0:
                    if self._pending is not None and not self._live:
                        self._load(self._pending)
                        self._pending = None
                        self._player.play()
                        self._fade_to(self._vol)
                    else:
                        self._player.pause()   # silenzio: ferma davvero
            else:
                self._out.setVolume(v + (step if self._target > v else -step))
        except Exception:
            try:
                self._fade.stop()
            except Exception:
                pass
