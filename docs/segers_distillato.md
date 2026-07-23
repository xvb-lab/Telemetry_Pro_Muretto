# Segers distillato — analisi dati da paddock vero, sui NOSTRI canali

Fonte: J. Segers, *Analysis Techniques for Racecar Data Acquisition* (2ª ed.),
distillato 23/07/2026 sui canali che ABBIAMO (shared memory LMU + recorder
100Hz). Regola di casa: dove il libro e i dati S397 divergono, **vincono i
dati del gioco**. Il PDF resta locale (copyright): qui c'è la conoscenza,
riscritta e mappata sul nostro codice.

Canali nostri citati: `g_lat/g_long`, `speed`, `throttle`, `brake`,
`brake_press[4]` (bpress %), `brake_temp[4]`, `wheel_rot[4]`,
`tyre_press[4]`, `tyre_surf[4][3]` (I-M-O), `tyre_carcass[4]`,
`susp_defl[4]` (mm, 100Hz), `susp_force[4]`, `ride_h[4]`, `slip_lat[4]`,
`df_front/df_rear`, `lapdist`. DA AGGIUNGERE al reader (piccoli):
**sterzo** (`mUnfilteredSteering`) e **yaw rate** (`mLocalRot.y`).

---

## 1. FRENATA (cap. 5)

- **Rapidità di frenata**: tempo da inizio frenata al picco di −G.
  **< 0.5 s = veloce**; il derivato d(g_long)/dt picchia ~3 G/s su un
  pilota buono. Metrica per giro: picco medio di build-up.
- **Target di decelerazione**: picco −G ≈ **95% del picco laterale**
  (correzioni: motore anteriore −2%, gomme larghe −2%, motore post. +2%).
  In curva vale il cerchio: G_long_max = √(G_comb² − G_lat²).
  → Il nostro grip_margin ha già il combined-G: aggiungere il check
  "freni sotto il potenziale" (non è colpa del pilota se il bias è storto).
- **Frenata anticipata**: VALLE nel G combinato tra picco frenata e picco
  laterale (il pilota non usa tutto il grip nella transizione). Firma
  d'oro per il coach curve.
