from unittest.mock import Mock

import pytest

from td_ts_compressor import CompressorSpec, TeradataTimeSeriesCompressor, check_config
from td_ts_compressor import core


def test_check_config_executes_and_fetches_probe(monkeypatch):
    cursor = Mock()
    cursor.fetchall.return_value = [(1,), (2,), (3,)]
    execute = Mock(return_value=cursor)
    monkeypatch.setattr(core, "_teradataml_execute_sql", lambda: execute)

    assert check_config(operator_database="utility_db", mapping_name="custom_map") is True
    query = execute.call_args.args[0]
    assert "FROM utility_db.custom_map" in query
    assert "SYS_CALENDAR.CALENDAR" in query
    assert "time_type('numeric')" in query
    assert "n_max('3')" in query
    cursor.fetchall.assert_called_once()
    cursor.close.assert_called_once()


@pytest.mark.parametrize("during_fetch", [False, True])
def test_check_config_preserves_database_errors(monkeypatch, during_fetch):
    error = RuntimeError("EXECUTE FUNCTION permission denied")
    cursor = Mock()
    execute = Mock(return_value=cursor)
    if during_fetch:
        cursor.fetchall.side_effect = error
    else:
        execute.side_effect = error
    monkeypatch.setattr(core, "_teradataml_execute_sql", lambda: execute)

    with pytest.raises(RuntimeError) as caught:
        check_config()
    assert caught.value is error
    if during_fetch:
        cursor.close.assert_called_once()


def test_check_config_rejects_empty_result(monkeypatch):
    cursor = Mock()
    cursor.fetchall.return_value = []
    monkeypatch.setattr(core, "_teradataml_execute_sql", lambda: Mock(return_value=cursor))
    with pytest.raises(RuntimeError, match="expected 3 rows"):
        check_config()
    cursor.close.assert_called_once()


def test_instance_check_config_uses_configured_mapping(monkeypatch):
    probe = Mock(return_value=True)
    monkeypatch.setattr(core, "check_config", probe)
    compressor = TeradataTimeSeriesCompressor(
        CompressorSpec(id_columns=["id"], time_column="t", value_column="v", mapping_name="custom_map"),
        operator_database="utility_db",
    )
    assert compressor.check_config() is True
    probe.assert_called_once_with(operator_database="utility_db", mapping_name="custom_map")
