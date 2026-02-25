"""Surgical Pre-Critic — mechanical confidence modifiers, FAIL filtering, ranking.

Reads candidate-verification.json, candidate_shortlist.json, screening_data.json,
and portfolio.json. Computes deterministic confidence modifiers (4 components),
filters FAIL candidates, ranks by final score, builds bullet summaries and
portfolio impact. Writes candidate-pre-critic.md for the LLM critic.

Usage:
    python3 tools/surgical_pre_critic.py
"""
import json
import sys
import datetime
from pathlib import Path

# Same-directory imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
from surgical_filter import SECTOR_CONCENTRATION_LIMIT
from surgical_screener import SECTOR_MAP

ROOT = Path(__file__).resolve().parent.parent
VERIFICATION_JSON_PATH = ROOT / "candidate-verification.json"
SHORTLIST_JSON_PATH = ROOT / "candidate_shortlist.json"
SCREENING_DATA_PATH = ROOT / "screening_data.json"
PORTFOLIO_PATH = ROOT / "portfolio.json"
OUTPUT_PATH = ROOT / "candidate-pre-critic.md"

VALID_VERDICTS = {"PASS", "FLAG", "FAIL"}


# ---------------------------------------------------------------------------
# Input Validation
# ---------------------------------------------------------------------------

def validate_inputs():
    """Load and validate all 4 input JSON files.

    Returns (verification, shortlist, screening, portfolio) or exits.
    """
    # --- candidate-verification.json ---
    if not VERIFICATION_JSON_PATH.exists():
        print(f"*Error: {VERIFICATION_JSON_PATH.name} not found — verifier must write JSON output*")
        sys.exit(1)
    try:
        verification = json.loads(VERIFICATION_JSON_PATH.read_text())
    except json.JSONDecodeError as e:
        print(f"*Error: {VERIFICATION_JSON_PATH.name} is malformed JSON: {e}*")
        sys.exit(1)
    if not verification.get("candidates"):
        print(f"*Error: {VERIFICATION_JSON_PATH.name} has empty candidates list*")
        sys.exit(1)

    # Validate candidate schema
    required_fields = ["ticker", "original_score", "adjustment", "adjusted_score", "verdict"]
    for i, cand in enumerate(verification["candidates"]):
        missing = [f for f in required_fields if f not in cand]
        if missing:
            print(f"*Error: {VERIFICATION_JSON_PATH.name} candidate #{i+1} missing: {', '.join(missing)}*")
            sys.exit(1)
        if cand["verdict"] not in VALID_VERDICTS:
            print(f"*Error: {VERIFICATION_JSON_PATH.name} candidate #{i+1} ({cand['ticker']}) "
                  f"invalid verdict \"{cand['verdict']}\" — expected one of {sorted(VALID_VERDICTS)}*")
            sys.exit(1)

    # --- candidate_shortlist.json ---
    if not SHORTLIST_JSON_PATH.exists():
        print(f"*Error: {SHORTLIST_JSON_PATH.name} not found — run surgical_filter.py first*")
        sys.exit(1)
    try:
        shortlist = json.loads(SHORTLIST_JSON_PATH.read_text())
    except json.JSONDecodeError as e:
        print(f"*Error: {SHORTLIST_JSON_PATH.name} is malformed JSON: {e}*")
        sys.exit(1)

    # --- screening_data.json ---
    if not SCREENING_DATA_PATH.exists():
        print(f"*Error: {SCREENING_DATA_PATH.name} not found — run surgical_screener.py first*")
        sys.exit(1)
    try:
        screening = json.loads(SCREENING_DATA_PATH.read_text())
    except json.JSONDecodeError as e:
        print(f"*Error: {SCREENING_DATA_PATH.name} is malformed JSON: {e}*")
        sys.exit(1)

    # --- portfolio.json ---
    if not PORTFOLIO_PATH.exists():
        print(f"*Error: {PORTFOLIO_PATH.name} not found*")
        sys.exit(1)
    try:
        portfolio = json.loads(PORTFOLIO_PATH.read_text())
    except json.JSONDecodeError as e:
        print(f"*Error: {PORTFOLIO_PATH.name} is malformed JSON: {e}*")
        sys.exit(1)

    # Type coercion + arithmetic integrity (LLMs may emit strings or wrong sums)
    for cand in verification["candidates"]:
        for int_field in ("original_score", "adjustment", "adjusted_score"):
            try:
                cand[int_field] = int(cand[int_field])
            except (ValueError, TypeError):
                print(f"*Error: {VERIFICATION_JSON_PATH.name} candidate {cand.get('ticker', '?')} "
                      f"has non-numeric {int_field}: {cand[int_field]!r}*")
                sys.exit(1)
        expected = cand["original_score"] + cand["adjustment"]
        if cand["adjusted_score"] != expected:
            print(f"*Warning: {cand['ticker']} adjusted_score mismatch — "
                  f"original {cand['original_score']} + adjustment {cand['adjustment']} "
                  f"= {expected}, but JSON says {cand['adjusted_score']}. Using computed value.*")
            cand["adjusted_score"] = expected

    # Cross-validate: verification tickers must be in shortlist
    shortlist_tickers = {e["ticker"] for e in shortlist.get("shortlist", [])}
    for cand in verification["candidates"]:
        if cand["ticker"] not in shortlist_tickers:
            print(f"*Warning: phantom ticker {cand['ticker']} in verification — not in shortlist, skipping*")

    # Freshness: compare generated timestamps
    ver_ts = verification.get("generated", "")
    shortlist_ts = shortlist.get("generated", "")
    screening_ts = screening.get("generated", "")
    if ver_ts and shortlist_ts and ver_ts < shortlist_ts:
        print(f"*Warning: {VERIFICATION_JSON_PATH.name} ({ver_ts}) older than "
              f"{SHORTLIST_JSON_PATH.name} ({shortlist_ts}) — files may be stale*")
    if shortlist_ts and screening_ts and shortlist_ts < screening_ts:
        print(f"*Warning: {SHORTLIST_JSON_PATH.name} ({shortlist_ts}) older than "
              f"{SCREENING_DATA_PATH.name} ({screening_ts}) — files may be stale*")

    return verification, shortlist, screening, portfolio


