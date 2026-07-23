# Ingegneria della telemetria — il cervello tecnico di Telemetry Pro

> Come un ingegnere di pista, un meccanico e un capo squadra leggono i dati —
> e come lo facciamo noi, canale per canale, con le formule e le soglie.
> Questo documento è la BASE di: briefing garage professionali, suggerimenti
> live in pista, advisor assetto, e la futura **pagina Garage** (tab per ogni
> parte dell'auto, con consigli di setup per pista selezionata).

---

## 1. L'inventario dei canali (cosa ABBIAMO GIÀ, verificato nel reader)

Per OGNI ruota, a ogni lettura (5 Hz nel muretto, di più nel recorder):

| Canale | Campo | Uso ingegneristico |
|---|---|---|
| **Battistrada 3 zone** | `mTemperature[3]` (sx/centro/dx del battistrada) | camber, pressioni, stile guida |
| **Strato interno 3 zone** | `mTireInnerLayerTemperature[3]` | la "verità" termica (meno rumore della superficie) |
| **Carcassa** | `mTireCarcassTemperature` | finestra d'esercizio vera (docs/dati_lmu.md) |
| **Pressione** | `mPressure` (kPa) | crown effect, finestre minime a caldo |
| **Usura** | `mWear` (0-1) | degrado per ruota → per assale/lato |
| **Grip fract** | `mGripFract` | frazione di impronta che slitta |
| **Temp freno** | `mBrakeTemp` | finestre per materiale (acciaio GT / carbonio proto) |
| **Pressione freno** | `mBrakePressure` per ruota | come lavora l'impianto in staccata |
| **Corsa sospensione** | `mSuspensionDeflection` (mm) | cordoli, bump, fondo corsa |
| **Carico pushrod** | `mSuspForce` (N) | trasferimenti di carico reali |
| **Ride height** | `mRideHeight` (mm) | bottoming, rake |
| **Slide laterale** | `mLateralPatchVel` | sotto/sovrasterzo per curva |
| **Rotazione ruota** | `mRotation` | bloccaggi (transizione) |
| **Flat spot** | `mFlat` (bool!) | spiattellamento CONFERMATO dal gioco |
| **Superficie** | `mSurfaceType` (5=cordolo) | dove sei con ogni ruota |
| **Aero** | `mFrontDownforce`/`mRearDownforce` (N) | bilancio aero reale |
| **Curve apprese** | learn: `d, vmin, ventry, drop, brake_d, brake_peak, spike, hot_wheel` per curva | il riferimento personale |

---

## 2. Diagnostica da manuale (sintomo → firma nei dati → consiglio)

### 2.1 Gomme — camber (spread interno/esterno)
- **Regola pro** (Autosport Labs / YourDataDriven): spread interno-esterno del
  battistrada **≤ 10 °C**; l'interno DEVE essere il più caldo (con camber
  negativo) di ~5-8 °C in curva.
- **Firma**: `T_int - T_est > 12 °C` costante su un asse → **troppo camber**;
  `T_est ≥ T_int` → **poco camber** (o pressioni sbagliate).
- **Consiglio**: ±0,2/0,4° di camber per volta. Sull'anteriore agisce anche
  sull'ingresso curva; sul posteriore su trazione e stabilità.

### 2.2 Gomme — pressione (crown effect)
- **Regola pro**: `T_centro` confrontata con `media(T_int, T_est)`:
  - centro **più caldo** di >5 °C → **pressione alta** (gonfia, impronta a cupola)
  - centro **più freddo** di >5 °C → **pressione bassa** (lavorano le spalle)
- **Le nostre finestre a caldo** (dati_lmu.md): GT 1,90-2,00 bar · proto 1,80-1,95.
- **Consiglio**: ±0,3/0,5 psi per volta; ricordare che +10 °C carcassa ≈ +0,6 psi.

### 2.3 Bilancio telaio — sotto/sovrasterzo (per curva!)
- **Firma primaria**: slide medio anteriore vs posteriore (`slip_lat`) NELLE
  CURVE, per curva appresa: `F/R > 1.4` sostenuto → sottosterzo; `R/F > 1.4`
  → sovrasterzo. (Già campionato dal setup coach; da attribuire per curva.)
