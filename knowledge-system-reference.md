# Knowledge System Reference — Reusable Architecture for Agentic Workflows

This document describes a complete vector-backed knowledge system designed for agentic workflows. It covers the vector database, memory ingestion, semantic querying with decay/outcome scoring, and periodic consolidation that forces belief revision. The system is domain-agnostic in design — the trading domain is used as a concrete example.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Vector Database Layer (ChromaDB)](#2-vector-database-layer-chromadb)
3. [Memory File Format & Parsing](#3-memory-file-format--parsing)
4. [Deterministic ID Generation](#4-deterministic-id-generation)
5. [Data Ingestion Pathways](#5-data-ingestion-pathways)
6. [Semantic Query with Scoring Pipeline](#6-semantic-query-with-scoring-pipeline)
7. [Workflow Integration Pattern](#7-workflow-integration-pattern)
8. [Knowledge Consolidation System](#8-knowledge-consolidation-system)
9. [Belief Revision Framework](#9-belief-revision-framework)
10. [Apply System (Store Mutations)](#10-apply-system-store-mutations)
11. [Design Principles](#11-design-principles)
12. [Implementation Checklist](#12-implementation-checklist)

---

## 1. System Overview

The knowledge system has three layers:

```
┌──────────────────────────────────────────────────────────┐
│  Narrative Files (memory.md per entity)                  │
│  Human-readable logs: trades, observations, lessons      │
│  → Source of truth for ingestion                         │
├──────────────────────────────────────────────────────────┤
│  Vector Store (ChromaDB)                                 │
│  Searchable index: semantic queries, decay scoring       │
│  → Consumed by workflow agents via query function        │
├──────────────────────────────────────────────────────────┤
│  Consolidation System (periodic)                         │
│  Belief revision: contradictions, classification, apply  │
│  → Produces annotations, supersessions, new lessons      │
└──────────────────────────────────────────────────────────┘
```

**Key separation**: Narrative files are append-only human text. The vector store is a computed index that can be resynced from narrative files at any time. Consolidation is a periodic process that synthesizes raw events into accumulated knowledge and writes back into the vector store.

---

## 2. Vector Database Layer (ChromaDB)

### Setup

```python
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

CHROMA_DIR = project_root / ".chroma"

ef = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
client = chromadb.PersistentClient(path=str(CHROMA_DIR))
collection = client.get_or_create_collection(
    name="your_collection_name",
    embedding_function=ef,
    metadata={"hnsw:space": "cosine"},
)
```

| Setting | Value | Why |
| :--- | :--- | :--- |
| Embedding model | `all-MiniLM-L6-v2` | 384-dim, fast, good semantic similarity |
| Distance metric | `cosine` | Normalized comparison, scale-invariant |
| Storage | Local SQLite via `PersistentClient` | Zero infrastructure, persists to `.chroma/` |
| Collection | Single collection | Simple schema, filter by metadata at query time |

### Metadata Schema

Every entry has these metadata fields:

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `entity` | string | Yes | Grouping key (e.g., ticker symbol, project name, customer ID) |
| `category` | string | Yes | Entry type: `trade`, `observation`, `lesson`, `plan`, `news`, `macro` |
| `date` | string | Yes | ISO date `YYYY-MM-DD` or `"unknown"` |
| `source` | string | Yes | Origin: `memory.md`, `cmd_fill`, `cmd_sell`, `manual`, `consolidation` |
| `outcome` | string | No | Result metric (e.g., `+7.8%`, `-3.2%`). Used for outcome boost scoring |
| `superseded` | string | No | `"true"` if belief has been structurally invalidated. Filtered from queries |
| `consolidated_from` | string | No | JSON-encoded list of source entry IDs (e.g., `'["abc123","def456"]'`) |
| `sample_size` | string | No | For portfolio-level lessons — evidence count |

**Important**: ChromaDB metadata values must be strings, ints, or floats. Lists/dicts must be JSON-encoded as strings.

### Document Content

The `documents` field contains the full text of the knowledge entry. This is what gets embedded and searched semantically. Examples:

```
"CIFR: BUY 7 shares @ $13.87 (active-zone). Now 20 shares @ $14.02 avg."
"Originally misclassified as bounce-only. Actually has 2-week accumulation pattern."
"BTC hash rate difficulty increase causing sector-wide margin compression."
```

---

## 3. Memory File Format & Parsing

Each entity has a `memory.md` file with structured sections. The parser supports two formats:

### Bullet-List Format

```markdown
## Trade Log
- **2026-02-19:** BUY 7 shares @ $13.87 via active-zone entry
- **2026-03-01:** SELL 6 @ $16.08, full exit. Profit: +7.8% from $14.02 avg

## Observations
- **2026-02-25:** BTC hash rate difficulty increase causing sector-wide selling

## Lessons
- Support at $13.45 has 44% hold rate across 9 approaches — unreliable without wick offset
```

### Table Format

```markdown
## Trade Log
| Date | Action | Details |
| :--- | :--- | :--- |
| 2026-02-19 | BUY | 7 shares @ $13.87 via active-zone entry |
| 2026-03-01 | SELL | 6 @ $16.08, full exit. +7.8% from $14.02 avg |
```

### Section-to-Category Mapping

```python
SECTION_MAP = {
    "## Trade Log":     "trade",
    "## Trade History": "trade",
    "## Observations":  "observation",
    "## Lessons":       "lesson",
    "## Plan":          "plan",
}
```

The parser:
1. Detects `## ` headers to classify the current section
2. Within each section, detects bullet-list (`- `) or table (`|`) format
3. Extracts date via regex: `r'(\d{4}-\d{2}-\d{2})'`
4. Strips formatting (bold markers, bullet prefixes)
5. Multi-line bullet entries are concatenated until the next bullet or section
6. Falls back to `"unknown"` for dates that can't be parsed

---

## 4. Deterministic ID Generation

IDs are deterministic SHA256 hashes to enable idempotent upserts:

```python
import hashlib

def make_id(entity, category, date, text):
    raw = f"{entity}_{category}_{date}_{text[:80]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:8]
```

**Why this matters**: Running `ingest` or `resync` multiple times produces the same IDs, so `collection.upsert()` overwrites rather than duplicating. The first 80 chars of text are included to differentiate entries on the same date with the same category.

---

## 5. Data Ingestion Pathways

### A. Bulk Ingest (Initial Load / Resync)

```
memory.md files → parse → upsert into ChromaDB
```

The `ingest` command scans all `entities/*/memory.md` files, parses each, and bulk-upserts. The `resync` command deletes the entire collection first, then re-ingests from scratch.

**When to use**: Initial setup, after manual edits to memory files, or to recover from corruption.

### B. Automatic Event Storage (Real-Time)

Hook into your application's action handlers to store events as they happen:

```python
def store_fill(entity, price, shares, total_shares, new_avg, zone):
    """Called from your action handler when an event occurs."""
    text = f"{entity}: BUY {shares} shares @ ${price:.2f} ({zone}). "
           f"Now {total_shares} shares @ ${new_avg:.2f} avg."
    date = datetime.date.today().isoformat()
    doc_id = make_id(entity, "trade", date, text)
    collection.upsert(
        ids=[doc_id],
        documents=[text],
        metadatas=[{"entity": entity, "category": "trade",
                    "date": date, "source": "auto_fill"}]
    )

def store_sell(entity, price, shares, old_avg, pct_change):
    """Called when a position is closed — includes outcome metadata."""
    sign = "+" if pct_change >= 0 else ""
    text = f"{entity}: SELL {shares} @ ${price:.2f} (full exit). "
           f"Profit: {sign}{pct_change}% from ${old_avg:.2f} avg."
    date = datetime.date.today().isoformat()
    doc_id = make_id(entity, "trade", date, text)
    collection.upsert(
        ids=[doc_id],
        documents=[text],
        metadatas=[{"entity": entity, "category": "trade",
                    "date": date, "outcome": f"{sign}{pct_change}%",
                    "source": "auto_sell"}]
    )
```

**Key design**: Fills and sells are stored automatically by hooking into the portfolio management functions. Lessons and observations must be added manually (via CLI or bulk ingest).

### C. Manual CLI

```bash
python3 tools/knowledge_store.py add --entity CIFR --category observation \
    --date 2026-03-04 "BTC hash rate increase creating mining margin pressure"

python3 tools/knowledge_store.py add --entity CIFR --category lesson \
    --outcome "+7.8%" "Full exit at +7.8% confirms active-zone entry thesis"
```

---

## 6. Semantic Query with Scoring Pipeline

The query function does more than raw vector similarity. It applies a 3-factor scoring pipeline:

### Query Flow

```
User query text → ChromaDB cosine similarity → filter pipeline → ranked results
```

### Scoring Formula

```
effective_relevance = base_relevance × decay × outcome_boost
```

Where:

#### Base Relevance (from cosine distance)
```python
base_relevance = 1.0 - (cosine_distance / 2.0)
# Range: 0.0 to 1.0
# Threshold: skip if <= 0.4
```

#### Temporal Decay (exponential, half-life 60 days)
```python
DECAY_HALF_LIFE_DAYS = 60

def compute_decay(date_str):
    if date_str == "unknown":
        return 0.5  # conservative default
    days_ago = (today - parsed_date).days
    return 0.5 ** (days_ago / DECAY_HALF_LIFE_DAYS)

# Examples:
# Today:    1.0
# 30 days:  0.71
# 60 days:  0.5
# 120 days: 0.25
# 180 days: 0.125
```

#### Outcome Boost (amplifies results with known outcomes)
```python
def compute_outcome_boost(outcome_str):
    pct = parse_outcome_pct(outcome_str)  # "+7.8%" → 7.8
    if pct is None:
        return 1.0  # no boost
    return 1.0 + min(abs(pct) / 20.0, 0.5)  # max 1.5x

# Examples:
# No outcome: 1.0x
# +5%:        1.25x
# +10%:       1.5x (capped)
# -15%:       1.5x (absolute value — losses are also informative)
```

### Filtering Pipeline

```python
def query_entity_knowledge(entity, context_hint, n=3, include_superseded=False):
    # 1. Fetch 3x candidates (compensate for filtering)
    fetch_n = min(n * 3, collection.count())
    results = collection.query(
        query_texts=[context_hint],
        n_results=fetch_n,
        where={"entity": entity},
    )

    # 2. Score and filter
    adjusted_hits = []
    for doc, meta, dist in zip(docs, metas, dists):
        if not include_superseded and meta.get("superseded") == "true":
            continue  # Skip invalidated beliefs
        base_rel = 1.0 - dist / 2.0
        if base_rel <= 0.4:
            continue  # Below relevance threshold
        decay = compute_decay(meta.get("date", "unknown"))
        outcome_boost = compute_outcome_boost(meta.get("outcome", ""))
        effective = base_rel * decay * outcome_boost
        if effective > 0.4:
            adjusted_hits.append((doc, meta, effective))

    # 3. Sort by effective relevance, return top N
    adjusted_hits.sort(key=lambda x: x[2], reverse=True)
    return adjusted_hits[:n]
```

### Output Format

The query returns a compact string for embedding in agent outputs:

```
**Knowledge:** 3 trades, 2 lessons. Top: Sold 6 @ $16.08, full exit +7.8% (0.82)
```

The number in parentheses is the effective relevance score after decay and outcome boost.

### Cached Collection Pattern

For high-frequency callers (e.g., workflow pre-scripts that query per entity), use a cached collection to avoid re-initializing ChromaDB on every call:

```python
_CACHED_COLLECTION = None
_CACHE_INITIALIZED = False
_TRANSIENT_ERROR_COUNT = 0

def get_cached_collection():
    global _CACHED_COLLECTION, _CACHE_INITIALIZED, _TRANSIENT_ERROR_COUNT
    if _CACHE_INITIALIZED:
        return _CACHED_COLLECTION
    try:
        _, collection = get_collection()
        _CACHED_COLLECTION = collection
        _CACHE_INITIALIZED = True
        _TRANSIENT_ERROR_COUNT = 0
        return collection
    except (SystemExit, ImportError):
        _CACHE_INITIALIZED = True  # permanent failure
        return None
    except Exception:
        _TRANSIENT_ERROR_COUNT += 1
        if _TRANSIENT_ERROR_COUNT >= 3:
            _CACHE_INITIALIZED = True  # give up after 3 retries
        return None
```

---

## 7. Workflow Integration Pattern

### How Workflows Consume Knowledge

Workflow pre-scripts (Python) call `query_entity_knowledge()` during data gathering. The knowledge line is embedded into the condensed data file that the LLM agent reads.

```python
# In a workflow pre-script (e.g., status_gatherer.py):
from knowledge_store import query_ticker_knowledge

for ticker in active_tickers:
    knowledge = query_ticker_knowledge(ticker, f"{ticker} recent performance")
    if knowledge:
        output_lines.append(knowledge)
    # → "**Knowledge:** 2 trades, 1 lesson. Top: BUY 7 @ $13.87 (0.78)"
```

### Design Rule: Python Pre-Scripts for Mechanical Work, LLMs for Reasoning

The foundational pattern across all workflows:

| Layer | Responsibility | Example |
| :--- | :--- | :--- |
| Python pre-script | Data gathering, arithmetic, cross-referencing, formatting | Fetch prices, compute P/L, query knowledge store |
| LLM agent | Qualitative judgment, thesis evaluation, risk assessment | "Should we hold or exit this position?" |
| Python critic | Verification checks, consistency validation | Check math, verify citations, validate JSON |

This separation is critical because:
- LLMs get arithmetic wrong ~5-10% of the time
- Python is deterministic and fast (seconds vs minutes)
- LLMs are good at synthesis, judgment, and natural language reasoning
- Python can't evaluate "is this a temporary or structural change?"

### 3-Phase Workflow Template

```yaml
phases:
  - id: gather
    name: Data Extraction
    agent: gatherer          # Thin wrapper: runs Python pre-script
    artifacts: [raw.md]
    timeout_minutes: 3

  - id: analyze
    name: Analysis
    agent: analyst           # LLM reads raw.md, applies judgment
    depends_on: [gather]
    requires: [raw.md]
    artifacts: [report.md, updates.json]
    timeout_minutes: 10

  - id: review
    name: Verification
    agent: critic            # Runs Python critic, then LLM validates quality
    depends_on: [analyze]
    requires: [raw.md, report.md, updates.json]
    artifacts: [review.md]
    timeout_minutes: 5
```

---

## 8. Knowledge Consolidation System

The consolidation system transforms raw, append-only knowledge entries into synthesized beliefs with periodic review. This is the highest-value component.

### Why Consolidation Exists

Raw knowledge stores have a fundamental problem: entries are facts without synthesis. After 6 months, you might have:
- Entry A: "Level $13.45 held on approach" (Feb 2025)
- Entry B: "Level $13.45 broke on high volume" (Aug 2025)
- Entry C: "Level $13.45 held after bounce" (Oct 2025)
- Entry D: "Level $13.45 broke, -5% intraday" (Jan 2026)

Which belief is correct? The store has no opinion. Consolidation forces that opinion.

### Architecture

```
Phase 1: Python Pre-Script (knowledge_consolidator.py, ~5s)
├── Bulk retrieve all ChromaDB entries
├── Compute per-entity stats (win rate, avg return, etc.)
├── Load domain-specific validation data (e.g., wick analysis)
├── Filter placeholder/stub entries
├── Build belief evidence tables (FOR vs AGAINST with weights)
├── Score contradictions (0-1 scale)
├── Aggregate cross-entity patterns
└── Write raw.md

Phase 2: LLM Analyst (~3-5 min)
├── Read raw.md (ONLY input — single file)
├── For each contradiction score > 0.3:
│   ├── Classify: TEMPORARY or STRUCTURAL (no hedging)
│   ├── Cite >=2 specific evidence points
│   └── Generate action (annotate or supersede)
├── Synthesize per-entity knowledge cards
├── Write portfolio-level lessons (sample >= 5)
├── Write report.md
└── Write updates.json

Phase 3: Python Critic + LLM (~2 min)
├── 6 mechanical verification checks
├── LLM validates classification quality
└── Write review.md

Manual Step: apply command
└── Read updates.json → mark superseded, add lessons, annotate entries
```

### Contradiction Scoring

```python
def score_contradiction(evidence_for, evidence_against):
    """0.0 = no contradiction, 1.0 = total contradiction.

    Recency weighting: evidence from last 30 days gets 2x weight.
    Score = weighted_against / (weighted_for + weighted_against)
    """
    if not evidence_against:
        return 0.0

    weighted_for = sum(e["weight"] for e in evidence_for)
    weighted_against = sum(e["weight"] for e in evidence_against)

    total = weighted_for + weighted_against
    if total == 0:
        return 0.0

    return weighted_against / total
```

Evidence items have a `weight` field: `1.0` for events older than 30 days, `2.0` for recent events. This biases toward recency without ignoring history.

### Evidence Table Format (in raw.md)

```markdown
#### Belief: "CIFR $14.26 PA holds reliably at 62%" (Lesson ID: def456ab)
| Field | Detail |
| :--- | :--- |
| Evidence FOR | 4 holds out of 9 approaches (44% raw) |
| Evidence AGAINST | Level migrated to $13.45; 3 breaks in 30 days |
| Context Events | BTC hash rate difficulty increase, sector-wide selling |
| Contradiction Score | 0.45 |

*LLM: Classify — TEMPORARY or STRUCTURAL.*
```

### Per-Entity Stats

```python
def compute_entity_stats(entries):
    return {
        "event_count": total_events,
        "win_count": wins,
        "loss_count": losses,
        "win_rate": win_count / (win_count + loss_count),
        "avg_return_pct": mean_of_outcomes,
        "lesson_count": lesson_entries,
        "observation_count": observation_entries,
        "has_sufficient_data": total >= 3,
    }
```

### Cross-Entity Pattern Aggregation

The consolidator also identifies patterns that span multiple entities:

```python
def aggregate_cross_entity_patterns(all_stats, all_domain_data):
    # Example patterns:
    # "Entities with <3 data points: 67% failure rate"
    # "Same-category exits avg +5.8% vs cross-category +3.2%"
    # "Sector X win rate: 78% vs portfolio avg 65%"
    return [{"pattern": str, "sample_size": int, "confidence": str}]
```

### Placeholder Filtering

Before building evidence tables, filter out stub entries:

```python
def filter_placeholder_entries(entries):
    """Skip entries that are placeholders, not real beliefs."""
    skip_patterns = [
        r'^\(none',
        r'^\(first',
        r'^\(no trades',
        r'^New onboarding',
        r'^pending',
    ]
    return [e for e in entries
            if len(e["text"].strip()) >= 25
            and not any(re.match(p, e["text"]) for p in skip_patterns)]
```

---

## 9. Belief Revision Framework

This is the design center — the hardest problem in knowledge management. When evidence contradicts a stored belief, is the belief wrong (structural) or is the environment temporarily deviating?

### Classification Rules (Embedded in LLM Persona)

The LLM analyst MUST follow these rules when classifying contradictions:

```
1. Pick exactly TEMPORARY or STRUCTURAL. No "possibly", "likely", "unclear."

2. Cite at least 2 SPECIFIC data points. Numbers, dates, or percentages from
   the evidence table. "The data shows contradictions" is NOT a citation.

3. "External conditions" alone does NOT justify TEMPORARY.
   BAD:  "Temporary because conditions were unfavorable"
   GOOD: "Temporary because [specific event] on [date] caused [metric] to drop [amount]"

4. "The belief broke" alone does NOT justify STRUCTURAL.
   BAD:  "Structural because it failed 3 times"
   GOOD: "Structural because [fundamental change] on [date] permanently shifted
          the underlying dynamics"

5. RECENCY BIAS CHECK — if evidence_against is all from the last 30 days
   AND evidence_for spans 6+ months, ask: "Is 30 days enough to invalidate
   6 months?" If the answer is "only if a fundamental changed," check for
   the fundamental. No fundamental found → lean TEMPORARY.

6. ACCUMULATION CHECK — if evidence_against shows 3+ independent failures
   across 3+ weeks (not a single event), lean STRUCTURAL regardless of
   named catalyst. Multiple failures over time signal degradation,
   not a temporary shock.

7. DEFAULT WHEN GENUINELY UNCERTAIN: TEMPORARY with annotation is safer
   than false STRUCTURAL. A false STRUCTURAL deletes a valid belief.
   A false TEMPORARY keeps a stale belief but with a warning flag.
```

**Rules 5 and 6 are the forcing functions:**
- Rule 5 prevents recency bias — recent failures don't automatically kill long-held beliefs
- Rule 6 prevents persistence bias — accumulated evidence across weeks IS structural
- Together they force the LLM to weigh time horizon AND frequency

### Mandatory Output Format

```markdown
### [ENTITY] Belief: "[belief text]"

**Classification:** TEMPORARY | STRUCTURAL

**Justification:**
- [Specific data point 1 — number, date, or percentage]
- [Specific data point 2]
- TEMPORARY: "[Named event] caused deviation during [date range]"
- STRUCTURAL: "[Named change] invalidates belief because [mechanism]"

**Action:**
- TEMPORARY → Annotate: "[original belief] — Note: [event] temporary deviation [dates]"
- STRUCTURAL → Supersede: "[new belief based on current evidence]"
```

---

## 10. Apply System (Store Mutations)

The consolidation workflow produces `updates.json`. A separate `apply` command reads it and mutates the vector store. This is deliberately manual — review the report before applying.

### updates.json Format

```json
{
  "superseded": [
    {"id": "abc123ef", "reason": "structural: secondary offering shifted dynamics"}
  ],
  "new_lessons": [
    {
      "entity": "APLD",
      "category": "lesson",
      "text": "Former $25 support invalidated by Feb 2026 secondary offering...",
      "source": "consolidation",
      "consolidated_from": ["abc123ef", "def456ab"]
    }
  ],
  "annotations": [
    {
      "id": "ghi789cd",
      "append_text": " — Note: BTC correction Feb 12-18 temporary deviation"
    }
  ],
  "portfolio_lessons": [
    {
      "category": "portfolio_lesson",
      "text": "Entities with <3 data points have 67% failure rate...",
      "sample_size": 18
    }
  ]
}
```

### Apply Operations

```python
def cmd_apply():
    data = json.loads(updates_path.read_text())

    # 1. Mark superseded entries
    for entry in data.get("superseded", []):
        old_meta = collection.get(ids=[entry["id"]])["metadatas"][0]
        old_meta["superseded"] = "true"
        collection.update(ids=[entry["id"]], metadatas=[old_meta])

    # 2. Add new lesson entries (with consolidated_from lineage)
    for entry in data.get("new_lessons", []):
        doc_id = make_id(entry["entity"], "lesson", today, entry["text"])
        meta = {
            "entity": entry["entity"],
            "category": "lesson",
            "date": today,
            "source": "consolidation",
            "consolidated_from": json.dumps(entry.get("consolidated_from", []))
        }
        collection.upsert(ids=[doc_id], documents=[entry["text"]], metadatas=[meta])

    # 3. Append annotation text (idempotent — skip if already appended)
    for ann in data.get("annotations", []):
        result = collection.get(ids=[ann["id"]], include=["documents", "metadatas"])
        old_doc = result["documents"][0]
        if old_doc.endswith(ann["append_text"]):
            continue  # already annotated
        collection.update(ids=[ann["id"]], documents=[old_doc + ann["append_text"]])

    # 4. Add portfolio-level lessons under entity="PORTFOLIO"
    for entry in data.get("portfolio_lessons", []):
        doc_id = make_id("PORTFOLIO", "portfolio_lesson", today, entry["text"])
        collection.upsert(ids=[doc_id], documents=[entry["text"]],
                          metadatas=[{"entity": "PORTFOLIO", "category": "portfolio_lesson",
                                      "date": today, "source": "consolidation",
                                      "sample_size": str(entry["sample_size"])}])
```

---

## 11. Design Principles

### 1. State vs Narrative Separation
- **Machine state** (portfolio.json, database): structured, authoritative, drives application logic
- **Narrative** (memory.md files): human-readable logs, source for ingestion, not queried by code
- **Vector index** (ChromaDB): computed from narrative + auto events, can be resynced any time

### 2. Python for Mechanical, LLM for Reasoning
- Python pre-scripts handle: data gathering, arithmetic, cross-referencing, formatting, verification
- LLM agents handle: synthesis, thesis evaluation, classification judgment, natural language generation
- This split makes workflows deterministic where they can be and intelligent where they must be

### 3. Single-File Agent Input
- Each LLM agent reads ONE file (e.g., `raw.md`). All data needed for that phase is pre-assembled by the Python pre-script
- Prevents context window overflow at scale (30+ entities)
- Budget: ~6-7 KB per entity in condensed output

### 4. Idempotent Operations
- Deterministic IDs → `upsert` is always safe to repeat
- Annotation `endswith` guard → running apply twice doesn't double-annotate
- Resync → delete + re-ingest from source files rebuilds clean state

### 5. Manual Apply Gate
- Workflows produce reports; they don't auto-mutate knowledge state
- User reviews `report.md` and `review.md` before running `apply`
- Prevents cascading errors from LLM misclassification

### 6. Decay Over Deletion
- Old entries decay in relevance (exponential, 60-day half-life) but aren't deleted
- Superseded entries are filtered from queries but remain in the store for lineage
- "Forgotten" knowledge can be recovered by querying with `include_superseded=True`

### 7. Verification as First-Class Citizen
Every workflow phase that involves LLM output gets a critic phase with mechanical checks:

| Check | What It Verifies |
| :--- | :--- |
| Coverage | Every flagged item has a classification |
| Evidence citations | Every classification cites >= 2 specific data points (numbers/dates/%) |
| JSON well-formedness | updates.json parses, all required fields present |
| Superseded-replacement pairing | Every superseded ID has a matching new lesson |
| Stats transcription | Report metrics match raw data |
| Threshold gates | Portfolio lessons meet minimum sample size |

---

## 12. Implementation Checklist

### Phase 1: Vector Store Foundation
- [ ] Install dependencies: `pip install chromadb sentence-transformers`
- [ ] Create `knowledge_store.py` with ChromaDB setup, `make_id()`, `get_collection()`
- [ ] Implement `cmd_add` (manual CLI entry)
- [ ] Implement `cmd_query` (semantic search with cosine distance)
- [ ] Implement `cmd_stats` (collection summary by entity/category)
- [ ] Define your entity directory structure (`entities/*/memory.md`)
- [ ] Define `SECTION_MAP` for your domain's section headers

### Phase 2: Memory Parsing & Ingestion
- [ ] Implement memory.md parser (bullet-list + table formats)
- [ ] Implement `cmd_ingest` (bulk parse → upsert)
- [ ] Implement `cmd_resync` (delete collection → re-ingest)
- [ ] Add deterministic ID generation
- [ ] Test: ingest, resync, verify no duplicates

### Phase 3: Automatic Event Storage
- [ ] Implement `store_event()` functions for your domain's key actions
- [ ] Hook into your application's action handlers (e.g., portfolio manager)
- [ ] Include `outcome` metadata where applicable (for outcome boost)
- [ ] Test: trigger action → verify entry appears in knowledge store

### Phase 4: Enhanced Query Pipeline
- [ ] Implement `compute_decay()` (exponential, configurable half-life)
- [ ] Implement `compute_outcome_boost()` (configurable cap)
- [ ] Add superseded filtering to query function
- [ ] Implement cached collection pattern for high-frequency callers
- [ ] Add transient error retry with max attempts
- [ ] Test: verify decay scoring, superseded filtering, outcome boost

### Phase 5: Workflow Integration
- [ ] Create Python pre-scripts that call `query_entity_knowledge()`
- [ ] Embed knowledge lines in condensed data files for LLM agents
- [ ] Verify knowledge surfaces in workflow outputs

### Phase 6: Consolidation System
- [ ] Create `knowledge_consolidator.py` (Phase 1 pre-script)
  - [ ] `load_all_entries()` — bulk ChromaDB retrieval
  - [ ] `compute_entity_stats()` — per-entity metrics
  - [ ] `filter_placeholder_entries()` — remove stubs
  - [ ] `build_belief_evidence_table()` — FOR/AGAINST with weights
  - [ ] `score_contradiction()` — 0-1 scale with recency bias
  - [ ] `aggregate_cross_entity_patterns()` — portfolio-level
  - [ ] Entry ID Reference tables for lineage tracking
- [ ] Create LLM analyst persona with 7 classification rules
- [ ] Create `knowledge_consolidation_critic.py` (6 verification checks)
- [ ] Create workflow YAML (3 phases: gather → analyze → review)
- [ ] Implement `cmd_apply` with idempotent guards
- [ ] Test full pipeline: consolidator → analyst → critic → apply → verify queries

### Phase 7: Operational
- [ ] Run initial resync to populate store from existing memory files
- [ ] Run first consolidation to establish baseline
- [ ] Set cadence (weekly/monthly) for consolidation runs
- [ ] Document the apply review process for operators

---

## Appendix: CLI Reference

```bash
# Add a knowledge entry manually
python3 tools/knowledge_store.py add --entity ENTITY --category CATEGORY \
    [--date YYYY-MM-DD] [--outcome "+X.X%"] "Entry text here"

# Semantic search
python3 tools/knowledge_store.py query "search terms" [--entity ENTITY] [--n 5] [--verbose]

# Bulk ingest from memory.md files
python3 tools/knowledge_store.py ingest

# View stats
python3 tools/knowledge_store.py stats

# Delete and re-ingest (clean rebuild)
python3 tools/knowledge_store.py resync

# Apply consolidation updates (after reviewing reports)
python3 tools/knowledge_store.py apply
```

## Appendix: Dependencies

```
chromadb>=0.4.0
sentence-transformers>=2.0.0
```

ChromaDB uses SQLite internally — no external database required. The `.chroma/` directory contains all persistent state and can be deleted + resynced at any time.
