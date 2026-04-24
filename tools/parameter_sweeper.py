"""Parameter sweeper — find optimal dip thresholds per ticker.

Optimized approach:
  1. Pre-compute per-day dip/bounce/entry data for each ticker (graph-based, once per dip_threshold)
  2. Sweep target/stop as pure arithmetic on entry vs remaining bars (no graph rebuild)

Usage:
    python3 tools/parameter_sweeper.py --cached             # use cached 5-min data
    python3 tools/parameter_sweeper.py --days 60             # download fresh data
    python3 tools/parameter_sweeper.py --cached --dry-run    # show results without writing
    python3 tools/parameter_sweeper.py --cached --ticker OKLO  # sweep one ticker
"""
import sys
import json
import time
import itertools
import argparse
from pathlib import Path
from collections import defaultdict
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

def _log_progress(msg):
    """Timestamped progress to stderr."""
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


from neural_dip_evaluator import (
    build_first_hour_graph, build_decision_graph,
    DIP_CONFIG, _extract_col, _extract_latest,
)
from neural_dip_backtester import (
    download_intraday, download_daily, load_cached,
    compute_ranges_for_day,
    CACHE_DIR, INTRADAY_CACHE, DAILY_CACHE,
)
from trading_calendar import is_trading_day
from expected_edge import attach_expected_edge

_ROOT = Path(__file__).resolve().parent.parent
PROFILES_PATH = _ROOT / "data" / "ticker_profiles.json"

# ---------------------------------------------------------------------------
# Sweep grid
# ---------------------------------------------------------------------------

SWEEP_TARGETS = [2.0, 3.0, 3.5, 4.0, 5.0, 6.0]
SWEEP_STOPS = [-2.0, -3.0, -4.0, -5.0]
SWEEP_DIP_THRESHOLDS = [0.5, 1.0, 1.5, 2.0, 2.5]
SWEEP_BOUNCE_THRESHOLDS = [0.3]  # not yet varied
SWEEP_BREADTH = [0.10, 0.20, 0.30, 0.40, 0.50]


# ---------------------------------------------------------------------------
# Phase 1: Pre-compute per-day signals for each dip_threshold
# ---------------------------------------------------------------------------

