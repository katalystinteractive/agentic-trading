#!/usr/bin/env python3
"""Knowledge Consolidator — Phase 1 pre-script for knowledge-consolidation-workflow.

Bulk retrieves all ChromaDB entries, computes per-ticker stats, loads wick data
for level cross-reference, builds belief evidence tables with contradiction scores,
aggregates cross-ticker patterns, and writes knowledge-consolidation-raw.md.

Usage: python3 tools/knowledge_consolidator.py
"""

import json
import math
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TICKERS_DIR = PROJECT_ROOT / "tickers"
OUTPUT_PATH = PROJECT_ROOT / "knowledge-consolidation-raw.md"

TODAY = date.today()
RECENCY_DAYS = 30


# ---------------------------------------------------------------------------
# ChromaDB bulk retrieval
# ---------------------------------------------------------------------------

def load_all_entries() -> dict[str, list[dict]]:
    """Bulk retrieve all ChromaDB entries grouped by ticker."""
    from knowledge_store import _get_collection

    _, collection = _get_collection()
    count = collection.count()
    if count == 0:
        return {}

    result = collection.get(include=["documents", "metadatas"])
    grouped = defaultdict(list)
    for id_, doc, meta in zip(result["ids"], result["documents"], result["metadatas"]):
        ticker = meta.get("ticker", "UNKNOWN")
        if ticker == "TEST":
            continue
        grouped[ticker].append({"id": id_, "doc": doc, "meta": meta})
    return dict(grouped)


# ---------------------------------------------------------------------------
# Per-ticker stats
# ---------------------------------------------------------------------------

_PROFIT_RE = re.compile(r'Profit.*?([+-]?\d+\.?\d*)%')
_PROFIT_RE2 = re.compile(r'([+-]\d+\.?\d*)%\s*from\s*\$')


def compute_ticker_stats(entries: list[dict]) -> dict:
    """Compute trade stats from entries."""
    cats = defaultdict(int)
    for e in entries:
        cats[e["meta"].get("category", "other")] += 1

    win_count = 0
    loss_count = 0
    returns = []

    for e in entries:
        if e["meta"].get("category") != "trade":
            continue
        if "SELL" not in e["doc"].upper():
            continue
        m = _PROFIT_RE.search(e["doc"])
        if not m:
            m = _PROFIT_RE2.search(e["doc"])
        if not m:
            continue
        pct = float(m.group(1))
        returns.append(pct)
        if pct >= 0:
            win_count += 1
        else:
            loss_count += 1

    total_sells = win_count + loss_count
    win_rate = round(win_count / total_sells * 100) if total_sells > 0 else None
    avg_return = round(sum(returns) / len(returns), 2) if returns else None

    # Most mentioned levels
    level_counts = defaultdict(int)
    for e in entries:
        for m in re.finditer(r'\$(\d+\.?\d{1,2})', e["doc"]):
            level_counts[m.group(0)] += 1
    top_levels = sorted(level_counts.items(), key=lambda x: x[1], reverse=True)[:3]

    return {
        "trade_count": cats.get("trade", 0),
        "observation_count": cats.get("observation", 0),
        "lesson_count": cats.get("lesson", 0),
        "news_count": cats.get("news", 0),
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": win_rate,
        "avg_return_pct": avg_return,
        "most_mentioned_levels": top_levels,
        "has_sufficient_data": len(entries) >= 3,
        "category_breakdown": dict(cats),
    }


# ---------------------------------------------------------------------------
# Wick data loading
# ---------------------------------------------------------------------------

_DETAIL_HEADER_RE = re.compile(r'^### Detail: \$([0-9]+\.?[0-9]*)')
_SUPPORT_TABLE_RE = re.compile(r'^\| \$(\d+\.?\d*)\s*\|')


