from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _solution(epoch_time: datetime, east: float, north: float, up: float):
    from core.positioning_models import SolutionStatus

    return SimpleNamespace(
        status=SolutionStatus.UNCERTAIN,
        epoch_time=epoch_time,
        has_reference_position=True,
        error_east=east,
        error_north=north,
        error_up=up,
        latitude=39.0,
        longitude=116.0,
        height=50.0,
    )


def test_residual_widget_uses_solution_time_and_supports_y_axis_zoom():
    _qapp()
    from ui.positioning.widgets import ResidualWidget

    start = datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc)
    widget = ResidualWidget()
    widget.set_render_enabled(True)
    try:
        widget.update_solution(_solution(start, 0.10, -0.20, 0.30))
        widget.update_solution(_solution(start + timedelta(seconds=30), 0.15, -0.10, 0.25))

        times, series, uses_reference = widget._series_for_mode()
        assert times == [
            start.replace(tzinfo=None),
            (start + timedelta(seconds=30)).replace(tzinfo=None),
        ]
        assert series["East"] == [0.10, 0.15]
        assert uses_reference is True

        old_limit = max(abs(value) for value in widget.ax.get_ylim())
        widget._on_y_scroll(SimpleNamespace(inaxes=widget.ax, button="up"))
        new_limit = max(abs(value) for value in widget.ax.get_ylim())
        assert widget.auto_y.isChecked() is False
        assert new_limit < old_limit
    finally:
        widget.close()


def test_atmosphere_widget_uses_numeric_dates_and_independent_parameter_scales():
    _qapp()
    from core.positioning_models import PositioningMode
    from ui.positioning.widgets import AtmosphereWidget

    start = datetime(2026, 6, 28, tzinfo=timezone.utc)
    widget = AtmosphereWidget()
    widget.set_render_enabled(True)
    try:
        for index in range(20):
            widget.update_solution(
                SimpleNamespace(
                    epoch_time=start + timedelta(days=index),
                    mode=PositioningMode.PPP,
                    ztd=2.400 + index * 0.001,
                    zhd=2.270,
                    zwd=0.130 + index * 0.001,
                )
            )
        widget.canvas.draw()

        for _name, ax in zip(widget.PARAMETERS, widget.axes, strict=True):
            assert ax.xaxis.get_offset_text().get_visible() is False
        assert not hasattr(widget, "value_labels")

        labels = [label.get_text() for label in widget.axes[-1].get_xticklabels()]
        assert labels
        assert all(not any(character.isalpha() for character in label) for label in labels)

        assert widget.axes[0].get_ylim()[1] - widget.axes[0].get_ylim()[0] < 0.10
        assert widget.axes[1].get_ylim()[1] - widget.axes[1].get_ylim()[0] < 0.10
        assert widget.axes[2].get_ylim()[1] - widget.axes[2].get_ylim()[0] < 0.05
        assert widget.summary_labels["ZTD"].text() == "ZTD  2.419 m"
        assert widget.summary_labels["ZHD"].text() == "ZHD  2.270 m"
        assert widget.summary_labels["ZWD"].text() == "ZWD  0.149 m"

        # Preserve valid atmosphere values even if an external caller provides
        # a non-local mode representation instead of PositioningMode.PPP.
        widget.update_solution(
            SimpleNamespace(
                epoch_time=start + timedelta(days=20),
                mode="Precise Point Positioning (PPP)",
                ztd=2.410,
                zhd=2.270,
                zwd=0.140,
            )
        )
        assert widget.summary_labels["ZWD"].text() == "ZWD  0.140 m"
    finally:
        widget.close()


def test_atmosphere_widget_retains_long_trends_without_storing_every_ui_refresh():
    _qapp()
    from core.positioning_models import PositioningMode
    from ui.positioning.widgets import AtmosphereWidget

    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    widget = AtmosphereWidget()
    try:
        for offset, ztd in ((0.0, 2.400), (0.25, 2.401), (3600.0, 2.410), (21600.0, 2.420)):
            widget.update_solution(
                SimpleNamespace(
                    epoch_time=start + timedelta(seconds=offset),
                    mode=PositioningMode.PPP,
                    ztd=ztd,
                    zhd=2.270,
                    zwd=ztd - 2.270,
                )
            )

        assert len(widget.times) == 3
        assert widget.history["ZTD"] == pytest.approx([2.401, 2.410, 2.420])
        assert widget.times[-1] - widget.times[0] > timedelta(hours=5)
    finally:
        widget.close()


