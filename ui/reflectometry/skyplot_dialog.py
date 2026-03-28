"""Reflectometry skyplot dialog with highlighted reflection zones."""

from __future__ import annotations

from typing import Mapping

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from core.reflectometry.config import GeometryConfig, ProcessingConfig
from core.reflectometry.services.geometry import effective_reflection_zones, matches_reflection_zones
from ui.gnss_colordef import get_sys_color
from ui.responsive import adaptive_window_size


class ReflectometrySkyplotCanvas(FigureCanvas):
    """Polar skyplot with shaded reflectometry zones."""

    def __init__(self, parent: QWidget | None = None) -> None:
        palette = QApplication.palette()
        is_dark = palette.color(palette.ColorRole.Window).lightness() < 128
        self.theme = {
            "bg": "#161A23" if is_dark else "#FFFFFF",
            "fg": "#E2E8F0" if is_dark else "#0F172A",
            "grid": "#334155" if is_dark else "#CBD5E1",
            "muted": "#94A3B8" if is_dark else "#64748B",
            "accent": "#2563EB" if not is_dark else "#60A5FA",
            "zone_colors": ["#2563EB", "#0D9488", "#D97706", "#7C3AED"],
        }
        self.fig = Figure(figsize=(6.4, 6.2), dpi=100, facecolor=self.theme["bg"])
        self.ax = self.fig.add_subplot(111, projection="polar")
        super().__init__(self.fig)
        self.setParent(parent)
        self._init_plot()

    def _init_plot(self) -> None:
        self.ax.set_facecolor(self.theme["bg"])
        self.ax.set_theta_zero_location("N")
        self.ax.set_theta_direction(-1)
        self.ax.set_rlim(0, 90)
        self.ax.set_yticks([0, 15, 30, 45, 60, 75, 90])
        self.ax.set_yticklabels(
            ["90 deg", "75 deg", "60 deg", "45 deg", "30 deg", "15 deg", "0 deg"],
            fontsize=8,
            color=self.theme["muted"],
        )
        self.ax.set_thetagrids(
            [0, 45, 90, 135, 180, 225, 270, 315],
            ["N", "45", "E", "135", "S", "225", "W", "315"],
            fontsize=9,
            fontweight="bold",
            color=self.theme["fg"],
        )
        self.ax.grid(True, color=self.theme["grid"], linestyle="--", linewidth=0.8, alpha=0.55)
        self.ax.spines["polar"].set_visible(False)
        self.ax.set_title("REFLECTOMETRY SKYPLOT", pad=18, fontsize=11, fontweight="bold", color=self.theme["accent"])
        base_theta = np.linspace(0.0, 2.0 * np.pi, 180)
        self.ax.fill(base_theta, np.full_like(base_theta, 90.0), color=self.theme["accent"], alpha=0.03, zorder=0)

    def update_view(
        self,
        satellites: Mapping[str, object],
        active_systems: set[str],
        geometry_config: GeometryConfig,
        processing_config: ProcessingConfig,
    ) -> None:
        self.ax.clear()
        self._init_plot()
        self._draw_reflection_zones(geometry_config, processing_config)
        self._draw_satellites(satellites, active_systems, geometry_config, processing_config)
        self.draw_idle()

    def _draw_reflection_zones(self, geometry_config: GeometryConfig, processing_config: ProcessingConfig) -> None:
        zones = effective_reflection_zones(geometry_config, processing_config)
        for zone_index, zone in enumerate(zones):
            color = self.theme["zone_colors"][zone_index % len(self.theme["zone_colors"])]
            segments = _split_azimuth_segments(zone.azimuth_windows)
            for segment_index, (start_deg, end_deg) in enumerate(segments):
                theta = np.radians(np.linspace(start_deg, end_deg, 180))
                lower = np.full(theta.shape, 90.0 - zone.max_elevation_deg, dtype=float)
                upper = np.full(theta.shape, 90.0 - zone.min_elevation_deg, dtype=float)
                self.ax.fill_between(theta, lower, upper, color=color, alpha=0.18, zorder=1)
                self.ax.plot(theta, lower, color=color, linewidth=1.0, alpha=0.7, zorder=2)
                self.ax.plot(theta, upper, color=color, linewidth=1.0, alpha=0.7, zorder=2)
                self.ax.plot(
                    [np.radians(start_deg), np.radians(start_deg)],
                    [90.0 - zone.max_elevation_deg, 90.0 - zone.min_elevation_deg],
                    color=color,
                    linewidth=1.0,
                    alpha=0.55,
                    zorder=2,
                )
                self.ax.plot(
                    [np.radians(end_deg), np.radians(end_deg)],
                    [90.0 - zone.max_elevation_deg, 90.0 - zone.min_elevation_deg],
                    color=color,
                    linewidth=1.0,
                    alpha=0.55,
                    zorder=2,
                )
                if segment_index == 0:
                    label_theta = np.radians(_segment_midpoint(start_deg, end_deg))
                    label_radius = 90.0 - ((zone.min_elevation_deg + zone.max_elevation_deg) / 2.0)
                    self.ax.text(
                        label_theta,
                        label_radius,
                        zone.name,
                        fontsize=8,
                        fontweight="bold",
                        ha="center",
                        va="center",
                        color=color,
                        zorder=3,
                    )

    def _draw_satellites(
        self,
        satellites: Mapping[str, object],
        active_systems: set[str],
        geometry_config: GeometryConfig,
        processing_config: ProcessingConfig,
    ) -> None:
        if not satellites:
            self.ax.text(
                0.5,
                0.5,
                "Waiting for tracked satellites...",
                transform=self.ax.transAxes,
                ha="center",
                va="center",
                fontsize=12,
                color=self.theme["muted"],
            )
            return

        for key, sat in sorted(satellites.items()):
            if key[0] not in active_systems:
                continue
            elevation = getattr(sat, "elevation", getattr(sat, "el", None))
            azimuth = getattr(sat, "azimuth", getattr(sat, "az", None))
            if elevation is None or azimuth is None:
                continue

            elevation_value = float(elevation)
            azimuth_value = float(azimuth)
            radius = 90.0 - elevation_value
            in_zone = matches_reflection_zones(
                azimuth_deg=azimuth_value,
                elevation_deg=elevation_value,
                geometry_config=geometry_config,
                processing_config=processing_config,
            )
            color = get_sys_color(key[0])
            self.ax.scatter(
                np.radians(azimuth_value),
                radius,
                c=color,
                s=125 if in_zone else 72,
                alpha=0.95 if in_zone else 0.42,
                edgecolors=self.theme["bg"] if not in_zone else "#0F172A",
                linewidth=1.4 if in_zone else 0.9,
                zorder=5 if in_zone else 4,
            )
            self.ax.text(
                np.radians(azimuth_value),
                radius,
                key,
                fontsize=7.5,
                ha="center",
                va="center",
                fontweight="bold",
                color="#FFFFFF" if self.theme["bg"] != "#FFFFFF" else "#0F172A",
                zorder=6,
            )


