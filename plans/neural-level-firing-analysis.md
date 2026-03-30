# Analysis: Level-Firing Neurons with Subscription-Based Propagation

**Date**: 2026-03-29 (Sunday, 2:12 PM local / 7:12 AM ET)
**Purpose**: Analyze the architecture where neurons fire at LEVELS (not binary yes/no), transmit the level value through synapses, and downstream neurons SUBSCRIBE to specific levels they care about.

---

## 1. What You're Describing

### Current architecture (binary neurons):
```
DIP_THRESHOLD neuron → fires TRUE/FALSE (dip > 1%? yes or no)
                     → ALL dependants receive the same TRUE/FALSE
```

Each ticker uses the same threshold. The neuron makes the decision.

### Proposed architecture (level-firing neurons):
```
DIP_LEVEL neuron → fires with VALUE (0.5%, 1.2%, 2.7%, 3.1%...)
                 → EVERY dependent receives the raw value
                 → Each dependent SUBSCRIBES to the level it cares about

OKLO subscribes to dip_level >= 1.0% (big swinger, any dip works)
AR subscribes to dip_level >= 2.0% (needs deeper dip)
IONQ subscribes to dip_level >= 2.0% (also needs deeper dip)
```

**The neuron doesn't decide. It observes and reports. The subscriber decides based on its own threshold.**

---

## 2. Three Types of Neurons in This Model

### Type 1: Observer Neurons (sensors)
These watch a data source and fire with the current VALUE whenever it changes. No logic, no thresholds, no decisions.

```
DIP_LEVEL: fires with 2.3% (how much the ticker dipped from open)
BOUNCE_LEVEL: fires with 0.8% (how much it bounced in second hour)
RANGE_LEVEL: fires with 10.7% (median daily range)
VIX_LEVEL: fires with 31.0 (current VIX)
PRICE_LEVEL: fires with $8.66 (current price)
```

These are pure measurement neurons. They fire on every update with the raw observation. **No if/else logic inside them.**

### Type 2: Subscription Neurons (per-ticker decision gates)
These receive synapse signals from observer neurons but only ACTIVATE when the value matches their subscription criteria. Each ticker has its own subscription neuron with its own threshold.

```
OKLO:DIP_GATE subscribes to DIP_LEVEL where value >= 1.0%
  → receives DIP_LEVEL = 2.3% → ACTIVATES (2.3% >= 1.0%)

AR:DIP_GATE subscribes to DIP_LEVEL where value >= 2.0%
  → receives DIP_LEVEL = 2.3% → ACTIVATES (2.3% >= 2.0%)

NVDA:DIP_GATE subscribes to DIP_LEVEL where value >= 1.0%
  → receives DIP_LEVEL = 0.4% → STAYS SILENT (0.4% < 1.0%)
```

**The subscription threshold IS the per-ticker tuning.** OKLO's DIP_GATE has threshold 1.0% because that's what simulation optimized. AR's has 2.0%. The observer neuron is the same — the subscription criteria differ.

### Type 3: Aggregator Neurons (combine multiple subscriptions)
These are AND-gates or OR-gates that fire only when multiple subscription neurons have activated.

```
OKLO:CANDIDATE = AND(
    OKLO:DIP_GATE activated,
    OKLO:BOUNCE_GATE activated,
    OKLO:RANGE_GATE activated,
    OKLO:NOT_CATASTROPHIC activated,
    OKLO:EARNINGS_CLEAR activated
)
```

Same as current CANDIDATE neuron, but now its inputs are subscription neurons with per-ticker thresholds, not global binary neurons.

---

## 3. How This Maps to the Three Ticker Behaviors

### Big Swinger (OKLO):
```
Observers:
  DIP_LEVEL → 2.3% (OKLO dipped 2.3% from open)
  BOUNCE_LEVEL → 1.5% (OKLO bounced 1.5% in second hour)
  RANGE_LEVEL → 7.7% (OKLO's median daily range)

Subscriptions (OKLO's thresholds):
  OKLO:DIP_GATE subscribes DIP_LEVEL >= 1.0% → ACTIVE (2.3% >= 1.0%)
  OKLO:BOUNCE_GATE subscribes BOUNCE_LEVEL >= 0.3% → ACTIVE (1.5% >= 0.3%)
  OKLO:RANGE_GATE subscribes RANGE_LEVEL >= 3.0% → ACTIVE (7.7% >= 3.0%)

  OKLO:TARGET_LEVEL = 5.0% (big swinger needs high target)
  OKLO:STOP_LEVEL = -3.0%

  OKLO:CANDIDATE → AND gate → ACTIVE
  OKLO:BUY_DIP → fires with: entry=$X, target=entry×1.05, stop=entry×0.97
```

