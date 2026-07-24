# -*- coding: utf-8 -*-
"""COLLAUDO MAPPE (24/07): fa girare il rilevatore VERO del widget su
OGNI mappa presente (utente + dotazione app) e pretende curve trovate.
Uscita 0 = tutto sano; 1 = qualcosa e' rotto (con l'errore stampato).

Uso:  python tools/check_mappe.py
"""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    from PySide6.QtWidgets import QApplication
    QApplication(sys.argv)
    from widgets.map.widget import MapCanvas, _load_map, _svg_index
    from data.track_info import info_for_track

    nomi = sorted(_svg_index().keys())
    if not nomi:
        print("nessuna mappa da collaudare (ok: si registrano girando)")
        return 0
    errori = 0
    for nome in nomi:
        try:
            path, secs, pit = _load_map(nome)
            if not path:
                print("%-40s ERRORE: mappa non caricabile" % nome)
                errori += 1
                continue
            mc = MapCanvas()
            mc._track = nome
            mc._path, mc._secs, mc._pit9 = path, secs, pit
            turns = mc._turns_map()
            inf = info_for_track(nome, None)
            uff = inf[1] if inf else None
            # dottrina 24/07 sera: il censimento si scrive SEMPRE
            # (riferimento interno) — quindi curve>0 obbligatorio;
            # girare questo tool CENSISCE anche le mappe arretrate
            _why = str(getattr(mc, "_tm_reason", "") or "")
            ok = len(turns) > 0
            segno = "OK " if ok else "ERR"
            if not ok:
                errori += 1
            print("%s %-38s punti=%-5d curve=%-2d ufficiali=%s "
                  "settori=%s corsia=%s  [%s]" % (
                      segno, nome, len(path), len(turns),
                      uff if uff is not None else "-",
                      "si" if len(secs) >= 2 else "NO",
                      "si" if pit else "no", _why or "?"))
        except Exception:
            errori += 1
            print("%-40s ECCEZIONE:" % nome)
            traceback.print_exc()
    print()
    if errori:
        print("COLLAUDO FALLITO: %d problemi" % errori)
        return 1
    print("COLLAUDO SUPERATO: %d mappe, rilevatore sano" % len(nomi))
    return 0


if __name__ == "__main__":
    sys.exit(main())
