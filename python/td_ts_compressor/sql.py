"""SQL builders for the ``ts_compress_to`` Teradata table operator."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re
from typing import Iterable, Mapping, Sequence


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$#]*$")


def _as_list(values: str | Sequence[str]) -> list[str]:
    if isinstance(values, str):
        return [values]
    return list(values)


def quote_literal(value: object) -> str:
    """Return a Teradata string literal."""

    text = str(value)
    return "'" + text.replace("'", "''") + "'"


def quote_identifier(identifier: str) -> str:
    """Return an identifier, quoting only when needed."""

    if "." in identifier:
        return ".".join(quote_identifier(part) for part in identifier.split("."))
    if _IDENTIFIER_RE.match(identifier):
        return identifier
    return '"' + identifier.replace('"', '""') + '"'


def _using_clause(name: str, value: object) -> str:
    return f"        {name}({quote_literal(value)})"


@dataclass(frozen=True)
class CompressionParameters:
    """Operator USING parameters.

    Values are serialized as Teradata string literals because the function
    mapping exposes the parameters in SQLTable style.

    ``min_relative_gain`` and ``min_absolute_gain`` are accepted for compatibility
    but have no effect in the bundled C operator.
    """

    distance_max: str | int | float = 1.0
    n_max: str | int = "-1"
    min_relative_gain: str | int | float | None = None
    min_absolute_gain: str | int | float | None = None
    auto_log_drop: str | int | float | None = None
    tol_x: str | int | float = "auto"
    tol_y: str | int | float = "auto"
    plot_width_px: int = 1600
    plot_height_px: int = 900
    plot_x_fraction: str | int | float = 0.95

    def with_overrides(self, **overrides: object) -> "CompressionParameters":
        return replace(self, **overrides)

    def using_lines(self) -> list[str]:
        values = {
            "distance_max": self.distance_max,
            "n_max": self.n_max,
            "min_relative_gain": self.min_relative_gain,
            "min_absolute_gain": self.min_absolute_gain,
            "auto_log_drop": self.auto_log_drop,
            "tol_x": self.tol_x,
            "tol_y": self.tol_y,
            "plot_width_px": self.plot_width_px,
            "plot_height_px": self.plot_height_px,
            "plot_x_fraction": self.plot_x_fraction,
        }
        return [
            _using_clause(name, value)
            for name, value in values.items()
            if value is not None
        ]


@dataclass(frozen=True)
class CompressorSpec:
    """Column and mapping configuration for one compressor invocation."""

    id_columns: Sequence[str]
    time_column: str
    value_column: str
    time_type: str = "auto"
    time_unit: str = "second"
    mapping_name: str = "ts_compress_seq_to_map"
    function_name: str = "ts_compress_seq_to"

    def __post_init__(self) -> None:
        if not self.id_columns:
            raise ValueError("id_columns must contain at least one column")

    @property
    def id_column_csv(self) -> str:
        return ",".join(self.id_columns)

    def ordered_columns(self, columns: Sequence[str] | None = None) -> list[str]:
        if columns is not None:
            return list(columns)
        ordered = [*self.id_columns, self.time_column, self.value_column]
        return list(dict.fromkeys(ordered))


def qualified_table_name(table_name: str, schema_name: str | None = None) -> str:
    """Return a quoted table name, optionally schema-qualified."""

    if schema_name:
        return f"{quote_identifier(schema_name)}.{quote_identifier(table_name)}"
    return quote_identifier(table_name)


def _source_count(table_name: str | None, input_query: str | None) -> int:
    return sum(value is not None for value in (table_name, input_query))


def source_sql(
    *,
    table_name: str | None = None,
    schema_name: str | None = None,
    input_query: str | None = None,
) -> str:
    """Return a FROM source for a table, view, or SQL query."""

    if _source_count(table_name, input_query) != 1:
        raise ValueError("provide exactly one of table_name or input_query")
    if schema_name and not table_name:
        raise ValueError("schema_name requires table_name")

    if table_name:
        return qualified_table_name(table_name, schema_name)
    return f"(\n{input_query}\n        ) AS source_query"


def input_projection_sql(
    *,
    table_name: str | None = None,
    schema_name: str | None = None,
    input_query: str | None = None,
    spec: CompressorSpec,
    columns: Sequence[str] | None = None,
) -> str:
    """Build the schema-preserving ON subquery with metadata placeholders."""

    selected_columns = spec.ordered_columns(columns)
    compact_numeric_projection = (
        len(selected_columns) == len(spec.id_columns) + 2
        and selected_columns == [*spec.id_columns, spec.time_column, spec.value_column]
        and spec.time_type.lower() == "numeric"
    )
    projection = []
    for column in selected_columns:
        identifier = quote_identifier(column)
        if compact_numeric_projection and column == spec.time_column:
            projection.append(f"            CAST({identifier} AS BIGINT) AS {identifier}")
        elif compact_numeric_projection and column == spec.value_column:
            projection.append(f"            CAST({identifier} AS FLOAT) AS {identifier}")
        else:
            projection.append(f"            {identifier}")
    projection.extend(
        [
            "            CAST(NULL AS INTEGER) AS compression_importance",
            "            CAST(NULL AS FLOAT) AS compression_distance",
        ]
    )

    source = source_sql(
        table_name=table_name,
        schema_name=schema_name,
        input_query=input_query,
    )

    return "(\n        SELECT\n" + ",\n".join(projection) + f"\n        FROM {source}\n    )"


def compression_sql(
    *,
    table_name: str | None = None,
    schema_name: str | None = None,
    compressor_database: str | None = None,
    input_query: str | None = None,
    spec: CompressorSpec,
    parameters: CompressionParameters | None = None,
    columns: Sequence[str] | None = None,
) -> str:
    """Return a SELECT statement that invokes the compressor mapping."""

    params = parameters or CompressionParameters()
    selected_columns = spec.ordered_columns(columns)
    on_sql = input_projection_sql(
        table_name=table_name,
        schema_name=schema_name,
        input_query=input_query,
        spec=spec,
        columns=selected_columns,
    )
    partition_cols = ", ".join(quote_identifier(c) for c in spec.id_columns)
    using_lines = [
        _using_clause("id_columns", spec.id_column_csv),
        _using_clause("id_column_count", len(spec.id_columns)),
        _using_clause("time_column", spec.time_column),
        _using_clause("value_column", spec.value_column),
        _using_clause("time_column_index", selected_columns.index(spec.time_column)),
        _using_clause("value_column_index", selected_columns.index(spec.value_column)),
        _using_clause("time_unit", spec.time_unit),
        _using_clause("time_type", spec.time_type),
        *params.using_lines(),
    ]

    return f"""SELECT t.*
