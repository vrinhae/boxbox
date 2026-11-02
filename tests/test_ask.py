"""Tests for the tool-use loop with a scripted fake client: no network, no API key, no cost."""

import json
from types import SimpleNamespace as NS

from agents.ask import ask
from tests.fixtures.fake_snapshot import fake_snapshot
from tools.jsonl_log import read_events


def tool_call(name, args, id="call_1"):
    return NS(id=id, function=NS(name=name, arguments=json.dumps(args)))


def reply(content=None, calls=None):
    return NS(choices=[NS(message=NS(content=content, tool_calls=calls))],
              usage=NS(prompt_tokens=100, completion_tokens=10))


class FakeClient:
    """Returns the scripted replies in order and records every request."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs["messages"])))  # snapshot of messages at call time
        return self.replies.pop(0)


def test_answers_after_using_a_tool(tmp_path):
    client = FakeClient(
        reply(calls=[tool_call("query_laps", {"driver": "VER", "last_n": 1})]),
        reply(content="VER is on 18-lap-old softs."),
    )
    answer = ask("What tyres is VER on?", fake_snapshot(18), client=client, model="fake", run_id="t", log_dir=tmp_path)

    assert answer == "VER is on 18-lap-old softs."
    # Second request carries the tool result back to the LLM.
    tool_msg = client.requests[1][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "call_1"
    assert json.loads(tool_msg["content"])[0]["compound"] == "SOFT"

    events = read_events(tmp_path / "t.jsonl")
    assert [e["event"] for e in events] == ["agent_msg", "tool_call", "agent_msg"]
    assert events[0]["tool_calls"] == ["query_laps"] and events[0]["tokens_in"] == 100
    assert events[2]["content"] == "VER is on 18-lap-old softs."


def test_system_prompt_states_lap_and_driver(tmp_path):
    client = FakeClient(reply(content="ok"))
    ask("hi", fake_snapshot(7, ego_driver="HAM"), client=client, model="fake", log_dir=tmp_path)
    system = client.requests[0][0]["content"]
    assert "lap 7 of 57" in system and "HAM" in system


def test_tool_error_goes_back_to_llm(tmp_path):
    client = FakeClient(
        reply(calls=[tool_call("query_laps", {"driver": "NOR"})]),
        reply(calls=[tool_call("query_laps", {"driver": "LEC", "last_n": 1}, id="call_2")]),
        reply(content="LEC is on softs."),
    )
    assert ask("NOR tyres?", fake_snapshot(), client=client, model="fake", log_dir=tmp_path) == "LEC is on softs."
    assert "drivers in this race" in json.loads(client.requests[1][-1]["content"])["error"]


def test_bad_json_arguments_dont_crash(tmp_path):
    bad = NS(id="call_1", function=NS(name="query_laps", arguments="{driver: VER"))
    client = FakeClient(reply(calls=[bad]), reply(content="done"))
    assert ask("q", fake_snapshot(), client=client, model="fake", log_dir=tmp_path) == "done"
    assert "not valid JSON" in json.loads(client.requests[1][-1]["content"])["error"]


def test_stops_after_max_rounds(tmp_path):
    client = FakeClient(*[reply(calls=[tool_call("get_race_control", {}, id=f"c{i}")]) for i in range(3)])
    answer = ask("loop forever", fake_snapshot(), client=client, model="fake", log_dir=tmp_path, max_rounds=3)
    assert "no answer after 3 rounds" in answer
    assert len(client.requests) == 3
