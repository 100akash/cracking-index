/* Cracking Test Analyzer: runs the Python engine (engine/*.py) in the browser with Pyodide.
   The page sends {id, path, body}; the worker answers {id, out} where out is a JSON string.
   Files never leave this tab. */
const q = new URL(self.location.href).searchParams;
const BASE = q.get("pyodide") || "https://cdn.jsdelivr.net/npm/pyodide@0.29.4/";
const VER = q.get("v") || "";
const FILES = ["core.py", "parse.py", "specs.py", "methods.py", "report.py", "routes.py"];
importScripts(BASE + "pyodide.js");

// openpyxl is pure Python and not part of the Pyodide distribution, so its wheels ship in vendor/.
const VENDOR = { openpyxl: ["et_xmlfile-2.0.0-py3-none-any.whl", "openpyxl-3.1.5-py2.py3-none-any.whl"] };
let py;
const loaded = new Set();
async function need(pkgs) {
  const todo = pkgs.filter((p) => !loaded.has(p));
  if (!todo.length) return;
  const urls = [];
  todo.forEach((p) => (VENDOR[p] ? VENDOR[p].forEach((w) => urls.push(new URL("../vendor/" + w, self.location.href).href)) : urls.push(p)));
  await py.loadPackage(urls);
  todo.forEach((p) => loaded.add(p));
}

const ready = (async () => {
  py = await loadPyodide({ indexURL: BASE });
  await need(["numpy", "scipy"]);
  const root = new URL("../engine/", self.location.href);
  for (const f of FILES) {
    const r = await fetch(new URL(f, root).href + (VER ? "?v=" + VER : ""));
    if (!r.ok) throw new Error(`Could not load ${f} (${r.status})`);
    py.FS.writeFile("/home/pyodide/" + f, await r.text());
  }
  py.runPython("import os, sys\nos.environ['MPLBACKEND'] = 'Agg'\nsys.path.insert(0, '/home/pyodide')\nimport routes");
  return py.globals.get("routes").handle_json;
})();

self.onmessage = async (e) => {
  const { id, path, body, xlsx } = e.data;
  try {
    const handle = await ready;
    if (path === "export") await need(["openpyxl", "matplotlib"]);
    if (path === "parse" && xlsx) await need(["openpyxl"]);
    self.postMessage({ id, out: handle(path, body || "") });
  } catch (err) {
    self.postMessage({ id, out: JSON.stringify({ ok: false, error: "The calculation engine did not load. " + (err && err.message ? err.message : err) }) });
  }
};
