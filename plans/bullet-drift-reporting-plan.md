# Bullet Drift Reporting — Implementation Plan
*Author: 2026-04-22 | Status: ready for verification (rev 2)*

## Goal
After the weekly_reoptimize.py wick refresh changes support levels, tier classifications, and buy_at prices, detect which of the user's live broker BUY orders are now out-of-sync with fresh recommendations. Emit a copy-paste actionable report (move/cancel/resize/add rows) so no manual diffing is required. Never auto-mutate portfolio.json — broker remains source of truth until user confirms.

## Key insight: `data["bullet_plan"]` is already cached

`analyze_stock_data` in `wick_offset_analyzer.py:1054` already calls `_compute_bullet_plan` and caches the result as `data["bullet_plan"]`. The drift reporter uses this cached plan directly — no extraction, no re-computation. Each entry already has `support_price`, `buy_at`, `tier` (= `effective_tier`), `shares`, and `zone` ("Active" or "Reserve"). Note: `_compute_bullet_plan` returns a dict `{"active": [...], "reserve": [...], "active_total_cost": ..., ...}`, not a flat list — iterate `data["bullet_plan"]["active"] + data["bullet_plan"]["reserve"]` to get all entries.

## PR Manifest (4 files changed, 1 new module, 1 new test file)

1. **`tools/bullet_recommender.py`** — modify `merge_convergent_levels` (lines 95-121) to add `merged_from` field on surviving levels.
2. **`tools/bullet_drift_report.py`** (NEW) — all drift logic: snapshot, matching, classification, render, archive, CLI.
3. **`tools/weekly_reoptimize.py`** — wire snapshot capture into STEP 0 loop; wire drift report call after `step_tournament()`.
4. **`tools/morning_compiler.py`** — add `build_broker_actions_section()` helper; append to `output_parts` before final merge at line 626.
5. **`tests/test_bullet_drift_report.py`** (NEW) — unit coverage.

---

## Step 1 — Modify `merge_convergent_levels`

**File:** `tools/bullet_recommender.py`, lines 95-121.

**Change:** On each surviving level, add `merged_from` field.

```python
def merge_convergent_levels(levels, tolerance=CONVERGENCE_TOLERANCE):
    """Merge levels whose recommended_buy prices cluster within tolerance.
    Returns (merged_levels, merge_notes). Each surviving level gains a
    `merged_from` list: [{"price": float, "source": str}, ...] of absorbed levels.
    """
    if not levels:
        return [], []
    merged, merge_notes = [], []
    sorted_levels = sorted(levels, key=lambda l: -l["recommended_buy"])
    used = [False] * len(sorted_levels)
    for i, lvl in enumerate(sorted_levels):
        if used[i]:
            continue
        cluster = [lvl]
        used[i] = True
        for j in range(i + 1, len(sorted_levels)):
            if used[j]:
                continue
            ref = cluster[0]["recommended_buy"]
            if abs(sorted_levels[j]["recommended_buy"] - ref) / ref <= tolerance:
                cluster.append(sorted_levels[j])
                used[j] = True
        best = max(cluster, key=lambda l: l["hold_rate"])
        absorbed = [l for l in cluster if l is not best]
        best["merged_from"] = [
            {"price": l["support_price"], "source": l["source"]} for l in absorbed
        ]
        if absorbed:
            sources = [f"${l['support_price']:.2f} {l['source']}" for l in cluster]
            merge_notes.append(
                f"Merged: {' + '.join(sources)} -> buy at ${best['recommended_buy']:.2f}"
            )
        merged.append(best)
    return merged, merge_notes
```

**Regression check:** Only caller is line 359 of bullet_recommender.py (`valid_levels, merge_notes = merge_convergent_levels(valid_levels)`). New field is additive; no consumer depends on its absence. No tests currently cover this function directly (grep confirms). Run full suite after change to confirm no indirect failures.

---

## Step 2 — New module `tools/bullet_drift_report.py`

### 2.1 Module header

