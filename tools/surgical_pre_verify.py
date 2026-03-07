"""Surgical Pre-Verifier — mechanical cross-verification using JSON inputs.

Reads candidate_shortlist.json, candidate-evaluation.json, candidate-evaluation.md,
and screening_data.json. Runs 7 deterministic checks and writes candidate-pre-verify.md
with findings for the LLM verifier.

Usage:
    python3 tools/surgical_pre_verify.py
"""
import json
import re
import sys
import datetime
from pathlib import Path

# Same-directory imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
from surgical_screener import SECTOR_MAP
from surgical_filter import RECENCY_WINDOW_DAYS, RECENCY_DROP_THRESHOLD

ROOT = Path(__file__).resolve().parent.parent
SCREENING_DATA_PATH = ROOT / "screening_data.json"
JSON_INPUT_PATH = ROOT / "candidate_shortlist.json"
EVAL_JSON_PATH = ROOT / "candidate-evaluation.json"
EVAL_MD_PATH = ROOT / "candidate-evaluation.md"
OUTPUT_PATH = ROOT / "candidate-pre-verify.md"

VALID_RECOMMENDATIONS = {"Onboard", "Watch", "Monitor"}


# ---------------------------------------------------------------------------
# Input Validation
# ---------------------------------------------------------------------------

def validate_inputs():
    """Check all required input files exist and are reasonably fresh.

    Returns (shortlist_json, eval_json, eval_text, screening_data) or exits.
    """
    if not SCREENING_DATA_PATH.exists():
        print(f"*Error: {SCREENING_DATA_PATH.name} not found — run surgical_screener.py first*")
        sys.exit(1)
    try:
        screening_data = json.loads(SCREENING_DATA_PATH.read_text())
    except json.JSONDecodeError as e:
        print(f"*Error: {SCREENING_DATA_PATH.name} is malformed JSON: {e}*")
        sys.exit(1)

    if not JSON_INPUT_PATH.exists():
        print(f"*Error: {JSON_INPUT_PATH.name} not found — run surgical_filter.py first*")
        sys.exit(1)
    try:
        shortlist_json = json.loads(JSON_INPUT_PATH.read_text())
    except json.JSONDecodeError as e:
        print(f"*Error: {JSON_INPUT_PATH.name} is malformed JSON: {e}*")
        sys.exit(1)
    if len(shortlist_json.get("shortlist", [])) == 0:
        print(f"*Error: {JSON_INPUT_PATH.name} has empty shortlist — nothing to verify*")
        sys.exit(1)

    if not EVAL_JSON_PATH.exists():
        print(f"*Error: {EVAL_JSON_PATH.name} not found — evaluator must write JSON output*")
        sys.exit(1)
    try:
        eval_json = json.loads(EVAL_JSON_PATH.read_text())
    except json.JSONDecodeError as e:
        print(f"*Error: {EVAL_JSON_PATH.name} is malformed JSON: {e}*")
        sys.exit(1)
    if len(eval_json.get("candidates", [])) == 0:
        print(f"*Error: {EVAL_JSON_PATH.name} has empty candidates list*")
        sys.exit(1)

    # Validate candidate schema
    required_fields = ["rank", "ticker", "score", "key_flags", "recommendation"]
    for i, cand in enumerate(eval_json["candidates"]):
        missing = [f for f in required_fields if f not in cand]
        if missing:
            field_list = ", ".join(missing)
            print(f"*Error: {EVAL_JSON_PATH.name} candidate #{i+1} missing fields: {field_list}*")
            sys.exit(1)
        if not isinstance(cand.get("key_flags"), list):
            print(f"*Error: {EVAL_JSON_PATH.name} candidate #{i+1} key_flags must be a list*")
            sys.exit(1)
        rec = cand.get("recommendation", "")
        if rec not in VALID_RECOMMENDATIONS:
            print(f"*Warning: {EVAL_JSON_PATH.name} candidate #{i+1} ({cand.get('ticker', '?')}) "
                  f"has unexpected recommendation \"{rec}\" — expected one of {sorted(VALID_RECOMMENDATIONS)}*")

    if not EVAL_MD_PATH.exists():
        print(f"*Error: {EVAL_MD_PATH.name} not found — evaluator phase must complete first*")
        sys.exit(1)
    eval_text = EVAL_MD_PATH.read_text()

    # Freshness: compare generated timestamps
    shortlist_ts = shortlist_json.get("generated", "")
    screening_ts = screening_data.get("generated", "")
    if shortlist_ts and screening_ts and shortlist_ts < screening_ts:
        print(f"*Warning: {JSON_INPUT_PATH.name} ({shortlist_ts}) older than "
              f"{SCREENING_DATA_PATH.name} ({screening_ts}) — files may be stale*")

    eval_ts = eval_json.get("generated", "")
    if eval_ts and shortlist_ts and eval_ts < shortlist_ts:
        print(f"*Warning: {EVAL_JSON_PATH.name} ({eval_ts}) older than "
              f"{JSON_INPUT_PATH.name} ({shortlist_ts}) — evaluation may be stale*")

    return shortlist_json, eval_json, eval_text, screening_data


