"""Shared numeric tools for the Cracking Test Analyzer.

Units inside the engine: load in kN, displacement in mm, time in s.
Work in kN*mm is the same as J.
"""
import math
import numpy as np

try:
    from scipy.optimize import curve_fit
except Exception:  # scipy is loaded by the worker; keep import errors readable
    curve_fit = None


# ---------------------------------------------------------------- basics
def trapz(y, x):
    """Trapezoid rule (the quadrangle rule in T 394, D7313 and the drafts)."""
    y = np.asarray(y, float)
    x = np.asarray(x, float)
    if len(x) < 2:
        return 0.0
    return float(np.sum((x[1:] - x[:-1]) * (y[1:] + y[:-1]) * 0.5))


def r2(y, f):
    y = np.asarray(y, float)
    f = np.asarray(f, float)
    ss = float(np.sum((y - y.mean()) ** 2))
    if ss <= 0:
        return float("nan")
    return 1.0 - float(np.sum((y - f) ** 2)) / ss


def linfit(x, y):
    """Least-squares line. Returns slope, intercept, R²."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    if len(x) < 2 or np.ptp(x) == 0:
        return float("nan"), float("nan"), float("nan")
    a, b = np.polyfit(x, y, 1)
    return float(a), float(b), r2(y, a * x + b)


def interp_cross(x, y, level, i0, direction="down"):
    """First crossing of `level` after index i0. Linear interpolation
    between the two bracketing points. Returns (x, index) or (nan, None)."""
    y = np.asarray(y, float)
    x = np.asarray(x, float)
    for k in range(max(i0, 0), len(y) - 1):
        a, b = y[k], y[k + 1]
        hit = (a >= level > b) if direction == "down" else (a <= level < b)
        if hit:
            if a == b:
                return float(x[k]), k
            return float(x[k] + (level - a) * (x[k + 1] - x[k]) / (b - a)), k
    return float("nan"), None


def sampling_hz(t):
    t = np.asarray(t, float)
    if len(t) < 3:
        return float("nan")
    dt = np.diff(t)
    dt = dt[dt > 0]
    if not len(dt):
        return float("nan")
    return float(1.0 / np.median(dt))


def decimate(x, y, n=400):
    """Thin a curve for plotting, keeping the extreme load point."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    if len(x) <= n:
        idx = np.arange(len(x))
    else:
        idx = np.unique(np.concatenate([np.linspace(0, len(x) - 1, n).astype(int), [int(np.nanargmax(y))]]))
    return [[_r(x[i]), _r(y[i])] for i in idx if np.isfinite(x[i]) and np.isfinite(y[i])]


def _r(v, d=5):
    v = float(v)
    if not math.isfinite(v):
        return None
    return round(v, d)


def clean(v):
    """Make numpy values JSON safe."""
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    if isinstance(v, np.ndarray):
        return [clean(x) for x in v.tolist()]
    if isinstance(v, (np.floating, float)):
        v = float(v)
        return v if math.isfinite(v) else None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


# ---------------------------------------------------------------- record prep
def prepare(t, P, u, start_load, end_load, tare=False, extra=None, end_rule="below"):
    """Zero, trim and tidy one record.

    * tare: subtract the first load reading from all loads.
    * start: the first point at or above `start_load` becomes u = 0.
    * end: stop at the first point after the peak that falls below
      `end_load` (that point is not kept).
    extra: dict of other channels (same length) to trim alongside.
    Returns a dict with the trimmed arrays and the indices used.
    """
    t = np.asarray(t, float)
    P = np.asarray(P, float)
    u = np.asarray(u, float)
    extra = {k: np.asarray(v, float) for k, v in (extra or {}).items()}
    ok = np.isfinite(P) & np.isfinite(u) & np.isfinite(t)
    for v in extra.values():
        ok &= np.isfinite(v)
    t, P, u = t[ok], P[ok], u[ok]
    extra = {k: v[ok] for k, v in extra.items()}
    info = {"n_raw": int(len(P))}
    if len(P) < 10:
        raise ValueError("Too few numeric rows in this file.")
    if tare:
        info["tare"] = float(P[0])
        P = P - P[0]
    ip_all = int(np.argmax(P))
    above = np.where(P[: ip_all + 1] >= start_load)[0]
    i0 = int(above[0]) if len(above) else 0
    info["start_found"] = bool(len(above))
    below = np.where(P[ip_all:] < end_load)[0]
    i1 = ip_all + int(below[0]) if len(below) else len(P)
    info["end_found"] = bool(len(below))
    sl = slice(i0, i1)
    u0 = u[i0]
    out = {
        "t": t[sl] - t[i0],
        "P": P[sl],
        "u": u[sl] - u0,
        "extra": {k: v[sl] - v[i0] for k, v in extra.items()},
        "extra_abs": {k: v[sl] for k, v in extra.items()},
        "info": info,
        "full": {"t": t, "P": P, "u": u - u0, "i0": i0, "i1": i1},
    }
    if len(out["P"]) < 8:
        raise ValueError("Too few points between the start and end trims. Check the trim loads and units.")
    out["ip"] = int(np.argmax(out["P"]))
    return out


