"""Calculations for each test. Every function takes one prepared record
and returns outputs, plot data, fit details and data columns for export.

Record keys: t (s), P (kN), u (mm, LLD or average LLD), cmod (mm or None).
dims: specimen dimensions in mm. st: settings for the run.
"""
import math

import numpy as np

from core import (DONUT_FB, decimate, fit_post_donut, fit_post_ifit, gauss4, gauss4_d, interp_cross, linfit,
                  poly_prepeak, prepare, r2, trapz)


def _pts(x, y, n=300):
    return decimate(x, y, n)


def _curve(f, a, b, n=120):
    x = np.linspace(a, b, n)
    return [[round(float(i), 5), round(float(j), 5)] for i, j in zip(x, f(x))]


def _base(rec, st, extra=None):
    return prepare(rec["t"], rec["P"], rec["u"], st["start_load"], st["end_load"], st.get("tare", False), extra=extra)


def _seat_triangle(u, P):
    """Seating triangle 0.5 * u_r * P_r: extend the initial slope to zero load."""
    k = min(len(u), 6)
    S0, _, _ = linfit(u[:k], P[:k])
    if not (S0 and S0 > 0 and math.isfinite(S0)):
        return 0.0, float("nan")
    ur = P[0] / S0
    return 0.5 * ur * P[0], ur


def _common_out(pr):
    t, P, u, ip = pr["t"], pr["P"], pr["u"], pr["ip"]
    return {"Pmax": float(P[ip]), "t_peak": float(t[ip]), "u_peak": float(u[ip])}


# ====================================================================== I-FIT
def ifit(rec, dims, st):
    pr = _base(rec, st)
    t, P, u, ip = pr["t"], pr["P"], pr["u"], pr["ip"]
    t_, D, a = dims["t"], dims["D"], dims["a"]
    lig = dims.get("lig") or (D / 2 - a)
    warn, notes = [], []
    f6, r2pre, coef, scale = poly_prepeak(u, P, ip)
    u0 = float(u[ip])
    Wseat, ur = _seat_triangle(u, P)
    fitted = st["mode"] == "fitted"
    if fitted:
        up = np.linspace(0, u0, 1001)
        Wpre = trapz(f6(up), up)
    else:
        Wpre = trapz(P[: ip + 1], u[: ip + 1])
    if not st.get("seating", True):
        Wseat = 0.0
    uu, pp = u[ip:], P[ip:]
    out = _common_out(pr)
    fit = fit_post_ifit(uu, pp) if len(uu) >= 13 else None
    if fit is None:
        warn.append("The post-peak fit found no valid inflection point. FI and slope are blank.")
        m = ui = Pi = float("nan")
        Wpost = trapz(pp, uu)
        r2post = float("nan")
    else:
        m, ui, Pi = fit["inf"]["m"], fit["inf"]["ui"], fit["inf"]["Pi"]
        r2post = fit["r2"]
        if not fit["accepted"]:
            warn.append(f"Post-peak fit R² {fit['r2']:.4f} is below 0.997. The best fit was used.")
        notes.append(f"Post-peak fit accepted at f lower bound {fit['fb']}.")
        if fitted:
            xp = np.arange(uu[0], uu[-1] + 1e-12, 0.005)
            Wpost = trapz(gauss4(xp, *fit["p"]), xp)
        else:
            Wpost = trapz(pp, uu)
    if r2pre < 0.997:
        warn.append(f"Pre-peak fit R² {r2pre:.4f} is below 0.997.")
    Wf = Wpre + Wseat + Wpost
    A = lig * t_
    Gf = Wf / A * 1e6
    out.update({
        "Gf": Gf, "m": m, "m_abs": abs(m), "FI": Gf / abs(m) * 0.01 if m == m and m != 0 else float("nan"),
        "u0": u0, "u1": ui - Pi / m if m == m and m != 0 else float("nan"), "ui": ui, "Pi": Pi,
        "Wf": Wf, "W_pre": Wpre, "W_post": Wpost, "W_seat": Wseat,
        "Gf_pre": (Wpre + Wseat) / A * 1e6,
        "strength": out["Pmax"] * 1000 / (2 * (D / 2) * t_),
        "secant": float(f6(u0 / 2) / (u0 / 2)) if u0 > 0 else float("nan"),
        "r2_pre": r2pre, "r2_post": r2post, "lig_used": lig,
    })
    plot = {"x": "LLD (mm)", "y": "Load (kN)",
            "series": [{"name": "Raw data", "cls": "raw", "pts": _pts(u, P)}], "points": [], "lines": []}
    if fit is not None:
        pre = _curve(f6, 0, u0, 80)
        post = _curve(lambda x: gauss4(x, *fit["p"]), u0, uu[-1], 160)
        plot["series"].append({"name": "Fitted curve", "cls": "fit", "pts": pre + post[1:]})
        plot["points"] += [{"name": "Peak", "x": u0, "y": out["Pmax"]}, {"name": "Inflection", "x": ui, "y": Pi},
                           {"name": "u₁", "x": out["u1"], "y": 0}]
        x0 = max(0, ui - Pi * 0.6 / abs(m))
        plot["lines"].append({"name": "Tangent at inflection", "cls": "tan",
                              "pts": [[x0, Pi + m * (x0 - ui)], [out["u1"], 0]]})
    fit_info = {
        "pre": {"type": "6th-order polynomial on u/u0", "coef": [float(c) for c in coef], "u_scale": scale, "r2": r2pre},
        "post": None if fit is None else {
            "type": "4-term Gaussian", "params": [float(x) for x in fit["p"]], "r2": fit["r2"], "f_lower": fit["fb"],
            "accepted": fit["accepted"], "tried": fit["tried"],
            "candidates": [{k: v for k, v in c.items()} for c in fit["cands"]]},
        "seating": {"P_r": float(P[0]), "u_r": ur, "W": Wseat},
    }
    cols = {"Time (s)": t, "LLD zeroed (mm)": u, "Load (kN)": P}
    if fit is not None:
        cols["Load fitted (kN)"] = np.where(u <= u0, f6(u), gauss4(u, *fit["p"]))
    return dict(outputs=out, warnings=warn, notes=notes, plot=plot, fit=fit_info, cols=cols, pr=pr)


