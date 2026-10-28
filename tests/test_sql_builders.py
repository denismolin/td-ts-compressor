from td_ts_compressor import (
    CompressorSpec,
    TeradataTimeSeriesCompressor,
    __version__,
    analytical_points,
    fixed_budget,
    install_table_operator_sql,
    visual_fidelity,
)
from td_ts_compressor.core import bundled_c_source_path
from td_ts_compressor.sql import quote_identifier, quote_literal, register_sql


def test_package_version_is_exported():
    assert __version__ == "0.1.11"


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


def test_operator_database_and_data_database_are_independent():
    compressor = TeradataTimeSeriesCompressor(
        CompressorSpec(
            id_columns=["mac_code"],
            time_column="seq_no",
            value_column="generator_speed",
            time_type="numeric",
        ),
        operator_database="operator_db",
    )

    sql = compressor.compress(
        data_database="data_db",
        table_name="wind_series_view",
        as_dataframe=False,
    )

    assert "FROM operator_db.ts_compress_seq_to_map" in sql
    assert "FROM data_db.wind_series_view" in sql


def test_schema_name_and_data_database_conflict_is_rejected():
    compressor = TeradataTimeSeriesCompressor(
        CompressorSpec(
            id_columns=["series_id"],
            time_column="seq_no",
            value_column="y",
        )
    )

    try:
        compressor.compress(
            schema_name="old_name",
            data_database="new_name",
            table_name="series_table",
            as_dataframe=False,
        )
    except ValueError as exc:
        assert "schema_name and data_database" in str(exc)
    else:
        raise AssertionError("conflicting source database names should fail")


def test_input_query_source_is_supported_for_compression_and_features():
    compressor = TeradataTimeSeriesCompressor(
        CompressorSpec(
            id_columns=["series_id"],
            time_column="seq_no",
            value_column="y",
            time_type="numeric",
        ),
        operator_database="operator_db",
    )
    input_query = "SELECT series_id, seq_no, y FROM analytics.source_view WHERE y IS NOT NULL"

    compress_sql = compressor.compress(
        input_query=input_query,
        as_dataframe=False,
    )
    features_sql = compressor.features(
        input_query=input_query,
        as_dataframe=False,
    )

    assert "FROM operator_db.ts_compress_seq_to_map" in compress_sql
    assert input_query in compress_sql
    assert "COUNT(*) AS original_points" in features_sql
    assert input_query in features_sql


def test_compact_numeric_projection_supports_multiple_id_columns():
    compressor = TeradataTimeSeriesCompressor(
        CompressorSpec(
            id_columns=["plant_id", "sensor_id"],
            time_column="seq_no",
            value_column="y",
            time_type="numeric",
        ),
        operator_database="operator_db",
    )

    sql = compressor.compress(
        input_query="SELECT plant_id, sensor_id, seq_no, y FROM analytics.source_view",
        columns=["plant_id", "sensor_id", "seq_no", "y"],
        parameters=fixed_budget(n_max=50),
        as_dataframe=False,
    )

    assert "PARTITION BY plant_id, sensor_id" in sql
    assert "id_column_count('2')" in sql
    assert "time_column_index('2')" in sql
    assert "value_column_index('3')" in sql
    assert "CAST(seq_no AS BIGINT) AS seq_no" in sql
    assert "CAST(y AS FLOAT) AS y" in sql


def test_dataframe_like_source_uses_backing_query():
    class FakeDataFrame:
        def show_query(self):
            return "SELECT series_id, seq_no, y FROM volatile_input;"

    compressor = TeradataTimeSeriesCompressor(
        CompressorSpec(
            id_columns=["series_id"],
            time_column="seq_no",
            value_column="y",
        ),
        operator_database="operator_db",
    )

    sql = compressor.compress(dataframe=FakeDataFrame(), as_dataframe=False)

    assert "FROM operator_db.ts_compress_seq_to_map" in sql
    assert "SELECT series_id, seq_no, y FROM volatile_input" in sql
    assert "volatile_input;" not in sql


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

    assert "FROM (\nSELECT t.*" in sql
    assert "COUNT(*) AS remaining_points" in sql
    assert "COUNT(*) AS compressed_points" in sql
    assert "retained_ratio" in sql
    assert "retained_pct" in sql
    assert "compression_ratio" in sql
    assert "distance_rank_1" in sql
    assert "distance_rank_2" in sql
    assert "auto_log_drop('1.0')" in sql
    assert "FROM analytics.input_timeseries_compress" in sql
    assert "FROM utility_db.ts_compress_seq_to_map" in sql


def test_feature_sql_can_add_label_column():
    compressor = TeradataTimeSeriesCompressor(
        CompressorSpec(
            id_columns=["series_id"],
            time_column="seq_no",
            value_column="y",
            time_type="numeric",
        ),
        operator_database="operator_db",
    )

    sql = compressor.features(
        table_name="input_timeseries",
        parameters=analytical_points(),
        label_column="mode_raw",
        label_value="analytical_points",
        as_dataframe=False,
    )

    assert "'analytical_points' AS mode_raw" in sql
    assert "GROUP BY 1, 2, 3" in sql


