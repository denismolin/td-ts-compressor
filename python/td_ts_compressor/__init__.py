"""Python interface for the Teradata ``ts_compress_to`` table operator."""

from .core import (
    TeradataTimeSeriesCompressor,
    install_table_operator,
    install_table_operator_sql,
)
from .recipes import analytical_points, fixed_budget, visual_fidelity
from .sql import CompressionParameters, CompressorSpec
from .tdfs4ds import ProcessFeatureEngineeringArtifact

__version__ = "0.1.10"

__all__ = [
    "CompressionParameters",
    "CompressorSpec",
    "ProcessFeatureEngineeringArtifact",
    "TeradataTimeSeriesCompressor",
    "__version__",
    "install_table_operator",
    "install_table_operator_sql",
    "analytical_points",
    "fixed_budget",
    "visual_fidelity",
]
