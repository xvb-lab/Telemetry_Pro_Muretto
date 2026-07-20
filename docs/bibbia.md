# La Bibbia — LMU Telemetry Pro 0.3b

Documento di riferimento **UNICO** della ricostruzione 0.3b. Prima di
scrivere o toccare un pezzo, si legge la sua voce qui. Nasce dal collaudato
di v2/v3 (0% errore sui dati) + le decisioni prese il 2026-07-20.

Backup della vecchia root (con `.git` e la vecchia bibbia
`docs_official/dev/muretto_bibbia.md`):
`..\Telemetry_Pro_BACKUP_2026-07-20_203351\`.

---

## 0. Perché ricostruiamo

La v3 aveva il **motore dati preciso** ma UI + telemetria + muretto giravano
in **un solo processo**: si contendevano CPU/GIL → l'app andava a scatti
(diagnosi py-spy: `list_sessions` teneva il GIL ~600 ms ogni 4 s). 0.3b
riparte con **architettura a processi separati**, portandosi dietro
l'esperienza (moduli collaudati, bug gia' capiti, regole fisse).

---

## 1. Principi FISSI (non si violano MAI)

1. **Dati SOLO da LMU.** Se un dato manca, il muretto **tace** — non inventa
   mai numeri. Consumi/giri/autonomia sono lo specchio in tempo reale
   dell'HUD di LMU. Errore ammesso sulle strategie: **0%** (si corrono
   campionati veri: rimanere a secco o dare strategie assurde e' inaccettabile).
2. **Consigli, non ordini.** Il muretto informa, il pilota decide.
   "Box box box" perentorio **solo per sicurezza reale** (wet, ruota,
   foratura, danno grave, energia in esaurimento).
3. **State-aware.** Ogni frase confronta prima lo STATO reale: mai
   consigliare cio' che e' gia' vero; mai frasi "da pista" mentre sei ai
   box / in corsia / con pit chiamato.
4. **Rispetta il collaudato.** Cio' che funziona in pista non si tocca senza
   motivo. Un passo alla volta, su dettatura. Si legge cosa c'e' PRIMA di
   riscrivere.
5. **Anti-ripetizione.** Un avviso si dice quando la CONCLUSIONE cambia, non
   a ogni tick. Isteresi sulle soglie + riarmo alla sosta.

---

## 2. Architettura 0.3b — tre processi separati

Tre processi distinti perché CPU/GIL non si accavallino:

| Processo | Entry point | Ruolo |
|---|---|---|
| **APP / UI** | `main.py` | finestre, review, config, **launcher** |
| **MURETTO** | `engineer/run_engineer.py` | il cervello ingegnere (parlato) |
| **OVERLAY** | `overlays/run_overlay.py <nome>` | uno per overlay, su schermo |
| *(condiviso)* | `core/` | lettura LMU, config: usato da tutti e tre |

Regola d'oro: UI, muretto e overlay leggono LMU **passando da `core/`**, mai
l'uno dall'altro. L'app lancia muretto e overlay come processi figli
(`main.py::start_muretto` / `start_overlays`).

---

## 3. Struttura cartelle

```
main.py                 APP / UI (processo 1)
core/                   codice CONDIVISO
  shared_memory.py      stream scoring (rivali, settori, bandiere, meteo, gomme)
  reader.py             stream fisica  (TelemetryReader: VE, fuel, RPM, gear, temp)
  (lmu_live)            derivazione strategica 0% — DA ESTRARRE dal vecchio recorder
  voice.py              TTS multilingua (da portare)
  config.py             impostazioni (da portare)
ui/                     interfaccia app
engineer/               MURETTO (processo 2)
  run_engineer.py
overlays/               OVERLAY (processi 3+)
  run_overlay.py
settings/               dati modificabili
  engineer_msgs.json    catalogo frasi (4 lingue)
  *.qss                 stili overlay
assets/
  icons/  audio/  img/
docs/
  bibbia.md             questo file
