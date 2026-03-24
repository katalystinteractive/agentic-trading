#!/usr/bin/env python3
"""
Morning Gatherer — Runs all data collection tools and computes derived fields.

Replaces the LLM-based gatherer agent that hit context window limits when
making 52+ sequential API round-trips. This script runs all tools as
subprocesses, computes derived fields from portfolio.json, and writes
morning-tools-raw.md in under 5 minutes.

Usage: python3 tools/morning_gatherer.py
"""

import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

from trading_calendar import as_of_date_label, last_trading_day, is_trading_day
from shared_constants import MATCH_TOLERANCE
from wick_offset_analyzer import sizing_description

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO = PROJECT_ROOT / "portfolio.json"
TOOLS_DIR = PROJECT_ROOT / "tools"
OUTPUT = PROJECT_ROOT / "morning-tools-raw.md"

# Active bullets max from capital settings (default, overridden from portfolio.json)
DEFAULT_BULLETS_MAX = 5

from shared_utils import (
    compute_days_held, compute_time_stop,
    TIME_STOP_EXCEEDED_DAYS, TIME_STOP_APPROACHING_DAYS,
)


def run_tool(tool_name, args=None, timeout=60):
    """Run a Python tool and capture stdout. Returns (stdout, error_msg)."""
    cmd = ["python3", str(TOOLS_DIR / tool_name)]
    if args:
        cmd.extend(args)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=str(PROJECT_ROOT)
        )
        if result.returncode != 0:
            err = result.stderr.strip() or f"Exit code {result.returncode}"
            return result.stdout.strip(), f"*Error running {tool_name}: {err}*"
        return result.stdout.strip(), None
    except subprocess.TimeoutExpired:
        return "", f"*Error: {tool_name} timed out after {timeout}s*"
    except Exception as e:
        return "", f"*Error running {tool_name}: {e}*"


def run_ticker_tools(ticker, tool_list):
    """Run multiple tools for a ticker in parallel. Returns dict of {tool: (output, error)}."""
    results = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {}
        for tool_name in tool_list:
            futures[executor.submit(run_tool, tool_name, [ticker])] = tool_name
        for future in as_completed(futures):
            tool_name = futures[future]
            try:
                output, error = future.result()
                results[tool_name] = (output, error)
            except Exception as e:
                results[tool_name] = ("", f"*Error: {e}*")
    return results


def load_portfolio():
    """Load and parse portfolio.json."""
    with open(PORTFOLIO) as f:
        return json.load(f)


def get_current_prices(portfolio_status_output):
    """Parse current prices from portfolio_status.py raw stdout.
    Returns dict of {ticker: price}.
    Only parses the Active Positions table — stops at the next section header
    to avoid overwriting with Watchlist Day High values.

    Note: single-phase section detection (just '# Active Positions') because
    this parses raw portfolio_status.py stdout, NOT the wrapped markdown in
    morning-tools-raw.md. See morning_compiler.parse_active_positions() for
    the two-phase version that navigates the '## Portfolio Status Output' wrapper."""
    prices = {}
    in_active = False
    for line in portfolio_status_output.split("\n"):
        stripped = line.strip()
        if "Active Positions" in stripped and stripped.startswith("#"):
            in_active = True
            continue
        if in_active and stripped.startswith("#"):
            break
        if in_active and stripped.startswith("|") and not stripped.startswith("| Ticker") and not stripped.startswith("| :"):
            parts = [p.strip() for p in stripped.split("|")]
            if len(parts) >= 5:
                ticker = parts[1].strip()
                price_str = parts[4].strip().replace("$", "").replace(",", "")
                try:
                    prices[ticker] = float(price_str)
                except ValueError:
                    pass
    return prices


def get_watchlist_prices(portfolio_status_output):
    """Parse current prices from Pending Orders table for watchlist tickers.
    Returns dict of {ticker: price}."""
    prices = {}
    in_pending = False
    for line in portfolio_status_output.split("\n"):
        line = line.strip()
        if "Pending Orders" in line and line.startswith("#"):
            in_pending = True
            continue
        if in_pending and line.startswith("#"):
            in_pending = False
            continue
        if in_pending and line.startswith("|") and not line.startswith("| Ticker") and not line.startswith("| :"):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 5:
                ticker = parts[1].strip()
                price_str = parts[4].strip().replace("$", "").replace(",", "")
                try:
                    if ticker not in prices:
                        prices[ticker] = float(price_str)
                except ValueError:
                    pass
    return prices


