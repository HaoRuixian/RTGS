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
    PositionMapWidget, PositionInfoWidget, AccuracyWidget, ResidualWidget
)
from ui.monitoring.workers import IOThread, DataProcessingThread, StreamSignals
from ui.ConfigDialog import ConfigDialog
from ui.positioning.positioning_config_dialog import PositioningConfigDialog
from ui.style import get_app_stylesheet
from core.ring_buffer import RingBuffer
from core.rtcm_handler import RTCMHandler, get_shared_handler
from core.positioning_models import PositioningMode
from core.global_config import get_global_config
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
        self.resize(1600, 1000)
        
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
                'baudrate': 115200
            },
            'EPH_ENABLED': False,
            'EPH': {
                'source': 'NTRIP Server',
                'host': '',
                'port': 2101,
                'mountpoint': '',
                'user': '',
                'password': '',
                'baudrate': 115200
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
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_ui)
        self.update_timer.start(100)  # Update UI every 100ms
        
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
        btn_back = QPushButton("< Back to Launcher")
        btn_back.setMaximumWidth(200)
        btn_back.clicked.connect(self.on_back_to_launcher)
        top_bar.addWidget(btn_back)
        
        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        top_bar.addWidget(line)
        
        # Mode selector
        top_bar.addWidget(QLabel("Positioning Mode:"))
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["SPP (Single Point Positioning)", "PPP (Precise Point) [TBD]", "RTK (Real-Time) [TBD]"])
        self.combo_mode.setCurrentIndex(0)
        self.combo_mode.currentIndexChanged.connect(self.on_mode_changed)
        self.combo_mode.setMaximumWidth(300)
        top_bar.addWidget(self.combo_mode)
        
        # Config button
        btn_config = QPushButton("Config")
        btn_config.setMaximumWidth(100)
        btn_config.clicked.connect(self.open_config_dialog)
        top_bar.addWidget(btn_config)

        # Positioning settings button
        btn_pos_settings = QPushButton("Pos Settings")
        btn_pos_settings.setMaximumWidth(140)
        btn_pos_settings.clicked.connect(self.open_positioning_settings_dialog)
        top_bar.addWidget(btn_pos_settings)
        
        # Start/Stop button
        self.btn_start = QPushButton("Start Positioning")
        self.btn_start.setMaximumWidth(150)
        self.btn_start.setObjectName("PrimaryButton")
        self.btn_start.clicked.connect(self.toggle_positioning)
        top_bar.addWidget(self.btn_start)
        
        # Status indicators
        top_bar.addStretch()
        self.lbl_obs_status = QLabel("OBS: OFF")
        self.lbl_obs_status.setStyleSheet("background: #ddd; padding: 4px 8px; border-radius: 4px;")
        top_bar.addWidget(self.lbl_obs_status)
        
        self.lbl_pos_status = QLabel("POS: IDLE")
        self.lbl_pos_status.setStyleSheet("background: #ddd; padding: 4px 8px; border-radius: 4px;")
        top_bar.addWidget(self.lbl_pos_status)
        
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
        self.history_table.setColumnCount(7)
        self.history_table.setHorizontalHeaderLabels([
            "Time", "Lat (°)", "Lon (°)", "Height (m)", 
            "HDOP", "Sats", "Status"
        ])
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

    def open_config_dialog(self):
        """Open stream configuration dialog."""
        # Create a simple config dialog (same as monitoring module)
        from ui.ConfigDialog import ConfigDialog
        dlg = ConfigDialog(self, self.settings)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.settings = dlg.get_settings()
            self.append_log("Settings updated")
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

    def open_positioning_settings_dialog(self):
        """Open dialog to configure positioning (SPP) parameters."""
        dlg = PositioningConfigDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            params = dlg.get_settings()
            # Apply to positioning thread and positioner
            self.append_log("Positioning settings updated")
            # Update min satellites and elevation
            min_sats = params.get('min_satellites', None)
            min_el = params.get('cutoff_elevation_deg', None)
            if min_sats is not None or min_el is not None:
                self.positioning_thread.set_parameters(min_satellites=min_sats, min_elevation=min_el)
            # Update weight mode
            weight = params.get('weight_mode', None)
            if weight and hasattr(self.positioning_thread.positioner, 'WEIGHT_MODE'):
                self.positioning_thread.positioner.WEIGHT_MODE = weight

    def toggle_positioning(self):
        """Start/stop positioning."""
        if not self.is_running:
            self.start_positioning()
        else:
            self.stop_positioning()

    def start_positioning(self):
        """Start all threads."""
        try:
            # Ensure streams are running (start streams only if not present)
            self.start_streams()

            # Create fresh positioning ring buffer
            self.positioning_ring_buffer = RingBuffer(maxsize=200)
            self.positioning_thread.set_ring_buffer(self.positioning_ring_buffer)

            # Start positioning thread if not already running
            if not getattr(self.positioning_thread, 'is_alive', lambda: False)():
                self.positioning_thread.start()

            self.is_running = True
            self.btn_start.setText("Stop Positioning")
            self.btn_start.setStyleSheet("background: #ff6666;")
            self.append_log("Positioning started")
            
        except Exception as e:
            self.append_log(f"Error starting positioning: {str(e)}")
            self.is_running = False

    def start_streams(self):
        """Start IO and DataProcessing threads only (do not start positioning)."""
        # Validate configuration minimal requirements
        if not self.settings.get('OBS', {}).get('host') and self.settings.get('OBS', {}).get('source') == 'NTRIP Server':
            raise RuntimeError("Missing OBS NTRIP host configuration")

        # Initialize buffers only if not already present
        if 'OBS' not in self.ring_buffers:
            self.ring_buffers['OBS'] = RingBuffer(maxsize=1000)

            # Start IOThread for OBS
            io_thread_obs = IOThread(
                'OBS', self.settings['OBS'],
                self.ring_buffers['OBS'],
                self.observer_signals
            )
            io_thread_obs.start()
            self.io_threads.append(io_thread_obs)

            # Start DataProcessingThread for OBS
            proc_thread_obs = DataProcessingThread(
                'OBS', self.ring_buffers['OBS'],
                self.rtcm_handler, self.observer_signals
            )
            proc_thread_obs.start()
            self.processing_threads.append(proc_thread_obs)

        # EPH stream
        if self.settings.get('EPH_ENABLED') and 'EPH' not in self.ring_buffers:
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

            self.is_running = False
            self.btn_start.setText("Start Positioning")
            self.btn_start.setStyleSheet("")
            self.append_log("Positioning stopped")
            
        except Exception as e:
            self.append_log(f"Error stopping positioning: {str(e)}")

    @Slot(object)
    def on_observation_epoch(self, epoch_obs):
        """Receive observation epoch from monitoring and forward to positioning."""
        # Submit to positioning ring buffer
        self.positioning_ring_buffer.put(epoch_obs, block=False)

    @Slot(object)
    def on_positioning_solution(self, solution):
        """Receive positioning solution."""
        # Update UI
        self.info_widget.update_solution(solution)
        self.accuracy_widget.update_solution(solution)
        self.residual_widget.update_solution(solution)
        self.map_widget.update_track(solution.latitude, solution.longitude, solution.hdop)
        
        # Add to history
        row = self.history_table.rowCount()
        self.history_table.insertRow(0)  # Insert at top
        
        items = [
            QTableWidgetItem(datetime.utcnow().strftime('%H:%M:%S')),
            QTableWidgetItem(f"{solution.latitude:.6f}"),
            QTableWidgetItem(f"{solution.longitude:.6f}"),
            QTableWidgetItem(f"{solution.height:.2f}"),
            QTableWidgetItem(f"{solution.hdop:.2f}"),
            QTableWidgetItem(str(solution.num_satellites)),
            QTableWidgetItem(solution.status.value),
        ]
        
        for col, item in enumerate(items):
            item.setFont(QFont("Courier", 9))
            
            # Color code status
            if col == 6:  # Status column
                if "Fixed" in item.text():
                    item.setForeground(QColor("green"))
                elif "Uncertain" in item.text():
                    item.setForeground(QColor("orange"))
                else:
                    item.setForeground(QColor("red"))
            
            self.history_table.setItem(0, col, item)
        
        # Keep only last 100 rows
        while self.history_table.rowCount() > 100:
            self.history_table.removeRow(self.history_table.rowCount() - 1)

    @Slot(str)
    def update_stream_status(self, stream_name: str, connected: bool):
        """Update stream status indicator."""
        if stream_name == 'OBS':
            if connected:
                self.lbl_obs_status.setText("OBS: ON")
                self.lbl_obs_status.setStyleSheet("background: #66ff66; padding: 4px 8px; border-radius: 4px;")
            else:
                self.lbl_obs_status.setText("OBS: OFF")
                self.lbl_obs_status.setStyleSheet("background: #ddd; padding: 4px 8px; border-radius: 4px;")

    @Slot(str, bool)
    def update_positioning_status(self, status_name: str, active: bool):
        """Update positioning status indicator."""
        if active:
            self.lbl_pos_status.setText("POS: ACTIVE")
            self.lbl_pos_status.setStyleSheet("background: #66ff66; padding: 4px 8px; border-radius: 4px;")
        else:
            self.lbl_pos_status.setText("POS: IDLE")
            self.lbl_pos_status.setStyleSheet("background: #ddd; padding: 4px 8px; border-radius: 4px;")

    @Slot()
    def update_ui(self):
        """Update UI elements (timer-based)."""
        # Refresh log display
        log_text = '\n'.join(list(self.log_queue))
        self.log_area.setPlainText(log_text)
        self.log_area.verticalScrollBar().setValue(
            self.log_area.verticalScrollBar().maximum()
        )

    @Slot(str)
    def append_log(self, message: str):
        """Append message to log."""
        timestamp = datetime.now().strftime('%H:%M:%S')
        log_msg = f"[{timestamp}] {message}"
        self.log_queue.append(log_msg)

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
        self.setStyleSheet(get_app_stylesheet())