```

---

## 4. Il motore dati (core) — il cuore, 0% errore

Due lettori collaudati (gia' in `core/`), coprono i due stream della shared
memory di LMU:

- **`reader.py`** (`TelemetryReader`, stream **fisica**): `read()` → dict con
  VirtualEnergy (energia ibrida), Fuel, FuelCapacity, carcasse gomme, RPM,
  gear, acqua/olio. API: `read()`, `stop()`.
- **`shared_memory.py`** (stream **scoring**): rivali, settori, bandiere,
  meteo, mescole, usura gomme, posizioni, track limits, pit, yellow phases.

Sopra i due lettori vive **`lmu_live`** (da estrarre dal vecchio
`recorder.py` monolitico): la derivazione strategica DIRETTA di LMU, unita a
`/rest/strategy/usage` + tabella `_ve_table` del pit menu. Campi:

- `constraint` ENERGY/FUEL · `ve_pct` · `fuel_l` · `fuel_max`
- `per_lap` (consumo/giro, sempre conto DEL GIOCO) · `autonomy_laps`
- `laps_needed` · `target_pct` · `ve_table` · `compound4` · `raining` · `wetness`

**Regola d'oro:** qualunque calcolo strategico parte da `lmu_live`. Mai
reintrodurre stime nostre (regex, delta grezzi) come nella v2.

REST vive utili (porta 6397, censite in `data_library.md` del backup):
`/rest/strategy/usage`, `PitMenu/receivePitMenu`, `TireManagement`,
`/rest/sessions`, `sessions/weather`. **Le chiamate REST vanno fatte
NON-bloccanti** (thread dedicato / async) — mai dentro il loop di
campionamento (era la causa di stutter). Riferimento concettuale:
`async_request.py` di TinyPedal (GPL, solo da studiare).

---

## 5. Il muretto (engineer) — parlato-only

L'ingegnere **non ha overlay né testo a schermo**: pura voce. Pipeline:

```
core (dati LMU)  →  cervello (legge → decide)  →  voce (TTS)
```

Gira nel suo processo, isolato. Legge LMU da `core`, decide con i moduli
(sez. 9), parla via `core/voice.py` scegliendo la frase dal catalogo nella
lingua attiva.

---

## 6. I tre ingegneri (ruoli e voci)

Tre ruoli, ognuno con voce e colore suoi:

| Ruolo | Colore | Di cosa parla |
|---|---|---|
| **RACE ENGINEER** | arancio `#e8802a` | bandiere, danni, gomme montate, box, motore, batteria, saluti |
| **STRATEGY ENGINEER** | blu `#45b4ef` | piano gara, consumo vs target, soste, meteo, undercut/overcut |
| **PERFORMANCE ENGINEER** (spotter) | verde `#37d67a` | tempi, settori (dove perdi), bloccaggi, contatti, traffico |

Ogni codice-messaggio ha il suo ruolo assegnato (nel vecchio
`engineer_overlay.py::_role`). Un messaggio nuovo VA assegnato a un ruolo.

**3 voci per ruolo × 4 lingue** (edge-tts, tabella collaudata):

| Ruolo | 🇮🇹 IT | 🇬🇧 EN | 🇪🇸 ES | 🇫🇷 FR |
|---|---|---|---|---|
| RACE | Giuseppe | Christopher | Álvaro | Henri |
| STRATEGY | Diego | Ryan | Jorge | Jean |
| PERFORMANCE | Isabella | Sonia | Elvira | Denise |

---

## 7. Multilingua — 4 lingue

- Catalogo `settings/engineer_msgs.json`: campi `it / en / es / fr` (+
  `variants_it`, `cat`, `level`, `beep`). Stato: **it/en completi (285)**,
  **es/fr ~7 frasi corti** (rifinitura).
- Motore `core/voice.py`: backend multipli (edge-tts neurale = scelta
  primaria online; SAPI5/pyttsx3 fallback). Parametro `lang`.
- **Tutto ONLINE** (i campionati lo sono sempre): nessun vincolo offline.

---

## 8. Radio a due vie (pilota ↔ muretto)