def extract_days_to_earnings(earnings_output):
    """Extract 'Days Until' from earnings_analyzer output. Returns int or None."""
    for line in earnings_output.split("\n"):
        if "Days Until" in line and "|" in line:
            parts = [p.strip() for p in line.split("|")]
            for p in parts:
                try:
                    return int(p)
                except ValueError:
                    continue
    return None


## compute_days_held and compute_time_stop are imported from shared_utils


def compute_bullets_used(bullets_raw, note, capital):
    """Compute bullets_used display string."""
    max_bullets = capital.get("active_bullets_max", DEFAULT_BULLETS_MAX)

    if isinstance(bullets_raw, int):
        result = f"{bullets_raw}/{max_bullets}"
    elif isinstance(bullets_raw, str):
        match = re.match(r"(\d+)", bullets_raw)
        if match:
            n = match.group(1)
            result = f"{n}/{max_bullets}"
            if "pre-strategy" in bullets_raw:
                result += " (pre-strategy)"
        else:
            result = f"?/{max_bullets}"
    else:
        result = f"?/{max_bullets}"

    # Check note for pool status
    if note:
        if "exhausted" in note.lower() or "active pool exhausted" in note.lower():
            result += ", pool exhausted"
        remaining = re.search(r'~?\$(\d+)\s*remaining', note)
        if remaining:
            result += f", ~${remaining.group(1)} remaining"

    return result


def format_price(price):
    """Format price with $ and 2 decimals."""
    if price is None:
        return "N/A"
    return f"${price:.2f}"


def cross_reference_fills(positions, pending_orders):
    """Cross-reference pending orders against recorded fill_prices and legacy notes.

    Checks both BUY and SELL orders:
    - BUY orders: matched against fill_prices within MATCH_TOLERANCE
    - Both types: legacy "(filled 20..." note pattern marks as RECORDED

    Returns dict of {(ticker, order_price): "RECORDED"}.
    """
    recorded = {}
    for ticker, orders in pending_orders.items():
        fill_prices = positions.get(ticker, {}).get("fill_prices", [])
        for order in orders:
            price = order.get("price", 0)
            if price == 0:
                continue
            # Legacy filled order: "(filled 20..." in note field (any type)
            if "(filled 20" in order.get("note", ""):
                recorded[(ticker, price)] = "RECORDED"
                continue
            # Check BUY orders against fill_prices
            if order.get("type", "").upper() == "BUY":
                for fp in fill_prices:
                    if fp == 0:
                        continue
                    if abs(fp - price) / price <= MATCH_TOLERANCE:
                        recorded[(ticker, price)] = "RECORDED"
                        break
    return recorded