def precompute_signals(tickers, trading_days, intraday, daily, n):
    """For each dip_threshold, compute which tickers dip/bounce and entry prices.

    Returns: {dip_thresh: {day: {tk: {dipped, bounced, entry, remaining_high,
                                       remaining_low, remaining_close}}}}
    """
    print("Pre-computing signals per dip_threshold...")
    signals = {}

    for dip_thresh in SWEEP_DIP_THRESHOLDS:
        # Build profile: ALL tickers use this dip_threshold
        profile = {tk: {
            "dip_threshold": dip_thresh,
            "bounce_threshold": DIP_CONFIG["bounce_threshold_pct"],
            "target_pct": 4.0,  # doesn't matter for signal computation
            "stop_pct": -3.0,
        } for tk in tickers}

        day_signals = {}
        graph_errors = 0
        data_errors = 0
        for day in trading_days:
            day_bars = intraday[intraday.index.date == day]
            if len(day_bars) < 12:
                continue

            hist_ranges = compute_ranges_for_day(daily, tickers, day)
            # For tickers missing range data, default to viable=True
            # (universe tickers are pre-screened for swing >= 10%, stronger than 3% range gate)
            for t in tickers:
                if t not in hist_ranges or not hist_ranges[t].get("range_pct"):
                    hist_ranges[t] = {"range_pct": 10.0, "recovery_pct": 70, "viable": True}
            static = {t: {"verdict": ["UNKNOWN"], "catastrophic": None,
                          "dip_viable": "UNKNOWN", "earnings_gate": "CLEAR"}
                      for t in tickers}

            fh_bars = day_bars.iloc[:12]
            try:
                _, fh_state = build_first_hour_graph(
                    tickers, fh_bars, static, hist_ranges, "Neutral", profile)
            except Exception as e:
                graph_errors += 1
                if graph_errors <= 3:
                    _log_progress(f"graph build error ({day}): {type(e).__name__}: {e}")
                continue

            # Compute raw breadth ratio from per-ticker dip_pct (no filtering)
            dip_count_for_day = sum(
                1 for t in tickers
                if fh_state.get(f"{t}:dip_pct", 0) >= dip_thresh)
            breadth_ratio = round(dip_count_for_day / n, 3) if n > 0 else 0

            # Skip days where breadth is below the minimum sweep value
            if breadth_ratio < min(SWEEP_BREADTH):
                continue

            # Get bounce + entry data per ticker
            decision_bars = day_bars.iloc[:min(18, len(day_bars))]
            remaining = day_bars.iloc[18:] if len(day_bars) > 18 else None

            day_entry = {"_breadth_ratio": breadth_ratio}
            for tk in tickers:
                fh_low = fh_state.get(f"{tk}:first_hour_low")
                current = _extract_latest(decision_bars, tk, n)
                if not current or not fh_low or fh_low <= 0 or current <= 0:
                    continue

                bounce_pct = round((current - fh_low) / fh_low * 100, 1)
                dip_pct = fh_state.get(f"{tk}:dip_pct", 0)
                dipped = dip_pct >= dip_thresh
                bounced = bounce_pct >= DIP_CONFIG["bounce_threshold_pct"]

                # Check static gates
                hr = hist_ranges.get(tk, {})
                if not hr.get("viable", False):
                    continue

                if not (dipped and bounced):
                    continue

                # Pre-extract remaining bar data for P/L computation
                rem_high = rem_low = rem_close = None
                if remaining is not None and len(remaining) > 0:
                    try:
                        tk_high = _extract_col(remaining, "High", tk, n)
                        tk_low = _extract_col(remaining, "Low", tk, n)
                        tk_close = _extract_col(remaining, "Close", tk, n)
                        rem_high = float(tk_high.max()) if len(tk_high) > 0 else None
                        rem_low = float(tk_low.min()) if len(tk_low) > 0 else None
                        rem_close = float(tk_close.iloc[-1]) if len(tk_close) > 0 else None
                    except Exception as e:
                        data_errors += 1
                        if data_errors <= 3:
                            _log_progress(f"data extract error ({day}/{tk}): {type(e).__name__}: {e}")
                        continue

                if rem_high is None:
                    continue

                day_entry[tk] = {
                    "entry": round(current, 2),
                    "dip_pct": dip_pct,
                    "bounce_pct": bounce_pct,
                    "rem_high": rem_high,
                    "rem_low": rem_low,
                    "rem_close": rem_close,
                }

            # Store if any ticker had signal data (besides _breadth_ratio)
            if len(day_entry) > 1:
                day_signals[str(day)] = day_entry

        signals[dip_thresh] = day_signals
        n_days = len(day_signals)
        total_errs = graph_errors + data_errors
        errs = f" ({graph_errors} graph + {data_errors} data errors)" if total_errs > 0 else ""
        print(f"  dip_thresh={dip_thresh}%: {n_days} signal days{errs}", flush=True)

    return signals


# ---------------------------------------------------------------------------
# Phase 2: Sweep target/stop per ticker (pure arithmetic, no graph)
# ---------------------------------------------------------------------------

