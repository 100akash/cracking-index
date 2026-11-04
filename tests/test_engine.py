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
    fs = sorted(glob.glob(os.path.join(ROOT, "examples", f"{test}_{mix}_*.csv")))
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
    dct = parse("dct")[0]
    load = [c for c in dct["cols"] if c["role"] == "load"][0]
    assert load["unit"] == "n" and load["unit_source"] == "header"


def test_all_tests_run_and_pass_checks():
    for t in TESTS:
        F = parse(t)
        r = call("run", {"test": t, "settings": {}, "files": payload(F)})
        for rep in r["replicates"]:
            assert "error" not in rep, (t, rep.get("error"))
            assert rep["checks"]["rate"]["ok"] is True, (t, rep["checks"]["rate"])
            assert rep["checks"]["hz"]["ok"] is True, (t, rep["checks"]["hz"])
            idx = routes.specs.TESTS[t]["index"]
            assert rep["outputs"][idx] is not None and math.isfinite(rep["outputs"][idx]), (t, idx)


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
