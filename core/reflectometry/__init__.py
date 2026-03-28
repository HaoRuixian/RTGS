"""Reflectometry public namespace.

The package root stays lightweight and resolves public symbols lazily so that
submodules such as ``core.reflectometry.providers`` can be imported without
eagerly pulling in optional configuration dependencies.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, tuple[str, str]] = {
    "ArcDirection": ("core.reflectometry.models", "ArcDirection"),
    "ArcSolution": ("core.reflectometry.models", "ArcSolution"),
    "BatchProcessor": ("core.reflectometry.services.batch", "BatchProcessor"),
    "CacheObservationProvider": ("core.reflectometry.providers", "CacheObservationProvider"),
    "DEFAULT_CONFIG_YAML": ("core.reflectometry.config", "DEFAULT_CONFIG_YAML"),
    "GeometryConfig": ("core.reflectometry.config", "GeometryConfig"),
    "InputConfig": ("core.reflectometry.config", "InputConfig"),
    "IrConfig": ("core.reflectometry.config", "IrConfig"),
    "ListObservationProvider": ("core.reflectometry.providers", "ListObservationProvider"),
    "LoggingConfig": ("core.reflectometry.config", "LoggingConfig"),
    "ObservationProvider": ("core.reflectometry.providers", "ObservationProvider"),
    "ObservationRecord": ("core.reflectometry.models", "ObservationRecord"),
    "OutputConfig": ("core.reflectometry.config", "OutputConfig"),
    "ProcessingConfig": ("core.reflectometry.config", "ProcessingConfig"),
    "ProcessingRunResult": ("core.reflectometry.models", "ProcessingRunResult"),
    "ProductResult": ("core.reflectometry.models", "ProductResult"),
    "ProductType": ("core.reflectometry.models", "ProductType"),
    "ProductsConfig": ("core.reflectometry.config", "ProductsConfig"),
    "QcConfig": ("core.reflectometry.config", "QcConfig"),
    "RealtimeProcessor": ("core.reflectometry.services.realtime", "RealtimeProcessor"),
    "ReceiverPosition": ("core.reflectometry.models", "ReceiverPosition"),
    "ReflectionZoneConfig": ("core.reflectometry.config", "ReflectionZoneConfig"),
    "ReflectorConfig": ("core.reflectometry.config", "ReflectorConfig"),
    "SnrSeries": ("core.reflectometry.models", "SnrSeries"),
    "SnrUnit": ("core.reflectometry.models", "SnrUnit"),
    "StationConfig": ("core.reflectometry.config", "StationConfig"),
    "config_to_dict": ("core.reflectometry.config", "config_to_dict"),
    "dump_example_config": ("core.reflectometry.config", "dump_example_config"),
    "load_config": ("core.reflectometry.config", "load_config"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = _EXPORTS[name]
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