def sweep_ticker(tk, signals, day_filter=None):
    """Sweep all target/stop combos for one ticker using pre-computed signals.

    Args:
        day_filter: optional set of day strings to include (for cross-validation split)

    Returns: (best_params, best_stats, best_trades, features)
      - best_trades: list of per-trade dicts for the best combo
      - features: behavioral feature vector for clustering
    """
    best_pnl = float("-inf")
    best_params = None
    best_stats = None
    best_trades = []
    combo_idx = 0
    total_combos = len(SWEEP_DIP_THRESHOLDS) * len(SWEEP_TARGETS) * len(SWEEP_STOPS) * len(SWEEP_BREADTH)

    for dip_thresh in SWEEP_DIP_THRESHOLDS:
        day_signals = signals.get(dip_thresh, {})

        for target_pct, stop_pct, breadth_thresh in itertools.product(
                SWEEP_TARGETS, SWEEP_STOPS, SWEEP_BREADTH):
            combo_idx += 1
            if combo_idx % 100 == 0 or combo_idx == 1:
                _log_progress(f"dip combo {combo_idx}/{total_combos}")
            total_pnl = 0.0
            trades = 0
            wins = 0
            exits = defaultdict(int)
            trade_list = []

            for day_str, day_data in day_signals.items():
                if day_filter and day_str not in day_filter:
                    continue
                # Breadth gate — skip days below this breadth threshold
                if day_data.get("_breadth_ratio", 0) < breadth_thresh:
                    continue
                if tk not in day_data:
                    continue

                d = day_data[tk]
                entry = d["entry"]
                target = round(entry * (1 + target_pct / 100), 2)
                stop = round(entry * (1 + stop_pct / 100), 2)

                rem_high = d["rem_high"]
                rem_low = d["rem_low"]
                rem_close = d["rem_close"]

                if rem_low <= stop:
                    pnl = stop - entry
                    exit_reason = "STOP"
                elif rem_high >= target:
                    pnl = target - entry
                    exit_reason = "TARGET"
                else:
                    pnl = rem_close - entry
                    exit_reason = "EOD_CUT"

                total_pnl += pnl
                trades += 1
                if pnl > 0:
                    wins += 1
                exits[exit_reason] += 1
                trade_list.append({
                    "day": day_str,
                    "ticker": tk,
                    "entry": entry,
                    "pnl": round(pnl, 4),
                    "pnl_pct": round(pnl / entry * 100, 2) if entry > 0 else 0,
                    "exit_reason": exit_reason,
                    "dip_pct": d["dip_pct"],
                    "bounce_pct": d["bounce_pct"],
                    "fired_inputs": {
                        f"{tk}:dip_gate": {f"{tk}:dip_level": d["dip_pct"]},
                        f"{tk}:bounce_gate": {f"{tk}:bounce_level": d["bounce_pct"]},
                    },
                })

            if trades >= 1 and total_pnl > best_pnl:
                best_pnl = total_pnl
                best_params = {
                    "dip_threshold": dip_thresh,
                    "bounce_threshold": DIP_CONFIG["bounce_threshold_pct"],
                    "target_pct": target_pct,
                    "stop_pct": stop_pct,
                    "breadth_threshold": breadth_thresh,
                }
                best_stats = {
                    "total_pnl": round(total_pnl, 2),
                    "trades": trades,
                    "wins": wins,
                    "win_rate": round(wins / trades * 100, 1) if trades else 0,
                    "exits": dict(exits),
                }
                best_trades = trade_list

    # Extract behavioral features from best-param trades
    features = _extract_features(tk, signals, best_trades, best_params)

    return best_params, best_stats, best_trades, features


def evaluate_params(tk, params, signals, day_filter=None):
    """Evaluate fixed params on specific days. For cross-validation."""
    if not params:
        return {"trades": 0, "pnl": 0, "wins": 0}

    dip_thresh = params["dip_threshold"]
    target_pct = params["target_pct"]
    stop_pct = params["stop_pct"]
    breadth_thresh = params.get("breadth_threshold", 0.50)
    day_signals = signals.get(dip_thresh, {})

    total_pnl = 0.0
    trades = 0
    wins = 0

    for day_str, day_data in day_signals.items():
        if day_filter and day_str not in day_filter:
            continue
        if day_data.get("_breadth_ratio", 0) < breadth_thresh:
            continue
        if tk not in day_data:
            continue

        d = day_data[tk]
        entry = d["entry"]
        target = round(entry * (1 + target_pct / 100), 2)
        stop = round(entry * (1 + stop_pct / 100), 2)

        if d["rem_low"] <= stop:
            pnl = stop - entry
        elif d["rem_high"] >= target:
            pnl = target - entry
        else:
            pnl = d["rem_close"] - entry

        total_pnl += pnl
        trades += 1
        if pnl > 0:
            wins += 1

    return {
        "trades": trades,
        "pnl": round(total_pnl, 2),
        "wins": wins,
        "win_rate": round(wins / trades * 100, 1) if trades else 0,
    }


