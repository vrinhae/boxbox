"""Tools as the LLM sees them, and the single entry point that runs them.

TOOL_SPECS describes each tool in the OpenAI function-calling format. The LLM
picks a tool and arguments; run_tool executes it against the snapshot the
caller supplies and logs a tool_call event. The LLM never chooses the lap or
the snapshot, so it can't ask for data past the current lap.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from data.schema import LapSnapshot
from tools.jsonl_log import DEFAULT_LOG_DIR, log_event
from tools.query import get_race_control, query_laps

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "query_laps",
            "description": (
                "Completed laps so far: lap time, position, tyre compound, tyre age, stint, "
                "pit in/out and track status. Filter with driver and last_n to keep results small."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "driver": {"type": "string", "description": "Three-letter driver code, e.g. VER. Omit for all drivers."},
                    "last_n": {"type": "integer", "minimum": 1, "description": "Only the last n completed laps."},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_race_control",
            "description": "Race control messages so far: flags, safety car, DRS.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
]

_TOOLS: dict[str, Callable[..., Any]] = {"query_laps": query_laps, "get_race_control": get_race_control}


def run_tool(
    name: str,
    args: dict,
    snap: LapSnapshot,
    *,
    agent: str,
    run_id: str | None = None,
    log_dir: Path | str = DEFAULT_LOG_DIR,
) -> Any:
    """Run one tool call and log it. Errors come back as {"error": ...} so the LLM can retry."""
    fn = _TOOLS.get(name)
    if fn is None:
        result: Any = {"error": f"unknown tool {name!r}; available: {sorted(_TOOLS)}"}
    else:
        try:
            result = fn(snap, **args)
        except (TypeError, ValueError) as e:  # bad arguments from the LLM
            result = {"error": str(e)}

    log_event(snap.race_id, snap.lap, "tool_call", run_id=run_id, log_dir=log_dir,
              agent=agent, tool=name, args=args, result=result)
    return result