def test_features_by_mode_sql_unions_parameter_modes():
    compressor = TeradataTimeSeriesCompressor(
        CompressorSpec(
            id_columns=["series_id_1", "series_id_2"],
            time_column="seq_no",
            value_column="y",
            time_type="numeric",
        ),
        operator_database="operator_db",
    )

    sql = compressor.features_by_mode_sql(
        table_name="input_timeseries",
        modes={
            "visual_fidelity": visual_fidelity(width_px=320, height_px=200),
            "analytical_points": analytical_points(auto_log_drop=1.0),
        },
        top_k_distances=1,
        mode_column="mode_raw",
        order_by=["series_id_2", "mode_raw"],
    )

    assert "'visual_fidelity' AS mode_raw" in sql
    assert "'analytical_points' AS mode_raw" in sql
    assert "\nUNION ALL\n" in sql
    assert "plot_width_px('320')" in sql
    assert "auto_log_drop('1.0')" in sql
    assert "distance_rank_1" in sql
    assert "ORDER BY 3, 1" in sql


def test_features_by_mode_order_by_is_independent_of_source_column_order():
    compressor = TeradataTimeSeriesCompressor(
        CompressorSpec(
            id_columns=["series_id_1", "series_id_2"],
            time_column="seq_no",
            value_column="y",
            time_type="numeric",
        ),
        operator_database="operator_db",
    )
    input_query = (
        "SELECT y, extra_payload, series_id_2, seq_no, series_id_1 "
        "FROM analytics.reordered_source"
    )

    sql = compressor.features_by_mode_sql(
        input_query=input_query,
        columns=["series_id_1", "series_id_2", "seq_no", "y", "extra_payload"],
        modes={
            "visual_fidelity": visual_fidelity(width_px=320, height_px=200),
            "analytical_points": analytical_points(auto_log_drop=1.0),
        },
        top_k_distances=1,
        mode_column="mode_raw",
        order_by=["series_id_2", "mode_raw"],
    )

    assert input_query in sql
    assert "series_id_1,\n            series_id_2,\n            seq_no,\n            y" in sql
    assert "time_column_index('2')" in sql
    assert "value_column_index('3')" in sql
    assert "ORDER BY 3, 1" in sql


def test_features_by_mode_sql_rejects_unknown_order_column():
    compressor = TeradataTimeSeriesCompressor(
        CompressorSpec(
            id_columns=["series_id"],
            time_column="seq_no",
            value_column="y",
        )
    )

    try:
        compressor.features_by_mode_sql(
            table_name="input_timeseries",
            modes={"visual_fidelity": visual_fidelity()},
            order_by=["missing_column"],
        )
    except ValueError as exc:
        assert "order_by column" in str(exc)
    else:
        raise AssertionError("features_by_mode_sql should reject unknown order columns")


def test_features_by_mode_sql_rejects_empty_modes():
    compressor = TeradataTimeSeriesCompressor(
        CompressorSpec(
            id_columns=["series_id"],
            time_column="seq_no",
            value_column="y",
        )
    )

    try:
        compressor.features_by_mode_sql(table_name="input_timeseries", modes={})
    except ValueError as exc:
        assert "modes" in str(exc)
    else:
        raise AssertionError("features_by_mode_sql should reject empty modes")


def test_process_feature_engineering_builds_process_view_and_docs():
    compressor = TeradataTimeSeriesCompressor(
        CompressorSpec(
            id_columns=["mac_code"],
            time_column="seq_no",
            value_column="generator_speed",
            time_type="numeric",
        ),
        operator_database="operator_db",
    )

    artifact = compressor.process_feature_engineering(
        process_database="analytics",
        process_name="vw_feat_generator_speed_compression",
        source_database="raw",
        source_object="input_wind_plateau_full_csv",
        parameters=analytical_points(),
        top_k_distances=2,
        mode_name="analytical_points",
        feature_prefix="ts_",
        source_object_description="Raw turbine sensor readings.",
        source_column_descriptions={
            "mac_code": "Machine identifier for a wind turbine.",
            "seq_no": "Sequential sample number within each turbine signal.",
            "generator_speed": "Generator rotation speed measured by the turbine sensor.",
        },
        use_tdfs4ds_dictionary=False,
    )

    assert artifact.qualified_process_name == "analytics.vw_feat_generator_speed_compression"
    assert artifact.process_sql.startswith(
        "REPLACE VIEW analytics.vw_feat_generator_speed_compression AS\n"
        "LOCKING ROW FOR ACCESS"
    )
    assert "FROM raw.input_wind_plateau_full_csv" in artifact.process_sql
    assert "mac_code,\n    original_points AS ts_original_points" in artifact.process_sql
    assert "distance_rank_2 AS ts_distance_rank_2" in artifact.process_sql
    assert artifact.feature_names == [
        "ts_original_points",
        "ts_remaining_points",
        "ts_compressed_points",
        "ts_retained_ratio",
        "ts_retained_pct",
        "ts_compression_ratio",
        "ts_reduction_pct",
        "ts_max_selected_distance",
        "ts_avg_selected_distance",
        "ts_std_selected_distance",
        "ts_distance_rank_1",
        "ts_distance_rank_2",
    ]
    assert artifact.metadata["mode"] == "analytical_points"

    object_row = artifact.object_df.iloc[0].to_dict()
    assert object_row["DATABASE_NAME"] == "analytics"
    assert object_row["OBJECT_NAME"] == "vw_feat_generator_speed_compression"
    assert object_row["OBJECT_TYPE"] == "V"
    assert "Raw turbine sensor readings" in object_row["BUSINESS_DESCRIPTION"]
    assert "Generator rotation speed" in object_row["BUSINESS_DESCRIPTION"]

    columns = artifact.columns_df.set_index("COLUMN_NAME")
    assert columns.loc["mac_code", "BUSINESS_DESCRIPTION"] == (
        "Machine identifier for a wind turbine."
    )
    assert "Generator rotation speed" in columns.loc[
        "ts_original_points", "BUSINESS_DESCRIPTION"
    ]
    assert "compression importance rank 2" in columns.loc[
        "ts_distance_rank_2", "BUSINESS_DESCRIPTION"
    ]


