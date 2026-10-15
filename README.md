# boxbox

Multi-agent LLM system that makes lap-by-lap F1 pit-stop decisions on replayed historical races. See [CLAUDE.md](CLAUDE.md) for the rules and [docs/PLAN.md](docs/PLAN.md) for tasks and owners.

## Setup

Requires Python 3.11+ (developed in WSL).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # then add your OpenRouter API key
pytest
```

If `python3 -m venv` fails with "ensurepip is not available" (common on WSL/Ubuntu), run `sudo apt install python3-venv`, or use [uv](https://docs.astral.sh/uv/): `uv venv .venv && uv pip install -e ".[dev]"`.

LLM calls go through [OpenRouter](https://openrouter.ai). Set `OPENROUTER_API_KEY` and pick a model with `PITWALL_MODEL` in `.env`.

FastF1 downloads are cached in `data/cache/` and run logs go to `logs/`; both are gitignored.

## Project Structure

```
boxbox/
├── data/          # FastF1 loader, per-lap snapshots (schema.py), cache/
├── sim/           # Race simulator and rival policies
├── agents/        # One file per agent, plus the orchestration graph
├── tools/         # Agent tools: query_laps, simulate, run_python, JSONL logging
├── baselines/     # Rule-based and single-agent baselines
├── eval/          # Run configs, metrics, and ablations
├── notebooks/     # Exploration and plots
├── tests/
└── docs/          # PLAN.md
```
