"""Launcher di UN overlay nel suo processo Python (parallelismo vero).

Ogni overlay ha il SUO interprete/GIL/event-loop Qt: l'OS lo mette su un core
diverso, non viene bloccato dagli altri né dalla UI/muretto.

Uso: python -m overlays.run_overlay <chiave>   (chiavi in overlays/registry.py)

Legge la stessa config dal disco (rispetta le impostazioni dell'app). Watchdog:
se l'app principale muore, l'overlay si chiude da solo (LMU_PARENT_PID via env).
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.fonts=false")
# root del progetto sul path (per import widgets/core)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import gc
    gc.freeze()
except Exception:
    pass

from PySide6.QtWidgets import QApplication


def main():
    key = sys.argv[1].strip().lower() if len(sys.argv) > 1 else "map"

    from overlays.registry import WIDGETS
    cls, label = None, key
    for k, lab, c in WIDGETS:
        if k == key:
            cls, label = c, lab
            break
    if cls is None:
        valid = " ".join(k for k, _, _ in WIDGETS)
        print("[run_overlay] chiave sconosciuta: '%s'. Valide: %s" % (key, valid))
        return 2

    # font nitidi su monitor scalati/multi-monitor (stessa cura di main.py)
    try:
        import ctypes as _ct
        _ct.windll.user32.SetProcessDpiAwarenessContext(_ct.c_void_p(-4))
    except Exception:
        pass
    try:
        from PySide6.QtCore import Qt as _Qt
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            _Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass
    app = QApplication(sys.argv)
    app.setApplicationName("LMU Overlay — %s" % label)

    # watchdog: se muore l'app padre, l'overlay si chiude da solo
    _ppid = os.environ.get("LMU_PARENT_PID")
    if _ppid:
        import threading

        def _watch(pid):
            try:
                pid = int(pid)
            except (TypeError, ValueError):
                return
            if os.name == "nt":
                try:
                    import ctypes
                    h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
                    if h:
                        ctypes.windll.kernel32.WaitForSingleObject(h, -1)
                        os._exit(0)
                except Exception:
                    pass
            import time as _tw
            while True:
                _tw.sleep(2.0)
                try:
                    os.kill(pid, 0)
                except OSError:
                    os._exit(0)

        threading.Thread(target=_watch, args=(_ppid,), daemon=True).start()

    try:
        from core.utils import load_custom_fonts
        load_custom_fonts()
    except Exception:
        pass

    overlay = cls()
    try:
        if hasattr(overlay, "set_enabled"):
            overlay.set_enabled(True)   # gli overlay gestiscono da soli l'auto-hide
        else:
            overlay.show()
    except Exception:
        try:
            overlay.show()
        except Exception:
            pass

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
