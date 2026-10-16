"""JSONL run logger: one JSON object per line, appended as events happen.

Every agent message, tool call, plan and decision goes through log_event, and
the replay viewer reads these files back (see docs/PLAN.md, Replay viewer).
JSONL suits this: appending a line is cheap, a crashed run still leaves every
line written before the crash, and pandas can load it with read_json(lines=True).
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

# The six event types the replay viewer understands. Rejecting anything else
# catches typos like "tool_cal" at the call site instead of in the viewer.
EVENT_TYPES = frozenset({"lap_state", "route", "agent_msg", "tool_call", "plan", "decision"})

DEFAULT_LOG_DIR = Path("logs")

# Keys log_event fills in itself; a caller's **fields must not overwrite them.
_RESERVED = {"timestamp", "run_id", "race_id", "lap", "event"}


def log_event(
    race_id: str,
    lap: int,
    event: str,
    *,
    run_id: str | None = None,
    log_dir: Path | str = DEFAULT_LOG_DIR,
    **fields: Any,
) -> None:
    """Append one event to <log_dir>/<run_id>.jsonl.

    run_id names the file, so several runs of the same race (different ego
    drivers or systems) don't mix. It defaults to race_id. Example:

        log_event("2023_bahrain", 14, "tool_call", run_id="2023_bahrain_LEC_multi",
                  agent="Strategist", tool="simulate", args={...}, result={...})
    """
    if event not in EVENT_TYPES:
        raise ValueError(f"unknown event type {event!r}; expected one of {sorted(EVENT_TYPES)}")
    clash = _RESERVED & fields.keys()
    if clash:
        raise ValueError(f"fields {sorted(clash)} are set by log_event itself")

    run_id = run_id or race_id
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "race_id": race_id,
        "lap": lap,
        "event": event,
        **fields,
    }

    path = Path(log_dir) / f"{run_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    # default= handles anything json can't encode natively, so a logging call
    # never crashes a race replay.
    line = json.dumps(record, default=_to_jsonable, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_events(path: Path | str) -> list[dict]:
    """Load every event from one JSONL log file, in the order they were written."""
    with Path(path).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _to_jsonable(obj: Any) -> Any:
    """Fallback encoder for types json.dumps doesn't know."""
    # Schema objects (LapSnapshot, DriverState, ...) become plain dicts.
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    # Compound.SOFT -> "SOFT", TrackStatus.SC -> "SC".
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (set, frozenset)):
        return sorted(obj, key=str)
    # Last resort (Paths, numpy scalars, ...): the string form beats crashing.
    return str(obj)
