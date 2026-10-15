# PitWall plan

Owners: **Valarie**, **Aidan**. Update this file in the same PR as the work it describes.

## Current week: Week 1

### Aidan: data layer
- [ ] `data/loader.py`: load 2023 Bahrain with FastF1, clean it, save per-lap parquet to `data/cache/`
- [ ] `data/state.py`: `get_state(race_id, lap, ego_driver) -> LapSnapshot`
- [ ] `tests/test_no_lookahead.py`: snapshot at lap N contains nothing after lap N
- [ ] Notebook: lap time vs tyre age per compound (inputs for the week 2 sim fit)

Done when `get_state("2023_bahrain", 20, "VER")` returns a correct snapshot and the test passes.

### Valarie: setup + plumbing
- [x] `pyproject.toml` (Python 3.11+, fastf1, pandas, pyarrow, pytest, LLM SDK + framework), setup steps in README
- [x] `.gitignore` entry for `data/cache/` and `logs/`
- [ ] `tools/jsonl_log.py`: JSONL logger (timestamp, race, lap, agent, tool, args, result)
- [ ] `tools/query.py`: `query_laps`, `get_race_control`, built against a hand-made fake `LapSnapshot`
- [ ] One LLM call that uses a tool, logged to JSONL

Done when an LLM calls `query_laps` on the fake snapshot and the call appears in the log.

### End of week, together
- [ ] Swap the fake snapshot for `get_state`; LLM answers "what tyres is VER on at lap 20?" from real data

## Interfaces

Shared contract: `data/schema.py` (`LapSnapshot`). Changes to it get their own small PR reviewed by both.

```python
# data/state.py (Aidan)
def get_state(race_id: str, lap: int, ego_driver: str) -> LapSnapshot: ...

# tools/query.py (Valarie): take a snapshot, never touch FastF1 or the cache
def query_laps(snap: LapSnapshot, driver: str | None = None, last_n: int | None = None) -> list[dict]: ...
def get_race_control(snap: LapSnapshot) -> list[dict]: ...

# tools/jsonl_log.py (Valarie)
def log_event(race_id: str, lap: int, agent: str, tool: str, args: dict, result: object) -> None: ...
```

## Roadmap

| Week | Valarie | Aidan |
|---|---|---|
| 1 | Setup, JSONL logger, query tools | Loader, `get_state`, lookahead test |
| 2 | Replay loop | Simulator v1, validated against real results; rule-based baseline |
| 3 | Single-agent baseline | `simulate` tool; expand to 8–10 races |
| 4 | Race Engineer + Strategist (committed plan) | Telemetry Analyst |
| 5 | Event-driven routing, send-back (max 2 rounds) | Rival Modeler |
| 6 | `run_python` sandbox, ablations | Eval harness, metrics |
| 7 | Writeup | Plots, writeup |

Weeks 2+ are a draft; reassign as needed.

## Decisions log
- 2026-10-15: First race is 2023 Bahrain (dry, normal strategies).
- 2026-10-15: `LapSnapshot` is frozen and rejects records after `lap` on construction.
- 2026-10-15: Strategist uses deterministic `simulate` calls for Must tier; Monte Carlo is stretch.
- 2026-10-15: LLM calls go through OpenRouter via the `openai` SDK; model set by `PITWALL_MODEL` in `.env`.
- TODO: agent framework (own loop vs LangGraph); confirm with Aidan.
