from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QHBoxLayout, QLabel,
    QDoubleSpinBox, QComboBox, QSpinBox, QPushButton, QSizePolicy
)
from PySide6.QtCore import Qt
from core.global_config import update_positioning_settings, get_positioning_settings


class PositioningConfigDialog(QDialog):
    """Dialog to configure positioning (SPP) parameters."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Positioning Settings")
        self.setMinimumWidth(380)

        self.settings = get_positioning_settings().copy()

        layout = QVBoxLayout(self)
        form = QFormLayout()

        # Cutoff elevation (degrees)
        self.cutoff_spin = QDoubleSpinBox()
        self.cutoff_spin.setRange(0.0, 90.0)
        self.cutoff_spin.setValue(float(self.settings.get('cutoff_elevation_deg', 10.0)))
        self.cutoff_spin.setSingleStep(0.5)
        form.addRow("Cutoff Elevation (deg):", self.cutoff_spin)

        # Minimum satellites
        self.min_sats_spin = QSpinBox()
        self.min_sats_spin.setRange(2, 12)
        self.min_sats_spin.setValue(int(self.settings.get('min_satellites', 4)))
        form.addRow("Minimum Satellites:", self.min_sats_spin)

        # Weight mode
        self.weight_mode = QComboBox()
        self.weight_mode.addItems(["elevation", "snr", "equal"])
        self.weight_mode.setCurrentText(self.settings.get('weight_mode', 'elevation'))
        form.addRow("Weight Mode:", self.weight_mode)

        # Random walk (m/sqrt(s)) - optional
        self.random_walk = QDoubleSpinBox()
        self.random_walk.setRange(0.0, 100.0)
        self.random_walk.setValue(float(self.settings.get('random_walk', 0.0)))
        self.random_walk.setSingleStep(0.1)
        form.addRow("Random Walk:", self.random_walk)

        # Smoothing window (epochs)
        self.smoothing_window = QSpinBox()
        self.smoothing_window.setRange(0, 1000)
        self.smoothing_window.setValue(int(self.settings.get('smoothing_window', 0)))
        form.addRow("Smoothing Window (epochs):", self.smoothing_window)

        layout.addLayout(form)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_ok = QPushButton("Save")
        btn_ok.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        btn_ok.clicked.connect(self.on_accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)

    def on_accept(self):
        params = {
            'cutoff_elevation_deg': float(self.cutoff_spin.value()),
            'min_satellites': int(self.min_sats_spin.value()),
            'weight_mode': self.weight_mode.currentText(),
            'random_walk': float(self.random_walk.value()),
            'smoothing_window': int(self.smoothing_window.value()),
        }
        update_positioning_settings(params)
        self.accept()

    def get_settings(self):
        return {
            'cutoff_elevation_deg': float(self.cutoff_spin.value()),
            'min_satellites': int(self.min_sats_spin.value()),
            'weight_mode': self.weight_mode.currentText(),
            'random_walk': float(self.random_walk.value()),
            'smoothing_window': int(self.smoothing_window.value()),
        }
