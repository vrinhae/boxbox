"""Ask an LLM a question about the race and let it use the query tools.

This is the basic tool-use loop every agent will build on:
  1. send the question plus the tool list
  2. if the LLM asks for tools, run them and send the results back
  3. repeat until it answers in plain text (or max_rounds is hit)
Every LLM reply is logged as agent_msg and every tool run as tool_call.

Run it (uses the fake race until data/state.py lands):
    python -m agents.ask "What tyres is VER on?"
    python -m agents.ask "Who has pitted so far?" --lap 14
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data.schema import LapSnapshot
from tools.jsonl_log import DEFAULT_LOG_DIR, log_event
from tools.registry import TOOL_SPECS, run_tool

SYSTEM_PROMPT = (
    "You are an F1 race engineer's assistant. It is the end of lap {lap} of {total} in {race}; "
    "you work for {ego}. Use the tools to look up data instead of guessing, and answer briefly."
)


def ask(
    question: str,
    snap: LapSnapshot,
    *,
    client=None,
    model: str | None = None,
    agent: str = "Assistant",
    run_id: str | None = None,
    log_dir: Path | str = DEFAULT_LOG_DIR,
    max_rounds: int = 5,
) -> str:
    if client is None or model is None:
        from agents.llm import default_model, get_client
        client = client or get_client()
        model = model or default_model()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(
            lap=snap.lap, total=snap.total_laps, race=snap.race_id, ego=snap.ego_driver)},
        {"role": "user", "content": question},
    ]

    for round_ in range(1, max_rounds + 1):
        reply = client.chat.completions.create(model=model, messages=messages, tools=TOOL_SPECS)
        msg = reply.choices[0].message
        calls = msg.tool_calls or []
        log_event(snap.race_id, snap.lap, "agent_msg", run_id=run_id, log_dir=log_dir,
                  agent=agent, round=round_, model=model, content=msg.content,
                  tool_calls=[c.function.name for c in calls],
                  tokens_in=reply.usage.prompt_tokens, tokens_out=reply.usage.completion_tokens)

        if not calls:
            return msg.content or ""

        # Echo the assistant's tool request back, then answer each call with its result.
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
                for c in calls
            ],
        })
        for c in calls:
            try:
                args = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                result = {"error": f"arguments were not valid JSON: {c.function.arguments!r}"}
            else:
                result = run_tool(c.function.name, args, snap, agent=agent, run_id=run_id, log_dir=log_dir)
            messages.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(result)})

    return f"(no answer after {max_rounds} rounds of tool calls)"


def main() -> None:
    from tests.fixtures.fake_snapshot import FAKE_LAPS, fake_snapshot

    p = argparse.ArgumentParser(description="Ask the LLM about the (fake) race.")
    p.add_argument("question")
    p.add_argument("--lap", type=int, default=FAKE_LAPS)
    p.add_argument("--run-id", default="ask_demo")
    a = p.parse_args()

    snap = fake_snapshot(a.lap)
    print(ask(a.question, snap, run_id=a.run_id))
    print(f"\nlogged to {DEFAULT_LOG_DIR / (a.run_id + '.jsonl')}")


if __name__ == "__main__":
    main()
