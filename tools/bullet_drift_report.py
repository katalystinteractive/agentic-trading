"""Bullet drift reporter — diff pre/post wick refreshes to flag stale broker orders.

Two-hook design that wires into weekly_reoptimize.py:
  1. `write_before_snapshot()` — captured inside STEP 0 wick loop (per-ticker `data`
     dicts collected into a cache, then written to data/bullet_snapshot_before.json).
  2. `generate_drift_report()` — called after STEP 11 tournament. Reads the
     freshly written tickers/<ticker>/wick_analysis.md per ticker, diffs
     against before-snapshot, emits
     bullet_drift_report.{md,json} plus archived copies.

Classification:
  - UNCHANGED — matched level, |new_buy - old_price| <= MATCH_TOLERANCE (0.5%), tier unchanged
  - MOVE      — matched level, dist in (0.5%, DRIFT_TOLERANCE=5%]
  - CANCEL    — no match within 0.5% (including merged_from fallback) OR matched level
                effective_tier == Skip OR dist > 5%
  - RESIZE    — matched, dist <= 0.5%, tier changed Full↔Std↔Half
  - ADD       — new >>Place level without any matching pending order
  - FILLED    — order missing from after; trade_history shows a matching BUY in the window
  - CANCELLED — order missing from after; no matching trade (absence is the only signal)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from bullet_recommender import (
    CONVERGENCE_TOLERANCE,
    DRIFT_TOLERANCE,
    merge_convergent_levels,
)
from shared_constants import MATCH_TOLERANCE

PROJECT_ROOT = _TOOLS_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
SNAPSHOT_PATH = DATA_DIR / "bullet_snapshot_before.json"
REPORT_JSON = DATA_DIR / "bullet_drift_report.json"
REPORT_MD = PROJECT_ROOT / "bullet_drift_report.md"
ARCHIVE_DIR = DATA_DIR / "bullet_drift_history"
ARCHIVE_RETENTION_DAYS = 28
SCHEMA_VERSION = 1
DRIFT_WORKERS = 1

NOTE_PRICE_RE = re.compile(r"—\s+\$?([\d.]+)\s+([A-Za-z+]+)")
TIER_IN_NOTE_RE = re.compile(r"\b(Full|Std|Half|Skip)\s+tier")
CURRENT_PRICE_RE = re.compile(r"\*\*Current Price:\s+\$([\d,]+(?:\.\d+)?)\*\*")


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def _extract_level_fields(level: dict) -> dict:
    return {
        "support_price": level["support_price"],
        "source": level["source"],
        "recommended_buy": level["recommended_buy"],
        "effective_tier": level.get("effective_tier", level["tier"]),
        "hold_rate": level["hold_rate"],
        "zone": level["zone"],
        "merged_from": level.get("merged_from", []),
    }


def _extract_plan_fields(plan_entry: dict) -> dict:
    return {
        "support_price": plan_entry["support_price"],
        "buy_at": plan_entry["buy_at"],
        "tier": plan_entry["tier"],
        "shares": plan_entry["shares"],
        "zone": plan_entry["zone"],
    }


def write_before_snapshot(tracked_tickers, pending_orders_all, data_cache,
                          snapshot_path: Path | None = None) -> dict:
    """Assemble and write snapshot. Called after STEP 0 wick loop completes.

    Arguments:
        tracked_tickers    : iterable of tickers weekly_reoptimize STEP 0 refreshed.
        pending_orders_all : portfolio.json["pending_orders"] dict.
        data_cache         : {ticker: data_dict from analyze_stock_data} collected
                             during the STEP 0 loop.
        snapshot_path      : override for dry-run/testing.
    """
    now = time.time()
    orders_tickers = {
        t for t, orders in pending_orders_all.items()
        if any(o.get("filled") is not True for o in orders)
    }
    tracked_set = set(tracked_tickers)
    snapshot_set = tracked_set & orders_tickers
    orphan_set = orders_tickers - tracked_set

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_ts": now,
        "tickers": {},
    }

    for ticker in sorted(snapshot_set):
        data = data_cache.get(ticker)
        if data is None:
            snapshot["tickers"][ticker] = {
                "status": "WICK_MISSING",
                "reason": "data_cache missing entry for ticker",
                "pending_orders": [dict(o) for o in pending_orders_all[ticker]],
            }
            continue
        # Apply merge to expose merged_from for later matching.
        # Filter out levels with no recommended_buy (Skip tier + no holds) —
        # they can't match any pending order and crash the merge comparator.
        raw_levels = [dict(lvl) for lvl in data.get("levels", [])
                      if lvl.get("recommended_buy") is not None]
        merged_levels, _ = merge_convergent_levels(raw_levels)
        plan = data.get("bullet_plan") or {}
        plan_flat = (plan.get("active") or []) + (plan.get("reserve") or [])
        snapshot["tickers"][ticker] = {
            "status": "OK",
            "current_price": data.get("current_price"),
            "levels": [_extract_level_fields(l) for l in merged_levels],
            "bullet_plan": [_extract_plan_fields(p) for p in plan_flat],
            "pending_orders": [dict(o) for o in pending_orders_all[ticker]],
        }

    for ticker in sorted(orphan_set):
        live = [o for o in pending_orders_all[ticker] if o.get("filled") is not True]
        snapshot["tickers"][ticker] = {
            "status": "ORPHAN",
            "reason": "ticker not in weekly_reoptimize tracked set",
            "pending_orders": live,
        }

    target = snapshot_path or SNAPSHOT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(snapshot, indent=2, default=str))
    return snapshot


# ---------------------------------------------------------------------------
# Drift report
# ---------------------------------------------------------------------------


def generate_drift_report(dry_run: bool = False,
                          snapshot_path: Path | None = None) -> dict:
    """Read snapshot, diff against fresh per-ticker wick markdown, write reports."""
    source = snapshot_path or SNAPSHOT_PATH
    if not source.exists():
        return {"status": "NO_SNAPSHOT", "message": f"missing {source}"}

    before = json.loads(source.read_text())
    if before.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"schema_version mismatch in {source}: expected {SCHEMA_VERSION}, "
            f"got {before.get('schema_version')}"
        )

    snapshot_ts = before.get("snapshot_ts", 0.0)
    report_ts = time.time()

    trade_history_path = PROJECT_ROOT / "trade_history.json"
    if trade_history_path.exists():
        trade_history = json.loads(trade_history_path.read_text()).get("trades", [])
    else:
        trade_history = []

    report = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_ts": snapshot_ts,
        "report_ts": report_ts,
        "tickers": {},
    }

    drift_work = {}
    for ticker, entry in before.get("tickers", {}).items():
        status = entry.get("status")
        if status == "ORPHAN":
            report["tickers"][ticker] = {
                "status": "ORPHAN",
                "reason": entry.get("reason", ""),
                "orders": [
                    {"action": "ORPHAN", "old_price": o.get("price"),
                     "old_shares": o.get("shares"), "note": o.get("note", "")}
                    for o in entry.get("pending_orders", [])
                ],
            }
        elif status == "WICK_MISSING":
            report["tickers"][ticker] = {
                "status": "WICK_MISSING",
                "reason": entry.get("reason", ""),
                "orders": [
                    {"action": "WICK_MISSING", "old_price": o.get("price"),
                     "old_shares": o.get("shares"), "note": o.get("note", "")}
                    for o in entry.get("pending_orders", [])
                ],
            }
        else:
            drift_work[ticker] = entry

    for ticker, entry in drift_work.items():
        try:
            report["tickers"][ticker] = _drift_one(
                ticker, entry, trade_history, snapshot_ts, report_ts
            )
        except Exception as exc:
            report["tickers"][ticker] = {
                "status": "ERROR",
                "reason": f"{type(exc).__name__}: {exc}",
                "orders": [],
            }

    md_content = render_markdown(report)

    if dry_run:
        tmp_json = Path("/tmp/bullet_drift_report.json")
        tmp_md = Path("/tmp/bullet_drift_report.md")
        tmp_json.write_text(json.dumps(report, indent=2, default=str))
        tmp_md.write_text(md_content)
        return report

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, default=str))
    REPORT_MD.write_text(md_content)
    _archive_copy(report, md_content)
    _prune_archive()
    return report


def _drift_one(ticker: str, before_entry: dict, trade_history: list,
               snapshot_ts: float, report_ts: float) -> dict:
    """Compute drift for one ticker."""
    wick_path = _wick_analysis_path(ticker)
    if not wick_path.exists():
        return {
            "status": "WICK_MISSING",
            "reason": f"missing {wick_path}",
            "orders": [
                {"action": "WICK_MISSING", "old_price": o.get("price"),
                 "old_shares": o.get("shares"), "note": o.get("note", "")}
                for o in before_entry.get("pending_orders", [])
            ],
        }

    after_data = _parse_wick_analysis(wick_path)
    if after_data is None:
        return {
            "status": "WICK_MISSING",
            "reason": f"could not parse {wick_path}",
            "orders": [
                {"action": "WICK_MISSING", "old_price": o.get("price"),
                 "old_shares": o.get("shares"), "note": o.get("note", "")}
                for o in before_entry.get("pending_orders", [])
            ],
        }

    after_levels_raw = [dict(lvl) for lvl in after_data.get("levels", [])
                        if lvl.get("recommended_buy") is not None]
    after_levels, _ = merge_convergent_levels(after_levels_raw)
    after_plan_raw = after_data.get("bullet_plan") or {}
    after_plan_flat = (after_plan_raw.get("active") or []) + (after_plan_raw.get("reserve") or [])

    orders_report = []
    live_before = [o for o in before_entry.get("pending_orders", [])
                   if o.get("filled") is not True]

    matched_plan_supports = []

    for order in live_before:
        note_support = _parse_note_support(
            order.get("note", ""), reference_price=order.get("price")
        )
        match_level = None
        if note_support is not None:
            match_level = _find_level_by_support(
                after_levels, note_support, check_merged_from=True
            )
        if match_level is None:
            match_level = _find_level_by_support(
                after_levels, order.get("price", 0.0), check_merged_from=True
            )

        if match_level is None:
            orders_report.append(_classify_missing(
                ticker, order, trade_history, snapshot_ts, report_ts
            ))
            continue

        plan_match = _find_plan_entry_by_support(
            after_plan_flat, match_level["support_price"]
        )
        if plan_match is not None:
            matched_plan_supports.append(plan_match["support_price"])
        orders_report.append(_classify_drift(order, match_level, plan_match))

    # ADD detection: plan entries without a matching pending order
    for plan_entry in after_plan_flat:
        if not plan_entry.get("buy_at"):
            continue
        sp = plan_entry["support_price"]
        if not sp:
            continue
        already_matched = any(
            abs(sp - ms) / sp <= CONVERGENCE_TOLERANCE for ms in matched_plan_supports
        )
        if already_matched:
            continue
        has_price_match = any(
            abs(o.get("price", 0) - plan_entry["buy_at"]) / plan_entry["buy_at"]
            <= CONVERGENCE_TOLERANCE
            for o in live_before
        )
        if has_price_match:
            continue
        orders_report.append({
            "action": "ADD",
            "support_price": sp,
            "new_price": plan_entry["buy_at"],
            "new_tier": plan_entry["tier"],
            "new_shares": plan_entry["shares"],
            "zone": plan_entry["zone"],
        })

    return {
        "status": "OK",
        "current_price": after_data.get("current_price"),
        "orders": orders_report,
    }


# ---------------------------------------------------------------------------
# Wick markdown parsing
# ---------------------------------------------------------------------------


def _wick_analysis_path(ticker: str) -> Path:
    return PROJECT_ROOT / "tickers" / ticker.upper() / "wick_analysis.md"


def _parse_wick_analysis(path: Path) -> dict | None:
    """Parse the freshly written wick_analysis.md into drift-report fields."""
    text = path.read_text(encoding="utf-8")
    current = _parse_current_price(text)
    levels = _parse_support_table(text)
    plan = _parse_bullet_plan_table(text)
    if current is None or not levels:
        return None
    return {
        "current_price": current,
        "levels": levels,
        "bullet_plan": {"active": plan},
    }


def _parse_current_price(text: str) -> float | None:
    match = CURRENT_PRICE_RE.search(text)
    if not match:
        return None
    return _parse_number(match.group(1))


def _parse_support_table(text: str) -> list[dict]:
    rows = _parse_markdown_table_after(
        text, "### Support Levels & Buy Recommendations"
    )
    levels = []
    for row in rows:
        support = _parse_money(row.get("Support"))
        buy_at = _parse_money(row.get("Buy At"))
        if support is None:
            continue
        tier = (row.get("Tier") or "").strip()
        levels.append({
            "support_price": support,
            "source": (row.get("Source") or "").strip(),
            "recommended_buy": buy_at,
            "tier": tier,
            "effective_tier": tier,
            "hold_rate": _parse_percent(row.get("Hold Rate")) or 0.0,
            "zone": (row.get("Zone") or "").strip(),
            "merged_from": [],
        })
    return levels


def _parse_bullet_plan_table(text: str) -> list[dict]:
    rows = _parse_markdown_table_after(text, "### Suggested Bullet Plan")
    plan = []
    for row in rows:
        support = _parse_money(row.get("Level"))
        buy_at = _parse_money(row.get("Buy At"))
        if support is None or buy_at is None:
            continue
        plan.append({
            "support_price": support,
            "buy_at": buy_at,
            "tier": (row.get("Tier") or "").strip(),
            "shares": _parse_number(row.get("Shares")) or 0,
            "zone": (row.get("Zone") or "").strip(),
        })
    return plan


def _parse_markdown_table_after(text: str, heading: str) -> list[dict]:
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == heading)
    except StopIteration:
        return []

    table_lines = []
    for line in lines[start + 1:]:
        stripped = line.strip()
        if stripped.startswith("### "):
            break
        if stripped.startswith("|"):
            table_lines.append(stripped)
        elif table_lines and stripped:
            break

    if len(table_lines) < 3:
        return []
    headers = _split_md_row(table_lines[0])
    rows = []
    for line in table_lines[2:]:
        cells = _split_md_row(line)
        if len(cells) != len(headers):
            continue
        rows.append(dict(zip(headers, cells)))
    return rows


def _split_md_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _parse_money(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"\$([\d,]+(?:\.\d+)?)", value)
    if not match:
        return None
    return _parse_number(match.group(1))


def _parse_percent(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"(-?[\d,]+(?:\.\d+)?)%", value)
    if not match:
        return None
    return _parse_number(match.group(1))


def _parse_number(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


def _classify_drift(order: dict, match_level: dict, plan_entry: dict | None) -> dict:
    old_price = order["price"]
    new_price = match_level["recommended_buy"]
    if old_price == 0:
        dist = float("inf")
    else:
        dist = abs(new_price - old_price) / old_price
    tier_before = _tier_from_order_note(order.get("note", ""))
    tier_after = match_level.get("effective_tier") or match_level.get("tier")
    new_shares = plan_entry["shares"] if plan_entry else None

    if tier_after == "Skip":
        return {
            "action": "CANCEL",
            "reason": "tier demoted to Skip",
            "support_price": match_level["support_price"],
            "old_price": old_price,
            "old_shares": order.get("shares"),
        }
    if dist > DRIFT_TOLERANCE:
        return {
            "action": "CANCEL",
            "reason": f"buy_at drifted {dist * 100:.1f}% (> {DRIFT_TOLERANCE * 100:.0f}%)",
            "support_price": match_level["support_price"],
            "old_price": old_price,
            "new_price": new_price,
            "old_shares": order.get("shares"),
        }
    if dist <= MATCH_TOLERANCE and tier_before == tier_after:
        return {
            "action": "UNCHANGED",
            "support_price": match_level["support_price"],
            "old_price": old_price,
            "new_price": new_price,
        }
    if dist <= MATCH_TOLERANCE and tier_before != tier_after:
        return {
            "action": "RESIZE",
            "support_price": match_level["support_price"],
            "old_price": old_price,
            "old_shares": order.get("shares"),
            "new_shares": new_shares,
            "tier_before": tier_before,
            "tier_after": tier_after,
        }
    return {
        "action": "MOVE",
        "support_price": match_level["support_price"],
        "old_price": old_price,
        "new_price": new_price,
        "delta_pct": dist * 100,
        "old_shares": order.get("shares"),
        "new_shares": new_shares,
        "tier_before": tier_before,
        "tier_after": tier_after,
    }


def _classify_missing(ticker: str, order: dict, trade_history: list,
                      snapshot_ts: float, report_ts: float) -> dict:
    for trade in trade_history:
        if trade.get("ticker") != ticker:
            continue
        if trade.get("side") != "BUY":
            continue
        if not _trade_date_overlaps_window(trade.get("date", ""), snapshot_ts, report_ts):
            continue
        order_price = order.get("price", 0) or 0
        if order_price == 0:
            continue
        if abs(trade.get("price", 0) - order_price) / order_price <= MATCH_TOLERANCE:
            return {
                "action": "FILLED",
                "old_price": order_price,
                "old_shares": order.get("shares"),
                "fill_price": trade.get("price"),
                "fill_date": trade.get("date"),
            }
    return {
        "action": "CANCELLED",
        "reason": "absent from after-snapshot and no matching trade in window",
        "old_price": order.get("price"),
        "old_shares": order.get("shares"),
    }


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------


def _find_level_by_support(levels: list, target_price: float,
                            check_merged_from: bool = False) -> dict | None:
    """Fuzzy match support_price within CONVERGENCE_TOLERANCE. Tie-break by hold_rate."""
    if target_price == 0:
        return None
    candidates = []
    for lvl in levels:
        sp = lvl.get("support_price", 0) or 0
        if sp > 0 and abs(sp - target_price) / target_price <= CONVERGENCE_TOLERANCE:
            candidates.append(lvl)
            continue
        if check_merged_from:
            for m in lvl.get("merged_from") or []:
                mp = m.get("price", 0) or 0
                if mp > 0 and abs(mp - target_price) / target_price <= CONVERGENCE_TOLERANCE:
                    candidates.append(lvl)
                    break
    if not candidates:
        return None
    return max(candidates, key=lambda l: l.get("hold_rate", 0) or 0)


def _find_plan_entry_by_support(plan_flat: list, target_support: float) -> dict | None:
    if target_support == 0:
        return None
    for p in plan_flat:
        sp = p.get("support_price", 0) or 0
        if sp > 0 and abs(sp - target_support) / target_support <= CONVERGENCE_TOLERANCE:
            return p
    return None


def _parse_note_support(note: str, reference_price: float | None = None) -> float | None:
    if not note:
        return None
    m = NOTE_PRICE_RE.search(note)
    if not m:
        return None
    parsed_text = m.group(1)
    try:
        parsed = float(parsed_text)
    except ValueError:
        return None
    if "$" not in m.group(0):
        parsed = _repair_shell_expanded_support(parsed_text, reference_price)
    return parsed


def _repair_shell_expanded_support(parsed_text: str,
                                   reference_price: float | None) -> float:
    """Repair `$129.79` shell-expanded to `29.79` using the order price."""
    parsed = float(parsed_text)
    if reference_price is None or reference_price < 100 or parsed >= 100:
        return parsed
    candidates = []
    for prefix in "123456789":
        candidate = float(f"{prefix}{parsed_text}")
        distance = abs(candidate - reference_price) / reference_price
        candidates.append((distance, candidate))
    distance, repaired = min(candidates, key=lambda item: item[0])
    if distance > 0.20:
        return parsed
    return repaired


def _tier_from_order_note(note: str) -> str | None:
    if not note:
        return None
    m = TIER_IN_NOTE_RE.search(note)
    return m.group(1) if m else None


def _trade_date_overlaps_window(date_str: str, snapshot_ts: float, report_ts: float) -> bool:
    """Return whether a date-only trade could have occurred during the report window."""
    try:
        trade_day = datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return False

    trade_start = trade_day.timestamp()
    trade_end = trade_day.replace(hour=23, minute=59, second=59).timestamp()
    return trade_start < report_ts and trade_end >= snapshot_ts


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------


def render_markdown(report: dict) -> str:
    def _ts(t):
        try:
            return datetime.fromtimestamp(float(t)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(t)

    lines = [
        "# Bullet Drift Report",
        f"*Generated: {_ts(report.get('report_ts', 0))} | "
        f"Snapshot: {_ts(report.get('snapshot_ts', 0))}*",
        "",
    ]

    action_keys = ("MOVE", "CANCEL", "RESIZE", "ADD", "FILLED", "CANCELLED")
    summary_header = ("Ticker",) + action_keys + ("Status",)
    summary_rows: list = [summary_header]
    for ticker, entry in sorted(report.get("tickers", {}).items()):
        status = entry.get("status", "OK")
        if status != "OK":
            summary_rows.append((ticker,) + ("-",) * len(action_keys) + (status,))
            continue
        counts = {k: 0 for k in action_keys}
        for o in entry.get("orders", []):
            if o["action"] in counts:
                counts[o["action"]] += 1
        summary_rows.append((ticker,) + tuple(str(counts[k]) for k in action_keys) + ("OK",))
    lines.extend(_format_table(summary_rows))

    for ticker, entry in sorted(report.get("tickers", {}).items()):
        lines.append(f"\n## {ticker}")
        status = entry.get("status", "OK")
        if status == "ORPHAN":
            lines.append(f"*{entry.get('reason','')}.* Manual review required at broker.")
            continue
        if status == "WICK_MISSING":
            lines.append(f"*WICK_MISSING:* {entry.get('reason','')}")
            continue
        if status == "ERROR":
            lines.append(f"*ERROR:* {entry.get('reason','')}")
            continue
        rows = _per_ticker_rows(entry.get("orders", []))
        if rows:
            lines.extend(_format_table(rows))
        cmds = [_order_to_broker_cmd(ticker, o) for o in entry.get("orders", [])]
        cmds = [c for c in cmds if c]
        if cmds:
            lines.append("\n**Copy-paste broker actions:**")
            for c in cmds:
                lines.append(f"- {c}")

    return "\n".join(lines) + "\n"


def _format_table(rows: list) -> list:
    if not rows:
        return []
    header = rows[0]
    out = ["| " + " | ".join(str(c) for c in header) + " |",
           "| " + " | ".join(":---" for _ in header) + " |"]
    for row in rows[1:]:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return out


def _per_ticker_rows(orders: list) -> list:
    if not orders:
        return []
    header = ("Action", "Support", "Old $", "New $", "Δ%", "Shares", "Note")
    rows: list = [header]
    for o in orders:
        action = o.get("action", "?")
        support = f"${o['support_price']}" if "support_price" in o and o["support_price"] is not None else "—"
        old_p = f"${o['old_price']}" if o.get("old_price") is not None else "—"
        if "new_price" in o and o["new_price"] is not None:
            new_p = f"${o['new_price']}"
        elif "fill_price" in o and o["fill_price"] is not None:
            new_p = f"${o['fill_price']}"
        else:
            new_p = "—"
        delta = f"{o['delta_pct']:.1f}%" if "delta_pct" in o else "—"
        shares = _format_shares(o)
        note = o.get("reason", "") or ""
        rows.append((action, support, old_p, new_p, delta, shares, note))
    return rows


def _format_shares(o: dict) -> str:
    if o.get("new_shares") is not None and o.get("old_shares") is not None \
            and o["new_shares"] != o["old_shares"]:
        return f"{o['old_shares']} → {o['new_shares']}"
    if o.get("old_shares") is not None:
        return str(o["old_shares"])
    if o.get("new_shares") is not None:
        return str(o["new_shares"])
    return "—"


def _order_to_broker_cmd(ticker: str, o: dict) -> str | None:
    action = o.get("action", "")
    if action == "UNCHANGED":
        return None
    if action == "FILLED":
        return None
    if action == "CANCELLED":
        return None
    if action in ("ORPHAN", "WICK_MISSING"):
        return None
    if action == "ADD":
        return (f"(optional ADD) {ticker} BUY {o.get('new_shares','?')} "
                f"@ ${o.get('new_price','?')}")
    if action == "CANCEL":
        return f"Cancel {ticker} BUY {o.get('old_shares','?')} @ ${o.get('old_price','?')}"
    if action == "MOVE":
        return (f"Cancel {ticker} BUY {o.get('old_shares','?')} "
                f"@ ${o.get('old_price','?')} · "
                f"Place {ticker} BUY {o.get('new_shares') or o.get('old_shares','?')} "
                f"@ ${o.get('new_price','?')}")
    if action == "RESIZE":
        if o.get("new_shares") is None or o.get("new_shares") == o.get("old_shares"):
            return None
        tier_before = o.get("tier_before")
        tier_after = o.get("tier_after")
        suffix = ""
        if tier_before and tier_after:
            suffix = f" (tier {tier_before}→{tier_after})"
        elif tier_after:
            suffix = f" (tier ?→{tier_after})"
        return (f"Adjust {ticker} BUY shares: {o.get('old_shares','?')} → "
                f"{o.get('new_shares','?')} @ ${o.get('old_price','?')}{suffix}")
    return None


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------


def _archive_copy(report: dict, md_content: str) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    date_key = datetime.now().strftime("%Y-%m-%d")
    (ARCHIVE_DIR / f"{date_key}.json").write_text(
        json.dumps(report, indent=2, default=str)
    )
    (ARCHIVE_DIR / f"{date_key}.md").write_text(md_content)


def _prune_archive() -> None:
    if not ARCHIVE_DIR.exists():
        return
    cutoff = time.time() - ARCHIVE_RETENTION_DAYS * 86400
    for pattern in ("*.json", "*.md"):
        for f in ARCHIVE_DIR.glob(pattern):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bullet drift reporter: diff pre/post wick refresh for pending BUY orders."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Write outputs to /tmp/ instead of repo paths."
    )
    args = parser.parse_args()
    report = generate_drift_report(dry_run=args.dry_run)
    status = report.get("status", "OK")
    tickers = len(report.get("tickers", {}))
    print(f"Drift report: status={status}, tickers={tickers}")
    if args.dry_run:
        print("Dry-run output at /tmp/bullet_drift_report.{json,md}")


if __name__ == "__main__":
    main()
