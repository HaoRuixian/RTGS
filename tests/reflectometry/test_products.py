"""Product policy tests."""

from core.reflectometry.config import ProductsConfig
from core.reflectometry.services.products import apply_environment_product_policy


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

