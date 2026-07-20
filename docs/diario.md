# Diario di sviluppo — LMU Telemetry Pro 0.3b

Registro cronologico delle modifiche (più recente in alto). Ogni voce: cosa,
perché. Si aggiorna a ogni intervento, insieme alla bibbia (`docs/bibbia.md`).

---

## 2026-07-20 — Avvio ricostruzione 0.3b

**Contesto / perché la ricostruzione.**
La v3 andava a scatti: UI + telemetria + muretto in **un solo processo** si
contendevano CPU/GIL. Diagnosi con py-spy: `list_sessions` (apriva tutti i
408 file `.lmtel` = 258 MB ogni 4 s) teneva il GIL ~600 ms → freeze
periodici della UI. Fix applicato alla vecchia app (cache metadati per file
in `db.py`, 622 ms → 68 ms) ma la lezione è architetturale → 0.3b nasce a
**processi separati**. Vecchia root azzerata dall'utente; backup completo
salvato in `..\Telemetry_Pro_BACKUP_2026-07-20_203351\` (521 MB, con `.git`).

**Decisioni di progetto (vedi bibbia).**
- 3 processi separati: UI (`main.py`) / muretto (`engineer/`) / overlay
  (`overlays/`) + `core/` condiviso.
- Muretto **parlato-only** (niente overlay/testo per lui).
- **Multilingua 4 lingue** (IT/EN/ES/FR), 3 voci per ruolo via edge-tts.
- **Tutto online** (campionati sempre online): edge-tts + STT cloud.
- **Radio a 2 vie**: pilota parla al muretto. 3 modalità (solo radio /
  push-to-talk / sempre in ascolto). Wake word: muretto / engineer / muro /
  ingénieur (modificabile in opzioni).
- Intent **deterministico** a parole chiave, mai LLM: risponde solo dal dato
  reale, se manca dice che non ce l'ha.

**Fatto.**
- `main.py`: scheletro app/UI — finestra "LMU Telemetry Pro 0.3b" con icona,
  `AppUserModelID` per l'icona in taskbar, agganci launcher `start_muretto` /
  `start_overlays`. Avvio con `pythonw.exe` (niente console; per debug si usa
  `python.exe`).
- Struttura cartelle: `core/ ui/ engineer/ overlays/ settings/ docs/` con
  `__init__.py` e stub eseguibili (`engineer/run_engineer.py`,
  `overlays/run_overlay.py`) — verificati, partono puliti.
- `assets/` ordinato per tipo: `icons/` (icona app importata), `audio/`,
  `img/`.
- Dati (mattone 1): portati in `core/` i due lettori collaudati —
  `shared_memory.py` (stream scoring) e `reader.py` (`TelemetryReader`, stream
  fisica: VE/fuel/RPM/gear/temp). Import + `read()` testati OK.
- Documentazione: scritta `docs/bibbia.md` (riferimento unico) e questo diario.

**Da fare (mattoni, in ordine).**
1. Estrarre `lmu_live` (derivazione strategica 0%) dal vecchio `recorder.py`
   monolitico → `core/`.
2. Voce + lingue: portare `core/voice.py` + `settings/engineer_msgs.json`.
3. Radio a 2 vie: STT online + wake word + intent deterministico.
4. Cervello: moduli decisionali, priorità 1 = settori "dove perdo"
   (`sector_panel_data`).