# ---------------------------------------------------------------------------
# FAIL Filtering
# ---------------------------------------------------------------------------

def filter_fail_candidates(verification, shortlist_lookup):
    """Remove candidates with FAIL verdict or wick_failed.

    Returns (eligible, eliminated) where eligible is a list of raw
    verification candidate dicts and eliminated is a list of
    {"ticker": str, "reason": str} dicts.
    """
    eligible = []
    eliminated = []

    for cand in verification["candidates"]:
        ticker = cand["ticker"]
        sl_entry = shortlist_lookup.get(ticker)

        if not sl_entry:
            eliminated.append({
                "ticker": ticker,
                "reason": "Not in shortlist (phantom ticker)",
            })
            continue

        if sl_entry.get("wick_failed"):
            eliminated.append({
                "ticker": ticker,
                "reason": "Wick analysis failed — modifier not computable",
            })
            continue

        if cand["verdict"] == "FAIL":
            eliminated.append({
                "ticker": ticker,
                "reason": f"FAIL verdict: {cand.get('key_finding', 'no details')}",
            })
            continue

        eligible.append(cand)

    return eligible, eliminated


# ---------------------------------------------------------------------------
# Confidence Modifier Components
# ---------------------------------------------------------------------------

def _compute_sample_size(shortlist_entry):
    """Sample Size component: -10 to +5."""
    sm = shortlist_entry.get("stress_metrics", {})
    ver = shortlist_entry.get("verification", {})

    all_above_3 = sm.get("all_active_above_3", False)
    min_approaches = sm.get("min_active_approaches", 0)
    sample_flags = ver.get("sample_size_flags", [])

    score = 0
    if all_above_3 and min_approaches >= 6:
        score = 5
    elif all_above_3:
        score = 2
    else:
        score = -5

    if sample_flags:
        score -= 5

    return max(-10, min(5, score))


def _compute_recency(shortlist_entry, screening_data):
    """Recency component: -10 to +3. Active-zone levels only."""
    ticker = shortlist_entry["ticker"]
    recency_detail = shortlist_entry.get("verification", {}).get("recency_detail", [])

    # Get active-zone support prices from screening_data bullet plan
    wick = screening_data.get("wick_analyses", {}).get(ticker, {})
    bp = wick.get("bullet_plan", {})
    active_supports = {round(b["support_price"], 2) for b in bp.get("active", [])}

    if not active_supports:
        return 0

    # Count trends for active-zone levels only
    deteriorating_count = 0
    zero_hold_count = 0
    improving_count = 0
    total_active_with_data = 0

    for rd in recency_detail:
        sp = round(rd["support_price"], 2)
        if sp not in active_supports:
            continue
        if rd.get("recent_events", 0) <= 0:
            continue

        total_active_with_data += 1
        trend = rd.get("trend", "")

        if trend == "Deteriorating":
            deteriorating_count += 1
        if rd.get("recent_hold_pct") == 0:
            zero_hold_count += 1
        if trend == "Improving":
            improving_count += 1

    # Evaluate top to bottom, first match wins
    if zero_hold_count >= 2:
        return -10
    if zero_hold_count == 1:
        return -7
    if deteriorating_count >= 2 and zero_hold_count == 0:
        return -5
    if deteriorating_count == 1 and zero_hold_count == 0:
        return -3
    if deteriorating_count == 0 and total_active_with_data > 0 and improving_count == total_active_with_data:
        return 3
    if deteriorating_count == 0 and total_active_with_data > 0 and improving_count >= total_active_with_data * 0.5:
        return 1
    return 0


