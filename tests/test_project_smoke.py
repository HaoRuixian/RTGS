"""项目级最小 smoke test。"""

from __future__ import annotations

import importlib

import pytest


def test_core_modules_import_and_ring_buffer_keeps_latest_items() -> None:
    """核心模块可导入，环形缓存满载时保留最新数据。"""
    from core.config_paths import default_ir_config_path, default_stream_config_path
    from core.data_models import EpochObservation, SatelliteState, SignalData
    from core.ring_buffer import RingBuffer

    assert default_stream_config_path().name == "example_config.yaml"
    assert default_ir_config_path().name == "default_ir.yaml"

    signal = SignalData(
        signal_id="1C",
        snr=45.0,
        phase=1000.0,
        pseudorange=21000000.0,
        lock_time=0,
        half_cycle=0,
        doppler=-1200.0,
    )
    satellite = SatelliteState(sys_id="G", prn=1, signals={"1C": signal})
    epoch = EpochObservation(gps_time=0.0, satellites={"G01": satellite})
    assert epoch.satellites["G01"].signals["1C"].snr == 45.0

    buffer = RingBuffer(maxsize=2)
    assert buffer.put("first")
    assert buffer.put("second")
    assert buffer.put("third")
    assert buffer.qsize() == 2
    assert buffer.get(block=False) == "second"
    assert buffer.get(block=False) == "third"
    assert buffer.get(block=False) is None


def test_gui_entrypoints_are_importable_when_gui_dependencies_exist() -> None:
    """GUI 依赖存在时，历史入口和标准入口都应可导入。"""
    for module_name in ("PySide6", "matplotlib", "numpy", "pandas", "scipy", "serial", "pyrtcm"):
        pytest.importorskip(module_name)

    gui_main = importlib.import_module("gui_main")
    main_module = importlib.import_module("main")
    app_manager = importlib.import_module("ui.app_manager")

    assert gui_main.APPLICATION_NAME == "RTGS - RealTimeGNSS Studio"
    assert callable(gui_main.main)
    assert main_module.main is gui_main.main
    assert hasattr(app_manager, "AppManager")
