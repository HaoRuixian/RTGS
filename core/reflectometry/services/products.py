"""Product conversion strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta
from statistics import mean

from core.reflectometry.config import ProductsConfig
from core.reflectometry.models import ProductType
from core.reflectometry.models import (
    ArcSolution,
    ProductResult,
    ReflectorHeightResult,
    SeaLevelResult,
    SnowDepthResult,
    WindowAggregateResult,
)

_WATER_ENVIRONMENTS = {"coastal", "riverbank", "shore", "sea", "riverside"}
_SNOW_ENVIRONMENTS = {"snowfield", "snow", "glacier", "ice"}
_HEIGHT_ONLY_ENVIRONMENTS = {"inland", "urban", "farmland", "soil", "plain"}


class ProductStrategy(ABC):
    """Strategy interface for product conversion."""

    @abstractmethod
    def build(self, solution: ArcSolution) -> ProductResult | None:
        """Create a product from a successful arc solution."""


class ReflectorHeightStrategy(ProductStrategy):
    """Return reflector height directly as a product."""

    def build(self, solution: ArcSolution) -> ProductResult | None:
        if not solution.success or solution.reflector_height_m is None:
            return None
        return ReflectorHeightResult(
            timestamp=_midpoint(solution.timestamp_start, solution.timestamp_end),
            value=solution.reflector_height_m,
            source_arc_count=1,
            confidence=solution.quality_metrics.confidence if solution.quality_metrics else 0.0,
            metadata=_base_product_metadata(solution),
        )


class SeaLevelStrategy(ProductStrategy):
    """Convert reflector height into sea level."""

    def __init__(self, reference_level_m: float) -> None:
        self.reference_level_m = reference_level_m

    def build(self, solution: ArcSolution) -> ProductResult | None:
        if not solution.success or solution.reflector_height_m is None:
            return None
        sea_level = self.reference_level_m - solution.reflector_height_m
        return SeaLevelResult(
            timestamp=_midpoint(solution.timestamp_start, solution.timestamp_end),
            value=sea_level,
            source_arc_count=1,
            confidence=solution.quality_metrics.confidence if solution.quality_metrics else 0.0,
            metadata={
                **_base_product_metadata(solution),
                "reference_level_m": self.reference_level_m,
            },
        )


class SnowDepthStrategy(ProductStrategy):
    """Convert reflector height into snow depth using a reference surface."""

    def __init__(self, reference_height_m: float) -> None:
        self.reference_height_m = reference_height_m

    def build(self, solution: ArcSolution) -> ProductResult | None:
        if not solution.success or solution.reflector_height_m is None:
            return None
        snow_depth = self.reference_height_m - solution.reflector_height_m
        return SnowDepthResult(
            timestamp=_midpoint(solution.timestamp_start, solution.timestamp_end),
            value=snow_depth,
            source_arc_count=1,
            confidence=solution.quality_metrics.confidence if solution.quality_metrics else 0.0,
            metadata={
                **_base_product_metadata(solution),
                "reference_height_m": self.reference_height_m,
            },
        )


class ProductConverter:
    """Apply enabled strategies and aggregate window-level products."""

    def __init__(self, config: ProductsConfig, environment_type: str = "unknown") -> None:
        config = apply_environment_product_policy(config, environment_type)
        self.strategies: list[ProductStrategy] = []
        if config.enable_reflector_height:
            self.strategies.append(ReflectorHeightStrategy())
        if config.enable_sea_level and config.sea_level_reference is not None:
            self.strategies.append(SeaLevelStrategy(config.sea_level_reference))
        if config.enable_snow_depth and config.snow_depth_reference_height is not None:
            self.strategies.append(SnowDepthStrategy(config.snow_depth_reference_height))

    def convert(self, solutions: list[ArcSolution]) -> list[ProductResult]:
        """Create products from all successful arc solutions."""
        products: list[ProductResult] = []
        for solution in solutions:
            for strategy in self.strategies:
                product = strategy.build(solution)
                if product is not None:
                    products.append(product)
        return products

    def aggregate(
        self,
        products: list[ProductResult],
        window_start: datetime,
        window_end: datetime,
    ) -> list[WindowAggregateResult]:
        """Aggregate products over the current processing window."""
        grouped: dict[ProductType, list[ProductResult]] = defaultdict(list)
        for product in products:
            grouped[product.product_type].append(product)

        aggregate_products: list[ProductResult] = []
        for product_type, items in grouped.items():
            weights = [max(item.confidence, 0.05) for item in items]
            total_weight = sum(weights)
            weighted_value = sum(item.value * weight for item, weight in zip(items, weights)) / max(total_weight, 1e-12)
            aggregate_products.append(
                ProductResult(
                    product_type=product_type,
                    timestamp=_midpoint(window_start, window_end),
                    value=weighted_value,
                    unit=items[0].unit,
                    source_arc_count=len(items),
                    confidence=round(float(mean([item.confidence for item in items])), 4),
                    metadata={"aggregation": "weighted_mean"},
                )
            )

        if not aggregate_products:
            return []
        return [WindowAggregateResult(window_start=window_start, window_end=window_end, products=aggregate_products)]


def _midpoint(start: datetime, end: datetime) -> datetime:
    return start + (end - start) / 2


def _base_product_metadata(solution: ArcSolution) -> dict[str, str]:
    return {
        "arc_id": solution.arc_id,
        "constellation": solution.constellation,
        "satellite": solution.satellite,
        "signal": solution.signal,
    }


def classify_environment(environment_type: str | None) -> str:
    """Classify station environment into a product policy group."""
    normalized = (environment_type or "").strip().lower()
    if normalized in _WATER_ENVIRONMENTS:
        return "water"
    if normalized in _SNOW_ENVIRONMENTS:
        return "snow"
    if normalized in _HEIGHT_ONLY_ENVIRONMENTS:
        return "height_only"
    return "manual"


def apply_environment_product_policy(config: ProductsConfig, environment_type: str | None) -> ProductsConfig:
    """Adjust enabled products to match the configured station environment."""
    mode = classify_environment(environment_type)
    if mode == "water":
        return replace(
            config,
            enable_reflector_height=True,
            enable_sea_level=True,
            enable_snow_depth=False,
            snow_depth_reference_height=None,
        )
    if mode == "snow":
        return replace(
            config,
            enable_reflector_height=True,
            enable_sea_level=False,
            enable_snow_depth=True,
            sea_level_reference=None,
        )
    if mode == "height_only":
        return replace(
            config,
            enable_reflector_height=True,
            enable_sea_level=False,
            enable_snow_depth=False,
            sea_level_reference=None,
            snow_depth_reference_height=None,
        )
    return replace(config, enable_reflector_height=True)