# ==================================================================== IDEAL-CT
POISSON = {"design": (-1.78, 6.45e-5), "av7": (0.25, 5.21e-5)}


def idealct(rec, dims, st):
    pr = _base(rec, st)
    t, P, u, ip = pr["t"], pr["P"], pr["u"], pr["ip"]
    t_, D = dims["t"], dims["D"]
    warn, notes = [], []
    out = _common_out(pr)
    Pm = out["Pmax"]
    Wf = trapz(P, u)
    Gf = Wf / (D * t_) * 1e6
    uu, pp = u[ip:], P[ip:]
    fit = fit_post_ifit(uu, pp) if len(uu) >= 13 else None
    fitted = st["mode"] == "fitted" and fit is not None
    if st["mode"] == "fitted" and fit is None:
        warn.append("The post-peak fit failed. Crossings use the raw data.")
    if fit is not None and not fit["accepted"]:
        warn.append(f"Post-peak fit R² {fit['r2']:.4f} is below 0.997. The best fit was used.")
    if fitted:
        xs = np.arange(uu[0], uu[-1] + 1e-12, 0.001)
        ys = gauss4(xs, *fit["p"])
        cx, cy, k0 = xs, ys, 0
    else:
        cx, cy, k0 = u, P, ip
    l85, _ = interp_cross(cx, cy, 0.85 * Pm, k0)
    l75, _ = interp_cross(cx, cy, 0.75 * Pm, k0)
    l65, _ = interp_cross(cx, cy, 0.65 * Pm, k0)
    m75 = float("nan")
    if all(math.isfinite(v) for v in (l85, l65)):
        sel = (u >= l85) & (u <= l65) & (np.arange(len(u)) >= ip)
        if sel.sum() >= 2:
            m75, _, _ = linfit(u[sel], P[sel])
            m75 *= 1e6  # kN/mm -> N/m
        else:
            m75 = (0.65 - 0.85) * Pm / (l65 - l85) * 1e6
            warn.append("Fewer than two points between P85 and P65. Slope from the two crossing points.")
    else:
        warn.append("The curve does not drop to 65% of peak. CT index is blank.")
    CT = (t_ / 62) * (l75 / D) * (Gf / abs(m75)) * 1e6 if math.isfinite(m75) and m75 != 0 else float("nan")
    # N_flex (Yin et al. 2018)
    Sc = Pm / out["u_peak"] * 1000 if out["u_peak"] > 0 else float("nan")  # kN/m
    if st.get("poisson", "fixed") == "fixed":
        mu = float(st.get("mu", 0.35))
    else:
        aa, bb = POISSON[st.get("mix", "design")]
        mu = 0.15 + 0.35 / (1 + math.exp(aa + bb * Sc))
    Nflex = T_inf = s_inf = float("nan")
    if fit is not None:
        ui, m = fit["inf"]["ui"], fit["inf"]["m"]
        sig = lambda p: 2 * p * 1e6 / (math.pi * t_ * D)  # kPa
        eps = lambda d: 100 * mu * d / D  # %
        k = int(np.searchsorted(u, ui))
        xs = np.concatenate([u[:k], [ui]])
        ys = np.concatenate([P[:k], [float(np.interp(ui, u, P))]])
        T_inf = trapz(sig(ys), eps(xs))
        s_inf = sig(m) / (100 * mu / D)
        Nflex = T_inf / abs(s_inf) if s_inf else float("nan")
    else:
        warn.append("No inflection point found. N<sub>flex</sub> is blank.")
    out.update({"Wf": Wf, "Gf": Gf, "l85": l85, "l75": l75, "l65": l65, "m75": m75, "m75_abs": abs(m75),
                "CT": CT, "Nflex": Nflex, "T_inf": T_inf, "s_inf": abs(s_inf), "mu": mu, "Sc": Sc,
                "strength": 2 * Pm * 1000 / (math.pi * t_ * D),
                "r2_post": fit["r2"] if fit else float("nan")})
    plot = {"x": "LLD (mm)", "y": "Load (kN)",
            "series": [{"name": "Raw data", "cls": "raw", "pts": _pts(u, P)}], "points": [], "lines": []}
    if fit is not None:
        plot["series"].append({"name": "Post-peak fit", "cls": "fit", "pts": _curve(lambda x: gauss4(x, *fit["p"]), uu[0], uu[-1], 160)})
        plot["points"].append({"name": "N<sub>flex</sub> inflection", "x": fit["inf"]["ui"], "y": fit["inf"]["Pi"]})
    plot["points"] += [{"name": "Peak", "x": out["u_peak"], "y": Pm}]
    for nm, lv, fr in (("P₈₅", l85, .85), ("P₇₅", l75, .75), ("P₆₅", l65, .65)):
        if math.isfinite(lv):
            plot["points"].append({"name": nm, "x": lv, "y": fr * Pm})
    if math.isfinite(m75) and math.isfinite(l75):
        mk = m75 / 1e6
        plot["lines"].append({"name": "m₇₅", "cls": "tan", "pts": [[l75 - 0.25 * Pm / abs(mk), 0.75 * Pm + 0.25 * Pm],
                                                                   [l75 + 0.75 * Pm / abs(mk), 0]]})
    fit_info = {"post": None if fit is None else {
        "type": "4-term Gaussian", "params": [float(x) for x in fit["p"]], "r2": fit["r2"], "f_lower": fit["fb"],
        "accepted": fit["accepted"], "tried": fit["tried"]},
        "crossings_from": "fitted curve" if fitted else "raw data",
        "nflex": {"poisson": st.get("poisson", "fixed"), "mix": st.get("mix"), "mu": mu, "Sc_kN_per_m": Sc}}
    cols = {"Time (s)": t, "LLD zeroed (mm)": u, "Load (kN)": P}
    if fit is not None:
        cols["Load fitted, post-peak (kN)"] = np.where(np.arange(len(u)) >= ip, gauss4(u, *fit["p"]), np.nan)
    return dict(outputs=out, warnings=warn, notes=notes, plot=plot, fit=fit_info, cols=cols, pr=pr)


