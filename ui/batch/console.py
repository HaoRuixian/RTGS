"""Standalone multi-station control console."""

from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.global_config import get_global_config
from ui.batch.station import StationRecord
from ui.batch.worker import StationProcess
from ui.shared.config_dialog import ConfigDialog

MODES = ("Monitoring", "Positioning", "Reflectometry", "Refractometry")


class StationEditorDialog(QDialog):
    """Collect the station identity and optionally load a complete YAML config."""

    def __init__(self, parent=None, station: StationRecord | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Station" if station is None else "Edit Station")
        self.resize(520, 180)
        self.station = station
        self.name_edit = QLineEdit(station.name if station else "")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(MODES)
        if station:
            self.mode_combo.setCurrentText(station.mode)
        self.path_edit = QLineEdit(station.config_path if station else "")
        self.path_edit.setReadOnly(True)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)

        form = QFormLayout()
        form.addRow("Station name:", self.name_edit)
        form.addRow("Run mode:", self.mode_combo)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)
        form.addRow("YAML config (optional):", path_row)

        ok = QPushButton("OK")
        cancel = QPushButton("Cancel")
        ok.clicked.connect(self._accept)
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select station configuration", "", "YAML Files (*.yaml *.yml);;All Files (*)"
        )
        if path:
            self.path_edit.setText(path)
            if not self.name_edit.text().strip():
                self.name_edit.setText(Path(path).stem)

    def _accept(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Station", "Please enter a station name.")
            return
        self.accept()

    def values(self) -> tuple[str, str, str]:
        return self.name_edit.text().strip(), self.mode_combo.currentText(), self.path_edit.text().strip()


class BatchConsole(QMainWindow):
    """Independent station supervisor for parallel monitoring and positioning."""

    HEADERS = [
        "Station",
        "Mode",
        "Stream",
        "State",
        "Messages",
        "Epochs",
        "Satellites",
        "Receiver / Antenna",
        "Position",
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._apply_light_palette()
        self.setWindowTitle("RTGS - Multi-Station Console")
        self.resize(1320, 680)
        self.setMinimumSize(980, 520)
        self.stations: list[StationRecord] = []
        self._detail_window = None
        self._detail_station_id: str | None = None
        self._detail_snapshot: dict | None = None
        self._detail_generation = 0
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_workers)
        self._timer.start(250)

        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #f5f7fb;
                color: #17212b;
            }
            QLabel {
                color: #17212b;
            }
            QPushButton {
                min-height: 34px;
                padding: 0 13px;
                border: 1px solid #b7c4d6;
                border-radius: 5px;
                background: #ffffff;
                color: #17212b;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #e8f1ff;
                border-color: #2563eb;
            }
            QPushButton:pressed {
                background: #d7e7ff;
            }
            QTableWidget {
                background: #ffffff;
                alternate-background-color: #f7f9fc;
                color: #17212b;
                selection-background-color: #cfe1ff;
                selection-color: #102a43;
                border: 1px solid #b7c4d6;
                gridline-color: #d8e0ea;
                font-size: 13px;
            }
            QTableWidget::item {
                padding: 7px 8px;
                color: #17212b;
            }
            QHeaderView::section {
                min-height: 32px;
                padding: 6px 8px;
                background: #e6edf6;
                color: #17212b;
                border: 0;
                border-right: 1px solid #c9d4e2;
                border-bottom: 1px solid #b7c4d6;
                font-size: 13px;
                font-weight: 700;
            }
            QMenu {
                background: #ffffff;
                color: #17212b;
                border: 1px solid #b7c4d6;
                padding: 5px;
                font-size: 13px;
            }
            QMenu::item {
                padding: 8px 28px 8px 12px;
            }
            QMenu::item:selected {
                background: #dbeafe;
                color: #102a43;
            }
            QLineEdit, QComboBox {
                min-height: 30px;
                background: #ffffff;
                color: #17212b;
                border: 1px solid #aebdce;
                border-radius: 4px;
                padding: 2px 7px;
            }
            QDialog {
                background: #f5f7fb;
                color: #17212b;
            }
            """
        )

    @staticmethod
    def _apply_light_palette() -> None:
        """Keep the standalone console and every detail module on a light theme."""
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return
        app.setStyle("Fusion")
        palette = app.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#f5f7fb"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#f7f9fc"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#17212b"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#17212b"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#17212b"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#cfe1ff"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#102a43"))
        app.setPalette(palette)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        title = QLabel("Multi-Station Console")
        title.setStyleSheet("font-size: 22px; font-weight: 700; color: #17212b;")
        subtitle = QLabel("Run independent monitoring and positioning pipelines side by side.")
        subtitle.setStyleSheet("font-size: 12px; color: #667085;")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        toolbar = QHBoxLayout()
        for text, callback in (
            ("Add Station", self.add_station),
            ("Edit Station", self.edit_station),
            ("Configure Streams", self.configure_station),
            ("Remove", self.remove_station),
            ("Start Selected", self.start_selected),
            ("Stop Selected", self.stop_selected),
            ("Start All", self.start_all),
            ("Stop All", self.stop_all),
        ):
            button = QPushButton(text)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_station_context_menu)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setMinimumSectionSize(105)
        for column, width in {
            0: 125,
            1: 105,
            2: 155,
            3: 175,
            4: 85,
            5: 75,
            6: 85,
            7: 190,
            8: 190,
        }.items():
            self.table.setColumnWidth(column, width)
        layout.addWidget(self.table, 1)

        self.summary = QLabel("No stations configured")
        self.summary.setStyleSheet("color: #667085; padding: 4px 2px;")
        layout.addWidget(self.summary)

    def _show_station_context_menu(self, position: QPoint) -> None:
        row = self.table.rowAt(position.y())
        if row < 0 or row >= len(self.stations):
            return
        self.table.selectRow(row)
        station = self.stations[row]
        menu = QMenu(self)
        current_mode = station.mode if station.mode in MODES else "Monitoring"
        menu.addAction(
            f"Open {current_mode} Details",
            lambda: self.open_station_detail(station, current_mode),
        )
        menu.addSeparator()
        for module_name in MODES:
            if module_name != current_mode:
                menu.addAction(
                    f"Open {module_name} Details",
                    lambda checked=False, name=module_name: self.open_station_detail(station, name),
                )
        menu.addSeparator()
        menu.addAction("Configure Streams", self.configure_station)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def open_station_detail(self, station: StationRecord, module_name: str) -> None:
        """Open a detailed workbench with this station's isolated configuration."""
        if self._detail_window is not None and self._detail_window.isVisible():
            if self._detail_station_id == station.station_id:
                self._detail_window.raise_()
                self._detail_window.activateWindow()
                return
            if self._detail_snapshot is not None:
                get_global_config().from_dict(self._detail_snapshot)
            self._detail_generation += 1
            self._detail_window.close()
            self._detail_window = None
            self._detail_station_id = None
            self._detail_snapshot = None

        from ui.monitoring.module import MonitoringModule
        from ui.positioning.module import PositioningModule
        from ui.reflectometry.module import ReflectometryModule
        from ui.refractometry.module import RefractometryModule

        module_classes = {
            "Monitoring": MonitoringModule,
            "Positioning": PositioningModule,
            "Reflectometry": ReflectometryModule,
            "Refractometry": RefractometryModule,
        }
        module_cls = module_classes[module_name]
        global_config = get_global_config()
        snapshot = copy.deepcopy(global_config.to_dict())
        self._detail_generation += 1
        detail_generation = self._detail_generation
        self._detail_snapshot = snapshot
        global_config.from_dict(station.payload())
        try:
            window = module_cls()
            window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            window.setWindowTitle(f"{window.windowTitle()} - {station.name}")
            window.back_to_launcher.connect(window.close)
            self._detail_window = window
            self._detail_station_id = station.station_id

            # These workbenches own their visual pipeline, so inject the same
            # station settings before starting their stream threads.
            if hasattr(window, "settings"):
                window.settings = station.legacy_settings()
            if module_name == "Monitoring":
                QTimer.singleShot(0, window.restart_streams)
            elif module_name == "Positioning":
                QTimer.singleShot(0, window.start_positioning)
            elif module_name == "Reflectometry":
                QTimer.singleShot(0, window.restart_streams)
            window.destroyed.connect(
                lambda _obj=None, saved=snapshot, generation=detail_generation: self._restore_detail_config(
                    saved, generation
                )
            )
            window.show()
            window.raise_()
            window.activateWindow()
        except Exception:
            global_config.from_dict(snapshot)
            self._detail_snapshot = None
            self._detail_window = None
            self._detail_station_id = None
            QMessageBox.critical(
                self,
                "Open detail module",
                f"Unable to open {module_name} for {station.name}.",
            )

    def _restore_detail_config(self, snapshot: dict, generation: int) -> None:
        if generation != self._detail_generation:
            return
        get_global_config().from_dict(snapshot)
        self._detail_snapshot = None
        self._detail_window = None
        self._detail_station_id = None

    def add_station(self) -> None:
        dialog = StationEditorDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, mode, path = dialog.values()
        try:
            station = StationRecord.from_yaml(path, name=name, mode=mode) if path else StationRecord(name, mode)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Station configuration", str(exc))
            return
        self.stations.append(station)
        self._refresh_table(select_index=len(self.stations) - 1)

    def edit_station(self) -> None:
        station = self._selected_station()
        if station is None:
            return
        if station._runtime is not None:
            QMessageBox.information(self, "Station", "Stop the station before editing it.")
            return
        dialog = StationEditorDialog(self, station)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, mode, path = dialog.values()
        station.name, station.mode = name, mode
        if path and path != station.config_path:
            try:
                station.config = StationRecord.from_yaml(path).config
                station.config_path = path
            except (OSError, ValueError) as exc:
                QMessageBox.critical(self, "Station configuration", str(exc))
                return
        self._refresh_table()

    def configure_station(self) -> None:
        station = self._selected_station()
        if station is None:
            return
        if station._runtime is not None:
            QMessageBox.information(self, "Station", "Stop the station before editing streams.")
            return
        global_config = get_global_config()
        snapshot = copy.deepcopy(global_config.to_dict())
        dialog = ConfigDialog(self, station.legacy_settings())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            global_config.from_dict(snapshot)
            return
        try:
            values = dialog.get_settings()
            station.update_from_legacy(values)
            station.config["positioning_settings"] = copy.deepcopy(
                global_config.get_positioning_settings()
            )
        finally:
            # ConfigDialog is shared with the single-station UI and updates the
            # singleton on accept; restore it immediately to keep this console isolated.
            global_config.from_dict(snapshot)
        self._refresh_table()

    def remove_station(self) -> None:
        indexes = sorted({index.row() for index in self.table.selectionModel().selectedRows()}, reverse=True)
        for row in indexes:
            station = self.stations[row]
            self._stop_station(station)
            del self.stations[row]
        self._refresh_table()

    def start_selected(self) -> None:
        for station in self._selected_stations():
            self._start_station(station)

    def stop_selected(self) -> None:
        for station in self._selected_stations():
            self._stop_station(station)

    def start_all(self) -> None:
        for station in self.stations:
            self._start_station(station)

    def stop_all(self) -> None:
        for station in self.stations:
            self._stop_station(station)

    def _start_station(self, station: StationRecord) -> None:
        if station._runtime is not None and station._runtime.is_alive():
            return
        station.status = "Starting"
        station.stream_status = "Connecting"
        station.last_error = ""
        station.message_count = station.epoch_count = station.satellite_count = 0
        runtime = StationProcess(station.station_id, station.mode, station.payload())
        station._runtime = runtime
        try:
            runtime.start()
        except Exception as exc:
            station._runtime = None
            station.status = "Error"
            station.last_error = str(exc)
        self._refresh_table()

    def _stop_station(self, station: StationRecord) -> None:
        if station._runtime is not None:
            station.status = "Stopping"
            station._runtime.stop()
        else:
            station.status = "Stopped"
        self._refresh_table()

    def _poll_workers(self) -> None:
        for station in self.stations:
            runtime = station._runtime
            if runtime is None:
                continue
            for event in runtime.poll():
                self._apply_event(station, event)
            if not runtime.is_alive() and station.status not in {"Stopped", "Error"}:
                runtime.join(0.1)
                station._runtime = None
                if station.status != "Error":
                    station.status = "Stopped"
        self._refresh_table()

    def _apply_event(self, station: StationRecord, event: dict) -> None:
        kind = event.get("kind")
        station.last_update = str(event.get("time", ""))
        if kind == "started":
            station.status = "Running"
        elif kind == "stream":
            station.stream_status = str(event.get("value", ""))
            if station.status == "Starting":
                station.status = "Running"
        elif kind == "metrics":
            station.message_count = int(event.get("messages", station.message_count))
            station.epoch_count = int(event.get("epochs", station.epoch_count))
            station.satellite_count = int(event.get("satellites", station.satellite_count))
        elif kind == "metadata":
            station.receiver = str(event.get("receiver", station.receiver))
            station.antenna = str(event.get("antenna", station.antenna))
            if event.get("position"):
                station.position = str(event["position"])
        elif kind == "position":
            station.position = str(event.get("value", ""))
        elif kind == "error":
            station.status = "Error"
            station.last_error = str(event.get("value", ""))
        elif kind == "stopped":
            station.status = "Stopped"
            runtime = station._runtime
            station._runtime = None
            if runtime is not None:
                runtime.join(0.1)

    def _selected_stations(self) -> list[StationRecord]:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        return [self.stations[row] for row in rows if 0 <= row < len(self.stations)]

    def _selected_station(self) -> StationRecord | None:
        selected = self._selected_stations()
        return selected[0] if selected else None

    def _refresh_table(self, select_index: int | None = None) -> None:
        self.table.setRowCount(len(self.stations))
        running = 0
        for row, station in enumerate(self.stations):
            if station.status in {"Running", "Starting", "Stopping"}:
                running += 1
            values = [
                station.name,
                station.mode,
                (
                    f"{station.config.get('obs_settings', {}).get('mountpoint', '') or '-'}"
                    f" ({station.stream_status})"
                ),
                station.status if not station.last_error else f"{station.status}: {station.last_error}",
                str(station.message_count),
                str(station.epoch_count),
                str(station.satellite_count),
                " / ".join(value for value in (station.receiver, station.antenna) if value) or "-",
                station.position or "-",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(row, column, item)
        self.summary.setText(f"{len(self.stations)} stations | {running} active")
        if select_index is not None and 0 <= select_index < len(self.stations):
            self.table.selectRow(select_index)

    def closeEvent(self, event) -> None:
        self._timer.stop()
        if self._detail_window is not None:
            if self._detail_snapshot is not None:
                get_global_config().from_dict(self._detail_snapshot)
            self._detail_generation += 1
            self._detail_window.close()
            self._detail_window = None
            self._detail_snapshot = None
        self.stop_all()
        for station in self.stations:
            if station._runtime is not None:
                station._runtime.join(2.0)
                station._runtime = None
        event.accept()
