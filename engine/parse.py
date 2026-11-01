"""Read test files and guess what each column holds.

Handles plain CSV/TSV/TXT, DAQ exports with metadata lines and a units
row, and XLSX (first sheet). Returns the numeric table plus a guess for
each column's role and unit. The page asks the user to confirm.
"""
import csv
import io
import re

import numpy as np

ROLES = ["time", "load", "load2", "lld", "lld2", "cmod", "ignore"]

LOAD_UNITS = {"kn": 1.0, "n": 1e-3, "lbf": 4.4482216e-3, "lb": 4.4482216e-3, "kip": 4.4482216, "kgf": 9.80665e-3}
DISP_UNITS = {"mm": 1.0, "in": 25.4, "um": 1e-3, "m": 1000.0, "cm": 10.0}
TIME_UNITS = {"s": 1.0, "ms": 1e-3, "min": 60.0}


def _num(s):
    s = str(s).strip().strip('"').strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        try:
            return float(s.replace(",", "."))
        except ValueError:
            return None


def _rows_from_text(text):
    lines = text.splitlines()
    sample = "\n".join(lines[:200])
    counts = {d: sample.count(d) for d in [",", "\t", ";"]}
    delim = max(counts, key=counts.get)
    if counts[delim] == 0:
        return [ln.split() for ln in lines], "space"
    if delim == ";" and counts[","] > 0:
        pass  # decimal commas, handled by _num
    return list(csv.reader(lines, delimiter=delim)), {",": "comma", "\t": "tab", ";": "semicolon"}[delim]


def _rows_from_xlsx(data):
    import openpyxl  # loaded by the worker for xlsx files
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = []
    for r in ws.iter_rows(values_only=True):
        rows.append(["" if v is None else str(v) for v in r])
    return rows


def _strip_trailing(rows):
    out = []
    for r in rows:
        r = list(r)
        while r and str(r[-1]).strip() == "":
            r.pop()
        out.append(r)
    return out


def _is_numeric_row(r, ncol=None):
    if not r:
        return False
    vals = [_num(x) for x in r]
    good = sum(v is not None for v in vals)
    return good >= max(2, int(0.8 * len(r)))


def read_table(name, data):
    """Return (header list, units list, numeric 2D array, meta dict)."""
    low = name.lower()
    meta = {"name": name}
    if low.endswith(".xls"):
        raise ValueError("Old .xls files are not supported. Save the file as .xlsx or .csv and add it again.")
    if low.endswith(".xlsx") or low.endswith(".xlsm"):
        rows = _rows_from_xlsx(data)
        meta["format"] = "xlsx"
    else:
        if isinstance(data, bytes):
            for enc in ("utf-8-sig", "utf-16", "latin-1"):
                try:
                    text = data.decode(enc)
                    if enc == "utf-16" and "\x00" in text:
                        continue
                    break
                except UnicodeDecodeError:
                    continue
        else:
            text = data
        rows, delim = _rows_from_text(text)
        meta["format"] = "text"
        meta["delimiter"] = delim
    rows = _strip_trailing(rows)

    # first block of at least 5 numeric rows
    start = None
    for i in range(len(rows)):
        if _is_numeric_row(rows[i]) and all(_is_numeric_row(rows[j]) for j in range(i, min(i + 5, len(rows)))):
            start = i
            break
    if start is None:
        raise ValueError("No block of numeric data was found in this file.")
    width = max(len(rows[j]) for j in range(start, min(start + 50, len(rows))))

    # header and units rows: the nearest non-empty, non-numeric rows above
    above = [k for k in range(start - 1, -1, -1) if any(str(c).strip() for c in rows[k])]
    header, units = None, None
    if above:
        k = above[0]
        cand = rows[k]
        if len(above) > 1 and _looks_units(cand):
            units = cand
            header = rows[above[1]]
            meta["units_row"] = True
        else:
            header = cand
    if header is None:
        header = [f"Column {i + 1}" for i in range(width)]
        meta["no_header"] = True
    header = [str(h).strip().strip('"').strip() for h in header] + [""] * width
    header = [h if h else f"Column {i + 1}" for i, h in enumerate(header[:width])]
    units = ([str(u).strip().strip('"').strip() for u in units] + [""] * width)[:width] if units else [""] * width
    meta["metadata_lines"] = int(max(0, (above[-1] if above else start) - 0)) if above else 0
    meta["header_line"] = int(above[1] if meta.get("units_row") else (above[0] if above else -1)) + 1

    data_rows = []
    for r in rows[start:]:
        vals = [_num(x) for x in (list(r) + [""] * width)[:width]]
        if sum(v is not None for v in vals) < max(2, int(0.8 * width)):
            if data_rows:
                # allow a few junk rows inside data, stop on a footer block
                continue
            continue
        data_rows.append([np.nan if v is None else v for v in vals])
    arr = np.array(data_rows, float)
    # drop all-NaN columns
    keep = [i for i in range(arr.shape[1]) if np.isfinite(arr[:, i]).any()]
    arr = arr[:, keep]
    header = [header[i] for i in keep]
    units = [units[i] for i in keep]
    return header, units, arr, meta


