"""Hand-made 5-lap race for building tools before data/state.py lands.

fake_snapshot(lap) slices the race the same way get_state will: everything up
to and including `lap`, nothing after. Three drivers; HAM pits at the end of
lap 3 (soft -> hard). The numbers are invented, not real 2023 Bahrain data.
"""

from __future__ import annotations

from data.schema import Compound, DriverState, LapRecord, LapSnapshot, RaceControlMessage, TrackStatus

RACE_ID = "fake_bahrain"
TOTAL_LAPS = 57
FAKE_LAPS = 5

S, H = Compound.SOFT, Compound.HARD
G, Y = TrackStatus.GREEN, TrackStatus.YELLOW

TEAMS = {"VER": "Red Bull", "LEC": "Ferrari", "HAM": "Mercedes"}

# (driver, lap, lap_time, compound, tyre_age, stint, pit_in, pit_out, track_status)
_LAPS = [
    ("VER", 1, 97.8, S, 1, 1, False, False, G),
    ("LEC", 1, 98.3, S, 1, 1, False, False, G),
    ("HAM", 1, 98.9, S, 1, 1, False, False, G),
    ("VER", 2, 95.1, S, 2, 1, False, False, G),
    ("LEC", 2, 95.4, S, 2, 1, False, False, G),
    ("HAM", 2, 95.6, S, 2, 1, False, False, G),
    ("VER", 3, 95.2, S, 3, 1, False, False, G),
    ("LEC", 3, 95.5, S, 3, 1, False, False, G),
    ("HAM", 3, 117.4, S, 3, 1, True, False, G),
    ("VER", 4, 95.9, S, 4, 1, False, False, Y),
    ("LEC", 4, 96.1, S, 4, 1, False, False, Y),
    ("HAM", 4, 97.0, H, 1, 2, False, True, Y),
    ("VER", 5, 95.4, S, 5, 1, False, False, G),
    ("LEC", 5, 95.8, S, 5, 1, False, False, G),
    ("HAM", 5, 95.3, H, 2, 2, False, False, G),
]

_RACE_CONTROL = [
    RaceControlMessage(1, "Flag", "GREEN LIGHT - PIT EXIT OPEN", "GREEN"),
    RaceControlMessage(2, "Drs", "DRS ENABLED"),
    RaceControlMessage(4, "Flag", "YELLOW IN TRACK SECTOR 7", "YELLOW"),
    RaceControlMessage(5, "Flag", "CLEAR IN TRACK SECTOR 7", "CLEAR"),
]


def fake_snapshot(lap: int = FAKE_LAPS, ego_driver: str = "LEC") -> LapSnapshot:
    if not 1 <= lap <= FAKE_LAPS:
        raise ValueError(f"fake race only has laps 1..{FAKE_LAPS}")

    rows = [r for r in _LAPS if r[1] <= lap]
    cum = {d: sum(r[2] for r in rows if r[0] == d) for d in TEAMS}
    order = sorted(TEAMS, key=cum.get)
    pos = {d: i + 1 for i, d in enumerate(order)}

    # Positions per lap, so each LapRecord carries where the driver was then.
    lap_pos: dict[tuple[str, int], int] = {}
    for n in range(1, lap + 1):
        totals = {d: sum(r[2] for r in rows if r[0] == d and r[1] <= n) for d in TEAMS}
        for i, d in enumerate(sorted(TEAMS, key=totals.get)):
            lap_pos[(d, n)] = i + 1

    history = tuple(
        LapRecord(
            driver=d, lap=n, lap_time=t, position=lap_pos[(d, n)], compound=c, tyre_age=age, stint=stint,
            pit_in=pin, pit_out=pout, track_status=ts,
            is_accurate=not (pin or pout or n == 1 or ts != G),
        )
        for d, n, t, c, age, stint, pin, pout, ts in rows
    )

    drivers = []
    for d in TEAMS:
        mine = [r for r in history if r.driver == d]
        last = mine[-1]
        i = order.index(d)
        drivers.append(DriverState(
            driver=d, team=TEAMS[d], position=pos[d],
            gap_to_leader=round(cum[d] - cum[order[0]], 3),
            gap_ahead=round(cum[d] - cum[order[i - 1]], 3) if i > 0 else None,
            gap_behind=round(cum[order[i + 1]] - cum[d], 3) if i < len(order) - 1 else None,
            last_lap_time=last.lap_time, compound=last.compound, tyre_age=last.tyre_age, stint=last.stint,
            pit_stops=sum(r.pit_in for r in mine),
            compounds_used=tuple(dict.fromkeys(r.compound for r in mine)),
        ))

    return LapSnapshot(
        race_id=RACE_ID, lap=lap, total_laps=TOTAL_LAPS, track_status=history[-1].track_status,
        ego_driver=ego_driver, drivers=tuple(sorted(drivers, key=lambda s: s.position)),
        history=history, race_control=tuple(m for m in _RACE_CONTROL if m.lap <= lap),
    )
