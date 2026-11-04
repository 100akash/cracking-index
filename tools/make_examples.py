"""Make the SCB and IDT strength example files in examples/.

These are synthetic curves, not test data. Each set is back-calculated so the
tool returns the published means of two mixtures from:

  Marasteanu, M., et al. (2007). Investigation of Low Temperature Cracking in
  Asphalt Pavements: National Pooled Fund Study 776. Report MN/RC 2007-43,
  Minnesota Department of Transportation.
  https://rosap.ntl.bts.gov/view/dot/38925

  Mix A = 58-34:M1:4:GR (PG 58-34, granite), -24 C.
  Mix B = 58-34:M1:4:LM (PG 58-34, limestone), -24 C.

SCB (Table 6.4): fracture energy Gf and toughness KIC, mean and CoV.
  Peak load comes from KIC through the tool's KIC equation (25 x 150 mm, 15 mm notch).
  The post-peak width of each curve is solved so the tool's Gf hits the target.
IDT strength (Table 6.6, 12.5 mm/min): mean strength only.
  Peak load = St * pi * t * D / 2 for the tool's default 50 x 150 mm specimen.
  The report gives no CoV for strength, so 5% is assumed.

Assumed, not from the report: the curve shapes, CMOD and LLD at peak, ram
displacement at peak, noise and sampling rates. Three replicates per mix are
spread at mean - SD, mean and mean + SD, so the sample mean and CoV match exactly.

The other tests use anonymized lab records and are not made here.
Run: python tools/make_examples.py
"""
import base64
import json
import math
import os
import sys

import numpy as np

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "examples")
sys.path.insert(0, os.path.join(ROOT, "engine"))
import routes  # noqa: E402

rng = np.random.default_rng(7)
SRC = "Back-calculated from MN/RC 2007-43"

# mean, CoV, and the order of the three replicates (in SDs from the mean)
SCB = {"MixA": {"label": "58-34 granite at -24 C", "KIC": (1.0, 0.040, [0, -1, 1]), "Gf": (549.0, 0.110, [1, -1, 0]), "c0": 0.100, "n": 5, "hz": 10},
       "MixB": {"label": "58-34 limestone at -24 C", "KIC": (0.7, 0.058, [1, 0, -1]), "Gf": (327.8, 0.094, [-1, 1, 0]), "c0": 0.085, "n": 7, "hz": 20}}
IDT = {"MixA": {"label": "58-34 granite at -24 C", "St": (7.40, 0.05, [0, 1, -1]), "u0": 0.80, "n": 4, "w": 0.08, "hz": 50},
       "MixB": {"label": "58-34 limestone at -24 C", "St": (5.06, 0.05, [-1, 0, 1]), "u0": 0.65, "n": 5, "w": 0.05, "hz": 50}}


def rise(x, n):
    """0 to 1 over 0 <= x <= 1: near linear at first, flat at the peak (larger n is more linear)."""
    x = np.clip(x, 0, 1)
    return (x - x ** n / n) / (1 - 1 / n)


def daq(path, cols, names, units, title, note):
    """DAQ-style export: metadata lines, blank lines, quoted header, units row."""
    with open(path, "w", newline="") as f:
        f.write(f"Example project,{title}\n")
        f.write(f"Synthetic data,{note}\n")
        f.write(f"Source,{SRC}\n")
        f.write("Note,Not a real test\n\n\n")
        f.write(",".join(f'"{n}"' for n in names) + "\n")
        f.write(",".join(f'"{u}"' for u in units) + "\n")
        for row in zip(*cols):
            f.write(",".join(f"{v:.6g}" for v in row) + "\n")


def simple(path, cols, names):
    with open(path, "w", newline="") as f:
        f.write(",".join(names) + "\n")
        for row in zip(*cols):
            f.write(",".join(f"{v:.6g}" for v in row) + "\n")


def engine(test, path):
    """Run one file through the tool with default settings and dimensions."""
    b64 = base64.b64encode(open(path, "rb").read()).decode()
    f = json.loads(routes.handle_json("parse", json.dumps({"files": [{"name": os.path.basename(path), "b64": b64}]})))["data"]["files"][0]
    units = {c["role"]: c["unit"] for c in f["cols"] if c["role"] != "ignore"}
    body = {"test": test, "settings": {}, "files": [{"id": f["id"], "roles": f["roles"], "units": units, "dims": {}, "label": "R"}]}
    r = json.loads(routes.handle_json("run", json.dumps(body)))["data"]
    routes.handle_json("forget", json.dumps({"ids": [f["id"]], "runs": [r["run"]]}))
    return r["replicates"][0]["outputs"]


def scb_P_from_KIC(K, t=25.0, D=150.0, a=15.0):
    r = D / 2
    ar = a / r
    Y = 4.782 - 1.219 * ar + 0.063 * math.exp(7.045 * ar)
    sigma0 = K / (Y * math.sqrt(math.pi * a / 1000))  # MPa
    return sigma0 * 2 * (r / 1000) * (t / 1000) * 1000  # kN