# ---------------------------------------------------------------------------
# Check 1: Evaluation Score & Recommendation Match (JSON-to-JSON)
# ---------------------------------------------------------------------------

def check_evaluation_scores(eval_json, shortlist_json):
    """Compare evaluator's scores/recommendations against shortlist JSON.

    Returns: {"mismatches": [...], "missing_from_eval": [...], "extra_in_eval": [...]}
    """
    shortlist_lookup = {
        entry["ticker"]: entry for entry in shortlist_json["shortlist"]
    }
    eval_lookup = {
        cand["ticker"]: cand for cand in eval_json["candidates"]
    }

    mismatches = []
    for ticker, sl_entry in shortlist_lookup.items():
        if ticker not in eval_lookup:
            continue
        ev = eval_lookup[ticker]
        if ev["score"] != sl_entry["total_score"]:
            mismatches.append({
                "ticker": ticker,
                "shortlist_score": sl_entry["total_score"],
                "eval_score": ev["score"],
            })

    # Check for omissions (both directions)
    missing_from_eval = [
        t for t in shortlist_lookup if t not in eval_lookup
    ]
    extra_in_eval = [
        t for t in eval_lookup if t not in shortlist_lookup
    ]

    return {
        "mismatches": mismatches,
        "missing_from_eval": missing_from_eval,
        "extra_in_eval": extra_in_eval,
    }


# ---------------------------------------------------------------------------
# Check 2: Flag Coverage in Prose
# ---------------------------------------------------------------------------

def _split_eval_sections(eval_text):
    """Split evaluation markdown into per-ticker sections.

    Header format depends on evaluator LLM output. Pattern matches:
      ## Candidate #1: RGTI   /  ## 1: RGTI  /  ## Candidate 1 — RGTI
    If zero sections parsed, prints a warning — likely the LLM used an
    unexpected header format and all flags will report as "missed".
    """
    pattern = re.compile(r'##\s+(?:Candidate\s+)?#?\d+[:\s—–-]+([A-Z]+)', re.IGNORECASE)
    sections = {}
    matches = list(pattern.finditer(eval_text))
    for i, m in enumerate(matches):
        ticker = m.group(1).upper()
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(eval_text)
        sections[ticker] = eval_text[start:end]
    if not sections and eval_text.strip():
        print("*Warning: could not parse any per-ticker sections from candidate-evaluation.md "
              "— flag coverage check may report false misses*")
    return sections


def _extract_flag_keywords(flag):
    """Extract 2-3 search keywords from a flag string."""
    flag_lower = flag.lower()
    if "recency" in flag_lower and "deteriorat" in flag_lower:
        return ["recency", "deteriorat"]
    if "sample" in flag_lower and "size" in flag_lower:
        return ["sample", "size"]
    if "sector" in flag_lower and "concentrat" in flag_lower:
        return ["sector", "concentrat"]
    if "budget" in flag_lower and "exceed" in flag_lower:
        return ["budget", "exceed"]
    if "gap" in flag_lower and "reserve" in flag_lower:
        return ["gap", "reserve"]
    if "wick" in flag_lower and "fail" in flag_lower:
        return ["wick", "fail"]
    # Default: first word + longest word after colon
    parts = flag.split(":", 1)
    first_word = parts[0].strip().split()[0].lower() if parts[0].strip() else ""
    if len(parts) > 1:
        words = parts[1].strip().split()
        longest = max(words, key=len).lower() if words else ""
    else:
        words = flag.strip().split()
        longest = max(words[1:], key=len).lower() if len(words) > 1 else ""
    return [kw for kw in [first_word, longest] if kw]


