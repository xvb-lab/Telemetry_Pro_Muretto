"""core/muretto_proc.py — avvio/stop del processo MURETTO (engineer.run_engineer).

Singleton di processo condiviso NELLO STESSO processo UI: main.py lo lancia
all'avvio (se engineer_on), e il toggle "Engineer" nella UI lo accende/spegne
DAL VIVO senza riavviare l'app. Difensivo: niente eccezioni verso la UI.
"""
import sys
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_proc = None


def is_running():
    return _proc is not None and _proc.poll() is None


def start():
    """Avvia il muretto se non gia' attivo. Ritorna True se e' (o resta) su."""
    global _proc
    if is_running():
        return True
    kw = {"cwd": str(_ROOT)}
    if sys.platform == "win32":
        kw["creationflags"] = 0x08000000          # niente console
    try:
        _proc = subprocess.Popen(
            [sys.executable, "-m", "engineer.run_engineer"], **kw)
        return True
    except Exception:
        _proc = None
        return False


def stop():
    """Ferma il muretto se attivo."""
    global _proc
    p = _proc
    if p is not None and p.poll() is None:
        try:
            p.terminate()
        except Exception:
            pass
    _proc = None


def restart():
    stop()
    start()
