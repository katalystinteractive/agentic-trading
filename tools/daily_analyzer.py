"""Daily Analyzer — consolidated session tool.

Processes fills/sells in batch, shows consolidated placed orders with
position summaries and sell targets, recommends new deployments,
evaluates watchlist fitness, and screens for new candidates.

Usage:
    python3 tools/daily_analyzer.py --fills "CIFR:14.18:8" --sells "LUNR:18.89:2"
    python3 tools/daily_analyzer.py                   # full flow: Parts 1-5 (~6-11 min)
    python3 tools/daily_analyzer.py --no-deploy       # Parts 1-2 only (quick)
    python3 tools/daily_analyzer.py --no-fitness      # Parts 1-3 only
    python3 tools/daily_analyzer.py --no-screen       # Parts 1-4 only (skip screening)
"""
import sys
import json
import re
import argparse
import subprocess
from pathlib import Path
from datetime import date

_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
COOLDOWN_PATH = _ROOT / "cooldown.json"
FITNESS_JSON_PATH = _ROOT / "watchlist-fitness.json"
SHORTLIST_JSON_PATH = _ROOT / "candidate_shortlist.json"
REMOVAL_SCORE_THRESHOLD = 50
CANDIDATE_SCORE_THRESHOLD = 80

sys.path.insert(0, str(TOOLS_DIR))
from portfolio_manager import _load, cmd_fill, cmd_sell, parse_bullets_used


# ---------------------------------------------------------------------------
# Part 1 — Process fills and sells
# ---------------------------------------------------------------------------

def parse_specs(spec_string):
    """Parse 'TICKER:PRICE:SHARES,...' → (list of tuples, parse_error_count)."""
    if not spec_string:
        return [], 0
    results = []
    errors = 0
    for item in spec_string.split(","):
        item = item.strip()
        if not item:
            continue
        parts = item.split(":")
        if len(parts) != 3:
            print(f"*Error: bad spec '{item}' — expected TICKER:PRICE:SHARES*")
            errors += 1
            continue
        ticker = parts[0].strip().upper()
        try:
            price = float(parts[1].strip())
            shares = int(parts[2].strip())
        except ValueError:
            print(f"*Error: bad spec '{item}' — price/shares not numeric*")
            errors += 1
            continue
        if shares <= 0:
            print(f"*Error: bad spec '{item}' — shares must be positive*")
            errors += 1
            continue
        results.append((ticker, price, shares))
    return results, errors


def process_transactions(fills, sells, parse_errors=0):
    """Call cmd_fill/cmd_sell for each spec with sys.exit trap."""
    if not fills and not sells and not parse_errors:
        return

    ok, fail = 0, parse_errors

    # Suppress sell_target auto-output during batch fills
    import sell_target_calculator
    _orig_analyze = sell_target_calculator.analyze_ticker
    sell_target_calculator.analyze_ticker = lambda *a, **kw: None

    for ticker, price, shares in fills:
        args = argparse.Namespace(ticker=ticker, price=price, shares=shares)
        try:
            data = _load()
            cmd_fill(data, args)
            ok += 1
            print()
        except SystemExit:
            print(f"*Error: failed to process fill {ticker}:{price}:{shares}*")
            fail += 1
            print()
        except Exception as e:
            print(f"*Error: fill {ticker}:{price}:{shares} — {e}*")
            fail += 1
            print()

    # Restore sell_target_calculator
    sell_target_calculator.analyze_ticker = _orig_analyze

    for ticker, price, shares in sells:
        args = argparse.Namespace(ticker=ticker, price=price, shares=shares)
        try:
            data = _load()
            cmd_sell(data, args)
            ok += 1
            print()
        except SystemExit:
            print(f"*Error: failed to process sell {ticker}:{price}:{shares}*")
            fail += 1
            print()
        except Exception as e:
            print(f"*Error: sell {ticker}:{price}:{shares} — {e}*")
            fail += 1
            print()

    summary = f"**Processed {ok} transaction(s)**"
    if fail:
        summary += f", **{fail} failed**"
    print(summary)
    print()


# ---------------------------------------------------------------------------
# Part 2 — Consolidated placed orders table
# ---------------------------------------------------------------------------

def truncate_note(note, max_len=45):
    """Extract label + tier from order note."""
    if not note:
        return ""
    m = re.match(
        r'((?:A\d|B\d|R\d|Bullet \d|Reserve \d).*?,\s*(?:Full|Std|Half|Skip)[\^v]?)',
        note,
    )
    if m:
        return m.group(1)
    return note[:max_len] + ("..." if len(note) > max_len else "")


def _is_active_buy(order):
    """Unfilled, placed BUY order."""
    return (
        order.get("type") == "BUY"
        and order.get("placed", False)
        and "filled" not in order
    )


