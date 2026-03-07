"""Vector knowledge store for trading memory.

Backed by ChromaDB (local SQLite) with sentence-transformers embeddings.
Supports manual add, semantic query, bulk ingest from memory.md files,
auto-storage from cmd_fill()/cmd_sell(), full resync, and stats.

Usage:
    python3 tools/knowledge_store.py add --ticker CIFR --category trade \
        --date 2026-03-04 --outcome "+7.8%" "Sold 6 @ $16.08, full exit."

    python3 tools/knowledge_store.py query "stock gapping down on dilution news"
    python3 tools/knowledge_store.py query "weak signal level" --ticker CIFR --n 3 --verbose

    python3 tools/knowledge_store.py ingest
    python3 tools/knowledge_store.py stats
    python3 tools/knowledge_store.py resync
"""
import sys
import re
import json
import math
import hashlib
import argparse
import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_CHROMA_DIR = _ROOT / ".chroma"
_TICKERS_DIR = _ROOT / "tickers"

TODAY = datetime.date.today().isoformat()

# ---------------------------------------------------------------------------
# Section header classification
# ---------------------------------------------------------------------------

SECTION_MAP = {
    "## Trade Log":                "trade",
    "## Trade History":            "trade",
    "## Observations":             "observation",
    "## Observations (continued)": "observation",
    "## Lessons":                  "lesson",
    "## Plan":                     "plan",
    "## Action Required":          "plan",
}


def _classify_section(header_line: str) -> str:
    stripped = header_line.strip()
    if stripped in SECTION_MAP:
        return SECTION_MAP[stripped]
    for key, category in SECTION_MAP.items():
        if stripped.startswith(key):
            return category
    return "observation"


# ---------------------------------------------------------------------------
# Bullet-list parsing helpers
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(
    r'^-\s+'                # bullet prefix "- "
    r'\*{0,2}'              # optional bold **
    r'(\d{4}-\d{2}-\d{2})'  # capture YYYY-MM-DD
    r'[^:]*:'               # optional suffix text then colon
    r'\*{0,2}\s*'           # optional closing bold
)


def _extract_date(line: str):
    """Extract YYYY-MM-DD from a bullet line, or None."""
    m = _DATE_RE.match(line)
    return m.group(1) if m else None


def _strip_bullet_prefix(line: str) -> str:
    """Strip bullet marker and optional date prefix, return content text."""
    m = _DATE_RE.match(line)
    if m:
        return line[m.end():].strip()
    text = re.sub(r'^-\s+\*{0,2}\s*', '', line)
    return text.rstrip('*').strip()


# ---------------------------------------------------------------------------
# Memory.md parser (dual: bullet-list + table)
# ---------------------------------------------------------------------------

def _parse_memory(ticker: str, filepath: Path) -> list:
    entries = []
    current_section = None
    current_entry = None
    in_table_mode = False
    table_columns = []
    date_col = 0

    lines = filepath.read_text().splitlines() + [None]  # None = EOF sentinel

    for line in lines:
        # Flush on EOF or new section header
        if line is None or line.startswith("## "):
            if current_entry and current_entry["text"].strip():
                entries.append(current_entry)
                current_entry = None
            if line is None:
                break
            current_section = _classify_section(line)
            in_table_mode = False
            table_columns = []
            continue

        if current_section is None:
            continue

        # --- Table detection and parsing ---
        if not in_table_mode and line.strip().startswith("|"):
            # Header row
            table_columns = [c.strip() for c in line.strip().strip("|").split("|")]
            date_col = next(
                (i for i, c in enumerate(table_columns)
                 if c.lower() in ("date", "filled")),
                0,
            )
            in_table_mode = True
            continue

        if in_table_mode and line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            # Skip alignment row
            if all(re.fullmatch(r'[\s:*\-]*', c) for c in cells):
                continue
            entry_date = cells[date_col] if date_col < len(cells) else "unknown"
            content_parts = [c for i, c in enumerate(cells) if i != date_col and c]
            entries.append({
                "ticker": ticker,
                "category": current_section,
                "date": entry_date,
                "text": " ".join(content_parts),
                "source": "memory.md",
            })
            continue

        # Exit table mode on non-table line
        if in_table_mode and not line.strip().startswith("|"):
            in_table_mode = False

        # --- Bullet-list parsing ---
        if line.startswith("- "):
            if current_entry and current_entry["text"].strip():
                entries.append(current_entry)
            current_entry = {
                "ticker": ticker,
                "category": current_section,
                "date": _extract_date(line) or "unknown",
                "text": _strip_bullet_prefix(line),
                "source": "memory.md",
            }
        elif current_entry is not None:
            if not line.strip():
                current_entry["text"] += "\n"
            else:
                current_entry["text"] += " " + line.strip()

    return entries


