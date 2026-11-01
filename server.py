"""Optional local server for development and offline use.

    python server.py            then open http://localhost:8765/?local=1

The page then calls the same Python engine through this server instead of
running it in the browser. Needs numpy, scipy, openpyxl and matplotlib.
Without ?local=1 the page runs the engine in the browser as usual.
"""
import http.server
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "engine"))
os.environ.setdefault("MPLBACKEND", "Agg")
import routes  # noqa: E402


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def do_POST(self):
        if not self.path.startswith("/api/"):
            self.send_error(404)
            return
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode("utf-8") if n else ""
        out = routes.handle_json(self.path[5:].split("?")[0], body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"Cracking Test Analyzer on http://localhost:{port}/?local=1")
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
