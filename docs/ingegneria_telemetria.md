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

---

## 9. MURETTO LIVE — matrice causa→effetto (guida → assetto → radio)

> Il cuore operativo: dal SINTOMO rilevato al CONSIGLIO (di guida subito,
> d'assetto al box). Gerarchia interventi: Aero → Molle → Ammortizzatori →
> Geometrie. Regola radio: BREVE, si dice la SOLUZIONE, non il problema.

### 9.1 Matrice assetto per FASE × VELOCITA'
| Fase | Sintomo | Trigger nei nostri dati | Guida (subito) | Assetto (box) |
|---|---|---|---|---|
| **Ingresso** | Sottosterzo in staccata | slip F≫R + sterzo che cresce senza yaw | bias un filo indietro | ARB ant. morbida · bump ant. morbido · toe-out ant. |
| **Ingresso** | Coda che scappa in staccata | slip R≫F in frenata · locks post. | bias avanti · +freno motore | rebound post. piu' duro · coast ramp diff giu' |
| **Centro <120 km/h** | Sottosterzo | slip F≫R a pedali neutri | linea piu' a V | molla/ARB ant. morbida · +camber ant. (se 3-zone conferma) |
| **Centro >160 km/h** | Sottosterzo | idem nei curvoni | — | +carico ant. (flap) o −ala post. · −ride height ant. |
| **Centro** | Sovrasterzo | slip R≫F | — | ARB post. morbida (lenta) · +ala post. / −rake (veloce) |
| **Uscita** | Pattinamento/sovrasterzo trazione | wheelspin per curva (gia' live) · raffiche tc_cut | TC su · gas piu' rotondo | molle/bump post. morbidi · toe-in post. · power ramp su |
| **Uscita** | Power understeer | muso leggero sul gas (slip F sale col throttle) | — | molle post./heave piu' dure · power ramp giu' |
| **Cordoli** | Instabilita' | kerb events + istogramma damper alto | meno cordolo (gia' live) | fast bump giu' · slow rebound post. su |
| **Alta vel.** | Bottoming/stallo aero | ride_h a zero (gia' live) | — | heave/packers su · +2mm altezza |

### 9.2 Regole live da muretto (lap-by-lap)
- **ΔP gomme freddo→caldo**: target pressione a caldo per mescola; il
  muretto calcola il delta dello stint e detta le pressioni di PARTENZA
  del prossimo: *"parti 0,3 piu' bassa sulla posteriore destra: a caldo
  gonfia oltre finestra e consuma il centro"* (canali gia' nei samples).
- **Brake migration col carburante**: l'auto si svuota → il bilancio
  arretra il baricentro → tendenza al bloccaggio ANTERIORE a fine stint
  (trend dei lock per giro): *"sposta il bias 1,5 indietro, il serbatoio
  e' leggero"*.
- **Lift & Coast MIRATO**: dal fuel/VE mapping per curva (§6.2), il
  suggerimento con costo/beneficio: *"alza 50 metri prima di curva 8:
  perdi 0,15 ma risparmi 0,8 megajoule"* — MAI un L&C generico.
- **Freni in finestra**: sotto finestra in rettilineo → "scalda i freni";
  sopra → bias verso l'asse piu' freddo (finestre §2.4 per classe).
- **ABS Index (GT3)**: frequenza abs_active alta a pedale pieno →
  *"riduci la pressione iniziale dell'8%: l'ABS continuo scalda la gomma
  e ALLUNGA la frenata"*.

### 9.3 Formato radio (legge fissa)
- ❌ "Stai perdendo tempo in curva 4" → ✅ *"Curva 4: sacrifica
  l'ingresso, stacca 5 metri dopo, rotazione a V, gas pieno prima."*
- ❌ "L'auto scivola dietro" → ✅ *"TC su di due. Bias a 52, due click
  avanti."*
- Traffico: ✅ *"GT3 in arrivo a curva 8, nessuno dietro: aspetta
  l'uscita, niente tuffi."* (i mattoni live esistono: fast_class,
  box_anticipate/delay)
- E' la stessa regola dei nostri findings: `[Curva]·[Fase]·[Numero]·
  [Azione]` — una lingua sola per voce, debrief e pagina Garage.

### 9.4 Nota implementativa
La matrice 9.1 e' il MOTORE della futura pagina Garage: ogni riga =
regola dati→consiglio, coi nomi VERI del setup LMU (ARB, bump/rebound,
heave, packers, ramp diff, ride height, ali). Il muretto ne usa gia' le
colonne "Guida"; la colonna "Assetto" oggi esce nel debrief (§ findings)
e domani diventera' il Garage advisor con valori cliccabili.

---

## 10. La biblioteca — Goodman, "Race Car Vehicle Dynamics & Design" (MPhil, Aston 2009)

> In `docs/MPhil_EJ_Goodman_2009_reduced.pdf` (230 pp): la TEORIA con le
> formule dietro la matrice §9. Mappa dei capitoli → nostro motore:

| Capitolo (pagina) | Cosa ci da' |
|---|---|
| 7 **The Tyre** (24-60) | 36 pagine di modello gomma: slip angle/ratio, carico→grip — fondamento di §2.1-2.3 |
| 13 Wheel Alignment (80) | toe = slip angle indotto → righe "geometrie" della matrice |
| 14 **Weight Transfer** (83-93) | trasferimenti sospesi/non sospesi, altezze centri di rollio → il PERCHE' di ARB/molle in §9.1 |
| 15 Suspension Rates (94) | motion ratio / installed stiffness → convertire "click molla" in rigidezza RUOTA (serve al Garage advisor per suggerire valori sensati) |
| 16 Damping (98-110) | teoria smorzamento → istogrammi §5.5 |
| 18 Brake System (118) | bilancio freni meccanico |
| 22-24 **Data Analysis** (137-151) | metodologia analisi dati pista (l'antenato accademico del nostro §5) |
| 25 Lap Time Simulation (152+) | simulato vs reale sovrapposti → metodo di VALIDAZIONE per Time-Loss/ghost lap |
| 27 **Track Tuning** (174-181) | il capitolo-gemello del nostro §9 (sotto) |

### 10.1 Metodo da test-day (cap. 27, adattato al sim)
- **Adjustment Table**: registro di OGNI modifica assetto + effetto — se
  nulla funziona, si torna alla baseline. → La pagina Garage DEVE avere
  lo storico modifiche con esito (feature chiave, presa da qui).
- **Un cambio alla volta**: mai due modifiche insieme, o non sai cosa ha
  agito. → Il Garage advisor propone UNA modifica per uscita.
- **Test bilancio freni**: frenate a pedale crescente fino al primo
  bloccaggio → QUALE ruota si ferma prima dice da che parte spostare il
  bias (il nostro lock detector per ruota lo fa gia' in automatico).
- **Test bilancio telaio**: stessa linea a velocita' crescente finche'
  un asse molla → distribuzione momento di rollio ant/post da correggere
  (= il nostro slip F/R per curva, formalizzato).
- **Wheel speeds sovrapposte**: le 4 ruote in un grafico = diagnosi
  freni+trasmissione a colpo d'occhio (da aggiungere alla pagina
  telemetria: plot 4 ruote da `wheel_rot`).
- **Pressioni gomme**: si settano SOLO al momento di uscire (instabili
  da ferme) — coerente col nostro brief d'uscita.

---

## 11. Il lato PILOTA — Bentley, "Data for Drivers" (Speed Secrets, free)

> Il complemento del Goodman: come un COACH legge 4 canali (Speed, G,
> Throttle, Brake) per migliorare il pilota. Regole semplici, tutte
> rilevabili coi nostri dati:

- **U vs V nella traccia velocita'**: curva a U = rolling speed portata
  (bene nei curvoni), V = punta-e-gira (bene nei tornanti). Il TIPO
  sbagliato per quella curva = tempo perso → confronto forma vs best.
- **Coasting / "lazy throttle"** (LA regola d'oro): tempo tra rilascio
  freno e prima apertura gas. Se veleggi (niente pedali) piu' di ~0,4s
  nella stessa curva ripetutamente → *"raccorda freno e gas in curva X"*.
  → IMPLEMENTATO live (coast detector per curva nel corner coach).
- **Sloppy footwork**: blip/sovrapposizioni freno-gas sporche in scalata
  (visibili incrociando throttle, brake e LongG) → analisi post.
- **Forma della frenata**: colpo iniziale deciso + rilascio dolce = buona;
  gradini/esitazioni = "hesitant lap" (post, dal gradiente §5.2).
- **Min speed su PIU' giri, non solo il best**: la consistenza delle
  minime per curva vale piu' del giro singolo (gia' nel nostro §8 PCA
  e nel confronto vmin per curva).
- **In fast - out slow**: sterzo mantenuto a lungo + LatG estesa +
  "secondary deceleration" = sei entrato troppo forte e stai
  strusciando via velocita' → firma: sterzo che non si apre dopo
  l'apex mentre la velocita' cala ancora.
- **Processo di revisione** (ordine fisso): Speed → LatG → LongG →
  Throttle → Brake → Steering — buon ordine anche per i tab della
  pagina telemetria.
- Fonte: PDF ufficiale gratuito Speed Secrets (2018), 68 pp — scaricato
  e verificato. Cita a sua volta il Segers come riferimento avanzato.

---

## 12. OptimumG Tech Tips (Giaraffa/Rouelle) — molle e frequenze

> Serie gratuita ufficiale OptimumG. Tip 1 "Springs & Dampers — The
> Phantom Knowledge": la BASE NUMERICA per le molle del Garage advisor.

- **Frequenze di ride**: si parte dalla frequenza naturale desiderata,
  non dalla molla: `f = (1/2π)·√(K/m)` → la molla si RICAVA da massa
  sospesa per ruota + motion ratio + frequenza target.
- **Regola del 10%**: il POSTERIORE va ~10% piu' alto di frequenza
  dell'anteriore — dopo un bump il retro "raggiunge" il fronte e il
  beccheggio si smorza (fondamento della riga bottoming/heave §9.1).
- Range tipici (letteratura OptimumG): stradali 0,5-1,5 Hz · racing
  senza effetto suolo ~1,5-2,5 Hz · aero car 3-5+ Hz. Il Garage advisor
  usera' la classe per proporre la finestra giusta.
- **Tip 2 — la formula della molla** (con disciplina delle unita', kg
  non Newton!): `Ks = 4π² · fr² · m_sospesa · MR²` (MR = motion ratio
  ruota/molla). E baseline **barre antirollio** dal roll gradient scelto.
- **Tip 3 — terza molla (heave)**: ride frequency alta per l'aero SENZA
  irrigidire il bump singolo (es. ride 1,5 Hz, singola ruota 1,0 Hz):
  e' la teoria dietro la riga heave/packers della matrice §9.1.
- **Tip 4 — damping**: trasmissibilita' (output/input in ampiezza),
  damping ratio e curva ammortizzatore di BASELINE → i numeri per
  giudicare gli istogrammi §5.5.
- Fonte: 4 PDF ufficiali optimumg.com (scaricati e letti). NB: il
  contenuto del SEMINARIO OptimumG e' proprietario (le copie su Scribd
  sono upload non autorizzati): i Tech Tips gratuiti coprono la teoria
  che ci serve.

---

## 13. Le VIE DEI DATI in LMU — mappa completa (verificata)

1. **Shared memory (mmap+ctypes)** — LA nostra via, gia' in produzione
   (pyLMUSharedMemory): TelemetryInfo alta frequenza + ScoringInfo
   sessione. Tutto il doc si basa su questa.
2. **Plugin C++ / DamPlugin → MoTeC .ld** — via power-user opzionale:
   massima fedelta' per chi vuole i2 Pro. Non necessaria al nostro
   stack (il recorder SQLite copre l'analisi §5); da valutare solo come
   export "pro" futuro. (Compatibilita' DamPlugin-LMU da verificare.)
3. **⭐ RESULTS XML (`UserData/Log/Results/*.xml`) — LA PEPITA, verificata
   sul disco (2416 file!)**: per OGNI vettura, OGNI giro:
   `s1/s2/s3, topspeed, fuel+fuelUsed, ve+veUsed,` e **usura delle 4
   gomme per giro** (`twfl twfr twrl twrr`) + mescole per ruota.
   Cioe': dati che l'HUD non mostra — anche dei RIVALI. Sblocca:
   - **curve di degrado degli avversari** (§6.5 applicato agli altri):
     undercut/overcut calcolato su usura VERA, non stimata
   - consumi rivali giro per giro → previsione delle loro soste
   - stint analysis post-gara di tutto il campo (pagina Race Control /
     futura pagina report)
   - calibrazione del nostro modello degrado con centinaia di gare
     d'archivio GIA' presenti
   → Parser XML = prossimo mattone dati ad altissimo rendimento.
   **⚠ VERITA' VERIFICATA (23/07)**: questi XML locali esistono solo per
   sessioni OFFLINE/custom (`ConnectionType=Custom`); le gare ONLINE
   RaceControl NON li scrivono in locale (S397 protegge i dati altrui in
   MP — niente app-spia). STRATEGIA A DUE STADI, come i team veri:
   1) OFFLINE: calibrare il modello usura→perdita di passo per
      auto/pista/mescola sull'archivio (migliaia di giri gia' sul disco);
   2) ONLINE: applicare il modello alla curva dei TEMPI dei rivali
      (sempre pubblici) → degrado e finestre pit STIMATI da ingegnere,
      non letti. Nemmeno i team WEC vedono la telemetria altrui.
4. **Trace log** (`trace*.txt`) — gia' usato: penalita' verbatim,
   track limits lifecycle, pass monitoring (coi suoi limiti di flush).
5. **REST localhost:6397** — gia' usato: pit menu, wearables, strategia,
   regole sessione, gomme disponibili.

Riferimenti codice aperto per confronto mapping: CrewChiefV4 (C#),
SimHub rF2 plugin, wrapper "rFactor 2 Shared Memory Python".

---

## 14. Decisioni di ARCHITETTURA (il verdetto, agli atti)

> Valutata la proposta "pro" classica (plugin C++ → ZeroMQ → Python →
> web dashboard) contro il nostro stack REALE e funzionante. Regola:
> ogni pezzo deve avere una ragione, non un pedigree.

| Livello | Scelta NOSTRA | Perche' |
|---|---|---|
| Estrazione | Python mmap+ctypes, **64 Hz** (misurato) | copre tutto il §5 salvo damper fini; un plugin C++ nel gioco = iniezione (rischi anti-cheat online), manutenzione a ogni patch, toolchain per gli utenti |
| Trasporto | NESSUN bus: 3 processi leggono la shared memory in modo indipendente | zero single-point-of-failure, zero serializzazione; ZeroMQ ha senso TRA pc, non sullo stesso host |
| Storage | SQLite batched (WAL) | regge 64 Hz, interrogabile in SQL; la critica al CSV e' giusta ma non ci riguarda; parquet solo per export/analisi |
| Analisi | Python + **NumPy/SciPy** (dal §5 in poi) | filtri, derivate, resampling, Time-Loss; ML con sklearn/numpy prima di qualsiasi framework pesante (§8) |
| UI | PySide6 nativo | 10k utenti vogliono un exe, non un server; web/Grafana = complessita' operativa spostata su di loro |

**Opzioni future nel cassetto** (solo se il bisogno diventa reale):
- sidecar **C# esterno** (shared memory → ring binario 200+ Hz) per gli
  istogrammi damper spinti — MAI un plugin dentro il gioco;
- mini-server FastAPI per un **pit-display su tablet** (muretto sul
  secondo schermo di casa).

*Fonti: [YourDataDriven](https://www.yourdatadriven.com/guide-to-interpreting-tyre-temperatures-in-motorsports/),
[Autosport Labs](https://www.autosportlabs.com/using_tire_temperatures_for_better_grip_and_faster_lap_times/),
[Alsense](https://www.alsense.eu/racecar-engineering-tire-brake-temperature-sensors/),
[Brembo WEC](https://www.brembo.com/en/motorsport/wec),
[PMW GT3 brakes](https://www.pmw-magazine.com/features/insight-gt3-brake-development.html),
guida ufficiale LMU + docs/dati_lmu.md (finestre verificate).*
