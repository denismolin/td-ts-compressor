"""Helpers for tdfs4ds process-view feature engineering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .sql import (
    CompressionParameters,
    CompressorSpec,
    _feature_output_columns,
    qualified_table_name,
    quote_identifier,
    quote_literal,
)


BUSINESS_OBJECT_COLUMNS = [
    "DATABASE_NAME",
    "OBJECT_NAME",
    "OBJECT_TYPE",
    "BUSINESS_DESCRIPTION",
]
BUSINESS_COLUMN_COLUMNS = [
    "DATABASE_NAME",
    "TABLE_NAME",
    "COLUMN_NAME",
    "BUSINESS_DESCRIPTION",
]


@dataclass(frozen=True)
class ProcessFeatureEngineeringArtifact:
    """Generated tdfs4ds process view and business dictionary payloads."""

    process_database: str
    process_name: str
    process_sql: str
    feature_names: list[str]
    object_df: object
    columns_df: object
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def qualified_process_name(self) -> str:
        return qualified_table_name(self.process_name, self.process_database)


@dataclass(frozen=True)
class SourceDocumentation:
    """Business dictionary context used to describe generated features."""

    object_description: str | None
    column_descriptions: dict[str, str]


def build_process_feature_engineering_artifact(
    *,
    process_database: str,
    process_name: str,
    source_database: str | None,
    source_object: str | None,
    spec: CompressorSpec,
    feature_query: str,
    parameters: CompressionParameters,
    top_k_distances: int = 0,
    mode_name: str | None = None,
    feature_prefix: str = "",
    feature_suffix: str = "",
    series_description: str | None = None,
    source_object_description: str | None = None,
    source_column_descriptions: Mapping[str, str] | None = None,
    use_tdfs4ds_dictionary: bool = True,
) -> ProcessFeatureEngineeringArtifact:
    """Build a process view SQL statement and tdfs4ds dictionary dataframes."""

    process_database = _require_non_empty("process_database", process_database)
    process_name = _require_non_empty("process_name", process_name)
    source_docs = _resolve_source_documentation(
        source_database=source_database,
        source_object=source_object,
        columns=[*spec.id_columns, spec.time_column, spec.value_column],
        explicit_object_description=source_object_description,
        explicit_column_descriptions=source_column_descriptions,
        use_tdfs4ds_dictionary=use_tdfs4ds_dictionary,
    )
    output_columns = _feature_output_columns(
        spec=spec,
        top_k_distances=top_k_distances,
    )
    id_columns = list(spec.id_columns)
    base_feature_names = [column for column in output_columns if column not in id_columns]
    feature_names = [_apply_affixes(name, feature_prefix, feature_suffix) for name in base_feature_names]
    process_sql = _process_view_sql(
        process_database=process_database,
        process_name=process_name,
        feature_query=feature_query,
        id_columns=id_columns,
        base_feature_names=base_feature_names,
        feature_names=feature_names,
    )
    docs = _documentation_context(
        spec=spec,
        mode_name=mode_name,
        parameters=parameters,
        source_database=source_database,
        source_object=source_object,
        source_docs=source_docs,
        series_description=series_description,
    )
    object_df, columns_df = _business_dictionary_dataframes(
        process_database=process_database,
        process_name=process_name,
        id_columns=id_columns,
        feature_pairs=list(zip(base_feature_names, feature_names)),
        docs=docs,
    )
    metadata = {
        "source": "td-ts-compressor",
        "mode": mode_name,
        "source_database": source_database,
        "source_object": source_object,
    }
    return ProcessFeatureEngineeringArtifact(
        process_database=process_database,
        process_name=process_name,
        process_sql=process_sql,
        feature_names=feature_names,
        object_df=object_df,
        columns_df=columns_df,
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _process_view_sql(
    *,
    process_database: str,
    process_name: str,
    feature_query: str,
    id_columns: Sequence[str],
    base_feature_names: Sequence[str],
    feature_names: Sequence[str],
) -> str:
    select_lines = [f"    {quote_identifier(column)}" for column in id_columns]
    select_lines.extend(
        f"    {quote_identifier(source)} AS {quote_identifier(target)}"
        for source, target in zip(base_feature_names, feature_names)
    )
    select_sql = ",\n".join(select_lines)
    return f"""REPLACE VIEW {qualified_table_name(process_name, process_database)} AS
