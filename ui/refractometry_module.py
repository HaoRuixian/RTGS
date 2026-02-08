from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QTabWidget,
                             QPushButton, QLabel, QTableWidget, QTableWidgetItem,
                             QHBoxLayout)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvasQTAgg
from matplotlib.figure import Figure


class RefractometryModule(QMainWindow):
    """
    Refractometry module for ZTD, PWV and ionospheric parameter estimation.
    """
    back_to_launcher = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("GNSS RT Monitor - Refractometry")
        self.resize(1200, 750)
        self.setup_ui()

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Header with back button
        header = QHBoxLayout()
        title = QLabel("Refractometry Analysis")
        title_font = QFont("Segoe UI", 14, QFont.Weight.Bold)
        title.setFont(title_font)
        header.addWidget(title)
        header.addStretch()
        back_btn = QPushButton("< Back to Launcher")
        back_btn.clicked.connect(self._on_back)
        header.addWidget(back_btn)
        layout.addLayout(header)

        # Tab widget
        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_ztd_tab(), "ZTD Analysis")
        self.tabs.addTab(self._create_pwv_tab(), "PWV Estimation")
        self.tabs.addTab(self._create_ionosphere_tab(), "Ionospheric Parameters")
        self.tabs.addTab(self._create_gradients_tab(), "Tropospheric Gradients")

        layout.addWidget(self.tabs)

    def _create_ztd_tab(self):
        """Zenith Total Delay analysis tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Time series plot
        fig = Figure(figsize=(10, 4), dpi=100)
        ax = fig.add_subplot(111)
        ax.set_xlabel("Time (min)")
        ax.set_ylabel("ZTD (mm)")
        ax.set_title("Real-time Zenith Total Delay")
        ax.grid(True, alpha=0.3)
        canvas = FigureCanvasQTAgg(fig)
        layout.addWidget(canvas)

        # Statistics table
        table = QTableWidget(5, 2)
        table.setHorizontalHeaderLabels(["Parameter", "Value"])
        table.setMaximumHeight(150)
        params = ["Current ZTD", "Average ZTD", "Max ZTD", "Min ZTD", "Std Dev"]
        values = ["0.00 mm", "0.00 mm", "0.00 mm", "0.00 mm", "0.00 mm"]
        for i, (param, value) in enumerate(zip(params, values)):
            table.setItem(i, 0, QTableWidgetItem(param))
            table.setItem(i, 1, QTableWidgetItem(value))
        layout.addWidget(table)

        return widget

    def _create_pwv_tab(self):
        """Precipitable Water Vapor estimation tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # PWV time series
        fig = Figure(figsize=(10, 4), dpi=100)
        ax = fig.add_subplot(111)
        ax.set_xlabel("Time (min)")
        ax.set_ylabel("PWV (mm)")
        ax.set_title("Real-time Precipitable Water Vapor")
        ax.grid(True, alpha=0.3)
        canvas = FigureCanvasQTAgg(fig)
        layout.addWidget(canvas)

        # PWV statistics
        table = QTableWidget(5, 2)
        table.setHorizontalHeaderLabels(["Parameter", "Value"])
        table.setMaximumHeight(150)
        params = ["Current PWV", "Average PWV", "Max PWV", "Min PWV", "Std Dev"]
        values = ["0.00 mm", "0.00 mm", "0.00 mm", "0.00 mm", "0.00 mm"]
        for i, (param, value) in enumerate(zip(params, values)):
            table.setItem(i, 0, QTableWidgetItem(param))
            table.setItem(i, 1, QTableWidgetItem(value))
        layout.addWidget(table)

        return widget

    def _create_ionosphere_tab(self):
        """Ionospheric parameter estimation tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # TEC time series
        fig = Figure(figsize=(10, 4), dpi=100)
        ax = fig.add_subplot(111)
        ax.set_xlabel("Time (min)")
        ax.set_ylabel("TEC (TECU)")
        ax.set_title("Real-time Total Electron Content")
        ax.grid(True, alpha=0.3)
        canvas = FigureCanvasQTAgg(fig)
        layout.addWidget(canvas)

        # Ionosphere statistics
        table = QTableWidget(5, 2)
        table.setHorizontalHeaderLabels(["Parameter", "Value"])
        table.setMaximumHeight(150)
        params = ["Current TEC", "Average TEC", "Max TEC", "Min TEC", "Rate of Change"]
        values = ["0.00 TECU", "0.00 TECU", "0.00 TECU", "0.00 TECU", "0.00 TECU/min"]
        for i, (param, value) in enumerate(zip(params, values)):
            table.setItem(i, 0, QTableWidgetItem(param))
            table.setItem(i, 1, QTableWidgetItem(value))
        layout.addWidget(table)

        return widget

    def _create_gradients_tab(self):
        """Tropospheric gradients tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Gradient vectors
        fig = Figure(figsize=(10, 4), dpi=100)
        ax = fig.add_subplot(111)
        ax.set_xlabel("North-South Gradient (mm)")
        ax.set_ylabel("East-West Gradient (mm)")
        ax.set_title("Tropospheric Gradient Vectors")
        ax.grid(True, alpha=0.3)
        ax.set_xlim(-10, 10)
        ax.set_ylim(-10, 10)
        canvas = FigureCanvasQTAgg(fig)
        layout.addWidget(canvas)

        # Gradient statistics
        table = QTableWidget(4, 2)
        table.setHorizontalHeaderLabels(["Parameter", "Value"])
        table.setMaximumHeight(130)
        params = ["North-South Gradient", "East-West Gradient", "Total Magnitude", "Direction"]
        values = ["0.00 mm", "0.00 mm", "0.00 mm", "0.00 °"]
        for i, (param, value) in enumerate(zip(params, values)):
            table.setItem(i, 0, QTableWidgetItem(param))
            table.setItem(i, 1, QTableWidgetItem(value))
        layout.addWidget(table)

        return widget

    def _on_back(self):
        """Emit signal to return to launcher."""
        self.back_to_launcher.emit()
        self.close()
