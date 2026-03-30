"""Product conversion strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from statistics import mean

import numpy as np

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


@dataclass(slots=True)
class DynamicSeaLevelEstimate:
    corrected_value_m: float
    velocity_mps: float
    acceleration_mps2: float
    sample_count: int
    effective_sample_count: int
    rejected_sample_count: int
    correction_offset_m: float
    weighted_peak_to_noise_ratio: float | None
    window_start: datetime
    window_end: datetime
    robust_iterations: int
    sigma0: float
    max_standardized_residual: float


@dataclass(slots=True)
class RobustIgg3FitResult:
    beta: np.ndarray
    residuals: np.ndarray
    standardized_residuals: np.ndarray
    final_weights: np.ndarray
    iterations: int
    sigma0: float
    effective_sample_count: int
    rejected_sample_count: int
    condition_number_before: float
    condition_number_after: float


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
        self.config = config
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
        if self.config.enable_dynamic_sea_level_correction:
            products.extend(self._build_dynamic_sea_level_products(products))
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
            weights = [_product_weight(item) for item in items]
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
                    metadata={"aggregation": "pnr_weighted_mean", "weight_field": "peak_to_noise_ratio"},
                )
            )

        if not aggregate_products:
            return []
        return [WindowAggregateResult(window_start=window_start, window_end=window_end, products=aggregate_products)]

    def _build_dynamic_sea_level_products(self, products: list[ProductResult]) -> list[ProductResult]:
        sea_level_products = sorted(
            [item for item in products if item.product_type == ProductType.SEA_LEVEL],
            key=lambda item: item.timestamp,
        )
        if len(sea_level_products) < self.config.dynamic_sea_level_min_points:
            return []

        derived_products: list[ProductResult] = []
        for reference_product in sea_level_products:
            estimate = self._estimate_dynamic_sea_level_window(
                sea_level_products=sea_level_products,
                reference_product=reference_product,
            )
            if estimate is None:
                continue
            metadata = {
                "aggregation": "second_order_dynamic_correction",
                "dynamic_model_order": 2,
                "dynamic_regression_method": "igg3",
                "dynamic_window_hours": self.config.dynamic_sea_level_window_hours,
                "dynamic_sample_count": estimate.sample_count,
                "dynamic_effective_sample_count": estimate.effective_sample_count,
                "dynamic_rejected_sample_count": estimate.rejected_sample_count,
                "correction_offset_m": estimate.correction_offset_m,
                "sea_level_velocity_mps": estimate.velocity_mps,
                "sea_level_acceleration_mps2": estimate.acceleration_mps2,
                "dynamic_robust_iterations": estimate.robust_iterations,
                "dynamic_sigma0": estimate.sigma0,
                "dynamic_max_standardized_residual": estimate.max_standardized_residual,
                "dynamic_igg3_k0": self.config.dynamic_sea_level_igg3_k0,
                "dynamic_igg3_k1": self.config.dynamic_sea_level_igg3_k1,
                "reference_level_m": reference_product.metadata.get("reference_level_m"),
                "constellation": "M",
                "satellite": "Combined",
                "signal": "Combined",
                "arc_direction": "combined",
                "peak_to_noise_ratio": estimate.weighted_peak_to_noise_ratio,
                "window_start": estimate.window_start.isoformat(),
                "window_end": estimate.window_end.isoformat(),
            }
            mean_confidence = reference_product.confidence
            derived_products.extend(
                [
                    ProductResult(
                        product_type=ProductType.SEA_LEVEL_DYNAMIC_CORRECTED,
                        timestamp=reference_product.timestamp,
                        value=estimate.corrected_value_m,
                        unit="m",
                        source_arc_count=estimate.sample_count,
                        confidence=mean_confidence,
                        metadata=dict(metadata),
                    ),
                    ProductResult(
                        product_type=ProductType.SEA_LEVEL_RATE,
                        timestamp=reference_product.timestamp,
                        value=estimate.velocity_mps,
                        unit="m/s",
                        source_arc_count=estimate.sample_count,
                        confidence=mean_confidence,
                        metadata=dict(metadata),
                    ),
                    ProductResult(
                        product_type=ProductType.SEA_LEVEL_ACCELERATION,
                        timestamp=reference_product.timestamp,
                        value=estimate.acceleration_mps2,
                        unit="m/s^2",
                        source_arc_count=estimate.sample_count,
                        confidence=mean_confidence,
                        metadata=dict(metadata),
                    ),
                ]
            )
        return derived_products

    def _estimate_dynamic_sea_level_window(
        self,
        *,
        sea_level_products: list[ProductResult],
        reference_product: ProductResult,
    ) -> DynamicSeaLevelEstimate | None:
        window_seconds = float(self.config.dynamic_sea_level_window_hours) * 3600.0
        window_start = reference_product.timestamp - timedelta(seconds=window_seconds)
        window_items = [
            item
            for item in sea_level_products
            if window_start <= item.timestamp <= reference_product.timestamp
        ]
        if len(window_items) < self.config.dynamic_sea_level_min_points:
            return None

        design_rows: list[list[float]] = []
        observations: list[float] = []
        base_weights: list[float] = []
        peak_to_noise_weighted_sum = 0.0
        peak_to_noise_weight_total = 0.0
        for item in window_items:
            roc_like_seconds = _roc_like_seconds(item)
            if roc_like_seconds is None:
                continue
            item_weight = _product_weight(item)
            delta_t_seconds = (item.timestamp - reference_product.timestamp).total_seconds()
            design_rows.append(
                [
                    1.0,
                    roc_like_seconds + delta_t_seconds,
                    roc_like_seconds * delta_t_seconds + delta_t_seconds * delta_t_seconds,
                ]
            )
            observations.append(float(item.value))
            base_weights.append(item_weight)
            peak_to_noise_ratio = item.metadata.get("peak_to_noise_ratio")
            if peak_to_noise_ratio is not None:
                try:
                    peak_to_noise_weighted_sum += float(peak_to_noise_ratio) * item_weight
                    peak_to_noise_weight_total += item_weight
                except (TypeError, ValueError):
                    pass

        if len(design_rows) < self.config.dynamic_sea_level_min_points:
            return None

        X = np.asarray(design_rows, dtype=float)
        y = np.asarray(observations, dtype=float)
        weights = np.asarray(base_weights, dtype=float)
        if np.linalg.matrix_rank(X) < 3:
            return None

        fit = self._solve_dynamic_regression(X, y, weights)
        if fit is None:
            return None
        required_effective_samples = min(len(design_rows), max(3, self.config.dynamic_sea_level_min_points - 1))
        if fit.effective_sample_count < required_effective_samples:
            return None

        corrected_value = float(fit.beta[0])
        velocity = float(fit.beta[1])
        acceleration = float(fit.beta[2])
        weighted_peak_to_noise_ratio = (
            peak_to_noise_weighted_sum / peak_to_noise_weight_total if peak_to_noise_weight_total > 0.0 else None
        )
        return DynamicSeaLevelEstimate(
            corrected_value_m=corrected_value,
            velocity_mps=velocity,
            acceleration_mps2=acceleration,
            sample_count=len(design_rows),
            effective_sample_count=fit.effective_sample_count,
            rejected_sample_count=fit.rejected_sample_count,
            correction_offset_m=corrected_value - float(reference_product.value),
            weighted_peak_to_noise_ratio=weighted_peak_to_noise_ratio,
            window_start=window_start,
            window_end=reference_product.timestamp,
            robust_iterations=fit.iterations,
            sigma0=fit.sigma0,
            max_standardized_residual=float(np.max(np.abs(fit.standardized_residuals))) if fit.standardized_residuals.size else 0.0,
        )

    def _solve_dynamic_regression(
        self,
        X: np.ndarray,
        y: np.ndarray,
        base_weights: np.ndarray,
    ) -> RobustIgg3FitResult | None:
        return _robust_igg3_fit(
            X,
            y,
            base_weights,
            k0=self.config.dynamic_sea_level_igg3_k0,
            k1=self.config.dynamic_sea_level_igg3_k1,
            max_iterations=self.config.dynamic_sea_level_max_iterations,
            tolerance=self.config.dynamic_sea_level_tolerance,
            min_weight=self.config.dynamic_sea_level_min_weight,
            regularization=self.config.dynamic_sea_level_regularization,
            normalize=self.config.dynamic_sea_level_normalize_design,
        )


def _midpoint(start: datetime, end: datetime) -> datetime:
    return start + (end - start) / 2


def _base_product_metadata(solution: ArcSolution) -> dict[str, str | float | None]:
    return {
        "arc_id": solution.arc_id,
        "constellation": solution.constellation,
        "satellite": solution.satellite,
        "signal": solution.signal,
        "arc_direction": solution.arc_direction.value if solution.arc_direction is not None else None,
        "peak_to_noise_ratio": solution.peak_to_noise_ratio,
        "roc_like_seconds": solution.metadata.get("roc_like"),
        "elevation_rate_deg_per_min": solution.metadata.get("elevation_rate_deg_per_min"),
        "mean_azimuth_deg": solution.metadata.get("mean_azimuth_deg"),
    }


def _product_weight(product: ProductResult) -> float:
    peak_to_noise_ratio = product.metadata.get("peak_to_noise_ratio")
    if peak_to_noise_ratio is None:
        return 1.0
    try:
        return max(float(peak_to_noise_ratio), 1e-6)
    except (TypeError, ValueError):
        return 1.0


def _roc_like_seconds(product: ProductResult) -> float | None:
    value = product.metadata.get("roc_like_seconds")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _robust_scale(residuals: np.ndarray) -> float:
    if residuals.size == 0:
        return 0.0
    median = float(np.median(residuals))
    mad = float(np.median(np.abs(residuals - median)))
    if mad > 1e-12:
        return 1.4826 * mad
    rms = float(np.sqrt(np.mean(np.square(residuals))))
    return rms


def _robust_igg3_fit(
    X: np.ndarray,
    y: np.ndarray,
    initial_weights: np.ndarray,
    *,
    k0: float,
    k1: float,
    max_iterations: int,
    tolerance: float,
    min_weight: float,
    regularization: float,
    normalize: bool,
) -> RobustIgg3FitResult | None:
    if X.ndim != 2 or y.ndim != 1 or X.shape[0] != y.shape[0]:
        return None

    X_normalized, means, scales, normalized_columns = _normalize_design_matrix(X, normalize)
    raw_weights = np.maximum(np.asarray(initial_weights, dtype=float), min_weight)
    if not np.any(raw_weights > 0.0):
        raw_weights = np.ones_like(y, dtype=float)
    weight_scale = max(float(np.max(raw_weights)), min_weight)
    weights = np.maximum(raw_weights / weight_scale, min_weight)

    previous_beta: np.ndarray | None = None
    beta_normalized: np.ndarray | None = None
    iterations = 0
    sigma0 = 0.0
    condition_before = _safe_condition_number(X)
    condition_after = _safe_condition_number(X_normalized)

    for iteration in range(1, max_iterations + 1):
        solved = _solve_weighted_normal_system(X_normalized, y, weights, regularization)
        if solved is None:
            return None
        beta_candidate, normal_matrix = solved
        residuals = X_normalized @ beta_candidate - y
        degrees_of_freedom = max(X_normalized.shape[0] - X_normalized.shape[1], 1)
        if iteration == 1:
            sigma0 = max(_robust_scale(residuals), np.finfo(float).eps)
        else:
            sigma0 = float(
                np.sqrt(max(float(residuals.T @ (weights * residuals)) / degrees_of_freedom, np.finfo(float).eps))
            )

        qx = np.linalg.pinv(normal_matrix)
        hat_diagonal = _weighted_hat_diagonal(X_normalized, qx)
        denominator = sigma0 * np.sqrt(
            np.maximum((1.0 / np.maximum(weights, min_weight)) - hat_diagonal, np.finfo(float).eps)
        )
        standardized_residuals = residuals / denominator
        absolute_residuals = np.abs(standardized_residuals)

        new_weights = weights.copy()
        mid_mask = (absolute_residuals > k0) & (absolute_residuals <= k1)
        high_mask = absolute_residuals > k1
        new_weights[mid_mask] = (
            (k0 / np.maximum(absolute_residuals[mid_mask], np.finfo(float).eps))
            * ((k1 - absolute_residuals[mid_mask]) / max(k1 - k0, np.finfo(float).eps)) ** 2
            * weights[mid_mask]
        )
        new_weights[high_mask] = min_weight
        new_weights[~np.isfinite(new_weights)] = min_weight
        new_weights = np.maximum(new_weights, min_weight)

        beta_normalized = beta_candidate
        iterations = iteration
        if previous_beta is not None and float(np.max(np.abs(beta_candidate - previous_beta))) < tolerance:
            weights = new_weights
            break
        previous_beta = beta_candidate
        weights = new_weights

    if beta_normalized is None:
        return None

    solved = _solve_weighted_normal_system(X_normalized, y, weights, regularization)
    if solved is None:
        return None
    beta_normalized, normal_matrix = solved
    residuals = X_normalized @ beta_normalized - y
    degrees_of_freedom = max(X_normalized.shape[0] - X_normalized.shape[1], 1)
    sigma0 = float(np.sqrt(max(float(residuals.T @ (weights * residuals)) / degrees_of_freedom, np.finfo(float).eps)))
    qx = np.linalg.pinv(normal_matrix)
    hat_diagonal = _weighted_hat_diagonal(X_normalized, qx)
    denominator = sigma0 * np.sqrt(
        np.maximum((1.0 / np.maximum(weights, min_weight)) - hat_diagonal, np.finfo(float).eps)
    )
    standardized_residuals = residuals / denominator
    beta = _backtransform_normalized_coefficients(beta_normalized, means, scales, normalized_columns)
    residuals_original = X @ beta - y

    rejection_mask = np.abs(standardized_residuals) >= (k1 - 1e-9)
    rejected_sample_count = int(np.count_nonzero(rejection_mask))
    effective_sample_count = int(weights.size - rejected_sample_count)

    return RobustIgg3FitResult(
        beta=beta,
        residuals=residuals_original,
        standardized_residuals=standardized_residuals,
        final_weights=weights,
        iterations=iterations,
        sigma0=sigma0,
        effective_sample_count=effective_sample_count,
        rejected_sample_count=rejected_sample_count,
        condition_number_before=condition_before,
        condition_number_after=condition_after,
    )


def _normalize_design_matrix(
    X: np.ndarray,
    normalize: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    column_count = X.shape[1]
    means = np.zeros(column_count, dtype=float)
    scales = np.ones(column_count, dtype=float)
    normalized_columns = np.zeros(column_count, dtype=bool)
    X_normalized = np.asarray(X, dtype=float).copy()

    if not normalize:
        return X_normalized, means, scales, normalized_columns

    for column_index in range(column_count):
        column = X[:, column_index]
        if np.allclose(column, column[0]) or np.allclose(column, 1.0):
            continue
        scale = float(np.std(column))
        if scale <= np.finfo(float).eps:
            continue
        mean_value = float(np.mean(column))
        X_normalized[:, column_index] = (column - mean_value) / scale
        means[column_index] = mean_value
        scales[column_index] = scale
        normalized_columns[column_index] = True

    return X_normalized, means, scales, normalized_columns


def _backtransform_normalized_coefficients(
    beta_normalized: np.ndarray,
    means: np.ndarray,
    scales: np.ndarray,
    normalized_columns: np.ndarray,
) -> np.ndarray:
    beta = np.asarray(beta_normalized, dtype=float).copy()
    intercept_adjustment = 0.0
    for column_index, normalized in enumerate(normalized_columns):
        if not normalized:
            continue
        beta[column_index] = beta_normalized[column_index] / scales[column_index]
        intercept_adjustment += beta_normalized[column_index] * means[column_index] / scales[column_index]
    if beta.size > 0:
        beta[0] = beta_normalized[0] - intercept_adjustment
    return beta


def _solve_weighted_normal_system(
    X: np.ndarray,
    y: np.ndarray,
    weights: np.ndarray,
    regularization: float,
) -> tuple[np.ndarray, np.ndarray] | None:
    weighted_design = weights[:, None] * X
    normal_matrix = X.T @ weighted_design
    rhs = X.T @ (weights * y)
    if _safe_reciprocal_condition(normal_matrix) < 1e-14 and regularization > 0.0:
        normal_matrix = normal_matrix + regularization * np.eye(normal_matrix.shape[0], dtype=float)
    try:
        beta = np.linalg.solve(normal_matrix, rhs)
    except np.linalg.LinAlgError:
        try:
            beta = np.linalg.lstsq(normal_matrix, rhs, rcond=None)[0]
        except np.linalg.LinAlgError:
            return None
    return beta, normal_matrix


def _weighted_hat_diagonal(X: np.ndarray, qx: np.ndarray) -> np.ndarray:
    hat = np.einsum("ij,jk,ik->i", X, qx, X)
    return np.clip(hat, 0.0, 1.0 - np.finfo(float).eps)


def _safe_condition_number(matrix: np.ndarray) -> float:
    try:
        value = float(np.linalg.cond(matrix))
    except np.linalg.LinAlgError:
        return float("inf")
    return value if np.isfinite(value) else float("inf")


def _safe_reciprocal_condition(matrix: np.ndarray) -> float:
    condition_number = _safe_condition_number(matrix)
    if condition_number <= 0.0 or not np.isfinite(condition_number):
        return 0.0
    return 1.0 / condition_number


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


