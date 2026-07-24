"""ui/tab_community.py — scheda estratta 1:1 da window.py."""

from ui.widgets import _car_logo_into, _fmt_ms, _EMPTY_LOGO_SVG, _brand_from_car_name
import os
import sqlite3
import time
import math
from PySide6.QtWidgets import (QWidget, QMainWindow, QTabWidget, QTabBar, QVBoxLayout,
                               QHBoxLayout, QComboBox, QPushButton, QLabel,
                               QTableWidget, QTableWidgetItem, QHeaderView,
                               QAbstractItemView, QStyledItemDelegate, QMessageBox,
                               QColorDialog, QStackedWidget, QGridLayout, QSizePolicy,
                               QLineEdit, QFrame, QCheckBox)
from PySide6.QtCore import Qt, QRectF, QPointF, QTimer, QSize
from pathlib import Path
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QPolygonF, QFont, QPainterPath, QLinearGradient, QPixmap
from telemetry import common as _common
from telemetry.common import (_ACCENT, _BG, _CLASS_COL, _CMP_COL, _CMP_IS_BEST, _FG, _FUCHSIA, _FUX, _GOLD, _GRID, _HYBRID_HINTS, _MONTHS, _SEL_COL, _SEL_IS_BEST, _SVG_RENDERER_CACHE, _SvgBox, _TRK_COL, _best_color, _clear_layout, _cmp_col, _date_human, _draw_lap_legend, _draw_sector_times, _dur, _f2, _faster_colors, _fastest_lap, _fmt, _heat, _is_b, _is_hybrid, _rows, _sel_col, _two_best_laps)
from telemetry.trace_view import (EnergiaView, GommeView, GuidaView, LineChart, LiveView, MappaView, TrajectoryView, _BrakesTab, _CatTable, _CmpChart, _DeltaTab, _FitTable, _GGCanvas, _GGTab, _LapData, _LiveMap, _LiveSpeedChart, _PedalChart, _PedalsTab, _StintTab, _SuspTab, _TraceChart, _TraceTab, _TyreCorner, _TyresTab, _WorksheetTab, _delta_series, _load_track_svg, _resample, _spd_series, _t_series, _wheel_widget)
from telemetry.engineer_tab import _EngineerTab
from data.tracks import (_ALT_LAYOUT_STEMS, _LAYOUT_LABELS, _OV_LOGO_ALIASES, _OV_TRACKLOGO_DIR, _OV_TRACKMAPS_PNG_DIR, _OV_TRACKMAPS_SVG_DIR, _OV_TRACKMAP_DIR, _TRACK_PNG_ALIASES, _TRACK_ROT_JSON, _cmap_layout_key, _decode_stem, _layout_key_for_cmap, _layout_key_for_track, _ov_tracklogo_file, _ov_trackmap_file, _ov_trackmap_idx, _track_is_alt, _track_layout_key, _track_layout_label, _track_logo_stem, _track_png_file, _track_rot, _track_rot_map, _track_short, _track_styled_svg, _trackmap_white_bytes, _trackmap_white_cache)
from ui.widgets import (_CircleCheck, _ClassBadge, _ClassChip, _ClickFrame, _EXPORT_SVG, _ExportButton, _FOLDER_SVG, _Switch, _TRASH_SVG, _XButton, _X_SVG, _abbr_num, _chip, _class_color, _export_icon, _export_icon_cache, _folder_icon, _folder_icon_cache, _mk_check, _svg_icon, _trash_icon, _trash_icon_cache, _x_icon, _x_icon_cache)
try:
    from PySide6.QtSvgWidgets import QSvgWidget
except Exception:
    QSvgWidget = None
try:
    from PySide6.QtSvg import QSvgRenderer
except Exception:
    QSvgRenderer = None
from PySide6.QtCore import QByteArray
from telemetry import db as _db
from telemetry.reader import TelemetryReader
from core.classes import class_tag
from ui.icons import FUEL_WEIGHT_SVG as _FUEL_WEIGHT_SVG
try:
    from core.paths import PROFILE_FILE as _PROFILE_FILE
except Exception:
    _PROFILE_FILE = Path(__file__).resolve().parent.parent / "settings" / "profile.json"


