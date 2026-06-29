"""Parameter recipes for common compression workflows."""

from __future__ import annotations

from .sql import CompressionParameters


def visual_fidelity(
    *,
    width_px: int = 1024,
    height_px: int = 768,
    distance_max: float = 1.0,
    plot_x_fraction: float = 0.95,
) -> CompressionParameters:
    """Keep enough points for a line plot at the requested display size."""

    return CompressionParameters(
        distance_max=distance_max,
        n_max="-1",
        tol_x="auto",
        tol_y="auto",
        plot_width_px=width_px,
        plot_height_px=height_px,
        plot_x_fraction=plot_x_fraction,
    )


def analytical_points(*, auto_log_drop: float = 1.5) -> CompressionParameters:
    """Extract important points using the operator's adaptive elbow rule."""

    return CompressionParameters(
        distance_max="-1",
        n_max="auto",
        auto_log_drop=auto_log_drop,
        tol_x="auto",
        tol_y="auto",
    )


def fixed_budget(*, n_max: int) -> CompressionParameters:
    """Keep a fixed maximum number of important points per series."""

    if n_max < 2:
        raise ValueError("n_max must be at least 2 because endpoints are always kept")
    return CompressionParameters(
        distance_max="-1",
        n_max=str(n_max),
        tol_x="auto",
        tol_y="auto",
    )