```python
"""Bullet drift reporter: diff before/after wick refreshes to flag stale broker orders."""
import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import yfinance as yf
from shared_constants import MATCH_TOLERANCE
from bullet_recommender import CONVERGENCE_TOLERANCE, DRIFT_TOLERANCE, merge_convergent_levels
from wick_offset_analyzer import analyze_stock_data

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SNAPSHOT_PATH = DATA_DIR / "bullet_snapshot_before.json"
REPORT_JSON = DATA_DIR / "bullet_drift_report.json"
REPORT_MD = PROJECT_ROOT / "bullet_drift_report.md"
ARCHIVE_DIR = DATA_DIR / "bullet_drift_history"
ARCHIVE_RETENTION_DAYS = 28
SCHEMA_VERSION = 1

NOTE_PRICE_RE = re.compile(r'—\s+\$?([\d.]+)\s+([A-Za-z+]+)')
TIER_IN_NOTE_RE = re.compile(r'\b(Full|Std|Half|Skip)\s+tier')
```

### 2.2 Snapshot write — called from weekly_reoptimize.py after STEP 0 loop

```python
def write_before_snapshot(tracked_tickers, pending_orders_all, data_cache):
    """
    Called once after STEP 0 loop completes. Builds and writes snapshot file.
    
    Parameters:
        tracked_tickers : set of tickers STEP 0 processed (has fresh `data`)
        pending_orders_all : portfolio.json["pending_orders"] dict
        data_cache : {ticker: data_dict} — pre-computed analyze_stock_data output
                     populated during STEP 0 loop by caller (see Step 3.1 below)
    """
    now = time.time()
    orders_tickers = {
        t for t, orders in pending_orders_all.items()
        if any(o.get("filled") is not True for o in orders)
    }
    snapshot_set = set(tracked_tickers) & orders_tickers
    orphan_set = orders_tickers - set(tracked_tickers)

    snapshot = {"schema_version": SCHEMA_VERSION, "snapshot_ts": now, "tickers": {}}

    for ticker in sorted(snapshot_set):
        data = data_cache.get(ticker)
        if data is None:
            snapshot["tickers"][ticker] = {
                "status": "WICK_MISSING", "reason": "data_cache missing",
                "pending_orders": [dict(o) for o in pending_orders_all[ticker]],
            }
            continue
        bullet_plan_flat = (data.get("bullet_plan", {}).get("active", []) +
                            data.get("bullet_plan", {}).get("reserve", []))
        snapshot["tickers"][ticker] = {
            "status": "OK",
            "current_price": data.get("current_price"),
            "levels": [_extract_level_fields(l) for l in data.get("levels", [])],
            "bullet_plan": [_extract_plan_fields(p) for p in bullet_plan_flat],
            "pending_orders": [dict(o) for o in pending_orders_all[ticker]],
        }

    for ticker in sorted(orphan_set):
        live = [o for o in pending_orders_all[ticker] if o.get("filled") is not True]
        snapshot["tickers"][ticker] = {
            "status": "ORPHAN",
            "reason": "ticker not in weekly_reoptimize tracked set",
            "pending_orders": live,
        }

    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, default=str))
    return snapshot


def _extract_level_fields(level):
    """Flatten level dict to snapshot schema."""
    return {
        "support_price": level["support_price"],
        "source": level["source"],
        "recommended_buy": level["recommended_buy"],
        "effective_tier": level.get("effective_tier", level["tier"]),
        "hold_rate": level["hold_rate"],
        "zone": level["zone"],
    }


def _extract_plan_fields(plan_entry):
    """Flatten bullet_plan entry to snapshot schema."""
    return {
        "support_price": plan_entry["support_price"],
        "buy_at": plan_entry["buy_at"],
        "tier": plan_entry["tier"],
        "shares": plan_entry["shares"],
        "zone": plan_entry["zone"],
    }
```

**Note:** levels list retains Skip-tier entries (needed for CANCEL detection). bullet_plan excludes Skip-tier entries (that's why the recommender doesn't size them). Drift detector compares pending order against bullet_plan for active recommendations; checks levels list to detect "matched but now Skip" CANCEL path.

### 2.3 Drift report generation — called as STEP 12

