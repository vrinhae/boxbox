"""Loader tests on a tiny hand-made OpenF1 response: no network.

The race: 3 laps, three cars. AAA leads throughout. BBB pits at the end of
lap 1 (soft -> hard). CCC retires on lap 3 (OpenF1 lists the lap with no
duration). A VSC runs during lap 2.
"""

import pandas as pd
import pytest

from data.loader import build_race, find_session, read_race, status_periods
from data.schema import TrackStatus

START = pd.Timestamp("2026-06-28T13:00:00Z")
SESSION = {"year": 2026, "location": "São Paulo", "country_name": "Brazil", "circuit_short_name": "Interlagos",
           "date_start": "2026-06-28T13:00:00+00:00", "session_key": 1}


def t(seconds):
    return (START + pd.Timedelta(seconds=seconds)).isoformat()


def lap(n, number, start, duration, out=False):
    return {"driver_number": n, "lap_number": number, "date_start": t(start), "lap_duration": duration, "is_pit_out_lap": out}


RAW = {
    "drivers": [
        {"driver_number": 1, "name_acronym": "AAA", "team_name": "Team A", "full_name": "Ann A"},
        {"driver_number": 2, "name_acronym": "BBB", "team_name": "Team B", "full_name": "Bob B"},
        {"driver_number": 3, "name_acronym": "CCC", "team_name": "Team C", "full_name": "Cat C"},
    ],
    "laps": [
        lap(1, 1, 0, 90.0), lap(1, 2, 90, 95.0), lap(1, 3, 185, 89.0),
        lap(2, 1, 0, 111.0), lap(2, 2, 111, 96.0, out=True), lap(2, 3, 207, 90.0),
        lap(3, 1, 0, 92.0), lap(3, 2, 92, 95.5), lap(3, 3, 187.5, None),  # retired on lap 3
    ],
    "stints": [
        {"driver_number": 1, "stint_number": 1, "lap_start": 1, "lap_end": 3, "compound": "MEDIUM", "tyre_age_at_start": 0},
        {"driver_number": 2, "stint_number": 1, "lap_start": 1, "lap_end": 1, "compound": "SOFT", "tyre_age_at_start": 3},
        {"driver_number": 2, "stint_number": 2, "lap_start": 2, "lap_end": 3, "compound": "HARD", "tyre_age_at_start": 0},
        {"driver_number": 3, "stint_number": 1, "lap_start": 1, "lap_end": 3, "compound": "MEDIUM", "tyre_age_at_start": 0},
    ],
    "pit": [{"driver_number": 2, "lap_number": 1}],
    "race_control": [
        {"date": t(-60), "lap_number": 1, "category": "Flag", "flag": "GREEN", "scope": "Track", "sector": None, "driver_number": None, "message": "GREEN LIGHT - PIT EXIT OPEN"},
        {"date": t(120), "lap_number": 2, "category": "SafetyCar", "flag": None, "scope": "Track", "sector": None, "driver_number": None, "message": "VSC DEPLOYED"},
        {"date": t(150), "lap_number": 2, "category": "SafetyCar", "flag": None, "scope": "Track", "sector": None, "driver_number": None, "message": "VSC ENDING"},
    ],
    "weather": [{"rainfall": 0}],
    "session_result": [
        {"driver_number": 1, "position": 1, "number_of_laps": 3, "dnf": False, "dns": False, "dsq": False, "points": 25},
        {"driver_number": 2, "position": 2, "number_of_laps": 3, "dnf": False, "dns": False, "dsq": False, "points": 18},
        {"driver_number": 3, "position": None, "number_of_laps": 2, "dnf": True, "dns": False, "dsq": False, "points": 0},
    ],
}


@pytest.fixture(scope="module")
def built():
    return build_race(RAW, SESSION)


def row(laps, driver, n):
    (r,) = laps[(laps["driver"] == driver) & (laps["lap"] == n)].itertuples()
    return r


def test_meta(built):
    _, _, _, meta = built
    assert meta["race_id"] == "2026_sao_paulo"
    assert meta["total_laps"] == 3
    assert meta["drivers"]["BBB"] == {"number": 2, "team": "Team B", "name": "Bob B"}
    assert meta["rain"] is False


def test_unfinished_lap_is_dropped(built):
    laps = built[0]
    assert sorted(laps.loc[laps["driver"] == "CCC", "lap"]) == [1, 2]
    assert len(laps) == 8


