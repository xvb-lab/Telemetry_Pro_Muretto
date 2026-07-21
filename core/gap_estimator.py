"""
core/gap_estimator.py — Gap TEMPORALE tra auto, senza effetto "elastico".

Il gap spaziale (differenza di distanza in pista / velocità) respira a ogni
curva perché le due auto sono in punti diversi del tracciato. Qui invece si
calcola il vero distacco di TEMPO: confrontiamo l'istante in cui ciascuna auto
passa lo STESSO punto del tracciato, usando uno storico (tempo, distanza).

Uso:
    est = GapEstimator()
    est.update({sid: total_dist, ...})        # ogni tick, distanza monotona (m)
    g = est.gap(ref_sid, other_sid, ref_total, other_total)
    # g > 0  -> other è DAVANTI a ref di g secondi
    # g < 0  -> other è DIETRO a ref di |g| secondi
    # g None -> storico insufficiente
"""
import time
from collections import deque


class GapEstimator:
    def __init__(self, history_s: float = 120.0):
        self._hist = {}            # sid -> deque[(t, total_dist)]
        self._history_s = history_s
        self._now = time.monotonic()

    def update(self, totals: dict):
        now = time.monotonic()
        self._now = now
        cutoff = now - self._history_s
        for sid, td in totals.items():
            dq = self._hist.get(sid)
            if dq is None:
                dq = deque()
                self._hist[sid] = dq
            # reset sessione / teleport: la distanza cala -> azzera storico
            if dq and td < dq[-1][1] - 1.0:
                dq.clear()
            # evita campioni fermi (auto immobile): aggiorna comunque il tempo
            if dq and abs(td - dq[-1][1]) < 1e-6:
                dq[-1] = (now, td)
            else:
                dq.append((now, td))
            while len(dq) > 2 and dq[0][0] < cutoff:
                dq.popleft()
        # rimuovi auto sparite
        live = set(totals)
        for sid in [s for s in self._hist if s not in live]:
            self._hist.pop(sid, None)

    def _time_at(self, sid, target_td):
        """Istante (monotonic) in cui sid era a target_td, interpolato.
        None se fuori dallo storico disponibile."""
        dq = self._hist.get(sid)
        if not dq or len(dq) < 2:
            return None
        if target_td <= dq[0][1] or target_td > dq[-1][1]:
            return None
        prev = dq[0]
        for cur in dq:
            if cur[1] >= target_td:
                t0, d0 = prev
                t1, d1 = cur
                if d1 == d0:
                    return t1
                f = (target_td - d0) / (d1 - d0)
                return t0 + (t1 - t0) * f
            prev = cur
        return None

    def gap(self, ref_sid, other_sid, ref_total, other_total):
        now = self._now
        if other_total >= ref_total:
            # other DAVANTI: quando other passò dove ref è ORA
            t = self._time_at(other_sid, ref_total)
            return (now - t) if t is not None else None
        else:
            # other DIETRO: quando ref passò dove other è ORA
            t = self._time_at(ref_sid, other_total)
            return (-(now - t)) if t is not None else None