### EOD Drifter (AR):
```
Observers (same neurons, same values):
  DIP_LEVEL → 1.8% (AR dipped 1.8%)

Subscriptions (AR's thresholds — different from OKLO):
  AR:DIP_GATE subscribes DIP_LEVEL >= 2.0% → SILENT (1.8% < 2.0%)
  → AR doesn't trade today because its dip wasn't deep enough
```

Same observer neuron fired the same value. OKLO's subscription activated. AR's didn't. **The neuron didn't decide — the subscription decided.**

### If AR had dipped 2.5%:
```
  AR:DIP_GATE subscribes DIP_LEVEL >= 2.0% → ACTIVE (2.5% >= 2.0%)
  AR:TARGET_LEVEL = 2.0% (EOD drifter needs low target)
  AR:STOP_LEVEL = -4.0% (wider stop)
  AR:BUY_DIP → fires with: entry=$X, target=entry×1.02, stop=entry×0.96
```

---

## 4. What the Synapse Carries

In the current model, a synapse carries: `True/False` (fired or not).

In the level-firing model, a synapse carries:
```python
{
    "source": "CLSK:DIP_LEVEL",
    "value": 2.3,           # the observed level
    "unit": "percent",       # what the value represents
    "timestamp": "10:30 ET", # when it was observed
}
```

The subscription neuron receives this and checks: `value >= my_threshold`.

**The reason chain becomes richer:**
```
CLSK:DIP_LEVEL fired at 2.3%
  → CLSK:DIP_GATE (threshold 2.0%) ACTIVATED at 2.3%
  → CLSK:BOUNCE_LEVEL fired at 1.1%
  → CLSK:BOUNCE_GATE (threshold 0.3%) ACTIVATED at 1.1%
  → CLSK:CANDIDATE AND-gate ACTIVATED
  → CLSK:BUY_DIP fired with target 3.5%, stop -3.0%
```

You see exactly WHAT value triggered each gate and what threshold it crossed.

---

## 5. Where Per-Ticker Thresholds Come From

The core thresholds (dip_threshold, target, stop) come from the **simulation sweep** (Test 3 in dip-parameter-tuning-analysis.md). The `bounce_threshold` and `behavior` fields are manually assigned based on observed patterns — they are NOT from the simulation output.

```python
TICKER_PROFILES = {
    # Test 3 results: dip_threshold, target, stop from simulation sweep
    # bounce_threshold: manually set (0.3% global default, pending per-ticker optimization)
    # behavior: manually classified from observed P/L patterns
    "OKLO": {"dip_threshold": 1.0, "bounce_threshold": 0.3,
             "target": 5.0, "stop": -3.0, "behavior": "big_swinger"},
    "AR":   {"dip_threshold": 2.0, "bounce_threshold": 0.3,
             "target": 2.0, "stop": -4.0, "behavior": "eod_drifter"},
    "IONQ": {"dip_threshold": 2.0, "bounce_threshold": 0.3,
             "target": 4.0, "stop": -3.0, "behavior": "moderate_recoverer"},
    "CLSK": {"dip_threshold": 2.0, "bounce_threshold": 0.3,
             "target": 3.5, "stop": -3.0, "behavior": "moderate_recoverer"},
    "NNE":  {"dip_threshold": 1.5, "bounce_threshold": 0.3,
             "target": 3.5, "stop": -4.0, "behavior": "moderate_recoverer"},
}
```

**Coverage gap:** Only 5 of ~21 tickers have profiles. The remaining 16 would fall back to DIP_CONFIG global defaults until swept through the backtester.

These profiles are pre-computed by the backtester/simulator. The neural network reads them at startup. When the simulation is re-run (monthly or after market shifts), the profiles update and the subscription thresholds change automatically.

---

## 6. Advantages Over the Current Binary Model

### 6.1 Shared Observers Benefit Market-Wide Signals
For **shared signals** (VIX, breadth), one observer neuron serves all tickers — each subscribes at its own threshold. Currently we'd need separate neurons for "breadth > 30%?", "breadth > 50%?", etc. With level-firing, ONE VIX_LEVEL neuron fires once and each ticker subscribes at its own level.

