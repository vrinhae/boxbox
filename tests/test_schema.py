import pytest

from data.schema import Compound, DriverState, LapRecord, LapSnapshot, TrackStatus


def make_snapshot(lap: int, history_laps: list[int]) -> LapSnapshot:
    ver = DriverState("VER", "Red Bull", 1, 0.0, None, 2.1, 95.2, Compound.SOFT, 5, 1, 0, (Compound.SOFT,))
    history = tuple(
        LapRecord("VER", n, 95.2, 1, Compound.SOFT, n, 1, False, False, TrackStatus.GREEN, True)
        for n in history_laps
    )
    return LapSnapshot("2023_bahrain", lap, 57, TrackStatus.GREEN, "VER", (ver,), history, ())


def test_valid_snapshot():
    snap = make_snapshot(5, [1, 2, 3, 4, 5])
    assert snap.ego.position == 1
    assert snap.laps_remaining == 52
    assert len(snap.laps_for("VER")) == 5


def test_rejects_future_laps():
    with pytest.raises(ValueError, match="lookahead"):
        make_snapshot(4, [1, 2, 3, 4, 5])
