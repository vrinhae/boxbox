"""Load a race from OpenF1 into the processed per-lap files the rest of PitWall reads.

FastF1 now needs an F1 TV subscription for timing data, so races come from
OpenF1 (api.openf1.org, 2023 onward, no login). The loader is the only code
that talks to OpenF1. It writes one folder per race, committed to git so
nobody needs a data server again:

    data/races/<race_id>/
      laps.parquet          one row per driver per completed lap (LapRecord fields + timing)
      race_control.parquet  one row per race control message
      results.parquet       final classification: for evaluation only, never for agents
      meta.json             race info, drivers, and any data warnings

Raw API responses are cached under data/cache/openf1/ (gitignored).
Agents never read these files; data/state.py slices them into LapSnapshots.

    python -m data.loader 2026 Spielberg     # build one race
    python -m data.loader 2026 --survey      # one line per race: rain, SC/VSC, red flags, DNFs
"""

from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from data.schema import Compound, TrackStatus

API = "https://api.openf1.org/v1"
ROOT = Path(__file__).resolve().parents[1]
RACES_DIR = ROOT / "data" / "races"
RAW_DIR = ROOT / "data" / "cache" / "openf1"

ENDPOINTS = ("drivers", "laps", "stints", "pit", "race_control", "weather", "session_result")

LAP_COLUMNS = [
    "driver", "driver_number", "lap", "lap_time", "lap_start", "lap_end", "position",
    "compound", "tyre_age", "stint", "pit_in", "pit_out", "track_status", "is_accurate",
]

# Higher wins when several statuses overlap one lap.
_STATUS_RANK = {TrackStatus.GREEN: 0, TrackStatus.YELLOW: 1, TrackStatus.VSC: 2, TrackStatus.SC: 3, TrackStatus.RED: 4}


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
        want = _slug(str(event))
        hits = [s for s in sessions if want in {_slug(s[k] or "") for k in ("location", "country_name", "circuit_short_name")}]
    if len(hits) != 1:
        options = ", ".join(f"{s['location']} ({s['session_key']})" for s in sessions)
        found = "no" if not hits else "several"
        raise ValueError(f"{found} {year} races match {event!r}; use a location or session key: {options}")
    return hits[0]


def race_id_for(session: dict) -> str:
    return f"{session['year']}_{_slug(session['location'])}"


def _slug(text: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_.lower()).strip("_")


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


