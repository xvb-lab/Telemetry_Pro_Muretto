"""data/tracks.py — fonte dati circuiti e risoluzione pista/layout: tabella
_TRACKS, etichette layout, alias, e funzioni che dal nome LMU ricavano mappa
SVG/logo/PNG/layout. Estratto 1:1 da window.py (ricostruzione, sezione circuiti)."""

import os
import sqlite3
import time
import math
from PySide6.QtWidgets import (QWidget, QMainWindow, QTabWidget, QTabBar, QVBoxLayout,
                               QHBoxLayout, QComboBox, QPushButton, QLabel,
                               QTableWidget, QTableWidgetItem, QHeaderView,
                               QAbstractItemView, QStyledItemDelegate, QMessageBox,
                               QColorDialog, QStackedWidget, QGridLayout, QSizePolicy,
                               QLineEdit, QFrame, QCheckBox)
from PySide6.QtCore import Qt, QRectF, QPointF, QTimer, QSize
from pathlib import Path
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QPolygonF, QFont, QPainterPath, QLinearGradient, QPixmap
from telemetry import common as _common
try:
    from PySide6.QtSvgWidgets import QSvgWidget
except Exception:
    QSvgWidget = None
try:
    from PySide6.QtSvg import QSvgRenderer
except Exception:
    QSvgRenderer = None
from PySide6.QtCore import QByteArray
from telemetry import db as _db
from telemetry.reader import TelemetryReader
from core.classes import class_tag
try:
    from core.paths import PROFILE_FILE as _PROFILE_FILE
except Exception:
    _PROFILE_FILE = Path(__file__).resolve().parent.parent / "settings" / "profile.json"


_OV_TRACKMAP_DIR = Path(__file__).resolve().parent.parent / "settings" / "trackmap"


_ov_trackmap_idx = None

# ─────────────────────────────────────────────────────────────────────────
# RISOLUTORE CIRCUITI CANONICO — una sola identità di layout per ogni pista.
# Fonte di verità: la tabella card _TRACKS (cmap = SVG del layout). Qualunque
# nome (grezzo LMU, corto, accentato, con suffissi) viene normalizzato e
# mappato alla STESSA chiave canonica usata da creazione, filtro e card.
# ─────────────────────────────────────────────────────────────────────────
import unicodedata as _ud


def _norm(s):
    s = _ud.normalize("NFKD", s or "")
    s = "".join(c for c in s if not _ud.combining(c))
    return " ".join("".join(c if c.isalnum() else " " for c in s.lower()).split())


def _nospace(s):
    return _norm(s).replace(" ", "")


# nomi LMU "strani" -> frammento del cmap canonico (per il match per frammento)
_LMU_LAYOUT_ALIASES = {
    "portimao": "algarve", "algarve": "algarve",
    "qatar": "lusail international", "losail": "lusail international",
    "le mans": "24 heures du mans", "lemans": "24 heures du mans",
    "sarthe": "sarthe", "interlagos": "jose carlos pace",
    "sao paulo": "jose carlos pace", "americas": "americas", "cota": "americas",
    "catalunya": "barcelona",
}

_JUNK = {"circuit", "de", "la", "du", "of", "the", "el", "do", "autodromo",
         "nazionale", "speedway", "raceway", "heures", "internazionale"}

_canon_idx = None    # (alias_map: norm->(key,logo), entries: [(key,logo,tokens)])


def _canon():
    """Indice canonico costruito (lazy) dalla tabella card _TRACKS."""
    global _canon_idx
    if _canon_idx is not None:
        return _canon_idx
    try:
        from telemetry.window import _TRACKS
    except Exception:
        _TRACKS = []
    amap = {}
    entries = []
    for e in _TRACKS:
        try:
            name, logo, cmap = e[2], e[3], e[4]
        except Exception:
            continue
        cstem = _decode_stem(cmap[:-4] if cmap.lower().endswith(".svg") else cmap)
        ckey = _norm(cstem)                         # CHIAVE CANONICA del layout
        entries.append((ckey, logo, set(ckey.split())))
        for form in (name, cstem):
            amap.setdefault(_norm(form), (ckey, logo))
            amap.setdefault(_nospace(form), (ckey, logo))
    if not entries:               # _TRACKS non ancora pronto: non cachare
        return (amap, entries)
    _canon_idx = (amap, entries)
    return _canon_idx