def test_process_feature_engineering_can_override_series_description():
    compressor = TeradataTimeSeriesCompressor(
        CompressorSpec(
            id_columns=["asset_id"],
            time_column="event_ts",
            value_column="temperature",
        )
    )

    artifact = compressor.process_feature_engineering(
        process_database="analytics",
        process_name="vw_feat_temperature_compression",
        source_object="asset_temperature",
        parameters=fixed_budget(n_max=12),
        series_description="asset temperature profile",
        feature_suffix="_cmp",
        use_tdfs4ds_dictionary=False,
    )

    assert "original_points AS original_points_cmp" in artifact.process_sql
    assert "asset temperature profile" in artifact.object_df.iloc[0][
        "BUSINESS_DESCRIPTION"
    ]
    assert "asset temperature profile" in artifact.columns_df.set_index("COLUMN_NAME").loc[
        "compression_ratio_cmp", "BUSINESS_DESCRIPTION"
    ]


def test_process_feature_engineering_rejects_missing_process_database():
    compressor = TeradataTimeSeriesCompressor(
        CompressorSpec(
            id_columns=["series_id"],
            time_column="seq_no",
            value_column="y",
        )
    )

    try:
        compressor.process_feature_engineering(
            process_database=None,
            process_name="vw_feat_missing_db",
            source_object="input_timeseries",
            use_tdfs4ds_dictionary=False,
        )
    except ValueError as exc:
        assert "process_database" in str(exc)
    else:
        raise AssertionError("missing process_database should fail")


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
    assert "TABLE_NAME(analytics.plot_generator_speed_compressed)" in plot_sql
    assert "ROW_AXIS(TIMECODE(date_time))" in plot_sql


def test_td_plot_table_name_is_identifier_quoted():
    compressor = TeradataTimeSeriesCompressor(
        CompressorSpec(
            id_columns=["series id"],
            time_column="sample ts",
            value_column="y value",
        )
    )

    plot_sql = compressor.td_plot_sql(
        schema_name="odd db",
        table_name="plot table",
    )

    assert 'TABLE_NAME("odd db"."plot table")' in plot_sql
    assert 'ROW_AXIS(TIMECODE("sample ts"))' in plot_sql
    assert 'SERIES_ID("series id")' in plot_sql


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
    )

    assert len(statements) == 2
    assert statements[0].startswith("REPLACE FUNCTION utility_db.ts_compress_seq_to()")
    assert "td_ts_compressor/resources/ts_compress_to.c" in statements[0].replace("\\", "/")
    assert statements[1].startswith(
        "REPLACE FUNCTION MAPPING utility_db.ts_compress_seq_to_map"
    )


def test_module_install_table_operator_sql_does_not_need_compressor_instance():
    statements = install_table_operator_sql(target_database="utility_db")

    assert len(statements) == 2
    assert statements[0].startswith("REPLACE FUNCTION utility_db.ts_compress_seq_to()")
    assert "td_ts_compressor/resources/ts_compress_to.c" in statements[0].replace("\\", "/")
    assert statements[1].startswith(
        "REPLACE FUNCTION MAPPING utility_db.ts_compress_seq_to_map"
    )


def test_module_install_table_operator_sql_supports_custom_names():
    statements = install_table_operator_sql(
        target_database="utility_db",
        function_name="my_compress_to",
        mapping_name="my_compress_to_map",
    )

    assert statements[0].startswith("REPLACE FUNCTION utility_db.my_compress_to()")
    assert statements[1].startswith(
        "REPLACE FUNCTION MAPPING utility_db.my_compress_to_map"
    )
    assert "FOR utility_db.my_compress_to" in statements[1]


def test_bundled_c_source_path_exists():
    source_path = bundled_c_source_path()

    assert source_path.name == "ts_compress_to.c"
    assert source_path.exists()