# ---------------------------------------------------------------------------
# ChromaDB access
# ---------------------------------------------------------------------------

def _get_collection():
    """Get or create ChromaDB collection. Returns (client, collection)."""
    try:
        import chromadb
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
    except ImportError:
        print("*Error: Could not initialize knowledge store. "
              "Run `pip install chromadb sentence-transformers`*")
        sys.exit(1)
    ef = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
    client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
    collection = client.get_or_create_collection(
        name="trading_knowledge",
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )
    return client, collection


def _make_id(ticker, category, date, text):
    raw = f"{ticker}_{category}_{date}_{text[:80]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:8]


# ---------------------------------------------------------------------------
# Public helpers (called from portfolio_manager.py)
# ---------------------------------------------------------------------------

_CACHED_COLLECTION = None
_CACHE_INITIALIZED = False
_TRANSIENT_ERROR_COUNT = 0
_UNCOUNTABLE_CATEGORIES = {"news", "macro"}

DECAY_HALF_LIFE_DAYS = 60


def _compute_decay(date_str: str) -> float:
    """Exponential decay: 1.0 today, 0.5 at 60 days, 0.25 at 120 days.
    Unknown dates get 0.5."""
    if not date_str or date_str == "unknown":
        return 0.5
    try:
        d = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        days_ago = (datetime.date.today() - d).days
        if days_ago < 0:
            days_ago = 0
        return math.pow(0.5, days_ago / DECAY_HALF_LIFE_DAYS)
    except (ValueError, TypeError):
        return 0.5


def _parse_outcome_pct(outcome_str: str):
    """Parse '+7.8%' or '-3.2%' into float. None if unparseable."""
    if not outcome_str:
        return None
    m = re.match(r'([+-]?\d+\.?\d*)%', outcome_str.strip())
    if m:
        return float(m.group(1))
    return None


def _get_cached_collection():
    """Return cached collection, initializing on first call. Returns None on failure.

    Caches on success and on permanent failure (missing deps). Transient errors
    (RuntimeError, etc.) are retried up to 3 times; then permanently disabled.
    """
    global _CACHED_COLLECTION, _CACHE_INITIALIZED, _TRANSIENT_ERROR_COUNT
    if _CACHE_INITIALIZED:
        return _CACHED_COLLECTION
    try:
        _, collection = _get_collection()
        _CACHED_COLLECTION = collection
        _CACHE_INITIALIZED = True
        _TRANSIENT_ERROR_COUNT = 0  # reset on success
        return collection
    except (SystemExit, ImportError):
        _CACHE_INITIALIZED = True  # permanent failure — don't retry
        return None
    except Exception:
        _TRANSIENT_ERROR_COUNT += 1
        if _TRANSIENT_ERROR_COUNT >= 3:
            print("*Warning: knowledge store initialization failed 3 times. "
                  "Disabling to prevent hang. Check .chroma/ permissions.*")
            _CACHE_INITIALIZED = True
        return None


