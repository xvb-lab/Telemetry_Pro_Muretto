"""core/results.py — statistiche RISULTATI GARA dalle sessioni registrate.

Scansiona i .lmtel in USER_DIR/logs, prende SOLO le gare (session_type >= 10)
e calcola: gare, vittorie (P1 di classe), podi (<=3), top 5 (<=5), DNF.

Posizione finale = `pos` (posizione di classe) dell'ULTIMO giro valido della
gara — LMU non salva una classifica finale, ma l'ultimo giro la rispecchia.
Il DNF viene dal campo `finish_status` in session_meta (2=DNF, 3=DQ): esiste
solo dalle gare registrate DOPO l'aggiunta della registrazione; le sessioni
piu' vecchie non ce l'hanno -> DNF non conteggiato per quelle.

Cache leggera (mtime della cartella) per non riscandire a ogni apertura.
"""
import glob
import os
import sqlite3

_CACHE = {"sig": None, "stats": None}


def _folder_sig(d):
    try:
        files = glob.glob(os.path.join(d, "*.lmtel"))
        return (len(files), max((os.path.getmtime(f) for f in files), default=0.0))
    except Exception:
        return None


def _scan(d):
    out = {"races": 0, "wins": 0, "podiums": 0, "top5": 0, "dnf": 0}
    for f in glob.glob(os.path.join(d, "*.lmtel")):
        con = None
        try:
            con = sqlite3.connect("file:%s?mode=ro" % f.replace("?", "%3f"),
                                  uri=True, timeout=0.5)
            st = con.execute(
                "SELECT session_type FROM session_meta WHERE id=1").fetchone()
            if not st or int(st[0] or 0) < 10:          # SOLO gare
                continue
            out["races"] += 1
            # DNF/DQ dal finish_status (se registrato)
            fs = None
            try:
                r = con.execute(
                    "SELECT finish_status FROM session_meta WHERE id=1").fetchone()
                fs = int(r[0]) if r and r[0] is not None else None
            except Exception:
                fs = None
            if fs is not None and fs >= 2:
                out["dnf"] += 1
                continue
            # posizione finale = pos dell'ultimo giro valido
            row = con.execute("SELECT pos FROM laps WHERE pos IS NOT NULL "
                              "AND pos > 0 ORDER BY lap DESC LIMIT 1").fetchone()
            if row and row[0]:
                p = int(row[0])
                if p == 1:
                    out["wins"] += 1
                if p <= 3:
                    out["podiums"] += 1
                if p <= 5:
                    out["top5"] += 1
        except Exception:
            pass
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass
    return out


def race_stats():
    """{'races','wins','podiums','top5','dnf'} dalle gare registrate."""
    try:
        from core.paths import LOGS_DIR
        d = str(LOGS_DIR)
    except Exception:
        return {"races": 0, "wins": 0, "podiums": 0, "top5": 0, "dnf": 0}
    sig = _folder_sig(d)
    if sig is not None and sig == _CACHE["sig"] and _CACHE["stats"] is not None:
        return _CACHE["stats"]
    stats = _scan(d)
    _CACHE["sig"] = sig
    _CACHE["stats"] = stats
    return stats
