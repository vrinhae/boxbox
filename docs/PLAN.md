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
- [x] `tools/jsonl_log.py`: JSONL logger (timestamp, race, lap, event type + fields; see Replay viewer)
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
def log_event(race_id: str, lap: int, event: str, *, run_id: str | None = None, **fields) -> None: ...  # writes logs/<run_id>.jsonl; event types: see Replay viewer
def read_events(path) -> list[dict]: ...
```

## Roadmap

| Week | Valarie | Aidan |
|---|---|---|
| 1 | Setup, JSONL logger, query tools | Loader, `get_state`, lookahead test |
| 2 | Replay loop (wires sim output back into snapshots) | Simulator v1, validated against real results; `get_state` merges sim laps for ego; rule-based baseline |
| 3 | Single-agent baseline | `simulate` tool; expand to 8–10 races |
| 4 | Race Engineer + Strategist (committed plan) | Telemetry Analyst |
| 5 | Event-driven routing, send-back (max 2 rounds) | Rival Modeler |
| 6 | `run_python` sandbox, ablations; replay viewer v1 | Eval harness, metrics |
| 7 | Replay viewer polish (demo), writeup | Plots, writeup |

Weeks 2+ are a draft; reassign as needed.

## Replay viewer

Streamlit app (`viz/app.py`) for debugging and the final demo. Design reference: [viewer-mockup.html](viewer-mockup.html) (made-up data; open in a browser). It **only reads `logs/*.jsonl`**: no agent or LLM calls, so replays are free and it never touches FastF1 or future data.

Screens:
- **Lap scrubber**: slider over laps; everything below updates to that lap.
- **Race order**: position, gaps, compound, tyre age for each driver at that lap.
- **Agent panel**: what triggered routing, which agents ran, their messages, send-back rounds, the final call, and the current Plan A + contingencies.
- **Strategy timeline**: stint bars coloured by compound, agent strategy vs real strategy.
- **Gap chart**: ego gap to car ahead/behind over the race, pit laps marked.
- **Compare runs**: pick two logs (e.g. multi-agent vs rule-based) for the same race.

Log events the viewer needs (`tools/jsonl_log.py` must support these from week 1):

| `event` | When | Key fields |
|---|---|---|
| `lap_state` | Once per lap, from the replay loop | positions, gaps, compounds, tyre ages, track status |
| `route` | Race Engineer picks agents | trigger(s), agents called |
| `agent_msg` | Each agent output or send-back | agent, round, content |
| `tool_call` | Every tool call / executed code | tool, args, result |
| `plan` | Strategist commits or revises | plan A, contingencies, reason |
| `decision` | Final call each lap | action (stay/box), compound |

Not in the Must tier: build v1 only once the Must items are done (end of week 5).

## Decisions log
- 2026-10-15: First race is 2023 Bahrain (dry, normal strategies).
- 2026-10-15: `LapSnapshot` is frozen and rejects records after `lap` on construction.
- 2026-10-15: Strategist uses deterministic `simulate` calls for Must tier; Monte Carlo is stretch.
- 2026-10-15: LLM calls go through OpenRouter via the `openai` SDK; model set by `PITWALL_MODEL` in `.env`.
- TODO: agent framework (own loop vs LangGraph); confirm with Aidan.
- 2026-10-15: Add a Streamlit replay viewer that reads JSONL logs only; weeks 6–7.
- 2026-10-15: One ego driver per run; all other cars replay their real race. Once the ego strategy diverges from reality, ego laps come from the sim and positions/gaps are recomputed, so from week 2 `get_state` builds snapshots from real rival data + simulated ego laps. Run 2–3 ego drivers per race; every system uses the same race/driver pairs.
