# ui/positioning_module.py
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QTableWidget, QTableWidgetItem,
                             QHeaderView, QTabWidget, QFrame, QSplitter, QStyle,
                             QApplication, QDialog)
from PySide6.QtCore import Qt, Slot, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np


class PositioningModule(QMainWindow):
    """
    Positioning module window - provides real-time GNSS positioning
    """
    back_to_launcher = Signal()
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GNSS RT Monitor - Positioning Module")
        self.resize(1600, 900)
        
        self.position_history = []
        self.accuracy_history = []
        self.current_position = {'lat': 0.0, 'lon': 0.0, 'height': 0.0}
        self.current_accuracy = {'hpe': 0.0, 'vpe': 0.0}
        
        self.setup_ui()
        self.apply_stylesheet()
        
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_position_display)
        # self.update_timer.start(1000)  # Update every second

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # Left panel - Controls and position info
        left_panel = QFrame()
        left_panel.setObjectName("Panel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(8)

        # Control buttons
        control_frame = QFrame()
        control_layout = QHBoxLayout(control_frame)
        
        self.connect_btn = QPushButton("Start Positioning")
        self.connect_btn.clicked.connect(self.toggle_positioning)
        self.connect_btn.setObjectName("PrimaryButton")
        
        back_btn = QPushButton("< Back")
        back_btn.clicked.connect(self._on_back)
        
        control_layout.addWidget(self.connect_btn)
        control_layout.addWidget(back_btn)
        left_layout.addWidget(control_frame)

        # Current position display
        pos_group = QFrame()
        pos_layout = QVBoxLayout(pos_group)
        pos_layout.addWidget(QLabel("Current Position:"))
        
        self.lat_label = QLabel("Latitude: 0.000000°")
        self.lon_label = QLabel("Longitude: 0.000000°")
        self.height_label = QLabel("Height: 0.000 m")
        
        pos_layout.addWidget(self.lat_label)
        pos_layout.addWidget(self.lon_label)
        pos_layout.addWidget(self.height_label)
        left_layout.addWidget(pos_group)

        # Accuracy display
        acc_group = QFrame()
        acc_layout = QVBoxLayout(acc_group)
        acc_layout.addWidget(QLabel("Position Accuracy:"))
        
        self.hpe_label = QLabel("Horizontal: 0.000 m")
        self.vpe_label = QLabel("Vertical: 0.000 m")
        
        acc_layout.addWidget(self.hpe_label)
        acc_layout.addWidget(self.vpe_label)
        left_layout.addWidget(acc_group)

        # Position history table
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(4)
        headers = ["Time", "Latitude (°)", "Longitude (°)", "Height (m)"]
        self.history_table.setHorizontalHeaderLabels(headers)
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        left_layout.addWidget(QLabel("Position History:"))
        left_layout.addWidget(self.history_table)

        # Right panel - Maps and plots
        right_panel = QFrame()
        right_panel.setObjectName("Panel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)

        # Tab widget for different views
        self.tabs = QTabWidget()
        
        # Position track map
        map_widget = QWidget()
        map_layout = QVBoxLayout(map_widget)
        
        fig_map = Figure(figsize=(10, 6), dpi=100)
        self.map_ax = fig_map.add_subplot(111)
        self.map_ax.set_xlabel("Longitude (°)")
        self.map_ax.set_ylabel("Latitude (°)")
        self.map_ax.set_title("Position Track")
        self.map_ax.grid(True, alpha=0.3)
        self.map_canvas = FigureCanvas(fig_map)
        map_layout.addWidget(self.map_canvas)
        
        self.tabs.addTab(map_widget, "Position Map")

        # Position time series
        ts_widget = QWidget()
        ts_layout = QVBoxLayout(ts_widget)
        
        fig_ts = Figure(figsize=(10, 6), dpi=100)
        self.ts_ax = fig_ts.add_subplot(111)
        self.ts_ax.set_xlabel("Time")
        self.ts_ax.set_ylabel("Position (m)")
        self.ts_ax.set_title("Position Time Series")
        self.ts_ax.grid(True, alpha=0.3)
        self.ts_canvas = FigureCanvas(fig_ts)
        ts_layout.addWidget(self.ts_canvas)
        
        self.tabs.addTab(ts_widget, "Time Series")

        # Accuracy plot
        acc_widget = QWidget()
        acc_layout = QVBoxLayout(acc_widget)
        
        fig_acc = Figure(figsize=(10, 6), dpi=100)
        self.acc_ax = fig_acc.add_subplot(111)
        self.acc_ax.set_xlabel("Time")
        self.acc_ax.set_ylabel("Accuracy (m)")
        self.acc_ax.set_title("Position Accuracy")
        self.acc_ax.grid(True, alpha=0.3)
        self.acc_canvas = FigureCanvas(fig_acc)
        acc_layout.addWidget(self.acc_canvas)
        
        self.tabs.addTab(acc_widget, "Accuracy")

        right_layout.addWidget(self.tabs)

        # Add panels to main layout
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([400, 1200])
        main_layout.addWidget(splitter)

    @Slot()
    def toggle_positioning(self):
        if self.connect_btn.text() == "Start Positioning":
            self.start_positioning()
        else:
            self.stop_positioning()

    def start_positioning(self):
        """Start positioning calculations"""
        self.connect_btn.setText("Stop Positioning")
        self.update_timer.start(1000)  # Update every second
        # Here would be the actual positioning logic

    def stop_positioning(self):
        """Stop positioning calculations"""
        self.connect_btn.setText("Start Positioning")
        self.update_timer.stop()

    @Slot()
    def update_position_display(self):
        """Update position display with current data"""
        # Simulate position update
        import random
        self.current_position['lat'] += random.uniform(-0.0001, 0.0001)
        self.current_position['lon'] += random.uniform(-0.0001, 0.0001)
        self.current_position['height'] += random.uniform(-0.1, 0.1)
        
        self.current_accuracy['hpe'] = random.uniform(0.5, 2.0)
        self.current_accuracy['vpe'] = random.uniform(1.0, 3.0)
        
        # Update labels
        self.lat_label.setText(f"Latitude: {self.current_position['lat']:.6f}°")
        self.lon_label.setText(f"Longitude: {self.current_position['lon']:.6f}°")
        self.height_label.setText(f"Height: {self.current_position['height']:.3f} m")
        self.hpe_label.setText(f"Horizontal: {self.current_accuracy['hpe']:.3f} m")
        self.vpe_label.setText(f"Vertical: {self.current_accuracy['vpe']:.3f} m")
        
        # Add to history
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.position_history.append({
            'time': timestamp,
            'lat': self.current_position['lat'],
            'lon': self.current_position['lon'],
            'height': self.current_position['height']
        })
        
        self.accuracy_history.append({
            'time': timestamp,
            'hpe': self.current_accuracy['hpe'],
            'vpe': self.current_accuracy['vpe']
        })
        
        # Update table
        self.update_history_table()
        
        # Update plots
        self.update_plots()

    def update_history_table(self):
        """Update position history table"""
        self.history_table.setRowCount(len(self.position_history))
        
        for row, pos in enumerate(reversed(self.position_history[-50:])):  # Show last 50 entries
            self.history_table.setItem(row, 0, QTableWidgetItem(pos['time']))
            self.history_table.setItem(row, 1, QTableWidgetItem(f"{pos['lat']:.6f}"))
            self.history_table.setItem(row, 2, QTableWidgetItem(f"{pos['lon']:.6f}"))
            self.history_table.setItem(row, 3, QTableWidgetItem(f"{pos['height']:.3f}"))

    def update_plots(self):
        """Update all plots"""
        if len(self.position_history) > 1:
            times = [entry['time'] for entry in self.position_history[-50:]]
            lats = [entry['lat'] for entry in self.position_history[-50:]]
            lons = [entry['lon'] for entry in self.position_history[-50:]]
            heights = [entry['height'] for entry in self.position_history[-50:]]
            
            # Update map
            self.map_ax.clear()
            self.map_ax.plot(lons, lats, 'b-o', markersize=4)
            self.map_ax.set_xlabel("Longitude (°)")
            self.map_ax.set_ylabel("Latitude (°)")
            self.map_ax.set_title("Position Track")
            self.map_ax.grid(True, alpha=0.3)
            self.map_canvas.draw()
            
            # Update time series
            self.ts_ax.clear()
            self.ts_ax.plot(range(len(heights)), heights, 'g-', label='Height')
            self.ts_ax.set_xlabel("Sample")
            self.ts_ax.set_ylabel("Height (m)")
            self.ts_ax.set_title("Position Time Series")
            self.ts_ax.legend()
            self.ts_ax.grid(True, alpha=0.3)
            self.ts_canvas.draw()
            
            # Update accuracy plot
            if len(self.accuracy_history) > 1:
                acc_times = [entry['time'] for entry in self.accuracy_history[-50:]]
                hpes = [entry['hpe'] for entry in self.accuracy_history[-50:]]
                vpes = [entry['vpe'] for entry in self.accuracy_history[-50:]]
                
                self.acc_ax.clear()
                self.acc_ax.plot(range(len(hpes)), hpes, 'b-', label='Horizontal')
                self.acc_ax.plot(range(len(vpes)), vpes, 'r-', label='Vertical')
                self.acc_ax.set_xlabel("Sample")
                self.acc_ax.set_ylabel("Accuracy (m)")
                self.acc_ax.set_title("Position Accuracy")
                self.acc_ax.legend()
                self.acc_ax.grid(True, alpha=0.3)
                self.acc_canvas.draw()

    def _on_back(self):
        """Return to launcher"""
        self.stop_positioning()
        self.back_to_launcher.emit()

    def apply_stylesheet(self):
        from ui.style import get_app_stylesheet
        self.setStyleSheet(get_app_stylesheet())

    def closeEvent(self, event):
        """Handle window closing"""
        self.stop_positioning()
        super().closeEvent(event)