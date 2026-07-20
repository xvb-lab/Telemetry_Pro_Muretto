# Logica strategica del muretto — spec autorevole

Ragionamento strategico fornito dall'utente (2026-07-20). È il "come decide" il
muretto. Regole fisse: **dati SOLO da LMU** (se manca, tace); **consigli non
ordini** (il muretto informa/consiglia; "box" perentorio solo per sicurezza —
qui: VE/benzina in esaurimento, wet, danno). La logica gira su **loop continuo**.

---

## 0. I tre flussi di dati del loop

1. **Ambiente**: % acqua in pista, evoluzione meteo (forecast).
2. **Vettura**: VE residua (MJ / %), litri benzina, temp **core gomme** (FL/FR/RL/RR),
   usura gomme.
3. **Cronometrico**: tempo sul giro, distacco dal delta ideale dello stint.

---

## 1. Asciutto (Dry) — obiettivo: DOUBLE/TRIPLE stint gomme

Cambiare gomme in LMU costa **~25-30 s**. Tenerle 2 stint = risparmi una sosta.
Al pit si cambia solo carburante/VE.

**Fase 1 — degrado (wear rate).** A fine 1° stint calcola l'usura % della gomma
PEGGIORE (spesso FL o RD secondo il circuito).
- usura **< 35%** → la gomma può fare un **2° stint**.
- usura **> 45%** → a fine 2° stint sarebbe **sotto il 10%** di vita → spiattellamento
  e crollo grip repentino ("**la rupe del degrado**"). NON tenerla.

**Fase 2 — finestra VE.** Monitora MJ/giro medi. Se il calcolo prevede VE a 0 a
**0.5 giri** dal traguardo/sosta → attiva routine **Lift & Coast**.

**Overcut (risparmio stint).** Se l'auto davanti si ferma → pista libera. Se le
tue **core gomme** sono ancora in finestra (75-87 °C proto) → spingi 2 giri a
energia massima (mappa alta): guadagni sui suoi pneumatici freddi appena montati.

---

## 2. Bagnato e transizione (Wet & Crossover)

Chiave: **% acqua in pista** (track wetness dalla telemetria). Sbagliare il
momento distrugge la gomma in 2 giri.

**Slick → Wet (si bagna).**
- **0-15%**: resta **slick**; alza il TC di +2 scatti.
- **15-20%** (zona grigia): monitora temp superficiali slick; sotto **55 °C** perdi
  aderenza.
- **> 20%**: chiama il **pit per le Wet**.

**Wet → Slick (asciuga) — il vero risparmio.**
- Sotto **15%** acqua la Wet bolle (core **>95 °C**), i tasselli si sciolgono.
- Se mancano pochi giri a fine gara/sosta carburante → **NON** fermarti per le
  slick: consiglia di guidare **fuori traiettoria nelle pozzanghere** (sui
  rettilinei) per **raffreddare** la Wet. Allunghi la vita della Wet su asciutto,
  risparmi una sosta da ~30 s.

---

## 3. Matematica per risparmiare uno stint (Fuel/VE saving)

Per togliere una sosta in gare lunghe (2.4h, 4h) estendi ogni stint di **1-2 giri**
rispetto allo standard.

**Ciclo (ogni giro):**
```
Giri_Rimanenti      = Giri_Totali - Giro_Attuale
Stint_Necessari     = Giri_Rimanenti / Autonomia_Max_Standard
```
Se il risultato ha decimale basso (es. **4.1** stint) → ti fermeresti a fine gara
per soli ~2 litri: **è lì che si risparmia lo stint**.

**Mitigazione (target consumo):**
```
Target_MJ_giro = VE_Rimanente / Giri_alla_sosta_ideale
```
Se serve risparmiare ~5%/giro → consiglia **Lift & Coast 100 m prima** di ogni
staccata principale.

**Controllo incrociato:** se il giro si alza di soli **0.4 s** ma eviti una sosta
da **30 s**, il guadagno netto a fine gara è **~15-20 s**.

---

## 4. Profilo strategico per classe

