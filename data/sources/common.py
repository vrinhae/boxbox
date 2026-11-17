"""What every data source shares: the output tables, how they are finished, and the data checks.

A source turns one race into four things:

    laps          one row per driver per completed lap, LAP_COLUMNS
    race_control  one row per race control message, RC_COLUMNS
    results       final classification (evaluation only), RESULT_COLUMNS
    meta          dict: race info, drivers, source, warnings

Each source fills the per-lap facts it knows (times, tyres, pits, track status) and
then calls finish(), which derives the columns that must mean the same thing whatever
the source: position, is_accurate, column order and the warnings.
"""

from __future__ import annotations

import re
import unicodedata

import pandas as pd

from data.schema import Compound, TrackStatus

LAP_COLUMNS = [
    "driver", "driver_number", "lap", "lap_time", "lap_start", "lap_end", "position",
    "compound", "tyre_age", "stint", "pit_in", "pit_out", "track_status", "is_accurate",
]
RC_COLUMNS = ["lap", "time", "category", "flag", "scope", "sector", "driver", "message"]
RESULT_COLUMNS = ["driver", "driver_number", "position", "laps", "dnf", "dns", "dsq", "points"]

# Higher wins when several statuses overlap one lap.
STATUS_RANK = {TrackStatus.GREEN: 0, TrackStatus.YELLOW: 1, TrackStatus.VSC: 2, TrackStatus.SC: 3, TrackStatus.RED: 4}


def worst_status(statuses) -> TrackStatus:
    return max(statuses, key=STATUS_RANK.__getitem__, default=TrackStatus.GREEN)


def slug(text: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_.lower()).strip("_")


def race_id(year: int, location: str) -> str:
    """Same id whichever source built the race, e.g. 2026_spielberg."""
    return f"{year}_{slug(location)}"


def finish(laps: pd.DataFrame, rc: pd.DataFrame, results: pd.DataFrame, meta: dict):
    """Derive the shared columns and checks. Returns (laps, race_control, results, meta).

    laps needs every LAP_COLUMNS column except position and is_accurate, and may carry
    source_accurate (False where the source itself distrusts a lap's timing).
    Times (lap_start, lap_end, rc time) are seconds from the start of lap 1.
    """
    laps = laps.copy()
    known = set(Compound.__members__)
    laps["compound"] = [c if c in known else Compound.UNKNOWN.value for c in laps["compound"]]
    for col in ("lap", "driver_number", "stint", "tyre_age"):
        laps[col] = laps[col].astype(int)
    for col in ("pit_in", "pit_out"):
        laps[col] = laps[col].astype(bool)
    laps["lap_time"] = laps["lap_time"].astype(float)

    # Position at the end of lap N = order in which drivers completed lap N.
    laps["position"] = laps.groupby("lap")["lap_end"].rank(method="first").astype(int)

    source_ok = laps["source_accurate"].fillna(False).astype(bool) if "source_accurate" in laps else True
    laps["is_accurate"] = (
        laps["lap_time"].notna() & ~laps["pit_in"] & ~laps["pit_out"] & (laps["lap"] > 1)
        & (laps["track_status"] == TrackStatus.GREEN.value) & source_ok
    )
    laps = laps[LAP_COLUMNS].sort_values(["lap", "position"]).reset_index(drop=True)
    rc = rc[RC_COLUMNS].sort_values("time", kind="stable").reset_index(drop=True)
    results = results[RESULT_COLUMNS].reset_index(drop=True)

    meta = {**meta, "warnings": meta.get("warnings", []) + validate(laps, results, meta)}
    return laps, rc, results, meta


def validate(laps: pd.DataFrame, results: pd.DataFrame, meta: dict) -> list[str]:
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
