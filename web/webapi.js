/* Cracking Test Analyzer: talks to the calculation engine.
   Default: a web worker running Python with Pyodide (worker.js). Nothing is sent to a server.
   Developer mode (?local=1 with server.py running): the same engine through a local server. */
(function () {
  const VER = window.CTA_VERSION || "";
  const qs = new URLSearchParams(location.search);
  const LOCAL = qs.get("local") === "1";
  let calc;
  if (LOCAL) {
    calc = async (path, body, _opts) => {
      const r = await fetch("api/" + path, { method: "POST", body: body ? JSON.stringify(body) : "" });
      const j = await r.json();
      if (!j.ok) throw new Error(j.error);
      return j.data;
    };
  } else {
    const PYO = qs.get("pyodide") || "";
    const worker = new Worker(`web/worker.js?v=${encodeURIComponent(VER)}${PYO ? "&pyodide=" + encodeURIComponent(PYO) : ""}`);
    let seq = 0;
    const pending = new Map();
    worker.onmessage = (e) => {
      const p = pending.get(e.data.id); if (!p) return;
      pending.delete(e.data.id);
      let r; try { r = JSON.parse(e.data.out); } catch (err) { return p.rej(err); }
      r.ok ? p.res(r.data) : p.rej(new Error(r.error));
    };
    worker.onerror = (e) => {
      const msg = "The calculation engine did not load. Check your internet connection and reload the page." + (e.message ? ` (${e.message})` : "");
      pending.forEach((p) => p.rej(new Error(msg))); pending.clear();
    };
    calc = (path, body, opts) => new Promise((res, rej) => {
      const id = ++seq; pending.set(id, { res, rej });
      worker.postMessage({ id, path, body: body ? JSON.stringify(body) : "", xlsx: !!(opts && opts.xlsx) });
    });
  }
  window.CTA_API = calc;
})();
