"""High-level Python facade for teradataml workflows."""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Mapping, Sequence

from .recipes import visual_fidelity
from .sql import (
    CompressionParameters,
    CompressorSpec,
    compression_sql,
    create_table_as_sql,
    feature_sql,
    features_by_mode_sql,
    register_sql,
    td_plot_sql,
)
from .tdfs4ds import ProcessFeatureEngineeringArtifact, build_process_feature_engineering_artifact


DEFAULT_FUNCTION_NAME = "ts_compress_seq_to"
DEFAULT_MAPPING_NAME = "ts_compress_seq_to_map"


def install_table_operator_sql(
    *,
    target_database: str | None,
    c_source_path: str | Path | None = None,
    function_name: str = DEFAULT_FUNCTION_NAME,
    mapping_name: str = DEFAULT_MAPPING_NAME,
) -> list[str]:
    """Return SQL statements to install the table operator in a database."""

    return register_sql(
        c_source_path=c_source_path or bundled_c_source_path(),
        target_database=target_database,
        spec=_operator_install_spec(
            function_name=function_name,
            mapping_name=mapping_name,
        ),
    )


def install_table_operator(
    *,
    target_database: str | None,
    c_source_path: str | Path | None = None,
    function_name: str = DEFAULT_FUNCTION_NAME,
    mapping_name: str = DEFAULT_MAPPING_NAME,
) -> None:
    """Install the function and mapping through ``teradataml.execute_sql``."""

    execute_sql = _teradataml_execute_sql()
    for statement in install_table_operator_sql(
        target_database=target_database,
        c_source_path=c_source_path,
        function_name=function_name,
        mapping_name=mapping_name,
    ):
        execute_sql(statement)