# ====================================================================== DONUT
def donut(rec, dims, st):
    pr = _base(rec, st)
    t, P, u, ip = pr["t"], pr["P"], pr["u"], pr["ip"]
    t_, D, d = dims["t"], dims["D"], dims["d"]
    warn, notes = [], []
    out = _common_out(pr)
    Wf = trapz(P, u)
    Gf = Wf / ((D - d) * t_) * 1e6
    l100p, P100p = float(u[ip]), float(P[ip])
    fitted = st["mode"] == "fitted"
    fit, cubic = None, None
    if fitted:
        sel = np.abs(u - l100p) <= 0.5
        if sel.sum() >= 5:
            c = np.polyfit(u[sel], P[sel], 3)
            xs = np.linspace(u[sel].min(), u[sel].max(), 2001)
            ys = np.polyval(c, xs)
            k = int(np.argmax(ys))
            P100, l100 = float(ys[k]), float(xs[k])
            cubic = {"coef": [float(x) for x in c], "r2": r2(P[sel], np.polyval(c, u[sel]))}
        else:
            P100, l100 = P100p, l100p
            warn.append("Too few points within ±0.5 mm of the peak for the cubic. Recorded peak used.")
        uu, pp = u[ip:], P[ip:]
        fit = fit_post_donut(uu, pp, P100, l100p, l100=max(l100, l100p)) if len(uu) >= 13 else None
        if fit is None:
            warn.append("The post-peak fit failed. l<sub>75</sub> uses the raw data.")
            l75, _ = interp_cross(u, P, 0.75 * P100, ip)
        else:
            if not fit["accepted"]:
                warn.append(f"Post-peak fit R² {fit['r2']:.4f} (needs 0.997 and a monotonic drop to P75). The best fit was used.")
            notes.append(f"Fit accepted at f lower bound {fit['fb']} L.")
            xs = np.arange(l100p, uu[-1] + 1e-12, 0.005)
            ys = gauss4(xs, *fit["p"])
            k0 = int(np.searchsorted(xs, l100))
            l75, _ = interp_cross(xs, ys, 0.75 * P100, k0)
    else:
        P100, l100 = P100p, l100p
        l75, _ = interp_cross(u, P, 0.75 * P100, ip)
    if not math.isfinite(l75):
        warn.append("The curve does not drop to 75% of peak. DI is blank.")
    S75 = (0.75 * P100 - P100) / (l75 - l100) if math.isfinite(l75) and l75 > l100 else float("nan")
    DI = Gf / abs(S75) * 0.001 if math.isfinite(S75) and S75 != 0 else float("nan")
    # not in the draft
    f6, _, _, _ = poly_prepeak(u, P, ip)
    sec = float(f6(l100 / 2) / (l100 / 2)) if l100 > 0 else float("nan")
    # contact quality (draft 10.5): first recorded load near 0.10 kN
    if P[0] > 0.25:
        warn.append(f"Record starts at {P[0]:.2f} kN. The draft asks for a 0.10 ± 0.01 kN contact load. Check seating.")
    out.update({"P100": P100, "l100": l100, "l75": l75, "S75": S75, "S75_abs": abs(S75), "DI": DI, "Wf": Wf, "Gf": Gf,
                "strength": P100 * 1000 / ((D - d) * t_), "secant": sec,
                "r2_post": fit["r2"] if fit else float("nan"), "fb": fit["fb"] if fit else float("nan")})
    plot = {"x": "LLD (mm)", "y": "Load (kN)",
            "series": [{"name": "Raw data", "cls": "raw", "pts": _pts(u, P)}], "points": [], "lines": []}
    if fit is not None:
        plot["series"].append({"name": "Post-peak fit", "cls": "fit", "pts": _curve(lambda x: gauss4(x, *fit["p"]), l100p, u[-1], 160)})
    plot["points"].append({"name": "P₁₀₀", "x": l100, "y": P100})
    if math.isfinite(l75):
        plot["points"].append({"name": "P₇₅", "x": l75, "y": 0.75 * P100})
        plot["lines"].append({"name": "S₇₅ secant", "cls": "tan", "pts": [[l100, P100], [l75, 0.75 * P100]]})
    fit_info = {"cubic": cubic, "post": None if fit is None else {
        "type": "4-term Gaussian, scaled bounds", "params": [float(x) for x in fit["p"]], "r2": fit["r2"],
        "f_lower_times_L": fit["fb"], "monotonic_to_P75": fit["mono"], "accepted": fit["accepted"], "tried": fit["tried"]},
        "applied": fitted}
    cols = {"Time (s)": t, "LLD zeroed (mm)": u, "Load (kN)": P}
    if fit is not None:
        cols["Load fitted, post-peak (kN)"] = np.where(np.arange(len(u)) >= ip, gauss4(u, *fit["p"]), np.nan)
    return dict(outputs=out, warnings=warn, notes=notes, plot=plot, fit=fit_info, cols=cols, pr=pr)


