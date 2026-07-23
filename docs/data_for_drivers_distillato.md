# Data for Drivers (Bentley/Speed Secrets) — distillato 23/07

Fonte: webinar "Data for Drivers" (Speed Secrets 2018), 68 slide. Non è
un libro d'ingegneria: è **come un COACH legge i dati e come PARLA al
pilota**. Complementare a Segers (l'ingegnere) — questo è il tono giusto
del nostro muretto quando fa coaching. PDF locale gitignorato.

## Euristiche di lettura (implementabili sui nostri canali)

| Firma nei dati | Diagnosi | Canali nostri |
|---|---|---|
| Cambio di pendenza nella decelerazione della VELOCITÀ | trail braking presente/assente (conferma col freno) | speed, brake |
| Gobba nel freno durante la scalata + calo del −G | il BLIP sta rovinando la frenata (footwork) | brake, g_long, gear |
| Pendenza di accelerazione che si affloscia tra le curve | "gas pigro" / veleggio (già nostro coast_waste) | speed, throttle |
| Gas che sale presto poi RICADE con laterale ancora alto | apertura anticipata → costretto a mollare in uscita (il classico errore: entry speed alta che ammazza l'uscita) | throttle, g_lat |
| Min speed che arriva TARDI nella curva | uscita lenta: ha portato troppa velocità in ingresso | speed vs lapdist |
| Decelerazione SECONDARIA dopo il rilascio freno | sta finendo la pista: tiene sterzo e "gratta" velocità (largo sull'uscita) | g_long, steer, g_lat |
| Curve: forma a **U** sopra ~105 km/h, a **V** sotto (aero: soglia ~120) | se la forma non torna, chiedersi PERCHÉ (linea sbagliata) | speed per curva |
| Giro "esitante" (freno incoerente, rilasci pigri, gas timido) | spesso è TRAFFICO — verificare prima di correggere il pilota | (noi: gap_ahead!) |
| Il giro più veloce NON è la verità: guarda i minimi PER CURVA sui giri diversi | il giro ideale = cucire i migliori settori (già nostro: theoretical) | db giri |

## Il processo del coach (per il debrief e l'Engineer Report)

Per ogni canale: guarda → nota l'incongruenza → scava → **chiedi PERCHÉ**
→ conferma con un altro canale → confronta (giri, sessioni) → obiettivo
per il PROSSIMO run. Mai dati senza contesto: "i dati non mentono, ma
non dicono tutto" (traffico, visione, coraggio non sono canali).

## Il LINGUAGGIO del coach (per le nostre frasi)

Esempi veri dalle sue coaching notes — questo è il tono:
- "**Pazienza in ingresso**: il minimo di velocità mettilo lì, poi
  rotazione presto e cura l'uscita"
- "Aspetta col gas: **lascia ruotare la macchina, poi impegnati a fondo
  sul gas**" (commit)
- "**Slow in – fast out**: ingrassa la frenata a metà, poi deciso"
- Obiettivi MISURABILI e piccoli: "**il 3% in più del giro a gas
  pieno**", "sperimenta tempi e velocità di RILASCIO del freno in T6-T9"
- Dare l'obiettivo per la sessione dopo, non la lista dei difetti.

## Cosa ne facciamo

1. FATTO 23/07: varianti in stile coach su gas_earlier / coast_waste /
   brake_release_dirty / timeloss_focus / grip_margin.
2. Backlog findings nuovi (canali già registrati): "gas presto →
   costretto a mollare" (throttle su-giù con laterale alto);
   "decelerazione secondaria" (uscita larga); giro esitante ↔ scusante
   traffico (gap_ahead già nel raw del muretto: il coach NON rimprovera
   se c'era traffico).
3. Debrief/Report: chiudere SEMPRE con UN obiettivo misurabile per il
   run successivo (stile "3% in più di full throttle").
