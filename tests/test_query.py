import json

import pytest

from data.schema import Compound
from tests.fixtures.fake_snapshot import fake_snapshot
from tools.query import get_race_control, query_laps


def test_all_laps_in_order():
    rows = query_laps(fake_snapshot(5))
    assert len(rows) == 15  # 3 drivers x 5 laps
    assert [r["lap"] for r in rows] == sorted(r["lap"] for r in rows)
    assert [r["driver"] for r in rows if r["lap"] == 2] == ["VER", "LEC", "HAM"]


def test_filter_by_driver():
    rows = query_laps(fake_snapshot(5), driver="HAM")
    assert [r["lap"] for r in rows] == [1, 2, 3, 4, 5]
    assert {r["driver"] for r in rows} == {"HAM"}
    pit = next(r for r in rows if r["pit_in"])
    assert pit["lap"] == 3
    assert rows[3]["compound"] == "HARD" and rows[3]["tyre_age"] == 1


def test_last_n():
    rows = query_laps(fake_snapshot(5), driver="VER", last_n=2)
    assert [r["lap"] for r in rows] == [4, 5]
    assert len(query_laps(fake_snapshot(5), last_n=1)) == 3
    # Asking for more laps than exist just returns them all.
    assert len(query_laps(fake_snapshot(2), last_n=10)) == 6


def test_only_sees_up_to_current_lap():
    rows = query_laps(fake_snapshot(3))
    assert max(r["lap"] for r in rows) == 3
    assert max(m["lap"] for m in get_race_control(fake_snapshot(3))) == 2


def test_bad_arguments_give_clear_errors():
    with pytest.raises(ValueError, match="drivers in this race: VER, LEC, HAM"):
        query_laps(fake_snapshot(), driver="NOR")
    with pytest.raises(ValueError, match="last_n"):
        query_laps(fake_snapshot(), last_n=0)


def test_race_control():
    msgs = get_race_control(fake_snapshot(5))
    assert [m["lap"] for m in msgs] == [1, 2, 4, 5]
    assert msgs[2] == {"lap": 4, "category": "Flag", "message": "YELLOW IN TRACK SECTOR 7", "flag": "YELLOW"}


def test_results_are_json_ready():
    snap = fake_snapshot(5)
    json.dumps(query_laps(snap))
    json.dumps(get_race_control(snap))
    assert query_laps(snap, driver="VER", last_n=1)[0]["compound"] == "SOFT"
    assert type(query_laps(snap, driver="VER", last_n=1)[0]["compound"]) is str


def test_fake_snapshot_state():
    snap = fake_snapshot(5)
    assert [d.driver for d in snap.drivers] == ["VER", "LEC", "HAM"]
    ham = snap.driver("HAM")
    assert ham.pit_stops == 1
    assert ham.compound == Compound.HARD
    assert ham.compounds_used == (Compound.SOFT, Compound.HARD)
    assert snap.ego.driver == "LEC" and snap.ego.gap_ahead > 0