# ======================================================================= SCB
def _stiffness_window(u, P, ip, frac=0.15, alpha=0.05):
    """Moving window of `frac` of the pre-peak points; best penalized R²."""
    n = ip + 1
    w = max(3, int(round(frac * n)))
    Pm = P[ip]
    best = None
    for s in range(0, n - w + 1):
        x, y = u[s: s + w], P[s: s + w]
        a, b, rr = linfit(x, y)
        if not math.isfinite(rr):
            continue
        lm = float(np.mean(y)) / Pm - 0.5
        pen = rr - alpha * lm * lm
        if best is None or pen > best["pen"]:
            best = {"S": a, "b": b, "r2": rr, "pen": pen, "i0": s, "i1": s + w - 1}
    return best


def scb(rec, dims, st):
    extra = {"cmod": rec["cmod"]} if rec.get("cmod") is not None else None
    pr = _base(rec, st, extra)
    t, P, u, ip = pr["t"], pr["P"], pr["u"], pr["ip"]
    t_, D, a = dims["t"], dims["D"], dims["a"]
    r = D / 2
    lig = dims.get("lig") or (r - a)
    warn, notes = [], []
    out = _common_out(pr)
    W = trapz(P, u)
    stf = _stiffness_window(u, P, ip, st.get("window", 0.15))
    S = stf["S"] if stf else float("nan")
    Wseat = 0.0
    if st.get("seating", True) and P[0] >= 0.3 and S > 0:
        Wseat = 0.5 * P[0] * (P[0] / S)
        notes.append(f"Record starts at {P[0]:.2f} kN (≥ 0.3 kN). Triangle OO′A added (T 394 Note 2).")
    # tail: P = c / u^2 fitted below 60% of peak, post-peak
    post = np.arange(len(P)) >= ip
    sel = post & (P < 0.6 * P[ip]) & (u > 0)
    c = float("nan")
    Wtail = 0.0
    uc = float(u[-1])
    if sel.sum() >= 3:
        x = 1 / u[sel] ** 2
        c = float(np.sum(x * P[sel]) / np.sum(x * x))
        Wtail = c / uc
    else:
        warn.append("Fewer than three points below 60% of peak. No tail was added.")
    if not pr["info"]["end_found"]:
        notes.append("The record ends before the load drops below the end trim. u<sub>c</sub> is the last point.")
    Wf = W + Wtail + Wseat
    Gf = Wf / (lig * t_) * 1e6
    sigma0 = out["Pmax"] * 1e-3 / (2 * (r / 1000) * (t_ / 1000))  # MPa
    ar = a / r
    Y = 4.782 - 1.219 * ar + 0.063 * math.exp(7.045 * ar)
    KIC = Y * sigma0 * math.sqrt(math.pi * a / 1000)
    out.update({"W": W, "Wtail": Wtail, "Wseat": Wseat, "Wf": Wf, "Gf": Gf, "KIC": KIC, "Y": Y, "S": S,
                "uc": uc, "c_tail": c, "lig_used": lig})
    plot = {"x": "Average LLD (mm)", "y": "Load (kN)",
            "series": [{"name": "Raw data", "cls": "raw", "pts": _pts(u, P)}], "points": [{"name": "Peak", "x": out["u_peak"], "y": out["Pmax"]}], "lines": []}
    if math.isfinite(c) and c > 0:
        xs = np.linspace(uc, uc * 2.2, 60)
        plot["series"].append({"name": "Power-law tail", "cls": "fit", "pts": [[float(x), float(c / x ** 2)] for x in xs]})
    if stf:
        x0, x1 = u[stf["i0"]], u[stf["i1"]]
        plot["lines"].append({"name": "Stiffness window", "cls": "tan", "pts": [[x0, S * x0 + stf["b"]], [x1, S * x1 + stf["b"]]]})
    fit_info = {"tail": {"model": "P = c/u²", "c": c, "points": int(sel.sum()), "uc": uc},
                "stiffness": None if not stf else {k: (float(v) if not isinstance(v, int) else v) for k, v in stf.items()}}
    cols = {"Time (s)": t, "Average LLD zeroed (mm)": u, "Load (kN)": P}
    if extra:
        cols["CMOD zeroed (mm)"] = pr["extra"]["cmod"]
    return dict(outputs=out, warnings=warn, notes=notes, plot=plot, fit=fit_info, cols=cols, pr=pr)