def _resolve(track):
    """(chiave_layout_canonica, logo_stem) per qualunque nome pista."""
    if not track:
        return (None, None)
    amap, entries = _canon()
    n = _norm(track)
    ns = _nospace(track)
    if n in amap:
        return amap[n]
    if ns in amap:
        return amap[ns]
    for k, frag in _LMU_LAYOUT_ALIASES.items():     # alias LMU -> per frammento
        if k in n:
            # tra le righe dello stesso circuito (che contengono il frammento)
            # scegli quella che condivide piu parole col nome LMU: cosi i layout
            # (es. "COTA National Circuit" vs base) non cadono sempre sul primo.
            tsig = {w for w in n.split() if w not in _JUNK and len(w) > 1}
            cand = None
            cand_score = None
            for ck, logo, toks in entries:
                if frag not in ck:
                    continue
                nsig = {w for w in toks if w not in _JUNK and len(w) > 1}
                shared = len(tsig & nsig)
                score = (shared, -len(nsig - tsig), len(ck))
                if cand_score is None or score > cand_score:
                    cand_score = score
                    cand = (ck, logo)
            if cand:
                return cand
    tsig = {w for w in n.split() if w not in _JUNK and len(w) > 1}
    if tsig:                                         # match a token significativi
        best = None
        best_score = None
        for ck, logo, toks in entries:
            nsig = {w for w in toks if w not in _JUNK and len(w) > 1}
            shared = len(tsig & nsig)
            if not shared:
                continue
            score = (shared, -len(nsig - tsig), len(ck))
            if best_score is None or score > best_score:
                best_score = score
                best = (ck, logo)
        if best:
            return best
    return (None, None)


def _ov_trackmap_file(track):
    """Risolve l'SVG della pista in settings/trackmap per nome (match esatto o approssimato)."""
    global _ov_trackmap_idx
    if not track:
        return None
    if _ov_trackmap_idx is None:
        import re
        idx = {}
        try:
            for f in _OV_TRACKMAP_DIR.glob("*.svg"):
                name = re.sub(r"#U([0-9a-fA-F]{4})",
                              lambda m: chr(int(m.group(1), 16)), f.stem)
                idx[name] = f
        except Exception:
            idx = {}
        _ov_trackmap_idx = idx
    if track in _ov_trackmap_idx:
        return _ov_trackmap_idx[track]
    # alias espliciti per nomi-pista che LMU manda senza il suffisso del file
    # (evita che il word-match li mandi sul layout sbagliato dello stesso circuito)
    _ALIAS = {
        "Silverstone Grand Prix Circuit": "Silverstone Grand Prix Circuit - ELMS",
    }
    if track in _ALIAS and _ALIAS[track] in _ov_trackmap_idx:
        return _ov_trackmap_idx[_ALIAS[track]]
    # match a PAROLE significative (ignora parole generiche): vince l'SVG che
    # condivide piu parole distintive col nome pista, a parita meno parole extra.
    # Cosi "Monza Curva Grande" risolve sul layout giusto e non sul Monza base.
    _JUNK = {"autodromo", "nazionale", "circuit", "international", "internazionale",
             "de", "la", "du", "of", "the", "el", "do", "speedway", "raceway",
             "grand", "prix", "gp", "heures", "24"}

    def _sig(s):
        ws = "".join(c if c.isalnum() else " " for c in s.lower()).split()
        return {w for w in ws if w not in _JUNK and len(w) > 1}

    tsig = _sig(track)
    if tsig:
        best = None
        best_score = None
        for name, f in _ov_trackmap_idx.items():
            nsig = _sig(name)
            shared = len(tsig & nsig)
            if shared == 0:
                continue
            score = (shared, -len(nsig - tsig), len(name))   # comuni, meno extra, piu specifico
            if best_score is None or score > best_score:
                best_score = score
                best = f
        if best is not None:
            return best
    # fallback: vecchio match per sottostringa
    tl = track.lower()
    for name, f in _ov_trackmap_idx.items():
        nl = name.lower()
        if tl in nl or nl in tl:
            return f
    return None