- **Conferma termica**: asse anteriore interno-strato più caldo del posteriore
  di ≥8 °C → conferma sottosterzo cronico (l'anteriore striscia).
- **Consigli assetto** (ordine di intervento, stile ingegnere):
  - Sottosterzo: più ala davanti → barra ant. più morbida → -camber ant. →
    -pressione ant. → (ingresso) più freno motore/bias indietro.
  - Sovrasterzo: più ala dietro → barra post. più morbida → differenziale
    (rampa rilascio) → +pressione post. di un filo.

### 2.4 Freni — finestre e gestione (per classe)
- **GT (acciaio)**: minima 150 °C, finestra **300-550**, overheating 700.
- **Proto (carbonio)**: minima 250 (sotto NON mordono), finestra **350-650**,
  overheating 800. (dati_lmu.md + Brembo WEC)
- **Firme**:
  - `bk > soglia_over` sostenuto 4s → già gestito (brakes_over).
  - **Squilibrio F/R**: `media(bk_ant) - media(bk_post) > 150 °C` costante →
    bias troppo avanti (o ducts posteriori troppo aperti) — e viceversa.
  - **Una ruota sistematicamente più calda** in staccata → check ducts/bias
    lato, o bloccaggi ripetuti (incrocia con lock zones).
  - **Sotto finestra al giro lanciato** (quali) → ducts troppo aperti.
- **Consiglio tipo**: "in staccata di curva 4 l'anteriore destra supera i
  650: chiudi mezzo click di bias o apri i ducts davanti".

### 2.5 Usura — dove e perché
- **Per lato**: `usura_dx - usura_sx` per stint → piste a senso orario
  consumano più la sinistra e viceversa; se il delta CRESCE oltre il normale
  (>1,5% a stint sul lato "sbagliato") → pressioni/camber da rivedere.
- **Per curva**: attribuiamo il consumo alle curve dove quella ruota slitta
  di più (slip per curva × tempo) → "per il long run stiamo usando molto la
  posteriore destra all'uscita di curva 9: trazione più dolce lì o un filo
  più di ala".
- **hot_wheel appreso** per curva (già nel learn!) = la ruota che soffre.

### 2.6 Cordoli, bump e fondo corsa
- **Cordolo violento**: ruota su `mSurfaceType==5` + salto di
  `mSuspensionDeflection` (>18 mm in 0,2s) → già rilevato (kerb_call).
- **IMPORTANTE — impatti finti**: il bump del cordolo genera anche
  `mLastImpactMagnitude` (LMU lo conta come "urto"): va CLASSIFICATO cordolo,
  NON contatto (niente verdetto danni). → implementato: se al momento
  dell'impatto una ruota è sul cordolo e nessuna auto è vicina = cordolo.
- **Bottoming**: `mRideHeight` che tocca ~0 ripetuto nello stesso punto →
  "tocca il fondo in staccata di curva 1: +2 mm di altezza o molle più dure".

### 2.7 Flat spot
- `mFlat` per ruota = **conferma del gioco** (non inferenza!): appena passa
  True → "spiattellata la {ruota}: vibrerà fino al cambio gomme". Resta sul
  treno anche rimontandolo (LMU lo modella).

### 2.8 Aero
- `mFrontDownforce/mRearDownforce` → **bilancio %** = F/(F+R) a velocità
  costante nei curvoni: confronta con il bilancio del tuo best. Spostamenti
  >1,5% spiegano cambi di comportamento ("hai perso carico davanti: ala o
  danno?"). Con danno aero incrociare con `aero` (wearables).

### 2.9 Ibrido (HY)
- Regole LMU (trophi/Coach Dave): regen al massimo è ottimale; SOC target
  ~¾; **SOC pieno in staccata = brake-by-wire che taglia un asse** (già nel
  nostro out-lap HY); mai box con batteria vuota (uscita solo elettrica).

---

## 3. Le TRE bocche del sistema

### A. Briefing garage (anche in PAUSA sessione)
Il muretto parla in garage se la sessione è VIVA (ET che avanza), anche se
sei nel monitor. Contenuto (dallo stint appena chiuso, stint analyzer):
1. Quadro stint: giri, best, passo (già: debrief_stint)
2. **Telaio**: "in curva 2 troppo sottosterzo" (slip per curva)
3. **Gomme**: "usura alta sulla posteriore destra, viene dall'uscita di
   curva 9" (usura + slip attribution) + camber/pressioni dalle 3 zone
4. **Freni**: squilibri/zone critiche
5. Programma: giro secco o long run (garage_prep già fatto)

### B. Suggerimenti live in pista
Già attivi: staccate vs riferimento, pattinamento per curva, bloccaggi,
cordoli, scivolate, track limits per curva, spia motore, fermo-check.
Da aggiungere (fase 2): bottoming, squilibrio freni, camber/pressioni
(solo fine stint — le 3 zone vanno lette in curva, media mobile).

### C. Advisor assetto → pagina GARAGE (visione)
La pagina Setups diventa un **garage a tab per parte auto**:
- **Gomme** (pressioni/camber dalla diagnostica 2.1-2.2, per pista)
- **Freni** (bias, ducts dalla 2.4)
- **Sospensioni** (barre, molle, altezze da 2.3/2.6)
- **Aero** (ali dal bilancio 2.8 + classe/pista)
- **Elettronica** (TC/ABS GT, mappe/regen HY)
Ogni tab: valore attuale, diagnosi dai TUOI dati sull'ultima sessione su
quella pista, consiglio con motivazione ("più ala davanti: nei curvoni
l'anteriore slitta 1,6× il posteriore"). Il muretto e il garage parlano
la stessa lingua (stesso motore diagnostico, questo doc).

---

## 4. Roadmap implementativa
1. ✅ Fatto: coach staccate/trazione, bloccaggi, cordoli (con classificazione
   impatti), scivolate, track limits per curva, out-lap per classe, prep
   garage, fermo-check, spia motore, flat spot (avviso da bloccaggi).
2. **Stint analyzer** (in corso): accumulo per curva (slip F/R, usura
   attribuita, freni) → findings a fine stint in garage.
3. `mFlat` live → conferma spiattellamento dal gioco.
4. 3 zone gomma → camber/pressioni a fine stint (media mobile in curva).
5. Bottoming + squilibrio freni.
6. Bilancio aero (downforce) nel confronto col best.
7. **Pagina Garage** (tab + advisor) — riusa il motore di questo doc.

---

## 5. Analisi POST-SESSIONE — spec formale (pagina Telemetria)

> Il live (5 Hz) fa le regole semplici delle sezioni 2-3. L'analisi RIGOROSA
> gira sui `samples` del recorder (SQLite, alta frequenza) — che registrano
> GIA' per ruota: deflessione sospensione, ride height, pressione freno,
> gomma a 3 strati, pressioni, usura, sterzo, G long/lat, brake bias.

### 5.1 Pre-processing
- **Resampling spaziale**: da dominio tempo a dominio distanza (`lapdist`)
  con interpolazione — il confronto giro-su-giro è punto-a-punto (il delta
  engine live usa gia' questo principio; qui si formalizza sui samples).
- **Filtraggio**: passa-basso (Butterworth 2° ordine) su sterzo e G per il
  post-processing; live bastano le medie mobili.
- **Segmentazione**: per curva dalle curve APPRESE (d, apex) — niente GPS,
  abbiamo lapdist + mPos.

### 5.2 Dinamica longitudinale
- **Pressure gradient** ΔP/Δt all'attacco del freno (canale `brake` +
  `brake_p_*` per ruota): attacco troppo lento = staccata sprecata.
- **Trail braking decay**: pendenza del rilascio freno vs sterzo/distanza
  dall'apex → transizione del carico in ingresso.
- **Throttle latency & linearity**: `t_gas_on − t_freno_off` + linearita'
  della prima apertura.

### 5.3 Dinamica laterale
- **Slip per ruota MISURATO**: rF2 da' `mLateralPatchVel` — meglio della
  stima di β da imbardata. (Da AGGIUNGERE ai samples: oggi e' solo live.)
- **Steering smoothness**: inversioni di segno di dδ/dt per metro nella
  stessa fase di inserimento = instabilita'/correzioni.
- **Apex**: Vmin locale + POSIZIONE dell'apex vs riferimento.

### 5.4 G-G e grip margin
- **G-G per fase** (gia' esiste il canvas): riempimento dell'ellisse.
- **Grip margin DIRETTO**: `mGripFract` (frazione di impronta che slitta,
  per ruota) = il "potenziale inespresso" senza scomporre le forze.
  (Da AGGIUNGERE ai samples insieme allo slip.)

### 5.5 Estensioni assetto (dai canali per-ruota gia' registrati)
- **Termica gomma vs slip**: gradiente termico (superficie/strato/carcassa)
  correlato a slip ed eventi (bloccaggi, pattinate) → "stai bruciando le
  gomme nei primi giri".
- **Piattaforma aero**: escursioni `ride_h_*` in frenata e alta velocita' →
  bottoming, beccheggio, piattaforma che cede (rake dinamico).
- **Istogrammi velocita' ammortizzatori**: derivata di `susp_d_*` divisa in
  basse/medie/alte velocita' per curva → cordoli presi troppo aggressivi,
  piattaforma destabilizzata.
- **Gradienti rollio/beccheggio**: rapporto G_lat/rollio e G_long/beccheggio
  (da ride_h per angolo) → efficacia del trasferimento di carico.

### 5.6 Output: Time-Loss Matrix (il re dei report)
Per ogni curva e fase (Staccata / Percorrenza / Uscita):
`ms_persi = ∫ (V_ref(s) − V(s)) ds / V_media` vs giro di riferimento →
tabella "dove perdi e quanto", che alimenta ANCHE il debrief vocale
("perdi 120 millesimi in ingresso curva 5") e i consigli assetto.
Formato output per anomalia: `[Curva X] · [Fase] · [Parametro] ·
scostamento quantificato · consiglio azionabile` — lo stesso pattern dei
findings del muretto: UNA lingua per garage, voce e pagina.

### Gap da colmare (piccoli)
1. Aggiungere ai samples: `slip_l per ruota` + `grip_fract per ruota`
   (8 colonne) — sblocca 5.3/5.4 dal registrato.
2. Cadenza samples: verificare che basti per ΔP/Δt (>=20 Hz consigliati
   in frenata).

---

## 6. Specifiche ENDURANCE (WEC / ELMS) — la nostra specialita'

> L'endurance non e' il giro secco: e' gestione su ore, traffico
> multiclasse e energia. Canali GIA' campionati nel recorder:
> `soc, regen_kw, boost_state, fuel, ve` per sample + tempi/usura per giro.

### 6.1 Ibrido (Hypercar) — deployment & recovery per giro
- **Curva di rilascio** dell'elettrico vs posizione sul giro (`boost_state`,
  `soc` sui samples): il pilota spende l'ibrido troppo presto? Arriva ai
  rettilinei principali in **clipping** (batteria vuota)?
- **Rigenerazione**: `regen_kw` in frenata correlata a lift-and-coast e
  trail braking → efficienza di ricarica. Regole LMU gia' nel muretto:
  regen max, SOC ~3/4, mai satura in staccata, mai box a batteria vuota.

### 6.2 Consumo mirato (fuel/VE mapping)
- `fuel`/`ve` per sample → **consumo per settore/curva** correlato al tempo:
  il risparmio si suggerisce DOVE costa meno ("lift in staccata di curva 1:
  −0,3 litri al giro per +0,05s"). Alimenta i piani eco gia' esistenti
  (plan_eco_save / fuel_save_option).

### 6.3 Aero spec WEC vs ELMS (LMP2/GT3)
- Nota: stessi telai, pacchetti diversi (Le Mans low-downforce vs ELMS
  high-downforce). L'algoritmo valuta il G_lat nei CURVONI vs l'atteso
  della configurazione — richiede la config aero dichiarata: entrera'
  dalla **pagina Garage** (input assetto). Nel frattempo: confronto col
  TUO storico su quella pista+classe (baseline personale).
- Canali live `df_front/df_rear` gia' esposti → (gap: aggiungerli ai
  samples per l'analisi post).

### 6.4 Traffico multiclasse & dirty air
- **Perdita in scia**: delta settoriale anomalo quando segui da vicino →
  quantificare il tempo perso nel traffico vs aria pulita.
  (Gap: registrare `gap_ahead` per sample — 1 colonna.)
- **Mappatura sorpassi doppiati**: dove anticipare/ritardare il sorpasso
  della classe lenta per non perdere slancio — il muretto ha gia' i
  mattoni live (traffic_ahead, box_anticipate/box_delay coi treni).

### 6.5 Multi-stint: curva di degrado del passo
- Sui `laps`: media e varianza dei tempi per stint (28-30 giri tipici),
  fit del degrado (lineare/esponenziale) → **il giro esatto** in cui il
  decadimento supera la convenienza del pit ("cliff detection" formale —
  il live ha gia' tyre_cliff euristico + deg appreso per pista).
- Output al pilota: "da meta' stint proteggi il posteriore: ingressi piu'
  dolci e trazione anticipata ma progressiva".

---

## 7. Profili PER CLASSE e PER AUTO (2023-2026) — regole specifiche

> La fisica cambia per vettura, non solo per classe. Queste regole vanno in
> un file dati (`settings/car_profiles.json`) letto da muretto e analisi:
> stessa fonte, zero hardcoding.

### 7.1 Verita' sui canali (cosa LMU espone DAVVERO)
| Canale richiesto | Stato da noi |
|---|---|
| MGU torque (± = regen) | ✅ `mElectricBoostMotorTorque` gia' nel reader (`emotor_tq`/`boost_torque`) |
| ABS activity / TC cut | ✅ GIA' nei samples (`abs_active`, `tc_cut`) |
| Wheel speed per ruota | ✅ `wheel_rot` (lockup detector live gia' attivo) |
| BBW / pressione freno per ruota | ✅ `brake_p_*` nei samples |
| Ride height ant/post | ✅ `ride_h_*` |
| Yaw rate | ⚠️ `mLocalRot` esiste nella struct — DA ESPORRE (1 campo) |
| MGU per ASSE (front vs rear) | ❌ LMU modella UN motore boost: la ripartizione LMH/LMDh si INFERISCE dal profilo auto |
| Torque sensor BoP sui semiassi | ❌ non esposto: il clipping si inferisce da coppia/gas/TC |

### 7.2 HYPERCAR — LMH (AWD) vs LMDh (RWD)
- **LMH (499P, GR010, 9X8, Valkyrie*)**: soglia ingaggio anteriore da BoP
  (~190-210 km/h, per-auto nel profilo). REGOLA: sotto soglia = 100% RWD
  (occhio sovrasterzo in trazione), sopra = tende al sottosterzo da
  trazione. Rilevazione: `boost_torque > 0` + `speed` vs soglia profilo +
  variazione yaw (quando esposto).
- **499P**: BBW complesso — in staccata, se `brake_p` anteriore alta MENTRE
  `emotor_tq < 0` (harvest) forte → rischio bloccaggio trascinato interno.
- **GR010**: tollera altezze basse ma monitorare **bottoming** in
  transizione frenata-inserimento (gia' rilevato); stint: micro-slip
  posteriore che scalda la carcassa (slip_lat rear + carcass trend).
- **9X8 2023 vs Evo 24+**: profilo pitch-sensitive (muso che si alza in
  rilascio = perdita effetto suolo) vs Evo con ala (validare trazione
  posteriore: slip ratio rear in uscita lenta).
- **LMDh (963, V-Series.R, M Hybrid, A424)**: harvest POSTERIORE — in
  staccata la derivata della decelerazione "a gradini" = blending
  freno/motore/MGU mal calibrato → retrotreno nervoso. 963: sospensioni
  rigide, cordoli con cautela. **Cadillac**: aspirato, gas lineare — se il
  pilota apre a gradino → pattinamento evitabile. **BMW/Alpine**: turbo
  lag — ritardo gas→coppia; se il turbo carica in piena piega il TC taglia
  a "pompaggio" (oscillazione `tc_cut` ripetuta = firma).
- **Valkyrie (25+)**: 100% termica — niente ibrido da gestire: focus tutto
  su bias termico freni e gomma.

### 7.3 LMP2 (Oreca 07) — no ABS, alto carico
- **Lockup senza ABS**: gia' attivo (transizione ruota <30%); aggiungere
  soglia PRE-allerta stile spec (`V_ruota < 0.85 × V_auto` in staccata).
- **Pitch sensitivity**: ride height ANTERIORE oltre soglia nei curvoni =
  muso che perde carico di colpo.

### 7.4 LMP3 — telaio flessibile
- **Rollio nei cambi di direzione**: gas prima che il rollio si stabilizzi
  = sovrasterzo pendolare (g_lat vs derivata ride_h dx/sx nelle esse).

### 7.5 GT: GTE (no ABS) vs LMGT3 (ABS obbligatorio)
- **GTE**: trail-braking chirurgico o spiattelli l'anteriore interna
  (rilascio lento + tanto sterzo = firma flat-spot; `mFlat` conferma).
- **LMGT3 — ABS Intervention Index**: frequenza di `abs_active` con freno
  a fondo → "riduci la pressione iniziale dell'8%, l'ABS che lavora
  sempre scalda la gomma e ALLUNGA la frenata". GIA' calcolabile dai
  samples. TC: raffiche di `tc_cut` in uscita = erogazione da rivedere.

### 7.6 Schema `car_profiles.json` (da creare)
```json
{ "Ferrari 499P": {"drive": "AWD", "awd_engage_kmh": 190,
    "hybrid": "front", "bbw": true, "note": "harvest ant in staccata"},
  "Porsche 963":  {"drive": "RWD", "hybrid": "rear",
    "kerb_tolerance": "low", "blending_check": true},
  "Cadillac V-Series.R": {"drive": "RWD", "aspirated": true,
    "throttle_linearity_check": true},
  "BMW M Hybrid V8": {"turbo": "twin", "turbo_lag_check": true},
  "Alpine A424": {"turbo": "single", "turbo_lag_check": true},
  "Aston Martin Valkyrie": {"hybrid": null, "pure_ice": true},
  "Toyota GR010": {"bottoming_watch": true, "awd_engage_kmh": 190} }
```
Il muretto legge il profilo dal `vehicle` corrente e attiva le regole
giuste; l'out-lap per classe diventa out-lap PER AUTO.

---

## 8. Livello "Ingegnere Virtuale" — AI, tracciato, pipeline sim

### 8.1 Pipeline dati (PRIMA di tutto — igiene del segnale)
- **Outlier/jitter filtering**: filtro MEDIANO sui picchi impossibili
  (50G per 1 frame da netcode/framerate) prima di ogni media/derivata.
  Obbligatorio e cheap: entra nella Time-Loss Matrix dal giorno 1.
- **Resampling a griglia fissa**: rF2 campiona a passo variabile (dipende
  dal frame): interpolazione (cubica) a frequenza fissa PRIMA delle
  derivate (gradiente frenata, velocita' ammortizzatori) — altrimenti i
  numeri mentono. Nota nostra: il recorder logga gia' t+lapdist per
  sample, quindi il resampling e' un passaggio di analisi, non di raccolta.
- **Normalizzazione condizioni**: tempi normalizzati per `track_temp` (gia'
  nei samples) e gommatura — MAI sgridare il pilota per un giro lento con
  l'asfalto 10 gradi piu' freddo. (Gap piccolo: loggare `track_grip` nei
  samples, 1 colonna.)

### 8.2 Tracciato
- **Curvatura κ della traiettoria** (da pos_x/pos_z gia' campionati):
  κ = |x'y'' − y'x''| / (x'²+y'²)^{3/2}. Picchi di curvatura oltre la
  geometria della curva = pilota che "spigola" → perde velocita' minima.
  Fattibile SUBITO, ottimo compagno della Time-Loss Matrix.
- **Ghost lap teorico**: non la somma dei best micro-settori (fisicamente
  incompatibili) ma ottimizzazione su cerchio d'aderenza. Passo intermedio
  gia' nostro: `theo_lap` (somma settori) → poi la versione vincolata.

### 8.3 Machine Learning (nell'ordine giusto)
1. **PCA/clustering stile di guida** (aggressivo/conservativo/traffico →
   quale stile paga sul PASSO MEDIO, non sul giro secco): fattibile in
   numpy puro sui nostri laps/samples appena c'e' storico. Primo ML da fare.
2. **Predizione cliff gomma** (LSTM su slip+temperature interne, 5-6 giri
   d'anticipo): PRIMA la versione statistica (pendenza EWMA del passo +
   trend carcassa — mezzo gia' vivo con tyre_cliff/deg appreso), POI la
   rete quando i dati bastano.
3. **"Slip magico" del tyre model** (mining sui giri dei piu' veloci):
   possibile col nostro bacino community (refs online + submissions) —
   e' IL vantaggio di avere 10k utenti: dataset che i singoli non hanno.

### 8.4 Priorita' consigliata (dal fattibile-subito al visionario)
1. Pipeline igiene (mediano + resampling) → 2. Time-Loss Matrix per
curva/fase → 3. Curvatura κ → 4. Normalizzazione track temp/grip →
5. ABS Index + blending LMDh (profili auto §7) → 6. PCA stile guida →
7. Cliff predittivo → 8. Ghost lap vincolato → 9. Mining community.

*Fonti: [YourDataDriven](https://www.yourdatadriven.com/guide-to-interpreting-tyre-temperatures-in-motorsports/),
[Autosport Labs](https://www.autosportlabs.com/using_tire_temperatures_for_better_grip_and_faster_lap_times/),
[Alsense](https://www.alsense.eu/racecar-engineering-tire-brake-temperature-sensors/),
[Brembo WEC](https://www.brembo.com/en/motorsport/wec),
[PMW GT3 brakes](https://www.pmw-magazine.com/features/insight-gt3-brake-development.html),
guida ufficiale LMU + docs/dati_lmu.md (finestre verificate).*
