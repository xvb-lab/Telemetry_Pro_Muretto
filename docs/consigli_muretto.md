# Consigli del muretto — base di conoscenza (coaching)

Consigli forniti dall'utente (2026-07-20) che il muretto potrà **dire** al
pilota. Regole fisse: **consigli non ordini**; un consiglio LIVE si dice solo
quando il **dato reale di LMU** lo conferma (se il dato manca, tace). I
consigli di SETUP sono base di conoscenza (pre-sessione), non allarmi live.

**Stato aggiornato al 23/07/2026** — questo file è la MATERIA PRIMA; la mappa
completa di ciò che il muretto fa è in `muretto_capabilities.md`.

Legenda: 🔴 LIVE · 🔧 SETUP · ✅ IN MACCHINA · ⏳ in attesa

---

## Gomme e temperature

- 🔴 ✅ **Warm-up out-lap (brake dragging).** IN MACCHINA: `outlap_tech_call`,
  frasi PER CLASSE (GT3: "due frenate decise e un filo di freno tenuto: il
  calore dei dischi entra nelle gomme"; HY/P2/P3: carbonio in finestra sopra
  i 250°C con staccate progressive). Parla in prova e in gara all'out-lap.
- 🔧 ⏳ **Pressioni in qualifica** (-0.15 bar a freddo, picco al 2° lanciato).
  Base di conoscenza per il futuro **Setup Advisor / pagina Garage**.
- 🔴 ✅ **Correzione camber live** (inner−outer > 15°). IN MACCHINA dal 23/07:
  finding `camber_spread` (Cantiere 2) — spread per ruota dai dati 3-zone,
  annunciato in prova ("camber da rivedere in garage"), one-shot per stint.

## Virtual Energy (VE / NRG)

- 🔴 🟡 **Lift & Coast.** IN MACCHINA e oltre: sistema LICO geometrico
  completo (punti di rilascio dalla geometria mappa, LED al beep, banca del
  risparmio, adattivo). ⏳ MANCA solo il pezzo "porta la Engine Map su
  risparmio PRIMA del rilascio": il muretto non suggerisce ancora il cambio
  mappa motore (dato `motor_map` disponibile nel raw).
- 🔧 ⏳ **Brake balance per rigenerazione (Hypercar)** (BB 48-49% indietro).
  Base di conoscenza per il Setup Advisor.

## Freni e radiatori

- 🔧 ⏳ **Brake ducts per la gara** (~600 °C di picco a regime, non nei primi
  giri). Base di conoscenza per il Setup Advisor. Le SOGLIE live freni per
  classe sono già attive (finestre in `target_pitwall.md`, fade in Cantiere 2).

## Meteo dinamico (wet)

- 🔴 ✅ **Cross-over wet.** IN MACCHINA con le soglie REALI S397 (asciutto
  <0.15, crossover, wet): decisioni pioggia state-aware (mai consigliare ciò
  che è già vero), ETA slick, grip "pista lavata".
- 🔴 ✅ **Traiettorie bagnate su slick.** IN MACCHINA: `rain_dryline` e la
  logica scia/fuori-scia (upgrade wetness) — su pista umida con slick
  consiglia la linea fuori dalla gommatura.

---

## Riepilogo

| Consiglio | Stato |
|---|---|
| Warm-up out-lap (freno tenuto) | ✅ in macchina, per classe |
| Camber live (I−O >15°) | ✅ in macchina (23/07) |
| Lift & Coast | ✅ sistema completo (LICO) |
| Cross-over wet + fuori-scia | ✅ in macchina (soglie S397) |
| Engine Map su risparmio col L&C | ⏳ unico pezzo LIVE mancante |
| Pressioni quali / BB regen / brake ducts | ⏳ Setup Advisor (Garage, in visione) |