def _is_mechanical_flag(flag):
    """Check if a flag is a mechanical verification issue (skip for prose coverage)."""
    # Tier/bullet-math issues: "TICKER $NN.NN: cost..."
    if re.match(r'^[A-Z]+ \$[\d.]+:', flag):
        return True
    # Pool deployment issues: "TICKER: active/reserve deployment..."
    if re.match(r'^[A-Z]+: (?:active|reserve) deployment', flag):
        return True
    return False


def check_flag_coverage(shortlist_json, eval_text):
    """Check if evaluator addressed each quality flag from the shortlist.

    Returns: dict of {ticker: {"addressed": [...], "missed": [...], "skipped_mechanical": int, "skipped_unparseable": int}}
    """
    sections = _split_eval_sections(eval_text)
    results = {}

    for entry in shortlist_json["shortlist"]:
        ticker = entry["ticker"]
        flags = entry.get("flags", [])
        section = sections.get(ticker, "")
        section_lower = section.lower()

        addressed = []
        missed = []
        skipped = 0
        skipped_unparseable = 0

        for flag in flags:
            if _is_mechanical_flag(flag):
                skipped += 1
                continue
            keywords = _extract_flag_keywords(flag)
            if not keywords:
                skipped_unparseable += 1
                continue
            if all(kw in section_lower for kw in keywords):
                addressed.append(flag)
            else:
                missed.append(flag)

        results[ticker] = {
            "addressed": addressed,
            "missed": missed,
            "skipped_mechanical": skipped,
            "skipped_unparseable": skipped_unparseable,
        }

    return results


# ---------------------------------------------------------------------------
# Check 3: Sector Classification Audit
# ---------------------------------------------------------------------------

def audit_sector_classifications(screening_data):
    """Check portfolio tickers for sector misclassifications.

    Returns: list of {"ticker": str, "labeled": str, "impact": str}
    """
    portfolio_ctx = screening_data.get("portfolio_context", {})
    all_tickers = set(
        portfolio_ctx.get("position_tickers", []) +
        portfolio_ctx.get("watchlist", []) +
        portfolio_ctx.get("pending_tickers", [])
    )

    issues = []
    for ticker in sorted(all_tickers):
        if SECTOR_MAP.get(ticker, "Unknown") == "Unknown":
            issues.append({
                "ticker": ticker,
                "labeled": "Unknown",
                "impact": "Sector diversity score may be incorrect for candidates in this ticker's true sector",
            })
    return issues


# ---------------------------------------------------------------------------
# Check 4: Duplicate Buy Price Detection
# ---------------------------------------------------------------------------

def detect_duplicate_buy_prices(shortlist_json, screening_data):
    """Find bullets with identical buy_at within the same ticker.

    Returns: list of {"ticker": str, "buy_at": float, "levels": [support_prices]}
    """
    wick_analyses = screening_data.get("wick_analyses", {})
    duplicates = []

    for entry in shortlist_json["shortlist"]:
        ticker = entry["ticker"]
        if entry.get("wick_failed"):
            continue
        wick = wick_analyses.get(ticker)
        if not wick or "bullet_plan" not in wick:
            continue

        bp = wick["bullet_plan"]
        all_bullets = bp.get("active", []) + bp.get("reserve", [])

        # Group by buy_at
        buy_at_map = {}
        for b in all_bullets:
            key = round(b["buy_at"], 2)
            buy_at_map.setdefault(key, []).append(b["support_price"])

        for buy_at, supports in buy_at_map.items():
            if len(supports) > 1:
                duplicates.append({
                    "ticker": ticker,
                    "buy_at": buy_at,
                    "levels": supports,
                })

    return duplicates


