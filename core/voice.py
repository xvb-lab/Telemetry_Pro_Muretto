"""core/voice.py — voce ingegnere a FRASE INTERA.

Dice esattamente la frase mostrata nell'overlay (nessun montaggio di pezzi).
Backend, in ordine di preferenza, tutti OFFLINE su Windows:
  1) SAPI5 via win32com (voce italiana di sistema, es. Microsoft Elsa)
  2) pyttsx3 (wrapper SAPI5)
  3) PowerShell System.Speech (.NET, nessuna dipendenza pip)

Gira in un thread dedicato con coda: non blocca l'overlay, le frasi non si
accavallano (una alla volta, in ordine). Se nessun backend è disponibile
(es. Linux/container) diventa un no-op silenzioso.
"""

import sys
from pathlib import Path
import re
import queue
import threading
import subprocess


# espansione abbreviazioni per la VOCE (l'overlay resta compatto)
_VX_S = {"1": "uno", "2": "due", "3": "tre"}
_re_sx = re.compile(r"\bS([123])\b")
_re_tx = re.compile(r"\bT(\d+)\b")
_re_dx = re.compile(r"\bdx\b")
_re_sn = re.compile(r"\bsx\b")
_re_laptime = re.compile(r"\b(\d+):(\d{1,2})\.(\d{1,3})\b")
# abbreviazioni comuni -> parola parlata (schermo compatto, VOCE naturale)
_re_min = re.compile(r"(\d+)\s*min\b")
_re_sec = re.compile(r"(\d+)\s*sec\b")
_re_pct = re.compile(r"(\d+)\s*%")
_re_kmh = re.compile(r"(\d+)\s*km/?h\b")
_re_deg = re.compile(r"(\d+)\s*\u00b0")
# unità parlate per lingua: (minuti, secondi, percento, kmh, gradi)
_VX_UNITS = {
    "it": ("minuti", "secondi", "percento", "chilometri orari", "gradi"),
    "en": ("minutes", "seconds", "percent", "kilometers per hour", "degrees"),
    "es": ("minutos", "segundos", "por ciento", "kil\u00f3metros por hora", "grados"),
    "fr": ("minutes", "secondes", "pour cent", "kilom\u00e8tres heure", "degr\u00e9s"),
}


def _expand_units(text, l):
    """min/sec/%/km/h/gradi -> parole parlate. '1 minuto' se il numero e' 1."""
    u = _VX_UNITS.get(l, _VX_UNITS["it"])
    _sg = {"it": ("minuto", "secondo", "grado"),
           "en": ("minute", "second", "degree"),
           "es": ("minuto", "segundo", "grado"),
           "fr": ("minute", "seconde", "degr\u00e9")}.get(l, None)

    def _mk(word, sing_idx):
        def _f(m):
            n = m.group(1)
            w = word
            if _sg and n == "1":
                w = _sg[sing_idx]
            return "%s %s" % (n, w)
        return _f
    text = _re_min.sub(_mk(u[0], 0), text)
    text = _re_sec.sub(_mk(u[1], 1), text)
    text = _re_pct.sub(lambda m: "%s %s" % (m.group(1), u[2]), text)
    text = _re_kmh.sub(lambda m: "%s %s" % (m.group(1), u[3]), text)
    text = _re_deg.sub(_mk(u[4], 2), text)
    return text