def build_race(raw: dict[str, list[dict]], session: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
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

    # Position at the end of lap N = order in which drivers completed lap N.
    laps["position"] = laps.groupby("lap")["lap_end"].rank(method="first").astype(int)

    # Tyres from stints.
    laps["compound"], laps["stint"], laps["tyre_age"] = Compound.UNKNOWN.value, 0, 0
    for s in raw["stints"]:
        if s["lap_start"] is None or s["lap_end"] is None:
            continue
        rows = (laps["driver_number"] == s["driver_number"]) & laps["lap"].between(s["lap_start"], s["lap_end"])
        compound = s["compound"] if s["compound"] in Compound.__members__ else Compound.UNKNOWN.value
        laps.loc[rows, "compound"] = compound
        laps.loc[rows, "stint"] = s["stint_number"]
        laps.loc[rows, "tyre_age"] = (s["tyre_age_at_start"] or 0) + laps.loc[rows, "lap"] - s["lap_start"] + 1

    pit_laps = {(p["driver_number"], p["lap_number"]) for p in raw["pit"] if p["lap_number"] is not None}
    laps["pit_in"] = [(d, n) in pit_laps for d, n in zip(laps["driver_number"], laps["lap"])]
    laps["pit_out"] = laps["is_pit_out_lap"].fillna(False).astype(bool)

    # Race control, and the worst track status seen during each lap.
    rc = pd.DataFrame(raw["race_control"], columns=["date", "lap_number", "category", "flag", "scope", "sector", "driver_number", "message"])
    rc["date"] = _ts(rc["date"])
    periods = status_periods(rc)

    def lap_status(start, end):
        worst = TrackStatus.GREEN
        for p_start, p_end, status in periods:
            if p_start < end and p_end > start and _STATUS_RANK[status] > _STATUS_RANK[worst]:
                worst = status
        return worst.value

    laps["track_status"] = [lap_status(s, e) for s, e in zip(laps["date_start"], laps["end"])]
    laps["is_accurate"] = (
        laps["lap_time"].notna() & ~laps["pit_in"] & ~laps["pit_out"] & (laps["lap"] > 1)
        & (laps["track_status"] == TrackStatus.GREEN.value)
    )
    laps["driver"] = laps["driver_number"].map(code)
    laps = laps[LAP_COLUMNS].sort_values(["lap", "position"]).reset_index(drop=True)

    rc = rc[rc["category"] != "SessionStatus"].copy()
    rc["time"] = (rc["date"] - race_start).dt.total_seconds().round(3)
    rc = rc.rename(columns={"lap_number": "lap"})
    rc["lap"] = rc["lap"].fillna(1).astype(int)
    rc["driver"] = rc["driver_number"].map(code)
    rc = rc[["lap", "time", "category", "flag", "scope", "sector", "driver", "message"]].sort_values("time").reset_index(drop=True)

    results = pd.DataFrame(raw["session_result"])
    results["driver"] = results["driver_number"].map(code)
    results = results.rename(columns={"number_of_laps": "laps"})[["driver", "driver_number", "position", "laps", "dnf", "dns", "dsq", "points"]]

    total_laps = int(results["laps"].max()) if len(results) else int(laps["lap"].max())
    meta = {
        "race_id": race_id_for(session),
        "year": session["year"],
        "location": session["location"],
        "country": session["country_name"],
        "circuit": session["circuit_short_name"],
        "date": session["date_start"][:10],
        "session_key": session["session_key"],
        "total_laps": total_laps,
        "drivers": {code[n]: {"number": n, "team": d["team_name"], "name": d["full_name"]} for n, d in sorted(drivers.items())},
        "rain": any(w.get("rainfall") for w in raw["weather"]),
        "source": "openf1",
        "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    meta["warnings"] = validate(laps, results, raw, meta)
    return laps, rc, results, meta


def validate(laps: pd.DataFrame, results: pd.DataFrame, raw: dict, meta: dict) -> list[str]:
    """Data oddities worth knowing about. Some are real race events, some are data errors."""
    warnings = []
    for driver, g in laps.groupby("driver"):
        if list(g["lap"]) != list(range(1, len(g) + 1)):
            warnings.append(f"{driver}: laps are not 1..{len(g)} without gaps")
        if (g["compound"] == Compound.UNKNOWN.value).any():
            warnings.append(f"{driver}: {int((g['compound'] == Compound.UNKNOWN.value).sum())} laps with unknown compound")
        stint_lengths = g.groupby("stint").size()
        for stint, n in stint_lengths.items():
            if n == 1 and stint < g["stint"].max():
                warnings.append(f"{driver}: stint {stint} is 1 lap long")
    if meta["rain"]:
        warnings.append("rain fell during the race (check for wet tyres)")
    for r in results.itertuples():
        done = int((laps["driver"] == r.driver).sum())
        if r.laps is not None and not pd.isna(r.laps) and done != int(r.laps):
            warnings.append(f"{r.driver}: {done} laps in timing data, {int(r.laps)} in results")
    # Final order from timing data should match the official classification for finishers.
    finishers = results[~results[["dnf", "dns", "dsq"]].any(axis=1)].dropna(subset=["position"])
    last = laps.sort_values("lap").groupby("driver").tail(1)
    order = last.sort_values(["lap", "lap_end"], ascending=[False, True])["driver"].tolist()
    official = finishers.sort_values("position")["driver"].tolist()
    ours = [d for d in order if d in official]
    if ours != official:
        # Usually post-race time penalties, which the timing data doesn't include.
        moved = [d for d, o in zip(ours, official) if d != o]
        warnings.append(f"finishing order on track differs from official results (penalties?): {', '.join(moved)}")
    return warnings


# ---------- Files ----------

def load_race(year: int, event: str | int, *, refresh: bool = False) -> Path:
    """Fetch a race from OpenF1 and write data/races/<race_id>/. Returns the folder."""
    session = find_session(year, event)
    raw = {ep: fetch(ep, session["session_key"], refresh=refresh) for ep in ENDPOINTS}
    if not raw["laps"]:
        raise ValueError(f"OpenF1 has no lap data for {race_id_for(session)} yet")
    laps, rc, results, meta = build_race(raw, session)

    out = RACES_DIR / meta["race_id"]
    out.mkdir(parents=True, exist_ok=True)
    laps.to_parquet(out / "laps.parquet", index=False)
    rc.to_parquet(out / "race_control.parquet", index=False)
    results.to_parquet(out / "results.parquet", index=False)
    (out / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    return out


def read_race(race_id: str, races_dir: Path | str = RACES_DIR) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """(laps, race_control, meta) for a built race. Results are left out on purpose."""
    folder = Path(races_dir) / race_id
    if not folder.exists():
        raise FileNotFoundError(f"no race {race_id!r} in {races_dir}; build it with python -m data.loader")
    meta = json.loads((folder / "meta.json").read_text())
    return pd.read_parquet(folder / "laps.parquet"), pd.read_parquet(folder / "race_control.parquet"), meta


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
            "race_id": race_id_for(s),
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


def main() -> None:
    p = argparse.ArgumentParser(description="Build processed race files from OpenF1.")
    p.add_argument("year", type=int)
    p.add_argument("event", nargs="?", help="location, country, circuit, or session key")
    p.add_argument("--survey", action="store_true", help="summarise every race of the season")
    p.add_argument("--refresh", action="store_true", help="re-download instead of using the raw cache")
    a = p.parse_args()

    if a.survey:
        print(survey(a.year).to_string(index=False))
        return
    if not a.event:
        p.error("give an event, or --survey")
    out = load_race(a.year, a.event, refresh=a.refresh)
    meta = json.loads((out / "meta.json").read_text())
    print(f"wrote {out.relative_to(ROOT)}: {meta['total_laps']} laps, {len(meta['drivers'])} drivers")
    for w in meta["warnings"]:
        print("  warning:", w)


if __name__ == "__main__":
    main()
