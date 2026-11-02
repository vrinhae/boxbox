# PitWall

Multi-agent LLM system that makes lap-by-lap F1 pit-stop decisions on replayed historical races (Multi-Agent Systems final project, 7 weeks, 2 people).

## Core rules
- Agents may only see data up to the current lap. Never give agents FastF1 or the full-session cache; serve pre-sliced per-lap snapshots.
- Python 3.11+, developed in WSL.

## Agents
- Telemetry Analyst: fits tire degradation, estimates pace loss + confidence, flags cliffs.
- Rival Modeler: probability each nearby rival pits soon; undercut/overcut threats.
- Strategist: keeps a committed plan (Plan A + contingencies), revises only on belief change; Monte Carlo over rival/safety-car uncertainty.
- Race Engineer: coordinator; event-driven routing (not every agent every lap), can send proposals back (max 2 rounds), makes final call. Does not execute code.

## Tools
- Simulator (sim/): lap-time model with tire deg, pit loss, rival policies.
- run_python(code): sandboxed (no network, timeout, memory cap), lap-truncated data preloaded.
- query_laps, get_race_control, simulate(strategy, rival_assumptions), shared function library.
- Log every tool call and executed code as JSONL.

## Scope tiers
- Must: replay loop, simple sim, 4 agents w/ routing + committed plan, rule-based + single-agent baselines, 8–10 test races.
- Should: code sandbox, agent negotiation, 2 ablations (fixed vs event-driven, tools vs code).
- Stretch: reactive rivals, cross-race memory, shared function library, Monte Carlo.

## Layout
data/ sim/ agents/ tools/ baselines/ eval/ notebooks/
## Plan
See docs/PLAN.md for this week's tasks, owners, interfaces, and decisions. Update it in the same PR as the work.

## Open questions
docs/PLAN.md has an "Open questions" section. At the start of a session, if any open question affects the user's area (see CLAUDE.local.md, or the owners in docs/PLAN.md) or the task they ask for, briefly raise it and ask them to decide before starting that work. When decided, move the outcome to the decisions log and delete the question.