# ---------------------------------------------------------------------------
# Check 5: Recency Flag Count Validation
# ---------------------------------------------------------------------------

def validate_recency_counts(shortlist_json, screening_data):
    """Recount deteriorating levels from raw events, compare vs flag count.

    Uses the FLAG threshold from surgical_filter.py verify_candidate():
        overall_hold - recent_hold_pct > RECENCY_DROP_THRESHOLD

    Only iterates levels in the bullet plan (active + reserve), NOT all levels.

    Returns: list of {"ticker": str, "flag_count": int, "actual_count": int, "details": [...]}
    """
    wick_analyses = screening_data.get("wick_analyses", {})
    mismatches = []

    for entry in shortlist_json["shortlist"]:
        ticker = entry["ticker"]
        if entry.get("wick_failed"):
            continue
        wick = wick_analyses.get(ticker)
        if not wick:
            continue

        # Parse flag count from shortlist flags
        flag_count = 0
        for f in entry.get("flags", []):
            m = re.match(r'Recency deterioration:\s*(\d+)\s+level', f, re.IGNORECASE)
            if m:
                flag_count = int(m.group(1))
                break

        # Get bullet plan support prices as scope
        bp = wick.get("bullet_plan", {})
        bp_support_prices = set()
        for b in bp.get("active", []) + bp.get("reserve", []):
            bp_support_prices.add(round(b["support_price"], 2))

        # Compute cutoff from wick data's last_date using shared constant
        last_date_str = wick.get("last_date", "")
        try:
            last_date = datetime.datetime.strptime(last_date_str, "%Y-%m-%d")
        except (ValueError, TypeError):
            last_date = datetime.datetime.now()
        cutoff = last_date - datetime.timedelta(days=RECENCY_WINDOW_DAYS)

        # Count deteriorating levels among bullet plan levels
        actual_count = 0
        details = []
        for lvl in wick.get("levels", []):
            sp = round(lvl["support_price"], 2)
            if sp not in bp_support_prices:
                continue
            events = lvl.get("events", [])
            if not events:
                continue

            overall_hold = lvl["hold_rate"]
            recent_events = []
            for e in events:
                try:
                    edate = datetime.datetime.strptime(e["date"], "%Y-%m-%d")
                    if edate >= cutoff:
                        recent_events.append(e)
                except (ValueError, TypeError):
                    continue

            if not recent_events:
                continue

            recent_held = sum(1 for e in recent_events if e["held"])
            recent_hold_pct = round(recent_held / len(recent_events) * 100, 1)

            if overall_hold - recent_hold_pct > RECENCY_DROP_THRESHOLD:
                actual_count += 1
                details.append({
                    "support_price": lvl["support_price"],
                    "overall_hold": overall_hold,
                    "recent_hold_pct": recent_hold_pct,
                })

        if actual_count != flag_count:
            mismatches.append({
                "ticker": ticker,
                "flag_count": flag_count,
                "actual_count": actual_count,
                "details": details,
            })

    return mismatches


# ---------------------------------------------------------------------------
# Check 6: Score Arithmetic Validation
# ---------------------------------------------------------------------------

def validate_score_arithmetic(shortlist_json):
    """Verify total_score matches sum of component scores.

    Returns: list of {"ticker": str, "expected": int/float, "actual": int/float}
    """
    mismatches = []

    for entry in shortlist_json["shortlist"]:
        ticker = entry["ticker"]
        scores = entry.get("scores", {})
        total = entry["total_score"]

        if entry.get("wick_failed"):
            # Wick-failed: total = min(40, sector_diversity)
            expected = min(40, scores.get("sector_diversity", 0))
        else:
            expected = sum(scores.values())

        if expected != total:
            mismatches.append({
                "ticker": ticker,
                "expected": expected,
                "actual": total,
            })

    return mismatches


# ---------------------------------------------------------------------------
# Check 7: Recommendation-Score Consistency
# ---------------------------------------------------------------------------