**Note:** For per-ticker observations (dip, bounce), each stock inherently has its own observer (`{tk}:dip_level`) because each stock has its own price. The "one observer, many subscribers" advantage does NOT apply here — the neuron count stays the same (N observers + N gates vs N binary neurons). The benefit for per-ticker signals is the value propagation and richer reason chains, not reduced neuron count.

### 6.2 Reason Chains Show Values, Not Just Pass/Fail
Current: `"CLSK:dipped: Dipped 2.3%"` — you see it passed but not what threshold it crossed.
Level-firing: `"CLSK:DIP_LEVEL=2.3% → CLSK:DIP_GATE(≥2.0%) ACTIVATED"` — you see the value, the threshold, and that it crossed.

### 6.3 Per-Ticker Tuning Without Code Changes
To change OKLO's dip threshold from 1.0% to 1.5%, update TICKER_PROFILES. No graph code changes. The subscription neuron reads its threshold from the profile.

### 6.4 Continuous Refinement
As the backtester produces new optimal parameters (monthly re-run), the profiles update. The neural network picks up new thresholds on next evaluation. No deployment, no code change — just a data file update.

### 6.5 Behavioral Classification is Explicit
Each ticker's profile has a `behavior` field: "big_swinger", "eod_drifter", "moderate_recoverer". This classifies the ticker's dip personality and drives the subscription pattern. New behavior types can be added without changing the neuron architecture.

---

## 7. Disadvantages / Complexity

### 7.1 More State to Manage
Each ticker has its own profile with 5+ thresholds. 21 tickers × 5 params = 105 configurable values vs 5 global values today.