class ReflectometrySkyplotDialog(QDialog):
    """Non-modal dialog showing the current reflectometry skyplot."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reflectometry Skyplot")
        adaptive_window_size(self, target=(900, 760), minimum=(700, 560))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.canvas = ReflectometrySkyplotCanvas(self)
        layout.addWidget(self.canvas, stretch=1)

        button_row = QHBoxLayout()
        button_row.addStretch()
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

    def update_view(
        self,
        satellites: Mapping[str, object],
        active_systems: set[str],
        geometry_config: GeometryConfig,
        processing_config: ProcessingConfig,
    ) -> None:
        self.canvas.update_view(satellites, active_systems, geometry_config, processing_config)


def _split_azimuth_segments(windows: list[list[float]]) -> list[tuple[float, float]]:
    segments: list[tuple[float, float]] = []
    for start_deg, end_deg in windows:
        if abs(end_deg - start_deg) >= 360.0:
            return [(0.0, 360.0)]
        start = start_deg % 360.0
        end = end_deg % 360.0
        if start <= end:
            segments.append((start, end))
        else:
            segments.append((start, 360.0))
            segments.append((0.0, end))
    return segments


def _segment_midpoint(start_deg: float, end_deg: float) -> float:
    if end_deg >= start_deg:
        return (start_deg + end_deg) / 2.0
    span = (360.0 - start_deg) + end_deg
    return (start_deg + span / 2.0) % 360.0