```python
def generate_drift_report(dry_run=False):
    """Reads SNAPSHOT_PATH, re-runs analyze_stock_data per ticker,
    computes diff, writes REPORT_JSON and REPORT_MD, archives copies.
    """
    report_ts = time.time()
    if not SNAPSHOT_PATH.exists():
        return {"status": "NO_SNAPSHOT", "message": "run snapshot-before first"}

    before = json.loads(SNAPSHOT_PATH.read_text())
    if before.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"schema_version mismatch: expected {SCHEMA_VERSION}, "
            f"got {before.get('schema_version')}"
        )

    trade_history = json.loads((PROJECT_ROOT / "trade_history.json").read_text())["trades"]
    snapshot_ts = before["snapshot_ts"]

    report = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_ts": snapshot_ts,
        "report_ts": report_ts,
        "tickers": {},
    }

    # Orphan and pre-snapshot-error tickers pass through directly
    drift_tickers = {}
    for ticker, before_entry in before["tickers"].items():
        status = before_entry.get("status")
        if status == "ORPHAN":
            report["tickers"][ticker] = {
                "status": "ORPHAN",
                "reason": before_entry["reason"],
                "orders": [
                    {"action": "ORPHAN", "old_price": o["price"],
                     "old_shares": o["shares"], "note": o.get("note", "")}
                    for o in before_entry["pending_orders"]
                ],
            }
        elif status == "WICK_MISSING":
            report["tickers"][ticker] = {
                "status": "WICK_MISSING",
                "reason": before_entry.get("reason", ""),
                "orders": [
                    {"action": "WICK_MISSING", "old_price": o["price"],
                     "old_shares": o["shares"], "note": o.get("note", "")}
                    for o in before_entry["pending_orders"]
                ],
            }
        else:
            drift_tickers[ticker] = before_entry

    # Parallel drift computation for OK tickers
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(_drift_one, t, e, trade_history, snapshot_ts, report_ts): t
            for t, e in drift_tickers.items()
        }
        for f in futures:
            t = futures[f]
            try:
                report["tickers"][t] = f.result()
            except Exception as e:
                report["tickers"][t] = {"status": "ERROR", "reason": str(e),
                                         "orders": []}

    if dry_run:
        (Path("/tmp") / "bullet_drift_report.json").write_text(
            json.dumps(report, indent=2, default=str)
        )
        (Path("/tmp") / "bullet_drift_report.md").write_text(render_markdown(report))
        return report

    REPORT_JSON.write_text(json.dumps(report, indent=2, default=str))
    md = render_markdown(report)
    REPORT_MD.write_text(md)
    _archive_copy(report, md)
    _prune_archive()
    return report
```

### 2.4 Per-ticker drift computation

```python
def _drift_one(ticker, before_entry, trade_history, snapshot_ts, report_ts):
    """Core drift logic for one ticker."""
    hist = yf.download(ticker, period="13mo", progress=False)
    after_data, err = analyze_stock_data(ticker, hist)
    if after_data is None:
        return {
            "status": "WICK_MISSING",
            "reason": err or "analyze_stock_data returned None",
            "orders": [
                {"action": "WICK_MISSING", "old_price": o["price"],
                 "old_shares": o["shares"], "note": o.get("note", "")}
                for o in before_entry["pending_orders"]
            ],
        }

    after_levels_raw = after_data.get("levels", [])
    # Apply merge to get merged_from on surviving levels for later lookups
    after_levels_merged, _ = merge_convergent_levels(after_levels_raw)
    after_plan_flat = (after_data.get("bullet_plan", {}).get("active", []) +
                       after_data.get("bullet_plan", {}).get("reserve", []))

    orders_report = []
    live_before = [o for o in before_entry["pending_orders"] if o.get("filled") is not True]

    for order in live_before:
        old_support = _parse_note_support(order.get("note", ""))
        match_level = None

        # Match strategy 1: note-parsed support against after_levels (with merged_from fallback)
        if old_support is not None:
            match_level = _find_level_by_support(after_levels_merged, old_support,
                                                  check_merged_from=True)
        # Match strategy 2: order price against after_levels
        if match_level is None:
            match_level = _find_level_by_support(after_levels_merged, order["price"],
                                                  check_merged_from=True)

        if match_level is None:
            # Missing order: disambiguate FILLED vs CANCELLED via trade_history
            orders_report.append(_classify_missing(ticker, order, trade_history,
                                                    snapshot_ts, report_ts))
            continue

        # Found a level match; now classify drift against plan entry (if any)
        plan_match = _find_plan_entry_by_support(after_plan_flat,
                                                   match_level["support_price"])
        orders_report.append(
            _classify_drift(order, match_level, plan_match)
        )

    # ADD detection: plan entries without any matching pending order
    for plan_entry in after_plan_flat:
        has_match = any(
            abs(o["price"] - plan_entry["buy_at"]) / plan_entry["buy_at"]
            <= CONVERGENCE_TOLERANCE
            for o in live_before
        )
        if not has_match:
            orders_report.append({
                "action": "ADD",
                "support_price": plan_entry["support_price"],
                "new_price": plan_entry["buy_at"],
                "new_tier": plan_entry["tier"],
                "new_shares": plan_entry["shares"],
                "zone": plan_entry["zone"],
            })

    return {
        "status": "OK",
        "current_price": after_data["current_price"],
        "orders": orders_report,
    }
```

