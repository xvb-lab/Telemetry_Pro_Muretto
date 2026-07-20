"""engineer — il MURETTO (l'ingegnere di gara), processo separato.

Il cervello che legge i dati LMU (via core), decide e parla. Gira nel suo
processo, isolato da UI e overlay, cosi' non si contendono CPU/GIL.
Regole fisse (vedi bibbia): dati SOLO da LMU, se manca tace; consigli non
ordini; state-aware; anti-ripetizione.
"""
