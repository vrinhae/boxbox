"""Read-only query tools agents call to look at the race.

Both take a LapSnapshot and nothing else, so they can only see what the
snapshot holds: data up to the current lap. They never touch FastF1 or the
cache. Results are plain dicts of JSON-friendly values (enums become their
string value) so they can go straight into an LLM tool result and the log.
"""

from __future__ import annotations

import dataclasses
from enum import Enum

from data.schema import LapSnapshot


def query_laps(snap: LapSnapshot, driver: str | None = None, last_n: int | None = None) -> list[dict]:
    """Completed laps, oldest first, ordered by position within each lap.

    driver: three-letter code (e.g. "VER") to return only that driver's laps.
    last_n: only the last n completed laps of the race (e.g. last_n=3 at lap 20
            returns laps 18-20).
    """
    if driver is not None and driver not in {d.driver for d in snap.drivers}:
        known = ", ".join(d.driver for d in snap.drivers)
        raise ValueError(f"unknown driver {driver!r}; drivers in this race: {known}")
    if last_n is not None and last_n < 1:
        raise ValueError(f"last_n must be at least 1, got {last_n}")

    first_lap = snap.lap - last_n + 1 if last_n is not None else 1
    laps = [
        r for r in snap.history
        if r.lap >= first_lap and (driver is None or r.driver == driver)
    ]
    laps.sort(key=lambda r: (r.lap, r.position if r.position is not None else 99))
    return [_plain(r) for r in laps]


def get_race_control(snap: LapSnapshot) -> list[dict]:
    """Race control messages so far (flags, safety car, DRS), oldest first."""
    return [_plain(m) for m in sorted(snap.race_control, key=lambda m: m.lap)]


def _plain(record) -> dict:
    """Dataclass -> dict, with enums replaced by their string values."""
    return {k: v.value if isinstance(v, Enum) else v for k, v in dataclasses.asdict(record).items()}