### 2.5 Classification helpers

```python
def _classify_drift(order, match_level, plan_entry):
    old_price = order["price"]
    new_price = match_level["recommended_buy"]
    dist = abs(new_price - old_price) / old_price
    tier_before = _tier_from_order_note(order.get("note", ""))
    tier_after = match_level.get("effective_tier", match_level.get("tier"))
    new_shares = plan_entry["shares"] if plan_entry else None

    # CANCEL conditions (check first)
    if tier_after == "Skip":
        return {
            "action": "CANCEL", "reason": "tier demoted to Skip",
            "support_price": match_level["support_price"],
            "old_price": old_price, "old_shares": order["shares"],
        }
    if dist > DRIFT_TOLERANCE:
        return {
            "action": "CANCEL",
            "reason": f"buy_at drifted {dist*100:.1f}% (> 5% DRIFT_TOLERANCE)",
            "support_price": match_level["support_price"],
            "old_price": old_price, "new_price": new_price,
            "old_shares": order["shares"],
        }

    # UNCHANGED
    if dist <= MATCH_TOLERANCE and tier_before == tier_after:
        return {
            "action": "UNCHANGED",
            "support_price": match_level["support_price"],
            "old_price": old_price, "new_price": new_price,
        }

    # RESIZE
    if dist <= MATCH_TOLERANCE and tier_before != tier_after:
        return {
            "action": "RESIZE",
            "support_price": match_level["support_price"],
            "old_price": old_price, "old_shares": order["shares"],
            "new_shares": new_shares,
            "tier_before": tier_before, "tier_after": tier_after,
        }

    # MOVE
    return {
        "action": "MOVE",
        "support_price": match_level["support_price"],
        "old_price": old_price, "new_price": new_price,
        "delta_pct": dist * 100,
        "old_shares": order["shares"], "new_shares": new_shares,
        "tier_before": tier_before, "tier_after": tier_after,
    }


def _classify_missing(ticker, order, trade_history, snapshot_ts, report_ts):
    """Order in BEFORE but not in AFTER: FILLED or CANCELLED."""
    for trade in trade_history:
        if trade.get("ticker") != ticker:
            continue
        if trade.get("side") != "BUY":
            continue
        t_epoch = _trade_date_to_epoch(trade.get("date", ""))
        if not (snapshot_ts <= t_epoch < report_ts):
            continue
        if abs(trade["price"] - order["price"]) / order["price"] <= MATCH_TOLERANCE:
            return {
                "action": "FILLED",
                "old_price": order["price"], "old_shares": order["shares"],
                "fill_price": trade["price"], "fill_date": trade["date"],
            }
    return {
        "action": "CANCELLED",
        "reason": "absent from after-snapshot and no matching trade in window",
        "old_price": order["price"], "old_shares": order["shares"],
    }
```

### 2.6 Matching + parsing helpers