def check_recommendation_consistency(eval_json, shortlist_json):
    """Check if recommendations align with scores and flags.

    Heuristic rules — flags for LLM review, not hard failures.

    Returns: list of {"ticker": str, "score": int, "recommendation": str, "concern": str}
    """
    shortlist_lookup = {
        e["ticker"]: e for e in shortlist_json["shortlist"]
    }
    concerns = []

    for cand in eval_json["candidates"]:
        ticker = cand["ticker"]
        if ticker not in shortlist_lookup:
            continue  # Phantom ticker — already caught by check 1 (extra_in_eval)
        score = cand["score"]
        rec = cand.get("recommendation", "")
        sl = shortlist_lookup[ticker]
        flags = sl.get("flags", [])

        # Quality flags only (exclude mechanical verification issues)
        quality_flags = [f for f in flags if not _is_mechanical_flag(f)]

        if score >= 85 and len(quality_flags) == 0 and rec in ("Watch", "Monitor"):
            concerns.append({
                "ticker": ticker,
                "score": score,
                "recommendation": rec,
                "concern": f"Score {score} with 0 quality flags suggests Onboard, got {rec}",
            })

        has_critical = any(
            "sector concentration" in f.lower() or "budget exceed" in f.lower()
            for f in quality_flags
        )
        if has_critical and rec == "Onboard":
            concerns.append({
                "ticker": ticker,
                "score": score,
                "recommendation": rec,
                "concern": "Critical flag (sector concentration or budget) present but recommended Onboard",
            })

        if score < 70 and rec == "Onboard":
            concerns.append({
                "ticker": ticker,
                "score": score,
                "recommendation": rec,
                "concern": f"Score {score} (<70) seems low for Onboard recommendation",
            })

    return concerns


# ---------------------------------------------------------------------------
# Output Rendering
# ---------------------------------------------------------------------------

