# NUAI-Like Velocity Candidate Research Analysis

## Summary

The current recency-weighted tournament scoring is useful, but it does not produce
a separate list of NUAI-like candidates. A separate advisory scanner is needed so
the current tournament findings, bullet recommendations, deployment decisions,
and portfolio state remain unaffected.

## Verified Boundaries

- Current live decisions flow through tournament, bullet recommender, deployment
  advisor, and portfolio mutation paths.
- Existing velocity tools are not artifact miners:
  - `tools/velocity_scanner.py` scores a single live technical setup from fresh
    Yahoo data.
  - `tools/velocity_dashboard.py` only scans `portfolio.json["velocity_watchlist"]`.
- The new scanner should read local artifacts and write only separate advisory
  outputs.
- Reporting integration into status or morning tools can happen later only as a
  clearly labeled advisory section.

## Evidence Sources

The first advisory scanner can use:

- `data/support_sweep_results.json`
- `data/sweep_support_levels.json`
- `data/resistance_sweep_results.json`
- `data/bounce_sweep_results.json`
- `data/regime_exit_sweep_results.json`
- `tickers/*/cycle_timing.json`
- `data/tournament_results.json` as context only
- `portfolio.json` as context only

`data/entry_sweep_results.json` is currently malformed and must be reported as
invalid input rather than consumed as evidence.

## Implementation Direction

Build `tools/velocity_candidate_research.py` as an advisory-only artifact miner.
It should normalize the different sweep schemas, favor 1m/3m evidence, include
cycle cadence and cycle-amplitude evidence, and write:

- `data/velocity_candidate_research.json`
- `data/velocity_candidate_research.md`

It must not modify portfolio, tournament, bullet, deployment, weekly promotion,
model-gate, or reporting files.
