# Hallucination Risk Audit — 2026-03-28

## Purpose
Every point where LLM judgment produces data, calculations, or directions
that could be fabricated. Each must be replaced with a Python script.

## Status: 7 CRITICAL, 9 MEDIUM, 5 LOW (acknowledged)

---

## CRITICAL (Affect Real Money)

### C1. Projected Sell Levels — LLM Math
- **Where:** active-ticker-analyst.md line 185-188
- **Fix:** Pre-compute in morning_splitter.py from portfolio.json
- **Status:** TODO

### C2. 16-Rule Verdict Logic — LLM Evaluation
- **Where:** active-ticker-analyst.md lines 36-108
- **Fix:** Pre-compute verdicts in morning_splitter.py, inject suggested_verdict
- **Status:** TODO

### C3. Momentum Classification — LLM Interpretation
- **Where:** active-ticker-analyst.md lines 57-60
- **Fix:** classify_momentum() in morning_splitter.py from RSI/MACD
- **Status:** TODO

### C4. Entry Gate Computation — LLM Logic
- **Where:** active-ticker-analyst.md lines 110-125
- **Fix:** Pre-compute gates in morning_splitter.py
- **Status:** TODO

### C5. Knowledge Belief Classification — LLM Judgment
- **Where:** knowledge-analyst.md lines 37-55
- **Fix:** Rule-based in knowledge_consolidator.py (3+ breaks = STRUCTURAL)
- **Status:** TODO

### C6. Candidate Score Adjustments — LLM +/-20
- **Where:** surgical-evaluator/verifier/critic agents
- **Fix:** Replace with deterministic factors (pattern quality, sub-sector overlap)
- **Status:** PARTIALLY DONE (sim-ranked workflow replaces scoring entirely)

### C7. Monthly Cycle Timing — LLM Determination
- **Where:** deep-dive-analyst.md lines 63-66
- **Fix:** Compute in deep_dive_pre_analyst.py from wick timestamps
- **Status:** TODO

---

## MEDIUM (Affect Analysis Quality)

### M1. Sell-Side Advisory — LLM Narrative
- Fix: Pre-compute triggers in morning_splitter.py

### M2. News Earnings Imminence — LLM Date Parsing
- Fix: Use earnings_analyzer.py structured data instead

### M3. Cycle Timing Cooldown Override — LLM Judgment
- Fix: Encode override conditions in cycle_timing_analyzer.py

### M4. Watchlist Fitness Verdict Override — LLM Judgment
- Fix: Encode in watchlist_fitness.py as deterministic rules

### M5. Dip Sim Qualitative Summary — LLM Narrative
- Fix: Add statistical analysis to dip_sim_analyzer.py

### M6. Candidate Sim Gate Assessment — LLM Interpretation
- Fix: Structured failure reasons from candidate_sim_gate.py

### M7. Exit Review Rule 3 Override — LLM Thesis Evaluation
- Fix: Structured signal detection in exit_review_pre_analyst.py

### M8. Universe Cache 7-Day Staleness
- Fix: Per-ticker timestamps, 3-day refresh, or fresh validation (DONE for sim_ranked_screener)

### M9. Sector Registry Hardcoded Map Staleness
- Fix: Periodic cross-check script against yfinance

---

## LOW (Cosmetic — Acknowledged)

L1. Persona text, L2. Objective lines, L3. News summaries,
L4. Executive summary, L5. Sector context line

---

## Priority Implementation Order

1. C1-C4 together (morning briefing mechanization) — biggest user impact
2. C6 (candidate scoring) — DONE via sim-ranked workflow
3. C7 (monthly cycle) — single function addition
4. C5 (knowledge classification) — reduces knowledge store corruption
5. M1-M9 incrementally
