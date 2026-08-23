"""Local dev server that mirrors the Vercel layout.

Serves the static frontend from public/ and routes POST /api/analyze to the same
`run_analysis` used by the Vercel function. Standard library only (plus
python-dotenv to load .env locally). On Vercel this file is unused — Vercel
serves public/ and runs api/analyze.py directly.

    python dev_server.py        # then open http://localhost:8000
"""
from __future__ import annotations

import importlib.util
import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # dotenv is optional for dev
    pass

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
PORT = int(os.environ.get("PORT", "8000"))

# Load api/analyze.py by path so we reuse the exact same logic as production.
_spec = importlib.util.spec_from_file_location(
    "vercel_analyze", BASE_DIR / "api" / "analyze.py"
)
_analyze = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_analyze)
run_analysis = _analyze.run_analysis
ApiError = _analyze.ApiError


class DevHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC_DIR), **kwargs)

    def _send_json(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/api/analyze":
            self._send_json(404, {"detail": "Not found."})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                payload = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                raise ApiError(400, "Request body is not valid JSON.")
            report = run_analysis(payload)
            self._send_json(200, report)
        except ApiError as exc:
            self._send_json(exc.status, {"detail": exc.detail})
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"detail": f"Unexpected server error: {exc}"})


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), DevHandler)
    print(f"Dev server running at http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