# ==================================================================== SLT-SCB
def sltscb(rec, dims, st):
    pr = _base(rec, st)
    t, P, u, ip = pr["t"], pr["P"], pr["u"], pr["ip"]
    t_, D, a = dims["t"], dims["D"], dims["a"]
    lig = dims.get("lig") or (D / 2 - a)
    warn, notes = [], []
    out = _common_out(pr)
    Wpre = trapz(P[: ip + 1], u[: ip + 1])
    Gpre = Wpre / (lig * t_) * 1e6
    stf = _stiffness_window(u, P, ip, st.get("window", 0.15))
    S = stf["S"] if stf else float("nan")
    drop = 100 * (1 - P[-1] / P[ip])
    if drop < 25 and not pr["info"]["end_found"]:
        warn.append(f"The record stops {drop:.0f}% below peak. The draft allows stopping after a 25% drop.")
    out.update({"W_pre": Wpre, "Gf_pre": Gpre, "S": S, "LCI": Gpre / S if S and S > 0 else float("nan"),
                "S_r2": stf["r2"] if stf else float("nan"), "S_lo": float(P[stf["i0"]]) if stf else float("nan"),
                "S_hi": float(P[stf["i1"]]) if stf else float("nan"), "drop": drop, "lig_used": lig})
    plot = {"x": "LLD (mm)", "y": "Load (kN)",
            "series": [{"name": "Raw data", "cls": "raw", "pts": _pts(u, P)}],
            "points": [{"name": "Peak", "x": out["u_peak"], "y": out["Pmax"]}], "lines": []}
    if stf:
        x0, x1 = u[stf["i0"]], u[stf["i1"]]
        ext = 0.15 * (x1 - x0)
        plot["lines"].append({"name": "Stiffness window", "cls": "tan",
                              "pts": [[x0 - ext, S * (x0 - ext) + stf["b"]], [x1 + ext, S * (x1 + ext) + stf["b"]]]})
    fit_info = {"stiffness": None if not stf else {"S": stf["S"], "intercept": stf["b"], "r2_raw": stf["r2"],
                                                   "r2_penalized": stf["pen"], "first_point": stf["i0"], "last_point": stf["i1"],
                                                   "window_fraction": st.get("window", 0.15), "alpha": 0.05}}
    cols = {"Time (s)": t, "LLD zeroed (mm)": u, "Load (kN)": P}
    return dict(outputs=out, warnings=warn, notes=notes, plot=plot, fit=fit_info, cols=cols, pr=pr)


