"""JSON entry point for the page. The worker calls handle_json(path, body).

Files are read once and kept in memory here, in the browser tab. Nothing
is sent anywhere.
"""
import base64
import json
import math
import traceback

import numpy as np

import core
import parse
import specs
from methods import ANALYZE

FILES = {}   # id -> {"name", "header", "units", "arr", "meta"}
RUNS = {}    # run id -> run payload for export
_seq = [0]


def _id(prefix):
    _seq[0] += 1
    return f"{prefix}{_seq[0]}"


# ------------------------------------------------------------------ helpers
def _record(fid, roles, units, test):
    f = FILES.get(fid)
    if f is None:
        raise ValueError("This file is no longer loaded. Add it again.")
    arr = f["arr"]
    spec = specs.TESTS[test]

    def col(role):
        i = roles.get(role)
        if i is None or i == "" or i < 0:
            return None
        return arr[:, int(i)].astype(float)

    seg_note = None
    t = col("time")
    start = 0
    if t is not None:
        t = t * parse.TIME_UNITS[units.get("time") or "s"]
        start = parse.time_segment(t)
        if start:
            seg_note = "After time reset"
    P = col("load")
    if P is None:
        raise ValueError("No load column is mapped.")
    P = P * parse.LOAD_UNITS[units.get("load") or "kn"]
    P2 = col("load2")
    if P2 is not None:  # two load cells: use their average
        P = 0.5 * (P + P2 * parse.LOAD_UNITS[units.get("load2") or units.get("load") or "kn"])
    u = col("lld")
    if u is not None:
        u = u * parse.DISP_UNITS[units.get("lld") or "mm"]
        u2 = col("lld2")
        if u2 is not None:
            u = 0.5 * (u + u2 * parse.DISP_UNITS[units.get("lld2") or units.get("lld") or "mm"])
    cm = col("cmod")
    if cm is not None:
        cm = cm * parse.DISP_UNITS[units.get("cmod") or "mm"]
    sl = slice(start, None)
    n = len(P)
    if t is None:
        t = np.arange(n, dtype=float)
        seg_note = "No time column"
    P, u, cm, flipped = _fix_signs(P, u, cm, sl)
    segment = seg_note or "Whole file"
    if flipped:
        segment += " · sign flipped: " + ", ".join("load" if x == "Load" else x for x in flipped)
    rec = {"t": t[sl], "P": P[sl], "u": None if u is None else u[sl], "cmod": None if cm is None else cm[sl],
           "segment": segment, "has_time": roles.get("time") not in (None, "", -1), "flipped": flipped}
    missing = [r for r in spec["needs"] if r != "lld2" and (
        (r == "time" and not rec["has_time"]) or (r == "lld" and rec["u"] is None) or (r == "cmod" and rec["cmod"] is None))]
    if test == "dct" and rec["u"] is None:
        rec["u"] = rec["cmod"]
    if rec["u"] is None and test != "idt":
        raise ValueError("No LLD column is mapped.")
    rec["missing"] = missing
    return rec


def _flip_text(flipped):
    names = flipped[0] if len(flipped) == 1 else ", ".join(flipped[:-1]) + " and " + flipped[-1]
    return f"{names} sign flipped" if len(flipped) == 1 else f"{names} signs flipped"