def build_report(checks, shortlist_json):
    """Render candidate-pre-verify.md from check results."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = []

    lines.append("# Mechanical Pre-Verification Report")
    lines.append(f"*Generated: {now} | Tool: surgical_pre_verify.py*")
    lines.append("")

    # --- Summary Table ---
    score_result = checks["score_match"]
    flag_result = checks["flag_coverage"]
    sector_result = checks["sector_audit"]
    dup_result = checks["duplicate_buy"]
    recency_result = checks["recency_counts"]
    arith_result = checks["score_arithmetic"]
    rec_result = checks["recommendation"]

    has_hard_fail = score_result["mismatches"] or score_result["missing_from_eval"]
    score_status = "FAIL" if has_hard_fail else ("WARN" if score_result["extra_in_eval"] else "PASS")
    score_detail = f"{len(score_result['mismatches'])} mismatches"
    if score_result["missing_from_eval"]:
        score_detail += f", {len(score_result['missing_from_eval'])} missing from eval"
    if score_result["extra_in_eval"]:
        score_detail += f", {len(score_result['extra_in_eval'])} extra in eval (not in shortlist)"

    total_missed = sum(len(v["missed"]) for v in flag_result.values())
    flag_status = "FAIL" if total_missed > 0 else "PASS"
    flag_detail = f"{total_missed} flags unaddressed" if total_missed else "All flags addressed"

    sector_status = "FAIL" if sector_result else "PASS"
    sector_detail = f"{len(sector_result)} misclassifications" if sector_result else "All sectors mapped"

    dup_status = "WARN" if dup_result else "PASS"
    dup_detail = f"{len(dup_result)} anomalies" if dup_result else "No duplicates"

    recency_status = "FAIL" if recency_result else "PASS"
    recency_detail = f"{len(recency_result)} mismatches" if recency_result else "All counts verified"

    arith_status = "FAIL" if arith_result else "PASS"
    arith_detail = f"{len(arith_result)} mismatches" if arith_result else "All sums verified"

    rec_status = "WARN" if rec_result else "PASS"
    rec_detail = f"{len(rec_result)} concerns" if rec_result else "All consistent"

    lines.append("## Summary")
    lines.append("| Check | Result | Details |")
    lines.append("| :--- | :--- | :--- |")
    lines.append(f"| Score match | {score_status} | {score_detail} |")
    lines.append(f"| Flag coverage | {flag_status} | {flag_detail} |")
    lines.append(f"| Sector audit | {sector_status} | {sector_detail} |")
    lines.append(f"| Duplicate buy prices | {dup_status} | {dup_detail} |")
    lines.append(f"| Recency counts | {recency_status} | {recency_detail} |")
    lines.append(f"| Score arithmetic | {arith_status} | {arith_detail} |")
    lines.append(f"| Recommendation consistency | {rec_status} | {rec_detail} |")
    lines.append("")

    # --- Score Adjustments Recommended ---
    if sector_result:
        lines.append("## Score Adjustments Recommended")
        lines.append("| Ticker | Issue | Impact |")
        lines.append("| :--- | :--- | :--- |")
        for issue in sector_result:
            lines.append(f"| {issue['ticker']} | Labeled \"{issue['labeled']}\" | {issue['impact']} |")
        lines.append("")

    # --- Per-Ticker Findings ---
    lines.append("## Per-Ticker Findings")
    for entry in shortlist_json["shortlist"]:
        ticker = entry["ticker"]
        lines.append(f"### {ticker}")

        # Score match
        mismatch = next((m for m in score_result["mismatches"] if m["ticker"] == ticker), None)
        if mismatch:
            lines.append(f"- Score match: **FAIL** — shortlist {mismatch['shortlist_score']} "
                         f"vs eval {mismatch['eval_score']}")
        elif ticker in score_result["missing_from_eval"]:
            lines.append(f"- Score match: **FAIL** — missing from evaluation JSON")
        else:
            lines.append(f"- Score match: PASS")

        # Flag coverage
        fc = flag_result.get(ticker, {})
        skip_parts = []
        if fc.get("skipped_mechanical"):
            skip_parts.append(f"{fc['skipped_mechanical']} mechanical")
        if fc.get("skipped_unparseable"):
            skip_parts.append(f"{fc['skipped_unparseable']} unparseable")
        skipped_str = f" ({', '.join(skip_parts)} skipped)" if skip_parts else ""
        if fc.get("missed"):
            lines.append(f"- Flag coverage: {len(fc.get('addressed', []))} addressed / "
                         f"**{len(fc['missed'])} missed**{skipped_str}")
            for missed in fc["missed"]:
                lines.append(f"  - Missed: {missed}")
        elif fc.get("addressed"):
            lines.append(f"- Flag coverage: {len(fc['addressed'])} addressed / 0 missed{skipped_str}")
        else:
            lines.append(f"- Flag coverage: No quality flags to check{skipped_str}")

        # Recency
        recency_issue = next((r for r in recency_result if r["ticker"] == ticker), None)
        if recency_issue:
            lines.append(f"- Recency count: **MISMATCH** — flag says {recency_issue['flag_count']}, "
                         f"actual {recency_issue['actual_count']}")

        # Duplicates
        ticker_dups = [d for d in dup_result if d["ticker"] == ticker]
        if ticker_dups:
            for d in ticker_dups:
                lines.append(f"- Duplicate buy price: ${d['buy_at']:.2f} at "
                             f"supports {', '.join(f'${s:.2f}' for s in d['levels'])}")

        # Score arithmetic
        arith_issue = next((a for a in arith_result if a["ticker"] == ticker), None)
        if arith_issue:
            lines.append(f"- Score arithmetic: **FAIL** — expected {arith_issue['expected']}, "
                         f"got {arith_issue['actual']}")

        # Recommendation consistency
        rec_issue = next((r for r in rec_result if r["ticker"] == ticker), None)
        if rec_issue:
            lines.append(f"- Recommendation: **{rec_issue['concern']}**")

        # Knowledge store context
        try:
            from knowledge_store import query_ticker_knowledge
            ks = query_ticker_knowledge(ticker, f"{ticker} support levels entry buy")
            if ks:
                lines.append(f"- {ks}")
        except Exception:
            pass

        lines.append("")

    # --- Data Quality Issues ---
    has_issues = sector_result or recency_result or dup_result or score_result["extra_in_eval"]
    if has_issues:
        lines.append("## Data Quality Issues")
        if sector_result:
            lines.append("### Sector Misclassifications")
            for issue in sector_result:
                lines.append(f"- {issue['ticker']}: labeled \"{issue['labeled']}\" — "
                             f"{issue['impact']}")
            lines.append("")
        if recency_result:
            lines.append("### Recency Count Mismatches")
            for r in recency_result:
                lines.append(f"- {r['ticker']}: flag says {r['flag_count']} deteriorating levels, "
                             f"actual is {r['actual_count']}")
                for d in r["details"]:
                    lines.append(f"  - ${d['support_price']}: overall {d['overall_hold']:.0f}% "
                                 f"vs recent {d['recent_hold_pct']:.0f}%")
            lines.append("")
        if dup_result:
            lines.append("### Duplicate Buy Prices")
            for d in dup_result:
                lines.append(f"- {d['ticker']}: ${d['buy_at']:.2f} shared by supports "
                             f"{', '.join(f'${s:.2f}' for s in d['levels'])}")
            lines.append("")
        if score_result["extra_in_eval"]:
            lines.append("### Extra Tickers in Evaluation")
            for ticker in score_result["extra_in_eval"]:
                lines.append(f"- **{ticker}**: evaluated but not in shortlist — possible LLM hallucination or typo")
            lines.append("")

    # --- Qualitative Focus Areas ---
    lines.append("## For Verifier: Qualitative Focus Areas")
    focus_num = 1
    for entry in shortlist_json["shortlist"]:
        ticker = entry["ticker"]
        items = []

        fc = flag_result.get(ticker, {})
        if fc.get("missed"):
            items.append(f"evaluate unaddressed flags: {', '.join(fc['missed'])}")

        rec_issue = next((r for r in rec_result if r["ticker"] == ticker), None)
        if rec_issue:
            items.append(f"review recommendation: {rec_issue['concern']}")

        ticker_dups = [d for d in dup_result if d["ticker"] == ticker]
        if ticker_dups:
            items.append("assess duplicate buy price convergence — coincidence or data issue?")

        if items:
            lines.append(f"{focus_num}. **{ticker}**: {'; '.join(items)}")
            focus_num += 1

    if focus_num == 1:
        lines.append("No specific mechanical issues found. Focus on thesis quality, risk callout depth, and recommendation logic.")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Surgical Pre-Verifier")
    print("=" * 40)

    shortlist_json, eval_json, eval_text, screening_data = validate_inputs()
    print(f"Loaded: {len(shortlist_json['shortlist'])} shortlisted, "
          f"{len(eval_json['candidates'])} evaluated")

    checks = {
        "score_match": check_evaluation_scores(eval_json, shortlist_json),
        "flag_coverage": check_flag_coverage(shortlist_json, eval_text),
        "sector_audit": audit_sector_classifications(screening_data),
        "duplicate_buy": detect_duplicate_buy_prices(shortlist_json, screening_data),
        "recency_counts": validate_recency_counts(shortlist_json, screening_data),
        "score_arithmetic": validate_score_arithmetic(shortlist_json),
        "recommendation": check_recommendation_consistency(eval_json, shortlist_json),
    }

    report = build_report(checks, shortlist_json)
    OUTPUT_PATH.write_text(report + "\n")
    print(f"\nWrote {OUTPUT_PATH.name}")

    # Print summary
    for name, key in [
        ("Score match", "score_match"),
        ("Flag coverage", "flag_coverage"),
        ("Sector audit", "sector_audit"),
        ("Duplicate buy", "duplicate_buy"),
        ("Recency counts", "recency_counts"),
        ("Score arithmetic", "score_arithmetic"),
        ("Recommendation", "recommendation"),
    ]:
        result = checks[key]
        if key == "score_match":
            n = len(result["mismatches"]) + len(result["missing_from_eval"]) + len(result["extra_in_eval"])
        elif key == "flag_coverage":
            n = sum(len(v["missed"]) for v in result.values())
        elif isinstance(result, list):
            n = len(result)
        else:
            n = 0
        if n == 0:
            status = "PASS"
        elif key in ("recommendation", "duplicate_buy"):
            status = "WARN"
        elif key == "score_match" and not result["mismatches"] and not result["missing_from_eval"]:
            status = "WARN"  # Only extra_in_eval — data quality, not score integrity
        else:
            status = "FAIL"
        print(f"  {name}: {status} ({n} issues)")


if __name__ == "__main__":
    main()
