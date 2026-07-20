# Target pit-wall & allarmi telemetria — per classe

Spec dettagliata (stile MoTeC i2 / Atlas) fornita dall'utente (2026-07-20):
pressioni, finestre temp, soglie d'allarme e math channels per classe. Base
per la config degli **allarmi** del muretto. In gara vince sempre il dato LIVE
di LMU; questi sono i target/bande d'allarme.

> ⚠️ **Conflitto dati da risolvere (finestre CORE gomme).** Questi numeri NON
> combaciano con `dati_lmu.md §2`:
> | | dati_lmu.md §2 (prima) | QUESTO doc (ora) |
> |---|---|---|
> | Proto/HY core | 75-87 °C (proto) | HY **85-105** · LMP2 **80-95** |
> | GT core | 70-90 °C | GT3 **75-90** (alarm >95) |
> **Adottati provvisoriamente i valori di QUESTO doc** (più granulari, per
> classe, con soglie d'allarme). Se i precedenti erano giusti, l'utente lo dice
> e si riallinea. Verificare comunque con la telemetria live (core reale).

---

## 1. Hypercar (LMH / LMDh)

**Pneumatici (Michelin HY)**
- Pressione cold target: **145 kPa** · hot target: **185 kPa** (finestra 182-188)
- Core ottimale: **85-105 °C** · ALARM HIGH >105 (degrado termico)
- Delta superficie I-M-O max: **25 °C** (oltre = blister)

**Freni (carbonio-carbonio)**
- Ottimale: **450-750 °C**
- ALARM LOW (vetrificazione in SC/FCY): <**350 °C**
- ALARM HIGH (ossidazione/usura): >**850 °C**

**Power Unit / VE (reg. WEC)**
- MGU-K deployment: nessuna coppia ibrida sotto **190 km/h** (LMH AWD)
- VE max per stint: **900 MJ**
- Allarme sovraconsumo VE (wheelspin post.): **1.15 MJ/km**

**Math channels**: Aero Balance (CoP) = RHF/(RHF+RHR)*100 · Energy Burn Rate =
d(Energy MJ)/dt [MJ/s] · Tyre Heat Gen = SlipRatio*DriveTorque + SlipAngle*Load

## 2. LMP2 (Oreca 07 Gibson)

**Pneumatici (Goodyear LMP2)**
- Cold: **135 kPa** · hot: **175 kPa** (172-178)
- Core ottimale: **80-95 °C** · ALARM HIGH >100

**Freni (carbonio)**
- Ottimale: **400-650 °C** (meno calore della HY) · glazing low <300

**Aero/altezze (porpoising/fondo)**
- Ride height post. critico: <**22 mm** (stallo diffusore)
- Heave damper travel max: **35 mm** (oltre = bumpstop)
- Consumo target: **1.85 L/giro** (media Le Mans)

**Math channels**: Rake = atan((RHR-RHF)/3010)*180/π · Downforce Collapse =
IF(RHR<22,1,0) · Damper Velocity (filtro 50 Hz cordoli)

## 3. LMGT3

**Pneumatici (Goodyear LMGT3)**
- Cold: **140 kPa** · hot: **165 kPa** (finestra strettissima 163-168)
- Core ottimale: **75-90 °C** · ALARM HIGH >95 (decadimento mescola)

**Freni (acciaio)**
- Ottimale: **300-600 °C** · glazing low <200 (pastiglie fredde)
- ALARM HIGH (ebollizione fluido/fading): >**720 °C**

**Elettronica (hardware GT3)**
- ABS target: intervento <**15%** slittamento long. (oltre taglia troppa pressione)
- TC target: <**8%** (oltre surriscalda le gomme posteriori)

**Math channels**: Yaw Rate Error (sotto/sovrasterzo reale) · Brake Pad Fading =
IF(BrakeDiscTemp>720,1,0) · Tyre Pressure Delta = HotPress - 165 (per chiamate pit)

---

*Uso: soglie ALARM → allarmi muretto (gomme/freni/VE); i math channels sono
riferimento per feature avanzate (setup/analisi). Confrontare i valori con
`_thermal_windows` del cervello e con `dati_lmu.md` prima di rilasciare.*
