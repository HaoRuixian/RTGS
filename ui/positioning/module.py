"""
GNSS RT Monitor - Positioning Module

Provides real-time GNSS positioning using pseudorange observations.
Supports multiple positioning modes: SPP (currently), PPP, RTK (future).

Architecture:
- Uses shared IOThread/DataProcessingThread from monitoring module for observations
- Own PositioningThread for SPP/PPP/RTK computation
- Real-time visualization of position, accuracy, and diagnostics
"""

import threading
import time
import math
from datetime import datetime
from collections import deque

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QFrame, 
    QSplitter, QStyle, QComboBox, QCheckBox, QTextEdit, QSpinBox,
    QDoubleSpinBox, QDialog
)
from PySide6.QtCore import Qt, Slot, QTimer, Signal
from PySide6.QtGui import QColor, QFont

from ui.positioning.workers import PositioningThread, PositioningSignals
from ui.positioning.widgets import (
    PositionMapWidget, PositionInfoWidget, AccuracyWidget, ResidualWidget,
    format_solution_status,
)
from ui.monitoring.workers import IOThread, DataProcessingThread, RinexReplayThread, StreamSignals
from ui.shared.config_dialog import ConfigDialog
from ui.positioning.positioning_config_dialog import PositioningConfigDialog
from ui.style import get_app_stylesheet, ui_scale_for_width
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
import numpy as np


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
        
        # Ring buffer for positioning epochs
        self.positioning_ring_buffer = RingBuffer(maxsize=200)
        
        self.positioning_thread = PositioningThread(
            "SPP", self.positioning_signals, self.positioning_ring_buffer, self.rtcm_handler
        )
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
            }
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
        self.is_running = False
        self.base_solution_ui_interval = 0.0
        self.solution_ui_interval = self.base_solution_ui_interval
        self.last_solution_ui_time = 0.0
        self.pending_solution = None
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_ui)
        self.update_timer.start(100)  # Update UI every 100ms
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
        top_bar = QHBoxLayout()
        
        # Back button
        self.btn_back = QPushButton("< Back to Launcher")
        self.btn_back.setMaximumWidth(200)
        self.btn_back.clicked.connect(self.on_back_to_launcher)
        top_bar.addWidget(self.btn_back)
        
        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        top_bar.addWidget(line)
        
        # Mode selector
        self.lbl_mode = QLabel("Positioning Mode:")
        top_bar.addWidget(self.lbl_mode)
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["SPP (Single Point Positioning)", "PPP (Precise Point) [TBD]", "RTK (Real-Time) [TBD]"])
        self.combo_mode.setCurrentIndex(0)
        self.combo_mode.currentIndexChanged.connect(self.on_mode_changed)
        self.combo_mode.setMaximumWidth(300)
        top_bar.addWidget(self.combo_mode)
        
        # Config button
        self.btn_config = QPushButton("Config")
        self.btn_config.setMaximumWidth(100)
        self.btn_config.clicked.connect(self.open_config_dialog)
        top_bar.addWidget(self.btn_config)

        # Positioning settings button
        self.btn_pos_settings = QPushButton("Pos Settings")
        self.btn_pos_settings.setMaximumWidth(140)
        self.btn_pos_settings.clicked.connect(self.open_positioning_settings_dialog)
        top_bar.addWidget(self.btn_pos_settings)

        self.lbl_coord_mode = QLabel("Display:")
        top_bar.addWidget(self.lbl_coord_mode)
        self.combo_coord_mode = QComboBox()
        self.combo_coord_mode.addItem("Lat/Lon/H", "LLH")
        self.combo_coord_mode.addItem("ECEF XYZ", "XYZ")
        self.combo_coord_mode.setMaximumWidth(150)
        self.combo_coord_mode.currentIndexChanged.connect(self.on_coordinate_mode_changed)
        top_bar.addWidget(self.combo_coord_mode)
        
        # Start/Stop button
        self.btn_start = QPushButton("Start Positioning")
        self.btn_start.setMaximumWidth(150)
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
        main_layout.addLayout(top_bar)
        
        # ======================================================================
        # Main content area
        # ======================================================================
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left panel: controls and info
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        
        # Position info
        left_layout.addWidget(QLabel("<b>Current Position</b>"))
        self.info_widget = PositionInfoWidget()
        left_layout.addWidget(self.info_widget)
        
        # Map
        left_layout.addWidget(QLabel("<b>Position Track</b>"))
        self.map_widget = PositionMapWidget()
        self.map_widget.setMinimumHeight(400)
        left_layout.addWidget(self.map_widget)
        
        splitter.addWidget(left_panel)
        
        # Right panel: analysis
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        
        # Tabs for different views
        self.right_tabs = QTabWidget()
        
        # Tab 1: Accuracy (DOP)
        self.accuracy_widget = AccuracyWidget()
        self.right_tabs.addTab(self.accuracy_widget, "DOP/Accuracy")
        
        # Tab 2: Residuals
        self.residual_widget = ResidualWidget()
        self.right_tabs.addTab(self.residual_widget, "Residuals")
        
        # Tab 3: Position history
        self.history_table = QTableWidget()
        self._configure_history_table()
        self.history_table.setAlternatingRowColors(True)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.right_tabs.addTab(self.history_table, "History")
        
        right_layout.addWidget(self.right_tabs)
        right_layout.addWidget(QLabel("<b>System Log</b>"))
        
        # Log area
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMaximumHeight(150)
        self.log_area.setStyleSheet(
            "background: #ffffff; color: #000000; "
            "font-family: Monospace; border: 1px solid #ccc;"
        )
        right_layout.addWidget(self.log_area)
        
        splitter.addWidget(right_panel)
        splitter.setSizes([600, 1000])
        
        main_layout.addWidget(splitter, stretch=1)
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
        self.map_widget.setMinimumHeight(max(280, int(400 * scale)))
        self.log_area.setMaximumHeight(max(110, int(150 * scale)))
        self.btn_back.setText("< Back to Launcher")
        self.btn_pos_settings.setText("Pos Settings")
        self.lbl_mode.setText("Positioning Mode:")
        self.lbl_coord_mode.setText("Display:")
        self._refresh_start_button_text()

    def _refresh_start_button_text(self):
        if getattr(self, "is_running", False):
            self.btn_start.setText("Stop Positioning")
        else:
            self.btn_start.setText("Start Positioning")

    def _set_status_badge(self, label: QLabel, text: str, color: str) -> None:
        label.setText(text)
        label.setStyleSheet(
            f"background-color: {color}; color: white; padding: 4px 8px; "
            "border-radius: 4px; font-weight: bold;"
        )

    def _configure_history_table(self) -> None:
        self.history_table.setColumnCount(7)
        if self.display_mode == "XYZ":
            headers = ["Time", "ECEF X (m)", "ECEF Y (m)", "ECEF Z (m)", "HDOP", "Sats", "Status"]
        else:
            headers = ["Time", "Lat (deg)", "Lon (deg)", "Height (m)", "HDOP", "Sats", "Status"]
        self.history_table.setHorizontalHeaderLabels(headers)

    def _refresh_history_table(self) -> None:
        if not hasattr(self, "history_table"):
            return
        self._configure_history_table()
        self.history_table.setRowCount(0)

        for row, (timestamp, solution) in enumerate(self.solution_history):
            self.history_table.insertRow(row)
            if self.display_mode == "XYZ":
                values = [
                    timestamp,
                    f"{solution.ecef_x:.3f}",
                    f"{solution.ecef_y:.3f}",
                    f"{solution.ecef_z:.3f}",
                    f"{solution.hdop:.2f}",
                    str(solution.num_satellites),
                    format_solution_status(solution.status),
                ]
            else:
                values = [
                    timestamp,
                    f"{solution.latitude:.8f}",
                    f"{solution.longitude:.8f}",
                    f"{solution.height:.3f}",
                    f"{solution.hdop:.2f}",
                    str(solution.num_satellites),
                    format_solution_status(solution.status),
                ]

            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFont(QFont("Consolas", 9))
                if col == 6:
                    self._style_status_item(item, solution.status)
                self.history_table.setItem(row, col, item)

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
            self._apply_replay_ui_policy(announce=True)
            self.append_log("Settings updated")
            if getattr(dlg, 'disconnect_requested', False):
                self.append_log("Disconnect requested: stopping positioning and data streams")
                self.stop_positioning()
                return
            # If user requested Connect from the dialog, start streams only (do not start positioning)
            if getattr(dlg, 'auto_connect', False):
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
        if not self.is_running:
            self.start_positioning()
        else:
            self.stop_positioning()

    def start_positioning(self):
        """Start all threads."""
        try:
            self._reset_solution_views()

            # Ensure streams are running (start streams only if not present)
            self.start_streams()

            # Create fresh positioning ring buffer
            self.positioning_ring_buffer = RingBuffer(maxsize=200)
            if (
                self.positioning_thread is None
                or (not self.positioning_thread.is_alive() and getattr(self.positioning_thread, "ident", None) is not None)
            ):
                self.positioning_thread = PositioningThread(
                    "SPP", self.positioning_signals, self.positioning_ring_buffer, self.rtcm_handler
                )
                modes = [PositioningMode.SPP, PositioningMode.PPP, PositioningMode.RTK]
                mode_index = min(self.combo_mode.currentIndex(), len(modes) - 1)
                self.positioning_thread.set_mode(modes[mode_index])
            else:
                self.positioning_thread.set_ring_buffer(self.positioning_ring_buffer)

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
        """Stop all threads."""
        try:
            # Stop positioning thread (will close its ring buffer)
            try:
                self.positioning_thread.stop()
            except Exception:
                pass

            # Stop processing threads
            for thread in list(self.processing_threads):
                try:
                    thread.stop()
                    thread.join(timeout=2)
                except Exception:
                    pass

            # Stop IO threads
            for thread in list(self.io_threads):
                try:
                    thread.stop()
                    thread.join(timeout=2)
                except Exception:
                    pass

            # Close buffers
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

            self.is_running = False
            self._refresh_start_button_text()
            self.btn_start.setStyleSheet("")
            self._reset_solution_views()
            self.append_log("Positioning stopped")
            
        except Exception as e:
            self.append_log(f"Error stopping positioning: {str(e)}")

    @Slot(object)
    def on_observation_epoch(self, epoch_obs):
        """Receive observation epoch from monitoring and forward to positioning."""
        if epoch_obs is None:
            return
        if getattr(epoch_obs, "utc_datetime", None) is None:
            return
        if not getattr(epoch_obs, "satellites", None):
            return
        # Submit to positioning ring buffer
        self.positioning_ring_buffer.put(epoch_obs, block=False)

    @Slot(object)
    def on_positioning_solution(self, solution):
        """Receive positioning solution."""
        self.pending_solution = solution
        now = time.time()
        if self.solution_ui_interval <= 0.0 or now - self.last_solution_ui_time >= self.solution_ui_interval:
            self._flush_pending_solution(now)

    def _apply_solution_to_ui(self, solution):
        """Render one positioning solution onto the UI."""
        self.info_widget.update_solution(solution)
        self.accuracy_widget.update_solution(solution)
        self.residual_widget.update_solution(solution)
        self._update_solution_badge(solution.status)
        if solution.status != SolutionStatus.NO_FIX:
            self.map_widget.update_solution(solution)

        self.solution_history.appendleft((datetime.utcnow().strftime('%H:%M:%S'), solution))
        self._refresh_history_table()

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
        label_map = {
            'OBS': self.lbl_obs_status,
            'EPH': self.lbl_eph_status,
            'SSR': self.lbl_ssr_status,
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

    @Slot()
    def update_ui(self):
        """Update UI elements (timer-based)."""
        # Refresh log display
        log_text = '\n'.join(list(self.log_queue))
        self.log_area.setPlainText(log_text)
        self.log_area.verticalScrollBar().setValue(
            self.log_area.verticalScrollBar().maximum()
        )
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

    def _apply_replay_ui_policy(self, announce: bool) -> None:
        previous_interval = getattr(self, "solution_ui_interval", self.base_solution_ui_interval)
        throttled_interval = choose_gui_refresh_interval(
            self.base_solution_ui_interval,
            self.settings.get("OBS", {}),
        )
        self.solution_ui_interval = throttled_interval if throttled_interval >= THROTTLED_GUI_INTERVAL_SECONDS else 0.0

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
            self.append_log("Positioning GUI refresh restored to per-solution updates")

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
