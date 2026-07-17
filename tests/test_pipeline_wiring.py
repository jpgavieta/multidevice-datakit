"""
tests/test_pipeline_wiring.py

Verifies the {"payload": ..., "ingest_method": ...} shape flows correctly
through extract.py -> transform.py -> load.py, WITHOUT hitting a real
database, API, or devices.yml. Mocks every external boundary.

USAGE:
pytest tests/test_pipeline_wiring.py -v
"""
from unittest.mock import patch, MagicMock
import json

import extract.extract as extract
import transform.transform as transform
import load.load as load


FAKE_DEVICES = [
    {"id": "fitbit_kol_01", "type": "fitbit", "start_date": None},
    {"id": "atmotube_kol_01", "type": "atmotube", "start_date": None},
]


def fake_fitbit_extract(device, start_date, end_date):
    return {"dailySteps": {"dataPoints": [{"dailySteps": {"value": 1234}}]}}


def fake_atmotube_extract(device, start_date, end_date):
    return {"pm": [{"value": 5}]}


# ---------------------------------------------------------------------------
# 1. extract.py: does the returned shape include payload + ingest_method?

@patch.object(extract, "load_devices", return_value=FAKE_DEVICES)
@patch.dict(extract.CLIENT_REGISTRY, {
    "fitbit": fake_fitbit_extract,
    "atmotube": fake_atmotube_extract,
})
def test_extract_embeds_ingest_method(mock_load_devices):
    result = extract.extract_all_devices(ingest_method="api_manual")

    assert "fitbit" in result and "atmotube" in result
    entry = result["fitbit"]["fitbit_kol_01"]
    assert set(entry.keys()) == {"payload", "ingest_method"}
    assert entry["ingest_method"] == "api_manual"
    assert entry["payload"] == fake_fitbit_extract(None, None, None)


def test_extract_rejects_invalid_ingest_method():
    try:
        extract.extract_all_devices(ingest_method="not_a_real_method")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "not_a_real_method" in str(e)


# ---------------------------------------------------------------------------
# 2. transform.py: does it unwrap ["payload"] before calling the parser,
#    and ignore ingest_method?


def test_transform_unwraps_payload_only():
    seen_payloads = []

    fake_parser = MagicMock()
    fake_parser.parse.side_effect = lambda payload: seen_payloads.append(payload) or {"pm": "FAKE_DF"}

    raw_data = {
        "atmotube": {
            "atmotube_kol_01": {
                "payload": {"pm": [{"value": 5}]},
                "ingest_method": "api_auto",
            }
        }
    }

    with patch.dict(transform.DEVICE_REGISTRY, {"atmotube": fake_parser}):
        result = transform.transform_device_data(raw_data)

    # parser only ever saw the payload, never the wrapper dict
    assert seen_payloads == [{"pm": [{"value": 5}]}]
    assert result["atmotube"]["atmotube_kol_01"]["data"]["pm"]["df"] == "FAKE_DF"


# ---------------------------------------------------------------------------
# 3. load.py: does it build the right SQL params for raw.ingests, per method?

@patch("load.load.execute_values")
@patch("load.load._get_connection")
def test_load_builds_correct_rows(mock_get_conn, mock_execute_values):
    mock_conn = MagicMock()
    mock_get_conn.return_value = mock_conn

    all_data = {
        "fitbit": {
            "fitbit_kol_01": {"payload": {"a": 1}, "ingest_method": "api_auto"},
        },
        "atmotube": {
            "atmotube_kol_01": {"payload": {"b": 2}, "ingest_method": "csv_manual"},
        },
    }

    load.load_raw_data(all_data)

    assert mock_execute_values.called
    _, args, kwargs = mock_execute_values.mock_calls[0]
    sql, rows = args[1], args[2]
    assert "raw.ingests" in sql
    assert ("fitbit", "fitbit_kol_01", "api_auto") == rows[0][:3]
    assert json.loads(rows[0][4]) == {"a": 1}
    assert ("atmotube", "atmotube_kol_01", "csv_manual") == rows[1][:3]
    mock_conn.commit.assert_called_once()


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))