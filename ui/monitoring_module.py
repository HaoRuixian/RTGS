"""
GNSS RT Monitoring Module - Real-time satellite observation visualization and quality monitoring.

This module provides the main UI and data orchestration for real-time GNSS monitoring.
It coordinates multiple background threads (IOThread, DataProcessingThread, LoggingThread),
manages ring buffers for inter-thread communication, and updates visualization widgets
(skyplot, SNR charts, satellite statistics) with live observation data.

Threading model:
  - UI Thread (main): Updates widgets, handles user input
  - IOThread: Receives RTCM messages (one per stream)
  - DataProcessingThread: Parses RTCM (one per stream)
  - LoggingThread: Records observations (started on demand)
  - Cleanup Timer: Removes stale satellites every 1 second
  - GUI Update Timer: Throttles refresh every 60 seconds

Signal flow:
  NTRIP → IOThread → ring_buffer → DataProcessingThread → merged_satellites 
       → epoch_signal → process_gui_epoch() → refresh_all_widgets()
"""

import time
import threading
from datetime import datetime
from collections import deque, defaultdict
import numpy as np

from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QTableWidget, QTableWidgetItem, QLabel, QTextEdit, 
                             QSplitter, QHeaderView, QTabWidget, QComboBox,
                             QCheckBox, QPushButton, QFrame, QApplication, QDialog, QStyle,
                             QFileDialog, QDialogButtonBox, QSpinBox, QListWidget)
from PySide6.QtCore import Qt, Slot, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.dates as mdates

from ui.gnss_colordef import get_sys_color, get_signal_color
from ui.monitoring.workers import IOThread, DataProcessingThread, StreamSignals, LoggingThread
from ui.monitoring.log_settings import LogSettingsDialog
from core.rtcm_handler import RTCMHandler
from core.ring_buffer import RingBuffer
from core.global_config import get_global_config
from ui.monitoring.widgets import SkyplotWidget, MultiSignalBarWidget, PlotSNRWidget, SatelliteNumWidget
from ui.ConfigDialog import ConfigDialog
from ui.style import get_app_stylesheet
import csv


