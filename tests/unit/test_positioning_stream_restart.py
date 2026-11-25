"""Regression coverage for applying changed positioning stream settings."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog

from ui.positioning import module as positioning_module


def _qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


class _StoppedWorker:
    name = "old-OBS"

    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True

    def is_alive(self) -> bool:
        return not self.stopped


def test_connect_after_stream_change_stops_old_worker_before_reconnect(monkeypatch) -> None:
    app = _qapp()
    window = positioning_module.PositioningModule()
    old_worker = _StoppedWorker()
    window.io_threads.append(old_worker)
    reconnected = []

    class _AcceptedDialog:
        auto_connect = True
        disconnect_requested = False

        def __init__(self, _parent, settings) -> None:
            self._settings = settings

        def exec(self):
            return QDialog.DialogCode.Accepted

        def get_settings(self):
            updated = dict(self._settings)
            updated["OBS"] = dict(updated["OBS"], mountpoint="NEW_STREAM")
            return updated

    monkeypatch.setattr(positioning_module, "ConfigDialog", _AcceptedDialog)
    monkeypatch.setattr(window, "start_streams", lambda: reconnected.append(True))

    try:
        window.open_config_dialog()
        app.processEvents()

        assert old_worker.stopped is True
        assert window.settings["OBS"]["mountpoint"] == "NEW_STREAM"
        assert reconnected == [True]
    finally:
        window.close()
