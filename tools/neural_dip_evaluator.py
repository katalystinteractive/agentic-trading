"""Neural Dip Evaluator — event-driven decision network for daily dip trades.

Builds per-phase dependency graphs with explicit neurons for every gate.
Cascades through 6 layers: Environment → Market-wide → Per-ticker → Gate → Portfolio → Decision.

Usage:
    python3 tools/neural_dip_evaluator.py --phase first_hour     # 10:30 AM breadth check
    python3 tools/neural_dip_evaluator.py --phase decision        # 11:00 AM buy/no-buy
    python3 tools/neural_dip_evaluator.py --phase eod_check       # 3:45 PM unfilled exits
    python3 tools/neural_dip_evaluator.py --phase decision --dry-run  # no email
"""
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import date, datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import yfinance as yf
from graph_engine import DependencyGraph
from neural_artifact_validator import ArtifactValidationError, load_validated_json
from expected_edge import score_graph_candidate
from shared_utils import compute_position_allocation
from trading_calendar import (
    is_trading_day, get_market_phase, market_time_to_utc_hour,
    ET, VALID_PHASES_FOR_MARKET,
)
from sector_registry import get_sector

_ROOT = Path(__file__).resolve().parent.parent
GRAPH_STATE_PATH = _ROOT / "data" / "graph_state.json"
FH_CACHE_PATH = _ROOT / "data" / "neural_fh_cache.json"
HIST_CACHE_PATH = _ROOT / "data" / "neural_hist_ranges_cache.json"

# ---------------------------------------------------------------------------
# Configuration — all thresholds in one place (from plan v2 Section 3.0)
# ---------------------------------------------------------------------------

DIP_CONFIG = {
    "dip_threshold_pct": 1.0,
    "bounce_threshold_pct": 0.3,
    "breadth_threshold": 0.50,
    "range_threshold_pct": 3.0,
    "recovery_threshold_pct": 60.0,
    "budget_normal": 100,
    "budget_risk_off": 50,
    "max_tickers": 5,
    "pdt_limit": 3,
    "capital_min": 100,
    # Portfolio optimization (Phase 4)
    "sector_concentration_pct": 40,   # max % of buys from one sector (e.g., 40% of 5 = 2)
    "correlation_threshold": 0.80,
}

# ---------------------------------------------------------------------------
# Per-ticker profiles — level-firing subscription thresholds
# ---------------------------------------------------------------------------

PROFILES_PATH = _ROOT / "data" / "ticker_profiles.json"


def _load_profiles():
    """Load per-ticker profiles from JSON. Missing file = empty dict."""
    if PROFILES_PATH.exists():
        try:
            data = load_validated_json(PROFILES_PATH)
        except ArtifactValidationError as e:
            print(f"*Warning: {e}. Ignoring learned ticker profiles.*")
            return {}
        return {k: v for k, v in data.items() if not k.startswith("_")}
    return {}


def _get_profile(tk, profiles):
    """Get profile for ticker, falling back to DIP_CONFIG globals."""
    if profiles and tk in profiles:
        return profiles[tk]
    return {
        "dip_threshold": DIP_CONFIG["dip_threshold_pct"],
        "bounce_threshold": DIP_CONFIG["bounce_threshold_pct"],
        "target_pct": 4.0,
        "stop_pct": -3.0,
        "breadth_threshold": DIP_CONFIG["breadth_threshold"],
    }


# ---------------------------------------------------------------------------
# Synapse weights — learned edge weights for neural connections
# ---------------------------------------------------------------------------

WEIGHTS_PATH = _ROOT / "data" / "synapse_weights.json"


def _load_weights(regime="Neutral"):
    """Load synapse weights. Regime-specific weights override base weights."""
    if not WEIGHTS_PATH.exists():
        return {}
    try:
        data = load_validated_json(WEIGHTS_PATH)
    except ArtifactValidationError as e:
        print(f"*Warning: {e}. Ignoring learned synapse weights.*")
        return {}
    base_w = data.get("weights", {})
    regime_w = data.get("regime_weights", {}).get(regime, {})
    merged = {**base_w, **regime_w}
    return merged


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_intraday(tickers, retries=1):
    """Fetch 5-min bars for all tickers. 1 retry, 3s delay."""
    for attempt in range(retries + 1):
        try:
            data = yf.download(tickers, period="1d", interval="5m",
                               progress=False)
            if data.empty:
                if attempt < retries:
                    time.sleep(3)
                    continue
                return None
            if len(tickers) > 1:
                try:
                    available = set(data["Close"].columns)
                    missing = [tk for tk in tickers if tk not in available]
                    if missing:
                        print(f"*Warning: missing tickers: {missing}*")
                except Exception:
                    pass
            return data
        except Exception as e:
            if attempt < retries:
                time.sleep(3)
                continue
            print(f"*Warning: yfinance failed: {e}*")
            return None
    return None


# ---------------------------------------------------------------------------
# Price extraction helpers
# ---------------------------------------------------------------------------

def _extract_col(data, col, tk, n_tickers):
    """Extract column from yfinance MultiIndex DataFrame."""
    if n_tickers > 1:
        return data[(col, tk)].dropna()
    return data[col].dropna()