```python
def _find_level_by_support(levels, target_price, check_merged_from=False):
    """Fuzzy match support_price within CONVERGENCE_TOLERANCE. Tie-break by hold_rate."""
    candidates = []
    for lvl in levels:
        sp = lvl["support_price"]
        if abs(sp - target_price) / target_price <= CONVERGENCE_TOLERANCE:
            candidates.append(lvl)
            continue
        if check_merged_from:
            for m in lvl.get("merged_from", []):
                if abs(m["price"] - target_price) / target_price <= CONVERGENCE_TOLERANCE:
                    candidates.append(lvl)
                    break
    if not candidates:
        return None
    return max(candidates, key=lambda l: l.get("hold_rate", 0))


def _find_plan_entry_by_support(plan_flat, target_support):
    for p in plan_flat:
        if abs(p["support_price"] - target_support) / target_support <= CONVERGENCE_TOLERANCE:
            return p
    return None


def _parse_note_support(note):
    if not note:
        return None
    m = NOTE_PRICE_RE.search(note)
    return float(m.group(1)) if m else None


def _tier_from_order_note(note):
    m = TIER_IN_NOTE_RE.search(note or "")
    return m.group(1) if m else None


def _trade_date_to_epoch(date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59
        )
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0.0
```

### 2.7 Markdown renderer + helpers

```python
def render_markdown(report):
    ts_fmt = lambda t: datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")
    lines = [
        "# Bullet Drift Report",
        f"*Generated: {ts_fmt(report['report_ts'])} | "
        f"Snapshot taken: {ts_fmt(report['snapshot_ts'])}*",
        "",
    ]
    # Summary table
    summary_header = ("Ticker", "MOVE", "CANCEL", "RESIZE", "ADD",
                      "FILLED", "CANCELLED", "Status")
    summary_rows = [summary_header]
    action_keys = ("MOVE", "CANCEL", "RESIZE", "ADD", "FILLED", "CANCELLED")
    for ticker, entry in sorted(report["tickers"].items()):
        status = entry.get("status", "OK")
        if status != "OK":
            summary_rows.append((ticker, "-", "-", "-", "-", "-", "-", status))
            continue
        counts = {k: 0 for k in action_keys}
        for o in entry.get("orders", []):
            if o["action"] in counts:
                counts[o["action"]] += 1
        summary_rows.append(
            (ticker,) + tuple(str(counts[k]) for k in action_keys) + ("OK",)
        )
    lines.extend(_format_table(summary_rows))

    # Per-ticker sections
    for ticker, entry in sorted(report["tickers"].items()):
        lines.append(f"\n## {ticker}")
        status = entry.get("status", "OK")
        if status == "ORPHAN":
            lines.append(f"*{entry['reason']}.* Manual review required at broker.")
            continue
        if status == "WICK_MISSING":
            lines.append(f"*WICK_MISSING:* {entry['reason']}")
            continue
        if status == "ERROR":
            lines.append(f"*ERROR:* {entry['reason']}")
            continue
        # Per-order table
        order_rows = _per_ticker_rows(entry.get("orders", []))
        if order_rows:
            lines.extend(_format_table(order_rows))
        # Copy-paste commands
        cmds = [_order_to_broker_cmd(ticker, o) for o in entry.get("orders", [])]
        cmds = [c for c in cmds if c]
        if cmds:
            lines.append("\n**Copy-paste broker actions:**")
            lines.extend(f"- {c}" for c in cmds)
    return "\n".join(lines) + "\n"


def _format_table(rows):
    """Build a GitHub-flavored markdown table from a list of tuples.
    First row is header. Returns list of strings."""
    if not rows:
        return []
    header = rows[0]
    out = ["| " + " | ".join(str(c) for c in header) + " |",
           "| " + " | ".join(":---" for _ in header) + " |"]
    for row in rows[1:]:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return out


def _per_ticker_rows(orders):
    """Build per-ticker action table. Returns header + rows as list of tuples."""
    if not orders:
        return []
    header = ("Action", "Support", "Old $", "New $", "Δ%", "Shares", "Note")
    rows = [header]
    for o in orders:
        action = o["action"]
        support = f"${o.get('support_price', '—')}" if "support_price" in o else "—"
        old_p = f"${o.get('old_price', '—')}" if "old_price" in o else "—"
        new_p = f"${o.get('new_price', o.get('fill_price', '—'))}" if any(
            k in o for k in ("new_price", "fill_price")
        ) else "—"
        delta = f"{o.get('delta_pct', 0):.1f}%" if "delta_pct" in o else "—"
        shares = _format_shares(o)
        note = o.get("reason", "")
        rows.append((action, support, old_p, new_p, delta, shares, note))
    return rows


def _format_shares(o):
    if "new_shares" in o and "old_shares" in o and o["new_shares"] != o["old_shares"]:
        return f"{o['old_shares']} → {o['new_shares']}"
    if "old_shares" in o:
        return str(o["old_shares"])
    if "new_shares" in o:
        return str(o["new_shares"])
    return "—"


def _order_to_broker_cmd(ticker, o):
    """Build copy-paste instruction. Returns None if no action required."""
    action = o["action"]
    if action in ("UNCHANGED", "FILLED", "ADD"):
        # UNCHANGED: no action. FILLED: broker already handled. ADD: optional.
        if action == "ADD":
            return (f"(optional ADD) {ticker} BUY {o['new_shares']} @ ${o['new_price']}")
        return None
    if action == "CANCEL":
        return f"Cancel {ticker} BUY {o['old_shares']} @ ${o['old_price']}"
    if action == "MOVE":
        return (f"Cancel {ticker} BUY {o['old_shares']} @ ${o['old_price']} · "
                f"Place {ticker} BUY {o.get('new_shares', o['old_shares'])} "
                f"@ ${o['new_price']}")
    if action == "RESIZE":
        tier_before = o.get("tier_before")
        tier_after = o.get("tier_after")
        tier_suffix = ""
        if tier_before and tier_after:
            tier_suffix = f" (tier {tier_before}→{tier_after})"
        elif tier_after:
            tier_suffix = f" (tier ?→{tier_after})"
        return (f"Adjust {ticker} BUY shares: {o['old_shares']} → {o['new_shares']} "
                f"@ ${o['old_price']}{tier_suffix}")
    if action == "CANCELLED":
        return None  # informational
    if action in ("ORPHAN", "WICK_MISSING"):
        return None  # shown in section header
    return None
```

