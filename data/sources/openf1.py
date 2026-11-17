"""OpenF1 source: api.openf1.org, 2023 onward, free, no login.

OpenF1 serves raw events per endpoint, so this module derives the per-lap columns
itself: lap end times, tyres from stint ranges, pits from the pit endpoint, and
track status from race control messages. Raw responses are cached as JSON under
data/cache/openf1/<session_key>/ (gitignored).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from data.schema import Compound, TrackStatus
from data.sources.common import finish, race_id, slug, worst_status

NAME = "openf1"
API = "https://api.openf1.org/v1"
RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "cache" / "openf1"
ENDPOINTS = ("drivers", "laps", "stints", "pit", "race_control", "weather", "session_result")


# ---------- Fetching ----------

def _get(endpoint: str, **params) -> list[dict]:
    url = f"{API}/{endpoint}?{urllib.parse.urlencode(params)}"
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:  # OpenF1 answers 404 when nothing matches
                return []
            if e.code != 429 or attempt == 4:
                raise
        time.sleep(2 ** attempt)  # rate limited: back off and retry
    raise RuntimeError("unreachable")


def fetch(endpoint: str, session_key: int, *, refresh: bool = False) -> list[dict]:
    """One OpenF1 endpoint for one session, cached as raw JSON."""
    path = RAW_DIR / str(session_key) / f"{endpoint}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    data = _get(endpoint, session_key=session_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    time.sleep(0.4)  # stay well under OpenF1's free rate limit
    return data


def race_sessions(year: int) -> list[dict]:
    """All race sessions of a season that actually ran."""
    return [s for s in _get("sessions", year=year, session_name="Race") if not s.get("is_cancelled")]


def find_session(year: int, event: str | int, sessions: list[dict] | None = None) -> dict:
    """Match a race by session key, location, country or circuit name (case and accents ignored)."""
    sessions = race_sessions(year) if sessions is None else sessions
    if isinstance(event, int) or str(event).isdigit():
        hits = [s for s in sessions if s["session_key"] == int(event)]
    else:
        want = slug(str(event))
        hits = [s for s in sessions if want in {slug(s[k] or "") for k in ("location", "country_name", "circuit_short_name")}]
    if len(hits) != 1:
        options = ", ".join(f"{s['location']} ({s['session_key']})" for s in sessions)
        found = "no" if not hits else "several"
        raise ValueError(f"{found} {year} races match {event!r}; use a location or session key: {options}")
    return hits[0]


def load(year: int, event: str | int, *, refresh: bool = False):
    """Fetch one race and build it. Returns (laps, race_control, results, meta)."""
    session = find_session(year, event)
    raw = {ep: fetch(ep, session["session_key"], refresh=refresh) for ep in ENDPOINTS}
    if not raw["laps"]:
        raise ValueError(f"OpenF1 has no lap data for {race_id(year, session['location'])} yet")
    return build_race(raw, session)


# ---------- Building ----------

def _ts(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, format="ISO8601")


def status_periods(race_control: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.Timestamp, TrackStatus]]:
    """Turn race control messages into (start, end, status) periods.

    SC runs from deployment to the next track-wide green or "TRACK CLEAR";
    VSC from deployment to "VSC ENDING"; red flags to the next green.
    Sector yellows run until that sector is cleared (or the whole track is).
    """
    periods = []
    open_: dict[str, tuple[pd.Timestamp, TrackStatus]] = {}  # key -> (start, status)
    end_of_race = race_control["date"].max() if len(race_control) else pd.Timestamp.now(tz="UTC")

    def close(key, at):
        if key in open_:
            start, status = open_.pop(key)
            periods.append((start, at, status))

    text = race_control[["category", "flag", "scope", "message"]].fillna("")
    for m in race_control.assign(**text).sort_values("date").itertuples():
        msg, flag, at = m.message.upper(), m.flag.upper(), m.date
        track_wide = m.scope == "Track"
        if m.category == "SafetyCar":
            if "VIRTUAL" in msg or msg.startswith("VSC"):
                if "DEPLOYED" in msg:
                    open_.setdefault("vsc", (at, TrackStatus.VSC))
                elif "ENDING" in msg:
                    close("vsc", at)
            elif "DEPLOYED" in msg:
                open_.setdefault("sc", (at, TrackStatus.SC))
        elif flag == "RED":
            open_.setdefault("red", (at, TrackStatus.RED))
        elif flag in ("YELLOW", "DOUBLE YELLOW") and m.scope == "Sector":
            open_.setdefault(f"sector{m.sector}", (at, TrackStatus.YELLOW))
        elif flag == "CLEAR" and m.scope == "Sector":
            close(f"sector{m.sector}", at)
        if (flag in ("GREEN", "CLEAR") and track_wide) or msg == "TRACK CLEAR":
            for key in [k for k in open_ if k != "vsc"]:
                close(key, at)
        if flag == "CHEQUERED":
            for key in list(open_):
                close(key, at)
    for key in list(open_):
        close(key, end_of_race)
    return periods


def build_race(raw: dict[str, list[dict]], session: dict):
    """Raw OpenF1 responses -> (laps, race_control, results, meta). Pure: no network or files."""
    drivers = {d["driver_number"]: d for d in raw["drivers"]}
    code = {n: d["name_acronym"] for n, d in drivers.items()}

    laps = pd.DataFrame(raw["laps"])[["driver_number", "lap_number", "date_start", "lap_duration", "is_pit_out_lap"]]
    laps = laps[laps["driver_number"].isin(code)].rename(columns={"lap_number": "lap"})
    laps["date_start"] = _ts(laps["date_start"])
    laps = laps.sort_values(["driver_number", "lap"]).reset_index(drop=True)

    # A lap ends when the next one starts; the last lap ends after its duration.
    # A lap with neither was never completed (the driver retired on it), so it is dropped.
    next_start = laps.groupby("driver_number")["date_start"].shift(-1)
    by_duration = laps["date_start"] + pd.to_timedelta(laps["lap_duration"], unit="s")
    laps["end"] = next_start.fillna(by_duration)
    laps = laps[laps["end"].notna()].copy()
    laps["lap_time"] = (laps["end"] - laps["date_start"]).dt.total_seconds().round(3)
    laps.loc[laps["lap_duration"].isna() & next_start.notna(), "lap_time"] = None  # no official time for this lap

    race_start = laps.loc[laps["lap"] == 1, "date_start"].min()
    laps["lap_start"] = (laps["date_start"] - race_start).dt.total_seconds().round(3)
    laps["lap_end"] = (laps["end"] - race_start).dt.total_seconds().round(3)

    # Tyres from stints.
    laps["compound"], laps["stint"], laps["tyre_age"] = Compound.UNKNOWN.value, 0, 0
    for s in raw["stints"]:
        if s["lap_start"] is None or s["lap_end"] is None:
            continue
        rows = (laps["driver_number"] == s["driver_number"]) & laps["lap"].between(s["lap_start"], s["lap_end"])
        laps.loc[rows, "compound"] = s["compound"]
        laps.loc[rows, "stint"] = s["stint_number"]
        laps.loc[rows, "tyre_age"] = (s["tyre_age_at_start"] or 0) + laps.loc[rows, "lap"] - s["lap_start"] + 1

    pit_laps = {(p["driver_number"], p["lap_number"]) for p in raw["pit"] if p["lap_number"] is not None}
    laps["pit_in"] = [(d, n) in pit_laps for d, n in zip(laps["driver_number"], laps["lap"])]
    laps["pit_out"] = laps["is_pit_out_lap"].fillna(False).astype(bool)

    # Race control, and the worst track status seen during each lap.
    rc = pd.DataFrame(raw["race_control"], columns=["date", "lap_number", "category", "flag", "scope", "sector", "driver_number", "message"])
    rc["date"] = _ts(rc["date"])
    periods = status_periods(rc)
    laps["track_status"] = [
        worst_status(status for p_start, p_end, status in periods if p_start < end and p_end > start).value
        for start, end in zip(laps["date_start"], laps["end"])
    ]
    laps["driver"] = laps["driver_number"].map(code)

    rc = rc[rc["category"] != "SessionStatus"].copy()
    rc["time"] = (rc["date"] - race_start).dt.total_seconds().round(3)
    rc = rc.rename(columns={"lap_number": "lap"})
    rc["lap"] = rc["lap"].fillna(1).astype(int)
    rc["driver"] = rc["driver_number"].map(code)

    results = pd.DataFrame(raw["session_result"])
    results["driver"] = results["driver_number"].map(code)
    results = results.rename(columns={"number_of_laps": "laps"})

    total_laps = int(results["laps"].max()) if len(results) else int(laps["lap"].max())
    meta = {
        "race_id": race_id(session["year"], session["location"]),
        "year": session["year"],
        "location": session["location"],
        "country": session["country_name"],
        "circuit": session["circuit_short_name"],
        "date": session["date_start"][:10],
        "session_key": session["session_key"],
        "total_laps": total_laps,
        "drivers": {code[n]: {"number": n, "team": d["team_name"], "name": d["full_name"]} for n, d in sorted(drivers.items())},
        "rain": any(w.get("rainfall") for w in raw["weather"]),
        "source": NAME,
        "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    return finish(laps, rc, results, meta)


# ---------- Season overview ----------

def survey(year: int) -> pd.DataFrame:
    """One row per race of a season, to pick clean dry races for development."""
    rows = []
    for s in race_sessions(year):
        key = s["session_key"]
        rc = fetch("race_control", key)
        if not rc:
            continue  # not run yet, or no data
        results = fetch("session_result", key)
        messages = [(m.get("message") or "").upper() for m in rc]
        rows.append({
            "race_id": race_id(year, s["location"]),
            "date": s["date_start"][:10],
            "laps": max((r.get("number_of_laps") or 0 for r in results), default=0),
            "rain": any(w.get("rainfall") for w in fetch("weather", key)),
            "sc": sum("SAFETY CAR DEPLOYED" in m and "VIRTUAL" not in m for m in messages),
            "vsc": sum(("VSC DEPLOYED" in m or "VIRTUAL SAFETY CAR DEPLOYED" in m) for m in messages),
            "red": sum((m.get("flag") or "") == "RED" for m in rc),
            "dnf": sum(bool(r.get("dnf") or r.get("dns")) for r in results),
            "stops": len(fetch("pit", key)),
        })
    return pd.DataFrame(rows)
