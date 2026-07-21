"""telemetry/ — App telemetria LMU integrata (motore live + recorder + UI).

Gira nello stesso processo-app del resto dell'overlay (multi-processo),
nessun exe separato. Sotto-moduli:
- strategy.py : logica stint/pit/strategia con verifica di fattibilità
- db.py       : storage SQLite per-evento (session/laps/sectors/samples)
- reader.py   : lettura completa shared memory + REST (tutti i canali)
- recorder.py : campionatore live -> aggregati giro/settore + tracce -> db
"""
