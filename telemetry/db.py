"""
telemetry/db.py — Storage telemetria per-evento (SQLite, un file per sessione).

Un file = una sessione (dal caricamento pista a fine sessione), nominato con
data/ora/pista/tipo in logs/. Tabelle:

  session_meta : 1 riga, metadati evento (data, pista, vettura, classe, sessione)
  laps         : 1 riga per giro completato (tempi, consumi, temp/usura fine giro)
  sectors      : 1 riga per settore (aggregati: temp min/avg/max, consumi, regen)
  samples      : campioni ad alta frequenza per le tracce (gas/freno/sterzo/G/pos),
                 indicizzati per giro -> usati da tab GUIDA e MAPPA

Scrittura a LOTTI: il recorder accumula righe e chiama flush() periodicamente
(mai I/O sul thread grafico). PRAGMA per performance + sicurezza ragionevole.
"""
import os
import sqlite3
import time
from pathlib import Path

_ROOT = Path(__file__).parent.parent
from core.paths import LOGS_DIR, REFS_DIR  # log e reference nella cartella dati utente

_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    started_at   TEXT,      -- ISO datetime locale
    started_et   REAL,      -- mCurrentET all'avvio
    session_len  REAL,      -- durata impostata della sessione (mEndET), in secondi
    track        TEXT,
    track_logo   TEXT,
    vehicle      TEXT,
    car_class    TEXT,
    session_type INTEGER,   -- 0..: P/Q/R (mSession)
    fuel_max     REAL,
    ve_max       REAL,
    app_version  TEXT,
    car_num      TEXT,
    -- condizioni della sessione (con cui sono stati fatti i tempi)
    driver       TEXT,
    team         TEXT,
    fuel_start   REAL,
    air_temp     REAL,
    track_temp   REAL,
    wetness      REAL,
    compound_f   TEXT,
    compound_r   TEXT,
    compounds4   TEXT,      -- 'S,M,H,W' per FL,FR,RL,RR
    forecast5    TEXT       -- 5 icone meteo previste (START..FINISH), es 'sun,cloud,rain,...'
);
CREATE TABLE IF NOT EXISTS laps (
    lap        INTEGER PRIMARY KEY,
    stint      INTEGER,
    lap_time   REAL,
    s1         REAL, s2 REAL, s3 REAL,
    invalid    INTEGER,
    fuel_used  REAL, ve_used REAL,
    fuel_end   REAL, ve_end  REAL,
    regen_gain_kwh REAL, boost_kwh REAL,               -- energia recuperata / spesa nel giro (kWh)
    soc_start REAL, soc_end REAL,                       -- stato batteria inizio/fine giro (%)
    -- temp/usura fine giro per ruota (fl,fr,rl,rr)
    t_fl REAL, t_fr REAL, t_rl REAL, t_rr REAL,        -- temp gomma carcassa (carcass)
    ts_fl REAL, ts_fr REAL, ts_rl REAL, ts_rr REAL,    -- temp gomma battistrada (tread/surface)
    ti_fl REAL, ti_fr REAL, ti_rl REAL, ti_rr REAL,    -- temp gomma strato interno (layer)
    p_fl REAL, p_fr REAL, p_rl REAL, p_rr REAL,        -- pressione gomma (kPa)
    w_fl REAL, w_fr REAL, w_rl REAL, w_rr REAL,        -- usura %
    b_fl REAL, b_fr REAL, b_rl REAL, b_rr REAL,        -- temp freno
    -- METEO / PISTA del giro (per condizione REF e tab meteo)
    declared_wet REAL,   -- 1.0 = WET, 0.0 = DRY (dichiarazione direttore di gara nel giro)
    air_temp   REAL,     -- temp aria (C)
    track_temp REAL,     -- temp pista (C)
    wetness    REAL,     -- bagnato pista del giro (0-1)
    rain_pct   REAL,     -- intensità pioggia del giro (%)
    compounds4 TEXT      -- mescola del giro: 'S,M,H,W' per FL,FR,RL,RR (per-stint)
);
CREATE TABLE IF NOT EXISTS sectors (
    lap     INTEGER,
    sector  INTEGER,            -- 0,1,2
    s_time  REAL,
    fuel_used REAL, ve_used REAL, regen_kwh REAL,
    spd_avg REAL, spd_max REAL,            -- velocità media/max nel settore (km/h)
    regen_gain_kwh REAL, boost_kwh REAL,   -- energia recuperata / spesa nel settore (kWh)
    soc_used REAL,                         -- delta SOC nel settore (start-end, %)
    -- gomme: temp media + usura delta nel settore (fl,fr,rl,rr)
    t_fl REAL, t_fr REAL, t_rl REAL, t_rr REAL,        -- carcassa
    ts_fl REAL, ts_fr REAL, ts_rl REAL, ts_rr REAL,    -- battistrada (tread)
    ti_fl REAL, ti_fr REAL, ti_rl REAL, ti_rr REAL,    -- strato interno (layer)
    p_fl REAL, p_fr REAL, p_rl REAL, p_rr REAL,        -- pressione media settore (kPa)
    w_fl REAL, w_fr REAL, w_rl REAL, w_rr REAL,
    b_fl REAL, b_fr REAL, b_rl REAL, b_rr REAL,
    PRIMARY KEY (lap, sector)
);
CREATE TABLE IF NOT EXISTS samples (
    lap     INTEGER,
    t       REAL,               -- tempo dall'inizio giro (s)
    lapdist REAL,               -- distanza sul giro (m)
    pos_x REAL, pos_y REAL, pos_z REAL,
    speed REAL,
    throttle REAL, brake REAL, steer REAL,
    g_long REAL, g_lat REAL,
    tc_active REAL, abs_active REAL,        -- TC/ABS in intervento (0/1)
    brake_bias REAL,                        -- ripartizione frenata (frazione posteriore)
    tc_map REAL, abs_map REAL, tc_slip REAL, tc_cut REAL,  -- impostazioni aiuti
    gear INTEGER, rpm REAL,
    soc REAL, regen_kw REAL, boost_state INTEGER,
    fuel REAL, ve REAL,                 -- carburante (L) e virtual energy (%) campionati
    tyre_t REAL, tyre_ts REAL, tyre_ti REAL,  -- media 4 ruote: carcassa / superficie / strato
    tyre_p REAL,                        -- media 4 ruote: pressione (kPa)
    brake_t REAL,                       -- media 4 ruote: temp disco freno
    -- PER RUOTA (FL/FR/RL/RR): carcassa, superficie, strato, pressione, freno
    tyre_t_fl REAL, tyre_t_fr REAL, tyre_t_rl REAL, tyre_t_rr REAL,
    tyre_ts_fl REAL, tyre_ts_fr REAL, tyre_ts_rl REAL, tyre_ts_rr REAL,
    tyre_ti_fl REAL, tyre_ti_fr REAL, tyre_ti_rl REAL, tyre_ti_rr REAL,
    tyre_p_fl REAL, tyre_p_fr REAL, tyre_p_rl REAL, tyre_p_rr REAL,
    brake_t_fl REAL, brake_t_fr REAL, brake_t_rl REAL, brake_t_rr REAL,
    susp_d_fl REAL, susp_d_fr REAL, susp_d_rl REAL, susp_d_rr REAL,   -- deflessione sospensione (mm)
    ride_h_fl REAL, ride_h_fr REAL, ride_h_rl REAL, ride_h_rr REAL,   -- altezza da terra (mm)
    brake_p_fl REAL, brake_p_fr REAL, brake_p_rl REAL, brake_p_rr REAL,  -- pressione freno (%)
    tyre_w_fl REAL, tyre_w_fr REAL, tyre_w_rl REAL, tyre_w_rr REAL,
    track_temp REAL, rain_pct REAL          -- meteo per-sample: asfalto (°C), pioggia (%)
);
CREATE INDEX IF NOT EXISTS idx_samples_lap ON samples(lap);
CREATE INDEX IF NOT EXISTS idx_sectors_lap ON sectors(lap);
CREATE TABLE IF NOT EXISTS timeloss (
    lap     INTEGER,            -- giro analizzato
    ref     INTEGER,            -- giro di riferimento (best della sessione)
    corner  TEXT,               -- 'T1'..'Tn'
    d       REAL,               -- lapdist apice (m)
    entry_s REAL, exit_s REAL, total_s REAL,   -- +perde / -guadagna
    vmin REAL, vmin_ref REAL,   -- velocita' minima in curva (km/h)
    PRIMARY KEY (lap, corner)
);
CREATE TABLE IF NOT EXISTS events (
    lap     INTEGER,
    t       REAL,               -- tempo dall'inizio giro (s)
    lapdist REAL,               -- distanza sul giro (m)
    x REAL, z REAL,             -- posizione mondo (per i marker sulla mappa)
    kind    TEXT,               -- 'contact' | 'tl' | 'lock'
    val     REAL                -- contact: magnitudo urto | tl: steps totali | lock: ruota 0-3
);
CREATE INDEX IF NOT EXISTS idx_events_lap ON events(lap);
"""


_TRACKS_JSON = _ROOT / "settings" / "tracks.json"

# Layout alternativi noti (oltre al tracciato principale). (sottostringa, etichetta).
# Stessa logica del pace: un layout alternativo non condivide REF/tempi col base.
# Più lungo prima, per evitare doppi match (outercircuit prima di outer).
_ALT_LAYOUTS = (
    ("curvagrande", "CurvaGrande"),
    ("outercircuit", "Outer"), ("outer", "Outer"),
    ("paddock", "Paddock"),
    ("endurance", "Endurance"),
    ("shortcircuit", "Short"), ("short", "Short"),
    ("classic", "Classic"),
    ("school", "School"),
    ("mulsanne", "Mulsanne"),
    ("international", "International"),   # prima di 'national': ne e' sottostringa
    ("national", "National"),
)


def _layout_suffix(track):
    """Etichetta del layout alternativo (es. 'CurvaGrande', 'Outer'), '' per il
    tracciato principale del circuito. '' fa sì che le varianti di nome dello
    stesso layout base condividano la stessa chiave REF."""
    n = "".join(c for c in (track or "").lower() if c.isalnum())
    for key, lab in _ALT_LAYOUTS:
        if key in n:
            return lab
    return ""
_track_map = None


def _short_track(track):
    """Nome pista corto via settings/tracks.json (es. 'Autodromo Nazionale
    Monza' -> 'Monza'). Fallback: prima parola alfanumerica."""
    global _track_map
    if _track_map is None:
        try:
            import json
            _track_map = json.loads(_TRACKS_JSON.read_text(encoding="utf-8"))
        except Exception:
            _track_map = {}
    t = (track or "").strip()
    if t in _track_map:
        return _track_map[t]
    # fallback: togli spazi/parole generiche, accorcia
    junk = ("autodromo", "nazionale", "circuit", "international", "de", "la",
            "du", "of", "the", "speedway", "raceway", "grand", "prix")
    words = [w for w in "".join(c if c.isalnum() else " " for c in t).split()
             if w.lower() not in junk]
    short = (words[0] if words else (t or "Track"))
    return "".join(c for c in short if c.isalnum())[:12] or "Track"


def make_filename(track, car_class, session=None, when=None):
    """Monza-06-21_19-25-43_GT3_Q.lmtel — nome file univoco per sessione.

    Include i secondi e il tipo di sessione (P/Q/R) così due sessioni diverse
    (anche stesso minuto/pista/auto) non condividono mai lo stesso file.
    """
    when = when or time.localtime()
    date = time.strftime("%m-%d", when)
    hms = time.strftime("%H-%M-%S", when)
    cls = "".join(c for c in (car_class or "") if c.isalnum())[:10] or "Car"
    try:
        st = int(session)
        styp = ("P" if 1 <= st <= 4 else "Q" if 5 <= st <= 8
                else "R" if st >= 10 else "")
    except Exception:
        styp = ""
    suffix = ("_" + styp) if styp else ""
    return f"{_short_track(track)}-{date}_{hms}_{cls}{suffix}.lmtel"


class TelemetryDB:
    """Apre/crea un file sessione e scrive a lotti."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(str(self.path), check_same_thread=False,
                                    timeout=3.0)
        self._con.execute("PRAGMA busy_timeout=3000;")
        self._con.execute("PRAGMA journal_mode=WAL;")
        self._con.execute("PRAGMA synchronous=NORMAL;")
        self._con.executescript(_SCHEMA)
        self._con.commit()
        self._migrate()
        self._buf_laps = []
        self._buf_sectors = []
        self._buf_samples = []
        self._buf_events = []
        self._buf_timeloss = []

    def _migrate(self):
        """Aggiunge colonne mancanti a file esistenti (schema vecchio) così le
        INSERT non falliscono mai in silenzio dopo un aggiornamento."""
        _TEXT_COLS = {"compounds4"}
        for tbl, cols in (("laps", self._LAP_COLS),
                          ("sectors", self._SEC_COLS),
                          ("samples", self._SMP_COLS)):
            try:
                have = {r[1] for r in self._con.execute(f"PRAGMA table_info({tbl})")}
                for c in cols:
                    if c not in have:
                        typ = "TEXT" if c in _TEXT_COLS else "REAL"
                        self._con.execute(f"ALTER TABLE {tbl} ADD COLUMN {c} {typ}")
            except Exception:
                pass
        self._con.commit()

    # ── metadati ──
    def write_meta(self, meta):
        cols = ["started_at", "started_et", "session_len", "track", "track_logo", "vehicle",
                "car_class", "session_type", "fuel_max", "ve_max", "app_version",
                "car_num", "driver", "team", "fuel_start", "air_temp", "track_temp",
                "wetness", "compound_f", "compound_r", "compounds4", "forecast5"]
        vals = [meta.get(c) for c in cols]
        self._con.execute(
            "INSERT OR REPLACE INTO session_meta (id,%s) VALUES (1,%s)"
            % (",".join(cols), ",".join("?" * len(cols))), vals)
        self._con.commit()

    def update_session_len(self, val):
        """Aggiorna SOLO la durata sessione (race_total assestato), senza toccare
        il resto del meta. Usato perche' all'apertura race_total non e' ancora reale."""
        try:
            self._con.execute("UPDATE session_meta SET session_len=? WHERE id=1",
                              (float(val),))
            self._con.commit()
        except Exception:
            pass

    # ── accumulo ──
    def add_lap(self, row):       self._buf_laps.append(row)
    def add_sector(self, row):    self._buf_sectors.append(row)
    def add_sample(self, row):    self._buf_samples.append(row)
    def add_event(self, row):     self._buf_events.append(row)
    def add_timeloss(self, row):  self._buf_timeloss.append(row)

    def _flush_table(self, table, cols, buf):
        if not buf:
            return
        ph = ",".join("?" * len(cols))
        sql = "INSERT OR REPLACE INTO %s (%s) VALUES (%s)" % (table, ",".join(cols), ph)
        rows = [[r.get(c) for c in cols] for r in buf]
        self._con.executemany(sql, rows)
        buf.clear()

    _LAP_COLS = ["lap", "stint", "lap_time", "s1", "s2", "s3", "invalid", "pos", "wet_max",
                 "fuel_used", "ve_used", "fuel_end", "ve_end",
                 "regen_gain_kwh", "boost_kwh", "soc_start", "soc_end",
                 "t_fl", "t_fr", "t_rl", "t_rr",
                 "ts_fl", "ts_fr", "ts_rl", "ts_rr",
                 "ti_fl", "ti_fr", "ti_rl", "ti_rr",
                 "p_fl", "p_fr", "p_rl", "p_rr",
                 "w_fl", "w_fr", "w_rl", "w_rr",
                 "b_fl", "b_fr", "b_rl", "b_rr",
                 "declared_wet", "air_temp", "track_temp", "wetness", "rain_pct",
                 "wetness_min", "wetness_max",
                 "compounds4"]
    _SEC_COLS = ["lap", "sector", "s_time", "fuel_used", "ve_used", "regen_kwh",
                 "spd_avg", "spd_max", "regen_gain_kwh", "boost_kwh", "soc_used",
                 "t_fl", "t_fr", "t_rl", "t_rr",
                 "ts_fl", "ts_fr", "ts_rl", "ts_rr",
                 "ti_fl", "ti_fr", "ti_rl", "ti_rr",
                 "p_fl", "p_fr", "p_rl", "p_rr",
                 "w_fl", "w_fr", "w_rl", "w_rr",
                 "b_fl", "b_fr", "b_rl", "b_rr"]
    _EVT_COLS = ["lap", "t", "lapdist", "x", "z", "kind", "val"]
    _TLM_COLS = ["lap", "ref", "corner", "d", "entry_s", "exit_s",
                 "total_s", "vmin", "vmin_ref"]

    _SMP_COLS = ["lap", "t", "lapdist", "pos_x", "pos_y", "pos_z", "speed",
                 "throttle", "brake", "steer", "g_long", "g_lat",
                 "tc_active", "abs_active", "brake_bias",
                 "tc_map", "abs_map", "tc_slip", "tc_cut",
                 "gear", "rpm",
                 "soc", "regen_kw", "boost_state", "fuel", "ve",
                 "tyre_t", "tyre_ts", "tyre_ti", "tyre_p", "brake_t",
                 "tyre_t_fl", "tyre_t_fr", "tyre_t_rl", "tyre_t_rr",
                 "tyre_ts_fl", "tyre_ts_fr", "tyre_ts_rl", "tyre_ts_rr",
                 "tyre_ti_fl", "tyre_ti_fr", "tyre_ti_rl", "tyre_ti_rr",
                 "tyre_p_fl", "tyre_p_fr", "tyre_p_rl", "tyre_p_rr",
                 "brake_t_fl", "brake_t_fr", "brake_t_rl", "brake_t_rr",
                 "susp_d_fl", "susp_d_fr", "susp_d_rl", "susp_d_rr",
                 "ride_h_fl", "ride_h_fr", "ride_h_rl", "ride_h_rr",
                 "brake_p_fl", "brake_p_fr", "brake_p_rl", "brake_p_rr",
                 "tyre_w_fl", "tyre_w_fr", "tyre_w_rl", "tyre_w_rr",
                 "sforce_fl", "sforce_fr", "sforce_rl", "sforce_rr",
                 "slat_fl", "slat_fr", "slat_rl", "slat_rr",
                 "track_temp", "rain_pct",
                 # grip margin / scia / normalizzazione (23/07)
                 "grip_fl", "grip_fr", "grip_rl", "grip_rr",
                 "df_front", "df_rear", "gap_ahead", "track_grip"]

    def flush(self):
        """Scrittura RESILIENTE e PARLANTE. Il vecchio flush aveva un solo
        try intorno a tutto con `except: pass`: se l'insert dei SAMPLES
        falliva (una riga avvelenata, un lock transitorio), l'errore spariva
        nel nulla, il buffer NON veniva svuotato e ogni flush successivo
        rifalliva uguale -> giri e settori salvati, CAMPIONI persi per tutta
        la sessione = tracce a buchi e mappa vuota, zero spiegazioni."""
        for table, cols, buf in (("laps", self._LAP_COLS, self._buf_laps),
                                 ("sectors", self._SEC_COLS, self._buf_sectors),
                                 ("samples", self._SMP_COLS, self._buf_samples),
                                 ("events", self._EVT_COLS, self._buf_events),
                                 ("timeloss", self._TLM_COLS, self._buf_timeloss)):
            if not buf:
                continue
            try:
                self._flush_table(table, cols, buf)
                self._con.commit()
                continue
            except Exception as e:
                self._db_diag(table, e, len(buf))
                try:
                    # l'executemany puo' aver inserito le righe PRIMA di
                    # quella avvelenata: via, o il recupero le duplica
                    self._con.rollback()
                except Exception:
                    pass
            # RECUPERO riga per riga: le buone si salvano, le cattive si
            # contano e si buttano. Se falliscono TUTTE e' un problema
            # transitorio (lock/IO): si ritenta al flush dopo, con un tetto
            # al buffer per non crescere all'infinito.
            ph = ",".join("?" * len(cols))
            sql = ("INSERT OR REPLACE INTO %s (%s) VALUES (%s)"
                   % (table, ",".join(cols), ph))
            ok = bad = 0
            for r in buf:
                try:
                    self._con.execute(sql, [r.get(c) for c in cols])
                    ok += 1
                except Exception:
                    bad += 1
            if ok == 0 and bad:
                if len(buf) > 20000:
                    del buf[:len(buf) // 2]
                    self._db_diag(table, "tutto fallito, buffer dimezzato",
                                  len(buf))
            else:
                buf.clear()
                if bad:
                    self._db_diag(table,
                                  "%d righe scartate (non scrivibili)" % bad,
                                  0)
        try:
            self._con.commit()
        except Exception as e:
            self._db_diag("commit", e, 0)

    def _db_diag(self, where, err, nbuf):
        """Ogni errore di scrittura lascia una riga in db_errors.log accanto
        alle sessioni, piu' l'ultimo errore leggibile dalla UI."""
        try:
            self.last_error = "%s: %r" % (where, err)
            import datetime as _dtm
            with open(str(LOGS_DIR / "db_errors.log"), "a",
                      encoding="utf-8") as f:
                f.write("%s  %s  buf=%s  %r\n" % (
                    _dtm.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    where, nbuf, err))
        except Exception:
            pass

    def close(self):
        self.flush()
        try:
            self._con.close()
        except Exception:
            pass


# ── lettura per la UI di review ───────────────────────────────────────────
# cache metadati per file: una sessione GIA' chiusa non cambia mai, quindi la
# si legge da sqlite UNA volta sola. Chiave d'invalidazione = (mtime,size) del
# .lmtel + (mtime,size) del suo -wal. Il recorder scrive in WAL: la sessione
# LIVE ha un -wal che cresce a ogni giro -> la sua firma cambia -> viene sempre
# riletta (board live sempre fresco); le sessioni chiuse non hanno -wal ->
# firma stabile -> servite dalla cache. Evita di riaprire centinaia di database
# a ogni refresh (era la causa del 67% CPU / scatti UI: 408 file ogni 4s).
_META_CACHE = {}


def _sess_sig(f):
    """Firma d'invalidazione del file sessione. Cambia solo se il .lmtel o il
    suo sidecar -wal sono stati riscritti."""
    st = f.stat()
    try:
        w = f.with_name(f.name + "-wal").stat()
        wsig = (w.st_mtime_ns, w.st_size)
    except OSError:
        wsig = (0, 0)
    return (st.st_mtime_ns, st.st_size, wsig[0], wsig[1])


def _read_session_meta(f):
    """Legge i metadati di UNA sessione da sqlite (la parte lenta: apre il db e
    fa gli scan della tabella laps)."""
    meta = {"file": str(f), "name": f.name}
    try:
        con = sqlite3.connect(str(f))
        cur = con.execute("SELECT started_at,track,track_logo,vehicle,car_class,"
                          "session_type,driver,team,wetness FROM session_meta WHERE id=1")
        row = cur.fetchone()
        if row:
            meta.update({"started_at": row[0], "track": row[1], "track_logo": row[2],
                         "vehicle": row[3], "car_class": row[4], "session_type": row[5],
                         "driver": row[6], "team": row[7], "wetness": row[8]})
        cur = con.execute("SELECT MIN(lap_time), COUNT(*) FROM laps "
                          "WHERE lap_time>0 AND invalid=0")
        r2 = cur.fetchone()
        if r2:
            meta["best_lap"] = r2[0]
            meta["laps"] = r2[1]
        cur = con.execute("SELECT SUM(lap_time) FROM laps WHERE lap_time>0")
        r3 = cur.fetchone()
        meta["duration"] = (r3[0] if (r3 and r3[0]) else 0.0)
        try:
            cur = con.execute("SELECT session_len FROM session_meta WHERE id=1")
            rr = cur.fetchone()
            meta["session_len"] = (rr[0] if rr else None)
        except Exception:
            meta["session_len"] = None
        try:
            cur = con.execute("SELECT forecast5 FROM session_meta WHERE id=1")
            rf = cur.fetchone()
            meta["forecast5"] = (rf[0] if rf else None)
        except Exception:
            meta["forecast5"] = None
        con.close()
    except Exception:
        pass
    return meta


def list_sessions(folder=None):
    """Elenco sessioni salvate (per il menu lista). Ritorna lista di dict
    con file + metadati, ordinata dalla più recente.
    folder: cartella da scandire (default LOGS_DIR; usata anche per le
    sessioni team importate, che vivono in una cartella isolata)."""
    out = []
    base = Path(folder) if folder else LOGS_DIR
    if not base.exists():
        return out
    cache = _META_CACHE
    for f in sorted(base.glob("*.lmtel"), reverse=True):
        key = str(f)
        try:
            sig = _sess_sig(f)
        except OSError:
            continue                              # sparito mentre scandivo
        hit = cache.get(key)
        if hit is not None and hit[0] == sig:
            out.append(dict(hit[1]))              # copia difensiva (i chiamanti mutano)
            continue
        meta = _read_session_meta(f)
        cache[key] = (sig, dict(meta))
        out.append(meta)
    # Ordina davvero dalla più recente: started_at (ISO) decrescente, con il
    # nome file come tie-break. Le sessioni senza started_at finiscono in coda.
    out.sort(key=lambda m: (m.get("started_at") or "", m.get("file") or ""),
             reverse=True)
    return out


def open_session(path):
    """Connessione in sola lettura a una sessione salvata (per i tab review)."""
    con = sqlite3.connect(str(path), timeout=3.0)
    try:
        con.execute("PRAGMA busy_timeout=3000;")
    except Exception:
        pass
    return con


def read_session_meta(con):
    """Tutte le colonne di session_meta come dict (condizioni della sessione)."""
    try:
        cur = con.execute("SELECT * FROM session_meta WHERE id=1")
        cols = [c[0] for c in cur.description]
        row = cur.fetchone()
        return dict(zip(cols, row)) if row else {}
    except Exception:
        return {}


def save_reference(src_con, lap, dest_path):
    """Salva UN giro come file di riferimento (.lmref).

    Esegue un backup online completo del DB sorgente e poi tiene solo il giro
    richiesto (samples/sectors/laps). Indipendente dal file di origine: il
    reference resta valido anche se la sessione viene cancellata.
    """
    import os
    if os.path.exists(dest_path):
        try:
            os.remove(dest_path)
        except OSError:
            pass
    dst = sqlite3.connect(dest_path)
    try:
        src_con.backup(dst)
        dst.execute("DELETE FROM samples WHERE lap<>?", (lap,))
        dst.execute("DELETE FROM sectors WHERE lap<>?", (lap,))
        dst.execute("DELETE FROM laps    WHERE lap<>?", (lap,))
        dst.commit()
        try:
            dst.execute("VACUUM"); dst.commit()
        except Exception:
            pass
    finally:
        dst.close()


# ── REFERENCE LAP automatici (best per classe + pista + meteo) ─────────────
REF_WET_THRESHOLD = 0.10          # wetness oltre cui la sessione è WET


def declared_wet_from_surface(surf4):
    """UNICA fonte DRY/WET per tempi/REF/stint: la dichiarazione netta di LMU
    `mSurfaceType` per ruota (0=asfalto asciutto, 1=asfalto bagnato,
    2-6=fuori pista). Guarda solo le ruote sull'asfalto (0/1) e dichiara WET se
    la maggioranza è bagnata. 1.0=WET, 0.0=DRY, None se ignoto."""
    if not surf4:
        return None
    try:
        asph = [int(s) for s in surf4 if int(s) in (0, 1)]
    except Exception:
        return None
    if not asph:
        return None
    nwet = sum(1 for s in asph if s == 1)
    return 1.0 if (nwet * 2) > len(asph) else 0.0


def ref_meteo(wetness):
    """Meteo a 2 stati fissi: 'WET' se wetness > soglia, altrimenti 'DRY'."""
    try:
        return "WET" if (wetness or 0.0) > REF_WET_THRESHOLD else "DRY"
    except Exception:
        return "DRY"


def ref_key(car_class, track, wetness):
    """(classe, pista_layout, meteo) normalizzati. None se mancano classe/pista.

    La pista include il LAYOUT (es. 'Monza' vs 'Monza_CurvaGrande') così i REF
    e i tempi non si mischiano tra layout diversi dello stesso circuito."""
    cls = "".join(c for c in (car_class or "") if c.isalnum()).upper()
    short = _short_track(track or "")
    if not cls or not short:
        return None
    suf = _layout_suffix(track or "")
    trk = (short + "_" + suf) if suf else short
    return (cls, trk, ref_meteo(wetness))


def ref_path(cls, trk, meteo):
    return REFS_DIR / f"ref_{cls}_{trk}_{meteo}.lmref"


def ref_path_for(car_class, track, wetness):
    k = ref_key(car_class, track, wetness)
    return ref_path(*k) if k else None


def ref_best_time(path):
    """lap_time del reference salvato (None se assente/illeggibile)."""
    try:
        import os
        if not os.path.exists(path):
            return None
        con = sqlite3.connect(str(path))
        row = con.execute("SELECT lap_time FROM laps ORDER BY lap LIMIT 1").fetchone()
        con.close()
        return row[0] if row and row[0] else None
    except Exception:
        return None


def update_reference_if_better(src_con, lap, car_class, track, wetness):
    """Se il giro `lap` (valido) è il miglior tempo per classe+pista+meteo,
    lo salva come reference sovrascrivendo il record precedente.
    Ritorna il path aggiornato, altrimenti None."""
    k = ref_key(car_class, track, wetness)
    if not k:
        return None
    path = ref_path(*k)
    try:
        row = src_con.execute(
            "SELECT lap_time FROM laps WHERE lap=? AND invalid=0", (lap,)).fetchone()
    except Exception:
        return None
    lt = row[0] if row else None
    if not lt or lt <= 0:
        return None
    best = ref_best_time(path)
    if best is not None and lt >= best:
        return None
    save_reference(src_con, lap, str(path))
    return str(path)


def list_references():
    """Tutti i reference salvati: lista di dict (cls, track, meteo, lap_time, path)."""
    out = []
    try:
        if not REFS_DIR.exists():
            return out
        for f in sorted(REFS_DIR.glob("ref_*.lmref")):
            d = {"path": str(f), "name": f.name}
            try:
                con = sqlite3.connect(str(f))
                r = con.execute("SELECT lap_time FROM laps ORDER BY lap LIMIT 1").fetchone()
                d["lap_time"] = r[0] if r else None
                con.close()
            except Exception:
                d["lap_time"] = None
            out.append(d)
    except Exception:
        pass
    return out
