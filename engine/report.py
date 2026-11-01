"""Exports: one workbook per replicate, a batch summary workbook, a PDF
report and a settings JSON, packed in one zip."""
import datetime as _dt
import io
import json
import math
import re
import zipfile

import numpy as np

import core
import specs

VERSION = "0.2"
SHORT = specs.SHORT
NAVY, ORANGE, GREY = "#13294B", "#FF5F05", "#9A968C"
PAL = [NAVY, ORANGE, "#7A1F1F", "#1B6B3A", "#5B6F95", "#C84113"]


def _slug(s, fallback):
    s = re.sub(r"\s*·\s*", "-", str(s or "").strip())
    s = "".join(w[:1].upper() + w[1:] for w in s.split())
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-")
    return s[:60] or fallback


def _plain(html):
    s = str(html or "")
    s = re.sub(r"<sub>(.*?)</sub>", r"\1", s)
    s = re.sub(r"<sup>(.*?)</sup>", r"^\1", s)
    s = re.sub(r"<[^>]+>", "", s)
    return s.replace("&nbsp;", " ")


def _fmt(v, dp):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "–"
    if abs(v) >= 1e5:
        return f"{v:.3g}"
    return f"{v:.{dp}f}"


def _std_plain(spec):
    return spec.get("standard_plain") or _plain(spec["standard"])


def _stats_table(spec, reps, mask):
    rows = []
    for o in spec["outputs"]:
        vals = [r["res"]["outputs"].get(o["key"]) for r, m in zip(reps, mask) if m]
        rows.append((o, core.stats(vals)))
    return rows