def _compute_portfolio_fit(shortlist_entry):
    """Portfolio Fit component: -5 to +5."""
    sm = shortlist_entry.get("stress_metrics", {})
    sector_count = sm.get("sector_count_after", 0)
    exceeds = sm.get("sector_exceeds_limit", False)

    if sector_count >= SECTOR_CONCENTRATION_LIMIT or exceeds:
        return -5
    if sector_count == 2:
        return 0
    if sector_count == 1:
        return 5
    return 0


def _compute_entry_timing(shortlist_entry):
    """Entry Timing component: -5 to +5."""
    sm = shortlist_entry.get("stress_metrics", {})
    b1_dist = sm.get("b1_distance_pct", 100.0)

    if b1_dist <= 3.0:
        return 5
    if b1_dist <= 5.0:
        return 3
    if b1_dist <= 10.0:
        return 0
    if b1_dist <= 15.0:
        return -3
    return -5


def compute_confidence_modifier(shortlist_entry, screening_data):
    """Compute 4-component confidence modifier for one candidate.

    Returns dict with component scores and totals.
    """
    sample = _compute_sample_size(shortlist_entry)
    recency = _compute_recency(shortlist_entry, screening_data)
    fit = _compute_portfolio_fit(shortlist_entry)
    timing = _compute_entry_timing(shortlist_entry)

    raw_total = sample + recency + fit + timing
    capped_total = max(-10, min(10, raw_total))

    return {
        "sample_size": sample,
        "recency": recency,
        "portfolio_fit": fit,
        "entry_timing": timing,
        "raw_total": raw_total,
        "capped_total": capped_total,
    }


# ---------------------------------------------------------------------------
# Final Scores & Ranking
# ---------------------------------------------------------------------------

def compute_final_scores(eligible, modifiers):
    """Compute final scores and rank candidates.

    Returns sorted list of dicts (descending by final_score, then
    adjusted_score descending, then ticker alphabetically for determinism).
    """
    ranked = []
    for cand in eligible:
        ticker = cand["ticker"]
        mod = modifiers[ticker]
        adjusted_score = cand["adjusted_score"]
        final_score = adjusted_score + mod["capped_total"]

        ranked.append({
            "ticker": ticker,
            "original_score": cand["original_score"],
            "adjustment": cand["adjustment"],
            "adjusted_score": adjusted_score,
            "verdict": cand["verdict"],
            "key_finding": cand.get("key_finding", ""),
            "modifier_components": mod,
            "capped_modifier": mod["capped_total"],
            "final_score": final_score,
        })

    ranked.sort(key=lambda x: (-x["final_score"], -x["adjusted_score"], x["ticker"]))

    # Assign ranks
    for i, entry in enumerate(ranked):
        entry["rank"] = i + 1

    return ranked


# ---------------------------------------------------------------------------
# Bullet Summary
# ---------------------------------------------------------------------------

def build_bullet_summary(ticker, screening_data):
    """Extract bullet plan summary for one ticker.

    Returns dict with keys: bullets (list), active_total, reserve_total, all_in.
    """
    wick = screening_data.get("wick_analyses", {}).get(ticker, {})
    bp = wick.get("bullet_plan", {})
    if not bp:
        return {"bullets": [], "active_total": 0, "reserve_total": 0, "all_in": 0}

    bullets = []
    for zone_key in ("active", "reserve"):
        for b in bp.get(zone_key, []):
            bullets.append({
                "zone": b.get("zone", zone_key.capitalize()),
                "support_price": b["support_price"],
                "buy_at": b["buy_at"],
                "hold_rate": b["hold_rate"],
                "tier": b.get("tier", ""),
                "shares": b["shares"],
                "cost": b["cost"],
            })

    active_total = bp.get("active_total_cost", sum(b["cost"] for b in bp.get("active", [])))
    reserve_total = bp.get("reserve_total_cost", sum(b["cost"] for b in bp.get("reserve", [])))

    return {
        "bullets": bullets,
        "active_total": active_total,
        "reserve_total": reserve_total,
        "all_in": active_total + reserve_total,
    }


