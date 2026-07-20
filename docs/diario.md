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

**Base di conoscenza di dominio (docs/) + calcolatore strategico.**
- Documenti autorevoli catturati (dall'utente, via ricerca): `dati_lmu.md`
  (VE/benzina per classe, finestre gomme/freni/motore, tempi box),
  `logica_strategia.md` (dry/wet/crossover, risparmio stint, loop 3 flussi,
  profilo per classe), `consigli_muretto.md` (coaching), `messaggi_radio.md`
  (vocabolario IT/EN), `numeri_strategia.md` (costanti: pit delta, wear+cliff,
  consumi, L&C, meteo, FCY, mescole).
- `core/pit_math.py`: calcolatore PURO deterministico dai numeri — `pit_delta`,
  `fcy_pit_saving`, `tyre_wear_per_lap`, `laps_to_cliff`, `double_stint_verdict`,
  `undercut_gain`, `consumption_per_lap`, `compound_for_asphalt`. Testato tutto.
  Sta sopra `lmu_live`, non tocca il cervello. Costanti = riferimento/fallback;
  in gara vince il dato vivo di LMU.

**Loop muretto AMPLIATO — parla tutti i moduli collaudati.**
- `run_engineer._emit_all`: dispatcher che chiama l'intero set di moduli-voce
  del cervello (RACE: flags/damage/aero/contact/engine/battery/wet_tyre/pit_ack ·
  STRATEGY: race_plan/box/strategy_check/weather/extra_stop/status/autofuel/
  position/pos/countdown · PERFORMANCE: lap_time/lap_feedback/tyre_life/grip/
  temp/gap/traffic/lock/pace/tlimits/rain/wet_patches). Ognuno difensivo +
  try/except: un modulo che sbaglia non ferma il muretto. Aggiunto `glitch`
  guard (salta i tick strappati) e `update_situation` prima di tutto.
- Testato su raw di gara sintetico: parlano piano/soste/box/status/countdown coi
  ruoli e voci giusti, nessun crash. I moduli muti (flags/gap/traffico/temp/
  tlimits) aspettano il glue con lo SCORING (rivali/flags/tyre_temp/brake_temp).
- NB: soglie collaudate NON toccate (es. tyre "dead" ~70% residuo); resta aperto
  il flag scala usura / core-temp vs docs (`target_pitwall.md`).

**Conferme dalla struct Shared Memory S397 (2026-07-20).**
- La spec C# di S397 conferma che il nostro reader (`pyLMUSharedMemory`) legge i
  buffer/campi giusti (`$rFactor2SMMP_Scoring/Telemetry/Extended$`). Non
  ri-trascritta (ridondante col reader che gira).
- ✅ **RISOLTO flag usura gomme**: `mWear` 1.0=nuovo→0.0=distrutto, *"drop-off
  serio sotto 0.70"* → la soglia collaudata del cervello (dead ~70%) è GIUSTA per
  S397. Bene NON averla sovrascritta. (Il "45% usato" dei docs era altra convenzione.)
- Canali disponibili confermati oltre le attese: `mUnfilteredThrottle/Brake`
  (pedali → coaching), `mRotation` (wheelspin/slip → voce VE sprecata),
  `mRideHeight`, `mBatteryCharge` (=MJ VE). Alcuni "setup-only" sono in realtà live.
- APERTO ancora: conflitto finestre CORE gomme (`target_pitwall` vs `dati_lmu §2`).

**Scoring glue — bandiere/gap/traffico VIVI.**
- `run_engineer`: agganciato lo SCORING al `raw` da `SharedMemory.instance()`:
  `raw["flags"]=mem.flags()` (+ checkered/penalties), `raw["rivals"]=mem.rivals()`.
- Chiavi verificate sul cervello (rivals letto 5×, flags 2×) prima di agganciare.
- **Provato LIVE (LMU in sessione)**: flags/rivals tornano dati veri e i moduli
  parlano — "Gialla avanti, 400" (`flags_call`) e "Richard Lietz sta a 0,3"
  (`gap_call`, rivale per nome). Nessun crash. Sbloccati flags/gap/traffico/pos.

**Contatti: "con chi mi sono toccato" (richiesta utente).**
- `core/shared_memory.nearest_car()`: auto più vicina lungo la pista di QUALSIASI
  classe (nome/classe/gap_m con segno). Glue: `raw["nearest_car"]`.
- `brain.contact_call`: all'urto cattura il più vicino, ma solo se **≤20 m** (un
  pilota, non un muro). Dopo 3 s: pulito → "Toccato con {name}, nessun danno";
  con danno → "Ti sei toccato con {name}" (l'entità la dice damage/aero). Muro →
  generico senza nome. Nuovi msg `contact_who`/`contact_ok_who` (it/en/es/fr),
  ruolo spotter. Testato: pulito/danno/muro OK; nearest_car live dà rivale reale.

**Pagina Opzioni + beep radio + impostazioni (richiesta utente).**
- `main.py` ora è una **pagina Opzioni**, non auto-start: interruttore
  **Ingegnere ON/OFF** (avvia/ferma il processo muretto, ricorda lo stato) +
  lingua, volume voce, beep on/off, **ritardo tono radio** (0-5 s, def 2),
  chiama-tempi-ogni-giro, tempi-con-decimi. Scrive `settings/engineer_cfg.json`
  (gitignorato: stato per-macchina). L'app È il launcher.
- **Beep radio** dal vecchio: `assets/audio/radio.mp3` (+ pagebeep.wav). `Voice`
  esteso: `speak(text, voice, beep)` → suona il tono + attende il ritardo PRIMA
  della voce (nel thread worker, non blocca il loop). `set_beep`/`set_tone_delay`.
- `run_engineer`: legge le opzioni e le applica alla voce (volume/beep/ritardo),
  **ri-lette live ogni ~2 s** (cambi dalle Opzioni senza riavviare); passa il
  `beep` del messaggio a `speak`.
- Provato: sintassi OK, beep suona (radio.mp3+ritardo+voce), e **l'app avvia da
  sé il muretto** all'apertura (app PID + muretto PID, una sola istanza).

**Fix posizioni: solo al traguardo (richiesta utente).**
- `brain.pos_call`: prima annunciava al primo cambio di `class_place` a metà giro
  (solo cooldown 8s). Ora **gate sul traguardo**: valuta la posizione una volta
  per giro, al cambio di `laps_completed`, confrontando con quella del giro
  precedente. Mid-lap tace. Testato: mid-lap muto, al traguardo annuncia
  guadagno/perdita, invariata muta.

**FIX mitragliata: ricollegato il `sanity_filter` (come la v2).**
- Errore mio: in `_emit_all` chiamavo i moduli e parlavo l'output GREZZO, saltando
  il muro di sanità → il muretto mitragliava frasi tutte insieme (feedback utente:
  "parla a mitragliatrice, informazioni inutili tutte insieme").
- Fix: ogni output di modulo ora passa da `brain.sanity_filter(out, raw)` (come
  faceva `engineer_tab._emit` in v2). Riattiva: **warm-up 5s** (niente raffica
  d'apertura sullo stato ereditato), **leggi di stato** (muta gap/pos/traffico in
  corsia o con pit chiamato), e l'**`_arbiter`**: stesso codice muto entro 25s,
  **max 3 info/20s** (warn/critical passano). Testato: warm-up/budget/legge OK.
- Nota gate contesto: `gap_call` (undercut) e `strat_extra_stop` si gate già da
  soli (rivale ai box / gomme ≤82% + gap che copre). Se restano frasi fuori
  contesto, aggiungere il gate al modolo specifico su feedback in pista.

**Gestore radio v2 portato (priorità + preemption gialla + riaccodo).**
- `engineer/radio.py` `RadioManager`: coda a **tier** (0 sicurezza … 4 coaching),
  scadenza **TTL** per tier, **mutua esclusione per gruppo** (consumi/gomme/
  pioggia/temp), cadenza minima 5s, no-repeat 20s. **Una alla volta.**
  **PREEMPTION GIALLA**: se parla qualcosa e arriva `local_yellow`/`yellow_flag`
  (e il corrente non è già sicurezza) → `vox.interrupt()` taglia, il messaggio
  interrotto viene **RIACCODATO**, e la gialla parla subito. Costanti tier/gruppi
  portate fedeli da `engineer_overlay` v2.
- `core/voice.py`: aggiunti `busy()` e `interrupt()` (taglia il playback MCI +
  svuota coda) + `_speaking`/`_abort_evt` (ritardo tono interrompibile).
- `run_engineer`: i moduli → `sanity_filter` → `_collect()` (lista candidati) →
  `radio.push()` → `radio.tick(vox)`. Non più _speak diretto (niente FIFO cieco).
- Testato: priorità (BOX prima del gap), preemption gialla (interrupt + riaccodo).

**Confronto v2↔v3 + port funzioni v2 mancanti.**
- Analisi: v3 (brain) 47 metodi, v2 59. Novità v3 (già presenti): autofuel_call,
  pace_notes_call, tlimits_call, curve apprese. Coperte in v3: strat_plan→race_plan,
  tyre_advice→wet_tyre/rain_live, best_lap_call→lap_feedback, yellow_call (no SC),
  update_situation (stato letto inline nel sanity_filter).
- DA PORTARE dalla v2 (mancanti): **sector_delta** (dove perdo, P1) ✅ FATTO,
  poi conditions_call, box_last_call, box_timing_call, pit_exit_traffic,
  wet_sector_map, fast_class_call.
- `sector_delta` portato (adattato: no seeding da settori appresi): a fine giro
  confronta i 3 settori col migliore, se perdi ≥0.18s dice dove; solo asciutto;
  cadenza 2 giri. Agganciato in `_collect` (spotter) + `raw["lap_time"]` nel glue.
  Testato: "perdi 5 decimi nel settore 2", muto sul bagnato.

**Bandiera wet sulle soglie VERE S397 (regola: soglia vera > interpretazione).**
- `rain_live` ora legge la **traiettoria ideale** (`wetness_min`, non la media) e
  usa il crossover reale S397: asciutto <0.15, zona grigia 0.15-0.20 (avviso
  "arriva pioggia"), **bagnato >0.20** con slick = ordine `rain_box_now`.
  Prima era 0.25 sulla media (mia interpretazione). Testato: 0.17→avviso,
  0.22→box wet. Regola fissa salvata in memoria (collaudato + soglie vere).

**Portate altre 3 funzioni v2** (con helper `_class_readable`/`_CLASS_READABLE`,
`_fmt_gap`): `fast_class_call` (pre-blu, classe veloce in arrivo), `pit_exit_traffic`
(traffico proiettato al rientro box), `wet_sector_map` (settore più bagnato).
Agganciate in `_collect`, testate. Con sector_delta = **4 di 6** funzioni v2 fatte.

**Beep radio più forte (richiesta utente).**
- `radio.mp3` era basso (picco 0.386 = 38%). Amplificato con soundfile+numpy:
  normalizzato a picco 0.97 (×2.51) + spinta soft-clip tanh ×1.5 → **RMS ×3**,
  senza distorsione dura. Salvato `assets/audio/radio.wav`. `run_engineer._BEEP`
  ora preferisce il WAV (fallback mp3). L'MCI lo suona uguale.

**FIX bug: muretto parlava fuori sessione + pit_exit a raffica.**
- Il muretto parlava anche nei menu/browser (shared memory piena di dati
  STANTII). Ora il loop parla **solo se `mem.is_on_track()`** (collaudato: True
  solo in pista realtime, False menu/pausa/replay). Fuori sessione = silenzio.
- `pit_exit_traffic` sparava "14 auto in arrivo" a ogni giro: aggiunto gate
  **pit_state != 0** (parla solo se un pit è chiamato/in corso). Testato.

**Da fare (mattoni, in ordine).**
0. Restano 2 funzioni v2, più delicate (accoppiate a box_call): `box_last_call`
   (rinforzo box all'ingresso corsia) e `box_timing_call` (anticipa/ritarda sosta
   per traffico) → servono: allineare lo stato box_call v3 (`_box_reason`) +
   creare i msg `box_timing_*`. Più `conditions_call` (verificare il suo msg).
1. Mappare `tyre_temp`/`brake_temp` (dal reader: carcass/inner/brk) → attiva
   `temp_call`; aggiungere `session_rules` se serve.
2. Collegare `pit_math` come voci nuove (undercut, FCY, mescola) senza toccare
   il collaudato; allineare soglie coi docs dove concordato.
3. Provare LIVE in una gara più lunga (piano + consumo + tutti i moduli).
4. Radio a 2 vie: STT online + wake word + intent deterministico.

**A FINE PROGETTO (release per i team) — da NON dimenticare:**
- **Docs BILINGUE** (IT + EN): tradurre bibbia/guida per i team internazionali.
- **Guida configurazione LMU**: come abilitare il plugin/shared memory + REST
  (porta 6397) perché il muretto legga i dati. Prerequisiti passo-passo.
- **Carrellata/overview**: una panoramica leggibile delle varie sezioni (cosa fa
  ogni parte, come si usa) — README esteso / guida utente.
