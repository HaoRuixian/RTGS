"""Formatting helpers for optional monitoring observations."""


def format_optional_observation(value, *, precision: int) -> str:
    """Format an available numeric observation, or leave a missing one blank."""
    if value is None:
        return ""
    return f"{float(value):.{precision}f}"
