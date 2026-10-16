import pytest

from data.schema import Compound, TrackStatus
from tests.test_schema import make_snapshot
from tools.jsonl_log import log_event, read_events


def test_appends_one_line_per_event(tmp_path):
    log_event("2023_bahrain", 1, "route", log_dir=tmp_path, trigger="Race start", agents=["Telemetry"])
    log_event("2023_bahrain", 1, "decision", log_dir=tmp_path, action="stay")

    events = read_events(tmp_path / "2023_bahrain.jsonl")
    assert [e["event"] for e in events] == ["route", "decision"]
    assert events[0]["agents"] == ["Telemetry"]
    assert events[1]["action"] == "stay"
    assert all(e["race_id"] == "2023_bahrain" and e["lap"] == 1 and e["timestamp"] for e in events)


def test_run_id_names_the_file(tmp_path):
    log_event("2023_bahrain", 3, "decision", run_id="2023_bahrain_LEC_multi", log_dir=tmp_path, action="box")

    assert (tmp_path / "2023_bahrain_LEC_multi.jsonl").exists()
    assert not (tmp_path / "2023_bahrain.jsonl").exists()


def test_rejects_unknown_event_type(tmp_path):
    with pytest.raises(ValueError, match="unknown event type"):
        log_event("2023_bahrain", 1, "tool_cal", log_dir=tmp_path)
    assert not any(tmp_path.iterdir())


def test_rejects_reserved_field(tmp_path):
    with pytest.raises(ValueError, match="timestamp"):
        log_event("2023_bahrain", 1, "decision", log_dir=tmp_path, timestamp="yesterday")


def test_serializes_schema_objects(tmp_path):
    snap = make_snapshot(5, [1, 2, 3, 4, 5])
    log_event("2023_bahrain", 5, "tool_call", log_dir=tmp_path,
              tool="get_state", args={"lap": 5}, result=snap.ego, compound=Compound.SOFT, status=TrackStatus.SC)

    (event,) = read_events(tmp_path / "2023_bahrain.jsonl")
    assert event["result"]["driver"] == "VER"
    assert event["result"]["compound"] == "SOFT"
    assert event["compound"] == "SOFT"
    assert event["status"] == "SC"
