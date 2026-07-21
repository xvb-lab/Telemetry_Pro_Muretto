"""core/motec_ld.py — Writer minimale per file MoTeC i2 (.ld).

Formato binario derivato da gotzl/ldparser (GPL). Scrive header + event +
meta-canali + dati come float32 (scale=1, shift=0, mul=1, dec=0), così il
valore memorizzato coincide col valore reale.

Uso:
    chans = [("Speed", "Speed", "km/h", [..floats..]), ...]
    write_ld(path, chans, freq=50, driver="..", vehicle="..", venue="..",
             comment="..", when=datetime.datetime.now())
Tutti i canali devono avere la stessa lunghezza (campionati alla stessa freq).
"""
import struct
import datetime
from array import array

_HEAD_FMT = "<" + (
    "I4x"     # ldmarker (0x40)
    "II"      # meta_ptr, data_ptr
    "20x"
    "I"       # event_ptr
    "24x"
    "HHH"     # static (1, 0x4240, 0x000F)
    "I"       # device serial
    "8s"      # device type
    "H"       # device version
    "H"       # static
    "I"       # num channels
    "4x"
    "16s"     # date
    "16x"
    "16s"     # time
    "16x"
    "64s"     # driver
    "64s"     # vehicle id
    "64x"
    "64s"     # venue
    "64x"
    "1024x"
    "I"       # static
    "66x"
    "64s"     # short comment
    "126x"
)
_EVENT_FMT = "<64s64s1024sH"
_CHAN_FMT = "<" + (
    "IIII"    # prev_ptr, next_ptr, data_ptr, data_len
    "H"       # counter
    "HHH"     # dtype_a, dtype, freq
    "hhhh"    # shift, mul, scale, dec
    "32s"     # name
    "8s"      # short name
    "12s"     # unit
    "40x"
)


def _b(s, n):
    return (s or "").encode("ascii", "replace")[:n - 1]


def write_ld(path, channels, freq=50, driver="", vehicle="", venue="",
             comment="", when=None):
    when = when or datetime.datetime.now()
    head_sz = struct.calcsize(_HEAD_FMT)
    event_sz = struct.calcsize(_EVENT_FMT)
    chan_sz = struct.calcsize(_CHAN_FMT)

    n = len(channels)
    event_ptr = head_sz
    meta_ptr0 = head_sz + event_sz
    data_ptr0 = meta_ptr0 + n * chan_sz

    # pre-calcola i puntatori meta/data di ogni canale
    metas = []
    data_ptr = data_ptr0
    for i, (_, _, _, data) in enumerate(channels):
        meta_ptr = meta_ptr0 + i * chan_sz
        prev = meta_ptr0 + (i - 1) * chan_sz if i > 0 else 0
        nxt = meta_ptr0 + (i + 1) * chan_sz if i < n - 1 else 0
        metas.append((meta_ptr, prev, nxt, data_ptr, len(data)))
        data_ptr += len(data) * 4   # float32

    with open(path, "wb") as f:
        # header
        f.write(struct.pack(
            _HEAD_FMT,
            0x40, meta_ptr0, data_ptr0, event_ptr,
            1, 0x4240, 0xf,
            0x1f44, b"ADL", 420, 0xadb0, n,
            when.strftime("%d/%m/%Y").encode(),
            when.strftime("%H:%M:%S").encode(),
            _b(driver, 64), _b(vehicle, 64), _b(venue, 64),
            0xc81a4, _b(comment, 64)))
        # event (nessun venue/vehicle: venue_ptr = 0)
        f.seek(event_ptr)
        f.write(struct.pack(_EVENT_FMT,
                            _b("Session", 64), _b("0", 64),
                            _b(comment, 1024), 0))
        # meta canali
        f.seek(meta_ptr0)
        for i, (name, short, unit, _) in enumerate(channels):
            meta_ptr, prev, nxt, dptr, dlen = metas[i]
            f.write(struct.pack(
                _CHAN_FMT,
                prev, nxt, dptr, dlen,
                0x2ee1 + i,
                0x07, 4, int(freq),        # float32
                0, 1, 1, 0,                # shift, mul, scale, dec
                _b(name, 32), _b(short, 8), _b(unit, 12)))
        # dati canali (float32 LE)
        import sys
        for (_, _, _, data) in channels:
            arr = array("f", [float(x) for x in data])
            if sys.byteorder == "big":
                arr.byteswap()
            f.write(arr.tobytes())
