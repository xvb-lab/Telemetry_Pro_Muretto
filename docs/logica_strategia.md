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
