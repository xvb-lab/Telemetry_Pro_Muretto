# Telemetry_Pro_Muretto

Ingegnere di gara (muretto) e telemetria per **Le Mans Ultimate** — progetto
per la community piloti. Ricostruzione **0.3b** in corso.

*Race engineer ("muretto") and telemetry app for Le Mans Ultimate — a driver
community project. **0.3b** rebuild in progress.*

---

## Cos'è / What it is

Un **muretto** che legge i dati reali di LMU e ti parla via radio: benzina,
energia ibrida, gomme, soste, meteo, bandiere, tempi e settori. E, novità
0.3b, **radio a due vie**: puoi chiedergli tu ("muretto, quanta benzina?").

- **Dati solo da LMU, 0% invenzioni.** Se un dato manca, tace.
- **Parlato multilingua** (🇮🇹 IT · 🇬🇧 EN · 🇪🇸 ES · 🇫🇷 FR) — 3 voci ingegnere.
- **Overlay** su schermo separati (mappa, dashboard, bandiere, standings…).

## Architettura / Architecture

Tre processi separati, così non si contendono le risorse:

| Processo | Entry | Ruolo |
|---|---|---|
| APP / UI | `main.py` | interfaccia, config, launcher |
| MURETTO | `engineer/run_engineer.py` | il cervello ingegnere (voce) |
| OVERLAY | `overlays/run_overlay.py <nome>` | overlay su schermo |
| *(condiviso)* | `core/` | lettura LMU, config |

Dettagli e regole: **`docs/bibbia.md`**. Registro modifiche: `docs/diario.md`.

## Requisiti / Requirements

- Le Mans Ultimate con shared memory + REST attivi (porta 6397)
- Python 3.10, PySide6
- Connessione internet (voce edge-tts + riconoscimento vocale online)

## Avvio / Run

```
pythonw main.py
```

---

*Work in progress. Vedi `docs/` per lo stato e la roadmap.*
