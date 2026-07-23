# Diario di sviluppo — LMU Telemetry Pro 0.3b

Registro cronologico delle modifiche (più recente in alto). Ogni voce: cosa,
perché. Si aggiorna a ogni intervento, insieme alla bibbia (`docs/bibbia.md`).

---

## 2026-07-22 — Race Control FIA (wec26flag): design bandiere, messaggi, priorità

**Ambito Race Control: SOLO player.** Deciso di NON mostrare investigation/penalità
degli altri piloti (troppa roba → il pilota si distrae). Le **penalità degli altri**
andranno nel **futuro Standings overlay**, non qui.

**Bandiere decise (bandiera = STATO, resta finché la condizione è vera).**
- Con immagine FIA (PNG in `assets/racecontrol/`): GREEN, BLUE, CHEQUERED, BLACK.
- Disegnate stile FIA (head `rc_head.png` + striscia colorata): RED FLAG, RED
  "PITS CLOSED", YELLOW SECTOR (solo se giallo locale entro **500m** davanti,
  come la dash). FCY rimossa (in LMU **non esiste** la full course yellow).

**Track limits del player — 5 livelli a COLORE (LMU color-coding).** L'utente è
"abituato ai colori" di LMU, quindi due **quadri colorati** (niente "!"):
- 🟩 verde = sotto warning (ok) · 🟨 giallo / 🟧 arancio / 🟥 rosso =
  **"TRACK LIMITS UNDER REVIEW"** (il colore sale con la vicinanza alla penalità) ·
  🟪 viola = **"TRACK OFF"** (strict limits: 4 ruote oltre la linea → giro
  cancellato all'istante).
- Soglie dai dati veri: `mTrackLimitsSteps` / `StepsPerPoint` / `StepsPerPenalty`.

**Penalità del player — frasi stile direttore di gara (EN/FIA).** Box **rosso,
testo bianco**. Motivo LMU **verbatim** + "FOR", es. `DRIVE-THROUGH FOR OUT OF
POSITION`, `10s STOP & GO FOR PIT LANE SPEEDING`.

**Scoperta dati penalità (dal trace `UserData/Log/trace*.txt`).** Verificato il
formato vero: `Local penalty et=<t> <n0> <n1> <n2> <n3> "MOTIVO"`.
- **n0** = DRIVE THROUGH · **n1** = STOP & GO (secondi) · **n2/n3** = +secondi
  (tempo aggiunto, es. rolling start).
- **L'"out line" NON ha stringa propria**: in LMU è loggata come motivo
  **`"Out of position"`** (`1 0 0 0` = drive through) — è quella che la nostra
  Race Control ha già catturato in gara. Motivi reali catalogati: `Track Limits`,
  `Speeding`, `Speeding In Pitlane`, `Exiting Pits Under Red`, `Driving Too Slow`,
  `Out of position`, `Erratic driving`, `Unsportsmanlike Driving`, `Exceeded
  energy allowance limit`. `core/race_control.py` decodifica già i 4 campi così.

**PRIORITÀ (alto = vince) e regole di coda.**
1. RED/PITS CLOSED · 2. CHEQUERED · 3. BLACK · 4. BLUE · 5. YELLOW SECTOR ·
   6. GREEN · 7. Penalità · 8. Track limits · 9. Slow car in sector.
- Bandiere = **stati** con precedenza sui messaggi. Messaggi = **eventi** in coda,
  mostrati **uno dopo l'altro per priorità**, ognuno **10s** (deciso 22/07).
- **Se arriva GIALLO o BLU mentre un messaggio è a schermo → il messaggio torna
  in coda (timer azzerato, riparte da 10s pieni)** e la bandiera prende il banner;
  a bandiera spenta la coda riparte. A pari livello: ordine d'arrivo.
- **GREEN FLAG**: appare **5s** una volta (se non sostituita nel frattempo); tanto
  LMU la richiama. Track limits: i 5 livelli a colore sono **definitivi** (nessun
  messaggio "conferma" extra).

**Rolling start / auto-pit — ricerca dati (per piloti SENZA HUD LMU).**
- **Non esiste** un flag "rolling vs standing" né uno "speed limit di formazione"
  nella shared memory. Disponibili: fasi `mGamePhase` (3=formazione, 4=countdown
  luci, 5=verde), `mIndividualPhase` (9=after formation), `mStartLight`/
  `mNumRedLights`; **allineamento** solo via `mTimeGapCarAhead` (gap davanti).
- **Auto-pit** = due assist distinti: **Auto pitlane** (guida in corsia) e **Auto
  Pit Speed Limiter** (inserisce il limitatore alla linea, NON frena in ingresso)
  → si riflettono su `mSpeedLimiter`/`mSpeedLimiterActive` (solo box, non formazione).

**Dev windows (scratchpad, per iterare la grafica prima di portarla nel widget):**
`rc_dev.py` (bandiere, ←/→) e `rc_msg_dev.py` (messaggi direzione: logo FIA a
sinistra + box bianco a larghezza variabile, una riga font pieno 28px, quadri
colore per i track limits, box rosso per le penalità).

**Da fare (Race Control).**
- Chiudere il testo dei messaggi "di conferma" track limits (viola/giallo/rosso).
- Portare la grafica approvata nel widget vero `widgets/wec26flag/widget.py` +
  cablare i dati (mSectorFlag 500m, mTrackLimitsSteps per il colore, race_control
  per le penalità) e implementare priorità+coda (≥20s, giallo/blu rimette in coda).
- Pannello Python con **bottoni** per triggerare bandiere/messaggi nel widget reale.

---

## 2026-07-21 — Safe release, briefing box, regole sessione, fix

**FIX pill "Garage · waiting for stint 1" incollata nel menu.**
- `recorder._tick`: l'auto-sgancio (ramo realtime) era protetto da `_ever_active`
  → se eri in garage in attesa dello stint 1 e tornavi al menu, non sganciava mai
  (dato shared memory stantìo `garage=True`). Guardia cambiata da `_ever_active`
  a **`not _wait_green`**: sgancia anche prima del 1° stint. Online intatto (in
  attesa del verde `_wait_green=True` → non sgancia; garage vivo → ET avanza).

**FIX sfarfallio overlay all'avvio.**
- `shared_memory.is_on_track()`: il debounce di 0.7s (anti-flicker in pista su
  lettura strappata `mInRealtime=0`) faceva **apparire gli overlay ~0.7s** all'avvio
  nel menu prima di sparire. Ora, a freddo (mai stati in realtime: `_rt_true_seen`
  None), torna subito False → niente flash. Debounce in pista invariato.

**Casco base di default (community).**
- `tab_community`: se il record non ha `helmet` valido (versioni vecchie), casco
  **grigio neutro** invece di riga spoglia.

**Muretto: briefing motore acceso + safe release uscita box.**
- `shared_memory.pit_scan()`: modello-dati della mappa per il muretto (ogni auto
  con `lapdist` + `x/z` + `in_pits` + `garage` + `speed` + `track_len`).
- `garage_briefing`: a motore acceso in box, UNA volta → grip pista, temp asfalto,
  gomme (nuove/usate + mescola). Se piove e hai le slick → avviso **critico**
  "non uscire, monta le wet".
- `pit_lane_release`: safe release **solo in USCITA** dal box (mai al rientro).
  (A) traffico NELLA corsia da distanza reale X/Z in avvicinamento (auto dai box
  accanto); (B) merge in pista via lapdist. "aspetta" → "vai". Trick mappa: in
  piazzola `garage=True` finché il musino non è fuori, poi `in_pits`; il rientro
  è `pit_state==2` (entering), mai da garage → `leaving = (garage o garage<25s)
  and pit_state!=2`. Raggio corsia 200m, cap velocità player 70 km/h.
- Fix "aria pulita" (pit_exit_traffic): detta **una volta per richiesta**, non a
  raffica ogni 25s stando fermi.

**Muretto: regole per tipo sessione + "pronti al pit".**
- `_LAW_QUALI_MUTE` in `_sane_one`: in **quali** (sei solo) lo spotter non dà
  **bandiere né traffico** (blue/yellow/traffic/fast_class/gap/opp/pit_exit/
  pit_release); restano tempi/settori/passo/gomme. In **pratica/non-gara** niente
  proiezione pit-exit "aria pulita" (solo gara).
- `pit_ready`: ~3s dopo la TUA chiamata pit → "pronti per il pit stop" (tutte le
  sessioni, una volta per richiesta).
- 3 nuovi eventi (garage_brief, garage_wrong_tyre, pit_release_wait/clear,
  pit_ready) × 4 lingue × 5 varianti; ruoli/voci assegnati.

**Da fare — backlog concordato (vedi memoria `v03b-backlog-muretto`).**
- **Modalità quali (info)**: chi in pole/miglior tempo e di quanto, delta per
  batterlo, dove perdo, out-lap "lavora la gomma" (quali_prep/quali_sector_live
  già ci sono).
- **Ritiro per danno terminale**: contatto + motore morto + non riparte entro 10s
  → silenzia i messaggi inutili e di': gara=ritiro, prova=esci sicuro/aspettiamo,
  quali=finita. 10 frasi ×3 casi ×4 lingue.
- **Debrief di stint in garage** (voce, non overlay): giri, miglior giro, migliori
  settori, passo, gomma, consumi, dove migliorare (settori/curve, bloccaggi).
- **Contatti più precisi**: leggere `mLastImpactPos` (posizione urto) + `dent_sev`
  (8 zone) → "botta dietro a sinistra / fiancata destra / davanti". Serve tarare
  una volta dal vivo il segno sinistra/destra.

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

**FASE 2 — UI COMPLETA reintegrata, app PRONTA.**
- Portati `telemetry/` (window.py 11k + common/trace_view/recorder/db/strategy/
  reader), `ui/` (tab overview/circuits/team/community/settings/overlay + widgets/
  icons), `gui/config_window`, `data/` (tracks). Import + istanza OK.
- **Engineer DECOUPLED**: `telemetry/engineer_tab.py` riscritto SNELLO (QWidget
  segnaposto + API minima cfg/no-op che tab_overlay/window si aspettano); NIENTE
  `engineer_overlay` né motore in-process. Il cervello è il processo muretto.
- `main.py` = entry nuovo: QApplication + `TelemetryWindow` + font + icona;
  **lancia il muretto separato** (se `engineer_on`) e lo chiude con l'app
  (`aboutToQuit`). Overlay: fix spawn di `tab_overlay` → `-m overlays.run_overlay`.
- **PROVATO**: `python main.py` → app UI VIVA + muretto VIVO (separato), log
  pulito, nessun crash. L'app completa gira senza engineer in-process (no scatti).
- Restano (FASE 3-5): online/community, fusione Opzioni ingegnere nella UI,
  riordino assets + centralizzazione paths, prova overlay live, bilingue UI.

**Assets reimportati TUTTI ("come prima", richiesta utente).**
- Portati dal backup: `assets/` completo (103M: bg/cars/catcards/class/flags/mfd/
  racecontrol/teamradio/tracklogos/trackcards/trackmaps_svg/weather/svg/video…),
  `fonts/` (34M: CP Mono/Bebas/Heebo/Titillium), `brandlogo/` (1.9M), `cardlogo/`.
  Merge non distruttivo: tenute le sotto-cartelle 0.3b `assets/icons` e
  `assets/audio` (toni). Nessun file oltre il limite GitHub. Servono a overlay
  (font/mappe/loghi) e UI per renderizzare giusti.

**FASE 1 reintegrazione — pipeline overlay PROVATO (map).**
- Portato `run_overlay` (dal backup: watchdog che chiude l'overlay se muore
  l'app, font, set_enabled) adattato a `overlays/registry.py` (chiave→classe).
- Portato overlay `map` (widget/reader/style) + `settings/style_map.qss` +
  dipendenza `core/rest_client.py`. Import OK.
- Provato: `python -m overlays.run_overlay map` gira come **processo SEPARATO**
  (PID a sé), zero errori, legge shared memory. Pattern overlay confermato.
- `main.py::start_overlays(keys)` implementato: lancia gli overlay come processi
  separati col watchdog (LMU_PARENT_PID). Da chiamare con la lista abilitata.
- FATTO: portato TUTTO il set WEC (map, wecrevs, wecbars, wec26board/battle/
  battleb[in wec26battle]/flag/mfd/mini + supporto standings/weconboard/relative/
  flag/list) + i loro QSS + i moduli core mancanti (brands, tyre_cell, online,
  race_model, soundtrack, ecc.). `overlays/registry.py` con tutti e 9.
  **Test: 9/9 overlay costruiscono senza errori.** Restano da agganciare alla UI
  (abilitazione) in FASE 2. NB: engineer.py NON ricopiato in core (è brain.py).

**3 pulsanti "prova toni" nelle Opzioni (richiesta utente).**
- `main.py`: riga "Prova toni" con 3 pulsanti (▶ Radio / ▶ Fine / ▶ Push-to-talk)
  che suonano il rispettivo tono (via MCI, in thread, al volume voce impostato)
  per ascoltarli e decidere se cambiarli. `_tone_path` (wav→mp3), `_play_tone`.

**Toni radio: OPEN + OVER + PTT (richiesta utente).**
- Schema toni: `radio` = tono OPEN prima della voce; **`end` = tono OVER a FINE
  messaggio** (nuovo); `radio2` = tono **push-to-talk** (riservato, la radio a
  2 vie è da fare). Tutti amplificati come `radio` (erano bassi) → .wav.
- `Voice.set_end(path, on)` + il worker suona `end.wav` DOPO la voce (saltato se
  il messaggio è tagliato dalla gialla). `run_engineer._END`/`_PTT` + `_apply_cfg`
  lega open+over allo stesso toggle "Beep radio". Testato: open→voce→over.

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

---

## 23/07/2026 — Indagine incidente Ascari: i danni fisici entrano nel muretto

**Il caso.** In gara una Hypercar si gira all'Ascari, la prendiamo in pieno e
LMU dà un "avvertimento giallo per guida antisportiva". Domanda: dov'è quel
dato? Indagine su TUTTI i canali.

**Esito indagine (negativo ma prezioso):**
- L'avvertimento antisportivo **non esiste in nessun dato accessibile**: non
  nel trace (al secondo della botta il motore scrive solo le ruote piegate),
  non nella shared memory (`mNumPenalties` resta 0), non nel REST. È un
  messaggio solo-grafica del motore (Coherent UI). Censite anche TUTTE le
  rotte REST dai binari del gioco: nessun canale messaggi.

**Scoperte collaterali (queste sì, d'oro):**
1. `hdvehicle.cpp: Bending wheel #N with severity S (toe: T; camber: C)` —
   ruota del GIOCATORE piegata, con gravità e geometrie storte. I wearables
   NON la vedono (suspensionDamage resta 0): è l'unica fonte del danno
   "macchina che tira da un lato".
2. `score.cpp: LocalDNF for driver "X" due to Engine/Suspension/Accident` —
   la CAUSA vera del ritiro (il "motore morto" che cercavamo da giorni).
   Attenzione: la riga esce anche in prova rientrando al monitor con danni,
   quindi va gatata alla sola gara.
3. Rotte REST scoperte dai binari: `strategy/pitstop-estimate` (tempo sosta
   GIÀ scomposto: benzina/gomme/freni/danni/penalità/totale — sblocca il
   countdown pit), `garage/getVehicleCondition` (vehicleDamage aggregato),
   `watch/standings/history` (storico giri per slot), `sessions/
   raceControlVerification` (da esplorare).

**Cosa è entrato in macchina (collaudato a secco):**
- `core/race_control.py`: parsing `Bending wheel` (per-ruota, finestra 8s,
  peggiore) + `LocalDNF` → `recent_wheel_bends()` / `latest_dnf()`; azzerati
  a ogni Steward::Restart; preload muto (mai annunciare il passato).
- `engineer/brain.py`: `wheel_bend_call` — annuncia la ruota piegata (soglia
  0.20, "forte" ≥ 0.50, mai ripetersi, parla DOPO il verdetto contatto) e il
  ritiro certificato (motore/sospensioni/incidente, SOLO in gara). Frasi in
  4 lingue, ruolo engineer, priorità radio P2 (piega) / P1 (ritiro).
- Il bottoming c'era già (finding di debrief a fine stint da `ride_h`).

**Dash (stesso giorno, richieste pilota):**
- Frecce hazard: dopo 5s da fermo in pista ANCHE a motore spento (in panne
  servono); mai in garage.
- Header: cella eventi (tempi/INVALID) ora z-sopra la cella delta — stessa
  ancora alla colonna LAP, aprendosi la copre, chiudendosi la scopre.
- Prova delta: a ogni giro chiuso `delta_check.log` scrive atteso (giro −
  best) vs mostrato — la certificazione che il delta converge al traguardo.
  Delta = SEMPRE vs il proprio best di sessione; fuxia/verde/bianco = solo
  contesto colore (P1 di classe / best personale / non migliori).

**Countdown pit (task #9) — stesso giorno.** MOD 2 (pagina PIT), nello spazio
ex-gauge: pannello "PIT STOP EST" con il totale della sosta e la scomposizione
LMU vera (ENERGY/TYRES/DAMAGE/PENALTY..., rotta `strategy/pitstop-estimate`,
aggiornata ogni 2s dalla corsia lenta wearables). Da FERMI in corsia box il
numero grande diventa il CRONO: stima − trascorso in ambra, oltre la stima
passa a +X rosso, si azzera quando riparti. Verificato offscreen (3 stati:
stima, countdown, overtime).
