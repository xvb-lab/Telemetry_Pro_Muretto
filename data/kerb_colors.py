# -*- coding: utf-8 -*-
"""COLORI CORDOLI per circuito (dettati dall'utente 24/07).
Chiave = pezzo del nome pista LMU, minuscolo. Valore = lista di 2 o 3
colori RGB: 2 colori = strisce alternate (dash), 3 colori = TRICOLORE
per lungo (tre bande parallele, rich. utente per Imola/Monza).
Condivisa da widget mappa overlay e pagina pista."""

_BIANCO = (240, 240, 240)
_ROSSO = (224, 40, 60)
_GIALLO = (255, 212, 0)
_BLU = (40, 90, 200)
_VERDE = (0, 140, 70)
_NERO = (28, 30, 36)

KERB_COLORS = {
    "fuji": [_BLU, _BIANCO],
    "americas": [_ROSSO, _GIALLO],           # COTA: cordoli rosso/giallo
    "algarve": [_BIANCO, _ROSSO],
    "portimao": [_BIANCO, _ROSSO],
    "bahrain": [_ROSSO, _BIANCO],
    "imola": [_VERDE, _BIANCO, _ROSSO],      # tricolore per lungo
    "enzo e dino": [_VERDE, _BIANCO, _ROSSO],
    "spa": [_GIALLO, _ROSSO],
    "sarthe": [_BLU, _GIALLO],               # Le Mans
    "lusail": [_BIANCO, _ROSSO],
    "monza": [_VERDE, _BIANCO, _ROSSO],      # tricolore per lungo
    "interlagos": [(0, 155, 58), _GIALLO, _BIANCO],   # verde/giallo/bianco
    "carlos pace": [(0, 155, 58), _GIALLO, _BIANCO],
    "sebring": [_BIANCO, _ROSSO],
    "daytona": [_BIANCO, _ROSSO],            # (chicane giallo/blu: futuro)
    "laguna seca": [_BIANCO, _ROSSO],
    "silverstone": [_BIANCO, _NERO],
    "barcelona": [_GIALLO, _ROSSO],
    "paul ricard": [_BIANCO, _ROSSO],
}

_DEFAULT = [_BIANCO, _ROSSO]


def kerb_colors(track):
    """Lista colori RGB del cordolo per la pista (2 o 3 voci)."""
    n = (track or "").lower()
    for k, v in KERB_COLORS.items():
        if k in n:
            return v
    return _DEFAULT
