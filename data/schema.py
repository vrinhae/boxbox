"""Per-lap snapshot schema: the contract between the data layer and the agents.

Agents and tools only ever receive a LapSnapshot. Nothing in it may come from
after `lap` (see CLAUDE.md core rules); LapSnapshot enforces this on creation.

Times are in seconds. None means the value is missing (e.g. a deleted lap time).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Compound(str, Enum):
    SOFT = "SOFT"
    MEDIUM = "MEDIUM"
    HARD = "HARD"
    INTERMEDIATE = "INTERMEDIATE"
    WET = "WET"
    UNKNOWN = "UNKNOWN"


class TrackStatus(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    SC = "SC"
    VSC = "VSC"
    RED = "RED"


@dataclass(frozen=True)
class LapRecord:
    """One completed lap by one driver."""

    driver: str  # three-letter code, e.g. "VER"
    lap: int
    lap_time: float | None
    position: int | None
    compound: Compound
    tyre_age: int  # laps on this set, including this lap
    stint: int
    pit_in: bool  # driver entered the pits at the end of this lap
    pit_out: bool  # driver left the pits at the start of this lap
    track_status: TrackStatus
    is_accurate: bool  # False for in/out laps, SC laps, etc. Exclude from pace fits


@dataclass(frozen=True)
class DriverState:
    """Where a driver stands at the end of the current lap."""

    driver: str
    team: str
    position: int | None
    gap_to_leader: float | None
    gap_ahead: float | None  # to the car one position ahead
    gap_behind: float | None  # to the car one position behind
    last_lap_time: float | None
    compound: Compound
    tyre_age: int
    stint: int
    pit_stops: int
    compounds_used: tuple[Compound, ...]  # dry races require two different compounds
    retired: bool = False


@dataclass(frozen=True)
class RaceControlMessage:
    lap: int
    category: str  # e.g. "Flag", "SafetyCar", "Drs", "Other"
    message: str
    flag: str | None = None


@dataclass(frozen=True)
class LapSnapshot:
    """Everything known at the end of `lap`. The only thing agents ever see."""

    race_id: str  # e.g. "2023_bahrain"
    lap: int  # last completed lap
    total_laps: int
    track_status: TrackStatus
    ego_driver: str  # the driver we make decisions for
    drivers: tuple[DriverState, ...]
    history: tuple[LapRecord, ...] = field(repr=False)  # all laps 1..lap, all drivers
    race_control: tuple[RaceControlMessage, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if not 0 <= self.lap <= self.total_laps:
            raise ValueError(f"lap {self.lap} outside 0..{self.total_laps}")
        future = [r for r in self.history if r.lap > self.lap]
        future += [m for m in self.race_control if m.lap > self.lap]
        if future:
            raise ValueError(
                f"lookahead: {len(future)} records after lap {self.lap} in snapshot"
            )
        if self.ego_driver not in {d.driver for d in self.drivers}:
            raise ValueError(f"ego driver {self.ego_driver} not in drivers")

    @property
    def laps_remaining(self) -> int:
        return self.total_laps - self.lap

    @property
    def ego(self) -> DriverState:
        return self.driver(self.ego_driver)

    def driver(self, code: str) -> DriverState:
        for d in self.drivers:
            if d.driver == code:
                return d
        raise KeyError(code)

    def laps_for(self, code: str) -> tuple[LapRecord, ...]:
        return tuple(r for r in self.history if r.driver == code)
