"""Daily Analyzer — consolidated session tool.

Processes fills/sells in batch, shows consolidated placed orders with
position summaries and sell targets, analyzes per-ticker performance,
recommends new deployments, evaluates watchlist fitness, screens for
new candidates, and reconciles broker state.

Usage:
    python3 tools/daily_analyzer.py --fills "CIFR:14.18:8" --sells "LUNR:18.89:2"
    python3 tools/daily_analyzer.py                   # full flow: Parts 1-7 (~7-14 min)
    python3 tools/daily_analyzer.py --no-deploy       # Parts 1-2, 7 only (quick)
    python3 tools/daily_analyzer.py --no-perf         # Parts 1-2, 4-7 (skip perf analysis)
    python3 tools/daily_analyzer.py --no-fitness      # Parts 1-4, 7 only
    python3 tools/daily_analyzer.py --no-screen       # Parts 1-5, 7 only (skip screening)
    python3 tools/daily_analyzer.py --no-recon        # Parts 1-6 only (skip reconciliation)
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
CANDIDATES_JSON_PATH = _ROOT / "data" / "candidates.json"
UNIVERSE_CACHE_PATH = _ROOT / "data" / "universe_screen_cache.json"
REMOVAL_SCORE_THRESHOLD = 50
CANDIDATE_SCORE_THRESHOLD = 80

sys.path.insert(0, str(TOOLS_DIR))
from portfolio_manager import _load, cmd_fill, cmd_sell, parse_bullets_used
from shared_utils import is_active_buy as _is_active_buy, is_active_sell as _is_active_sell
from shared_utils import compute_days_held, compute_time_stop


# ---------------------------------------------------------------------------
# Shared infrastructure
# ---------------------------------------------------------------------------

def _fetch_position_prices(tickers):
    """Batch-fetch live prices for position tickers. Returns {ticker: price}."""
    import yfinance as yf
    if not tickers:
        return {}
    try:
        data = yf.download(list(tickers), period="5d", progress=False)
        prices = {}
        for t in tickers:
            try:
                col = data["Close"][t] if len(tickers) > 1 else data["Close"]
                val = col.dropna().iloc[-1]
                prices[t] = round(float(val), 2)
            except (KeyError, IndexError):
                pass
        return prices
    except Exception:
        return {}


def print_market_regime():
    """Part 0: Fetch and display market regime."""
    try:
        from shared_regime import fetch_regime_detail
        detail = fetch_regime_detail()
        regime = detail["regime"]
        vix = detail["vix"]
    except Exception as e:
        print(f"*Warning: Market regime fetch failed ({e}), defaulting to Neutral*\n")
        regime = "Neutral"
        vix = None

    print("## Market Regime\n")
    print("| Field | Value |")
    print("| :--- | :--- |")
    print(f"| Regime | **{regime}** |")
    if vix is not None:
        print(f"| VIX | {vix:.1f} |")

    if regime == "Risk-Off":
        print("\n*Risk-Off modifiers active: time stops +14d, sell upgrades suppressed, deployment cautioned*")
    elif regime == "Risk-On":
        print("\n*Risk-On: standard rules, full deployment*")
    print()
    return regime


# ---------------------------------------------------------------------------
# Catastrophic drawdown constants
# ---------------------------------------------------------------------------
CATASTROPHIC_WARNING = 15.0
CATASTROPHIC_HARD_STOP = 25.0
CATASTROPHIC_EXIT_REVIEW = 40.0


def print_catastrophic_alerts(prices):
    """Alert on positions with severe drawdown from avg cost."""
    data = _load()
    positions = data.get("positions", {})

    alerts = []
    for ticker, pos in sorted(positions.items()):
        shares = pos.get("shares", 0)
        avg = pos.get("avg_cost", 0)
        if shares <= 0 or avg <= 0:
            continue
        price = prices.get(ticker)
        if price is None:
            continue
        drawdown = round((price - avg) / avg * 100, 1)
        if drawdown <= -CATASTROPHIC_WARNING:
            if drawdown <= -CATASTROPHIC_EXIT_REVIEW:
                severity = "EXIT REVIEW"
            elif drawdown <= -CATASTROPHIC_HARD_STOP:
                severity = "HARD STOP"
            else:
                severity = "WARNING"
            alerts.append((ticker, avg, price, drawdown, severity))

    if not alerts:
        return set()

    print("\n## Catastrophic Drawdown Alerts")
    print("| Ticker | Avg Cost | Price | Drawdown | Severity | Action |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- |")
    for ticker, avg, price, dd, sev in alerts:
        action = {
            "WARNING": "Check news before any action",
            "HARD STOP": "Pause all pending BUYs — do NOT average down",
            "EXIT REVIEW": "Recommend exit regardless of time stop",
        }[sev]
        print(f"| **{ticker}** | ${avg:.2f} | ${price:.2f} | {dd:.1f}% | **{sev}** | {action} |")

    return {t for t, _, _, _, s in alerts if s in ("HARD STOP", "EXIT REVIEW")}


def print_position_age_monitor(prices, regime="Neutral"):
    """Print position age table with time stop status."""
    data = _load()
    positions = data.get("positions", {})
    today = date.today()

    rows = []
    for ticker, pos in sorted(positions.items()):
        shares = pos.get("shares", 0)
        if shares <= 0:
            continue
        avg = pos.get("avg_cost", 0)
        entry = pos.get("entry_date", "")
        days, display, is_pre = compute_days_held(entry, today)
        status = compute_time_stop(days, is_pre, regime)
        price = prices.get(ticker, avg)
        pnl = round((price - avg) / avg * 100, 1) if avg > 0 else 0
        note = ""
        if is_pre:
            note = "Pre-strategy"
        elif status == "EXCEEDED":
            note = "Run exit-review workflow"
        elif status == "APPROACHING":
            note = "Plan exit strategy"
        rows.append((ticker, display, status, avg, pnl, note))

    if not rows:
        return

    flagged = [r for r in rows if r[2] in ("EXCEEDED", "APPROACHING")]
    if not flagged and regime != "Risk-Off":
        return

    print("\n## Position Age Monitor")
    if regime == "Risk-Off":
        print("*Risk-Off: time stops extended +14 days (APPROACHING >=59d, EXCEEDED >74d)*\n")
    print("| Ticker | Age | Status | Avg Cost | P/L% | Note |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- |")
    for ticker, display, status, avg, pnl, note in rows:
        marker = "**" if status in ("EXCEEDED", "APPROACHING") else ""
        print(f"| {marker}{ticker}{marker} | {display}d | {marker}{status}{marker} | ${avg:.2f} | {pnl:+.1f}% | {note} |")


def print_exit_strategy_summary():
    """Show exit strategy recommendation per active position based on daily range."""
    try:
        sd = json.load(open(_ROOT / "screening_data.json"))
    except (FileNotFoundError, json.JSONDecodeError):
        return

    data = _load()
    positions = data.get("positions", {})
    passer_map = {p["ticker"]: p for p in sd.get("passers", [])}

    # Backward compat: skip if screening_data doesn't have daily range fields yet
    if not any(p.get("median_daily_range") for p in passer_map.values()):
        return

    rows = []
    for ticker, pos in sorted(positions.items()):
        if pos.get("shares", 0) <= 0:
            continue
        p = passer_map.get(ticker)
        if not p:
            continue
        days_3 = p.get("days_above_3pct", 0)
        daily_rng = p.get("median_daily_range", 0)
        exit_type = "Same-Day 3%" if days_3 >= 60 else "Patient 6%+"
        rows.append((ticker, daily_rng, days_3, exit_type))

    if not rows:
        return

    print("\n## Exit Strategy by Ticker")
    print("| Ticker | Daily Range | Pct>=3% | Exit Type |")
    print("| :--- | :--- | :--- | :--- |")
    for ticker, rng, days, etype in rows:
        print(f"| {ticker} | {rng:.1f}% | {days:.0f}% | {etype} |")


def print_unfilled_same_day_exits():
    """Surface same-day exit orders that didn't fill."""
    data = _load()
    pending = data.get("pending_orders", {})

    unfilled = []
    for ticker, orders in pending.items():
        for o in orders:
            if o.get("type") == "SELL" and "same-day-exit" in o.get("note", "").lower():
                unfilled.append((ticker, o["price"], o["shares"]))

    if not unfilled:
        return

    print("\n## Unfilled Same-Day Exits")
    print("*These same-day exit orders are still pending.*\n")
    print("| Ticker | Price | Shares | Action |")
    print("| :--- | :--- | :--- | :--- |")
    for ticker, price, shares in unfilled:
        print(f"| {ticker} | ${price:.2f} | {shares} | Cancel or Hold? |")