def _extract_open(data, tk, n_tickers):
    """First bar's open = today's open."""
    try:
        col = _extract_col(data, "Open", tk, n_tickers)
        return round(float(col.iloc[0]), 2) if len(col) > 0 else None
    except (KeyError, IndexError):
        return None


def _extract_price_at(data, tk, et_hour, et_minute, n_tickers):
    """Price at specific ET time (finds closest bar)."""
    try:
        utc_target = market_time_to_utc_hour(et_hour, et_minute)
        col = _extract_col(data, "Close", tk, n_tickers)
        for idx in col.index:
            bar_hour = idx.hour + idx.minute / 60
            if bar_hour >= utc_target:
                return round(float(col.loc[idx]), 2)
        return round(float(col.iloc[-1]), 2) if len(col) > 0 else None
    except (KeyError, IndexError):
        return None


def _extract_first_hour_low(data, tk, n_tickers):
    """Lowest price between 9:30-10:30 ET."""
    try:
        fh_start = market_time_to_utc_hour(9, 30)
        fh_end = market_time_to_utc_hour(10, 30)
        col = _extract_col(data, "Low", tk, n_tickers)
        mask = [(idx.hour + idx.minute / 60 >= fh_start and
                 idx.hour + idx.minute / 60 < fh_end) for idx in col.index]
        fh_bars = col[mask]
        return round(float(fh_bars.min()), 2) if len(fh_bars) > 0 else None
    except (KeyError, IndexError):
        return None


