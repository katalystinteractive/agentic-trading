#!/usr/bin/env python3
"""
Morning Gatherer v2 — Sector-sharded parallel data collection.

Two-level parallel execution for scaled watchlists (100+ tickers):
  Level 1: Market + Capital Intelligence (unchanged from v1, ~90s)
  Level 2: Sector shards (8 concurrent sector workers, sequential per-ticker within each)

Delegates to morning_gatherer.py for the actual tool-running logic. This
wrapper adds sector-based sharding around the per-ticker phase.

Usage:
    python3 tools/morning_gatherer_v2.py              # sector-sharded mode
    python3 tools/morning_gatherer_v2.py --legacy      # fall back to v1 (no sharding)
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sector_registry import shard_tickers
from trading_calendar import as_of_date_label, last_trading_day, is_trading_day
from wick_offset_analyzer import sizing_description

# Re-use helpers from v1
from morning_gatherer import (
    run_tool, run_ticker_tools, load_portfolio,
    get_current_prices, get_watchlist_prices,
    extract_days_to_earnings,
    compute_bullets_used, format_price, cross_reference_fills,
)
from shared_utils import compute_days_held, compute_time_stop

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = PROJECT_ROOT / "morning-tools-raw.md"

# Concurrency settings
SECTOR_WORKERS = 8   # concurrent sector shards
REQUEST_SPACING = 0.5  # seconds between yfinance calls per worker


def _classify_tickers(positions, pending_orders, watchlist):
    """Classify tickers into active, engaged (watchlist with orders), scouting."""
    active = [t for t, p in positions.items()
              if isinstance(p.get("shares", 0), (int, float)) and p["shares"] > 0]
    engaged = []
    scouting = []
    for t in watchlist:
        if t in active:
            continue
        has_buy = any(o.get("type", "").upper() == "BUY" for o in pending_orders.get(t, []))
        if has_buy:
            engaged.append(t)
        else:
            scouting.append(t)
    return active, engaged, scouting


def _run_sector_shard(shard_name, tickers, spacing=REQUEST_SPACING):
    """Run per-ticker tools for all tickers in a sector shard.

    Args:
        shard_name: Sector group name (for logging)
        tickers: List of (ticker, tool_list) tuples
        spacing: Seconds between tool batches

    Returns:
        dict of {ticker: {tool: (output, error)}}
    """
    shard_results = {}
    for i, (ticker, tools) in enumerate(tickers):
        results = run_ticker_tools(ticker, tools)
        shard_results[ticker] = results
        if spacing > 0 and i < len(tickers) - 1:
            time.sleep(spacing)
    return shard_name, shard_results


def run_market_and_capital(data):
    """Run market-level and capital intelligence tools (Level 1).

    Returns: (market_output, portfolio_output, cap_intel_results, all_errors)
    """
    all_errors = []

    # Market-level tools
    print("\n[Level 1] Market + Capital Intelligence...")
    market_output, market_err = run_tool("market_pulse.py")
    if market_err:
        all_errors.append(market_err)
        print(f"  market_pulse: {market_err}")
    else:
        print("  market_pulse: OK")

    portfolio_output, portfolio_err = run_tool("portfolio_status.py")
    if portfolio_err:
        all_errors.append(portfolio_err)
        print(f"  portfolio_status: {portfolio_err}")
    else:
        print("  portfolio_status: OK")

    # Capital Intelligence tools (parallel)
    print("  Running Capital Intelligence tools...")
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

    ok_count = sum(1 for _, (_, e) in cap_intel_results.items() if not e)
    err_count = sum(1 for _, (_, e) in cap_intel_results.items() if e)
    print(f"  Capital Intel: {ok_count} OK, {err_count} errors")

    return market_output, portfolio_output, cap_intel_results, all_errors


def run_per_ticker_sharded(active, engaged, scouting):
    """Run per-ticker tools using sector-based sharding (Level 2+3).

    Returns: (active_results, watchlist_results, earnings_data, errors)
    """
    all_errors = []
    active_tools = ["earnings_analyzer.py", "technical_scanner.py",
                    "short_interest.py", "news_sentiment.py"]
    watchlist_tools = ["news_sentiment.py", "earnings_analyzer.py"]

    # Build ticker→tools mapping
    ticker_jobs = {}
    for t in active:
        ticker_jobs[t] = active_tools
    for t in engaged:
        ticker_jobs[t] = watchlist_tools

    if not ticker_jobs:
        return {}, {}, {}, []

    # Shard by sector
    all_tickers = list(ticker_jobs.keys())
    shards = shard_tickers(all_tickers)

    total_tickers = len(ticker_jobs)
    print(f"\n[Level 2] Sector-sharded per-ticker tools ({total_tickers} tickers, "
          f"{len(shards)} sectors, {SECTOR_WORKERS} workers)...")
    for name, tickers in sorted(shards.items()):
        print(f"  {name}: {', '.join(tickers)}")

    # Build shard work items: [(shard_name, [(ticker, tools), ...]), ...]
    shard_work = []
    for shard_name, shard_tickers_list in shards.items():
        items = [(t, ticker_jobs[t]) for t in shard_tickers_list if t in ticker_jobs]
        if items:
            shard_work.append((shard_name, items))

    # Run sector shards in parallel
    active_results = {}
    watchlist_results = {}
    earnings_data = {}
    t0 = time.monotonic()

    with ThreadPoolExecutor(max_workers=SECTOR_WORKERS) as executor:
        futures = {
            executor.submit(_run_sector_shard, name, items): name
            for name, items in shard_work
        }
        for future in as_completed(futures):
            shard_name = futures[future]
            try:
                _, shard_results = future.result()
                for ticker, results in shard_results.items():
                    # Classify into active or watchlist results
                    if ticker in active:
                        active_results[ticker] = results
                    else:
                        watchlist_results[ticker] = results

                    # Extract earnings data
                    earnings_out = results.get("earnings_analyzer.py", ("", None))[0]
                    days = extract_days_to_earnings(earnings_out)
                    earnings_data[ticker] = days

                    # Collect errors
                    for _, (_, err) in results.items():
                        if err:
                            all_errors.append(err)

                ok_ct = sum(1 for t, r in shard_results.items()
                            for _, (_, e) in r.items() if not e)
                err_ct = sum(1 for t, r in shard_results.items()
                             for _, (_, e) in r.items() if e)
                print(f"  {shard_name}: {len(shard_results)} tickers done "
                      f"({ok_ct} tools OK, {err_ct} errors)")
            except Exception as e:
                print(f"  {shard_name}: SHARD ERROR: {e}")
                all_errors.append(f"Shard {shard_name} error: {e}")

    elapsed = time.monotonic() - t0
    print(f"  Sector sharding complete: {elapsed:.0f}s")

    return active_results, watchlist_results, earnings_data, all_errors


def assemble_output(data, market_output, portfolio_output, cap_intel_results,
                    active_results, watchlist_results, earnings_data,
                    active_tickers, watchlist_with_orders, scouting,
                    all_prices, all_errors):
    """Assemble morning-tools-raw.md (same format as v1 for downstream compatibility)."""
    positions = data.get("positions", {})
    pending_orders = data.get("pending_orders", {})
    capital = data.get("capital", {})
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    today_str = last_trading_day().isoformat()

    # Position Summary
    pos_summary_rows = []
    for ticker in active_tickers:
        pos = positions[ticker]
        shares = pos["shares"]
        avg_cost = pos["avg_cost"]
        current = all_prices.get(ticker)
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
        note_short = note.split(".")[0] if note else "—"
        if note_short and "Pre-strategy" in note_short:
            note_short = note_short.replace("Pre-strategy position, ", "Pre-strategy, ")

        pos_summary_rows.append(
            f"| {ticker} | {shares} | ${avg_cost:.2f} | {format_price(current)} | {pl_str} "
            f"| {entry_date} | {days_display} | {time_stop} | {bullets} | {target_str} | {note_short} |"
        )

    # Pending Orders Detail
    pending_rows = []
    buy_count = 0
    sell_count = 0
    recorded_count = 0
    buy_by_ticker = {}
    sell_by_ticker = {}
    recorded_fills = cross_reference_fills(positions, pending_orders)

    all_orders = []
    for ticker in sorted(pending_orders.keys()):
        for order in pending_orders[ticker]:
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

        pos_info = positions.get(ticker, {})
        pos_shares = pos_info.get("shares", 0) if isinstance(pos_info.get("shares", 0), (int, float)) else 0
        active_str = f"Yes ({pos_shares} shares)" if pos_shares > 0 else "No (watchlist)"

        dte = earnings_data.get(ticker)
        dte_str = str(dte) if dte is not None else "Unknown"

        status_str = recorded_fills.get((ticker, order_price), "")
        if not status_str and order.get("filled"):
            status_str = "RECORDED"
        if status_str == "RECORDED" and order_type == "BUY":
            recorded_count += 1

        pending_rows.append(
            f"| {ticker} | {order_type} | ${order_price:.2f} | {order_shares} "
            f"| {format_price(current)} | {pct_str} | {active_str} "
            f"| {dte_str} | {status_str} | {order_note} |"
        )

    # Capital Intel outputs
    fill_prob_out = cap_intel_results.get("fill_probability", ("", ""))[0]
    cycle_phase_out = cap_intel_results.get("cycle_phase", ("", ""))[0]
    deploy_out = cap_intel_results.get("deploy", ("", ""))[0]
    cooldown_out = cap_intel_results.get("cooldown", ("", ""))[0]
    pullback_out = cap_intel_results.get("pullback", ("", ""))[0]
    loss_eval_out = cap_intel_results.get("loss_eval", ("", ""))[0]
    portfolio_opt_out = cap_intel_results.get("portfolio_opt", ("", ""))[0]

    # Velocity & Bounce
    velocity_pos = data.get("velocity_positions", {})
    bounce_pos = data.get("bounce_positions", {})
    has_velocity = any(v.get("shares", 0) > 0 for v in velocity_pos.values()) if velocity_pos else False
    has_bounce = any(v.get("shares", 0) > 0 for v in bounce_pos.values()) if bounce_pos else False

    # --- Assemble ---
    parts = []
    parts.append(f"# Morning Tools Raw Data — {today_str}\n")
    parts.append("---\n")

    parts.append("## Market Pulse Output\n")
    parts.append(f"*{now_str}*\n")
    parts.append(market_output)
    parts.append("\n---\n")

    parts.append("## Portfolio Status Output\n")
    parts.append(portfolio_output)
    parts.append("\n---\n")

    parts.append("## Position Summary\n")
    parts.append("| Ticker | Shares | Avg Cost | Current Price | P/L % | Entry Date | Days Held | Time Stop Status | Bullets Used | Target Exit | Note |")
    parts.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for row in pos_summary_rows:
        parts.append(row)
    parts.append("\n---\n")

    parts.append("## Pending Orders Detail\n")
    trading_today = is_trading_day()
    parts.append(f"*Data as of: {as_of_date_label()}. Trading day: {'Yes' if trading_today else 'No'}.*\n")
    parts.append("| Ticker | Type | Order Price | Shares | Current Price | % Below Current | Active Position | Days to Earnings | Status | Notes |")
    parts.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for row in pending_rows:
        parts.append(row)
    parts.append("\n---\n")

    parts.append("## Capital Intelligence\n")
    for out in [fill_prob_out, cycle_phase_out, deploy_out, cooldown_out,
                pullback_out, loss_eval_out, portfolio_opt_out]:
        parts.append(out or "*No output*")
        parts.append("")
    parts.append("\n---\n")

    # Per-Ticker Active (grouped by sector)
    parts.append("## Per-Ticker Active Tool Outputs\n")
    active_shards = shard_tickers(active_tickers)
    for shard_name in sorted(active_shards.keys()):
        parts.append(f"#### Sector: {shard_name}\n")
        for ticker in sorted(active_shards[shard_name]):
            parts.append(f"### {ticker}\n")
            results = active_results.get(ticker, {})

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

    # Per-Ticker Watchlist (grouped by sector)
    parts.append("## Per-Ticker Watchlist Tool Outputs\n")
    if watchlist_with_orders:
        watchlist_shards = shard_tickers(watchlist_with_orders)
        for shard_name in sorted(watchlist_shards.keys()):
            parts.append(f"#### Sector: {shard_name}\n")
            for ticker in sorted(watchlist_shards[shard_name]):
                parts.append(f"### {ticker}\n")
                results = watchlist_results.get(ticker, {})

                parts.append("#### News & Sentiment")
                parts.append(f"*Generated: {now_str}*\n")
                out, err = results.get("news_sentiment.py", ("", None))
                parts.append(out if out else (err or "*No data*"))
                parts.append("")

                parts.append("#### Earnings")
                out, err = results.get("earnings_analyzer.py", ("", None))
                parts.append(out if out else (err or "*No data*"))
                parts.append("\n---\n")

    # Scouting
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
        vel_keys = ", ".join(f"`{k}`" for k in ["velocity_positions", "velocity_pending",
                                                  "bounce_positions", "bounce_pending"])
        parts.append(f"No active velocity/bounce positions. ({vel_keys} all empty in portfolio.json)")
    parts.append("\n---\n")

    # Capital Summary
    parts.append("## Capital Summary\n")
    parts.append("| Metric | Value |")
    parts.append("| :--- | :--- |")
    deployed = sum(p["shares"] * p["avg_cost"] for p in positions.values()
                   if isinstance(p.get("shares", 0), (int, float)) and p["shares"] > 0)
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

    effective_buy_count = buy_count - recorded_count
    effective_json_buy_count = json_buy_count - recorded_count

    parts.append(f"- Total pending BUY orders in portfolio.json: **{json_buy_count}** across **{len(json_buy_tickers)}** tickers")
    parts.append(f"- Total pending BUY order rows written: **{buy_count}** ({recorded_count} RECORDED)")
    parts.append(f"- Total pending SELL orders in portfolio.json: **{json_sell_count}** across **{len(json_sell_tickers)}** tickers")
    parts.append(f"- Total pending SELL order rows written: **{sell_count}**")
    parts.append(f"- Active positions with tool data: **{len(active_tickers)}** ({', '.join(active_tickers)})")
    parts.append(f"- Watchlist tickers with tool data: **{len(watchlist_with_orders)}** ({', '.join(watchlist_with_orders)})")
    parts.append(f"- Scouting tickers: **{len(scouting)}**")

    mismatch = []
    if effective_json_buy_count != effective_buy_count:
        mismatch.append(f"BUY: json={effective_json_buy_count}, written={effective_buy_count}")
    if json_sell_count != sell_count:
        mismatch.append(f"SELL: json={json_sell_count}, written={sell_count}")
    parts.append(f"- Mismatch: **{'none' if not mismatch else '; '.join(mismatch)}**")

    if all_errors:
        parts.append(f"\n- Tool errors ({len(all_errors)}):")
        for err in all_errors:
            parts.append(f"  - {err}")
    parts.append("")

    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description="Morning Gatherer v2 — sector-sharded")
    parser.add_argument("--legacy", action="store_true",
                        help="Fall back to v1 morning_gatherer (no sharding)")
    args = parser.parse_args()

    if args.legacy:
        from morning_gatherer import main as v1_main
        v1_main()
        return

    t0 = time.monotonic()
    print("Morning Gatherer v2 — Sector-Sharded")
    print("=" * 50)

    data = load_portfolio()
    positions = data.get("positions", {})
    pending_orders = data.get("pending_orders", {})
    watchlist = data.get("watchlist", [])
    active_tickers, watchlist_with_orders, scouting = _classify_tickers(
        positions, pending_orders, watchlist)

    total = len(active_tickers) + len(watchlist_with_orders)
    print(f"Active: {len(active_tickers)}, Engaged: {len(watchlist_with_orders)}, "
          f"Scouting: {len(scouting)}, Total tools: {total}")

    # Level 1: Market + Capital Intelligence
    market_output, portfolio_output, cap_intel_results, errors_l1 = run_market_and_capital(data)

    # Parse prices
    active_prices = get_current_prices(portfolio_output)
    watchlist_prices = get_watchlist_prices(portfolio_output)
    all_prices = {**active_prices, **watchlist_prices}

    # Level 2+3: Sector-sharded per-ticker tools
    active_results, watchlist_results, earnings_data, errors_l2 = run_per_ticker_sharded(
        active_tickers, watchlist_with_orders, scouting)

    all_errors = errors_l1 + errors_l2

    # Assemble output
    print("\nAssembling morning-tools-raw.md...")
    output_text = assemble_output(
        data, market_output, portfolio_output, cap_intel_results,
        active_results, watchlist_results, earnings_data,
        active_tickers, watchlist_with_orders, scouting,
        all_prices, all_errors)

    OUTPUT.write_text(output_text, encoding="utf-8")

    elapsed = time.monotonic() - t0
    size_kb = OUTPUT.stat().st_size / 1024
    print(f"\n{'=' * 50}")
    print(f"Output: {OUTPUT} ({size_kb:.1f} KB)")
    print(f"Tickers processed: {len(active_results)} active, {len(watchlist_results)} watchlist")
    print(f"Tool errors: {len(all_errors)}")
    print(f"Elapsed: {elapsed:.0f}s")


if __name__ == "__main__":
    main()