def _is_active_sell(order):
    """Unfilled, placed SELL order."""
    return (
        order.get("type") == "SELL"
        and order.get("placed", False)
        and "filled" not in order
    )


def print_consolidated_orders():
    """Build and print Part 2 table from portfolio.json."""
    data = _load()
    positions = data.get("positions", {})
    pending = data.get("pending_orders", {})

    # Collect tickers to show: has shares OR has active placed orders
    tickers_to_show = set()
    for ticker, pos in positions.items():
        if pos.get("shares", 0) > 0:
            tickers_to_show.add(ticker)
    for ticker, orders in pending.items():
        for o in orders:
            if (_is_active_buy(o) or _is_active_sell(o)):
                tickers_to_show.add(ticker)
                break

    if not tickers_to_show:
        print("*No active positions or placed orders.*")
        return

    today = date.today().isoformat()
    print(f"## Placed Orders & Positions — {today} ({len(tickers_to_show)} tickers)")
    print()
    print("| Ticker | Type | Price | Shares | Note |")
    print("| :--- | :--- | :--- | :--- | :--- |")

    first_ticker = True
    for ticker in sorted(tickers_to_show):
        if not first_ticker:
            print("| — | — | — | — | — |")
        first_ticker = False

        orders = pending.get(ticker, [])
        pos = positions.get(ticker, {})
        shares = pos.get("shares", 0)
        avg_cost = pos.get("avg_cost", 0)

        # BUY rows (price descending — highest first)
        active_buys = [o for o in orders if _is_active_buy(o)]
        active_buys.sort(key=lambda o: o["price"], reverse=True)
        for o in active_buys:
            note = truncate_note(o.get("note", ""))
            print(f"| {ticker} | BUY | ${o['price']:.2f} | {o['shares']} | {note} |")

        # Position summary (only if shares > 0)
        if shares > 0:
            bu_raw = pos.get("bullets_used", 0)
            bu = parse_bullets_used(bu_raw, pos.get("note", ""))
            parts = []
            if bu["active"]:
                parts.append(f"{bu['active']}A")
            if bu["reserve"]:
                parts.append(f"R{bu['reserve']}")
            if bu["pre_strategy"]:
                parts.append("pre")
            bu_label = "+".join(parts) + " used" if parts else "0 used"
            print(
                f"| **{ticker}** | **Position** | **${avg_cost:.2f} avg** "
                f"| **{shares} sh** | **{bu_label}** |"
            )

        # SELL rows — priority: placed SELL orders → target_exit → math fallback
        sell_rows_printed = 0
        for o in orders:
            if _is_active_sell(o):
                pnl = round((o["price"] - avg_cost) / avg_cost * 100, 1) if avg_cost > 0 else 0
                sign = "+" if pnl >= 0 else ""
                print(
                    f"| **{ticker}** | **SELL** | **${o['price']:.2f}** "
                    f"| **{o['shares']}** | **{sign}{pnl}%** |"
                )
                sell_rows_printed += 1

        if sell_rows_printed == 0 and shares > 0:
            target = pos.get("target_exit")
            if target:
                pnl = round((target - avg_cost) / avg_cost * 100, 1) if avg_cost > 0 else 0
                sign = "+" if pnl >= 0 else ""
                print(
                    f"| **{ticker}** | **SELL** | **${target:.2f}** "
                    f"| **{shares}** | **target {sign}{pnl}%** |"
                )
            else:
                fallback = round(avg_cost * 1.06, 2)
                print(
                    f"| **{ticker}** | **SELL** | **${fallback:.2f}** "
                    f"| **{shares}** | **math 6.0%** |"
                )

    print()


# ---------------------------------------------------------------------------
# Part 3 — Deployment recommendations
# ---------------------------------------------------------------------------

def find_deployment_tickers():
    """Identify tickers needing new limit orders (no active placed buys, not on cooldown)."""
    data = _load()
    positions = data.get("positions", {})
    pending = data.get("pending_orders", {})
    watchlist = data.get("watchlist", [])

    # Union of watchlist + position tickers
    all_tickers = set(watchlist) | set(positions.keys())

    # Load cooldowns
    cooldown_tickers = {}  # ticker → reeval_date
    if COOLDOWN_PATH.exists():
        try:
            with open(COOLDOWN_PATH, "r", encoding="utf-8") as f:
                cd = json.load(f)
            today = date.today().isoformat()
            for entry in cd.get("cooldowns", []):
                if entry.get("reeval_date", "") > today:
                    cooldown_tickers[entry["ticker"]] = entry["reeval_date"]
        except (json.JSONDecodeError, KeyError):
            pass

    result = []
    skipped_cooldown = []
    for ticker in sorted(all_tickers):
        orders = pending.get(ticker, [])
        pos = positions.get(ticker, {})
        shares = pos.get("shares", 0)

        # Skip dead entries: no shares and no pending orders at all
        if shares == 0 and not orders:
            continue

        # Check active coverage
        has_active_buy = any(_is_active_buy(o) for o in orders)
        if has_active_buy:
            continue

        # Cooldown check — only for tickers that would otherwise need deployment
        if ticker in cooldown_tickers:
            skipped_cooldown.append(
                f"{ticker} (until {cooldown_tickers[ticker]})"
            )
            continue

        result.append(ticker)

    if skipped_cooldown:
        print(f"*Cooldown: {', '.join(skipped_cooldown)}*")
        print()

    return result


