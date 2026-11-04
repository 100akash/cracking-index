"""Engine checks on the synthetic example files. Run: python -m pytest tests"""
import base64
import glob
import io
import json
import math
import os
import sys
import zipfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "engine"))
os.environ.setdefault("MPLBACKEND", "Agg")
import core  # noqa: E402
import routes  # noqa: E402

TESTS = ["ifit", "idealct", "donut", "scb", "sltscb", "dct", "idt"]


def call(path, body):
    r = json.loads(routes.handle_json(path, json.dumps(body)))
    assert r["ok"], r.get("error")
    return r["data"]


def parse(test, mix="*"):
    fs = sorted(glob.glob(os.path.join(ROOT, "examples", f"{test}_{mix}_*.*")))
    assert fs, "run tools/make_examples.py first"
    return call("parse", {"files": [{"name": os.path.basename(f), "b64": base64.b64encode(open(f, "rb").read()).decode()} for f in fs]})["files"]


def payload(F):
    return [{"id": f["id"], "roles": f["roles"], "units": {c["role"]: c["unit"] for c in f["cols"] if c["role"] != "ignore"},
             "dims": {}, "label": f"R{i + 1}"} for i, f in enumerate(F)]


def test_trapz_and_stats():
    x = np.linspace(0, 1, 101)
    assert abs(core.trapz(x, x) - 0.5) < 1e-12
    s = core.stats([1, 2, 3])
    assert s["n"] == 3 and abs(s["mean"] - 2) < 1e-12 and abs(s["sd"] - 1) < 1e-12


def test_parse_guesses_roles_and_units():
    F = parse("ifit")
    a = F[0]
    assert a["time_reset"] and a["meta"]["units_row"]
    assert set(a["roles"]) >= {"time", "load", "lld"}
    dct = parse("dct", "MixB")[0]  # tab-separated text with a units row and an extra temperature column
    assert dct["meta"]["delimiter"] == "tab" and dct["meta"]["units_row"]
    roles = {c["role"] for c in dct["cols"]}
    assert {"time", "load", "cmod"} <= roles
    load = [c for c in dct["cols"] if c["role"] == "load"][0]
    assert load["unit"] == "kn" and load["unit_source"] == "header"


def test_all_tests_run_and_pass_checks():
    for t in TESTS:
        F = parse(t)
        r = call("run", {"test": t, "settings": {}, "files": payload(F)})
        for rep in r["replicates"]:
            assert "error" not in rep, (t, rep.get("error"))
            if t in ("idealct", "dct"):
                continue  # lab examples with known warnings (low sampling, no time column); tested below
            assert rep["checks"]["rate"]["ok"] is True, (t, rep["checks"]["rate"])
            assert rep["checks"]["hz"]["ok"] is True, (t, rep["checks"]["hz"])
            idx = routes.specs.TESTS[t]["index"]
            assert rep["outputs"][idx] is not None and math.isfinite(rep["outputs"][idx]), (t, idx)


def test_idealct_examples_and_missing_time():
    # Mix A: DAQ export sampled at 30 Hz (below the D8225 minimum). Mix B: processed export with no time column.
    want = {"MixA": [120.0, 81.4, 106.0, 116.7], "MixB": [198.6, 201.9, 130.5, 151.4]}
    for mix, ref in want.items():
        F = parse("idealct", mix)
        r = call("run", {"test": "idealct", "settings": {}, "files": payload(F)})
        ct = [x["outputs"]["CT"] for x in r["replicates"]]
        assert all(abs(a - b) < 0.5 for a, b in zip(ct, ref)), (mix, ct)
        for rep in r["replicates"]:
            if mix == "MixA":
                assert rep["checks"]["rate"]["ok"] is True and rep["checks"]["hz"]["ok"] is False
            else:
                assert rep["checks"]["rate"]["ok"] is None and rep["checks"]["hz"]["ok"] is None
                assert any("No time column" in w for w in rep["warnings"])
                assert not any("Missing column" in w for w in rep["warnings"])
    # DCT: time is optional; raw uses the measured CMOD, fitted uses CMOD vs time
    assert "time" not in routes.specs.TESTS["dct"]["needs"] and "time" in routes.specs.TESTS["dct"]["optional"]


