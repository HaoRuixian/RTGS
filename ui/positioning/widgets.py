"""
Positioning module UI widgets - map and charts for position visualization.
"""

from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import numpy as np
from typing import List, Optional


MAX_HISTORY = 300


def _build_theme():
    palette = QApplication.palette()
    is_dark = palette.color(palette.ColorRole.Window).lightness() < 128
    return {
        "bg": "#161A23" if is_dark else "#FFFFFF",
        "fg": "#E2E8F0" if is_dark else "#0F172A",
        "muted": "#94A3B8" if is_dark else "#64748B",
        "grid": "#1D2435" if is_dark else "#CBD5E1",
        "accent": "#3B82F6" if is_dark else "#2563EB",
        "east": "#2563EB",
        "north": "#5E8C61",
        "up": "#D96459",
        "current": "#D96459",
        "fixed": "#2A692D",
        "unfixed": "#B7791F",
        "nofix": "#6D2F2B",
    }


def _style_axis(ax, theme):
    ax.set_facecolor(theme["bg"])
    ax.grid(True, color=theme["grid"], alpha=0.45, linestyle=":")
    ax.tick_params(colors=theme["muted"], labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(theme["grid"])
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def format_solution_status(status) -> str:
    raw = getattr(status, "value", str(status))
    if raw == "Uncertain":
        return "Unfixed"
    return raw


def _status_color(status, theme):
    text = format_solution_status(status)
    if text == "Fixed":
        return QColor(theme["fixed"])
    if text == "Unfixed":
        return QColor(theme["unfixed"])
    return QColor(theme["nofix"])


def _make_font(family: str, point_size: int, weight: QFont.Weight | None = None) -> QFont:
    font = QFont(family, point_size)
    if weight is not None:
        font.setWeight(weight)
    return font


def _finite(value) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except Exception:
        return False


class LegacyPositionMapWidget(QWidget):
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


class PositionMapWidget(QWidget):
    """Position track display with LLH and ECEF XYZ modes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme = _build_theme()
        self.display_mode = "LLH"
        self.samples = []

        self.figure = Figure(figsize=(10, 8), dpi=100, facecolor=self.theme["bg"])
        self.ax = self.figure.add_subplot(111)
        self.canvas = FigureCanvas(self.figure)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)

        self._draw_empty()
        self.figure.tight_layout()

    def set_display_mode(self, mode: str):
        mode = "XYZ" if mode == "XYZ" else "LLH"
        if self.display_mode == mode:
            return
        self.display_mode = mode
        self._redraw()

    def update_solution(self, solution):
        """Append a positioning solution and redraw the track."""
        if solution is None:
            return

        self.samples.append(
            {
                "lat": float(getattr(solution, "latitude", np.nan)),
                "lon": float(getattr(solution, "longitude", np.nan)),
                "height": float(getattr(solution, "height", np.nan)),
                "x": float(getattr(solution, "ecef_x", np.nan)),
                "y": float(getattr(solution, "ecef_y", np.nan)),
                "z": float(getattr(solution, "ecef_z", np.nan)),
                "hdop": float(getattr(solution, "hdop", 0.0) or 0.0),
            }
        )
        if len(self.samples) > MAX_HISTORY:
            self.samples = self.samples[-MAX_HISTORY:]
        self._redraw()

    def update_track(
        self,
        latitude: float,
        longitude: float,
        hdop: float = 0.0,
        ecef_x: float | None = None,
        ecef_y: float | None = None,
        ecef_z: float | None = None,
        height: float | None = None,
    ):
        """Compatibility wrapper for callers that pass coordinates directly."""
        self.samples.append(
            {
                "lat": float(latitude),
                "lon": float(longitude),
                "height": float(height) if height is not None else np.nan,
                "x": float(ecef_x) if ecef_x is not None else np.nan,
                "y": float(ecef_y) if ecef_y is not None else np.nan,
                "z": float(ecef_z) if ecef_z is not None else np.nan,
                "hdop": float(hdop or 0.0),
            }
        )
        if len(self.samples) > MAX_HISTORY:
            self.samples = self.samples[-MAX_HISTORY:]
        self._redraw()

    def clear_track(self):
        """Clear the position track."""
        self.samples.clear()
        self._draw_empty()
        self.canvas.draw_idle()

    def export_to_folium(self, filename: Optional[str] = None):
        """Export the LLH track to a folium HTML map."""
        try:
            import folium
        except Exception:
            return None

        geo_samples = [
            item
            for item in self.samples
            if _finite(item.get("lat")) and _finite(item.get("lon"))
        ]
        if not geo_samples:
            return None

        center = (geo_samples[-1]["lat"], geo_samples[-1]["lon"])
        fmap = folium.Map(location=center, zoom_start=15)
        coords = [(item["lat"], item["lon"]) for item in geo_samples]
        folium.PolyLine(coords, color="blue", weight=3, opacity=0.7).add_to(fmap)
        folium.Marker(location=center, icon=folium.Icon(color="red", icon="star")).add_to(fmap)

        import tempfile, os
        if filename is None:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".html")
            filename = tmp.name
            tmp.close()

        fmap.save(filename)
        return os.path.abspath(filename)

    def show_in_browser(self):
        """Try to show exported folium map in a QWebEngineView dialog; fallback to default browser."""
        html_path = self.export_to_folium()
        if not html_path:
            return False

        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtWidgets import QDialog, QVBoxLayout

            dlg = QDialog()
            dlg.setWindowTitle("Position Map")
            layout = QVBoxLayout(dlg)
            view = QWebEngineView()
            view.load("file:///" + html_path.replace("\\", "/"))
            layout.addWidget(view)
            dlg.resize(900, 700)
            dlg.exec()
            return True
        except Exception:
            import webbrowser
            webbrowser.open("file://" + html_path)
            return True

    def _draw_empty(self):
        self.ax.clear()
        _style_axis(self.ax, self.theme)
        if self.display_mode == "XYZ":
            self.ax.set_xlabel("ECEF X (m)", color=self.theme["muted"])
            self.ax.set_ylabel("ECEF Y (m)", color=self.theme["muted"])
            self.ax.set_title("ECEF XYZ Position Track", color=self.theme["fg"], fontsize=10, fontweight="bold")
        else:
            self.ax.set_xlabel("Longitude (deg)", color=self.theme["muted"])
            self.ax.set_ylabel("Latitude (deg)", color=self.theme["muted"])
            self.ax.set_title("LLH Position Track", color=self.theme["fg"], fontsize=10, fontweight="bold")
        self.ax.text(
            0.5,
            0.5,
            "Waiting for positioning solution...",
            transform=self.ax.transAxes,
            ha="center",
            va="center",
            color=self.theme["muted"],
            fontsize=11,
        )

    def _redraw(self):
        valid_samples = self._valid_samples()
        if not valid_samples:
            self._draw_empty()
            self.figure.tight_layout()
            self.canvas.draw_idle()
            return

        xs, ys, title = self._coordinates_for_mode(valid_samples)
        if not xs or not ys:
            self._draw_empty()
            self.figure.tight_layout()
            self.canvas.draw_idle()
            return

        self.ax.clear()
        _style_axis(self.ax, self.theme)
        self.ax.set_title(title, color=self.theme["fg"], fontsize=10, fontweight="bold")

        if self.display_mode == "XYZ":
            self.ax.set_xlabel("ECEF X (m)", color=self.theme["muted"])
            self.ax.set_ylabel("ECEF Y (m)", color=self.theme["muted"])
            try:
                self.ax.ticklabel_format(style="plain", useOffset=False)
            except Exception:
                pass
        else:
            self.ax.set_xlabel("Longitude (deg)", color=self.theme["muted"])
            self.ax.set_ylabel("Latitude (deg)", color=self.theme["muted"])

        if len(xs) > 1:
            self.ax.plot(xs, ys, color=self.theme["accent"], alpha=0.75, linewidth=1.6, label="Track")
            start_idx = max(0, len(xs) - 60)
            denom = max(1, (len(xs) - 1) - start_idx)
            for i in range(start_idx, len(xs) - 1):
                alpha = 0.3 + 0.7 * ((i - start_idx) / denom)
                self.ax.scatter(xs[i], ys[i], c=self.theme["accent"], s=18, alpha=max(0.0, min(1.0, alpha)))

        self.ax.scatter(
            xs[-1],
            ys[-1],
            c=self.theme["current"],
            s=180,
            marker="*",
            label="Current",
            zorder=10,
            edgecolors=self.theme["fg"],
            linewidth=0.8,
        )

        current = valid_samples[-1]
        hdop = current.get("hdop", 0.0)
        if self.display_mode == "LLH" and hdop > 0:
            uncertainty_m = hdop if hdop >= 50 else hdop * 1.0
            uncertainty_deg = uncertainty_m / 111000.0
            import matplotlib.patches as patches
            circle = patches.Circle(
                (xs[-1], ys[-1]),
                uncertainty_deg,
                fill=False,
                color=self.theme["current"],
                linestyle="--",
                alpha=0.6,
                linewidth=1.2,
            )
            self.ax.add_patch(circle)

        self._autoscale(xs, ys)
        legend = self.ax.legend(loc="upper right", fontsize=8, frameon=False)
        if legend:
            for text in legend.get_texts():
                text.set_color(self.theme["muted"])
        self.figure.tight_layout()
        self.canvas.draw_idle()

    def _valid_samples(self):
        if self.display_mode == "XYZ":
            return [
                item for item in self.samples
                if _finite(item.get("x")) and _finite(item.get("y")) and _finite(item.get("z"))
            ]
        return [
            item for item in self.samples
            if _finite(item.get("lat")) and _finite(item.get("lon")) and _finite(item.get("height"))
        ]

    def _coordinates_for_mode(self, samples):
        current = samples[-1]
        if self.display_mode == "XYZ":
            xs = [item["x"] for item in samples]
            ys = [item["y"] for item in samples]
            title = (
                "ECEF XYZ Track - "
                f"X {current['x']:.3f} m, Y {current['y']:.3f} m, Z {current['z']:.3f} m"
            )
            return xs, ys, title

        xs = [item["lon"] for item in samples]
        ys = [item["lat"] for item in samples]
        title = (
            "LLH Track - "
            f"Lon {current['lon']:.8f} deg, Lat {current['lat']:.8f} deg, H {current['height']:.3f} m"
        )
        return xs, ys, title

    def _autoscale(self, xs, ys):
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        min_range = 1.0 if self.display_mode == "XYZ" else 0.0005
        x_range = max(x_max - x_min, min_range)
        y_range = max(y_max - y_min, min_range)
        self.ax.set_xlim(x_min - x_range * 0.12, x_max + x_range * 0.12)
        self.ax.set_ylim(y_min - y_range * 0.12, y_max + y_range * 0.12)


class LegacyPositionInfoWidget(QWidget):
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

    def clear(self):
        """Reset the table to placeholder values."""
        for row in range(self.table.rowCount()):
            value_item = QTableWidgetItem("--")
            value_item.setFont(QFont("Courier", 10))
            self.table.setItem(row, 1, value_item)


class PositionInfoWidget(QWidget):
    """Current positioning information with switchable coordinate rows."""

    COMMON_PARAMETERS = [
        "Clock Bias",
        "Num Satellites",
        "HDOP",
        "VDOP",
        "PDOP",
        "Solution Status",
        "Convergence",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.display_mode = "LLH"
        self.current_solution = None
        self.theme = _build_theme()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Parameter", "Value"])
        self.table.setMaximumHeight(400)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        self.parameter_rows = {}
        self._rebuild_rows()

    def set_display_mode(self, mode: str):
        mode = "XYZ" if mode == "XYZ" else "LLH"
        if self.display_mode == mode:
            return
        self.display_mode = mode
        self._rebuild_rows()
        if self.current_solution is not None:
            self.update_solution(self.current_solution)

    def update_solution(self, solution):
        """Update table with a new solution."""
        if solution is None:
            return

        self.current_solution = solution
        if self.display_mode == "XYZ":
            updates = {
                "ECEF X": f"{solution.ecef_x:.3f} m",
                "ECEF Y": f"{solution.ecef_y:.3f} m",
                "ECEF Z": f"{solution.ecef_z:.3f} m",
            }
        else:
            updates = {
                "Latitude": f"{solution.latitude:.8f} deg",
                "Longitude": f"{solution.longitude:.8f} deg",
                "Height (WGS84)": f"{solution.height:.3f} m",
            }

        updates.update(
            {
                "Clock Bias": f"{solution.clock_bias:.3e} m",
                "Num Satellites": str(solution.num_satellites),
                "HDOP": f"{solution.hdop:.2f}",
                "VDOP": f"{solution.vdop:.2f}",
                "PDOP": f"{solution.pdop:.2f}",
                "Solution Status": format_solution_status(solution.status),
                "Convergence": "Yes" if solution.convergence else "No",
            }
        )

        for param, value in updates.items():
            if param not in self.parameter_rows:
                continue
            row = self.parameter_rows[param]
            item = QTableWidgetItem(value)
            item.setFont(_make_font("Consolas", 10))
            if param == "Solution Status":
                item.setForeground(_status_color(solution.status, self.theme))
                item.setFont(_make_font("Consolas", 10, QFont.Weight.Bold))
            self.table.setItem(row, 1, item)

    def clear(self):
        """Reset the table to placeholder values."""
        self.current_solution = None
        for row in range(self.table.rowCount()):
            value_item = QTableWidgetItem("--")
            value_item.setFont(_make_font("Consolas", 10))
            self.table.setItem(row, 1, value_item)

    def _rebuild_rows(self):
        coordinate_rows = (
            ["ECEF X", "ECEF Y", "ECEF Z"]
            if self.display_mode == "XYZ"
            else ["Latitude", "Longitude", "Height (WGS84)"]
        )
        parameters = coordinate_rows + self.COMMON_PARAMETERS
        self.table.setRowCount(len(parameters))
        self.parameter_rows = {}

        for i, param in enumerate(parameters):
            self.parameter_rows[param] = i
            label_item = QTableWidgetItem(param)
            label_item.setFont(_make_font("Segoe UI", 10, QFont.Weight.DemiBold))
            self.table.setItem(i, 0, label_item)

            value_item = QTableWidgetItem("--")
            value_item.setFont(_make_font("Consolas", 10))
            self.table.setItem(i, 1, value_item)


class AccuracyWidget(QWidget):
    """
    Display accuracy metrics and DOP values.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme = _build_theme()
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Create figure for DOP visualization
        self.figure = Figure(figsize=(8, 4), dpi=100, facecolor=self.theme["bg"])
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
        self._draw_empty()
    
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
        _style_axis(self.ax_dop, self.theme)
        
        x = range(max(0, self.epochs - 300), self.epochs)
        
        if len(self.dop_history['HDOP']) > 0:
            self.ax_dop.plot(x, self.dop_history['HDOP'], label='HDOP', color=self.theme["accent"], linewidth=1.5)
            self.ax_dop.plot(x, self.dop_history['VDOP'], label='VDOP', color=self.theme["up"], linewidth=1.5)
            self.ax_dop.plot(x, self.dop_history['PDOP'], label='PDOP', color=self.theme["north"], linewidth=1.5)
        
        self.ax_dop.set_xlabel('Epoch', color=self.theme["muted"])
        self.ax_dop.set_ylabel('DOP Value', color=self.theme["muted"])
        self.ax_dop.set_title('Dilution of Precision (DOP) Over Time', color=self.theme["fg"], fontsize=10, fontweight="bold")
        legend = self.ax_dop.legend(loc='upper right', frameon=False, fontsize=8)
        if legend:
            for text in legend.get_texts():
                text.set_color(self.theme["muted"])
        self.figure.tight_layout()
        self.canvas.draw_idle()
    
    def clear(self):
        """Clear history and plot."""
        for key in self.dop_history:
            self.dop_history[key].clear()
        self.epochs = 0
        self._draw_empty()
        self.canvas.draw_idle()

    def _draw_empty(self):
        self.ax_dop.clear()
        _style_axis(self.ax_dop, self.theme)
        self.ax_dop.set_xlabel('Epoch', color=self.theme["muted"])
        self.ax_dop.set_ylabel('DOP Value', color=self.theme["muted"])
        self.ax_dop.set_title('Dilution of Precision (DOP) Over Time', color=self.theme["fg"], fontsize=10, fontweight="bold")


class LegacyResidualWidget(QWidget):
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


class ResidualWidget(QWidget):
    """Three-direction position residual sequence."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme = _build_theme()
        self.display_mode = "LLH"
        self.solutions = []
        self.epochs = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.figure = Figure(figsize=(8, 4), dpi=100, facecolor=self.theme["bg"])
        self.ax = self.figure.add_subplot(111)
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)

        self._draw_empty()

    def set_display_mode(self, mode: str):
        mode = "XYZ" if mode == "XYZ" else "LLH"
        if self.display_mode == mode:
            return
        self.display_mode = mode
        self._redraw()

    def update_solution(self, solution):
        """Update residual sequence using offsets from the first visible solution."""
        if solution is None:
            return
        if format_solution_status(getattr(solution, "status", "")) == "No Fix":
            return

        self.epochs += 1
        self.solutions.append(solution)
        if len(self.solutions) > MAX_HISTORY:
            self.solutions = self.solutions[-MAX_HISTORY:]
        self._redraw()

    def clear(self):
        """Clear history and plot."""
        self.solutions.clear()
        self.epochs = 0
        self._draw_empty()
        self.canvas.draw_idle()

    def _draw_empty(self):
        self.ax.clear()
        _style_axis(self.ax, self.theme)
        self.ax.set_xlabel("Epoch", color=self.theme["muted"])
        self.ax.set_ylabel("Offset from first solution (m)", color=self.theme["muted"])
        title = "Position Residual Sequence (ECEF XYZ)" if self.display_mode == "XYZ" else "Position Residual Sequence (East/North/Up)"
        self.ax.set_title(title, color=self.theme["fg"], fontsize=10, fontweight="bold")
        self.ax.axhline(y=0, color=self.theme["grid"], linestyle="-", linewidth=0.8)
        self.ax.text(
            0.5,
            0.5,
            "Waiting for fixed/unfixed solution...",
            transform=self.ax.transAxes,
            ha="center",
            va="center",
            color=self.theme["muted"],
            fontsize=11,
        )

    def _redraw(self):
        if not self.solutions:
            self._draw_empty()
            self.figure.tight_layout()
            self.canvas.draw_idle()
            return

        series = self._series_for_mode()
        if not series:
            self._draw_empty()
            self.figure.tight_layout()
            self.canvas.draw_idle()
            return

        self.ax.clear()
        _style_axis(self.ax, self.theme)
        self.ax.axhline(y=0, color=self.theme["grid"], linestyle="-", linewidth=0.8)
        x = range(self.epochs - len(next(iter(series.values()))) + 1, self.epochs + 1)

        colors = [self.theme["east"], self.theme["north"], self.theme["up"]]
        for (label, values), color in zip(series.items(), colors):
            self.ax.plot(x, values, label=label, color=color, linewidth=1.6)

        self.ax.set_xlabel("Epoch", color=self.theme["muted"])
        self.ax.set_ylabel("Offset from first solution (m)", color=self.theme["muted"])
        title = "Position Residual Sequence (ECEF XYZ)" if self.display_mode == "XYZ" else "Position Residual Sequence (East/North/Up)"
        self.ax.set_title(title, color=self.theme["fg"], fontsize=10, fontweight="bold")

        all_values = np.array([value for values in series.values() for value in values], dtype=float)
        if all_values.size:
            max_abs = max(0.05, float(np.nanmax(np.abs(all_values))))
            self.ax.set_ylim(-max_abs * 1.2, max_abs * 1.2)

        legend = self.ax.legend(loc="upper right", frameon=False, fontsize=8)
        if legend:
            for text in legend.get_texts():
                text.set_color(self.theme["muted"])

        self.figure.tight_layout()
        self.canvas.draw_idle()

    def _series_for_mode(self):
        if self.display_mode == "XYZ":
            valid = [
                sol for sol in self.solutions
                if _finite(getattr(sol, "ecef_x", np.nan))
                and _finite(getattr(sol, "ecef_y", np.nan))
                and _finite(getattr(sol, "ecef_z", np.nan))
            ]
            if not valid:
                return {}
            ref = valid[0]
            return {
                "dX": [float(sol.ecef_x - ref.ecef_x) for sol in valid],
                "dY": [float(sol.ecef_y - ref.ecef_y) for sol in valid],
                "dZ": [float(sol.ecef_z - ref.ecef_z) for sol in valid],
            }

        valid = [
            sol for sol in self.solutions
            if _finite(getattr(sol, "latitude", np.nan))
            and _finite(getattr(sol, "longitude", np.nan))
            and _finite(getattr(sol, "height", np.nan))
        ]
        if not valid:
            return {}

        ref = valid[0]
        ref_lat_rad = np.radians(float(ref.latitude))
        return {
            "East": [
                float((sol.longitude - ref.longitude) * 111000.0 * np.cos(ref_lat_rad))
                for sol in valid
            ],
            "North": [
                float((sol.latitude - ref.latitude) * 111000.0)
                for sol in valid
            ],
            "Up": [
                float(sol.height - ref.height)
                for sol in valid
            ],
        }
