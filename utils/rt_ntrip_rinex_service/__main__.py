"""Command line entry point for the standalone service."""

from __future__ import annotations

import argparse
import signal
import threading
import time
from pathlib import Path

from .config_store import ConfigStore
from .manager import RuntimeManager
from .web import build_server


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run multiple RT NTRIP streams, write RINEX, and expose a Web management UI.",
    )
    parser.add_argument(
        "config",
        nargs="?",
        default=str(Path(__file__).resolve().parent / "examples" / "rt_multi_ntrip_rinex.yaml"),
        help="YAML config path.",
    )
    parser.add_argument("--station", action="append", default=[], help="Only run the named station. Repeatable.")
    parser.add_argument("--poll-seconds", type=int, default=60, help="Config polling interval in seconds.")
    parser.add_argument("--merge-poll-seconds", type=int, default=300, help="Daily merge scan interval in seconds.")
    parser.add_argument("--web-host", default="127.0.0.1", help="Web UI bind host.")
    parser.add_argument("--web-port", type=int, default=8088, help="Web UI bind port.")
    parser.add_argument("--no-web", action="store_true", help="Run workers without the Web UI.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    store = ConfigStore(args.config)
    manager = RuntimeManager(
        store,
        poll_seconds=args.poll_seconds,
        merge_poll_seconds=args.merge_poll_seconds,
        station_names=args.station,
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
    if not args.no_web:
        server = build_server(manager, args.web_host, args.web_port)
        manager.logs.write(f"Web UI listening on http://{args.web_host}:{args.web_port}")
        server_thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True)
        server_thread.start()
        try:
            while not stop_event.is_set():
                time.sleep(0.5)
        finally:
            server.shutdown()
            server.server_close()
            manager.stop()
        return 0

    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    finally:
        manager.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
