"""Serialization helpers and file outputs for reflectometry results."""

from __future__ import annotations

from abc import ABC, abstractmethod
import csv
from dataclasses import asdict, is_dataclass, replace
from datetime import datetime
import json
from pathlib import Path
from typing import Any

try:
    import pandas as pd
except Exception:  # pragma: no cover - optional CSV/DataFrame dependency
    pd = None

from .config import OutputConfig
from .models import ArcDirection, ArcSolution, ProcessingRunResult, ProductResult, ProductType


def _require_pandas():
    if pd is None:
        raise RuntimeError("pandas is required for CSV/DataFrame reflectometry outputs.")
    return pd


class ResultSerializer:
    @staticmethod
    def _normalize(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, (ArcDirection, ProductType)):
            return value.value
        if isinstance(value, list):
            return [ResultSerializer._normalize(item) for item in value]
        if isinstance(value, dict):
            return {key: ResultSerializer._normalize(item) for key, item in value.items()}
        if is_dataclass(value):
            return ResultSerializer._normalize(asdict(value))
        return value

    @classmethod
    def to_dict(cls, result: ProcessingRunResult) -> dict[str, Any]:
        return cls._normalize(asdict(result))

    @staticmethod
    def arc_solutions_to_rows(arc_solutions: list[ArcSolution]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for solution in arc_solutions:
            rows.append(
                {
                    "station_id": solution.station_id,
                    "arc_id": solution.arc_id,
                    "timestamp_start": solution.timestamp_start,
                    "timestamp_end": solution.timestamp_end,
                    "constellation": solution.constellation,
                    "satellite": solution.satellite,
                    "signal": solution.signal,
                    "arc_direction": solution.arc_direction.value,
                    "reflector_height_m": solution.reflector_height_m,
                    "peak_frequency": solution.peak_frequency,
                    "peak_power": solution.peak_power,
                    "peak_to_noise_ratio": solution.peak_to_noise_ratio,
                    "qc_flags": ",".join(solution.qc_flags),
                    "success": solution.success,
                    "fail_reason": solution.fail_reason,
                    "candidate_count": len(solution.candidates),
                    "confidence": solution.quality_metrics.confidence if solution.quality_metrics else None,
                }
            )
        return rows

    @staticmethod
    def arc_solutions_to_frame(arc_solutions: list[ArcSolution]) -> pd.DataFrame:
        return _require_pandas().DataFrame(ResultSerializer.arc_solutions_to_rows(arc_solutions))

    @staticmethod
    def products_to_rows(products: list[ProductResult]) -> list[dict[str, Any]]:
        return [
            {
                "product_type": item.product_type.value,
                "timestamp": item.timestamp,
                "value": item.value,
                "unit": item.unit,
                "source_arc_count": item.source_arc_count,
                "confidence": item.confidence,
                "metadata": item.metadata,
            }
            for item in products
        ]

    @staticmethod
    def products_to_frame(products: list[ProductResult]) -> pd.DataFrame:
        return _require_pandas().DataFrame(ResultSerializer.products_to_rows(products))

    @staticmethod
    def window_aggregates_to_rows(result: ProcessingRunResult) -> list[dict[str, Any]]:
        return [
            {
                "window_start": aggregate.window_start,
                "window_end": aggregate.window_end,
                "product_count": len(aggregate.products),
                "metadata": aggregate.metadata,
            }
            for aggregate in result.window_aggregates
        ]

    @classmethod
    def to_frames(cls, result: ProcessingRunResult) -> dict[str, pd.DataFrame]:
        pandas = _require_pandas()
        return {
            "arc_solutions": cls.arc_solutions_to_frame(result.arc_solutions),
            "products": cls.products_to_frame(result.products),
            "window_aggregates": pandas.DataFrame(cls.window_aggregates_to_rows(result)),
        }


class ResultSink(ABC):
    @abstractmethod
    def write(self, result: ProcessingRunResult, output_dir: Path) -> list[Path]:
        """Persist a result bundle and return written paths."""


class CsvResultWriter(ResultSink):
    def write(self, result: ProcessingRunResult, output_dir: Path) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        rows_by_name = {
            "arc_solutions": ResultSerializer.arc_solutions_to_rows(result.arc_solutions),
            "products": ResultSerializer.products_to_rows(result.products),
            "window_aggregates": ResultSerializer.window_aggregates_to_rows(result),
        }
        written: list[Path] = []
        for name, rows in rows_by_name.items():
            path = output_dir / f"{name}.csv"
            _write_csv_rows(path, rows)
            written.append(path)
        return written


class JsonResultWriter(ResultSink):
    def write(self, result: ProcessingRunResult, output_dir: Path) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "results.json"
        path.write_text(json.dumps(ResultSerializer.to_dict(result), indent=2, ensure_ascii=False), encoding="utf-8")
        return [path]


class OutputManager:
    def __init__(self, output_config: OutputConfig) -> None:
        self.output_config = output_config
        self._writers: dict[str, ResultSink] = {"csv": CsvResultWriter(), "json": JsonResultWriter()}

    def write(self, result: ProcessingRunResult) -> list[Path]:
        output_dir = Path(self.output_config.output_dir)
        filtered_result = result
        if not self.output_config.save_arc_level_results:
            filtered_result = ProcessingRunResult(
                station_id=result.station_id,
                arc_solutions=[],
                products=result.products,
                window_aggregates=result.window_aggregates,
                daily_summaries=result.daily_summaries,
                metadata=result.metadata,
            )
        if self.output_config.save_arc_level_results and not self.output_config.save_qc_flags:
            filtered_result = ProcessingRunResult(
                station_id=result.station_id,
                arc_solutions=[replace(solution, qc_flags=[]) for solution in result.arc_solutions],
                products=result.products,
                window_aggregates=result.window_aggregates,
                daily_summaries=result.daily_summaries,
                metadata=result.metadata,
            )
        written: list[Path] = []
        for file_format in self.output_config.file_format:
            written.extend(self._writers[file_format].write(filtered_result, output_dir))
        return written


def _write_csv_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if rows:
        fieldnames = list(rows[0].keys())
    else:
        fieldnames = []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if fieldnames:
            writer.writeheader()
            for row in rows:
                writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _csv_value(value: Any) -> Any:
    normalized = ResultSerializer._normalize(value)
    if isinstance(normalized, (dict, list)):
        return json.dumps(normalized, ensure_ascii=False)
    return normalized
