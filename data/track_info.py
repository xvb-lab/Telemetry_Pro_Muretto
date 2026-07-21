# -*- coding: utf-8 -*-
"""Anagrafica piste: lunghezza (m), numero curve, anno di apertura.
Chiave = 'base' pista (prima voce di _TRACKS), minuscolo. Usata dalla pagina
pista dedicata (info a sinistra). Dati raccolti per i circuiti WEC/ELMS/IMSA.
"""

# base -> (lunghezza_m, curve, anno)
TRACK_INFO = {
    # ── WEC ──
    "lemans":        (13626, 38, 1923),
    "spa":           (7004, 20, 1921),
    "fuji":          (4563, 16, 1966),
    "bahrain":       (5412, 15, 2004),
    "silverstone":   (5891, 18, 1948),
    "cota":          (5513, 20, 2012),
    "interlagos":    (4309, 15, 1940),
    "shanghai":      (5451, 16, 2004),
    "nurburgring":   (5148, 17, 1984),
    "sebring":       (6019, 17, 1950),
    "mexico":        (4304, 17, 1959),
    "portimao":      (4684, 15, 2008),
    "imola":         (4909, 22, 1953),
    "lusail":        (5380, 16, 2004),
    "monza":         (5793, 11, 1922),
    # ── ELMS (extra) ──
    "paulricard":    (5771, 15, 1970),
    "barcelona":     (4657, 14, 1991),
    "redbullring":   (4318, 10, 1969),
    "hungaroring":   (4381, 14, 1986),
    "estoril":       (4182, 13, 1972),
    "donington":     (4020, 12, 1931),
    "jarama":        (3850, 16, 1967),
    "vallelunga":    (4085, 14, 1951),
    "zolder":        (4011, 10, 1963),
    "mugello":       (5245, 15, 1974),
    "aragon":        (5344, 18, 2009),
    # ── IMSA (extra) ──
    "daytona":       (5730, 12, 1959),
    "longbeach":     (3167, 11, 1975),
    "lagunaseca":    (3602, 11, 1957),
    "midohio":       (3634, 13, 1962),
    "watkinsglen":   (5552, 11, 1956),
    "mosport":       (3957, 10, 1961),
    "limerock":      (2414, 7, 1957),
    "roadamerica":   (6515, 14, 1955),
    "vir":           (5260, 17, 1957),
    "roadatlanta":   (4088, 12, 1970),
    "detroit":       (2654, 9, 1982),
    "indianapolis":  (3925, 14, 1909),
    "kansas":        (3810, 6, 2001),
}


# base -> nome COMPLETO/ufficiale (per il titolo della pagina pista)
TRACK_NAME = {
    "lemans":        "Circuit de la Sarthe",
    "spa":           "Spa-Francorchamps",
    "fuji":          "Fuji Speedway",
    "bahrain":       "Bahrain International Circuit",
    "silverstone":   "Silverstone Circuit",
    "cota":          "Circuit of the Americas",
    "interlagos":    "Autódromo José Carlos Pace",
    "shanghai":      "Shanghai International Circuit",
    "nurburgring":   "Nürburgring GP-Strecke",
    "sebring":       "Sebring International Raceway",
    "mexico":        "Autódromo Hermanos Rodríguez",
    "portimao":      "Algarve International Circuit",
    "imola":         "Autodromo Enzo e Dino Ferrari",
    "lusail":        "Lusail International Circuit",
    "monza":         "Autodromo Nazionale Monza",
    "paulricard":    "Circuit Paul Ricard",
    "barcelona":     "Circuit de Barcelona-Catalunya",
    "redbullring":   "Red Bull Ring",
    "hungaroring":   "Hungaroring",
    "estoril":       "Autódromo do Estoril",
    "donington":     "Donington Park",
    "jarama":        "Circuito del Jarama",
    "vallelunga":    "Autodromo di Vallelunga",
    "zolder":        "Circuit Zolder",
    "mugello":       "Mugello Circuit",
    "aragon":        "MotorLand Aragón",
    "daytona":       "Daytona International Speedway",
    "longbeach":     "Long Beach Street Circuit",
    "lagunaseca":    "WeatherTech Raceway Laguna Seca",
    "midohio":       "Mid-Ohio Sports Car Course",
    "watkinsglen":   "Watkins Glen International",
    "mosport":       "Canadian Tire Motorsport Park",
    "limerock":      "Lime Rock Park",
    "roadamerica":   "Road America",
    "vir":           "Virginia International Raceway",
    "roadatlanta":   "Michelin Raceway Road Atlanta",
    "detroit":       "Detroit Street Circuit",
    "indianapolis":  "Indianapolis Motor Speedway",
    "kansas":        "Kansas Speedway",
}


# base -> codice paese ISO (per la bandiera, assets/flags/<cc>.svg)
TRACK_COUNTRY = {
    "lemans": "fr", "paulricard": "fr",
    "spa": "be", "zolder": "be",
    "fuji": "jp", "bahrain": "bh", "lusail": "qa",
    "silverstone": "gb", "donington": "gb",
    "interlagos": "br", "shanghai": "cn", "nurburgring": "de", "mexico": "mx",
    "portimao": "pt", "estoril": "pt",
    "imola": "it", "monza": "it", "vallelunga": "it", "mugello": "it",
    "barcelona": "es", "jarama": "es", "aragon": "es",
    "redbullring": "at", "hungaroring": "hu", "mosport": "ca",
    "cota": "us", "sebring": "us", "daytona": "us", "longbeach": "us",
    "lagunaseca": "us", "midohio": "us", "watkinsglen": "us", "limerock": "us",
    "roadamerica": "us", "vir": "us", "roadatlanta": "us", "detroit": "us",
    "indianapolis": "us", "kansas": "us",
}


def track_info(base):
    """(lunghezza_m, curve, anno) per la base pista, o None."""
    if not base:
        return None
    return TRACK_INFO.get(str(base).strip().lower())


def track_country(base):
    """Codice paese ISO della pista (per la bandiera), o None."""
    if not base:
        return None
    return TRACK_COUNTRY.get(str(base).strip().lower())


def track_name(base):
    """Nome completo/ufficiale della pista, o None."""
    if not base:
        return None
    return TRACK_NAME.get(str(base).strip().lower())
