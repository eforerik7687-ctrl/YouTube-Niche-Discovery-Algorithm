"""Simple server to serve dashboard and trigger pipeline runs."""
import json
import subprocess
import sys
import threading
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler

PIPELINE_LOCK = threading.Lock()
RUNNING = False


class Handler(SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/run":
            self.handle_run()
        else:
            self.send_error(404)

    def handle_run(self):
        global RUNNING
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        keywords = body.get("keywords", [])
        if not keywords:
            self.send_json({"status": "No keywords provided"}, 400)
            return
        if RUNNING:
            self.send_json({"status": "Pipeline already running"})
            return

        RUNNING = True
        self.send_json({"status": "Started: " + ", ".join(keywords)})
        self.server._run_pipeline(keywords)

    def send_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, fmt, *args):
        print(f"[server] {fmt % args}")


class NicheServer(HTTPServer):
    allow_reuse_address = True

    def _run_pipeline(self, keywords):
        def task():
            global RUNNING
            try:
                cmd = [sys.executable, str(Path(__file__).parent / "src" / "cli.py")] + keywords
                subprocess.run(cmd, cwd=Path(__file__).parent, capture_output=True, text=True)
            finally:
                RUNNING = False
        threading.Thread(target=task, daemon=True).start()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = NicheServer(("0.0.0.0", port), Handler)
    print(f"[server] http://localhost:{port}/dashboard.html")
    server.serve_forever()