# ---------------------------------------------------------------- workbooks
def _replicate_xlsx(run, rep, batch, included, reason):
    from openpyxl import Workbook
    from openpyxl.chart import Reference, ScatterChart, Series
    from openpyxl.styles import Alignment, Font, PatternFill

    spec = specs.TESTS[run["test"]]
    res = rep["res"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    head = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor=NAVY[1:])
    bold = Font(bold=True)

    def section(r, title):
        ws.cell(r, 1, title).font = head
        ws.cell(r, 1).fill = fill
        ws.cell(r, 2).fill = fill
        ws.cell(r, 3).fill = fill
        return r + 1

    r = 1
    ws.cell(r, 1, f"{spec['name']} · {_std_plain(spec)}").font = Font(bold=True, size=14)
    r += 1
    ws.cell(r, 1, f"Cracking Test Analyzer v{VERSION} · akashto.com/cracking-index")
    r += 2
    r = section(r, "Replicate")
    for k, v in [("Label", rep["label"]), ("File", rep["file"]), ("Status", "Included" if included else f"Excluded · {reason}"),
                 ("Test segment", res["segment"])]:
        ws.cell(r, 1, k); ws.cell(r, 2, v); r += 1
    r += 1
    r = section(r, "Batch")
    for k, v in _batch_rows(batch):
        ws.cell(r, 1, k); ws.cell(r, 2, v); r += 1
    r += 1
    r = section(r, "Columns used")
    for role, name in rep["mapping"]["columns"].items():
        ws.cell(r, 1, role.upper()); ws.cell(r, 2, name); ws.cell(r, 3, rep["mapping"]["units"].get(role, "")); r += 1
    r += 1
    r = section(r, "Specimen (mm)")
    for d in spec["dims"]:
        ws.cell(r, 1, d["label"]); ws.cell(r, 2, res["dims"].get(d["key"])); r += 1
    if res["dims"].get("av") is not None:
        ws.cell(r, 1, "Air voids (%)"); ws.cell(r, 2, res["dims"]["av"]); r += 1
    r += 1
    r = section(r, "Settings")
    for k, v in _settings_rows(run["test"], run["settings"]):
        ws.cell(r, 1, k); ws.cell(r, 2, v); r += 1
    r += 1
    r = section(r, "Outputs")
    out_row = r
    for o in spec["outputs"]:
        v = res["outputs"].get(o["key"])
        ws.cell(r, 1, _plain(o["label"]))
        c = ws.cell(r, 2, None if v is None or (isinstance(v, float) and not math.isfinite(v)) else float(v))
        c.number_format = "0." + "0" * o["dp"] if o["dp"] else "0"
        ws.cell(r, 3, _plain(o["unit"]))
        if o.get("main"):
            ws.cell(r, 1).font = bold
            c.font = bold
        r += 1
    r += 1
    r = section(r, "Checks")
    ch = res["checks"]
    rt = ch["rate"]
    ws.cell(r, 1, "Loading rate"); ws.cell(r, 2, rt.get("value")); ws.cell(r, 3, _ok(rt.get("ok")) + f" target {specs.target(spec)}"); r += 1
    hz = ch["hz"]
    ws.cell(r, 1, "Sampling (Hz)"); ws.cell(r, 2, hz.get("value")); ws.cell(r, 3, _ok(hz.get("ok")) + f" min {spec['min_hz']} Hz"); r += 1
    ws.cell(r, 1, "Dimensions"); ws.cell(r, 3, _ok(ch["dims"]["ok"]) + (" " + ch["dims"]["text"] if ch["dims"]["text"] else "")); r += 1
    for w in res["warnings"]:
        ws.cell(r, 1, "Warning"); ws.cell(r, 2, _plain(w)); r += 1
    for n in res["notes"]:
        ws.cell(r, 1, "Note"); ws.cell(r, 2, _plain(n)); r += 1
    ws.column_dimensions["A"].width = 44
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 34
    for row in ws.iter_rows(min_row=1, max_row=r):
        for c in row:
            c.alignment = Alignment(vertical="top")

    # data sheet
    wd = wb.create_sheet("Data")
    cols = res["cols"]
    names = list(cols)
    for j, n in enumerate(names, 1):
        wd.cell(1, j, n).font = bold
    arrs = [np.asarray(cols[n], float) for n in names]
    n = len(arrs[0])
    for i in range(n):
        for j, a in enumerate(arrs, 1):
            v = a[i]
            if math.isfinite(v):
                wd.cell(i + 2, j, round(float(v), 7))
    for j in range(1, len(names) + 1):
        wd.column_dimensions[chr(64 + j)].width = 20

    # chart: load vs displacement, with the fit if present
    xcol = 2
    ch_ = ScatterChart()
    ch_.title = f"{rep['label']}"
    ch_.style = 13
    ch_.x_axis.title = names[xcol - 1]
    ch_.y_axis.title = "Load (kN)"
    ch_.height, ch_.width = 9, 16
    xref = Reference(wd, min_col=xcol, min_row=2, max_row=n + 1)
    ycol = names.index("Load (kN)") + 1
    s1 = Series(Reference(wd, min_col=ycol, min_row=1, max_row=n + 1), xref, title_from_data=True)
    s1.marker.symbol = "circle"
    s1.marker.size = 3
    s1.graphicalProperties.line.noFill = True
    s1.marker.graphicalProperties.solidFill = "9A968C"
    s1.marker.graphicalProperties.line.solidFill = "9A968C"
    ch_.series.append(s1)
    for nm in names:
        if "fitted" in nm.lower() and "Load" in nm:
            j = names.index(nm) + 1
            s2 = Series(Reference(wd, min_col=j, min_row=1, max_row=n + 1), xref, title_from_data=True)
            s2.marker.symbol = "none"
            s2.graphicalProperties.line.solidFill = "FF5F05"
            s2.graphicalProperties.line.width = 22000
            s2.smooth = False
            ch_.series.append(s2)
    ch_.x_axis.delete = False
    ch_.y_axis.delete = False
    ws.add_chart(ch_, "E3")

    # fit sheet
    wf = wb.create_sheet("Fit")
    rr = 1
    for k, v in _flatten(res.get("fit") or {}):
        wf.cell(rr, 1, k)
        wf.cell(rr, 2, v if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v))
        rr += 1
    wf.column_dimensions["A"].width = 46
    wf.column_dimensions["B"].width = 28
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def _replicate_csv(rep):
    cols = rep["res"]["cols"]
    names = list(cols)
    arrs = [np.asarray(cols[n], float) for n in names]
    lines = [",".join(names)]
    for i in range(len(arrs[0])):
        lines.append(",".join("" if not math.isfinite(a[i]) else f"{a[i]:.7g}" for a in arrs))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _flatten(d, pre=""):
    if isinstance(d, dict):
        out = []
        for k, v in d.items():
            out += _flatten(v, f"{pre}.{k}" if pre else str(k))
        return out
    if isinstance(d, list):
        if d and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in d):
            return [(pre, ", ".join(f"{x:.6g}" for x in d))]
        out = []
        for i, x in enumerate(d):
            out += _flatten(x, f"{pre}[{i + 1}]")
        return out
    return [(pre, core.clean(d))]


