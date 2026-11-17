"""Build a race into the processed per-lap files the rest of PitWall reads.

Two sources give the same tables (see data/sources/):

    openf1  api.openf1.org, free, no login (default)
    fastf1  F1's timing archive via the fastf1 package; needs an F1 TV login
            (run `python -m fastf1 auth f1tv` once yourself)

The loader and data/sources/ are the only code that talk to either. Each race is
one folder, committed to git so nobody needs a data server again:

    data/races/<race_id>/
      laps.parquet          one row per driver per completed lap (LapRecord fields + timing)
      race_control.parquet  one row per race control message
      results.parquet       final classification: for evaluation only, never for agents
      meta.json             race info, drivers, source, and any data warnings

Raw downloads are cached under data/cache/<source>/ (gitignored).
Agents never read these files; data/state.py slices them into LapSnapshots.

    python -m data.loader 2026 Spielberg                    # build one race from OpenF1
    python -m data.loader 2026 Spielberg --source fastf1    # same race from FastF1
    python -m data.loader 2026 --survey                     # one line per race (OpenF1)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from data.sources import fastf1, openf1
from data.sources.common import LAP_COLUMNS  # noqa: F401  (re-exported for callers)

ROOT = Path(__file__).resolve().parents[1]
RACES_DIR = ROOT / "data" / "races"
SOURCES = {openf1.NAME: openf1, fastf1.NAME: fastf1}
DEFAULT_SOURCE = openf1.NAME


def write_race(laps: pd.DataFrame, rc: pd.DataFrame, results: pd.DataFrame, meta: dict,
               races_dir: Path | str = RACES_DIR) -> Path:
    out = Path(races_dir) / meta["race_id"]
    out.mkdir(parents=True, exist_ok=True)
    laps.to_parquet(out / "laps.parquet", index=False)
    rc.to_parquet(out / "race_control.parquet", index=False)
    results.to_parquet(out / "results.parquet", index=False)
    (out / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    return out


def load_race(year: int, event: str | int, *, source: str = DEFAULT_SOURCE, refresh: bool = False,
              races_dir: Path | str = RACES_DIR) -> Path:
    """Build one race from a source and write races_dir/<race_id>/. Returns the folder."""
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}; choose from {', '.join(SOURCES)}")
    return write_race(*SOURCES[source].load(year, event, refresh=refresh), races_dir=races_dir)


def read_race(race_id: str, races_dir: Path | str = RACES_DIR) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """(laps, race_control, meta) for a built race. Results are left out on purpose."""
    folder = Path(races_dir) / race_id
    if not folder.exists():
        raise FileNotFoundError(f"no race {race_id!r} in {races_dir}; build it with python -m data.loader")
    meta = json.loads((folder / "meta.json").read_text())
    return pd.read_parquet(folder / "laps.parquet"), pd.read_parquet(folder / "race_control.parquet"), meta


def main() -> None:
    p = argparse.ArgumentParser(description="Build processed race files from OpenF1 or FastF1.")
    p.add_argument("year", type=int)
    p.add_argument("event", nargs="?", help="location, country, circuit, or session key")
    p.add_argument("--source", choices=sorted(SOURCES), default=DEFAULT_SOURCE)
    p.add_argument("--out", type=Path, default=RACES_DIR, help="folder to write races into (default data/races)")
    p.add_argument("--survey", action="store_true", help="summarise every race of the season (OpenF1)")
    p.add_argument("--refresh", action="store_true", help="re-download instead of using the raw cache")
    a = p.parse_args()

    if a.survey:
        print(openf1.survey(a.year).to_string(index=False))
        return
    if not a.event:
        p.error("give an event, or --survey")
    out = load_race(a.year, a.event, source=a.source, refresh=a.refresh, races_dir=a.out)
    meta = json.loads((out / "meta.json").read_text())
    shown = out.resolve().relative_to(ROOT) if out.resolve().is_relative_to(ROOT) else out
    print(f"wrote {shown} from {meta['source']}: {meta['total_laps']} laps, {len(meta['drivers'])} drivers")
    for w in meta["warnings"]:
        print("  warning:", w)


if __name__ == "__main__":
    main()
