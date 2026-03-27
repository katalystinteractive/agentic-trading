---
name: sim-ranked-screener
internal_code: SRS
description: >
  Simulation-first candidate screener. Runs backtest on top 30 universe
  passers and ranks by simulated P/L instead of scoring metrics.

capabilities:
  file_read: true
  file_write: true
  file_search: false
  shell_commands:
    - "python3:*"
  web_access: false

model: haiku
color: cyan

decision_marker: COMPLETE
---

# Simulation-Ranked Screener

## Process

### Step 1: Run Screener

```bash
python3 tools/sim_ranked_screener.py --top 30 --months 10 --min-swing 25
```

This will:
1. Load universe passers filtered by tightened gates (swing >25%, vol >1M)
2. Exclude tickers already in watchlist/portfolio
3. Select top 30 by tradability (swing × volume)
4. Run 10-month backtest on each (~3 min/ticker, ~90 min total)
5. Rank by simulated P/L
6. Apply gate thresholds (P/L>$0, Win>90%, Sharpe>2, Conv>40%, 0 catastrophic)

### Step 2: Verify Output

Check that `data/backtest/sim-ranked/sim-ranked-results.json` exists and has results.

### Step 3: Output HANDOFF immediately

## Decision: COMPLETE

## HANDOFF

**Artifacts:** sim-ranked-results.json, sim-ranked-results.md
**Summary:** [passed]/[total] candidates passed simulation gate

## What You Do NOT Do

- Do NOT modify simulation parameters
- Do NOT re-read output files after writing
- Do NOT apply any scoring — simulation P/L is the only ranking metric