def _ok(v):
    return {True: "✓", False: "✗", None: "–"}[v]


def _batch_rows(batch):
    b = batch or {}
    t = b.get("temp")
    temp = "–" if t in (None, "") else f"{t} °{b.get('temp_unit', 'C')}"
    rows = [("Project ID", b.get("project") or "–"), ("Mix ID", b.get("mix") or "–"), ("Test date", b.get("date") or "–"),
            ("Test temperature", temp)]
    for k, lab in (("vma", "Design VMA (%)"), ("nmas", "NMAS (mm)"), ("binder", "Binder content (%)"), ("pg", "Binder PG")):
        if b.get(k) not in (None, ""):
            rows.append((lab, b[k]))
    return rows


def _settings_rows(test, st):
    spec = specs.TESTS[test]
    rows = [("Standard", _std_plain(spec)),
            ("Loading", f"{spec['control_label']}, {specs.target(spec)}"),
            ("Data mode", st["mode"].capitalize()),
            ("Displacement zero", "At the start load"),
            ("Trim start / end (kN)", f"{st['start_load']:g} / {st['end_load']:g}")]
    if test in ("ifit", "scb"):
        rows.append(("Seating energy", "Added" if st["seating"] else "Left out"))
    rows.append(("Load tare", "On" if st["tare"] else "Off"))
    if test == "idealct":
        if st.get("poisson", "fixed") == "fixed":
            rows.append(("Poisson's ratio for Nflex", f"Fixed {float(st.get('mu', 0.35)):g}"))
        else:
            rows.append(("Poisson's ratio for Nflex", "From secant stiffness, " + ("Ndesign" if st.get("mix") == "design" else "7% air voids") + " model"))
    if test in ("scb", "sltscb"):
        rows.append(("Stiffness window", f"{100 * float(st.get('window', 0.15)):g}% of pre-peak points, penalized R²"))
    return rows