class _TrackRow(QFrame):
    """Riga pista: logo circuito + nome + badge classe SVG cliccabili."""

    def __init__(self, track, classes, on_pick):
        super().__init__()
        self.setObjectName("commTrack")
        self.setStyleSheet("#commTrack{background:rgba(255,255,255,0.05);"
                           "border:none;border-radius:10px;}")
        h = QHBoxLayout(self); h.setContentsMargins(12, 10, 14, 10); h.setSpacing(12)
        disp = (track or "").replace("-", " ")
        logo = _SvgBox(); logo.setFixedSize(72, 46)      # logo pista piu' grande
        f = _ov_tracklogo_file(disp)
        logo.load(str(f) if f else _EMPTY_LOGO_SVG)
        h.addWidget(logo, 0, Qt.AlignVCenter)
        nm = QLabel(_track_short(track))
        nm.setStyleSheet("color:#f2f4f7;font-size:16px;font-weight:700;"  # nome piu' grande
                         "background:transparent;")
        nm.setMinimumWidth(160)
        h.addWidget(nm)
        h.addStretch()
        # classi: sub-layout compatto. Niente piu' numero sotto (rimosso): solo
        # i badge classe cliccabili.
        cls_row = QHBoxLayout()
        cls_row.setContentsMargins(0, 0, 0, 0); cls_row.setSpacing(6)
        _cdir = Path(__file__).resolve().parent.parent / "assets" / "class"
        for c in classes:
            _cp = _cdir / ((c or "").lower() + ".svg")
            if _cp.exists():
                chip = _ClassBadge(c, str(_cp), lambda cc=c: on_pick(track, cc))
            else:
                chip = _ClassChip(c, lambda cc=c: on_pick(track, cc))
            cls_row.addWidget(chip, 0, Qt.AlignVCenter)
        h.addLayout(cls_row)


def _car_render_path(model):
    """Modello del record ('Porsche 911 GT3 R LMGT3') -> render
    ufficiale in assets/car-th (WEC 2026 -> 2025 -> ELMS). None se
    non c'e' un render onesto per quel modello."""
    ml = (model or "").lower()
    if not ml:
        return None
    RULES = [
        ("porsche 911", "porsche-911"), ("porsche 963", "porsche-963"),
        ("bmw m4", "bmw-m4"), ("bmw m hybrid", "bmwm-hybrid"),
        ("ferrari 296", "ferrari-296"), ("ferrari 499", "ferrari-499"),
        ("296", "ferrari-296"), ("499", "ferrari-499"),
        ("mclaren 720", "mclaren-720s"), ("mustang", "ford-mustang"),
        ("corvette", "corvette"), ("lexus", "lexus"),
        ("mercedes", "mercedes"), ("valkyrie", "valkyrie"),
        ("vantage", "aston-martin-gt3"), ("aston", "aston-martin"),
        ("oreca", "oreca-07"), ("ligier", "ligier-js"),
        ("duqueine", "duqueine"), ("cadillac", "cadillac"),
        ("toyota", "toyota"), ("peugeot", "peugeot"),
        ("alpine", "alpine"), ("genesis", "genesis"),
        ("lamborghini", "lamborghini"),
    ]
    tok = next((t for k, t in RULES if k in ml), None)
    if not tok:
        return None
    root = Path(__file__).resolve().parent.parent / "assets"
    for sub in ("car-th", "car-th/2025", "car-th/elms"):
        d = root / sub
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.png")):
            if tok in f.name.lower():
                return f
    return None