_LAYOUT_LABELS = {
    "Monza Curva Grande Circuit": "Curva Grande",
    "Bahrain Endurance Circuit": "Endurance",
    "Bahrain Outer Circuit": "Outer",
    "Bahrain Paddock Circuit": "Paddock",
    "Circuit de Spa-Francorchamps Endurance": "Endurance",
    "Fuji Speedway Classic": "Classic",
    "Lusail Short Circuit": "Short",
    "Sebring School Circuit": "School",
    "Circuit de la Sarthe Mulsanne": "Mulsanne",
    "24 Heures du Mans 2022": "2022",
    "Paul Ricard - ELMS": "ELMS",
    "Paul Ricard - 1A": "1A",
    "Paul Ricard - 1A-V2": "1A-V2",
    "Paul Ricard - 1A-V2-Short": "1A-V2 Short",
    "Paul Ricard - 3A": "3A",
    "Silverstone International Circuit": "International",
    "Silverstone National Circuit": "National",
    "Silverstone Grand Prix Circuit - ELMS": "ELMS",
    "Circuit of the Americas National": "National",
}


def _track_layout_label(track):
    """Variante di layout leggibile (es. 'Curva Grande', 'Outer'), '' se layout
    principale. Prima dallo stem SVG del trackmap; se manca (24/07:
    l'Endurance non aveva lo SVG stilizzato e il titolo restava senza
    layout) fallback sul NOME della pista per sottostringa."""
    import re
    p = _ov_trackmap_file(track)
    if p:
        stem = re.sub(r"#U([0-9a-fA-F]{4})",
                      lambda m: chr(int(m.group(1), 16)), p.stem)
        lab = _LAYOUT_LABELS.get(stem, "")
        if lab:
            return lab
    tl = (track or "").lower()
    best = ("", "")
    for stem, lab in _LAYOUT_LABELS.items():
        if stem.lower() in tl and len(stem) > len(best[0]):
            best = (stem, lab)
    return best[1]


def _track_layout_key(track):
    """Chiave canonica del layout. Stessa identità usata da creazione, filtro e
    card: _track_layout_key(nome) == _cmap_layout_key(cmap) per la stessa pista."""
    k, _ = _resolve(track)
    return k if k else _norm(track)


_trackmap_white_cache = {}


def _trackmap_white_bytes(track):
    """SVG del tracciato (settings/trackmap) ricolorato in BIANCO, come bytes.
    None se non trovato."""
    p = _ov_trackmap_file(track)
    if not p:
        return None
    key = str(p)
    cached = _trackmap_white_cache.get(key, 0)
    if cached != 0:
        return cached
    try:
        txt = p.read_text(encoding="utf-8", errors="replace")
        txt = txt.replace('stroke="black"', 'stroke="#ffffff"') \
                 .replace('stroke="#000000"', 'stroke="#ffffff"') \
                 .replace('stroke="#000"', 'stroke="#ffffff"')
        import re as _re
        txt = _re.sub(r'stroke-width="[\d.]+"', 'stroke-width="34"', txt)
        out = txt.encode("utf-8")
    except Exception:
        out = None
    _trackmap_white_cache[key] = out
    return out


_TRACK_ROT_JSON = _OV_TRACKMAP_DIR.parent / "trackmap_rot.json"


_track_rot_map = None


