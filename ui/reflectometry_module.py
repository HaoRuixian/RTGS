# ui/reflectometry_module.py
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QTableWidget, QTableWidgetItem,
                             QHeaderView, QTabWidget, QFrame, QSplitter, QComboBox,
                             QSpinBox, QDoubleSpinBox, QCheckBox)
from PySide6.QtCore import Qt, Slot, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np


class ReflectometryModule(QMainWindow):
    """
    Reflectometry module - GNSS-IR signal reflection analysis
    """
    back_to_launcher = Signal()
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GNSS RT Monitor - Reflectometry Module")
        self.resize(1600, 900)
        
        self.reflectometry_data = {}
        self.interferogram_data = []
        
        self.setup_ui()
        self.apply_stylesheet()
        
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_reflectometry_display)
        
    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        
        top_bar = QHBoxLayout()
        btn_back = QPushButton("< Back to Launcher")
        btn_back.setMaximumWidth(150)
        btn_back.clicked.connect(self.on_back)
        
        title_label = QLabel("Reflectometry Module - GNSS-IR Analysis")
        title_font = QFont("Microsoft YaHei", 14, QFont.Weight.Bold)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #FF8844;")
        
        btn_config = QPushButton("Configure")
        btn_config.setMaximumWidth(100)
        
        top_bar.addWidget(btn_back)
        top_bar.addSpacing(20)
        top_bar.addWidget(title_label)
        top_bar.addStretch()
        top_bar.addWidget(btn_config)
        
        main_layout.addLayout(top_bar)
        
        tabs = QTabWidget()
        
        tab_interferogram = self.create_interferogram_tab()
        tabs.addTab(tab_interferogram, "Interferogram")
        
        tab_spectrum = self.create_spectrum_tab()
        tabs.addTab(tab_spectrum, "Spectrum Analysis")
        
        tab_parameters = self.create_parameters_tab()
        tabs.addTab(tab_parameters, "Reflection Parameters")
        
        tab_inversion = self.create_inversion_tab()
        tabs.addTab(tab_inversion, "Height Inversion")
        
        main_layout.addWidget(tabs)
    
    def create_interferogram_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 15, 15, 15)
        
        control_frame = QFrame()
        control_frame.setStyleSheet("""
            QFrame {
                background-color: #f9f9f9;
                border: 1px solid #ddd;
                border-radius: 5px;
            }
        """)
        control_layout = QHBoxLayout(control_frame)
        
        control_label = QLabel("Interferogram Control")
        control_label_font = QFont("Microsoft YaHei", 10, QFont.Weight.Bold)
        control_label.setFont(control_label_font)
        control_layout.addWidget(control_label)
        
        sat_label = QLabel("Select Satellite:")
        self.sat_combo = QComboBox()
        self.sat_combo.addItems(["All Satellites", "G01", "G02", "R01", "E01"])
        
        freq_label = QLabel("Frequency:")
        self.freq_combo = QComboBox()
        self.freq_combo.addItems(["L1", "L5"])
        
        btn_refresh = QPushButton("Refresh Data")
        btn_refresh.setMaximumWidth(100)
        
        control_layout.addWidget(sat_label)
        control_layout.addWidget(self.sat_combo)
        control_layout.addSpacing(30)
        control_layout.addWidget(freq_label)
        control_layout.addWidget(self.freq_combo)
        control_layout.addSpacing(20)
        control_layout.addWidget(btn_refresh)
        control_layout.addStretch()
        
        layout.addWidget(control_frame)
        
        self.interferogram_canvas = FigureCanvas(Figure(figsize=(10, 5), dpi=100))
        self.interferogram_ax = self.interferogram_canvas.figure.add_subplot(111)
        self.interferogram_ax.set_title("Interferogram - Carrier Phase vs Reflection Delay")
        self.interferogram_ax.set_xlabel("Reflection Delay Distance (m)")
        self.interferogram_ax.set_ylabel("Carrier Phase (cycle)")
        self.interferogram_ax.grid(True, alpha=0.3)
        
        layout.addWidget(self.interferogram_canvas)
        
        return widget
    
    def create_spectrum_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 15, 15, 15)
        
        self.spectrum_canvas = FigureCanvas(Figure(figsize=(10, 4), dpi=100))
        
        self.spectrum_ax1 = self.spectrum_canvas.figure.add_subplot(121)
        self.spectrum_ax1.set_title("Power Spectrum")
        self.spectrum_ax1.set_xlabel("Frequency (Hz)")
        self.spectrum_ax1.set_ylabel("Power (dB)")
        self.spectrum_ax1.grid(True, alpha=0.3)
        
        self.spectrum_ax2 = self.spectrum_canvas.figure.add_subplot(122)
        self.spectrum_ax2.set_title("Phase Spectrum")
        self.spectrum_ax2.set_xlabel("Frequency (Hz)")
        self.spectrum_ax2.set_ylabel("Phase (rad)")
        self.spectrum_ax2.grid(True, alpha=0.3)
        
        layout.addWidget(self.spectrum_canvas)
        
        stats_frame = QFrame()
        stats_frame.setStyleSheet("""
            QFrame {
                background-color: #f9f9f9;
                border: 1px solid #ddd;
                border-radius: 5px;
            }
        """)
        stats_layout = QHBoxLayout(stats_frame)
        
        peak_freq_layout = QVBoxLayout()
        peak_freq_label = QLabel("Peak Frequency")
        peak_freq_label.setStyleSheet("color: #666666; font-size: 10px;")
        self.peak_freq_value = QLabel("0.0 Hz")
        peak_freq_layout.addWidget(peak_freq_label)
        peak_freq_layout.addWidget(self.peak_freq_value)
        
        snr_layout = QVBoxLayout()
        snr_label = QLabel("Signal-to-Noise Ratio (SNR)")
        snr_label.setStyleSheet("color: #666666; font-size: 10px;")
        self.snr_value = QLabel("0.0 dB")
        snr_layout.addWidget(snr_label)
        snr_layout.addWidget(self.snr_value)
        
        bw_layout = QVBoxLayout()
        bw_label = QLabel("Spectrum Width")
        bw_label.setStyleSheet("color: #666666; font-size: 10px;")
        self.bw_value = QLabel("0.0 Hz")
        bw_layout.addWidget(bw_label)
        bw_layout.addWidget(self.bw_value)
        
        stats_layout.addLayout(peak_freq_layout)
        stats_layout.addSpacing(30)
        stats_layout.addLayout(snr_layout)
        stats_layout.addSpacing(30)
        stats_layout.addLayout(bw_layout)
        stats_layout.addStretch()
        
        layout.addWidget(stats_frame)
        
        return widget
    
    def create_parameters_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 15, 15, 15)
        
        params_frame = QFrame()
        params_frame.setStyleSheet("""
            QFrame {
                background-color: #f9f9f9;
                border: 1px solid #ddd;
                border-radius: 5px;
            }
        """)
        params_layout = QVBoxLayout(params_frame)
        
        title = QLabel("Reflection Surface Parameters")
        title_font = QFont("Microsoft YaHei", 12, QFont.Weight.Bold)
        title.setFont(title_font)
        params_layout.addWidget(title)
        
        grid_layout = QHBoxLayout()
        
        rho_layout = QVBoxLayout()
        rho_title = QLabel("Reflection Coefficient (rho)")
        rho_title.setStyleSheet("color: #666666; font-size: 10px;")
        self.rho_value = QLabel("0.00")
        rho_font = QFont("Courier New", 12, QFont.Weight.Bold)
        self.rho_value.setFont(rho_font)
        self.rho_value.setStyleSheet("color: #FF8844;")
        rho_layout.addWidget(rho_title)
        rho_layout.addWidget(self.rho_value)
        
        roughness_layout = QVBoxLayout()
        roughness_title = QLabel("Surface Roughness (sigma)")
        roughness_title.setStyleSheet("color: #666666; font-size: 10px;")
        self.roughness_value = QLabel("0.00 cm")
        roughness_font = QFont("Courier New", 12, QFont.Weight.Bold)
        self.roughness_value.setFont(roughness_font)
        self.roughness_value.setStyleSheet("color: #FF8844;")
        roughness_layout.addWidget(roughness_title)
        roughness_layout.addWidget(self.roughness_value)
        
        moisture_layout = QVBoxLayout()
        moisture_title = QLabel("Soil Moisture (SM)")
        moisture_title.setStyleSheet("color: #666666; font-size: 10px;")
        self.moisture_value = QLabel("0.00 m3/m3")
        moisture_font = QFont("Courier New", 12, QFont.Weight.Bold)
        self.moisture_value.setFont(moisture_font)
        self.moisture_value.setStyleSheet("color: #FF8844;")
        moisture_layout.addWidget(moisture_title)
        moisture_layout.addWidget(self.moisture_value)
        
        grid_layout.addLayout(rho_layout)
        grid_layout.addSpacing(30)
        grid_layout.addLayout(roughness_layout)
        grid_layout.addSpacing(30)
        grid_layout.addLayout(moisture_layout)
        grid_layout.addStretch()
        
        params_layout.addLayout(grid_layout)
        layout.addWidget(params_frame)
        
        self.param_ts_canvas = FigureCanvas(Figure(figsize=(10, 4), dpi=100))
        self.param_ts_ax = self.param_ts_canvas.figure.add_subplot(111)
        self.param_ts_ax.set_title("Soil Moisture Time Series")
        self.param_ts_ax.set_xlabel("Time")
        self.param_ts_ax.set_ylabel("Soil Moisture (m3/m3)")
        self.param_ts_ax.grid(True, alpha=0.3)
        
        layout.addWidget(self.param_ts_canvas)
        
        return widget
    
    def create_inversion_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 15, 15, 15)
        
        settings_frame = QFrame()
        settings_frame.setStyleSheet("""
            QFrame {
                background-color: #f9f9f9;
                border: 1px solid #ddd;
                border-radius: 5px;
            }
        """)
        settings_layout = QHBoxLayout(settings_frame)
        
        settings_title = QLabel("Inversion Configuration")
        settings_title_font = QFont("Microsoft YaHei", 10, QFont.Weight.Bold)
        settings_title.setFont(settings_title_font)
        settings_layout.addWidget(settings_title)
        
        method_label = QLabel("Inversion Method:")
        self.method_combo = QComboBox()
        self.method_combo.addItems(["Least Squares", "Kalman Filter", "Bayesian Method"])
        
        window_label = QLabel("FFT Window:")
        self.window_spinbox = QSpinBox()
        self.window_spinbox.setValue(256)
        self.window_spinbox.setRange(64, 2048)
        
        confidence_label = QLabel("Confidence Level:")
        self.confidence_spinbox = QDoubleSpinBox()
        self.confidence_spinbox.setValue(0.95)
        self.confidence_spinbox.setRange(0.0, 1.0)
        self.confidence_spinbox.setSingleStep(0.05)
        
        btn_invert = QPushButton("Execute Inversion")
        btn_invert.setMaximumWidth(120)
        
        settings_layout.addWidget(method_label)
        settings_layout.addWidget(self.method_combo)
        settings_layout.addSpacing(20)
        settings_layout.addWidget(window_label)
        settings_layout.addWidget(self.window_spinbox)
        settings_layout.addSpacing(20)
        settings_layout.addWidget(confidence_label)
        settings_layout.addWidget(self.confidence_spinbox)
        settings_layout.addSpacing(20)
        settings_layout.addWidget(btn_invert)
        settings_layout.addStretch()
        
        layout.addWidget(settings_frame)
        
        self.inversion_canvas = FigureCanvas(Figure(figsize=(10, 5), dpi=100))
        
        self.inversion_ax1 = self.inversion_canvas.figure.add_subplot(121)
        self.inversion_ax1.set_title("Reflection Point Height")
        self.inversion_ax1.set_xlabel("Time")
        self.inversion_ax1.set_ylabel("Height (m)")
        self.inversion_ax1.grid(True, alpha=0.3)
        
        self.inversion_ax2 = self.inversion_canvas.figure.add_subplot(122)
        self.inversion_ax2.set_title("Inversion Accuracy")
        self.inversion_ax2.set_xlabel("Time")
        self.inversion_ax2.set_ylabel("Height Error (m)")
        self.inversion_ax2.grid(True, alpha=0.3)
        
        layout.addWidget(self.inversion_canvas)
        
        return widget
    
    def update_reflectometry_display(self):
        pass
    
    def on_back(self):
        self.back_to_launcher.emit()
        self.close()
    
    def apply_stylesheet(self):
        pass
