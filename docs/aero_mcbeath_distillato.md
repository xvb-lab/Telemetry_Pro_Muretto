# Competition Car Aerodynamics (McBeath, 3ª ed.) — distillato 23/07

Fonte: S. McBeath, *Competition Car Aerodynamics* (letture mirate: cap.
5 ali, cap. 6 fondo, cap. 8 misure in pista). PDF locale gitignorato.
Il nostro vantaggio sleale: **LMU ci dà la downforce VERA in Newton**
(`df_front`/`df_rear`) e le altezze per ruota (`ride_h`) live — quello
che McBeath misura con celle di carico e laser, noi lo leggiamo gratis.

## Le leggi operative

### Ali (cap. 5)
- **Angolo**: la downforce cresce con l'angolo fino allo **stallo**
  (profilo singolo: picco verso 12-16°). Un po' di separazione al picco
  è NORMALE; oltre, la downforce CROLLA ma il drag resta → un click
  d'ala oltre lo stallo è tutto perso. Per il nostro `R WING P1-P18`:
  se un click in più non aumenta il carico misurato (`df_rear`), sei
  al limite utile — torna indietro.
- **Camber**: più camber = più carico a parità d'angolo, fino a un
  limite oltre cui il flusso molla (nel suo studio: 9% ok, 12% collassa).
- **Regola pratica per i click**: valutare OGNI click con il carico
  misurato, non a sensazione: ΔdF_rear reale vs Δvelocità di punta.

### Ala anteriore e sensibilità al beccheggio
- Vicino al suolo l'ala anteriore può rendere **fino al doppio** che in
  aria libera; a 63mm rende ~33% in più che a 132mm → sensibilissima
  all'altezza.
- Troppo bassa → **stallo a compressione** → il muso si rialza → il
  flusso riattacca → risucchiato giù di nuovo = **porpoising**
  (oscillazione). Rimedi reali: terzi elementi e damping low-speed che
  controllano l'assetto (li abbiamo nel .svm!).
- **Detector possibile da noi** (backlog): oscillazione periodica di
  `ride_h` anteriore + `df_front` nei tratti veloci = porpoising/pitch
  sensitivity → consiglio: +1mm davanti o più pacchetto.

### Fondo e RAKE (cap. 6 — dati VW Motorsport)
- Fondo piatto con **rake negativo** (muso più basso della coda) =
  venturi: gola corta davanti, lungo diffusore dietro.
- **Abbassare il davanti o alzare il dietro**: più downforce TOTALE e
  bilancio spostato **in AVANTI** — bastano 1-2 gradi per cambiare
  tanto. È la manopola di bilancio più potente dopo le ali.
- Limite: troppo basso davanti = separazione/stallo del fondo (e il
  nostro finding `diffuser_stall` già guarda il posteriore basso).
- Diffusori corti e ripidi restano attaccati grazie all'interazione con
  l'ala posteriore (piano basso) → toccare l'ala cambia ANCHE il fondo.

### Misurare (cap. 8) — il protocollo che il muretto può GUIDARE
- **Test A/B alla Carroll Smith**: 5 giri per configurazione, stessa
  pista/gomme, scarta i giri anomali, media, e RITORNA alla baseline
  periodicamente (gomme che calano falsano il confronto).
- **Rettilineo a velocità costante** (Somerset/F1): tratto fisso,
  velocità tenuta costante, leggi il carico medio → confronto tra
  configurazioni. Noi: `df_front`/`df_rear` medi su un tratto di
  rettilineo a V costante = numeri da vero tunnel del vento.
- **Coastdown per il drag**: folle da alta velocità, il tasso di
  decelerazione = drag totale; per i CONFRONTI (config A vs B) non
  serve scorporare l'attrito meccanico.
- Sempre: **contano gli incrementi**, non i valori assoluti.

## Cosa ne facciamo (agganci concreti)
1. **Consiglio ala v2**: oggi consigliamo ±1 click dal comportamento
   (attitude velocity). Upgrade: verificare il click con `df_rear`
   misurata (se +1 click non porta carico → stallo, torna giù) e
   avvisare del costo in velocità di punta.
2. **Bilancio aero** già misurato (df front %): con le leggi del rake,
   il Setup Advisor del Garage potrà proporre rake invece di ala dove
   serve bilancio + carico insieme.
3. **Porpoising detector** (backlog): oscillazioni ride_h+df davanti.
4. **Modalità "test aero" guidata** (backlog Garage): il muretto guida
   il protocollo A/B (5 giri, baseline, medie) e riporta ΔdF, Δv_max,
   Δtempi — il tunnel del vento dei poveri, ma coi numeri veri di LMU.