FROM {qualified_table_name(spec.mapping_name, compressor_database)}
(
    ON {on_sql} AS InputTable
    PARTITION BY {partition_cols}
    ORDER BY {quote_identifier(spec.time_column)}
    USING
{chr(10).join(using_lines)}
) AS t"""


def feature_sql(
    *,
    table_name: str | None = None,
    schema_name: str | None = None,
    input_query: str | None = None,
    compressor_database: str | None = None,
    spec: CompressorSpec,
    parameters: CompressionParameters | None = None,
    columns: Sequence[str] | None = None,
    top_k_distances: int = 0,
    label_column: str | None = None,
    label_value: object | None = None,
) -> str:
    """Build SQL feature engineering around compressed rows."""

    if (label_column is None) != (label_value is None):
        raise ValueError("label_column and label_value must be provided together")

    compressed = compression_sql(
        table_name=table_name,
        schema_name=schema_name,
        input_query=input_query,
        compressor_database=compressor_database,
        spec=spec,
        parameters=parameters,
        columns=columns,
    )
    ids = [quote_identifier(column) for column in spec.id_columns]
    select_lines = []
    if label_column is not None:
        select_lines.append(
            f"{quote_literal(label_value)} AS {quote_identifier(label_column)}"
        )
    select_lines.extend(f"c.{column}" for column in ids)
    id_select = ",\n    ".join(select_lines)
    original_select = ", ".join(ids)
    join_predicate = " AND\n  ".join(
        f"c.{column} = o.{column}" for column in ids
    )
    group_by_count = len(select_lines) + 1
    group_by = ", ".join(str(i) for i in range(1, group_by_count + 1))
    top_k = ""
    if top_k_distances < 0:
        raise ValueError("top_k_distances cannot be negative")
    if top_k_distances:
        top_k = ",\n" + ",\n".join(
            "    MAX(CASE WHEN c.compression_importance = "
            f"{i} THEN c.compression_distance END) AS distance_rank_{i}"
            for i in range(1, top_k_distances + 1)
        )

    source = source_sql(
        table_name=table_name,
        schema_name=schema_name,
        input_query=input_query,
    )

    return f"""SELECT
    {id_select},
    o.original_points,
    COUNT(*) AS remaining_points,
    COUNT(*) AS compressed_points,
    COUNT(*) / CAST(o.original_points AS FLOAT) AS retained_ratio,
    100.0 * COUNT(*) / CAST(o.original_points AS FLOAT) AS retained_pct,
    o.original_points / CAST(COUNT(*) AS FLOAT) AS compression_ratio,
    100.0 * (1.0 - COUNT(*) / CAST(o.original_points AS FLOAT)) AS reduction_pct,
    MAX(c.compression_distance) AS max_selected_distance,
    AVG(c.compression_distance) AS avg_selected_distance,
    STDDEV_SAMP(c.compression_distance) AS std_selected_distance{top_k}