class _RankRow(QFrame):
    """Riga classifica: posizione + pilota/team + logo + gomma + kg + tempo+gap
    + settori. Il 1° in tinta oro."""

    def __init__(self, pos, rec, leader_ms, wet=False):
        super().__init__()
        self.setObjectName("rankRow")
        top = (pos == 1)
        _ACC = "#4aa3df" if wet else _GOLD          # WET=azzurro, DRY=oro
        _accrgba = "rgba(74,163,223,0.16)" if wet else "rgba(245,197,66,0.16)"
        # bordo sinistro per categoria: WEC (HY/GT3) azzurrino, ELMS (P2/P3/GTE) arancio
        _clsu = (rec.get("car_class") or rec.get("class")
                 or (rec.get("key") or "").split("_")[0] or "").upper()
        if ("HY" in _clsu) or ("LMH" in _clsu) or ("HYPER" in _clsu) or ("GT3" in _clsu):
            _bord = "#00b9ff"
        elif ("P2" in _clsu) or ("P3" in _clsu) or ("GTE" in _clsu):
            _bord = "#ff5f00"
        else:
            _bord = "#ffffff"
        # CARD BROADCAST NATIVA: sfondo in TINTA BRAND (niente PNG),
        # loghi SVG nostri (nitidi) e font Archivo come le onboard
        self._card_bg = None
        try:
            from PySide6.QtGui import QColor as _QC
            from core.wec_style import (brand_color_from_text, is_light,
                                        brand_from_text, row_gradient,
                                        row_color)
            _bn = brand_from_text((rec.get("car") or "") + " "
                                  + (rec.get("team") or ""))
            # override riga (Toyota bordeaux) anche sulle classifiche
            _c = (row_color(_bn) if _bn else None) or \
                brand_color_from_text((rec.get("car") or "") + " "
                                      + (rec.get("team") or ""))
            self._card_bg = _QC(_c) if _c else None
            # su base CHIARA: nero leggero (come il logo Cadillac),
            # non piu' navy
            self._card_txc = "#18181C" if (_c and is_light(_c)) \
                else "#ffffff"
            self._card_tri = row_gradient(_bn) if _bn else None
            from core.wec_style import row_corner as _rcor
            self._card_acc = _rcor(_bn) if _bn else ""
        except Exception:
            self._card_bg = None
        if self._card_bg is not None:
            self.setFixedHeight(84)
            self.setStyleSheet("#rankRow{background:transparent;"
                               "border:none;}")
            h = QHBoxLayout(self)
            h.setContentsMargins(16, 8, 14, 8)
            h.setSpacing(0)
        else:
            self.setStyleSheet(
                "#rankRow{background:%s;border:none;border-left:3px solid %s;"
                "border-radius:9px;}"
                % ("rgba(10,0,50,0.90)", _bord))
            h = QHBoxLayout(self)
            h.setContentsMargins(13, 10, 14, 10)
            h.setSpacing(0)
        pcol = "#ffffff"
        pb = QLabel(str(pos)); pb.setFixedWidth(44); pb.setAlignment(Qt.AlignCenter)
        if self._card_bg is not None:
            # numero grande corsivo, stesso stile delle card onboard
            pb.setStyleSheet(
                "color:%s;font-family:'Archivo SemiExpanded';"
                "font-size:30px;font-weight:900;font-style:italic;"
                "background:transparent;"
                % getattr(self, "_card_txc", "#ffffff"))
        else:
            pb.setStyleSheet("color:%s;font-size:18px;font-weight:800;"
                             "background:transparent;" % pcol)
        # logo SVG nostro: box LARGO sulle card + PROPORZIONE per
        # marchio dalla libreria (tutti visivamente della stessa taglia)
        box = _SvgBox()
        if self._card_bg is not None:
            try:
                from core.wec_style import brand_from_text, LOGO_SCALE
                _bnm = brand_from_text((rec.get("car") or "") + " "
                                       + (rec.get("team") or ""))
                _k = LOGO_SCALE.get(_bnm, 1.0)
            except Exception:
                _k = 1.0
            box.setFixedSize(96, max(30, min(66, int(58 * _k))))
        else:
            box.setFixedSize(58, 46)
        _car_logo_into(box, rec.get("team"), rec.get("car"))
        # sulle card: versione LOGO DEDICATA da cardlogo/ (se esiste)
        if self._card_bg is not None:
            try:
                from core.wec_style import card_logo_path
                _clp = card_logo_path(_bnm)
                if _clp and "cardlogo" in _clp:
                    box.load(_clp)
            except Exception:
                pass
        if self._card_bg is not None:
            # POSIZIONE prima, poi LOGO (attaccati)
            h.addWidget(pb); h.addSpacing(2)
            h.addWidget(box, 0, Qt.AlignVCenter); h.addSpacing(12)
        else:
            h.addWidget(pb); h.addSpacing(10)
            h.addWidget(box, 0, Qt.AlignVCenter); h.addSpacing(12)
        dcol = QVBoxLayout(); dcol.setSpacing(1); dcol.setContentsMargins(0, 0, 0, 0)
        # nome corto broadcast: "J. Sanfilippo" / "J. M. Sanfilippo" (util unico)
        from core.utils import short_name as _sn
        _pn = _sn(rec.get("player") or "") or "\u2014"
        dl = QLabel(_pn.upper())
        if self._card_bg is not None:
            dl.setStyleSheet(
                "color:%s;font-family:'Archivo SemiExpanded';"
                "font-size:15px;font-weight:900;font-style:italic;"
                "background:transparent;"
                % getattr(self, "_card_txc", "#ffffff"))
        else:
            dl.setStyleSheet("color:#eef0f4;font-family:'Archivo SemiExpanded';font-size:15px;"
                             "font-weight:800;background:transparent;")
        cl = QLabel(rec.get("car") or "\u2014")
        tl = QLabel(rec.get("team") or "NO TEAM")
        if self._card_bg is not None:
            # su card: colore adattivo (scuro su basi chiare)
            _txc = getattr(self, "_card_txc", "#ffffff")
            cl.setStyleSheet("color:%s;font-family:'Archivo SemiExpanded';"
                             "font-size:12px;font-weight:700;"
                             "background:transparent;" % _txc)
            tl.setStyleSheet("color:%s;font-family:'Archivo SemiExpanded';"
                             "font-size:12px;font-weight:600;"
                             "background:transparent;" % _txc)
        else:
            cl.setStyleSheet("color:%s;font-family:'Archivo SemiExpanded';font-size:12px;"
                             "font-weight:700;background:transparent;"
                             % _bord)
            tl.setStyleSheet("color:#a79fb0;font-family:'Archivo SemiExpanded';"
                             "font-size:12px;font-weight:600;"
                             "background:transparent;")
        dcol.addWidget(dl); dcol.addWidget(cl); dcol.addWidget(tl)
        dw = QWidget(); dw.setLayout(dcol)
        dw.setFixedWidth(252 if self._card_bg is not None else 200)
        dw.setStyleSheet("background:transparent;")
        h.addWidget(dw)
        if self._card_bg is not None:
            # card COMPATTA: dati SUBITO dopo i nomi (niente vuoto),
            # larghezza fissa — la card non si espande a tutta pagina
            h.addSpacing(26)
        else:
            h.addSpacing(8)
        # CASCO del pilota: livrea scelta dall'autore del tempo (campo
        # "helmet" nel record del Worker). Se manca (record delle versioni
        # vecchie) mostriamo un CASCO BASE neutro, cosi' la riga non resta
        # spoglia e si copre la differenza tra vecchia versione e questa.
        _hcode = str(rec.get("helmet") or "").strip()
        _hex = _hcode if (_hcode.startswith("#") and len(_hcode) == 7) \
            else "#8a90a0"                    # grigio neutro = casco base
        _helmet_w = None
        try:
            from ui.icons import helmet_svg_bytes
            _hbx = _SvgBox(); _hbx.setFixedSize(46, 36)
            _hbx.setStyleSheet("background:transparent;")
            _hbx.load(helmet_svg_bytes(_hex))
            _helmet_w = _hbx      # aggiunto DOPO i kg carburante
        except Exception:
            pass
        # GAP subito dopo il nome (prima dei simboli). Bianco, accento sul 1°.
        _ms0 = rec.get("lap_ms")
        _gap = ("+%.3f" % ((_ms0 - leader_ms) / 1000.0)) \
            if (leader_ms and _ms0 and _ms0 > leader_ms) else ""
        gcol = QLabel(_gap)
        # GAP piu' grande (rich. 24/07 sera: quasi doppio, 13->22px)
        gcol.setStyleSheet("color:%s;font-family:'Archivo SemiExpanded';font-size:22px;"
                           "font-weight:800;background:transparent;"
                           % ("#f2f4f7"))
        gcol.setFixedWidth(96)
        gcol.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        # (il gap viene aggiunto ACCANTO AL TEMPO, sul blu: leggibile)
        from core.tyre_cell import TyreCell
        c4 = rec.get("compounds4") or ""
        # record VECCHI con la "Soft" finta su GT3 (bug "Slick"->S del
        # reader, corretto alla fonte): in GT3 la dry e' solo la MEDIA
        _cls = (rec.get("car_class") or rec.get("class") or "").upper()
        if "GT3" in _cls:
            c4 = c4.replace("S", "M")
            if (rec.get("compound") or "").upper() == "S":
                rec = dict(rec, compound="M")
        four = [x.strip() for x in c4.split(",") if x.strip()]
        single = rec.get("compound") or (four[0] if four else "M")
        # il diametro del badge = 24*scale (NON dipende da 'size'): uso scale
        # per farlo grande come la goccia benzina (~31 px).
        _oncard = self._card_bg is not None
        # su card: icone COMPATTE (vanno a destra dopo il tempo)
        tc = TyreCell(size=36, scale=(0.95 if _oncard else 1.3))
        tc.setStyleSheet("background:transparent;")
        _ts = rec.get("tyre_state_pct")
        _new = (_ts is None) or (_ts >= 99.0)
        if len(four) == 4:
            tc.set_tyre(single, four, new4=[_new, _new, _new, _new], single_new=_new)
        else:
            tc.set_tyre(single, None, single_new=_new)
        tc.setFixedHeight(26 if _oncard else 34)
        # mescola sopra, USURA % sotto
        # margine BASSO sulla card (rich. 24/07 sera): con la riga
        # centrata verticalmente, un pad in basso alza il simbolo gomma
        _tcol = QVBoxLayout(); _tcol.setSpacing(1)
        _tcol.setContentsMargins(0, 0, 0, 8 if _oncard else 0)
        _tcol.addWidget(tc, 0, Qt.AlignHCenter)
        _wl = QLabel(("%d%%" % round(_ts)) if _ts is not None else "—")
        _wl.setAlignment(Qt.AlignHCenter)
        _wl.setStyleSheet("color:#f2f4f7;font-size:%dpx;font-weight:700;"
                          "background:transparent;"
                          % (12 if _oncard else 12))
        _tcol.addWidget(_wl, 0, Qt.AlignHCenter)
        _tw = QWidget(); _tw.setLayout(_tcol)
        _tw.setStyleSheet("background:transparent;")
        fl = rec.get("fuel_l")
        # goccia viola benzina sopra, kg sotto
        _fcol = QVBoxLayout(); _fcol.setSpacing(1)
        _fcol.setContentsMargins(0, 0 if _oncard else 8, 0, 0)
        _fic = _SvgBox()
        # benzina un filo piu' grande (rich. 24/07 sera: stesso diametro
        # del simbolo gomma) 24->28
        _fic.setFixedSize(*((28, 28) if _oncard else (32, 32)))
        try:
            from ui.icons import FUEL_WEIGHT_SVG as _FWS
            _fic.load(_FWS.encode("utf-8") if isinstance(_FWS, str) else _FWS)
        except Exception:
            pass
        _fcol.addWidget(_fic, 0, Qt.AlignHCenter)
        fk = QLabel(("+%.0f kg" % (fl * 0.75)) if fl is not None else "\u2014")
        fk.setStyleSheet("color:#e8eaee;font-size:%dpx;font-weight:700;"
                         "background:transparent;margin-top:2px;"
                         % (12 if _oncard else 12))
        fk.setAlignment(Qt.AlignHCenter)
        _fcol.addWidget(fk, 0, Qt.AlignHCenter)
        _fw = QWidget(); _fw.setFixedWidth(46 if _oncard else 64)
        _fw.setLayout(_fcol)
        _fw.setStyleSheet("background:transparent;")
        if not _oncard:
            # righe flat: layout storico (gomma+benzina prima del casco)
            h.addWidget(_tw, 0, Qt.AlignVCenter); h.addSpacing(14)
            h.addWidget(_fw)
        # card: niente render qui (le auto vivono negli OVERLAY);
        # gomma e benzina compatte vanno dopo il tempo. CASCO RIMOSSO
        # dalla classifica (rich. 24/07 sera: cambiata idea) in entrambi
        # i layout
        if self._card_bg is None:
            h.addStretch()
        else:
            # STRETCH prima del gruppo (rich. 24/07 sera): spinge gap,
            # tempo, settori e simboli a DESTRA a riempire lo spazio
            # lasciato dalle medaglie tolte
            h.addStretch(1)
            h.addSpacing(18)
        h.addWidget(gcol); h.addSpacing(8)
        ms = rec.get("lap_ms")
        if self._card_bg is not None:
            # card: TEMPO sopra grande, SETTORI sotto piccoli
            _tcol2 = QVBoxLayout()
            _tcol2.setSpacing(1)
            _tcol2.setContentsMargins(0, 0, 0, 0)
            t = QLabel(_fmt_ms(ms))
            t.setStyleSheet("color:#f2f4f7;font-family:'Archivo SemiExpanded';"
                            "font-size:19px;font-weight:800;"
                            "background:transparent;")
            t.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            _tcol2.addWidget(t)
            # COLORI SETTORE come sulla mappa (rich. 24/07 sera): S1
            # rosso del traguardo, S2/S3 azzurro delle tacche settore
            _SCOL9 = ("#ff6b6b", "#33bbff", "#33bbff")
            _secs = "&nbsp;&nbsp;&nbsp;".join(
                '<span style="color:%s">%s</span>' % (
                    _c, (_fmt_ms(rec.get(_sk)) if rec.get(_sk) else "—"))
                for _sk, _c in zip(("s1_ms", "s2_ms", "s3_ms"), _SCOL9))
            _s2 = QLabel(_secs)
            _s2.setTextFormat(Qt.RichText)
            # settori un filo piu' grandi (rich. 24/07 sera): 11->13px
            _s2.setStyleSheet("font-family:'Archivo SemiExpanded';"
                              "font-size:13px;font-weight:700;"
                              "background:transparent;")
            _s2.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            _tcol2.addWidget(_s2)
            _tw2 = QWidget()
            _tw2.setLayout(_tcol2)
            # colonna PIU' LARGA (rich. 24/07 sera): i settori erano
            # schiacciati, l'ultimo si tagliava
            _tw2.setFixedWidth(184)
            _tw2.setStyleSheet("background:transparent;")
            h.addWidget(_tw2, 0, Qt.AlignVCenter)
            # icone COMPATTE dopo il tempo: mescola+usura, benzina+kg
            h.addSpacing(24)
            h.addWidget(_tw, 0, Qt.AlignVCenter)
            h.addSpacing(10)
            h.addWidget(_fw, 0, Qt.AlignVCenter)
            # niente stretch finale: il gruppo arriva fino al BORDO
            # destro (rich. 24/07 sera), solo un margine
            h.addSpacing(22)
            # -100px (rich. 24/07 sera): a 980 usciva una barra scroll
            # orizzontale per un pelo
            self.setFixedWidth(880)
        else:
            t = QLabel(_fmt_ms(ms))
            t.setStyleSheet("color:%s;font-family:'Archivo SemiExpanded';font-size:19px;"
                            "font-weight:800;background:transparent;"
                            % ("#f2f4f7"))
            t.setFixedWidth(104)
            t.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            h.addWidget(t)
            h.addSpacing(10)
            # colori settore come sulla mappa: S1 rosso, S2/S3 azzurro
            _SCOL9 = ("#ff6b6b", "#33bbff", "#33bbff")
            for _sk, _sc9 in zip(("s1_ms", "s2_ms", "s3_ms"), _SCOL9):
                _sv = rec.get(_sk)
                _sl = QLabel(_fmt_ms(_sv) if _sv else "—")
                _sl.setFixedWidth(62)
                _sl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                _sl.setStyleSheet("color:%s;font-family:'Archivo SemiExpanded';"
                                  "font-size:14px;font-weight:700;"
                                  "background:transparent;" % _sc9)
                h.addWidget(_sl); h.addSpacing(6)

    def _trophy_widget(self, pos):
        """Colonna TROFEO a larghezza FISSA (non spinge la riga): trofeo per i
        primi 3 (oro/argento/bronzo), vuota per gli altri -> spazio riservato
        uguale per tutte le righe. Render 2x nitido (niente sgranatura)."""
        lb = QLabel()
        lb.setFixedWidth(60)
        lb.setAlignment(Qt.AlignCenter)
        lb.setStyleSheet("background:transparent;")
        if pos in (1, 2, 3):
            try:
                from PySide6.QtGui import QPixmap
                _tp = (Path(__file__).resolve().parent.parent
                       / "assets" / "img" / ("tr_%d.png" % pos))
                if _tp.exists():
                    pm = QPixmap(str(_tp))
                    if not pm.isNull():
                        dpr = 2.0
                        pm = pm.scaledToHeight(int(52 * dpr),
                                               Qt.SmoothTransformation)
                        pm.setDevicePixelRatio(dpr)
                        lb.setPixmap(pm)
            except Exception:
                pass
        return lb

    def paintEvent(self, e):
        # sfondo card: TINTA BRAND con gradiente + barra bianca diagonale
        # (stile onboard), tutto nativo: zero PNG, zero sgranature
        bg = getattr(self, "_card_bg", None)
        if bg is not None:
            from PySide6.QtGui import (QPainter, QPainterPath, QColor,
                                       QLinearGradient, QPen)
            from PySide6.QtCore import QRectF, QPointF, Qt
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            # spigoli VIVI, niente border radius (stile broadcast)
            # tinta brand a sinistra con TAGLIO NETTO dopo i nomi,
            # poi blu WEC #0A0032 pieno (niente sfumatura)
            cut = 418.0
            g = QLinearGradient(0, 0, cut, 0)
            tri = getattr(self, "_card_tri", None)
            if tri:
                # stop UFFICIALI della style guide (niente neon)
                g.setColorAt(0.0, QColor(tri[0]))
                g.setColorAt(1.0, QColor(tri[1]))
            else:
                g.setColorAt(0.0, bg.lighter(112))
                g.setColorAt(1.0, bg)
            p.fillRect(QRectF(0, 0, cut, self.height()), g)
            # parte destra (tempi) TRASLUCIDA (esperimento 24/07 sera):
            # base scura semi-trasparente + velo chiaro tenue = vetro
            # smerigliato ma piu' OPACO (era troppo chiaro)
            p.fillRect(QRectF(cut, 0, self.width() - cut,
                              self.height()), QColor(13, 27, 42, 150))
            p.fillRect(QRectF(cut, 0, self.width() - cut,
                              self.height()), QColor(228, 236, 248, 22))
            # STRISCE oblique sul taglio (stile Alpine) per i team scelti
            _acc = getattr(self, "_card_acc", None) or []
            if _acc:
                from PySide6.QtGui import QPolygonF
                _h = float(self.height())
                p.setPen(Qt.NoPen)
                _bw, _sl = 16.0, 46.0
                for _i, _cc in enumerate(reversed(_acc)):
                    _tr = cut - _i * _bw    # bordo dx striscia (alto)
                    p.setBrush(QColor(_cc))
                    if _i == 0 and len(_acc) >= 3:
                        # ULTIMA striscia delle triple: banda+angolo in
                        # UN poligono solo (niente cucitura tra neri)
                        p.drawPolygon(QPolygonF([
                            QPointF(_tr - _bw, 0.0), QPointF(cut, 0.0),
                            QPointF(cut, _h),
                            QPointF(_tr - _sl - _bw, _h)]))
                        continue
                    p.drawPolygon(QPolygonF([
                        QPointF(_tr - _bw, 0.0), QPointF(_tr, 0.0),
                        QPointF(_tr - _sl, _h),
                        QPointF(_tr - _sl - _bw, _h)]))
            p.end()
        super().paintEvent(e)