def test_positions_and_timing(built):
    laps = built[0]
    assert [r.driver for r in laps[laps["lap"] == 1].itertuples()] == ["AAA", "CCC", "BBB"]
    assert row(laps, "BBB", 2).position == 3 and row(laps, "CCC", 2).position == 2
    assert row(laps, "AAA", 3).lap_end == 274.0
    assert row(laps, "AAA", 2).lap_time == 95.0


def test_tyres_and_pits(built):
    laps = built[0]
    first, second = row(laps, "BBB", 1), row(laps, "BBB", 2)
    assert (first.compound, first.tyre_age, first.stint, first.pit_in) == ("SOFT", 4, 1, True)  # used set: 3 laps old at start
    assert (second.compound, second.tyre_age, second.stint, second.pit_out) == ("HARD", 1, 2, True)
    assert not row(laps, "AAA", 1).pit_in


def test_vsc_marks_overlapping_laps(built):
    laps = built[0]
    assert set(laps.loc[laps["lap"] == 2, "track_status"]) == {"VSC"}
    assert set(laps.loc[laps["lap"] == 3, "track_status"]) == {"GREEN"}
    assert not row(laps, "AAA", 2).is_accurate  # VSC
    assert not row(laps, "AAA", 1).is_accurate  # lap 1
    assert row(laps, "AAA", 3).is_accurate


def test_results_kept_apart_and_warnings(built):
    _, rc, results, meta = built
    assert results.set_index("driver").loc["CCC", "dnf"]
    assert list(rc["message"]) == ["GREEN LIGHT - PIT EXIT OPEN", "VSC DEPLOYED", "VSC ENDING"]
    assert meta["warnings"] == ["BBB: stint 1 is 1 lap long"]


def test_status_periods_sector_yellow_and_sc():
    rc = pd.DataFrame([
        {"date": START, "category": "Flag", "flag": "YELLOW", "scope": "Sector", "sector": 4, "message": "YELLOW IN TRACK SECTOR 4"},
        {"date": START + pd.Timedelta(seconds=10), "category": "Flag", "flag": "CLEAR", "scope": "Sector", "sector": 4, "message": "CLEAR IN TRACK SECTOR 4"},
        {"date": START + pd.Timedelta(seconds=20), "category": "SafetyCar", "flag": None, "scope": "Track", "sector": None, "message": "SAFETY CAR DEPLOYED"},
        {"date": START + pd.Timedelta(seconds=90), "category": "Flag", "flag": "GREEN", "scope": "Track", "sector": None, "message": "TRACK CLEAR"},
    ])
    got = [(s, e, status) for s, e, status in status_periods(rc)]
    assert (START, START + pd.Timedelta(seconds=10), TrackStatus.YELLOW) in got
    assert (START + pd.Timedelta(seconds=20), START + pd.Timedelta(seconds=90), TrackStatus.SC) in got


def test_find_session_by_name_or_key():
    sessions = [
        {"session_key": 11, "location": "São Paulo", "country_name": "Brazil", "circuit_short_name": "Interlagos"},
        {"session_key": 12, "location": "Austin", "country_name": "United States", "circuit_short_name": "Austin"},
        {"session_key": 13, "location": "Las Vegas", "country_name": "United States", "circuit_short_name": "Las Vegas"},
    ]
    assert find_session(2026, "sao paulo", sessions)["session_key"] == 11
    assert find_session(2026, "Interlagos", sessions)["session_key"] == 11
    assert find_session(2026, 13, sessions)["location"] == "Las Vegas"
    with pytest.raises(ValueError, match="several"):
        find_session(2026, "United States", sessions)


@pytest.mark.parametrize("race_id", ["2026_spielberg", "2026_budapest"])
def test_committed_races_are_consistent(race_id):
    laps, rc, meta = read_race(race_id)
    assert meta["race_id"] == race_id and meta["source"] == "openf1"
    for _, g in laps.groupby("lap"):
        assert sorted(g["position"]) == list(range(1, len(g) + 1))
    for _, g in laps.groupby("driver"):
        assert list(g.sort_values("lap")["lap"]) == list(range(1, len(g) + 1))
    assert laps["lap"].max() == meta["total_laps"]
    assert set(laps["driver"]) <= set(meta["drivers"])
