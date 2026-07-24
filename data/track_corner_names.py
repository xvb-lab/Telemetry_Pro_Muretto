# -*- coding: utf-8 -*-
"""NOMI UFFICIALI delle curve per circuito (dettati dall'utente 24/07).
Chiave pista = pezzo del nome completo LMU, minuscolo.
Valore = {numero_curva: nome}. I range (T2-T6) sono espansi: ogni
numero del range porta lo stesso nome.

Usi futuri: etichette col nome sulla mappa, ingegnere che chiama la
curva per nome ("occhio a Eau Rouge"), pagina pista."""


def _rng(d, a, b, name):
    for i in range(a, b + 1):
        d[i] = name
    return d


CORNER_NAMES = {
    "fuji": _rng(_rng({1: "TGR Corner", 3: "Coca-Cola", 6: "Advan",
                       10: "Dunlop", 13: "GR Supra", 16: "Panasonic"},
                      4, 5, "100R"), 4, 5, "100R"),
    "americas": _rng(_rng({1: "Big Red", 11: "Hairpin",
                           20: "Ultima curva"},
                          2, 6, "The Esses"), 12, 15, "Stadium"),
    "algarve": {1: "Primeira", 3: "Lagos", 5: "Torre VIP", 8: "Macau",
                10: "Portimao", 11: "Portimao", 13: "Sagres",
                14: "Craig Jones", 15: "Galp"},
    "portimao": {1: "Primeira", 3: "Lagos", 5: "Torre VIP", 8: "Macau",
                 10: "Portimao", 11: "Portimao", 13: "Sagres",
                 14: "Craig Jones", 15: "Galp"},
    "bahrain": {1: "Michael Schumacher"},
    "enzo e dino": _rng(_rng(_rng(_rng(_rng(
        {7: "Tosa", 9: "Piratella"},
        2, 3, "Tamburello"), 4, 5, "Villeneuve"),
        11, 12, "Acque Minerali"), 14, 15, "Variante Alta"),
        17, 18, "Rivazza"),
    "imola": _rng(_rng(_rng(_rng(_rng(
        {7: "Tosa", 9: "Piratella"},
        2, 3, "Tamburello"), 4, 5, "Villeneuve"),
        11, 12, "Acque Minerali"), 14, 15, "Variante Alta"),
        17, 18, "Rivazza"),
    "spa": _rng(_rng(_rng(_rng(_rng(_rng(
        {1: "La Source", 8: "Bruxelles", 9: "Speaker's Corner",
         14: "Campus", 15: "Stavelot", 16: "Paul Frere"},
        2, 4, "Eau Rouge/Raidillon"), 5, 7, "Les Combes"),
        10, 11, "Pouhon"), 12, 13, "Fagnes"),
        17, 18, "Blanchimont"), 19, 20, "Bus Stop"),
    "sarthe": _rng(_rng(_rng(_rng(_rng(_rng(
        {6: "Tertre Rouge", 13: "Mulsanne", 16: "Arnage"},
        1, 3, "Dunlop"), 7, 9, "Chicane Daytona"),
        10, 12, "Chicane Michelin"), 14, 15, "Indianapolis"),
        23, 28, "Porsche Curves"), 29, 30, "Corvette"),
    "monza": _rng(_rng(_rng(
        {3: "Curva Grande", 6: "Lesmo 1", 7: "Lesmo 2",
         11: "Parabolica"},
        1, 2, "Prima Variante"), 4, 5, "Roggia"),
        8, 10, "Ascari"),
    "interlagos": _rng(_rng(_rng(_rng(
        {3: "Curva do Sol", 8: "Laranjinha", 9: "Pinheirinho",
         10: "Bico de Pato", 11: "Mergulho", 12: "Juncao"},
        1, 2, "S do Senna"), 4, 5, "Descida do Lago"),
        6, 7, "Ferradura"), 13, 15, "Subida dos Boxes"),
    "carlos pace": _rng(_rng(_rng(_rng(
        {3: "Curva do Sol", 8: "Laranjinha", 9: "Pinheirinho",
         10: "Bico de Pato", 11: "Mergulho", 12: "Juncao"},
        1, 2, "S do Senna"), 4, 5, "Descida do Lago"),
        6, 7, "Ferradura"), 13, 15, "Subida dos Boxes"),
    "sebring": _rng(_rng(
        {7: "Hairpin", 10: "Cunningham", 13: "Tower Turn",
         17: "Sunset Bend"},
        3, 5, "The Esses"), 15, 16, "Le Mans Curve"),
    "daytona": _rng(_rng(
        {3: "Pedro Rodriguez", 5: "West Horseshoe"},
        1, 2, "International Horseshoe"), 8, 9, "Bus Stop"),
    "laguna seca": {2: "Andretti Hairpin", 8: "The Corkscrew",
                    9: "Rainey Curve", 11: "Mario Andretti"},
    "silverstone grand prix": _rng(_rng(
        {1: "Abbey", 2: "Farm", 3: "Village", 4: "The Loop",
         5: "Aintree", 6: "Brooklands", 7: "Luffield", 8: "Woodcote",
         9: "Copse", 15: "Stowe", 16: "Vale"},
        10, 14, "Maggotts/Becketts"), 17, 18, "Club"),
    # layout corto: stessi nomi del GP, numerazione National
    "silverstone national": {1: "Copse", 2: "Maggotts", 3: "Becketts",
                             4: "Brooklands", 5: "Luffield",
                             6: "Woodcote"},
    "barcelona": _rng(_rng(
        {3: "Renault", 4: "Repsol", 5: "Seat", 7: "Wurth",
         8: "Campsa", 9: "La Caixa", 10: "Banc Sabadell",
         12: "Europcar"},
        1, 2, "Elf"), 13, 14, "RACC"),
    "paul ricard": _rng(_rng(
        {3: "Hotel", 4: "Camp de Bendor", 5: "Sainte Baume",
         10: "Signes", 11: "Le Beausset", 12: "Bendor",
         14: "Virage du Pont"},
        1, 2, "S de la Verrerie"), 8, 9, "Chicane Nord"),
}


def corner_name(track, num):
    """Nome ufficiale della curva num per la pista, o None."""
    n = (track or "").lower()
    for k, d in CORNER_NAMES.items():
        if k in n:
            return d.get(int(num))
    return None