def query_ticker_knowledge(ticker, context_hint, n=3, include_superseded=False):
    """Query knowledge store for a ticker, return compact summary string.

    Returns string like:
      "**Knowledge:** 3 trades, 2 lessons. Top: Sold 6 @ $16.08, full exit +7.8% (0.82)"
    Returns "" on any error or no relevant results.

    Enhanced with decay weighting, outcome boost, and superseded filtering.
    """
    try:
        collection = _get_cached_collection()
        if collection is None or collection.count() == 0:
            return ""
        # Fetch extra candidates to compensate for filtering
        fetch_n = min(n * 3, collection.count())
        results = collection.query(
            query_texts=[context_hint],
            n_results=fetch_n,
            where={"ticker": ticker.upper()},
        )
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        dists = results["distances"][0]

        adjusted_hits = []
        for d, m, dist in zip(docs, metas, dists):
            if not include_superseded and m.get("superseded") == "true":
                continue
            base_rel = 1.0 - dist / 2.0
            if base_rel <= 0.4:
                continue
            decay = _compute_decay(m.get("date", "unknown"))
            outcome_boost = 1.0
            outcome_str = m.get("outcome", "")
            if outcome_str:
                pct = _parse_outcome_pct(outcome_str)
                if pct is not None:
                    outcome_boost = 1.0 + min(abs(pct) / 20.0, 0.5)  # max 1.5x
            effective = base_rel * decay * outcome_boost
            if effective > 0.4:
                adjusted_hits.append((d, m, effective))
        adjusted_hits.sort(key=lambda x: x[2], reverse=True)
        hits = adjusted_hits[:n]

        if not hits:
            return ""
        # Count by category
        cats = {}
        for _, m, _ in hits:
            c = m.get("category", "other")
            cats[c] = cats.get(c, 0) + 1
        cat_str = ", ".join(
            f"{v} {k}" if k in _UNCOUNTABLE_CATEGORIES
            else f"{v} {k}{'s' if v > 1 else ''}"
            for k, v in cats.items()
        )
        # Top hit snippet
        top_doc = hits[0][0].replace("\n", " ").strip()
        top_rel = f"{hits[0][2]:.2f}"
        short = top_doc[:80] + "..." if len(top_doc) > 80 else top_doc
        return f"**Knowledge:** {cat_str}. Top: {short} ({top_rel})"
    except Exception:
        return ""


def store_fill(ticker, price, shares, total_shares, new_avg, zone):
    """Store a fill event. Called from portfolio_manager.cmd_fill()."""
    collection = _get_cached_collection()
    if collection is None:
        print("*Warning: knowledge store unavailable — fill not recorded.*")
        return
    text = (f"{ticker}: BUY {shares} shares @ ${price:.2f} ({zone}). "
            f"Now {total_shares} shares @ ${new_avg:.2f} avg.")
    d = datetime.date.today().isoformat()
    doc_id = _make_id(ticker, "trade", d, text)
    collection.upsert(ids=[doc_id], documents=[text],
                      metadatas=[{"ticker": ticker, "category": "trade",
                                  "date": d, "source": "cmd_fill"}])


def store_sell(ticker, price, shares, old_avg, pct_change):
    """Store a sell event (full close). Called from portfolio_manager.cmd_sell()."""
    collection = _get_cached_collection()
    if collection is None:
        print("*Warning: knowledge store unavailable — sell not recorded.*")
        return
    sign = "+" if pct_change >= 0 else ""
    text = (f"{ticker}: SELL {shares} shares @ ${price:.2f} (full exit). "
            f"Profit: {sign}{pct_change}% from ${old_avg:.2f} avg. Position closed.")
    d = datetime.date.today().isoformat()
    doc_id = _make_id(ticker, "trade", d, text)
    collection.upsert(ids=[doc_id], documents=[text],
                      metadatas=[{"ticker": ticker, "category": "trade",
                                  "date": d, "outcome": f"{sign}{pct_change}%",
                                  "source": "cmd_sell"}])


def store_partial_sell(ticker, price, shares, remaining):
    """Store a partial sell (trim). Called from portfolio_manager.cmd_sell() else branch."""
    collection = _get_cached_collection()
    if collection is None:
        print("*Warning: knowledge store unavailable — sell not recorded.*")
        return
    text = (f"{ticker}: SELL {shares} shares @ ${price:.2f} "
            f"(partial trim). {remaining} shares remaining.")
    d = datetime.date.today().isoformat()
    doc_id = _make_id(ticker, "trade", d, text)
    collection.upsert(ids=[doc_id], documents=[text],
                      metadatas=[{"ticker": ticker, "category": "trade",
                                  "date": d, "source": "cmd_sell"}])


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def cmd_add(args):
    """Add a single knowledge entry."""
    _, collection = _get_collection()
    d = args.date or TODAY
    text = args.text
    doc_id = _make_id(args.ticker.upper(), args.category, d, text)
    meta = {"ticker": args.ticker.upper(), "category": args.category,
            "date": d, "source": "manual"}
    if args.outcome:
        meta["outcome"] = args.outcome
    collection.upsert(ids=[doc_id], documents=[text], metadatas=[meta])
    print(f"Added 1 entry for {args.ticker.upper()} ({args.category}, {d}).")