def _expand_voice(text, lang="it"):
    """Rende il testo leggibile dalla TTS. IT: S1->settore uno, T7->curva 7,
    dx->destra, tempi 1:42.500 -> '1 42 e 5', dizionario pronuncia.
    EN: S1->sector 1, T7->turn 7, tempi -> '1 42 point 5'."""
    if not text:
        return text
    _l = str(lang).lower()[:2]
    if _l in ("en", "es", "fr"):
        _SEC = {"en": r"sector \1", "es": r"sector \1", "fr": r"secteur \1"}
        _TRN = {"en": r"turn \1", "es": r"curva \1", "fr": r"virage \1"}
        _PNT = {"en": "point", "es": "coma", "fr": "virgule"}
        text = _re_sx.sub(_SEC[_l], text)
        text = _re_tx.sub(_TRN[_l], text)

        def _lt_x(m):
            mn, sc, ms = m.group(1), m.group(2), m.group(3)
            dec = ms[0] if ms else "0"
            return "%s %s %s %s" % (mn, sc, _PNT[_l], dec)
        text = _re_laptime.sub(_lt_x, text)
        text = _expand_units(text, _l)
        return text
    text = _re_sx.sub(lambda m: "settore " + _VX_S[m.group(1)], text)
    text = _re_tx.sub(r"curva \1", text)
    text = _re_dx.sub("destra", text)
    text = _re_sn.sub("sinistra", text)
    # tempo giro: leggi minuti, secondi, decimo (es. 1:42.500 -> "1 42 e 5")
    def _lt(m):
        mn, sc, ms = m.group(1), m.group(2), m.group(3)
        dec = ms[0] if ms else "0"
        return "%s %s e %s" % (mn, sc, dec)
    text = _re_laptime.sub(_lt, text)
    text = _expand_units(text, "it")
    # PRONUNCIA ITALIANA (solo voce): dizionario editabile in
    # settings/pronuncia_it.json — "parola scritta" -> "come dirla".
    for _rx, _rep in _pron_it():
        text = _rx.sub(_rep, text)
    return text


_PRON_IT_CACHE = None


def _pron_it():
    """Carica (una volta) il dizionario pronuncia da settings/pronuncia_it.json.
    Voci come regex a confine di parola, case-sensitive (per le sigle)."""
    global _PRON_IT_CACHE
    if _PRON_IT_CACHE is not None:
        return _PRON_IT_CACHE
    import json as _json
    import re as _re2
    out = []
    try:
        f = Path(__file__).resolve().parent.parent / "settings" / "pronuncia_it.json"
        if f.exists():
            d = _json.loads(f.read_text(encoding="utf-8"))
            # sigle/parole piu' LUNGHE prima (LMGT3 prima di GT3)
            for k in sorted(d.keys(), key=len, reverse=True):
                if k.startswith("_"):
                    continue
                v = str(d[k])
                # parole comuni (tutte minuscole) -> ignora maiuscole a inizio
                # frase; SIGLE (con maiuscole) -> match esatto
                fl = _re2.IGNORECASE if k == k.lower() else 0
                out.append((_re2.compile(r"\b" + _re2.escape(k) + r"\b", fl), v))
    except Exception:
        out = []
    _PRON_IT_CACHE = out
    return out


def _is_italian(desc):
    d = (desc or "").lower()
    return ("ital" in d or "elsa" in d or "cosimo" in d or "it-it" in d)


# Voci Edge TTS italiane (nome tecnico, etichetta leggibile)
IT_EDGE_VOICES = [
    ("it-IT-GiuseppeNeural", "Giuseppe (uomo)"),
    ("it-IT-DiegoNeural", "Diego (uomo)"),
    ("it-IT-IsabellaNeural", "Isabella (donna)"),
]