### Hypercar (HY) — efficienza ibrida
~1030 kg, ibrido 4WD/RWD, VE in **MJ** dai sensori di coppia. La mappa motore
influenza direttamente il consumo VE. Se la VE finisce prima della benzina →
**Lift & Coast**. **Doppio stint gomme = standard sull'asciutto** (risparmia i
12 s del cambio). Usura: 4WD (Toyota/Ferrari/Peugeot) anteriori più omogenee;
LMDh RWD (Porsche/Cadillac/BMW) tendono a distruggere le **posteriori**. In sim
il consumo è lineare/matematico (stile di guida + TC). **Rischio: Stop&Go 100 s
per sforamento VE.**

### LMGT3 — gomme + bloccaggio freni
~1300+ kg, no ibrido, VE per BoP. Usura **asimmetrica** (motore ant./centrale/
post. secondo l'auto): sui stop-and-go (Imola/Fuji) fuori le posteriori (trazione)
o le anteriori (inserimento). **Doppio stint più rischioso** della HY → spesso si
cambiano solo le **2 gomme più sollecitate** (~6 s). **ABS**: troppo alto =
surriscaldi la superficie in frenata; troppo basso = **spiattellamento**. Il
muretto monitora i **picchi di temp gomma dopo le staccate**. Autonomia energia
~53-55 min. Focus: **conservazione gomma posteriore**. Critico: **temp core /
canale ABS**. Rischio: spiattellamento + surriscaldamento.

### LMP2 — classica "old school"
Oreca 07 / Gibson V8, **niente VE né ibrido**. Calcolo sui **litri reali** (75 L),
consumo costante. Nessun sensore di coppia: finire la benzina = **auto si spegne**,
**niente Stop&Go 100 s**. Usura molto **lineare** (~930 kg); **triplo stint**
possibile su piste a basso degrado (Le Mans). Focus: **soste minime** (multi-stint
gomme). Critico: **litri**. Rischio: **restare a secco in pista**.

### LMP3 — classe d'ingresso (ELMS)
Come LMP2 ma meno potenza, gomme più strette. **No ABS**, freni in **acciaio**
(non carbonio). Focus termico: **non far raffreddare troppo i freni** sui
rettilinei lunghi (parzializza i condotti) o non frena alla curva dopo. Serbatoi
100 L → stint lunghi, ma le gomme calano di più nella **2ª metà** dello stint
rispetto alle LMP2. Critico: **finestra d'esercizio gomma / temp freni**.
Rischio: **bloccaggio anteriore + usura precoce**.

### Tabella comparativa
| Classe | Focus muretto | Variabile critica | Rifornimento su | Rischio principale |
|---|---|---|---|---|
| **Hypercar** | efficienza / recupero | MJ residui | finestra VE | Stop&Go 100 s (sforamento VE) |
| **LMGT3** | conservazione gomma post. | temp core / canale ABS | finestra VE | spiattellamento + surriscaldo |
| **LMP2** | soste minime (multi-stint) | litri benzina | litri reali | restare a secco |
| **LMP3** | temp freni acciaio | finestra gomma | litri reali | bloccaggio ant. + usura precoce |

---

## 5. Architettura calcolo (Studio 397) + conflitto pit-time

**Lo stint finisce al LIMITE MINORE tra tre:**
1. **Energia/carburante**: `floor(capacità / consumo_giro)` (HY in MJ, es. 900/80 = 11 giri).
2. **Gomme**: `floor(100% / usura_giro_ruota_peggiore)`; anticipa se glazing/usura oltre soglia (il drop-off costa più del cambio).
3. **Tempo di guida** (endurance): limite regolamentare pilota.
Il muretto prende il **minimo**. Buona parte è già in `lmu_live` (`autonomy_laps`,
`laps_needed`).

**Decisione cambio vs double-stint** (formula S397):
`IF(drop_off_giro * giri_rimanenti_stint > ~15 s) → CAMBIA, altrimenti DOUBLE STINT`.
Double-stint quasi obbligato se asfalto <25°C e usura meccanica <40% a fine stint.

**FCY/Slow Zone (80 km/h):** giro +35-45% di tempo, consumo -50/60%; un giro FCY
allunga lo stint energetico HY di ~0.7 giri. In finestra → **entra subito** (pit
loss relativo crolla); fuori finestra → mappa risparmio estremo.

**Extreme fuel saving vs Splash&Dash:** in LMU conviene SEMPRE risparmiare (L&C
+0.4 s/giro) piuttosto che una sosta extra a fine gara (~33 s persi). Target:
`MJ_target_giro = VE_attuale / giri_rimanenti`.

**⚠️ CONFLITTO pit-time (da NON risolvere a mano):**
- Studio 397: **rifornimento e gomme SIMULTANEI** (`Simultaneous_Pit_Work=TRUE`),
  i tempi **non si sommano** → sosta ≈ max(refuel, gomme), non somma.
- Ma `dati_lmu.md §4` sommava (VE 30-32 + gomme 12 = ~42-44 s). E i numeri
  divergono (Le Mans 28 vs 34.5 s; cambio gomme 14-16 vs 12 s; refuel LMP2 3.5
  vs 2.1-2.5 L/s; refuel GT3 ~2.8 L/s con restrittore; ricarica HY ~25 MJ/s).
- **Risoluzione:** per il tempo sosta il muretto usa la **stima LIVE del gioco**
  `/rest/strategy/pitstop-estimate` (tiene conto del simultaneo) → autorevole; le
  costanti sono solo fallback. Il conflitto diventa irrilevante live.
- Serbatoi GT3 variabili: Ferrari 296 ~105 L, Porsche ~100 L (da dato LMU, non fisso).

---

## 6. Moduli avanzati (RealRoad, traffico, affidabilità 24h, coaching)

**RealRoad / crossover** — `Track_Rubber_Level` (0→1, più gomma = meno slip =
meno usura); **wetness on-path vs off-path** (l'off-path serve per i sorpassi in
wet; forse già in `wetness_min/max`). Crossover affinato: Wet quando **on-path
>18%** OPPURE **temp slick <65°C** sostenuta (water cooling). Aquaplaning ~
speed×wetness/tread (oltre soglia il carico anteriore crolla).

**Traffico multi-classe** 🟢 — `Traffic_Time_Lost = sector_actual - sector_ideal`.
Undercut strategico: se `laps_to_pit<3` E si prevede un gruppo GT3 in un settore
→ **box in anticipo** per uscire in **aria pulita** (perdere ~4 s nel traffico >
fermarsi 2 giri prima del target). *Serve lo scoring glue (settori + rivali).*

**Affidabilità endurance (6/8/24h)** 🟢 NUOVO —
- Motore: `Engine_Stress = integrate((RPM/maxRPM)*(temp/115))`; **overrev/money-shift
  = danno permanente**. Azione: se acqua >105°C sostenuta nel traffico →
  **short-shift** (cambia 500 rpm prima) o esci dalla scia. *(RPM+temp li abbiamo.)*
- Freni: HY carbonio ~0 usura a ~600°C, **catastrofica <200°C** (abrasione a
  freddo) o **>900°C** (ossidazione). *(temp freni live.)*

**Coaching / consistenza** 🟢 —
- `Stint_Consistency = std_dev(ultimi 5 giri puliti)`; target Gold/Plat **<0.350 s**
  a Le Mans. *(costruibile dai lap time.)*
- Brake release smoothness (deriv. pedale freno), coasting per raffreddare le
  posteriori a metà stint. *(serve il canale pedali.)*

---

## Mappa ai dati che GIÀ abbiamo (core)

- Autonomia / per_lap / laps_needed / target_pct / constraint → `lmu_live`
  (`core/strategy.py`). Copre gran parte di §1-fase2 e §3.
- Usura gomme (`tyre_wear`), temp core (`tyre_temp`) → `core/reader.py` /
  `shared_memory` → §1-fase1 (wear rate) e §2 (soglie temp).
- Wetness % → reader/shared_memory → §2 (crossover).
- Delta/tempo giro → reader → §0-cronometrico, overcut.

**Da costruire nel cervello** (moduli): decisione double-stint su wear rate,
overcut, crossover wet con le soglie sopra, "elimina una sosta" con la
matematica di §3. Alcuni esistono già in forma nel brain v3 (race_plan/
strategy_check/box_call) → verificare e allineare a QUESTE soglie.
