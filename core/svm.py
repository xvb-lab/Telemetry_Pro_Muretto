"""core/svm.py — Parser round-trip per i file setup LMU (.svm).

Formato: stile INI.
  Righe header (prima della prima sezione): VehicleClassSetting=..., //commenti
  Sezioni: [GENERAL], [SUSPENSION], ...
  Chiavi:  KeyNameSetting=<intero>//<valore leggibile>

Il parser conserva TUTTE le righe verbatim (commenti inclusi). Modificando il
valore di una chiave si rigenera solo quella riga; il resto resta identico.
"""
import re

_KV = re.compile(r'^([A-Za-z0-9_]+)=(-?\d+)(//.*)?$')


class SVM(object):
    def __init__(self, lines, eol="\n", trailing=""):
        self._lines = lines        # lista di dict
        self._eol = eol
        self._trailing = trailing

    @classmethod
    def parse(cls, text):
        eol = "\r\n" if "\r\n" in text else "\n"
        # conserva eventuale newline finale
        trailing = eol if text.endswith(("\n", "\r")) else ""
        raw_lines = text.splitlines()
        lines = []
        section = None
        for raw in raw_lines:
            s = raw.strip()
            if s.startswith("[") and s.endswith("]"):
                section = s[1:-1]
                lines.append({"type": "section", "name": section, "raw": raw})
                continue
            m = _KV.match(s)
            if m and not s.startswith("//"):
                key, val, comment = m.group(1), int(m.group(2)), (m.group(3) or "")
                lines.append({"type": "kv", "section": section, "key": key,
                              "value": val, "comment": comment, "raw": raw})
            else:
                lines.append({"type": "raw", "raw": raw})
        return cls(lines, eol, trailing)

    def to_text(self):
        return self._eol.join(l["raw"] for l in self._lines) + self._trailing

    def sections(self):
        """Ritorna lista ordinata: [(section, [entry...])] dove entry e' il dict
        della riga kv (con idx)."""
        out = []; cur = None
        for i, l in enumerate(self._lines):
            if l["type"] == "section":
                cur = (l["name"], [])
                out.append(cur)
            elif l["type"] == "kv" and cur is not None:
                e = dict(l); e["idx"] = i
                cur[1].append(e)
        return out

    def get(self, section, key):
        for l in self._lines:
            if l["type"] == "kv" and l.get("section") == section and l["key"] == key:
                return l["value"]
        return None

    def set_value(self, idx, value):
        """Aggiorna il valore (intero) di una riga kv e rigenera la riga raw.
        Mantiene il commento esistente come riferimento (LMU lo ricalcola al
        caricamento, ma resta leggibile)."""
        l = self._lines[idx]
        if l["type"] != "kv":
            return
        value = int(value)
        if value == l["value"]:
            return
        l["value"] = value
        # rigenera la riga: chiave=valore + commento originale (di riferimento)
        l["raw"] = "%s=%d%s" % (l["key"], value, l.get("comment") or "")

    def vehicle_class(self):
        for l in self._lines:
            if l["type"] == "raw" and l["raw"].startswith("VehicleClassSetting="):
                return l["raw"].split("=", 1)[1].strip().strip('"')
        return ""

    def notes(self):
        return self.get("GENERAL", None) or ""