def load_wick_data(ticker: str) -> dict | None:
    """Read wick_analysis.md, extract support levels + detail tables."""
    path = TICKERS_DIR / ticker / "wick_analysis.md"
    if not path.exists():
        return None

    text = path.read_text()
    lines = text.splitlines()

    # Parse support level summary table
    levels = {}
    for line in lines:
        m = _SUPPORT_TABLE_RE.match(line.strip())
        if m:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            support = float(m.group(1))
            try:
                approaches = int(cells[2]) if len(cells) > 2 else 0
                held = int(cells[3]) if len(cells) > 3 else 0
                hold_rate_str = cells[4] if len(cells) > 4 else "0%"
                hold_rate = int(hold_rate_str.replace("%", "").strip())
            except (ValueError, IndexError):
                approaches, held, hold_rate = 0, 0, 0
            levels[support] = {
                "support": support,
                "hold_rate": hold_rate,
                "approaches": approaches,
                "held": held,
                "details": [],
            }

    if not levels:
        return None

    # Parse detail tables
    current_level = None
    in_detail_table = False
    for line in lines:
        dm = _DETAIL_HEADER_RE.match(line.strip())
        if dm:
            price = float(dm.group(1))
            # Find closest level
            closest = min(levels.keys(), key=lambda l: abs(l - price))
            if abs(closest - price) / max(price, 0.01) < 0.03:
                current_level = closest
                in_detail_table = False
            else:
                current_level = None
            continue

        if current_level is None:
            continue

        stripped = line.strip()
        if stripped.startswith("| :") or stripped.startswith("| ---"):
            in_detail_table = True
            continue
        if stripped.startswith("| Date"):
            in_detail_table = True
            continue

        if in_detail_table and stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if len(cells) < 4:
                continue
            if re.fullmatch(r'[\s:\-\*]*', cells[0]):
                continue

            date_str = cells[0]
            try:
                wick_low = float(cells[1].replace("$", ""))
            except ValueError:
                continue
            held_raw = cells[3].strip().strip("*").upper()
            result = "BROKE" if "BROKE" in held_raw else "Held"

            levels[current_level]["details"].append({
                "date": date_str,
                "low": wick_low,
                "result": result,
            })
        elif in_detail_table and not stripped.startswith("|"):
            in_detail_table = False
            current_level = None

    return {"levels": list(levels.values())}


# ---------------------------------------------------------------------------
# Placeholder lesson filter
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(
    r'^\(none|^\(first|^\(no trades|^New onboarding|^pending', re.IGNORECASE
)


def filter_placeholder_lessons(entries: list[dict]) -> list[dict]:
    """Filter out placeholder/stub lesson entries."""
    result = []
    for e in entries:
        text = e["doc"].strip()
        if len(text) < 25:
            continue
        if _PLACEHOLDER_RE.match(text):
            continue
        result.append(e)
    return result


# ---------------------------------------------------------------------------
# Contradiction scoring
# ---------------------------------------------------------------------------

def _parse_date(date_str: str) -> date | None:
    """Parse YYYY-MM-DD date string."""
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


def _is_recent(date_str: str) -> bool:
    """Check if date is within RECENCY_DAYS of today."""
    d = _parse_date(date_str)
    if d is None:
        return False
    return (TODAY - d).days <= RECENCY_DAYS


def _score_contradiction(evidence_for: list[dict], evidence_against: list[dict]) -> float:
    """0.0 = no contradiction, 1.0 = total contradiction.
    Recent evidence (< 30 days) gets 2x weight."""
    weighted_for = sum(e.get("weight", 1.0) for e in evidence_for)
    weighted_against = sum(e.get("weight", 1.0) for e in evidence_against)

    total = weighted_for + weighted_against
    if total == 0:
        return 0.0
    if weighted_against == 0:
        return 0.0

    return round(weighted_against / total, 2)


# ---------------------------------------------------------------------------
# Belief evidence tables
# ---------------------------------------------------------------------------

