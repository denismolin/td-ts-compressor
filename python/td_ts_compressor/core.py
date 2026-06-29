"""High-level Python facade for teradataml workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .recipes import visual_fidelity
from .sql import (
    CompressionParameters,
    CompressorSpec,
    compression_sql,
    create_table_as_sql,
    feature_sql,
    register_sql,
    td_plot_sql,
)


class TeradataTimeSeriesCompressor:
    """Pythonic wrapper for the ``ts_compress_to`` function mapping.

    Methods return SQL by default. When ``as_dataframe=True`` they lazily import
    ``teradataml`` and return ``teradataml.DataFrame.from_query(...)``.
    """

    def __init__(self, spec: CompressorSpec, compressor_database: str | None = None):
        self.spec = spec
        self.compressor_database = compressor_database

    def sql(
        self,
        *,
        table_name: str | None = None,
        schema_name: str | None = None,
        input_query: str | None = None,
        parameters: CompressionParameters | None = None,
        columns: Sequence[str] | None = None,
    ) -> str:
        return compression_sql(
            table_name=table_name,
            schema_name=schema_name,
            compressor_database=self.compressor_database,
            input_query=input_query,
            spec=self.spec,
            parameters=parameters,
            columns=columns,
        )

    def compress(
        self,
        *,
        table_name: str | None = None,
        schema_name: str | None = None,
        input_query: str | None = None,
        parameters: CompressionParameters | None = None,
        columns: Sequence[str] | None = None,
        as_dataframe: bool = True,
    ):
        query = self.sql(
            table_name=table_name,
            schema_name=schema_name,
            input_query=input_query,
            parameters=parameters,
            columns=columns,
        )
        if not as_dataframe:
            return query
        return _teradataml_dataframe(query)

    def features_sql(
        self,
        *,
        table_name: str,
        schema_name: str | None = None,
        parameters: CompressionParameters | None = None,
        columns: Sequence[str] | None = None,
        top_k_distances: int = 0,
    ) -> str:
        return feature_sql(
            table_name=table_name,
            schema_name=schema_name,
            compressor_database=self.compressor_database,
            spec=self.spec,
            parameters=parameters,
            columns=columns,
            top_k_distances=top_k_distances,
        )

    def features(
        self,
        *,
        table_name: str,
        schema_name: str | None = None,
        parameters: CompressionParameters | None = None,
        columns: Sequence[str] | None = None,
        top_k_distances: int = 0,
        as_dataframe: bool = True,
    ):
        query = self.features_sql(
            table_name=table_name,
            schema_name=schema_name,
            parameters=parameters,
            columns=columns,
            top_k_distances=top_k_distances,
        )
        if not as_dataframe:
            return query
        return _teradataml_dataframe(query)

    def materialize_for_td_plot_sql(
        self,
        *,
        table_name: str,
        schema_name: str | None = None,
        output_table: str,
        output_schema_name: str | None = None,
        parameters: CompressionParameters | None = None,
        columns: Sequence[str] | None = None,
    ) -> str:
        query = self.sql(
            table_name=table_name,
            schema_name=schema_name,
            parameters=parameters or visual_fidelity(),
            columns=columns,
        )
        return create_table_as_sql(
            table_name=output_table,
            schema_name=output_schema_name,
            query=query,
            primary_index=self.spec.id_columns,
        )

    def td_plot_sql(
        self,
        *,
        table_name: str,
        schema_name: str | None = None,
        title: str | None = None,
        width: int = 1024,
        height: int = 768,
        plot_type: str = "line",
    ) -> str:
        return td_plot_sql(
            table_name=table_name,
            schema_name=schema_name,
            spec=self.spec,
            title=title,
            width=width,
            height=height,
            plot_type=plot_type,
        )

    def install_table_operator_sql(
        self,
        *,
        target_database: str,
        c_source_path: str | Path,
    ) -> list[str]:
        """Return SQL statements to install the operator in a database."""

        return register_sql(
            c_source_path=c_source_path,
            target_database=target_database,
            spec=self.spec,
        )

    def install_table_operator(
        self,
        *,
        target_database: str,
        c_source_path: str | Path,
    ) -> None:
        """Install the function and mapping through ``teradataml.execute_sql``."""

        execute_sql = _teradataml_execute_sql()
        for statement in self.install_table_operator_sql(
            target_database=target_database,
            c_source_path=c_source_path,
        ):
            execute_sql(statement)

    def register_sql(
        self,
        c_source_path: str | Path,
        target_database: str | None = None,
    ) -> list[str]:
        return register_sql(
            c_source_path=c_source_path,
            target_database=target_database,
            spec=self.spec,
        )

    def register(
        self,
        c_source_path: str | Path,
        target_database: str | None = None,
    ) -> None:
        execute_sql = _teradataml_execute_sql()
        for statement in self.register_sql(c_source_path, target_database):
            execute_sql(statement)

    def execute(self, statement: str) -> None:
        _teradataml_execute_sql()(statement)


def _teradataml_dataframe(query: str):
    try:
        from teradataml import DataFrame
    except ImportError as exc:
        raise ImportError(
            "Install the teradataml extra or pass as_dataframe=False to receive SQL."
        ) from exc
    return DataFrame.from_query(query)


def _teradataml_execute_sql():
    try:
        from teradataml import execute_sql
    except ImportError as exc:
        raise ImportError("Install the teradataml extra before executing SQL.") from exc
    return execute_sql
