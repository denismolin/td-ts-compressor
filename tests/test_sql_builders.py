from td_ts_compressor import (
    CompressorSpec,
    TeradataTimeSeriesCompressor,
    analytical_points,
    fixed_budget,
    visual_fidelity,
)
from td_ts_compressor.sql import quote_identifier, quote_literal, register_sql


def test_compression_sql_contains_operator_contract_columns():
    compressor = TeradataTimeSeriesCompressor(
        CompressorSpec(
            id_columns=["mac_code"],
            time_column="seq_no",
            value_column="generator_speed",
            time_type="numeric",
        ),
        compressor_database="utility_db",
    )

    sql = compressor.compress(
        schema_name="analytics",
        table_name="input_wind_plateau_full_csv",
        parameters=visual_fidelity(width_px=100, height_px=100),
        as_dataframe=False,
    )

    assert "FROM utility_db.ts_compress_seq_to_map" in sql
    assert "PARTITION BY mac_code" in sql
    assert "ORDER BY seq_no" in sql
    assert "FROM analytics.input_wind_plateau_full_csv" in sql
    assert "compression_importance" in sql
    assert "compression_distance" in sql
    assert "id_columns('mac_code')" in sql
    assert "time_type('numeric')" in sql
    assert "plot_width_px('100')" in sql


def test_feature_sql_adds_pythonic_aggregates_and_top_k_distances():
    compressor = TeradataTimeSeriesCompressor(
        CompressorSpec(
            id_columns=["series_id_1", "series_id_2"],
            time_column="seq_no",
            value_column="y",
            time_type="numeric",
        ),
        compressor_database="utility_db",
    )

    sql = compressor.features(
        schema_name="analytics",
        table_name="input_timeseries_compress",
        parameters=analytical_points(auto_log_drop=1.0),
        top_k_distances=2,
        as_dataframe=False,
    )

    assert "WITH compressed AS" in sql
    assert "COUNT(*) AS remaining_points" in sql
    assert "compression_ratio" in sql
    assert "distance_rank_1" in sql
    assert "distance_rank_2" in sql
    assert "auto_log_drop('1.0')" in sql
    assert "FROM analytics.input_timeseries_compress" in sql
    assert "FROM utility_db.ts_compress_seq_to_map" in sql


def test_td_plot_workflow_sql_materializes_before_plotting():
    compressor = TeradataTimeSeriesCompressor(
        CompressorSpec(
            id_columns=["mac_code"],
            time_column="date_time",
            value_column="generator_speed",
            time_type="timestamp",
        )
    )

    create_sql = compressor.materialize_for_td_plot_sql(
        schema_name="raw",
        table_name="wind_full",
        output_schema_name="analytics",
        output_table="plot_generator_speed_compressed",
    )
    plot_sql = compressor.td_plot_sql(
        schema_name="analytics",
        table_name="plot_generator_speed_compressed",
    )

    assert "CREATE MULTISET TABLE analytics.plot_generator_speed_compressed AS" in create_sql
    assert "FROM raw.wind_full" in create_sql
    assert "PRIMARY INDEX (mac_code)" in create_sql
    assert "EXECUTE FUNCTION TD_PLOT" in plot_sql
    assert "TABLE_NAME('analytics.plot_generator_speed_compressed')" in plot_sql
    assert "ROW_AXIS(TIMECODE(date_time))" in plot_sql


def test_fixed_budget_validates_endpoint_budget():
    try:
        fixed_budget(n_max=1)
    except ValueError as exc:
        assert "at least 2" in str(exc)
    else:
        raise AssertionError("fixed_budget should reject n_max below 2")


def test_literal_and_identifier_quoting():
    assert quote_literal("a'b") == "'a''b'"
    assert quote_identifier("db.table") == "db.table"
    assert quote_identifier("odd name") == '"odd name"'


def test_register_sql_uses_custom_function_and_mapping_names():
    spec = CompressorSpec(
        id_columns=["mac_code"],
        time_column="seq_no",
        value_column="speed",
        function_name="my_compress_to",
        mapping_name="my_compress_to_map",
    )

    statements = register_sql(
        c_source_path="./src/ts_compress_to.c",
        target_database="utility_db",
        spec=spec,
    )

    assert "REPLACE FUNCTION utility_db.my_compress_to()" in statements[0]
    assert "REPLACE FUNCTION MAPPING utility_db.my_compress_to_map" in statements[1]
    assert "FOR utility_db.my_compress_to" in statements[1]


def test_install_table_operator_sql_targets_database():
    compressor = TeradataTimeSeriesCompressor(
        CompressorSpec(
            id_columns=["mac_code"],
            time_column="seq_no",
            value_column="speed",
        ),
        compressor_database="utility_db",
    )

    statements = compressor.install_table_operator_sql(
        target_database="utility_db",
        c_source_path="./src/ts_compress_to.c",
    )

    assert len(statements) == 2
    assert statements[0].startswith("REPLACE FUNCTION utility_db.ts_compress_seq_to()")
    assert statements[1].startswith(
        "REPLACE FUNCTION MAPPING utility_db.ts_compress_seq_to_map"
    )
