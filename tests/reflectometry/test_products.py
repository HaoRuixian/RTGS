"""Product policy tests."""

from datetime import datetime, timedelta

from core.reflectometry.config import ProductsConfig
from core.reflectometry.models import ArcDirection, ArcSolution, ProductResult, ProductType
from core.reflectometry.services.products import ProductConverter, apply_environment_product_policy


def test_coastal_environment_disables_snow_products():
    config = ProductsConfig(
        enable_reflector_height=True,
        enable_sea_level=False,
        enable_snow_depth=True,
        sea_level_reference=6.8,
        snow_depth_reference_height=4.8,
    )

    normalized = apply_environment_product_policy(config, "coastal")

    assert normalized.enable_reflector_height is True
    assert normalized.enable_sea_level is True
    assert normalized.enable_snow_depth is False
    assert normalized.snow_depth_reference_height is None


def test_snow_environment_disables_sea_level_products():
    config = ProductsConfig(
        enable_reflector_height=True,
        enable_sea_level=True,
        enable_snow_depth=False,
        sea_level_reference=6.8,
        snow_depth_reference_height=4.8,
    )

    normalized = apply_environment_product_policy(config, "snowfield")

    assert normalized.enable_reflector_height is True
    assert normalized.enable_sea_level is False
    assert normalized.enable_snow_depth is True
    assert normalized.sea_level_reference is None


def test_product_aggregate_uses_peak_to_noise_ratio_weights():
    converter = ProductConverter(ProductsConfig())
    window_start = datetime(2026, 3, 19, 0, 0, 0)
    window_end = window_start + timedelta(minutes=30)
    products = [
        ProductResult(
            product_type=ProductType.REFLECTOR_HEIGHT,
            timestamp=window_start,
            value=4.0,
            unit="m",
            source_arc_count=1,
            confidence=0.95,
            metadata={"peak_to_noise_ratio": 1.0},
        ),
        ProductResult(
            product_type=ProductType.REFLECTOR_HEIGHT,
            timestamp=window_start + timedelta(minutes=5),
            value=8.0,
            unit="m",
            source_arc_count=1,
            confidence=0.10,
            metadata={"peak_to_noise_ratio": 9.0},
        ),
    ]

    aggregates = converter.aggregate(products, window_start, window_end)

    assert len(aggregates) == 1
    aggregate_product = aggregates[0].products[0]
    assert aggregate_product.value == 7.6
    assert aggregate_product.metadata["aggregation"] == "pnr_weighted_mean"
    assert aggregate_product.metadata["weight_field"] == "peak_to_noise_ratio"


