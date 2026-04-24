# agentic-trading

[![CI](https://github.com/katalystinteractive/agentic-trading/actions/workflows/ci.yml/badge.svg)](https://github.com/katalystinteractive/agentic-trading/actions/workflows/ci.yml)

Agentic research and operations workspace for the surgical mean-reversion
strategy documented in [strategy.md](strategy.md). The repo combines Python
screeners, portfolio and order-state tools, backtests, workflow definitions,
and generated trading reports.

This is an operational trading workspace. Treat `portfolio.json` and
`trade_history.json` as live state, not sample data.

## Setup

Use Python 3.10 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e '.[dev]'
```

For compatibility with older workflows, this is equivalent:

```bash
python3 -m pip install -r requirements.txt
```

To reproduce the validated direct dependency versions, install with the lock
file as a constraints file:

```bash
python3 -m pip install -e '.[dev]' -c requirements.lock
```

## Quick Checks

Run the test suite:

```bash
python3 -m pytest -q
```

Run the full local quality gate, including tool import-health checks:

```bash
make quality
```

Smoke-check representative command surfaces:

```bash
python3 tools/backtest_engine.py --help
python3 tools/bullet_recommender.py --help
python3 tools/daily_analyzer.py --help
python3 tools/portfolio_manager.py --help
```

Many tools fetch live market data through `yfinance`. Network-backed commands
can fail or vary when providers throttle, return empty data, or change schemas.
The tests mock the most important network-sensitive paths where practical.

## Project Layout

- `tools/` - Python tools for screening, portfolio operations, backtesting, reporting, and workflow support.
- `tests/` - Unit and regression tests.
- `workflows/` - YAML workflow definitions for the agent/workflow runner.
- `.workflow/agents/` - Agent instructions used by the workflow definitions.
- `.workflow/skills/` - Local workflow skills.
- `plans/` - Backlog, analysis notes, and implementation plans.
- `docs/` - Operator and source-control documentation.
- `docs/neural-graph-policy.md` - Contract for live policy weights versus
  diagnostic-only learned support signals.
- `templates/state/` - Bootstrap templates for local portfolio/trade state.
- `tickers/` - Per-ticker memory plus generated ticker analysis artifacts.
- `data/` - Runtime data, caches, sweep outputs, and backtest artifacts.
- `portfolio.json` and `trade_history.json` - Current operational state.

## Strategy Map

Core strategy context lives in [strategy.md](strategy.md). At a high level:

- `bullet_recommender.py` converts wick/support analysis into deployable buy levels.
- `portfolio_manager.py` is the only supported writer for portfolio and trade state.
- `daily_analyzer.py` is the consolidated daily operations surface.
- `weekly_reoptimize.py` refreshes sweep results, clustering, weights, and tournament inputs.
- `backtest_engine.py`, `candidate_sim_gate.py`, and related reporters validate strategy edges.
- Workflow YAML files compose the tools into morning, status, candidate, backtest, and review runs.

The `neural_*` tools implement a learned graph policy, not a trained neural
network. See [docs/neural-graph-policy.md](docs/neural-graph-policy.md) for the
contract between deterministic gates, swept parameters, learned live weights,
diagnostic-only weights, and generated artifacts.

## State Files

Live state:

- `portfolio.json` - positions, pending orders, watchlist, capital pools, and order metadata.
- `trade_history.json` - append-style trade ledger used for reconciliation and drift reports.

Bootstrap templates:

```bash
cp templates/state/portfolio.template.json portfolio.json
cp templates/state/trade_history.template.json trade_history.json
```

Only use the template copy commands for a fresh clone or throwaway sandbox. Do
not overwrite live state with templates.

Safety behavior in `portfolio_manager.py`:

- validates portfolio and trade-history shape before saving
- writes via atomic temp-file replace
- creates timestamped backups before overwrite
- uses `.portfolio.lock` for advisory mutation locking
- renames corrupt JSON aside instead of silently discarding it

## Command Safety

Read-only or reporting commands:

```bash
python3 tools/bullet_recommender.py TICKER
python3 tools/bullet_recommender.py TICKER --mode audit
python3 tools/backtest_engine.py --help
python3 tools/backtest_reporter.py --help
python3 tools/candidate_sim_gate.py --help
python3 tools/order_proximity_monitor.py --dry-run
python3 tools/weekly_reoptimize.py --dry-run
```

Commands that write generated reports or caches, but should not mutate live
portfolio/trade state:

```bash
python3 tools/portfolio_status.py
python3 tools/daily_analyzer.py --no-deploy --no-perf --no-fitness --no-screen --no-recon
python3 tools/backtest_engine.py --data-dir data/backtest/latest --execution-stress
```

Portfolio-mutating commands. Use these for confirmed broker actions:

```bash
python3 tools/portfolio_manager.py fill TICKER --price 10.00 --shares 3
python3 tools/portfolio_manager.py sell TICKER --price 11.00 --shares 3
python3 tools/portfolio_manager.py order TICKER --type BUY --price 9.50 --shares 2 --note "A1"
python3 tools/portfolio_manager.py place TICKER --price 9.50
python3 tools/portfolio_manager.py cancel TICKER --price 9.50
python3 tools/portfolio_manager.py unpause TICKER
python3 tools/portfolio_manager.py watch TICKER
python3 tools/portfolio_manager.py unwatch TICKER
```

Batch fill/sell entry also mutates state through the same transaction APIs:

```bash
python3 tools/daily_analyzer.py --fills "CIFR:14.18:8" --sells "LUNR:18.89:2"
python3 tools/daily_analyzer.py --fills "CIFR:14.18:8:2026-03-26"
```

Auto-fill recording in `order_proximity_monitor.py` is disabled by default. Only
use `--enable-auto-fill` after broker verification.

## Daily Workflow

1. Inspect market and portfolio state.

```bash
python3 tools/daily_analyzer.py --no-deploy
```

2. Verify any broker fills or sells before recording them.

```bash
python3 tools/portfolio_manager.py fill TICKER --price PRICE --shares SHARES
python3 tools/portfolio_manager.py sell TICKER --price PRICE --shares SHARES
```

3. Review next deployable orders for one or more tickers.

```bash
python3 tools/bullet_recommender.py TICKER
python3 tools/bullet_recommender.py TICKER --mode audit
```

4. Monitor placed orders without sending emails or recording auto-fills.

```bash
python3 tools/order_proximity_monitor.py --dry-run
```

5. If using workflow orchestration, the morning and status flows are defined in:

- [workflows/morning-briefing-workflow.yaml](workflows/morning-briefing-workflow.yaml)
- [workflows/status-workflow.yaml](workflows/status-workflow.yaml)

## Weekly Workflow

The weekly optimizer is designed for Saturday maintenance and can be run in
dry-run mode first:

```bash
python3 tools/weekly_reoptimize.py --dry-run
python3 tools/weekly_reoptimize.py --no-email
```

The script documents the cron form in its module docstring:

```cron
0 6 * * 6 cd /Users/kamenkamenov/agentic-trading && python3 tools/weekly_reoptimize.py >> data/reoptimize.log 2>&1
```

Candidate and watchlist review workflows:

- [workflows/sim-ranked-candidate-workflow.yaml](workflows/sim-ranked-candidate-workflow.yaml)
- [workflows/watchlist-fitness-workflow.yaml](workflows/watchlist-fitness-workflow.yaml)
- [workflows/deep-dive-workflow.yaml](workflows/deep-dive-workflow.yaml)

Backtest workflows:

- [workflows/backtest-surgical-workflow.yaml](workflows/backtest-surgical-workflow.yaml)
- [workflows/backtest-dip-workflow.yaml](workflows/backtest-dip-workflow.yaml)

## Backtesting

Collected backtest datasets live under `data/backtest/` and are generated
artifacts. A surgical backtest run expects a Phase 1 data directory:

```bash
python3 tools/backtest_engine.py --data-dir data/backtest/latest --execution-stress
python3 tools/backtest_reporter.py --data-dir data/backtest/latest
```

`--execution-stress` writes `execution_stress.json` comparing optimistic,
conservative, and no-same-day-exit execution assumptions. Candidate gates use
conservative same-day execution assumptions for pass/fail decisions.

## Emergency Procedures

Corrupt `portfolio.json` or `trade_history.json`:

1. Stop scheduled jobs that could write state.
2. Inspect the latest timestamped backup next to the affected file.
3. Validate JSON before restoring:

```bash
python3 -m json.tool portfolio.json
python3 -m json.tool trade_history.json
```

4. Restore from the latest known-good backup only after preserving the corrupt file for inspection.

Failed or stuck cron run:

1. Check the relevant generated log, usually under `data/`.
2. Check for a currently running process before starting another write-heavy job:

```bash
ps -ax | rg "weekly_reoptimize|daily_analyzer|portfolio_manager|order_proximity_monitor"
```

3. Re-run with `--dry-run`, `--skip-download`, or `--no-email` where supported.

Stale lock concern:

- `.portfolio.lock` is an advisory lock file. Its existence alone does not mean
  the portfolio is locked.
- First check for an active writer process.
- Do not delete the lock file as the first recovery step.

Yfinance/provider failure:

- Re-run later or use cached-data flags where available.
- Treat missing prices, stale prices, or empty history as a data-quality failure, not a trading signal.
- Prefer `--dry-run` until provider data looks normal again.

Test failure:

```bash
python3 -m pytest -q
python3 -m pytest tests/path_to_failing_test.py -q
```

Keep the suite green before trusting live workflow output.

## Generated Artifacts

Safe to delete/regenerate when not needed for an active investigation:

- generated root-level reports such as `morning-briefing*.md`, `status-*.md`, and candidate reports
- `.workflow-state/`
- `morning-work/`
- `data/backtest/`
- sweep/cache outputs under `data/`
- generated ticker files such as `tickers/*/wick_analysis.md` and `tickers/*/cycle_timing.json`

Keep tracked source, docs, workflow definitions, tests, templates, and durable
ticker `identity.md` / `memory.md` files unless you intentionally change them.

The detailed tracking policy is in [docs/source-control-policy.md](docs/source-control-policy.md).

## Source Control

Generated runtime artifacts are ignored by `.gitignore` where possible. Some
legacy generated artifacts were previously tracked and have been removed from
the index while preserved locally.

Before reviewing or committing changes:

```bash
git status --short
git ls-files -ci --exclude-standard
python3 -m pytest -q
```

`git ls-files -ci --exclude-standard` should return no tracked files that now
match ignore rules.