FROM (
{compressed}
) AS c
JOIN (
    SELECT {original_select}, COUNT(*) AS original_points
    FROM {source}
    GROUP BY {original_select}
) AS o
  ON {join_predicate}
GROUP BY {group_by}"""


def _feature_output_columns(
    *,
    spec: CompressorSpec,
    top_k_distances: int = 0,
    label_column: str | None = None,
) -> list[str]:
    columns = []
    if label_column is not None:
        columns.append(label_column)
    columns.extend(spec.id_columns)
    columns.extend(
        [
            "original_points",
            "remaining_points",
            "compressed_points",
            "retained_ratio",
            "retained_pct",
            "compression_ratio",
            "reduction_pct",
            "max_selected_distance",
            "avg_selected_distance",
            "std_selected_distance",
        ]
    )
    columns.extend(f"distance_rank_{rank}" for rank in range(1, top_k_distances + 1))
    return columns


def _order_by_positions(
    order_by: Sequence[str | int],
    output_columns: Sequence[str],
) -> str:
    positions = []
    for item in order_by:
        if isinstance(item, int):
            positions.append(str(item))
            continue
        if item.isdigit():
            positions.append(item)
            continue
        try:
            positions.append(str(output_columns.index(item) + 1))
        except ValueError as exc:
            raise ValueError(
                f"order_by column {item!r} is not in the feature output columns"
            ) from exc
    return ", ".join(positions)


def features_by_mode_sql(
    *,
    modes: Mapping[str, CompressionParameters],
    table_name: str | None = None,
    schema_name: str | None = None,
    input_query: str | None = None,
    compressor_database: str | None = None,
    spec: CompressorSpec,
    columns: Sequence[str] | None = None,
    top_k_distances: int = 0,
    mode_column: str = "mode",
    order_by: str | Sequence[str | int] | None = None,
) -> str:
    """Build feature SQL for several parameter modes and combine the results."""

    if not modes:
        raise ValueError("modes must contain at least one entry")

    mode_queries = [
        feature_sql(
            table_name=table_name,
            schema_name=schema_name,
            input_query=input_query,
            compressor_database=compressor_database,
            spec=spec,
            parameters=parameters,
            columns=columns,
            top_k_distances=top_k_distances,
            label_column=mode_column,
            label_value=mode_name,
        )
        for mode_name, parameters in modes.items()
    ]
    sql = "\nUNION ALL\n".join(mode_queries)
    if order_by:
        if isinstance(order_by, str):
            order_by_sql = order_by
        else:
            output_columns = _feature_output_columns(
                spec=spec,
                top_k_distances=top_k_distances,
                label_column=mode_column,
            )
            order_by_sql = _order_by_positions(order_by, output_columns)
        sql += f"\nORDER BY {order_by_sql}"
    return sql


def register_sql(
    *,
    c_source_path: str | Path,
    target_database: str | None = None,
    spec: CompressorSpec | None = None,
) -> list[str]:
    """Return SQL statements that register the C function and mapping."""

    spec = spec or CompressorSpec(
        id_columns=["series_id"],
        time_column="seq_no",
        value_column="y",
    )
    source = Path(c_source_path).as_posix()
    external_name = f"CS!{spec.function_name}!{source}!F!ts_compress_to"
    function_name = qualified_table_name(spec.function_name, target_database)
    mapping_name = qualified_table_name(spec.mapping_name, target_database)
    function_sql = f"""REPLACE FUNCTION {function_name}()
