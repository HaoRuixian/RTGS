"""Paths to read-only PPP model data distributed with RTGS."""

from __future__ import annotations

from pathlib import Path

PPP_RESOURCE_DIR = Path(__file__).resolve().parent / "resources" / "ppp"
DEFAULT_ANTEX_PATH = PPP_RESOURCE_DIR / "igs20.atx.gz"
DEFAULT_BLQ_PATH = PPP_RESOURCE_DIR / "OCEAN-GOT48.blq"


def default_ppp_model_path(kind: str) -> Path:
    """Return a bundled PPP model path and fail clearly if packaging omitted it."""
    normalized = str(kind or "").strip().lower()
    if normalized == "antex":
        path = DEFAULT_ANTEX_PATH
    elif normalized == "blq":
        path = DEFAULT_BLQ_PATH
    else:
        raise ValueError(f"Unknown PPP model resource: {kind}")
    if not path.is_file():
        raise FileNotFoundError(f"Bundled PPP {normalized.upper()} resource is missing: {path}")
    return path


__all__ = [
    "DEFAULT_ANTEX_PATH",
    "DEFAULT_BLQ_PATH",
    "PPP_RESOURCE_DIR",
    "default_ppp_model_path",
]
