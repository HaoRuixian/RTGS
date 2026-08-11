"""
GNSS RT Monitor - Positioning Module

Provides real-time GNSS positioning using pseudorange observations.
Supports SPP/PPP in Python and RTK through a native process engine.

Architecture:
- Uses shared IOThread/DataProcessingThread from monitoring module for observations
- Own PositioningThread for SPP/PPP/RTK computation
- Real-time visualization of position, accuracy, and diagnostics
"""

import threading
import time
from datetime import datetime
from collections import deque

from PySide6.QtWidgets import (
    QAbstractItemView, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QFrame, 
    QSplitter, QStyle, QComboBox, QDialog, QPlainTextEdit
)
from PySide6.QtCore import Qt, Slot, QTimer, Signal
from PySide6.QtGui import QColor, QFont

from ui.positioning.workers import PositioningThread, PositioningSignals, RTKEngineThread
from ui.positioning.widgets import (
    PositionMapWidget, PositionInfoWidget, AccuracyWidget, AtmosphereWidget, ResidualWidget,
    format_solution_status,
)
from ui.monitoring.workers import IOThread, DataProcessingThread, RinexReplayThread, StreamSignals
from ui.shared.config_dialog import ConfigDialog
from ui.positioning.positioning_config_dialog import PositioningConfigDialog
from ui.style import get_app_stylesheet
from ui.responsive import adaptive_window_size, window_ui_scale
from core.ring_buffer import RingBuffer
from core.rtcm_handler import RTCMHandler, get_shared_handler
from core.positioning_models import PositioningMode, SolutionStatus
from core.global_config import get_global_config
from core.stream_settings import is_realtime_stream_configured, stream_source
from core.replay_ui_policy import (
    THROTTLED_GUI_INTERVAL_SECONDS,
    choose_gui_refresh_interval,
    estimate_effective_replay_period_seconds,
)