I team vogliono **parlare** col muretto: non solo lui che chiama, ma domande
del pilota ("quanta benzina?", "che gap ho dietro?", "quando fermo?", "come
stanno le gomme?") con risposta **dal dato reale**.

- **Canale d'ingresso**: microfono → **STT online**. Sta nel processo muretto.
- **3 modalità** (opzione utente):
  1. **Solo radio** — una via, parla solo lui (come ora)
  2. **Push-to-talk** — bind premuto = "ti sto parlando"
  3. **Sempre in ascolto** — mic aperto, serve la parola d'attivazione
- **Parola d'attivazione** (modificabile in opzioni), default:
  IT=**muretto** · EN=**engineer** · ES=**muro** · FR=**ingénieur**
  (*mur* scartato: 1 sillaba → falsi trigger).
- **Interpretazione DETERMINISTICA** a parole chiave: la domanda si mappa su
  quale dato reale rispondere. **NO LLM** che allucina numeri. Se il dato
  manca → "non ho il dato", mai inventato (coerente col principio 1).

---

## 9. Catalogo moduli del cervello (da portare da v2/v3, un pezzo alla volta)

Base = i moduli-voce collaudati (v2/v3), adattati alla struttura nuova. Dalla
vecchia bibbia, **priorità di riporto**:

1. **`sector_panel_data` / `sector_delta`** — DOVE PERDI/GUADAGNI nei settori
   e nelle curve (l'utente lo vuole; anche "la curva dove il pilota fatica"
   dal profilo appreso della v2). **Priorità n.1.**
2. `conditions_call` — info periodiche pista (temp asfalto, grip).
3. `box_last_call` — rinforzo chiamata box all'ingresso corsia.
4. `box_timing_call` — anticipa/ritarda sosta di un giro per traffico.
5. `pit_exit_traffic` — traffico previsto al rientro.
6. `wet_sector_map` — settore bagnato.

Già coperti / da NON riportare: `yellow_call` full-course (**qui non c'è
safety car**; la gialla LOCALE nei ~500 m davanti sta in `flags_call`),
`tyre_advice`→`wet_tyre`/`rain_live`, `strat_plan`→`race_plan`/`box_call`,
`best_lap_call`→`lap_feedback`.

Moduli-voce principali (dal catalogo v3): `flags_call`, `damage_call`,
`aero_call`, `contact_call`, `engine_check`, `battery_check`, `pit_ack`,
`wet_tyre`; `race_plan`, `box_call`, `strategy_check`, `weather_check`,
`status_update`, `autofuel_call`, `countdown`, `pos_call`; `lap_time_call`,
`lap_feedback`, `theo_lap`, quali_*, `lock_pattern_call`, `grip_call`,
`tlimits_call`, `traffic_ahead_call`, `tyre_life`, `rain_live`.

---

## 10. Regole trasversali

- **sanity_filter**: ultimo cancello prima della voce. Blocca frasi da pista
  se sei ai box/corsia/pit chiamato.
- **Anti-ripetizione**: firma della CONCLUSIONE (non dei numeri grezzi che
  ballano); isteresi; riarmo al pit.
- **Un modulo alla volta**: si porta, si compila, si prova in pista, si
  valida, poi il prossimo. Mai 12 fix alla cieca.
- **REST non-bloccante** sempre (vedi sez. 4).

---

## 11. Stato e roadmap

**Fatto** (root 0.3b):
- `main.py`: finestra + icona, AUMID taskbar, avvio con `pythonw` (no console)
- struttura cartelle: core/ ui/ engineer/ overlays/ settings/ docs/
- `assets/{icons,audio,img}/` (icona app importata)
- dati: `core/shared_memory.py` + `core/reader.py` portati e testati (import + `read()`)

**Da fare** (mattoni, in ordine):
1. Estrarre `lmu_live` dal vecchio `recorder.py` → `core/`
2. Voce + lingue: `core/voice.py` + `settings/engineer_msgs.json`
3. Radio a 2 vie: STT + wake word + intent deterministico
4. Cervello: moduli sez. 9, priorità 1 = settori "dove perdo"

---

## 12. Riferimenti

- Backup completo vecchia app: `..\Telemetry_Pro_BACKUP_2026-07-20_203351\`
- Vecchia bibbia muretto: `<backup>\docs_official\dev\muretto_bibbia.md`
- Censimento dati: `<backup>\...\data_library.md`
- TinyPedal (GPL, solo riferimento concettuale — processi separati, REST
  async): `C:\Users\jonal\Downloads\TinyPedal-master`

*Aggiornare questo file a ogni modulo portato o regola cambiata.*
