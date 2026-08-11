"""
Positioning module UI widgets - map and charts for position visualization.
"""

from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QCheckBox,
    QDoubleSpinBox,
    QGridLayout,
    QHeaderView,
    QSizePolicy,
    QStyle,
    QToolButton,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
)
from PySide6.QtCore import QObject, QStandardPaths, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter, ScalarFormatter
from datetime import datetime, timedelta, timezone
import io
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen
import matplotlib.pyplot as plt
import numpy as np
from typing import List, Optional

from core.positioning_models import PositioningMode


MAX_HISTORY = 300
WEB_MERCATOR_RADIUS_M = 6_378_137.0
WEB_MERCATOR_HALF_WORLD_M = math.pi * WEB_MERCATOR_RADIUS_M


def _lonlat_to_web_mercator(lon: float, lat: float) -> tuple[float, float]:
    lat = max(-85.05112878, min(85.05112878, float(lat)))
    x = WEB_MERCATOR_RADIUS_M * math.radians(float(lon))
    y = WEB_MERCATOR_RADIUS_M * math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0))
    return x, y


def _web_mercator_to_lonlat(x: float, y: float) -> tuple[float, float]:
    lon = math.degrees(float(x) / WEB_MERCATOR_RADIUS_M)
    lat = math.degrees(2.0 * math.atan(math.exp(float(y) / WEB_MERCATOR_RADIUS_M)) - math.pi / 2.0)
    return lon, lat


class _TileSignals(QObject):
    tiles_ready = Signal(int, object, object)


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


def _solution_epoch_time(solution) -> datetime:
    """Return a naive UTC datetime suitable for Matplotlib date axes."""
    epoch_time = getattr(solution, "epoch_time", None)
    if isinstance(epoch_time, datetime):
        if epoch_time.tzinfo is not None:
            return epoch_time.astimezone(timezone.utc).replace(tzinfo=None)
        return epoch_time

    gps_week = int(getattr(solution, "gps_week", 0) or 0)
    gps_sow = float(getattr(solution, "timestamp", 0.0) or 0.0)
    if gps_week > 0:
        return datetime(1980, 1, 6) + timedelta(weeks=gps_week, seconds=gps_sow - 18.0)
    if gps_sow > 1_000_000_000.0:
        return datetime.utcfromtimestamp(gps_sow)
    return datetime.utcnow()


def _configure_time_axis(ax, theme) -> None:
    locator = mdates.AutoDateLocator(minticks=3, maxticks=6)
    ax.xaxis.set_major_locator(locator)

    def numeric_utc_label(value, _position=None):
        span_seconds = abs(float(ax.get_xlim()[1] - ax.get_xlim()[0])) * 86400.0
        tick_time = mdates.num2date(value, tz=timezone.utc)
        if span_seconds >= 180.0 * 86400.0:
            return tick_time.strftime("%Y-%m")
        if span_seconds >= 86400.0:
            return tick_time.strftime("%m-%d")
        if span_seconds >= 6.0 * 3600.0:
            return tick_time.strftime("%m-%d\n%H:%M")
        if span_seconds >= 5.0 * 60.0:
            return tick_time.strftime("%H:%M")
        return tick_time.strftime("%H:%M:%S")

    ax.xaxis.set_major_formatter(FuncFormatter(numeric_utc_label))
    ax.xaxis.get_offset_text().set_visible(False)
    ax.set_xlabel("UTC time", color=theme["muted"], fontsize=7)


def _set_time_limits(ax, times: List[datetime]) -> None:
    if not times:
        return
    first = times[0]
    last = times[-1]
    if last <= first:
        padding = timedelta(seconds=30)
    else:
        padding = max(timedelta(seconds=1), (last - first) * 0.03)
    ax.set_xlim(first - padding, last + padding)


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


def _format_counts_value(counts) -> str:
    if not counts:
        return "--"
    try:
        items = sorted(counts.items())
    except Exception:
        return str(counts)
    return ", ".join(f"{key}:{int(value)}" for key, value in items)