# ---------------------------------------------------------------------------
# Portfolio Impact
# ---------------------------------------------------------------------------

def build_portfolio_impact(ranked, shortlist_lookup, screening_data, portfolio, top_n=3):
    """Compute portfolio impact if top N candidates were onboarded.

    Returns dict with sector exposure, capital, and position counts.
    """
    top = ranked[:top_n]
    if not top:
        return {}

    # Current active position count (pending-order-only tickers NOT counted)
    active_count = len(portfolio.get("positions", {}))
    new_sectors = []
    per_candidate = []
    total_active_cost = 0
    total_reserve_cost = 0
    total_all_in = 0

    for entry in top:
        ticker = entry["ticker"]
        sl = shortlist_lookup.get(ticker, {})
        sm = sl.get("stress_metrics", {})

        # Sector info
        passer = sl.get("passer", {})
        sector = passer.get("sector", SECTOR_MAP.get(ticker, "Unknown"))

        # Capital from screening_data bullet plan
        wick = screening_data.get("wick_analyses", {}).get(ticker, {})
        bp = wick.get("bullet_plan", {})
        act_cost = bp.get("active_total_cost", sm.get("active_total_cost", 0))
        res_cost = bp.get("reserve_total_cost", sm.get("reserve_total_cost", 0))
        all_in = sm.get("all_in_cost", act_cost + res_cost)

        per_candidate.append({
            "ticker": ticker,
            "sector": sector,
            "active_cost": round(act_cost, 2),
            "reserve_cost": round(res_cost, 2),
            "all_in_cost": round(all_in, 2),
        })

        total_active_cost += act_cost
        total_reserve_cost += res_cost
        total_all_in += all_in

        # Check if sector is new
        if sm.get("sector_count_after", 0) == 1:
            new_sectors.append(f"{ticker} ({sector})")

    return {
        "per_candidate": per_candidate,
        "new_sectors": new_sectors,
        "total_active_cost": round(total_active_cost, 2),
        "total_reserve_cost": round(total_reserve_cost, 2),
        "total_all_in_cost": round(total_all_in, 2),
        "positions_before": active_count,
        "positions_after": active_count + len(top),
    }


# ---------------------------------------------------------------------------
# Report Builder
# ---------------------------------------------------------------------------

