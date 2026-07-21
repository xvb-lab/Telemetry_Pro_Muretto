"""Condivisione sessioni tra compagni di squadra (locale, isolata).

DR1 esporta una sessione in uno zip (cartella <nome sessione>/ + .lmtel) e la
manda a DR2. DR2 la importa: viene estratta in una cartella ISOLATA in
%APPDATA% (team_sessions/), separata da sessioni normali, reference e ingegnere.
Le sessioni team servono SOLO al confronto telemetrie: non entrano nel learning
e non vanno online.
"""
import os
import zipfile
from pathlib import Path

from core.paths import TEAM_DIR
from telemetry import db as _db


def _safe(name):
    keep = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in str(name))
    return keep or "session"


# ── EXPORT (DR1) ──────────────────────────────────────────────────────────
def export_session(lmtel_path, out_dir):
    """Crea uno zip con dentro la cartella <nome sessione>/<file>.lmtel.
    Ritorna il path dello zip, o None."""
    src = Path(lmtel_path)
    if not src.exists():
        return None
    try:
        stem = _safe(src.stem)
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        zpath = out / (stem + ".zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            # struttura: <stem>/<stem>.lmtel  (cartella ordinata col nome sessione)
            z.write(src, arcname="%s/%s" % (stem, src.name))
        return str(zpath)
    except Exception:
        return None


# ── IMPORT (DR2) ──────────────────────────────────────────────────────────
def import_zip(zip_path):
    """Estrae il .lmtel dallo zip nella cartella team isolata. Ritorna il path
    del file importato, o None. Gestisce i nomi duplicati."""
    zp = Path(zip_path)
    if not zp.exists():
        return None
    try:
        TEAM_DIR.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zp, "r") as z:
            members = [m for m in z.namelist() if m.lower().endswith(".lmtel")]
            if not members:
                return None
            m = members[0]                          # una sessione per zip
            name = os.path.basename(m) or "session.lmtel"
            dst = TEAM_DIR / name
            if dst.exists():                        # evita sovrascritture
                i = 2
                base = dst.stem
                while dst.exists():
                    dst = TEAM_DIR / ("%s_%d.lmtel" % (base, i))
                    i += 1
            with z.open(m) as fsrc, open(dst, "wb") as fdst:
                fdst.write(fsrc.read())
        # verifica minima che sia un .lmtel valido
        try:
            import sqlite3
            c = sqlite3.connect(str(dst))
            c.execute("SELECT 1 FROM session_meta WHERE id=1")
            c.close()
        except Exception:
            try:
                dst.unlink()
            except Exception:
                pass
            return None
        return str(dst)
    except Exception:
        return None


# ── LISTA / ELIMINA ───────────────────────────────────────────────────────
def list_team_sessions():
    """Sessioni team importate (stessi metadati delle normali)."""
    sess = _db.list_sessions(folder=TEAM_DIR)
    for s in sess:
        s["team_session"] = True
    return sess


def delete_team_session(path):
    try:
        p = Path(path)
        if not p.exists():
            return False
        # sicurezza: il file deve stare dentro la cartella team (confronto
        # robusto, normalizzato e case-insensitive su Windows)
        try:
            pp = os.path.normcase(os.path.abspath(str(p.parent)))
            td = os.path.normcase(os.path.abspath(str(TEAM_DIR)))
        except Exception:
            pp = str(p.parent); td = str(TEAM_DIR)
        if pp != td:
            return False
        p.unlink()
        return True
    except Exception:
        pass
    return False
