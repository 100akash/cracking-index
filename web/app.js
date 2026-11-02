/* Cracking Test Analyzer: page logic. Four steps: test, upload, process, results.
   All calculations run in the engine (Python, in this tab). */
(function () {
  "use strict";
  const API = window.CTA_API;
  const ART = window.CTA_ART || {};
  const VER = window.CTA_VERSION || "";
  const app = document.getElementById("app");
  const stepsNav = document.getElementById("steps");

  /* ------------------------------------------------------------ state */
  const S = {
    step: 1, specs: null, order: null,
    domain: "service", test: "ifit", temp: "25.0", tempUnit: "C",
    files: [], active: null, confirmed: {}, checks: {}, previewFile: null,
    settings: {}, dimMode: "avg", dims: {}, labels: {},
    batch: { project: "", mix: "", date: new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10), vma: "", nmas: "", binder: "", pg: "" },
    preview: null, previewBusy: false,
    run: null, manual: {}, reasons: {}, outlier: false, curveSel: "all",
    exp: { format: "xlsx", include_excluded: true }, busy: false,
  };
  const spec = () => S.specs[S.test];

  /* ------------------------------------------------------------ helpers */
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fin = (v) => typeof v === "number" && isFinite(v);
  const fmt = (v, dp = 2) => (fin(v) ? (Math.abs(v) >= 1e5 ? v.toExponential(2).replace("e+", "e") : v.toFixed(dp)) : "–");
  const fmtSig = (v, n = 4) => (fin(v) ? Number(v.toPrecision(n)).toString() : "–");
  const stem = (n) => String(n).replace(/\.[^.]+$/, "");
  const toast = (msg, bad) => {
    const t = document.getElementById("toast");
    t.textContent = msg; t.className = "toast show" + (bad ? " bad" : "");
    clearTimeout(toast._t); toast._t = setTimeout(() => (t.className = "toast"), bad ? 6000 : 3000);
  };
  const ROLE_LABEL = { time: "Time", load: "Load", load2: "Load 2 (averaged)", lld: "LLD", lld2: "LLD 2 (averaged)", cmod: "CMOD", ignore: "Ignore" };
  const UNITS = {
    time: [["s", "s"], ["ms", "ms"], ["min", "min"]],
    load: [["kn", "kN"], ["n", "N"], ["lbf", "lbf"], ["kip", "kip"]],
    disp: [["mm", "mm"], ["in", "in"], ["um", "µm"]],
  };
  const unitKind = (role) => (role === "time" ? "time" : ["load", "load2"].includes(role) ? "load" : ["lld", "lld2", "cmod"].includes(role) ? "disp" : null);
  const unitText = (u) => ({ kn: "kN", n: "N", lbf: "lbf", kip: "kip", mm: "mm", in: "in", um: "µm", s: "s", ms: "ms", min: "min" }[u] || u || "");

  /* ------------------------------------------------------------ steps bar */
  const STEPS = ["Test", "Upload", "Process", "Results"];
  function canGo(n) {
    if (n === 1) return true;
    if (n === 2) return !!S.test;
    if (n === 3) return S.files.length > 0 && allConfirmed();
    if (n === 4) return !!S.run;
    return false;
  }
  function stepState(n) {
    if (n === 1) return S.test && String(S.temp).trim() !== "" ? "done" : "todo";
    if (n === 2) {
      if (!S.files.length || (S.seen || 1) < 2) return "todo";
      const bad = S.files.some((f) => { const c = S.checks[f.id]; return !c || c.error || (c.rate && c.rate.ok === false) || (c.hz && c.hz.ok === false); });
      return allConfirmed() && !bad ? "done" : "attn";
    }
    if (n === 3) {
      if (!S.files.length || (S.seen || 1) < 3) return "todo";
      if (!S.files.every((f) => dimsReady(f.id))) return "attn";
      return S.run ? "done" : "todo";
    }
    if (n === 4) {
      if (!S.run) return "todo";
      const { inc } = included();
      const cv = idxCov();
      const ok = inc.filter(Boolean).length >= S.specs[S.run.test].min_reps && S.run.replicates.every((r) => !r.error && !r.warnings.length) && !(cv != null && cv > COV_FLAG);
      return ok ? "done" : "attn";
    }
    return "todo";
  }
  const STATE_TITLE = { done: "Done", attn: "Needs your attention", todo: "Not started" };
  function renderSteps() {
    stepsNav.innerHTML = STEPS.map((t, i) => {
      const n = i + 1, cur = S.step === n, st = stepState(n);
      let sub = "";
      if (n === 1 && st === "done") sub = `: ${esc(spec().name)}, ${esc(S.temp || "–")} °${S.tempUnit}`;
      if (n === 2 && S.files.length) sub = `: ${S.files.length} file${S.files.length === 1 ? "" : "s"}`;
      return `<button class="step" data-go="${n}" ${cur ? 'aria-current="step"' : ""} ${canGo(n) ? "" : "disabled"} title="${STATE_TITLE[st]}">
        <span class="n ${st}">${n}</span><span>${t}${sub}</span></button>`;
    }).join("");
    const cur = stepsNav.querySelector("[aria-current]");
    if (cur && stepsNav.scrollWidth > stepsNav.clientWidth) stepsNav.scrollLeft = cur.offsetLeft - 16;
  }
  const mark = (st) => `<i class="si ${st}" title="${STATE_TITLE[st] || ""}" aria-label="${STATE_TITLE[st] || ""}"></i>`;
  function guide() {
    let txt = "", btn = "";
    if (S.step === 1) { txt = `Pick the test you ran and record the temperature. Then continue.`; btn = `<button class="btn primary small" data-go="2">Continue to upload</button>`; }
    else if (S.step === 2) {
      const gs = groups(), open = gs.findIndex(([s]) => !S.confirmed[s]);
      const bad = S.files.filter((f) => { const c = S.checks[f.id]; return c && ((c.rate && c.rate.ok === false) || (c.hz && c.hz.ok === false)); }).length;
      if (!S.files.length) { txt = "Add one file per replicate, or load the example files to try the tool."; btn = `<button class="btn small" data-act="examples">Load example files</button>`; }
      else if (open >= 0) { txt = `Check the column mapping for Format ${String.fromCharCode(65 + open)} and confirm it.`; btn = `<button class="btn primary small" data-act="gconfirm" data-sig="${esc(gs[open][0])}">Show mapping</button>`; }
      else { txt = bad ? `Mapping confirmed. ${bad} file${bad === 1 ? " has" : "s have"} a rate or sampling warning. You can still continue.` : "Mapping confirmed and loading checks pass. Continue to processing."; btn = `<button class="btn primary small" data-go="3">Continue to processing</button>`; }
    } else if (S.step === 3) {
      const p = S.files.filter((f) => !dimsReady(f.id)).length;
      if (p) { txt = `Enter the dimensions or accept the defaults for ${p} specimen${p === 1 ? "" : "s"}.`; btn = `<button class="btn soft small" data-act="acceptall">Accept all defaults</button>`; }
      else { txt = "Dimensions are in. Check the fit, then run the analysis."; btn = `<button class="btn primary small" data-act="run">Run analysis</button>`; }
    } else if (S.step === 4) {
      const sp4 = S.specs[S.run.test], { inc } = included(), nI = inc.filter(Boolean).length;
      const nW = S.run.replicates.filter((r) => r.error || (r.warnings && r.warnings.length)).length;
      const cv = idxCov();
      if (nW) txt = `${nW} replicate${nW === 1 ? " has" : "s have"} warnings. Read them in the Replicates table, then export.`;
      else if (nI < sp4.min_reps) txt = `Only ${nI} replicate${nI === 1 ? " is" : "s are"} included. ${esc(sp4.standard_plain || sp4.standard)} asks for at least ${sp4.min_reps}. Export, or include more.`;
      else if (cv != null && cv > COV_FLAG) txt = `All checks pass, but the ${esc(S.short[sp4.index] || sp4.index)} COV is ${cv.toFixed(1)}%. Look at the curves for an outlier, then export.`;
      else txt = "All replicates pass their checks. Review the results, then export.";
      btn = `<button class="btn primary small" data-act="export" ${S.busy ? "disabled" : ""}>${S.busy ? '<span class="busy"></span> Building files' : "Export results (.zip)"}</button>`;
    }
    return `<div class="guide"><span class="pill">Next</span><span class="gt">${txt}</span>${btn}</div>`;
  }
  function go(n) {
    if (!canGo(n)) return;
    S.step = n; S.seen = Math.max(S.seen || 1, n); render(); window.scrollTo(0, 0);
    if (n === 3) refreshPreview();
  }
  const footer = () => `<p class="disclaimer">Check results against the standard before use. Cite as: Bajaj, A. (2026). <i>Cracking Test Analyzer</i> (Version 0.1). akashto.com/cracking-index</p>
    <p class="verline">v0.1 · Made by Akash Bajaj · <a href="https://akashto.com" target="_blank" rel="noopener">akashto.com</a> · <a href="references.html">References</a> · <a href="https://github.com/100akash/cracking-index/blob/main/CHANGELOG.md" target="_blank" rel="noopener">Changes</a> · <a href="https://github.com/100akash/cracking-index/issues" target="_blank" rel="noopener">Report an issue</a></p>`;
  function render() {
    renderSteps();
    const f = [null, viewTest, viewUpload, viewProcess, viewResults][S.step];
    app.innerHTML = guide() + f() + footer();
    after();
  }
  let afterFns = [];
  function after() { const fns = afterFns; afterFns = []; fns.forEach((fn) => fn()); }

  /* ------------------------------------------------------------ step 1: test */
  function viewTest() {
    const order = S.order[S.domain];
    if (!order.includes(S.test)) S.test = order[0];
    const sp = spec();
    const cards = order.map((k) => {
      const t = S.specs[k], cur = k === S.test;
      const outs = [...new Set(t.outputs.filter((o) => o.main).map((o) => o.label))].join(", ");
      return `<article class="tcard" ${cur ? 'aria-current="true"' : ""}>
        ${cur ? '<span class="tag">Selected</span>' : ""}
        <div class="art">${ART[k] || ""}</div>
        <h3>${esc(t.name)}</h3>
        <span class="std">${t.standard} · ${esc(t.geometry)}</span>
        <div class="row"><span class="chip navy">${t.control_label} · ${fmtRate(t.rate)} ${t.rate_unit}</span></div>
        <p class="small muted">Outputs: ${outs}${k === "idealct" ? ", plus N<sub>flex</sub>." : "."}</p>
        <span class="small" style="color:var(--navy)"><strong>Needs:</strong> ${needsText(t)}</span>
        <span class="small muted oneline" title="${esc(t.temp_note)}">${esc(t.temp_note)}</span>
        <button class="btn${cur ? " navy" : ""}" data-act="pick" data-k="${k}">${cur ? "Selected" : "Select"}</button>
      </article>`;
    }).join("");
    return `<section class="stack"><h1>Choose your test</h1>
      <p class="lead">Pick the temperature domain, record the test temperature, then select the test you ran. You only process the test you need.</p></section>
      <section class="card">
        <div class="grid2">
          <div class="stack"><span class="label">Temperature domain</span>
            <div class="domain">
              <button data-act="domain" data-d="low" aria-pressed="${S.domain === "low"}"><b>Low temperature</b><span>SCB, SLT-SCB, DCT, IDT strength</span></button>
              <button data-act="domain" data-d="service" aria-pressed="${S.domain === "service"}"><b>Service temperature</b><span>I-FIT, IDEAL-CT, DONUT</span></button>
            </div></div>
          <div class="stack"><span class="label">Test temperature (record only)</span>
            <div class="row"><input type="text" inputmode="decimal" class="num" id="temp" value="${esc(S.temp)}" aria-label="Test temperature">
              <div class="seg" role="group" aria-label="Temperature unit"><button data-act="tunit" data-u="C" aria-pressed="${S.tempUnit === "C"}">°C</button><button data-act="tunit" data-u="F" aria-pressed="${S.tempUnit === "F"}">°F</button></div></div>
            <span class="small muted">The usual temperature is on each card.</span>
          </div>
        </div>
      </section>
      <section class="tests">${cards}</section>
      <div class="foot"><span>Selected: <strong>${esc(sp.name)}</strong> at ${esc(S.temp || "–")} °${S.tempUnit}</span>
        <button class="btn primary" data-go="2">Continue to upload</button></div>`;
  }
  const fmtRate = (r) => (r < 0.01 ? String(r) : String(+r.toFixed(3)));
  function needsText(t) {
    if (t.needs.length === 1) return "load (time and LLD for the rate check)";
    const m = { time: "time", load: "load", lld: "LLD", cmod: "CMOD" };
    let s = t.needs.map((x) => m[x]).join(", ");
    if (t.optional.includes("cmod")) s += " (CMOD optional)";
    return s;
  }

  /* ------------------------------------------------------------ step 2: upload */
  function groups() {
    const g = new Map();
    S.files.forEach((f) => { if (!g.has(f.signature)) g.set(f.signature, []); g.get(f.signature).push(f); });
    return [...g.entries()];
  }
  function allConfirmed() { return groups().every(([sig]) => S.confirmed[sig]); }
  function groupNeedsReview(files) {
    const f = files[0];
    return f.notes.length > 0 || f.cols.some((c) => c.role !== "ignore" && c.unit_source !== "header") || missingRoles(f).length > 0;
  }
  function missingRoles(f) {
    const roles = Object.values(f.cols).reduce((a, c) => (a[c.role] = 1, a), {});
    return spec().needs.filter((r) => !roles[r]);
  }
  function viewUpload() {
    const sp = spec();
    const gs = groups();
    if (gs.length && !gs.find(([s]) => s === S.active)) S.active = gs[0][0];
    const gHtml = gs.map(([sig, fs], i) => {
      const ok = S.confirmed[sig];
      const m = fs[0].meta;
      const desc = [m.format === "xlsx" ? "Excel sheet" : (m.delimiter || "") + " separated",
        m.units_row ? "units row" : "no units row", fs[0].time_reset ? "time resets" : null, `${fs[0].header.length} columns`].filter(Boolean).join(" · ");
      return `<div class="group" role="button" tabindex="0" data-act="group" data-sig="${esc(sig)}" ${sig === S.active ? 'aria-current="true"' : ""}>
        <div class="row"><strong>Format ${String.fromCharCode(65 + i)}</strong><span class="small muted">${esc(desc)}</span><span class="spacer"></span>
          ${ok ? '<span class="chip ok">✓ Mapping confirmed</span>' : '<span class="chip warn">Review mapping</span>'}</div>
        <div class="filelist">${fs.map((f) => `<span>${esc(f.name)} · ${f.rows} rows <button class="x" data-act="rmfile" data-id="${f.id}" aria-label="Remove ${esc(f.name)}">✕</button></span>`).join("")}</div>
      </div>`;
    }).join("");
    const errs = S.fileErrors && S.fileErrors.length ? `<div class="notice err"><strong>Some files could not be read.</strong><ul>${S.fileErrors.map((e) => `<li>${esc(e.name)}: ${esc(e.error)}</li>`).join("")}</ul></div>` : "";
    const nReview = gs.filter(([s]) => !S.confirmed[s]).reduce((a, [, fs]) => a + fs.length, 0);
    return `<section class="stack"><h1>Upload test files</h1>
      <p class="lead">Add one file per replicate. The tool reads each file's columns, guesses time, load, LLD and CMOD, and asks you to confirm.</p></section>
      <div class="grid-side">
        <section class="card">
          <div class="drop" id="drop"><svg width="40" height="40" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4M7 9l5-5 5 5M5 20h14" stroke="#13294B" stroke-width="2" fill="none" stroke-linecap="round"/></svg>
            <strong>Drop CSV, TXT or XLSX files here</strong><span class="small muted">Select several at once.</span>
            <div class="row"><label class="btn navy">Browse files<input type="file" id="fileinput" multiple accept=".csv,.txt,.tsv,.dat,.xlsx,.xlsm" class="hidden"></label>
            <button class="btn" data-act="examples">Load example files</button></div>
            <span class="small muted">Example files are synthetic curves for a made-up Mix A.</span>
          </div>
          ${errs}
          ${gs.length ? `<div class="groups">${gHtml}</div>` : ""}
        </section>
        <section class="card"><h3>What the tool needs for ${esc(sp.name)}</h3>
          <p class="small"><strong>Needs:</strong> ${needsText(sp)}</p>
          <p class="small muted">${sp.control_label} at ${fmtRate(sp.rate)} ${sp.rate_unit}. Target ${esc(rateTarget(sp))}. Sampling at least ${sp.min_hz} Hz.</p>
          ${sp.tol_note ? `<p class="small muted">${esc(sp.tol_note)}</p>` : ""}
          <p class="small muted">Units are read from the header or units row. When a file does not say, the tool guesses from the values and asks you to check.</p>
        </section>
      </div>
      ${S.active ? mappingCard(gs.find(([s]) => s === S.active)) : ""}
      ${S.files.length ? checksCard() : ""}
      <div class="foot"><button class="btn" data-go="1">Back</button>
        <span class="spacer"></span>${nReview ? `<span class="small warn">${nReview} file${nReview === 1 ? "" : "s"} need${nReview === 1 ? "s" : ""} the mapping confirmed</span>` : ""}
        <button class="btn primary" data-go="3" ${canGo(3) ? "" : "disabled"}>Continue to processing</button></div>`;
  }
  function rateTarget(sp) {
    if (sp.tol_note || Math.abs(sp.rate_tol / sp.rate - 0.05) < 1e-9) return `${fmtRate(sp.rate)} ${sp.rate_unit} ± 5%`;
    return `${fmtRate(sp.rate)} ± ${+sp.rate_tol.toFixed(4)} ${sp.rate_unit}`;
  }
  function mappingCard([sig, fs]) {
    const f = fs[0], sp = spec();
    const roles = ["time", "load", "load2", "lld", "lld2", "cmod", "ignore"];
    const rows = f.cols.map((c) => {
      const kind = unitKind(c.role);
      const unitSel = kind ? `<select data-act="unit" data-i="${c.index}" aria-label="Unit for ${esc(c.name)}">${UNITS[kind].map(([v, l]) => `<option value="${v}" ${c.unit === v ? "selected" : ""}>${l}</option>`).join("")}</select>
        ${c.unit_source === "guess" ? '<span class="chip warn" title="Guessed from the values">check</span>' : ""}` : '<span class="muted">–</span>';
      const note = [];
      if (c.role === "time" && f.time_reset) note.push("Time resets after the contact hold. The part before the last reset is dropped.");
      if (c.role === "lld2") note.push("Averaged with LLD.");
      if (c.role === "load2") note.push("Averaged with Load.");
      if (/actuator|stroke|position|ram/i.test(c.name) && c.role === "lld") note.push("Machine stroke. Zeroed at the start load.");
      return `<tr><td><strong>${esc(c.name)}</strong>${c.unit_text ? ` <span class="muted small">(${esc(c.unit_text)})</span>` : ""}</td>
        <td>${unitSel}</td><td class="mono small">${c.first.map((v) => fmtSig(v, 5)).join(", ")}</td>
        <td><select data-act="role" data-i="${c.index}" aria-label="Role for ${esc(c.name)}">${roles.map((r) => `<option value="${r}" ${c.role === r ? "selected" : ""}>${ROLE_LABEL[r]}</option>`).join("")}</select></td>
        <td class="small muted">${note.join(" ")}</td></tr>`;
    }).join("");
    const miss = missingRoles(f);
    const notes = [...f.notes];
    if (!f.cols.some((c) => c.role === "cmod") && !sp.needs.includes("cmod")) notes.push(`No CMOD column found. ${sp.name} does not need one.`);
    return `<section class="card"><div class="row"><h3>${mark(S.confirmed[sig] ? "done" : "attn")}Column mapping · ${fs.length} file${fs.length === 1 ? "" : "s"} with this header</h3><span class="spacer"></span>
        ${S.confirmed[sig] ? '<span class="chip ok">✓ Confirmed</span>' : `<button class="btn primary small" data-act="confirm" data-sig="${esc(sig)}" ${miss.length ? "disabled" : ""}>Confirm mapping</button>`}</div>
      <div class="tblwrap"><table class="tbl"><thead><tr><th>Column in file</th><th>Unit</th><th>First values</th><th>Role</th><th>Note</th></tr></thead><tbody>${rows}</tbody></table></div>
      ${miss.length ? `<div class="notice">Map a column to: ${miss.map((r) => ROLE_LABEL[r]).join(", ")}.</div>` : ""}
      ${notes.length ? `<ul class="small muted" style="margin:0;padding-left:18px">${notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
    </section>`;
  }
  function checksCard() {
    const sp = spec();
    const rows = S.files.map((f) => {
      const c = S.checks[f.id];
      if (!c) return `<tr><td>${esc(stem(f.name))}</td><td colspan="4"><span class="busy"></span></td></tr>`;
      if (c.error) return `<tr><td>${esc(stem(f.name))}</td><td colspan="4" class="bad">${esc(c.error)}</td></tr>`;
      const r = c.rate, hz = c.hz;
      const rt0 = r.value == null ? `<span class="muted">${esc(r.text || "–")}</span>` : `<span class="${r.ok ? "ok" : "bad"}">${r.ok ? "✓" : "✗"} ${fmtSig(r.value, 4)} ${sp.rate_unit}</span>`;
      const hzt = hz.value == null ? '<span class="muted">–</span>' : `<span class="${hz.ok ? "ok" : "bad"}">${hz.ok ? "✓" : "✗"} ${fmt(hz.value, 1)} Hz</span>`;
      const rt = rt0;
      return `<tr><td>${esc(stem(f.name))}</td><td style="white-space:nowrap">${rt}</td><td class="small muted">${esc(rateTarget(sp))}</td><td style="white-space:nowrap">${hzt}</td><td class="small">${esc(c.segment)}${c.missing && c.missing.length ? ` · <span class="warn">missing ${c.missing.join(", ")}</span>` : ""}</td></tr>`;
    }).join("");
    if (!S.previewFile || !S.files.find((f) => f.id === S.previewFile)) S.previewFile = S.files[0].id;
    const pc = S.checks[S.previewFile];
    afterFns.push(() => {});
    return `<div class="grid2">
      <section class="card"><h3>${mark(S.files.every((f) => { const c = S.checks[f.id]; return c && !c.error && c.rate.ok !== false && c.hz.ok !== false; }) ? "done" : "attn")}Loading checks</h3>
        <div class="tblwrap"><table class="tbl"><thead><tr><th>File</th><th>${sp.control === "cmod" ? "CMOD" : "LLD"} rate</th><th>Target</th><th>Sampling</th><th>Segment</th></tr></thead><tbody>${rows}</tbody></table></div>
        <p class="small muted">Rate is a line fit of ${sp.control === "cmod" ? "CMOD" : "LLD"} vs. time from 25% of peak (rising) to the ${sp.end_load} kN cut-off${S.test === "dct" ? " (D7313 uses the slope of CMOD vs. time over the whole record)" : ""}. Checks warn only. They never block a run.</p>
      </section>
      <section class="card"><div class="row"><h3>Preview</h3><span class="spacer"></span>
        <div class="tabs">${S.files.map((f) => `<button data-act="pfile" data-id="${f.id}" aria-pressed="${f.id === S.previewFile}">${esc(stem(f.name))}</button>`).join("")}</div></div>
        ${pc && pc.plot ? plotSVG({ series: [{ cls: "raw", pts: pc.plot, name: "Recorded" }], x: S.test === "dct" ? "CMOD (mm), zeroed at the start load" : "LLD (mm), zeroed at the start load", y: "Load (kN)" }, { h: 300, band: pc.trim }) : '<p class="muted small">Pick the columns to see the curve.</p>'}
        <p class="small muted">Shaded: the part kept after the start and end trims.</p>
      </section></div>`;
  }

  /* ------------------------------------------------------------ step 3: process */
  function defaultsFor(test) {
    const t = S.specs[test];
    return { mode: t.mode, start_load: t.start_load, end_load: t.end_load, seating: t.seating, tare: false, poisson: "fixed", mu: 0.35, mix: "design", window: 0.15 };
  }
  function viewProcess() {
    const sp = spec(), st = S.settings;
    const std = sp.standard_plain || sp.standard;
    const dev = [];
    const d = defaultsFor(S.test);
    if (st.mode !== d.mode) dev.push("data mode");
    if (+st.start_load !== d.start_load || +st.end_load !== d.end_load) dev.push("trim");
    if (st.seating !== d.seating) dev.push("seating energy");
    if (st.tare) dev.push("load tare");
    const fitTests = ["ifit", "idealct", "donut"];
    const settings = `<section class="card"><h3>${mark(dev.length ? "attn" : "done")}Settings</h3>
      ${fitTests.includes(S.test) ? `<div class="stack" style="gap:6px"><span class="label">Data mode</span>
        <div class="seg" role="group"><button data-act="mode" data-v="fitted" aria-pressed="${st.mode === "fitted"}">Fitted</button><button data-act="mode" data-v="raw" aria-pressed="${st.mode === "raw"}">Raw</button></div>
        <span class="small muted">${sp.fit_note}</span></div>` : `<div class="stack" style="gap:6px"><span class="label">Data mode</span><span class="small">Raw data. ${sp.fit_note}</span></div>`}
      <div class="stack" style="gap:6px"><span class="label">Displacement zero</span><span class="small">At the start load, for every replicate</span></div>
      <div class="stack" style="gap:6px"><span class="label">Trim</span>
        <div class="row"><label class="f">Start at load (kN)<input type="text" inputmode="decimal" class="num" data-set="start_load" value="${st.start_load}"></label>
        <label class="f">End below load (kN)<input type="text" inputmode="decimal" class="num" data-set="end_load" value="${st.end_load}"></label></div></div>
      ${["ifit", "scb"].includes(S.test) ? `<label class="toggle"><input type="checkbox" data-set="seating" ${st.seating ? "checked" : ""}><span>Add seating energy<small>${esc(sp.seating_note)}</small></span></label>` : ""}
      <label class="toggle"><input type="checkbox" data-set="tare" ${st.tare ? "checked" : ""}><span>Tare load<small>Subtract the first load reading from every load. Lowers G<sub>f</sub> by a few percent. Flagged when on.</small></span></label>
      ${S.test === "idealct" ? `<div class="stack" style="gap:6px"><span class="label">Poisson's ratio for N<sub>flex</sub></span>
        <div class="seg" role="group"><button data-act="poisson" data-v="fixed" aria-pressed="${st.poisson === "fixed"}">Fixed 0.35</button><button data-act="poisson" data-v="sc" aria-pressed="${st.poisson === "sc"}">From secant stiffness</button></div>
        ${st.poisson === "sc" ? `<div class="seg" role="group"><button data-act="mix" data-v="design" aria-pressed="${st.mix === "design"}">N<sub>design</sub> specimens</button><button data-act="mix" data-v="av7" aria-pressed="${st.mix === "av7"}">7% air voids</button></div>` : ""}
        <span class="small muted">Yin et al. (2018). μ = 0.15 + 0.35/(1 + e<sup>a + b·S<sub>c</sub></sup>), S<sub>c</sub> = P<sub>max</sub>/Δ<sub>Pmax</sub>.</span></div>` : ""}
      ${dev.length ? `<div class="notice">Changed from ${std}: ${dev.join(", ")}. This is flagged in the report.</div>` : ""}
      <button class="linkbtn" data-act="resetset">Reset to ${std} defaults</button>
    </section>`;
    const pv = S.preview;
    const pf = S.files.find((f) => f.id === S.previewFile) || S.files[0];
    S.previewFile = pf.id;
    let pvHtml = '<p class="muted small"><span class="busy"></span> Fitting…</p>';
    if (pv && pv.error) pvHtml = `<div class="notice err">${esc(pv.error)}</div>`;
    else if (pv && !S.previewBusy) {
      const o = pv.outputs;
      const chips = [];
      if (fin(o.r2_pre)) chips.push(`<span class="chip ${o.r2_pre >= 0.997 ? "ok" : "warn"}">${o.r2_pre >= 0.997 ? "✓" : "!"} Pre-peak R² ${fmt(o.r2_pre, 4)}</span>`);
      if (fin(o.r2_post)) chips.push(`<span class="chip ${o.r2_post >= 0.997 ? "ok" : "warn"}">${o.r2_post >= 0.997 ? "✓" : "!"} Post-peak R² ${fmt(o.r2_post, 4)} (≥ 0.997)</span>`);
      const idx = sp.outputs.find((x) => x.key === sp.index);
      chips.push(`<span class="chip navy">${idx.label} ${fmtOut(idx, o[idx.key])}</span>`);
      pvHtml = plotSVG(pv.plot, { h: 330 }) + legend(pv.plot) + `<div class="row">${chips.join("")}</div>` +
        (pv.warnings.length ? `<div class="notice"><ul>${pv.warnings.map((w) => `<li>${w}</li>`).join("")}</ul></div>` : "") +
        (pv.notes.length ? `<p class="small muted">${pv.notes.join(" ")}</p>` : "") +
        `<p class="small muted">Preview uses this replicate's current dimensions${dimsReady(pf.id) ? "" : " (defaults until confirmed)"}.</p>`;
    }
    const preview = `<section class="card"><div class="row"><h3>${mark(pv && pv.outputs && !pv.warnings.length ? "done" : pv && (pv.error || (pv.warnings && pv.warnings.length)) ? "attn" : "todo")}Fit preview</h3><span class="spacer"></span>
      <div class="tabs">${S.files.map((f) => `<button data-act="pv" data-id="${f.id}" aria-pressed="${f.id === S.previewFile}">${esc(label(f))}</button>`).join("")}</div></div>${pvHtml}</section>`;
    const b = S.batch;
    const batch = `<section class="card"><h3>Batch details (optional)</h3><p class="small muted">For the record and the report. Not used in calculations.</p>
      <div class="fgrid4">
        ${bf("project", "Project ID")}${bf("mix", "Mix ID")}<label class="f">Test date<input type="date" data-batch="date" value="${esc(b.date)}"></label>
        <label class="f">Test temperature (°${S.tempUnit})<input type="text" inputmode="decimal" id="temp2" value="${esc(S.temp)}"></label>
        ${bf("vma", "Design VMA (%)")}${bf("nmas", "NMAS (mm)")}${bf("binder", "Binder content (%)")}${bf("pg", "Binder PG", "e.g. 64-22")}
      </div></section>`;
    const ready = S.files.every((f) => dimsReady(f.id));
    const pending = S.files.filter((f) => !dimsReady(f.id)).length;
    const checks = S.files.map((f) => S.checks[f.id]).filter(Boolean);
    const badChecks = checks.filter((c) => (c.rate && c.rate.ok === false) || (c.hz && c.hz.ok === false)).length;
    const runCard = `<section class="card navy"><ul class="small checklist">
        <li class="ok">✓ ${S.files.length} file${S.files.length === 1 ? "" : "s"} mapped</li>
        <li class="${dev.length ? "warn" : "ok"}">${dev.length ? "! Settings differ from " + std : "✓ Settings follow " + std}</li>
        ${badChecks ? `<li class="warn">! ${badChecks} file${badChecks === 1 ? "" : "s"} with a rate or sampling warning</li>` : ""}
        ${pending ? `<li class="warn">! ${pending} specimen${pending === 1 ? "" : "s"} still show grey defaults. Type values or accept the defaults to run.</li>` : '<li class="ok">✓ Dimensions entered</li>'}</ul>
      <button class="btn primary run" data-act="run" ${ready && !S.busy ? "" : "disabled"}>${S.busy ? '<span class="busy"></span> Running' : `Run analysis · ${S.files.length} replicate${S.files.length === 1 ? "" : "s"}`}</button></section>`;
    return `<section class="stack"><h1>Process</h1><p class="lead">Check the settings, look at the fit, enter specimen details, then run. Defaults follow ${std}. Anything you change from the standard is flagged in the report.</p></section>
      <div class="grid-side narrow">${preview}${settings}</div>
      ${batch}${dimsCard()}${runCard}
      <div class="foot"><button class="btn" data-go="2">Back</button></div>`;
  }
  const bf = (k, l, ph) => `<label class="f">${l}<input type="text" data-batch="${k}" value="${esc(S.batch[k])}"${ph ? ` placeholder="${ph}"` : ""}></label>`;
  function label(f) { return S.labels[f.id] != null ? S.labels[f.id] : stem(f.name); }

  /* dimensions: per file, per key: {v: [readings] or number, ok: confirmed} */
  function dimRow(fid) {
    if (!S.dims[fid]) S.dims[fid] = {};
    const row = S.dims[fid];
    spec().dims.forEach((d) => {
      if (d.derived) return;
      if (!row[d.key]) row[d.key] = { vals: Array(d.readings || 1).fill(""), ok: false };
    });
    if (!row.av) row.av = { vals: [""], ok: true };
    return row;
  }
  function dimValue(fid, d) {
    const r = dimRow(fid)[d.key];
    if (!r) return null;
    const n = S.dimMode === "ind" ? (d.readings || 1) : 1;
    const xs = r.vals.slice(0, n).map((x) => parseFloat(x)).filter((x) => isFinite(x));
    if (xs.length) return xs.reduce((a, b) => a + b, 0) / xs.length;
    return r.ok && d.default != null ? d.default : null;
  }
  function dimsReady(fid) {
    const row = dimRow(fid);
    return spec().dims.every((d) => d.derived || row[d.key].ok || dimValue(fid, d) != null && row[d.key].vals.some((x) => x !== "" && isFinite(parseFloat(x))));
  }
  function dimsFor(fid) {
    const out = {};
    spec().dims.forEach((d) => {
      if (d.derived) {
        const r = dimRow(fid)["lig_override"];
        if (r && isFinite(parseFloat(r))) out[d.key] = parseFloat(r);
        return;
      }
      const v = dimValue(fid, d);
      out[d.key] = v == null ? d.default : v;
    });
    const av = parseFloat(dimRow(fid).av.vals[0]);
    if (isFinite(av)) out.av = av;
    return out;
  }
  function dimsCard() {
    const sp = spec();
    const head = sp.dims.map((d) => `<th class="n">${esc(d.label)} (${d.unit})</th>`).join("") + "<th class='n'>Air voids (%)</th><th>Check</th>";
    const rows = S.files.map((f) => {
      const row = dimRow(f.id);
      const cells = sp.dims.map((d) => {
        if (d.derived) {
          const D = dimValue(f.id, sp.dims.find((x) => x.key === "D")), a = dimValue(f.id, sp.dims.find((x) => x.key === "a"));
          const Dd = D != null ? D : sp.dims.find((x) => x.key === "D").default, ad = a != null ? a : sp.dims.find((x) => x.key === "a").default;
          const auto = Dd != null && ad != null ? (Dd / 2 - ad).toFixed(2) : "";
          return `<td class="n"><input type="text" inputmode="decimal" class="num" data-lig="${f.id}" value="${esc(row.lig_override || "")}" placeholder="${auto}" title="Fills from r − a unless you measured it"></td>`;
        }
        const r = row[d.key];
        const n = S.dimMode === "ind" ? (d.readings || 1) : 1;
        const ins = Array.from({ length: n }, (_, i) => {
          const v = r.vals[i] || "";
          const pend = !v && !r.ok;
          const val = v || (r.ok && i === 0 && n === 1 && d.default != null ? "" : "");
          return `<input type="text" inputmode="decimal" class="num${pend ? " pending" : ""}" data-dim="${f.id}" data-k="${d.key}" data-i="${i}" value="${esc(val)}" placeholder="${d.default != null ? d.default : ""}" aria-label="${esc(d.label)} ${n > 1 ? "reading " + (i + 1) : ""} for ${esc(label(f))}">`;
        }).join("");
        return `<td class="n"><div class="readings" style="justify-content:flex-end">${ins}</div>${n > 1 ? `<span class="small muted">avg ${fmt(dimValue(f.id, d), 2)}</span>` : ""}</td>`;
      }).join("");
      const ready = dimsReady(f.id);
      const dv = dimsFor(f.id);
      const bad = sp.dims.filter((d) => d.lo != null && dv[d.key] != null && (dv[d.key] < d.lo || dv[d.key] > d.hi));
      const chk = !ready ? `<button class="btn soft small" data-act="acceptrow" data-id="${f.id}">Accept defaults</button>` :
        bad.length ? `<span class="warn small">! ${bad.map((d) => d.key).join(", ")} outside ${esc(sp.standard_plain || sp.standard.replace(/<[^>]+>/g, ""))}</span>` : `<span class="ok small">✓ Within ${esc(sp.standard_plain || sp.standard.replace(/<[^>]+>/g, ""))}</span>`;
      return `<tr><td><input type="text" data-label="${f.id}" value="${esc(label(f))}" style="width:150px" aria-label="Specimen name"><div class="small muted">${esc(f.name)}</div></td>${cells}
        <td class="n"><input type="text" inputmode="decimal" class="num" data-av="${f.id}" value="${esc(row.av.vals[0])}" placeholder="optional"></td><td>${chk}</td></tr>`;
    }).join("");
    return `<section class="card"><div class="row"><h3>${mark(S.files.every((f) => dimsReady(f.id)) ? "done" : "attn")}Specimen dimensions</h3><span class="spacer"></span>
        <div class="seg" role="group"><button data-act="dimmode" data-v="avg" aria-pressed="${S.dimMode === "avg"}">Averaged values</button><button data-act="dimmode" data-v="ind" aria-pressed="${S.dimMode === "ind"}">Individual readings</button></div>
        <button class="btn small" data-act="paste">Paste from Excel</button>${S.files.every((f) => dimsReady(f.id)) ? "" : '<button class="btn soft small" data-act="acceptall">Accept all defaults</button>'}</div>
      <div class="tblwrap"><table class="tbl"><thead><tr><th>Specimen</th>${head}</tr></thead><tbody>${rows}</tbody></table></div>
      <p class="small muted">Grey values are nominals. Type a value or accept the default for each specimen. ${esc(sp.dims_note)}${sp.dims.some((d) => d.derived) ? " Ligament fills from r − a unless you measured it." : ""}${S.dimMode === "ind" ? " Individual readings are averaged." : ""}</p>
    </section>`;
  }

  /* ------------------------------------------------------------ step 4: results */
  function included() {
    const reps = S.run.replicates;
    const sp = S.specs[S.run.test];
    const inc = reps.map((r) => !r.error && S.manual[r.id] !== false);
    const why = reps.map((r) => (r.error ? "could not be processed" : S.manual[r.id] === false ? (S.reasons[r.id] || "excluded by hand") : ""));
    if (S.outlier) {
      const idx = reps.map((r, i) => (inc[i] && r.outputs && fin(r.outputs[sp.index]) ? i : -1)).filter((i) => i >= 0);
      if (idx.length >= 2) {
        const vals = idx.map((i) => reps[i].outputs[sp.index]);
        const m = vals.reduce((a, b) => a + b, 0) / vals.length;
        let far = idx[0], best = -1;
        idx.forEach((i) => { const d = Math.abs(reps[i].outputs[sp.index] - m); if (d > best) { best = d; far = i; } });
        inc[far] = false; why[far] = "outlier rule";
      }
    }
    return { inc, why };
  }
  const COV_FLAG = 25;  // tool choice, not a limit from the standards
  function idxCov() {
    if (!S.run) return null;
    const sp = S.specs[S.run.test], { inc } = included();
    const s = stats(S.run.replicates.map((r, i) => (inc[i] && r.outputs ? r.outputs[sp.index] : null)));
    return s.cov;
  }
  function stats(vals) {
    const a = vals.filter(fin);
    const n = a.length;
    if (!n) return { n: 0 };
    const mean = a.reduce((x, y) => x + y, 0) / n;
    const sd = n > 1 ? Math.sqrt(a.reduce((x, y) => x + (y - mean) ** 2, 0) / (n - 1)) : null;
    return { n, mean, sd, cov: sd != null && mean ? (100 * sd) / Math.abs(mean) : null };
  }
  function fmtOut(o, v) { return o.sci && fin(v) ? Number(v.toPrecision(3)).toExponential(2).replace("e+", "e") : fmt(v, o.dp); }
  function viewResults() {
    const run = S.run, sp = S.specs[run.test];
    const reps = run.replicates;
    const { inc, why } = included();
    const nInc = inc.filter(Boolean).length;
    const st = run.settings;
    const std = sp.standard_plain || sp.standard;
    const chips = [`<span class="chip navy">${st.mode === "fitted" ? "Fitted" : "Raw"}${["ifit", "idealct", "donut"].includes(run.test) && st.mode === "fitted" ? ` (${esc(std)})` : ""}</span>`];
    if (["ifit", "scb"].includes(run.test)) chips.push(`<span class="chip">${st.seating ? "Seating energy added" : "No seating energy"}</span>`);
    chips.push(`<span class="chip">Load tare ${st.tare ? "on" : "off"}</span>`, `<span class="chip">Trim ${st.start_load} / ${st.end_load} kN</span>`, `<span class="chip">Zero at start load</span>`);
    if (run.test === "idealct") chips.push(`<span class="chip">μ ${st.poisson === "fixed" ? "fixed 0.35" : "from S<sub>c</sub>, " + (st.mix === "design" ? "N<sub>design</sub>" : "7% AV")}</span>`);
    const allChecks = reps.every((r) => r.checks && r.checks.rate.ok !== false && r.checks.hz.ok !== false);
    const tiles = sp.outputs.filter((o) => o.main).map((o, k) => {
      const s = stats(reps.map((r, i) => (inc[i] && r.outputs ? r.outputs[o.key] : null)));
      const sAll = stats(reps.map((r) => (r.outputs ? r.outputs[o.key] : null)));
      return `<div class="tile${k === 0 ? " lead1" : ""}"><span class="label">${o.label}</span>
        <span class="v">${fmtOut(o, s.mean)}<span class="u">${o.unit}</span></span>
        <span class="s">SD ${s.sd == null ? "–" : fmtOut(o, s.sd)} · COV ${s.cov == null ? "–" : s.cov.toFixed(1) + "%"} · n = ${s.n}${nInc < reps.length ? ` of ${reps.length}` : ""}</span>
        ${nInc < reps.length && sAll.n ? `<span class="s">All ${sAll.n}: ${fmtOut(o, sAll.mean)}, COV ${sAll.cov == null ? "–" : sAll.cov.toFixed(1) + "%"}</span>` : ""}</div>`;
    }).join("");
    const moreItem = (o) => {
      const s = stats(reps.map((r, i) => (inc[i] && r.outputs ? r.outputs[o.key] : null)));
      return `<div><dt>${o.label}</dt><dd>${fmtOut(o, s.mean)} ${o.unit}${s.cov != null ? ` <span class="muted small">· COV ${s.cov.toFixed(1)}%</span>` : ""}</dd></div>`;
    };
    const more = sp.outputs.filter((o) => !o.main && !o.other).map(moreItem).join("");
    const others = sp.outputs.filter((o) => o.other).map(moreItem).join("");
    const keys = sp.table;
    const olab = Object.fromEntries(sp.outputs.map((o) => [o.key, o]));
    const dimKeys = sp.dims.filter((d) => ["t", "B", "lig", "D"].includes(d.key)).slice(0, 2);
    const rows = reps.map((r, i) => {
      if (r.error) return `<tr class="off"><td><input type="checkbox" disabled></td><td>${esc(r.label)}</td><td colspan="${dimKeys.length + keys.length + 2}" class="bad">${esc(r.error)}</td></tr>`;
      const c = r.checks;
      const ck = [["Rate", c.rate.ok], ["Hz", c.hz.ok], ["Dims", c.dims.ok], ["Fit", c.fit.ok]].filter(([, v]) => v !== null && v !== undefined)
        .map(([n, v]) => `<span class="${v ? "ok" : "bad"}">${v ? "✓" : "✗"} ${n}</span>`).join(" ");
      return `<tr class="${inc[i] ? "" : "off"}"><td><input type="checkbox" data-act="inc" data-id="${r.id}" ${S.manual[r.id] === false ? "" : "checked"} aria-label="Include ${esc(r.label)}"></td>
        <td style="white-space:nowrap"><strong>${esc(r.label)}</strong></td>${dimKeys.map((d) => `<td class="n">${fmt(r.dims[d.key], 1)}</td>`).join("")}
        ${keys.map((k) => `<td class="n">${fmtOut(olab[k], r.outputs[k])}</td>`).join("")}
        <td class="small">${ck}${r.warnings.length ? ` <span class="warn" title="${esc(r.warnings.map((w) => w.replace(/<[^>]+>/g, "")).join("\n"))}">! ${r.warnings.length} warning${r.warnings.length === 1 ? "" : "s"}</span>` : ""}</td>
        <td class="small">${inc[i] ? "Included" : `<span class="warn">Excluded · ${esc(why[i])}</span>`}</td></tr>`;
    }).join("");
    const warnList = reps.filter((r) => r.warnings && r.warnings.length).map((r) => `<li><strong>${esc(r.label)}:</strong> ${r.warnings.join(" ")}</li>`).join("");
    const cur = S.curveSel;
    const curveIds = ["all", ...reps.filter((r) => !r.error).map((r) => r.id)];
    let curve;
    if (cur === "all") {
      const series = reps.filter((r) => !r.error).map((r, k) => {
        const i = reps.indexOf(r);
        const s = r.plot.series.find((q) => q.cls === "fit" && q.pts.length && q.pts[0][0] < 0.05 * q.pts[q.pts.length - 1][0]) || r.plot.series[0];
        return { cls: inc[i] ? "c" + (k % 6) : "excl", pts: s.pts, name: r.label + (inc[i] ? "" : " (excluded)") };
      });
      curve = plotSVG({ series, x: reps.find((r) => !r.error).plot.x, y: "Load (kN)" }, { h: 340, lines: true }) + legend({ series });
    } else {
      const r = reps.find((x) => x.id === cur);
      curve = plotSVG(r.plot, { h: 340 }) + legend(r.plot);
    }
    const idx = olab[sp.index];
    const bars = barSVG(reps.map((r, i) => ({ label: r.label, v: r.outputs ? r.outputs[sp.index] : null, inc: inc[i] })), idx);
    const base = [S.batch.project || "Project", sp.name, S.batch.mix || "Mix"].map((s) => String(s).trim().split(/\s+/).map((w) => w[0].toUpperCase() + w.slice(1)).join("").replace(/[^A-Za-z0-9._-]+/g, "-")).join("_");
    return `<section class="stack"><h1>Results</h1>
      <p class="lead">${esc(sp.name)} · ${std} · ${esc(S.temp)} °${S.tempUnit}${S.batch.project ? " · " + esc(S.batch.project) : ""}${S.batch.mix ? " · " + esc(S.batch.mix) : ""}</p>
      <div class="row">${chips.join("")}</div>
      <p class="small ${allChecks ? "ok" : "warn"}">${reps.length} replicate${reps.length === 1 ? "" : "s"} · ${allChecks ? "all rate and sampling checks pass" : "some checks warn"} · ${reps.length - nInc} excluded</p></section>
      <section class="tiles">${tiles}</section>
      ${(() => { const cv = idxCov(); return cv != null && cv > COV_FLAG && nInc >= 3 ? `<div class="notice">The ${esc(S.short[sp.index] || sp.index)} COV of the included set is ${cv.toFixed(1)}%. Check the curves and the "Remove one outlier" option. The tool flags a COV above ${COV_FLAG}%.</div>` : ""; })()}
      ${nInc < sp.min_reps ? `<div class="notice">Only ${nInc} replicate${nInc === 1 ? " is" : "s are"} included. ${std} asks for at least ${sp.min_reps} specimens per result.</div>` : ""}
      <section class="card"><details class="more"><summary>More outputs (included replicates)</summary><dl class="kv">${more}</dl></details>
        ${others ? `<details class="more"><summary>Other indices (not in ${esc(std)})</summary><dl class="kv">${others}</dl>
          <p class="small muted">Proposed in the literature. Papers are on the <a href="references.html#${S.run.test}">References page</a>. The main results above follow the standard.</p></details>` : ""}</section>
      <section class="card"><div class="row"><h3>${mark(stepState(4))}Replicates</h3><span class="spacer"></span>
        <label class="toggle"><input type="checkbox" data-act="outlier" ${S.outlier ? "checked" : ""}><span>Remove one outlier<small>Drops the ${esc(idx.label.replace(/<[^>]+>/g, ""))} farthest from the mean of the included replicates</small></span></label></div>
        <div class="tblwrap"><table class="tbl"><thead><tr><th>Include</th><th>Specimen</th>${dimKeys.map((d) => `<th class="n">${esc(d.label.split(" ")[0])} (mm)</th>`).join("")}${keys.map((k) => `<th class="n" title="${esc(olab[k].label.replace(/<[^>]+>/g, ""))}">${esc(S.short[k] || k)}</th>`).join("")}<th>Checks</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table></div>
        <p class="small muted">Untick any row to exclude it by hand. Stats update right away, and the reason goes into the report. Warnings never remove a replicate on their own.</p>
        ${warnList ? `<div class="notice"><strong>Warnings</strong><ul>${warnList}</ul></div>` : ""}
      </section>
      <div class="grid-side narrow">
        <section class="card"><div class="row"><h3>Curves</h3><span class="spacer"></span>
          <div class="tabs">${curveIds.map((id) => `<button data-act="curve" data-id="${id}" aria-pressed="${cur === id}">${id === "all" ? "All" : esc(reps.find((r) => r.id === id).label)}</button>`).join("")}</div></div>${curve}</section>
        <section class="card"><h3>${idx.label} by replicate</h3>${bars}<p class="small muted">Line: mean of the included set. Grey: excluded.</p></section>
      </div>
      <section class="card"><h3>Export</h3>
        <ul class="small" style="margin:0;padding-left:18px;display:flex;flex-direction:column;gap:6px">
          <li><strong>${S.exp.format === "csv" ? "CSV" : "XLSX"} × ${reps.length}</strong> <span class="mono">${esc(base)}_${esc(String(reps[0].label).replace(/\s*·\s*/g, "-").replace(/\s+/g, ""))}.${S.exp.format}</span>, one per replicate. ${S.exp.format === "csv" ? "Processed data only." : "Summary sheet (inputs, settings, outputs, checks) with a chart · Data sheet (time, zeroed and trimmed, fitted) · Fit sheet."}</li>
          <li><strong>XLSX</strong> <span class="mono">${esc(base)}_batch-summary.xlsx</span>. All replicates in one table, stats for the included set and for all.</li>
          <li><strong>PDF</strong> <span class="mono">${esc(base)}_summary.pdf</span>. Page 1 summary and protocol, one page per replicate, then methods and references.</li>
          <li><strong>JSON</strong> <span class="mono">${esc(base)}_settings.json</span>. Mapping, settings, dimensions and exclusions.</li></ul>
        <div class="row"><div class="seg" role="group"><button data-act="efmt" data-v="xlsx" aria-pressed="${S.exp.format === "xlsx"}">Excel with charts</button><button data-act="efmt" data-v="csv" aria-pressed="${S.exp.format === "csv"}">CSV, data only</button></div>
          <label class="toggle"><input type="checkbox" data-act="eexcl" ${S.exp.include_excluded ? "checked" : ""}><span>Include excluded replicates</span></label><span class="spacer"></span>
          <button class="btn primary" data-act="export" ${S.busy ? "disabled" : ""}>Download ${esc(base)}.zip</button></div>
        <p class="small muted">The first export loads the Excel and PDF libraries. It can take a few seconds.</p>
      </section>
      <div class="foot"><button class="btn" data-go="3">Back to processing</button></div>`;
  }

  /* ------------------------------------------------------------ plots */
  const COLORS = ["#13294B", "#FF5F05", "#7A1F1F", "#1B6B3A", "#5B6F95", "#C84113"];
  function niceTicks(max, n = 5) {
    if (!(max > 0)) return [0, 1];
    const raw = max / n, p = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => s >= raw) || raw;
    const out = []; for (let v = 0; v <= max + step * 0.001; v += step) out.push(+v.toFixed(10));
    if (out[out.length - 1] < max) out.push(+(out[out.length - 1] + step).toFixed(10));
    return out;
  }
  function plotSVG(pl, opt = {}) {
    const W = 640, H = opt.h || 300, L = 52, R = 14, T = 12, B = 40;
    let xmax = 0, ymax = 0;
    const all = [...(pl.series || [])];
    all.forEach((s) => s.pts.forEach(([x, y]) => { if (fin(x) && x > xmax) xmax = x; if (fin(y) && y > ymax) ymax = y; }));
    (pl.points || []).forEach((p) => { if (fin(p.y) && p.y > ymax) ymax = p.y; });
    const xt = niceTicks(xmax * 1.02), yt = niceTicks(ymax * 1.05);
    const X1 = xt[xt.length - 1], Y1 = yt[yt.length - 1];
    const sx = (x) => L + (x / X1) * (W - L - R), sy = (y) => T + (1 - y / Y1) * (H - T - B);
    const cl = (v, a, b) => Math.max(a, Math.min(b, v));
    let g = "";
    xt.forEach((v) => (g += `<line class="grid" x1="${sx(v)}" x2="${sx(v)}" y1="${T}" y2="${H - B}"/><text x="${sx(v)}" y="${H - B + 16}" text-anchor="middle">${+v.toFixed(4)}</text>`));
    yt.forEach((v) => (g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${sy(v)}" y2="${sy(v)}"/><text x="${L - 6}" y="${sy(v) + 4}" text-anchor="end">${+v.toFixed(4)}</text>`));
    if (opt.band) g += `<rect x="${sx(Math.max(0, opt.band[0]))}" y="${T}" width="${Math.max(0, sx(opt.band[1]) - sx(Math.max(0, opt.band[0])))}" height="${H - T - B}" fill="#E8EDF5" opacity=".6"/>`;
    g += `<line class="ax" x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}"/><line class="ax" x1="${L}" x2="${L}" y1="${T}" y2="${H - B}"/>`;
    g += `<text x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle">${pl.x ? pl.x.replace(/<[^>]+>/g, "") : ""}</text>`;
    g += `<text transform="translate(14 ${(T + H - B) / 2}) rotate(-90)" text-anchor="middle">${pl.y || ""}</text>`;
    const path = (pts) => pts.filter(([x, y]) => fin(x) && fin(y)).map(([x, y], i) => `${i ? "L" : "M"}${sx(cl(x, 0, X1)).toFixed(1)} ${sy(cl(y, 0, Y1)).toFixed(1)}`).join("");
    (pl.series || []).forEach((s, k) => {
      if (s.cls === "raw" && !opt.lines) {
        g += `<path d="${s.pts.filter(([x, y]) => fin(x) && fin(y)).map(([x, y]) => `M${sx(x).toFixed(1)} ${sy(cl(y, 0, Y1)).toFixed(1)}h0.01`).join("")}" stroke="#9A968C" stroke-width="3.2" stroke-linecap="round" fill="none"/>`;
      } else if (s.cls === "fit") {
        g += `<path d="${path(s.pts)}" stroke="#FF5F05" stroke-width="2.4" fill="none"/>`;
      } else if (s.cls === "excl") {
        g += `<path d="${path(s.pts)}" stroke="#9A968C" stroke-width="1.6" stroke-dasharray="5 4" fill="none"/>`;
      } else {
        const c = COLORS[+String(s.cls).replace("c", "") % 6] || COLORS[k % 6];
        g += `<path d="${path(s.pts)}" stroke="${c}" stroke-width="2.2" fill="none"/>`;
      }
    });
    (pl.lines || []).forEach((ln) => { g += `<path d="${path(ln.pts)}" stroke="#13294B" stroke-width="1.5" stroke-dasharray="6 4" fill="none"/>`; });
    (pl.points || []).forEach((p) => {
      if (!fin(p.x) || !fin(p.y)) return;
      g += `<circle cx="${sx(p.x)}" cy="${sy(p.y)}" r="4.5" fill="#FFF" stroke="#13294B" stroke-width="2"/><text x="${sx(p.x) + 7}" y="${sy(p.y) - 7}" style="fill:#13294B;font-weight:600">${p.name.replace(/<[^>]+>/g, "")}</text>`;
    });
    return `<svg class="plot" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc((pl.y || "") + " vs " + (pl.x || "").replace(/<[^>]+>/g, ""))}">${g}</svg>`;
  }
  function legend(pl) {
    const items = (pl.series || []).map((s, k) => {
      const c = s.cls === "raw" ? "#9A968C" : s.cls === "fit" ? "#FF5F05" : s.cls === "excl" ? "#9A968C" : COLORS[+String(s.cls).replace("c", "") % 6] || COLORS[k % 6];
      return `<span><i style="background:${c}${s.cls === "raw" ? ";height:6px;width:6px;border-radius:50%" : ""}"></i>${s.name}</span>`;
    });
    (pl.lines || []).forEach((l) => items.push(`<span><i style="background:repeating-linear-gradient(90deg,#13294B 0 5px,transparent 5px 8px)"></i>${l.name}</span>`));
    return `<div class="legend">${items.join("")}</div>`;
  }
  function barSVG(items, o) {
    const W = 360, H = 230, L = 44, B = 46, T = 10, R = 8;
    const vals = items.map((i) => (fin(i.v) ? i.v : 0));
    const yt = niceTicks(Math.max(...vals, 0) * 1.1);
    const Y1 = yt[yt.length - 1];
    const sy = (y) => T + (1 - y / Y1) * (H - T - B);
    const bw = (W - L - R) / Math.max(1, items.length);
    const inc = items.filter((i) => i.inc && fin(i.v)).map((i) => i.v);
    const s = stats(inc);
    let g = "";
    yt.forEach((v) => (g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${sy(v)}" y2="${sy(v)}"/><text x="${L - 6}" y="${sy(v) + 4}" text-anchor="end">${+v.toFixed(3)}</text>`));
    if (s.n > 1 && s.sd != null) g += `<rect x="${L}" y="${sy(s.mean + s.sd)}" width="${W - L - R}" height="${Math.max(0, sy(s.mean - s.sd) - sy(s.mean + s.sd))}" fill="#E8EDF5" opacity=".8"/>`;
    items.forEach((it, k) => {
      const v = fin(it.v) ? it.v : 0, x = L + k * bw + bw * 0.18;
      g += `<rect x="${x}" y="${sy(v)}" width="${bw * 0.64}" height="${H - B - sy(v)}" fill="${it.inc ? "#FF5F05" : "#C9C5BA"}"/>`;
      g += `<text x="${x + bw * 0.32}" y="${sy(v) - 4}" text-anchor="middle" style="fill:#1C1C1A">${fmtOut(o, it.v)}</text>`;
      g += `<text x="${x + bw * 0.32}" y="${H - B + 16}" text-anchor="middle">${esc(String(it.label).slice(-10))}</text>`;
    });
    if (s.n) g += `<line x1="${L}" x2="${W - R}" y1="${sy(s.mean)}" y2="${sy(s.mean)}" stroke="#13294B" stroke-width="2"/>`;
    g += `<line class="ax" x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}"/>`;
    return `<svg class="plot" viewBox="0 0 ${W} ${H}" role="img" aria-label="Index by replicate">${g}</svg>`;
  }

  /* ------------------------------------------------------------ actions */
  async function addFiles(list) {
    const arr = [...list];
    if (!arr.length) return;
    S.busy = true; toast(`Reading ${arr.length} file${arr.length === 1 ? "" : "s"}…`);
    const payload = await Promise.all(arr.map(async (f) => ({ name: f.name, b64: await toB64(f) })));
    try {
      const r = await API("parse", { files: payload }, { xlsx: arr.some((f) => /\.xls[xm]$/i.test(f.name)) });
      S.fileErrors = r.files.filter((f) => f.error);
      r.files.filter((f) => !f.error).forEach((f) => {
        f.cols.forEach((c) => { if (c.role === "ignore") c.unit = c.unit || null; });
        S.files.push(f);
      });
      if (S.files.length) S.active = S.active || S.files[0].signature;
      await runChecks();
    } catch (e) { toast(e.message, true); }
    S.busy = false; render();
  }
  function toB64(file) {
    return new Promise((res, rej) => {
      const fr = new FileReader();
      fr.onload = () => res(String(fr.result).split(",")[1] || "");
      fr.onerror = () => rej(fr.error);
      fr.readAsDataURL(file);
    });
  }
  async function loadExamples() {
    const names = [1, 2, 3].map((i) => `${S.test}_MixA_R${i}.csv`);
    try {
      const files = await Promise.all(names.map(async (n) => {
        const r = await fetch(`examples/${n}?v=${VER}`);
        if (!r.ok) throw new Error(`Could not load ${n}`);
        return new File([await r.blob()], n);
      }));
      S.files = []; S.confirmed = {}; S.checks = {}; S.dims = {}; S.labels = {};
      files.forEach((f, i) => (S.labels["pending" + i] = null));
      await addFiles(files);
      S.files.forEach((f, i) => (S.labels[f.id] = `Mix A · R${i + 1}`));
      if (!S.batch.project) S.batch.project = "Example project";
      if (!S.batch.mix) S.batch.mix = "Mix A";
      render();
    } catch (e) { toast(e.message, true); }
  }
  function mappingOf(f) {
    const roles = {}, units = {};
    f.cols.forEach((c) => { if (c.role !== "ignore") { roles[c.role] = c.index; units[c.role] = c.unit; } });
    return { roles, units };
  }
  async function runChecks(ids) {
    const fs = S.files.filter((f) => !ids || ids.includes(f.id));
    fs.forEach((f) => delete S.checks[f.id]);
    try {
      const r = await API("check", { test: S.test, settings: S.settings, files: fs.map((f) => ({ id: f.id, ...mappingOf(f) })) });
      r.files.forEach((c) => (S.checks[c.id] = c));
    } catch (e) { fs.forEach((f) => (S.checks[f.id] = { error: e.message })); }
  }
  function setRole(sig, idx, role) {
    S.files.filter((f) => f.signature === sig).forEach((f) => {
      const c = f.cols.find((x) => x.index === idx);
      if (role !== "ignore") f.cols.forEach((x) => { if (x.role === role && x.index !== idx) x.role = "ignore"; });
      c.role = role;
      const k = unitKind(role);
      if (k && !UNITS[k].some(([v]) => v === c.unit)) { c.unit = UNITS[k][0][0]; c.unit_source = "guess"; }
    });
    S.confirmed[sig] = false;
  }
  function filePayload(f) { return { id: f.id, ...mappingOf(f), dims: dimsFor(f.id), label: label(f) }; }
  let pvTimer;
  function refreshPreview(delay = 0) {
    clearTimeout(pvTimer);
    pvTimer = setTimeout(async () => {
      if (S.step !== 3 || !S.files.length) return;
      const f = S.files.find((x) => x.id === S.previewFile) || S.files[0];
      S.previewFile = f.id; S.previewBusy = true;
      const token = (refreshPreview.t = (refreshPreview.t || 0) + 1);
      try {
        const r = await API("preview", { test: S.test, settings: S.settings, file: filePayload(f) });
        if (token !== refreshPreview.t) return;
        S.preview = r;
      } catch (e) { S.preview = { error: e.message }; }
      S.previewBusy = false;
      if (S.step === 3) render();
    }, delay);
  }
  async function doRun() {
    S.busy = true; render();
    try {
      const r = await API("run", { test: S.test, settings: S.settings, files: S.files.map(filePayload) });
      S.run = r; S.manual = {}; S.reasons = {}; S.outlier = false; S.curveSel = "all";
      S.busy = false; S.step = 4; S.seen = 4; render(); window.scrollTo(0, 0);
    } catch (e) { S.busy = false; render(); toast(e.message, true); }
  }
  async function doExport() {
    const { inc, why } = included();
    S.busy = true; render();
    try {
      const r = await API("export", {
        run: S.run.run, included: inc, reasons: why, options: S.exp,
        batch: { ...S.batch, temp: S.temp, temp_unit: S.tempUnit },
      });
      const bin = atob(r.b64), u8 = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
      const url = URL.createObjectURL(new Blob([u8], { type: "application/zip" }));
      const a = document.createElement("a"); a.href = url; a.download = r.name; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
      toast("Saved " + r.name);
    } catch (e) { toast(e.message, true); }
    S.busy = false; render();
  }
  function pasteDialog() {
    const dlg = document.getElementById("dialog");
    const sp = spec();
    const cols = sp.dims.filter((d) => !d.derived).map((d) => d.label).concat(["Air voids (optional)"]);
    dlg.innerHTML = `<form method="dialog" class="stack"><h3>Paste dimensions</h3>
      <p class="small muted">One row per specimen, in the order shown (${S.files.map((f) => esc(label(f))).join(", ")}). Columns: ${cols.map(esc).join(", ")}. Averaged values only.</p>
      <textarea id="pastebox" placeholder="50.2\t150.1\t15.0"></textarea>
      <div class="row"><span class="spacer"></span><button class="btn" value="cancel">Cancel</button><button class="btn primary" value="ok" id="pasteok">Fill table</button></div></form>`;
    dlg.showModal();
    dlg.onclose = () => {
      if (dlg.returnValue !== "ok") return;
      const lines = document.getElementById("pastebox").value.trim().split(/\r?\n/).filter((l) => l.trim());
      const keys = sp.dims.filter((d) => !d.derived).map((d) => d.key);
      S.dimMode = "avg";
      lines.forEach((ln, i) => {
        const f = S.files[i]; if (!f) return;
        const cells = ln.split(/\t|;|,(?=\s*\d)/).map((x) => x.trim());
        keys.forEach((k, j) => { if (cells[j] && isFinite(parseFloat(cells[j]))) { const r = dimRow(f.id)[k]; r.vals[0] = cells[j]; r.ok = true; } });
        if (cells[keys.length] && isFinite(parseFloat(cells[keys.length]))) dimRow(f.id).av.vals[0] = cells[keys.length];
      });
      render(); refreshPreview(50);
    };
  }

  /* ------------------------------------------------------------ events */
  app.addEventListener("click", (e) => {
    const t = e.target.closest("[data-act],[data-go]");
    if (!t || t.disabled) return;
    if (t.dataset.go) return go(+t.dataset.go);
    const a = t.dataset.act;
    if (a === "domain") {
      if (S.domain !== t.dataset.d) {
        S.domain = t.dataset.d; S.test = S.order[S.domain][0];
        const c = S.domain === "low" ? -12 : 25;  // usual starting values: 25 °C service, −12 °C low temperature
        S.temp = (S.tempUnit === "F" ? c * 9 / 5 + 32 : c).toFixed(1);
        resetForTest();
      }
      render();
    }
    else if (a === "pick") { if (S.test !== t.dataset.k) { S.test = t.dataset.k; resetForTest(); } render(); }
    else if (a === "tunit") {
      const u = t.dataset.u, v = parseFloat(S.temp);
      if (u !== S.tempUnit && isFinite(v)) S.temp = (u === "F" ? v * 9 / 5 + 32 : (v - 32) * 5 / 9).toFixed(1);
      S.tempUnit = u; render();
    }
    else if (a === "examples") loadExamples();
    else if (a === "group") { S.active = t.dataset.sig; render(); }
    else if (a === "gconfirm") { S.active = t.dataset.sig; render(); const m = app.querySelector('[data-act="confirm"]'); if (m) m.closest(".card").scrollIntoView({ behavior: "smooth", block: "start" }); }
    else if (a === "rmfile") {
      e.stopPropagation();
      const id = t.dataset.id;
      S.files = S.files.filter((f) => f.id !== id); delete S.checks[id]; delete S.dims[id];
      API("forget", { ids: [id] }).catch(() => {});
      render();
    }
    else if (a === "confirm") { S.confirmed[t.dataset.sig] = true; render(); }
    else if (a === "pfile") { S.previewFile = t.dataset.id; render(); }
    else if (a === "mode") { S.settings.mode = t.dataset.v; render(); refreshPreview(); }
    else if (a === "poisson") { S.settings.poisson = t.dataset.v; render(); refreshPreview(); }
    else if (a === "mix") { S.settings.mix = t.dataset.v; render(); refreshPreview(); }
    else if (a === "resetset") { S.settings = defaultsFor(S.test); render(); refreshPreview(); runChecks().then(() => S.step === 2 && render()); }
    else if (a === "pv") { S.previewFile = t.dataset.id; S.preview = null; render(); refreshPreview(); }
    else if (a === "dimmode") { S.dimMode = t.dataset.v; render(); }
    else if (a === "acceptrow") { acceptDefaults(t.dataset.id); render(); refreshPreview(50); }
    else if (a === "acceptall") { S.files.forEach((f) => acceptDefaults(f.id)); render(); refreshPreview(50); }
    else if (a === "paste") pasteDialog();
    else if (a === "run") doRun();
    else if (a === "curve") { S.curveSel = t.dataset.id; render(); }
    else if (a === "efmt") { S.exp.format = t.dataset.v; render(); }
    else if (a === "export") doExport();
  });
  app.addEventListener("keydown", (e) => {
    const t = e.target.closest('[data-act="group"]');
    if (t && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); t.click(); }
  });
  function acceptDefaults(fid) {
    const row = dimRow(fid);
    spec().dims.forEach((d) => { if (!d.derived) row[d.key].ok = true; });
  }
  function resetForTest() {
    S.settings = defaultsFor(S.test); S.dims = {}; S.preview = null; S.run = null;
    if (S.files.length) runChecks().then(() => S.step === 2 && render());
  }
  app.addEventListener("change", async (e) => {
    const t = e.target;
    const a = t.dataset.act;
    if (a === "role" || a === "unit") {
      const sig = S.active, idx = +t.dataset.i;
      if (a === "role") setRole(sig, idx, t.value);
      else S.files.filter((f) => f.signature === sig).forEach((f) => { const c = f.cols.find((x) => x.index === idx); c.unit = t.value; c.unit_source = "user"; });
      S.confirmed[sig] = false;
      const ids = S.files.filter((f) => f.signature === sig).map((f) => f.id);
      render(); await runChecks(ids); render();
    } else if (a === "inc") {
      S.manual[t.dataset.id] = t.checked ? undefined : false;
      if (!t.checked && !S.reasons[t.dataset.id]) S.reasons[t.dataset.id] = "excluded by hand";
      render();
    } else if (a === "outlier") { S.outlier = t.checked; render(); }
    else if (a === "eexcl") { S.exp.include_excluded = t.checked; }
    else if (t.dataset.set) {
      const k = t.dataset.set;
      if (t.type === "checkbox") S.settings[k] = t.checked;
      else { const v = parseFloat(t.value); if (isFinite(v) && v >= 0) S.settings[k] = v; else { toast("Enter a load in kN.", true); } }
      render(); refreshPreview();
      if (["start_load", "end_load", "tare"].includes(k)) runChecks();
    } else if (t.id === "fileinput") { await addFiles(t.files); t.value = ""; }
    else if (t.dataset.dim || t.dataset.av || t.dataset.lig || t.dataset.label) { render(); refreshPreview(50); }
  });
  app.addEventListener("input", (e) => {
    const t = e.target;
    if (t.id === "temp" || t.id === "temp2") { S.temp = t.value; return; }
    if (t.dataset.batch) { S.batch[t.dataset.batch] = t.value; return; }
    if (t.dataset.label) { S.labels[t.dataset.label] = t.value; return; }
    if (t.dataset.av) { dimRow(t.dataset.av).av.vals[0] = t.value; return; }
    if (t.dataset.lig) { dimRow(t.dataset.lig).lig_override = t.value; return; }
    if (t.dataset.dim) {
      const r = dimRow(t.dataset.dim)[t.dataset.k];
      r.vals[+t.dataset.i] = t.value;
      t.classList.remove("pending");
      const v = parseFloat(t.value);
      t.classList.toggle("bad", t.value !== "" && !(isFinite(v) && v > 0));
      if (t.value !== "") r.ok = true;
      const run = app.querySelector('.run[data-act="run"]');
      if (run && !S.busy) run.disabled = !S.files.every((f) => dimsReady(f.id));
      renderSteps();
    }
  });
  stepsNav.addEventListener("click", (e) => { const t = e.target.closest("[data-go]"); if (t && !t.disabled) go(+t.dataset.go); });
  // drag and drop
  app.addEventListener("dragover", (e) => { const d = e.target.closest("#drop"); if (d) { e.preventDefault(); d.classList.add("over"); } });
  app.addEventListener("dragleave", (e) => { const d = e.target.closest("#drop"); if (d) d.classList.remove("over"); });
  app.addEventListener("drop", (e) => { const d = e.target.closest("#drop"); if (d) { e.preventDefault(); d.classList.remove("over"); addFiles(e.dataTransfer.files); } });

  /* ------------------------------------------------------------ boot */
  (async function boot() {
    try {
      const r = await API("tests");
      S.specs = r.tests; S.order = r.order; S.short = r.short || {};
      S.settings = defaultsFor(S.test);
      render();
    } catch (e) {
      app.innerHTML = `<div class="boot"><h1>Cracking Test Analyzer</h1><p class="err">${esc(e.message)}</p><p>Reload the page to try again.</p></div>`;
    }
  })();
})();