def test_current_solution_uses_paired_columns_and_mode_specific_fields():
    _qapp()
    import shiboken6

    from core.positioning_models import PositioningMode, PositioningSolution, SolutionStatus
    from ui.positioning.widgets import PositionInfoWidget

    widget = PositionInfoWidget()
    try:
        widget.set_positioning_mode(PositioningMode.PPP)
        assert widget.table.columnCount() == 4
        assert "Differential Age" not in widget.parameter_cells
        assert "Ambiguity Ratio" not in widget.parameter_cells
        assert "PPP Ambiguities" in widget.parameter_cells
        assert "Coordinate Stability" in widget.parameter_cells

        solution = PositioningSolution(
            timestamp=0,
            gps_week=0,
            latitude=48.5,
            longitude=-123.0,
            height=1.0,
            ecef_x=-2304501.0,
            ecef_y=-3547589.0,
            ecef_z=4757288.0,
            mode=PositioningMode.PPP,
            status=SolutionStatus.FIXED,
            convergence=True,
            diagnostics={"ar_status": "waiting", "ar_candidate_count": 8},
        )
        widget.update_solution(solution)
        assert widget.table.item(*widget.parameter_cells["Solution Status"]).text() == "Fixed"
        assert widget.table.item(*widget.parameter_cells["PPP Ambiguities"]).text() == "Float"
        assert (
            widget.table.item(*widget.parameter_cells["AR Constraints / Candidates"]).text()
            == "0 / 8"
        )

        widget.set_positioning_mode(PositioningMode.RTK)
        assert "Differential Age" in widget.parameter_cells
        assert "Ambiguity Ratio" in widget.parameter_cells
    finally:
        widget.close()
        shiboken6.delete(widget)


def test_position_map_fills_initial_rectangular_canvas_and_draws_track():
    app = _qapp()
    from ui.positioning.widgets import PositionMapWidget

    widget = PositionMapWidget()
    widget._request_tiles_for_view = lambda: None
    widget.resize(900, 360)
    widget.show()
    app.processEvents()
    try:
        for index in range(12):
            widget.update_solution(
                SimpleNamespace(
                    latitude=39.984430 + index * 0.000005,
                    longitude=116.343040 + index * 0.000008,
                    height=125.0,
                    ecef_x=-2171646.0 + index,
                    ecef_y=4385696.0 + index,
                    ecef_z=4076742.0,
                    hdop=1.0,
                )
            )
        widget.canvas.draw()

        axes_ratio = float(widget.ax.bbox.width / widget.ax.bbox.height)
        x_limits = widget.ax.get_xlim()
        y_limits = widget.ax.get_ylim()
        view_ratio = abs(float(x_limits[1] - x_limits[0]) / float(y_limits[1] - y_limits[0]))
        assert widget.ax.get_aspect() == "auto"
        assert axes_ratio > 2.0
        assert view_ratio == pytest.approx(axes_ratio, rel=0.02)
        assert len(widget.track_line.get_xdata()) == 12
        assert len(widget.track_outline.get_xdata()) == 12
        assert len(widget.history_points.get_xdata()) == 11
        assert len(widget.start_point.get_xdata()) == 1
    finally:
        widget.close()


def test_position_map_switches_between_street_and_satellite_tile_layers():
    _qapp()

    import shiboken6
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    from ui.positioning.widgets import PositionMapWidget

    widget = PositionMapWidget()
    widget._request_tiles_for_view = lambda: None
    try:
        assert widget.tile_source_combo.currentData() == "satellite"
        assert widget._tile_source == "satellite"
        assert widget._tile_url_candidates("satellite", 12, 654, 1582)[0].endswith("/12/1582/654")
        assert "Esri" in widget.map_attribution.get_text()
        assert widget.north_label.get_color() == "#FFFFFF"
        assert widget.scale_bar.get_color() == "#FFFFFF"
        wheel = QWheelEvent(
            QPointF(8, 8),
            QPointF(8, 8),
            QPoint(),
            QPoint(0, -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(widget.tile_source_combo, wheel)
        assert widget._tile_source == "satellite"

        widget.update_track(48.546, -123.008, height=0.0)
        first_extent = widget.ax.get_xlim(), widget.ax.get_ylim()
        widget.update_track(48.5460001, -123.0080001, height=0.1)
        np_extent = widget.ax.get_xlim(), widget.ax.get_ylim()
        for observed, expected in zip(np_extent, first_extent, strict=True):
            assert observed == pytest.approx(expected, abs=1e-6, rel=0)

        widget.tile_source_combo.setCurrentIndex(1)
        assert widget._tile_source == "osm"
        assert widget._tile_url_candidates("osm", 12, 654, 1582)[0].endswith("/12/654/1582.png")
        assert widget.scale_bar.get_color() == widget.theme["fg"]
    finally:
        widget.close()
        shiboken6.delete(widget)


def test_stopping_an_initial_rtk_run_does_not_disable_unstarted_spp_thread():
    app = _qapp()
    from ui.positioning.module import PositioningModule

    window = PositioningModule()
    try:
        window.combo_mode.setCurrentIndex(2)
        assert window.positioning_thread.ident is None
        assert window.positioning_thread.running is True

        window.is_running = True
        window.stop_positioning()
        app.processEvents()

        assert window.positioning_thread.ident is None
        assert window.positioning_thread.running is True
    finally:
        window.close()
