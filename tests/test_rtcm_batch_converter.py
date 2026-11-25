from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.data_models import EpochObservation, SatelliteState, SignalData
from utils import rtcm_batch_converter
from utils.rtcm_batch_converter import (
    BatchConversionOptions,
    BatchConversionReport,
    convert_file,
    convert_folder,
    filter_epoch,
    find_input_files,
)


class _Reader:
    messages: list[tuple[bytes, object]] = []

    def __init__(self, _stream):
        self._iterator = iter(self.messages)

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._iterator)


class _Handler:
    def __init__(self, *_args, **_kwargs):
        self.last_station_coords = [1.0, 2.0, 3.0]

    def process_message(self, message):
        return message


def _epoch(at: datetime, *, system: str = "G", prn: int = 1) -> EpochObservation:
    signal = SignalData(
        signal_id="1C",
        snr=45.0,
        phase=1000.0,
        pseudorange=21_000_000.0,
        lock_time=0,
        half_cycle=0,
        doppler=-123.0,
    )
    satellite = SatelliteState(system, prn, signals={"1C": signal})
    return EpochObservation(0.0, {f"{system}{prn:02d}": satellite}, utc_datetime=at)


def _factories(messages):
    _Reader.messages = [(b"", epoch) for epoch in messages]
    return (lambda stream: _Reader(stream)), (lambda: _Handler())


def test_find_input_files_filters_extensions_and_recurses(tmp_path):
    (tmp_path / "a.rtcm").write_bytes(b"")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "b.DAT").write_bytes(b"")
    (tmp_path / "ignore.txt").write_bytes(b"")

    assert [item.name for item in find_input_files(tmp_path, extensions=(".rtcm", ".dat"))] == [
        "a.rtcm",
        "b.DAT",
    ]


def test_filter_epoch_keeps_selected_systems_and_values():
    epoch = _epoch(datetime.now(timezone.utc))
    options = BatchConversionOptions(
        input_dir=".",
        output_dir=".",
        systems=("G",),
        observation_types=("c", "l", "s"),
    )

    filtered = filter_epoch(epoch, options)

    assert filtered is not None
    signal = filtered.satellites["G01"].signals["1C"]
    assert signal.pseudorange is not None
    assert signal.phase is not None
    assert signal.snr is not None
    assert signal.doppler is None


def test_convert_file_splits_and_decimates_with_selected_observations(tmp_path):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    epochs = [_epoch(start + timedelta(seconds=value)) for value in (0, 30, 60)]
    epochs.append(_epoch(start + timedelta(days=1)))
    reader_factory, handler_factory = _factories(epochs)
    source = tmp_path / "sample.rtcm"
    source.write_bytes(b"input")
    options = BatchConversionOptions(
        input_dir=tmp_path,
        output_dir=tmp_path / "out",
        extensions=(".rtcm",),
        systems=("G",),
        observation_types=("C", "L", "S"),
        split_seconds=86_400,
        sample_interval_seconds=60,
        overwrite=True,
    )

    result = convert_file(
        source,
        options,
        reader_factory=reader_factory,
        handler_factory=handler_factory,
    )

    assert result.error == ""
    assert result.written_epochs == 3
    assert len(result.output_paths) == 2
    first_text = result.output_paths[0].read_text(encoding="utf-8")
    assert "C1C" in first_text
    assert "D1C" not in first_text
    assert first_text.count("\n> ") == 2


def test_explicit_sampling_interval_aligns_epochs_to_rinex_grid(tmp_path):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    epochs = [_epoch(start + timedelta(seconds=value)) for value in (2, 17)]
    reader_factory, handler_factory = _factories(epochs)
    source = tmp_path / "offset.rtcm"
    source.write_bytes(b"input")
    options = BatchConversionOptions(
        input_dir=tmp_path,
        output_dir=tmp_path / "out",
        extensions=(".rtcm",),
        systems=("G",),
        split_seconds=86_400,
        sample_interval_seconds=15,
        overwrite=True,
    )

    result = convert_file(
        source,
        options,
        reader_factory=reader_factory,
        handler_factory=handler_factory,
    )

    assert result.error == ""
    assert result.written_epochs == 2
    text = result.output_paths[0].read_text(encoding="utf-8")
    assert "> 2026 01 01 00 00 15.0000000  0  1" in text
    assert "> 2026 01 01 00 00 30.0000000  0  1" in text