def _fix_signs(P, u, cm, sl):
    """Some frames record tension as negative load, or displacement that grows in the negative direction.
    Load is flipped when its largest reading is negative. Each displacement channel is flipped when it
    moves in the negative direction between the start of the test and the load peak. Offsets do not matter."""
    flipped = []
    Ps = P[sl]
    fin = Ps[np.isfinite(Ps)]
    if fin.size and fin.min() < 0 and -fin.min() > max(fin.max(), 0.0):
        P = -P
        flipped.append("Load")
        Ps = P[sl]
    if not np.isfinite(Ps).any():
        return P, u, cm, flipped
    ip = int(np.nanargmax(Ps))

    def fix(x, name):
        if x is None:
            return x
        xs = x[sl]
        k = max(1, min(20, len(xs) // 50))
        d = xs[ip] - np.nanmedian(xs[:k])
        if np.isfinite(d) and d < 0:
            flipped.append(name)
            return -x
        return x
    u = fix(u, "LLD")
    cm = fix(cm, "CMOD")
    return P, u, cm, flipped


def _rate(test, rec, pr, res=None):
    spec = specs.TESTS[test]
    if not rec["has_time"]:
        return {"value": None, "ok": None, "text": "No time column"}
    if test == "dct" and res is not None:
        v = res.get("rate_mm_s")
    else:
        if spec["control"] == "cmod":
            x = pr["extra"].get("cmod") if pr.get("extra") else None
            if x is None:
                return {"value": None, "ok": None, "text": "No CMOD column"}
        else:
            x = pr["u"]
        if x is None or not np.isfinite(x).all():
            return {"value": None, "ok": None, "text": "No LLD column"}
        v, _ = core.rate_check(pr["t"], x, pr["P"], pr["ip"])
    if v is None or not math.isfinite(v):
        return {"value": None, "ok": None, "text": "Could not fit"}
    if spec["rate_unit"] == "mm/min":
        v *= 60
    ok = abs(v - spec["rate"]) <= spec["rate_tol"] + 1e-12
    return {"value": v, "ok": bool(ok), "unit": spec["rate_unit"]}


def _hz(test, rec):
    spec = specs.TESTS[test]
    if not rec["has_time"]:
        return {"value": None, "ok": None}
    hz = core.sampling_hz(rec["t"])
    return {"value": hz, "ok": bool(hz >= spec["min_hz"] * 0.98), "min": spec["min_hz"]}


def _dims(test, dims):
    spec = specs.TESTS[test]
    bad = []
    for d in spec["dims"]:
        v = dims.get(d["key"])
        if d.get("derived") or v is None:
            continue
        if "lo" in d and not (d["lo"] <= v <= d["hi"]):
            bad.append(f"{d['label']} {v:g} mm is outside {d['lo']:g} to {d['hi']:g} mm")
    return {"ok": not bad, "text": "; ".join(bad)}


def _clean_dims(test, dims):
    spec = specs.TESTS[test]
    out = {}
    for d in spec["dims"]:
        v = dims.get(d["key"])
        try:
            v = float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            v = None
        if v is None and d.get("default") is not None:
            v = float(d["default"])
        out[d["key"]] = v
    if "lig" in out and out["lig"] is None and out.get("D") and out.get("a") is not None:
        out["lig"] = out["D"] / 2 - out["a"]
    for k in ("av",):
        if dims.get(k) not in (None, ""):
            try:
                out[k] = float(dims[k])
            except (TypeError, ValueError):
                pass
    return out


def _settings(test, st):
    spec = specs.TESTS[test]
    s = {"mode": spec["mode"], "start_load": spec["start_load"], "end_load": spec["end_load"],
         "seating": spec["seating"], "tare": False, "poisson": "fixed", "mu": 0.35, "mix": "design", "window": 0.15}
    for k, v in (st or {}).items():
        if v is not None and v != "":
            s[k] = v
    s["start_load"] = float(s["start_load"])
    s["end_load"] = float(s["end_load"])
    s["deviations"] = []
    if s["mode"] != spec["mode"]:
        s["deviations"].append(f"Data mode set to {s['mode']} (default {spec['mode']}).")
    if abs(s["start_load"] - spec["start_load"]) > 1e-9 or abs(s["end_load"] - spec["end_load"]) > 1e-9:
        s["deviations"].append(f"Trim set to {s['start_load']:g} / {s['end_load']:g} kN (default {spec['start_load']:g} / {spec['end_load']:g}).")
    if bool(s["seating"]) != bool(spec["seating"]) and test in ("ifit", "scb"):
        s["deviations"].append("Seating energy " + ("added." if s["seating"] else "left out."))
    if s["tare"]:
        s["deviations"].append("Load tare on: first load reading subtracted.")
    return s


def _analyze(test, f, st):
    rec = _record(f["id"], f["roles"], f.get("units", {}), test)
    dims = _clean_dims(test, f.get("dims", {}))
    res = ANALYZE[test](rec, dims, st)
    pr = res["pr"]
    out = res["outputs"]
    rate = _rate(test, rec, pr, res)
    out["rate"] = rate["value"] if rate["value"] is not None else float("nan")
    hz = _hz(test, rec)
    out["hz"] = hz["value"] if hz["value"] is not None else float("nan")
    checks = {"rate": rate, "hz": hz, "dims": _dims(test, dims)}
    fitok = None
    for k in ("r2_post",):
        if k in out and out[k] == out[k]:
            fitok = out[k] >= 0.997
    if "r2_pre" in out and out["r2_pre"] == out["r2_pre"]:
        fitok = (fitok is not False) and out["r2_pre"] >= 0.997
    checks["fit"] = {"ok": fitok}
    warn = list(res["warnings"])
    if rec.get("flipped"):
        res["notes"] = [_flip_text(rec["flipped"]) + ": the file records them as negative."] + list(res.get("notes") or [])
    if rec["missing"]:
        warn.append("Missing column: " + ", ".join(rec["missing"]) + ".")
    if not rec["has_time"] and "time" not in rec["missing"]:
        # time is optional here: results use load and displacement only
        warn.append("No time column. Loading rate and sampling were not checked.")
        if "t_peak" in out:
            out["t_peak"] = float("nan")
    if rate["ok"] is False:
        sp = specs.TESTS[test]
        warn.append(f"Loading rate {rate['value']:.4g} {sp['rate_unit']} is outside {specs.target(sp)}.")
    if hz["ok"] is False:
        warn.append(f"Sampling {hz['value']:.1f} Hz is below the {hz['min']} Hz minimum.")
    if not checks["dims"]["ok"]:
        warn.append(checks["dims"]["text"] + ".")
    if pr.get("info") and not pr["info"].get("start_found", True):
        warn.append("Load never reached the start trim. The record starts at the first point.")
    res.update({"checks": checks, "warnings": warn, "dims": dims, "segment": rec["segment"], "rec": rec})
    return res


# ------------------------------------------------------------------ routes
def r_tests(body):
    return specs.public()


def r_parse(body):
    out = []
    for f in body.get("files", []):
        name = f.get("name", "file")
        try:
            data = base64.b64decode(f["b64"]) if "b64" in f else f.get("text", "")
            header, units, arr, meta = parse.read_table(name, data)
            cols, roles, notes = parse.guess_columns(header, units, arr)
            fid = _id("f")
            FILES[fid] = {"name": name, "header": header, "units": units, "arr": arr, "meta": meta}
            tcol = roles.get("time")
            reset = bool(tcol is not None and parse.time_segment(arr[:, tcol]) > 0)
            out.append({"id": fid, "name": name, "rows": int(arr.shape[0]), "header": header, "cols": cols,
                        "roles": roles, "notes": notes, "signature": parse.signature(header), "meta": meta,
                        "time_reset": reset})
        except Exception as e:
            out.append({"name": name, "error": str(e)})
    return {"files": out}


def r_forget(body):
    for fid in body.get("ids", []):
        FILES.pop(fid, None)
    for rid in body.get("runs", []):
        RUNS.pop(rid, None)
    return {"ok": True}


def r_check(body):
    """Loading checks on the upload screen: rate, sampling, plot."""
    test = body["test"]
    st = _settings(test, body.get("settings"))
    out = []
    for f in body.get("files", []):
        try:
            rec = _record(f["id"], f["roles"], f.get("units", {}), test)
            x = rec["u"] if rec["u"] is not None else rec["cmod"]
            if test in ("scb", "dct") and rec["cmod"] is not None and test == "dct":
                x = rec["cmod"]
            extra = {"cmod": rec["cmod"]} if rec["cmod"] is not None else None
            if x is None:
                x = np.arange(len(rec["P"]), dtype=float)
            pr = core.prepare(rec["t"], rec["P"], x, st["start_load"], st["end_load"], st["tare"], extra=extra)
            rate = _rate(test, rec, pr)
            if test == "dct" and rec["cmod"] is not None and rec["has_time"]:
                a1, _, _ = core.linfit(pr["t"], pr["u"])
                rate = {"value": a1, "ok": bool(abs(a1 - 0.017) <= 0.017 * 0.05), "unit": "mm/s"}
            full = pr["full"]
            out.append({"id": f["id"], "rate": rate, "hz": _hz(test, rec), "segment": rec["segment"],
                        "missing": rec["missing"], "pmax": float(pr["P"].max()),
                        "plot": core.decimate(full["u"], full["P"], 300),
                        "trim": [float(pr["u"][0]), float(pr["u"][-1])]})
        except Exception as e:
            out.append({"id": f.get("id"), "error": str(e)})
    return {"files": out}


def r_preview(body):
    test = body["test"]
    st = _settings(test, body.get("settings"))
    res = _analyze(test, body["file"], st)
    return {"plot": res["plot"], "outputs": res["outputs"], "warnings": res["warnings"], "notes": res["notes"],
            "checks": res["checks"]}


def r_run(body):
    test = body["test"]
    st = _settings(test, body.get("settings"))
    reps = []
    stored = []
    for f in body.get("files", []):
        label = f.get("label") or FILES.get(f["id"], {}).get("name", f["id"])
        try:
            res = _analyze(test, f, st)
            reps.append({"id": f["id"], "label": label, "file": FILES[f["id"]]["name"], "outputs": res["outputs"],
                         "checks": res["checks"], "warnings": res["warnings"], "notes": res["notes"],
                         "plot": res["plot"], "dims": res["dims"], "segment": res["segment"]})
            stored.append({"label": label, "file": FILES[f["id"]]["name"], "res": res, "mapping": {
                "roles": f["roles"], "units": f.get("units", {}),
                "columns": {r: FILES[f["id"]]["header"][int(i)] for r, i in f["roles"].items() if i not in (None, "", -1)}},
                "raw_dims": f.get("dims", {})})
        except Exception as e:
            reps.append({"id": f["id"], "label": label, "file": FILES.get(f["id"], {}).get("name"), "error": str(e)})
    rid = _id("run")
    # keep earlier batches' runs so they can still be exported; drop the run this one replaces
    for old in body.get("drop", []):
        RUNS.pop(old, None)
    RUNS[rid] = {"test": test, "settings": st, "reps": stored}
    return {"run": rid, "test": test, "settings": st, "replicates": reps}


def r_export(body):
    import report  # needs openpyxl and matplotlib, loaded on first export
    run = RUNS.get(body.get("run"))
    if run is None:
        raise ValueError("Run the analysis again before exporting.")
    data, name = report.build_zip(run, body)
    return {"name": name, "b64": base64.b64encode(data).decode("ascii")}


ROUTES = {"tests": r_tests, "parse": r_parse, "forget": r_forget, "check": r_check, "preview": r_preview,
          "run": r_run, "export": r_export}


def handle_json(path, body):
    try:
        b = json.loads(body) if body else {}
        fn = ROUTES.get(path.strip("/"))
        if fn is None:
            raise ValueError(f"Unknown route {path}")
        return json.dumps({"ok": True, "data": core.clean(fn(b))})
    except Exception as e:
        tb = traceback.format_exc(limit=3)
        return json.dumps({"ok": False, "error": str(e), "trace": tb})