def _format_satellite_list(satellites, per_line: int = 8) -> str:
    if not satellites:
        return "--"
    ordered = sorted(str(item) for item in satellites)
    lines = [
        ", ".join(ordered[index : index + per_line])
        for index in range(0, len(ordered), per_line)
    ]
    return "\n".join(lines)


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
    """Interactive track display with persistent zoom and drag-to-pan."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme = _build_theme()
        self.display_mode = "LLH"
        self.samples = []
        self._pan_anchor = None
        self._base_map_enabled = True
        self._tile_source = "osm"
        self._tile_cache = {}
        self._tile_cache_lock = threading.Lock()
        cache_root = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
        self._tile_cache_dir = Path(cache_root or (Path.home() / ".cache" / "RTGS")) / "map_tiles" / "osm"
        self._tile_cache_dir.mkdir(parents=True, exist_ok=True)
        self._tile_artists = []
        self._tile_request_key = None
        self._pending_tile_signature = None
        self._tile_generation = 0
        self._tile_signals = _TileSignals(self)
        self._tile_signals.tiles_ready.connect(self._on_tiles_ready)
        self._tile_debounce_timer = QTimer(self)
        self._tile_debounce_timer.setSingleShot(True)
        self._tile_debounce_timer.setInterval(140)
        self._tile_debounce_timer.timeout.connect(self._start_pending_tile_request)
        self._layout_refresh_timer = QTimer(self)
        self._layout_refresh_timer.setSingleShot(True)
        self._layout_refresh_timer.setInterval(0)
        self._layout_refresh_timer.timeout.connect(self._sync_canvas_layout)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("MapHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 6, 6, 6)
        header_layout.setSpacing(8)
        title = QLabel("Position track")
        title.setObjectName("SectionTitle")
        self.position_summary = QLabel("Waiting for solution")
        self.position_summary.setProperty("class", "muted")
        self.position_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        header_layout.addWidget(title)
        header_layout.addWidget(self.position_summary)
        self.tile_status = QLabel("")
        self.tile_status.setProperty("class", "muted")
        header_layout.addWidget(self.tile_status)
        header_layout.addStretch()

        self.follow_button = QToolButton()
        self.follow_button.setCheckable(True)
        self.follow_button.setChecked(True)
        self.follow_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogYesButton))
        self.follow_button.setToolTip("Follow latest position")
        self.follow_button.toggled.connect(self._on_follow_changed)
        header_layout.addWidget(self.follow_button)

        reset_button = QToolButton()
        reset_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        reset_button.setToolTip("Fit complete track")
        reset_button.clicked.connect(self.reset_view)
        header_layout.addWidget(reset_button)

        self.base_map_button = QToolButton()
        self.base_map_button.setText("Base map")
        self.base_map_button.setCheckable(True)
        self.base_map_button.setChecked(True)
        self.base_map_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.base_map_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton))
        self.base_map_button.setToolTip("WGS84 OpenStreetMap tiles without GCJ-02 coordinate offset")
        self.base_map_button.toggled.connect(self._on_base_map_toggled)
        header_layout.addWidget(self.base_map_button)
        layout.addWidget(header)

        self.figure = Figure(figsize=(10, 8), dpi=100, facecolor=self.theme["bg"])
        self.ax = self.figure.add_subplot(111)
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        self.canvas.mpl_connect("resize_event", self._on_canvas_resize)
        self._initialize_plot()
        self._layout_refresh_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_layout_refresh_timer"):
            self._layout_refresh_timer.start()

    def _sync_canvas_layout(self):
        if not hasattr(self, "track_line"):
            return
        self._apply_map_axis_style()
        if self.samples:
            self._redraw(force_autoscale=self.follow_button.isChecked())
        else:
            self.canvas.draw_idle()

    def set_display_mode(self, mode: str):
        mode = "XYZ" if mode == "XYZ" else "LLH"
        if self.display_mode == mode:
            return
        self.display_mode = mode
        self.follow_button.setChecked(True)
        self._initialize_plot()
        self._redraw(force_autoscale=True)

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
        self.position_summary.setText("Waiting for solution")
        self.follow_button.setChecked(True)
        self._initialize_plot()
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

    def _initialize_plot(self):
        self._tile_generation += 1
        self._tile_request_key = None
        self._pending_tile_signature = None
        self._tile_debounce_timer.stop()
        self._tile_artists = []
        self.ax.clear()
        _style_axis(self.ax, self.theme)
        if self.display_mode == "XYZ":
            self.ax.set_aspect("auto")
            self.ax.set_xlabel("ECEF X (m)", color=self.theme["muted"])
            self.ax.set_ylabel("ECEF Y (m)", color=self.theme["muted"])
            self.ax.xaxis.set_major_formatter(ScalarFormatter(useOffset=False))
            self.ax.yaxis.set_major_formatter(ScalarFormatter(useOffset=False))
        else:
            # Fill the available rectangle.  Geographic scale remains uniform
            # because _fit_map_view_aspect adjusts the data limits to the
            # rendered axes ratio.
            self.ax.set_aspect("auto")
            self.ax.set_xlabel("Longitude (deg)", color=self.theme["muted"])
            self.ax.set_ylabel("Latitude (deg)", color=self.theme["muted"])
            self.ax.xaxis.set_major_formatter(
                FuncFormatter(lambda value, _pos: f"{_web_mercator_to_lonlat(value, 0.0)[0]:.5f}")
            )
            self.ax.yaxis.set_major_formatter(
                FuncFormatter(lambda value, _pos: f"{_web_mercator_to_lonlat(0.0, value)[1]:.5f}")
            )
        self._apply_map_axis_style()
        self.track_outline, = self.ax.plot(
            [], [], color="#FFFFFF", alpha=0.92, linewidth=4.2,
            solid_capstyle="round", solid_joinstyle="round", zorder=7,
        )
        self.track_line, = self.ax.plot(
            [], [], color=self.theme["accent"], alpha=1.0, linewidth=2.2,
            solid_capstyle="round", solid_joinstyle="round", zorder=8,
        )
        self.history_points, = self.ax.plot(
            [], [], linestyle="none", marker="o", markersize=4.0,
            markerfacecolor=self.theme["accent"], markeredgecolor="#FFFFFF",
            markeredgewidth=0.6, alpha=0.82, zorder=9,
        )
        self.start_point, = self.ax.plot(
            [], [], linestyle="none", marker="s", markersize=6,
            markerfacecolor="#FFFFFF", markeredgecolor=self.theme["accent"],
            markeredgewidth=1.4, zorder=9,
        )
        self.current_point, = self.ax.plot(
            [], [], linestyle="none", marker="o", markersize=8,
            markerfacecolor=self.theme["current"], markeredgecolor=self.theme["fg"],
            markeredgewidth=0.8, zorder=10,
        )
        from matplotlib.patches import Circle
        self.uncertainty_circle = Circle(
            (0, 0), 0, fill=False, color=self.theme["current"],
            linestyle="--", alpha=0.55, linewidth=1.1, visible=False,
        )
        self.ax.add_patch(self.uncertainty_circle)
        self.empty_text = self.ax.text(
            0.5,
            0.5,
            "Waiting for positioning solution...",
            transform=self.ax.transAxes,
            ha="center",
            va="center",
            color=self.theme["muted"],
            fontsize=10,
        )
        self.map_attribution = self.ax.text(
            0.995, 0.008, "(c) OpenStreetMap contributors",
            transform=self.ax.transAxes, ha="right", va="bottom",
            color=self.theme["muted"], fontsize=6, zorder=20,
            visible=self.display_mode == "LLH" and self._base_map_enabled,
        )
        self.scale_bar, = self.ax.plot(
            [], [], color=self.theme["fg"], linewidth=2.5,
            marker="|", markersize=7, zorder=20,
            visible=self.display_mode == "LLH",
        )
        self.scale_label = self.ax.text(
            0.0, 0.0, "", ha="center", va="bottom",
            color=self.theme["fg"], fontsize=7, fontweight="bold",
            zorder=20, visible=self.display_mode == "LLH",
        )
        self.north_label = self.ax.text(
            0.018, 0.975, "N\n↑", transform=self.ax.transAxes,
            ha="center", va="top", color=self.theme["fg"],
            fontsize=8, fontweight="bold", zorder=20,
            visible=self.display_mode == "LLH",
        )

    def _apply_map_axis_style(self):
        if self.display_mode == "LLH" and self._base_map_enabled:
            self.ax.set_aspect("auto")
            self.ax.set_axis_off()
            self.ax.grid(False)
            self.figure.subplots_adjust(left=0.002, right=0.998, bottom=0.002, top=0.998)
            return
        self.ax.set_axis_on()
        self.ax.set_aspect("auto")
        _style_axis(self.ax, self.theme)
        self.figure.subplots_adjust(left=0.10, right=0.985, bottom=0.12, top=0.97)

    def _redraw(self, force_autoscale=False):
        valid_samples = self._valid_samples()
        if not valid_samples:
            self.track_outline.set_data([], [])
            self.track_line.set_data([], [])
            self.history_points.set_data([], [])
            self.start_point.set_data([], [])
            self.current_point.set_data([], [])
            self.empty_text.set_visible(True)
            self.canvas.draw_idle()
            return

        xs, ys, summary = self._coordinates_for_mode(valid_samples)
        if not xs or not ys:
            self.canvas.draw_idle()
            return
        self.empty_text.set_visible(False)
        self.position_summary.setText(summary)
        self.track_outline.set_data(xs, ys)
        self.track_line.set_data(xs, ys)
        self.history_points.set_data(xs[-120:-1], ys[-120:-1])
        if len(xs) > 1:
            self.start_point.set_data([xs[0]], [ys[0]])
        else:
            self.start_point.set_data([], [])
        self.current_point.set_data([xs[-1]], [ys[-1]])

        current = valid_samples[-1]
        hdop = current.get("hdop", 0.0)
        if self.display_mode == "LLH" and hdop > 0:
            uncertainty_m = hdop if hdop >= 50 else hdop * 1.0
            self.uncertainty_circle.center = (xs[-1], ys[-1])
            latitude_scale = max(math.cos(math.radians(float(current["lat"]))), 0.1)
            self.uncertainty_circle.set_radius(uncertainty_m / latitude_scale)
            self.uncertainty_circle.set_visible(True)
        else:
            self.uncertainty_circle.set_visible(False)

        if force_autoscale or self.follow_button.isChecked():
            self._autoscale(xs, ys)
        if self.display_mode == "LLH":
            self._fit_map_view_aspect()
            self._update_scale_bar()
        if self.display_mode == "LLH" and self._base_map_enabled:
            self._request_tiles_for_view()
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
            summary = f"X {current['x']:.3f}  Y {current['y']:.3f}  Z {current['z']:.3f} m"
            return xs, ys, summary

        projected = [
            _lonlat_to_web_mercator(item["lon"], item["lat"])
            for item in samples
        ]
        xs = [point[0] for point in projected]
        ys = [point[1] for point in projected]
        summary = f"{current['lat']:.7f}, {current['lon']:.7f}   H {current['height']:.2f} m"
        return xs, ys, summary

    def _autoscale(self, xs, ys):
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        if self.display_mode == "XYZ":
            min_range = 1.0
            ground_to_map = 1.0
        else:
            _lon, center_lat = _web_mercator_to_lonlat(
                (x_min + x_max) / 2.0, (y_min + y_max) / 2.0
            )
            ground_to_map = 1.0 / max(math.cos(math.radians(center_lat)), 0.1)
            min_range = (60.0 if self._base_map_enabled else 30.0) * ground_to_map
        x_range = max(x_max - x_min, min_range)
        y_range = max(y_max - y_min, min_range)
        if self.display_mode == "LLH" and self._base_map_enabled:
            margin_x = max(x_range * 0.16, 8.0 * ground_to_map)
            margin_y = max(y_range * 0.16, 8.0 * ground_to_map)
        else:
            margin_x = x_range * 0.16
            margin_y = y_range * 0.16
        center_x = (x_min + x_max) / 2.0
        center_y = (y_min + y_max) / 2.0
        view_x_span = x_range + 2.0 * margin_x
        view_y_span = y_range + 2.0 * margin_y
        self.ax.set_xlim(center_x - view_x_span / 2.0, center_x + view_x_span / 2.0)
        self.ax.set_ylim(center_y - view_y_span / 2.0, center_y + view_y_span / 2.0)

    def _fit_map_view_aspect(self):
        if self.display_mode != "LLH":
            return
        x0, x1 = self.ax.get_xlim()
        y0, y1 = self.ax.get_ylim()
        x_span = max(abs(x1 - x0), 1e-9)
        y_span = max(abs(y1 - y0), 1e-9)
        target = max(0.1, float(self.ax.bbox.width) / max(float(self.ax.bbox.height), 1.0))
        center_x, center_y = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        if x_span / y_span < target:
            x_span = y_span * target
        else:
            y_span = x_span / target
        self.ax.set_xlim(center_x - x_span / 2.0, center_x + x_span / 2.0)
        self.ax.set_ylim(center_y - y_span / 2.0, center_y + y_span / 2.0)

    def _update_scale_bar(self):
        if self.display_mode != "LLH":
            self.scale_bar.set_visible(False)
            self.scale_label.set_visible(False)
            return
        x0, x1 = self.ax.get_xlim()
        y0, y1 = self.ax.get_ylim()
        map_span = abs(x1 - x0)
        if map_span <= 0.0:
            return
        _lon, center_lat = _web_mercator_to_lonlat((x0 + x1) / 2.0, (y0 + y1) / 2.0)
        latitude_scale = max(math.cos(math.radians(center_lat)), 0.1)
        target_ground_m = map_span * latitude_scale * 0.22
        magnitude = 10.0 ** math.floor(math.log10(max(target_ground_m, 1e-6)))
        scale_ground_m = magnitude
        for multiplier in (1.0, 2.0, 5.0, 10.0):
            candidate = multiplier * magnitude
            if candidate <= target_ground_m:
                scale_ground_m = candidate
        scale_map_m = scale_ground_m / latitude_scale
        start_x = min(x0, x1) + map_span * 0.055
        bar_y = min(y0, y1) + abs(y1 - y0) * 0.055
        self.scale_bar.set_data([start_x, start_x + scale_map_m], [bar_y, bar_y])
        self.scale_bar.set_visible(True)
        label = f"{scale_ground_m / 1000.0:g} km" if scale_ground_m >= 1000.0 else f"{scale_ground_m:g} m"
        self.scale_label.set_position((start_x + scale_map_m / 2.0, bar_y + abs(y1 - y0) * 0.018))
        self.scale_label.set_text(label)
        self.scale_label.set_visible(True)

    @staticmethod
    def _tile_xy(lon: float, lat: float, zoom: int) -> tuple[int, int]:
        lat = max(-85.05112878, min(85.05112878, float(lat)))
        n = 2 ** zoom
        x = int((float(lon) + 180.0) / 360.0 * n)
        lat_rad = math.radians(lat)
        y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
        return max(0, min(n - 1, x)), max(0, min(n - 1, y))

    @staticmethod
    def _tile_extent(x: int, y: int, zoom: int) -> tuple[float, float, float, float]:
        n = 2 ** zoom
        tile_size_m = 2.0 * WEB_MERCATOR_HALF_WORLD_M / n
        west = -WEB_MERCATOR_HALF_WORLD_M + x * tile_size_m
        east = west + tile_size_m
        north = WEB_MERCATOR_HALF_WORLD_M - y * tile_size_m
        south = north - tile_size_m
        return west, east, south, north

    def _request_tiles_for_view(self):
        if self.display_mode != "LLH" or not self._base_map_enabled:
            return
        x0, x1 = self.ax.get_xlim()
        y0, y1 = self.ax.get_ylim()
        if not all(math.isfinite(value) for value in (x0, x1, y0, y1)):
            return
        dpr = max(1.0, float(self.canvas.devicePixelRatioF()))
        resolution = max(
            abs(x1 - x0) / max(1.0, self.canvas.width() * dpr),
            abs(y1 - y0) / max(1.0, self.canvas.height() * dpr),
        )
        zoom = max(3, min(19, int(math.ceil(math.log2(2.0 * WEB_MERCATOR_HALF_WORLD_M / (256.0 * resolution))))))
        lon0, lat0 = _web_mercator_to_lonlat(min(x0, x1), min(y0, y1))
        lon1, lat1 = _web_mercator_to_lonlat(max(x0, x1), max(y0, y1))
        while True:
            tx0, ty0 = self._tile_xy(lon0, lat1, zoom)
            tx1, ty1 = self._tile_xy(lon1, lat0, zoom)
            n = 2 ** zoom
            tile_count = (tx1 - tx0 + 1) * (ty1 - ty0 + 1)
            if tile_count <= 20 or zoom <= 3:
                break
            zoom -= 1
        if tx0 == tx1:
            tx0, tx1 = max(0, tx0 - 1), min(n - 1, tx1 + 1)
        if ty0 == ty1:
            ty0, ty1 = max(0, ty0 - 1), min(n - 1, ty1 + 1)
        signature = (zoom, tx0, tx1, ty0, ty1)
        if signature == self._tile_request_key:
            self._pending_tile_signature = None
            self._tile_debounce_timer.stop()
            return
        if signature == self._pending_tile_signature:
            return
        self._pending_tile_signature = signature
        self.tile_status.setText("Loading map...")
        self._tile_debounce_timer.start()

    def _start_pending_tile_request(self):
        signature = self._pending_tile_signature
        self._pending_tile_signature = None
        if signature is None or not self._base_map_enabled or self.display_mode != "LLH":
            return
        self._tile_request_key = signature
        self._tile_generation += 1
        generation = self._tile_generation
        threading.Thread(
            target=self._download_tiles,
            args=(generation, signature),
            daemon=True,
            name="rtgs-map-tiles",
        ).start()

    def _tile_url_candidates(self, zoom: int, x: int, y: int) -> tuple[str, ...]:
        osm_de = f"https://tile.openstreetmap.de/{zoom}/{x}/{y}.png"
        osm_hot = f"https://a.tile.openstreetmap.fr/hot/{zoom}/{x}/{y}.png"
        osm_standard = f"https://tile.openstreetmap.org/{zoom}/{x}/{y}.png"
        return osm_de, osm_hot, osm_standard

    def _download_tiles(self, generation: int, signature: tuple[int, int, int, int, int]):
        zoom, tx0, tx1, ty0, ty1 = signature
        try:
            from PIL import Image
        except Exception:
            self._tile_signals.tiles_ready.emit(generation, signature, [])
            return

        coordinates = [
            (zoom, tile_x, tile_y, Image)
            for tile_y in range(ty0, ty1 + 1)
            for tile_x in range(tx0, tx1 + 1)
        ]
        with ThreadPoolExecutor(max_workers=min(6, len(coordinates))) as pool:
            results = list(pool.map(self._load_tile, coordinates))
        images = [result for result in results if result is not None]
        self._tile_signals.tiles_ready.emit(generation, signature, images)

    def _load_tile(self, request_data):
        zoom, tile_x, tile_y, image_class = request_data
        cache_key = (zoom, tile_x, tile_y)
        cache_path = self._tile_cache_dir / f"{zoom}_{tile_x}_{tile_y}.tile"
        with self._tile_cache_lock:
            image = self._tile_cache.get(cache_key)
        if image is None and cache_path.is_file():
            try:
                with image_class.open(cache_path) as tile:
                    image = np.asarray(tile.convert("RGBA"))
                with self._tile_cache_lock:
                    self._tile_cache[cache_key] = image
            except Exception:
                try:
                    cache_path.unlink()
                except OSError:
                    pass
        if image is None:
            for url in self._tile_url_candidates(zoom, tile_x, tile_y):
                try:
                    request = Request(url, headers={"User-Agent": "RTGS/0.1 map viewer"})
                    with urlopen(request, timeout=2.0) as response:
                        raw = response.read()
                    with image_class.open(io.BytesIO(raw)) as tile:
                        image = np.asarray(tile.convert("RGBA"))
                    with self._tile_cache_lock:
                        try:
                            cache_path.write_bytes(raw)
                        except OSError:
                            pass
                        self._tile_cache[cache_key] = image
                        while len(self._tile_cache) > 256:
                            self._tile_cache.pop(next(iter(self._tile_cache)))
                    break
                except Exception:
                    continue
        if image is None:
            return None
        return self._tile_extent(tile_x, tile_y, zoom), image

    def _on_tiles_ready(self, generation: int, signature: tuple, images):
        if generation != self._tile_generation or signature != self._tile_request_key:
            return
        self.tile_status.setText("Map ready" if images else "Map unavailable")
        for artist in self._tile_artists:
            try:
                artist.remove()
            except (AttributeError, ValueError):
                pass
        self._tile_artists = []
        view = (self.ax.get_xlim(), self.ax.get_ylim())
        for extent, image in images:
            artist = self.ax.imshow(
                image,
                extent=extent,
                origin="upper",
                interpolation="nearest",
                aspect="auto",
                zorder=0,
            )
            self._tile_artists.append(artist)
        if images:
            self.ax.set_xlim(*view[0])
            self.ax.set_ylim(*view[1])
        self.canvas.draw_idle()

    def _on_base_map_toggled(self, enabled: bool):
        self._base_map_enabled = bool(enabled)
        self._tile_generation += 1
        self._tile_request_key = None
        self._pending_tile_signature = None
        self._tile_debounce_timer.stop()
        if not self._base_map_enabled:
            self.tile_status.setText("")
            self.map_attribution.set_visible(False)
            for artist in self._tile_artists:
                try:
                    artist.remove()
                except (AttributeError, ValueError):
                    pass
            self._tile_artists = []
        elif self.display_mode == "LLH":
            self.map_attribution.set_visible(True)
        self._apply_map_axis_style()
        self._redraw(force_autoscale=True)

    def reset_view(self):
        self.follow_button.setChecked(True)
        self._redraw(force_autoscale=True)

    def _on_follow_changed(self, checked):
        if checked:
            self._redraw(force_autoscale=True)

    def _on_scroll(self, event):
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return
        scale = 0.82 if event.button == "up" else 1.22
        x0, x1 = self.ax.get_xlim()
        y0, y1 = self.ax.get_ylim()
        self.ax.set_xlim(event.xdata - (event.xdata - x0) * scale, event.xdata + (x1 - event.xdata) * scale)
        self.ax.set_ylim(event.ydata - (event.ydata - y0) * scale, event.ydata + (y1 - event.ydata) * scale)
        self.follow_button.setChecked(False)
        if self.display_mode == "LLH":
            self._update_scale_bar()
        if self._base_map_enabled and self.display_mode == "LLH":
            self._request_tiles_for_view()
        self.canvas.draw_idle()

    def _on_press(self, event):
        if event.button == 1 and event.inaxes == self.ax and event.xdata is not None and event.ydata is not None:
            self._pan_anchor = (event.x, event.y, self.ax.get_xlim(), self.ax.get_ylim())

    def _on_motion(self, event):
        if self._pan_anchor is None or event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return
        anchor_x, anchor_y, x_limits, y_limits = self._pan_anchor
        width = max(1.0, float(self.ax.bbox.width))
        height = max(1.0, float(self.ax.bbox.height))
        dx = (event.x - anchor_x) * (x_limits[1] - x_limits[0]) / width
        dy = (event.y - anchor_y) * (y_limits[1] - y_limits[0]) / height
        self.ax.set_xlim(x_limits[0] - dx, x_limits[1] - dx)
        self.ax.set_ylim(y_limits[0] - dy, y_limits[1] - dy)
        self.follow_button.setChecked(False)
        if self.display_mode == "LLH":
            self._update_scale_bar()
        self.canvas.draw_idle()

    def _on_release(self, _event):
        self._pan_anchor = None
        if self.display_mode == "LLH":
            self._update_scale_bar()
        if self._base_map_enabled and self.display_mode == "LLH":
            self._request_tiles_for_view()

    def _on_canvas_resize(self, _event):
        if self.display_mode != "LLH" or not hasattr(self, "scale_bar"):
            return
        self._layout_refresh_timer.start()


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
        "Reference",
        "East / North / Up Error",
        "Horizontal / 3D Error",
        "Clock Bias",
        "Num Satellites",
        "Solution Source",
        "Used Systems",
        "Candidate Systems",
        "Used Satellites",
        "Quality Reason",
        "Differential Age",
        "Ambiguity Ratio",
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
        self.table.setMaximumHeight(520)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
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
                "Reference": (
                    getattr(solution, "reference_source", "") or "--"
                    if getattr(solution, "has_reference_position", False)
                    else "--"
                ),
                "East / North / Up Error": (
                    f"{solution.error_east:+.3f} / {solution.error_north:+.3f} / {solution.error_up:+.3f} m"
                    if getattr(solution, "has_reference_position", False)
                    else "--"
                ),
                "Horizontal / 3D Error": (
                    f"{solution.error_horizontal:.3f} / {solution.error_3d:.3f} m"
                    if getattr(solution, "has_reference_position", False)
                    else "--"
                ),
                "Clock Bias": f"{solution.clock_bias:.3e} m",
                "Num Satellites": str(solution.num_satellites),
                "Solution Source": getattr(solution, "solution_source", "") or "--",
                "Used Systems": _format_counts_value(getattr(solution, "used_system_counts", {})),
                "Candidate Systems": _format_counts_value(getattr(solution, "candidate_system_counts", {})),
                "Used Satellites": _format_satellite_list(getattr(solution, "used_satellites", [])),
                "Quality Reason": getattr(solution, "quality_reason", "") or "--",
                "Differential Age": (
                    f"{solution.differential_age_s:.2f} s"
                    if getattr(solution, "mode", None) == PositioningMode.RTK else "--"
                ),
                "Ambiguity Ratio": (
                    f"{solution.ambiguity_ratio:.2f}"
                    if getattr(solution, "mode", None) == PositioningMode.RTK else "--"
                ),
                "HDOP": f"{solution.hdop:.2f}" if _finite(solution.hdop) else "--",
                "VDOP": f"{solution.vdop:.2f}" if _finite(solution.vdop) else "--",
                "PDOP": f"{solution.pdop:.2f}" if _finite(solution.pdop) else "--",
                "Solution Status": format_solution_status(solution.status),
                "Convergence": "Yes" if solution.convergence else "No",
            }
        )

        resize_needed = False
        for param, value in updates.items():
            if param not in self.parameter_rows:
                continue
            row = self.parameter_rows[param]
            item = self.table.item(row, 1)
            if item.text() != value:
                item.setText(value)
                if param in {"Used Satellites", "Quality Reason"}:
                    resize_needed = True
            if param == "Solution Status":
                item.setForeground(_status_color(solution.status, self.theme))
                item.setFont(_make_font("Consolas", 10, QFont.Weight.Bold))
        if resize_needed:
            self.table.resizeRowsToContents()

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
            label_item.setForeground(QColor(self.theme["muted"]))
            label_item.setFlags(label_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 0, label_item)

            value_item = QTableWidgetItem("--")
            value_item.setFont(_make_font("Consolas", 10))
            value_item.setFlags(value_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 1, value_item)


class AccuracyWidget(QWidget):
    """Four compact, independently scaled DOP monitors."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme = _build_theme()
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.figure = Figure(figsize=(6, 5), dpi=100, facecolor=self.theme["bg"])
        self.axes = self.figure.subplots(2, 2)
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)
        self.dop_history = {
            'HDOP': [],
            'VDOP': [],
            'PDOP': [],
            'GDOP': [],
        }
        self.times = []
        self.epochs = 0
        self.colors = {
            "HDOP": self.theme["accent"],
            "VDOP": self.theme["up"],
            "PDOP": self.theme["north"],
            "GDOP": "#8B5CF6",
        }
        self.lines = {}
        self.value_labels = {}
        self.render_enabled = True
        self._initialize_plots()

    def set_render_enabled(self, enabled: bool):
        self.render_enabled = bool(enabled)
        if self.render_enabled:
            self._render_history()
    
    def update_solution(self, solution):
        """Update DOP values and plot."""
        if solution is None:
            return
        
        self.epochs += 1
        self.times.append(_solution_epoch_time(solution))
        self.times = self.times[-MAX_HISTORY:]
        values = {
            "HDOP": getattr(solution, "hdop", np.nan),
            "VDOP": getattr(solution, "vdop", np.nan),
            "PDOP": getattr(solution, "pdop", np.nan),
            "GDOP": getattr(solution, "gdop", np.nan),
        }
        for key, value in values.items():
            self.dop_history[key].append(float(value) if _finite(value) else np.nan)
            self.dop_history[key] = self.dop_history[key][-MAX_HISTORY:]

        if self.render_enabled:
            self._render_history()

    def _render_history(self):
        if not self.dop_history["HDOP"]:
            return
        x = self.times[-len(self.dop_history["HDOP"]):]
        for key, ax in zip(self.dop_history, self.axes.flat):
            history = np.asarray(self.dop_history[key], dtype=float)
            self.lines[key].set_data(x, history)
            latest = history[-1]
            self.value_labels[key].set_text(f"{latest:.2f}" if np.isfinite(latest) else "--")
            _set_time_limits(ax, x)
            finite = history[np.isfinite(history)]
            ceiling = max(2.0, float(np.max(finite)) * 1.2) if finite.size else 2.0
            ax.set_ylim(0, ceiling)
        self.canvas.draw_idle()
    
    def clear(self):
        """Clear history and plot."""
        for key in self.dop_history:
            self.dop_history[key].clear()
        self.epochs = 0
        self.times.clear()
        for key in self.lines:
            self.lines[key].set_data([], [])
            self.value_labels[key].set_text("--")
        for ax in self.axes.flat:
            ax.set_ylim(0, 2)
        if self.render_enabled:
            self.canvas.draw_idle()

    def _initialize_plots(self):
        for key, ax in zip(self.dop_history, self.axes.flat):
            _style_axis(ax, self.theme)
            ax.set_title(key, loc="left", color=self.theme["muted"], fontsize=8, fontweight="bold")
            ax.tick_params(labelsize=7)
            ax.set_ylim(0, 2)
            _configure_time_axis(ax, self.theme)
            self.lines[key], = ax.plot([], [], color=self.colors[key], linewidth=1.4)
            self.value_labels[key] = ax.text(
                0.98, 0.93, "--", transform=ax.transAxes,
                ha="right", va="top", color=self.theme["fg"],
                fontsize=11, fontweight="bold",
            )
        self.figure.subplots_adjust(left=0.08, right=0.98, bottom=0.08, top=0.91, hspace=0.40, wspace=0.22)


