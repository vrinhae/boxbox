# PitWall plan

Owners: **Valarie**, **Aidan**. Update this file in the same PR as the work it describes.

## Current week: Week 1

### Aidan: data layer
- [ ] `data/loader.py`: load the first 2026 race (see decisions log) from OpenF1, clean it, save per-lap parquet to `data/races/<race_id>/` (committed; `data/cache/` holds raw downloads and stays gitignored)
- [ ] `data/state.py`: `get_state(race_id, lap, ego_driver) -> LapSnapshot`
- [ ] `tests/test_no_lookahead.py`: snapshot at lap N contains nothing after lap N
- [ ] Notebook: lap time vs tyre age per compound (inputs for the week 2 sim fit)

Done when `get_state("2026_<race>", 20, "VER")` returns a correct snapshot and the test passes.

### Valarie: setup + plumbing
- [x] `pyproject.toml` (Python 3.11+, fastf1, pandas, pyarrow, pytest, LLM SDK + framework), setup steps in README
- [x] `.gitignore` entry for `data/cache/` and `logs/`
- [x] `tools/jsonl_log.py`: JSONL logger (timestamp, race, lap, event type + fields; see Replay viewer)
- [x] `tools/query.py`: `query_laps`, `get_race_control`, built against a hand-made fake `LapSnapshot`
- [x] One LLM call that uses a tool, logged to JSONL (`python -m agents.ask "..."`)

Done when an LLM calls `query_laps` on the fake snapshot and the call appears in the log.

### End of week, together
- [ ] Swap the fake snapshot for `get_state`; LLM answers "what tyres is VER on at lap 20?" from real data

## Interfaces

Shared contract: `data/schema.py` (`LapSnapshot`). Changes to it get their own small PR reviewed by both.

```python
# data/state.py (Aidan)
def get_state(race_id: str, lap: int, ego_driver: str) -> LapSnapshot: ...

# tools/query.py (Valarie): take a snapshot, never touch raw race data or the cache
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

## Open questions

Raised but not decided. Decide together, then move the outcome to the decisions log and delete the question here.

### Q2. Loader should take any race (Aidan; #2)
We want a historical library to browse old races, not just one test race. Write the loader as e.g. `load_race(year, event)` rather than hard-coding Bahrain. No extra work if done from the start.

### Q5. Viewer race picker (Valarie, week 6)
The viewer only shows races that have been run (it reads `logs/`), so it needs dropdowns for race, driver and system built from the log files. The mockup is missing this. Races are run from the terminal, e.g. `python -m eval.run --race 2026_austin --driver LEC --system multi_agent`.

## Decisions log
- 2026-10-15: ~~First race is 2023 Bahrain~~ (replaced 2026-11-06: post-cutoff 2026 races, see below).
- 2026-10-15: `LapSnapshot` is frozen and rejects records after `lap` on construction.
- 2026-10-15: Strategist uses deterministic `simulate` calls for Must tier; Monte Carlo is stretch.
- 2026-10-15: LLM calls go through OpenRouter via the `openai` SDK; model set by `PITWALL_MODEL` in `.env`.
- 2026-10-15: Add a Streamlit replay viewer that reads JSONL logs only; weeks 6–7.
- 2026-10-15: One ego driver per run; all other cars replay their real race. Once the ego strategy diverges from reality, ego laps come from the sim and positions/gaps are recomputed, so from week 2 `get_state` builds snapshots from real rival data + simulated ego laps. Run 2–3 ego drivers per race; every system uses the same race/driver pairs.
- 2026-11-18: Race data comes from OpenF1 (#16), built by `python -m data.loader <year> <event>` into `data/races/<race_id>/`, which is committed so nobody needs a data server again (campus, grading, demo day). FastF1 3.9 needs an F1 TV subscription for all timing data (that was the HTTP 401, not the Wi-Fi). Valarie has F1 TV, so FastF1 builds (`--source fastf1`) are used locally to validate new races but never committed, since the repo is public. On 2026 Spielberg the two sources matched on every lap, position, tyre and stint; FastF1 additionally caught 3 pit-lane visits without a tyre change and VSC laps up to the green flag.
- 2026-11-06: Evaluate only on races after the training cutoff of the model we evaluate with (#18). LLMs may remember earlier races from training data, which the no-lookahead rule can't block. Newer models can have cutoffs well into 2026, so in practice that means late-2026 races; record the evaluation model and its cutoff here once chosen. Development model `openai/gpt-4o-mini` (cutoff around late 2023) can use any 2026 race. First development race: a clean dry 2026 race (Aidan picks; not Austin, whose data has a 1-lap stint on lap 1 and a DNF). Older races are fine for browsing in the library. Stretch: measure LLM memory by comparing old races, old races with names hidden, and 2026 races.
- 2026-11-06: Agent framework is our own loop (#10): plain Python over the `openai` SDK, growing from `agents/ask.py`. No LangGraph.
- TODO: evaluation model and its training cutoff (decides which 2026 races are eligible).
