# Implementation Plan: Plugging Neural Profiles into Computation Tools

**Date**: 2026-03-29
**Source analysis**: `plans/neural-tool-integration-analysis.md` (verified, 7/7 correct)
**Goal**: Neural pool/bullets/sell targets flow through the SAME computation tools that produce actual orders — not just displayed in a separate section.

---

## Scope

5 files, ~71 lines. All changes backward compatible — falls back to existing defaults when no neural profile.

| Step | File | Change | Lines |
| :--- | :--- | :--- | :--- |
| 1 | `shared_utils.py` | Add neural pool tier to `get_ticker_pool()` | ~20 |
| 2 | `broker_reconciliation.py` | Merge neural sell targets in `_load_profiles()` + reorder priority | ~20 |
| 3 | `wick_offset_analyzer.py` | Check neural bullets in `load_capital_config()` | ~15 |
| 4 | `graph_builder.py` | Merge neural profiles into its own profiles dict | ~15 |
| 5 | `bullet_recommender.py` | Pass ticker to `load_capital_config(ticker)` | ~1 |

**NOT modified**: `daily_analyzer.py` (neural display already exists, computation inherits from upstream changes)

---

## Step 1: `shared_utils.py` — Neural Pool Tier

**Function**: `get_ticker_pool()` (line 55)

**Current priority** (FACT, verified):
1. multi-period-results.json
2. portfolio.json capital section
3. hardcoded $300/$300

**New priority**:
1. multi-period-results.json (simulation-backed, always wins)
2. **neural_support_candidates.json** (NEW)
3. portfolio.json capital section
4. hardcoded $300/$300

**Where to insert** (after the multi-period check, before portfolio.json fallback):

```python
# After multi-period check (around line 79), before portfolio.json fallback:

# Check neural support profiles
try:
    ns_path = Path(__file__).resolve().parent.parent / "data" / "neural_support_candidates.json"
    if ns_path.exists():
        with open(ns_path) as f:
            ns_data = json.load(f)
        for c in ns_data.get("candidates", []):
            if c["ticker"] == ticker:
                params = c.get("params", {})
                return {
                    "active_pool": params.get("active_pool", _DEFAULT_ACTIVE),
                    "reserve_pool": params.get("reserve_pool", _DEFAULT_RESERVE),
                    "total_pool": params.get("active_pool", _DEFAULT_ACTIVE) + params.get("reserve_pool", _DEFAULT_RESERVE),
                    "source": "neural_support",
                    "composite": None,
                }
except (FileNotFoundError, json.JSONDecodeError, KeyError):
    pass
```

**Backward compat**: If file doesn't exist or ticker not in candidates, falls through to portfolio.json then $300.

---

## Step 2: `broker_reconciliation.py` — Neural Sell Targets + Priority Reorder

### 2.1 Merge neural profiles into `_load_profiles()`

**Current** (lines 42-47): Reads `ticker_profiles.json` only.

**Change**: After loading ticker_profiles.json, merge neural_support_candidates.json as secondary source:

```python
def _load_profiles():
    profiles = {}
    try:
        with open(PROFILES_PATH) as f:
            profiles = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Merge neural support candidates (secondary source for sell targets)
    try:
        ns_path = _ROOT / "data" / "neural_support_candidates.json"
        if ns_path.exists():
            with open(ns_path) as f:
                ns_data = json.load(f)
            for c in ns_data.get("candidates", []):
                tk = c["ticker"]
                if tk not in profiles:
                    profiles[tk] = {}
                # Only set if no existing optimal_target_pct
                if not profiles[tk].get("optimal_target_pct"):
                    profiles[tk]["optimal_target_pct"] = c["params"].get("sell_default")
                    profiles[tk]["_neural_source"] = "neural_support"
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass

    return profiles
```

### 2.2 Reorder `compute_recommended_sell()` priority

**Current** (lines 137-152):
1. profiles → optimal_target_pct
2. pos → target_exit
3. SELL_DEFAULT_PCT (6.0%)

**New priority** (manual override first):
1. pos → target_exit (user manual override — highest priority)
2. profiles → optimal_target_pct (includes neural via merged profiles)
3. SELL_DEFAULT_PCT (6.0%)

