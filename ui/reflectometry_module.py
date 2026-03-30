"""Reflectometry module integrated with the application's core reflectometry pipeline."""

from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from datetime import datetime
import logging
import threading
import time

import matplotlib.dates as mdates
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import numpy as np
import yaml
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QSpinBox,
)

from core.geo_utils import ecef2lla
from core.config_paths import default_ir_config_path, ensure_config_directories
from core.global_config import get_global_config
from core.replay_ui_policy import (
    THROTTLED_GUI_INTERVAL_SECONDS,
    choose_gui_refresh_interval,
    estimate_effective_replay_period_seconds,
)
from core.ring_buffer import RingBuffer
from core.rtcm_handler import get_shared_handler
from core.reflectometry import (
    ObservationRecord,
    ProcessingRunResult,
    ProductType,
    RealtimeProcessor,
    ReceiverPosition,
    config_to_dict,
    dump_example_config,
    load_config,
)
from core.reflectometry.config import minimum_required_arc_samples
from core.reflectometry.models import SnrSeries
from core.reflectometry.rinex_batch import build_observation_records_from_epoch
from core.reflectometry.services.geometry import matches_reflection_zones
from core.reflectometry.models import ArcSolution, ProductResult
from ui.ConfigDialog import ConfigDialog
from ui.gnss_colordef import get_sys_color
from ui.monitoring.workers import DataProcessingThread, IOThread, RinexReplayThread, StreamSignals
from ui.reflectometry.arc_status import (
    ArcSelectorOption,
    ArcStatusRow,
    TrackingArcContext,
    build_solution_selector_option,
    build_solution_status_row,
    build_tracking_context,
    build_tracking_selector_option,
    build_tracking_status_row,
    collect_latest_tracking_buffers,
    format_arc_time_summary,
    match_live_arc_id_for_solution,
)
from ui.reflectometry.ir_config_dialog import ReflectometryConfigDialog
from ui.reflectometry.skyplot_dialog import ReflectometrySkyplotDialog
from ui.reflectometry.workers import ReflectometryBatchSignals, RinexBatchAnalysisThread
from ui.style import get_app_stylesheet
from ui.responsive import adaptive_window_size, window_ui_scale


class ToolbarCanvasPanel(QWidget):
    """Small helper widget bundling toolbar and matplotlib canvas."""

    def __init__(self, figsize: tuple[float, float] = (8.0, 4.5), parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.figure = Figure(figsize=figsize, dpi=100, facecolor="#FFFFFF")
        self.canvas = FigureCanvas(self.figure)
        self.toolbar = NavigationToolbar(self.canvas, self)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)


class SortableTableWidgetItem(QTableWidgetItem):
    """Table item with an explicit sort key for stable numeric and datetime sorting."""

    def __init__(self, text: str, *, sort_value=None) -> None:
        super().__init__(text)
        self.sort_value = text if sort_value is None else sort_value

    def __lt__(self, other: QTableWidgetItem) -> bool:
        other_value = getattr(other, "sort_value", other.text())
        try:
            return self.sort_value < other_value
        except Exception:
            return super().__lt__(other)