class AtmosphereWidget(QWidget):
    """Compact real-time monitor for PPP zenith troposphere estimates."""

    PARAMETERS = ("ZTD", "ZHD", "ZWD")
    DEFAULT_LIMITS = {
        "ZTD": (2.0, 3.0),
        "ZHD": (2.0, 2.6),
        "ZWD": (0.0, 0.5),
    }
    MIN_SPANS = {"ZTD": 0.05, "ZHD": 0.05, "ZWD": 0.02}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme = _build_theme()
        self.history = {name: [] for name in self.PARAMETERS}
        self.colors = {"ZTD": "#2563EB", "ZHD": "#5E8C61", "ZWD": "#D96459"}
        self.times = []
        self.epochs = 0
        self.figure = Figure(figsize=(6, 5), dpi=100, facecolor=self.theme["bg"])
        self.axes = self.figure.subplots(3, 1, sharex=True)
        self.canvas = FigureCanvas(self.figure)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        summary = QHBoxLayout()
        summary.setContentsMargins(8, 2, 8, 0)
        summary.setSpacing(12)
        self.summary_labels = {}
        for name in self.PARAMETERS:
            label = QLabel(f"{name}  --")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setFont(_make_font("Consolas", 9, QFont.Weight.Bold))
            label.setStyleSheet(f"color: {self.colors[name]};")
            self.summary_labels[name] = label
            summary.addWidget(label, 1)
        layout.addLayout(summary)
        layout.addWidget(self.canvas, 1)
        self.lines = {}
        self.value_labels = {}
        self.render_enabled = False
        self._initialize_plots()

    def set_render_enabled(self, enabled: bool):
        self.render_enabled = bool(enabled)
        if self.render_enabled:
            self._render_history()

    def _initialize_plots(self):
        for index, (name, ax) in enumerate(zip(self.PARAMETERS, self.axes)):
            _style_axis(ax, self.theme)
            ax.set_title(f"{name} (m)", loc="left", color=self.theme["muted"], fontsize=8, fontweight="bold")
            ax.tick_params(labelsize=7)
            ax.set_ylim(*self.DEFAULT_LIMITS[name])
            _configure_time_axis(ax, self.theme)
            if index < len(self.PARAMETERS) - 1:
                ax.tick_params(labelbottom=False)
                ax.set_xlabel("")
            self.lines[name], = ax.plot([], [], color=self.colors[name], linewidth=1.4)
            self.value_labels[name] = ax.text(
                0.98, 0.90, "--", transform=ax.transAxes,
                ha="right", va="top", color=self.theme["fg"],
                fontsize=10, fontweight="bold",
            )
        self.figure.subplots_adjust(left=0.10, right=0.98, bottom=0.13, top=0.96, hspace=0.38)

    def update_solution(self, solution):
        if solution is None:
            return
        self.epochs += 1
        self.times.append(_solution_epoch_time(solution))
        self.times = self.times[-MAX_HISTORY:]
        mode_value = getattr(solution, "mode", None)
        mode = str(getattr(mode_value, "name", mode_value) or "").upper()
        raw_values = {
            "ZTD": getattr(solution, "ztd", np.nan),
            "ZHD": getattr(solution, "zhd", np.nan),
            "ZWD": getattr(solution, "zwd", np.nan),
        }
        has_estimate = mode == "PPP" or any(
            _finite(value) and abs(float(value)) > 1e-9
            for value in raw_values.values()
        )
        values = raw_values if has_estimate else {name: np.nan for name in self.PARAMETERS}
        for name, value in values.items():
            numeric_value = float(value) if _finite(value) else np.nan
            self.history[name].append(numeric_value)
            self.history[name] = self.history[name][-MAX_HISTORY:]
            self.summary_labels[name].setText(
                f"{name}  {numeric_value:.3f} m" if np.isfinite(numeric_value) else f"{name}  --"
            )
        if self.render_enabled:
            self._render_history()

    def _render_history(self):
        if not self.history["ZTD"]:
            return
        x = self.times[-len(self.history["ZTD"]):]
        for name, ax in zip(self.PARAMETERS, self.axes):
            values = np.asarray(self.history[name], dtype=float)
            self.lines[name].set_data(x, values)
            latest = values[-1]
            self.value_labels[name].set_text(f"{latest:.3f}" if np.isfinite(latest) else "--")
            _set_time_limits(ax, x)
            finite = values[np.isfinite(values)]
            self._set_parameter_limits(name, ax, finite)
        self.canvas.draw_idle()

    def _set_parameter_limits(self, name, ax, finite):
        if not finite.size:
            ax.set_ylim(*self.DEFAULT_LIMITS[name])
            return
        data_min = float(np.min(finite))
        data_max = float(np.max(finite))
        span = max(data_max - data_min, self.MIN_SPANS[name])
        center = 0.5 * (data_min + data_max)
        padding = 0.65 * span
        lower = max(0.0, center - padding)
        upper = max(center + padding, lower + self.MIN_SPANS[name])
        ax.set_ylim(lower, upper)

    def clear(self):
        self.epochs = 0
        self.times.clear()
        for name in self.PARAMETERS:
            self.history[name].clear()
            self.lines[name].set_data([], [])
            self.value_labels[name].set_text("--")
            self.summary_labels[name].setText(f"{name}  --")
        for name, ax in zip(self.PARAMETERS, self.axes):
            ax.set_ylim(*self.DEFAULT_LIMITS[name])
        if self.render_enabled:
            self.canvas.draw_idle()


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
    """Position error sequence with time and controllable vertical scaling."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme = _build_theme()
        self.display_mode = "LLH"
        self.solutions = []
        self.epochs = 0
        self.render_enabled = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        controls = QHBoxLayout()
        controls.setContentsMargins(8, 2, 8, 0)
        controls.addStretch()
        self.auto_y = QCheckBox("Auto Y")
        self.auto_y.setChecked(True)
        self.auto_y.setToolTip("Automatically fit the vertical error range")
        self.auto_y.toggled.connect(self._on_y_scale_changed)
        controls.addWidget(self.auto_y)
        controls.addWidget(QLabel("Y range"))
        self.y_range = QDoubleSpinBox()
        self.y_range.setRange(0.01, 10000.0)
        self.y_range.setDecimals(2)
        self.y_range.setSingleStep(0.10)
        self.y_range.setValue(1.0)
        self.y_range.setSuffix(" m")
        self.y_range.setEnabled(False)
        self.y_range.setToolTip("Set the symmetric positive and negative Y-axis range")
        self.y_range.valueChanged.connect(self._on_y_scale_changed)
        controls.addWidget(self.y_range)
        layout.addLayout(controls)

        self.figure = Figure(figsize=(8, 4), dpi=100, facecolor=self.theme["bg"])
        self.ax = self.figure.add_subplot(111)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.mpl_connect("scroll_event", self._on_y_scroll)
        self.canvas.setToolTip("Scroll over the plot to zoom the Y axis")
        layout.addWidget(self.canvas, 1)

        self.lines = []
        self.placeholder = None
        self._initialize_plot()

    def _on_y_scale_changed(self, _value=None):
        self.y_range.setEnabled(not self.auto_y.isChecked())
        if self.render_enabled:
            self._redraw()

    def _on_y_scroll(self, event):
        if event.inaxes is not self.ax:
            return
        current = max(abs(float(value)) for value in self.ax.get_ylim())
        factor = 0.80 if event.button == "up" else 1.25
        target = min(max(current * factor, self.y_range.minimum()), self.y_range.maximum())
        self.auto_y.blockSignals(True)
        self.auto_y.setChecked(False)
        self.auto_y.blockSignals(False)
        self.y_range.setEnabled(True)
        self.y_range.setValue(target)

    def set_display_mode(self, mode: str):
        mode = "XYZ" if mode == "XYZ" else "LLH"
        if self.display_mode == mode:
            return
        self.display_mode = mode
        if self.render_enabled:
            self._redraw()

    def set_render_enabled(self, enabled: bool):
        enabled = bool(enabled)
        if self.render_enabled == enabled:
            return
        self.render_enabled = enabled
        if enabled:
            self._redraw()

    def update_solution(self, solution):
        if solution is None or format_solution_status(getattr(solution, "status", "")) == "No Fix":
            return
        self.epochs += 1
        self.solutions.append(solution)
        self.solutions = self.solutions[-MAX_HISTORY:]
        if self.render_enabled:
            self._redraw()

    def clear(self):
        self.solutions.clear()
        self.epochs = 0
        for line in self.lines:
            line.set_data([], [])
        self._set_placeholder_visible(True)
        self.ax.set_ylim(-1.0, 1.0)
        self.canvas.draw_idle()

    def _initialize_plot(self):
        _style_axis(self.ax, self.theme)
        _configure_time_axis(self.ax, self.theme)
        self.ax.axhline(y=0, color=self.theme["grid"], linestyle="-", linewidth=0.8)
        colors = [self.theme["east"], self.theme["north"], self.theme["up"]]
        self.lines = [self.ax.plot([], [], color=color, linewidth=1.5)[0] for color in colors]
        self.placeholder = self.ax.text(
            0.5, 0.5, "Waiting for positioning solution...", transform=self.ax.transAxes,
            ha="center", va="center", color=self.theme["muted"], fontsize=10,
        )
        self.ax.set_ylim(-1.0, 1.0)
        self._update_labels(False)
        self.figure.subplots_adjust(left=0.08, right=0.98, bottom=0.18, top=0.88)

    def _set_placeholder_visible(self, visible: bool):
        if self.placeholder is not None:
            self.placeholder.set_visible(visible)

    def _update_labels(self, uses_reference: bool):
        if self.display_mode == "XYZ":
            title = "ECEF coordinate error" if uses_reference else "ECEF offset from first solution"
        else:
            title = "East / North / Up position error" if uses_reference else "ENU offset from first solution"
        self.ax.set_title(title, color=self.theme["fg"], fontsize=10, fontweight="bold")
        self.ax.set_ylabel("Error (m)" if uses_reference else "Offset (m)", color=self.theme["muted"])

    def _redraw(self):
        times, series, uses_reference = self._series_for_mode()
        if not times or not series:
            for line in self.lines:
                line.set_data([], [])
            self._set_placeholder_visible(True)
            self.canvas.draw_idle()
            return

        self._set_placeholder_visible(False)
        labels = list(series)
        for index, line in enumerate(self.lines):
            if index < len(labels):
                label = labels[index]
                line.set_data(times, series[label])
                line.set_label(label)
                line.set_visible(True)
            else:
                line.set_visible(False)
        _set_time_limits(self.ax, times)
        self._update_labels(uses_reference)

        all_values = np.asarray([value for values in series.values() for value in values], dtype=float)
        finite = np.abs(all_values[np.isfinite(all_values)])
        if self.auto_y.isChecked():
            max_abs = max(0.05, float(np.max(finite))) if finite.size else 1.0
            y_limit = max_abs * 1.15
        else:
            y_limit = float(self.y_range.value())
        self.ax.set_ylim(-y_limit, y_limit)

        legend = self.ax.legend(loc="upper right", frameon=False, fontsize=8, ncol=3)
        if legend:
            for text in legend.get_texts():
                text.set_color(self.theme["muted"])
        self.canvas.draw_idle()

    def _series_for_mode(self):
        if self.display_mode == "XYZ":
            valid = [
                sol for sol in self.solutions
                if _finite(getattr(sol, "ecef_x", np.nan))
                and _finite(getattr(sol, "ecef_y", np.nan))
                and _finite(getattr(sol, "ecef_z", np.nan))
            ]
            referenced = [sol for sol in valid if getattr(sol, "has_reference_position", False)]
            if referenced:
                return (
                    [_solution_epoch_time(sol) for sol in referenced],
                    {
                        "dX": [float(sol.error_ecef_x) for sol in referenced],
                        "dY": [float(sol.error_ecef_y) for sol in referenced],
                        "dZ": [float(sol.error_ecef_z) for sol in referenced],
                    },
                    True,
                )
            if not valid:
                return [], {}, False
            ref = valid[0]
            return (
                [_solution_epoch_time(sol) for sol in valid],
                {
                    "dX": [float(sol.ecef_x - ref.ecef_x) for sol in valid],
                    "dY": [float(sol.ecef_y - ref.ecef_y) for sol in valid],
                    "dZ": [float(sol.ecef_z - ref.ecef_z) for sol in valid],
                },
                False,
            )

        referenced = [sol for sol in self.solutions if getattr(sol, "has_reference_position", False)]
        if referenced:
            return (
                [_solution_epoch_time(sol) for sol in referenced],
                {
                    "East": [float(sol.error_east) for sol in referenced],
                    "North": [float(sol.error_north) for sol in referenced],
                    "Up": [float(sol.error_up) for sol in referenced],
                },
                True,
            )

        valid = [
            sol for sol in self.solutions
            if _finite(getattr(sol, "latitude", np.nan))
            and _finite(getattr(sol, "longitude", np.nan))
            and _finite(getattr(sol, "height", np.nan))
        ]
        if not valid:
            return [], {}, False
        ref = valid[0]
        ref_lat_rad = np.radians(float(ref.latitude))
        return (
            [_solution_epoch_time(sol) for sol in valid],
            {
                "East": [float((sol.longitude - ref.longitude) * 111000.0 * np.cos(ref_lat_rad)) for sol in valid],
                "North": [float((sol.latitude - ref.latitude) * 111000.0) for sol in valid],
                "Up": [float(sol.height - ref.height) for sol in valid],
            },
            False,
        )