LOCKING ROW FOR ACCESS
SELECT
{select_sql}
FROM (
{feature_query}
) AS compressor_features"""


def _resolve_source_documentation(
    *,
    source_database: str | None,
    source_object: str | None,
    columns: Sequence[str],
    explicit_object_description: str | None,
    explicit_column_descriptions: Mapping[str, str] | None,
    use_tdfs4ds_dictionary: bool,
) -> SourceDocumentation:
    column_docs = dict(explicit_column_descriptions or {})
    object_doc = explicit_object_description
    if use_tdfs4ds_dictionary and source_database and source_object:
        fetched = _fetch_tdfs4ds_business_dictionary(
            source_database=source_database,
            source_object=source_object,
            columns=columns,
        )
        if object_doc is None:
            object_doc = fetched.object_description
        for column, description in fetched.column_descriptions.items():
            column_docs.setdefault(column, description)
    return SourceDocumentation(
        object_description=object_doc,
        column_descriptions=column_docs,
    )


def _fetch_tdfs4ds_business_dictionary(
    *,
    source_database: str,
    source_object: str,
    columns: Sequence[str],
) -> SourceDocumentation:
    try:
        import tdfs4ds  # type: ignore
        from teradataml import DataFrame  # type: ignore
    except ImportError:
        return SourceDocumentation(None, {})

    dictionary_schema = (
        getattr(tdfs4ds, "SCHEMA", None)
        or getattr(tdfs4ds, "DATABASE", None)
        or source_database
    )
    object_description = _fetch_object_description(
        DataFrame=DataFrame,
        dictionary_schema=dictionary_schema,
        source_database=source_database,
        source_object=source_object,
    )
    column_descriptions = _fetch_column_descriptions(
        DataFrame=DataFrame,
        dictionary_schema=dictionary_schema,
        source_database=source_database,
        source_object=source_object,
        columns=columns,
    )
    return SourceDocumentation(object_description, column_descriptions)


def _fetch_object_description(
    *,
    DataFrame: object,
    dictionary_schema: str,
    source_database: str,
    source_object: str,
) -> str | None:
    query = f"""
SELECT BUSINESS_DESCRIPTION
FROM {qualified_table_name("FS_BUSINESS_DICTIONARY_OBJECTS", dictionary_schema)}
WHERE UPPER(DATABASE_NAME) = UPPER({quote_literal(source_database)})
  AND UPPER(OBJECT_NAME) = UPPER({quote_literal(source_object)})
"""
    try:
        rows = DataFrame.from_query(query).to_pandas()
    except Exception:
        return None
    if rows.empty or "BUSINESS_DESCRIPTION" not in rows:
        return None
    value = rows["BUSINESS_DESCRIPTION"].dropna()
    if value.empty:
        return None
    return str(value.iloc[0])


def _fetch_column_descriptions(
    *,
    DataFrame: object,
    dictionary_schema: str,
    source_database: str,
    source_object: str,
    columns: Sequence[str],
) -> dict[str, str]:
    if not columns:
        return {}
    column_literals = ", ".join(quote_literal(column.upper()) for column in columns)
    query = f"""
SELECT COLUMN_NAME, BUSINESS_DESCRIPTION
FROM {qualified_table_name("FS_BUSINESS_DICTIONARY_COLUMNS", dictionary_schema)}
WHERE UPPER(DATABASE_NAME) = UPPER({quote_literal(source_database)})
  AND UPPER(TABLE_NAME) = UPPER({quote_literal(source_object)})
  AND UPPER(COLUMN_NAME) IN ({column_literals})
