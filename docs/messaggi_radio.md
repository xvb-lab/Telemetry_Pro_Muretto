# Vocabolario radio del muretto — esempi (IT / EN)

Esempi di comunicazioni radio forniti dall'utente (2026-07-20). Guidano
l'arricchimento di `settings/engineer_msgs.json`. Ogni voce: **trigger** (dato
reale LMU che la fa scattare) + **ruolo** (voce) + testo IT/EN. Regole:
consigli non ordini (perentorio solo per sicurezza); si dice solo col dato vero.

Ruoli: 🟢 PERFORMANCE (spotter) · 🔵 STRATEGY · 🟠 RACE ENGINEER

---

## 1. Traffico dinamico (dipende dalla classe che guidi)

### Se guidi HYPERCAR (sei tu che sorpassi) — 🟢 PERFORMANCE
Logica: digli **dove** e **quale classe** incontra, per evitare contatti in staccata.
- *Trigger: gruppo di doppiati di classe inferiore nei ~settori davanti.*
  - EN: "Traffic ahead, GT cluster in sector 2."
  - IT: "Traffico davanti, gruppo GT nel settore 2."
- *Trigger: pista libera dietro.*
  - EN: "Clear track behind, focus on entry."
  - IT: "Pista libera dietro, concentrati sull'ingresso."
- *Trigger: doppiato specifico identificato + lato/curva.*
  - EN: "Pass the Mustang on the left, turn 4."
  - IT: "Passa la Mustang a sinistra, curva 4."

### Se guidi LMGT3 (sei tu che vieni sorpassato) — 🟢 PERFORMANCE
Logica: il muretto è il suo **specchietto** — evita che chiuda su un prototipo.
- *Trigger: prototipo più veloce in avvicinamento + gap.*
  - EN: "Hypercar closing, 3 seconds back."
  - IT: "Hypercar in rimonta, 3 secondi dietro."
- *Trigger: prototipo affiancato in curva + lato.*
  - EN: "Hold your line, Porsche inside turn 1."
  - IT: "Tieni la traiettoria, Porsche all'interno curva 1."
- *Trigger: leader in sorpasso ora.*
  - EN: "Leader passing now, stay right."
  - IT: "Il leader passa ora, stai a destra."

## 2. Strategie di stop (pit window / incroci) — 🔵 STRATEGY

- **Pre-avviso (3 giri alla sosta)** — *Trigger: giri alla sosta pianificata = 3.*
  - EN: "Pit stop in 3 laps. Energy target is {mj} MJ per lap. Confirm."
  - IT: "Sosta tra 3 giri. Target energia {mj} MJ a giro. Conferma."
- **Chiamata box (giro di rientro)** — *Trigger: giro sosta; sicurezza.*
  - EN: "Box this lap, box this lap. Fuel only, no tyres. Confirm pit limiter."
  - IT: "Box questo giro, box questo giro. Solo carburante, niente gomme. Conferma limitatore."
- **Variazione piano (traffico/meteo)** — *Trigger: piano cambiato.*
  - EN: "Invert to Plan B. Staying out, 2 more laps. Push now."
  - IT: "Passa al Piano B. Restiamo fuori, altri 2 giri. Spingi ora."

## 3. Gestione auto (gomme / freni / VE) — 🟠 RACE / 🟢 PERFORMANCE

- **Surriscaldo gomma** — *Trigger: temp core ruota oltre finestra (es. >90° GT).*
  - EN: "Front left tyre core overheating, {deg} degrees. Back off in turn 3."
  - IT: "Anteriore sinistra in surriscaldamento, {deg} gradi. Alza il piede in curva 3."
- **Freni critici** — *Trigger: temp freni oltre limite classe.*
  - EN: "Brake temps critical. Use more engine braking."
  - IT: "Temperature freni critiche. Usa più freno motore."
- **VE oltre target** — *Trigger: consumo VE > target del piano.*
  - EN: "Energy consumption too high. Target is minus {mj} MJ. Lift and coast 100 meters."
  - IT: "Consumo energia troppo alto. Target meno {mj} MJ. Lift and coast a 100 metri."

---

*Molti hanno già un codice in `engineer_msgs.json` (gap_/traffic_/box_/chk_…);
i nuovi elementi da aggiungere: traffico CONSAPEVOLE DELLA CLASSE (HY vs GT3),
target in MJ espliciti, lato+curva del sorpasso. Ogni voce nuova va assegnata a
un ruolo in `engineer/roles.py`.*