def main():
    print("Morning Gatherer — Tool Execution Script")
    print("=" * 50)

    data = load_portfolio()
    capital = data.get("capital", {})
    positions = data.get("positions", {})
    pending_orders = data.get("pending_orders", {})
    watchlist = data.get("watchlist", [])

    # Classify tickers
    active_tickers = [t for t, p in positions.items() if isinstance(p.get("shares", 0), int) and p["shares"] > 0]
    watchlist_with_orders = []
    scouting = []
    for t in watchlist:
        if t in active_tickers:
            continue
        has_buy = any(o.get("type", "").upper() == "BUY" for o in pending_orders.get(t, []))
        if has_buy:
            watchlist_with_orders.append(t)
        else:
            scouting.append(t)

    print(f"Active: {len(active_tickers)} ({', '.join(active_tickers)})")
    print(f"Watchlist with orders: {len(watchlist_with_orders)} ({', '.join(watchlist_with_orders)})")
    print(f"Scouting: {len(scouting)} ({', '.join(scouting)})")

    all_errors = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    today_str = last_trading_day().isoformat()

    # --- Step 1: Market-level tools ---
    print("\n[1/13] Running market_pulse.py...")
    market_output, market_err = run_tool("market_pulse.py")
    if market_err:
        all_errors.append(market_err)
        print(f"  {market_err}")
    else:
        print("  OK")

    print("[2/13] Running portfolio_status.py...")
    portfolio_output, portfolio_err = run_tool("portfolio_status.py")
    if portfolio_err:
        all_errors.append(portfolio_err)
        print(f"  {portfolio_err}")
    else:
        print("  OK")

    # Parse current prices from portfolio_status output
    active_prices = get_current_prices(portfolio_output)
    watchlist_prices = get_watchlist_prices(portfolio_output)
    all_prices = {**active_prices, **watchlist_prices}

    # --- Step 1b: Capital Intelligence tools (parallel) ---
    print("[3-9/14] Running Capital Intelligence tools in parallel...")
    cap_intel_tools = {
        "fill_probability": ("fill_probability.py", 120),
        "cycle_phase": ("cycle_phase_detector.py", 60),
        "deploy": ("deployment_advisor.py", 60),
        "cooldown": ("cooldown_evaluator.py", 60),
        "pullback": ("pullback_profiler.py", 120),
        "loss_eval": ("loss_evaluator.py", 60),
        "portfolio_opt": ("portfolio_optimizer.py", 120),
    }
    cap_intel_results = {}
    with ThreadPoolExecutor(max_workers=7) as executor:
        futures = {
            executor.submit(run_tool, script, timeout=timeout): key
            for key, (script, timeout) in cap_intel_tools.items()
        }
        for future in as_completed(futures):
            key = futures[future]
            out, err = future.result()
            cap_intel_results[key] = (out, err)
            if err:
                all_errors.append(err)
                print(f"  {key}: {err}")
            else:
                print(f"  {key}: OK")
    fill_prob_out = cap_intel_results["fill_probability"][0]
    cycle_phase_out = cap_intel_results["cycle_phase"][0]
    deploy_out = cap_intel_results["deploy"][0]
    cooldown_out = cap_intel_results["cooldown"][0]
    pullback_out = cap_intel_results["pullback"][0]
    loss_eval_out = cap_intel_results["loss_eval"][0]
    portfolio_opt_out = cap_intel_results.get("portfolio_opt", ("", ""))[0]

    # --- Step 2: Per-ticker tools for active positions ---
    active_tools = ["earnings_analyzer.py", "technical_scanner.py", "short_interest.py", "news_sentiment.py"]
    active_results = {}  # {ticker: {tool: (output, error)}}
    earnings_data = {}  # {ticker: days_to_earnings}

    print(f"\n[10/14] Running per-ticker tools for {len(active_tickers)} active positions...")
    for i, ticker in enumerate(active_tickers, 1):
        print(f"  [{i}/{len(active_tickers)}] {ticker}...", end=" ", flush=True)
        results = run_ticker_tools(ticker, active_tools)
        active_results[ticker] = results
        errors = [e for _, (_, e) in results.items() if e]
        all_errors.extend(errors)
        print(f"{'OK' if not errors else f'{len(errors)} errors'}")

        # Extract days_to_earnings
        earnings_out = results.get("earnings_analyzer.py", ("", None))[0]
        days = extract_days_to_earnings(earnings_out)
        earnings_data[ticker] = days

    # --- Step 3: Per-ticker tools for watchlist ---
    watchlist_tools = ["news_sentiment.py", "earnings_analyzer.py"]
    watchlist_results = {}

    print(f"\n[11/14] Running per-ticker tools for {len(watchlist_with_orders)} watchlist tickers...")
    for i, ticker in enumerate(watchlist_with_orders, 1):
        print(f"  [{i}/{len(watchlist_with_orders)}] {ticker}...", end=" ", flush=True)
        results = run_ticker_tools(ticker, watchlist_tools)
        watchlist_results[ticker] = results
        errors = [e for _, (_, e) in results.items() if e]
        all_errors.extend(errors)
        print(f"{'OK' if not errors else f'{len(errors)} errors'}")

        earnings_out = results.get("earnings_analyzer.py", ("", None))[0]
        days = extract_days_to_earnings(earnings_out)
        earnings_data[ticker] = days

    # --- Step 4: Compute derived fields ---
    print("\n[12/14] Computing derived fields...")

    # Position Summary rows
    pos_summary_rows = []
    for ticker in active_tickers:
        pos = positions[ticker]
        shares = pos["shares"]
        avg_cost = pos["avg_cost"]
        current = active_prices.get(ticker)
        if current:
            pl_pct = (current - avg_cost) / avg_cost * 100
            pl_str = f"+{pl_pct:.1f}%" if pl_pct >= 0 else f"{pl_pct:.1f}%"
        else:
            pl_str = "N/A"

        entry_date = pos.get("entry_date", "Unknown")
        days_held, days_display, is_pre = compute_days_held(entry_date)
        time_stop = compute_time_stop(days_held, is_pre)
        bullets = compute_bullets_used(pos.get("bullets_used", 0), pos.get("note", ""), capital)

        target = pos.get("target_exit")
        target_str = format_price(target) if target else "No target (recovery)"

        note = pos.get("note", "")
        # Abbreviate note for table
        if note:
            note_short = note.split(".")[0]  # first sentence
            if "Pre-strategy" in note_short:
                note_short = note_short.replace("Pre-strategy position, ", "Pre-strategy, ")
        else:
            note_short = "—"

        pos_summary_rows.append(
            f"| {ticker} | {shares} | ${avg_cost:.2f} | {format_price(current)} | {pl_str} | {entry_date} | {days_display} | {time_stop} | {bullets} | {target_str} | {note_short} |"
        )

    # Pending Orders Detail rows
    pending_rows = []
    buy_count = 0
    sell_count = 0
    recorded_count = 0
    buy_by_ticker = {}
    sell_by_ticker = {}

    # Cross-reference fills against recorded fill_prices
    recorded_fills = cross_reference_fills(positions, pending_orders)

    # Collect all orders sorted by ticker then price
    all_orders = []
    for ticker in sorted(pending_orders.keys()):
        orders = pending_orders[ticker]
        for order in orders:
            all_orders.append((ticker, order))

    for ticker, order in all_orders:
        order_type = order.get("type", "").upper()
        order_price = order.get("price", 0)
        order_shares = order.get("shares", 0)
        order_note = order.get("note", "")
        current = all_prices.get(ticker)

        if order_type == "BUY":
            buy_count += 1
            buy_by_ticker[ticker] = buy_by_ticker.get(ticker, 0) + 1
            if current and current > 0:
                pct_below = (order_price - current) / current * 100
                pct_str = f"{pct_below:.1f}%"
            else:
                pct_str = "N/A"
        else:
            sell_count += 1
            sell_by_ticker[ticker] = sell_by_ticker.get(ticker, 0) + 1
            pct_str = "N/A"

        # Active position check
        pos_info = positions.get(ticker, {})
        pos_shares = pos_info.get("shares", 0) if isinstance(pos_info.get("shares", 0), int) else 0
        if pos_shares > 0:
            active_str = f"Yes ({pos_shares} shares)"
        else:
            active_str = "No (watchlist)"

        # Days to earnings
        dte = earnings_data.get(ticker)
        dte_str = str(dte) if dte is not None else "Unknown"

        # Status — RECORDED if fill already confirmed
        status_str = recorded_fills.get((ticker, order_price), "")
        # Check individual order's "filled" field (catches orders not in dict)
        if not status_str and order.get("filled"):
            status_str = "RECORDED"
        if status_str == "RECORDED" and order_type == "BUY":
            recorded_count += 1

        pending_rows.append(
            f"| {ticker} | {order_type} | ${order_price:.2f} | {order_shares} | {format_price(current)} | {pct_str} | {active_str} | {dte_str} | {status_str} | {order_note} |"
        )

    # --- Step 5: Velocity & Bounce ---
    print("[13/14] Checking velocity/bounce positions...")
    velocity_pos = data.get("velocity_positions", {})
    bounce_pos = data.get("bounce_positions", {})
    has_velocity = any(v.get("shares", 0) > 0 for v in velocity_pos.values()) if velocity_pos else False
    has_bounce = any(v.get("shares", 0) > 0 for v in bounce_pos.values()) if bounce_pos else False

    # --- Step 6: Assemble output ---
    print("[14/14] Writing morning-tools-raw.md...")

    parts = []
    parts.append(f"# Morning Tools Raw Data — {today_str}\n")
    parts.append("---\n")

    # Market Pulse
    parts.append("## Market Pulse Output\n")
    parts.append(f"*{now_str}*\n")
    parts.append(market_output)
    parts.append("\n---\n")

    # Portfolio Status
    parts.append("## Portfolio Status Output\n")
    parts.append(portfolio_output)
    parts.append("\n---\n")

    # Position Summary
    parts.append("## Position Summary\n")
    parts.append("| Ticker | Shares | Avg Cost | Current Price | P/L % | Entry Date | Days Held | Time Stop Status | Bullets Used | Target Exit | Note |")
    parts.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for row in pos_summary_rows:
        parts.append(row)
    parts.append("\n---\n")

    # Pending Orders Detail
    parts.append("## Pending Orders Detail\n")
    trading_today = is_trading_day()
    parts.append(f"*Data as of: {as_of_date_label()}. Trading day: {'Yes' if trading_today else 'No'}.*\n")
    parts.append("| Ticker | Type | Order Price | Shares | Current Price | % Below Current | Active Position | Days to Earnings | Status | Notes |")
    parts.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for row in pending_rows:
        parts.append(row)
    parts.append("\n---\n")

    # Capital Intelligence
    parts.append("## Capital Intelligence\n")
    parts.append(fill_prob_out or "*No output*")
    parts.append("")
    parts.append(cycle_phase_out or "*No output*")
    parts.append("")
    parts.append(deploy_out or "*No output*")
    parts.append("")
    parts.append(cooldown_out or "*No output*")
    parts.append("")
    parts.append(pullback_out or "*No output*")
    parts.append("")
    parts.append(loss_eval_out or "*No output*")
    parts.append("")
    parts.append(portfolio_opt_out or "*No output*")
    parts.append("\n---\n")

    # Per-Ticker Active Tool Outputs
    parts.append("## Per-Ticker Active Tool Outputs\n")
    for ticker in active_tickers:
        parts.append(f"### {ticker}\n")
        results = active_results[ticker]

        parts.append("#### Earnings")
        parts.append(f"*Generated: {now_str}*\n")
        out, err = results.get("earnings_analyzer.py", ("", None))
        parts.append(out if out else (err or "*No data*"))
        parts.append("")

        parts.append("#### Technical Signals")
        out, err = results.get("technical_scanner.py", ("", None))
        parts.append(out if out else (err or "*No data*"))
        parts.append("")

        parts.append("#### Short Interest")
        out, err = results.get("short_interest.py", ("", None))
        parts.append(out if out else (err or "*No data*"))
        parts.append("")

        parts.append("#### News & Sentiment")
        out, err = results.get("news_sentiment.py", ("", None))
        parts.append(out if out else (err or "*No data*"))

        parts.append("\n---\n")

    # Per-Ticker Watchlist Tool Outputs
    parts.append("## Per-Ticker Watchlist Tool Outputs\n")
    for ticker in watchlist_with_orders:
        parts.append(f"### {ticker}\n")
        results = watchlist_results[ticker]

        parts.append("#### News & Sentiment")
        parts.append(f"*Generated: {now_str}*\n")
        out, err = results.get("news_sentiment.py", ("", None))
        parts.append(out if out else (err or "*No data*"))
        parts.append("")

        parts.append("#### Earnings")
        out, err = results.get("earnings_analyzer.py", ("", None))
        parts.append(out if out else (err or "*No data*"))

        parts.append("\n---\n")

    # Scouting Tickers
    parts.append("## Scouting Tickers (No Orders)\n")
    if scouting:
        for t in scouting:
            parts.append(f"- {t}")
    else:
        parts.append("None")
    parts.append("\n---\n")

    # Velocity & Bounce
    parts.append("## Velocity & Bounce Positions\n")
    if has_velocity or has_bounce:
        if has_velocity:
            parts.append("### Velocity Positions")
            parts.append(json.dumps(velocity_pos, indent=2))
        if has_bounce:
            parts.append("### Bounce Positions")
            parts.append(json.dumps(bounce_pos, indent=2))
    else:
        vel_keys = ", ".join(f"`{k}`" for k in ["velocity_positions", "velocity_pending", "bounce_positions", "bounce_pending"])
        parts.append(f"No active velocity/bounce positions. ({vel_keys} all empty in portfolio.json)")
    parts.append("\n---\n")

    # Capital Summary
    parts.append("## Capital Summary\n")
    parts.append("| Metric | Value |")
    parts.append("| :--- | :--- |")

    # Compute deployed
    deployed = sum(p["shares"] * p["avg_cost"] for p in positions.values()
                   if isinstance(p.get("shares", 0), int) and p["shares"] > 0)
    parts.append(f"| Deployed (from portfolio_status.py) | ${deployed:,.2f} |")
    parts.append(f"| Per-Stock Total Budget | ${capital.get('per_stock_total', 600):.2f} |")
    parts.append(f"| Active Pool | ${capital.get('active_pool', 300):.2f} per stock |")
    parts.append(f"| Reserve Pool | ${capital.get('reserve_pool', 300):.2f} per stock |")
    parts.append(f"| Active Bullets Max | {capital.get('active_bullets_max', 5)} |")
    parts.append(f"| Reserve Bullets Max | {capital.get('reserve_bullets_max', 3)} |")
    desc = sizing_description()
    parts.append(f"| Sizing Method | {desc['method']} |")

    vel_cap = data.get("velocity_capital", {})
    bounce_cap = data.get("bounce_capital", {})
    parts.append(f"| Velocity Pool Total | ${vel_cap.get('total_pool', 1000):,.2f} |")
    parts.append(f"| Bounce Pool Total | ${bounce_cap.get('total_pool', 1000):,.2f} |")
    parts.append("\n---\n")

    # Cross-Check Summary
    parts.append("## Cross-Check Summary\n")

    buy_ticker_summary = ", ".join(f"{t}:{c}" for t, c in sorted(buy_by_ticker.items()))
    sell_ticker_summary = ", ".join(f"{t}:{c}" for t, c in sorted(sell_by_ticker.items()))

    # Count BUY/SELL from portfolio.json directly for verification
    json_buy_count = 0
    json_sell_count = 0
    json_buy_tickers = {}
    json_sell_tickers = {}
    for ticker, orders in pending_orders.items():
        for o in orders:
            if o.get("type", "").upper() == "BUY":
                json_buy_count += 1
                json_buy_tickers[ticker] = json_buy_tickers.get(ticker, 0) + 1
            elif o.get("type", "").upper() == "SELL":
                json_sell_count += 1
                json_sell_tickers[ticker] = json_sell_tickers.get(ticker, 0) + 1

    # Adjust counts to exclude RECORDED orders for mismatch check
    effective_buy_count = buy_count - recorded_count
    effective_json_buy_count = json_buy_count - recorded_count

    parts.append(f"- Total pending BUY orders in portfolio.json: **{json_buy_count}** across **{len(json_buy_tickers)}** tickers ({', '.join(f'{t}:{c}' for t, c in sorted(json_buy_tickers.items()))})")
    parts.append(f"- Total pending BUY order rows written: **{buy_count}** ({recorded_count} RECORDED)")
    parts.append(f"- Total pending SELL orders in portfolio.json: **{json_sell_count}** across **{len(json_sell_tickers)}** tickers ({', '.join(f'{t}:{c}' for t, c in sorted(json_sell_tickers.items()))})")
    parts.append(f"- Total pending SELL order rows written: **{sell_count}**")
    parts.append(f"- Active positions with tool data: **{len(active_tickers)}** ({', '.join(active_tickers)})")
    parts.append(f"- Watchlist tickers with tool data: **{len(watchlist_with_orders)}** ({', '.join(watchlist_with_orders)})")
    parts.append(f"- Scouting tickers (no orders): **{len(scouting)}** ({', '.join(scouting)})" if scouting else f"- Scouting tickers (no orders): **0**")

    # Mismatch check (using effective counts that exclude RECORDED orders)
    mismatch = []
    if effective_json_buy_count != effective_buy_count:
        mismatch.append(f"BUY count mismatch: portfolio.json={effective_json_buy_count}, written={effective_buy_count}")
    if json_sell_count != sell_count:
        mismatch.append(f"SELL count mismatch: portfolio.json={json_sell_count}, written={sell_count}")
    parts.append(f"- Mismatch: **{'none' if not mismatch else '; '.join(mismatch)}**")

    if all_errors:
        parts.append(f"\n- Tool errors ({len(all_errors)}):")
        for err in all_errors:
            parts.append(f"  - {err}")
    parts.append("")

    # Write output
    output_text = "\n".join(parts)
    OUTPUT.write_text(output_text, encoding="utf-8")

    size_kb = OUTPUT.stat().st_size / 1024
    print(f"\n{'=' * 50}")
    print(f"Output: {OUTPUT} ({size_kb:.1f} KB)")
    print(f"Active positions: {len(active_tickers)}")
    print(f"Watchlist tickers: {len(watchlist_with_orders)} (with pending orders)")
    print(f"Scouting: {len(scouting)} (no orders)")
    print(f"Tool errors: {len(all_errors)}")
    print(f"BUY orders: {buy_count} (json: {json_buy_count}, {recorded_count} RECORDED) {'✓' if effective_buy_count == effective_json_buy_count else '✗ MISMATCH'}")
    print(f"SELL orders: {sell_count} (json: {json_sell_count}) {'✓' if sell_count == json_sell_count else '✗ MISMATCH'}")


if __name__ == "__main__":
    main()