class Voice:
    def __init__(self, lang="it", rate=0, volume=100, enabled=True,
                 edge_voice="it-IT-GiuseppeNeural"):
        self.enabled = bool(enabled)
        self.lang = lang
        self._rate = int(rate)
        self._volume = int(volume)
        self._edge_voice = edge_voice
        self._edge_failed = False
        self._beep_path = None        # tono radio prima della voce (open)
        self._beep_on = True
        self._tone_delay = 2.0        # ritardo tono -> voce (s)
        self._end_path = None         # tono di FINE messaggio (over)
        self._end_on = True
        self._speaking = False        # True mentre suona un messaggio
        self._abort_evt = threading.Event()   # taglio del messaggio in corso
        self._q = queue.Queue()
        self._backend = None          # impostato dal thread worker
        self._ready = threading.Event()
        self._stop = False
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    # ── API pubblica ──
    def speak(self, text, voice=None, beep=False, vol=None):
        """Accoda una frase intera. `voice` = voce Edge per QUESTA frase.
        `beep` = tono radio + ritardo prima di parlare. `vol` = boost SSML per
        QUESTA frase (es. '+20%') per alzare una voce specifica. No-op se off."""
        if not text or not self.enabled:
            return
        self._q.put((str(text), voice, bool(beep), vol))

    # ── tono radio (beep) + ritardo ───────────────────────────────────────
    def set_beep(self, path=None, enabled=True):
        """Percorso del file tono radio (mp3/wav) e on/off del beep."""
        if path is not None:
            self._beep_path = str(path)
        self._beep_on = bool(enabled)

    def set_tone_delay(self, seconds):
        """Ritardo (s) tra il tono radio e la voce."""
        try:
            self._tone_delay = max(0.0, min(5.0, float(seconds)))
        except (TypeError, ValueError):
            pass

    def set_end(self, path=None, enabled=True):
        """Tono di FINE messaggio (l'"over" della radio), suonato DOPO la voce."""
        if path is not None:
            self._end_path = str(path)
        self._end_on = bool(enabled)

    def busy(self):
        """True se sta parlando o ha ancora messaggi in coda."""
        return self._speaking or not self._q.empty()

    def interrupt(self):
        """Taglia SUBITO il messaggio in corso e svuota la coda (preemption
        della gialla). Chi chiama riaccoda ciò che serve ripetere."""
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass
        self._abort_evt.set()
        self._mci_stop()

    def _mci_stop(self):
        """Ferma la riproduzione MCI in corso (sblocca il 'play wait')."""
        try:
            import ctypes
            ctypes.windll.winmm.mciSendStringW("stop lmuvoce_mci", None, 0, 0)
        except Exception:
            pass

    def set_enabled(self, on):
        self.enabled = bool(on)
        if not on:
            # svuota la coda così tace subito
            try:
                while True:
                    self._q.get_nowait()
            except queue.Empty:
                pass

    def set_volume(self, v):
        """Volume voce 0..100 (applicato alla riproduzione MCI)."""
        try:
            self._volume = max(0, min(100, int(v)))
        except Exception:
            pass

    def set_voice_name(self, name):
        """Cambia la voce Edge TTS (es. it-IT-IsabellaNeural). Si applica
        dalla prossima frase."""
        if name:
            self._edge_voice = str(name)
            self._edge_failed = False

    def voice_name(self):
        return getattr(self, "_edge_voice", "it-IT-GiuseppeNeural")

    def available(self):
        self._ready.wait(timeout=2.0)
        return self._backend is not None

    def backend(self):
        self._ready.wait(timeout=2.0)
        return self._backend

    # ── thread worker: tutto il COM/SAPI vive qui ──
    def _loop(self):
        sapi = None
        eng = None
        backend = None
        # COM init nel thread (necessario per win32com)
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass
        # 0) Edge TTS (neurale, online) — voce migliore, frase intera
        if backend is None:
            try:
                import edge_tts  # noqa: F401
                backend = "edge"
            except Exception:
                pass
        # 1) SAPI via win32com
        if backend is None:
            try:
                import win32com.client
                sapi = win32com.client.Dispatch("SAPI.SpVoice")
                try:
                    for v in sapi.GetVoices():
                        if _is_italian(v.GetDescription()):
                            sapi.Voice = v
                            break
                except Exception:
                    pass
                try:
                    if self._rate:
                        sapi.Rate = max(-10, min(10, self._rate))
                    sapi.Volume = max(0, min(100, self._volume))
                except Exception:
                    pass
                backend = "sapi"
            except Exception:
                sapi = None
        # 2) pyttsx3
        if backend is None:
            try:
                import pyttsx3
                eng = pyttsx3.init()
                try:
                    for v in eng.getProperty("voices"):
                        if _is_italian(getattr(v, "name", "") + " " +
                                       " ".join(getattr(v, "languages", []) or [])):
                            eng.setProperty("voice", v.id)
                            break
                except Exception:
                    pass
                try:
                    eng.setProperty("volume", self._volume / 100.0)
                except Exception:
                    pass
                backend = "pyttsx3"
            except Exception:
                eng = None
        # 3) PowerShell System.Speech (solo Windows, nessuna dipendenza)
        if backend is None and sys.platform.startswith("win"):
            backend = "powershell"

        self._backend = backend
        self._ready.set()
        if backend is None:
            return                      # no-op silenzioso (Linux/container)

        while not self._stop:
            try:
                item = self._q.get()
            except Exception:
                break
            if item is None:
                break
            _beep = False
            if isinstance(item, tuple):
                text = item[0]
                _pv = item[1] if len(item) > 1 else None
                _beep = bool(item[2]) if len(item) > 2 else False
                _vol = item[3] if len(item) > 3 else None   # boost SSML frase
                if _pv:                       # voce per QUESTA frase
                    self._edge_voice = _pv
                    self._edge_failed = False
            else:
                text = item                   # retro-compat: stringa semplice
                _vol = None
            if text is None:
                break
            if not self.enabled:
                continue
            self._speaking = True
            self._abort_evt.clear()
            try:
                # tono radio (courtesy beep) + ritardo PRIMA della voce
                if _beep and self._beep_on:
                    if self._beep_path:
                        try:
                            self._play_mci(str(self._beep_path))
                        except Exception:
                            pass
                    self._abort_evt.wait(self._tone_delay)   # ritardo interrompibile
                if self._abort_evt.is_set():
                    continue                    # tagliato durante beep/ritardo
                text = _expand_voice(text)
                if backend == "edge":
                    if not self._edge_failed and self._say_edge(text, _vol):
                        pass
                    else:
                        self._edge_failed = True   # niente rete: passa a Elsa
                        self._say_powershell(text)
                elif backend == "sapi":
                    sapi.Speak(text, 0)             # 0 = sincrono in questo thread
                elif backend == "pyttsx3":
                    eng.say(text)
                    eng.runAndWait()
                elif backend == "powershell":
                    self._say_powershell(text)
                # tono di FINE messaggio (over), dopo la voce; saltato se tagliato
                if not self._abort_evt.is_set() and self._end_on and self._end_path:
                    try:
                        self._play_mci(str(self._end_path))
                    except Exception:
                        pass
            except Exception:
                pass
            finally:
                self._speaking = False

    def _say_edge(self, text, vol=None):
        """Edge TTS: sintetizza la frase intera in mp3 e la riproduce (MCI).
        `vol` = boost SSML (es. '+20%') per alzare QUESTA voce. Ritorna True se
        ok, False se fallisce (niente rete) -> fallback Elsa."""
        import os
        import tempfile
        import asyncio
        try:
            import edge_tts
        except Exception:
            return False
        path = None
        try:
            fd, path = tempfile.mkstemp(suffix=".mp3", prefix="lmuvoce_")
            os.close(fd)
            rate = ("%+d%%" % self._rate) if self._rate else "+0%"
            volume = vol or "+0%"

            async def _go():
                comm = edge_tts.Communicate(text, self._edge_voice,
                                            rate=rate, volume=volume)
                await comm.save(path)

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_go())
            finally:
                loop.close()
            if not os.path.exists(path) or os.path.getsize(path) < 256:
                return False
            self._play_mci(path)
            return True
        except Exception:
            return False
        finally:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

    def _play_mci(self, path):
        """Riproduce un file audio via MCI di Windows (winmm), bloccante.
        Applica il volume voce (0..100 -> 0..1000 MCI)."""
        import ctypes
        mci = ctypes.windll.winmm.mciSendStringW
        alias = "lmuvoce_mci"
        mci('close %s' % alias, None, 0, 0)
        # 'mpegvideo' gestisce gli mp3 su Windows
        if mci('open "%s" type mpegvideo alias %s' % (path, alias), None, 0, 0) != 0:
            mci('open "%s" alias %s' % (path, alias), None, 0, 0)
        try:
            vol = max(0, min(1000, int(getattr(self, "_volume", 100)) * 10))
            mci('setaudio %s volume to %d' % (alias, vol), None, 0, 0)
        except Exception:
            pass
        mci('play %s wait' % alias, None, 0, 0)
        mci('close %s' % alias, None, 0, 0)

    @staticmethod
    def _say_powershell(text):
        ps = (
            "Add-Type -AssemblyName System.Speech;"
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            "foreach($v in $s.GetInstalledVoices()){"
            "  if($v.VoiceInfo.Culture.Name -eq 'it-IT'){"
            "    $s.SelectVoice($v.VoiceInfo.Name);break}};"
            "$t=[Console]::In.ReadToEnd();$s.Speak($t)"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                input=text, text=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            pass