def build_belief_evidence_table(
    lesson: dict, entries: list[dict], wick_data: dict | None
) -> dict:
    """Build evidence FOR/AGAINST a lesson entry using wick detail tables."""
    text = lesson["doc"]
    entry_id = lesson["id"]

    base = {
        "belief": text[:120],
        "entry_id": entry_id,
        "evidence_for": [],
        "evidence_against": [],
        "context_events": [],
        "contradiction_score": 0.0,
        "needs_llm_review": False,
        "note": None,
    }

    # Extract price from lesson
    price_match = re.search(r'\$(\d+\.?\d*)', text)
    if not price_match:
        base["note"] = "no_price_in_lesson"
        return base
    lesson_price = float(price_match.group(1))

    if wick_data is None:
        base["note"] = "no_wick_data"
        return base

    # Find closest wick level within 3%
    best_level = None
    best_dist = float("inf")
    for level in wick_data["levels"]:
        dist = abs(level["support"] - lesson_price) / max(lesson_price, 0.01)
        if dist < best_dist:
            best_dist = dist
            best_level = level
    if best_level is None or best_dist > 0.03:
        base["note"] = "no_wick_match"
        return base

    if best_level["approaches"] < 3:
        base["note"] = "insufficient_approaches"
        return base

    # Build evidence from wick detail table
    evidence_for = []
    evidence_against = []
    for detail in best_level["details"]:
        weight = 2.0 if _is_recent(detail["date"]) else 1.0
        item = {
            "event": f"Wick ${detail['low']:.2f} on {detail['date']} → {detail['result']}",
            "date": detail["date"],
            "weight": weight,
        }
        if detail["result"] == "Held":
            evidence_for.append(item)
        else:
            evidence_against.append(item)

    # Context events from ChromaDB trade entries near this price
    context_events = []
    for e in entries:
        if e["meta"].get("category") != "trade":
            continue
        for pm in re.finditer(r'\$(\d+\.?\d{1,2})', e["doc"]):
            trade_price = float(pm.group(1))
            if abs(trade_price - lesson_price) / max(lesson_price, 0.01) < 0.05:
                context_events.append(e["doc"][:100])
                break

    score = _score_contradiction(evidence_for, evidence_against)

    return {
        "belief": text[:120],
        "entry_id": entry_id,
        "level_matched": best_level["support"],
        "evidence_for": evidence_for,
        "evidence_against": evidence_against,
        "context_events": context_events,
        "contradiction_score": score,
        "needs_llm_review": score > 0.3,
        "note": None,
    }


# ---------------------------------------------------------------------------
# Cross-ticker patterns
# ---------------------------------------------------------------------------

def aggregate_cross_ticker_patterns(
    all_stats: dict, all_wick_data: dict[str, dict]
) -> list[dict]:
    """Portfolio-level patterns from wick data and trade stats."""
    from market_context_gatherer import SECTOR_MAP

    patterns = []

    # Break rate by approach count
    buckets = {"1-3": {"broke": 0, "total": 0}, "4-6": {"broke": 0, "total": 0},
               "7+": {"broke": 0, "total": 0}}
    for ticker, wd in all_wick_data.items():
        if ticker == "TEST":
            continue
        for level in wd["levels"]:
            a = level["approaches"]
            if a <= 3:
                bucket = "1-3"
            elif a <= 6:
                bucket = "4-6"
            else:
                bucket = "7+"
            broke = sum(1 for d in level["details"] if d["result"] == "BROKE")
            buckets[bucket]["broke"] += broke
            buckets[bucket]["total"] += len(level["details"])

    for bucket_name, data in buckets.items():
        if data["total"] > 0:
            rate = round(data["broke"] / data["total"] * 100)
            confidence = "High" if data["total"] >= 20 else "Medium" if data["total"] >= 10 else "Low"
            patterns.append({
                "pattern": f"Levels with {bucket_name} approaches: {rate}% break rate",
                "evidence": f"{data['broke']}/{data['total']} approaches broke",
                "sample_size": data["total"],
                "confidence": confidence,
            })

    # Win rate by sector
    sector_wins = defaultdict(lambda: {"wins": 0, "losses": 0})
    for ticker, stats in all_stats.items():
        if ticker == "TEST":
            continue
        sector = SECTOR_MAP.get(ticker, "Unknown")
        if sector == "Unknown":
            continue
        sector_wins[sector]["wins"] += stats["win_count"]
        sector_wins[sector]["losses"] += stats["loss_count"]

    for sector, data in sector_wins.items():
        total = data["wins"] + data["losses"]
        if total >= 2:
            rate = round(data["wins"] / total * 100)
            confidence = "High" if total >= 10 else "Medium" if total >= 5 else "Low"
            patterns.append({
                "pattern": f"{sector} sector win rate: {rate}%",
                "evidence": f"{data['wins']}/{total} trades profitable",
                "sample_size": total,
                "confidence": confidence,
            })

    return patterns