def print_deployment_recs(tickers):
    """Run bullet_recommender per ticker via subprocess."""
    if not tickers:
        print("*All tickers have active placed orders — no deployment needed.*")
        return

    print(f"## Deployment Recommendations ({len(tickers)} tickers)")
    print()

    for ticker in tickers:
        print(f"### {ticker}")
        print()
        try:
            result = subprocess.run(
                [sys.executable, str(TOOLS_DIR / "bullet_recommender.py"), ticker],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0 and result.stdout.strip():
                print(result.stdout.strip())
            else:
                if result.stdout.strip():
                    print(result.stdout.strip())
                    print()
                err = result.stderr.strip() if result.stderr.strip() else "unknown error"
                print(f"*Error running bullet_recommender for {ticker}: {err}*")
        except subprocess.TimeoutExpired:
            print(f"*Error: bullet_recommender timed out for {ticker}*")
        except Exception as e:
            print(f"*Error: {e}*")
        print()


# ---------------------------------------------------------------------------
# Part 4 — Watchlist Fitness Check
# ---------------------------------------------------------------------------

def run_watchlist_fitness():
    """Run watchlist_fitness.py, print summary, flag removal candidates."""
    print("## Part 4 — Watchlist Fitness Check")
    print()
    try:
        result = subprocess.run(
            [sys.executable, str(TOOLS_DIR / "watchlist_fitness.py")],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            print(f"*Error: watchlist_fitness.py failed: {result.stderr.strip() or 'unknown'}*")
            return
    except subprocess.TimeoutExpired:
        print("*Error: watchlist_fitness.py timed out (180s)*")
        return
    except Exception as e:
        print(f"*Error: {e}*")
        return

    if result.stdout.strip():
        print(result.stdout.strip())
        print()

    # Read JSON
    try:
        with open(FITNESS_JSON_PATH) as f:
            fitness_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"*Error reading {FITNESS_JSON_PATH.name}: {e}*")
        return

    all_tickers = fitness_data.get("tickers", [])
    print(f"*Evaluated {len(all_tickers)} tickers.*")
    print()

    # Cross-reference portfolio.json for removal check
    data = _load()
    positions = data.get("positions", {})
    pending = data.get("pending_orders", {})

    removal = []
    for entry in all_tickers:
        ticker = entry.get("ticker", "")
        score = entry.get("fitness_score")
        if score is None or score >= REMOVAL_SCORE_THRESHOLD:
            continue
        if positions.get(ticker, {}).get("shares", 0) > 0:
            continue
        if any(_is_active_buy(o) for o in pending.get(ticker, [])):
            continue
        removal.append(entry)

    if removal:
        removal.sort(key=lambda e: e["fitness_score"])
        print(f"### Removal Candidates ({len(removal)} tickers)")
        print()
        print("| Ticker | Score | Verdict | Note |")
        print("| :--- | :--- | :--- | :--- |")
        for entry in removal:
            r_ticker = entry.get("ticker", "")
            note = (entry.get("verdict_note") or "").replace("|", "-")
            if len(note) > 60:
                note = note[:60] + "..."
            verdict = (entry.get("verdict") or "").replace("|", "-")
            print(f"| {r_ticker} | {entry['fitness_score']} | {verdict} | {note} |")
        print()
    else:
        print("*No removal candidates — all tickers score >= 50 or have active positions/orders.*")
        print()


# ---------------------------------------------------------------------------
# Part 5 — New Candidate Screening
# ---------------------------------------------------------------------------

def run_candidate_screening():
    """Run screener → filter → print new strong candidates not already tracked."""
    print("## Part 5 — New Candidate Screening")
    print()
    print("*Running screener (~3-5 min)...*")
    print()

    # Step A: Screener
    try:
        result = subprocess.run(
            [sys.executable, str(TOOLS_DIR / "surgical_screener.py")],
            capture_output=True, text=True, timeout=420,
        )
        if result.returncode != 0:
            print(f"*Error: surgical_screener.py failed: {result.stderr.strip() or 'unknown'}*")
            return
    except subprocess.TimeoutExpired:
        print("*Error: surgical_screener.py timed out (420s)*")
        return
    except Exception as e:
        print(f"*Error: {e}*")
        return

    # Step B: Filter (only runs if screener succeeded)
    try:
        result = subprocess.run(
            [sys.executable, str(TOOLS_DIR / "surgical_filter.py")],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            print(f"*Error: surgical_filter.py failed: {result.stderr.strip() or 'unknown'}*")
            return
    except subprocess.TimeoutExpired:
        print("*Error: surgical_filter.py timed out (180s)*")
        return
    except Exception as e:
        print(f"*Error: {e}*")
        return

    if result.stdout.strip():
        print(result.stdout.strip())
        print()
    else:
        print("*Filter completed.*")
        print()

    # Read shortlist JSON
    try:
        with open(SHORTLIST_JSON_PATH) as f:
            shortlist_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"*Error reading {SHORTLIST_JSON_PATH.name}: {e}*")
        return

    # Build tracked set from portfolio.json
    data = _load()
    tracked = set(data.get("watchlist", [])) | set(data.get("positions", {}).keys())

    shortlist = shortlist_data.get("shortlist", [])
    print(f"*Shortlisted {len(shortlist)} tickers.*")
    print()

    new_candidates = []
    already_tracked = []
    for entry in shortlist:
        ticker = entry.get("ticker", "")
        score = entry.get("total_score", 0)
        if score < CANDIDATE_SCORE_THRESHOLD:
            continue
        if ticker in tracked:
            already_tracked.append((ticker, score))
        else:
            new_candidates.append(entry)

    if new_candidates:
        new_candidates.sort(key=lambda e: e.get("total_score", 0), reverse=True)
        print(f"### New Candidates ({len(new_candidates)} tickers, score >= {CANDIDATE_SCORE_THRESHOLD}, not tracked)")
        print()
        print("| Ticker | Score | Sector | Swing | Top Strength |")
        print("| :--- | :--- | :--- | :--- | :--- |")
        for entry in new_candidates:
            c_ticker = entry.get("ticker", "")
            c_score = entry.get("total_score", 0)
            passer = entry.get("passer") or {}
            sector = (passer.get("sector") or "—").replace("|", "-")
            swing = passer.get("median_swing")
            swing_str = f"{swing:.1f}%" if swing is not None else "—"

            # Top Strength from cycle timing
            ct = passer.get("cycle_timing") or {}
            if "total_cycles" in ct and "immediate_fill_pct" in ct:
                strength = f"{ct['total_cycles']} cycles, {ct['immediate_fill_pct']:.0f}% fill"
            else:
                flags = entry.get("flags", [])
                if flags:
                    s = str(flags[0]).replace("|", "-")
                    strength = s[:40] + ("..." if len(s) > 40 else "")
                else:
                    strength = "—"

            print(f"| {c_ticker} | {c_score} | {sector} | {swing_str} | {strength} |")
        print()
    else:
        print(f"*No new candidates scoring >= {CANDIDATE_SCORE_THRESHOLD} outside current watchlist.*")
        print()

    if already_tracked:
        already_tracked.sort(key=lambda x: x[1], reverse=True)
        labels = ", ".join(f"{t} ({s})" for t, s in already_tracked)
        print(f"*Already tracked: {labels}*")
        print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Daily Analyzer — consolidated session tool",
    )
    parser.add_argument(
        "--fills", type=str, default="",
        help='Comma-separated fill specs: "TICKER:PRICE:SHARES,..."',
    )
    parser.add_argument(
        "--sells", type=str, default="",
        help='Comma-separated sell specs: "TICKER:PRICE:SHARES,..."',
    )
    parser.add_argument(
        "--no-deploy", action="store_true",
        help="Skip Parts 3-5 (deployment, fitness, screening)",
    )
    parser.add_argument(
        "--no-fitness", action="store_true",
        help="Skip Parts 4-5 (fitness check and screening)",
    )
    parser.add_argument(
        "--no-screen", action="store_true",
        help="Skip Part 5 (new candidate screening)",
    )
    args = parser.parse_args()

    fills, fill_parse_err = parse_specs(args.fills)
    sells, sell_parse_err = parse_specs(args.sells)
    parse_errors = fill_parse_err + sell_parse_err

    # Part 1: Process transactions
    if fills or sells or parse_errors:
        print("## Part 1 — Processing Transactions")
        print()
        process_transactions(fills, sells, parse_errors)

    # Part 2: Consolidated orders
    print_consolidated_orders()

    # Part 3: Deployment recommendations
    if not args.no_deploy:
        deploy_tickers = find_deployment_tickers()
        print_deployment_recs(deploy_tickers)

    # Part 4: Watchlist Fitness Check
    if not args.no_deploy and not args.no_fitness:
        run_watchlist_fitness()

    # Part 5: New Candidate Screening
    if not args.no_deploy and not args.no_fitness and not args.no_screen:
        run_candidate_screening()


if __name__ == "__main__":
    main()
