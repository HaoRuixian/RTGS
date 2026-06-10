"""Dependency-free Web API and static file server."""

from __future__ import annotations

from email import policy
from email.parser import BytesParser
import json
from datetime import datetime, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import secrets
from threading import RLock
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .runtime import RealtimeEkfRuntimeManager


PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
SESSION_COOKIE = "rt_ekf_session"
SESSION_TTL_SECONDS = 12 * 60 * 60


def _configured_users() -> dict[str, dict[str, str]]:
    admin_user = os.getenv("RT_EKF_ADMIN_USER", "adminHRX").strip() or "adminHRX"
    viewer_user = os.getenv("RT_EKF_VIEWER_USER", "viewer").strip() or "viewer"
    users = {
        admin_user: {
            "password": os.getenv("RT_EKF_ADMIN_PASSWORD", "hao20030801"),
            "role": "admin",
            "display_name": admin_user,
        },
        viewer_user: {
            "password": os.getenv("RT_EKF_VIEWER_PASSWORD", "123456"),
            "role": "viewer",
            "display_name": viewer_user,
        },
    }
    return {name: data for name, data in users.items() if data.get("password")}


USERS = _configured_users()
_SESSIONS: dict[str, dict[str, Any]] = {}
_SESSION_LOCK = RLock()