def cmd_query(args):
    """Semantic search with optional ticker filter."""
    _, collection = _get_collection()
    if collection.count() == 0:
        print("*Knowledge store is empty. Run `ingest` first.*")
        return
    kwargs = {"query_texts": [args.text], "n_results": min(args.n, collection.count())}
    if args.ticker:
        kwargs["where"] = {"ticker": args.ticker.upper()}
    results = collection.query(**kwargs)
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    dists = results["distances"][0]

    if not docs:
        print(f"*No results found for \"{args.text}\".*")
        return

    print(f"### Knowledge Search: \"{args.text}\"")
    print("| # | Ticker | Date | Category | Relevance | Content |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- |")
    for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists), 1):
        relevance = round(1.0 - (dist / 2.0), 2)
        content = doc.replace("\n", " ").strip()
        short = content[:100] + "..." if len(content) > 100 else content
        print(f"| {i} | {meta['ticker']} | {meta['date']} | {meta['category']} "
              f"| {relevance} | {short} |")

    if args.verbose:
        print()
        for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists), 1):
            relevance = round(1.0 - (dist / 2.0), 2)
            print(f"**{i}. [{meta['ticker']}] {meta['date']} "
                  f"({meta['category']}, {relevance})**")
            print(doc.strip())
            print()


def cmd_ingest(args):
    """Bulk ingest from all tickers/*/memory.md files."""
    _, collection = _get_collection()
    memory_files = sorted(_TICKERS_DIR.glob("*/memory.md"))
    if not memory_files:
        print("*No memory.md files found in tickers/.*")
        return

    total = 0
    breakdown = []
    for filepath in memory_files:
        ticker = filepath.parent.name.upper()
        entries = _parse_memory(ticker, filepath)
        if not entries:
            continue
        ids = []
        documents = []
        metadatas = []
        for entry in entries:
            doc_id = _make_id(entry["ticker"], entry["category"],
                              entry["date"], entry["text"])
            meta = {"ticker": entry["ticker"], "category": entry["category"],
                    "date": entry["date"], "source": entry["source"]}
            ids.append(doc_id)
            documents.append(entry["text"])
            metadatas.append(meta)
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        total += len(entries)
        breakdown.append((ticker, len(entries)))

    print(f"Ingested {total} entries from {len(breakdown)} tickers.")
    print("| Ticker | Entries |")
    print("| :--- | :--- |")
    for ticker, count in breakdown:
        print(f"| {ticker} | {count} |")


def cmd_stats(args):
    """Print collection stats by category and ticker."""
    _, collection = _get_collection()
    count = collection.count()
    if count == 0:
        print("*Knowledge store is empty.*")
        return

    all_data = collection.get(include=["metadatas"])
    metas = all_data["metadatas"]

    by_ticker = {}
    by_category = {}
    for meta in metas:
        t = meta.get("ticker", "unknown")
        c = meta.get("category", "unknown")
        by_ticker[t] = by_ticker.get(t, 0) + 1
        by_category[c] = by_category.get(c, 0) + 1

    print(f"### Knowledge Store: {count} total entries")
    print()
    print("**By Ticker:**")
    print("| Ticker | Count |")
    print("| :--- | :--- |")
    for t in sorted(by_ticker):
        print(f"| {t} | {by_ticker[t]} |")

    print()
    print("**By Category:**")
    print("| Category | Count |")
    print("| :--- | :--- |")
    for c in sorted(by_category):
        print(f"| {c} | {by_category[c]} |")


def cmd_resync(args):
    """Delete collection and re-ingest from scratch."""
    global _CACHED_COLLECTION, _CACHE_INITIALIZED, _TRANSIENT_ERROR_COUNT
    _CACHED_COLLECTION = None
    _CACHE_INITIALIZED = False
    _TRANSIENT_ERROR_COUNT = 0
    client, _ = _get_collection()
    client.delete_collection("trading_knowledge")
    print("Collection deleted. Re-ingesting...")
    cmd_ingest(args)