def rate_check(t, x, P, ip, end_index=None):
    """Line fit of control displacement vs. time from 25% of peak (rising)
    to the end of the trimmed record. Returns rate in mm/s and R²."""
    t = np.asarray(t, float)
    x = np.asarray(x, float)
    P = np.asarray(P, float)
    if len(t) < 5 or not np.all(np.isfinite(x)):
        return float("nan"), float("nan")
    rise = np.where(P[: ip + 1] >= 0.25 * P[ip])[0]
    i25 = int(rise[0]) if len(rise) else 0
    j = len(t) if end_index is None else end_index
    if j - i25 < 3:
        return float("nan"), float("nan")
    a, _, rr = linfit(t[i25:j], x[i25:j])
    return a, rr


# ---------------------------------------------------------------- fits
def poly_prepeak(u, P, ip, deg=6):
    """6th-order polynomial on the ascending branch (T 393 X1.3)."""
    uu, pp = u[: ip + 1], P[: ip + 1]
    deg = min(deg, max(1, len(uu) - 2))
    scale = uu[-1] if uu[-1] > 0 else 1.0
    c = np.polyfit(uu / scale, pp, deg)
    f = lambda x: np.polyval(c, np.asarray(x, float) / scale)
    return f, r2(pp, f(uu)), c, scale


def gauss4(u, *p):
    y = np.zeros_like(np.asarray(u, float))
    for i in range(4):
        d, e, f = p[3 * i: 3 * i + 3]
        y = y + d * np.exp(-((u - e) / f) ** 2)
    return y


def gauss4_d(u, p):
    """First and second derivatives of gauss4."""
    d1 = np.zeros_like(u)
    d2 = np.zeros_like(u)
    for i in range(4):
        d, e, f = p[3 * i: 3 * i + 3]
        z = (u - e) / f
        g = d * np.exp(-z * z)
        d1 = d1 + g * (-2 * z / f)
        d2 = d2 + g * (4 * z * z - 2) / (f * f)
    return d1, d2


IFIT_FB = [0.9, 0.7, 0.5, 0.3, 0.1, 0.05, 0.01, 0.005, 0.001]
DONUT_FB = [0.20, 0.15, 0.10, 0.06, 0.03, 0.02, 0.01]


def _fit_one(uu, pp, p0, lo, hi):
    p0 = np.clip(np.asarray(p0, float), np.asarray(lo) + 1e-9, np.asarray(hi) - 1e-9)
    p, _ = curve_fit(gauss4, uu, pp, p0=p0, bounds=(lo, hi), maxfev=20000)
    return p


def ifit_inflection(p, u_a, u_b, n=6000):
    """Inflection point of the post-peak fit (T 393 X1.4).

    Candidates are sign changes of the second derivative where the slope is
    negative. Criterion 2: the tangent must stay at or below the curve from
    u_i until the curve drops to 30% of P_i. Of the candidates that pass,
    the steepest is used. This reproduces the slopes of the widely used
    I-FIT software on the files we checked."""
    x = np.linspace(u_a, u_b, n)
    y = gauss4(x, *p)
    d1, d2 = gauss4_d(x, p)
    idx = np.where(np.sign(d2[:-1]) != np.sign(d2[1:]))[0]
    cands = []
    for k in idx:
        # refine root by linear interpolation
        a, b = d2[k], d2[k + 1]
        w = a / (a - b) if a != b else 0.0
        ui = x[k] + w * (x[k + 1] - x[k])
        Pi = float(gauss4(np.array([ui]), *p)[0])
        m = float(gauss4_d(np.array([ui]), p)[0][0])
        if m >= 0 or Pi <= 0:
            continue
        stop = np.where(y[k:] <= 0.3 * Pi)[0]
        j = k + (int(stop[0]) if len(stop) else len(y) - k - 1)
        seg = slice(k, max(j, k + 2))
        c2 = float(np.min(y[seg] - (Pi + m * (x[seg] - ui))))
        tol = -1e-3 * max(Pi, 1e-6)
        cands.append({"ui": float(ui), "Pi": Pi, "m": m, "c2": c2, "ok": c2 >= tol})
    good = [c for c in cands if c["ok"]]
    good.sort(key=lambda c: c["m"])
    return (good[0] if good else None), cands


