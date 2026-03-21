from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QHBoxLayout, QLabel,
    QDoubleSpinBox, QComboBox, QSpinBox, QPushButton, QSizePolicy,
    QGroupBox, QCheckBox
)
from PySide6.QtCore import Qt
from core.global_config import update_positioning_settings, get_positioning_settings


class PositioningConfigDialog(QDialog):
    """Dialog to configure positioning (SPP) parameters."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Positioning Settings (SPP)")
        self.setMinimumWidth(500)

        self.settings = get_positioning_settings().copy()

        layout = QVBoxLayout(self)

        basic_group = QGroupBox("Basic Settings")
        basic_layout = QFormLayout()

        self.cutoff_spin = QDoubleSpinBox()
        self.cutoff_spin.setRange(0.0, 90.0)
        self.cutoff_spin.setValue(float(self.settings.get("cutoff_elevation_deg", 10.0)))
        self.cutoff_spin.setSingleStep(0.5)
        self.cutoff_spin.setSuffix(" 掳")
        basic_layout.addRow("Cutoff Elevation Angle:", self.cutoff_spin)

        self.min_sats_spin = QSpinBox()
        self.min_sats_spin.setRange(2, 12)
        self.min_sats_spin.setValue(int(self.settings.get("min_satellites", 4)))
        basic_layout.addRow("Minimum Satellites:", self.min_sats_spin)

        self.max_pdop_spin = QDoubleSpinBox()
        self.max_pdop_spin.setRange(0.1, 100.0)
        self.max_pdop_spin.setValue(float(self.settings.get("max_pdop", 10.0)))
        self.max_pdop_spin.setSingleStep(0.5)
        basic_layout.addRow("Maximum PDOP:", self.max_pdop_spin)

        basic_group.setLayout(basic_layout)
        layout.addWidget(basic_group)

        iono_group = QGroupBox("Ionosphere Correction")
        iono_layout = QFormLayout()

        self.iono_option = QComboBox()
        self.iono_option.addItem("IFLC (Dual-freq IF-LC)", "IFLC")
        self.iono_option.addItem("SINGLE (Single-freq + TGD)", "SINGLE")
        current_iono = self.settings.get("ionosphere_option", "IFLC")
        iono_index = self.iono_option.findData(current_iono)
        if iono_index >= 0:
            self.iono_option.setCurrentIndex(iono_index)
        iono_layout.addRow("Ionosphere Model:", self.iono_option)

        iono_group.setLayout(iono_layout)
        layout.addWidget(iono_group)

        tropo_group = QGroupBox("Troposphere Correction")
        tropo_layout = QFormLayout()

        self.tropo_model = QComboBox()
        self.tropo_model.addItem("Sastamoinen", "Sastamoinen")
        self.tropo_model.addItem("HMSL (Height-based)", "HMSL")
        self.tropo_model.addItem("None (No correction)", "None")
        current_tropo = self.settings.get("troposphere_model", "Sastamoinen")
        tropo_index = self.tropo_model.findData(current_tropo)
        if tropo_index >= 0:
            self.tropo_model.setCurrentIndex(tropo_index)
        tropo_layout.addRow("Troposphere Model:", self.tropo_model)

        tropo_group.setLayout(tropo_layout)
        layout.addWidget(tropo_group)

        gnss_group = QGroupBox("GNSS Systems")
        gnss_layout = QFormLayout()

        self.gnss_gps = QCheckBox("GPS (G)")
        self.gnss_glonass = QCheckBox("GLONASS (R)")
        self.gnss_galileo = QCheckBox("Galileo (E)")
        self.gnss_beidou = QCheckBox("BeiDou (C)")

        gnss_systems = self.settings.get("gnss_systems", ["G", "R", "E", "C"])
        self.gnss_gps.setChecked("G" in gnss_systems)
        self.gnss_glonass.setChecked("R" in gnss_systems)
        self.gnss_galileo.setChecked("E" in gnss_systems)
        self.gnss_beidou.setChecked("C" in gnss_systems)

        gnss_layout.addRow("Available Systems:", self.gnss_gps)
        gnss_layout.addRow("", self.gnss_glonass)
        gnss_layout.addRow("", self.gnss_galileo)
        gnss_layout.addRow("", self.gnss_beidou)

        gnss_group.setLayout(gnss_layout)
        layout.addWidget(gnss_group)

        weight_group = QGroupBox("Observation Weighting")
        weight_layout = QFormLayout()

        self.weight_mode = QComboBox()
        self.weight_mode.addItem("Elevation Angle", "elevation")
        self.weight_mode.addItem("Signal-to-Noise Ratio (SNR)", "snr")
        self.weight_mode.addItem("Equal Weight", "equal")
        self.weight_mode.setCurrentText(self.settings.get("weight_mode", "elevation"))
        weight_layout.addRow("Weighting Method:", self.weight_mode)

        weight_group.setLayout(weight_layout)
        layout.addWidget(weight_group)

        smooth_group = QGroupBox("Smoothing & Filtering")
        smooth_layout = QFormLayout()

        self.use_smoothing = QCheckBox("Enable Position Smoothing")
        self.use_smoothing.setChecked(self.settings.get("use_smoothing", False))
        smooth_layout.addRow("", self.use_smoothing)

        self.smoothing_window = QSpinBox()
        self.smoothing_window.setRange(0, 1000)
        self.smoothing_window.setValue(int(self.settings.get("smoothing_window", 10)))
        smooth_layout.addRow("Smoothing Window (epochs):", self.smoothing_window)

        self.random_walk = QDoubleSpinBox()
        self.random_walk.setRange(0.0, 100.0)
        self.random_walk.setValue(float(self.settings.get("random_walk", 0.0)))
        self.random_walk.setSingleStep(0.1)
        self.random_walk.setSuffix(" m/鈭歴")
        smooth_layout.addRow("Random Walk (m/鈭歴):", self.random_walk)

        smooth_group.setLayout(smooth_layout)
        layout.addWidget(smooth_group)

        status_group = QGroupBox("Solution Status Thresholds")
        status_layout = QFormLayout()

        self.uncertain_std = QDoubleSpinBox()
        self.uncertain_std.setRange(0.1, 100.0)
        self.uncertain_std.setValue(float(self.settings.get("uncertain_std_pos", 5.0)))
        self.uncertain_std.setSingleStep(0.1)
        self.uncertain_std.setSuffix(" m")
        status_layout.addRow("Uncertain Std Dev Threshold:", self.uncertain_std)

        self.fixed_std = QDoubleSpinBox()
        self.fixed_std.setRange(0.1, 100.0)
        self.fixed_std.setValue(float(self.settings.get("fixed_std_pos", 2.5)))
        self.fixed_std.setSingleStep(0.1)
        self.fixed_std.setSuffix(" m")
        status_layout.addRow("Fixed Std Dev Threshold:", self.fixed_std)

        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_ok = QPushButton("Save")
        btn_ok.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        btn_ok.clicked.connect(self.on_accept)
        btn_reset = QPushButton("Reset to Defaults")
        btn_reset.clicked.connect(self.on_reset_defaults)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_reset)
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)

    def on_reset_defaults(self):
        """Reset all settings to defaults."""
        defaults = {
            "cutoff_elevation_deg": 10.0,
            "min_satellites": 4,
            "max_pdop": 10.0,
            "ionosphere_option": "IFLC",
            "troposphere_model": "Sastamoinen",
            "gnss_systems": ["G", "R", "E", "C"],
            "weight_mode": "elevation",
            "use_smoothing": False,
            "smoothing_window": 10,
            "random_walk": 0.0,
            "uncertain_std_pos": 5.0,
            "fixed_std_pos": 2.5,
        }

        self.cutoff_spin.setValue(defaults["cutoff_elevation_deg"])
        self.min_sats_spin.setValue(defaults["min_satellites"])
        self.max_pdop_spin.setValue(defaults["max_pdop"])
        self.iono_option.setCurrentData(defaults["ionosphere_option"])
        self.tropo_model.setCurrentData(defaults["troposphere_model"])
        self.gnss_gps.setChecked("G" in defaults["gnss_systems"])
        self.gnss_glonass.setChecked("R" in defaults["gnss_systems"])
        self.gnss_galileo.setChecked("E" in defaults["gnss_systems"])
        self.gnss_beidou.setChecked("C" in defaults["gnss_systems"])
        self.weight_mode.setCurrentData(defaults["weight_mode"])
        self.use_smoothing.setChecked(defaults["use_smoothing"])
        self.smoothing_window.setValue(defaults["smoothing_window"])
        self.random_walk.setValue(defaults["random_walk"])
        self.uncertain_std.setValue(defaults["uncertain_std_pos"])
        self.fixed_std.setValue(defaults["fixed_std_pos"])

    def on_accept(self):
        params = self.get_settings()
        update_positioning_settings(params)
        self.accept()

    def get_settings(self):
        gnss_systems = []
        if self.gnss_gps.isChecked():
            gnss_systems.append("G")
        if self.gnss_glonass.isChecked():
            gnss_systems.append("R")
        if self.gnss_galileo.isChecked():
            gnss_systems.append("E")
        if self.gnss_beidou.isChecked():
            gnss_systems.append("C")

        return {
            "cutoff_elevation_deg": float(self.cutoff_spin.value()),
            "min_satellites": int(self.min_sats_spin.value()),
            "max_pdop": float(self.max_pdop_spin.value()),
            "ionosphere_option": self.iono_option.currentData(),
            "troposphere_model": self.tropo_model.currentData(),
            "gnss_systems": gnss_systems if gnss_systems else ["G"],
            "weight_mode": self.weight_mode.currentData(),
            "use_smoothing": self.use_smoothing.isChecked(),
            "smoothing_window": int(self.smoothing_window.value()),
            "random_walk": float(self.random_walk.value()),
            "uncertain_std_pos": float(self.uncertain_std.value()),
            "fixed_std_pos": float(self.fixed_std.value()),
        }
