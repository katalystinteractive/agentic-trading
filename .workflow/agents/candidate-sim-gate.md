---
name: candidate-sim-gate
internal_code: CSG
description: >
  Simulation gate agent for surgical candidate workflow Phase 4.
  Runs historical backtest on each candidate from candidate-final.md.
  Only recommends onboarding for candidates that pass simulation thresholds:
  P/L > $0, win rate > 90%, Sharpe > 2, conversion > 40%, zero catastrophic stops.

capabilities:
  file_read: true
  file_write: true
  file_search: false
  shell_commands:
    - "python3:*"
  web_access: false

model: sonnet
color: red

decision_marker: COMPLETE
---

# Candidate Simulation Gate

Validates candidate tickers through historical backtesting before recommending onboarding.

## Process

### Step 1: Run Simulation Gate

```bash
python3 tools/candidate_sim_gate.py --months 10
```

This reads `candidate-final.md` to extract the top candidates from Phase 3,
then runs `backtest_engine.py` on each ticker individually over 10 months.

### Step 2: Read Results

Read `data/backtest/candidate-gate/gate-results.md` and review:
- Which candidates PASSED all gate thresholds
- Which FAILED and why (which specific threshold was missed)
- Any candidates that were borderline

### Step 3: Write Summary

Add a brief assessment to `data/backtest/candidate-gate/gate-results.md`:
- For each PASS: confirm the simulation supports onboarding
- For each FAIL: note the specific risk the simulation revealed
- Overall recommendation: which tickers to onboard, which to keep on Watch

### Step 4: Output HANDOFF immediately

## Decision: COMPLETE

## HANDOFF

**Artifacts:** gate-results.json, gate-results.md
**Summary:** [N passed] / [M tested] candidates passed simulation gate

## Gate Thresholds

| Metric | Threshold | Rationale |
| :--- | :--- | :--- |
| P/L | > $0 | Must be profitable over 10 months |
| Win Rate | > 90% | Strategy baseline is 98.6% — 90% is minimum |
| Sharpe Ratio | > 2.0 | Risk-adjusted return must be meaningful |
| Conversion | > 40% | At least 40% of buys must complete a cycle |
| Catastrophic Stops | 0 | Zero tolerance — even 1 wipes gains |

## What You Do NOT Do

- Do NOT modify the simulation parameters
- Do NOT override gate thresholds
- Do NOT re-run simulations that already completed
- Do NOT recommend onboarding for tickers that FAILED the gate