def _track_rot(track):
    """Rotazione (gradi) del tracciato per la pista, da settings/trackmap_rot.json
    (chiave = stem SVG del layout). 0 se assente."""
    global _track_rot_map
    if _track_rot_map is None:
        import json
        try:
            _track_rot_map = json.loads(_TRACK_ROT_JSON.read_text(encoding="utf-8"))
        except Exception:
            _track_rot_map = {}
    p = _ov_trackmap_file(track)
    if not p:
        return 0.0
    import re
    stem = re.sub(r"#U([0-9a-fA-F]{4})",
                  lambda m: chr(int(m.group(1), 16)), p.stem)
    try:
        return float(_track_rot_map.get(stem, 0))
    except Exception:
        return 0.0


_OV_TRACKLOGO_DIR = Path(__file__).resolve().parent.parent / "assets" / "tracklogos"


_OV_TRACKMAPS_SVG_DIR = Path(__file__).resolve().parent.parent / "assets" / "trackmaps_svg"


def _track_styled_svg(track):
    """SVG mappa in stile (gradiente + linea centrale) per il LAYOUT, già
    orientata. None se non disponibile."""
    p = _ov_trackmap_file(track)
    if not p:
        return None
    cand = _OV_TRACKMAPS_SVG_DIR / p.name
    return cand if cand.exists() else None


_ALT_LAYOUT_STEMS = {
    "Monza Curva Grande Circuit", "Bahrain Outer Circuit", "Bahrain Paddock Circuit",
    "Circuit de Spa-Francorchamps Endurance", "Circuit de la Sarthe Mulsanne",
    "24 Heures du Mans 2022", "Fuji Speedway Classic",
    "Lusail Short Circuit", "Sebring School Circuit",
}