# ---------------------------------------------------------------------------
# Main — write knowledge-consolidation-raw.md
# ---------------------------------------------------------------------------

def main():
    print("Loading all ChromaDB entries...", file=sys.stderr)
    all_entries = load_all_entries()
    total_entries = sum(len(v) for v in all_entries.values())

    if total_entries == 0:
        print("*Knowledge store is empty. Nothing to consolidate.*")
        sys.exit(1)

    print(f"Found {total_entries} entries across {len(all_entries)} tickers.", file=sys.stderr)

    all_stats = {}
    all_wick_data = {}
    all_beliefs = []
    contradictions = []
    skipped_tickers = []
    ticker_sections = []

    for ticker in sorted(all_entries.keys()):
        entries = all_entries[ticker]
        stats = compute_ticker_stats(entries)
        all_stats[ticker] = stats

        wick_data = load_wick_data(ticker)
        if wick_data:
            all_wick_data[ticker] = wick_data

        if not stats["has_sufficient_data"]:
            skipped_tickers.append((ticker, len(entries)))
            continue

        # Build ticker section
        cat_parts = []
        for cat, count in sorted(stats["category_breakdown"].items()):
            cat_parts.append(f"{count} {cat}")
        cat_str = ", ".join(cat_parts)

        section = []
        section.append(f"### {ticker} ({len(entries)} entries: {cat_str})")
        section.append("| Metric | Value |")
        section.append("| :--- | :--- |")
        if stats["win_rate"] is not None:
            section.append(f"| Win Rate | {stats['win_rate']}% "
                           f"({stats['win_count']}/{stats['win_count'] + stats['loss_count']} cycles) |")
        if stats["avg_return_pct"] is not None:
            section.append(f"| Avg Return | {stats['avg_return_pct']:+.2f}% |")
        if stats["most_mentioned_levels"]:
            levels_str = ", ".join(f"{l} ({c}x)" for l, c in stats["most_mentioned_levels"])
            section.append(f"| Top Levels | {levels_str} |")
        if wick_data:
            best = max(wick_data["levels"], key=lambda l: l["approaches"])
            section.append(f"| Most Reliable Level | ${best['support']:.2f} "
                           f"({best['hold_rate']}% hold, {best['approaches']} approaches) |")

        # Entry ID Reference table
        section.append("")
        section.append(f"#### Entry ID Reference — {ticker}")
        section.append("| ID | Category | Date | Content |")
        section.append("| :--- | :--- | :--- | :--- |")
        for e in entries:
            content_short = e["doc"].replace("\n", " ").strip()[:80]
            section.append(f"| {e['id']} | {e['meta'].get('category', '?')} "
                           f"| {e['meta'].get('date', '?')} | {content_short} |")

        # Lessons and belief evidence
        lesson_entries = [e for e in entries if e["meta"].get("category") == "lesson"]
        filtered_lessons = filter_placeholder_lessons(lesson_entries)

        if filtered_lessons:
            section.append("")
            section.append("**Existing Lessons:**")
            for i, le in enumerate(filtered_lessons, 1):
                section.append(f"{i}. \"{le['doc'][:100]}\" "
                               f"({le['meta'].get('date', '?')}, ID: {le['id']})")

            section.append("")
            section.append("**Belief Evidence Tables:**")

            for le in filtered_lessons:
                belief = build_belief_evidence_table(le, entries, wick_data)
                all_beliefs.append({"ticker": ticker, **belief})

                if belief["note"]:
                    section.append(f"\n*Skipped: {le['doc'][:60]}... — {belief['note']}*")
                    continue

                section.append(f"\n#### Belief: \"{belief['belief']}\" (Lesson ID: {belief['entry_id']})")
                section.append("| Field | Detail |")
                section.append("| :--- | :--- |")

                for_items = [e["event"] for e in belief["evidence_for"]]
                against_items = [e["event"] for e in belief["evidence_against"]]
                for_str = "; ".join(for_items) if for_items else "None"
                against_str = "; ".join(against_items) if against_items else "None"
                ctx_str = "; ".join(belief["context_events"][:3]) if belief["context_events"] else "None"

                section.append(f"| Evidence FOR | {for_str} |")
                section.append(f"| Evidence AGAINST | {against_str} |")
                section.append(f"| Context Events | {ctx_str} |")
                section.append(f"| Contradiction Score | {belief['contradiction_score']} |")

                if belief["needs_llm_review"]:
                    section.append("")
                    section.append("*LLM: Classify — TEMPORARY or STRUCTURAL. "
                                   "Cite ≥2 specific data points from the table above.*")
                    contradictions.append({
                        "ticker": ticker,
                        "belief": belief["belief"],
                        "entry_id": belief["entry_id"],
                        "score": belief["contradiction_score"],
                        "key_against": against_items[0] if against_items else "N/A",
                    })

        section.append("")
        section.append("---")
        ticker_sections.append("\n".join(section))

    # Cross-ticker patterns
    cross_patterns = aggregate_cross_ticker_patterns(all_stats, all_wick_data)

    # Assemble output
    out = []
    out.append(f"# Knowledge Consolidation — {TODAY.isoformat()}")
    out.append("")
    out.append(f"**Entries processed:** {total_entries} across {len(all_entries)} tickers")
    out.append("")

    out.append("## Per-Ticker Knowledge Cards")
    out.append("")
    for section in ticker_sections:
        out.append(section)

    # Contradictions summary
    if contradictions:
        out.append("")
        out.append("## Belief Contradictions Requiring Review")
        out.append("| # | Ticker | Belief | Lesson ID | Score | Key Evidence Against |")
        out.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for i, c in enumerate(contradictions, 1):
            out.append(f"| {i} | {c['ticker']} | {c['belief'][:50]} "
                       f"| {c['entry_id']} | {c['score']} | {c['key_against'][:60]} |")
    else:
        out.append("")
        out.append("## Belief Contradictions Requiring Review")
        out.append("")
        out.append("*No contradictions above 0.3 threshold detected.*")

    # Cross-ticker patterns
    out.append("")
    out.append("## Cross-Ticker Patterns")
    if cross_patterns:
        out.append("| Pattern | Evidence | Sample | Confidence |")
        out.append("| :--- | :--- | :--- | :--- |")
        for p in cross_patterns:
            out.append(f"| {p['pattern']} | {p['evidence']} "
                       f"| {p['sample_size']} | {p['confidence']} |")
    else:
        out.append("*Insufficient data for cross-ticker patterns.*")

    # Skipped tickers
    if skipped_tickers:
        out.append("")
        out.append("## Tickers Skipped (< 3 entries)")
        skipped_str = ", ".join(f"{t} ({c})" for t, c in skipped_tickers)
        out.append(skipped_str)

    content = "\n".join(out) + "\n"
    OUTPUT_PATH.write_text(content)
    print(f"Wrote {OUTPUT_PATH.name} ({len(content)} bytes, "
          f"{len(all_entries)} tickers, {len(contradictions)} contradictions)")


if __name__ == "__main__":
    main()