def cmd_apply(args):
    """Apply consolidation updates from knowledge-consolidation-updates.json."""
    updates_path = _ROOT / "knowledge-consolidation-updates.json"
    if not updates_path.exists():
        print("*Error: knowledge-consolidation-updates.json not found. "
              "Run the knowledge-consolidation-workflow first.*")
        return

    try:
        data = json.loads(updates_path.read_text())
    except json.JSONDecodeError as e:
        print(f"*Error: JSON parse error: {e}*")
        return

    if not isinstance(data, dict):
        print(f"*Error: updates.json top-level must be an object, got {type(data).__name__}*")
        return

    _, collection = _get_collection()
    applied = {"superseded": 0, "new_lessons": 0, "annotations": 0, "portfolio_lessons": 0}

    # 1. Mark superseded entries
    for entry in data.get("superseded", []):
        entry_id = entry.get("id")
        if not entry_id:
            continue
        try:
            result = collection.get(ids=[entry_id], include=["metadatas"])
            if not result["metadatas"]:
                print(f"*Warning: ID {entry_id} not found — skipping supersede.*")
                continue
            old_meta = result["metadatas"][0]
            old_meta["superseded"] = "true"
            collection.update(ids=[entry_id], metadatas=[old_meta])
            applied["superseded"] += 1
        except Exception as e:
            print(f"*Warning: Failed to supersede {entry_id}: {e}*")

    # 2. Add new lesson entries
    for entry in data.get("new_lessons", []):
        ticker = entry.get("ticker", "UNKNOWN").upper()
        text = entry.get("text", "")
        if not text:
            continue
        d = TODAY
        doc_id = _make_id(ticker, "lesson", d, text)
        meta = {
            "ticker": ticker,
            "category": entry.get("category", "lesson"),
            "date": d,
            "source": "consolidation",
        }
        consolidated_from = entry.get("consolidated_from", [])
        if consolidated_from:
            meta["consolidated_from"] = json.dumps(consolidated_from)
        collection.upsert(ids=[doc_id], documents=[text], metadatas=[meta])
        applied["new_lessons"] += 1

    # 3. Append annotation text to existing entries
    for ann in data.get("annotations", []):
        ann_id = ann.get("id")
        append_text = ann.get("append_text", "")
        if not ann_id or not append_text:
            continue
        try:
            result = collection.get(ids=[ann_id], include=["documents", "metadatas"])
            if not result["documents"]:
                print(f"*Warning: ID {ann_id} not found — skipping annotation.*")
                continue
            old_doc = result["documents"][0]
            old_meta = result["metadatas"][0]
            collection.update(ids=[ann_id], documents=[old_doc + append_text],
                              metadatas=[old_meta])
            applied["annotations"] += 1
        except Exception as e:
            print(f"*Warning: Failed to annotate {ann_id}: {e}*")

    # 4. Add portfolio lessons under ticker="PORTFOLIO"
    for entry in data.get("portfolio_lessons", []):
        text = entry.get("text", "")
        if not text:
            continue
        d = TODAY
        doc_id = _make_id("PORTFOLIO", "portfolio_lesson", d, text)
        meta = {
            "ticker": "PORTFOLIO",
            "category": "portfolio_lesson",
            "date": d,
            "source": "consolidation",
        }
        sample_size = entry.get("sample_size")
        if sample_size is not None:
            meta["sample_size"] = str(sample_size)
        collection.upsert(ids=[doc_id], documents=[text], metadatas=[meta])
        applied["portfolio_lessons"] += 1

    print(f"Applied consolidation updates:")
    print(f"| Action | Count |")
    print(f"| :--- | :--- |")
    print(f"| Superseded | {applied['superseded']} |")
    print(f"| New Lessons | {applied['new_lessons']} |")
    print(f"| Annotations | {applied['annotations']} |")
    print(f"| Portfolio Lessons | {applied['portfolio_lessons']} |")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Vector knowledge store for trading memory")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add")
    p_add.add_argument("text")
    p_add.add_argument("--ticker", required=True)
    p_add.add_argument("--category", required=True,
                       choices=["trade", "observation", "lesson",
                                "news", "macro", "plan"])
    p_add.add_argument("--date", default=None)
    p_add.add_argument("--outcome", default=None)

    p_query = sub.add_parser("query")
    p_query.add_argument("text")
    p_query.add_argument("--ticker", default=None)
    p_query.add_argument("--n", type=int, default=5)
    p_query.add_argument("--verbose", action="store_true")

    sub.add_parser("ingest")
    sub.add_parser("stats")
    sub.add_parser("resync")
    sub.add_parser("apply")

    args = parser.parse_args()
    {
        "add": cmd_add,
        "query": cmd_query,
        "ingest": cmd_ingest,
        "stats": cmd_stats,
        "resync": cmd_resync,
        "apply": cmd_apply,
    }[args.command](args)


if __name__ == "__main__":
    main()