def _looks_units(r):
    txt = " ".join(str(c) for c in r).lower()
    if not txt.strip():
        return False
    toks = [str(c).strip().strip("()[]").lower() for c in r if str(c).strip()]
    known = set(LOAD_UNITS) | set(DISP_UNITS) | set(TIME_UNITS) | {"sec", "inch", "inches", "mm/min", "µm", "μm", "pt", "-"}
    return sum(t in known for t in toks) >= max(1, len(toks) // 2)


def _unit_from_text(s):
    s = s.lower()
    m = re.search(r"[\(\[]\s*([a-zµμ/]+)\s*[\)\]]", s)
    tok = m.group(1) if m else s.strip()
    tok = tok.replace("µ", "u").replace("μ", "u")
    alias = {"sec": "s", "secs": "s", "seconds": "s", "second": "s", "msec": "ms", "inch": "in", "inches": "in",
             "lbs": "lbf", "lb": "lbf", "kips": "kip", "kilonewton": "kn", "newton": "n", "micron": "um", "microns": "um"}
    tok = alias.get(tok, tok)
    for table, kind in ((LOAD_UNITS, "load"), (DISP_UNITS, "disp"), (TIME_UNITS, "time")):
        if tok in table:
            return tok, kind
    # words inside the name
    for word, kind in (("kn", "load"), ("lbf", "load"), ("kip", "load"), ("mm", "disp"), ("inch", "disp")):
        if re.search(r"\b" + word + r"\b", s):
            return ({"inch": "in"}.get(word, word)), kind
    return None, None


def guess_columns(header, units, arr):
    """Guess role and unit for every column."""
    cols = []
    for i, h in enumerate(header):
        name = h.lower()
        u, ukind = _unit_from_text(units[i]) if units[i] else (None, None)
        if u is None:
            u, ukind = _unit_from_text(h)
        col = arr[:, i]
        fin = col[np.isfinite(col)]
        info = {"index": i, "name": h, "unit_text": units[i], "first": [float(x) for x in fin[:3]],
                "min": float(fin.min()) if len(fin) else None, "max": float(fin.max()) if len(fin) else None}
        score = {}
        if re.search(r"\b(point|pt|index|count|sample|step|cycle|segment)s?\b", name):
            score["ignore"] = 5
        if re.search(r"time|\bsec\b|elapsed", name) or ukind == "time":
            score["time"] = 6
        if re.search(r"load|force", name) or ukind == "load":
            score["load"] = 6 + (1 if "top" in name else 0) + (1 if "load" in name else 0)
        if re.search(r"cmod|crack.?mouth|\bcod\b|clip", name):
            score["cmod"] = 8
        if re.search(r"lld|load.?line", name):
            score["lld"] = 9
        elif re.search(r"lvdt", name):
            score["lld"] = 7
        elif re.search(r"disp|deform|extens|position|stroke|actuator|\bram\b|crosshead", name) or ukind == "disp":
            score["lld"] = 5 - (1 if re.search(r"position|stroke|actuator|ram|crosshead", name) else 0)
        if re.search(r"temp", name):
            score = {"ignore": 9}
        info["scores"] = score
        info["unit"] = u
        info["unit_source"] = "header" if u else None
        cols.append(info)

    # time column fallback: first monotonic column with steady steps
    if not any("time" in c["scores"] for c in cols):
        for c in cols:
            col = arr[:, c["index"]]
            d = np.diff(col[np.isfinite(col)])
            if len(d) > 5 and np.mean(d > 0) > 0.95 and np.std(d) < 0.2 * abs(np.mean(d)) and "ignore" not in c["scores"]:
                if not (c["first"] and float(c["first"][0]).is_integer() and abs(np.mean(d) - 1) < 1e-9):
                    c["scores"]["time"] = 3
                    break

    taken = set()
    def pick(role, k=1):
        best = sorted([c for c in cols if role in c["scores"] and c["index"] not in taken], key=lambda c: -c["scores"][role])
        return best[:k]
    roles = {}
    for role in ["time", "load", "cmod", "lld"]:
        got = pick(role, 2 if role == "lld" else 1)
        if got:
            roles[role] = got[0]["index"]
            taken.add(got[0]["index"])
            if role == "lld" and len(got) > 1 and got[1]["scores"]["lld"] >= 5 and re.search(r"lld|lvdt", got[1]["name"].lower()) and re.search(r"lld|lvdt", got[0]["name"].lower()):
                roles["lld2"] = got[1]["index"]
                taken.add(got[1]["index"])
    for c in cols:
        c["role"] = next((r for r, i in roles.items() if i == c["index"]), "ignore")
        # unit guess from magnitude when the header does not say
        if c["unit"] is None and c["role"] != "ignore":
            c["unit"], c["unit_source"] = _unit_from_values(c["role"], arr[:, c["index"]])
    notes = []
    loads = [c for c in cols if "load" in c["scores"]]
    if len(loads) > 1:
        notes.append("More than one load column. Pick the load cell you used, or set the other one as Load 2 to average them.")
    lds = [c for c in cols if "lld" in c["scores"]]
    if len(lds) > 1:
        notes.append("More than one displacement column. Pick the one that is LLD.")
    return cols, roles, notes


def _unit_from_values(role, col):
    fin = np.abs(col[np.isfinite(col)])
    if not len(fin):
        return None, "unknown"
    mx = float(np.max(fin))
    if role == "load":
        if mx > 200:
            return "n", "guess"
        return "kn", "guess"
    if role in ("lld", "lld2", "cmod"):
        if mx > 200:
            return "um", "guess"
        return "mm", "guess"
    if role == "time":
        d = np.diff(col[np.isfinite(col)])
        d = d[d > 0]
        if len(d) and np.median(d) >= 5:
            return "ms", "guess"
        return "s", "guess"
    return None, "unknown"


def time_segment(t):
    """Index where the last time reset ends (0 if none)."""
    t = np.asarray(t, float)
    d = np.diff(t)
    resets = np.where(d < 0)[0]
    if len(resets):
        return int(resets[-1] + 1)
    return 0


def signature(header):
    return "|".join(h.lower() for h in header)