def print_pdt_status():
    """Show pattern day trade count from same-day-exit pending sells."""
    data = _load()
    pending = data.get("pending_orders", {})
    same_day_count = sum(
        1 for orders in pending.values()
        for o in orders
        if o.get("type") == "SELL" and "same-day-exit" in o.get("note", "").lower()
    )
    if same_day_count > 0:
        print(f"\n*PDT Status: {same_day_count} same-day exit(s) pending — track against 3/5-day limit*")


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


def print_tier_summary():
    """Print a compact tier one-liner from watchlist_manager.py."""
    try:
        result = subprocess.run(
            [sys.executable, str(TOOLS_DIR / "watchlist_manager.py"), "--json", "status"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return
        totals = json.loads(result.stdout).get("totals", {})
    except Exception:
        return
    parts = []
    for tier in ("ACTIVE", "ENGAGED", "SCOUTING", "CANDIDATE"):
        count = totals.get(tier, 0)
        if count:
            parts.append(f"{count} {tier}")
    if parts:
        print(f"*Tiers: {' | '.join(parts)}*")
        print()


# ---------------------------------------------------------------------------
# Part 3 — Ticker Performance Analysis
# ---------------------------------------------------------------------------

def run_ticker_perf_analysis():
    """Run ticker_perf_analyzer.py, display results."""
    print("## Part 3 — Ticker Performance Analysis")
    print()
    try:
        result = subprocess.run(
            [sys.executable, str(TOOLS_DIR / "ticker_perf_analyzer.py"), "--json"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            print(f"*Error: ticker_perf_analyzer.py failed: {result.stderr.strip() or 'unknown'}*")
            return
    except subprocess.TimeoutExpired:
        print("*Error: ticker_perf_analyzer.py timed out (300s)*")
        return
    except Exception as e:
        print(f"*Error: {e}*")
        return

    if result.stdout.strip():
        # Strip the subprocess's own header (we already printed the Part 3 version)
        lines = result.stdout.strip().split("\n")
        if lines and lines[0].startswith("## "):
            lines = lines[1:]
        output = "\n".join(lines).strip()
        if output:
            print(output)
        print()


# ---------------------------------------------------------------------------
# Part 4 — Deployment recommendations
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


def print_deployment_recs(tickers, paused=None):
    """Run bullet_recommender per ticker via subprocess."""
    if not tickers:
        print("*All tickers have active placed orders — no deployment needed.*")
        return

    print(f"## Part 4 — Deployment Recommendations ({len(tickers)} tickers)")
    print()

    for ticker in tickers:
        if paused and ticker in paused:
            print(f"### {ticker}\n")
            print("*PAUSED: Catastrophic drawdown — review before deploying*\n")
            continue
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
# Part 5 — Watchlist Fitness Check
# ---------------------------------------------------------------------------

def run_watchlist_fitness():
    """Run watchlist_fitness.py, print summary, flag removal candidates."""
    print("## Part 5 — Watchlist Fitness Check")
    print()
    try:
        result = subprocess.run(
            [sys.executable, str(TOOLS_DIR / "watchlist_fitness.py"), "--summary-only"],
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
# Part 6 — New Candidate Screening
# ---------------------------------------------------------------------------

def run_candidate_screening(wide_screen=False):
    """Run screener → filter → print new strong candidates not already tracked."""
    print("## Part 6 — New Candidate Screening")
    print()

    # Build screener args
    screener_args = [sys.executable, str(TOOLS_DIR / "surgical_screener.py")]
    if wide_screen:
        if UNIVERSE_CACHE_PATH.exists():
            screener_args.append("--universe")
            print("*Running wide screener (dynamic universe)...*")
        else:
            print("*Universe cache not found — using default 160-ticker universe. "
                  "Run: python3 tools/universe_screener.py to enable wide screening.*")
    else:
        print("*Running screener (~3-5 min)...*")
    print()

    # Step A: Screener
    try:
        result = subprocess.run(
            screener_args,
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

    _persist_candidates([e["ticker"] for e in new_candidates])


def _persist_candidates(tickers):
    """Auto-add screening candidates to data/candidates.json for cross-session tracking."""
    added_count = 0

    # Step 1: Add new tickers (skip if empty)
    if tickers:
        try:
            result = subprocess.run(
                [sys.executable, str(TOOLS_DIR / "candidate_tracker.py"), "add"] + tickers,
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0 and result.stdout:
                m = re.search(r"Added (\d+)", result.stdout)
                if m:
                    added_count = int(m.group(1))
        except Exception:
            pass

    # Step 2: Age-out stale entries
    try:
        subprocess.run(
            [sys.executable, str(TOOLS_DIR / "candidate_tracker.py"), "age-out"],
            capture_output=True, text=True, timeout=30,
        )
    except Exception:
        pass

    # Step 3: Report pool size
    try:
        with open(CANDIDATES_JSON_PATH) as f:
            pool = json.load(f).get("candidates", [])
        msg = f"*Candidate pool: {len(pool)} tickers"
        if added_count:
            msg += f" ({added_count} new added)"
        msg += "*"
        print(msg)
        print()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Part 7 — Broker Reconciliation
# ---------------------------------------------------------------------------

def run_broker_reconciliation():
    """Run broker_reconciliation.py for Part 7."""
    try:
        result = subprocess.run(
            [sys.executable, str(TOOLS_DIR / "broker_reconciliation.py")],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            print("## Part 7 — Broker Reconciliation")
            print()
            print(f"*Error: broker_reconciliation.py failed: {result.stderr.strip() or 'unknown'}*")
            return
    except subprocess.TimeoutExpired:
        print("## Part 7 — Broker Reconciliation")
        print()
        print("*Error: broker_reconciliation.py timed out (300s)*")
        return
    except Exception as e:
        print("## Part 7 — Broker Reconciliation")
        print()
        print(f"*Error: {e}*")
        return

    if result.stdout.strip():
        print(result.stdout.strip())
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
        help="Skip Parts 3-6 (perf analysis, deployment, fitness, screening)",
    )
    parser.add_argument(
        "--no-recon", action="store_true",
        help="Skip Part 7 (broker reconciliation)",
    )
    parser.add_argument(
        "--no-perf", action="store_true",
        help="Skip Part 3 (performance analysis)",
    )
    parser.add_argument(
        "--no-fitness", action="store_true",
        help="Skip Parts 5-6 (fitness check and screening)",
    )
    parser.add_argument(
        "--no-screen", action="store_true",
        help="Skip Part 6 (new candidate screening)",
    )
    parser.add_argument(
        "--wide-screen", action="store_true",
        help="Use dynamic universe for screening (requires universe_screener.py cache)",
    )
    args = parser.parse_args()

    fills, fill_parse_err = parse_specs(args.fills)
    sells, sell_parse_err = parse_specs(args.sells)
    parse_errors = fill_parse_err + sell_parse_err

    # Part 0: Market Regime
    regime = print_market_regime()

    # Part 1: Process transactions
    if fills or sells or parse_errors:
        print("## Part 1 — Processing Transactions")
        print()
        process_transactions(fills, sells, parse_errors)

    # Part 2: Consolidated orders
    print_consolidated_orders()
    print_tier_summary()

    # Fetch live prices once for monitoring sections
    data = _load()
    active_tickers = [t for t, p in data.get("positions", {}).items() if p.get("shares", 0) > 0]
    live_prices = _fetch_position_prices(active_tickers)

    # Position Age Monitor
    print_position_age_monitor(live_prices, regime=regime)

    # Catastrophic Drawdown Alerts
    paused_tickers = print_catastrophic_alerts(live_prices)

    # Exit Strategy Summary
    print_exit_strategy_summary()

    # Unfilled Same-Day Exits
    print_unfilled_same_day_exits()

    # PDT Status
    print_pdt_status()

    # Part 3: Performance Analysis (before deployment so profiles are fresh)
    if not args.no_deploy and not args.no_perf:
        if regime != "Risk-Off":
            run_ticker_perf_analysis()
        else:
            print("## Part 3 — Ticker Performance Analysis\n")
            print("*Suppressed: Risk-Off regime — sell target upgrades paused*\n")

    # Part 4: Deployment recommendations
    if not args.no_deploy:
        if regime == "Risk-Off":
            print("*CAUTION: Risk-Off regime — consider half-sizing or pausing watchlist entries*\n")
        deploy_tickers = find_deployment_tickers()
        print_deployment_recs(deploy_tickers, paused=paused_tickers)

    # Part 5: Watchlist Fitness Check
    if not args.no_deploy and not args.no_fitness:
        run_watchlist_fitness()

    # Part 6: New Candidate Screening
    if not args.no_deploy and not args.no_fitness and not args.no_screen:
        run_candidate_screening(wide_screen=args.wide_screen)

    # Part 7: Broker Reconciliation (independent of --no-deploy)
    if not args.no_recon:
        run_broker_reconciliation()


if __name__ == "__main__":
    main()
