"""
core/race_memory.py — MEMORIA VOLATILE DI GARA.

Due strutture, zero dipendenze, vita = una sessione:

- RaceDiary: DIARIO degli eventi (pioggia on/off, soste, safety car, cambi
  di posizione, piani annunciati) con giro e ora. Serve ai moduli per
  ragionare sul PASSATO ("quanto e' durato l'ultimo scroscio?", "quante
  soste ho fatto?") invece di vivere nel presente del singolo tick — e
  finisce sul log del tab per l'autopsia post-gara.

- Commitments: REGISTRO DEGLI IMPEGNI presi via radio ("slick al giro 15",
  "pioggia al giro 22"). Ogni promessa con scadenza viene rivista a ogni
  tick dal revisore dell'engineer: mantenuta -> si chiude in silenzio;
  invalidata -> il modulo che l'ha presa annuncia il cambio; SCADUTA senza
  che il fatto sia successo -> va detta. Il muretto non puo' piu'
  promettere e dimenticare, per costruzione.
"""
import time
from collections import deque


class RaceDiary:
    """Diario eventi a capienza fissa. note() registra, drain_lines()
    scarica le righe nuove pronte per il log del tab."""

    def __init__(self, maxlen=400):
        self._ev = deque(maxlen=maxlen)
        self._pending = []

    def note(self, kind, lap=None, **data):
        e = {"kind": kind, "lap": lap, "t": time.time(), "data": dict(data)}
        self._ev.append(e)
        extra = " ".join("%s=%s" % kv for kv in data.items())
        self._pending.append(
            "DIARIO giro %s: %s%s" % (lap if lap is not None else "?",
                                      kind, (" " + extra) if extra else ""))
        return e

    def last(self, kind):
        """Ultimo evento di quel tipo, o None."""
        for e in reversed(self._ev):
            if e["kind"] == kind:
                return e
        return None

    def count(self, kind, since_lap=None):
        return sum(1 for e in self._ev if e["kind"] == kind
                   and (since_lap is None or (e["lap"] or 0) >= since_lap))

    def events(self):
        return list(self._ev)

    def drain_lines(self):
        out, self._pending = self._pending, []
        return out

    def __eq__(self, other):
        return (isinstance(other, RaceDiary)
                and list(self._ev) == list(other._ev)
                and self._pending == other._pending)


class Commitments:
    """Impegni radio attivi: UNO per chiave (il nuovo sostituisce il
    vecchio). Ogni impegno: codice del messaggio, giro in cui e' stato
    preso, scadenza (giro) e dati liberi (contatore solleciti incluso)."""

    def __init__(self):
        self._c = {}

    def open(self, cid, code, lap_made, due_lap=None, **data):
        self._c[cid] = {"cid": cid, "code": code, "lap": lap_made,
                        "due": due_lap, "data": dict(data)}
        return self._c[cid]

    def get(self, cid):
        return self._c.get(cid)

    def close(self, cid):
        return self._c.pop(cid, None)

    def extend(self, cid, new_due):
        if cid in self._c:
            self._c[cid]["due"] = new_due

    def active(self):
        return list(self._c.values())

    def __eq__(self, other):
        return isinstance(other, Commitments) and self._c == other._c