class _CommunityTab(QWidget):
    """Tab 'Community': sinistra le piste (logo + tag classe colorati). Clicchi
    un tag -> a destra la classifica ricca di quella pista+classe (1° in cima,
    poi i tempi successivi). Toggle DRY/WET."""
    _CLS_ORDER = {"HY": 0, "P2": 1, "P3": 2, "GT3": 3, "GTE": 4}

    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self); root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)
        bar = QHBoxLayout(); bar.setSpacing(8)
        title = QLabel("COMMUNITY"); title.setObjectName("ovColCap")
        bar.addWidget(title); bar.addStretch()
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setCursor(Qt.PointingHandCursor)
        self._refresh_btn.clicked.connect(lambda: self.reload(force=True))
        bar.addWidget(self._refresh_btn)
        root.addLayout(bar)
        self._status = QLabel(""); self._status.setObjectName("ovColCap")
        root.addWidget(self._status)
        body = QHBoxLayout(); body.setSpacing(12)
        from PySide6.QtWidgets import QScrollArea
        # sinistra: piste
        scL = QScrollArea(); scL.setWidgetResizable(True)
        scL.setFrameShape(QFrame.NoFrame)
        scL.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scL.setMinimumWidth(530); scL.setMaximumWidth(620)
        hostL = QWidget(); self._tracks_v = QVBoxLayout(hostL)
        self._tracks_v.setContentsMargins(0, 0, 0, 0); self._tracks_v.setSpacing(6)
        self._tracks_v.addStretch()
        scL.setWidget(hostL); body.addWidget(scL, 2)
        # destra: classifica
        rp = QFrame(); rp.setObjectName("ovCard")
        rpl = QVBoxLayout(rp); rpl.setContentsMargins(12, 12, 12, 12); rpl.setSpacing(8)
        hdr = QHBoxLayout()
        self._rank_title = QLabel("Select a track / class")
        self._rank_title.setStyleSheet("color:#e8eaee;font-size:13px;font-weight:700;"
                                       "background:transparent;")
        hdr.addWidget(self._rank_title); hdr.addStretch()
        self._dry_btn = QPushButton("DRY"); self._wet_btn = QPushButton("WET")
        for b, m in ((self._dry_btn, "DRY"), (self._wet_btn, "WET")):
            b.setCursor(Qt.PointingHandCursor); b.setCheckable(True)
            b.clicked.connect(lambda _=False, mm=m: self._set_meteo(mm))
            hdr.addWidget(b)
        rpl.addLayout(hdr)
        scR = QScrollArea(); scR.setWidgetResizable(True)
        scR.setFrameShape(QFrame.NoFrame)
        scR.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        hostR = QWidget(); self._rank_v = QVBoxLayout(hostR)
        self._rank_v.setContentsMargins(0, 0, 0, 0); self._rank_v.setSpacing(6)
        self._rank_v.addStretch()
        scR.setWidget(hostR); rpl.addWidget(scR, 1)
        body.addWidget(rp, 3)
        root.addLayout(body, 1)
        self._rows = []; self._tree = {}
        self._sel_track = None; self._sel_cls = None; self._sel_meteo = "DRY"
        self.reload()

    @staticmethod
    def _parse_key(key):
        parts = (key or "").split("_")
        if len(parts) < 3:
            return ("", key or "", "")
        return (parts[0], "_".join(parts[1:-1]), parts[-1])

    def reload(self, force=False):
        try:
            from core import online
            if not online.enabled():
                self._status.setText("Online non configurato (settings/online.json)")
                self._rows = []; self._build_tree(); return
            if force:
                self._rows = online.all_refs(refresh=True) or []
            else:
                online.load_async()
                self._rows = online.cached_refs() or []
            self._status.setText("%d piste" % len({self._parse_key(r.get("key"))[1]
                                                   for r in self._rows}))
        except Exception as e:
            self._rows = []
            self._status.setText("Errore: %s" % e)
        self._build_tree()

    def _build_tree(self):
        tree = {}
        pop = {}
        for r in self._rows:
            cls, trk, cond = self._parse_key(r.get("key"))
            trk = (trk or "").strip()         # chiave già corta+layout dall'upload
            tree.setdefault(trk, {}).setdefault(cls, set()).add(cond)
            pop[trk] = pop.get(trk, 0) + 1     # popolazione = n. record/sessioni
        # SCHELETRO: tutte le piste LMU x tutte le classi, sempre presenti
        try:
            _db._short_track("")               # forza il load di tracks.json
            all_tracks = sorted(set((_db._track_map or {}).values()))
        except Exception:
            all_tracks = []
        for trk in all_tracks:
            d = tree.setdefault(trk, {})
            for cls in ("HY", "P2", "P3", "GT3", "GTE"):
                d.setdefault(cls, set())
        self._tree = tree
        self._track_pop = pop
        self._render_tracks()

    def _render_tracks(self):
        while self._tracks_v.count() > 1:
            it = self._tracks_v.takeAt(0); w = it.widget()
            if w:
                w.deleteLater()
        pop = getattr(self, "_track_pop", {})
        if not self._tree:                     # nessun tempo online ancora
            empty = QLabel("No community times yet.\nBe the first: set a lap and it "
                           "will appear here.")
            empty.setWordWrap(True); empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet("color:#9aa0aa;font-family:'Archivo SemiExpanded';font-size:13px;"
                                "padding:24px;background:transparent;")
            self._tracks_v.insertWidget(self._tracks_v.count() - 1, empty)
            return
        # ordina per popolazione (decrescente), poi alfabetico a parità
        for trk in sorted(self._tree.keys(),
                          key=lambda t: (-pop.get(t, 0), t.lower())):
            classes = sorted(self._tree[trk].keys(),
                             key=lambda c: self._CLS_ORDER.get(c.upper(), 9))
            row = _TrackRow(trk, classes, self._pick)
            self._tracks_v.insertWidget(self._tracks_v.count() - 1, row)

    def _pick(self, track, cls):
        self._sel_track = track; self._sel_cls = cls
        conds = self._tree.get(track, {}).get(cls, set())
        self._sel_meteo = "WET" if ("WET" in conds and "DRY" not in conds) else "DRY"
        self._dry_btn.setEnabled(True)            # DRY sempre (mostra vuoto se nessun tempo)
        self._wet_btn.setEnabled("WET" in conds)
        self._refresh_rank()

    def _set_meteo(self, m):
        self._sel_meteo = m
        self._refresh_rank()

    def _refresh_rank(self):
        self._dry_btn.setChecked(self._sel_meteo == "DRY")
        self._wet_btn.setChecked(self._sel_meteo == "WET")
        disp = _track_short(self._sel_track)
        self._rank_title.setText("%s \u00b7 %s \u00b7 %s"
                                 % (self._sel_cls or "", disp, self._sel_meteo))
        while self._rank_v.count() > 1:
            it = self._rank_v.takeAt(0); w = it.widget()
            if w:
                w.deleteLater()
        if not (self._sel_track and self._sel_cls):
            return
        key = "%s_%s_%s" % (self._sel_cls, self._sel_track, self._sel_meteo)
        try:
            from core import online
            rows = online.top(key, 30)
        except Exception:
            rows = []
        lead = rows[0].get("lap_ms") if rows else None
        for i, rec in enumerate(rows):
            self._rank_v.insertWidget(self._rank_v.count() - 1,
                                      _RankRow(i + 1, rec, lead,
                                               wet=(self._sel_meteo == "WET")))

    def set_enabled(self, *_):
        pass