- **Bloccaggio**: crollo verticale di `wheel_rot` della singola ruota
  (già lo usiamo). Blocca per prima la ruota più scarica (interna,
  sull'asse col bias più alto).
- **Diagnosi bias**: sottosterzo in ingresso+centro + poca −G = troppo
  bias AVANTI; sovrasterzo in ingresso = troppo bias DIETRO.
- **Balance dalle temperature**: `TempBias = Tf/(Tf+Tr)·100` (front vs
  rear brake_temp). ~50% tipico; deriva dal bias meccanico ma con inerzia.
- **Velocità termiche**: dT/dt gated freno ON = build-up (°C/s, mordente);
  gated freno OFF = raffreddamento (media per giro bassa = ducts efficaci).
  → consigli brake ducts con NUMERI, non a sensazione.
- **Endurance**: tempo per giro sopra la soglia critica del materiale
  (es. 700 °C acciaio) = metrica salva-freni per le 6/8h.

## 2. CURVA E BILANCIO (cap. 7)

- **Sequenza**: staccata → trail-braking → (eventuale) neutro → uscita.
  Il G combinato è il raggio istantaneo del cerchio di trazione: piatto
  e pieno = pilota che usa tutto, valli = tempo lasciato.
- **Firme SOVRASTERZO**: correzioni di sterzo (fino al controsterzo),
  buchi nel g_lat **> 0.25 G per > 0.3 s** (sotto: sono sconnessioni),
  latG medio più basso del previsto, gas pieno rifiutato.
- **Firme SOTTOSTERZO**: sterzo che continua a CRESCERE in percorrenza;
  picco sterzo PRIMA del picco latG (ingresso); latG che scende mentre lo
  sterzo sale (centro/uscita); attesa lunga per il gas pieno.
- **Understeer angle** (con lo sterzo nel raw):
  `δu = δ − WB·G_lat/V²` (δ = angolo ruota esterna, WB = passo).
  δu > 0 sottosterzo, < 0 sovrasterzo. La MEDIA PER GIRO è la statistica
  regina: trend gomme che invecchiano (media che scende = va verso il
  sovrasterzo), confronto assetti, stile pilota. Nota vera dal libro: il
  giro più VELOCE della serie aveva la media understeer più ALTA — non
  demonizzare il sottosterzo.
- **Attitude velocity** (con lo yaw rate): `ω_att = r − G_lat/V`.
  Positivo = il posteriore sta uscendo, negativo = anteriore che spinge.
  Perfetto da proiettare sulla NOSTRA mappa (dove sovra/sottosterzi).

## 3. GOMME (cap. 8)

- **GRIP FACTORS** (medie per giro del G combinato, gated):
  - overall: G_comb quando > 1 G (solo grip-limited)
  - cornering: |g_lat| > 0.5
  - braking: g_long < −1
  - traction: g_long > 0 e |g_lat| > 0.5
  - aero: |g_lat| > 1 e V > 120 km/h
  Run chart per giro = DEGRADO OGGETTIVO della gomma (cala lap dopo lap),
  pista che gommina, vento che gira. Sostituisce le sensazioni.
- **Pressioni**: si stabilizzano dopo **4-7 giri** — giudizi di assetto
  prima di allora NON valgono (il nostro press-finding parte dal 3° giro
  di stint: portarlo a 4-5). Cold press dalla legge dei gas:
  `P_cold = (P_hot+1)·(T_cold+273)/(T_hot+273) − 1` (bar assoluti).
- **Finestra ottima**: X-Y |g_lat| vs T gomma → il bordo alto della nuvola
  dice il range dove nasce il grip. Metriche: % del giro IN finestra
  (efficienza), % LOW, % HIGH per assale.
- **Bilancio dal ΔT interno-esterno**: più load transfer su un assale =
  più differenza dentro/fuori su quell'assale. Barra più dura → ΔT più
  grande. Sottosterzo col ΔT front ≫ rear = troppo transfer davanti →
  barra/molle più morbide davanti.
- **Workload**: `T_i / ΣT·100` per ruota — chi lavora di più (e quale
  gomma parte più bassa di pressione a freddo).
- **Camber dalla 3-zone**: spread interno-esterno per CURVA (non solo
  media giro): media ~7 °C davanti ok, ~15 °C = troppo camber. Guardare
  la ruota ESTERNA della curva. (Il nostro camber_spread già lo fa a
  soglia 15°: giusto.)

## 4. AMMORTIZZATORI (cap. 11) — la novità grossa

- **Shock speed** = d(`susp_defl`)/dt (mm/s). Bump positivo, rebound
  negativo (verificare segno nostro).
- **Range di velocità**:
  | mm/s | dominio |
  |---|---|
  | < 5 | attrito (non si tocca col damping) |
  | 5–25 | LOW SPEED: movimenti di cassa (roll/pitch) = bilancio transitorio, è QUI che si regola l'handling |
  | 25–200 | strada (sconnessioni) = contact patch load |
  | > 200 | cordoli |
- **ISTOGRAMMA velocità** (per ruota, bin fissi, assi uguali): per il
  grip meccanico l'ideale è **simmetrico e gaussiano** (stessa energia
  in bump e rebound). Auto aero: skew VOLUTO (tanto rebound davanti per
  tenere giù il muso/rake) — non "correggerlo".
- **Statistiche**: zero-bin height = riferimento di rigidezza del
  quarto (se l'auto va bene, quei numeri sono l'assetto); mediana ≈ 0
  (≠0 = bias bump/rebound); deviazione std = quanto high-speed vede la
  ruota; skewness (neg = bias bump); kurtosis (alta = tutto in low-speed).
- **Lettura operativa** (dal libro, tabella vera): LF col 3.5% di tempo
  in più in rebound low → **meno click di rebound LF** (o più bump);
  differenza front/rear in high-speed ~6% → **più high-speed damping
  dietro** (bump e rebound). LMU ha slow/fast bump/rebound nei .svm →
  motore PERFETTO per il Setup Advisor.
- **Box plot** 15°/85° percentile come vista alternativa.

## 5. IL PILOTA (cap. 14) — metriche di coaching

Filosofia: 4 assi — **performance, smoothness, risposta, consistenza**.
E il monito del libro: un problema "del pilota" può essere assetto (e
viceversa); mai minare la fiducia — far SCOPRIRE, non accusare.