class ReflectometryModule(QMainWindow):
    """GNSS reflectometry workbench using the application's core reflectometry pipeline."""

    back_to_launcher = Signal()
    ALL_SYSTEMS = ("G", "R", "E", "C", "J", "S", "I")
    PRODUCT_VIEW_LABELS = {
        "by_system": "By System",
        "by_direction": "By Arc Direction",
        "by_signal": "By Signal / Frequency",
        "by_pnr_band": "By P/N Band",
        "pnr_weighted_epoch": "PNR-Weighted Epoch",
    }

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("GNSS RT Reflectometry Module")
        adaptive_window_size(self, target=(1800, 1000), minimum=(1120, 700))

        self.analysis_logger = logging.getLogger("reflectometry_ui.analysis")
        self.analysis_logger.handlers.clear()
        self.analysis_logger.addHandler(logging.NullHandler())
        self.analysis_logger.propagate = False

        self.merged_satellites: dict[str, object] = {}
        self.sat_last_seen: dict[str, float] = {}
        self.observation_buffer: deque[ObservationRecord] = deque()
        self.latest_epoch_data = None
        self.latest_result: ProcessingRunResult | None = None
        self.latest_series_by_arc = {}
        self.last_processor: RealtimeProcessor | None = None
        self.selected_arc_id: str | None = None
        self.last_analysis_timestamp: datetime | None = None
        self.analysis_running = False
        self.analysis_loop_enabled = False
        self.analysis_button_state = "idle"
        self.batch_analysis_thread: RinexBatchAnalysisThread | None = None
        self.skyplot_dialog: ReflectometrySkyplotDialog | None = None
        self.live_realtime_processor: RealtimeProcessor | None = None
        self.pending_live_records: list[ObservationRecord] = []
        self.live_product_history: dict[tuple[str, str, str], ProductResult] = {}
        self.processed_observation_count = 0
        self.selected_product_type: str | None = None
        self.selected_product_view_mode = "by_system"
        self.product_system_checks: dict[str, QCheckBox] = {}
        self.tracking_context_by_arc: dict[str, TrackingArcContext] = {}
        self.solution_arc_key_map: dict[str, str] = {}
        self.current_live_arc_ids: set[str] = set()
        self._compact_scale = None

        self.last_gui_update_time = 0.0
        self.base_gui_update_interval = 0.4
        self.gui_update_interval = self.base_gui_update_interval
        self.pending_update = False
        self.last_runtime_config_signature: tuple[object, ...] | None = None

        config = get_global_config()
        self.active_systems = set(config.target_systems) if config.target_systems else set(self.ALL_SYSTEMS)
        self.stream_status = {"OBS": False, "EPH": False}
        self.eph_data_available = False

        self.signals = StreamSignals()
        self.signals.log_signal.connect(self.append_log)
        self.signals.epoch_signal.connect(self.process_gui_epoch)
        self.signals.status_signal.connect(self.update_status)
        self.batch_signals = ReflectometryBatchSignals()
        self.batch_signals.log_signal.connect(self.append_log)
        self.batch_signals.completed.connect(self._on_batch_analysis_completed)
        self.batch_signals.failed.connect(self._on_batch_analysis_failed)
        self.batch_signals.cancelled.connect(self._on_batch_analysis_cancelled)

        self.io_threads: list[IOThread] = []
        self.processing_threads: list[DataProcessingThread] = []
        self.ring_buffers: dict[str, RingBuffer] = {}
        self.handler = get_shared_handler()

        self.settings = self._default_stream_settings()
        self._apply_gui_refresh_policy(announce=False)
        ensure_config_directories()
        self.ir_config_path = default_ir_config_path()
        if not self.ir_config_path.exists():
            dump_example_config(self.ir_config_path)
        self.ir_config = load_config(self.ir_config_path)
        self.ir_config.logging.console = False
        self.ir_config.logging.rotating_file = False
        self.active_systems = self._configured_active_systems()

        self.setup_ui()
        self._sync_mode_combo_label()
        self._apply_runtime_controls_from_config()
        self._sync_runtime_ir_defaults(force=True)
        self._refresh_config_view()
        self._update_summary_cards()

        self.cleanup_timer = threading.Timer(1.0, self.cleanup_stale_satellites)
        self.cleanup_timer.daemon = True
        self.cleanup_timer.start()

        self.gui_update_timer = QTimer()
        self.gui_update_timer.timeout.connect(self._check_pending_update)
        self.gui_update_timer.start(80)

        self.analysis_timer = QTimer()
        self.analysis_timer.timeout.connect(self._maybe_run_auto_analysis)
        self.analysis_timer.start(1000)

        self.signals.log_signal.emit("=== GNSS Reflectometry module ready ===")
        self.signals.log_signal.emit("Edit or import an IR config, then connect a realtime OBS/EPH stream to start analysis.")

    def setup_ui(self) -> None:
        """Build the reflectometry UI with the same visual language as Monitoring."""
        self.setStyleSheet(get_app_stylesheet())

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        top_bar = QHBoxLayout()

        self.btn_back = QPushButton("< Back to Launcher")
        self.btn_back.clicked.connect(self.on_back_to_launcher)
        top_bar.addWidget(self.btn_back)

        top_bar.addWidget(self._make_separator())

        self.btn_cfg = QPushButton("Config")
        try:
            settings_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogInfoView)
            if not settings_icon.isNull():
                self.btn_cfg.setIcon(settings_icon)
        except Exception:
            pass
        self.btn_cfg.clicked.connect(self.open_config_dialog)
        top_bar.addWidget(self.btn_cfg)

        self.btn_ir_config = QPushButton("IR Config")
        self.btn_ir_config.clicked.connect(self.open_ir_config_dialog)
        top_bar.addWidget(self.btn_ir_config)

        self.btn_run = QPushButton("Start Analysis")
        self.btn_run.clicked.connect(self.toggle_analysis)
        top_bar.addWidget(self.btn_run)

        self.btn_export = QPushButton("Export Results")
        self.btn_export.clicked.connect(self.export_results)
        top_bar.addWidget(self.btn_export)

        top_bar.addWidget(self._make_separator())

        self.lbl_window = QLabel("Arc Window (min):")
        top_bar.addWidget(self.lbl_window)
        self.window_spin = QSpinBox()
        self.window_spin.setRange(5, 240)
        self.window_spin.setValue(20)
        self.window_spin.setToolTip("Maximum arc duration retained for realtime IR analysis. Older samples are discarded.")
        self.window_spin.valueChanged.connect(self._on_window_changed)
        top_bar.addWidget(self.window_spin)

        self.lbl_interval = QLabel("Interval (s):")
        top_bar.addWidget(self.lbl_interval)
        self.auto_interval_spin = QSpinBox()
        self.auto_interval_spin.setRange(3, 600)
        self.auto_interval_spin.setValue(20)
        top_bar.addWidget(self.auto_interval_spin)

        top_bar.addWidget(self._make_separator())
        self.lbl_systems = QLabel("Systems:")
        top_bar.addWidget(self.lbl_systems)
        self.chk_sys: dict[str, QCheckBox] = {}
        self._system_names = {
            "G": ("GPS", "GPS"),
            "R": ("GLONASS", "GLO"),
            "E": ("Galileo", "GAL"),
            "C": ("BeiDou", "BDS"),
            "J": ("QZSS", "QZS"),
            "S": ("SBAS", "SBAS"),
            "I": ("IRNSS", "IRN"),
        }
        for sys_char, name in [
            ("G", "GPS"),
            ("R", "GLONASS"),
            ("E", "Galileo"),
            ("C", "BeiDou"),
            ("J", "QZSS"),
            ("S", "SBAS"),
            ("I", "IRNSS"),
        ]:
            checkbox = QCheckBox(name)
            checkbox.setChecked(sys_char in self.active_systems)
            checkbox.setStyleSheet(f"QCheckBox {{ color: {get_sys_color(sys_char)}; font-weight: bold; }}")
            checkbox.stateChanged.connect(self.on_filter_changed)
            self.chk_sys[sys_char] = checkbox
            top_bar.addWidget(checkbox)

        for widget in [
            self.lbl_window,
            self.window_spin,
            self.lbl_interval,
            self.auto_interval_spin,
            self.lbl_systems,
            *self.chk_sys.values(),
        ]:
            widget.setVisible(False)

        self.lbl_status_obs = QLabel("OBS: OFF")
        self.lbl_status_eph = QLabel("EPH: OFF")
        for label in (self.lbl_status_obs, self.lbl_status_eph):
            label.setProperty("class", "status")
            top_bar.addWidget(label)
        self._render_status_indicators()

        top_bar.addStretch()
        layout.addLayout(top_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)
        self.left_panel.setMinimumWidth(360)
        self.left_panel.setMaximumWidth(420)

        summary_frame = QFrame()
        summary_frame.setObjectName("Panel")
        grid = QGridLayout(summary_frame)
        grid.setContentsMargins(16, 16, 16, 16)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)

        self.mountpoint_label = QLabel("--")
        self.mountpoint_label.setWordWrap(True)
        self.mountpoint_label.setStyleSheet("font-size: 22px; font-weight: 800; color: #0F172A; margin-bottom: 6px;")
        left_layout.addWidget(self.mountpoint_label)

        self.summary_labels: dict[str, QLabel] = {}
        summary_rows = [
            ("IR Config", "ir_config"),
            ("Analysis Mode", "analysis_mode"),
            ("Tracked Sats", "tracked_satellites"),
            ("Buffered", "buffered_samples"),
            ("Last Run", "last_run"),
            ("Arc Count", "arc_solutions"),
            ("Successful", "successful_arcs"),
            ("Height", "latest_height"),
            ("Sea Level", "latest_sea_level"),
            ("Snow Depth", "latest_snow_depth"),
        ]
        for row_index, (title, key) in enumerate(summary_rows):
            title_label = QLabel(title)
            title_label.setStyleSheet("color: #64748B; font-size: 12px;")
            value_label = QLabel("--")
            value_label.setStyleSheet("font-weight: 700; color: #1E293B; font-size: 13px;")
            value_label.setWordWrap(True)
            self.summary_labels[key] = value_label
            r = row_index // 2
            c = (row_index % 2) * 2
            grid.addWidget(title_label, r, c)
            grid.addWidget(value_label, r, c + 1)

        left_layout.addWidget(summary_frame)

        live_header_row = QHBoxLayout()
        live_header_row.setContentsMargins(4, 8, 4, 4)
        live_header_row.setSpacing(8)
        live_header_row.addWidget(QLabel("<b>Tracking</b>"))
        live_header_row.addStretch()
        self.btn_show_skyplot = QPushButton("Skyplot")
        skyplot_icon = self._standard_icon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        if skyplot_icon is not None:
            self.btn_show_skyplot.setIcon(skyplot_icon)
        self.btn_show_skyplot.setToolTip("Open a skyplot with the configured reflection zones highlighted.")
        self.btn_show_skyplot.clicked.connect(self.open_skyplot_dialog)
        live_header_row.addWidget(self.btn_show_skyplot)
        left_layout.addLayout(live_header_row)
        self.live_table = QTableWidget()
        self.live_table.setColumnCount(4)
        self.live_table.setHorizontalHeaderLabels(["Satellite", "Elevation", "Azimuth", "Signals"])
        self.live_table.setAlternatingRowColors(True)
        self.live_table.setShowGrid(False)
        self.live_table.setWordWrap(True)
        self.live_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.live_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.live_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.live_table.verticalHeader().setVisible(False)
        self.live_table.verticalHeader().setDefaultSectionSize(32)
        live_header = self.live_table.horizontalHeader()
        live_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        live_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        live_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        live_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.live_table.setStyleSheet(
            """
            QTableWidget {
                background: #FFFFFF;
                border: 1px solid #D7E0EA;
                border-radius: 10px;
                alternate-background-color: #F7FAFC;
                gridline-color: transparent;
                padding: 4px;
            }
            QTableWidget::item {
                padding: 8px 10px;
                border-bottom: 1px solid #EEF2F6;
            }
            QHeaderView::section {
                background: #EEF4FA;
                color: #1F2937;
                padding: 8px 10px;
                border: 0;
                border-bottom: 1px solid #D7E0EA;
                font-weight: 600;
            }
            """
        )
        left_layout.addWidget(self.live_table, stretch=1)

        splitter.addWidget(self.left_panel)

        self.main_tabs = QTabWidget()
        self.main_tabs.addTab(self._build_dashboard_tab(), "Arc Status")
        self.main_tabs.addTab(self._build_series_tab(), "Arc Series")
        self.main_tabs.addTab(self._build_products_tab(), "Products")
        self.main_tabs.addTab(self._build_config_tab(), "IR Config")
        splitter.addWidget(self.main_tabs)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 7)
        splitter.setCollapsible(0, False)
        layout.addWidget(splitter, stretch=1)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMaximumHeight(80)
        self.max_log_lines = 500
        layout.addWidget(self.log_area)
        self._set_run_button_state("idle")
        self._apply_compact_ui()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_compact_ui()

    def _apply_compact_ui(self) -> None:
        if not hasattr(self, "left_panel") or not hasattr(self, "product_selector"):
            return
        scale = window_ui_scale(self)
        if self._compact_scale == scale:
            return

        self._compact_scale = scale
        self.setStyleSheet(get_app_stylesheet(scale))
        self.left_panel.setMinimumWidth(max(300, int(360 * scale)))
        self.left_panel.setMaximumWidth(max(360, int(420 * scale)))
        self.product_selector.setMinimumWidth(max(180, int(220 * scale)))
        self.log_area.setMaximumHeight(max(60, int(80 * scale)))
        self.mountpoint_label.setStyleSheet(
            f"font-size: {max(16, int(20 * scale))}px; font-weight: 800; color: #0F172A;"
        )
        self.btn_back.setText("< Back to Launcher")
        self.btn_ir_config.setText("IR Config")
        self.btn_export.setText("Export Results")
        self.lbl_window.setText("Arc Window (min):")
        self.lbl_interval.setText("Interval (s):")
        self.lbl_systems.setText("Systems:")

        for sys_char, checkbox in self.chk_sys.items():
            full_text, _short_text = self._system_names[sys_char]
            checkbox.setText(full_text)

        self._set_run_button_state(self.analysis_button_state)
        self._render_status_indicators()

    def _build_dashboard_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.arc_table = QTableWidget()
        self.arc_table.setColumnCount(11)
        self.arc_table.setHorizontalHeaderLabels(
            [
                "Arc ID",
                "Satellite",
                "Signal",
                "Direction",
                "Time",
                "Elevation (deg)",
                "Mean Az (deg)",
                "Reflector Height (m)",
                "P/N",
                "Status",
                "QC / Reason",
            ]
        )
        self.arc_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.arc_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.arc_table.setAlternatingRowColors(True)
        self.arc_table.setShowGrid(False)
        self.arc_table.verticalHeader().setVisible(False)
        self.arc_table.itemSelectionChanged.connect(self._on_arc_selection_changed)
        header = self.arc_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(10, QHeaderView.ResizeMode.Stretch)
        self.arc_table.setStyleSheet(
            """
            QTableWidget {
                background: #FFFFFF;
                border: 1px solid #D7E0EA;
                border-radius: 10px;
                alternate-background-color: #F7FAFC;
                gridline-color: transparent;
            }
            QTableWidget::item {
                padding: 7px 10px;
                border-bottom: 1px solid #EEF2F6;
            }
            QTableWidget::item:selected {
                background: #E6F0FB;
                color: #0F172A;
            }
            QHeaderView::section {
                background: #EEF4FA;
                color: #0F172A;
                padding: 8px 10px;
                border: 0;
                border-bottom: 1px solid #D7E0EA;
                font-weight: 700;
            }
            """
        )
        layout.addWidget(self.arc_table)
        return widget

    def _build_series_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)

        selector_frame = QFrame()
        selector_frame.setObjectName("Panel")
        selector_layout = QHBoxLayout(selector_frame)
        selector_layout.setContentsMargins(12, 10, 12, 10)
        selector_layout.setSpacing(10)

        selector_layout.addWidget(QLabel("Arc Segment"))
        self.arc_selector_combo = QComboBox()
        self.arc_selector_combo.currentIndexChanged.connect(self._on_arc_selector_changed)
        selector_layout.addWidget(self.arc_selector_combo, stretch=1)

        self.btn_prev_arc = QPushButton("Previous")
        self.btn_prev_arc.clicked.connect(lambda: self._step_arc_selection(-1))
        selector_layout.addWidget(self.btn_prev_arc)

        self.btn_next_arc = QPushButton("Next")
        self.btn_next_arc.clicked.connect(lambda: self._step_arc_selection(1))
        selector_layout.addWidget(self.btn_next_arc)

        layout.addWidget(selector_frame)

        detail_frame = QFrame()
        detail_frame.setObjectName("Panel")
        detail_grid = QGridLayout(detail_frame)
        detail_grid.setContentsMargins(16, 16, 16, 16)
        detail_grid.setHorizontalSpacing(16)
        detail_grid.setVerticalSpacing(8)

        self.arc_detail_labels: dict[str, QLabel] = {}
        detail_rows = [
            ("Arc ID", "arc_id"),
            ("Satellite", "satellite"),
            ("Signal", "signal"),
            ("Direction", "direction"),
            ("Time Span", "time_span"),
            ("Start El", "start_el"),
            ("End El", "end_el"),
            ("Mean Az", "mean_az"),
            ("Reflector Height", "height"),
            ("Peak P/N", "peak_pnr"),
        ]
        for row_index, (title, key) in enumerate(detail_rows):
            title_label = QLabel(title)
            title_label.setStyleSheet("color: #64748B; font-size: 12px;")
            value_label = QLabel("--")
            value_label.setWordWrap(True)
            value_label.setStyleSheet("font-weight: 700; color: #1E293B; font-size: 13px;")
            self.arc_detail_labels[key] = value_label
            detail_grid.addWidget(title_label, row_index // 2, (row_index % 2) * 2)
            detail_grid.addWidget(value_label, row_index // 2, (row_index % 2) * 2 + 1)

        layout.addWidget(detail_frame)

        content_splitter = QSplitter(Qt.Orientation.Horizontal)

        series_container = QFrame()
        series_container.setObjectName("Panel")
        series_layout = QVBoxLayout(series_container)
        series_layout.setContentsMargins(12, 12, 12, 12)
        series_layout.setSpacing(8)
        self.series_header = QLabel("Choose an arc segment to inspect raw SNR and detrended residuals.")
        self.series_header.setWordWrap(True)
        self.series_header.setStyleSheet("color: #64748B; font-size: 12px; margin-bottom: 4px;")
        series_layout.addWidget(self.series_header)
        self.series_panel = ToolbarCanvasPanel(figsize=(8.5, 5.8))
        self.series_ax_raw = self.series_panel.figure.add_subplot(211)
        self.series_ax_residual = self.series_panel.figure.add_subplot(212)
        self.series_panel.figure.subplots_adjust(hspace=0.38, bottom=0.10, top=0.92, left=0.10, right=0.97)
        series_layout.addWidget(self.series_panel)
        content_splitter.addWidget(series_container)

        spectrum_container = QFrame()
        spectrum_container.setObjectName("Panel")
        spectrum_layout = QVBoxLayout(spectrum_container)
        spectrum_layout.setContentsMargins(12, 12, 12, 12)
        spectrum_layout.setSpacing(8)
        self.spectrum_header = QLabel("Spectrum and the primary peak for the selected arc will appear here.")
        self.spectrum_header.setWordWrap(True)
        self.spectrum_header.setStyleSheet("color: #64748B; font-size: 12px; margin-bottom: 4px;")
        spectrum_layout.addWidget(self.spectrum_header)
        self.spectrum_panel = ToolbarCanvasPanel(figsize=(6.2, 4.2))
        self.spectrum_ax = self.spectrum_panel.figure.add_subplot(111)
        self.spectrum_panel.figure.subplots_adjust(bottom=0.22, top=0.90, left=0.12, right=0.98)
        spectrum_layout.addWidget(self.spectrum_panel, stretch=4)
        self.primary_peak_label = QLabel("Primary peak metrics will appear here.")
        self.primary_peak_label.setWordWrap(True)
        self.primary_peak_label.setObjectName("HintLabel")
        self.primary_peak_label.setStyleSheet("font-weight: 700; color: #1E293B; font-size: 13px; margin-top: 8px;")
        spectrum_layout.addWidget(self.primary_peak_label)
        content_splitter.addWidget(spectrum_container)

        content_splitter.setStretchFactor(0, 7)
        content_splitter.setStretchFactor(1, 5)
        layout.addWidget(content_splitter, stretch=1)

        self._clear_series_plot()
        self._clear_spectrum_plot()
        self._clear_arc_detail_summary()
        self._populate_arc_selector()
        return widget

    def _build_products_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        controls_layout = QHBoxLayout()
        controls_layout.addWidget(QLabel("Variable:"))
        self.product_selector = QComboBox()
        self.product_selector.setMinimumWidth(220)
        self.product_selector.currentIndexChanged.connect(self._on_product_selection_changed)
        controls_layout.addWidget(self.product_selector)
        controls_layout.addSpacing(12)
        controls_layout.addWidget(QLabel("Display:"))
        self.product_view_mode_combo = QComboBox()
        self.product_view_mode_combo.addItem("By System", "by_system")
        self.product_view_mode_combo.addItem("By Arc Direction", "by_direction")
        self.product_view_mode_combo.addItem("By Signal / Frequency", "by_signal")
        self.product_view_mode_combo.addItem("By P/N Band", "by_pnr_band")
        self.product_view_mode_combo.addItem("PNR-Weighted Epoch", "pnr_weighted_epoch")
        self.product_view_mode_combo.currentIndexChanged.connect(self._on_product_view_mode_changed)
        controls_layout.addWidget(self.product_view_mode_combo)
        controls_layout.addSpacing(12)
        controls_layout.addWidget(QLabel("Systems:"))
        for sys_char, label in [
            ("G", "GPS"),
            ("R", "GLO"),
            ("E", "GAL"),
            ("C", "BDS"),
            ("J", "QZS"),
            ("S", "SBAS"),
            ("I", "IRNSS"),
        ]:
            checkbox = QCheckBox(label)
            checkbox.setChecked(True)
            checkbox.stateChanged.connect(self._on_product_system_filter_changed)
            checkbox.setStyleSheet(f"color: {get_sys_color(sys_char)}; font-weight: 600;")
            self.product_system_checks[sys_char] = checkbox
            controls_layout.addWidget(checkbox)
        controls_layout.addStretch(1)
        layout.addLayout(controls_layout)

        self.product_panel = ToolbarCanvasPanel()
        self.product_ax = self.product_panel.figure.add_subplot(111)
        self.product_panel.figure.subplots_adjust(bottom=0.16, top=0.92, left=0.09, right=0.97)
        layout.addWidget(self.product_panel)

        self.product_table = QTableWidget()
        self.product_table.setColumnCount(8)
        self.product_table.setHorizontalHeaderLabels(
            ["Timestamp", "System", "Direction", "Satellite", "Signal / Freq", "Value", "Unit", "P/N"]
        )
        self.product_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.product_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.product_table.setAlternatingRowColors(True)
        self.product_table.setShowGrid(False)
        self.product_table.setWordWrap(False)
        self.product_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.product_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.product_table.verticalHeader().setVisible(False)
        self.product_table.verticalHeader().setDefaultSectionSize(32)
        product_header = self.product_table.horizontalHeader()
        product_header.setSectionsClickable(True)
        product_header.setSortIndicatorShown(True)
        product_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        product_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        product_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        product_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        product_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        product_header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        product_header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        product_header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        product_header.setSortIndicator(0, Qt.SortOrder.DescendingOrder)
        self.product_table.setSortingEnabled(True)
        self.product_table.setStyleSheet(
            """
            QTableWidget {
                background: #FFFFFF;
                border: 1px solid #D7E0EA;
                border-radius: 10px;
                alternate-background-color: #F8FBFF;
                gridline-color: transparent;
                padding: 4px;
            }
            QTableWidget::item {
                padding: 7px 10px;
                border-bottom: 1px solid #EEF2F6;
            }
            QTableWidget::item:selected {
                background: #E7F0FA;
                color: #0F172A;
            }
            QHeaderView::section {
                background: #EEF4FA;
                color: #0F172A;
                padding: 8px 10px;
                border: 0;
                border-bottom: 1px solid #D7E0EA;
                font-weight: 700;
            }
            """
        )
        layout.addWidget(self.product_table)
        self._populate_product_selector()
        self._clear_product_plot()
        return widget

    def _build_config_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        runtime_card = QFrame()
        runtime_card.setObjectName("Panel")
        runtime_layout = QVBoxLayout(runtime_card)
        runtime_layout.setContentsMargins(16, 16, 16, 16)
        runtime_layout.setSpacing(10)

        runtime_title = QLabel("Realtime Product Controls")
        runtime_title.setStyleSheet("font-size: 16px; font-weight: 800; color: #0F172A;")
        runtime_layout.addWidget(runtime_title)

        runtime_description = QLabel(
            "Adjust the in-memory IR config used by the current session. "
            "Use the full IR Config editor if you also want to save these values back to YAML."
        )
        runtime_description.setWordWrap(True)
        runtime_description.setStyleSheet("color: #475569;")
        runtime_layout.addWidget(runtime_description)

        runtime_grid = QGridLayout()
        runtime_grid.setHorizontalSpacing(12)
        runtime_grid.setVerticalSpacing(8)

        self.runtime_dynamic_correction_chk = QCheckBox("Enable second-order dynamic sea-level correction")
        self.runtime_dynamic_correction_chk.setToolTip(
            "Apply the second-order dynamic correction from the current IR config to realtime sea-level products."
        )
        self.runtime_dynamic_correction_chk.stateChanged.connect(self._on_runtime_dynamic_controls_changed)
        runtime_grid.addWidget(QLabel("Dynamic Correction"), 0, 0)
        runtime_grid.addWidget(self.runtime_dynamic_correction_chk, 0, 1)

        self.runtime_dynamic_window_spin = QDoubleSpinBox()
        self.runtime_dynamic_window_spin.setRange(0.5, 48.0)
        self.runtime_dynamic_window_spin.setDecimals(2)
        self.runtime_dynamic_window_spin.setSingleStep(0.5)
        self.runtime_dynamic_window_spin.setKeyboardTracking(False)
        self.runtime_dynamic_window_spin.setSuffix(" h")
        self.runtime_dynamic_window_spin.setToolTip(
            "Trailing time window used to estimate sea-level rate and acceleration for the dynamic correction."
        )
        self.runtime_dynamic_window_spin.valueChanged.connect(self._on_runtime_dynamic_controls_changed)
        runtime_grid.addWidget(QLabel("Window Length"), 1, 0)
        runtime_grid.addWidget(self.runtime_dynamic_window_spin, 1, 1)

        runtime_layout.addLayout(runtime_grid)

        self.runtime_dynamic_status_label = QLabel()
        self.runtime_dynamic_status_label.setWordWrap(True)
        self.runtime_dynamic_status_label.setStyleSheet("color: #334155;")
        runtime_layout.addWidget(self.runtime_dynamic_status_label)

        runtime_button_row = QHBoxLayout()
        runtime_button_row.addStretch()
        runtime_editor_button = QPushButton("Open Full IR Config")
        runtime_editor_button.clicked.connect(self.open_ir_config_dialog)
        runtime_button_row.addWidget(runtime_editor_button)
        runtime_layout.addLayout(runtime_button_row)

        layout.addWidget(runtime_card)

        self.config_info_label = QLabel()
        self.config_info_label.setWordWrap(True)
        layout.addWidget(self.config_info_label)

        self.config_text = QPlainTextEdit()
        self.config_text.setReadOnly(True)
        layout.addWidget(self.config_text)
        return widget

    def _default_stream_settings(self) -> dict:
        global_config = get_global_config()
        obs_cfg = global_config.obs_settings
        eph_cfg = global_config.eph_settings
        return {
            "OBS": {
                "source": getattr(obs_cfg, "source_type", "NTRIP Server"),
                "host": getattr(obs_cfg, "host", ""),
                "port": getattr(obs_cfg, "port", 2101),
                "mountpoint": getattr(obs_cfg, "mountpoint", ""),
                "user": getattr(obs_cfg, "user", ""),
                "password": getattr(obs_cfg, "password", ""),
                "baudrate": getattr(obs_cfg, "baudrate", 115200),
                "databits": getattr(obs_cfg, "databits", 8),
                "stopbits": getattr(obs_cfg, "stopbits", 1),
                "parity": getattr(obs_cfg, "parity", "None"),
                "flowctrl": getattr(obs_cfg, "flowctrl", "None"),
                "file_path": getattr(obs_cfg, "file_path", ""),
                "replay_speed": getattr(obs_cfg, "replay_speed", 1.0),
                "file_type": getattr(obs_cfg, "file_type", "Auto Detect"),
                "final_results_only": getattr(obs_cfg, "final_results_only", False),
            },
            "EPH_ENABLED": bool(getattr(eph_cfg, "enabled", False)),
            "EPH": {
                "source": getattr(eph_cfg, "source_type", "NTRIP Server"),
                "host": getattr(eph_cfg, "host", ""),
                "port": getattr(eph_cfg, "port", 2101),
                "mountpoint": getattr(eph_cfg, "mountpoint", ""),
                "user": getattr(eph_cfg, "user", ""),
                "password": getattr(eph_cfg, "password", ""),
                "baudrate": getattr(eph_cfg, "baudrate", 115200),
                "databits": getattr(eph_cfg, "databits", 8),
                "stopbits": getattr(eph_cfg, "stopbits", 1),
                "parity": getattr(eph_cfg, "parity", "None"),
                "flowctrl": getattr(eph_cfg, "flowctrl", "None"),
                "file_path": getattr(eph_cfg, "file_path", ""),
                "replay_speed": getattr(eph_cfg, "replay_speed", 1.0),
                "file_type": getattr(eph_cfg, "file_type", "Auto Detect"),
                "final_results_only": getattr(eph_cfg, "final_results_only", False),
            },
        }

    def _make_separator(self) -> QFrame:
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        return separator

    def _on_mode_changed(self) -> None:
        if not self.analysis_running:
            self._set_run_button_state("active" if self.analysis_loop_enabled else "idle")
        self._update_summary_cards()

    def _on_window_changed(self, _: int) -> None:
        self._trim_observation_buffer()
        self._clear_live_product_history()
        self._reset_realtime_processing(reseed_from_buffer=True)
        self.refresh_live_widgets()

    def _configured_active_systems(self) -> set[str]:
        include = {item.strip() for item in self.ir_config.input.constellations if str(item).strip()}
        exclude = {item.strip() for item in self.ir_config.input.exclude_constellations if str(item).strip()}
        active = include if include else set(self.ALL_SYSTEMS)
        return active - exclude

    def _apply_runtime_controls_from_config(self) -> None:
        active_systems = self._configured_active_systems()
        self.active_systems = active_systems

        if hasattr(self, "window_spin"):
            self.window_spin.blockSignals(True)
            try:
                self.window_spin.setValue(int(max(1, self.ir_config.processing.live_arc_window_minutes)))
            finally:
                self.window_spin.blockSignals(False)

        if hasattr(self, "auto_interval_spin"):
            self.auto_interval_spin.blockSignals(True)
            try:
                self.auto_interval_spin.setValue(int(max(1, self.ir_config.processing.live_analysis_interval_seconds)))
            finally:
                self.auto_interval_spin.blockSignals(False)

        for sys_char, checkbox in getattr(self, "chk_sys", {}).items():
            checkbox.blockSignals(True)
            try:
                checkbox.setChecked(sys_char in active_systems)
            finally:
                checkbox.blockSignals(False)

        self._sync_runtime_dynamic_controls_from_config()

    def _sync_runtime_dynamic_controls_from_config(self) -> None:
        if not hasattr(self, "runtime_dynamic_correction_chk"):
            return

        self.runtime_dynamic_correction_chk.blockSignals(True)
        self.runtime_dynamic_window_spin.blockSignals(True)
        try:
            self.runtime_dynamic_correction_chk.setChecked(
                bool(self.ir_config.products.enable_dynamic_sea_level_correction)
            )
            self.runtime_dynamic_window_spin.setValue(float(self.ir_config.products.dynamic_sea_level_window_hours))
        finally:
            self.runtime_dynamic_correction_chk.blockSignals(False)
            self.runtime_dynamic_window_spin.blockSignals(False)

        self._update_runtime_dynamic_control_state()

    def _update_runtime_dynamic_control_state(self) -> None:
        if not hasattr(self, "runtime_dynamic_correction_chk"):
            return

        sea_level_enabled = bool(self.ir_config.products.enable_sea_level)
        correction_enabled = bool(self.runtime_dynamic_correction_chk.isChecked())
        window_hours = float(self.runtime_dynamic_window_spin.value())

        self.runtime_dynamic_correction_chk.setEnabled(sea_level_enabled)
        self.runtime_dynamic_window_spin.setEnabled(sea_level_enabled and correction_enabled)

        if not sea_level_enabled:
            self.runtime_dynamic_status_label.setText(
                "Dynamic correction is currently unavailable because sea-level products are disabled in this IR config."
            )
            return

        if correction_enabled:
            self.runtime_dynamic_status_label.setText(
                f"Realtime sea-level estimation is using the second-order trailing-window correction. "
                f"Current window length: {window_hours:g} h."
            )
            return

        self.runtime_dynamic_status_label.setText(
            "Realtime sea-level estimation is currently showing the raw sea-level product without the second-order correction."
        )

    def _on_runtime_dynamic_controls_changed(self, _value=None) -> None:
        if not hasattr(self, "runtime_dynamic_correction_chk"):
            return

        if not self.ir_config.products.enable_sea_level:
            self._update_runtime_dynamic_control_state()
            return

        enabled = bool(self.runtime_dynamic_correction_chk.isChecked())
        window_hours = float(self.runtime_dynamic_window_spin.value())
        previous_enabled = bool(self.ir_config.products.enable_dynamic_sea_level_correction)
        previous_window = float(self.ir_config.products.dynamic_sea_level_window_hours)

        self.ir_config.products.enable_dynamic_sea_level_correction = enabled
        self.ir_config.products.dynamic_sea_level_window_hours = window_hours
        self._update_runtime_dynamic_control_state()
        self._refresh_config_view()

        if previous_enabled == enabled and abs(previous_window - window_hours) < 1e-9:
            return

        self.append_log(
            "Realtime dynamic sea-level correction updated: "
            f"{'enabled' if enabled else 'disabled'}, window {window_hours:g} h."
        )

        if self.analysis_running:
            self.append_log("New dynamic-correction settings will be applied after the current analysis finishes.")
            return

        if self._is_headless_file_analysis_mode():
            self.append_log("Re-run Start Analysis to regenerate fast file-analysis products with the new correction settings.")
            return

        if not self.observation_buffer:
            return

        self._clear_live_product_history()
        self._reset_realtime_processing(reseed_from_buffer=True)
        self.run_ir_analysis()

    def _use_fast_file_analysis(self) -> bool:
        return self._is_headless_file_analysis_mode()

    def _is_headless_file_analysis_mode(self) -> bool:
        obs_settings = self.settings.get("OBS", {}) or {}
        return (
            str(obs_settings.get("source", "")) == "RINEX File"
            and bool(obs_settings.get("final_results_only", False))
        )

    def _is_rinex_replay_source(self) -> bool:
        obs_settings = self.settings.get("OBS", {}) or {}
        return str(obs_settings.get("source", "")) == "RINEX File"

    def _mode_label(self) -> str:
        if self._is_headless_file_analysis_mode():
            return "File Fast Loop (Realtime Logic)"
        if self._is_rinex_replay_source():
            return "File Replay (Realtime Logic)"
        return "Realtime Stream"

    def _sync_mode_combo_label(self) -> None:
        if not hasattr(self, "mode_combo"):
            return
        label = self._mode_label()
        self.mode_combo.blockSignals(True)
        try:
            self.mode_combo.clear()
            self.mode_combo.addItem(label)
            self.mode_combo.setCurrentIndex(0)
        finally:
            self.mode_combo.blockSignals(False)

    @staticmethod
    def _ecef_position_from_global_config() -> list[float] | None:
        approx_rec_pos = getattr(get_global_config(), "approx_rec_pos", None)
        if approx_rec_pos and len(approx_rec_pos) == 3 and any(abs(float(item)) > 1e-6 for item in approx_rec_pos):
            return [float(approx_rec_pos[0]), float(approx_rec_pos[1]), float(approx_rec_pos[2])]
        return None

    def toggle_analysis(self) -> None:
        if self._is_headless_file_analysis_mode():
            self.run_ir_analysis()
            return
        self._set_analysis_loop_enabled(
            not self.analysis_loop_enabled,
            announce=True,
            trigger_now=not self.analysis_loop_enabled,
        )

    def _set_analysis_loop_enabled(self, enabled: bool, *, announce: bool, trigger_now: bool = False) -> None:
        if enabled == self.analysis_loop_enabled and not trigger_now:
            return
        self.analysis_loop_enabled = enabled

        if announce:
            if self._is_headless_file_analysis_mode():
                mode_label = "fast file"
            else:
                mode_label = "replay" if self._is_rinex_replay_source() else "realtime"
            self.append_log(
                f"Automatic {mode_label} reflectometry analysis started."
                if enabled
                else f"Automatic {mode_label} reflectometry analysis stopped."
            )

        if not enabled and not self.analysis_running:
            self._set_run_button_state("idle")
        elif enabled:
            self._reset_realtime_processing(reseed_from_buffer=True)
            self._set_run_button_state("active")
            if trigger_now:
                QTimer.singleShot(0, self._maybe_run_auto_analysis)

    @Slot(object)
    def process_gui_epoch(self, epoch_data) -> None:
        """Receive one EpochObservation from the shared processing pipeline."""
        self.latest_epoch_data = epoch_data
        try:
            self.handler.apply_station_coordinates()
        except Exception:
            pass
        self._sync_runtime_ir_defaults()

        now = time.time()
        timestamp = getattr(epoch_data, "utc_datetime", None) or datetime.utcnow()
        epoch_records = self._epoch_to_observation_records(epoch_data, timestamp)
        for record in epoch_records:
            self.observation_buffer.append(record)
        self.pending_live_records.extend(epoch_records)
        self._trim_observation_buffer(timestamp)

        for prn, sat in getattr(epoch_data, "satellites", {}).items():
            self.merged_satellites[prn] = sat
            self.sat_last_seen[prn] = now

        if now - self.last_gui_update_time >= self.gui_update_interval:
            self.refresh_live_widgets()
            self.last_gui_update_time = now
            self.pending_update = False
        else:
            self.pending_update = True

    def _epoch_to_observation_records(self, epoch_data, timestamp: datetime) -> list[ObservationRecord]:
        """Convert one EpochObservation into canonical reflectometry observations."""
        receiver_position = self._current_receiver_position(self.ir_config.station.receiver_position)
        observations = build_observation_records_from_epoch(
            epoch_data,
            station_id=self.ir_config.station.station_id,
            timestamp=timestamp,
            receiver_position=receiver_position,
            active_systems=set(self.active_systems),
            input_config=self.ir_config.input,
        )
        return [record for record in observations if self._record_matches_buffer_filters(record)]

    def _trim_observation_buffer(self, reference_time: datetime | None = None) -> None:
        """Keep only the most recent realtime observations inside the analysis window."""
        if not self.observation_buffer:
            self.pending_live_records.clear()
            return
        end_time = reference_time or self.observation_buffer[-1].timestamp
        cutoff = end_time.timestamp() - self._live_window_seconds()
        while self.observation_buffer and self.observation_buffer[0].timestamp.timestamp() < cutoff:
            self.observation_buffer.popleft()
        self._trim_pending_live_records(end_time)

    def _trim_pending_live_records(self, reference_time: datetime | None = None) -> None:
        """Keep pending realtime samples aligned with the configured arc window."""
        if not self.pending_live_records:
            return
        end_time = reference_time or self.pending_live_records[-1].timestamp
        cutoff = end_time.timestamp() - self._live_window_seconds()
        self.pending_live_records = [
            record for record in self.pending_live_records if record.timestamp.timestamp() >= cutoff
        ]

    def _live_window_seconds(self) -> float:
        """Return the realtime analysis window length in seconds."""
        return float(self.window_spin.value()) * 60.0

    def refresh_live_widgets(self) -> None:
        """Refresh realtime observation widgets and summary cards."""
        self._populate_live_observation_table()
        if self.analysis_loop_enabled or self.analysis_running or self.live_realtime_processor:
            self._populate_arc_table()
        self._refresh_skyplot_dialog()
        self._update_summary_cards()

    def _populate_live_observation_table(self) -> None:
        self.live_table.setRowCount(0)
        satellites = [(key, sat) for key, sat in sorted(self.merged_satellites.items()) if key[0] in self.active_systems]
        for satellite_key, satellite in satellites:
            elevation = getattr(satellite, "elevation", getattr(satellite, "el", None))
            azimuth = getattr(satellite, "azimuth", getattr(satellite, "az", None))
            if not self._geometry_matches_buffer_filters(
                azimuth_deg=_optional_float(azimuth),
                elevation_deg=_optional_float(elevation),
            ):
                continue
            signals = getattr(satellite, "signals", {}) or {}
            valid_signals = {
                signal_key: signal
                for signal_key, signal in signals.items()
                if float(getattr(signal, "snr", 0.0) or 0.0) > 0.0 and self._signal_is_enabled(satellite_key[0], str(signal_key))
            }
            if not valid_signals:
                continue
            signal_list = ", ".join(sorted(str(signal_key) for signal_key in valid_signals))
            display_elevation = _optional_float(elevation)
            row_values = [
                satellite_key,
                f"{display_elevation:.2f} deg" if display_elevation is not None else "--",
                f"{float(azimuth):.2f} deg" if azimuth is not None else "--",
                signal_list,
            ]
            row_index = self.live_table.rowCount()
            self.live_table.insertRow(row_index)
            for column, value in enumerate(row_values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setForeground(QColor(get_sys_color(satellite_key[0])))
                    item.setData(Qt.ItemDataRole.ToolTipRole, f"{satellite_key} is currently tracked.")
                elif column == 3:
                    item.setData(Qt.ItemDataRole.ToolTipRole, signal_list)
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                self.live_table.setItem(row_index, column, item)
        self.live_table.resizeRowsToContents()

    def _record_matches_buffer_filters(self, record: ObservationRecord) -> bool:
        if record.constellation not in self.active_systems:
            return False
        if not self._signal_is_enabled(record.constellation, record.signal):
            return False
        return self._geometry_matches_buffer_filters(record.azimuth_deg, record.elevation_deg)

    def _signal_is_enabled(self, constellation: str, signal: str) -> bool:
        include_constellations = set(self.ir_config.input.constellations)
        include_signals = set(self.ir_config.input.signals)
        exclude_constellations = set(self.ir_config.input.exclude_constellations)
        exclude_signals = set(self.ir_config.input.exclude_signals)

        if include_constellations and constellation not in include_constellations:
            return False
        if constellation in exclude_constellations:
            return False
        if include_signals and signal not in include_signals:
            return False
        if signal in exclude_signals:
            return False
        return True

    def _geometry_matches_buffer_filters(
        self,
        azimuth_deg: float | None,
        elevation_deg: float | None,
    ) -> bool:
        if azimuth_deg is None or elevation_deg is None:
            return False
        return matches_reflection_zones(
            azimuth_deg=float(azimuth_deg),
            elevation_deg=float(elevation_deg),
            geometry_config=self.ir_config.geometry,
            processing_config=self.ir_config.processing,
        )

    def _reset_realtime_processing(self, *, reseed_from_buffer: bool = False) -> None:
        if self.live_realtime_processor is not None:
            self.live_realtime_processor.reset()
        self.live_realtime_processor = None
        self.pending_live_records = list(self.observation_buffer) if reseed_from_buffer else []

    def _filtered_satellites_snapshot(self) -> dict[str, object]:
        snapshot: dict[str, object] = {}
        for satellite_key, satellite in sorted(self.merged_satellites.items()):
            if satellite_key[0] not in self.active_systems:
                continue
            signals = getattr(satellite, "signals", {}) or {}
            has_enabled_signal = any(
                float(getattr(signal, "snr", 0.0) or 0.0) > 0.0 and self._signal_is_enabled(satellite_key[0], str(signal_key))
                for signal_key, signal in signals.items()
            )
            if has_enabled_signal:
                snapshot[satellite_key] = satellite
        return snapshot

    def open_skyplot_dialog(self) -> None:
        if self.skyplot_dialog is None:
            self.skyplot_dialog = ReflectometrySkyplotDialog(self)
            self.skyplot_dialog.finished.connect(self._clear_skyplot_dialog_reference)
        self._refresh_skyplot_dialog()
        self.skyplot_dialog.show()
        self.skyplot_dialog.raise_()
        self.skyplot_dialog.activateWindow()

    def _clear_skyplot_dialog_reference(self, _result: int | None = None) -> None:
        self.skyplot_dialog = None

    def _refresh_skyplot_dialog(self) -> None:
        if self.skyplot_dialog is None:
            return
        self.skyplot_dialog.update_view(
            satellites=self._filtered_satellites_snapshot(),
            active_systems=set(self.active_systems),
            geometry_config=self.ir_config.geometry,
            processing_config=self.ir_config.processing,
        )

    def _standard_icon(self, pixmap: QStyle.StandardPixmap):
        try:
            icon = self.style().standardIcon(pixmap)
        except Exception:
            return None
        return icon if not icon.isNull() else None

    def _set_run_button_state(self, state: str, tooltip: str | None = None) -> None:
        self.analysis_button_state = state
        if self._is_headless_file_analysis_mode():
            mode_prefix = "Fast File Analysis"
            active_text = "Fast File Analysis Running"
        elif self._is_rinex_replay_source():
            mode_prefix = "Replay Analysis"
            active_text = "Stop Replay Analysis"
        else:
            mode_prefix = "Realtime Analysis"
            active_text = "Stop Realtime Analysis"
        button_states = {
            "idle": {
                "text": f"Start {mode_prefix}",
                "icon": QStyle.StandardPixmap.SP_MediaPlay,
                "color": "#2563EB",
                "border": "#1D4ED8",
            },
            "active": {
                "text": active_text,
                "icon": QStyle.StandardPixmap.SP_MediaStop,
                "color": "#0F766E",
                "border": "#115E59",
            },
            "running": {
                "text": f"Running {mode_prefix}...",
                "icon": QStyle.StandardPixmap.SP_MediaStop,
                "color": "#EA580C",
                "border": "#C2410C",
            },
            "success": {
                "text": f"{mode_prefix} Complete",
                "icon": QStyle.StandardPixmap.SP_DialogApplyButton,
                "color": "#15803D",
                "border": "#166534",
            },
            "failed": {
                "text": f"{mode_prefix} Failed",
                "icon": QStyle.StandardPixmap.SP_MessageBoxWarning,
                "color": "#B42318",
                "border": "#912018",
            },
        }
        current = button_states.get(state, button_states["idle"])
        pad_v = 7
        pad_h = 14
        self.btn_run.setText(current["text"])
        icon = self._standard_icon(current["icon"])
        if icon is not None:
            self.btn_run.setIcon(icon)
        self.btn_run.setEnabled(state != "running")
        self.btn_run.setToolTip(tooltip or current["text"])
        self.btn_run.setStyleSheet(
            f"""
              QPushButton {{
                  background-color: {current["color"]};
                  color: white;
                  border: 1px solid {current["border"]};
                  border-radius: 8px;
                  padding: {pad_v}px {pad_h}px;
                  font-weight: 600;
              }}
            QPushButton:disabled {{
                background-color: {current["color"]};
                color: rgba(255, 255, 255, 0.92);
            }}
            """
        )

    def _sync_runtime_ir_defaults(self, force: bool = False) -> None:
        station_id = self._current_stream_station_id()
        receiver_position = self._current_receiver_position(self.ir_config.station.receiver_position)
        signature = (
            station_id or self.ir_config.station.station_id,
            receiver_position.latitude_deg,
            receiver_position.longitude_deg,
            receiver_position.height_m,
            receiver_position.x_m,
            receiver_position.y_m,
            receiver_position.z_m,
        )
        if not force and signature == self.last_runtime_config_signature:
            return

        changed = False
        if station_id and station_id != self.ir_config.station.station_id:
            self.ir_config.station.station_id = station_id
            changed = True

        if self._receiver_position_changed(receiver_position, self.ir_config.station.receiver_position):
            self.ir_config.station.receiver_position = receiver_position
            changed = True

        self.last_runtime_config_signature = signature
        if changed:
            self._reset_realtime_processing(reseed_from_buffer=True)
            self._refresh_config_view()
            self._update_summary_cards()

    def _current_stream_station_id(self) -> str | None:
        mountpoint = str((self.settings.get("OBS", {}) or {}).get("mountpoint", "") or "").strip()
        if not mountpoint:
            global_mountpoint = getattr(get_global_config().obs_settings, "mountpoint", "")
            mountpoint = str(global_mountpoint or "").strip()
        if not mountpoint:
            return None
        return mountpoint.strip("/")

    def _serialize_ir_config(self) -> str:
        return yaml.safe_dump(config_to_dict(self.ir_config), sort_keys=False, allow_unicode=False)

    def _receiver_position_changed(
        self,
        updated: ReceiverPosition,
        current: ReceiverPosition | None,
    ) -> bool:
        if current is None:
            return True
        return (
            updated.latitude_deg != current.latitude_deg
            or updated.longitude_deg != current.longitude_deg
            or updated.height_m != current.height_m
            or updated.x_m != current.x_m
            or updated.y_m != current.y_m
            or updated.z_m != current.z_m
        )

    def _check_pending_update(self) -> None:
        if self.pending_update and time.time() - self.last_gui_update_time >= self.gui_update_interval:
            self.refresh_live_widgets()
            self.last_gui_update_time = time.time()
            self.pending_update = False

    def _maybe_run_auto_analysis(self) -> None:
        """Trigger realtime analysis when enabled and enough time has passed."""
        if self._is_headless_file_analysis_mode():
            return
        if not self.analysis_loop_enabled:
            return
        if self.analysis_running:
            return
        if not self.observation_buffer:
            return
        if self.last_analysis_timestamp is None:
            self.run_ir_analysis()
            return
        elapsed = (datetime.utcnow() - self.last_analysis_timestamp).total_seconds()
        if elapsed >= self.auto_interval_spin.value():
            self.run_ir_analysis()

    def run_ir_analysis(self) -> None:
        """Run the reflectometry pipeline against the realtime observation buffer."""
        if self.analysis_running:
            return
        if self._is_headless_file_analysis_mode():
            self._start_file_batch_analysis()
            return

        analysis_label = "replay" if self._is_rinex_replay_source() else "realtime"
        self.analysis_running = True
        self._set_run_button_state("running")
        QApplication.processEvents()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.append_log(f"Running GNSS-IR {analysis_label} analysis...")
            processor, result = self._run_processing_cycle()
            if processor is None or result is None:
                self._set_run_button_state("active" if self.analysis_loop_enabled else "idle")
                return
            self.latest_result = result
            self._merge_live_product_history(result)
            self.latest_series_by_arc = processor.get_intermediate_series()
            if isinstance(processor, RealtimeProcessor):
                processor.clear_finalized_history()
            self.last_processor = processor
            self.last_analysis_timestamp = datetime.utcnow()
            self._populate_arc_table()
            self._populate_product_selector()
            self._populate_product_table()
            self._refresh_product_plot()
            self._ensure_selected_arc_visible()
            self._update_summary_cards()
            success_count = sum(item.success for item in result.arc_solutions)
            self.append_log(
                f"{analysis_label.title()} IR analysis finished: {len(result.arc_solutions)} arcs, "
                f"{success_count} successful, {len(result.products)} products."
            )
            next_state = "active" if self.analysis_loop_enabled else "success"
            self._set_run_button_state(
                next_state,
                tooltip=(
                    f"Last run: {len(result.arc_solutions)} arcs, "
                    f"{success_count} successful, {len(result.products)} products."
                ),
            )
        except Exception as exc:
            self.append_log(f"{analysis_label.title()} IR analysis failed: {exc}")
            if self.analysis_loop_enabled:
                self._set_analysis_loop_enabled(False, announce=False)
            self._set_run_button_state("failed", tooltip=str(exc))
            QMessageBox.warning(self, "Reflectometry", f"{analysis_label.title()} IR analysis failed:\n{exc}")
        finally:
            QApplication.restoreOverrideCursor()
            self.analysis_running = False

    def _start_file_batch_analysis(self) -> None:
        if self.batch_analysis_thread is not None and self.batch_analysis_thread.is_alive():
            return

        obs_settings = self.settings.get("OBS", {}) or {}
        eph_settings = self.settings.get("EPH", {}) or {}
        if not obs_settings.get("file_path"):
            QMessageBox.information(self, "Reflectometry", "Please select a RINEX observation file first.")
            return
        if self.settings.get("EPH_ENABLED") and not eph_settings.get("file_path"):
            QMessageBox.information(self, "Reflectometry", "Please select an ephemeris file first.")
            return

        self._sync_runtime_ir_defaults(force=True)
        runtime_config = deepcopy(self.ir_config)
        runtime_config.logging.console = False
        runtime_config.logging.rotating_file = False
        runtime_config.station.receiver_position = self._current_receiver_position(runtime_config.station.receiver_position)
        station_id = self._current_stream_station_id() or runtime_config.station.station_id
        runtime_config.station.station_id = station_id

        self.analysis_running = True
        self.analysis_loop_enabled = False
        running_tooltip = "Running fast file analysis with realtime logic..." if self._is_headless_file_analysis_mode() else "Running batch file analysis..."
        self._set_run_button_state("running", tooltip=running_tooltip)
        if self._is_headless_file_analysis_mode():
            self.append_log("Running GNSS-IR fast file analysis with realtime logic...")
        else:
            self.append_log("Running GNSS-IR file batch analysis (products-only mode)...")

        self.batch_analysis_thread = RinexBatchAnalysisThread(
            obs_settings=obs_settings,
            eph_settings=eph_settings,
            ir_config=runtime_config,
            active_systems=set(self.active_systems),
            target_systems=sorted(self.active_systems),
            receiver_position=runtime_config.station.receiver_position,
            receiver_position_ecef=self._ecef_position_from_global_config(),
            station_id=station_id,
            handler=self.handler,
            logger=self.analysis_logger,
            signals=self.batch_signals,
            use_realtime_logic=self._is_headless_file_analysis_mode(),
            live_window_seconds=self._live_window_seconds() if self._is_headless_file_analysis_mode() else None,
            analysis_interval_seconds=float(self.auto_interval_spin.value()) if self._is_headless_file_analysis_mode() else None,
        )
        self.batch_analysis_thread.start()

    @Slot(object)
    def _on_batch_analysis_completed(self, payload: object) -> None:
        self.batch_analysis_thread = None
        self.analysis_running = False
        result = payload["result"]
        processor = payload["processor"]
        used_realtime_logic = bool(payload.get("used_realtime_logic", False))
        self.latest_result = result
        self.latest_series_by_arc = dict(payload.get("series_by_arc", {}))
        self.last_processor = processor
        self.last_analysis_timestamp = datetime.utcnow()
        self.processed_observation_count = int(payload.get("observation_count", 0) or 0)
        self._clear_live_product_history()
        self._reset_realtime_processing(reseed_from_buffer=False)
        self._populate_arc_table()
        self._populate_product_selector()
        self._populate_product_table()
        self._refresh_product_plot()
        self._ensure_selected_arc_visible()
        self._update_summary_cards()
        success_count = sum(item.success for item in result.arc_solutions)
        if used_realtime_logic:
            self.append_log(
                f"Fast file analysis finished: {len(result.arc_solutions)} arcs, "
                f"{success_count} successful, {len(result.products)} products, "
                f"{self.processed_observation_count} observations processed."
            )
        else:
            self.append_log(
                f"File batch analysis finished: {len(result.arc_solutions)} arcs, "
                f"{success_count} successful, {len(result.products)} products, "
                f"{self.processed_observation_count} observations processed."
            )
        self._set_run_button_state(
            "success",
            tooltip=(
                f"Last run: {len(result.arc_solutions)} arcs, "
                f"{success_count} successful, {len(result.products)} products."
            ),
        )

    @Slot(str)
    def _on_batch_analysis_failed(self, message: str) -> None:
        self.batch_analysis_thread = None
        self.analysis_running = False
        prefix = "Fast file analysis" if self._is_headless_file_analysis_mode() else "File batch analysis"
        self.append_log(f"{prefix} failed: {message}")
        self._set_run_button_state("failed", tooltip=message)
        QMessageBox.warning(self, "Reflectometry", f"{prefix} failed:\n{message}")

    @Slot()
    def _on_batch_analysis_cancelled(self) -> None:
        self.batch_analysis_thread = None
        self.analysis_running = False
        if self._is_headless_file_analysis_mode():
            self.append_log("Fast file analysis cancelled.")
        else:
            self.append_log("File batch analysis cancelled.")
        self._set_run_button_state("idle")

    def _run_processing_cycle(self) -> tuple[RealtimeProcessor | None, ProcessingRunResult | None]:
        return self._run_live_realtime_analysis()

    def _ensure_live_realtime_processor(self) -> RealtimeProcessor:
        self._sync_runtime_ir_defaults()
        if self.live_realtime_processor is None:
            runtime_config = deepcopy(self.ir_config)
            runtime_config.logging.console = False
            runtime_config.logging.rotating_file = False
            runtime_config.station.receiver_position = self._current_receiver_position(runtime_config.station.receiver_position)
            self.live_realtime_processor = RealtimeProcessor(runtime_config, logger=self.analysis_logger)
        return self.live_realtime_processor

    def _run_live_realtime_analysis(self) -> tuple[RealtimeProcessor | None, ProcessingRunResult | None]:
        observations = [item for item in self.observation_buffer if item.constellation in self.active_systems]
        if not observations:
            QMessageBox.information(
                self,
                "Reflectometry",
                "No reflectometry observations are available yet. Start the OBS/EPH source first.",
            )
            return None, None

        created_processor = self.live_realtime_processor is None
        processor = self._ensure_live_realtime_processor()
        if created_processor and not self.pending_live_records:
            self.pending_live_records = list(observations)

        reference_time = observations[-1].timestamp
        self._trim_pending_live_records(reference_time)
        pending_records = list(self.pending_live_records)
        self.pending_live_records.clear()
        if pending_records:
            result = processor.ingest(
                pending_records,
                reference_time=reference_time,
                window_seconds=self._live_window_seconds(),
                include_open_preview=True,
            )
        else:
            result = processor.snapshot(
                reference_time=reference_time,
                window_seconds=self._live_window_seconds(),
                include_open_preview=True,
            )
        return processor, result

    def _finalize_rinex_replay_analysis(self) -> None:
        if not self._is_rinex_replay_source():
            return
        if not self.analysis_loop_enabled:
            return
        if self.analysis_running:
            QTimer.singleShot(200, self._finalize_rinex_replay_analysis)
            return
        if self.live_realtime_processor is None and not self.pending_live_records:
            self.analysis_loop_enabled = False
            self._set_run_button_state("success", tooltip="RINEX replay completed.")
            return

        self.analysis_running = True
        self._set_run_button_state("running", tooltip="Finalizing replay analysis...")
        try:
            processor = self._ensure_live_realtime_processor()
            if self.pending_live_records:
                reference_time = self.pending_live_records[-1].timestamp
                self._trim_pending_live_records(reference_time)
                pending_records = list(self.pending_live_records)
                self.pending_live_records.clear()
                if pending_records:
                    processor.ingest(
                        pending_records,
                        reference_time=reference_time,
                        window_seconds=self._live_window_seconds(),
                        include_open_preview=True,
                    )

            result = processor.flush()
            self.latest_result = result
            self._merge_live_product_history(result)
            self.latest_series_by_arc = processor.get_intermediate_series()
            self.last_processor = processor
            self.last_analysis_timestamp = datetime.utcnow()
            self._populate_arc_table()
            self._populate_product_selector()
            self._populate_product_table()
            self._refresh_product_plot()
            self._ensure_selected_arc_visible()
            self._update_summary_cards()
            success_count = sum(item.success for item in result.arc_solutions)
            self.append_log(
                f"RINEX replay finalized: {len(result.arc_solutions)} arcs, "
                f"{success_count} successful, {len(result.products)} products."
            )
            self.analysis_loop_enabled = False
            self._set_run_button_state(
                "success",
                tooltip=(
                    f"Replay finalized: {len(result.arc_solutions)} arcs, "
                    f"{success_count} successful, {len(result.products)} products."
                ),
            )
        except Exception as exc:
            self.analysis_loop_enabled = False
            self.append_log(f"RINEX replay finalization failed: {exc}")
            self._set_run_button_state("failed", tooltip=str(exc))
        finally:
            self.analysis_running = False

    def _ensure_selected_arc_visible(self) -> None:
        if self.arc_table.rowCount() == 0:
            self.selected_arc_id = None
            self._clear_arc_detail_summary()
            self._clear_series_plot()
            self._clear_spectrum_plot()
            self._populate_arc_selector()
            return

        if self.selected_arc_id:
            if (
                self._current_arc_table_selection() == self.selected_arc_id
                and self.arc_selector_combo.currentData() == self.selected_arc_id
            ):
                return
            if self._find_solution_by_arc_id(self.selected_arc_id) is not None:
                self._set_selected_arc(self.selected_arc_id)
                return
            if self._is_tracking_arc_id(self.selected_arc_id):
                if self.selected_arc_id in self.tracking_context_by_arc:
                    self._select_tracking_arc(self.selected_arc_id)
                    return

        solution_entries = self._displayed_solution_entries()
        if not solution_entries:
            tracking_arc_id = next(iter(self.tracking_context_by_arc), None)
            if tracking_arc_id is not None:
                self._select_tracking_arc(tracking_arc_id)
                return
            self.selected_arc_id = None
            self._clear_arc_detail_summary()
            self._clear_series_plot()
            self._clear_spectrum_plot()
            self._populate_arc_selector()
            return

        preferred_arc_id: str | None = None
        for solution, browse_key in solution_entries:
            if solution.success:
                preferred_arc_id = browse_key
                break
        if preferred_arc_id is None and solution_entries:
            preferred_arc_id = solution_entries[0][1]
        if preferred_arc_id is not None:
            self._set_selected_arc(preferred_arc_id)

    def _populate_arc_table(self) -> None:
        selected_arc_id = self.selected_arc_id
        scroll_value = self.arc_table.verticalScrollBar().value()
        self.arc_table.blockSignals(True)
        self.arc_table.setRowCount(0)
        self.solution_arc_key_map = {}
        self.tracking_context_by_arc = self._collect_tracking_contexts()
        solution_entries = self._displayed_solution_entries()
        displayed_live_arc_ids = {browse_key for _solution, browse_key in solution_entries}
        row_index = 0
        for solution, browse_key in solution_entries:
            elevation_text, mean_az_text = self._arc_table_geometry_text(browse_key)
            row_index = self._append_arc_status_row(
                row_index,
                build_solution_status_row(
                    solution,
                    browse_key=browse_key,
                    display_arc_id=self._display_arc_id(browse_key),
                    time_summary=format_arc_time_summary(solution.timestamp_start, solution.timestamp_end),
                    elevation_text=elevation_text,
                    mean_az_text=mean_az_text,
                ),
            )

        for context in self.tracking_context_by_arc.values():
            if context.arc_id in displayed_live_arc_ids:
                continue
            row_index = self._append_arc_status_row(
                row_index,
                build_tracking_status_row(context, display_arc_id=self._display_arc_id(context.arc_id)),
            )

        self.arc_table.blockSignals(False)
        self.arc_table.resizeRowsToContents()
        self._populate_arc_selector()
        if selected_arc_id:
            if self._find_solution_by_arc_id(selected_arc_id) is not None:
                self._set_selected_arc(selected_arc_id)
            elif self._is_tracking_arc_id(selected_arc_id) and selected_arc_id in self.tracking_context_by_arc:
                self._select_tracking_arc(selected_arc_id)
        self.arc_table.verticalScrollBar().setValue(scroll_value)

    def _append_arc_status_row(self, row_index: int, row: ArcStatusRow) -> int:
        """Insert one Arc Status row into the table."""
        self.arc_table.insertRow(row_index)
        for column, value in enumerate(row.values):
            item = QTableWidgetItem(value)
            if column == 0:
                item.setData(Qt.ItemDataRole.UserRole, row.arc_id)
                item.setToolTip(row.tooltip)
            if column == 9 and row.status_color:
                item.setForeground(QColor(row.status_color))
            self.arc_table.setItem(row_index, column, item)
        return row_index + 1

    def _displayed_solution_entries(self) -> list[tuple[ArcSolution, str]]:
        """Return solved arcs that should appear in the current Arc Status view."""
        if self.latest_result is None:
            return []

        entries: list[tuple[ArcSolution, str]] = []
        for solution in self.latest_result.arc_solutions:
            browse_key = match_live_arc_id_for_solution(solution, self.tracking_context_by_arc)
            if browse_key is None:
                browse_key = self._browse_key_for_solution(solution)
            self.solution_arc_key_map[browse_key] = solution.arc_id
            entries.append((solution, browse_key))
        return entries

    def _collect_tracking_contexts(self) -> dict[str, TrackingArcContext]:
        contexts: dict[str, TrackingArcContext] = {}
        if self.live_realtime_processor is None:
            self.current_live_arc_ids = set()
            return contexts
        required_duration = self._tracking_preview_threshold_seconds()
        live_buffers = collect_latest_tracking_buffers(
            [record for record in self.observation_buffer if self._record_matches_buffer_filters(record)],
            max_time_gap_seconds=float(self.ir_config.processing.max_time_gap_seconds),
        )
        for buffer in live_buffers:
            if not buffer:
                continue
            ready_for_preview = self._buffer_ready_for_preview(buffer)
            context = build_tracking_context(
                buffer,
                required_duration=required_duration,
                ready_for_preview=ready_for_preview,
            )
            contexts[context.arc_id] = context
        self.current_live_arc_ids = set(contexts)
        return dict(sorted(contexts.items(), key=lambda item: item[1].time_summary))

    def _buffer_ready_for_preview(self, buffer: list[ObservationRecord]) -> bool:
        if len(buffer) < minimum_required_arc_samples(self.ir_config.processing):
            return False
        if len(buffer) < 2:
            return False
        duration_seconds = (buffer[-1].timestamp - buffer[0].timestamp).total_seconds()
        return duration_seconds >= self._tracking_preview_threshold_seconds()

    def _tracking_preview_threshold_seconds(self) -> float:
        """Return the realtime duration threshold before an open arc enters solving."""
        return max(float(self.ir_config.qc.min_arc_duration), self._live_window_seconds())

    def _populate_product_table(self) -> None:
        header = self.product_table.horizontalHeader()
        sort_column = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        if sort_column < 0:
            sort_column = 0
            sort_order = Qt.SortOrder.DescendingOrder

        self.product_table.setSortingEnabled(False)
        self.product_table.setRowCount(0)
        products = self._selected_products_for_display()
        if not products:
            self.product_table.setSortingEnabled(True)
            return

        ordered_products = sorted(
            products,
            key=lambda item: (
                item.timestamp,
                self._product_constellation(item),
                self._product_signal(item),
                item.value,
            ),
            reverse=True,
        )
        for row_index, product in enumerate(ordered_products):
            self.product_table.insertRow(row_index)
            constellation = self._product_constellation(product)
            system_label = self._system_display_name(constellation)
            direction_key = self._product_direction(product)
            direction_label = self._direction_display_name(direction_key)
            peak_to_noise_ratio = self._product_peak_to_noise_ratio(product)
            pnr_band = self._pnr_band_key(peak_to_noise_ratio)
            row_items = [
                self._make_product_table_item(
                    product.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    sort_value=product.timestamp,
                    alignment=Qt.AlignmentFlag.AlignCenter,
                ),
                self._make_product_table_item(
                    system_label,
                    sort_value=system_label,
                    foreground=get_sys_color(constellation) if constellation != "--" else None,
                    bold=True,
                ),
                self._make_product_table_item(
                    direction_label,
                    sort_value=self._direction_sort_order(direction_key),
                    foreground=self._product_group_color("by_direction", direction_key, 0),
                ),
                self._make_product_table_item(self._product_satellite(product)),
                self._make_product_table_item(self._product_signal(product)),
                self._make_product_table_item(
                    f"{product.value:.3f}",
                    sort_value=float(product.value),
                    alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    bold=True,
                ),
                self._make_product_table_item(
                    product.unit,
                    alignment=Qt.AlignmentFlag.AlignCenter,
                ),
                self._make_product_table_item(
                    f"{peak_to_noise_ratio:.2f}" if peak_to_noise_ratio is not None else "--",
                    sort_value=float(peak_to_noise_ratio) if peak_to_noise_ratio is not None else -1.0,
                    alignment=Qt.AlignmentFlag.AlignCenter,
                    foreground=self._pnr_band_text_color(pnr_band),
                    background=self._pnr_band_background_color(pnr_band),
                    bold=peak_to_noise_ratio is not None,
                ),
            ]
            for column, item in enumerate(row_items):
                self.product_table.setItem(row_index, column, item)
        self.product_table.resizeRowsToContents()
        self.product_table.setSortingEnabled(True)
        self.product_table.sortItems(sort_column, sort_order)

    def _populate_product_selector(self) -> None:
        if not hasattr(self, "product_selector"):
            return
        products = self._products_for_display()
        product_types: list[str] = []
        seen: set[str] = set()
        for product in products:
            product_type = product.product_type.value
            if product_type not in seen:
                seen.add(product_type)
                product_types.append(product_type)

        self.product_selector.blockSignals(True)
        try:
            current_type = self.selected_product_type
            self.product_selector.clear()
            if not product_types:
                self.product_selector.addItem("No products available", None)
                self.product_selector.setEnabled(False)
                self.selected_product_type = None
                return
            for product_type in product_types:
                self.product_selector.addItem(self._format_product_type_label(product_type), product_type)
            self.product_selector.setEnabled(True)
            selected_index = self.product_selector.findData(current_type)
            if selected_index < 0:
                selected_index = 0
            self.product_selector.setCurrentIndex(selected_index)
            self.selected_product_type = self.product_selector.currentData()
        finally:
            self.product_selector.blockSignals(False)

    def _on_product_selection_changed(self, index: int) -> None:
        if index < 0 or not hasattr(self, "product_selector"):
            return
        self.selected_product_type = self.product_selector.itemData(index)
        self._populate_product_table()
        self._refresh_product_plot()

    def _on_product_view_mode_changed(self, index: int) -> None:
        if index < 0 or not hasattr(self, "product_view_mode_combo"):
            return
        self.selected_product_view_mode = str(self.product_view_mode_combo.itemData(index) or "by_system")
        self._refresh_product_plot()

    def _on_product_system_filter_changed(self, _: int) -> None:
        self._populate_product_table()
        self._refresh_product_plot()

    def _on_arc_selection_changed(self) -> None:
        items = self.arc_table.selectedItems()
        if not items:
            return
        row = items[0].row()
        arc_id_item = self.arc_table.item(row, 0)
        if arc_id_item is None:
            return
        arc_id = arc_id_item.data(Qt.ItemDataRole.UserRole) or arc_id_item.text()
        arc_id = str(arc_id)
        if self._find_solution_by_arc_id(arc_id) is not None:
            self._set_selected_arc(arc_id, sync_table=False, sync_combo=True)
            return
        if self._is_tracking_arc_id(arc_id):
            self._select_tracking_arc(arc_id, sync_table=False, sync_combo=True)

    def _populate_arc_selector(self) -> None:
        self.arc_selector_combo.blockSignals(True)
        try:
            current_key = self.selected_arc_id
            self.arc_selector_combo.clear()
            has_solutions = self.latest_result is not None and bool(self.latest_result.arc_solutions)
            has_tracking = bool(self.tracking_context_by_arc)
            if not has_solutions and not has_tracking:
                self.arc_selector_combo.addItem("No arc status available", None)
                self.arc_selector_combo.setEnabled(False)
                self.btn_prev_arc.setEnabled(False)
                self.btn_next_arc.setEnabled(False)
                return

            self.arc_selector_combo.setEnabled(True)
            solution_entries = self._displayed_solution_entries()
            displayed_live_arc_ids = {browse_key for _solution, browse_key in solution_entries}
            options: list[ArcSelectorOption] = []
            for solution, browse_key in solution_entries:
                elevation_text, mean_az_text = self._arc_table_geometry_text(browse_key)
                options.append(
                    build_solution_selector_option(
                        solution,
                        browse_key=browse_key,
                        elevation_text=elevation_text,
                        mean_az_text=mean_az_text,
                        time_summary=format_arc_time_summary(solution.timestamp_start, solution.timestamp_end),
                    )
                )

            for tracking_arc_id, context in self.tracking_context_by_arc.items():
                if tracking_arc_id in displayed_live_arc_ids:
                    continue
                options.append(build_tracking_selector_option(context))

            for option in options:
                self.arc_selector_combo.addItem(option.label, option.arc_id)

            selected_arc_id = current_key
            if selected_arc_id:
                index = self.arc_selector_combo.findData(selected_arc_id)
                if index >= 0:
                    self.arc_selector_combo.setCurrentIndex(index)
                else:
                    self.arc_selector_combo.setCurrentIndex(0)
            else:
                self.arc_selector_combo.setCurrentIndex(0)
            has_multiple = self.arc_selector_combo.count() > 1
            self.btn_prev_arc.setEnabled(has_multiple)
            self.btn_next_arc.setEnabled(has_multiple)
        finally:
            self.arc_selector_combo.blockSignals(False)

    def _on_arc_selector_changed(self, index: int) -> None:
        if index < 0:
            return
        arc_id = self.arc_selector_combo.itemData(index)
        if not arc_id:
            self.selected_arc_id = None
            self._clear_arc_detail_summary()
            self._clear_series_plot()
            self._clear_spectrum_plot()
            return
        if self._find_solution_by_arc_id(str(arc_id)) is not None:
            self._set_selected_arc(str(arc_id), sync_table=True, sync_combo=False)
            return
        if self._is_tracking_arc_id(str(arc_id)):
            self._select_tracking_arc(str(arc_id), sync_table=True, sync_combo=False)

    def _step_arc_selection(self, step: int) -> None:
        if not self.arc_selector_combo.isEnabled() or self.arc_selector_combo.count() <= 1:
            return
        next_index = (self.arc_selector_combo.currentIndex() + step) % self.arc_selector_combo.count()
        self.arc_selector_combo.setCurrentIndex(next_index)

    def _set_selected_arc(
        self,
        arc_id: str,
        *,
        sync_table: bool = True,
        sync_combo: bool = True,
    ) -> None:
        solution = self._find_solution_by_arc_id(arc_id)
        if solution is None:
            return
        self.selected_arc_id = arc_id
        if sync_table:
            self._select_arc_table_row(arc_id)
        if sync_combo:
            self._select_arc_combo_item(arc_id)
        self._refresh_arc_detail_summary(solution)
        self._refresh_series_plot(solution)
        self._refresh_spectrum_plot(solution)

    def _select_tracking_arc(
        self,
        arc_id: str,
        *,
        sync_table: bool = True,
        sync_combo: bool = True,
    ) -> None:
        context = self.tracking_context_by_arc.get(arc_id)
        if context is None:
            return
        self.selected_arc_id = arc_id
        if sync_table:
            self._select_arc_table_row(arc_id)
        if sync_combo:
            self._select_arc_combo_item(arc_id)
        self._refresh_tracking_arc_detail(context)
        self._refresh_tracking_series_plot(context)
        self._show_tracking_spectrum_placeholder(context)

    def _find_solution_by_arc_id(self, arc_id: str) -> ArcSolution | None:
        if self.latest_result is None:
            return None
        actual_arc_id = self.solution_arc_key_map.get(arc_id, arc_id)
        return next((item for item in self.latest_result.arc_solutions if item.arc_id == actual_arc_id), None)

    def _is_tracking_arc_id(self, arc_id: str) -> bool:
        return arc_id in self.tracking_context_by_arc

    def _select_arc_table_row(self, arc_id: str) -> None:
        self.arc_table.blockSignals(True)
        try:
            self.arc_table.clearSelection()
            for row in range(self.arc_table.rowCount()):
                item = self.arc_table.item(row, 0)
                if item is not None and str(item.data(Qt.ItemDataRole.UserRole) or item.text()) == arc_id:
                    self.arc_table.selectRow(row)
                    break
        finally:
            self.arc_table.blockSignals(False)

    def _current_arc_table_selection(self) -> str | None:
        selected_items = self.arc_table.selectedItems()
        if not selected_items:
            return None
        item = self.arc_table.item(selected_items[0].row(), 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole) or item.text()
        return str(value) if value else None

    def _select_arc_combo_item(self, arc_id: str) -> None:
        index = self.arc_selector_combo.findData(arc_id)
        if index < 0:
            return
        self.arc_selector_combo.blockSignals(True)
        try:
            self.arc_selector_combo.setCurrentIndex(index)
        finally:
            self.arc_selector_combo.blockSignals(False)

    def _refresh_arc_detail_summary(self, solution: ArcSolution) -> None:
        start_el_text, end_el_text, mean_az_text = self._arc_geometry_text(solution.arc_id)
        self.arc_detail_labels["arc_id"].setText(solution.arc_id)
        self.arc_detail_labels["satellite"].setText(solution.satellite)
        self.arc_detail_labels["signal"].setText(solution.signal)
        self.arc_detail_labels["direction"].setText(solution.arc_direction.value)
        self.arc_detail_labels["time_span"].setText(
            f"{solution.timestamp_start.strftime('%H:%M:%S')} - {solution.timestamp_end.strftime('%H:%M:%S')}"
        )
        self.arc_detail_labels["start_el"].setText(f"{start_el_text} deg" if start_el_text != "--" else "--")
        self.arc_detail_labels["end_el"].setText(f"{end_el_text} deg" if end_el_text != "--" else "--")
        self.arc_detail_labels["mean_az"].setText(f"{mean_az_text} deg" if mean_az_text != "--" else "--")
        self.arc_detail_labels["height"].setText(
            f"{solution.reflector_height_m:.3f} m" if solution.reflector_height_m is not None else "--"
        )
        self.arc_detail_labels["peak_pnr"].setText(
            f"{solution.peak_to_noise_ratio:.2f}" if solution.peak_to_noise_ratio is not None else "--"
        )

    def _clear_arc_detail_summary(self) -> None:
        if not hasattr(self, "arc_detail_labels"):
            return
        for label in self.arc_detail_labels.values():
            label.setText("--")

    def _arc_geometry_text(self, arc_id: str) -> tuple[str, str, str]:
        series = self.latest_series_by_arc.get(arc_id)
        if series is None or not series.elevation_deg:
            return "--", "--", "--"
        start_elevation = float(series.elevation_deg[0])
        end_elevation = float(series.elevation_deg[-1])
        mean_azimuth = _circular_mean_deg(series.azimuth_deg)
        return (
            f"{start_elevation:.2f}",
            f"{end_elevation:.2f}",
            f"{mean_azimuth:.2f}" if mean_azimuth is not None else "--",
        )

    def _arc_table_geometry_text(self, arc_id: str) -> tuple[str, str]:
        series = self._series_for_arc(arc_id)
        if series is None or not series.elevation_deg:
            return "--", "--"
        start_elevation = float(series.elevation_deg[0])
        end_elevation = float(series.elevation_deg[-1])
        mean_elevation = float(sum(series.elevation_deg) / len(series.elevation_deg))
        mean_azimuth = _circular_mean_deg(series.azimuth_deg)
        return (
            f"{mean_elevation:.2f} ({start_elevation:.2f}->{end_elevation:.2f})",
            f"{mean_azimuth:.2f}" if mean_azimuth is not None else "--",
        )

    def _arc_start_end_elevation(self, arc_id: str) -> tuple[str, str]:
        series = self._series_for_arc(arc_id)
        if series is None or not series.elevation_deg:
            return "--", "--"
        return f"{float(series.elevation_deg[0]):.2f}", f"{float(series.elevation_deg[-1]):.2f}"

    def _series_for_arc(self, arc_id: str) -> SnrSeries | None:
        actual_arc_id = self.solution_arc_key_map.get(arc_id, arc_id)
        tracking_context = self.tracking_context_by_arc.get(arc_id)
        return self.latest_series_by_arc.get(actual_arc_id) or (tracking_context.series if tracking_context else None)

    @staticmethod
    def _display_arc_id(arc_id: str) -> str:
        parts = arc_id.split("-")
        if len(parts) >= 4:
            return "-".join(parts[:4])
        return arc_id

    @staticmethod
    def _browse_key_for_solution(solution: ArcSolution) -> str:
        start_token = solution.timestamp_start.strftime("%Y%m%dT%H%M%S")
        return (
            f"{solution.station_id}-{solution.satellite}-{solution.signal}-"
            f"{solution.arc_direction.value}-{start_token}"
        )

    def _refresh_series_plot(self, solution: ArcSolution) -> None:
        self.series_ax_raw.clear()
        self.series_ax_residual.clear()
        series = self._series_for_arc(solution.arc_id)

        if series is None:
            self._clear_series_plot()
            return

        x_values = np.asarray(series.sin_elevation, dtype=float)
        sort_index = np.argsort(x_values)
        x_values = x_values[sort_index]
        raw = np.asarray(series.snr_db_hz, dtype=float)[sort_index]
        residual = np.asarray(series.residual, dtype=float)[sort_index]

        self.series_ax_raw.plot(x_values, raw, ".-", color="#2563EB", linewidth=1.2, markersize=3)
        self.series_ax_raw.set_title("Raw SNR vs sin(Elevation)")
        self.series_ax_raw.set_xlabel("sin(Elevation)")
        self.series_ax_raw.set_ylabel("SNR (dB-Hz)")
        self.series_ax_raw.grid(True, alpha=0.3)

        self.series_ax_residual.plot(x_values, residual, ".-", color="#E67E22", linewidth=1.2, markersize=3)
        self.series_ax_residual.axhline(0.0, color="#94A3B8", linewidth=1.0, linestyle="--")
        self.series_ax_residual.set_title("Detrended Residual")
        self.series_ax_residual.set_xlabel("sin(Elevation)")
        self.series_ax_residual.set_ylabel("Residual")
        self.series_ax_residual.grid(True, alpha=0.3)

        self.series_header.setText(
            f"Selected arc: {solution.satellite} {solution.signal} | "
            f"{solution.arc_direction.value} | "
            f"height={solution.reflector_height_m:.3f} m"
            if solution.reflector_height_m is not None
            else f"Selected arc: {solution.satellite} {solution.signal} | {solution.arc_direction.value}"
        )
        self.series_panel.canvas.draw_idle()

    def _refresh_tracking_arc_detail(self, context: TrackingArcContext) -> None:
        self.arc_detail_labels["arc_id"].setText(context.arc_id)
        self.arc_detail_labels["satellite"].setText(context.satellite)
        self.arc_detail_labels["signal"].setText(context.signal)
        self.arc_detail_labels["direction"].setText(context.direction)
        self.arc_detail_labels["time_span"].setText(context.time_summary)
        start_el_text, end_el_text = self._arc_start_end_elevation(context.arc_id)
        self.arc_detail_labels["start_el"].setText(f"{start_el_text} deg" if start_el_text != "--" else "--")
        self.arc_detail_labels["end_el"].setText(f"{end_el_text} deg" if end_el_text != "--" else "--")
        self.arc_detail_labels["mean_az"].setText(f"{context.mean_az} deg" if context.mean_az != "--" else "--")
        self.arc_detail_labels["height"].setText("--")
        self.arc_detail_labels["peak_pnr"].setText("--")

    def _refresh_tracking_series_plot(self, context: TrackingArcContext) -> None:
        series = context.series
        self.series_ax_raw.clear()
        self.series_ax_residual.clear()
        x_values = np.asarray(series.sin_elevation, dtype=float)
        sort_index = np.argsort(x_values)
        x_values = x_values[sort_index]
        raw = np.asarray(series.snr_db_hz, dtype=float)[sort_index]

        self.series_ax_raw.plot(x_values, raw, ".-", color="#2563EB", linewidth=1.2, markersize=3)
        self.series_ax_raw.set_title("Raw SNR vs sin(Elevation)")
        self.series_ax_raw.set_xlabel("sin(Elevation)")
        self.series_ax_raw.set_ylabel("SNR (dB-Hz)")
        self.series_ax_raw.grid(True, alpha=0.3)

        self.series_ax_residual.set_title("Detrended Residual")
        self.series_ax_residual.set_xlabel("sin(Elevation)")
        self.series_ax_residual.set_ylabel("Residual")
        self.series_ax_residual.text(
            0.5,
            0.5,
            "Tracking stage\nDetrend preview disabled",
            ha="center",
            va="center",
            fontsize=12,
            color="#64748B",
            transform=self.series_ax_residual.transAxes,
        )
        self.series_ax_residual.grid(False)
        status_text = "solving" if context.status == "solving" else "waiting for arc window"
        self.series_header.setText(
            f"Tracking arc: {context.satellite} {context.signal} | {context.direction} | {status_text}"
        )
        self.series_panel.canvas.draw_idle()

    def _show_tracking_spectrum_placeholder(self, context: TrackingArcContext) -> None:
        self.spectrum_ax.clear()
        ready_text = "Spectrum will appear after realtime solving completes."
        if context.status != "solving":
            ready_text = "Spectrum will appear after the arc window is filled."
        self.spectrum_header.setText(
            f"LSP pending for {context.satellite} {context.signal}. {ready_text}"
        )
        self.primary_peak_label.setText("Primary peak is only available after LSP solving finishes.")
        self.spectrum_ax.set_title("Lomb-Scargle Spectrum Pending")
        self.spectrum_ax.set_xlabel("Spectral Frequency")
        self.spectrum_ax.set_ylabel("Power")
        self.spectrum_ax.text(
            0.5,
            0.5,
            "Tracking arc\nSolving in progress" if context.status == "solving" else "Tracking arc\nWaiting for arc window",
            ha="center",
            va="center",
            fontsize=12,
            color="#64748B",
            transform=self.spectrum_ax.transAxes,
        )
        self.spectrum_ax.grid(False)
        self.spectrum_panel.canvas.draw_idle()

    def _refresh_spectrum_plot(self, solution: ArcSolution) -> None:
        self.spectrum_ax.clear()

        if not solution.spectrum_frequency or not solution.spectrum_power:
            self._clear_spectrum_plot()
            return

        frequencies = np.asarray(solution.spectrum_frequency, dtype=float)
        power = np.asarray(solution.spectrum_power, dtype=float)
        primary = solution.candidates[0] if solution.candidates else None
        self.spectrum_ax.plot(frequencies, power, color="#2563EB", linewidth=1.2)
        self.spectrum_ax.set_title("Lomb-Scargle Spectrum")
        self.spectrum_ax.set_xlabel("Spectral Frequency")
        self.spectrum_ax.set_ylabel("Power")
        self.spectrum_ax.grid(True, alpha=0.3)
        self.spectrum_ax.tick_params(axis="x", labelsize=8, pad=6)
        self.spectrum_ax.margins(x=0.02)

        if primary is not None:
            self.spectrum_ax.scatter(
                primary.spectral_frequency,
                primary.power,
                color="#B42318",
                s=52,
                zorder=3,
            )
            self.spectrum_ax.annotate(
                f"{primary.reflector_height_m:.2f} m",
                (primary.spectral_frequency, primary.power),
                textcoords="offset points",
                xytext=(0, 6),
                ha="center",
                fontsize=8,
            )
            self.primary_peak_label.setText(
                "Primary Peak | "
                f"Height {primary.reflector_height_m:.3f} m | "
                f"Frequency {primary.spectral_frequency:.4f} | "
                f"P/N {primary.peak_to_noise_ratio:.2f}"
            )
        else:
            self.primary_peak_label.setText("Primary peak not available for this arc.")

        self.spectrum_header.setText(
            f"Spectrum summary | primary frequency={solution.peak_frequency:.4f} | "
            f"reflector height={solution.reflector_height_m:.3f} m"
            if solution.peak_frequency is not None and solution.reflector_height_m is not None
            else "Spectrum summary"
        )
        self.spectrum_panel.canvas.draw_idle()

    def _refresh_product_plot(self) -> None:
        self.product_ax.clear()
        products = self._selected_products_for_display()
        if not products:
            self._clear_product_plot()
            return

        view_mode = self._current_product_view_mode()
        if view_mode == "pnr_weighted_epoch":
            ordered_products = sorted(products, key=lambda item: item.timestamp)
            self.product_ax.scatter(
                [item.timestamp for item in ordered_products],
                [item.value for item in ordered_products],
                label="Raw inversions",
                s=26,
                color="#CBD5E1",
                alpha=0.38,
                edgecolors="none",
                zorder=1,
            )

            weighted_epochs = self._weighted_product_epochs(products)
            if weighted_epochs:
                timestamps = [item["timestamp"] for item in weighted_epochs]
                values = [item["value"] for item in weighted_epochs]
                self.product_ax.plot(
                    timestamps,
                    values,
                    color="#C2410C",
                    linewidth=2.2,
                    alpha=0.96,
                    label="PNR-weighted epoch value",
                    zorder=3,
                )
                self.product_ax.scatter(
                    timestamps,
                    values,
                    s=54,
                    color="#EA580C",
                    alpha=0.98,
                    edgecolors="#FFF7ED",
                    linewidths=0.8,
                    label="_nolegend_",
                    zorder=4,
                )
        else:
            grouped = self._group_products_for_view(products, view_mode)
            for index, (group_key, group_products) in enumerate(grouped.items()):
                points = sorted(group_products, key=lambda item: item.timestamp)
                color = self._product_group_color(view_mode, group_key, index)
                timestamps = [item.timestamp for item in points]
                values = [item.value for item in points]
                self.product_ax.plot(
                    timestamps,
                    values,
                    color=color,
                    linewidth=1.6,
                    alpha=0.45,
                    zorder=2,
                )
                self.product_ax.scatter(
                    timestamps,
                    values,
                    label=self._product_group_label(view_mode, group_key),
                    s=42,
                    color=color,
                    alpha=0.92,
                    edgecolors="#FFFFFF",
                    linewidths=0.6,
                    zorder=3,
                )

        self.product_ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        self.product_ax.tick_params(axis="x", labelrotation=20)
        selected_type = self.selected_product_type or products[0].product_type.value
        self.product_ax.set_title(
            f"{self._format_product_type_label(selected_type)} Trend | {self._product_view_label(view_mode)}"
        )
        self.product_ax.set_xlabel("Time")
        unit = str(products[0].unit or "").strip()
        self.product_ax.set_ylabel(f"Value ({unit})" if unit else "Value")
        self.product_ax.grid(True, alpha=0.3)
        handles, labels = self.product_ax.get_legend_handles_labels()
        if handles:
            self.product_ax.legend(loc="best")
        self.product_panel.canvas.draw_idle()

    def _clear_series_plot(self) -> None:
        self.series_ax_raw.clear()
        self.series_ax_residual.clear()
        self.series_header.setText("Choose an arc segment to inspect raw SNR and detrended residuals.")
        self.series_ax_raw.set_title("Raw SNR vs sin(Elevation)")
        self.series_ax_raw.set_xlabel("sin(Elevation)")
        self.series_ax_raw.set_ylabel("SNR (dB-Hz)")
        self.series_ax_raw.grid(True, alpha=0.3)
        self.series_ax_residual.set_title("Detrended Residual")
        self.series_ax_residual.set_xlabel("sin(Elevation)")
        self.series_ax_residual.set_ylabel("Residual")
        self.series_ax_residual.grid(True, alpha=0.3)
        self.series_panel.canvas.draw_idle()

    def _clear_spectrum_plot(self) -> None:
        self.spectrum_ax.clear()
        self.spectrum_header.setText("Spectrum and the primary peak for the selected arc will appear here.")
        self.primary_peak_label.setText("Primary peak metrics will appear here.")
        self.spectrum_ax.set_title("Lomb-Scargle Spectrum")
        self.spectrum_ax.set_xlabel("Spectral Frequency")
        self.spectrum_ax.set_ylabel("Power")
        self.spectrum_ax.grid(True, alpha=0.3)
        self.spectrum_ax.tick_params(axis="x", labelsize=8, pad=6)
        self.spectrum_panel.canvas.draw_idle()

    def _clear_product_plot(self) -> None:
        self.product_ax.clear()
        self.product_ax.set_title("Reflectometry Products")
        self.product_ax.set_xlabel("Time")
        self.product_ax.set_ylabel("Value")
        self.product_ax.grid(True, alpha=0.3)
        self.product_panel.canvas.draw_idle()

    def _merge_live_product_history(self, result: ProcessingRunResult) -> None:
        for product in result.products:
            arc_id = str(product.metadata.get("arc_id", ""))
            key = (product.product_type.value, product.timestamp.isoformat(), arc_id)
            self.live_product_history[key] = product

    def _clear_live_product_history(self) -> None:
        self.live_product_history = {}

    def _products_for_display(self) -> list[ProductResult]:
        if self.live_product_history:
            return list(self.live_product_history.values())
        if self.latest_result is None:
            return []
        return list(self.latest_result.products)

    def _selected_products_for_display(self) -> list[ProductResult]:
        products = self._products_for_display()
        if not products:
            return []
        selected_type = self.selected_product_type
        if not selected_type:
            selected_type = products[0].product_type.value
            self.selected_product_type = selected_type
        active_systems = self._selected_product_systems()
        return [
            item
            for item in products
            if item.product_type.value == selected_type
            and (
                self._product_constellation(item) in active_systems
                or self._product_constellation(item) not in self.ALL_SYSTEMS
            )
        ]

    def _current_product_view_mode(self) -> str:
        if hasattr(self, "product_view_mode_combo"):
            current_mode = self.product_view_mode_combo.currentData()
            if current_mode:
                self.selected_product_view_mode = str(current_mode)
        return self.selected_product_view_mode or "by_system"

    def _product_solution(self, product: ProductResult) -> ArcSolution | None:
        arc_id = str(product.metadata.get("arc_id", "")).strip()
        if not arc_id:
            return None
        return self._find_solution_by_arc_id(arc_id)

    def _product_constellation(self, product: ProductResult) -> str:
        value = product.metadata.get("constellation")
        if value not in (None, ""):
            return str(value)
        solution = self._product_solution(product)
        return solution.constellation if solution is not None else "--"

    def _product_satellite(self, product: ProductResult) -> str:
        value = product.metadata.get("satellite")
        if value not in (None, ""):
            return str(value)
        solution = self._product_solution(product)
        return solution.satellite if solution is not None else "--"

    def _product_signal(self, product: ProductResult) -> str:
        value = product.metadata.get("signal")
        if value not in (None, ""):
            return str(value)
        solution = self._product_solution(product)
        return solution.signal if solution is not None else "--"

    def _product_peak_to_noise_ratio(self, product: ProductResult) -> float | None:
        value = product.metadata.get("peak_to_noise_ratio")
        if value not in (None, ""):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
        solution = self._product_solution(product)
        if solution is None or solution.peak_to_noise_ratio is None:
            return None
        return float(solution.peak_to_noise_ratio)

    def _product_direction(self, product: ProductResult) -> str:
        value = product.metadata.get("arc_direction")
        if value not in (None, ""):
            return str(value)
        solution = self._product_solution(product)
        if solution is None or solution.arc_direction is None:
            return "unknown"
        return str(solution.arc_direction.value)

    def _direction_display_name(self, direction: str) -> str:
        return {
            "rising": "Rising",
            "setting": "Setting",
            "combined": "Combined",
            "unknown": "Unknown",
        }.get(direction, direction.title())

    @staticmethod
    def _direction_sort_order(direction: str) -> int:
        return {
            "rising": 0,
            "setting": 1,
            "combined": 2,
            "unknown": 3,
        }.get(direction, 99)

    def _pnr_band_key(self, peak_to_noise_ratio: float | None) -> str:
        if peak_to_noise_ratio is None:
            return "pnr_unknown"
        if peak_to_noise_ratio < 3.0:
            return "pnr_lt_3"
        if peak_to_noise_ratio < 6.0:
            return "pnr_3_6"
        if peak_to_noise_ratio < 10.0:
            return "pnr_6_10"
        return "pnr_gte_10"

    @staticmethod
    def _pnr_band_label(band: str) -> str:
        return {
            "pnr_lt_3": "P/N < 3",
            "pnr_3_6": "P/N 3-6",
            "pnr_6_10": "P/N 6-10",
            "pnr_gte_10": "P/N >= 10",
            "pnr_unknown": "P/N Unknown",
        }.get(band, band)

    @staticmethod
    def _pnr_band_sort_order(band: str) -> int:
        return {
            "pnr_lt_3": 0,
            "pnr_3_6": 1,
            "pnr_6_10": 2,
            "pnr_gte_10": 3,
            "pnr_unknown": 4,
        }.get(band, 99)

    @staticmethod
    def _pnr_band_background_color(band: str) -> str:
        return {
            "pnr_lt_3": "#FEE2E2",
            "pnr_3_6": "#FFEDD5",
            "pnr_6_10": "#DCFCE7",
            "pnr_gte_10": "#BBF7D0",
            "pnr_unknown": "#E5E7EB",
        }.get(band, "#E5E7EB")

    @staticmethod
    def _pnr_band_text_color(band: str) -> str:
        return {
            "pnr_lt_3": "#B42318",
            "pnr_3_6": "#C2410C",
            "pnr_6_10": "#166534",
            "pnr_gte_10": "#166534",
            "pnr_unknown": "#475569",
        }.get(band, "#475569")

    def _product_view_label(self, view_mode: str | None = None) -> str:
        return self.PRODUCT_VIEW_LABELS.get(view_mode or self._current_product_view_mode(), "By System")

    def _group_products_for_view(
        self,
        products: list[ProductResult],
        view_mode: str,
    ) -> dict[str, list[ProductResult]]:
        grouped: dict[str, list[ProductResult]] = defaultdict(list)
        for product in products:
            grouped[self._product_group_key(product, view_mode)].append(product)
        return dict(sorted(grouped.items(), key=lambda item: self._product_group_sort_key(view_mode, item[0])))

    def _product_group_key(self, product: ProductResult, view_mode: str) -> str:
        if view_mode == "by_direction":
            return self._product_direction(product)
        if view_mode == "by_signal":
            return self._product_signal(product) or "--"
        if view_mode == "by_pnr_band":
            return self._pnr_band_key(self._product_peak_to_noise_ratio(product))
        return self._product_constellation(product)

    def _product_group_sort_key(self, view_mode: str, group_key: str) -> tuple[object, str]:
        if view_mode == "by_system":
            try:
                return (self.ALL_SYSTEMS.index(group_key), group_key)
            except ValueError:
                return (len(self.ALL_SYSTEMS), group_key)
        if view_mode == "by_direction":
            return (self._direction_sort_order(group_key), group_key)
        if view_mode == "by_pnr_band":
            return (self._pnr_band_sort_order(group_key), group_key)
        return (group_key, group_key)

    def _product_group_label(self, view_mode: str, group_key: str) -> str:
        if view_mode == "by_direction":
            return self._direction_display_name(group_key)
        if view_mode == "by_signal":
            return group_key
        if view_mode == "by_pnr_band":
            return self._pnr_band_label(group_key)
        return self._system_display_name(group_key)

    def _product_group_color(self, view_mode: str, group_key: str, index: int) -> str:
        signal_palette = [
            "#2563EB",
            "#EA580C",
            "#0F766E",
            "#7C3AED",
            "#D97706",
            "#DC2626",
            "#0891B2",
            "#4F46E5",
        ]
        if view_mode == "by_system":
            return get_sys_color(group_key) if group_key in self.ALL_SYSTEMS else "#64748B"
        if view_mode == "by_direction":
            return {
                "rising": "#2563EB",
                "setting": "#EA580C",
                "unknown": "#94A3B8",
            }.get(group_key, "#64748B")
        if view_mode == "by_pnr_band":
            return {
                "pnr_lt_3": "#DC2626",
                "pnr_3_6": "#EA580C",
                "pnr_6_10": "#16A34A",
                "pnr_gte_10": "#047857",
                "pnr_unknown": "#94A3B8",
            }.get(group_key, "#64748B")
        return signal_palette[index % len(signal_palette)]

    def _make_product_table_item(
        self,
        text: str,
        *,
        sort_value=None,
        alignment: Qt.AlignmentFlag | None = None,
        foreground: str | QColor | None = None,
        background: str | QColor | None = None,
        bold: bool = False,
    ) -> QTableWidgetItem:
        item = SortableTableWidgetItem(text, sort_value=sort_value)
        if alignment is not None:
            item.setTextAlignment(int(alignment))
        if foreground is not None:
            item.setForeground(QColor(foreground) if isinstance(foreground, str) else foreground)
        if background is not None:
            item.setBackground(QColor(background) if isinstance(background, str) else background)
        if bold:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        return item

    def _product_weight(self, product: ProductResult) -> float:
        peak_to_noise_ratio = self._product_peak_to_noise_ratio(product)
        if peak_to_noise_ratio is None:
            return 1.0
        return max(peak_to_noise_ratio, 1e-6)

    def _weighted_product_epochs(self, products: list[ProductResult]) -> list[dict[str, object]]:
        grouped: dict[datetime, list[ProductResult]] = defaultdict(list)
        for product in products:
            grouped[self._normalize_product_timestamp(product.timestamp)].append(product)

        weighted_epochs: list[dict[str, object]] = []
        for timestamp, items in sorted(grouped.items(), key=lambda entry: entry[0]):
            weights = [self._product_weight(item) for item in items]
            total_weight = sum(weights)
            if total_weight <= 0.0:
                weights = [1.0 for _ in items]
                total_weight = float(len(items))
            weighted_value = sum(item.value * weight for item, weight in zip(items, weights)) / total_weight
            weighted_epochs.append(
                {
                    "timestamp": timestamp,
                    "value": weighted_value,
                    "source_count": len(items),
                    "weight_sum": total_weight,
                }
            )
        return weighted_epochs

    @staticmethod
    def _normalize_product_timestamp(timestamp: datetime) -> datetime:
        return timestamp.replace(microsecond=0)

    @staticmethod
    def _format_product_type_label(product_type: str) -> str:
        label_overrides = {
            ProductType.SEA_LEVEL_DYNAMIC_CORRECTED.value: "Sea Level (Dynamic Corrected)",
            ProductType.SEA_LEVEL_RATE.value: "Sea Level Rate",
            ProductType.SEA_LEVEL_ACCELERATION.value: "Sea Level Acceleration",
        }
        if product_type in label_overrides:
            return label_overrides[product_type]
        return product_type.replace("_", " ").title()

    def _selected_product_systems(self) -> set[str]:
        return {system for system, checkbox in self.product_system_checks.items() if checkbox.isChecked()}

    @staticmethod
    def _system_display_name(system: str) -> str:
        return {
            "G": "GPS",
            "R": "GLONASS",
            "E": "Galileo",
            "C": "BeiDou",
            "J": "QZSS",
            "S": "SBAS",
            "I": "IRNSS",
            "M": "Combined",
        }.get(system, system)

    def _refresh_config_view(self) -> None:
        dynamic_status = "On" if self.ir_config.products.enable_dynamic_sea_level_correction else "Off"
        sea_level_status = "On" if self.ir_config.products.enable_sea_level else "Off"
        dynamic_window_hours = float(self.ir_config.products.dynamic_sea_level_window_hours)
        self.config_info_label.setText(
            f"Current IR YAML: {self.ir_config_path}\n"
            f"Station: {self.ir_config.station.station_id} | "
            f"Sea Level: {sea_level_status} | Dynamic Correction: {dynamic_status} | "
            f"Window: {dynamic_window_hours:g} h\n"
            "Realtime stream defaults are applied in memory."
        )
        try:
            self.config_text.setPlainText(self._serialize_ir_config())
        except Exception as exc:
            self.config_text.setPlainText(f"Failed to read config file:\n{exc}")
        self._update_runtime_dynamic_control_state()

    def _update_summary_cards(self) -> None:
        tracked_satellites = len([key for key in self.merged_satellites if key[0] in self.active_systems])
        mountpoint_text = self._current_stream_station_id() or self.ir_config.station.station_id or "--"
        buffered_samples = len(self.observation_buffer)
        if self._use_fast_file_analysis() and self.processed_observation_count > 0:
            buffered_samples = self.processed_observation_count
        self.mountpoint_label.setText(mountpoint_text)
        self.summary_labels["ir_config"].setText(self.ir_config_path.name)
        self.summary_labels["analysis_mode"].setText(self._mode_label())
        self.summary_labels["tracked_satellites"].setText(str(tracked_satellites))
        self.summary_labels["buffered_samples"].setText(str(buffered_samples))
        self.summary_labels["last_run"].setText(
            self.last_analysis_timestamp.strftime("%H:%M:%S") if self.last_analysis_timestamp else "--"
        )

        if self.latest_result is None:
            self.summary_labels["arc_solutions"].setText("--")
            self.summary_labels["successful_arcs"].setText("--")
            self.summary_labels["latest_height"].setText("--")
            self.summary_labels["latest_sea_level"].setText("--")
            self.summary_labels["latest_snow_depth"].setText("--")
            return

        self.summary_labels["arc_solutions"].setText(str(len(self.latest_result.arc_solutions)))
        self.summary_labels["successful_arcs"].setText(str(sum(item.success for item in self.latest_result.arc_solutions)))
        self.summary_labels["latest_height"].setText(self._latest_product_text(ProductType.REFLECTOR_HEIGHT.value))
        self.summary_labels["latest_sea_level"].setText(self._latest_product_text(ProductType.SEA_LEVEL.value))
        self.summary_labels["latest_snow_depth"].setText(self._latest_product_text(ProductType.SNOW_DEPTH.value))

    def _latest_product_text(self, product_type: str) -> str:
        if (
            product_type == ProductType.SEA_LEVEL.value
            and self.ir_config.products.enable_dynamic_sea_level_correction
        ):
            corrected_products = [
                item
                for item in self._products_for_display()
                if item.product_type.value == ProductType.SEA_LEVEL_DYNAMIC_CORRECTED.value
            ]
            if corrected_products:
                products = corrected_products
            else:
                products = [item for item in self._products_for_display() if item.product_type.value == product_type]
        else:
            products = [item for item in self._products_for_display() if item.product_type.value == product_type]
        if not products:
            return "--"
        product = sorted(products, key=lambda item: item.timestamp)[-1]
        peak_to_noise_ratio = self._product_peak_to_noise_ratio(product)
        if peak_to_noise_ratio is None:
            return f"{product.value:.3f} {product.unit}"
        return f"{product.value:.3f} {product.unit} | P/N {peak_to_noise_ratio:.2f}"

    def export_results(self) -> None:
        if self.last_processor is None or self.latest_result is None:
            QMessageBox.information(self, "Reflectometry", "No IR results are available to export.")
            return
        try:
            written = self.last_processor.write_outputs(self.latest_result)
            self.append_log(f"Exported {len(written)} files to {self.last_processor.config.output.output_dir}")
            QMessageBox.information(
                self,
                "Reflectometry",
                "Results exported:\n" + "\n".join(str(path) for path in written),
            )
        except Exception as exc:
            self.append_log(f"Export failed: {exc}")
            QMessageBox.warning(self, "Reflectometry", f"Export failed:\n{exc}")

    def open_ir_config_dialog(self) -> None:
        self._sync_runtime_ir_defaults(force=True)
        dialog = ReflectometryConfigDialog(self.ir_config_path, self, initial_yaml_text=self._serialize_ir_config())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            config_path, config, yaml_text = dialog.get_config()
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(yaml_text, encoding="utf-8")
            self.ir_config_path = config_path
            self.ir_config = config
            self.ir_config.logging.console = False
            self.ir_config.logging.rotating_file = False
            self._apply_runtime_controls_from_config()
            self.observation_buffer = deque(
                [record for record in self.observation_buffer if self._record_matches_buffer_filters(record)]
            )
            self._clear_live_product_history()
            self._reset_realtime_processing(reseed_from_buffer=True)
            self._refresh_config_view()
            self.refresh_live_widgets()
            self._populate_arc_table()
            self._update_summary_cards()
            self.append_log(f"IR config updated: {self.ir_config_path}")
        except Exception as exc:
            QMessageBox.warning(self, "Reflectometry", f"Failed to apply IR config:\n{exc}")

    def on_filter_changed(self) -> None:
        self.active_systems = {key for key, checkbox in self.chk_sys.items() if checkbox.isChecked()}
        self.observation_buffer = deque(
            [record for record in self.observation_buffer if self._record_matches_buffer_filters(record)]
        )
        self._clear_live_product_history()
        self._reset_realtime_processing(reseed_from_buffer=True)
        self.refresh_live_widgets()
        if self._use_fast_file_analysis():
            self._populate_arc_table()
            self._populate_product_selector()
            self._populate_product_table()
            self._refresh_product_plot()
            self._ensure_selected_arc_visible()
            self._update_summary_cards()

    def cleanup_stale_satellites(self) -> None:
        now = time.time()
        stale_prns = [prn for prn, last_seen in self.sat_last_seen.items() if now - last_seen > 5.0]
        for prn in stale_prns:
            self.merged_satellites.pop(prn, None)
            self.sat_last_seen.pop(prn, None)

        self.cleanup_timer = threading.Timer(2.0, self.cleanup_stale_satellites)
        self.cleanup_timer.daemon = True
        self.cleanup_timer.start()

    def open_config_dialog(self) -> None:
        dialog = ConfigDialog(self, self.settings)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.settings = dialog.get_settings()
            self._sync_mode_combo_label()
            self._apply_gui_refresh_policy(announce=True)
            self._sync_runtime_ir_defaults(force=True)
            if getattr(dialog, "disconnect_requested", False):
                self.disconnect_streams()
            elif getattr(dialog, "auto_connect", False):
                self.restart_streams()

    def disconnect_streams(self) -> None:
        self.restart_streams(start_streams=False)

    def restart_streams(self, start_streams: bool = True) -> None:
        self.append_log("=== Restarting reflectometry streams ===" if start_streams else "=== Disconnecting streams ===")
        self._apply_gui_refresh_policy(announce=False)
        self._sync_mode_combo_label()

        if self.batch_analysis_thread is not None:
            self.batch_analysis_thread.signals = None
            self.batch_analysis_thread.stop()
            self.batch_analysis_thread.join(timeout=1.0)
            self.batch_analysis_thread = None

        for thread in self.io_threads:
            thread.stop()
        for thread in self.processing_threads:
            thread.stop()
        for thread in self.io_threads + self.processing_threads:
            thread.join(timeout=1.0)

        for buffer in self.ring_buffers.values():
            buffer.close()

        self.io_threads.clear()
        self.processing_threads.clear()
        self.ring_buffers.clear()
        self._reset_status_indicators()

        self.merged_satellites.clear()
        self.sat_last_seen.clear()
        self.observation_buffer.clear()
        self._clear_live_product_history()
        self._reset_realtime_processing(reseed_from_buffer=False)
        self.latest_result = None
        self.latest_series_by_arc = {}
        self.processed_observation_count = 0
        self.selected_arc_id = None
        self.analysis_loop_enabled = False
        self.analysis_running = False
        self._set_run_button_state("idle")
        self._populate_arc_table()
        self._populate_product_table()
        self._clear_series_plot()
        self._clear_spectrum_plot()
        self._clear_product_plot()
        self.refresh_live_widgets()

        if not start_streams:
            self.append_log("Streams disconnected")
            return

        self.handler = get_shared_handler()

        if self._use_fast_file_analysis():
            self.stream_status["OBS"] = True
            self.eph_data_available = bool(
                self.settings.get("EPH_ENABLED") and (self.settings.get("EPH", {}) or {}).get("file_path")
            )
            self._render_status_indicators()
            self.append_log(
                "Fast RINEX file analysis mode ready. Click Start Analysis to run realtime logic without replay or live UI updates."
            )
            self.append_log(f"Active GNSS systems: {', '.join(sorted(self.active_systems))}")
            return

        if self._is_stream_configured(self.settings["OBS"]):
            if self.settings["OBS"].get("source") == "RINEX File":
                obs_thread = RinexReplayThread(
                    "OBS",
                    self.settings["OBS"],
                    self.signals,
                    handler=self.handler,
                    eph_settings=self.settings.get("EPH", {}),
                    target_systems=sorted(self.active_systems),
                )
                obs_thread.start()
                self.io_threads.append(obs_thread)
                self.append_log("OBS RINEX replay thread started")
            else:
                obs_buffer = RingBuffer(maxsize=1000)
                self.ring_buffers["OBS"] = obs_buffer
                obs_thread = IOThread("OBS", self.settings["OBS"], obs_buffer, self.signals)
                proc_thread = DataProcessingThread("OBS", obs_buffer, self.handler, self.signals)
                obs_thread.start()
                proc_thread.start()
                self.io_threads.append(obs_thread)
                self.processing_threads.append(proc_thread)
                self.append_log("OBS stream threads started")
        else:
            self.append_log("OBS stream not configured")

        if (
            self.settings.get("EPH_ENABLED")
            and self.settings["OBS"].get("source") != "RINEX File"
            and self._is_stream_configured(self.settings["EPH"])
        ):
            if self.settings["EPH"].get("source") == "File":
                self.append_log("EPH file source is supported through RINEX observation replay mode")
            else:
                eph_buffer = RingBuffer(maxsize=1000)
                self.ring_buffers["EPH"] = eph_buffer
                eph_thread = IOThread("EPH", self.settings["EPH"], eph_buffer, self.signals)
                proc_thread = DataProcessingThread("EPH", eph_buffer, self.handler, self.signals)
                eph_thread.start()
                proc_thread.start()
                self.io_threads.append(eph_thread)
                self.processing_threads.append(proc_thread)
                self.append_log("EPH stream threads started")
        elif self.settings.get("EPH_ENABLED"):
            self.append_log("EPH stream enabled but not configured")

        self.append_log(f"Active GNSS systems: {', '.join(sorted(self.active_systems))}")

    def _is_stream_configured(self, settings: dict) -> bool:
        source = settings.get("source", "NTRIP Server")
        if source == "Serial Port":
            return bool(settings.get("port"))
        if source in {"RINEX File", "File"}:
            return bool(settings.get("file_path"))
        return bool(settings.get("host"))

    @Slot(str)
    def append_log(self, text: str) -> None:
        log_text = f"[{datetime.now().strftime('%H:%M:%S')}] {text}"
        self.log_area.append(log_text)
        document = self.log_area.document()
        if document.blockCount() > self.max_log_lines:
            cursor = self.log_area.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            for _ in range(100):
                cursor.movePosition(cursor.MoveOperation.Down, cursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()

    @Slot(str, bool)
    def update_status(self, name: str, connected: bool) -> None:
        if name == "EPH_DATA":
            self.eph_data_available = bool(connected)
            self._render_status_indicator("EPH")
            return

        if name not in self.stream_status:
            return
        self.stream_status[name] = bool(connected)
        self._render_status_indicator(name)
        if name == "OBS" and not connected and self._is_rinex_replay_source():
            QTimer.singleShot(0, self._finalize_rinex_replay_analysis)

    def _reset_status_indicators(self) -> None:
        self.stream_status = {"OBS": False, "EPH": False}
        self.eph_data_available = False
        self._render_status_indicators()

    def _render_status_indicators(self) -> None:
        self._render_status_indicator("OBS")
        self._render_status_indicator("EPH")

    def _render_status_indicator(self, name: str) -> None:
        if name == "OBS":
            label = self.lbl_status_obs
            connected = self.stream_status.get("OBS", False)
        else:
            label = self.lbl_status_eph
            connected = self.stream_status.get("EPH", False) or self.eph_data_available

        color = "#2A692D" if connected else "#6D2F2B"
        label.setText(f"{name}: {'ON' if connected else 'OFF'}")
        label.setStyleSheet(
            f"background-color: {color}; color: white; padding: 4px 8px; "
            "border-radius: 4px; font-weight: bold;"
        )

    def _current_receiver_position(self, fallback: ReceiverPosition | None) -> ReceiverPosition:
        config = get_global_config()
        approx_rec_pos = getattr(config, "approx_rec_pos", None)
        if approx_rec_pos and len(approx_rec_pos) == 3 and any(abs(float(item)) > 1e-6 for item in approx_rec_pos):
            lat_rad, lon_rad, height_m = ecef2lla(approx_rec_pos)
            return ReceiverPosition(
                latitude_deg=float(np.degrees(lat_rad)),
                longitude_deg=float(np.degrees(lon_rad)),
                height_m=float(height_m),
                x_m=float(approx_rec_pos[0]),
                y_m=float(approx_rec_pos[1]),
                z_m=float(approx_rec_pos[2]),
            )
        return fallback or ReceiverPosition()

    def on_back_to_launcher(self) -> None:
        self.back_to_launcher.emit()
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.skyplot_dialog is not None:
            self.skyplot_dialog.close()
        if self.batch_analysis_thread is not None:
            self.batch_analysis_thread.signals = None
            self.batch_analysis_thread.stop()
            self.batch_analysis_thread.join(timeout=1.0)
            self.batch_analysis_thread = None
        for thread in self.io_threads:
            thread.stop()
        for thread in self.processing_threads:
            thread.stop()
        for buffer in self.ring_buffers.values():
            buffer.close()
        if hasattr(self, "cleanup_timer"):
            self.cleanup_timer.cancel()
        if hasattr(self, "gui_update_timer"):
            self.gui_update_timer.stop()
        if hasattr(self, "analysis_timer"):
            self.analysis_timer.stop()
        event.accept()

    def _apply_gui_refresh_policy(self, announce: bool) -> None:
        previous_interval = getattr(self, "gui_update_interval", self.base_gui_update_interval)
        self.gui_update_interval = choose_gui_refresh_interval(
            self.base_gui_update_interval,
            self.settings.get("OBS", {}),
        )

        timer_interval_ms = 100 if self.gui_update_interval >= THROTTLED_GUI_INTERVAL_SECONDS else 80
        if hasattr(self, "gui_update_timer"):
            self.gui_update_timer.start(timer_interval_ms)

        if not announce:
            return

        if abs(self.gui_update_interval - previous_interval) < 1e-9:
            return

        if self.gui_update_interval >= THROTTLED_GUI_INTERVAL_SECONDS:
            effective_period = estimate_effective_replay_period_seconds(self.settings.get("OBS", {}))
            if effective_period and effective_period > 0.0:
                self.append_log(
                    f"High-rate RINEX replay detected, GUI refresh capped at {self.gui_update_interval:.1f}s "
                    f"(effective epoch period {effective_period:.3f}s)"
                )
            else:
                self.append_log(
                    f"High-rate RINEX replay detected, GUI refresh capped at {self.gui_update_interval:.1f}s"
                )
        else:
            self.append_log(f"GUI refresh restored to {self.gui_update_interval:.1f}s cadence")


def _optional_float(value) -> float | None:
    if value is None:
        return None
    return float(value)


def _circular_mean_deg(values) -> float | None:
    if not values:
        return None
    radians = np.radians(np.asarray(values, dtype=float) % 360.0)
    sin_mean = float(np.mean(np.sin(radians)))
    cos_mean = float(np.mean(np.cos(radians)))
    if abs(sin_mean) < 1e-12 and abs(cos_mean) < 1e-12:
        return None
    return float((np.degrees(np.arctan2(sin_mean, cos_mean)) + 360.0) % 360.0)

