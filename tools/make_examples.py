"""Make the synthetic example files in examples/.

These are made-up curves for a made-up "Mix A". They are not test data.
Run: python tools/make_examples.py
"""
import os

import numpy as np

OUT = os.path.join(os.path.dirname(__file__), "..", "examples")
rng = np.random.default_rng(7)


def shape(x, bpre, bpost):
    x = np.maximum(x, 1e-9)
    g = x * np.exp(1 - x)
    return g ** np.where(x <= 1, bpre, bpost)


def daq(path, cols, names, units, title):
    """DAQ-style export: metadata lines, blank lines, quoted header, units row."""
    with open(path, "w", newline="") as f:
        f.write(f"Example project,{title}\n")
        f.write("Synthetic data,made-up Mix A\n")
        f.write("Station,Example frame\n")
        f.write("Note,Not a real test\n\n\n")
        f.write(",".join(f'"{n}"' for n in names) + "\n")
        f.write(",".join(f'"{u}"' for u in units) + "\n")
        for row in zip(*cols):
            f.write(",".join(f"{v:.6g}" for v in row) + "\n")


def simple(path, cols, names):
    with open(path, "w", newline="") as f:
        f.write(",".join(names) + ",\n")
        for i, row in enumerate(zip(*cols)):
            f.write(",".join(f"{v:.6g}" for v in row) + ",\n")


def lld_test(P, u0, bpre, bpost, rate_mm_min, hz, stop, tmax, noise=0.012, contact=0.02, hold=1.0):
    """Displacement-controlled curve. Adds a contact hold with a time reset."""
    v = rate_mm_min / 60
    t = np.arange(0, tmax, 1 / hz)
    u = v * t
    load = P * shape(u / u0, bpre, bpost) + rng.normal(0, noise, len(t))
    ip = int(np.argmax(load))
    below = np.where(load[ip:] < stop)[0]
    end = ip + int(below[0]) + 4 if len(below) else len(t)
    return t[:end], load[:end], u[:end]


def mixA_service():
    reps = {  # peak kN, u0 mm, bpre, bpost, rate, Hz
        "ifit": [(4.05, 1.08, 1.2, 1.8, 50.2, 50), (5.20, 0.82, 1.1, 2.6, 49.8, 50), (3.90, 1.15, 1.25, 1.7, 50.4, 40)],
        "idealct": [(9.1, 1.55, 1.15, 2.2, 50.3, 50), (8.7, 1.62, 1.2, 2.0, 49.9, 50), (9.5, 1.50, 1.1, 2.4, 50.6, 50)],
        "donut": [(6.2, 1.05, 1.2, 2.1, 50.1, 60), (6.5, 1.00, 1.15, 2.3, 49.7, 60), (5.9, 1.10, 1.25, 1.95, 50.5, 60)],
    }
    for test, rr in reps.items():
        for k, (P, u0, a, b, rate, hz) in enumerate(rr, 1):
            t, load, u = lld_test(P, u0, a, b, rate, hz, 0.1, 14)
            name = os.path.join(OUT, f"{test}_MixA_R{k}.csv")
            if k < 3:
                # DAQ format with a contact hold and a time reset
                th = np.arange(0, 1, 1 / hz)
                hold_load = 0.1 + rng.normal(0, 0.003, len(th))
                tt = np.concatenate([th, t + 1 / hz])
                ll = np.concatenate([hold_load, load + 0.0])
                uu = np.concatenate([np.zeros(len(th)), u])
                tt[len(th):] = t + 1 / hz  # time restarts after the hold
                act = uu * 1.03 + 18.4 + 0.04 * ll
                daq(name, [tt, ll, ll + rng.normal(0, 0.004, len(ll)), uu, act],
                    ["Time", "Load cell 1", "Load cell 2", "LVDT 1", "Actuator"], ["s", "kN", "kN", "mm", "mm"],
                    f"{test.upper()} example")
            else:
                simple(name, [np.arange(1, len(t) + 1), t, load, u, u * 1.03 + 0.2],
                       ["Point", "Time", "Load", "Displacement Channel 1", "Displacement Channel 2"])


