"""
core/classes.py — Mappa il nome classe LMU alla sigla breve (stile LMU).

L'API può restituire nomi diversi (Hyper, Hypercar, LMP2, LMP2_ELMS, ...).
class_tag() normalizza alla sigla mostrata: HY / P2 / P3 / GT3 / GTE.
Il colore lo mette il QSS via #class_col[cls="HY"] ecc.
"""


def class_tag(car_class: str) -> str:
    up = (car_class or "").upper()
    if "HYPER" in up or "LMH" in up or "LMDH" in up or up == "HY":
        return "HY"
    if "LMP2" in up or up in ("P2", "LMP2_ELMS"):
        return "P2"
    if "LMP3" in up or up == "P3":
        return "P3"
    if "GT3" in up:
        return "GT3"
    if "GTE" in up:
        return "GTE"
    return up[:3] if up else ""