class TeradataTimeSeriesCompressor:
    """Pythonic wrapper for the ``ts_compress_to`` function mapping.

    Methods return SQL by default. When ``as_dataframe=True`` they lazily import
    ``teradataml`` and return ``teradataml.DataFrame.from_query(...)``.
    """

    def __init__(
        self,
        spec: CompressorSpec,
        compressor_database: str | None = None,
        operator_database: str | None = None,
    ):
        self.spec = spec
        self.operator_database = operator_database or compressor_database
        self.compressor_database = self.operator_database

    def sql(
        self,
        *,
        table_name: str | None = None,
        schema_name: str | None = None,
        data_database: str | None = None,
        input_query: str | None = None,
        dataframe: object | None = None,
        parameters: CompressionParameters | None = None,
        columns: Sequence[str] | None = None,
    ) -> str:
        input_query = _resolve_input_query(input_query, dataframe)
        source_database = _resolve_data_database(schema_name, data_database)
        return compression_sql(
            table_name=table_name,
            schema_name=source_database,
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
        data_database: str | None = None,
        input_query: str | None = None,
        dataframe: object | None = None,
        parameters: CompressionParameters | None = None,
        columns: Sequence[str] | None = None,
        as_dataframe: bool = True,
    ):
        query = self.sql(
            table_name=table_name,
            schema_name=schema_name,
            data_database=data_database,
            input_query=input_query,
            dataframe=dataframe,
            parameters=parameters,
            columns=columns,
        )
        if not as_dataframe:
            return query
        return _teradataml_dataframe(query)

    def features_sql(
        self,
        *,
        table_name: str | None = None,
        schema_name: str | None = None,
        data_database: str | None = None,
        input_query: str | None = None,
        dataframe: object | None = None,
        parameters: CompressionParameters | None = None,
        columns: Sequence[str] | None = None,
        top_k_distances: int = 0,
        label_column: str | None = None,
        label_value: object | None = None,
    ) -> str:
        input_query = _resolve_input_query(input_query, dataframe)
        source_database = _resolve_data_database(schema_name, data_database)
        return feature_sql(
            table_name=table_name,
            schema_name=source_database,
            input_query=input_query,
            compressor_database=self.compressor_database,
            spec=self.spec,
            parameters=parameters,
            columns=columns,
            top_k_distances=top_k_distances,
            label_column=label_column,
            label_value=label_value,
        )

    def features(
        self,
        *,
        table_name: str | None = None,
        schema_name: str | None = None,
        data_database: str | None = None,
        input_query: str | None = None,
        dataframe: object | None = None,
        parameters: CompressionParameters | None = None,
        columns: Sequence[str] | None = None,
        top_k_distances: int = 0,
        label_column: str | None = None,
        label_value: object | None = None,
        as_dataframe: bool = True,
    ):
        query = self.features_sql(
            table_name=table_name,
            schema_name=schema_name,
            data_database=data_database,
            input_query=input_query,
            dataframe=dataframe,
            parameters=parameters,
            columns=columns,
            top_k_distances=top_k_distances,
            label_column=label_column,
            label_value=label_value,
        )
        if not as_dataframe:
            return query
        return _teradataml_dataframe(query)

    def process_feature_engineering(
        self,
        *,
        process_database: str,
        process_name: str,
        source_object: str | None = None,
        source_database: str | None = None,
        input_query: str | None = None,
        dataframe: object | None = None,
        parameters: CompressionParameters | None = None,
        columns: Sequence[str] | None = None,
        top_k_distances: int = 0,
        mode_name: str | None = None,
        feature_prefix: str = "",
        feature_suffix: str = "",
        series_description: str | None = None,
        source_object_description: str | None = None,
        source_column_descriptions: Mapping[str, str] | None = None,
        use_tdfs4ds_dictionary: bool = True,
    ) -> ProcessFeatureEngineeringArtifact:
        """Build a tdfs4ds process view and deterministic dictionary dataframes."""

        feature_query = self.features_sql(
            table_name=source_object,
            schema_name=source_database,
            input_query=input_query,
            dataframe=dataframe,
            parameters=parameters,
            columns=columns,
            top_k_distances=top_k_distances,
        )
        return build_process_feature_engineering_artifact(
            process_database=process_database,
            process_name=process_name,
            source_database=source_database,
            source_object=source_object,
            spec=self.spec,
            feature_query=feature_query,
            parameters=parameters or CompressionParameters(),
            top_k_distances=top_k_distances,
            mode_name=mode_name,
            feature_prefix=feature_prefix,
            feature_suffix=feature_suffix,
            series_description=series_description,
            source_object_description=source_object_description,
            source_column_descriptions=source_column_descriptions,
            use_tdfs4ds_dictionary=use_tdfs4ds_dictionary,
        )

    def features_by_mode_sql(
        self,
        *,
        modes: Mapping[str, CompressionParameters],
        table_name: str | None = None,
        schema_name: str | None = None,
        data_database: str | None = None,
        input_query: str | None = None,
        dataframe: object | None = None,
        columns: Sequence[str] | None = None,
        top_k_distances: int = 0,
        mode_column: str = "mode",
        order_by: str | Sequence[str | int] | None = None,
    ) -> str:
        input_query = _resolve_input_query(input_query, dataframe)
        source_database = _resolve_data_database(schema_name, data_database)
        return features_by_mode_sql(
            modes=modes,
            table_name=table_name,
            schema_name=source_database,
            input_query=input_query,
            compressor_database=self.compressor_database,
            spec=self.spec,
            columns=columns,
            top_k_distances=top_k_distances,
            mode_column=mode_column,
            order_by=order_by,
        )

    def features_by_mode(
        self,
        *,
        modes: Mapping[str, CompressionParameters],
        table_name: str | None = None,
        schema_name: str | None = None,
        data_database: str | None = None,
        input_query: str | None = None,
        dataframe: object | None = None,
        columns: Sequence[str] | None = None,
        top_k_distances: int = 0,
        mode_column: str = "mode",
        order_by: str | Sequence[str | int] | None = None,
        as_dataframe: bool = True,
    ):
        query = self.features_by_mode_sql(
            modes=modes,
            table_name=table_name,
            schema_name=schema_name,
            data_database=data_database,
            input_query=input_query,
            dataframe=dataframe,
            columns=columns,
            top_k_distances=top_k_distances,
            mode_column=mode_column,
            order_by=order_by,
        )
        if not as_dataframe:
            return query
        return _teradataml_dataframe(query)

    def materialize_for_td_plot_sql(
        self,
        *,
        table_name: str | None = None,
        schema_name: str | None = None,
        data_database: str | None = None,
        input_query: str | None = None,
        dataframe: object | None = None,
        output_table: str,
        output_schema_name: str | None = None,
        parameters: CompressionParameters | None = None,
        columns: Sequence[str] | None = None,
    ) -> str:
        query = self.sql(
            table_name=table_name,
            schema_name=schema_name,
            data_database=data_database,
            input_query=input_query,
            dataframe=dataframe,
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
        c_source_path: str | Path | None = None,
    ) -> list[str]:
        """Return SQL statements to install the operator in a database."""

        return install_table_operator_sql(
            target_database=target_database,
            c_source_path=c_source_path,
            function_name=self.spec.function_name,
            mapping_name=self.spec.mapping_name,
        )

    def install_table_operator(
        self,
        *,
        target_database: str,
        c_source_path: str | Path | None = None,
    ) -> None:
        """Install the function and mapping through ``teradataml.execute_sql``."""

        install_table_operator(
            target_database=target_database,
            c_source_path=c_source_path,
            function_name=self.spec.function_name,
            mapping_name=self.spec.mapping_name,
        )

    def register_sql(
        self,
        c_source_path: str | Path | None = None,
        target_database: str | None = None,
    ) -> list[str]:
        return install_table_operator_sql(
            target_database=target_database,
            c_source_path=c_source_path,
            function_name=self.spec.function_name,
            mapping_name=self.spec.mapping_name,
        )

    def register(
        self,
        c_source_path: str | Path | None = None,
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


def _resolve_input_query(
    input_query: str | None,
    dataframe: object | None,
) -> str | None:
    if input_query is not None and dataframe is not None:
        raise ValueError("provide only one of input_query or dataframe")
    if dataframe is None:
        return input_query
    return _dataframe_query(dataframe)


def _resolve_data_database(
    schema_name: str | None,
    data_database: str | None,
) -> str | None:
    if schema_name and data_database and schema_name != data_database:
        raise ValueError("schema_name and data_database must match when both are provided")
    return data_database or schema_name


def _dataframe_query(dataframe: object) -> str:
    """Return SQL backing a teradataml DataFrame-like object."""

    for method_name in ("to_sql", "show_query"):
        method = getattr(dataframe, method_name, None)
        if method is None:
            continue
        try:
            value = method()
        except TypeError:
            continue
        if isinstance(value, str) and value.strip():
            return value.strip().rstrip(";")

    for attr_name in ("query", "_query"):
        value = getattr(dataframe, attr_name, None)
        if isinstance(value, str) and value.strip():
            return value.strip().rstrip(";")

    for attr_name in ("table_name", "_table_name"):
        value = getattr(dataframe, attr_name, None)
        if isinstance(value, str) and value.strip():
            return f"SELECT * FROM {value.strip()}"

    raise TypeError(
        "dataframe must expose SQL through to_sql(), show_query(), query, "
        "_query, table_name, or _table_name"
    )


def bundled_c_source_path() -> Path:
    """Return the installed path to the bundled ``ts_compress_to.c`` source."""

    source = resources.files("td_ts_compressor.resources").joinpath(
        "ts_compress_to.c"
    )
    return Path(str(source))


def _operator_install_spec(
    *,
    function_name: str,
    mapping_name: str,
) -> CompressorSpec:
    return CompressorSpec(
        id_columns=["series_id"],
        time_column="seq_no",
        value_column="y",
        function_name=function_name,
        mapping_name=mapping_name,
    )


def _teradataml_execute_sql():
    try:
        from teradataml import execute_sql
    except ImportError as exc:
        raise ImportError("Install the teradataml extra before executing SQL.") from exc
    return execute_sql
