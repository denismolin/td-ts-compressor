"""Python interface for the Teradata ``ts_compress_to`` table operator."""

from .core import TeradataTimeSeriesCompressor
from .recipes import analytical_points, fixed_budget, visual_fidelity
from .sql import CompressionParameters, CompressorSpec

__all__ = [
    "CompressionParameters",
    "CompressorSpec",
    "TeradataTimeSeriesCompressor",
    "analytical_points",
    "fixed_budget",
    "visual_fidelity",
]
