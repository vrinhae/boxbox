import json

import pytest

from data.schema import Compound
from tests.fixtures.fake_snapshot import FAKE_LAPS, fake_snapshot
from tools.query import get_race_control, query_laps


def test_all_laps_in_order():
    rows = query_laps(fake_snapshot())
    assert len(rows) == 3 * FAKE_LAPS
    assert [r["lap"] for r in rows] == sorted(r["lap"] for r in rows)
    assert [r["driver"] for r in rows if r["lap"] == 2] == ["VER", "LEC", "HAM"]


def test_filter_by_driver():
    rows = query_laps(fake_snapshot(), driver="HAM")
    assert [r["lap"] for r in rows] == list(range(1, FAKE_LAPS + 1))
    assert {r["driver"] for r in rows} == {"HAM"}
    assert [r["lap"] for r in rows if r["pit_in"]] == [12]
    lap13 = rows[12]
    assert lap13["pit_out"] and lap13["compound"] == "HARD" and lap13["tyre_age"] == 1


def test_last_n():
    rows = query_laps(fake_snapshot(18), driver="VER", last_n=2)
    assert [r["lap"] for r in rows] == [17, 18]
    assert len(query_laps(fake_snapshot(18), last_n=1)) == 3
    # Asking for more laps than exist just returns them all.
    assert len(query_laps(fake_snapshot(2), last_n=10)) == 6


def test_only_sees_up_to_current_lap():
    snap = fake_snapshot(10)
    assert max(r["lap"] for r in query_laps(snap)) == 10
    assert not any(r["pit_in"] for r in query_laps(snap, driver="HAM"))  # HAM's stop is on lap 12
    assert max(m["lap"] for m in get_race_control(fake_snapshot(5))) == 3


def test_bad_arguments_give_clear_errors():
    with pytest.raises(ValueError, match="drivers in this race: VER, LEC, HAM"):
        query_laps(fake_snapshot(), driver="NOR")
    with pytest.raises(ValueError, match="last_n"):
        query_laps(fake_snapshot(), last_n=0)


def test_race_control():
    msgs = get_race_control(fake_snapshot())
    assert [m["lap"] for m in msgs] == [1, 3, 8, 9]
    assert msgs[2] == {"lap": 8, "category": "Flag", "message": "YELLOW IN TRACK SECTOR 7", "flag": "YELLOW"}


def test_results_are_json_ready():
    snap = fake_snapshot()
    json.dumps(query_laps(snap))
    json.dumps(get_race_control(snap))
    row = query_laps(snap, driver="VER", last_n=1)[0]
    assert row["compound"] == "SOFT" and type(row["compound"]) is str


def test_fake_race_is_realistic():
    snap = fake_snapshot()
    ham = snap.driver("HAM")
    assert ham.pit_stops == 1
    assert ham.compounds_used == (Compound.SOFT, Compound.HARD)
    assert [d.driver for d in snap.drivers] == ["VER", "LEC", "HAM"]
    assert snap.ego.driver == "LEC" and snap.ego.gap_ahead > 0

    ver = [r["lap_time"] for r in query_laps(snap, driver="VER")]
    ham_laps = query_laps(snap, driver="HAM")
    assert 20 < ham_laps[11]["lap_time"] - ver[11] < 25        # in-lap costs the pit loss
    assert ver[16] > ver[3]                                     # softs wear: lap 17 slower than lap 4
    assert ham_laps[17]["lap_time"] < ver[17]                   # fresh hards beat 18-lap-old softs
