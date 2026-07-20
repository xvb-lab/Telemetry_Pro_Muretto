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
- Repo git: `git init` pulito, `.gitignore` + `README.md` bilingue (IT/EN),
  primo commit 0.3b su `main`. Remote `origin` =
  github.com/xvb-lab/Telemetry_Pro_Muretto (**pubblica**), push ok. Prima del
  push: scan segreti pulito, nessun file >1MB, `__pycache__`/`.claude` esclusi.

**Strategia — il cuore (`core/strategy.py`).**
Estratto `lmu_live` dal vecchio `recorder.py` monolitico, **logica invariata**
(regola 0%), in un modulo pulito e autonomo per il processo muretto:
- fetch REST: `fetch_pit_menu` (tabella VE %→giri), `fetch_strategy_usage`
  (storia giro-per-giro), `fetch_refuel_strategy` (vincolo ENERGY/FUEL +
  obiettivo sosta).
- puro/deterministico: `usage_per_lap` (consumo reale sull'arco più lungo,
  immune alla quantizzazione a byte), `measured_per_lap` (frazione → %/litri),
  `build_lmu_live` (constraint/per_lap/autonomia/laps_needed/target_pct).
- `StrategyFeed`: thread dedicato **non-bloccante** (menu+vincolo ogni ~3s,
  usage al cambio giro), produce `lmu_live` su richiesta con la fisica fresca.
- Testato deterministicamente: ENERGY misurato, fallback tabella pit menu,
  FUEL in litri, conversione misurata, arco usage — tutti OK. Senza rete non
  inventa (constraint/per_lap None) e non crasha.

**Voce + lingue (`core/voice.py` + `settings/engineer_msgs.json`).**
Portati dal backup, nessuna dipendenza interna (solo stdlib + backend TTS).
- Backend **edge-tts** (neurale, online) installato e funzionante: frase IT
  ("Muretto pronto…") e EN ("Engineer online…") sintetizzate ed eseguite senza
  errori funzionali. Multilingua confermato cambiando `voice_name` + `lang`.
- SAPI/pyttsx3 non installati: non servono (tutto online).
- Nota: i warning "Event loop is closed" (asyncio ProactorEventLoop + edge_tts)
  compaiono solo su stderr a chiusura, e SOLO se avvii con `python.exe`. L'app
  gira con `pythonw` → stderr scartato → invisibili. Codice voce lasciato
  invariato (collaudato).

**Cervello (`engineer/brain.py`) — port dell'INTERO cervello collaudato.**
Scelta: invece di reinventare i pezzi, portato tutto `engineer.py` (v3) +
dipendenze in `core/` — la strada più veloce e affidabile per lasciare la cosa
*completa* (l'utente ha poco tempo).
- Dipendenze portate in `core/`: `classes.py` (class_tag), `muretto.py`
  (piano, autonomo), `paths.py`, `engineer_learn.py` (profili appresi),
  `config.py`, `utils.py`.
- Staccato dal vecchio overlay: nuovo `core/engineer_cfg.py` (opzioni muretto
  da `settings/engineer_cfg.json`) al posto di `engineer_overlay._load_cfg`.
- `Engineer(lang)` importa e si istanzia: 283 messaggi caricati, metodi
  strategia presenti (race_plan, box_call, strategy_check, countdown,
  status_update). I metodi sono difensivi (try/except, `[]` se manca il dato)
  → coerente con "tace se manca".

**Loop muretto + ruoli/voci — IL MURETTO PARLA LA STRATEGIA.**
- `engineer/roles.py`: mappa codice-messaggio → ruolo (RACE/STRATEGY/
  PERFORMANCE) + tabella 12 voci edge-tts (3 ruoli × 4 lingue), portate fedeli
  dal vecchio `engineer_overlay.py`.
- `core/voice.py`: aggiunto `speak(text, voice=...)` in modo additivo (la voce
  viaggia in coda con la frase) così i 3 ruoli non si accavallano. Stringa
  semplice e sentinella `None` restano identiche (retro-compat).
- `engineer/run_engineer.py`: loop live (reader + StrategyFeed + brain + voce,
  con glue `raw` = fisica + `lmu_live` + `lmu_strat`) e modalità `--demo`.
- **Demo eseguita e verificata**: il muretto (voce STRATEGY, Diego) dice il
  piano gara ("93 giri, col pieno 68 giri, 2 stint 1 sosta"), l'arco meteo
  ("asciutto fino al 58, poi bagnato"), le soste pianificate, e il coaching
  consumo vs target (over/ok/push). Catena completa cervello→ruolo→voce OK nel
  processo separato.
- Sbavatura nota: "1 soste" → "1 sosta" (plurale), cosmetica, da limare.

**PROVA LIVE — il muretto parla coi dati veri di LMU.**
- Bug trovato: `reader.py`/`shared_memory.py` dipendono da **`pyLMUSharedMemory`**
  (mappatura shared memory di LMU, solo ctypes+mmap) che NON avevo portato →
  `reader.read()` tornava vuoto anche in pista. Portata `pyLMUSharedMemory/`
  (__init__ + lmu_data.py) nella root.
- Dopo il fix, `reader.read()` in sessione dà **99 campi reali** (driver, GT3,
  session_type 10, race_remaining, fuel 93/120, est_lap 54.9s...).
- Loop live provato in pista: ha detto (voce RACE ENGINEER) "Manca un minuto
  alla fine / Siamo all'ultimo minuto" (`countdown`, sessione a fine tempo).
  Catena reader→brain→ruolo→voce OK dal vivo. Piano/consumo non uditi solo
  perché la sessione di test stava finendo (serve una gara più lunga).

**Da fare (mattoni, in ordine).**
1. Provare piano gara + consumo vs target in una gara LIVE più lunga.
2. Radio a 2 vie: STT online + wake word + intent deterministico.
3. Resto del cervello: settori "dove perdo", ecc.
