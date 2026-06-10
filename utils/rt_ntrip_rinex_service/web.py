"""Small dependency-free Web UI and JSON API."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse, parse_qs

from .manager import RuntimeManager


PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"


class RTRinexRequestHandler(SimpleHTTPRequestHandler):
    manager: RuntimeManager

    server_version = "RTRinexWeb/0.2"

    def __init__(self, *args, directory: str | None = None, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        self.manager.logs.write(f"[web] {self.address_string()} {format % args}")

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            return self._send_json(self.manager.status())
        if parsed.path == "/api/config":
            return self._send_json({"path": str(self.manager.store.path), "config": self.manager.store.load_raw()})
        if parsed.path == "/api/stations":
            return self._send_json(
                {
                    "stations": self.manager.store.list_station_dicts(),
                    "runtime": self.manager.status()["stations"],
                }
            )
        if parsed.path == "/api/logs":
            query = parse_qs(parsed.query)
            limit = int((query.get("limit") or ["200"])[0])
            source = (query.get("source") or [""])[0]
            return self._send_json(
                {
                    "lines": self.manager.logs.lines(limit, source=source),
                    "sources": self.manager.logs.sources(),
                }
            )
        if parsed.path in {"", "/"}:
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/reload":
            self.manager.reload_config(force=True)
            self.manager.trigger_reload()
            return self._send_json({"ok": True, "status": self.manager.status()})
        if parsed.path == "/api/merge":
            results = self.manager.run_due_merges()
            self.manager.trigger_merge()
            return self._send_json({"ok": True, "results": results})
        if parsed.path == "/api/stations":
            payload = self._read_json()
            station = self.manager.store.upsert_station(payload)
            self.manager.trigger_reload()
            return self._send_json({"ok": True, "station": station}, status=HTTPStatus.CREATED)
        return self._send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        prefix = "/api/stations/"
        if parsed.path.startswith(prefix):
            name = unquote(parsed.path[len(prefix) :])
            payload = self._read_json()
            station = self.manager.store.upsert_station(payload, original_name=name)
            self.manager.trigger_reload()
            return self._send_json({"ok": True, "station": station})
        if parsed.path == "/api/config":
            payload = self._read_json()
            raw = payload.get("config", payload) if isinstance(payload, dict) else payload
            if not isinstance(raw, dict):
                return self._send_error(HTTPStatus.BAD_REQUEST, "Config payload must be an object")
            self.manager.store.save_raw(raw)
            self.manager.trigger_reload()
            return self._send_json({"ok": True})
        return self._send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        prefix = "/api/stations/"
        if parsed.path.startswith(prefix):
            name = unquote(parsed.path[len(prefix) :])
            removed = self.manager.store.delete_station(name)
            self.manager.trigger_reload()
            return self._send_json({"ok": True, "removed": removed})
        return self._send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def _read_json(self) -> Any:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc

    def _send_json(self, payload: Any, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"ok": False, "error": message}, status=status)

    def handle_one_request(self) -> None:
        try:
            super().handle_one_request()
        except Exception as exc:
            try:
                self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            except Exception:
                pass


def build_server(manager: RuntimeManager, host: str, port: int) -> ThreadingHTTPServer:
    class BoundHandler(RTRinexRequestHandler):
        pass

    BoundHandler.manager = manager
    return ThreadingHTTPServer((host, int(port)), BoundHandler)
