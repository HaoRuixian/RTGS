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
        assert times == [start.replace(tzinfo=None), (start + timedelta(seconds=30)).replace(tzinfo=None)]
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

        for name, ax in zip(widget.PARAMETERS, widget.axes):
            assert ax.xaxis.get_offset_text().get_visible() is False
            assert widget.value_labels[name].get_text() != "--"

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
