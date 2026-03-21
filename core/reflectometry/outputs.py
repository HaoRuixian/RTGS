"""Serialization helpers and file outputs for reflectometry results."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, is_dataclass, replace
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

from core.reflectometry.config import OutputConfig
from core.reflectometry.models import ArcDirection, ArcSolution, ProcessingRunResult, ProductResult, ProductType


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
    def arc_solutions_to_frame(arc_solutions: list[ArcSolution]) -> pd.DataFrame:
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
        return pd.DataFrame(rows)

    @staticmethod
    def products_to_frame(products: list[ProductResult]) -> pd.DataFrame:
        return pd.DataFrame(
            [
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
        )

    @classmethod
    def to_frames(cls, result: ProcessingRunResult) -> dict[str, pd.DataFrame]:
        return {
            "arc_solutions": cls.arc_solutions_to_frame(result.arc_solutions),
            "products": cls.products_to_frame(result.products),
            "window_aggregates": pd.DataFrame(
                [
                    {
                        "window_start": aggregate.window_start,
                        "window_end": aggregate.window_end,
                        "product_count": len(aggregate.products),
                        "metadata": aggregate.metadata,
                    }
                    for aggregate in result.window_aggregates
                ]
            ),
        }


class ResultSink(ABC):
    @abstractmethod
    def write(self, result: ProcessingRunResult, output_dir: Path) -> list[Path]:
        """Persist a result bundle and return written paths."""


class CsvResultWriter(ResultSink):
    def write(self, result: ProcessingRunResult, output_dir: Path) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        frames = ResultSerializer.to_frames(result)
        written: list[Path] = []
        for name, frame in frames.items():
            path = output_dir / f"{name}.csv"
            frame.to_csv(path, index=False)
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
