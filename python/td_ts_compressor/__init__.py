"""Python interface for the Teradata ``ts_compress_to`` table operator."""

from .core import TeradataTimeSeriesCompressor
from .recipes import analytical_points, fixed_budget, visual_fidelity
from .sql import CompressionParameters, CompressorSpec
from .tdfs4ds import ProcessFeatureEngineeringArtifact

__version__ = "0.1.9"

__all__ = [
    "CompressionParameters",
    "CompressorSpec",
    "ProcessFeatureEngineeringArtifact",
    "TeradataTimeSeriesCompressor",
    "__version__",
    "analytical_points",
    "fixed_budget",
    "visual_fidelity",
]
