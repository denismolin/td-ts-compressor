# Package Usage

`td-ts-compressor` is a Python interface for users who already have the
`ts_compress_to` function mapping available in Teradata Vantage, or who want to
install it in a target database from Python.

## Core Objects

`CompressorSpec` describes the table shape and Teradata function mapping:

```python
from td_ts_compressor import CompressorSpec

spec = CompressorSpec(
    id_columns=["mac_code"],
    time_column="seq_no",
    value_column="generator_speed",
    time_type="numeric",
)
```

`TeradataTimeSeriesCompressor` uses the spec to build SQL:

```python
from td_ts_compressor import TeradataTimeSeriesCompressor

compressor = TeradataTimeSeriesCompressor(
    spec,
    operator_database="utility_db",
)
```

`operator_database` is the database where the table operator function mapping
is installed. Source tables and views can live elsewhere and are addressed with
`data_database` plus `table_name`. For derived sources, pass `input_query=...`
or `dataframe=...` instead.

## Recipes

Use `visual_fidelity` before plotting or dashboarding:

```python
from td_ts_compressor import visual_fidelity

sql = compressor.compress(
    data_database="analytics",
    table_name="signal_series",
    parameters=visual_fidelity(width_px=1024, height_px=768),
    as_dataframe=False,
)
```

Use `analytical_points` when the selected rows are analytical results:

```python
from td_ts_compressor import analytical_points

sql = compressor.compress(
    data_database="analytics",
    table_name="signal_series",
    parameters=analytical_points(auto_log_drop=1.5),
    as_dataframe=False,
)
```

Use `fixed_budget` when each series needs a predictable maximum count:

```python
from td_ts_compressor import fixed_budget

sql = compressor.compress(
    data_database="analytics",
    table_name="signal_series",
    parameters=fixed_budget(n_max=80),
    as_dataframe=False,
)
```

## Teradataml Behavior

Methods return `teradataml.DataFrame` objects by default. If `teradataml` is
not installed, pass `as_dataframe=False` and execute the SQL with your own
connection layer.

```python
query = compressor.features(
    data_database="analytics",
    table_name="signal_series",
    top_k_distances=5,
    as_dataframe=False,
)
```

## Install The Table Operator

```python
statements = compressor.install_table_operator_sql(
    target_database="utility_db",
)
```

`install_table_operator()` executes those statements through
`teradataml.execute_sql`.

The package bundles the `ts_compress_to.c` source file used for installation.
Pass `c_source_path=...` only when you want to install a modified local source
file.