```python
def compute_recommended_sell(ticker, avg_cost, pos, profiles):
    # 1. Manual override always wins
    te = pos.get("target_exit")
    if te is not None:
        return te, "target_exit"

    # 2. Profile (ticker_profiles.json or neural_support fallback)
    profile = profiles.get(ticker, {})
    opt = profile.get("optimal_target_pct")
    if opt is not None:
        source = profile.get("_neural_source", "optimized")
        return round(avg_cost * (1 + opt / 100), 2), f"{source} {opt:.1f}%"

    # 3. Hardcoded fallback
    return round(avg_cost * (1 + SELL_DEFAULT_PCT / 100), 2), f"standard {SELL_DEFAULT_PCT:.1f}%"
```

---

## Step 3: `wick_offset_analyzer.py` — Neural Bullets

**Function**: `load_capital_config()` (line 46)

**Where**: After calling `get_ticker_pool(ticker)` for pool values (which now returns neural pool via Step 1), check neural profile for bullet counts:

```python
# After pool lookup, before returning:
# Check neural support for bullet overrides
try:
    ns_path = Path(__file__).resolve().parent.parent / "data" / "neural_support_candidates.json"
    if ns_path.exists() and ticker:
        with open(ns_path) as f:
            ns_data = json.load(f)
        for c in ns_data.get("candidates", []):
            if c["ticker"] == ticker:
                params = c.get("params", {})
                if params.get("active_bullets_max"):
                    result["active_bullets_max"] = params["active_bullets_max"]
                if params.get("reserve_bullets_max"):
                    result["reserve_bullets_max"] = params["reserve_bullets_max"]
                break
except (FileNotFoundError, json.JSONDecodeError, KeyError):
    pass
```

**Backward compat**: If no neural profile, keeps existing 5/3 defaults.

---

## Step 4: `graph_builder.py` — Merge Neural Profiles

**Current** (lines 174-180): Loads `ticker_profiles.json` directly into a `profiles` dict.

**Change**: After loading ticker_profiles.json, merge neural_support_candidates.json (same pattern as Step 2.1):

```python
# After existing profiles load (line 180):
try:
    ns_path = _ROOT / "data" / "neural_support_candidates.json"
    if ns_path.exists():
        with open(ns_path) as f:
            ns_data = json.load(f)
        for c in ns_data.get("candidates", []):
            tk = c["ticker"]
            if tk not in profiles:
                profiles[tk] = {}
            if not profiles[tk].get("optimal_target_pct"):
                profiles[tk]["optimal_target_pct"] = c["params"].get("sell_default")
except (FileNotFoundError, json.JSONDecodeError, KeyError):
    pass
```

---

## Step 5: `bullet_recommender.py` — Pass Ticker

**Current** (line 223):
```python
cap = load_capital_config()
```

**Change**:
```python
cap = load_capital_config(ticker)
```

**Note** (from verification): The CLI callers already pass ticker at lines 1111/1127. Line 223 is a fallback path inside `run_recommend()`. Fixing it ensures any future caller without pre-loaded cap gets neural values.

---

## Verification

After implementation, run:

```bash
python3 -c "
from tools.shared_utils import get_ticker_pool
# APP has neural pool=$500
pool = get_ticker_pool('APP')
print(f'APP pool: {pool}')
# Should show source='neural_support', active_pool=500

# AAPL has no neural profile
pool2 = get_ticker_pool('AAPL')
print(f'AAPL pool: {pool2}')
# Should show source='default' or 'portfolio', active_pool=300
"
```

```bash
python3 -c "
from tools.broker_reconciliation import _load_profiles, compute_recommended_sell
profiles = _load_profiles()
# APP should have optimal_target_pct=10.0 from neural
print(f'APP profile: {profiles.get(\"APP\", {})}')

# With target_exit set → manual wins
sell, src = compute_recommended_sell('APP', 100.0, {'target_exit': 108.0}, profiles)
print(f'With target_exit: sell={sell}, source={src}')
# Should show 108.0, 'target_exit'

# Without target_exit → neural wins
sell2, src2 = compute_recommended_sell('APP', 100.0, {}, profiles)
print(f'Without target_exit: sell={sell2}, source={src2}')
# Should show 110.0 (10%), 'neural_support 10.0%'
"
```

---

## What Changes After Implementation

**Before** (current):
```
RDW: pool=$300, 5 bullets, sell at $8.85 (6.0%)
  → 6 shares per level, sell target too low
  Neural section says: "pool=$500, 7 bullets, sell at 10%"  ← IGNORED
```

**After**:
```
RDW: pool=$500, 7 bullets, sell at $8.98 (10.0%)
  → 9 shares per level, sell target from neural
  Neural section: "pool=$500, 7 bullets, sell at 10%"  ← MATCHES computation
```