- **Gas**:
  - Istogramma throttle + **media gas per giro** (più alta = più veloce);
    bin 100% alto, part-throttle basso ("tip-tap sul gas" = grip chiesto
    male in uscita).
  - **Full-throttle time** % del giro (GT ~63-64% su pista media): run
    chart per gara = si vede il fuel save E il degrado gomme.
  - **THROTTLE ACCEPTANCE**: latG al momento del 100% gas / latG max
    della curva. Target per potenza: >400 CV → **80%**; 250-400 → 85%;
    150-250 → 90%. Sotto target e senza problemi di bilancio = troppo
    cauto sul gas (curva per curva!).
  - **Throttle speed** (d(gas)/dt, gated: né rilasci né full): media per
    giro ~20-21 %/s riferimento GT. Fluttuazioni alte in uscita = pitch
    = carichi che ballano = trazione persa.
- **Coasting** (`gas<5% e freno~0`): due tipi. Gas→freno = SEMPRE tempo
  perso (potevi frenare dopo). Freno→gas = può essere tecnica d'ingresso
  (ok se entry speed più alta e gas pieno prima). Metrica: % giro in
  coasting + proiezione sulla mappa (dove).
- **Frenata pilota**:
  - Punto di frenata: dipende dalla velocità d'arrivo (6 km/h in più =
    ~17 m prima) — mai confrontare punti senza confrontare le velocità.
  - **Aggressiveness**: picco di velocità pressione all'attacco
    (~250-300 bar/s = attacco da pro; media per giro dei picchi >40bar/s
    = statistica). Da noi: d(brake)/dt in %/s, stessa logica.
  - **Release smoothness** (Jackie Stewart: "conta quando lo TOGLI"):
    media |d(freno)/dt| nella fase di rilascio — bassa e lineare = pro;
    su/giù = footwork sporco (spesso col blip in scalata).
- **Sterzo**: media |d(δ)/dt| per giro = smoothness; alta = o mani
  nervose o assetto che obbliga a correzioni (chiedere prima al pilota!).
- **Traiettoria**: `R = V²/G_lat`, curvatura `1/R`. Il picco di curvatura
  più BASSO = linea più veloce in quella curva. Firme apice: plateau di
  latG = apice centrale; picco latG presto poi cala piano = apice tardivo
  (uscita libera per il gas); picco latG TARDI + gas tardi = apice
  anticipato = uscita strozzata (l'errore classico). Media curvatura per
  giro + varianza per curva = qualità e consistenza delle linee.

## 6. METRICHE (cap. 17) — il metodo

- Un NUMERO per giro → run chart → trend. È già la filosofia dei nostri
  findings: questa tabella è il menù per Engineer Report e debrief.
- Attenzione alle medie gated: mai mediare gli zeri fuori condizione
  (sommare valori e CONTARE i campioni validi, poi dividere).
- Metriche chiave (tabella del libro, tutte fattibili da noi): media gas,
  % full throttle, % coasting, % tempo sui freni, distanza in frenata,
  aggressiveness, release smoothness, bias freni, grip factors ×5,
  smoothness sterzo, curvatura media, T gomme min/max/med, ΔT sx-dx,
  % tempo shock low/high bump/rebound, understeer angle medio.

## 7. LA PISTA (cap. 18)

- **Quadranti del cerchio G** (% tempo per quadrante: uscita dx, uscita
  sx, staccata dx, staccata sx): dice DOVE investire l'assetto (se il
  35% del giro è "uscita da curve a destra", lavora lì) e quale gomma
  lavora di più (→ pressione a freddo differenziata).
- **Lavoro freni**: W = ½·M·V² gated freno ON, integrato per giro (MJ):
  classifica delle piste brake-killer (Monza vs Le Mans).
- **BUMPINESS**: media |shock speed| per giro = quanto è sconnessa la
  pista; gated per fase (in frenata / in trazione) e **proiettata sulla
  nostra trackmap** = mappa dei dossi. Nessun rivale ce l'ha.

---

## Cosa ne facciamo (priorità proposte)

1. **Metriche pilota nel debrief/Engineer Report** (throttle acceptance
   per curva, % coasting, aggressiveness, release smoothness, smoothness
   sterzo*, media gas, % full): canali già registrati, solo math.
2. **Grip factors per giro** nel recorder → degrado oggettivo + trend
   pista; alimenta anche il muretto ("le gomme hanno perso il 5%").
3. **Istogrammi ammortizzatori** (pagina telemetria + statistiche) →
   base del Setup Advisor damping coi click slow/fast di LMU.
4. *Reader: aggiungere `steering` e `yaw_rate`* → understeer angle medio
   per giro + attitude velocity sulla mappa.
5. **Bumpiness sulla mappa** + quadranti G in Track data.
6. Ritocchi al collaudato: press-finding dal 4°-5° giro di stint (non
   3°); check freni "sotto il 95% del laterale".