def test_daily_split_uses_utc_time_across_midnight(tmp_path):
    start = datetime(2026, 1, 1, 23, 59, 42, tzinfo=timezone.utc)
    epochs = [_epoch(start), _epoch(start + timedelta(seconds=30))]
    reader_factory, handler_factory = _factories(epochs)
    source = tmp_path / "midnight.rtcm"
    source.write_bytes(b"input")
    options = BatchConversionOptions(
        input_dir=tmp_path,
        output_dir=tmp_path / "out",
        extensions=(".rtcm",),
        systems=("G",),
        split_seconds=86_400,
        sample_interval_seconds=15,
        overwrite=True,
    )

    result = convert_file(
        source,
        options,
        reader_factory=reader_factory,
        handler_factory=handler_factory,
    )

    assert result.error == ""
    assert len(result.output_paths) == 1
    text = result.output_paths[0].read_text(encoding="utf-8")
    assert "GPS         TIME OF FIRST OBS" in text
    assert "> 2026 01 02 00 00  0.0000000  0  1" in text
    assert "> 2026 01 02 00 00 30.0000000  0  1" in text


def test_convert_file_uses_short_metadata_scan(tmp_path):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    epochs = [_epoch(start + timedelta(seconds=15 * index)) for index in range(130)]
    reader_factory, handler_factory = _factories(epochs)
    source = tmp_path / "sample.rtcm"
    source.write_bytes(b"input")
    options = BatchConversionOptions(tmp_path, tmp_path / "out", overwrite=True)

    result = convert_file(
        source,
        options,
        reader_factory=reader_factory,
        handler_factory=handler_factory,
    )

    assert result.error == ""
    assert result.scanned_epochs == 101
    assert result.written_epochs == 130


def test_convert_folder_routes_default_pipeline_to_process_pool(tmp_path, monkeypatch):
    source = tmp_path / "sample.dat"
    source.write_bytes(b"input")
    expected = BatchConversionReport()
    captured = {}

    def fake_parallel(paths, options, **callbacks):
        captured["paths"] = paths
        captured["workers"] = options.max_workers
        captured["callbacks"] = callbacks
        return expected

    monkeypatch.setattr(rtcm_batch_converter, "_convert_folder_parallel", fake_parallel)
    options = BatchConversionOptions(
        tmp_path, tmp_path / "out", extensions=(".dat",), max_workers=4
    )

    report = convert_folder(options)

    assert report is expected
    assert captured["paths"] == [source]
    assert captured["workers"] == 4


def test_convert_folder_merges_daily_outputs_from_adjacent_inputs(tmp_path):
    first = tmp_path / "20260101.dat"
    second = tmp_path / "20260102.dat"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    epoch_by_name = {
        first.name: [
            _epoch(datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=15 * index))
            for index in range(5760)
        ],
        second.name: [
            _epoch(datetime(2026, 1, 2, tzinfo=timezone.utc) + timedelta(seconds=15 * index))
            for index in range(5760)
        ],
    }

    class PerFileReader:
        def __init__(self, stream):
            self._messages = iter(
                (b"", epoch) for epoch in epoch_by_name[Path(stream.name).name]
            )

        def __iter__(self):
            return self

        def __next__(self):
            return next(self._messages)

    options = BatchConversionOptions(
        input_dir=tmp_path,
        output_dir=tmp_path / "out",
        extensions=(".dat",),
        systems=("G",),
        split_seconds=86_400,
        sample_interval_seconds=15,
        overwrite=True,
        max_workers=1,
    )

    report = convert_folder(
        options,
        reader_factory=PerFileReader,
        handler_factory=lambda: _Handler(),
    )

    assert report.failed_files == 0
    assert len(report.files) == 2
    assert len(list((tmp_path / "out").glob("*.rnx"))) == 2
    assert report.files[0].output_paths[1] == report.files[1].output_paths[0]
    text = report.files[1].output_paths[0].read_text(encoding="utf-8")
    assert "> 2026 01 02 00 00  0.0000000  0  1" in text
    assert "> 2026 01 02 23 59 45.0000000  0  1" in text


def test_convert_folder_drops_single_epoch_daily_boundary_fragment(tmp_path):
    first = tmp_path / "20260101.dat"
    second = tmp_path / "20260102.dat"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    epoch_by_name = {
        first.name: [
            _epoch(datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=15 * index))
            for index in range(5760)
        ],
        second.name: [_epoch(datetime(2026, 1, 2, 0, 0, 0, tzinfo=timezone.utc))],
    }

    class PerFileReader:
        def __init__(self, stream):
            self._messages = iter(
                (b"", epoch) for epoch in epoch_by_name[Path(stream.name).name]
            )

        def __iter__(self):
            return self

        def __next__(self):
            return next(self._messages)

    logs = []
    options = BatchConversionOptions(
        input_dir=tmp_path,
        output_dir=tmp_path / "out",
        extensions=(".dat",),
        systems=("G",),
        split_seconds=86_400,
        sample_interval_seconds=15,
        overwrite=True,
        max_workers=1,
    )

    report = convert_folder(
        options,
        reader_factory=PerFileReader,
        handler_factory=lambda: _Handler(),
        log_callback=logs.append,
    )

    outputs = list((tmp_path / "out").glob("*.rnx"))
    assert report.failed_files == 0
    assert len(outputs) == 1
    assert report.files[1].output_paths == []
    assert any("Skipped incomplete daily fragment" in line for line in logs)
