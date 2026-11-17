"""Loader tests on one tiny hand-made race, as OpenF1 and as FastF1 would serve it: no network.

The race: 3 laps, three cars. AAA leads throughout. BBB pits at the end of
lap 1 (soft -> hard). CCC retires on lap 3 (OpenF1 lists the lap with no
duration; FastF1 lists it with no end time). A VSC runs during lap 2.
"""

from types import SimpleNamespace

import pandas as pd
import pytest

from data.loader import load_race, read_race
from data.schema import TrackStatus
from data.sources import fastf1 as ff1_source
from data.sources.openf1 import build_race, find_session, status_periods

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


# ---------- FastF1: the same race as a stand-in FastF1 session ----------

T0 = pd.Timedelta(seconds=1000)  # session time when lap 1 starts
NAT = pd.NaT


def ff_lap(code, number, n, start, end, lap_time, compound, life, stint, status="1", pit_in=False, pit_out=None):
    s = lambda x: NAT if x is None else T0 + pd.Timedelta(seconds=x)  # noqa: E731
    return {
        "Driver": code, "DriverNumber": str(number), "LapNumber": float(n), "LapStartTime": s(start), "Time": s(end),
        "LapTime": NAT if lap_time is None else pd.Timedelta(seconds=lap_time), "Compound": compound, "TyreLife": float(life),
        "Stint": float(stint), "PitInTime": s(end - 2) if pit_in else NAT, "PitOutTime": s(pit_out),
        "TrackStatus": status, "IsAccurate": True, "FastF1Generated": False,
    }


FF1_LAPS = pd.DataFrame([
    ff_lap("AAA", 1, 1, 0, 90, 90.0, "MEDIUM", 1, 1, pit_out=-600),  # left the garage before the formation lap
    ff_lap("AAA", 1, 2, 90, 185, 95.0, "MEDIUM", 2, 1, status="167"),
    ff_lap("AAA", 1, 3, 185, 274, 89.0, "MEDIUM", 3, 1),
    ff_lap("BBB", 2, 1, 0, 111, 111.0, "SOFT", 4, 1, pit_in=True),
    ff_lap("BBB", 2, 2, 111, 207, 96.0, "HARD", 1, 2, status="16", pit_out=125),
    ff_lap("BBB", 2, 3, 207, 297, 90.0, "HARD", 2, 2),
    ff_lap("CCC", 3, 1, 0, 92, 92.0, "MEDIUM", 1, 1),
    ff_lap("CCC", 3, 2, 92, 187.5, 95.5, "MEDIUM", 2, 1, status="167"),
    {**ff_lap("CCC", 3, 3, 187.5, 200, None, "MEDIUM", 3, 1), "Time": NAT},  # retired: never completed
])


def ff_session(laps=FF1_LAPS):
    utc = lambda x: (START + pd.Timedelta(seconds=x)).tz_convert(None)  # FastF1 gives naive UTC  # noqa: E731
    rc = pd.DataFrame([
        {"Time": utc(-60), "Category": "Flag", "Message": "GREEN LIGHT - PIT EXIT OPEN", "Flag": "GREEN", "Scope": "Track", "Sector": None, "RacingNumber": None, "Lap": 1},
        {"Time": utc(120), "Category": "SafetyCar", "Message": "VSC DEPLOYED", "Flag": None, "Scope": "Track", "Sector": None, "RacingNumber": None, "Lap": 2},
        {"Time": utc(150), "Category": "SafetyCar", "Message": "VSC ENDING", "Flag": None, "Scope": "Track", "Sector": None, "RacingNumber": None, "Lap": 2},
        {"Time": utc(274), "Category": "Flag", "Message": "CHEQUERED FLAG", "Flag": "CHEQUERED", "Scope": "Track", "Sector": None, "RacingNumber": None, "Lap": 3},
    ])
    results = pd.DataFrame([
        {"DriverNumber": "1", "Abbreviation": "AAA", "TeamName": "Team A", "FullName": "Ann A", "Position": 1.0, "ClassifiedPosition": "1", "Laps": 3.0, "Points": 25.0},
        {"DriverNumber": "2", "Abbreviation": "BBB", "TeamName": "Team B", "FullName": "Bob B", "Position": 2.0, "ClassifiedPosition": "2", "Laps": 3.0, "Points": 18.0},
        {"DriverNumber": "3", "Abbreviation": "CCC", "TeamName": "Team C", "FullName": "Cat C", "Position": 3.0, "ClassifiedPosition": "R", "Laps": 2.0, "Points": 0.0},
    ])
    return SimpleNamespace(
        laps=laps, results=results, race_control_messages=rc, weather_data=pd.DataFrame({"Rainfall": [False]}),
        event=pd.Series({"EventDate": pd.Timestamp("2026-06-28"), "Location": "São Paulo", "Country": "Brazil"}),
        session_info={"Key": 9000, "Meeting": {"Circuit": {"ShortName": "Interlagos"}}}, date=pd.Timestamp("2026-06-28 13:00"),
    )


@pytest.fixture(scope="module")
def built_ff1():
    return ff1_source.build_race(ff_session())


def test_fastf1_and_openf1_give_the_same_laps(built, built_ff1):
    pd.testing.assert_frame_equal(built_ff1[0], built[0], check_dtype=False)


def test_fastf1_meta_matches_openf1(built, built_ff1):
    skip = {"source", "session_key", "fetched"}
    assert {k: v for k, v in built_ff1[3].items() if k not in skip} == {k: v for k, v in built[3].items() if k not in skip}
    assert built_ff1[3]["source"] == "fastf1"


def test_fastf1_race_control_lined_up_on_chequered_flag(built_ff1):
    rc = built_ff1[1].set_index("message")
    assert rc.loc["VSC DEPLOYED", "time"] == 120.0 and rc.loc["GREEN LIGHT - PIT EXIT OPEN", "time"] == -60.0


def test_fastf1_results(built_ff1):
    results = built_ff1[2].set_index("driver")
    assert results.loc["CCC", "dnf"] and pd.isna(results.loc["CCC", "position"])
    assert results.loc["AAA", "position"] == 1 and not results.loc["AAA", "dnf"]


def test_fastf1_drops_generated_laps_and_keeps_pit_lane_starts():
    laps = FF1_LAPS.copy()
    laps.loc[0, "PitOutTime"] = T0 + pd.Timedelta(seconds=20)  # AAA starts from the pit lane
    extra = {**ff_lap("CCC", 3, 3, 187.5, 280, 92.5, "MEDIUM", 3, 1), "FastF1Generated": True}
    built = ff1_source.build_race(ff_session(pd.concat([laps, pd.DataFrame([extra])], ignore_index=True)))[0]
    assert row(built, "AAA", 1).pit_out
    assert 3 not in set(built.loc[built["driver"] == "CCC", "lap"])


def test_unknown_source_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown source"):
        load_race(2026, "Spielberg", source="ergast", races_dir=tmp_path)
