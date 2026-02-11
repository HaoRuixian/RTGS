"""
Positioning module UI widgets - map and charts for position visualization.
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import numpy as np
from typing import List, Optional


class PositionMapWidget(QWidget):
    """
    Real-time position map display using matplotlib.
    
    Shows:
    - Position track (latitude vs longitude)
    - Current position marker
    - Uncertainty ellipses (optional)
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.figure = Figure(figsize=(10, 8), dpi=100)
        self.ax = self.figure.add_subplot(111)
        self.canvas = FigureCanvas(self.figure)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        
        # Setup map
        self.ax.set_xlabel("Longitude (°E)")
        self.ax.set_ylabel("Latitude (°N)")
        self.ax.set_title("GNSS Position Map")
        self.ax.grid(True, alpha=0.3, linestyle='--')
        
        # Data storage
        self.lats = []
        self.lons = []
        self.first_update = True
        
        self.figure.tight_layout()
    
    def update_track(self, latitude: float, longitude: float, hdop: float = 0.0):
        """
        Update position on map with actual geographic coordinates.
        
        Args:
            latitude: Current latitude (degrees)
            longitude: Current longitude (degrees)
            hdop: Horizontal DOP for uncertainty circle
        """
        self.lats.append(latitude)
        self.lons.append(longitude)
        
        # Update plot
        self.ax.clear()
        self.ax.set_xlabel("Longitude (°E)")
        self.ax.set_ylabel("Latitude (°N)")
        self.ax.set_title(f"GNSS Position Map - Current: ({longitude:.6f}°E, {latitude:.6f}°N)")
        self.ax.grid(True, alpha=0.3, linestyle='--')
        
        # Plot track line
        if len(self.lons) > 1:
            self.ax.plot(self.lons[:-1], self.lats[:-1], 'b-', alpha=0.6, linewidth=1.5, label='Track')
        
        # Plot history points (fade effect)
        if len(self.lons) > 1:
            # Color gradient from old to new
            start_idx = max(0, len(self.lons) - 50)
            denom = max(1, (len(self.lons) - 1) - start_idx)
            for i in range(start_idx, len(self.lons) - 1):
                # Safely compute alpha in [0.0, 1.0]
                rel = (i - start_idx) / denom
                alpha = 0.3 + 0.7 * rel
                alpha = max(0.0, min(1.0, alpha))
                self.ax.scatter(self.lons[i], self.lats[i], c='blue', s=15, alpha=alpha)
        
        # Plot current position with large marker
        if len(self.lons) > 0:
            self.ax.scatter(self.lons[-1], self.lats[-1], c='red', s=200, 
                          marker='*', label=f'Current', zorder=10, edgecolors='darkred', linewidth=1)
        
        # Add uncertainty circle
        if hdop > 0 and len(self.lons) > 0:
            # hdop may be unitless (typical DOP) or already in meters.
            # If hdop looks small (<50) treat as unitless and assume sigma_range~1m.
            if hdop < 50:
                sigma_range_m = 1.0
                uncertainty_m = hdop * sigma_range_m
            else:
                # If large, treat hdop as meters directly
                uncertainty_m = hdop

            # Convert meters to degrees approximation (1 deg ≈ 111000 m)
            uncertainty_deg = uncertainty_m / 111000.0

            import matplotlib.patches as patches
            circle = patches.Circle((self.lons[-1], self.lats[-1]), uncertainty_deg, 
                                   fill=False, color='red', linestyle='--', alpha=0.6, linewidth=1.5)
            self.ax.add_patch(circle)
        
        # Auto-scale with margin
        if len(self.lons) > 1:
            lon_min, lon_max = min(self.lons), max(self.lons)
            lat_min, lat_max = min(self.lats), max(self.lats)
            
            # Add margin (0.1% of range or minimum 0.0005 degrees)
            lon_range = max(lon_max - lon_min, 0.001)
            lat_range = max(lat_max - lat_min, 0.001)
            margin_lon = lon_range * 0.1
            margin_lat = lat_range * 0.1
            
            self.ax.set_xlim(lon_min - margin_lon, lon_max + margin_lon)
            self.ax.set_ylim(lat_min - margin_lat, lat_max + margin_lat)
        elif len(self.lons) == 1:
            # Single point - show a reasonable view
            self.ax.set_xlim(self.lons[0] - 0.01, self.lons[0] + 0.01)
            self.ax.set_ylim(self.lats[0] - 0.01, self.lats[0] + 0.01)
        
        self.ax.legend(loc='upper right', fontsize=9)
        self.figure.tight_layout()
        self.canvas.draw()
    
    def clear_track(self):
        """Clear the position track."""
        self.lats.clear()
        self.lons.clear()
        self.ax.clear()
        self.ax.set_xlabel("Longitude (°E)")
        self.ax.set_ylabel("Latitude (°N)")
        self.ax.set_title("GNSS Position Map")
        self.ax.grid(True, alpha=0.3, linestyle='--')
        self.canvas.draw()

    def export_to_folium(self, filename: Optional[str] = None):
        """Export current track to a folium HTML map. Returns path to HTML or None.

        Falls back gracefully if folium not installed.
        """
        try:
            import folium
        except Exception:
            return None

        if len(self.lats) == 0:
            return None

        center = (self.lats[-1], self.lons[-1])
        fmap = folium.Map(location=center, zoom_start=15)

        # Add track polyline
        coords = list(zip(self.lats, self.lons))
        folium.PolyLine(coords, color='blue', weight=3, opacity=0.7).add_to(fmap)

        # Add current marker
        folium.Marker(location=center, icon=folium.Icon(color='red', icon='star')).add_to(fmap)

        import tempfile, os
        if filename is None:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.html')
            filename = tmp.name
            tmp.close()

        fmap.save(filename)
        return os.path.abspath(filename)

    def show_in_browser(self):
        """Try to show exported folium map in a QWebEngineView dialog; fallback to default browser."""
        html_path = self.export_to_folium()
        if not html_path:
            return False

        # Try to open with QWebEngineView
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtWidgets import QDialog, QVBoxLayout

            dlg = QDialog()
            dlg.setWindowTitle('Position Map')
            layout = QVBoxLayout(dlg)
            view = QWebEngineView()
            view.load('file:///' + html_path.replace('\\', '/'))
            layout.addWidget(view)
            dlg.resize(900, 700)
            dlg.exec()
            return True
        except Exception:
            import webbrowser
            webbrowser.open('file://' + html_path)
            return True


