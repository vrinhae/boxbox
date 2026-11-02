from tests.fixtures.fake_snapshot import fake_snapshot
from tools.jsonl_log import read_events
from tools.registry import TOOL_SPECS, _TOOLS, run_tool


def test_every_spec_has_a_function():
    assert {s["function"]["name"] for s in TOOL_SPECS} == set(_TOOLS)


def test_runs_tool_and_logs_it(tmp_path):
    snap = fake_snapshot(18)
    result = run_tool("query_laps", {"driver": "VER", "last_n": 1}, snap, agent="Test", log_dir=tmp_path)

    assert result[0]["compound"] == "SOFT"
    (event,) = read_events(tmp_path / f"{snap.race_id}.jsonl")
    assert event["event"] == "tool_call"
    assert event["tool"] == "query_laps" and event["agent"] == "Test"
    assert event["args"] == {"driver": "VER", "last_n": 1}
    assert event["lap"] == 18


def test_bad_arguments_come_back_as_error(tmp_path):
    snap = fake_snapshot()
    assert "drivers in this race" in run_tool("query_laps", {"driver": "NOR"}, snap, agent="T", log_dir=tmp_path)["error"]
    assert "error" in run_tool("query_laps", {"lap": 30}, snap, agent="T", log_dir=tmp_path)  # LLM can't pick the lap
    assert "unknown tool" in run_tool("get_state", {}, snap, agent="T", log_dir=tmp_path)["error"]
    assert len(read_events(tmp_path / f"{snap.race_id}.jsonl")) == 3  # errors are logged too
