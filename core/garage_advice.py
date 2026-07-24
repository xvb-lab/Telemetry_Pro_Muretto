# -*- coding: utf-8 -*-
"""CONSIGLI GARAGE dell'ingegnere (rich. 24/07 sera): quando il muretto
segnala a voce un problema d'assetto ("differenza termica sulla spalla,
rivedi il camber"), scrive QUI anche il consiglio concreto — voce del
setup, regolazione suggerita, motivo. La pagina Setups li mostra sopra
l'editor .svm: il pilota legge, regola e prova.

File: USER_DIR/learn/garage_advice.json — lista di record
{ts, data, track, car, sezione, voce, consiglio, motivo}.
Dedupe per (pista, voce): resta il piu' fresco. Nessuna dipendenza Qt.
"""
import json
import time

from core.paths import USER_DIR

_FP = USER_DIR / "learn" / "garage_advice.json"


def _load():
    try:
        rows = json.loads(_FP.read_text(encoding="utf-8"))
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def add(track, car, sezione, voce, consiglio, motivo=""):
    """Aggiunge/aggiorna un consiglio (dedupe per pista+voce)."""
    try:
        rows = [r for r in _load()
                if not (r.get("track") == (track or "")
                        and r.get("voce") == voce)]
        rows.append({"ts": time.time(),
                     "data": time.strftime("%d/%m %H:%M"),
                     "track": track or "", "car": car or "",
                     "sezione": sezione or "", "voce": voce,
                     "consiglio": consiglio, "motivo": motivo or ""})
        rows = rows[-60:]                 # tetto: gli ultimi 60
        _FP.parent.mkdir(parents=True, exist_ok=True)
        _FP.write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                       encoding="utf-8")
    except Exception:
        pass


def list_all():
    """Tutti i consigli, dal piu' recente."""
    return sorted(_load(), key=lambda r: -float(r.get("ts") or 0))


def clear():
    """Svuota l'elenco (tasto Pulisci della pagina Setups)."""
    try:
        _FP.unlink()
    except Exception:
        pass
