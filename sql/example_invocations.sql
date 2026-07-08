-- BIGINT sequence-number version.
SELECT *
FROM ts_identity_to_map
(
    ON mydb.input_timeseries
    PARTITION BY series_id_1, series_id_2
    ORDER BY seq_no
) AS t;

-- TIMESTAMP(6) ordering-column version.
SELECT *
FROM ts_identity_to_map
(
    ON mydb.input_timeseries
    PARTITION BY series_id_1, series_id_2
    ORDER BY ts
) AS t;

-- Parameterized mapping variant.
SELECT *
FROM ts_identity_to_map
(
    ON mydb.input_timeseries
    PARTITION BY series_id_1, series_id_2
    ORDER BY seq_no
    USING
    window_size(10)
    lag(1)
    method('identity')
) AS t;