# ======================================================================== DCT
def dct(rec, dims, st):
    if rec.get("cmod") is None:
        raise ValueError("DCT needs a CMOD column.")
    # CMOD is the x channel for DCT
    r2rec = dict(rec, u=rec["cmod"])
    pr = _base(r2rec, st)
    t, P, cm, ip = pr["t"], pr["P"], pr["u"], pr["ip"]
    B, lig = dims["B"], dims["lig"]
    warn, notes = [], []
    out = _common_out(pr)
    # D7313 8.1: line fit of CMOD vs time over the test, CMOD_fit = a1 * t
    a1, a0, rr = linfit(t, cm)
    cmfit = a1 * t
    area = trapz(P, cmfit)
    Gf = area / (B * lig) * 1e6
    out.update({"Gf": Gf, "area": area, "cmod_end": float(cmfit[-1]), "cmod_r2": rr, "cmod_slope": a1,
                "cmod_icpt": a0})
    out.pop("u_peak", None)
    plot = {"x": "CMOD (mm)", "y": "Load (kN)",
            "series": [{"name": "Load vs. CMOD (raw)", "cls": "raw", "pts": _pts(cm, P)},
                       {"name": "Load vs. CMOD<sub>fit</sub>", "cls": "fit", "pts": _pts(cmfit, P)}],
            "points": [{"name": "Peak", "x": float(cmfit[ip]), "y": out["Pmax"]}], "lines": []}
    fit_info = {"cmod_fit": {"slope_mm_per_s": a1, "intercept_mm": a0, "r2": rr, "used": "CMOD_fit = a1 × t"}}
    cols = {"Time (s)": t, "CMOD zeroed (mm)": cm, "CMOD fitted (mm)": cmfit, "Load (kN)": P}
    return dict(outputs=out, warnings=warn, notes=notes, plot=plot, fit=fit_info, cols=cols, pr=pr, rate_mm_s=a1)