class PositionInfoWidget(QWidget):
    """
    Display current positioning information in a table format.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        
        # Create table
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Parameter", "Value"])
        self.table.setMaximumHeight(400)
        
        # Pre-fill common parameters
        parameters = [
            "Latitude",
            "Longitude",
            "Height (WGS84)",
            "ECEF X",
            "ECEF Y",
            "ECEF Z",
            "Clock Bias",
            "Num Satellites",
            "HDOP",
            "VDOP",
            "PDOP",
            "Solution Status",
            "Convergence",
        ]
        
        self.table.setRowCount(len(parameters))
        self.parameter_rows = {}
        
        for i, param in enumerate(parameters):
            self.parameter_rows[param] = i
            item = QTableWidgetItem(param)
            item.setFont(QFont("Courier", 10))
            self.table.setItem(i, 0, item)
            
            value_item = QTableWidgetItem("--")
            value_item.setFont(QFont("Courier", 10))
            self.table.setItem(i, 1, value_item)
        
        layout.addWidget(self.table)
    
    def update_solution(self, solution):
        """Update table with new solution."""
        if solution is None:
            return
        
        updates = {
            "Latitude": f"{solution.latitude:.6f}°",
            "Longitude": f"{solution.longitude:.6f}°",
            "Height (WGS84)": f"{solution.height:.2f} m",
            "ECEF X": f"{solution.ecef_x:.2f} m",
            "ECEF Y": f"{solution.ecef_y:.2f} m",
            "ECEF Z": f"{solution.ecef_z:.2f} m",
            "Clock Bias": f"{solution.clock_bias:.2e} m",
            "Num Satellites": str(solution.num_satellites),
            "HDOP": f"{solution.hdop:.2f}",
            "VDOP": f"{solution.vdop:.2f}",
            "PDOP": f"{solution.pdop:.2f}",
            "Solution Status": solution.status.value,
            "Convergence": "Yes" if solution.convergence else "No",
        }
        
        for param, value in updates.items():
            if param in self.parameter_rows:
                row = self.parameter_rows[param]
                item = QTableWidgetItem(value)
                item.setFont(QFont("Courier", 10))
                
                # Color code status
                if param == "Solution Status":
                    if "Fixed" in value:
                        item.setForeground(QColor("green"))
                    elif "Uncertain" in value:
                        item.setForeground(QColor("orange"))
                    else:
                        item.setForeground(QColor("red"))
                
                self.table.setItem(row, 1, item)


class AccuracyWidget(QWidget):
    """
    Display accuracy metrics and DOP values.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        
        # Create figure for DOP visualization
        self.figure = Figure(figsize=(8, 4), dpi=100)
        self.ax_dop = self.figure.add_subplot(111)
        self.canvas = FigureCanvas(self.figure)
        
        layout.addWidget(self.canvas)
        
        # Variables for plotting
        self.dop_history = {
            'HDOP': [],
            'VDOP': [],
            'PDOP': [],
            'GDOP': [],
        }
        self.epochs = 0
    
    def update_solution(self, solution):
        """Update DOP values and plot."""
        if solution is None:
            return
        
        self.epochs += 1
        self.dop_history['HDOP'].append(solution.hdop)
        self.dop_history['VDOP'].append(solution.vdop)
        self.dop_history['PDOP'].append(solution.pdop)
        self.dop_history['GDOP'].append(solution.gdop)
        
        # Keep only last 300 epochs
        for key in self.dop_history:
            if len(self.dop_history[key]) > 300:
                self.dop_history[key] = self.dop_history[key][-300:]
        
        # Update plot
        self.ax_dop.clear()
        
        x = range(max(0, self.epochs - 300), self.epochs)
        
        if len(self.dop_history['HDOP']) > 0:
            self.ax_dop.plot(x, self.dop_history['HDOP'], label='HDOP', color='blue')
            self.ax_dop.plot(x, self.dop_history['VDOP'], label='VDOP', color='red')
            self.ax_dop.plot(x, self.dop_history['PDOP'], label='PDOP', color='green')
        
        self.ax_dop.set_xlabel('Epoch')
        self.ax_dop.set_ylabel('DOP Value')
        self.ax_dop.set_title('Dilution of Precision (DOP) Over Time')
        self.ax_dop.legend(loc='upper right')
        self.ax_dop.grid(True, alpha=0.3)
        self.figure.tight_layout()
        self.canvas.draw()
    
    def clear(self):
        """Clear history and plot."""
        for key in self.dop_history:
            self.dop_history[key].clear()
        self.epochs = 0
        self.ax_dop.clear()
        self.canvas.draw()