def test_dct_examples_and_sign_flip():
    # Mix A records load and CMOD as negative: the tool flips them. Mix B is sampled at 19 Hz.
    want = {"MixA": [392.6, 558.0, 508.6], "MixB": [833.6, 573.6, 853.8, 628.5]}
    for mix, ref in want.items():
        F = parse("dct", mix)
        r = call("run", {"test": "dct", "settings": {}, "files": payload(F)})
        gf = [x["outputs"]["Gf"] for x in r["replicates"]]
        assert all(abs(a - b) < 1.0 for a, b in zip(gf, ref)), (mix, gf)
        for rep in r["replicates"]:
            assert rep["outputs"]["Pmax"] > 2.5
            if mix == "MixA":
                assert "sign flipped" in rep["segment"] and rep["checks"]["rate"]["ok"] is True and rep["checks"]["hz"]["ok"] is True
            else:
                assert "sign flipped" not in rep["segment"] and rep["checks"]["hz"]["ok"] is False


def test_dct_raw_and_fitted_cmod():
    F = parse("dct")
    raw = call("run", {"test": "dct", "settings": {}, "files": payload(F)})
    fit = call("run", {"test": "dct", "settings": {"mode": "fitted"}, "files": payload(F)})
    for a, b in zip(raw["replicates"], fit["replicates"]):
        ga, gb = a["outputs"]["Gf"], b["outputs"]["Gf"]
        assert math.isfinite(ga) and math.isfinite(gb) and ga != gb
        assert abs(ga - gb) / gb < 0.1  # constant CMOD rate: the fit stays close to the measured CMOD
    assert raw["settings"]["mode"] == "raw" and fit["settings"]["mode"] == "fitted"


def test_donut_examples():
    want = {"MixA": [5.94, 6.66, 6.18, 6.50], "MixB": [5.25, 6.40, 5.69, 6.14]}
    for mix, ref in want.items():
        F = parse("donut", mix)
        r = call("run", {"test": "donut", "settings": {}, "files": payload(F)})
        di = [x["outputs"]["DI"] for x in r["replicates"]]
        assert all(abs(a - b) < 0.02 for a, b in zip(di, ref)), (mix, di)


def test_ifit_values_on_example():
    # two anonymized lab sets: Mix A (DAQ export with a units row) and Mix B (processed, no units row)
    want = {"MixA": [9.5, 9.7, 11.2, 10.9], "MixB": [6.3, 6.0, 9.0, 5.0]}
    for mix, ref in want.items():
        F = parse("ifit", mix)
        assert len({f["signature"] for f in F}) == 1
        r = call("run", {"test": "ifit", "settings": {}, "files": payload(F)})
        fi = [x["outputs"]["FI"] for x in r["replicates"]]
        assert all(abs(a - b) < 0.3 for a, b in zip(fi, ref)), (mix, fi)
    o = r["replicates"][0]["outputs"]
    assert abs(o["FI"] - o["Gf"] / o["m_abs"] * 0.01) < 1e-9
    assert o["r2_post"] > 0.997


def test_ifit_slope_matches_known_gaussian():
    # a curve made from one known 4-term Gaussian: the fit should find its slope
    p = [3.0, 1.0, 1.2, 1.5, 2.0, 1.4, 0.4, 3.2, 1.6, 0.05, 4.5, 2.0]
    u = np.linspace(1.0, 5.5, 500)
    P = core.gauss4(u, *p)
    fit = core.fit_post_ifit(u, P)
    ref, _ = core.ifit_inflection(np.array(p), u[0], u[-1])
    assert fit["r2"] > 0.999
    assert abs(fit["inf"]["m"] - ref["m"]) / abs(ref["m"]) < 0.02


def test_export_zip():
    F = parse("ifit")
    r = call("run", {"test": "ifit", "settings": {}, "files": payload(F)})
    e = call("export", {"run": r["run"], "batch": {"project": "Example project", "mix": "Mix A"}, "included": [True, False, True],
                        "reasons": ["", "outlier rule", ""], "options": {}})
    z = zipfile.ZipFile(io.BytesIO(base64.b64decode(e["b64"])))
    names = z.namelist()
    assert any(n.endswith("_summary.pdf") for n in names)
    assert sum(n.endswith(".xlsx") for n in names) == 4
    assert z.read([n for n in names if n.endswith(".pdf")][0])[:4] == b"%PDF"


def test_errors_are_readable():
    r = json.loads(routes.handle_json("parse", json.dumps({"files": [{"name": "x.xls", "b64": ""}]})))
    assert r["ok"] and "not supported" in r["data"]["files"][0]["error"]
    r = json.loads(routes.handle_json("nope", "{}"))
    assert not r["ok"]