def test_product_converter_adds_second_order_dynamic_sea_level_products():
    converter = ProductConverter(
        ProductsConfig(
            enable_reflector_height=True,
            enable_sea_level=True,
            sea_level_reference=10.0,
            enable_dynamic_sea_level_correction=True,
            dynamic_sea_level_window_hours=1.0,
            dynamic_sea_level_min_points=6,
        )
    )
    start = datetime(2026, 3, 19, 0, 0, 0)
    corrected_height = 2.0
    velocity_mps = 0.005
    acceleration_mps2 = 1.0e-5
    roc_like_seconds = 120.0
    solutions: list[ArcSolution] = []
    for index in range(6):
        timestamp = start + timedelta(seconds=index * 60)
        delta_t_seconds = (timestamp - (start + timedelta(seconds=300))).total_seconds()
        sea_level = (
            corrected_height
            + (roc_like_seconds + delta_t_seconds) * velocity_mps
            + (roc_like_seconds * delta_t_seconds + delta_t_seconds**2) * acceleration_mps2
        )
        reflector_height = 10.0 - sea_level
        solutions.append(
            ArcSolution(
                station_id="TEST",
                arc_id=f"ARC-{index}",
                timestamp_start=timestamp,
                timestamp_end=timestamp + timedelta(seconds=30),
                constellation="G",
                satellite="G01",
                signal="1C",
                arc_direction=ArcDirection.RISING,
                reflector_height_m=reflector_height,
                peak_frequency=1.0,
                peak_power=12.0,
                peak_to_noise_ratio=6.0,
                qc_flags=[],
                success=True,
                quality_metrics=None,
                metadata={"roc_like": roc_like_seconds},
            )
        )

    products = converter.convert(solutions)

    corrected_products = [
        item for item in products if item.product_type == ProductType.SEA_LEVEL_DYNAMIC_CORRECTED
    ]
    rate_products = [item for item in products if item.product_type == ProductType.SEA_LEVEL_RATE]
    acceleration_products = [
        item for item in products if item.product_type == ProductType.SEA_LEVEL_ACCELERATION
    ]

    assert corrected_products
    assert rate_products
    assert acceleration_products

    latest_corrected = sorted(corrected_products, key=lambda item: item.timestamp)[-1]
    latest_rate = sorted(rate_products, key=lambda item: item.timestamp)[-1]
    latest_acceleration = sorted(acceleration_products, key=lambda item: item.timestamp)[-1]

    assert round(latest_corrected.value, 6) == round(corrected_height, 6)
    assert round(latest_rate.value, 6) == round(velocity_mps, 6)
    assert round(latest_acceleration.value, 8) == round(acceleration_mps2, 8)
    assert latest_corrected.metadata["dynamic_model_order"] == 2
    assert latest_corrected.metadata["dynamic_sample_count"] == 6
    assert latest_corrected.metadata["signal"] == "Combined"


def test_dynamic_correction_uses_igg3_to_reject_outliers():
    converter = ProductConverter(
        ProductsConfig(
            enable_reflector_height=True,
            enable_sea_level=True,
            sea_level_reference=10.0,
            enable_dynamic_sea_level_correction=True,
            dynamic_sea_level_window_hours=1.0,
            dynamic_sea_level_min_points=6,
            dynamic_sea_level_max_iterations=25,
            dynamic_sea_level_igg3_k0=0.5,
            dynamic_sea_level_igg3_k1=2.0,
        )
    )
    start = datetime(2026, 3, 19, 0, 0, 0)
    corrected_height = 2.0
    velocity_mps = 0.004
    acceleration_mps2 = 8.0e-6
    roc_like_seconds = 90.0
    outlier_index = 2
    solutions: list[ArcSolution] = []
    for index in range(7):
        timestamp = start + timedelta(seconds=index * 60)
        delta_t_seconds = (timestamp - (start + timedelta(seconds=360))).total_seconds()
        sea_level = (
            corrected_height
            + (roc_like_seconds + delta_t_seconds) * velocity_mps
            + (roc_like_seconds * delta_t_seconds + delta_t_seconds**2) * acceleration_mps2
        )
        if index == outlier_index:
            sea_level += 2.0
        reflector_height = 10.0 - sea_level
        solutions.append(
            ArcSolution(
                station_id="TEST",
                arc_id=f"OUTLIER-{index}",
                timestamp_start=timestamp,
                timestamp_end=timestamp + timedelta(seconds=30),
                constellation="G",
                satellite="G02",
                signal="1C",
                arc_direction=ArcDirection.RISING,
                reflector_height_m=reflector_height,
                peak_frequency=1.0,
                peak_power=12.0,
                peak_to_noise_ratio=8.0,
                qc_flags=[],
                success=True,
                quality_metrics=None,
                metadata={"roc_like": roc_like_seconds},
            )
        )

    products = converter.convert(solutions)
    corrected_products = [
        item for item in products if item.product_type == ProductType.SEA_LEVEL_DYNAMIC_CORRECTED
    ]
    assert corrected_products

    latest_corrected = sorted(corrected_products, key=lambda item: item.timestamp)[-1]
    assert abs(latest_corrected.value - corrected_height) < 0.02
    assert latest_corrected.metadata["dynamic_regression_method"] == "igg3"
    assert latest_corrected.metadata["dynamic_effective_sample_count"] >= 5
    assert latest_corrected.metadata["dynamic_rejected_sample_count"] >= 1