### 2.8 Archive + prune

```python
def _archive_copy(report, md_content):
    ARCHIVE_DIR.mkdir(exist_ok=True)
    date_key = datetime.now().strftime("%Y-%m-%d")
    (ARCHIVE_DIR / f"{date_key}.json").write_text(
        json.dumps(report, indent=2, default=str)
    )
    (ARCHIVE_DIR / f"{date_key}.md").write_text(md_content)


def _prune_archive():
    if not ARCHIVE_DIR.exists():
        return
    cutoff = time.time() - ARCHIVE_RETENTION_DAYS * 86400
    for pattern in ("*.json", "*.md"):
        for f in ARCHIVE_DIR.glob(pattern):
            if f.stat().st_mtime < cutoff:
                f.unlink()
```

### 2.9 CLI entry point

```python
def main():
    parser = argparse.ArgumentParser(
        description="Bullet drift reporter: diff pre/post wick refresh for pending BUY orders."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Write outputs to /tmp/ instead of repo paths. For testing."
    )
    args = parser.parse_args()
    report = generate_drift_report(dry_run=args.dry_run)
    status = report.get("status", "OK")
    print(f"Drift report: status={status}, "
          f"tickers={len(report.get('tickers', {}))}")
    if args.dry_run:
        print("Dry-run output written to /tmp/bullet_drift_report.{json,md}")


if __name__ == "__main__":
    main()
```

---

## Step 3 — Wire into `weekly_reoptimize.py`

**File:** `tools/weekly_reoptimize.py`.

### 3.1 STEP 0 loop modifications

Add import at top of file (near existing imports):
```python
from bullet_drift_report import write_before_snapshot, generate_drift_report
```

**Before** the STEP 0 loop at line 601, initialize the data cache (insert at line 600 or nearby, before the for-loop):
```python
_before_snapshot_buffer = {}  # ticker → data dict, populated during wick refresh
```