class PositioningModule(QMainWindow):
    """
    Main positioning module window.
    
    Responsibilities:
    - Manage data streams (NTRIP/Serial) via shared IOThread and DataProcessingThread
    - Compute positions via PositioningThread
    - Display real-time position, accuracy, and diagnostics
    """
    back_to_launcher = Signal()
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RTGS - Positioning Module")
        adaptive_window_size(self, target=(1600, 1000), minimum=(1080, 700))

        # ======================================================================
        # Thread management
        # ======================================================================
        # Shared components (data acquisition)
        self.observer_signals = StreamSignals()
        self.observer_signals.log_signal.connect(self.append_log)
        self.observer_signals.epoch_signal.connect(self.on_observation_epoch)
        self.observer_signals.status_signal.connect(self.update_stream_status)

        self.ring_buffers = {}
        self.io_threads = []
        self.processing_threads = []
        self.rtcm_handler = get_shared_handler()

        # Positioning computation
        self.positioning_signals = PositioningSignals()
        self.positioning_signals.solution_signal.connect(self.on_positioning_solution)
        self.positioning_signals.log_signal.connect(self.append_log)
        self.positioning_signals.status_signal.connect(self.update_positioning_status)
        self.positioning_signals.stream_status_signal.connect(self.update_stream_status)
        
        # Ring buffer for positioning epochs
        self.positioning_ring_buffer = RingBuffer(maxsize=200)
        
        self.positioning_thread = PositioningThread(
            "POS", self.positioning_signals, self.positioning_ring_buffer, self.rtcm_handler
        )
        self.rtk_thread = None
        self._compact_scale = None
        self.display_mode = "LLH"
        self.solution_history = deque(maxlen=100)
        
        # ======================================================================
        # Stream configuration
        # ======================================================================
        self.settings = {
            'OBS': {
                'source': 'NTRIP Server',
                'host': '',
                'port': 2101,
                'mountpoint': '',
                'user': '',
                'password': '',
                'baudrate': 115200,
                'file_path': '',
                'replay_speed': 1.0,
                'file_type': 'Auto Detect',
            },
            'EPH_ENABLED': False,
            'EPH': {
                'source': 'NTRIP Server',
                'host': '',
                'port': 2101,
                'mountpoint': '',
                'user': '',
                'password': '',
                'baudrate': 115200,
                'file_path': '',
                'replay_speed': 1.0,
                'file_type': 'Auto Detect',
            },
            'SSR_ENABLED': False,
            'SSR': {
                'source': 'NTRIP Server',
                'host': '',
                'port': 2101,
                'mountpoint': '',
                'user': '',
                'password': '',
                'baudrate': 115200,
                'file_path': '',
                'replay_speed': 1.0,
                'file_type': 'Auto Detect',
            },
            'BASE_ENABLED': False,
            'BASE': {
                'source': 'NTRIP Server',
                'host': '',
                'port': 2101,
                'mountpoint': '',
                'user': '',
                'password': '',
                'baudrate': 115200,
                'data_format': 'RTCM3',
            },
        }
        
        # ======================================================================
        # UI components
        # ======================================================================
        self.setup_ui()
        self.apply_stylesheet()
        
        # ======================================================================
        # Status and logging
        # ======================================================================
        self.log_queue = deque(maxlen=500)
        self._pending_log_lines = deque(maxlen=500)
        self._log_dirty = False
        self._log_paused = False
        self.is_running = False
        self.is_stopping = False
        self._stopping_threads = []
        self._stop_deadline = 0.0
        self._stop_poll_timer = QTimer(self)
        self._stop_poll_timer.setInterval(100)
        self._stop_poll_timer.timeout.connect(self._poll_stop_completion)
        self.base_solution_ui_interval = 0.25
        self.solution_ui_interval = self.base_solution_ui_interval
        self.last_solution_ui_time = 0.0
        self.pending_solution = None
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_ui)
        self.update_timer.start(100)
        self._apply_replay_ui_policy(announce=False)
        
        self.append_log("=== RTGS Positioning Module Initialized ===")

    def setup_ui(self):
        """Build UI layout."""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)
        
        # ======================================================================
        # Top control bar
        # ======================================================================
        control_bar = QFrame()
        control_bar.setObjectName("ControlBar")
        top_bar = QHBoxLayout(control_bar)
        top_bar.setContentsMargins(8, 6, 8, 6)
        top_bar.setSpacing(8)

        self.btn_back = QPushButton("Back")
        self.btn_back.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        self.btn_back.setToolTip("Back to launcher")
        self.btn_back.clicked.connect(self.on_back_to_launcher)
        top_bar.addWidget(self.btn_back)
        
        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        top_bar.addWidget(line)
        
        # Mode selector
        self.lbl_mode = QLabel("Mode")
        top_bar.addWidget(self.lbl_mode)
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["SPP", "PPP", "RTK"])
        self.combo_mode.setItemData(0, "Single Point Positioning", Qt.ItemDataRole.ToolTipRole)
        self.combo_mode.setItemData(1, "Precise Point Positioning", Qt.ItemDataRole.ToolTipRole)
        self.combo_mode.setItemData(2, "Single-base or network RTK", Qt.ItemDataRole.ToolTipRole)
        self.combo_mode.setCurrentIndex(0)
        self.combo_mode.currentIndexChanged.connect(self.on_mode_changed)
        self.combo_mode.setMinimumWidth(90)
        self.combo_mode.setMaximumWidth(140)
        top_bar.addWidget(self.combo_mode)
        
        # Config button
        self.btn_config = QPushButton("Streams")
        self.btn_config.setToolTip("Configure observation, ephemeris and SSR streams")
        self.btn_config.clicked.connect(self.open_config_dialog)
        top_bar.addWidget(self.btn_config)

        # Positioning settings button
        self.btn_pos_settings = QPushButton("Solver")
        self.btn_pos_settings.setToolTip("Configure positioning engine")
        self.btn_pos_settings.clicked.connect(self.open_positioning_settings_dialog)
        top_bar.addWidget(self.btn_pos_settings)

        self.lbl_coord_mode = QLabel("Coordinates")
        top_bar.addWidget(self.lbl_coord_mode)
        self.combo_coord_mode = QComboBox()
        self.combo_coord_mode.addItem("Lat/Lon/H", "LLH")
        self.combo_coord_mode.addItem("ECEF XYZ", "XYZ")
        self.combo_coord_mode.setMaximumWidth(150)
        self.combo_coord_mode.currentIndexChanged.connect(self.on_coordinate_mode_changed)
        top_bar.addWidget(self.combo_coord_mode)
        
        # Start/Stop button
        self.btn_start = QPushButton("Start")
        self.btn_start.setMinimumWidth(90)
        self.btn_start.setObjectName("PrimaryButton")
        self.btn_start.clicked.connect(self.toggle_positioning)
        top_bar.addWidget(self.btn_start)
        
        # Status indicators
        self.lbl_obs_status = QLabel("OBS: OFF")
        self.lbl_obs_status.setProperty("class", "status")
        self._set_status_badge(self.lbl_obs_status, "OBS: OFF", "#6D2F2B")
        top_bar.addWidget(self.lbl_obs_status)

        self.lbl_eph_status = QLabel("EPH: OFF")
        self.lbl_eph_status.setProperty("class", "status")
        self._set_status_badge(self.lbl_eph_status, "EPH: OFF", "#6D2F2B")
        top_bar.addWidget(self.lbl_eph_status)

        self.lbl_ssr_status = QLabel("SSR: OFF")
        self.lbl_ssr_status.setProperty("class", "status")
        self._set_status_badge(self.lbl_ssr_status, "SSR: OFF", "#6D2F2B")
        top_bar.addWidget(self.lbl_ssr_status)
        
        self.lbl_pos_status = QLabel("POS: IDLE")
        self.lbl_pos_status.setProperty("class", "status")
        self._set_status_badge(self.lbl_pos_status, "POS: IDLE", "#4B5563")
        top_bar.addWidget(self.lbl_pos_status)
        
        top_bar.addStretch()
        main_layout.addWidget(control_bar)
        
        # ======================================================================
        # Main content area
        # ======================================================================
        workspace_splitter = QSplitter(Qt.Orientation.Vertical)
        visual_splitter = QSplitter(Qt.Orientation.Horizontal)

        self.map_widget = PositionMapWidget()
        self.map_widget.setMinimumHeight(240)
        visual_splitter.addWidget(self.map_widget)

        accuracy_panel = QFrame()
        accuracy_panel.setObjectName("Panel")
        accuracy_layout = QVBoxLayout(accuracy_panel)
        accuracy_layout.setContentsMargins(8, 6, 8, 8)
        accuracy_layout.setSpacing(4)
        accuracy_title = QLabel("Precision monitors")
        accuracy_title.setObjectName("SectionTitle")
        accuracy_layout.addWidget(accuracy_title)
        self.accuracy_widget = AccuracyWidget()
        self.atmosphere_widget = AtmosphereWidget()
        self.monitor_tabs = QTabWidget()
        self.monitor_tabs.addTab(self.accuracy_widget, "DOP")
        self.monitor_tabs.addTab(self.atmosphere_widget, "Atmosphere")
        self.monitor_tabs.setDocumentMode(True)
        self.monitor_tabs.currentChanged.connect(self._on_monitor_tab_changed)
        accuracy_layout.addWidget(self.monitor_tabs, 1)
        visual_splitter.addWidget(accuracy_panel)
        visual_splitter.setStretchFactor(0, 9)
        visual_splitter.setStretchFactor(1, 11)
        visual_splitter.setSizes([640, 780])
        workspace_splitter.addWidget(visual_splitter)

        self.detail_tabs = QTabWidget()
        self.right_tabs = self.detail_tabs
        self.info_widget = PositionInfoWidget()
        self.detail_tabs.addTab(self.info_widget, "Current solution")

        self.residual_widget = ResidualWidget()
        self.detail_tabs.addTab(self.residual_widget, "Position offsets")

        self.history_table = QTableWidget()
        self._configure_history_table()
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setShowGrid(False)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.history_table.horizontalHeader().setHighlightSections(False)
        self.detail_tabs.addTab(self.history_table, "Solution history")

        log_page = QWidget()
        log_layout = QVBoxLayout(log_page)
        log_layout.setContentsMargins(6, 6, 6, 6)
        log_layout.setSpacing(6)
        log_controls = QHBoxLayout()
        self.btn_pause_log = QPushButton("Pause")
        self.btn_pause_log.setCheckable(True)
        self.btn_pause_log.setToolTip("Pause visual log updates while keeping messages buffered")
        self.btn_pause_log.toggled.connect(self._on_log_pause_toggled)
        btn_clear_log = QPushButton("Clear")
        btn_clear_log.clicked.connect(self.clear_log)
        self.lbl_log_state = QLabel("Live")
        self.lbl_log_state.setProperty("class", "muted")
        log_controls.addWidget(self.btn_pause_log)
        log_controls.addWidget(btn_clear_log)
        log_controls.addWidget(self.lbl_log_state)
        log_controls.addStretch()
        log_layout.addLayout(log_controls)

        self.log_area = QPlainTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_area.document().setMaximumBlockCount(500)
        log_layout.addWidget(self.log_area)
        self.detail_tabs.addTab(log_page, "System log")
        self.detail_tabs.currentChanged.connect(self._on_detail_tab_changed)
        workspace_splitter.addWidget(self.detail_tabs)
        workspace_splitter.setStretchFactor(0, 9)
        workspace_splitter.setStretchFactor(1, 11)
        workspace_splitter.setSizes([430, 500])

        main_layout.addWidget(workspace_splitter, stretch=1)
        self._apply_compact_ui()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_compact_ui()

    def _apply_compact_ui(self):
        if not hasattr(self, "map_widget") or not hasattr(self, "btn_back"):
            return
        scale = window_ui_scale(self)
        if self._compact_scale == scale:
            return

        self._compact_scale = scale
        self.setStyleSheet(get_app_stylesheet(scale))
        self.map_widget.setMinimumHeight(max(220, int(250 * scale)))
        self.btn_back.setText("Back")
        self.btn_pos_settings.setText("Solver")
        self.lbl_mode.setText("Mode")
        self.lbl_coord_mode.setText("Coordinates")
        self._refresh_start_button_text()

    def _refresh_start_button_text(self):
        if getattr(self, "is_running", False):
            self.btn_start.setText("Stop")
        else:
            self.btn_start.setText("Start")

    def _set_status_badge(self, label: QLabel, text: str, color: str) -> None:
        label.setText(text)
        label.setStyleSheet(
            f"background-color: {color}; color: white; padding: 4px 8px; "
            "border-radius: 4px; font-weight: bold;"
        )

    def _configure_history_table(self) -> None:
        self.history_table.setColumnCount(7)
        metric = "Ratio" if self.combo_mode.currentIndex() == 2 else "HDOP"
        if self.display_mode == "XYZ":
            headers = ["Time", "ECEF X (m)", "ECEF Y (m)", "ECEF Z (m)", metric, "Sats", "Status"]
        else:
            headers = ["Time", "Lat (deg)", "Lon (deg)", "Height (m)", metric, "Sats", "Status"]
        self.history_table.setHorizontalHeaderLabels(headers)

    def _refresh_history_table(self) -> None:
        if not hasattr(self, "history_table"):
            return
        self._configure_history_table()
        self.history_table.setUpdatesEnabled(False)
        self.history_table.setRowCount(len(self.solution_history))
        for row, (timestamp, solution) in enumerate(self.solution_history):
            self._populate_history_row(row, timestamp, solution)
        self.history_table.setUpdatesEnabled(True)

    def _history_values(self, timestamp, solution):
        if self.display_mode == "XYZ":
            coordinates = [f"{solution.ecef_x:.3f}", f"{solution.ecef_y:.3f}", f"{solution.ecef_z:.3f}"]
        else:
            coordinates = [f"{solution.latitude:.8f}", f"{solution.longitude:.8f}", f"{solution.height:.3f}"]
        metric = (
            f"{solution.ambiguity_ratio:.2f}"
            if getattr(solution, "mode", None) == PositioningMode.RTK
            else f"{solution.hdop:.2f}"
        )
        return [
            timestamp, *coordinates, metric,
            str(solution.num_satellites), format_solution_status(solution.status),
        ]

    def _populate_history_row(self, row, timestamp, solution):
        for col, value in enumerate(self._history_values(timestamp, solution)):
            item = QTableWidgetItem(value)
            item.setFont(QFont("Consolas", 9))
            item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignLeft if col in (0, 6) else Qt.AlignmentFlag.AlignRight))
            if col == 6:
                self._style_status_item(item, solution.status)
            self.history_table.setItem(row, col, item)

    def _prepend_history_row(self, timestamp, solution):
        self.history_table.setUpdatesEnabled(False)
        self.history_table.insertRow(0)
        self._populate_history_row(0, timestamp, solution)
        while self.history_table.rowCount() > self.solution_history.maxlen:
            self.history_table.removeRow(self.history_table.rowCount() - 1)
        self.history_table.setUpdatesEnabled(True)

    def _style_status_item(self, item: QTableWidgetItem, status: SolutionStatus) -> None:
        text = format_solution_status(status)
        if text == "Fixed":
            item.setForeground(QColor("#2A692D"))
        elif text == "Unfixed":
            item.setForeground(QColor("#B7791F"))
        else:
            item.setForeground(QColor("#6D2F2B"))
        status_font = QFont("Consolas", 9)
        status_font.setWeight(QFont.Weight.Bold)
        item.setFont(status_font)

    def _update_solution_badge(self, status: SolutionStatus) -> None:
        if status == SolutionStatus.FIXED:
            self._set_status_badge(self.lbl_pos_status, "POS: FIXED", "#2A692D")
        elif status == SolutionStatus.UNCERTAIN:
            self._set_status_badge(self.lbl_pos_status, "POS: UNFIXED", "#B7791F")
        else:
            self._set_status_badge(self.lbl_pos_status, "POS: NO FIX", "#6D2F2B")

    def _reset_solution_views(self) -> None:
        self.pending_solution = None
        self.last_solution_ui_time = 0.0
        self.solution_history.clear()
        self.info_widget.clear()
        self.accuracy_widget.clear()
        self.atmosphere_widget.clear()
        self.residual_widget.clear()
        self.map_widget.clear_track()
        self.history_table.setRowCount(0)
        self._set_status_badge(self.lbl_pos_status, "POS: IDLE", "#4B5563")

    def open_config_dialog(self):
        """Open stream configuration dialog."""
        # Create a simple config dialog (same as monitoring module)
        from ui.shared.config_dialog import ConfigDialog
        dlg = ConfigDialog(self, self.settings)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.settings = dlg.get_settings()
            self.positioning_thread.refresh_runtime_config()
            self._apply_replay_ui_policy(announce=True)
            self.append_log("Settings updated")
            if getattr(dlg, 'disconnect_requested', False):
                self.append_log("Disconnect requested: stopping positioning and data streams")
                self.stop_positioning()
                return
            # If user requested Connect from the dialog, start streams only (do not start positioning)
            if getattr(dlg, 'auto_connect', False):
                if self.combo_mode.currentIndex() == 2:
                    self.append_log("RTK streams are ready and will connect when RTK positioning starts")
                    return
                self.append_log("Auto-connect requested: starting data streams (positioning not started)")
                try:
                    self.start_streams()
                except Exception as e:
                    self.append_log(f"Error starting streams: {e}")

    def on_mode_changed(self, index):
        """Handle positioning mode change."""
        modes = [PositioningMode.SPP, PositioningMode.PPP, PositioningMode.RTK]
        if index < len(modes):
            self.positioning_thread.set_mode(modes[index])
            self.append_log(f"Positioning mode changed to {modes[index].value}")
            if modes[index] == PositioningMode.RTK:
                self._set_status_badge(self.lbl_ssr_status, "BASE: OFF", "#6D2F2B")
                self.lbl_ssr_status.setToolTip("RTK base station or network correction stream")
            else:
                self._set_status_badge(self.lbl_ssr_status, "SSR: OFF", "#6D2F2B")
                self.lbl_ssr_status.setToolTip("SSR correction stream")
            if self.is_running:
                self.append_log("Mode changes are applied after the current positioning run stops")
                self.stop_positioning()
            self._refresh_history_table()

    def on_coordinate_mode_changed(self, _index: int):
        """Switch all coordinate-oriented displays between LLH and ECEF XYZ."""
        mode = self.combo_coord_mode.currentData() or "LLH"
        self.display_mode = "XYZ" if mode == "XYZ" else "LLH"
        self.info_widget.set_display_mode(self.display_mode)
        self.map_widget.set_display_mode(self.display_mode)
        self.residual_widget.set_display_mode(self.display_mode)
        self._refresh_history_table()

    def open_positioning_settings_dialog(self):
        """Open dialog to configure positioning (SPP) parameters."""
        dlg = PositioningConfigDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            params = dlg.get_settings()
            self.positioning_thread.update_positioning_settings(params)
            self._ensure_stream_target_systems_for_positioning(params.get("gnss_systems", []), announce=True)
            active_systems = ",".join(params.get("gnss_systems", []))
            gps_only = "ON" if params.get("prefer_gps_only") else "OFF"
            self.append_log(f"Positioning settings updated: systems={active_systems}, prefer GPS-only={gps_only}")

    def _ensure_stream_target_systems_for_positioning(self, gnss_systems=None, announce: bool = False) -> None:
        """Keep the RTCM/RINEX stream filter wide enough for selected positioning systems."""
        selected = list(gnss_systems or getattr(self.positioning_thread.positioner, "gnss_systems", []) or [])
        if not selected:
            return

        config = get_global_config()
        current = [str(item).strip().upper()[:1] for item in (config.target_systems or []) if str(item).strip()]
        expanded = list(current)
        for system in selected:
            normalized = str(system).strip().upper()[:1]
            if normalized and normalized not in expanded:
                expanded.append(normalized)

        if expanded != current:
            config.update_general_settings({"target_systems": expanded})
            if announce:
                self.append_log(f"Stream target systems expanded for positioning: {','.join(expanded)}")

    def toggle_positioning(self):
        """Start/stop positioning."""
        if self.is_stopping:
            return
        if not self.is_running:
            self.start_positioning()
        else:
            self.stop_positioning()

    def start_positioning(self):
        """Start all threads."""
        if self.is_stopping:
            return
        try:
            self._reset_solution_views()

            mode_index = min(self.combo_mode.currentIndex(), 2)
            mode = [PositioningMode.SPP, PositioningMode.PPP, PositioningMode.RTK][mode_index]

            if mode == PositioningMode.RTK:
                config = get_global_config()
                if not config.base_settings.enabled:
                    raise RuntimeError("Enable and configure the RTK base/network stream in Streams")
                self.rtk_thread = RTKEngineThread("RTK", self.positioning_signals)
                self.is_running = True
                self.rtk_thread.start()
                self._refresh_start_button_text()
                self.btn_start.setStyleSheet("background-color: #B05E5E; color: white;")
                self._set_status_badge(self.lbl_pos_status, "POS: ACTIVE", "#2563EB")
                settings = config.get_positioning_settings()
                rtk_type = settings.get("rtk_type", "single_base")
                protocol = settings.get("rtk_network_protocol", "VRS")
                label = f"network {protocol}" if rtk_type == "network" else "single-base"
                self.append_log(f"RTK positioning started ({label})")
                return

            # SPP/PPP use RTGS stream decoding and epoch processing.
            self.start_streams()

            # Create fresh positioning ring buffer
            self.positioning_ring_buffer = RingBuffer(maxsize=200)
            if (
                self.positioning_thread is None
                or (not self.positioning_thread.is_alive() and getattr(self.positioning_thread, "ident", None) is not None)
            ):
                self.positioning_thread = PositioningThread(
                    "POS", self.positioning_signals, self.positioning_ring_buffer, self.rtcm_handler
                )
                self.positioning_thread.set_mode(mode)
            else:
                self.positioning_thread.set_ring_buffer(self.positioning_ring_buffer)

            # A stream YAML can provide both the exact evaluation coordinate
            # and PPP filter settings.  Synchronise them even when this thread
            # was constructed before the configuration dialog was opened.
            self.positioning_thread.refresh_runtime_config()

            # Start positioning thread if not already running
            if not getattr(self.positioning_thread, 'is_alive', lambda: False)():
                self.positioning_thread.start()

            self.is_running = True
            self._refresh_start_button_text()
            self.btn_start.setStyleSheet("background-color: #B05E5E; color: white;")
            self._set_status_badge(self.lbl_pos_status, "POS: ACTIVE", "#2563EB")
            self.append_log("Positioning started")
            
        except Exception as e:
            self.append_log(f"Error starting positioning: {str(e)}")
            self.is_running = False

    def start_streams(self):
        """Start IO and DataProcessing threads only (do not start positioning)."""
        self._apply_replay_ui_policy(announce=False)
        self._ensure_stream_target_systems_for_positioning()
        # Validate configuration minimal requirements
        obs_source = stream_source(self.settings.get('OBS', {}))
        if not self.settings.get('OBS', {}).get('host') and obs_source == 'NTRIP Server':
            raise RuntimeError("Missing OBS NTRIP host configuration")
        if not self.settings.get('OBS', {}).get('port') and obs_source == 'Serial Port':
            raise RuntimeError("Missing OBS serial port configuration")
        if not self.settings.get('OBS', {}).get('file_path') and obs_source == 'RINEX File':
            raise RuntimeError("Missing OBS RINEX observation file")

        # Initialize buffers only if not already present
        if 'OBS' not in self.ring_buffers and obs_source != 'RINEX File':
            self.ring_buffers['OBS'] = RingBuffer(maxsize=1000)

            io_thread_obs = IOThread(
                'OBS', self.settings['OBS'],
                self.ring_buffers['OBS'],
                self.observer_signals
            )
            io_thread_obs.start()
            self.io_threads.append(io_thread_obs)

            proc_thread_obs = DataProcessingThread(
                'OBS', self.ring_buffers['OBS'],
                self.rtcm_handler, self.observer_signals
            )
            proc_thread_obs.start()
            self.processing_threads.append(proc_thread_obs)
        elif obs_source == 'RINEX File' and not self.io_threads:
            replay_thread = RinexReplayThread(
                'OBS',
                self.settings['OBS'],
                self.observer_signals,
                handler=self.rtcm_handler,
                eph_settings=self.settings.get('EPH', {}),
                target_systems=get_global_config().target_systems,
            )
            replay_thread.start()
            self.io_threads.append(replay_thread)

        # EPH stream
        if self.settings.get('EPH_ENABLED') and obs_source != 'RINEX File' and 'EPH' not in self.ring_buffers:
            eph_source = stream_source(self.settings['EPH'])
            if eph_source == 'File':
                self.append_log("EPH file source is supported through RINEX observation replay mode")
            elif not is_realtime_stream_configured(self.settings['EPH']):
                self.append_log("EPH stream enabled but not configured")
            else:
                self.ring_buffers['EPH'] = RingBuffer(maxsize=500)

                io_thread_eph = IOThread(
                    'EPH', self.settings['EPH'],
                    self.ring_buffers['EPH'],
                    self.observer_signals
                )
                io_thread_eph.start()
                self.io_threads.append(io_thread_eph)

                proc_thread_eph = DataProcessingThread(
                    'EPH', self.ring_buffers['EPH'],
                    self.rtcm_handler, self.observer_signals
                )
                proc_thread_eph.start()
                self.processing_threads.append(proc_thread_eph)

        if self.settings.get('SSR_ENABLED') and obs_source != 'RINEX File' and 'SSR' not in self.ring_buffers:
            if not is_realtime_stream_configured(self.settings.get('SSR', {})):
                self.append_log("SSR stream enabled but not configured")
            else:
                self.ring_buffers['SSR'] = RingBuffer(maxsize=500)

                io_thread_ssr = IOThread(
                    'SSR', self.settings['SSR'],
                    self.ring_buffers['SSR'],
                    self.observer_signals
                )
                io_thread_ssr.start()
                self.io_threads.append(io_thread_ssr)

                proc_thread_ssr = DataProcessingThread(
                    'SSR', self.ring_buffers['SSR'],
                    self.rtcm_handler, self.observer_signals
                )
                proc_thread_ssr.start()
                self.processing_threads.append(proc_thread_ssr)

        self.append_log("Data streams started")

    def stop_positioning(self):
        """Request shutdown without blocking the GUI thread."""
        if self.is_stopping:
            return
        try:
            self.is_running = False
            self.is_stopping = True
            self.btn_start.setEnabled(False)
            self.btn_start.setText("Stopping...")

            threads = [self.positioning_thread, self.rtk_thread, *self.processing_threads, *self.io_threads]
            if self.positioning_thread.is_alive():
                try:
                    self.positioning_thread.stop()
                except Exception:
                    pass
            if self.rtk_thread is not None:
                try:
                    self.rtk_thread.stop()
                except Exception:
                    pass

            for thread in list(self.processing_threads):
                try:
                    thread.stop()
                except Exception:
                    pass

            for thread in list(self.io_threads):
                try:
                    thread.stop()
                except Exception:
                    pass

            for buf in self.ring_buffers.values():
                try:
                    buf.close()
                except Exception:
                    pass
            
            # Close positioning ring buffer
            try:
                self.positioning_ring_buffer.close()
            except Exception:
                pass

            self.io_threads.clear()
            self.processing_threads.clear()
            self.ring_buffers.clear()
            self.pending_solution = None
            self.update_stream_status('OBS', False)
            self.update_stream_status('EPH', False)
            self.update_stream_status('SSR', False)
            self.update_stream_status('BASE', False)

            self.btn_start.setStyleSheet("")
            self._reset_solution_views()
            self.append_log("Stopping positioning and data streams...")

            self._stopping_threads = [thread for thread in threads if thread is not None]
            self._stop_deadline = time.monotonic() + 3.0
            self._stop_poll_timer.start()
            self._poll_stop_completion()
            
        except Exception as e:
            self.append_log(f"Error stopping positioning: {str(e)}")
            self._finish_stop_ui()

    def _poll_stop_completion(self):
        alive = [thread for thread in self._stopping_threads if thread.is_alive()]
        self._stopping_threads = alive
        if alive and time.monotonic() < self._stop_deadline:
            return
        if alive:
            names = ", ".join(thread.name for thread in alive)
            self.append_log(f"Shutdown continues in background: {names}")
            threading.Thread(target=self._reap_threads, args=(alive,), daemon=True).start()
        self._finish_stop_ui()

    @staticmethod
    def _reap_threads(threads):
        for thread in threads:
            try:
                thread.join(timeout=10.0)
            except Exception:
                pass

    def _finish_stop_ui(self):
        self._stop_poll_timer.stop()
        self._stopping_threads = []
        self.is_stopping = False
        if self.rtk_thread is not None and not self.rtk_thread.is_alive():
            self.rtk_thread = None
        self.btn_start.setEnabled(True)
        self._refresh_start_button_text()
        self.append_log("Positioning stopped")

    @Slot(object)
    def on_observation_epoch(self, epoch_obs):
        """Receive observation epoch from monitoring and forward to positioning."""
        if not self.is_running:
            return
        if epoch_obs is None:
            return
        if getattr(epoch_obs, "utc_datetime", None) is None:
            return
        if not getattr(epoch_obs, "satellites", None):
            return
        if self.combo_mode.currentIndex() == 2:
            return
        # Submit to positioning ring buffer
        self.positioning_ring_buffer.put(epoch_obs, block=False)

    @Slot(object)
    def on_positioning_solution(self, solution):
        """Receive positioning solution."""
        if not self.is_running:
            return
        self.pending_solution = solution
        now = time.time()
        if self.solution_ui_interval <= 0.0 or now - self.last_solution_ui_time >= self.solution_ui_interval:
            self._flush_pending_solution(now)

    def _apply_solution_to_ui(self, solution):
        """Render one positioning solution onto the UI."""
        self.info_widget.update_solution(solution)
        self.accuracy_widget.update_solution(solution)
        self.atmosphere_widget.update_solution(solution)
        self.residual_widget.update_solution(solution)
        self._update_solution_badge(solution.status)
        if solution.status != SolutionStatus.NO_FIX:
            self.map_widget.update_solution(solution)

        epoch_time = getattr(solution, "epoch_time", None)
        if isinstance(epoch_time, datetime):
            timestamp = epoch_time.strftime('%H:%M:%S')
        else:
            timestamp = datetime.utcnow().strftime('%H:%M:%S')
        self.solution_history.appendleft((timestamp, solution))
        timestamp, _ = self.solution_history[0]
        self._prepend_history_row(timestamp, solution)

    def _flush_pending_solution(self, now: float | None = None):
        if self.pending_solution is None:
            return
        solution = self.pending_solution
        self.pending_solution = None
        self._apply_solution_to_ui(solution)
        self.last_solution_ui_time = time.time() if now is None else now

    @Slot(str)
    def update_stream_status(self, stream_name: str, connected: bool):
        """Update stream status indicator."""
        display_name = {
            'EPH_DATA': 'EPH',
            'SSR_DATA': 'SSR',
        }.get(stream_name, stream_name)
        if display_name == 'BASE' and self.combo_mode.currentIndex() != 2:
            return
        if display_name == 'SSR' and self.combo_mode.currentIndex() == 2:
            return
        label_map = {
            'OBS': self.lbl_obs_status,
            'EPH': self.lbl_eph_status,
            'SSR': self.lbl_ssr_status,
            'BASE': self.lbl_ssr_status,
        }
        label = label_map.get(display_name)
        if label is None:
            return
        color = "#2A692D" if connected else "#6D2F2B"
        state = "ON" if connected else "OFF"
        self._set_status_badge(label, f"{display_name}: {state}", color)

    @Slot(str, bool)
    def update_positioning_status(self, status_name: str, active: bool):
        """Update positioning status indicator."""
        if active:
            if self.lbl_pos_status.text() == "POS: IDLE":
                self._set_status_badge(self.lbl_pos_status, "POS: ACTIVE", "#2563EB")
        else:
            self._set_status_badge(self.lbl_pos_status, "POS: IDLE", "#4B5563")
            if status_name == "RTK" and self.is_running and not self.is_stopping:
                self.is_running = False
                self.btn_start.setStyleSheet("")
                self._refresh_start_button_text()

    @Slot()
    def update_ui(self):
        """Update UI elements (timer-based)."""
        self._flush_log_display()
        now = time.time()
        if self.pending_solution is not None:
            if self.solution_ui_interval <= 0.0 or now - self.last_solution_ui_time >= self.solution_ui_interval:
                self._flush_pending_solution(now)

    @Slot(str)
    def append_log(self, message: str):
        """Append message to log."""
        timestamp = datetime.now().strftime('%H:%M:%S')
        log_msg = f"[{timestamp}] {message}"
        self.log_queue.append(log_msg)
        self._pending_log_lines.append(log_msg)
        self._log_dirty = True

    def _flush_log_display(self):
        if not self._log_dirty or not self._pending_log_lines:
            return
        scrollbar = self.log_area.verticalScrollBar()
        cursor = self.log_area.textCursor()
        browsing = cursor.hasSelection() or scrollbar.value() < scrollbar.maximum()
        if self._log_paused or browsing:
            self.lbl_log_state.setText(
                f"Paused - {len(self._pending_log_lines)} buffered"
                if self._log_paused else f"Browsing - {len(self._pending_log_lines)} buffered"
            )
            return

        batch = "\n".join(self._pending_log_lines)
        self._pending_log_lines.clear()
        self.log_area.appendPlainText(batch)
        scrollbar.setValue(scrollbar.maximum())
        self._log_dirty = False
        self.lbl_log_state.setText("Live")

    def _on_log_pause_toggled(self, paused):
        self._log_paused = bool(paused)
        self.btn_pause_log.setText("Resume" if paused else "Pause")
        self.lbl_log_state.setText("Paused" if paused else "Live")

    def clear_log(self):
        self.log_queue.clear()
        self._pending_log_lines.clear()
        self._log_dirty = False
        self.log_area.clear()
        self.lbl_log_state.setText("Paused" if self._log_paused else "Live")

    def _on_detail_tab_changed(self, index):
        self.residual_widget.set_render_enabled(index == 1)

    def _on_monitor_tab_changed(self, index):
        self.accuracy_widget.set_render_enabled(index == 0)
        self.atmosphere_widget.set_render_enabled(index == 1)

    def _apply_replay_ui_policy(self, announce: bool) -> None:
        previous_interval = getattr(self, "solution_ui_interval", self.base_solution_ui_interval)
        throttled_interval = choose_gui_refresh_interval(
            self.base_solution_ui_interval,
            self.settings.get("OBS", {}),
        )
        self.solution_ui_interval = max(0.0, throttled_interval)

        if not announce:
            return

        if abs(self.solution_ui_interval - previous_interval) < 1e-9:
            return

        if self.solution_ui_interval >= THROTTLED_GUI_INTERVAL_SECONDS:
            effective_period = estimate_effective_replay_period_seconds(self.settings.get("OBS", {}))
            if effective_period and effective_period > 0.0:
                self.append_log(
                    f"High-rate RINEX replay detected, positioning GUI refresh capped at "
                    f"{self.solution_ui_interval:.1f}s (effective epoch period {effective_period:.3f}s)"
                )
            else:
                self.append_log(
                    f"High-rate RINEX replay detected, positioning GUI refresh capped at "
                    f"{self.solution_ui_interval:.1f}s"
                )
        else:
            self.append_log(
                f"Positioning GUI refresh restored to {self.solution_ui_interval:.2f}s cadence"
            )

    def on_back_to_launcher(self):
        """Return to launcher."""
        self.stop_positioning()
        self.back_to_launcher.emit()
        self.close()

    def closeEvent(self, event):
        """Clean up on window close."""
        self.stop_positioning()
        self.update_timer.stop()
        event.accept()

    def apply_stylesheet(self):
        """Apply application stylesheet."""
        self.setStyleSheet(get_app_stylesheet(self._compact_scale or 1.0))