RETURNS TABLE VARYING
USING FUNCTION ts_compress_to_contract
LANGUAGE C
NO SQL
NO EXTERNAL DATA
PARAMETER STYLE SQLTable
NOT DETERMINISTIC
CALLED ON NULL INPUT
EXTERNAL NAME {quote_literal(external_name)}"""
    mapping_sql = f"""REPLACE FUNCTION MAPPING {mapping_name}
FOR {function_name}
USING
    InputTable IN TABLE,
    id_columns,
    id_column_count,
    time_column,
    value_column,
    time_column_index,
    value_column_index,
    time_unit,
    time_type,
    distance_max,
    n_max,
    min_relative_gain,
    min_absolute_gain,
    auto_log_drop,
    tol_x,
    tol_y,
    plot_width_px,
    plot_height_px,
    plot_x_fraction"""
    return [function_sql, mapping_sql]


def td_plot_sql(
    *,
    table_name: str,
    schema_name: str | None = None,
    spec: CompressorSpec,
    title: str | None = None,
    width: int = 1024,
    height: int = 768,
    plot_type: str = "line",
) -> str:
    """Build a TD_PLOT invocation over a compressed table."""

    series_id = ", ".join(quote_identifier(column) for column in spec.id_columns)
    title = title or f"{spec.value_column} compressed"
    plot_table_name = qualified_table_name(table_name, schema_name)
    return f"""EXECUTE FUNCTION TD_PLOT(
    SERIES_SPEC(
        TABLE_NAME({plot_table_name}),
        ROW_AXIS(TIMECODE({quote_identifier(spec.time_column)})),
        SERIES_ID({series_id}),
        PAYLOAD(FIELDS({quote_identifier(spec.value_column)}), CONTENT(REAL))
    ),
    FUNC_PARAMS(
        TITLE({quote_literal(title)}),
        PLOTS[(TYPE({quote_literal(plot_type)}))],
        WIDTH({width}),
        HEIGHT({height})
    )
)"""


def create_table_as_sql(
    *,
    table_name: str,
    query: str,
    primary_index: Iterable[str],
    schema_name: str | None = None,
) -> str:
    """Materialize a query in Teradata with an explicit primary index."""

    pi = ", ".join(quote_identifier(column) for column in primary_index)
    return f"""CREATE MULTISET TABLE {qualified_table_name(table_name, schema_name)} AS
(
{query}
) WITH DATA
PRIMARY INDEX ({pi})"""