**Inside** the loop, after `data, err = analyze_stock_data(...)` at line 610 and before `_write_cache(...)` at line 613, add:
```python
if data is not None:
    _before_snapshot_buffer[tk] = data
```

**After** the loop completes (after the existing STEP 0 block concludes, before next step starts), add:
```python
# Capture bullet-drift snapshot before moving on to later steps
try:
    write_before_snapshot(_tracked, _port.get("pending_orders", {}),
                          _before_snapshot_buffer)
except Exception as e:
    print(f"  *** Bullet snapshot capture FAILED (non-fatal): {e}\n", flush=True)
```

### 3.2 Post-tournament drift report

Add after `step_tournament()` call (lines 764-768) and after `timings["tournament"] = tour_t`:
```python
# STEP 12: Bullet drift report
_t_drift = time.time()
try:
    drift = generate_drift_report()
    status = drift.get("status", "OK")
    elapsed = time.time() - _t_drift
    print(f"STEP 12: Drift report — status={status} in {elapsed:.1f}s", flush=True)
    timings["drift_report"] = elapsed
except Exception as e:
    print(f"STEP 12: Drift report FAILED — {e}", flush=True)
    timings["drift_report"] = 0
```

---

## Step 4 — Wire into `morning_compiler.py`

**File:** `tools/morning_compiler.py`.

### 4.1 Imports + constants + helper

Add to imports at top of `morning_compiler.py` (the file currently imports only `json, re, sys, Path`):
```python
import time
```

Add constants near top (after imports). `morning_compiler.py` does not currently define `DATA_DIR`, so either add it or use `PROJECT_ROOT` inline:
```python
BULLET_DRIFT_PATH = PROJECT_ROOT / "data" / "bullet_drift_report.json"
BULLET_DRIFT_MAX_AGE_DAYS = 7
```

Add helper function (insert before `build_output(...)` or equivalent top-level assembler — near line 540 where `output_parts` is initialized):
```python
def build_broker_actions_section():
    """Read bullet drift report and build a compact markdown subsection.
    Returns None if report missing or stale."""
    if not BULLET_DRIFT_PATH.exists():
        return None
    age_s = time.time() - BULLET_DRIFT_PATH.stat().st_mtime
    if age_s > BULLET_DRIFT_MAX_AGE_DAYS * 86400:
        return None
    try:
        data = json.loads(BULLET_DRIFT_PATH.read_text())
    except Exception:
        return None
    if data.get("schema_version") != 1:
        return None

    lines = [f"\n## Broker Actions — Bullet Drift "
             f"(weekly report, {age_s/86400:.0f}d old)\n"]
    any_action = False
    for ticker, entry in sorted(data.get("tickers", {}).items()):
        if entry.get("status") != "OK":
            continue
        actionable = [o for o in entry.get("orders", [])
                      if o.get("action") in ("MOVE", "CANCEL", "RESIZE", "ADD")]
        if not actionable:
            continue
        any_action = True
        lines.append(f"### {ticker}")
        for o in actionable:
            action = o["action"]
            if action == "MOVE":
                lines.append(f"- **MOVE**: cancel ${o['old_price']} → place ${o['new_price']}")
            elif action == "CANCEL":
                lines.append(f"- **CANCEL** @ ${o['old_price']} — {o.get('reason', '')}")
            elif action == "RESIZE":
                lines.append(f"- **RESIZE** @ ${o['old_price']}: shares "
                             f"{o['old_shares']} → {o['new_shares']}")
            elif action == "ADD":
                lines.append(f"- **ADD** (optional): BUY {o['new_shares']} "
                             f"@ ${o['new_price']}")
    if not any_action:
        return None
    return "\n".join(lines)
```

### 4.2 Append to output_parts

In the main assembler (the section between `output_parts = []` at line 541 and `merged = "\n".join(output_parts)` at line 627), append the broker section **before** the merge call. Concretely, insert at line 625 (or just before line 627):
```python
broker_section = build_broker_actions_section()
if broker_section:
    output_parts.append(broker_section)
```

