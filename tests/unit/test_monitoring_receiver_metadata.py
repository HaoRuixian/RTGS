from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_processing_thread_emits_decoded_rtcm_1033_metadata() -> None:
    from ui.monitoring.workers import DataProcessingThread, StreamSignals

    class OneMessageBuffer:
        closed = False

        def __init__(self):
            self.item = (b"", SimpleNamespace(identity="1033"))

        def get(self, **_kwargs):
            if self.item is not None:
                item, self.item = self.item, None
                return item
            self.closed = True
            return None

    class Handler:
        last_reference_station_id = None
        last_receiver_type_descriptor = ""
        last_receiver_firmware_version = ""
        last_receiver_serial_number = ""
        last_antenna_descriptor = ""

        def process_message(self, _message):
            self.last_reference_station_id = 4
            self.last_receiver_type_descriptor = "SEPT MOSAIC-X5"
            self.last_receiver_firmware_version = "4.14.4"
            self.last_receiver_serial_number = "4014259"
            self.last_antenna_descriptor = "LEIAR25.R4 NONE"
            return None

    signals = StreamSignals()
    emitted = []
    signals.receiver_metadata_signal.connect(emitted.append)
    worker = DataProcessingThread("OBS", OneMessageBuffer(), Handler(), signals)
    worker.run()

    assert emitted == [
        {
            "station_id": 4,
            "receiver_type": "SEPT MOSAIC-X5",
            "receiver_firmware": "4.14.4",
            "receiver_serial": "4014259",
            "antenna_type": "LEIAR25.R4 NONE",
            "position_ecef": None,
            "position_source": "",
        }
    ]


def test_receiver_metadata_is_hidden_until_rtcm_1033_arrives() -> None:
    from PySide6.QtWidgets import QApplication

    from ui.monitoring.module import MonitoringModule

    app = QApplication.instance() or QApplication([])
    window = MonitoringModule()
    try:
        assert window.receiver_bar.isHidden()

        window.update_receiver_metadata(
            {
                "station_id": 4,
                "receiver_type": "SEPT MOSAIC-X5",
                "receiver_firmware": "4.14.4",
                "receiver_serial": "4014259",
                "antenna_type": "LEIAR25.R4 NONE",
            }
        )
        app.processEvents()

        assert not window.receiver_bar.isHidden()
        assert window.lbl_receiver.text() == "MOSAIC-X5  |  LEIAR25.R4"
        assert "Firmware: 4.14.4" in window.lbl_receiver.toolTip()
        assert "Antenna: LEIAR25.R4 NONE" in window.lbl_receiver.toolTip()

        window._reset_status_indicators()
        assert window.receiver_bar.isHidden()
        assert window.lbl_receiver.text() == ""
    finally:
        window.close()
        app.processEvents()


def test_station_coordinates_are_preferred_and_update_epoch_geometry() -> None:
    from core.global_config import get_global_config
    from ui.monitoring.workers import DataProcessingThread, StreamSignals

    receiver = [-2304501.715471, -3547589.403673, 4757288.493561]
    satellite = SimpleNamespace(
        sat_pos_ecef=[15600000.0, -20400000.0, 21700000.0],
        azimuth=None,
        elevation=None,
    )
    epoch = SimpleNamespace(satellites={"G01": satellite})
    handler = SimpleNamespace(
        last_station_coords=receiver,
        last_reference_station_id=2,
        last_receiver_type_descriptor="",
        last_receiver_firmware_version="",
        last_receiver_serial_number="",
        last_antenna_descriptor="",
    )
    worker = DataProcessingThread("OBS", None, handler, StreamSignals())

    metadata = worker._ensure_receiver_position(epoch)

    assert metadata["position_ecef"] == receiver
    assert metadata["position_source"] == "RTCM 1005/1006"
    assert satellite.azimuth is not None
    assert satellite.elevation is not None
    assert get_global_config().approx_rec_pos == receiver


def test_missing_station_coordinates_use_spp_and_persist_position(monkeypatch) -> None:
    from core.global_config import get_global_config
    from ui.monitoring.workers import DataProcessingThread, StreamSignals

    receiver = [-2304501.715471, -3547589.403673, 4757288.493561]
    satellite = SimpleNamespace(
        sat_pos_ecef=[15600000.0, -20400000.0, 21700000.0],
        azimuth=None,
        elevation=None,
    )
    epoch = SimpleNamespace(satellites={"G01": satellite})
    handler = SimpleNamespace(
        last_station_coords=None,
        last_reference_station_id=None,
        last_receiver_type_descriptor="",
        last_receiver_firmware_version="",
        last_receiver_serial_number="",
        last_antenna_descriptor="",
    )
    config = get_global_config()
    old_position = config.approx_rec_pos
    config.approx_rec_pos = [0.0, 0.0, 0.0]

    class FakeSpp:
        calls = []

        def __init__(self, **_kwargs):
            pass

        def process_epoch(self, received_epoch, approx_position=None):
            self.calls.append((received_epoch, approx_position))
            return SimpleNamespace(position_ecef=receiver)

    monkeypatch.setattr("ui.monitoring.workers.SPPPositioner", FakeSpp)
    worker = DataProcessingThread("OBS", None, handler, StreamSignals())
    try:
        metadata = worker._ensure_receiver_position(epoch)

        assert FakeSpp.calls == [(epoch, None)]
        assert metadata["position_ecef"] == receiver
        assert metadata["position_source"] == "SPP fallback"
        assert config.approx_rec_pos == receiver
        assert satellite.azimuth is not None
        assert satellite.elevation is not None
    finally:
        config.approx_rec_pos = old_position
