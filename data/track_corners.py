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
    # MISURATE 24/07 dai giri utente (apici = picchi di curvatura
    # della mezzeria ufficiale, confermati dai minimi di velocita')
    "silverstone national": (2635, [378, 1077, 1124, 1922, 2109,
                                    2195]),
}


def corners_for_track(name, track_len=None):
    """[metri apice T1..Tn] riscalati su track_len, o None se pista
    non censita. Ordine: DB statico (manuale, VINCE sempre) poi
    censimento AUTOMATICO (<pista>_curve.json, scritto dal rilevatore
    del widget solo quando centra ESATTO il conto ufficiale — guardia
    anti-slittamento dei nomi)."""
    n = (name or "").lower()
    for k, (ref, pos) in CORNERS.items():
        if k in n:
            try:
                f = (float(track_len) / float(ref)) if track_len else 1.0
            except (TypeError, ValueError, ZeroDivisionError):
                f = 1.0
            return [p * f for p in pos]
    try:
        import json
        import re as _re
        from core.paths import USER_DIR

        def _nm(s):
            s = _re.sub(r"#U([0-9a-fA-F]{4})",
                        lambda m: chr(int(m.group(1), 16)),
                        (s or "").lower())
            for w in ("grand prix", "circuit", "international",
                      "raceway", "speedway", "the ", "2026"):
                s = s.replace(w, " ")
            return _re.sub(r"[^a-z0-9]+", "", s)

        tn = _nm(name)
        d = USER_DIR / "trackmap_official"
        if tn and d.exists():
            for j in d.glob("*_curve.json"):
                if _nm(j.stem[:-6]) != tn:      # via il suffisso _curve
                    continue
                o = json.loads(j.read_text(encoding="utf-8"))
                ref = float(o.get("len") or 0) or None
                pos = [float(x) for x in (o.get("apici") or [])]
                if not pos:
                    break
                try:
                    f = (float(track_len) / ref) \
                        if (track_len and ref) else 1.0
                except (TypeError, ValueError, ZeroDivisionError):
                    f = 1.0
                return [p * f for p in pos]
    except Exception:
        pass
    return None