def build_report(eliminated, ranked, bullet_summaries, portfolio_impact):
    """Generate candidate-pre-critic.md with all mechanical findings."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = []

    lines.append("# Mechanical Pre-Critic Report")
    lines.append(f"*Generated: {now} | Tool: surgical_pre_critic.py*")
    lines.append("")

    # --- 1. Elimination Log ---
    lines.append("## Elimination Log")
    if eliminated:
        lines.append("")
        lines.append("| Ticker | Reason |")
        lines.append("| :--- | :--- |")
        for e in eliminated:
            lines.append(f"| {e['ticker']} | {e['reason']} |")
    else:
        lines.append("No candidates eliminated.")
    lines.append("")

    # --- 2. Confidence Modifier Table ---
    lines.append("## Confidence Modifier Table")
    lines.append("")
    lines.append("| Ticker | Adjusted Score | Sample Size | Recency | Portfolio Fit | Entry Timing | Raw | Capped | Pre-Critic Score | Rank |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    for entry in ranked:
        mod = entry["modifier_components"]
        lines.append(
            f"| {entry['ticker']} "
            f"| {entry['adjusted_score']} "
            f"| {_fmt_modifier(mod['sample_size'])} "
            f"| {_fmt_modifier(mod['recency'])} "
            f"| {_fmt_modifier(mod['portfolio_fit'])} "
            f"| {_fmt_modifier(mod['entry_timing'])} "
            f"| {_fmt_modifier(mod['raw_total'])} "
            f"| {_fmt_modifier(mod['capped_total'])} "
            f"| {entry['final_score']} "
            f"| {entry['rank']} |"
        )
    lines.append("")

    # --- 3. Per-Candidate Bullet Summary ---
    lines.append("## Per-Candidate Bullet Summary")
    lines.append("")

    for entry in ranked:
        ticker = entry["ticker"]
        bs = bullet_summaries.get(ticker)
        if not bs or not bs["bullets"]:
            lines.append(f"### {ticker} (Rank #{entry['rank']})")
            lines.append("*No bullet plan data available.*")
            lines.append("")
            continue

        lines.append(f"### {ticker} (Rank #{entry['rank']})")
        lines.append("")
        lines.append("| Zone | Support | Buy At | Hold Rate | Tier | Shares | Cost |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

        for b in bs["bullets"]:
            lines.append(
                f"| {b['zone']} "
                f"| ${b['support_price']:.2f} "
                f"| ${b['buy_at']:.2f} "
                f"| {b['hold_rate']:.0f}% "
                f"| {b['tier']} "
                f"| {b['shares']} "
                f"| ${b['cost']:.2f} |"
            )

        lines.append(
            f"| **Totals** | | | | | "
            f"| Active: ${bs['active_total']:.2f}, Reserve: ${bs['reserve_total']:.2f}, "
            f"All-in: ${bs['all_in']:.2f} |"
        )
        lines.append("")

    # --- 4. Portfolio Impact Table ---
    if portfolio_impact and portfolio_impact.get("per_candidate"):
        lines.append("## Portfolio Impact (Top 3 Onboarded)")
        lines.append("")

        # Per-candidate capital
        lines.append("| Ticker | Sector | Active Cost | Reserve Cost | All-In Cost |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for pc in portfolio_impact["per_candidate"]:
            lines.append(
                f"| {pc['ticker']} "
                f"| {pc['sector']} "
                f"| ${pc['active_cost']:.2f} "
                f"| ${pc['reserve_cost']:.2f} "
                f"| ${pc['all_in_cost']:.2f} |"
            )
        lines.append(
            f"| **Total** | | "
            f"${portfolio_impact['total_active_cost']:.2f} | "
            f"${portfolio_impact['total_reserve_cost']:.2f} | "
            f"${portfolio_impact['total_all_in_cost']:.2f} |"
        )
        lines.append("")

        # Summary
        if portfolio_impact["new_sectors"]:
            lines.append(f"- **New sectors:** {', '.join(portfolio_impact['new_sectors'])}")
        else:
            lines.append("- **New sectors:** None")
        lines.append(f"- **Active positions:** {portfolio_impact['positions_before']} → "
                      f"{portfolio_impact['positions_after']}")
        lines.append("")

    # --- 5. Status Line ---
    lines.append("---")
    lines.append(f"Pre-critic: {len(ranked)} candidates ranked, {len(eliminated)} eliminated. "
                 f"LLM critic adjusts final scores by +/-10.")
    lines.append("")

    return "\n".join(lines)


def _fmt_modifier(val):
    """Format modifier value with explicit + sign for positives."""
    if val > 0:
        return f"+{val}"
    return str(val)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Surgical Pre-Critic")
    print("=" * 40)

    verification, shortlist, screening, portfolio = validate_inputs()

    # Build lookup
    shortlist_lookup = {e["ticker"]: e for e in shortlist.get("shortlist", [])}

    print(f"Loaded: {len(verification['candidates'])} verified, "
          f"{len(shortlist_lookup)} shortlisted")

    # Filter FAILs
    eligible, eliminated = filter_fail_candidates(verification, shortlist_lookup)
    print(f"Eligible: {len(eligible)}, Eliminated: {len(eliminated)}")
    for e in eliminated:
        print(f"  Eliminated {e['ticker']}: {e['reason']}")

    if not eligible:
        print("*Warning: no eligible candidates after FAIL filtering — report will contain only elimination log*")

    # Compute modifiers for eligible candidates
    modifiers = {}
    for cand in eligible:
        ticker = cand["ticker"]
        sl_entry = shortlist_lookup[ticker]
        modifiers[ticker] = compute_confidence_modifier(sl_entry, screening)

    # Rank
    ranked = compute_final_scores(eligible, modifiers)
    print(f"\nRanked candidates:")
    for entry in ranked:
        mod = entry["modifier_components"]
        print(f"  #{entry['rank']} {entry['ticker']}: "
              f"adj={entry['adjusted_score']} + mod={entry['capped_modifier']} "
              f"= final {entry['final_score']} "
              f"[S={mod['sample_size']}, R={mod['recency']}, "
              f"F={mod['portfolio_fit']}, T={mod['entry_timing']}]")

    # Bullet summaries
    bullet_summaries = {}
    for entry in ranked:
        bullet_summaries[entry["ticker"]] = build_bullet_summary(entry["ticker"], screening)

    # Portfolio impact for top 3
    portfolio_impact = build_portfolio_impact(ranked, shortlist_lookup, screening, portfolio, top_n=3)

    # Build and write report
    report = build_report(eliminated, ranked, bullet_summaries, portfolio_impact)
    OUTPUT_PATH.write_text(report)
    print(f"\nWrote {OUTPUT_PATH.name}")


if __name__ == "__main__":
    main()