class MonitoringModule(QMainWindow):

    back_to_launcher = Signal()
    
    def __init__(self):
        """
        Initialize MonitoringModule window.
        
        Procedure:
        1. Set up main window properties (title, size)
        2. Initialize data containers: merged_satellites, history buffers, active systems filter
        3. Configure GUI update throttling (limit refresh rate to 3-5 updates per second)
        4. Load GNSS system configuration from config.py (target systems)
        5. Create Qt signal/slot connections for thread communication
        6. Initialize ring buffers for inter-thread communication
        7. Build UI layout (setup_ui)
        8. Start background cleanup and GUI update timers
        """
        super().__init__()
        self.setWindowTitle("GNSS RT Monitoring Module")
        self.resize(1800, 1000)
        
        # Step 1: Initialize satellite data containers
        # merged_satellites: {prn_str: SatelliteState} - current epoch data from all threads
        self.merged_satellites = {}
        # sat_last_seen: {prn_str: timestamp} - track stale satellites for cleanup
        self.sat_last_seen = {}

        # sat_history: {prn_str: deque(maxlen=500)} - historical SNR/elevation for analysis tab
        # Each entry: {'time': datetime, 'el': elevation_deg, 'snr': {code: snr_value}}
        self.sat_history = defaultdict(lambda: deque(maxlen=500))
        self.current_sat_list = []  # Dropdown list for analysis tab selection
        
        # Step 2: Configure GUI update throttling to prevent excessive redrawing
        # Target: 3-5 updates per second (0.3s interval) for responsive but smooth rendering
        self.last_gui_update_time = 0
        self.gui_update_interval = 0.3  # Minimum interval between full widget refreshes (seconds)
        self.pending_update = False     # Flag: GUI refresh requested but throttled
        self.current_tab_index = 0      # Track visible tab to skip updates for hidden tabs
        self.last_table_data_hash = None  # Hash of table data to detect actual changes
        
        # Step 3: Load active GNSS systems from configuration
        # DEFAULT: G(GPS), R(GLONASS), E(Galileo), C(BeiDou), J(QZSS), S(SBAS)
        config = get_global_config()
        self.active_systems = set(config.target_systems) if config.target_systems else {'G', 'R', 'E', 'C', 'J', 'S'}
        
        # Step 4: Create Qt signal/slot connections for thread communication
        # Signals emitted by IOThread and DataProcessingThread in workers.py
        self.signals = StreamSignals()
        self.signals.log_signal.connect(self.append_log)       # Thread → UI: log messages
        self.signals.epoch_signal.connect(self.process_gui_epoch)  # Thread → UI: new epoch data
        self.signals.status_signal.connect(self.update_status)  # Thread → UI: connection status
        
        # Step 5: Initialize thread management structures
        # io_threads: list of IOThread (one per stream, receives RTCM from NTRIP)
        # processing_threads: list of DataProcessingThread (one per stream, parses RTCM)
        # ring_buffers: communication queues between IOThread → DataProcessingThread
        # logging_buffers: independent high-capacity buffers for LoggingThread
        self.io_threads = []
        self.processing_threads = []
        self.ring_buffers = {}  # {'OBS': RingBuffer, 'EPH': RingBuffer, ...}
        self.logging_buffers = {}  # {'OBS': RingBuffer(maxsize=5000), 'EPH': RingBuffer(...)}
        self.logging_buffer_ref = None  # Active logging buffer reference
        
        # Step 6: Set default stream configuration (will be overridden by ConfigDialog)
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
        # Logging configuration: format, directory, rotation, sampling
        self.logging_settings = {
            'enabled': False,
            'directory': '',
            'split_minutes': 60,
            'sample_interval': 1,
            'format': 'csv',
            'fields': ["PRN", "Sys", "El(°)", "Az(°)", "Freq", "SNR", "Pseudorange (m)", "Phase (cyc)"]
        }
        self.logging_active = False
        self.logging_thread = None
        
        # Step 7: Build UI layout
        self.setup_ui()
        
        # Step 8: Start background maintenance timers
        # Cleanup timer: every 2 seconds, remove satellites not updated for > 5 seconds
        # This prevents accumulation of stale data and releases memory
        self.cleanup_timer = threading.Timer(1.0, self.cleanup_stale_satellites)
        self.cleanup_timer.daemon = True
        self.cleanup_timer.start()
        
        # GUI update timer: every 50ms check if pending GUI update is needed
        # Implements throttling: only refresh if enough time has passed since last update
        self.gui_update_timer = QTimer()
        self.gui_update_timer.timeout.connect(self._check_pending_update)
        self.gui_update_timer.start(50)  # Check every 50ms for pending updates

        # Initial status message
        self.signals.log_signal.emit("=== GNSS RT Monitor Started ===")
        self.signals.log_signal.emit("Ready. Please configure streams via Config button.")

    def setup_ui(self):
        """
        Build and initialize the main UI layout.

        Layout overview:
        - Top control bar (navigation, config, system filters, status)
        - Main splitter:
            * Left: skyplot + satellite statistics
            * Right: tab widget (dashboard + analysis)
        - Bottom: log output area
        """

        # === Global style ===
        self.setStyleSheet(get_app_stylesheet())

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # ======================================================================
        # Top control bar
        # ======================================================================
        top_bar = QHBoxLayout()

        # Back to launcher
        btn_back = QPushButton("< Back to Launcher")
        btn_back.setMaximumWidth(400)
        btn_back.clicked.connect(self.on_back_to_launcher)
        top_bar.addWidget(btn_back)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        top_bar.addWidget(line)

        # Config button (with fallback icon)
        btn_cfg = QPushButton("Config")
        try:
            settings_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogInfoView)
            if settings_icon.isNull():
                settings_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
            if not settings_icon.isNull():
                btn_cfg.setIcon(settings_icon)
        except Exception:
            pass
        btn_cfg.clicked.connect(self.open_config_dialog)
        top_bar.addWidget(btn_cfg)

        # Logging settings
        self.btn_logging = QPushButton("Logging")
        self.btn_logging.clicked.connect(self.open_log_settings_dialog)
        top_bar.addWidget(self.btn_logging)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        top_bar.addWidget(line)

        # GNSS system filters
        top_bar.addWidget(QLabel("Systems:"))
        self.chk_sys = {}
        for sys_char, name in [
            ('G', 'GPS'), ('R', 'GLONASS'), ('E', 'Galileo'),
            ('C', 'BeiDou'), ('J', 'QZSS'), ('S', 'SBAS')
        ]:
            chk = QCheckBox(name)
            chk.setChecked(sys_char in self.active_systems)
            chk.stateChanged.connect(self.on_filter_changed)
            chk.setStyleSheet(
                f"QCheckBox {{ color: {get_sys_color(sys_char)}; font-weight: bold; }}"
            )
            self.chk_sys[sys_char] = chk
            top_bar.addWidget(chk)

        top_bar.addStretch()

        # Data stream status indicators
        self.lbl_status_obs = QLabel("OBS: OFF")
        self.lbl_status_eph = QLabel("EPH: OFF")
        for lbl in (self.lbl_status_obs, self.lbl_status_eph):
            lbl.setProperty("class", "status")
            lbl.setStyleSheet(
                "background-color: #ddd; padding: 4px 8px; border-radius: 4px;"
            )
            top_bar.addWidget(lbl)

        layout.addLayout(top_bar)

        # ======================================================================
        # Main content area (horizontal splitter)
        # ======================================================================
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ----------------------------------------------------------------------
        # Left panel: skyplot + satellite statistics
        # ----------------------------------------------------------------------
        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_splitter.setStyleSheet(
            "QSplitter::handle { background: rgba(250, 250, 250, 0.2); }"
        )

        self.skyplot = SkyplotWidget()
        left_splitter.addWidget(self.skyplot)

        sat_stats_container = QWidget()
        sat_stats_layout = QVBoxLayout(sat_stats_container)
        sat_stats_layout.setContentsMargins(0, 0, 0, 0)
        sat_stats_layout.setSpacing(3)

        self.sat_stats = SatelliteNumWidget()
        sat_stats_layout.addWidget(self.sat_stats)

        left_splitter.addWidget(sat_stats_container)
        left_splitter.setSizes([700, 200])
        left_splitter.setCollapsible(0, False)
        left_splitter.setCollapsible(1, False)

        splitter.addWidget(left_splitter)

        # ----------------------------------------------------------------------
        # Right panel: main tabs
        # ----------------------------------------------------------------------
        self.main_tabs = QTabWidget()

        # === Tab 1: Dashboard ===
        tab_over = QWidget()
        vbox_over = QVBoxLayout(tab_over)

        # Global SNR overview
        vbox_over.addWidget(QLabel("<b>Multi-Signal SNR Overview</b>"))
        self.bar_chart = MultiSignalBarWidget()
        self.bar_chart.setMinimumHeight(250)
        vbox_over.addWidget(self.bar_chart)

        # Detailed tables (sub-tabs)
        vbox_over.addWidget(QLabel("<b>Detailed</b>"))
        self.sub_tabs = QTabWidget()

        self.table_groups = {
            'ALL': ['G', 'R', 'E', 'C', 'J', 'S'],
            'GPS': ['G'],
            'BeiDou': ['C'],
            'GLONASS': ['R'],
            'Galileo': ['E'],
        }
        self.tables = {}

        headers = [
            "PRN", "Sys", "El(°)", "Az(°)", "Freq",
            "SNR (dBHz)", "Pseudorange (m)", "Phase (cyc)", "Doppler (Hz)"
        ]

        for tab_name in self.table_groups:
            table = QTableWidget()
            table.setColumnCount(len(headers))
            table.setHorizontalHeaderLabels(headers)

            header = table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)

            table.verticalHeader().setVisible(False)

            self.sub_tabs.addTab(table, tab_name)
            self.tables[tab_name] = table

        vbox_over.addWidget(self.sub_tabs)
        self.main_tabs.addTab(tab_over, "Dashboard")

        self.main_tabs.currentChanged.connect(self.on_tab_changed)

        # === Tab 2: SNR Display / Analysis ===
        tab_an = QWidget()
        vbox_an = QVBoxLayout(tab_an)

        h_ctrl = QHBoxLayout()
        h_ctrl.addWidget(QLabel("Target Satellite:"))
        self.combo_sat = QComboBox()
        self.combo_sat.currentTextChanged.connect(self.refresh_analysis_plot)
        h_ctrl.addWidget(self.combo_sat)

        h_ctrl.addWidget(QLabel("Mode:"))
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["Time Sequence", "Elevation"])
        self.combo_mode.currentTextChanged.connect(self.refresh_analysis_plot)
        h_ctrl.addWidget(self.combo_mode)

        h_ctrl.addWidget(QLabel("Signal:"))
        self.combo_sig = QComboBox()
        self.combo_sig.addItem("All")
        self.combo_sig.currentTextChanged.connect(self.refresh_analysis_plot)
        h_ctrl.addWidget(self.combo_sig)
        self._sig_items = ["All"]

        h_ctrl.addStretch()
        vbox_an.addLayout(h_ctrl)

        self.analysis_plot = PlotSNRWidget()
        vbox_an.addWidget(self.analysis_plot)

        self.main_tabs.addTab(tab_an, "SNR Display")

        splitter.addWidget(self.main_tabs)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)
        splitter.setCollapsible(0, False)

        layout.addWidget(splitter, stretch=1)

        # ======================================================================
        # Log output area
        # ======================================================================
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMaximumHeight(80)
        self.log_area.setStyleSheet(
            "background: #ffffff; color: #000000; "
            "font-family: Monospace; border: 1px solid #ccc;"
        )

        # Limit log growth for performance
        self.max_log_lines = 500
        layout.addWidget(self.log_area)


    def on_filter_changed(self):
        self.active_systems = {k for k, chk in self.chk_sys.items() if chk.isChecked()}
        self.refresh_all_widgets()

    def cleanup_stale_satellites(self):
        """
        Periodically remove satellites that have not been updated recently.

        This function runs in a background timer thread and is responsible for:
        - Detecting satellites whose last update exceeds a timeout threshold
        - Cleaning their current state and historical buffers
        - Rescheduling itself for the next cleanup cycle

        Note:
        - No GUI updates are performed here (thread-safety).
        - Intended to prevent stale data accumulation and memory growth.
        """

        now = time.time()

        # ------------------------------------------------------------------
        # Identify satellites exceeding inactivity timeout
        # ------------------------------------------------------------------
        timeout = 5.0  # seconds
        to_remove = [
            prn for prn, last_time in self.sat_last_seen.items()
            if now - last_time > timeout
        ]

        # ------------------------------------------------------------------
        # Remove stale satellites from all tracking containers
        # ------------------------------------------------------------------
        for prn in to_remove:
            self.merged_satellites.pop(prn, None)
            self.sat_last_seen.pop(prn, None)

            # Remove historical time series to free memory
            if prn in self.sat_history:
                del self.sat_history[prn]

        # GUI will refresh naturally on the next data update
        # (do NOT touch widgets from this background thread)

        # ------------------------------------------------------------------
        # Reschedule next cleanup cycle
        # ------------------------------------------------------------------
        self.cleanup_timer = threading.Timer(2.0, self.cleanup_stale_satellites)
        self.cleanup_timer.daemon = True
        self.cleanup_timer.start()


    @Slot(object)
    def process_gui_epoch(self, epoch_data):
        """
        Handle incoming epoch from DataProcessingThread and update UI.
        
        Procedure:
        1. Extract epoch timestamp and satellite count
        2. Merge epoch satellites into merged_satellites dict (maintains current state)
        3. Update satellite history (elevation, SNR time series for analysis tab)
        4. Apply GUI update throttling: only refresh if enough time has elapsed
        5. Log periodic statistics (every 5 seconds)
        
        Thread safety: Runs in UI thread (slot callback), safe to update widgets.
        Throttling: Limits full widget refresh to 3-5 Hz to avoid excessive redrawing.
        """
        now = time.time()
        current_dt = datetime.now()
        n_sats = len(epoch_data.satellites)
        n_signals = sum(len(sat.signals) for sat in epoch_data.satellites.values())

        # Step 1: Merge new epoch data into merged_satellites dictionary
        # This maintains a consistent "current state" of all tracked satellites
        # Each DataProcessingThread emits epochs when it receives all satellites for a time instant
        for prn, sat in epoch_data.satellites.items():
            # Store or update satellite state (includes position, signals, observations)
            self.merged_satellites[prn] = sat
            # Record when this satellite was last seen (for timeout detection)
            self.sat_last_seen[prn] = now
            
            # Step 2: Update historical data for SNR analysis plots
            # Extract elevation and SNR map from satellite observations
            el = getattr(sat, "el", getattr(sat, "elevation", 0)) or None
            # SNR map: {signal_code: snr_value} e.g., {'1C': 38.5, '5Q': 42.0}
            snr_map = {c: s.snr for c, s in sat.signals.items() if s and getattr(s, 'snr', 0)}
            # Append to history deque (maxlen=500 keeps last 500 samples per satellite)
            self.sat_history[prn].append({'time': current_dt, 'el': el, 'snr': snr_map})

        # Step 3: Apply GUI update throttling mechanism
        # Only refresh all widgets if sufficient time has passed since last refresh
        # This prevents excessive redrawing which causes CPU/GPU strain
        if now - self.last_gui_update_time >= self.gui_update_interval:
            # Enough time has passed - perform full widget refresh
            self.refresh_all_widgets()
            self.last_gui_update_time = now
            self.pending_update = False
            
            # Step 4: Periodic statistics logging (every 5 seconds)
            # Helps monitor system performance and data reception
            if not hasattr(self, '_last_stats_log_time'):
                self._last_stats_log_time = now
            if now - self._last_stats_log_time >= 5.0:
                total_sats = len(self.merged_satellites)
                self.signals.log_signal.emit(
                    f"Status: {total_sats} satellites tracked, "
                    f"{n_sats} in epoch, {n_signals} signals"
                )
                self._last_stats_log_time = now
        else:
            # Not enough time has passed - mark for deferred update
            # The GUI update timer will check this flag and refresh when throttle expires
            self.pending_update = True

    def _check_pending_update(self):
        if self.pending_update:
            now = time.time()
            if now - self.last_gui_update_time >= self.gui_update_interval:
                self.refresh_all_widgets()
                self.last_gui_update_time = now
                self.pending_update = False
    
    def on_tab_changed(self, index):
        self.current_tab_index = index
    
    def refresh_all_widgets(self):
        """
        Refresh all visualization widgets with current satellite data.
        
        Procedure:
        1. Create snapshot of merged_satellites dict (thread-safe copy)
        2. Conditionally update widgets based on visible tab
        3. Always update left-side widgets (skyplot, stats) - always visible
        4. Conditionally update tab-specific widgets (only if tab is active)
        5. Avoid redundant updates by checking current tab index
        
        Performance: Skips updates for hidden tabs to reduce CPU usage.
        Thread safety: Creates local dict snapshot to avoid concurrent modification issues.
        """
        # Step 1: Create snapshot of satellite data for thread-safe access
        # This prevents issues if other threads modify merged_satellites during iteration
        satellites_snapshot = dict(self.merged_satellites)
        
        # Step 2: Always update left-side widgets (they are always visible regardless of tab)
        # Left side contains: skyplot, satellite count statistics, multi-signal bar chart
        
        # Update skyplot with current satellite positions and signals
        # Filtered by self.active_systems (checkboxes at top)
        self.skyplot.update_satellites(satellites_snapshot, self.active_systems)
        
        # Update satellite count statistics widget (bottom-left)
        # Shows number of visible satellites per constellation
        self.sat_stats.update_data(satellites_snapshot, self.active_systems)
        
        # Update bar chart (multi-signal SNR overview)
        # Always visible in Dashboard tab and left side
        self.bar_chart.update_data(satellites_snapshot, self.active_systems)
        
        # Step 3: Update tab-specific widgets
        # Only refresh if the corresponding tab is currently active (avoid hidden widget updates)
        
        if self.current_tab_index == 0:
            # Dashboard tab active: update detailed satellite table
            self.update_table()
        
        elif self.current_tab_index == 1:
            # Analysis tab active: update SNR plot if a satellite is selected
            if self.combo_sat.currentText():
                self.refresh_analysis_plot()

    def update_table(self):
        """
        Update satellite observation table with current epoch data.
        
        Procedure:
        1. Create MD5 hash of current table data to detect changes
        2. Skip update if data hasn't changed (optimization)
        3. Populate table rows with satellite signals, applying system filters
        4. Color-code SNR values: green (>40), red (<30), default otherwise
        5. Maintain alternating row backgrounds for readability
        6. Update dropdown list for analysis tab with visible satellites
        
        Performance: Skips redundant updates if data hash unchanged.
        Threading: Snapshot copy for safe concurrent access.
        """
        # Step 1: Create hash of current table data to detect actual changes
        # This allows us to skip expensive table updates when data hasn't changed
        import hashlib
        satellites_snapshot = dict(self.merged_satellites)
        
        # Flatten satellite/signal data into hashable format
        # This captures all parameters that would appear in the table
        flat_rows = []
        for key, sat in sorted(satellites_snapshot.items()):
            el = getattr(sat, "el", getattr(sat, "elevation", 0)) or 0
            az = getattr(sat, "az", getattr(sat, "azimuth", 0)) or 0
            for code, sig in sorted(sat.signals.items()):
                if not sig: 
                    continue
                flat_rows.append((
                    key,
                    round(el, 1),
                    round(az, 1),
                    code,
                    round(getattr(sig, "snr", 0.0) or 0.0, 1),
                    round(getattr(sig, "pseudorange", 0.0) or 0.0, 3),
                    round(getattr(sig, "phase", 0.0) or 0.0, 3),
                ))
        # Compute MD5 hash to detect changes
        data_hash = hashlib.md5(str(flat_rows).encode()).hexdigest()
        
        # Step 2: Skip update if data hasn't changed (first call excepted)
        # This is critical for performance - prevents redrawing on every epoch
        # even if no new/changed signals are received
        if data_hash == self.last_table_data_hash and self.last_table_data_hash is not None:
            return
        
        # Step 3: Data has changed - update hash and rebuild table
        self.last_table_data_hash = data_hash
        
        # Disable widget updates during batch operations for performance
        # This prevents flicker and reduces CPU during table rebuild
        for t in self.tables.values():
            t.setUpdatesEnabled(False)
        
        try:
            # Step 4: Prepare display data and color scheme
            active_prns_in_view = []  # Build list of visible satellites for dropdown
            sys_map = {'G': 'GPS', 'R': 'GLO', 'E': 'GAL', 'C': 'BDS', 'J': 'QZS', 'S': 'SBS'}
            
            # Alternating background colors for row pairs (visual grouping)
            bg_colors = [QColor("#ffffff"), QColor("#b9b9b9")]

            # Step 5: Clear all sub-tables before repopulating
            for t in self.tables.values():
                t.setRowCount(0)

            # Sort satellites by key (PRN) for consistent ordering
            sorted_sats = sorted(satellites_snapshot.items())

            # Step 6: Populate table rows from sorted satellite list
            sat_counter = 0  # Counter for alternating row colors per satellite
            
            for key, sat in sorted_sats:
                sys_char = key[0]  # Extract constellation system from PRN
                
                # Extract position information
                el = getattr(sat, "el", getattr(sat, "elevation", 0)) or 0
                az = getattr(sat, "az", getattr(sat, "azimuth", 0)) or 0
                
                # Determine background color for this satellite's rows
                current_bg = bg_colors[sat_counter % 2]
                sat_counter += 1

                # Iterate through all signals for this satellite
                # Sort signal codes for consistent display (1C, 2W, 5Q, etc)
                sorted_codes = sorted(sat.signals.keys())
                
                # Skip satellites with no valid signals
                if not sorted_codes: 
                    continue
                
                # Flag to prevent duplicate dropdown entries
                added_to_dropdown = False

                # Step 7: Generate one table row per signal code
                # This allows multiple signals from same satellite on separate rows
                for code in sorted_codes:
                    sig = sat.signals[code]
                    if not sig: 
                        continue

                    # Extract observation values
                    snr = getattr(sig, 'snr', 0)
                    if snr == 0: 
                        continue  # Skip invalid/zero SNR signals
                    doppler = getattr(sig, 'doppler', 0)
                    
                    # Get pseudorange and phase (may be None/zero if not available)
                    pr = getattr(sig, 'pseudorange', 0)
                    ph = getattr(sig, 'phase', 0)
                    
                    # Format as strings with appropriate precision
                    pr_str = f"{pr:12.3f}" if pr else ""
                    ph_str = f"{ph:12.3f}" if ph else ""
                    
                    # Step 8: Build row data for this signal
                    row_items = [
                        key,                            # PRN (satellite identifier)
                        sys_map.get(sys_char, sys_char),# System name (GPS, GLO, GAL, etc)
                        f"{el:.1f}",                    # Elevation angle [degrees]
                        f"{az:.1f}",                    # Azimuth angle [degrees]
                        code,                           # Signal code (1C, 5Q, 2W, etc)
                        f"{snr:.1f}",                   # SNR [dB-Hz]
                        pr_str,                         # Pseudorange [meters]
                        ph_str,                         # Phase [cycles]
                        f"{doppler:.3f}",               # Doppler [Hz]
                    ]

                    # Step 9: Add row to applicable tables based on constellation filter
                    for tab_name, valid_systems in self.table_groups.items():
                        # Check if satellite's system is in this tab's system list
                        # (e.g., GPS satellites go in 'GPS' and 'ALL' tabs)
                        if sys_char in valid_systems:
                            # Only display if user checked this constellation
                            if sys_char in self.active_systems:
                                
                                if not added_to_dropdown:
                                    active_prns_in_view.append(key)
                                    added_to_dropdown = True
                                
                                # Get table widget for this tab
                                table = self.tables[tab_name]
                                row_idx = table.rowCount()
                                table.insertRow(row_idx)
                                
                                # Populate row cells with data and apply formatting
                                for col_idx, val in enumerate(row_items):
                                    item = QTableWidgetItem(str(val))
                                    # Center-align all cells for consistency
                                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                                    # Apply background color (alternating per satellite)
                                    item.setBackground(current_bg)
                                    
                                    # Special formatting for SNR column
                                    if col_idx == 5:  # SNR column index
                                        # Color-code SNR: green (good >40), red (poor <30)
                                        if snr > 40: 
                                            item.setForeground(QColor("green"))
                                        elif snr < 30: 
                                            item.setForeground(QColor("red"))
                                        # Bold font for emphasis
                                        item.setFont(QFont("Arial", 9, QFont.Weight.Bold))
                                    
                                    # Place formatted item in table
                                    table.setItem(row_idx, col_idx, item)

            # Step 10: Update Analysis tab dropdown list with visible satellites
            # Build sorted, deduplicated list of visible satellites
            current_sel = self.combo_sat.currentText()
            active_prns_in_view = sorted(list(set(active_prns_in_view)))
            
            # Update dropdown if list changed (avoid constant rebuilds)
            if active_prns_in_view != self.current_sat_list:
                self.current_sat_list = active_prns_in_view
                self.combo_sat.blockSignals(True)  # Prevent spurious updates
                self.combo_sat.clear()
                self.combo_sat.addItems(active_prns_in_view)
                # Restore previous selection if still valid
                if current_sel in active_prns_in_view:
                    self.combo_sat.setCurrentText(current_sel)
                self.combo_sat.blockSignals(False)
        finally:
            # Re-enable widget updates after batch operations complete
            # This triggers a single repaint instead of incremental redraws
            for t in self.tables.values():
                t.setUpdatesEnabled(True)

    def refresh_analysis_plot(self):
        prn = self.combo_sat.currentText()
        mode = self.combo_mode.currentText()
        if prn and mode:
            data = list(self.sat_history[prn])
            # Populate signal selector based on available signals for this satellite
            try:
                all_sigs = sorted({k for d in data for k in d.get('snr', {}).keys()})
            except Exception:
                all_sigs = []

            # Update combo_sig only when its items differ to avoid resetting selection constantly
            items = ["All"] + all_sigs
            if items != self._sig_items:
                cur = self.combo_sig.currentText()
                self.combo_sig.blockSignals(True)
                self.combo_sig.setUpdatesEnabled(False)
                self.combo_sig.clear()
                self.combo_sig.addItems(items)
                if cur in items:
                    self.combo_sig.setCurrentText(cur)
                self.combo_sig.setUpdatesEnabled(True)
                self.combo_sig.blockSignals(False)
                self._sig_items = items

            sig = self.combo_sig.currentText() if self.combo_sig.count() else None
            self.analysis_plot.update_plot(prn, data, mode, signal=(sig if sig != "All" else None))

    # ---- Logging Thread Management ----
    def open_log_settings_dialog(self):
        """
        Open logging configuration dialog.
        
        Procedure:
        1. Create LogSettingsDialog with current settings and recording state
        2. Connect recording toggle signal
        3. Show dialog (non-modal to allow interaction)
        4. Store dialog reference for updates
        5. Connect dialog close event to handle settings update
        """
        # Create dialog with current recording state
        dlg = LogSettingsDialog(self, self.logging_settings, self.logging_active)
        
        # Connect recording toggle signal
        dlg.recording_toggled.connect(self.handle_recording_toggle)
        
        # Update initial recording info
        self.update_recording_info_display(dlg)
        
        # Show dialog (non-modal to allow interaction)
        dlg.show()
        
        # Store dialog reference for updates
        self.log_settings_dialog = dlg
        
        # Connect dialog close event to handle settings update
        dlg.finished.connect(self.on_log_settings_closed)
        
        return dlg

    def handle_recording_toggle(self, start_recording):
        """
        Handle recording start/stop requests from the dialog.
        
        Args:
            start_recording (bool): True to start recording, False to stop
        """
        if start_recording:
            self.start_logging_from_dialog()
        else:
            self.stop_logging_from_dialog()

    def start_logging_from_dialog(self):
        """
        Start logging based on dialog settings.
        """
        # Get current settings from dialog
        if hasattr(self, 'log_settings_dialog') and self.log_settings_dialog:
            self.logging_settings = self.log_settings_dialog.get_settings()
        
        # Check if output directory is set
        directory = self.logging_settings.get('directory') or ''
        if not directory:
            self.signals.log_signal.emit("Logging: output directory not set")
            if hasattr(self, 'log_settings_dialog') and self.log_settings_dialog:
                self.log_settings_dialog.is_recording = False
                self.log_settings_dialog.update_recording_state()
            return False
        
        # Start logging
        self.start_logging()
        return True

    def stop_logging_from_dialog(self):
        """
        Stop logging from dialog request.
        """
        self.stop_logging()

    def on_log_settings_closed(self, result):
        """
        Handle dialog close event to apply settings.
        """
        if hasattr(self, 'log_settings_dialog') and self.log_settings_dialog:
            # Apply settings even if recording is active
            self.logging_settings = self.log_settings_dialog.get_settings()
            # Clean up reference
            self.log_settings_dialog = None

    def update_recording_info_display(self, dialog):
        """
        Update the recording information display in the dialog.
        """
        if not dialog:
            return
            
        info_text = ""
        if self.logging_active:
            info_text += "Status: 🟢 RECORDING\n"
            info_text += f"Format: {self.logging_settings.get('format', 'csv').upper()}\n"
            info_text += f"Directory: {self.logging_settings.get('directory', '')}\n"
            info_text += f"Files recorded: {self.get_recorded_file_count()}\n"
            info_text += f"Duration: {self.get_recording_duration()}\n"
            info_text += f"Current file: {self.get_current_filename()}\n"
            info_text += f"Split interval: {self.logging_settings.get('split_minutes', 60)} min\n"
            if self.logging_settings.get('format') == 'csv':
                info_text += f"Sampling: every {self.logging_settings.get('sample_interval', 1)} sec\n"
        else:
            info_text += "Status: ⚪ NOT RECORDING\n"
            info_text += "Click 'Start Recording' to begin logging data.\n"
            info_text += f"Output dir: {self.logging_settings.get('directory', 'Not set')}\n"
            info_text += f"Format: {self.logging_settings.get('format', 'csv').upper()}\n"
            
        dialog.update_recording_info(info_text)

    def get_recorded_file_count(self):
        """
        Get the number of files recorded so far.
        """
        if self.logging_active and self.logging_thread:
            return str(self.logging_thread.get_file_count())
        return "0"

    def get_recording_duration(self):
        """
        Get the current recording duration.
        """
        if self.logging_active and self.logging_thread:
            duration_seconds = self.logging_thread.get_duration()
            hours = int(duration_seconds // 3600)
            minutes = int((duration_seconds % 3600) // 60)
            seconds = int(duration_seconds % 60)
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return "00:00:00"

    def get_current_filename(self):
        """
        Get the current filename being written to.
        """
        if self.logging_active and self.logging_thread:
            return self.logging_thread.get_current_filename()
        return "N/A"

    def start_logging(self):
        """
        Start the logging thread.
        
        Procedure:
        1. Check if logging is already active (prevent double-start)
        2. Validate output directory configuration
        3. Create LoggingThread with current settings and buffers
        4. Set logging_active flag and start thread
        5. Log startup message
        6. Update dialog display if open
        """
        if self.logging_active:
            return
            
        directory = self.logging_settings.get('directory') or ''
        if not directory:
            self.signals.log_signal.emit("Logging: output directory not set")
            return
        
        # Create new LoggingThread with dedicated logging buffer
        self.logging_thread = LoggingThread(
            settings=self.logging_settings,
            ring_buffers=self.ring_buffers,
            merged_satellites=self.merged_satellites,
            signals=self.signals,
            logging_buffer=self.logging_buffer_ref
        )
        self.logging_active = True
        self.logging_thread.start()
        self.signals.log_signal.emit(f"Logging started -> {directory}")
        
        # Update dialog if open
        if hasattr(self, 'log_settings_dialog') and self.log_settings_dialog:
            self.log_settings_dialog.is_recording = True
            self.log_settings_dialog.update_recording_state()
            self.update_recording_info_display(self.log_settings_dialog)

    def stop_logging(self):
        """
        Stop the logging thread.
        
        Procedure:
        1. Check if logging is currently active
        2. Signal logging thread to stop
        3. Wait for thread to finish (timeout 2 seconds)
        4. Clear thread reference
        5. Log shutdown message
        6. Update dialog display if open
        """
        if not self.logging_active:
            return
            
        if self.logging_thread:
            self.logging_thread.stop()
            self.logging_thread.join(timeout=2.0)
            
        self.logging_thread = None
        self.logging_active = False
        self.signals.log_signal.emit("Logging stopped")
        
        # Update dialog if open
        if hasattr(self, 'log_settings_dialog') and self.log_settings_dialog:
            self.log_settings_dialog.is_recording = False
            self.log_settings_dialog.update_recording_state()
            self.update_recording_info_display(self.log_settings_dialog)

    # --- Config  ---
    def open_config_dialog(self):
        dlg = ConfigDialog(self, self.settings)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.settings = dlg.get_settings()
            self.restart_streams()

    def restart_streams(self):
        """
        Reinitialize data acquisition threads and buffers.
        
        Procedure:
        1. Stop all existing IO and processing threads gracefully
        2. Close all ring buffers to signal thread termination
        3. Clear thread references and data caches
        4. Stop active logging session if running
        5. Create new RTCMHandler instance (ephemeris cache)
        6. Initialize OBS stream thread pipeline if configured
        7. Initialize EPH stream thread pipeline if configured
        8. Log stream status and active GNSS systems
        
        Thread management:
        - Each stream (OBS, EPH) gets dedicated IO and DataProcessingThread
        - Shared RTCMHandler manages ephemeris caching across both streams
        - Ring buffers decouple thread speeds (IOThread → DataProcessingThread)
        - Logging buffer is independent (high capacity, separate from processing)
        """
        self.signals.log_signal.emit("=== Restarting streams ===")
        
        # Step 1: Stop all existing threads
        # This gracefully halts reception and processing of RTCM data
        if self.io_threads or self.processing_threads:
            self.signals.log_signal.emit("Stopping existing threads...")
            # Signal all threads to stop
            for t in self.io_threads: 
                t.stop()
            for t in self.processing_threads: 
                t.stop()
            # Wait for threads to exit (timeout 1 second per thread)
            for t in self.io_threads + self.processing_threads:
                t.join(timeout=1.0)
        
        # Step 2: Close all ring buffers
        # Closing signals buffer exhaustion, triggering thread cleanup
        for rb in self.ring_buffers.values():
            rb.close()
        for rb in self.logging_buffers.values():
            rb.close()
        
        # Step 3: Clear thread/buffer references to prepare for fresh start
        self.io_threads.clear()
        self.processing_threads.clear()
        self.ring_buffers.clear()
        self.logging_buffers.clear()
        self.logging_buffer_ref = None
        
        # Step 4: Stop logging if active (flushes pending writes)
        try:
            self.stop_logging()
        except Exception:
            pass

        # Step 5: Clear satellite state cache
        # Prevents old data from one session appearing in the next
        self.merged_satellites.clear()
        self.sat_last_seen.clear()
        self.sat_history.clear()
        self.signals.log_signal.emit("Cleared data cache")
        
        # Step 6: Create fresh RTCMHandler instance
        # Handler manages ephemeris caching and message parsing
        # Each restart gets a new handler (ephemeris cache resets)
        self.handler = RTCMHandler()
        
        # Step 7: Initialize OBS (Observation) stream thread pipeline
        # OBS streams provide raw observations (pseudorange, phase, SNR)
        # Check if OBS stream is configured (either NTRIP host or Serial port)
        obs_configured = False
        obs_source = self.settings['OBS'].get('source', 'NTRIP Server')
        if obs_source == 'NTRIP Server' and self.settings['OBS'].get('host'):
            obs_configured = True
        elif obs_source == 'Serial Port' and self.settings['OBS'].get('port'):
            obs_configured = True
            
        if obs_configured:
            self.signals.log_signal.emit("Initializing OBS stream...")
            
            # Create pair of buffers: one for processing, one for logging
            obs_buffer = RingBuffer(maxsize=1000)  # Standard processing buffer
            obs_logging_buffer = RingBuffer(maxsize=5000)  # High-capacity logging buffer
            
            # Store buffer references for shutdown
            self.ring_buffers['OBS'] = obs_buffer
            self.logging_buffers['OBS'] = obs_logging_buffer
            self.logging_buffer_ref = obs_logging_buffer
            
            # Create IOThread: receives RTCM via NTRIP or Serial, distributes to buffers
            io_thread = IOThread("OBS", self.settings['OBS'], obs_buffer, self.signals, obs_logging_buffer)
            io_thread.start()
            self.io_threads.append(io_thread)
            
            # Create DataProcessingThread: parses RTCM, emits epochs
            proc_thread = DataProcessingThread("OBS", obs_buffer, self.handler, self.signals)
            proc_thread.start()
            self.processing_threads.append(proc_thread)
            self.signals.log_signal.emit("OBS stream threads started")
        else:
            self.signals.log_signal.emit("OBS stream not configured")
        
        # Step 8: Initialize EPH (Ephemeris) stream thread pipeline if enabled
        # EPH streams provide navigation messages (satellite orbits, clocks)
        # Often obtained from separate NTRIP mount point or serial port
        if self.settings['EPH_ENABLED']:
            eph_source = self.settings['EPH'].get('source', 'NTRIP Server')
            eph_configured = False
            
            if eph_source == 'NTRIP Server' and self.settings['EPH'].get('host'):
                eph_configured = True
            elif eph_source == 'Serial Port' and self.settings['EPH'].get('port'):
                eph_configured = True
            
            if eph_configured:
                self.signals.log_signal.emit("Initializing EPH stream...")
                
                # Create pair of buffers for EPH stream
                eph_buffer = RingBuffer(maxsize=1000)
                eph_logging_buffer = RingBuffer(maxsize=5000)
                
                # Store buffer references
                self.ring_buffers['EPH'] = eph_buffer
                self.logging_buffers['EPH'] = eph_logging_buffer
                
                # Create IOThread for EPH stream
                io_thread = IOThread("EPH", self.settings['EPH'], eph_buffer, self.signals, eph_logging_buffer)
                io_thread.start()
                self.io_threads.append(io_thread)
                
                # Create DataProcessingThread for EPH stream
                # Note: Both OBS and EPH threads use same handler, so ephemeris is merged
                proc_thread = DataProcessingThread("EPH", eph_buffer, self.handler, self.signals)
                proc_thread.start()
                self.processing_threads.append(proc_thread)
                self.signals.log_signal.emit("EPH stream threads started")
            else:
                self.signals.log_signal.emit("EPH stream enabled but not configured")
        
        # Step 9: Log final status
        active_systems = ', '.join(sorted(self.active_systems))
        self.signals.log_signal.emit(f"Active GNSS systems: {active_systems}")
        self.signals.log_signal.emit("=== Stream initialization complete ===")

    @Slot(str)
    def append_log(self, text):
        """
        Append message to log display area.
        
        Procedure:
        1. Prepend timestamp to log message
        2. Append to log text area (QTextEdit)
        3. Limit log lines to prevent unbounded memory growth
        4. Remove oldest lines when exceeding max_log_lines threshold
        
        Performance: Batch removes 100 lines at a time when limit exceeded.
        """
        # Step 1: Format log message with timestamp
        log_text = f"[{datetime.now().strftime('%H:%M:%S')}] {text}"
        # Step 2: Append to UI text area
        self.log_area.append(log_text)
        
        # Step 3: Enforce maximum log line limit to prevent memory bloat
        # Without this, thousands of epochs would accumulate in the QTextEdit
        doc = self.log_area.document()
        if doc.blockCount() > self.max_log_lines:
            # Step 4: Delete oldest 100 lines (batch deletion for efficiency)
            cursor = self.log_area.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)  # Move to document start
            # Select first 100 lines
            for _ in range(100):
                cursor.movePosition(cursor.MoveOperation.Down, cursor.MoveMode.KeepAnchor)
            # Delete selected text
            cursor.removeSelectedText()

    @Slot(str, bool)
    def update_status(self, name, connected):
        """
        Update connection status indicator label.
        
        Procedure:
        1. Select label based on stream name (OBS or EPH)
        2. Update label text with connection state (ON/OFF)
        3. Apply color coding: green for connected, red for disconnected
        4. Update stylesheet to display new status
        """
        # Step 1: Choose label to update
        lbl = self.lbl_status_obs if name == "OBS" else self.lbl_status_eph
        
        # Step 2: Select color based on connection state
        color = "#2A692D" if connected else "#6D2F2B"  # Green if ON, Red if OFF
        
        # Step 3: Update label text and styling
        lbl.setText(f"{name}: {'ON' if connected else 'OFF'}")
        lbl.setStyleSheet(f"background-color: {color}; color: white; padding: 4px 8px; border-radius: 4px; font-weight: bold;")

    def on_back_to_launcher(self):
        """
        Signal parent to return to launcher screen and close this window.
        """
        self.back_to_launcher.emit()
        self.close()

    def closeEvent(self, event):
        """
        Handle window close event with proper cleanup.
        
        Procedure:
        1. Stop logging thread if active
        2. Stop all IO threads (disconnect from NTRIP)
        3. Stop all processing threads
        4. Close all ring buffers
        5. Cancel background cleanup timer
        6. Stop GUI update timer
        7. Accept close event
        
        Thread safety: Signals threads to stop and waits for graceful shutdown.
        """
        # Step 1: Stop logging first (flushes pending writes to files)
        try:
            self.stop_logging()
        except Exception:
            pass

        # Step 2-3: Stop all data acquisition threads
        for t in self.io_threads: 
            t.stop()
        for t in self.processing_threads: 
            t.stop()
        
        # Step 4: Close ring buffers (signals EOF to waiting threads)
        for rb in self.ring_buffers.values():
            rb.close()
        
        # Step 5: Cancel background cleanup timer
        if hasattr(self, 'cleanup_timer'): 
            self.cleanup_timer.cancel()
        
        # Step 6: Stop GUI update timer
        if hasattr(self, 'gui_update_timer'): 
            self.gui_update_timer.stop()
        
        # Step 7: Accept close event (proceed with window closure)
        event.accept()