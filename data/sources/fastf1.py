"""FastF1 source: F1's own timing archive via the fastf1 package.

Since FastF1 3.9 the archive (livetiming.formula1.com/static/...) needs an F1 TV
subscription, even for past races. Sign in once, yourself, with

    python -m fastf1 auth f1tv

FastF1 already gives most per-lap columns (Position, Compound, TyreLife, Stint,
pit times, TrackStatus, IsAccurate), so this module mostly renames them. Its
cache lives in data/cache/fastf1/ (gitignored).

Times: FastF1 lap times are session time; race control messages are UTC. Without
telemetry there is no exact link between the two, so race control times are lined
up on the chequered flag (the leader's last lap end), good to about a second.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from data.schema import Compound, TrackStatus
from data.sources.common import finish, race_id, worst_status

NAME = "fastf1"
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache" / "fastf1"

# FastF1 track status codes; a lap's TrackStatus string lists every code seen during it.
TRACK_CODES = {"1": TrackStatus.GREEN, "2": TrackStatus.YELLOW, "4": TrackStatus.SC, "5": TrackStatus.RED,
               "6": TrackStatus.VSC, "7": TrackStatus.VSC}  # 7 = VSC ending, still under VSC

# ClassifiedPosition letters: R retired, N not classified, W withdrawn (did not start), D/E disqualified/excluded.
DNF, DNS, DSQ = {"R", "N"}, {"W"}, {"D", "E"}


def open_session(year: int, event: str | int, *, refresh: bool = False):
    """Load a race with FastF1 (no telemetry: lap timing, messages and weather are enough)."""
    import fastf1  # imported here so the OpenF1 path and the tests never need it

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(CACHE_DIR), force_renew=refresh)
    session = fastf1.get_session(year, int(event) if str(event).isdigit() else event, "R")
    session.load(laps=True, telemetry=False, weather=True, messages=True)
    return session


def load(year: int, event: str | int, *, refresh: bool = False):
    """Load one race and build it. Returns (laps, race_control, results, meta)."""
    session = open_session(year, event, refresh=refresh)
    try:
        laps = session.laps
    except Exception:  # FastF1 raises DataNotLoadedError when the download failed
        laps = None
    if laps is None or not len(laps):
        raise ValueError(f"FastF1 returned no laps for {year} {event!r}. Signed in? Run: python -m fastf1 auth f1tv")
    return build_race(session)


def _seconds(series: pd.Series) -> pd.Series:
    return series.dt.total_seconds().round(3)


def build_race(session):
    """A loaded FastF1 race session -> (laps, race_control, results, meta). Pure: no network or files.

    Reads only session.laps, .results, .race_control_messages, .weather_data, .event,
    .session_info and .date, so tests can pass a stand-in object.
    """
    results = pd.DataFrame(session.results).copy()
    results["driver_number"] = results["DriverNumber"].astype(int)
    code = dict(zip(results["driver_number"], results["Abbreviation"]))

    laps = pd.DataFrame(session.laps).copy()
    if "FastF1Generated" in laps:  # laps FastF1 invented to fill gaps, not driven laps
        laps = laps[~laps["FastF1Generated"].fillna(False).astype(bool)]
    laps = laps[laps["Time"].notna() & laps["LapNumber"].notna()].copy()  # never completed
    laps["driver_number"] = laps["DriverNumber"].astype(int)
    laps["driver"] = laps["Driver"]
    laps["lap"] = laps["LapNumber"].astype(int)

    race_start = laps.loc[laps["lap"] == 1, "LapStartTime"].min()  # session time of the start
    laps["lap_start"] = _seconds(laps["LapStartTime"] - race_start)
    laps["lap_end"] = _seconds(laps["Time"] - race_start)
    laps["lap_time"] = _seconds(laps["LapTime"])

    laps["compound"] = laps["Compound"].fillna(Compound.UNKNOWN.value)
    laps["tyre_age"] = laps["TyreLife"].fillna(0)
    laps["stint"] = laps["Stint"].fillna(0)
    laps["pit_in"] = laps["PitInTime"].notna()
    # Grid starters can carry a lap-1 PitOutTime from leaving the garage before the
    # formation lap; only a pit-lane start leaves the pits after the race has begun.
    laps["pit_out"] = laps["PitOutTime"].notna() & ((laps["lap"] > 1) | (laps["PitOutTime"] > race_start))
    laps["track_status"] = [
        worst_status(TRACK_CODES[c] for c in str(s) if c in TRACK_CODES).value if pd.notna(s) else TrackStatus.GREEN.value
        for s in laps["TrackStatus"]
    ]
    laps["source_accurate"] = laps["IsAccurate"]

    # Race control: UTC timestamps, lined up with session time on the chequered flag.
    warnings = []
    rc = pd.DataFrame(session.race_control_messages).copy()
    rc["date"] = pd.to_datetime(rc["Time"], utc=True)
    chequered = rc.loc[rc["Flag"].fillna("").str.upper() == "CHEQUERED", "date"]
    if len(chequered):
        leader_finish = laps.loc[laps["lap"] == laps["lap"].max(), "lap_end"].min()
        start_utc = chequered.min() - pd.Timedelta(seconds=float(leader_finish))
        rc["time"] = _seconds(rc["date"] - start_utc)
    else:
        rc["time"] = float("nan")
        warnings.append("no chequered flag message: race control times unknown")
    rc["lap"] = rc["Lap"].fillna(1).astype(int)
    rc["driver"] = pd.to_numeric(rc["RacingNumber"], errors="coerce").map(code)
    rc = rc.rename(columns={"Category": "category", "Flag": "flag", "Scope": "scope", "Sector": "sector", "Message": "message"})
    rc = rc[rc["category"] != "SessionStatus"]

    classified = results["ClassifiedPosition"].fillna("").astype(str)
    results["driver"] = results["Abbreviation"]
    results["position"] = pd.to_numeric(classified, errors="coerce")  # NaN unless classified
    results["laps"] = results["Laps"].astype("Int64")
    results["dnf"], results["dns"], results["dsq"] = classified.isin(DNF), classified.isin(DNS), classified.isin(DSQ)
    results["points"] = results["Points"]

    event, info = session.event, getattr(session, "session_info", None) or {}
    year = int(pd.Timestamp(event["EventDate"]).year)
    weather = session.weather_data
    meta = {
        "race_id": race_id(year, event["Location"]),
        "year": year,
        "location": event["Location"],
        "country": event["Country"],
        "circuit": info.get("Meeting", {}).get("Circuit", {}).get("ShortName") or event["Location"],
        "date": str(pd.Timestamp(session.date).date()),
        "session_key": info.get("Key"),
        "total_laps": int(results["laps"].max()) if results["laps"].notna().any() else int(laps["lap"].max()),
        "drivers": {
            r.Abbreviation: {"number": int(r.driver_number), "team": r.TeamName, "name": r.FullName}
            for r in results.sort_values("driver_number").itertuples()
        },
        "rain": bool(weather is not None and len(weather) and weather["Rainfall"].fillna(False).astype(bool).any()),
        "source": NAME,
        "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "warnings": warnings,
    }
    return finish(laps, rc, results, meta)
