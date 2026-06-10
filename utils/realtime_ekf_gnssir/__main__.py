"""Command line entry point for realtime EKF-GNSSIR."""

from __future__ import annotations

import argparse
import signal
import threading
import time
from pathlib import Path

from .config import AppConfigStore


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run realtime EKF-GNSSIR water-level inversion from NTRIP RTCM streams.",
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parent / "config" / "app.yaml"),
        help="Realtime EKF-GNSSIR YAML config path.",
    )
    parser.add_argument("--station", action="append", default=[], help="Only expose/run the named station.")
    parser.add_argument("--host", default=None, help="Override Web bind host.")
    parser.add_argument("--port", type=int, default=None, help="Override Web bind port.")
    parser.add_argument("--no-web", action="store_true", help="Run station workers without Web UI.")
    parser.add_argument("--no-auto-start", action="store_true", help="Do not auto-start configured stations.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    from .runtime import RealtimeEkfRuntimeManager
    from .web import build_server

    store = AppConfigStore(args.config)
    config = store.load()
    manager = RealtimeEkfRuntimeManager(
        store,
        station_names=args.station,
        auto_start=not args.no_auto_start,
    )

    stop_event = threading.Event()
    server = None

    def request_stop(_signum=None, _frame=None) -> None:
        stop_event.set()

    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                signal.signal(sig, request_stop)
            except ValueError:
                pass

    manager.start()

    host = args.host or config.server.host
    port = int(args.port or config.server.port)

    if not args.no_web:
        server = build_server(manager, host, port)
        manager.logs.write("system", f"Web UI listening on http://{host}:{port}")
        server_thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True)
        server_thread.start()
        print(f"Realtime EKF-GNSSIR Web UI: http://{host}:{port}", flush=True)

    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        manager.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