class RealtimeEkfRequestHandler(SimpleHTTPRequestHandler):
    manager: RealtimeEkfRuntimeManager
    server_version = "RealtimeEkfGNSSIR/0.1"

    def __init__(self, *args, directory: str | None = None, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        self.manager.logs.write("web", f"{self.address_string()} {format % args}")

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
        if parsed.path == "/api/session":
            user = self._current_user()
            if user is None:
                return self._send_json({"authenticated": False, "user": None})
            return self._send_json({"authenticated": True, "user": _public_user(user)})
        if parsed.path == "/api/status":
            user = self._require_login()
            if user is None:
                return
            return self._send_json(_for_user(self.manager.status(), user))
        if parsed.path == "/api/config":
            user = self._require_admin()
            if user is None:
                return
            return self._send_json({"path": str(self.manager.store.path), "config": self.manager.store.load_raw()})
        if parsed.path == "/api/stations":
            user = self._require_login()
            if user is None:
                return
            return self._send_json(
                _for_user(
                    {
                        "stations": self.manager.stations_config(),
                        "runtime": self.manager.status()["stations"],
                    },
                    user,
                )
            )
        if parsed.path.startswith("/api/stations/") and parsed.path.endswith("/products"):
            user = self._require_login()
            if user is None:
                return
            name = unquote(parsed.path[len("/api/stations/") : -len("/products")])
            query = parse_qs(parsed.query)
            limit = _query_limit(query, default=200)
            start = _query_datetime(query, "start")
            end = _query_datetime(query, "end")
            return self._send_json(
                {
                    "station": name,
                    "start": start.isoformat() if start else None,
                    "end": end.isoformat() if end else None,
                    "limit": limit,
                    "products": self.manager.products(name, limit, start=start, end=end),
                }
            )
        if parsed.path.startswith("/api/stations/") and parsed.path.endswith("/reflectometry-config"):
            user = self._require_login()
            if user is None:
                return
            name = unquote(parsed.path[len("/api/stations/") : -len("/reflectometry-config")])
            return self._send_json(self.manager.reflectometry_config(name))
        if parsed.path == "/api/logs":
            user = self._require_login()
            if user is None:
                return
            query = parse_qs(parsed.query)
            source = (query.get("source") or [""])[0]
            limit = _query_int(parsed.query, "limit", 200)
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
        if parsed.path == "/api/login":
            return self._handle_login()
        if parsed.path == "/api/logout":
            return self._handle_logout()
        if parsed.path == "/api/reload":
            if self._require_admin() is None:
                return
            self.manager.reload_config(force=True)
            return self._send_json({"ok": True, "status": self.manager.status()})
        if parsed.path == "/api/stations":
            if self._require_admin() is None:
                return
            try:
                station = self.manager.store.create_station(self._read_json())
            except ValueError as exc:
                return self._send_error(HTTPStatus.CONFLICT, str(exc))
            self.manager.reload_config(force=True)
            return self._send_json({"ok": True, "station": station}, status=HTTPStatus.CREATED)

        postprocess_station = self._station_postprocess(parsed.path)
        if postprocess_station is not None:
            if self._require_admin() is None:
                return
            try:
                fields, files = self._read_multipart_form()
                payload = self.manager.run_rinex_postprocess(
                    postprocess_station,
                    observation_file=files.get("observation_file") or files.get("obs_file"),
                    ephemeris_file=files.get("ephemeris_file") or files.get("eph_file"),
                    ephemeris_file_type=str(fields.get("ephemeris_file_type") or "Auto Detect"),
                    use_rinex_position=_truthy(fields.get("use_rinex_position")),
                )
            except KeyError as exc:
                return self._send_error(HTTPStatus.NOT_FOUND, str(exc))
            except ValueError as exc:
                self.manager.logs.write(postprocess_station, f"RINEX postprocess failed: {exc}")
                return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
            except Exception as exc:
                self.manager.logs.write(postprocess_station, f"RINEX postprocess failed: {exc}")
                return self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            return self._send_json(payload)

        action = self._station_action(parsed.path)
        if action is not None:
            if self._require_admin() is None:
                return
            name, verb = action
            if verb == "start":
                return self._send_json({"ok": True, "station": self.manager.start_station(name)})
            if verb == "stop":
                return self._send_json({"ok": True, "station": self.manager.stop_station(name)})
            if verb == "restart":
                return self._send_json({"ok": True, "station": self.manager.restart_station(name)})
        return self._send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        if self._require_admin() is None:
            return
        if parsed.path == "/api/config":
            payload = self._read_json()
            raw = payload.get("config", payload) if isinstance(payload, dict) else payload
            if not isinstance(raw, dict):
                return self._send_error(HTTPStatus.BAD_REQUEST, "Config payload must be an object")
            self.manager.store.save_raw(raw)
            self.manager.reload_config(force=True)
            return self._send_json({"ok": True})
        prefix = "/api/stations/"
        if parsed.path.startswith(prefix):
            name = unquote(parsed.path[len(prefix) :])
            if name.endswith("/reflectometry-config"):
                station_name = unquote(name[: -len("/reflectometry-config")])
                payload = self._read_json()
                return self._send_json({"ok": True, "config": self.manager.update_reflectometry_config(station_name, payload)})
            try:
                station = self.manager.store.upsert_station(self._read_json(), original_name=name)
            except ValueError as exc:
                return self._send_error(HTTPStatus.CONFLICT, str(exc))
            self.manager.reload_config(force=True)
            return self._send_json({"ok": True, "station": station})
        return self._send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if self._require_admin() is None:
            return
        prefix = "/api/stations/"
        if parsed.path.startswith(prefix):
            name = unquote(parsed.path[len(prefix) :])
            self.manager.stop_station(name)
            removed = self.manager.store.delete_station(name)
            self.manager.reload_config(force=True)
            return self._send_json({"ok": True, "removed": removed})
        return self._send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def _station_action(self, path: str) -> tuple[str, str] | None:
        prefix = "/api/stations/"
        if not path.startswith(prefix):
            return None
        tail = path[len(prefix) :]
        parts = tail.split("/")
        if len(parts) != 2:
            return None
        name = unquote(parts[0])
        action = parts[1]
        if action not in {"start", "stop", "restart"}:
            return None
        return name, action

    def _station_postprocess(self, path: str) -> str | None:
        prefix = "/api/stations/"
        suffix = "/postprocess"
        if not path.startswith(prefix) or not path.endswith(suffix):
            return None
        name = path[len(prefix) : -len(suffix)]
        if not name or "/" in name:
            return None
        return unquote(name)

    def _read_json(self) -> Any:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc

    def _read_multipart_form(self) -> tuple[dict[str, str], dict[str, tuple[str, bytes]]]:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type.lower():
            raise ValueError("Expected multipart/form-data upload")
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            raise ValueError("Upload body is empty")
        body = self.rfile.read(length)
        header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
        message = BytesParser(policy=policy.default).parsebytes(header + body)
        fields: dict[str, str] = {}
        files: dict[str, tuple[str, bytes]] = {}
        for part in message.iter_parts():
            if part.get_content_disposition() != "form-data":
                continue
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            payload = part.get_payload(decode=True) or b""
            filename = part.get_filename()
            if filename:
                files[str(name)] = (str(filename), payload)
                continue
            charset = part.get_content_charset() or "utf-8"
            fields[str(name)] = payload.decode(charset, errors="replace")
        return fields, files

    def _handle_login(self) -> None:
        payload = self._read_json()
        username = str(payload.get("username", "") if isinstance(payload, dict) else "").strip()
        password = str(payload.get("password", "") if isinstance(payload, dict) else "")
        user = USERS.get(username)
        if user is None or not secrets.compare_digest(str(user["password"]), password):
            return self._send_error(HTTPStatus.UNAUTHORIZED, "Invalid username or password")
        token = secrets.token_urlsafe(32)
        session = {
            "username": username,
            "role": user["role"],
            "display_name": user.get("display_name", username),
            "expires_at": time.time() + SESSION_TTL_SECONDS,
        }
        with _SESSION_LOCK:
            _SESSIONS[token] = session
        self._send_json(
            {"ok": True, "authenticated": True, "user": _public_user(session)},
            cookies=[_session_cookie(token)],
        )

    def _handle_logout(self) -> None:
        token = self._session_token()
        if token:
            with _SESSION_LOCK:
                _SESSIONS.pop(token, None)
        self._send_json({"ok": True}, cookies=[_clear_session_cookie()])

    def _current_user(self) -> dict[str, Any] | None:
        token = self._session_token()
        if not token:
            return None
        now = time.time()
        with _SESSION_LOCK:
            session = _SESSIONS.get(token)
            if session is None:
                return None
            if float(session.get("expires_at", 0.0)) <= now:
                _SESSIONS.pop(token, None)
                return None
            session["expires_at"] = now + SESSION_TTL_SECONDS
            return dict(session)

    def _session_token(self) -> str:
        raw = self.headers.get("Cookie", "")
        if not raw:
            return ""
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            return ""
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel is not None else ""

    def _require_login(self) -> dict[str, Any] | None:
        user = self._current_user()
        if user is None:
            self._send_error(HTTPStatus.UNAUTHORIZED, "Login required")
            return None
        return user

    def _require_admin(self) -> dict[str, Any] | None:
        user = self._require_login()
        if user is None:
            return None
        if user.get("role") != "admin":
            self._send_error(HTTPStatus.FORBIDDEN, "Admin permission required")
            return None
        return user

    def _send_json(
        self,
        payload: Any,
        *,
        status: HTTPStatus = HTTPStatus.OK,
        cookies: list[str] | None = None,
    ) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        for cookie in cookies or []:
            self.send_header("Set-Cookie", cookie)
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


def build_server(manager: RealtimeEkfRuntimeManager, host: str, port: int) -> ThreadingHTTPServer:
    class BoundHandler(RealtimeEkfRequestHandler):
        pass

    BoundHandler.manager = manager
    return ThreadingHTTPServer((host, int(port)), BoundHandler)


def _query_int(query: str, name: str, default: int) -> int:
    values = parse_qs(query).get(name)
    if not values:
        return default
    try:
        return int(values[0])
    except (TypeError, ValueError):
        return default


def _query_limit(query: dict[str, list[str]], *, default: int = 200) -> int | None:
    raw = (query.get("limit") or [str(default)])[0]
    text = str(raw or "").strip().lower()
    if text in {"", "all", "none", "0"}:
        return None
    try:
        return max(1, int(text))
    except (TypeError, ValueError):
        return default


def _query_datetime(query: dict[str, list[str]], name: str) -> datetime | None:
    raw = (query.get(name) or [""])[0]
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "y"}


def _session_cookie(token: str) -> str:
    return (
        f"{SESSION_COOKIE}={token}; Path=/; Max-Age={SESSION_TTL_SECONDS}; "
        "HttpOnly; SameSite=Lax"
    )


def _clear_session_cookie() -> str:
    return f"{SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"


def _public_user(user: dict[str, Any]) -> dict[str, Any]:
    role = str(user.get("role") or "")
    return {
        "username": user.get("username"),
        "display_name": user.get("display_name") or user.get("username"),
        "role": role,
        "permissions": {
            "admin": role == "admin",
            "manage_stations": role == "admin",
            "edit_config": role == "admin",
            "download_products": True,
            "view": True,
        },
    }


def _for_user(payload: Any, user: dict[str, Any]) -> Any:
    if user.get("role") == "admin":
        return payload
    return _redact_passwords(payload)


def _redact_passwords(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() == "password" and item:
                redacted[key] = "******"
            else:
                redacted[key] = _redact_passwords(item)
        return redacted
    if isinstance(value, list):
        return [_redact_passwords(item) for item in value]
    return value


__all__ = ["build_server"]