# ======================================================================== IDT
def idt(rec, dims, st):
    t_, D = dims["t"], dims["D"]
    warn, notes = [], []
    P = np.asarray(rec["P"], float)
    t = np.asarray(rec["t"], float) if rec.get("t") is not None else np.arange(len(P), dtype=float)
    u = np.asarray(rec["u"], float) if rec.get("u") is not None else np.full(len(P), np.nan)
    if st.get("tare"):
        P = P - P[0]
    ok = np.isfinite(P)
    P, t, u = P[ok], t[ok], u[ok]
    ip = int(np.argmax(P))
    Pm = float(P[ip])
    St = 2 * Pm * 1000 / (math.pi * t_ * D)
    u0 = u - (u[0] if np.isfinite(u[0]) else 0)
    out = {"Pmax": Pm, "St": St, "St_psi": St * 145.0377, "t_peak": float(t[ip] - t[0]),
           "u_peak": float(u0[ip]) if np.isfinite(u0[ip]) else float("nan")}
    x = u0 if np.isfinite(u0).all() else t - t[0]
    plot = {"x": "LLD (mm)" if np.isfinite(u0).all() else "Time (s)", "y": "Load (kN)",
            "series": [{"name": "Raw data", "cls": "raw", "pts": _pts(x, P)}],
            "points": [{"name": "Peak", "x": float(x[ip]), "y": Pm}], "lines": []}
    pr = {"t": t - t[0], "P": P, "u": u0, "ip": ip, "info": {"end_found": True}, "full": None}
    cols = {"Time (s)": t - t[0], "LLD zeroed (mm)": u0, "Load (kN)": P}
    return dict(outputs=out, warnings=warn, notes=notes, plot=plot, fit={}, cols=cols, pr=pr)


ANALYZE = {"ifit": ifit, "idealct": idealct, "donut": donut, "scb": scb, "sltscb": sltscb, "dct": dct, "idt": idt}