def mixA_scb():
    """T 394: stroke ramp to 1 kN, then CMOD-control at 0.0005 mm/s."""
    for k, (P, c0) in enumerate([(3.6, 0.100), (3.4, 0.110), (3.8, 0.095)], 1):
        hz = 10
        t1 = np.arange(0, 1500, 1 / hz)
        cm = 0.0005 * t1
        x = np.maximum(cm - c0, 0) / (1.2 * c0)
        load = np.where(cm <= c0, 1.0 + (P - 1.0) * shape(cm / c0, 1.1, 1.0), P / (1 + x * x))
        load = load + rng.normal(0, 0.008, len(t1))
        ip = int(np.argmax(load))
        below = np.where(load[ip:] < 0.5)[0]
        end = ip + int(below[0]) + 3 if len(below) else len(t1)
        t1, load, cm = t1[:end], load[:end], cm[:end]
        lld = 1.0 * cm + load / 60
        ramp_t = np.arange(-40, 0, 1 / hz)
        ramp_load = np.linspace(0.6, 1.0, len(ramp_t), endpoint=False)
        ramp_lld = np.linspace(0, 1.0 / 60, len(ramp_t), endpoint=False)
        tt = np.concatenate([ramp_t, t1]) + 40
        ll = np.concatenate([ramp_load, load])
        base = np.concatenate([ramp_lld, lld])
        l1 = base * 0.98 + rng.normal(0, 0.0004, len(tt))
        l2 = base * 1.02 + rng.normal(0, 0.0004, len(tt))
        cc = np.concatenate([np.zeros(len(ramp_t)), cm])
        daq(os.path.join(OUT, f"scb_MixA_R{k}.csv"), [tt, ll, cc, l1, l2],
            ["Time", "Load", "CMOD", "LLD left", "LLD right"], ["s", "kN", "mm", "mm", "mm"], "SCB example")


def mixA_sltscb():
    for k, (P, u0, a) in enumerate([(7.4, 0.42, 1.08), (7.0, 0.45, 1.1), (7.8, 0.40, 1.06)], 1):
        hz = 50
        v = 0.15 / 60
        t = np.arange(0, 400, 1 / hz)
        u = v * t
        load = 0.5 + (P - 0.5) * shape(u / u0, a, 6.0) + rng.normal(0, 0.01, len(t))
        ip = int(np.argmax(load))
        drop = np.where(load[ip:] < 0.7 * P)[0]
        end = ip + int(drop[0]) if len(drop) else len(t)
        simple(os.path.join(OUT, f"sltscb_MixA_R{k}.csv"), [t[:end], load[:end], u[:end]],
               ["Time (s)", "Load (kN)", "LLD (mm)"])


def mixA_dct():
    for k, (P, c0, b) in enumerate([(3.1, 0.17, 1.7), (2.9, 0.18, 1.6), (3.3, 0.16, 1.8)], 1):
        hz = 25
        t = np.arange(0, 200, 1 / hz)
        cm = 0.0172 * t + rng.normal(0, 0.0005, len(t))
        load = P * shape(np.maximum(cm, 1e-9) / c0, 1.15, b) + rng.normal(0, 0.006, len(t))
        ip = int(np.argmax(load))
        below = np.where(load[ip:] < 0.1)[0]
        end = ip + int(below[0]) + 2 if len(below) else len(t)
        simple(os.path.join(OUT, f"dct_MixA_R{k}.csv"), [t[:end], load[:end] * 1000, cm[:end]],
               ["Time (s)", "Load (N)", "CMOD (mm)"])


def mixA_idt():
    for k, (P, u0) in enumerate([(14.2, 1.30), (13.6, 1.36), (14.9, 1.25)], 1):
        t, load, u = lld_test(P, u0, 1.15, 2.5, 12.6, 20, 0.5 * P, 30, noise=0.03)
        simple(os.path.join(OUT, f"idt_MixA_R{k}.csv"), [t, load, u], ["Time (s)", "Load (kN)", "Ram (mm)"])


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    mixA_service()
    mixA_scb()
    mixA_sltscb()
    mixA_dct()
    mixA_idt()
    print("written:", sorted(os.listdir(OUT)))
