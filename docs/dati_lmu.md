# Dati di dominio LMU — riferimento AUTOREVOLE

Valori forniti dall'utente (esperto di dominio) il 2026-07-20. Sono la **base
della strategia e degli allarmi** del muretto: il codice va calibrato su
QUESTI numeri, non su assunzioni. Non contraddire con l'intuizione.

---

## 1. Virtual Energy vs Benzina — per classe

In LMU l'auto può avere **VE e benzina insieme**: si consumano in parallelo.
Il vincolo che LEGA lo stint dipende dalla classe.

| Classe | Vincolo stint | Valore | Note |
|---|---|---|---|
| **Hypercar (HY)** | **Virtual Energy** | ~880–910 MJ/stint (BoP per costruttore) | consuma **VE *e* benzina**; VE a 0% = **Stop&Go 100 s** |
| **LMGT3** | **Virtual Energy** | ~350–380 MJ/stint (BoP circuito) | auto a benzina, ma VE a 0% = **Stop&Go 100 s** (~53–55 min a pieno regime) |
| **LMP2** | **Benzina** | serbatoio 75 L | niente VE nell'HUD; stint finisce coi litri |
| **LMGTE AM** | **Benzina** | ~88–90 L (BoP classico) | reg. 2023, zero VE |
| **LMP3** | **Benzina** | 100 L | nessun sistema VE/ibrido |

**Implicazioni muretto:**
- HY e LMGT3 → il vincolo è la **VE**; finirla = penalità 100 s (grave quanto
  restare a secco → chiamata di sicurezza).
- HY → tenere d'occhio **anche i litri** (si consumano entrambi).
- LMP2/LMP3/GTE AM → vincolo **benzina**, niente VE.
- Il constraint si rileva dai dati LMU (presenza voce VIRTUAL ENERGY), MAI
  assunto dal buonsenso. Vedi memoria `lmu-gt3-energia`.

---

## 2. Gomme e freni — finestre per gruppo di classe

### Prototipi (Hypercar / LMP2 / LMP3)
**Gomme slick (S/M/H)**
- Finestra esercizio (core/carcassa): **75–87 °C**
- Picco max (inizio perdita grip): 90–95 °C
- Minima di funzionamento: 60 °C (sotto = scivola completamente)
- Pressione minima a caldo: **1.80–1.95 bar** (mai sotto 1.80)

**Freni (carbonio)**
- Minima efficienza: **250 °C** (sotto = non frena alla prima staccata)
- Finestra ottimale: **350–650 °C**
- Overheating: **800 °C**
- Setup: regola i brake ducts per tenerli verdi nell'MFD.

### Gran Turismo (LMGT3 / LMGTE)
**Gomme slick (S/M/H)**
- Finestra esercizio (core/carcassa): **70–90 °C**
- Picco max (inizio perdita grip): 95–100 °C
- Minima di funzionamento: 55 °C
- Pressione minima a caldo: **1.90–2.00 bar**

**Freni (acciaio / carbonio GT)**
- Minima efficienza: **150 °C**
- Finestra ottimale: **300–550 °C**
- Overheating: **700 °C**
- Nota: le GT3 accumulano calore nei circuiti stop-and-go (Imola/Fuji).

---

## 3. Temperature motore (tutte le classi)
- **Olio**: ottimale **95–110 °C** · max **130 °C** (poi rottura)
- **Acqua**: ottimale **90–100 °C** · max **110 °C** (poi rottura)
- Sotto **80 °C** olio/acqua la mappa motore **taglia potenza** in automatico.

---

## 4. Tempi ai box (costo sosta — base della matematica strategica)

### Hypercar / LMGT3 (gestione Virtual Energy)
**Rifornimento energia (VE/NRG)**
- Base (innesto bocchettone): ~**7.5-8 s**
- Velocità di carica: in base alla VE mancante
- Pieno completo 0%→100% VE: ~**30-32 s** totali
- Regola: il tempo dipende **solo dalla % di VE** caricata, non dai litri reali.

**Cambio 4 gomme**: **12 s** netti (sequenziale: 5 s sx + 2 s spostamento + 5 s dx).
Parziale (solo ant. o solo post.): **5.5 s**.

**Sosta piena (VE 100% + 4 gomme): ~42-44 s.**

### LMP2 / LMGTE / LMP3 (litri di benzina reali)
**Rifornimento benzina**
- Base (innesto): ~**7 s**
- Imbarco: ~**2.1-2.5 L/s** (0.43-0.47 s per litro)
- Es. LMP2 +60 L: ~26-28 s di sola benzina · LMGTE +75 L: ~31-33 s

**Cambio 4 gomme**: **12 s** netti (stessa meccanica, niente simultaneo).

**Sosta piena (serbatoio vuoto + 4 gomme): ~38-45 s.**

> Nota: LMU espone anche una **stima sosta live** del gioco
> (`/rest/strategy/pitstop-estimate`) col pit-menu attuale — da preferire quando
> disponibile; questi valori sono il riferimento/fallback.

---

## 5. Modello degrado & consumi (pMBI — implementazione Studio 397)

Il degrado NON è lineare sui giri: è **multifattoriale**, calcolato in tempo reale.

**A. Usura meccanica (abrasione)** — dipende da Load (carico verticale) × Slip
velocity (scorrimento). HY: mescole rigide per reggere ~11500 N di downforce →
usura lenta. LMP2: sensibile agli angoli di deriva prolungati. GT3: peso 1300+ kg
+ camber del setup.

**B. Degrado chimico/termico (glazing / blistering)** — se la superficie supera
la soglia critica a lungo (es. **>105°C HY**), la mescola "cuoce": `Mu_peak` cala
in modo **permanente** (fino a **15-20%**) anche col battistrada intatto. Sintomo:
le **temperature crollano** (la gomma vetrificata scivola) → sottosterzo cronico.
→ **Glazing Index** = integrate(IF superficie>105,1,0): se sale, **anticipa il pit**.

**C. Deformazione plastica (flatspot)** — il bloccaggio in frenata crea un piatto:
vibrazioni + oscillazione del carico dinamico. Nelle **GT3 mitigato dall'ABS**.

**Consumi HY (Virtual Energy):** MJ, ~900/stint (BoP). Somma ICE + MGU-K, misurata
da sensori di coppia FIA sui semiassi. **Wheel spin (Slip Ratio >0.15) in uscita =
MJ CONTEGGIATI COME SPESI** anche senza accelerazione → **il sovrasterzo di potenza
taglia lo stint di 1-2 giri.** (Voce muretto live se abbiamo lo slip.)

**Consumi LMP2:** litri (~75 L), legati a RPM + Throttle. L&C + mappa magra → -5/8%.
**Consumi GT3:** litri + **restrittore di flusso BoP** → **rifornimento più lento** →
risparmiare benzina in pista = **meno secondi fermi ai box** (pesa sulla scelta sosta).

*(La formula "giri rimanenti" (Energy/burn o Fuel/used) è GIÀ in `lmu_live`:
`autonomy_laps`. Non si riscrive.)*

---

*Da usare per calibrare `_thermal_windows` / allarmi motore / strategia energia
e per il COSTO SOSTA nella matematica di `docs/logica_strategia.md`. Verificare
che i valori nel codice coincidano con questi.*