class ResidualWidget(QWidget):
    """
    Display pseudorange residuals statistics.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        
        # Create figure for residuals
        self.figure = Figure(figsize=(8, 4), dpi=100)
        self.ax = self.figure.add_subplot(111)
        self.canvas = FigureCanvas(self.figure)
        
        layout.addWidget(self.canvas)
        
        # Storage for history
        self.residuals_mean_hist = []
        self.residuals_std_hist = []
        self.residuals_max_hist = []
        self.epochs = 0
    
    def update_solution(self, solution):
        """Update residuals display."""
        if solution is None:
            return
        
        self.epochs += 1
        self.residuals_mean_hist.append(solution.residuals_mean)
        self.residuals_std_hist.append(solution.residuals_std)
        self.residuals_max_hist.append(solution.residuals_max)
        
        # Keep only last 300 epochs
        max_hist = 300
        if len(self.residuals_mean_hist) > max_hist:
            self.residuals_mean_hist = self.residuals_mean_hist[-max_hist:]
            self.residuals_std_hist = self.residuals_std_hist[-max_hist:]
            self.residuals_max_hist = self.residuals_max_hist[-max_hist:]
        
        # Update plot
        self.ax.clear()
        
        x = range(max(0, self.epochs - max_hist), self.epochs)
        
        if len(self.residuals_mean_hist) > 0:
            self.ax.plot(x, self.residuals_mean_hist, label='Mean', color='blue')
            self.ax.fill_between(x, 
                                np.array(self.residuals_mean_hist) - np.array(self.residuals_std_hist),
                                np.array(self.residuals_mean_hist) + np.array(self.residuals_std_hist),
                                alpha=0.3, color='blue', label='±σ')
            self.ax.plot(x, self.residuals_max_hist, label='Max', color='red', linestyle='--')
        
        self.ax.set_xlabel('Epoch')
        self.ax.set_ylabel('Residual (m)')
        self.ax.set_title('Pseudorange Residuals Statistics')
        self.ax.legend(loc='upper right')
        self.ax.grid(True, alpha=0.3)
        self.ax.axhline(y=0, color='k', linestyle='-', linewidth=0.5)
        
        self.figure.tight_layout()
        self.canvas.draw()
    
    def clear(self):
        """Clear history and plot."""
        self.residuals_mean_hist.clear()
        self.residuals_std_hist.clear()
        self.residuals_max_hist.clear()
        self.epochs = 0
        self.ax.clear()
        self.canvas.draw()
