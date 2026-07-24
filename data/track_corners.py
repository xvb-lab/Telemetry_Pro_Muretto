# -*- coding: utf-8 -*-
"""POSIZIONI UFFICIALI DELLE CURVE per pista (24/07, decisione con
l'utente): la numerazione T1..Tn e' un RIFERIMENTO (mappa, cartelli,
ingegnere che dice "curva 4") e non puo' dipendere da un rilevatore
geometrico — le curve veloci "quasi dritte" sono curve col loro numero.

Formato: chiave = pezzo del nome pista (minuscolo);
valore = (lunghezza_riferimento_m, [apice T1, apice T2, ...] in metri
dal traguardo). Le posizioni vengono riscalate sulla lunghezza vera
della mappa. Detection geometrica SOLO per piste non censite.

Per censire una pista: si guarda la mappa/telemetria e si scrivono i
metri degli apici (l'utente corregge a voce: 'la T3 sta a X')."""

CORNERS = {
    # Silverstone National, 6 curve (censita 24/07 dai giri utente;
    # posizioni da rifinire con lui)
    "silverstone national": (2641, [284, 900, 1005, 1833, 2020, 2330]),
}


def corners_for_track(name, track_len=None):
    """[metri apice T1..Tn] riscalati su track_len, o None se pista
    non censita."""
    n = (name or "").lower()
    for k, (ref, pos) in CORNERS.items():
        if k in n:
            try:
                f = (float(track_len) / float(ref)) if track_len else 1.0
            except (TypeError, ValueError, ZeroDivisionError):
                f = 1.0
            return [p * f for p in pos]
    return None