def _track_is_alt(track):
    """True se la pista è un layout alternativo (variante di un circuito base)."""
    p = _ov_trackmap_file(track)
    if not p:
        return False
    import re
    stem = re.sub(r"#U([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), p.stem)
    return stem in _ALT_LAYOUT_STEMS


_OV_TRACKMAPS_PNG_DIR = Path(__file__).resolve().parent.parent / "assets" / "trackmaps"


_TRACK_PNG_ALIASES = (
    ("monza", "monza"),
    ("sebring", "sebring"),
    ("spa", "spa"), ("francorchamps", "spa"),
    ("sarthe", "lemans"), ("mans", "lemans"),
    ("bahrain", "bahrain"), ("sakhir", "bahrain"),
    ("lusail", "qatar"), ("qatar", "qatar"), ("losail", "qatar"),
    ("americas", "cota"), ("cota", "cota"), ("austin", "cota"),
    ("fuji", "fuji"),
    ("interlagos", "interlagos"), ("carlos pace", "interlagos"), ("sao paulo", "interlagos"),
    ("algarve", "portimao"), ("portimao", "portimao"),
    ("barcelona", "barcelona"), ("catalunya", "barcelona"), ("montmelo", "barcelona"),
    ("paul ricard", "paulricard"), ("ricard", "paulricard"), ("castellet", "paulricard"),
    ("silverstone", "silverstone"),
    ("imola", "imola"), ("enzo e dino", "imola"), ("ferrari", "imola"),
)


def _track_png_file(track):
    """PNG della mappa pista (assets/trackmaps), None se non disponibile."""
    if not track:
        return None
    tl = track.lower()
    for sub, key in _TRACK_PNG_ALIASES:
        if sub in tl:
            p = _OV_TRACKMAPS_PNG_DIR / (key + ".png")
            if p.exists():
                return p
    return None


_OV_LOGO_ALIASES = {
    "monza": "Monza", "imola": "Imola", "enzo e dino": "Imola",
    "bahrain": "Bahrain", "barcelona": "Barcelona", "catalunya": "Barcelona",
    "fuji": "Fuji", "interlagos": "Interlagos", "carlos pace": "Interlagos",
    "silverstone": "Silverstone", "americas": "COTA", "cota": "COTA",
    "mans": "LeMans", "sarthe": "LeMans",
    "daytona": "Daytona", "laguna": "LagunaSeca", "watkins": "WatkinsGlen",
    "road atlanta": "RoadAtlanta", "indianapolis": "Indianapolis",
    "long beach": "LongBeach",
    "paul ricard": "PaulRicard", "ricard": "PaulRicard",
    "lusail": "lusail", "losail": "lusail",
}


def _ov_tracklogo_file(track):
    if not track:
        return None
    tl = track.lower()
    for k, v in _OV_LOGO_ALIASES.items():
        if k in tl:
            p = _OV_TRACKLOGO_DIR / (v + ".svg")
            if p.exists():
                return p
    try:
        for f in _OV_TRACKLOGO_DIR.glob("*.svg"):
            if f.stem.lower() in tl:
                return f
    except Exception:
        pass
    return None


def _track_logo_stem(track):
    """Nome breve del circuito (stem del logo) per un track name, o None."""
    _, logo = _resolve(track)
    if logo:
        return logo
    p = _ov_tracklogo_file(track)          # fallback vecchio
    return p.stem if p else None


def _track_short(track):
    """Nome pista breve e pulito (es. 'Bahrain Paddock Circuit' -> 'Bahrain',
    'Circuit de Spa Francorchamps' -> 'Spa')."""
    t = (track or "").replace("-", " ").strip()
    tl = t.lower()
    table = [
        ("spa", "Spa"), ("bahrain", "Bahrain"), ("monza", "Monza"),
        ("sarthe", "Le Mans"), ("le mans", "Le Mans"), ("lemans", "Le Mans"), ("fuji", "Fuji"),
        ("portim", "Portim\u00e3o"), ("algarve", "Portim\u00e3o"),
        ("barcelona", "Barcelona"), ("catalu", "Barcelona"),
        ("paul ricard", "Paul Ricard"), ("ricard", "Paul Ricard"),
        ("imola", "Imola"), ("interlagos", "Interlagos"),
        ("sebring", "Sebring"), ("atlanta", "Road Atlanta"),
        ("americas", "COTA"), ("cota", "COTA"),
        ("lusail", "Qatar"), ("losail", "Qatar"), ("qatar", "Qatar"),
        ("silverstone", "Silverstone"), ("nurburg", "N\u00fcrburgring"),
        ("daytona", "Daytona"), ("watkins", "Watkins Glen"),
    ]
    for k, v in table:
        if k in tl:
            base = v
            break
    else:
        base = t
    # appende la variante di layout (Mulsanne, Outer, Short, ...) se presente,
    # così la classifica distingue i tracciati dello stesso circuito
    # varianti la cui chiave-corta è basata sul nome (es. SilverstoneInternational,
    # PaulRicard1AV2Short): rilevate PRIMA del suffix generico (che prenderebbe "Short")
    _n = "".join(c for c in (track or "").lower() if c.isalnum())
    lay = ""
    for _k, _v in (("1av2short", "1A-V2 Short"), ("1av2", "1A-V2"),
                   ("1a", "1A"), ("3a", "3A"),
                   ("international", "International"), ("national", "National")):
        if _k in _n:
            lay = _v
            break
    if not lay:
        try:
            from telemetry.db import _layout_suffix
            lay = _layout_suffix(track)
        except Exception:
            lay = ""
    if lay:
        readable = {"CurvaGrande": "Curva Grande"}.get(lay, lay)
        if readable.lower() not in base.lower():
            base = "%s %s" % (base, readable)
    return base


def _decode_stem(s):
    import re
    return re.sub(r"#U([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s or "")


def _layout_key_for_track(track):
    """Chiave-layout (stem SVG decodificato) per una sessione, dal suo nome pista."""
    p = _ov_trackmap_file(track)
    return _decode_stem(p.stem) if p else None


def _layout_key_for_cmap(cmap):
    """Chiave-layout per una card del menu, dal nome file mappa."""
    stem = cmap[:-4] if cmap and cmap.lower().endswith(".svg") else (cmap or "")
    return _decode_stem(stem)


def _cmap_layout_key(cmap):
    """Chiave layout canonica di un cmap (stesso spazio di _track_layout_key)."""
    stem = cmap[:-4] if cmap and cmap.lower().endswith(".svg") else (cmap or "")
    return _norm(_decode_stem(stem))
