# Honest Assessment: Neural Firing Graph vs Snapshot Graph

**Date**: 2026-03-29 (Sunday)
**Purpose**: Evidence-based evaluation of whether the neural firing architecture is superior to what we already built. No enthusiasm, just facts.

---

## Verdict Summary

| Claim | Verdict | Evidence |
| :--- | :--- | :--- |
| More elegant/efficient | **FALSE** | Snapshot resolves 429 nodes in <50ms compute. Neural adds state machines, event loops, temporal tracking — more infrastructure for same logical output. |
| More flexible for simulation | **MISLEADING** | What-if in snapshot = change one input, call resolve(). What-if in neural = replay temporal sequence with clock simulation. More complex, not more flexible. |
| Gets closer to prediction | **FALSE** | Both are deterministic rule engines. Neural naming doesn't create learning. Prediction requires ML training loops, loss functions, gradient descent — none of which are in this proposal. |
| Brain-like is inherently better | **FALSE** | The analogy is cosmetic. Biological neurons learn (synaptic plasticity). These neurons have hardcoded thresholds. It's a finite state machine with biological labels. |

---

## What the Neural Model IS Actually Better At

These are genuine capabilities the snapshot model lacks:

1. **Temporal sequencing** — "evaluate breadth in first hour, evaluate bounce in second hour, then decide." The snapshot model can't sequence decisions across time windows within a single session.

2. **Real-time event response** — price tick → cascade evaluation. The snapshot model runs once per session.

3. **Multi-phase intraday decisions** — pre-market checks → open → first-hour → second-hour → decision. The snapshot model treats each run as independent.

**BUT**: All three require infrastructure we don't have:
- A persistent process running during market hours (not a CLI tool)
- Real-time or 5-minute price feeds (not end-of-day yfinance)
- Historical intraday data for backtesting (yfinance 5-min only goes back 60 days; longer history requires paid providers)

---

## What the Neural Model IS Worse At

| Aspect | Snapshot | Neural |
| :--- | :--- | :--- |
| Code size | 324 lines (engine) + 553 (builder) | Estimated 1,500-2,500 lines minimum |
| Test complexity | 93 cases, all deterministic | 3-5x more cases needed (temporal, sequence, race conditions) |
| Debugging | "What were the inputs? What did compute return?" | "Which neurons fired? In what order? Were time windows open?" |
| Adding new decision | 1 node + 1 compute function | Neuron + firing condition + temporal window + synapses + AND-gate |
| Performance | <50ms compute, 1.2s total with yfinance | More overhead: state tracking per neuron, event dispatch, clock management |

---

## The Core Problem

The neural model solves a problem we don't currently have: **real-time intraday decision-making with temporal dependencies.**

Our system is a **daily batch tool**. The user runs `python3 tools/daily_analyzer.py`, reads the dashboard, and acts at the broker. This happens once per session, not continuously during market hours.

The `dip_signal_checker.py` is the closest thing to real-time — it runs at 10:30 AM and checks breadth. But it's also a batch tool: run once, read output, decide. It doesn't continuously monitor.

Building a neural architecture on top of a batch system produces: **a more complex batch system that does the same thing.**

---

## What Would Make the Neural Model Worth Building

The neural model becomes valuable IF AND WHEN:

1. **The system runs continuously during market hours** — a persistent process, not a CLI tool
2. **Real-time price feeds exist** — websocket or 5-min polling, not end-of-day downloads
3. **Decisions happen automatically** — the system places orders based on neural firing, not just recommends
4. **Historical intraday data is available** — for backtesting temporal firing patterns

Without these, the neural model is architecture looking for a problem.

---

## The Right Path Forward

**If the goal is better daily dip decisions (current operational model):**
- The snapshot graph with dip_viable nodes (already built) handles this
- Run `dip_signal_checker.py` at 10:30 AM for breadth confirmation (already exists)
- No new architecture needed

**If the goal is real-time intraday automation (future):**
1. First: build the intraday data pipeline (the hard part, requires paid data or persistent polling)
2. Then: build a real-time event processor (Complex Event Processing pattern, proven in trading)
3. Keep the snapshot model for daily batch decisions — they serve different purposes
4. The neural model could be the event processor's decision engine — but only after the data pipeline exists

**If the goal is prediction:**
- Neither snapshot nor neural graph predicts anything
- Prediction requires: training data (historical input→outcome pairs), ML model (actual neural network or gradient boosted trees), training loop, validation
- This is a completely separate project from either graph architecture

---

## Conclusion

The neural firing metaphor is intellectually appealing but practically premature. The evidence says:

- **Today**: The snapshot graph does everything the daily workflow needs. 429 nodes, <50ms compute, composable reasons, state persistence, cross-run diffing. Working, tested, deployed.
- **The neural model**: Solves real-time temporal sequencing — a genuine capability gap. But that gap only matters when we have real-time data feeds and a persistent process to consume them.
- **Prediction**: Neither model predicts. That requires ML, not graph architecture.

Building the neural model now would be investing in infrastructure for a capability we can't use yet (no real-time feeds) while the existing system already handles the current workflow correctly.

The honest recommendation: use the snapshot graph for daily decisions (it works), use dip_signal_checker for intraday confirmation (it works), and save the neural architecture for when the system evolves from a CLI tool to a real-time monitor with live data feeds.
