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

*Fonti: [YourDataDriven](https://www.yourdatadriven.com/guide-to-interpreting-tyre-temperatures-in-motorsports/),
[Autosport Labs](https://www.autosportlabs.com/using_tire_temperatures_for_better_grip_and_faster_lap_times/),
[Alsense](https://www.alsense.eu/racecar-engineering-tire-brake-temperature-sensors/),
[Brembo WEC](https://www.brembo.com/en/motorsport/wec),
[PMW GT3 brakes](https://www.pmw-magazine.com/features/insight-gt3-brake-development.html),
guida ufficiale LMU + docs/dati_lmu.md (finestre verificate).*