def _extract_features(tk, signals, best_trades, best_params):
    """Compute behavioral feature vector for clustering.

    Features describe HOW this ticker dips and recovers — not the optimal
    params (those come from the sweep). The cluster groups tickers with
    similar dip behavior so new tickers can inherit defaults.
    """
    if not best_trades or not best_params:
        return None

    dip_thresh = best_params["dip_threshold"]

    # Count total days this ticker appeared across all signal days
    total_signal_days = 0
    total_dip_days = 0
    all_dip_pcts = []
    all_bounce_pcts = []

    day_signals = signals.get(dip_thresh, {})
    for day_str, tk_data in day_signals.items():
        total_signal_days += 1
        if tk in tk_data:
            total_dip_days += 1
            all_dip_pcts.append(tk_data[tk]["dip_pct"])
            all_bounce_pcts.append(tk_data[tk]["bounce_pct"])

    # From best-param trades
    pnl_pcts = [t["pnl_pct"] for t in best_trades]
    exit_reasons = [t["exit_reason"] for t in best_trades]
    n_trades = len(best_trades)

    target_hits = sum(1 for e in exit_reasons if e == "TARGET")
    stop_hits = sum(1 for e in exit_reasons if e == "STOP")
    eod_cuts = sum(1 for e in exit_reasons if e == "EOD_CUT")
    eod_positive = sum(1 for t in best_trades
                       if t["exit_reason"] == "EOD_CUT" and t["pnl"] > 0)

    return {
        "dip_frequency": round(total_dip_days / total_signal_days, 3)
            if total_signal_days > 0 else 0,
        "median_dip_depth_pct": round(float(np.median(all_dip_pcts)), 2)
            if all_dip_pcts else 0,
        "median_bounce_pct": round(float(np.median(all_bounce_pcts)), 2)
            if all_bounce_pcts else 0,
        "target_hit_rate": round(target_hits / n_trades, 3)
            if n_trades > 0 else 0,
        "stop_hit_rate": round(stop_hits / n_trades, 3)
            if n_trades > 0 else 0,
        "eod_cut_rate": round(eod_cuts / n_trades, 3)
            if n_trades > 0 else 0,
        "eod_recovery_rate": round(eod_positive / eod_cuts, 3)
            if eod_cuts > 0 else 0,
        "mean_pnl_pct": round(float(np.mean(pnl_pcts)), 3)
            if pnl_pcts else 0,
        "trade_count": n_trades,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Parameter Sweeper")
    parser.add_argument("--days", type=int, default=60,
                        help="Number of days (max 60 for 5-min data)")
    parser.add_argument("--cached", action="store_true",
                        help="Use cached intraday data")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print results without writing profiles")
    parser.add_argument("--ticker", type=str, default=None,
                        help="Sweep only this ticker (default: all)")
    parser.add_argument("--split", action="store_true",
                        help="Cross-validate: train on first 2/3, validate on last 1/3")
    parser.add_argument("--interval", choices=["5m", "1h"], default="5m",
                        help="Bar interval: 5m (60-day max) or 1h (730-day max)")
    args = parser.parse_args()

    max_days = 730 if args.interval == "1h" else 60
    days = min(args.days, max_days)

    # Load tickers
    from neural_dip_evaluator import _load_portfolio, _get_dip_candidates
    portfolio = _load_portfolio()
    tickers = _get_dip_candidates(portfolio)
    if not tickers:
        print("No tickers to sweep.")
        return

    n = len(tickers)
    sweep_tickers = [args.ticker] if args.ticker else tickers
    combos = (len(SWEEP_TARGETS) * len(SWEEP_STOPS) *
              len(SWEEP_DIP_THRESHOLDS) * len(SWEEP_BREADTH))

    print(f"Parameter Sweeper — {days} days, {len(sweep_tickers)} tickers")
    print(f"Grid: {len(SWEEP_TARGETS)} targets × {len(SWEEP_STOPS)} stops "
          f"× {len(SWEEP_DIP_THRESHOLDS)} dip × {len(SWEEP_BREADTH)} breadth "
          f"= {combos} combos/ticker\n")

    # Load data
    cache_path = CACHE_DIR / f"intraday_{args.interval.replace('m','min')}_{days}d.pkl"
    if args.cached and cache_path.exists():
        print(f"Loading cached {args.interval} data from {cache_path}...")
        intraday = load_cached(cache_path)
    else:
        intraday = download_intraday(tickers, days, interval=args.interval)

    if intraday is None or intraday.empty:
        print("*No intraday data. Cannot sweep.*")
        return

    if args.cached and DAILY_CACHE.exists():
        daily = load_cached(DAILY_CACHE)
    else:
        daily = download_daily(tickers, days + 30)

    if daily is None:
        daily = intraday

    all_dates = sorted(set(intraday.index.date))
    trading_days = [d for d in all_dates if is_trading_day(d)]
    print(f"Trading days: {len(trading_days)}\n")

    # Phase 1: Pre-compute signals (graph-based, once per dip_threshold)
    signals = precompute_signals(tickers, trading_days, intraday, daily, n)

    # Determine train/validate split
    all_day_strs = sorted(set(
        day_str for thresh_signals in signals.values()
        for day_str in thresh_signals.keys()
    ))
    if args.split and len(all_day_strs) >= 6:
        split_idx = len(all_day_strs) * 2 // 3
        train_days = set(all_day_strs[:split_idx])
        validate_days = set(all_day_strs[split_idx:])
        print(f"Cross-validation: train={len(train_days)} days, "
              f"validate={len(validate_days)} days\n")
    else:
        train_days = None  # use all days
        validate_days = None

    # Phase 2: Sweep target/stop per ticker (pure arithmetic)
    print(f"Sweeping {len(sweep_tickers)} tickers...")
    results = {}
    for i, tk in enumerate(sweep_tickers):
        best_params, best_stats, best_trades, features = sweep_ticker(
            tk, signals, day_filter=train_days)

        if best_params:
            # Cross-validate if split mode
            cv = None
            if validate_days:
                cv = evaluate_params(tk, best_params, signals,
                                     day_filter=validate_days)

            results[tk] = {
                "params": best_params, "stats": best_stats,
                "trades": best_trades, "features": features,
                "cross_validation": cv,
            }
            cv_str = ""
            if cv and cv["trades"] > 0:
                cv_str = f" CV=${cv['pnl']:.2f}({cv['trades']}t)"
            print(f"  [{i+1}/{len(sweep_tickers)}] {tk}: "
                  f"P/L=${best_stats['total_pnl']:.2f} "
                  f"({best_stats['trades']}t, {best_stats['win_rate']}%WR) "
                  f"dip>={best_params['dip_threshold']}% "
                  f"tgt={best_params['target_pct']}% "
                  f"stp={best_params['stop_pct']}%{cv_str}", flush=True)
        else:
            print(f"  [{i+1}/{len(sweep_tickers)}] {tk}: "
                  f"no profitable combo found", flush=True)

    # Write sweep results (consumed by ticker_clusterer.py)
    sweep_out = _ROOT / "data" / "sweep_results.json"
    sweep_data = {
        "_meta": {
            "schema_version": 1,
            "source": "parameter_sweeper.py",
            "execution_mode": "intraday_5min_neural_replay",
            "updated": date.today().isoformat(),
            "days": days,
            "trading_days": len(trading_days),
            "grid_size": combos,
            "tickers_swept": len(results),
        }
    }
    # Compute crude composite ($/month) for tournament ranking
    _sweep_months = max(days / 30.0, 1)
    for tk, r in results.items():
        _pnl = r["stats"].get("total_pnl", 0)
        r["stats"]["composite"] = round(_pnl / _sweep_months, 2)
        sweep_data[tk] = attach_expected_edge("dip", {
            "params": r["params"],
            "stats": r["stats"],
            "trades": r["trades"],
            "features": r["features"],
            "cross_validation": r.get("cross_validation"),
        })
    with open(sweep_out, "w") as f:
        json.dump(sweep_data, f, indent=2, default=str)
    print(f"\nSweep results saved to {sweep_out}")

    # Build profiles
    if not results:
        print("\nNo profiles produced.")
        return

    # Load existing profiles to preserve _meta
    existing = {}
    if PROFILES_PATH.exists():
        with open(PROFILES_PATH) as f:
            existing = json.load(f)

    profiles = {
        "_meta": {
            "version": existing.get("_meta", {}).get("version", 0) + 1,
            "source": "parameter_sweeper.py",
            "updated": date.today().isoformat(),
            "days_swept": days,
            "trading_days": len(trading_days),
            "grid_size": combos,
        }
    }

    for tk in tickers:
        if tk in results:
            p = dict(results[tk]["params"])
            p["_stats"] = results[tk]["stats"]
            profiles[tk] = p
        elif tk in existing and not tk.startswith("_"):
            profiles[tk] = existing[tk]

    if args.dry_run:
        n_profiles = len([k for k in profiles if not k.startswith("_")])
        print(f"\n--- DRY RUN — would write {n_profiles} profiles ---")
        print(json.dumps(profiles, indent=2))
    else:
        with open(PROFILES_PATH, "w") as f:
            json.dump(profiles, f, indent=2)
        n_profiles = len([k for k in profiles if not k.startswith("_")])
        print(f"\nWrote {n_profiles} profiles to {PROFILES_PATH}")

    # Summary table
    print(f"\n{'='*60}")
    print(f"| Ticker | Dip | Target | Stop | Trades | WR | P/L |")
    print(f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for tk in sorted(results.keys()):
        p = results[tk]["params"]
        s = results[tk]["stats"]
        print(f"| {tk} | {p['dip_threshold']}% | {p['target_pct']}% | "
              f"{p['stop_pct']}% | {s['trades']} | {s['win_rate']}% | "
              f"${s['total_pnl']:.2f} |")

    not_found = [tk for tk in sweep_tickers if tk not in results]
    if not_found:
        print(f"\nNo profile: {', '.join(not_found)}")


if __name__ == "__main__":
    main()
