# Source Control Policy

This repository contains code, strategy documentation, live trading state, and
large generated artifacts. Keep those categories separate so operational runs do
not bury source changes in generated diffs.

## Track

- Python source in `tools/`
- Tests in `tests/`
- Workflow and agent definitions in `workflows/` and `.workflow/`
- Strategy and durable planning docs
- State templates in `templates/state/`
- Durable ticker knowledge: `tickers/<TICKER>/identity.md` and `memory.md`

## Ignore

- Runtime workflow state in `.workflow-state/`
- Python packaging/test artifacts: `.venv/`, `.pytest_cache/`, `*.egg-info/`
- Backtest and simulation outputs in `data/backtest/` and `dip-sim-results/`
- Sweep outputs, logs, caches, and transient pools under `data/`
- Generated ticker analysis such as `wick_analysis.md` and `cycle_timing.json`
- Portfolio and trade history backups
- Generated root-level reports from daily/weekly workflows

## Live State

`portfolio.json` and `trade_history.json` are still tracked for the current
workflow, but templates now exist at:

- `templates/state/portfolio.template.json`
- `templates/state/trade_history.template.json`

A later migration should move live state to a local ignored state area or keep
tracking it intentionally with a documented commit cadence. Do not remove live
state from git history without first deciding how restores, backups, and
operator handoff should work.

## Legacy Tracked Artifacts

`.gitignore` does not hide files that are already tracked. Existing generated
artifacts currently tracked in git need a separate index cleanup using
`git rm --cached` after the policy is reviewed. Until then, this policy prevents
new untracked generated outputs from expanding the problem.