"""
    try:
        rows = DataFrame.from_query(query).to_pandas()
    except Exception:
        return {}
    if rows.empty:
        return {}
    column_lookup = {column.upper(): column for column in columns}
    return {
        column_lookup.get(str(row["COLUMN_NAME"]).upper(), str(row["COLUMN_NAME"])): str(
            row["BUSINESS_DESCRIPTION"]
        )
        for _, row in rows.dropna(subset=["COLUMN_NAME", "BUSINESS_DESCRIPTION"]).iterrows()
    }


def _documentation_context(
    *,
    spec: CompressorSpec,
    mode_name: str | None,
    parameters: CompressionParameters,
    source_database: str | None,
    source_object: str | None,
    source_docs: SourceDocumentation,
    series_description: str | None,
) -> dict[str, object]:
    column_docs = source_docs.column_descriptions
    value_doc = column_docs.get(spec.value_column)
    time_doc = column_docs.get(spec.time_column)
    id_docs = {
        column: column_docs.get(column)
        for column in spec.id_columns
        if column_docs.get(column)
    }
    series_text = series_description or _derive_series_description(
        spec=spec,
        value_doc=value_doc,
        id_docs=id_docs,
    )
    mode_text = mode_name or _mode_description(parameters)
    source_name = (
        qualified_table_name(source_object, source_database)
        if source_database and source_object
        else source_object
    )
    return {
        "series": series_text,
        "mode": mode_text,
        "source_name": source_name,
        "source_description": source_docs.object_description,
        "value_doc": value_doc,
        "time_doc": time_doc,
        "id_docs": id_docs,
    }


def _derive_series_description(
    *,
    spec: CompressorSpec,
    value_doc: str | None,
    id_docs: Mapping[str, str],
) -> str:
    if value_doc:
        return f"{value_doc.rstrip('.')} time series"
    if id_docs:
        return "series identified by " + ", ".join(id_docs.values())
    return "time series"


def _mode_description(parameters: CompressionParameters) -> str:
    if parameters.n_max == "auto":
        return "analytical important-points mode"
    if str(parameters.distance_max) != "-1":
        return "visual-fidelity mode"
    return "fixed-budget compression mode"


def _business_dictionary_dataframes(
    *,
    process_database: str,
    process_name: str,
    id_columns: Sequence[str],
    feature_pairs: Sequence[tuple[str, str]],
    docs: Mapping[str, object],
) -> tuple[object, object]:
    pd = _pandas()
    object_description = _object_description(docs)
    object_df = pd.DataFrame(
        [
            {
                "DATABASE_NAME": process_database,
                "OBJECT_NAME": process_name,
                "OBJECT_TYPE": "V",
                "BUSINESS_DESCRIPTION": object_description,
            }
        ],
        columns=BUSINESS_OBJECT_COLUMNS,
    )
    column_rows = [
        {
            "DATABASE_NAME": process_database,
            "TABLE_NAME": process_name,
            "COLUMN_NAME": column,
            "BUSINESS_DESCRIPTION": _id_column_description(column, docs),
        }
        for column in id_columns
    ]
    column_rows.extend(
        {
            "DATABASE_NAME": process_database,
            "TABLE_NAME": process_name,
            "COLUMN_NAME": output_name,
            "BUSINESS_DESCRIPTION": _feature_description(base_name, docs),
        }
        for base_name, output_name in feature_pairs
    )
    columns_df = pd.DataFrame(column_rows, columns=BUSINESS_COLUMN_COLUMNS)
    return object_df, columns_df


def _object_description(docs: Mapping[str, object]) -> str:
    source = docs.get("source_name")
    source_description = docs.get("source_description")
    source_clause = f" from {source}" if source else ""
    if source_description:
        source_clause += f", whose business meaning is: {source_description}"
    return (
        f"Feature engineering process view that summarizes each {docs['series']}"
        f"{source_clause}. The view applies ts_compress_to in {docs['mode']} and "
        "returns compression scale, retained-point, reduction, and selected-distance features."
    )


def _id_column_description(column: str, docs: Mapping[str, object]) -> str:
    id_docs = docs.get("id_docs") or {}
    if isinstance(id_docs, Mapping) and id_docs.get(column):
        return str(id_docs[column])
    return f"Identifier column for each {docs['series']}."


def _feature_description(base_name: str, docs: Mapping[str, object]) -> str:
    series = docs["series"]
    value_context = _value_context(docs)
    descriptions = {
        "original_points": f"Number of original observations in each {series}{value_context}.",
        "remaining_points": f"Number of observations retained by ts_compress_to for each {series}.",
        "compressed_points": f"Number of compressed points selected for each {series}.",
        "retained_ratio": f"Share of original observations retained after compression for each {series}.",
        "retained_pct": f"Percentage of original observations retained after compression for each {series}.",
        "compression_ratio": f"Ratio of original observations to retained compressed observations for each {series}. Higher values indicate stronger compression.",
        "reduction_pct": f"Percentage reduction in observations after compression for each {series}.",
        "max_selected_distance": f"Largest selected-point residual distance for each {series}, measured in the compressor's scaled coordinate system.",
        "avg_selected_distance": f"Average selected-point residual distance for each {series}, measured in the compressor's scaled coordinate system.",
        "std_selected_distance": f"Sample standard deviation of selected-point residual distances for each {series}.",
    }
    if base_name.startswith("distance_rank_"):
        rank = base_name.rsplit("_", 1)[-1]
        if rank in {"1", "2"}:
            endpoint = "first" if rank == "1" else "last"
            return (
                f"Residual distance of the {endpoint} endpoint with compression importance rank {rank} "
                f"for each {series}. Always 0 when present because endpoints are retained "
                "without a residual-distance calculation; NULL when this rank is absent."
            )
        return (
            f"Residual distance of the selected point with compression importance rank {rank} "
            f"for each {series}."
        )
    return descriptions[base_name]


def _value_context(docs: Mapping[str, object]) -> str:
    value_doc = docs.get("value_doc")
    time_doc = docs.get("time_doc")
    pieces = []
    if value_doc:
        pieces.append(f"value: {value_doc}")
    if time_doc:
        pieces.append(f"ordered by: {time_doc}")
    if not pieces:
        return ""
    return " (" + "; ".join(pieces) + ")"


def _apply_affixes(name: str, prefix: str, suffix: str) -> str:
    return f"{prefix}{name}{suffix}"


def _require_non_empty(name: str, value: str | None) -> str:
    if value is None or not str(value).strip():
        raise ValueError(f"{name} must be provided")
    return str(value).strip()


def _pandas():
    try:
        import pandas as pd
    except ImportError as exc:
        raise ImportError(
            "pandas is required to build tdfs4ds business dictionary dataframes"
        ) from exc
    return pd
