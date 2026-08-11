"""Standalone GUI for batch RTCM/Unicore to RINEX conversion."""

from __future__ import annotations

import sys
import multiprocessing
import threading
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from utils.rtcm_batch_converter import (
    DEFAULT_EXTENSIONS,
    DEFAULT_MAX_WORKERS,
    BatchConversionOptions,
    BatchConversionReport,
    convert_folder,
    find_input_files,
)


class BatchConverterWorker(QObject):
    """Run conversion away from the Qt GUI thread."""

    progress = Signal(int, int, str, int, int, str)
    log = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, options: BatchConversionOptions) -> None:
        super().__init__()
        self.options = options
        self.cancel_event = threading.Event()

    @Slot()
    def run(self) -> None:
        try:
            def on_progress(index, total, path, item):
                output_names = ", ".join(output.name for output in item.output_paths)
                self.progress.emit(index, total, str(path), item.written_epochs, bool(item.error), output_names)

            report = convert_folder(
                self.options,
                cancel_event=self.cancel_event,
                progress_callback=on_progress,
                log_callback=self.log.emit,
            )
            self.completed.emit(report)
        except Exception as exc:
            self.failed.emit(str(exc))

    def cancel(self) -> None:
        self.cancel_event.set()


class BatchConverterWindow(QMainWindow):
    """Desktop batch conversion workbench."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("RTGS | RTCM to RINEX Batch Converter")
        self.resize(1240, 820)
        self.setMinimumSize(1000, 680)
        self._thread: QThread | None = None
        self._worker: BatchConverterWorker | None = None
        self._build_ui()
        self._apply_style()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        heading = QHBoxLayout()
        title_block = QVBoxLayout()
        title_block.setSpacing(2)
        title = QLabel("RTCM to RINEX")
        title.setObjectName("title")
        subtitle = QLabel("Batch converter")
        subtitle.setObjectName("subtitle")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        heading.addLayout(title_block)
        heading.addStretch()
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("status")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setFixedHeight(30)
        self.status_label.setMinimumWidth(72)
        heading.addWidget(self.status_label)
        root.addLayout(heading)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)

        settings_scroll = QScrollArea()
        settings_scroll.setObjectName("settingsScroll")
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        settings_scroll.setMinimumWidth(460)
        settings_scroll.setMaximumWidth(560)
        settings_widget = QWidget()
        settings_layout = QVBoxLayout(settings_widget)
        settings_layout.setContentsMargins(0, 0, 8, 0)
        settings_layout.setSpacing(10)
        settings_scroll.setWidget(settings_widget)

        paths = QGroupBox("Input and output")
        path_form = QFormLayout(paths)
        path_form.setContentsMargins(12, 14, 12, 12)
        path_form.setHorizontalSpacing(10)
        path_form.setVerticalSpacing(8)
        self.input_edit, input_row = self._path_row("Select input folder")
        self.output_edit, output_row = self._path_row("Select output folder")
        path_form.addRow("Input folder", input_row)
        path_form.addRow("Output folder", output_row)
        self.recursive_check = QCheckBox("Include subfolders")
        self.recursive_check.setChecked(True)
        self.extensions_edit = QLineEdit(", ".join(DEFAULT_EXTENSIONS))
        self.extensions_edit.setToolTip("Comma-separated extensions, for example .rtcm3, .dat")
        path_form.addRow("Scan", self.recursive_check)
        path_form.addRow("Extensions", self.extensions_edit)
        settings_layout.addWidget(paths)

        systems_group = QGroupBox("Constellations")
        systems_layout = QGridLayout(systems_group)
        systems_layout.setContentsMargins(12, 14, 12, 12)
        systems_layout.setHorizontalSpacing(16)
        systems_layout.setVerticalSpacing(6)
        self.system_checks: dict[str, QCheckBox] = {}
        for index, (code, name) in enumerate((
            ("G", "GPS"), ("R", "GLONASS"), ("E", "Galileo"), ("C", "BeiDou"),
            ("J", "QZSS"), ("S", "SBAS"), ("I", "NavIC"),
        )):
            check = QCheckBox(f"{code}  {name}")
            check.setChecked(code in {"G", "R", "E", "C"})
            self.system_checks[code] = check
            systems_layout.addWidget(check, index // 2, index % 2)
        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        for label, selected in (("GREC", {"G", "R", "E", "C"}), ("All", set(self.system_checks))):
            preset = QPushButton(label)
            preset.setObjectName("secondaryButton")
            preset.clicked.connect(lambda _checked=False, value=selected: self._set_systems(value))
            preset_row.addWidget(preset)
        clear_systems = QPushButton("Clear")
        clear_systems.setObjectName("secondaryButton")
        clear_systems.clicked.connect(lambda: self._set_systems(set()))
        preset_row.addWidget(clear_systems)
        preset_row.addStretch()
        systems_layout.addLayout(preset_row, 4, 0, 1, 2)
        settings_layout.addWidget(systems_group)

        obs_group = QGroupBox("Observation values")
        obs_layout = QGridLayout(obs_group)
        obs_layout.setContentsMargins(12, 14, 12, 12)
        obs_layout.setHorizontalSpacing(18)
        obs_layout.setVerticalSpacing(7)
        self.obs_checks: dict[str, QCheckBox] = {}
        for index, (code, label) in enumerate((
            ("C", "C  Pseudorange"), ("L", "L  Carrier phase"),
            ("D", "D  Doppler"), ("S", "S  Signal strength"),
        )):
            check = QCheckBox(label)
            check.setChecked(True)
            self.obs_checks[code] = check
            obs_layout.addWidget(check, index // 2, index % 2)
        obs_hint = QLabel("Unavailable values are left blank; no values are fabricated.")
        obs_hint.setObjectName("muted")
        obs_layout.addWidget(obs_hint, 2, 0, 1, 2)
        settings_layout.addWidget(obs_group)

        timing_group = QGroupBox("Timing")
        timing_form = QFormLayout(timing_group)
        timing_form.setContentsMargins(12, 14, 12, 12)
        timing_form.setVerticalSpacing(8)
        self.split_combo = QComboBox()
        self.split_combo.addItem("1 day", 86400.0)
        self.split_combo.addItem("1 hour", 3600.0)
        self.split_combo.addItem("30 minutes", 1800.0)
        self.split_combo.addItem("15 minutes", 900.0)
        self.split_combo.addItem("Custom", None)
        self.split_combo.currentIndexChanged.connect(self._update_custom_timing)
        timing_form.addRow("File duration", self.split_combo)
        self.split_custom = QDoubleSpinBox()
        self.split_custom.setRange(1.0, 31_536_000.0)
        self.split_custom.setValue(86400.0)
        self.split_custom.setSuffix(" s")
        self.split_custom.setDecimals(1)
        self.split_custom.setEnabled(False)
        timing_form.addRow("Custom duration", self.split_custom)
        self.sample_combo = QComboBox()
        self.sample_combo.addItem("Automatic (source cadence)", None)
        for value in (1.0, 5.0, 10.0, 15.0, 30.0, 60.0):
            self.sample_combo.addItem(f"{value:g} s", value)
        self.sample_combo.addItem("Custom", "custom")
        self.sample_combo.currentIndexChanged.connect(self._update_custom_timing)
        timing_form.addRow("Output interval", self.sample_combo)
        self.sample_custom = QDoubleSpinBox()
        self.sample_custom.setRange(0.01, 86400.0)
        self.sample_custom.setValue(1.0)
        self.sample_custom.setSuffix(" s")
        self.sample_custom.setDecimals(2)
        self.sample_custom.setEnabled(False)
        timing_form.addRow("Custom interval", self.sample_custom)
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 16)
        self.workers_spin.setValue(DEFAULT_MAX_WORKERS)
        self.workers_spin.setSuffix(" processes")
        timing_form.addRow("Parallel jobs", self.workers_spin)
        settings_layout.addWidget(timing_group)

        metadata = QGroupBox("RINEX header")
        metadata_layout = QGridLayout(metadata)
        metadata_layout.setContentsMargins(12, 14, 12, 12)
        metadata_layout.setHorizontalSpacing(10)
        metadata_layout.setVerticalSpacing(7)
        self.station_edit = QLineEdit("RTGS")
        self.marker_edit = QLineEdit()
        self.receiver_edit = QLineEdit()
        self.receiver_number_edit = QLineEdit("00")
        self.country_edit = QLineEdit("CHN")
        self.receiver_serial_edit = QLineEdit()
        self.receiver_version_edit = QLineEdit()
        self.antenna_edit = QLineEdit("UNKNOWN")
        self.antenna_number_edit = QLineEdit()
        self.position_edit = QLineEdit()
        self.position_edit.setPlaceholderText("X, Y, Z (meters, optional)")
        self.reference_date_edit = QLineEdit()
        self.reference_date_edit.setPlaceholderText("YYYY-MM-DD (optional)")
        metadata_fields = (
            ("Station", self.station_edit, "Marker", self.marker_edit),
            ("Receiver type", self.receiver_edit, "Receiver no.", self.receiver_number_edit),
            ("Country", self.country_edit, "Receiver serial", self.receiver_serial_edit),
            ("Firmware", self.receiver_version_edit, "Antenna type", self.antenna_edit),
            ("Antenna serial", self.antenna_number_edit, "Reference UTC date", self.reference_date_edit),
        )
        for row, (label_a, field_a, label_b, field_b) in enumerate(metadata_fields):
            metadata_layout.addWidget(QLabel(label_a), row, 0)
            metadata_layout.addWidget(field_a, row, 1)
            metadata_layout.addWidget(QLabel(label_b), row, 2)
            metadata_layout.addWidget(field_b, row, 3)
        metadata_layout.addWidget(QLabel("Approx. ECEF"), 5, 0)
        metadata_layout.addWidget(self.position_edit, 5, 1, 1, 3)
        self.overwrite_check = QCheckBox("Overwrite existing output names")
        metadata_layout.addWidget(self.overwrite_check, 6, 0, 1, 4)
        settings_layout.addWidget(metadata)
        settings_layout.addStretch(1)

        splitter.addWidget(settings_scroll)

        results_panel = QWidget()
        results_layout = QVBoxLayout(results_panel)
        results_layout.setContentsMargins(4, 0, 0, 0)
        results_layout.setSpacing(10)
        action_row = QHBoxLayout()
        self.start_button = QPushButton("Start conversion")
        self.start_button.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_MediaPlay))
        self.start_button.clicked.connect(self.start_conversion)
        self.start_button.setObjectName("primaryButton")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_MediaStop))
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_conversion)
        action_row.addWidget(self.start_button)
        action_row.addWidget(self.stop_button)
        action_row.addStretch(1)
        results_layout.addLayout(action_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        results_layout.addWidget(self.progress)

        results_group = QGroupBox("File results")
        results_group_layout = QVBoxLayout(results_group)
        results_group_layout.setContentsMargins(8, 12, 8, 8)
        self.results_table = QTableWidget(0, 4)
        self.results_table.setHorizontalHeaderLabels(("Input file", "Status", "Epochs", "Output files"))
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setColumnWidth(0, 180)
        self.results_table.setColumnWidth(1, 80)
        self.results_table.setColumnWidth(2, 70)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.setWordWrap(False)
        results_group_layout.addWidget(self.results_table)
        results_layout.addWidget(results_group, 1)

        log_group = QGroupBox("Activity log")
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(8, 12, 8, 8)
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMinimumHeight(140)
        log_layout.addWidget(self.log_edit)
        results_layout.addWidget(log_group, 0)
        splitter.addWidget(results_panel)
        splitter.setSizes([500, 700])
        root.addWidget(splitter, 1)

    def _path_row(self, dialog_title: str):
        edit = QLineEdit()
        button = QPushButton("Browse")
        button.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_DirOpenIcon))
        button.clicked.connect(lambda: self._choose_directory(edit, dialog_title))
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(edit, 1)
        layout.addWidget(button)
        return edit, row

    def _choose_directory(self, edit: QLineEdit, title: str) -> None:
        path = QFileDialog.getExistingDirectory(self, title, edit.text() or str(Path.home()))
        if path:
            edit.setText(path)

    def _set_systems(self, selected: set[str]) -> None:
        for code, check in self.system_checks.items():
            check.setChecked(code in selected)

    def _update_custom_timing(self) -> None:
        self.split_custom.setEnabled(self.split_combo.currentData() is None)
        self.sample_custom.setEnabled(self.sample_combo.currentData() == "custom")

    def _selected_split_seconds(self) -> float:
        value = self.split_combo.currentData()
        return float(self.split_custom.value() if value is None else value)

    def _selected_sample_seconds(self) -> float | None:
        value = self.sample_combo.currentData()
        return float(self.sample_custom.value()) if value == "custom" else value

    def _build_options(self) -> BatchConversionOptions:
        input_text = self.input_edit.text().strip()
        output_text = self.output_edit.text().strip()
        input_dir = Path(input_text).expanduser()
        output_dir = Path(output_text).expanduser()
        if not input_dir.is_dir():
            raise ValueError("Select a valid input folder.")
        if not output_text:
            raise ValueError("Select an output folder.")
        systems = tuple(code for code, check in self.system_checks.items() if check.isChecked())
        observations = tuple(code for code, check in self.obs_checks.items() if check.isChecked())
        extensions = tuple(item.strip() for item in self.extensions_edit.text().split(",") if item.strip())
        approx_position = None
        position_text = self.position_edit.text().strip()
        if position_text:
            try:
                values = [float(item) for item in position_text.replace(",", " ").split()]
            except ValueError as exc:
                raise ValueError("ECEF coordinates must contain three numbers.") from exc
            if len(values) != 3:
                raise ValueError("ECEF coordinates must contain X, Y and Z.")
            approx_position = tuple(values)
        reference_utc = None
        reference_text = self.reference_date_edit.text().strip()
        if reference_text:
            try:
                reference_utc = datetime.strptime(reference_text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError as exc:
                raise ValueError("Reference UTC date must use YYYY-MM-DD.") from exc
        return BatchConversionOptions(
            input_dir=input_dir,
            output_dir=output_dir,
            recursive=self.recursive_check.isChecked(),
            extensions=extensions,
            systems=systems,
            observation_types=observations,
            split_seconds=self._selected_split_seconds(),
            sample_interval_seconds=self._selected_sample_seconds(),
            station_code=self.station_edit.text().strip() or "RTGS",
            receiver_number=self.receiver_number_edit.text().strip() or "00",
            country_code=self.country_edit.text().strip() or "CHN",
            marker_name=self.marker_edit.text().strip(),
            receiver_type=self.receiver_edit.text().strip(),
            receiver_serial=self.receiver_serial_edit.text().strip(),
            receiver_version=self.receiver_version_edit.text().strip(),
            antenna_type=self.antenna_edit.text().strip() or "UNKNOWN",
            antenna_number=self.antenna_number_edit.text().strip(),
            reference_utc=reference_utc,
            approx_position=approx_position,
            overwrite=self.overwrite_check.isChecked(),
            max_workers=self.workers_spin.value(),
        )

    @Slot()
    def start_conversion(self) -> None:
        if self._thread is not None:
            return
        try:
            options = self._build_options()
            files = len(find_input_files(
                options.input_dir,
                recursive=options.recursive,
                extensions=options.extensions,
            ))
            if files == 0:
                raise ValueError("No matching RTCM/Unicore files were found.")
        except Exception as exc:
            QMessageBox.warning(self, "Invalid settings", str(exc))
            return

        self.results_table.setRowCount(0)
        self.log_edit.clear()
        self.progress.setValue(0)
        self.status_label.setText("Converting")
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self._thread = QThread(self)
        self._worker = BatchConverterWorker(options)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.log.connect(self.log_edit.append)
        self._worker.completed.connect(self._on_completed)
        self._worker.failed.connect(self._on_failed)
        self._worker.completed.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread_finished)
        self._thread.start()

    @Slot()
    def stop_conversion(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.status_label.setText("Stopping...")
            self.stop_button.setEnabled(False)

    @Slot(int, int, str, int, int, str)
    def _on_progress(self, index: int, total: int, path: str, written: int, failed: int, output_names: str) -> None:
        self.progress.setValue(int(index * 100 / max(1, total)))
        row = self.results_table.rowCount()
        self.results_table.insertRow(row)
        self.results_table.setItem(row, 0, QTableWidgetItem(Path(path).name))
        self.results_table.setItem(row, 1, QTableWidgetItem("Failed" if failed else "Done"))
        self.results_table.setItem(row, 2, QTableWidgetItem(str(written)))
        self.results_table.setItem(row, 3, QTableWidgetItem(output_names or "No output"))

    @Slot(object)
    def _on_completed(self, report: BatchConversionReport) -> None:
        state = "Cancelled" if report.cancelled else f"Done: {report.succeeded_files} succeeded, {report.failed_files} failed"
        self.status_label.setText(state)
        self.progress.setValue(100 if not report.cancelled else self.progress.value())
        self.log_edit.append(f"{state}; wrote {report.written_epochs} epochs")

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self.status_label.setText("Failed")
        self.log_edit.append(f"Conversion task failed: {message}")
        QMessageBox.critical(self, "Conversion failed", message)

    @Slot()
    def _thread_finished(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
        self._thread = None
        self._worker = None
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #edf1f5; color: #25313c; }
            QScrollArea#settingsScroll { border: 0; background: transparent; }
            QGroupBox { background: #ffffff; border: 1px solid #d5dce3; border-radius: 4px; margin-top: 9px; padding-top: 8px; font-weight: 600; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #3e4c59; }
            QLabel { color: #33414d; background: transparent; }
            QCheckBox { background: transparent; }
            QLabel#title { font-size: 24px; font-weight: 700; color: #16232e; }
            QLabel#subtitle { font-size: 12px; color: #73808c; }
            QLabel#status { color: #216a9d; background: #e6f1fa; border: 1px solid #c8e0f1; border-radius: 3px; padding: 5px 10px; font-weight: 600; }
            QLabel#muted { color: #71808e; font-size: 11px; }
            QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox, QTextEdit, QTableWidget { background: #ffffff; border: 1px solid #c7d0d9; border-radius: 3px; padding: 5px; selection-background-color: #2b78ad; }
            QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus, QTextEdit:focus { border: 1px solid #2b78ad; }
            QPushButton { background: #ffffff; color: #34424e; border: 1px solid #c7d0d9; border-radius: 3px; padding: 6px 12px; }
            QPushButton:hover { background: #f2f6f9; border-color: #8ca9bd; }
            QPushButton:disabled { color: #9aa5ae; background: #e7ebee; border-color: #d4dbe0; }
            QPushButton#primaryButton { background: #256f9f; color: #ffffff; border-color: #256f9f; font-weight: 600; padding: 7px 16px; }
            QPushButton#primaryButton:hover { background: #1c5d87; border-color: #1c5d87; }
            QPushButton#secondaryButton { padding: 4px 10px; }
            QProgressBar { border: 1px solid #c7d0d9; border-radius: 3px; background: #ffffff; text-align: center; height: 20px; }
            QProgressBar::chunk { background: #4d91bd; }
            QHeaderView::section { background: #e8edf1; color: #43515d; border: 0; border-bottom: 1px solid #cbd4dc; padding: 6px; font-weight: 600; }
            QTableWidget { gridline-color: #e1e6eb; alternate-background-color: #f7f9fb; }
            QSplitter::handle { background: #d9e0e6; }
            """
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._worker is not None:
            self._worker.cancel()
        if self._thread is not None:
            self.status_label.setText("Stopping...")
            self._thread.quit()
            if not self._thread.wait(5000):
                event.ignore()
                return
        event.accept()


def main() -> int:
    multiprocessing.freeze_support()
    app = QApplication(sys.argv)
    app.setApplicationName("RTGS RTCM Batch Converter")
    window = BatchConverterWindow()
    window.show()
    return app.exec()


__all__ = ["BatchConverterWorker", "BatchConverterWindow", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