def _extract_latest(data, tk, n_tickers):
    """Most recent bar's close."""
    try:
        col = _extract_col(data, "Close", tk, n_tickers)
        return round(float(col.iloc[-1]), 2) if len(col) > 0 else None
    except (KeyError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Static context (graph_state.json + fallback)
# ---------------------------------------------------------------------------

def load_static_context(tickers):
    """Load regime, verdicts, catastrophic from graph_state.json.
    Falls back to live computation if missing/stale."""
    state = {}
    if GRAPH_STATE_PATH.exists():
        try:
            with open(GRAPH_STATE_PATH) as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    regime = state.get("regime")
    vix = state.get("vix")
    tickers_state = state.get("tickers", {})

    # Fallback: compute regime from live data if missing
    if regime is None:
        try:
            from shared_regime import fetch_regime_detail
            info = fetch_regime_detail()
            regime = info.get("regime", "Neutral")
            vix = info.get("vix")
        except Exception:
            regime = "Neutral"

    static = {}
    for tk in tickers:
        ts = tickers_state.get(tk, {})
        catastrophic = ts.get("catastrophic")
        verdict = ts.get("verdict", ["UNKNOWN"])
        dip_viable = ts.get("dip_viable", "UNKNOWN")
        earnings_gate = ts.get("earnings_gate")

        # Fallback: compute earnings if missing
        if earnings_gate is None:
            try:
                from earnings_gate import check_earnings_gate
                gate = check_earnings_gate(tk)
                earnings_gate = gate.get("status", "CLEAR")
            except Exception:
                earnings_gate = "CLEAR"

        static[tk] = {
            "verdict": verdict,
            "catastrophic": catastrophic,
            "dip_viable": dip_viable,
            "earnings_gate": earnings_gate,
        }

    return regime, vix, static


# ---------------------------------------------------------------------------
# Historical range computation (with caching)
# ---------------------------------------------------------------------------

def compute_historical_ranges(tickers):
    """Compute 1-month range + recovery stats per ticker.
    Cached to disk (4-hour TTL) to avoid re-downloading across phases.
    """
    # Check cache
    if HIST_CACHE_PATH.exists():
        cache_age = time.time() - HIST_CACHE_PATH.stat().st_mtime
        if cache_age < 14400:  # <4 hours
            try:
                with open(HIST_CACHE_PATH) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

    # Compute fresh
    result = {}
    try:
        data = yf.download(tickers, period="1mo", interval="1d", progress=False)
    except Exception:
        result = {tk: {"range_pct": 0, "recovery_pct": 0, "viable": False}
                  for tk in tickers}
        return result

    n = len(tickers)
    for tk in tickers:
        try:
            highs = _extract_col(data, "High", tk, n).values
            lows = _extract_col(data, "Low", tk, n).values
            if len(highs) < 5 or len(lows) < 5:
                result[tk] = {"range_pct": 0, "recovery_pct": 0, "viable": False}
                continue
            daily_range = (highs - lows) / lows * 100
            med_range = float(round(float(daily_range.mean()), 1))
            low_to_high = (highs - lows) / lows * 100
            recovery_days = int((low_to_high >= 3.0).sum())
            recovery_pct = round(recovery_days / len(low_to_high) * 100)
            cfg = DIP_CONFIG
            result[tk] = {
                "range_pct": med_range,
                "recovery_pct": recovery_pct,
                "viable": (med_range >= cfg["range_threshold_pct"]
                           and recovery_pct >= cfg["recovery_threshold_pct"]),
            }
        except Exception:
            result[tk] = {"range_pct": 0, "recovery_pct": 0, "viable": False}

    # Save cache
    try:
        HIST_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(HIST_CACHE_PATH, "w") as f:
            json.dump(result, f, indent=2)
    except OSError:
        pass

    return result


# ---------------------------------------------------------------------------
# Portfolio optimization helpers (Phase 4)
# ---------------------------------------------------------------------------

def _filter_sector_balance(candidates, max_buys, concentration_pct):
    """Filter candidates so no single sector exceeds concentration_pct of max_buys.

    At 5 buys / 40% concentration → max 2 per sector.
    At 20 buys / 40% concentration → max 8 per sector.
    Minimum 1 per sector (never block a sector entirely).
    Preserves rank order.
    """
    max_per_sector = max(1, int(max_buys * concentration_pct / 100))
    sector_counts = {}
    filtered = []
    skipped = []
    for c in candidates:
        sector = get_sector(c["ticker"])
        count = sector_counts.get(sector, 0)
        if count < max_per_sector:
            filtered.append(c)
            sector_counts[sector] = count + 1
        else:
            skipped.append((c["ticker"], sector))
    return filtered, skipped


def _filter_correlated(candidates, prices, n_tickers, threshold=0.80):
    """Remove candidates that correlate >threshold with already-selected ones.

    Uses intraday close prices for correlation computation.
    """
    if len(candidates) <= 1 or prices is None:
        return candidates, []

    selected = [candidates[0]]
    skipped = []

    for c in candidates[1:]:
        correlated = False
        for s in selected:
            try:
                corr = _compute_pair_correlation(
                    prices, c["ticker"], s["ticker"], n_tickers)
                if corr is not None and corr > threshold:
                    correlated = True
                    skipped.append((c["ticker"], s["ticker"], round(corr, 3)))
                    break
            except Exception:
                continue
        if not correlated:
            selected.append(c)
    return selected, skipped


def _compute_pair_correlation(prices, tk1, tk2, n):
    """Compute correlation between two tickers from intraday close prices."""
    try:
        c1 = _extract_col(prices, "Close", tk1, n)
        c2 = _extract_col(prices, "Close", tk2, n)
        if len(c1) < 5 or len(c2) < 5:
            return None
        # Align lengths
        min_len = min(len(c1), len(c2))
        c1 = c1.iloc[:min_len].values.astype(float)
        c2 = c2.iloc[:min_len].values.astype(float)
        # Drop NaN
        mask = ~(np.isnan(c1) | np.isnan(c2))
        c1, c2 = c1[mask], c2[mask]
        if len(c1) < 5:
            return None
        corr = float(np.corrcoef(c1, c2)[0, 1])
        return corr
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Graph builders (per plan v2 Section 3.4-3.5)
# ---------------------------------------------------------------------------

def build_first_hour_graph(tickers, prices, static, hist_ranges, regime,
                           profiles=None, weights=None):
    """Build first-hour graph: per-ticker dip detection + breadth aggregation.

    Level-firing architecture: observer neurons fire raw values,
    subscription gates compare values to per-ticker thresholds.
    Edge weights from synapse learning applied to gate inputs.
    """
    profiles = profiles or {}
    weights = weights or {}
    graph = DependencyGraph()
    cfg = DIP_CONFIG
    n = len(tickers)

    graph.add_node("regime", compute=lambda _: regime,
        reason_fn=lambda old, new, _: f"Regime: {new}")

    dip_count = 0
    for tk in tickers:
        o = _extract_open(prices, tk, n)
        c = _extract_price_at(prices, tk, 10, 30, n)
        dip_pct = round((o - c) / o * 100, 1) if o and c and o > 0 else 0
        profile = _get_profile(tk, profiles)
        dipped = dip_pct >= profile["dip_threshold"]
        if dipped:
            dip_count += 1

        st = static.get(tk, {})
        hr = hist_ranges.get(tk, {})
        cat = st.get("catastrophic")
        verdict = st.get("verdict", ["UNKNOWN"])
        v0 = verdict[0] if isinstance(verdict, list) else verdict
        eg = st.get("earnings_gate", "CLEAR")
        viable = st.get("dip_viable", "UNKNOWN")

        # Layer 1: Observer neuron — fires with raw dip value
        graph.add_node(f"{tk}:dip_level", compute=lambda _, pct=dip_pct: pct,
            reason_fn=lambda old, new, _: f"DIP_LEVEL={new:.1f}%")

        # Layer 2: Subscription gate — per-ticker threshold + learned edge weight
        graph.add_node(f"{tk}:dip_gate",
            compute=lambda inputs, thresh=profile["dip_threshold"], t=tk:
                inputs[f"{t}:dip_level"] >= thresh,
            depends_on=[f"{tk}:dip_level"],
            edge_weights=weights.get(f"{tk}:dip_gate", {}),
            reason_fn=lambda old, new, _, thresh=profile["dip_threshold"]:
                f"DIP_GATE(>={thresh}%) {'ACTIVATED' if new else 'SILENT'}")

        # Static gates
        graph.add_node(f"{tk}:dip_viable", compute=lambda _, v=viable: v in ("YES", "CAUTION", "UNKNOWN"),
            reason_fn=lambda old, new, _, v=viable: f"DIP_VIABLE={v}")
        graph.add_node(f"{tk}:not_catastrophic", compute=lambda _, c=cat: c not in ("HARD_STOP", "EXIT_REVIEW"),
            reason_fn=lambda old, new, _, c=cat: "Clear" if new else f"BLOCKED:{c}")
        graph.add_node(f"{tk}:not_exit", compute=lambda _, v=v0: v not in ("EXIT", "REDUCE"),
            reason_fn=lambda old, new, _, v=v0: "Clear" if new else f"BLOCKED:verdict={v}")
        graph.add_node(f"{tk}:earnings_clear", compute=lambda _, e=eg: e not in ("BLOCKED", "FALLING_KNIFE"),
            reason_fn=lambda old, new, _, e=eg: "Clear" if new else f"BLOCKED:earnings={e}")
        graph.add_node(f"{tk}:historical_range", compute=lambda _, h=hr: h.get("viable", False),
            reason_fn=lambda old, new, _, h=hr:
                f"Range {h.get('range_pct',0)}% rec {h.get('recovery_pct',0)}%" if new
                else f"BLOCKED:range={h.get('range_pct',0)}%")

    # Breadth — level-firing observer + subscription gate
    breadth_ratio = dip_count / n if n > 0 else 0
    graph.add_node("breadth_dip_level", compute=lambda _: breadth_ratio,
        reason_fn=lambda old, new, _: f"BREADTH_DIP={new:.0%}")
    graph.add_node("breadth_dip_gate",
        compute=lambda inputs: inputs["breadth_dip_level"] >= cfg["breadth_threshold"],
        depends_on=["breadth_dip_level"],
        reason_fn=lambda old, new, _, thresh=cfg["breadth_threshold"]:
            f"BREADTH_GATE(>={thresh:.0%}) {'FIRED' if new else 'NOT FIRED'}")

    graph.resolve()

    # Build state dict with extra per-ticker data for decision phase
    fh_state = graph.get_state()
    for tk in tickers:
        fh_state[f"{tk}:first_hour_low"] = _extract_first_hour_low(prices, tk, n)
        o = _extract_open(prices, tk, n)
        c = _extract_price_at(prices, tk, 10, 30, n)
        fh_state[f"{tk}:dip_pct"] = round((o - c) / o * 100, 1) if o and c and o > 0 else 0

    return graph, fh_state


def build_decision_graph(tickers, prices_11, fh_state, static, hist_ranges,
                         regime, profiles=None, weights=None):
    """Build decision graph: bounce + CANDIDATE AND-gate + RANKER + BUY_DIP.

    Level-firing architecture: observer neurons fire raw values,
    subscription gates compare values to per-ticker thresholds.
    Per-ticker target/stop from profiles. Synapse weights from learning.
    """
    profiles = profiles or {}
    weights = weights or {}
    graph = DependencyGraph()
    cfg = DIP_CONFIG
    n = len(tickers)

    breadth_dip_fired = fh_state.get("breadth_dip_gate", False)

    bounce_count = 0
    candidates = []

    for tk in tickers:
        profile = _get_profile(tk, profiles)
        fh_low = fh_state.get(f"{tk}:first_hour_low")
        current = _extract_latest(prices_11, tk, n)
        bounce_pct = round((current - fh_low) / fh_low * 100, 1) if fh_low and current and fh_low > 0 else 0
        bounced = bounce_pct >= profile["bounce_threshold"]
        if bounced:
            bounce_count += 1

        dip_pct = fh_state.get(f"{tk}:dip_pct", 0)
        dipped = dip_pct >= profile["dip_threshold"]
        st = static.get(tk, {})
        hr = hist_ranges.get(tk, {})
        cat = st.get("catastrophic")
        verdict = st.get("verdict", ["UNKNOWN"])
        v0 = verdict[0] if isinstance(verdict, list) else verdict
        eg = st.get("earnings_gate", "CLEAR")
        viable = st.get("dip_viable", "UNKNOWN")

        # Layer 1: Observer neurons — fire with raw values
        graph.add_node(f"{tk}:dip_level", compute=lambda _, pct=dip_pct: pct,
            reason_fn=lambda old, new, _: f"DIP_LEVEL={new:.1f}%")
        graph.add_node(f"{tk}:bounce_level", compute=lambda _, pct=bounce_pct: pct,
            reason_fn=lambda old, new, _: f"BOUNCE_LEVEL={new:.1f}%")

        # Layer 2: Subscription gates — per-ticker thresholds + learned edge weights
        graph.add_node(f"{tk}:dip_gate",
            compute=lambda inputs, thresh=profile["dip_threshold"], t=tk:
                inputs[f"{t}:dip_level"] >= thresh,
            depends_on=[f"{tk}:dip_level"],
            edge_weights=weights.get(f"{tk}:dip_gate", {}),
            reason_fn=lambda old, new, _, thresh=profile["dip_threshold"]:
                f"DIP_GATE(>={thresh}%) {'ACTIVATED' if new else 'SILENT'}")
        graph.add_node(f"{tk}:bounce_gate",
            compute=lambda inputs, thresh=profile["bounce_threshold"], t=tk:
                inputs[f"{t}:bounce_level"] >= thresh,
            depends_on=[f"{tk}:bounce_level"],
            edge_weights=weights.get(f"{tk}:bounce_gate", {}),
            reason_fn=lambda old, new, _, thresh=profile["bounce_threshold"]:
                f"BOUNCE_GATE(>={thresh}%) {'ACTIVATED' if new else 'SILENT'}")

        # Static gates — NO edge weights (safety gates are never learnable)
        graph.add_node(f"{tk}:dip_viable", compute=lambda _, v=viable: v in ("YES", "CAUTION", "UNKNOWN"),
            reason_fn=lambda old, new, _, v=viable: f"DIP_VIABLE={v}")
        graph.add_node(f"{tk}:not_catastrophic", compute=lambda _, c=cat: c not in ("HARD_STOP", "EXIT_REVIEW"),
            reason_fn=lambda old, new, _, c=cat: "Clear" if new else f"BLOCKED:{c}")
        graph.add_node(f"{tk}:not_exit", compute=lambda _, v=v0: v not in ("EXIT", "REDUCE"),
            reason_fn=lambda old, new, _, v=v0: "Clear" if new else f"BLOCKED:verdict={v}")
        graph.add_node(f"{tk}:earnings_clear", compute=lambda _, e=eg: e not in ("BLOCKED", "FALLING_KNIFE"),
            reason_fn=lambda old, new, _, e=eg: "Clear" if new else f"BLOCKED:earnings={e}")
        graph.add_node(f"{tk}:historical_range", compute=lambda _, h=hr: h.get("viable", False),
            reason_fn=lambda old, new, _, h=hr: "Range OK" if new else "BLOCKED:range")

        # Layer 4: CANDIDATE — soft AND with safety gate hard-AND
        # Safety gates (catastrophic, exit, earnings) ALWAYS hard AND — not learnable
        safety_ok = all([
            cat not in ("HARD_STOP", "EXIT_REVIEW"),
            v0 not in ("EXIT", "REDUCE"),
            eg not in ("BLOCKED", "FALLING_KNIFE"),
        ])
        # Signal gates participate in soft AND (learnable)
        signal_gates = [dipped, bounced,
                        viable in ("YES", "CAUTION", "UNKNOWN"),
                        hr.get("viable", False)]
        signal_score = sum(1.0 for g in signal_gates if g)
        # Soft threshold: at least 3 of 4 signal gates must pass
        is_candidate = safety_ok and signal_score >= 3.0

        graph.add_node(f"{tk}:candidate", compute=lambda _, c=is_candidate: c,
            depends_on=[f"{tk}:dip_gate", f"{tk}:bounce_gate", f"{tk}:dip_viable",
                        f"{tk}:not_catastrophic", f"{tk}:not_exit",
                        f"{tk}:earnings_clear", f"{tk}:historical_range"],
            edge_weights=weights.get(f"{tk}:candidate", {}),
            reason_fn=lambda old, new, _, sc=signal_score:
                f"CANDIDATE score={sc:.0f}/4 + safety OK" if new
                else f"Blocked (score={sc:.0f}/4)")

        if is_candidate:
            candidates.append({
                "ticker": tk, "dip_pct": dip_pct,
                "signal_score": signal_score,
                "signal_probability": round(signal_score / len(signal_gates), 3),
                "entry": round(current, 2) if current else 0,
                "target": round(current * (1 + profile["target_pct"] / 100), 2) if current else 0,
                "stop": round(current * (1 + profile["stop_pct"] / 100), 2) if current else 0,
            })

    # Layer 2: Breadth bounce — level-firing observer + subscription gate
    breadth_bounce_ratio = bounce_count / n if n > 0 else 0
    breadth_bounce_fired = breadth_bounce_ratio >= cfg["breadth_threshold"]
    signal_confirmed = breadth_dip_fired and breadth_bounce_fired

    graph.add_node("breadth_bounce_level", compute=lambda _: breadth_bounce_ratio,
        reason_fn=lambda old, new, _: f"BREADTH_BOUNCE={new:.0%}")
    graph.add_node("breadth_bounce_gate",
        compute=lambda inputs: inputs["breadth_bounce_level"] >= cfg["breadth_threshold"],
        depends_on=["breadth_bounce_level"],
        reason_fn=lambda old, new, _, thresh=cfg["breadth_threshold"]:
            f"BOUNCE_BREADTH_GATE(>={thresh:.0%}) {'FIRED' if new else 'NOT FIRED'}")
    graph.add_node("signal_confirmed", compute=lambda _: signal_confirmed,
        depends_on=["breadth_bounce_gate"],
        reason_fn=lambda old, new, _:
            "CONFIRMED" if new else "NOT CONFIRMED")

    # Layer 5: Portfolio constraints
    pdt_count = _count_pdt_trades()
    pdt_ok = pdt_count < cfg["pdt_limit"]
    capital = _get_dip_capital()
    capital_ok = capital >= cfg["capital_min"]

    graph.add_node("pdt_available", compute=lambda _: pdt_ok,
        reason_fn=lambda old, new, _: f"PDT {pdt_count}/{cfg['pdt_limit']}")
    graph.add_node("capital_available", compute=lambda _: capital_ok,
        reason_fn=lambda old, new, _: f"Capital ${capital:.0f}")

    # Rank candidates by dip magnitude
    candidates.sort(key=lambda c: c["dip_pct"], reverse=True)

    # Layer 5: Portfolio optimization — sector balance + correlation filter
    filtered = candidates
    sector_skipped = []
    corr_skipped = []

    if len(filtered) > 1:
        filtered, sector_skipped = _filter_sector_balance(
            filtered, cfg["max_tickers"], cfg["sector_concentration_pct"])
    if len(filtered) > 1:
        filtered, corr_skipped = _filter_correlated(
            filtered, prices_11, n, cfg["correlation_threshold"])

    top = filtered[:cfg["max_tickers"]]

    # Capital allocation — edge/confidence/risk adjusted within the total dip cap.
    total_budget = cfg["budget_normal"] if regime != "Risk-Off" else cfg["budget_risk_off"]
    budget_per = round(total_budget / len(top), 2) if top else total_budget
    raw_allocations = []
    for c in top:
        target_pct = ((c["target"] - c["entry"]) / c["entry"] * 100) if c["entry"] > 0 else 0
        stop_pct = ((c["stop"] - c["entry"]) / c["entry"] * 100) if c["entry"] > 0 else 0
        p_target = c.get("signal_probability", 0)
        score = score_graph_candidate(
            "dip",
            params={"target_pct": target_pct, "stop_pct": stop_pct},
            stats={"trades": c.get("signal_score", 0), "composite": c.get("signal_score", 0)},
            features={
                "target_hit_rate": p_target,
                "stop_hit_rate": max(0.0, 1.0 - p_target),
                "trade_count": c.get("signal_score", 0),
            },
        )
        allocation = compute_position_allocation(
            budget_per,
            c["entry"],
            features={
                "expected_edge_pct": score["expected_edge_pct"],
                "fill_likelihood": p_target,
                "trade_count": c.get("signal_score", 0),
                "target_pct": target_pct,
                "stop_pct": abs(stop_pct),
            },
            score=score,
            max_dollars=total_budget,
        )
        raw_allocations.append((c, score, allocation))

    raw_total = sum(a["allocated_dollars"] for _, _, a in raw_allocations)
    scale = min(1.0, total_budget / raw_total) if raw_total > 0 else 1.0
    for c, score, allocation in raw_allocations:
        scaled_budget = round(allocation["allocated_dollars"] * scale, 2)
        c["budget"] = scaled_budget
        c["allocation"] = {**allocation, "allocated_dollars": scaled_budget}
        c["score"] = score

    # Layer 6: Terminal BUY_DIP neurons
    for c in top:
        tk = c["ticker"]
        graph.add_node(f"{tk}:buy_dip",
            compute=lambda _, conf=signal_confirmed, pdt=pdt_ok, cap=capital_ok: conf and pdt and cap,
            depends_on=["signal_confirmed", "pdt_available", "capital_available", f"{tk}:candidate"],
            is_report=True,
            reason_fn=lambda old, new, _: "BUY" if new else "NO ACTION")

    # NO_ACTION neuron
    no_buys = not (signal_confirmed and pdt_ok and capital_ok and top)
    graph.add_node("no_action", compute=lambda _: no_buys, is_report=True,
        reason_fn=lambda old, new, _: "No dip play today" if new else "")

    graph.resolve()
    return graph, top, total_budget


# ---------------------------------------------------------------------------
# Portfolio helpers
# ---------------------------------------------------------------------------

def _load_portfolio():
    with open(_ROOT / "portfolio.json") as f:
        return json.load(f)


def _get_dip_candidates(portfolio):
    """Tickers eligible for dip evaluation: positions + watchlist with pending buys."""
    positions = portfolio.get("positions", {})
    watchlist = portfolio.get("watchlist", [])
    pending = portfolio.get("pending_orders", {})
    tickers = set()
    for tk, pos in positions.items():
        if pos.get("shares", 0) > 0:
            tickers.add(tk)
    for tk in watchlist:
        if any(o.get("type") == "BUY" for o in pending.get(tk, [])):
            tickers.add(tk)
    return sorted(tickers)


def _count_pdt_trades():
    """Count same-day exits in last 5 trading days."""
    try:
        with open(_ROOT / "trade_history.json") as f:
            trades = json.load(f).get("trades", [])
        cutoff = (date.today() - timedelta(days=7)).isoformat()
        return sum(1 for t in trades
                   if t.get("date", "") >= cutoff
                   and t.get("exit_reason") == "SAME_DAY_EXIT")
    except Exception:
        return 0


def _get_dip_capital():
    """Return available dip budget."""
    try:
        portfolio = _load_portfolio()
        return portfolio.get("capital", {}).get("dip_pool", 500)
    except Exception:
        return 500


# ---------------------------------------------------------------------------
# Phase evaluation functions
# ---------------------------------------------------------------------------

def evaluate_first_hour(tickers, static, hist_ranges, regime, dry_run=False):
    """10:30 AM: First-hour breadth check. Cache results for decision phase."""
    from notify import send_summary_email

    profiles = _load_profiles()
    syn_weights = _load_weights(regime)
    prices = fetch_intraday(tickers)
    if prices is None:
        print("*yfinance unavailable. Skipping first_hour.*")
        if not dry_run:
            send_summary_email("Dip Check 10:30 — Skipped",
                               "yfinance unavailable. Check ran but no data.")
        return

    graph, fh_state = build_first_hour_graph(
        tickers, prices, static, hist_ranges, regime, profiles, syn_weights)

    # Cache for decision phase
    try:
        FH_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(FH_CACHE_PATH, "w") as f:
            json.dump(fh_state, f, default=str)
    except OSError as e:
        print(f"*Warning: failed to cache first-hour state: {e}*")

    dip_count = sum(1 for tk in tickers if fh_state.get(f"{tk}:dip_gate"))
    breadth = fh_state.get("breadth_dip_gate", False)
    print(f"First-hour: {dip_count}/{len(tickers)} dipped. "
          f"Breadth {'FIRED' if breadth else 'NOT FIRED'}.")

    if not dry_run:
        send_summary_email(
            f"Dip Check 10:30 — {'Signal' if breadth else 'No Signal'}",
            f"Breadth: {dip_count}/{len(tickers)} tickers dipped.\n"
            f"Threshold: 50%. {'FIRED — watch for 11:00 decision.' if breadth else 'No dip signal today.'}\n"
            f"Regime: {regime}")


def evaluate_decision(tickers, static, hist_ranges, regime, dry_run=False):
    """11:00 AM: Full decision — load first-hour cache + bounce + decide."""
    from notify import send_summary_email

    profiles = _load_profiles()
    syn_weights = _load_weights(regime)

    # Load cached first-hour state
    fh_state = {}
    if FH_CACHE_PATH.exists():
        try:
            with open(FH_CACHE_PATH) as f:
                fh_state = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    if not fh_state:
        # Fallback: compute first-hour from current data
        print("*No first-hour cache. Computing from current data.*")
        prices = fetch_intraday(tickers)
        if prices is None:
            print("*yfinance unavailable. Skipping.*")
            if not dry_run:
                send_summary_email("Dip Check 11:00 — Skipped",
                                   "yfinance unavailable. No data for decision phase.")
            return
        _, fh_state = build_first_hour_graph(
            tickers, prices, static, hist_ranges, regime, profiles, syn_weights)

    if not fh_state.get("breadth_dip_gate"):
        print("Breadth dip NOT FIRED. No dip play today.")
        if not dry_run:
            send_summary_email("Dip Check 11:00 — No Dip",
                               "Breadth dip did not fire. No dip play today.")
        return

    # Fetch 11:00 prices
    prices_11 = fetch_intraday(tickers)
    if prices_11 is None:
        print("*yfinance unavailable at decision time. Skipping.*")
        if not dry_run:
            send_summary_email("Dip Check 11:00 — Skipped",
                               "yfinance unavailable at 11:00 decision time.")
        return

    decision_graph, top, budget = build_decision_graph(
        tickers, prices_11, fh_state, static, hist_ranges, regime, profiles,
        syn_weights)

    # Check fired BUY_DIP neurons
    decision_graph.propagate_signals()
    activated = decision_graph.get_activated_reports()
    buy_signals = [(name, node) for name, node in activated
                   if name.endswith(":buy_dip") and node.value]

    if not buy_signals:
        print("No dip play today — signal or candidates blocked.")
        # Show why each ticker was blocked
        blocked_reasons = []
        for tk in tickers:
            cand = decision_graph.nodes.get(f"{tk}:candidate")
            if cand and not cand.value:
                reasons = []
                for dep_name in (cand.depends_on or []):
                    dep = decision_graph.nodes.get(dep_name)
                    if dep and not dep.value and dep.reason_fn:
                        reasons.append(dep.reason_fn(None, dep.value, []))
                if reasons:
                    line = f"  {tk}: {', '.join(reasons)}"
                    print(line)
                    blocked_reasons.append(line)
        if not dry_run:
            body = "No tickers passed all gates.\n\nBlocked:\n" + "\n".join(blocked_reasons) if blocked_reasons else "No tickers passed all gates."
            send_summary_email("Dip Check 11:00 — No Buys", body)
        return

    # Output buy signals
    print(f"\n## Neural Dip Evaluator — {len(buy_signals)} BUY signal(s)\n")
    for name, node in buy_signals:
        tk = name.split(":")[0]
        candidate = next((c for c in top if c["ticker"] == tk), None)
        if not candidate:
            continue

        reason = node.signals[0].flat_reason() if node.signals else "No chain"
        node_path = node.signals[0].node_path_str() if node.signals else ""

        print(f"### {tk}: BUY at ${candidate['entry']:.2f}")
        print(f"- Target: ${candidate['target']:.2f} (+4%)")
        print(f"- Stop: ${candidate['stop']:.2f} (-3%)")
        print(f"- Budget: ${candidate.get('budget', budget)}")
        alloc = candidate.get("allocation", {})
        if alloc:
            print(f"- Allocation: ${candidate.get('budget', budget)} "
                  f"({alloc.get('allocation_action', 'baseline')} "
                  f"{alloc.get('allocation_multiplier', 1.0):.2f}x — "
                  f"{alloc.get('allocation_reason', 'no reason')})")
        print(f"- Regime: {regime}")
        print(f"- Path: {node_path}")
        print(f"- Reason: {reason}")
        print()

        if not dry_run:
            from notify import send_dip_alert
            _budget = candidate.get("budget", budget)
            _shares = max(round(_budget / candidate["entry"]), 1) if candidate["entry"] > 0 else 0
            try:
                from prediction_ledger import artifact_versions, record_prediction

                score = candidate.get("score", {})
                p_target = candidate.get("signal_probability", 0)
                record_prediction(
                    "dip",
                    tk,
                    {
                        "date": date.today().isoformat(),
                        "entry": candidate["entry"],
                        "target": candidate["target"],
                        "stop": candidate["stop"],
                        "budget": _budget,
                        "shares": _shares,
                        "allocated_dollars": candidate.get("budget"),
                        "allocation_multiplier": (candidate.get("allocation") or {}).get("allocation_multiplier"),
                        "allocation_action": (candidate.get("allocation") or {}).get("allocation_action"),
                        "regime": regime,
                        "dip_pct": round(candidate.get("dip_pct", 0), 3),
                    },
                    features={
                        "historical_range": hist_ranges.get(tk, {}),
                        "signal_score": candidate.get("signal_score"),
                        "signal_probability": p_target,
                        "regime": regime,
                        "allocation_reason": (candidate.get("allocation") or {}).get("allocation_reason"),
                    },
                    score=score,
                    artifact_versions=artifact_versions({
                        "ticker_profiles": PROFILES_PATH,
                        "synapse_weights": _ROOT / "data" / "synapse_weights.json",
                        "probability_calibration": _ROOT / "data" / "probability_calibration.json",
                    }),
                    reason=f"{node_path}\n{reason}",
                )
            except Exception as e:
                print(f"*Warning: prediction ledger write failed for {tk}: {e}*")
            send_dip_alert(tk, candidate["entry"], candidate["target"],
                          candidate["stop"], f"{node_path}\n{reason}",
                          regime, _budget, shares=_shares)


def evaluate_eod(tickers, dry_run=False):
    """3:45 PM: Check for unfilled same-day dip sells."""
    from notify import send_summary_email

    try:
        portfolio = _load_portfolio()
    except Exception:
        print("*Cannot load portfolio for EOD check.*")
        if not dry_run:
            send_summary_email("Dip EOD 3:45 — Skipped",
                               "Cannot load portfolio for EOD check.")
        return

    pending = portfolio.get("pending_orders", {})
    unfilled = []
    for tk in tickers:
        for order in pending.get(tk, []):
            if (order.get("type") == "SELL" and
                    "same-day" in order.get("note", "").lower()):
                unfilled.append((tk, order["price"], order.get("shares", 0)))

    if unfilled:
        print(f"\n## EOD Check — {len(unfilled)} unfilled same-day exit(s)\n")
        lines = []
        for tk, price, shares in unfilled:
            line = f"- {tk}: SELL @ ${price:.2f} x {shares} — consider manual close or hold"
            print(line)
            lines.append(line)
        if not dry_run:
            send_summary_email(f"Dip EOD 3:45 — {len(unfilled)} Unfilled",
                               "\n".join(lines))
    else:
        print("EOD: No unfilled same-day exits.")
        if not dry_run:
            send_summary_email("Dip EOD 3:45 — No Unfilled Exits",
                               "No same-day dip exits were left unfilled today.")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Neural Dip Evaluator")
    parser.add_argument("--phase", choices=["first_hour", "decision", "eod_check"],
                        default="decision")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print results but don't send email")
    args = parser.parse_args()

    # Gate: trading day
    if not is_trading_day():
        print(f"Market closed ({date.today()}). Skipping.")
        return

    # Gate: market phase validation
    actual_phase = get_market_phase()
    valid = VALID_PHASES_FOR_MARKET.get(args.phase, ())
    if actual_phase not in valid and actual_phase != "CLOSED":
        print(f"*Phase mismatch: requested {args.phase}, market is {actual_phase}. "
              f"Expected: {valid}. Proceeding anyway.*")

    # Load context
    portfolio = _load_portfolio()
    tickers = _get_dip_candidates(portfolio)
    if not tickers:
        print("No dip candidates (no positions or watchlist tickers).")
        return

    regime, vix, static = load_static_context(tickers)
    hist_ranges = compute_historical_ranges(tickers)

    print(f"Neural Dip Evaluator — {args.phase} | {len(tickers)} tickers | "
          f"Regime: {regime} | {datetime.now(ET).strftime('%H:%M ET')}")

    if args.phase == "first_hour":
        evaluate_first_hour(tickers, static, hist_ranges, regime, args.dry_run)
    elif args.phase == "decision":
        evaluate_decision(tickers, static, hist_ranges, regime, args.dry_run)
    elif args.phase == "eod_check":
        evaluate_eod(tickers, args.dry_run)


if __name__ == "__main__":
    main()
