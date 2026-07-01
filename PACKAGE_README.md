# td-ts-compressor

Python helpers for the `ts_compress_to` Teradata Vantage table operator.

This package is intentionally small: it bundles the `ts_compress_to` C table
operator source and builds Teradata SQL for compression, feature engineering,
installation, and `TD_PLOT` workflows. It does not include repository
notebooks, generated images, local datasets, or project-level documentation.

## Install

```powershell
uv pip install td-ts-compressor
```

For local development from this repository:

```powershell
uv pip install -e ".[dev]"
```

Install the optional Teradata interface when you want methods to return
`teradataml.DataFrame` objects or execute SQL directly:

```powershell
uv pip install -e ".[teradataml,dev]"
```

## Compress A Series Table

```python
from td_ts_compressor import (
    CompressorSpec,
    TeradataTimeSeriesCompressor,
    visual_fidelity,
)

compressor = TeradataTimeSeriesCompressor(
    CompressorSpec(
        id_columns=["mac_code"],
        time_column="seq_no",
        value_column="generator_speed",
        time_type="numeric",
    ),
    operator_database="utility_db",
)

compressed = compressor.compress(
    data_database="analytics",
    table_name="input_wind_plateau_full_csv",
    parameters=visual_fidelity(width_px=1024, height_px=768),
)
```

Pass `as_dataframe=False` to receive SQL instead of a `teradataml.DataFrame`.
`operator_database` is where the table operator function mapping is installed.
Source tables or views can live elsewhere and are addressed with
`data_database` plus `table_name`. You can also pass `input_query=...` or
`dataframe=...` for a SQL query or `teradataml.DataFrame` source.

## Install The Table Operator

Generate installation SQL for a target database:

```python
install_sql = compressor.install_table_operator_sql(
    target_database="utility_db",
)
```

Or execute the installation through `teradataml.execute_sql`:

```python
compressor.install_table_operator(
    target_database="utility_db",
)
```

Pass `c_source_path=...` only when you want to install a modified local C
source file instead of the C source bundled with the package.

## Build Features

```python
from td_ts_compressor import analytical_points

features = compressor.features(
    data_database="analytics",
    table_name="input_wind_plateau_full_csv",
    parameters=analytical_points(auto_log_drop=1.5),
    top_k_distances=3,
)
```

Generated feature SQL includes point counts, compression ratio, reduction
percentage, selected-distance aggregates, and optional distance ranks.

## Enable TD_PLOT On Large Tables

Materialize a compressed plotting table first, then call `TD_PLOT` on that
smaller table.

```python
create_plot_table_sql = compressor.materialize_for_td_plot_sql(
    data_database="analytics",
    table_name="input_wind_plateau_full_csv",
    output_schema_name="analytics",
    output_table="plot_generator_speed_compressed",
)

plot_sql = compressor.td_plot_sql(
    schema_name="analytics",
    table_name="plot_generator_speed_compressed",
    title="Generator speed compressed",
)
```

## Package Contents

Distributed artifacts include only:

- `td_ts_compressor` Python modules
- bundled `ts_compress_to.c` operator source
- package-specific documentation
- package tests in the source distribution
- package metadata

They exclude notebooks, generated plots, local data, SQL scripts, and the
broader repository documentation.

## Publishing

Publishing is configured through GitHub Actions and PyPI Trusted Publishing.
See `package_docs/publishing.md` in the source distribution for the release
process.
