"""Hand-made 18-lap race for building tools before data/state.py lands.

fake_snapshot(lap) slices the race the same way get_state will: everything up
to and including `lap`, nothing after. Three drivers start on softs; HAM makes
a normal early stop at the end of lap 12 (soft -> hard, a typical undercut
attempt), VER and LEC stay out. Yellow flag on lap 8. The numbers are invented
but follow realistic patterns: tyre wear, fuel burn-off, slow in/out laps.
"""

from __future__ import annotations

from data.schema import Compound, DriverState, LapRecord, LapSnapshot, RaceControlMessage, TrackStatus

RACE_ID = "fake_bahrain"
TOTAL_LAPS = 57
FAKE_LAPS = 18

TEAMS = {"VER": "Red Bull", "LEC": "Ferrari", "HAM": "Mercedes"}
BASE_PACE = {"VER": 95.0, "LEC": 95.3, "HAM": 95.5}  # seconds, fresh tyre, full fuel
PIT_IN_LAPS = {"HAM": [12]}

# compound: (offset vs soft in s, wear in s per lap of tyre age)
TYRES = {Compound.SOFT: (0.0, 0.08), Compound.HARD: (0.6, 0.03)}
PIT_LOSS = 21.5      # added to the in-lap
OUT_LAP_LOSS = 1.5   # cold tyres on the out-lap
YELLOW_LOSS = 0.7
YELLOW_LAPS = {8}

_RACE_CONTROL = [
    RaceControlMessage(1, "Flag", "GREEN LIGHT - PIT EXIT OPEN", "GREEN"),
    RaceControlMessage(3, "Drs", "DRS ENABLED"),
    RaceControlMessage(8, "Flag", "YELLOW IN TRACK SECTOR 7", "YELLOW"),
    RaceControlMessage(9, "Flag", "CLEAR IN TRACK SECTOR 7", "CLEAR"),
]


def _build_race() -> list[LapRecord]:
    """Every lap of the fake race, positions included."""
    raw = []  # (driver, lap, lap_time, compound, age, stint, pit_in, pit_out, status)
    for grid, d in enumerate(TEAMS):
        compound, age, stint = Compound.SOFT, 0, 1
        for n in range(1, FAKE_LAPS + 1):
            pit_out = n - 1 in PIT_IN_LAPS.get(d, [])
            if pit_out:
                compound, age, stint = Compound.HARD, 0, stint + 1
            age += 1
            pit_in = n in PIT_IN_LAPS.get(d, [])
            status = TrackStatus.YELLOW if n in YELLOW_LAPS else TrackStatus.GREEN
            offset, wear = TYRES[compound]
            t = BASE_PACE[d] + offset + wear * age - 0.05 * n
            t += (2.5 + 0.4 * grid) if n == 1 else 0       # standing start
            t += PIT_LOSS if pit_in else 0
            t += OUT_LAP_LOSS if pit_out else 0
            t += YELLOW_LOSS if status is TrackStatus.YELLOW else 0
            raw.append((d, n, round(t, 3), compound, age, stint, pit_in, pit_out, status))

    # Position at the end of each lap = order of total race time so far.
    totals = {d: 0.0 for d in TEAMS}
    position = {}
    for n in range(1, FAKE_LAPS + 1):
        for r in raw:
            if r[1] == n:
                totals[r[0]] += r[2]
        for i, d in enumerate(sorted(TEAMS, key=totals.get)):
            position[(d, n)] = i + 1

    return [
        LapRecord(
            driver=d, lap=n, lap_time=t, position=position[(d, n)], compound=c, tyre_age=age, stint=stint,
            pit_in=pin, pit_out=pout, track_status=ts,
            is_accurate=not (pin or pout or n == 1 or ts is not TrackStatus.GREEN),
        )
        for d, n, t, c, age, stint, pin, pout, ts in raw
    ]


_RACE = _build_race()


def fake_snapshot(lap: int = FAKE_LAPS, ego_driver: str = "LEC") -> LapSnapshot:
    if not 1 <= lap <= FAKE_LAPS:
        raise ValueError(f"fake race only has laps 1..{FAKE_LAPS}")

    history = tuple(r for r in _RACE if r.lap <= lap)
    cum = {d: sum(r.lap_time for r in history if r.driver == d) for d in TEAMS}
    order = sorted(TEAMS, key=cum.get)

    drivers = []
    for i, d in enumerate(order):
        mine = [r for r in history if r.driver == d]
        last = mine[-1]
        drivers.append(DriverState(
            driver=d, team=TEAMS[d], position=i + 1,
            gap_to_leader=round(cum[d] - cum[order[0]], 3),
            gap_ahead=round(cum[d] - cum[order[i - 1]], 3) if i > 0 else None,
            gap_behind=round(cum[order[i + 1]] - cum[d], 3) if i < len(order) - 1 else None,
            last_lap_time=last.lap_time, compound=last.compound, tyre_age=last.tyre_age, stint=last.stint,
            pit_stops=sum(r.pit_in for r in mine),
            compounds_used=tuple(dict.fromkeys(r.compound for r in mine)),
        ))

    return LapSnapshot(
        race_id=RACE_ID, lap=lap, total_laps=TOTAL_LAPS, track_status=history[-1].track_status,
        ego_driver=ego_driver, drivers=tuple(drivers),
        history=history, race_control=tuple(m for m in _RACE_CONTROL if m.lap <= lap),
    )
