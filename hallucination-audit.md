# Hallucination Risk Audit — 2026-03-28 (Verified)

## Purpose
Every point where LLM judgment produces data, calculations, or directions
that could be fabricated. Each must be replaced with a Python script.

## Status: 5 CRITICAL, 10 MEDIUM, 5 LOW (acknowledged)

---

## CRITICAL (Directly Affect Real Money Decisions)

### C1. Projected Sell Levels — LLM Math
- **Where:** active-ticker-analyst.md lines 185-188
- **What:** LLM computes scenario tables: New Avg = (shares × avg + new × buy) / total
- **Evidence:** NU-card.md shows LLM arithmetic ($15.38 average)
- **Fix:** Pre-compute in morning_splitter.py from portfolio.json
- **Status:** TODO

### C2. 16-Rule Verdict Logic — LLM Evaluation
- **Where:** active-ticker-analyst.md lines 36-108 (16 rules, first-match-wins)
- **What:** LLM applies verdict rules (EXIT/REDUCE/HOLD/MONITOR)
- **Mitigation:** morning_verifier.py check_verdicts() (lines 755-932) catches errors POST-HOC
- **Gap:** User sees briefing BEFORE verifier runs. Fix = move verifier logic UPSTREAM.
- **Fix:** Pre-compute suggested_verdict in morning_splitter.py (logic already exists in verifier)
- **Status:** TODO

### C3. Momentum Classification — LLM Interpretation
- **Where:** active-ticker-analyst.md lines 57-60
- **What:** LLM classifies Bullish/Neutral/Bearish from RSI/MACD values
- **Impact:** Affects verdict rules 8-9, 11-12 (can flip EXIT↔HOLD)
- **Mitigation:** morning_verifier.py compute_expected_momentum_label() (lines 364-395) exists
- **Fix:** Move compute_expected_momentum_label() into morning_splitter.py, inject into input
- **Status:** TODO

### C4. Entry Gate Computation — LLM Logic
- **Where:** active-ticker-analyst.md lines 110-125
- **What:** LLM evaluates Market Context Gate + Earnings Gate per pending order
- **Impact:** Determines ACTIVE/PAUSED for real money orders
- **Mitigation:** morning_verifier.py check_entry_gates() (line 1085) catches post-hoc
- **Fix:** Pre-compute in morning_splitter.py (regime + DTE already available in condensed)
- **Status:** TODO

### C6. Candidate Score Adjustments — LLM +/-20
- **Where:** surgical-evaluator/verifier/critic agents
- **What:** LLM adjusts scores +/-10 per phase (up to +/-20 total)
- **Fix:** sim-ranked workflow replaces scoring with simulation P/L ranking
- **Status:** DONE (sim-ranked workflow is fully mechanized; old workflow retained as fallback)

---

## MEDIUM (Affect Analysis Quality, Not Direct Money Decisions)

### C5 (reclassified). Knowledge Belief Classification — LLM Judgment
- **Where:** knowledge-analyst.md lines 37-55
- **What:** LLM classifies beliefs as TEMPORARY/STRUCTURAL
- **Impact:** Affects knowledge store (long-term memory), NOT direct buy/sell
- **Fix:** Automate deterministic rules (3+ breaks = STRUCTURAL); LLM only for ambiguous cases
- **Status:** TODO

### C7 (reclassified). Monthly Cycle Timing — LLM Determination
- **Where:** deep-dive-analyst.md lines 63-66
- **What:** LLM determines Early/Mid/Late monthly bottom from wick history
- **Impact:** Advisory text in identity files, NOT direct buy/sell decisions
- **Fix:** Compute from wick approach timestamps (group by day-of-month)
- **Status:** TODO

### M1. Sell-Side Advisory Content — LLM Narrative
- **What:** LLM generates specific sell price suggestions ("consider trimming at $X")
- **Risk:** Could suggest fabricated price targets
- **Fix:** Pre-compute triggers + constrain advisory to tool-computed sell targets only

### M2. News Earnings Imminence — MOSTLY DONE
- **What:** DTE already extracted by morning_gatherer.py extract_days_to_earnings()
- **Remaining:** LLM interprets news headlines for earnings context (appropriate LLM work)
- **Status:** MOSTLY FIXED

### M3. Cycle Timing Cooldown Override — LLM Judgment
- **Fix:** Encode override conditions as deterministic rules

### M4. Watchlist Fitness Verdict Override — LLM Judgment
- **Fix:** Encode in watchlist_fitness.py

### M5. Dip Sim Qualitative Summary — LLM Narrative
- **Status:** Appropriate LLM work (narrative synthesis of statistical results)

### M7. Exit Review Rule 3 Override — LLM Thesis Evaluation
- **Status:** BY DESIGN — Python flags the candidate, LLM evaluates thesis

### M8. Universe Cache 7-Day Staleness
- **Status:** PARTIALLY FIXED (sim_ranked_screener has fresh validation)

### M9. Sector Registry Hardcoded Map Staleness
- **Fix:** Periodic cross-check script against yfinance

### M10 (NEW). News Fabrication Risk
- **What:** LLM summarizes news and could fabricate events or price targets
- **Evidence:** Cards contain claims like "Morgan Stanley raised target to $X" — unverified
- **Fix:** Have news tools output pre-formatted headlines, LLM copies not interprets

### M11 (NEW). Recovery Position Classification
- **What:** LLM determines if position is "recovery" (affects which verdict rules apply)
- **Fix:** Deterministic classification from portfolio.json note field + P/L sign

---

## REMOVED (Already Mechanized)

### ~~M6. Candidate Sim Gate Assessment~~
- **Removed:** candidate_sim_gate.py handles all computation. Agent is thin wrapper.

---

## LOW (Cosmetic — Acknowledged)

L1. Persona text, L2. Objective lines, L3. News summaries,
L4. Executive summary, L5. Sector context line

---

## Verified Priority Implementation Order

1. **C1 + C3 + C4** (morning briefing pre-computation) — move existing verifier logic upstream
2. **C2** (verdict pre-computation) — same approach, highest impact
3. **C6** — DONE via sim-ranked workflow
4. **M10** (news fabrication) — constrain LLM to pre-formatted tool output
5. **M11** (recovery classification) — simple keyword + P/L check
6. **C5/C7** (knowledge + cycle timing) — lower priority, medium impact
7. **M1-M9** incrementally

## Key Architectural Insight

The morning verifier (morning_verifier.py) already contains Python implementations
of verdict logic, momentum classification, and entry gates. The fix is NOT writing
new logic — it's MOVING existing verified logic upstream from post-hoc checking to
pre-computation in morning_splitter.py. The code exists; it just runs too late.
