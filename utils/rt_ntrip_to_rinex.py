"""Run multiple RT NTRIP streams and store them as RINEX using a YAML config."""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.rt_ntrip_rinex import MultiStationRTRinexService, load_rt_rinex_config


def _build_logger() -> Callable[[str], None]:
    lock = threading.Lock()

    def _log(message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with lock:
            print(f"[{timestamp}] {message}", flush=True)

    return _log


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="实时将多个 NTRIP 数据流转换为 RINEX 并按站点独立存储。"
    )
    parser.add_argument(
        "config",
        help="YAML 配置文件路径",
    )
    parser.add_argument(
        "--station",
        action="append",
        dest="stations",
        default=[],
        help="仅运行指定站点名称，可重复传入多个 --station",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    logger = _build_logger()

    try:
        config = load_rt_rinex_config(args.config)
        service = MultiStationRTRinexService(
            config,
            log_fn=logger,
            station_names=args.stations,
        )
    except Exception as exc:
        print(f"配置加载失败: {exc}", file=sys.stderr)
        return 1

    stop_requested = threading.Event()

    def _request_stop(_signum=None, _frame=None) -> None:
        if stop_requested.is_set():
            return
        stop_requested.set()
        logger("Stopping RT NTRIP-to-RINEX service...")
        service.stop()

    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                signal.signal(sig, _request_stop)
            except ValueError:
                pass

    logger(
        f"Loaded {len(service.workers)} station(s) from {Path(config.config_path).name}"
    )
    service.start()

    try:
        while not stop_requested.is_set():
            alive = any(worker.is_alive() for worker in service.workers)
            if not alive:
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        _request_stop()
    finally:
        service.stop()
        service.join(timeout=10.0)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