Condensed path at `condensed_parts` (line 665+) is independent. Skipping condensed injection for now — raw file is what agents consume; condensed is for human skimming and doesn't need to carry the drift actions yet. Out of scope for this PR.

---

## Step 5 — Tests (`tests/test_bullet_drift_report.py`)

New file. Cover:

```python
class TestClassification:
    def test_unchanged(self): ...
    def test_move_small_drift(self): ...       # dist 1%
    def test_move_boundary(self): ...          # dist 4.9% (just under 5%)
    def test_cancel_over_drift(self): ...      # dist 5.5%
    def test_cancel_skip_tier(self): ...
    def test_resize_tier_change(self): ...
    def test_add_new_place(self): ...

class TestMatching:
    def test_note_support_parsed(self): ...
    def test_note_unparseable_fallback_to_price(self): ...
    def test_both_match_strategies_fail(self): ...  # becomes CANCELLED
    def test_merged_away_matched_via_merged_from(self): ...
    def test_tie_break_by_hold_rate(self): ...

class TestMissingOrder:
    def test_filled_within_window(self): ...
    def test_filled_outside_window_becomes_cancelled(self): ...
    def test_cancelled_no_matching_trade(self): ...

class TestSchemaGuard:
    def test_reader_raises_on_version_mismatch(self): ...

class TestTickerSets:
    def test_orphan_emits_orphan_rows(self): ...
    def test_all_filled_orders_filter_out(self): ...

class TestArchive:
    def test_prune_old_files(self): ...
    def test_keep_recent_files(self): ...
    def test_archive_both_json_and_md(self): ...
```

Fixture pattern: synthesize snapshot JSON + trade_history + pending_orders dicts, monkeypatch `yf.download` and `analyze_stock_data`, call `generate_drift_report(dry_run=True)`, assert expected rows.

---

## Step 6 — Manual verification

1. **Dry-run on current state:**
   ```bash
   python3 tools/bullet_drift_report.py --dry-run
   ```
   Outputs go to `/tmp/bullet_drift_report.{json,md}`. Verify report renders for current watchlist.

2. **Runtime timing:** instrument the STEP 12 block to log actual elapsed. Target < 30s for 20 tickers at 8 workers.

3. **Saturday cron test:** wait for next `weekly_reoptimize.py` run. Inspect `bullet_drift_report.md`. Spot-check MOVE/CANCEL/RESIZE/ADD counts against git diff of affected `wick_analysis.md` files.

---

## Dependencies / risks

- **`yf.download` double-fetch in drift report** — snapshot caches `data` from STEP 0's already-fetched `hist`. Drift report re-fetches `hist` in `_drift_one` per ticker. 20 redundant downloads ≈ 10-20s. Could be optimized in a follow-up by caching hist across the pipeline.
- **`portfolio.json` read atomicity** — snapshot reads `pending_orders` at one moment. Concurrent `cmd_fill` from another shell could cause torn reads. Existing codebase pattern; out of scope.
- **`merge_convergent_levels` refactor side effects** — adds `merged_from` field (additive). Only caller at bullet_recommender.py:359 uses the merged list; doesn't inspect the new field. Verify by running full test suite post-change.

## Out of scope
- velocity_pending, bounce_pending drift (separate strategies).
- Daily price-drift detection (only weekly).
- Auto-execution of broker cancels (flag-only).
- Condensed morning-briefing drift injection.

## Execution order (task list)

1. **Modify `merge_convergent_levels`** in `bullet_recommender.py` — add `merged_from` field.
2. Run full existing test suite — confirm no regressions.
3. **Write `tools/bullet_drift_report.py`** — module + CLI.
4. **Write `tests/test_bullet_drift_report.py`** — coverage of all paths.
5. **Wire snapshot capture** into `weekly_reoptimize.py` STEP 0 loop + post-loop call.
6. **Wire drift report** into `weekly_reoptimize.py` post-tournament.
7. **Wire `build_broker_actions_section`** into `morning_compiler.py`.
8. **Dry-run** end-to-end on current portfolio state.
9. **Time runtime**; adjust workers if > 30s.
10. Commit + let Saturday cron validate.