### 7.2 Profile Maintenance
Who updates the profiles? The backtester sweep needs to run periodically and write the results. If profiles are stale (optimized on bull market data, now we're in Risk-Off), the thresholds may be wrong.

### 7.3 Overfitting Risk
Per-ticker optimization on 3 months of data may overfit to that specific window. The optimal params for OKLO in Oct-Dec 2025 may not work in Jan-Mar 2026.

### 7.4 Observer Neuron Granularity
DIP_LEVEL fires with any change. But the graph engine resolves all nodes at once (snapshot model). For true level-firing, the observer would need to fire on price changes during market hours — which requires the event-driven model we deferred.

**Mitigation**: In the phased model (10:30, 11:00 evaluations), the observer fires once per phase with the current value. Not continuous, but functionally equivalent for the dip strategy which evaluates at 2 fixed time points.

---

## 8. How This Affects the Graph Engine

### Current graph_engine.py:
- Node.compute() returns a value
- Signal carries old_value → new_value + reason text
- has_changed() checks if value differs from prev

### What level-firing needs:
- Node.compute() returns the SAME thing (a value). No change needed.
- Signal ALREADY carries old_value/new_value. No change needed.
- The SUBSCRIPTION concept is new — but it can be implemented as a compute function:

```python
# Subscription neuron: standard compute function, no engine change
graph.add_node(f"{tk}:dip_gate",
    compute=lambda inputs, thresh=profile["dip_threshold"]:
        inputs[f"{tk}:dip_level"] >= thresh,
    depends_on=[f"{tk}:dip_level"],
    reason_fn=lambda old, new, _, thresh=profile["dip_threshold"],
              lvl=None: f"DIP_GATE(≥{thresh}%) {'ACTIVATED' if new else 'SILENT'}")
```

**The subscription IS the compute function's threshold.** The graph engine doesn't need to know about subscriptions — they're implemented as parameterized compute functions.

**This means: zero changes to graph_engine.py.** The level-firing + subscription model is an APPLICATION PATTERN, not an engine feature.

---

## 9. Architecture Summary

```
LAYER 1: OBSERVER NEURONS (fire with raw values)
  MARKET:VIX_LEVEL → 31.0
  MARKET:BREADTH_DIP_LEVEL → 76% (16/21 dipped)
  MARKET:BREADTH_BOUNCE_LEVEL → 81% (17/21 bounced)
  {tk}:DIP_LEVEL → 2.3% (this ticker's dip from open)
  {tk}:BOUNCE_LEVEL → 1.1% (this ticker's bounce)
  {tk}:RANGE_LEVEL → 7.7% (this ticker's historical median range)

LAYER 2: SUBSCRIPTION NEURONS (per-ticker, fire based on level vs threshold)
  {tk}:DIP_GATE → profile[tk].dip_threshold → ACTIVE/SILENT
  {tk}:BOUNCE_GATE → profile[tk].bounce_threshold → ACTIVE/SILENT
  {tk}:RANGE_GATE → profile[tk].range_threshold → ACTIVE/SILENT
  {tk}:TARGET_LEVEL → profile[tk].target (passed to BUY_DIP output)
  {tk}:STOP_LEVEL → profile[tk].stop (passed to BUY_DIP output)

LAYER 3: STATIC GATES (same as current — binary, from graph state)
  {tk}:NOT_CATASTROPHIC → ACTIVE/BLOCKED
  {tk}:EARNINGS_CLEAR → ACTIVE/BLOCKED
  {tk}:NOT_EXIT → ACTIVE/BLOCKED

LAYER 4: AGGREGATOR (AND-gate, per-ticker)
  {tk}:CANDIDATE → ALL subscription gates + static gates ACTIVE

LAYER 5: MARKET SIGNAL (shared)
  SIGNAL_CONFIRMED → BREADTH_DIP_LEVEL >= 50% AND BREADTH_BOUNCE_LEVEL >= 50%
  (or: SIGNAL_CONFIRMED could also be subscription-based — each ticker
   could subscribe to different breadth thresholds)

LAYER 6: TERMINAL
  {tk}:BUY_DIP → CANDIDATE + SIGNAL_CONFIRMED + PDT + CAPITAL
  Output carries: entry price, target (from profile), stop (from profile)
```

---

## 10. Implementation Approach

### What exists and works:
- graph_engine.py — unchanged, compute functions handle subscription logic
- Per-ticker loop in graph builder — already iterates tickers

### What's new:
1. **TICKER_PROFILES dict** — per-ticker thresholds from simulation sweep
2. **Observer neurons** — compute functions that return raw values (not boolean)
3. **Subscription neurons** — compute functions that compare value vs threshold
4. **Profile loading** — read TICKER_PROFILES from a JSON file or from multi-period-results.json

### What this replaces:
- Global `DIP_CONFIG` with one threshold per parameter
- Binary `{tk}:dipped` neurons (True/False)
- Replaced by: `{tk}:dip_level` (value) + `{tk}:dip_gate` (subscription at per-ticker threshold)

### Effort estimate:
- TICKER_PROFILES data: already computed in Test 3 (Section 14 of tuning analysis)
- Observer neurons: rename existing compute functions to return values instead of booleans (~20 line changes)
- Subscription neurons: add per-ticker threshold comparison (~30 new lines)
- Profile loading: ~20 lines (read from JSON)
- **Total: ~70 lines of changes in graph_builder or neural_dip_evaluator**

---

## 11. Open Questions

1. **Should BREADTH thresholds also be per-ticker?** Currently 50% global. Test 2 showed some tickers profit in Risk-Off (where breadth is lower). Per-ticker breadth subscriptions would let OKLO trade on 30% breadth days while LUNR requires 50%.

2. **How often to re-optimize profiles?** Monthly? After each regime change? The backtester can run automatically, but stale profiles = stale thresholds.

3. ~~**What about tickers not in the profile?**~~ **ANSWERED:** The existing `DIP_CONFIG` dict already serves as the global default fallback (line 37-48 of `neural_dip_evaluator.py`). Tickers without a profile entry use `DIP_CONFIG` values. The code pattern `cfg = DIP_CONFIG` at line 236 shows how this works. Implementation: `profile = TICKER_PROFILES.get(tk, DIP_CONFIG)`.

4. ~~**Should the observer neurons be per-ticker or shared?**~~ **ANSWERED by existing code structure:** The `for tk in tickers:` loop in `build_first_hour_graph()` (line 273) computes per-ticker dip/bounce from each stock's own OHLC data — these are inherently per-ticker observers. VIX and breadth are computed once outside the loop — these are inherently shared observers. The code structure already enforces this separation. No design decision needed.

5. **Overfitting protection**: Per-ticker optimization on 3 months could overfit. Mitigation: require minimum 20 trades in the simulation window. Use cross-validation (optimize on months 1-2, validate on month 3). Flag profiles with <20 trades as "LOW_CONFIDENCE" and use default thresholds.