def fit_post_ifit(uu, pp, accept=0.997):
    """Post-peak 4-term Gaussian, I-FIT bounds (±10, f lower bound loop)."""
    L = max(uu[-1] - uu[0], 1e-6)
    best, tried = None, []
    for fb in IFIT_FB:
        p0 = []
        for d, e, f in zip([1, .5, .3, .1], [0, .25, .5, .85], [L / 4, L / 3, L / 2, L]):
            p0 += [d * pp[0], uu[0] + e * L, max(f, fb * 1.01)]
        lo = [-10, -10, fb] * 4
        hi = [10, 10, 10] * 4
        try:
            p = _fit_one(uu, pp, p0, lo, hi)
        except Exception:
            tried.append({"fb": fb, "r2": None})
            continue
        rr = r2(pp, gauss4(uu, *p))
        inf, cands = ifit_inflection(p, uu[0], uu[-1])
        tried.append({"fb": fb, "r2": rr, "inflection": inf is not None})
        if inf is None:
            continue
        res = {"p": p, "r2": rr, "fb": fb, "inf": inf, "cands": cands}
        if best is None or rr > best["r2"]:
            best = res
        if rr > accept:
            best = res
            break
    if best is not None:
        best["accepted"] = best["r2"] > accept
        best["tried"] = tried
    return best


def fit_post_donut(uu, pp, P100, l100p, accept=0.997, l100=None):
    """Post-peak 4-term Gaussian with the scaled bounds of the DONUT draft
    (Appendix A.4). Returns the accepted fit or the best one tried."""
    L = max(uu[-1] - uu[0], 1e-6)
    best, tried = None, []
    for k in DONUT_FB:
        fb = k * L
        p0 = []
        for d, e, f in zip([1, .5, .3, .1], [0, .25, .5, .85], [L / 4, L / 3, L / 2, L]):
            p0 += [d * pp[0], l100p + e * L, max(f, fb * 1.01)]
        lo = [-1.5 * P100, l100p - L, fb] * 4
        hi = [1.5 * P100, l100p + L, 10 * L + 10] * 4
        try:
            p = _fit_one(uu, pp, p0, lo, hi)
        except Exception:
            tried.append({"fb": k, "r2": None})
            continue
        rr = r2(pp, gauss4(uu, *p))
        x = np.arange(l100 if l100 is not None else uu[0], uu[-1] + 1e-9, 0.005)
        y = gauss4(x, *p)
        cross = np.where(y <= 0.75 * P100)[0]
        # monotonic drop to P75; the Gaussian peak may sit a hair after the
        # cubic peak, so a rise of up to 0.5% of P100 before it is tolerated
        mono = False
        if len(cross):
            seg = y[: int(cross[0]) + 1]
            j = int(np.argmax(seg))
            mono = bool(np.all(np.diff(seg[j:]) <= 1e-9)) and (seg[j] - seg[0] <= 0.005 * P100)
        tried.append({"fb": k, "r2": rr, "monotonic": mono})
        res = {"p": p, "r2": rr, "fb": k, "mono": mono}
        score = rr - (0 if mono else 1)
        if best is None or score > best["score"]:
            best = dict(res, score=score)
        if rr >= accept and mono:
            best = dict(res, score=score)
            break
    if best is not None:
        best["accepted"] = best["r2"] >= accept and best["mono"]
        best["tried"] = tried
    return best


# ---------------------------------------------------------------- stats
def stats(vals):
    a = np.asarray([v for v in vals if v is not None and math.isfinite(v)], float)
    n = len(a)
    if n == 0:
        return {"n": 0, "mean": None, "sd": None, "cov": None, "min": None, "max": None}
    mean = float(a.mean())
    sd = float(a.std(ddof=1)) if n > 1 else None
    cov = (100 * sd / abs(mean)) if (sd is not None and mean != 0) else None
    return {"n": n, "mean": mean, "sd": sd, "cov": cov, "min": float(a.min()), "max": float(a.max())}