def scb_curve(P, c0, k, hz, n):
    """Stroke ramp to 1 kN, then CMOD control at 0.0005 mm/s. Softening P/(1 + x^2)."""
    t1 = np.arange(0, 6000, 1 / hz)
    cm = 0.0005 * t1
    x = np.maximum(cm - c0, 0) / (k * c0)
    load = np.where(cm <= c0, 1.0 + (P - 1.0) * rise(cm / c0, n), P / (1 + x * x))
    load = load + rng.normal(0, 0.004, len(t1))
    ip = int(np.argmax(load))
    below = np.where(load[ip:] < 0.5)[0]
    end = ip + int(below[0]) + 3 if len(below) else len(t1)
    t1, load, cm = t1[:end], load[:end], cm[:end]
    lld = 0.9 * cm + load / 40  # LLD follows CMOD plus an elastic part
    ramp_t = np.arange(-30, 0, 1 / hz)
    ramp_load = np.linspace(0.3, 1.0, len(ramp_t), endpoint=False)
    ramp_lld = np.linspace(0, 1.0 / 40, len(ramp_t), endpoint=False)
    tt = np.concatenate([ramp_t, t1]) + 30
    ll = np.concatenate([ramp_load, load])
    cc = np.concatenate([np.zeros(len(ramp_t)), cm])
    base = np.concatenate([ramp_lld, lld])
    return tt, ll, cc, base


def write_scb(mix, k_rep, P, c0, k, hz, cfg):
    tt, ll, cc, base = scb_curve(P, c0, k, hz, cfg["n"])
    path = os.path.join(OUT, f"scb_{mix}_R{k_rep}.csv")
    if mix == "MixA":
        st = np.random.default_rng(100 + k_rep)
        l1 = base * 0.97 + st.normal(0, 0.0004, len(tt))
        l2 = base * 1.03 + st.normal(0, 0.0004, len(tt))
        daq(path, [tt, ll, cc, l1, l2], ["Time", "Load", "CMOD", "LLD left", "LLD right"], ["s", "kN", "mm", "mm", "mm"],
            "SCB example", cfg["label"])
    else:
        simple(path, [tt, ll * 1000, cc, base + np.random.default_rng(200 + k_rep).normal(0, 0.0004, len(tt))],
               ["Time (s)", "Load (N)", "CMOD (mm)", "LLD (mm)"])
    return path


def make_scb():
    for mix, cfg in SCB.items():
        (Km, Kc, Kz), (Gm, Gc, Gz) = cfg["KIC"], cfg["Gf"]
        for i in range(3):
            K = Km * (1 + Kc * Kz[i])
            G = Gm * (1 + Gc * Gz[i])
            P = scb_P_from_KIC(K)
            seed = rng.bit_generator.state
            out = engine("scb", write_scb(mix, i + 1, P, cfg["c0"], 1.0, cfg["hz"], cfg))
            P = P * K / out["KIC"]  # remove the small bias from noise at the peak
            lo, hi = 0.05, 8.0
            for _ in range(40):  # solve the softening width so the tool's Gf matches
                k = math.sqrt(lo * hi)
                rng.bit_generator.state = seed
                out = engine("scb", write_scb(mix, i + 1, P, cfg["c0"], k, cfg["hz"], cfg))
                if out["Gf"] < G:
                    lo = k
                else:
                    hi = k
                if abs(out["Gf"] - G) < 0.05:
                    break
            print(f"scb {mix} R{i + 1}: Gf {out['Gf']:.1f} (target {G:.1f}), KIC {out['KIC']:.4f} (target {K:.4f}), Pmax {out['Pmax']:.3f} kN")


def idt_curve(P, u0, hz, n, w):
    v = 12.5 / 60
    t = np.arange(0, 20, 1 / hz)
    u = v * t
    post = P * np.exp(-((u - u0) / w) ** 2)  # brittle split after the peak
    load = np.where(u <= u0, P * rise(u / u0, n), post) + rng.normal(0, 0.03, len(t))
    ip = int(np.argmax(load))
    below = np.where(load[ip:] < 0.4 * P)[0]
    end = ip + int(below[0]) + 3 if len(below) else len(t)
    return t[:end], load[:end], u[:end]


def write_idt(mix, k_rep, P, u0, hz, cfg):
    t, load, u = idt_curve(P, u0, hz, cfg["n"], cfg["w"])
    path = os.path.join(OUT, f"idt_{mix}_R{k_rep}.csv")
    if mix == "MixA":
        simple(path, [t, load, u], ["Time (s)", "Load (kN)", "Ram (mm)"])
    else:
        daq(path, [t, load, u + 21.7], ["Time", "Axial force", "Actuator"], ["s", "kN", "mm"], "IDT strength example", cfg["label"])
    return path


def make_idt():
    for mix, cfg in IDT.items():
        Sm, Sc, Sz = cfg["St"]
        for i in range(3):
            St = Sm * (1 + Sc * Sz[i])
            P = St * math.pi * 50.0 * 150.0 / 2 / 1000  # kN, for the default 50 x 150 mm specimen
            seed = rng.bit_generator.state
            out = engine("idt", write_idt(mix, i + 1, P, cfg["u0"], cfg["hz"], cfg))
            P = P * St / out["St"]
            rng.bit_generator.state = seed
            out = engine("idt", write_idt(mix, i + 1, P, cfg["u0"], cfg["hz"], cfg))
            print(f"idt {mix} R{i + 1}: St {out['St']:.4f} MPa (target {St:.4f}), Pmax {out['Pmax']:.2f} kN")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        if f.startswith(("scb_", "idt_")):
            os.remove(os.path.join(OUT, f))
    make_scb()
    make_idt()