def _summary_xlsx(run, batch, mask, reasons):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    spec = specs.TESTS[run["test"]]
    reps = run["reps"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Replicates"
    bold = Font(bold=True)
    outs = spec["outputs"]
    head = ["Replicate", "File", "Status"] + [d["label"] + " (mm)" for d in spec["dims"]] + \
           [_plain(o["label"]) + (f" ({_plain(o['unit'])})" if o["unit"] else "") for o in outs] + ["Rate ok", "Hz ok", "Warnings"]
    for j, h in enumerate(head, 1):
        ws.cell(1, j, h).font = bold
    for i, (rep, m, why) in enumerate(zip(reps, mask, reasons), 2):
        res = rep["res"]
        row = [rep["label"], rep["file"], "Included" if m else f"Excluded · {why}"] + \
              [res["dims"].get(d["key"]) for d in spec["dims"]] + \
              [_num(res["outputs"].get(o["key"])) for o in outs] + \
              [_ok(res["checks"]["rate"].get("ok")), _ok(res["checks"]["hz"].get("ok")), " | ".join(_plain(w) for w in res["warnings"])]
        for j, v in enumerate(row, 1):
            ws.cell(i, j, v)
    w2 = wb.create_sheet("Stats")
    w2.cell(1, 1, f"{spec['name']} · {_std_plain(spec)}").font = Font(bold=True, size=13)
    r = 3
    for title, mk in (("Included replicates", mask), ("All replicates", [True] * len(reps))):
        w2.cell(r, 1, title).font = bold
        r += 1
        for j, h in enumerate(["Output", "Unit", "Mean", "SD", "COV (%)", "n", "Min", "Max"], 1):
            w2.cell(r, j, h).font = bold
        r += 1
        for o, s in _stats_table(spec, reps, mk):
            for j, v in enumerate([_plain(o["label"]), _plain(o["unit"]), s["mean"], s["sd"], s["cov"], s["n"], s["min"], s["max"]], 1):
                w2.cell(r, j, v)
            r += 1
        r += 1
    w3 = wb.create_sheet("Batch and settings")
    rr = 1
    for k, v in _batch_rows(batch) + _settings_rows(run["test"], run["settings"]):
        w3.cell(rr, 1, k); w3.cell(rr, 2, v); rr += 1
    for dv in run["settings"].get("deviations", []):
        w3.cell(rr, 1, "Change from the standard"); w3.cell(rr, 2, dv); rr += 1
    for s in (ws, w2, w3):
        s.column_dimensions["A"].width = 40
        s.column_dimensions["B"].width = 24
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def _num(v):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return None
    return float(v)


# ---------------------------------------------------------------- PDF
def _pdf(run, batch, mask, reasons):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    plt.rcParams.update({"font.size": 8.5, "font.family": "DejaVu Sans", "axes.edgecolor": "#4A4A47",
                         "axes.labelcolor": "#1C1C1A", "xtick.color": "#4A4A47", "ytick.color": "#4A4A47"})
    spec = specs.TESTS[run["test"]]
    reps = run["reps"]
    n_inc = sum(mask)
    pages = 2 + len(reps)
    bio = io.BytesIO()
    W, H = 8.5, 11
    stamp = _dt.date.today().isoformat()

    def frame(fig, page, title, sub):
        fig.text(0.07, 0.955, title, fontsize=15, weight="bold", color=NAVY)
        fig.text(0.07, 0.935, sub, fontsize=9, color="#4A4A47")
        fig.add_artist(plt.Line2D([0.07, 0.93], [0.925, 0.925], color=ORANGE, lw=2))
        fig.text(0.07, 0.03, "Cracking Test Analyzer v" + VERSION + " · akashto.com/cracking-index · Check results against the standard before use.",
                 fontsize=7, color="#6A6862")
        fig.text(0.93, 0.03, f"Page {page} of {pages}", fontsize=7, color="#6A6862", ha="right")

    def table(fig, x, y, rows, widths, size=8, bold_first=True, line=0.017):
        for i, row in enumerate(rows):
            xx = x
            for j, (cell, w) in enumerate(zip(row, widths)):
                fig.text(xx, y - i * line, str(cell), fontsize=size,
                         weight="bold" if (bold_first and i == 0) else "normal",
                         color=NAVY if (bold_first and i == 0) else "#1C1C1A")
                xx += w
        return y - len(rows) * line

    with PdfPages(bio) as pdf:
        # page 1: summary
        fig = plt.figure(figsize=(W, H))
        b = batch or {}
        sub = " · ".join(x for x in [b.get("project"), b.get("mix"), f"{len(reps)} replicates · {n_inc} included"] if x)
        frame(fig, 1, f"{spec['name']} summary report", sub + f" · Generated {stamp}")
        y = 0.9
        fig.text(0.07, y, "Batch", weight="bold", color=NAVY, fontsize=10)
        y = table(fig, 0.07, y - 0.02, [(k, v) for k, v in _batch_rows(batch)], [0.16, 0.25], bold_first=False)
        y2 = 0.9
        fig.text(0.52, y2, "Protocol and settings", weight="bold", color=NAVY, fontsize=10)
        table(fig, 0.52, y2 - 0.02, _settings_rows(run["test"], run["settings"]), [0.16, 0.26], bold_first=False, size=7.5)
        y = min(y, 0.74) - 0.02
        fig.text(0.07, y, "Results, included replicates", weight="bold", color=NAVY, fontsize=10)
        rows = [("Output", "Mean", "SD", "COV", "n")]
        for o, s in _stats_table(spec, reps, mask):
            if not o.get("main"):
                continue
            rows.append((_plain(o["label"]) + (f" ({_plain(o['unit'])})" if o["unit"] else ""), _fmt(s["mean"], o["dp"]),
                         _fmt(s["sd"], o["dp"]), "–" if s["cov"] is None else f"{s['cov']:.1f}%", s["n"]))
        y = table(fig, 0.07, y - 0.022, rows, [0.42, 0.13, 0.13, 0.1, 0.06])
        y -= 0.015
        fig.text(0.07, y, "Replicates", weight="bold", color=NAVY, fontsize=10)
        keys = spec["table"]
        olab = {o["key"]: o for o in spec["outputs"]}
        rows = [["Specimen"] + [SHORT.get(k, k) for k in keys] + ["Status"]]
        for rep, m, why in zip(reps, mask, reasons):
            o = rep["res"]["outputs"]
            st = "Included" if m else f"Excluded · {why}"
            if rep["res"]["warnings"]:
                st += " · warnings"
            rows.append([rep["label"][:22]] + [_fmt(o.get(k), olab[k]["dp"]) if not (olab[k].get("sci") and o.get(k) is not None) else f"{o.get(k):.3g}" for k in keys] + [st[:34]])
        wcol = [0.17] + [0.1] * len(keys) + [0.25]
        y = table(fig, 0.07, y - 0.022, rows, wcol, size=7.5)
        # plots
        ax = fig.add_axes([0.08, 0.14, 0.5, max(0.18, y - 0.2)])
        for i, (rep, m) in enumerate(zip(reps, mask)):
            pl = rep["res"]["plot"]
            s = next((q for q in pl["series"] if q["cls"] == "fit" and q["pts"][0][0] < 0.05 * max(1e-9, q["pts"][-1][0])), pl["series"][0])
            xs = [p[0] for p in s["pts"]]
            ys = [p[1] for p in s["pts"]]
            ax.plot(xs, ys, lw=1.4 if m else 0.9, ls="-" if m else "--", color=PAL[i % len(PAL)] if m else GREY,
                    label=rep["label"] + ("" if m else " (excluded)"))
        ax.set_xlabel(_plain(reps[0]["res"]["plot"]["x"]) if reps else "")
        ax.set_ylabel("Load (kN)")
        ax.set_ylim(bottom=0)
        ax.set_xlim(left=0)
        ax.legend(fontsize=7, frameon=False)
        ax.set_title("Load curves. Grey dashed: excluded.", fontsize=8, loc="left")
        ax2 = fig.add_axes([0.66, 0.14, 0.27, max(0.18, y - 0.2)])
        ik = spec["index"]
        vals = [rep["res"]["outputs"].get(ik) for rep in reps]
        cols = [ORANGE if m else GREY for m in mask]
        ax2.bar(range(len(vals)), [v if v is not None and math.isfinite(v) else 0 for v in vals], color=cols)
        inc = [v for v, m in zip(vals, mask) if m and v is not None and math.isfinite(v)]
        if inc:
            ax2.axhline(np.mean(inc), color=NAVY, lw=1)
        ax2.set_xticks(range(len(vals)))
        ax2.set_xticklabels([r["label"][-6:] for r in reps], rotation=45, fontsize=7)
        ax2.set_title(f"{SHORT.get(ik, ik)} by replicate. Line: included mean.", fontsize=8, loc="left")
        dev = run["settings"].get("deviations", [])
        exc = [f"{r['label']} excluded: {w}." for r, m, w in zip(reps, mask, reasons) if not m]
        msg = ("Changes from the standard: " + (" ".join(dev) if dev else "none.") + " " + " ".join(exc)).strip()
        if n_inc < spec["min_reps"]:
            msg += f" Only {n_inc} replicates are included. The standard asks for at least {spec['min_reps']}."
        fig.text(0.07, 0.07, msg[:240], fontsize=7.5, color="#8A2E0A" if (dev or exc) else "#1B6B3A", wrap=True)
        pdf.savefig(fig)
        plt.close(fig)

        # one page per replicate
        for i, (rep, m, why) in enumerate(zip(reps, mask, reasons)):
            res = rep["res"]
            fig = plt.figure(figsize=(W, H))
            frame(fig, i + 2, rep["label"], f"{rep['file']} · " + ("Included" if m else f"Excluded · {why}") + f" · {res['segment']}")
            ax = fig.add_axes([0.1, 0.52, 0.83, 0.37])
            pl = res["plot"]
            for s in pl["series"]:
                xs, ys = [p[0] for p in s["pts"]], [p[1] for p in s["pts"]]
                if s["cls"] == "raw":
                    ax.plot(xs, ys, ".", ms=2.4, color=GREY, label=_plain(s["name"]), zorder=3)
                else:
                    ax.plot(xs, ys, "-", lw=1.6, color=ORANGE, label=_plain(s["name"]))
            for ln in pl.get("lines", []):
                ax.plot([p[0] for p in ln["pts"]], [p[1] for p in ln["pts"]], "--", lw=1.1, color=NAVY, label=_plain(ln["name"]))
            for p in pl.get("points", []):
                if p["x"] is None or p["y"] is None:
                    continue
                ax.plot([p["x"]], [p["y"]], "o", ms=4, mfc="white", mec=NAVY)
                ax.annotate(_plain(p["name"]), (p["x"], p["y"]), xytext=(4, 4), textcoords="offset points", fontsize=7, color=NAVY)
            ax.set_xlabel(_plain(pl["x"]))
            ax.set_ylabel(_plain(pl["y"]))
            ax.set_xlim(left=0)
            ax.set_ylim(bottom=0)
            ax.legend(fontsize=7, frameon=False)
            y = 0.47
            fig.text(0.07, y, "Outputs", weight="bold", color=NAVY, fontsize=10)
            rows = [("Output", "Value", "Unit")]
            for o in spec["outputs"]:
                v = res["outputs"].get(o["key"])
                rows.append((_plain(o["label"]), (f"{v:.4g}" if o.get("sci") and v is not None else _fmt(v, o["dp"])), _plain(o["unit"])))
            table(fig, 0.07, y - 0.022, rows, [0.32, 0.1, 0.08], size=7.5, line=0.0165)
            fig.text(0.6, y, "Specimen and checks", weight="bold", color=NAVY, fontsize=10)
            ch = res["checks"]
            rows = [(d["label"], f"{res['dims'].get(d['key']):.2f} mm" if res["dims"].get(d["key"]) is not None else "–") for d in spec["dims"]]
            rt = ch["rate"]
            rows.append(("Loading rate", f"{_ok(rt.get('ok'))} {rt['value']:.4g} {spec['rate_unit']}" if rt.get("value") is not None else "–"))
            hz = ch["hz"]
            rows.append(("Sampling", f"{_ok(hz.get('ok'))} {hz['value']:.1f} Hz" if hz.get("value") is not None else "–"))
            rows.append(("Dimensions", _ok(ch["dims"]["ok"])))
            yy = table(fig, 0.6, y - 0.022, rows, [0.17, 0.16], size=7.5, bold_first=False, line=0.0165)
            yy -= 0.01
            for w in res["warnings"][:6]:
                fig.text(0.6, yy, "! " + _plain(w)[:60], fontsize=7, color="#8A2E0A")
                yy -= 0.015
            for nt in res["notes"][:4]:
                fig.text(0.6, yy, _plain(nt)[:62], fontsize=7, color="#4A4A47")
                yy -= 0.015
            pdf.savefig(fig)
            plt.close(fig)

        # methods page
        fig = plt.figure(figsize=(W, H))
        frame(fig, pages, "Methods and references", f"{spec['name']} · {_std_plain(spec)}")
        y = 0.89
        for para in _method_text(run["test"], run["settings"]):
            for ln in _wrap(para, 105):
                fig.text(0.07, y, ln, fontsize=8)
                y -= 0.016
            y -= 0.008
        y -= 0.01
        fig.text(0.07, y, "References", weight="bold", color=NAVY, fontsize=10)
        y -= 0.022
        for ref in spec["refs"]:
            for ln in _wrap(ref, 105):
                fig.text(0.07, y, ln, fontsize=8)
                y -= 0.016
            y -= 0.006
        pdf.savefig(fig)
        plt.close(fig)
    return bio.getvalue()


def _wrap(s, n):
    words, lines, cur = s.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > n:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines


def _method_text(test, st):
    spec = specs.TESTS[test]
    common = (f"Loads were converted to kN, displacements to mm and time to s. Displacement was set to zero at the first point at or above "
              f"{st['start_load']:g} kN. The record ends at the first point after the peak below {st['end_load']:g} kN. "
              f"Loading rate is a line fit of the control displacement vs. time from 25% of peak (rising) to the end of the record. "
              f"Sampling rate is 1 / median time step. Checks warn only.")
    if spec.get("tol_note"):
        common += " " + spec["tol_note"]
    t = {
        "ifit": ["Pre-peak: 6th-order polynomial, integrated at u0/1000 steps. Seating energy 0.5 u_r P_r from the initial slope (T 393 X1.3.1.5). "
                 "Post-peak: 4-term Gaussian sum, bounds ±10 on d and e, f lower bound tried at 0.9, 0.7, 0.5, 0.3, 0.1, 0.05, 0.01, 0.005, 0.001 until R² > 0.997. "
                 "Inflection points are roots of the second derivative with a negative slope. The tangent must stay at or below the curve until it drops to 30% of P_i; "
                 "of the candidates that pass, the steepest is used. Post-peak work is integrated at 0.005 mm steps.",
                 "Gf = Wf / ((r − a) t) × 10^6. FI = Gf / |m| × 0.01. Strength P/(2rt) and secant modulus at u0/2 are extra outputs, not part of T 393.",
                 "Other indices, not part of T 393: CRI = Gf / Pmax (Kaseer et al. 2018). BCI = 0.01 Gf L75 (Majidifard et al. 2021), with L75 the LLD where the load falls to 75% of peak after the peak, on the fitted curve in fitted mode and the recorded data in raw mode."],
        "idealct": ["Wf is the trapezoid area of the recorded curve from the start load to 100 N. Gf = Wf / (D t) × 10^6. "
                    "l85, l75, l65 are the first crossings after the peak (on the fitted curve in fitted mode, on the recorded data in raw mode). "
                    "|m75| is a least-squares line through all recorded points between l85 and l65, in N/m. CT index = (t/62)(l75/D)(Gf/|m75|) × 10^6.",
                    "Nflex (Yin et al. 2018): stress σ = 2P/(πtD), strain ε = μ Δ / D in %. T_inf is the area under σ–ε to the inflection point of the post-peak fit "
                    "(same routine as I-FIT). Nflex = T_inf / |s|, with s the σ–ε slope at the inflection point. μ is 0.35 or 0.15 + 0.35/(1 + exp(a + b S_c)), "
                    "S_c = Pmax/Δ_Pmax in kN/m; Ndesign a = −1.78, b = 6.45e-5; 7% air voids a = 0.25, b = 5.21e-5."],
        "donut": ["Wf is the trapezoid area of the recorded data from the contact load to termination. Gf = Wf / ((D − d) t) × 10^6. "
                  "Fitted mode follows draft Appendix A: cubic within ±0.5 mm of the recorded peak gives P100 and l100; a 4-term Gaussian with scaled bounds "
                  "(d within ±1.5 P100, e within l′100 ± L, f lower bound 0.20L down to 0.01L) is accepted at R² ≥ 0.997 with a monotonic drop to P75. "
                  "A rise of up to 0.5% of P100 just after the cubic peak is tolerated. |S75| is the secant from (l100, P100) to (l75, 0.75 P100). DI = Gf / |S75| × 0.001.",
                  "Nominal strength P100/((D − d) t) and secant modulus at l100/2 are extra outputs, not part of the draft."],
        "scb": ["Load vs. average LLD. W is the trapezoid area to u_c. The tail P = c/u² is fitted by least squares to post-peak points below 60% of peak; "
                "W_tail = c/u_c. When the record starts at 0.3 kN or more, triangle OO′A = P_0²/(2S) is added (T 394 Note 2). Gf = (W + W_tail + triangle) / ((r − a) t).",
                "K_IC = Y σ0 √(πa), σ0 = P/(2rt), Y = 4.782 − 1.219(a/r) + 0.063 exp(7.045 a/r). Stiffness S uses the SLT-SCB window method: "
                "a window of 15% of the pre-peak points, best R²_raw − 0.05 l_m², l_m = P_avg/P_max − 0.5."],
        "sltscb": ["G_f-pre = trapezoid area to the peak / ((r − a) t). Loading stiffness S: a window of 15% of the pre-peak points is moved along the ascending branch; "
                   "the window with the highest R²_penalized = R²_raw − 0.05 l_m² is used, with l_m = P_avg/P_max − 0.5. LCI = G_f-pre / S."],
        "dct": ["CMOD vs. time is fitted with a least-squares line over the record (D7313 8.1). CMOD_fit = slope × time. "
                "The area under load vs. CMOD_fit to 100 N uses the quadrangle rule. Gf = area / (B (W − a)). The CMOD rate check uses the fitted slope.",
                "Other index, not part of D7313: FST = Gf / Sf (Zhu et al. 2017), with fracture strength Sf = 2 Pmax (3W − a) / (B a²), a the ligament length and W the distance from the load line to the back edge (Apeagyei et al. 2006). FST is reported in 10^-6 m."],
        "idt": ["S_t = 2 P_f / (π b D), with P_f the peak load (T 322, 12.3). Creep compliance is not computed."],
    }[test]
    return [common] + t


# ---------------------------------------------------------------- zip
def build_zip(run, body):
    spec = specs.TESTS[run["test"]]
    reps = run["reps"]
    batch = body.get("batch") or {}
    mask = [bool(x) for x in (body.get("included") or [True] * len(reps))]
    reasons = list(body.get("reasons") or [""] * len(reps))
    opt = body.get("options") or {}
    proj = _slug(batch.get("project"), "Project")
    mix = _slug(batch.get("mix"), "Mix")
    tname = _slug(spec["name"], run["test"])
    base = f"{proj}_{tname}_{mix}"
    zb = io.BytesIO()
    with zipfile.ZipFile(zb, "w", zipfile.ZIP_DEFLATED) as z:
        for rep, m, why in zip(reps, mask, reasons):
            if not m and not opt.get("include_excluded", True):
                continue
            lab = _slug(rep["label"], "replicate")
            if opt.get("format", "xlsx") == "csv":
                z.writestr(f"{base}_{lab}.csv", _replicate_csv(rep))
            else:
                z.writestr(f"{base}_{lab}.xlsx", _replicate_xlsx(run, rep, batch, m, why))
        z.writestr(f"{base}_batch-summary.xlsx", _summary_xlsx(run, batch, mask, reasons))
        z.writestr(f"{base}_summary.pdf", _pdf(run, batch, mask, reasons))
        settings = {
            "tool": f"Cracking Test Analyzer v{VERSION}", "test": run["test"], "standard": _std_plain(spec),
            "batch": batch, "settings": {k: v for k, v in run["settings"].items()},
            "replicates": [{"label": r["label"], "file": r["file"], "mapping": r["mapping"], "dimensions": r["res"]["dims"],
                            "included": m, "reason": why} for r, m, why in zip(reps, mask, reasons)],
        }
        z.writestr(f"{base}_settings.json", json.dumps(core.clean(settings), indent=2, ensure_ascii=False))
    return zb.getvalue(), base + ".zip"
