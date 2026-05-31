# Commit Evaluation — `5216f69` "feat: add v2 trend monitoring pipeline"

**Status:** Plan-ready brief (conformance audit + resolved decisions; no code changes here)
**Author:** evaluation pass, hardened into a plan-ready brief
**Date:** 2026-05-31 (data as of last trading day Friday 2026-05-29)
**Commit:** `5216f6992abec6369c1237480baca3bdef404ea4` on `feature/agentic-trading-v2-trend-monitoring`
**Diff size:** 29 files, +5563 / −5

> **How to use this document.** §1–§5 are the conformance audit (what the commit
> does vs. the locked spec). §6 resolves the spec's *structural* gaps; §11–§13 resolve
> the *behavioral* gaps (decision rules, strategy gates) and the data sourcing — both
> with proposed defaults you must confirm. §7 reproduces the locked taxonomies inline.
> §8–§10 give the dependency order, fixtures, and guardrails. A planner should be able
> to write a one-shot implementation plan from §5–§13 without re-reading the spec —
> provided the `PROPOSED — confirm` items in §6 and §11–§13 are accepted.

---

## 1. Scope, Method, and Reconciliation Principle

This document evaluates commit `5216f69` against the **locked specification** it is
supposed to implement: `plans/agentic-trading-v2-workflow-principles-research.md`
(added in the same commit) — specifically the **Locked Implementation Decisions**
(§123–222), **Locked `recent_edge_score` Rules** (§166–222), **Trading-Native
Contract Design** (§1076–1264), **Locked Artifact Schemas** (§1265–1340),
**Scale Architecture** (§1471–1534), **Resume/Run-Status semantics** (§1562–1637),
and **State Boundary / Write Policy** (§1639–1696).

Method: read every tool and test added by the commit, ran the trend test suite,
cross-checked each artifact/field/threshold the code produces against the locked
rules, and ran a completeness audit of the spec itself to separate "code diverges
from spec" from "spec is itself under-specified."

**Reconciliation principle (locked with the author):** where committed code and the
locked spec disagree on a value (score formula, threshold, enum), **the spec is
authoritative and the code is the thing to change.** Resolutions below assume this
direction unless a §6 decision says otherwise.

### What the commit ships

- **9 tools** (`tools/`): `trend_contracts.py`, `daily_trend_snapshot.py`,
  `trend_extractor.py`, `trend_ledger.py`, `trend_validator.py`, `trend_critic.py`,
  `trend_action_planner.py`, `trend_phase_ledger.py`, `trend_reporter.py`; plus a
  `candidate_tracker.py` safety patch.
- **5 schema docs** (`schemas/trend_monitoring/*.schema.json`).
- **10 test files** — **20 tests, all passing**.
- **2 research docs** (the principles research + its gap-audit).

### Pipeline as built

`daily_trend_snapshot.py` → `daily-market-snapshot.json` → `trend_phase_ledger.py` /
`trend_ledger.py` (calls `trend_extractor.enrich_snapshot_record`) → `trend-ledger.json`
+ `validation-findings.json` + `critic-patches.json` → `trend_action_planner.py` →
`monitoring-actions.json` → `trend_reporter.py` → `daily-trend-report.md`.
`run-status.json` is rewritten by each tool; artifacts are copied into
`data/trend_monitoring/run-history/<date>/<run_id>/`.

---

## 2. Overall Assessment

The commit delivers a **clean, well-tested deterministic skeleton** that honors
several spec principles well (atomic writes, read-only `write_effect`, source-ref
provenance, reuse of `compute_support_level_score`, run-history lineage, the
`candidate_tracker` dry-run safety patch). The Python is consistent with house
conventions.

It realizes a **substantially simplified subset** of the locked spec. The two most
consequential gaps are conceptual:

1. **The ledger is stateless** — fully regenerated from the day's snapshot each run,
   with no `stable_key`, `id`, `first_seen/last_seen`, `transitions`, or
   `prior_ledger_run_id`. The spec's entire reason for existing — keep a durable,
   cross-run monitored pool (§275–276, §1250, §1283–1297) — is not yet implemented.
2. **The `recent_edge_score` math and thresholds diverge from the locked rules** —
   two of four normalization formulas differ, and none of the priority/readiness
   thresholds match the locked values (§166–222).

Treat this commit as **Phase 0 scaffolding**: internally coherent, not yet
spec-conformant. The gap ledger (§5) is prioritized; §8 sequences it.

---

## 3. Conformance Scorecard vs. Locked Decisions (§123–164)

| # | Locked decision | Status | Note |
| :--- | :--- | :--- | :--- |
| 1 | `recent_edge_score` weighted blend 40/25/20/15 | ⚠️ Partial | Weights correct; 2 of 4 normalization formulas diverge (§5.1) |
| 2 | Local `trend_phase_ledger.py` mini-harness, no mcp vendoring | ✅ Met | No mcp import; mini-harness present (chains snapshot→ledger only) |
| 3 | End-of-day schedule | ➖ N/A | CLI-chain only; workflow YAML is approval-gated, not required yet (§1599) |
| 4 | Scale: ≤500 monitored, ≤75 refresh, ≤30 review | ❌ Missing | No quotas/caps anywhere (§5.4) |
| 5 | Runtime target + `completed_with_gaps`/`failed` on overrun | ❌ Missing | No timing guard / `runtime_limit_exceeded` class — see §5.12 |
| 6 | Cache windows (same-day price, ≤3-day universe, 5-day support) | ❌ Missing | No cache-age gating; `cache_status` absent — see §5.5, §5.13 |
| 7 | Write boundary: only `data/trend_monitoring/`, no auto candidate write | ✅ Met | `write_effect: none` enforced in validator; candidate writes stay manual |
| 8 | Contracts as Python enums + JSON schema + deterministic tests | ⚠️ Partial | Present but incomplete: 2 validators/2 schemas missing, no agreement test (§5.7) |

---

## 4. What the commit gets right (credit)

- **Atomic writes** — `atomic_write_json/text` use tmp-file + `os.replace`
  (`trend_contracts.py:78–91`), matching the locked write semantics (§1575).
- **Read-only enforcement** — `validate_monitoring_actions` *rejects* any action
  whose `write_effect != "none"` (`trend_contracts.py:419`). Hard-codes the write
  boundary into the contract.
- **Source provenance** — every record/finding carries `source_refs` with
  `json_pointer`, `as_of_date`, `freshness`, `claim_field` (Source Evidence Model
  §1193). *(But the freshness enum and `claim_field` semantics are wrong — see §5.10,
  §5.11. This was incorrectly credited as fully conformant in an earlier draft.)*
- **No support-score duplication** — `trend_extractor` imports
  `compute_support_level_score` from `shared_utils` exactly as locked (§197–199).
- **Score-input transparency** — `recent_edge_score_inputs` records per-component
  `raw_value`/`normalized_value`/`weight`/`missing`; validator checks weights sum to
  1.0 (`trend_contracts.py:308`). Strong partial match to §204–207.
- **Run-history lineage** — `copy_to_run_history` snapshots every artifact under
  `run-history/<date>/<run_id>/`, matching the immutable-copy rule (§1573).
- **`candidate_tracker.py` safety patch** — `cmd_add`/`cmd_age_out`/
  `cmd_import_screening` now no-op the save under `--dry-run` and only save on a real
  delta. Aligns with the cautious write boundary.
- **Test hygiene** — one test file per tool, all 20 pass.

**Newly confirmed: areas the spec fully locks — do NOT redesign these.** An earlier
draft under-credited them. The implementation plan should treat them as authoritative
and conform to them rather than invent alternatives:

- **Resume / Idempotency** (§1562–1590): `run_id = <as_of_date>-<HHMMSS>-<short_hash>`,
  same-day rerun replaces current artifacts while preserving run-history, merge by
  `stable_key`, partial failure → `completed_with_gaps`, no phase may delete
  run-history.
- **Run-Status lifecycle** (§1592–1637): snapshot creates the file; later phases load
  + validate + update only their own `phase_statuses[]` entry; deterministic aggregate
  precedence (`failed` > `nonconverged` > `completed_with_gaps` > `completed`); on
  failure/nonconvergence the failing phase synthesizes `skipped` downstream entries.
- **Scale Architecture** (§1485–1534): the 7-step daily runtime strategy, sector/
  liquidity sharding, cache windows, and "LLM cost scales with promoted records, not
  the universe."
- **State Boundary / Write Policy** (§1639–1696): allowed/forbidden auto-writes and
  the human-approval boundary.

---

## 5. Gap Ledger (prioritized; each as Current → Target → Resolution → Acceptance)

### 5.1 — `recent_edge_score` math diverges from locked formulas — **BLOCKER**

- **Current:** `trend_extractor._score_delta_pct` uses `(d+15)/30·100` (±15 saturates);
  `_score_liquidity_freshness` blends `0.65·(vol/500k·100) + 0.35·{fresh:100,unknown:50,stale:35}`.
- **Target (§174–182):** fitness delta `50 + clamp(d,−25,25)·2` (±25 saturates);
  liquidity starts at 100 and subtracts 30 (partial provider) / 30 (stale cache) /
  20 (below-target avg vol, threshold `MIN_AVG_VOL=500_000`) / 20 (missing ATR), clamp
  0..100. Return component `50 + clamp(r,−20,20)·2.5` is already equivalent — keep.
- **Resolution:** rewrite `_score_delta_pct` to the ±25 form; replace
  `_score_liquidity_freshness` with the penalty model. The liquidity penalties need
  `partial-provider`, `stale-cache`, and `atr` signals the snapshot does not capture
  → **depends on §5.5 snapshot expansion.** Also fix the **denominator** (see §11.10):
  the current code sums present-component weights without dividing by their sum, so the
  spec's "excluded from the denominator" rule (§212) is violated and any record missing
  a component is under-scored.
- **Acceptance:** `_score_delta_pct(25)==100`, `(0)==50`, `(-25)==0`;
  liquidity unit test: full data = 100, partial+stale = 40, missing ATR + low vol
  applies −40, clamps at 0; **re-normalization:** a record with only the support
  component present (normalized 80, weight 0.40) scores **80**, not 32 (§11.10).

### 5.2 — Stateless ledger: no record identity, merge, or transitions — **BLOCKER**

- **Current:** `enrich_snapshot_record` emits only `ticker`, `metrics`, `source_refs`,
  `trend_state`. Ledger rebuilt from scratch each run.
- **Target (§1283–1297, §1250, §1579–1581):** records carry `id`, `stable_key`,
  `trend_category`, `trend_status`, `first_seen`, `last_seen`, `last_updated`,
  `patch_history`; ledger root carries `prior_ledger_run_id`, `run_status`,
  `transitions`, `summary`. `trend_ledger.py` merges against the prior ledger by
  `stable_key`; IDs stay stable across runs.
- **Resolution:** add `stable_key` (§6.7) + `trend_category` (§6.1); on each run load
  prior `trend-ledger.json`, match by `stable_key`, carry `first_seen`, recompute
  `last_seen`/transition (§6.6), allocate new `id` only for new keys.
- **Acceptance:** two-run fixture (§9): a key present both days → `persisting`,
  `first_seen` preserved, stable `id`; a key only in run 2 → `new`; a key only in run
  1 → `stale`→`retired` per §6.6.

### 5.3 — Missing `readiness`/`priority_tier`/`missing_edge_components`; wrong thresholds — **HIGH**

- **Current:** single `trend_state` with cutoffs `high_priority≥75`, `candidate≥60`,
  `monitor`, `insufficient_evidence` (`trend_extractor.py:142`); action planner uses
  `PROMOTE≥75`/`ADD≥60` (`trend_action_planner.py:29`). No `readiness`,
  `priority_tier`, `source_quality`, or `missing_edge_components[]`.
- **Target:** priority tiers `P1≥80 & fresh`, `P2≥65`, `P3≥50`, `P4<50` (§217);
  readiness `accepted≥65`, `monitor_only≥50`, `blocked`, `needs_data`, `failed`
  (§219–222); `missing_edge_components[]` required (§204–213); all-missing →
  `recent_edge_score:null`, `readiness:needs_data`, `source_quality:partial`, **plus**
  a `DATA_PROVIDER_GAP`/`INSUFFICIENT_RECENT_EDGE` finding (§214–216, currently silent).
- **Resolution:** replace `trend_state` with the locked derived-output enums (§7);
  emit `missing_edge_components[]` from the existing per-input `missing` flags; emit the
  finding on the all-missing path.
- **Acceptance:** score 82+fresh → P1/accepted; 55 → P3/monitor_only; all-missing →
  null/needs_data/partial **and** one INSUFFICIENT_RECENT_EDGE finding present.

### 5.4 — No quotas / scale caps — **HIGH**

- **Current:** one action per ledger record, uncapped, unranked.
- **Target (§115, §1327–1328):** `monitoring-actions.json` carries a `quotas` block
  (`max_review_actions=30`, `max_high_priority_refreshes=75`,
  `max_monitored_tickers=500`, + `used_*`); selection respects the caps.
- **Resolution:** implement the ranking/overflow rule in §6.2.
- **Acceptance:** >500-ticker fixture → exactly 500 monitored, ≤75 refresh-eligible,
  ≤30 review actions; overflow records get `monitor_only`/`daily`; `used_*` counters
  match the emitted counts (§9).

### 5.5 — Artifact schemas are a simplified subset — **HIGH**

- **Current:** snapshot is a flat `records` **list** with no `run_id`, `universe`,
  `provider_failures`, `cache_status`; `monitoring-actions` lacks `id`/`trend_id`/
  `action_category`/`priority_tier`/`next_workflow`/`human_approval_required`/
  `expires_after`; `run-status` lacks `started_at`/`source_universe_count`/
  `accepted_trend_count`/`blocked_trend_count`/`failed_record_count`/`failure_classes`/
  `artifact_paths`.
- **Target (§1269–1339):** snapshot roots on `run_id`, `universe`, `tickers` (object
  **keyed by symbol**, so pointers read `/tickers/ABCD/price`), `provider_failures`,
  `cache_status`; per-ticker adds `sector`, `volume`, `atr`, `daily_change_pct`,
  `monthly_swing`, `consistency`, `liquidity_status`, `earnings_status`, overlaps.
  Actions and run-status get their locked fields.
- **Resolution:** expand the snapshot writer + validator to the keyed-by-ticker shape
  and full field set; this is a **breaking change** — every `json_pointer` and every
  consumer (`trend_extractor`, `trend_ledger`, all `source_ref` construction) changes.
  No `SCHEMA_VERSION` bump needed (§6.5). The new `atr`/`sector`/`earnings`/`cache`/
  `provider` fields unblock §5.1 (liquidity) and the full classifier (§6.1).
- **Acceptance:** keyed-by-ticker fixture validates; a source_ref pointer resolves via
  RFC-6901 against the snapshot; run-status carries non-null counts after a run.

### 5.6 — Run-status lifecycle semantics not implemented — **HIGH**

*(Reframed: the missing workflow YAML is acceptable — it is approval-gated, §1599. The
real gap is the locked CLI-chain run-status semantics.)*

- **Current:** each tool independently **rebuilds all four** `phase_statuses` from
  scratch, with inconsistent timing (snapshot marks downstream phases `skipped` yet
  sets `finished_at`; planner reconstructs start times from the ledger's
  `generated_at`; reporter rebuilds everything). `run_id` is `uuid4().hex`
  (`trend_contracts.py:71`).
- **Target (§1569, §1592–1637):** `run_id = <as_of_date>-<HHMMSS>-<short_hash>`; snapshot
  creates the file; **each phase loads, validates, and updates only its own entry**,
  preserving others; deterministic aggregate precedence; failing/nonconverged phase
  synthesizes `skipped` downstream entries; report phase owns terminal `finished_at`.
- **Resolution:** add a shared `run_status.update_phase(phase, …)` helper in
  `trend_contracts.py` that loads → replaces one entry → recomputes aggregate; switch
  the `run_id` generator to the locked format; route every tool through the helper.
- **Acceptance:** running snapshot→ledger→actions→report yields one monotonic
  `run-status.json` with four owned entries and correct terminal status; a forced
  ledger `nonconverged` synthesizes `skipped` for actions+report and sets root status
  `nonconverged`.

### 5.7 — Contract surface incomplete — **MEDIUM**

- **Current:** validator is named `validate_daily_snapshot`; **no `validate_critic_patches`**
  (critic-patches written but never validated; absent from `VALIDATORS`); 5 schema files
  present, but `validation-findings.schema.json` and `critic-patches.schema.json` are
  missing while `source-ref.schema.json` (not one of the six) is added; **no
  schema↔validator agreement test**; critic operation vocabulary
  (`reject_record_until_source_ref_added`, …) and index-based finding links don't match
  the locked enum.
- **Target (§1315–1316, §1348–1365):** validators named `validate_daily_market_snapshot`
  + `validate_critic_patches`; six schema files mirroring the six artifacts; tests assert
  validators and `.schema.json` agree on required fields/enums/`schema_version`; patch
  `operation` ∈ {replace, append_blocked_reason, downgrade_readiness, merge_duplicate,
  retire_record, mark_needs_data}, linked by `finding_id`, with `unrepaired_findings[]`.
- **Resolution:** rename validator + add `critic-patches`/`validation-findings` to
  `VALIDATORS`; author the two missing schema files; add the agreement test; remap
  critic operations to the locked enum.
- **Acceptance:** `VALIDATORS` has 6 keys; agreement test passes; a malformed
  critic-patch fails validation.

### 5.8 — Support component is dead on live data (wrong key + scalar shape) — **BLOCKER**

*(Verified against the real file — this is worse than an earlier "shape coupling" draft.)*

- **Current:** the real `data/support_eval_latest.json` has shape
  `{date, proximity_pct, opportunities: [{ticker, price, support: <float>, distance_pct, ...}]}`.
  But `daily_trend_snapshot.py:130` reads `support.get("levels", [])` — the key is
  `opportunities`, not `levels` → **zero support records from live data**. And `support`
  is a **scalar float**, while `compute_recent_edge_score` only scores support
  `if isinstance(support_level, dict)` (`trend_extractor.py:76`) → null support anyway.
  The fixture happens to supply `levels[].level` as a dict, so tests pass and mask both
  faults.
- **Impact:** the highest-weighted component (0.40) is **never populated on real data**
  today — every live `recent_edge_score` silently drops 40% of its intended evidence.
- **Target:** support component reliably populated from the real source shape.
- **Resolution:** read `opportunities` (not `levels`); map the scalar `support` +
  `distance_pct` + `price` into the dict `compute_support_level_score` expects (or adapt
  the extractor to accept the scalar form). Align the fixture to the real shape so tests
  catch this class of bug.
- **Acceptance:** a fixture using the real `opportunities`/scalar-`support` shape yields
  a non-null support component and a non-null `recent_edge_score`.

### 5.9 — Determinism caveat & minor items — **LOW**

- Artifacts embed `utc_now()` (wall clock) + `run_id`, so output is not byte-reproducible
  given identical inputs. **Resolution:** inject a fixed clock + run-id seed for tests
  (see §10). `utc_now()` uses deprecated `datetime.utcnow()` (`trend_contracts.py:67`) →
  `datetime.now(timezone.utc)`.

### 5.10 — Freshness enum is wrong (and the spec is self-contradictory) — **MEDIUM**

- **Current:** code validates `SOURCE_FRESHNESS=(fresh, stale, unknown)`
  (`trend_contracts.py:32`); fixtures use `"fresh"`.
- **Target:** the spec gives **three** different sets — Source Evidence Model §1235
  (`same_day, fresh_cache, weekly_context, stale, unknown`), the bottleneck `source_status`
  §551 (`fresh, cached, stale, partial, failed`), and root `source_quality` §1247
  (`fresh, partial, stale, failed`). These were never reconciled.
- **Resolution:** adopt the canonical enum in §6.3 and migrate code + fixtures.
- **Acceptance:** a source_ref with `same_day` validates; with `fresh` (old value) fails.

### 5.11 — `claim_field` semantics + missing `source_quote` — **MEDIUM**

- **Current:** `claim_field` holds free-text source-field names (`"universe_pass"`,
  comma-joined names); `source_quote` is not emitted anywhere.
- **Target (§1236, §1218–1227, §1291):** `claim_field` is an RFC-6901 pointer to the
  *supported record field* (`/records/0/metrics/price`); `source_quote` is a required
  human-readable evidence mirror on ledger records.
- **Resolution:** change `source_ref(...)` callers to pass the record-field pointer;
  add `source_quote` construction in the extractor/ledger.
- **Acceptance:** a record's `claim_field` resolves as a pointer into the same record;
  `source_quote` is a non-empty list mirroring the cited values.

### 5.12 — Runtime guard absent — **MEDIUM** (spec is SPECIFIED here)

- **Current:** no timing instrumentation; a run cannot self-terminate.
- **Target (§150, §1523):** 45-min target; at the 90-min hard cap, emit
  `completed_with_gaps` or `failed` with current partial artifacts and a
  `runtime_limit_exceeded` failure class in `run-status.failure_classes`.
- **Resolution:** stamp a run start time (injectable, §10); each phase checks elapsed
  vs cap; on breach, finalize run-status with the failure class + partial artifacts.
- **Acceptance:** a simulated overrun (injected clock past 90 min) yields
  `run_status ∈ {completed_with_gaps, failed}` with `runtime_limit_exceeded` recorded
  and the partial artifacts preserved.

### 5.13 — Cache-window gating not enforced — **HIGH**

- **Current:** no cache-age computation or gating; `cache_status` absent (see §5.5).
- **Target (§153–156, §1510–1518):** same-day price required for actionability;
  universe cache ≤ 3 trading days; support/wick stale-warning after 5 trading days;
  weekly-only evidence may inform score but cannot make a trend actionable.
- **Resolution (enforcement rule — see §11.7 for the resolved policy):** populate
  `cache_status[].age_trading_days` (via `trading_calendar`, §13); a record violating
  the same-day-price window cannot be `P1`/`accepted`; support > 5 trading days →
  `STALE_SOURCE_ARTIFACT` finding + downgrade; weekly-only evidence caps readiness at
  `monitor_only`.
- **Acceptance:** a fixture with 6-day-old support → record downgraded, not `accepted`;
  a weekly-only-evidence record never exceeds `monitor_only`.

### 5.14 — Duplicate same-day `stable_key` not handled — **MEDIUM**

- **Current:** no dedup; two records with the same `stable_key` would both flow to
  action planning.
- **Target (§1583, finding `DUPLICATE_OR_FRAGMENTED_TREND` §1150):** duplicates merged
  or rejected before action planning.
- **Resolution (see §11.8):** merge same-day duplicate `stable_key` records (keep the
  higher `recent_edge_score`, union `source_refs`), emit one
  `DUPLICATE_OR_FRAGMENTED_TREND` finding (severity warning, non-blocking).
- **Acceptance:** a fixture with two same-`stable_key` records → one merged ledger
  record + one warning finding; action planner sees a single action.

### 5.15 — `provider_failures` not wired to `completed_with_gaps` — **MEDIUM**

- **Current:** no provider-failure capture; partial data is invisible.
- **Target (§1281, §1585):** `provider_failures[]` recorded in the snapshot; partial
  failures that still yield ≥ 1 source-backed ledger record → run `completed_with_gaps`.
- **Resolution:** capture per-ticker/field fetch failures into `provider_failures[]`
  (§13); fold their presence into the run-status aggregate precedence (§5.6) so any
  recorded provider failure forces at least `completed_with_gaps`.
- **Acceptance:** a fixture with a provider failure on one ticker but valid records for
  others → `run_status == completed_with_gaps` and the failure appears in
  `provider_failures[]`.

---

## 6. Resolved Spec Holes — `PROPOSED — confirm`

The spec is genuinely under-specified in seven places. These are the proposed
defaults; each is a decision point you can veto. Judgment calls (not spec-derived) are
flagged.

### 6.1 — Deterministic `trend_category` classifier *(JUDGMENT CALL)*

First-match-wins precedence (house pattern, cf. `exit_review_pre_analyst` first-match
ruleset), one category per record:

`EVENT_DRIVEN_SETUP` → `SUPPORT_RETEST` → `MEAN_REVERSION_PULLBACK` →
`BREAKOUT_ACCELERATION` → `VOLATILITY_EXPANSION` → `RELATIVE_STRENGTH_ROTATION` →
`DORMANT_OR_NO_ACTION`.

Phase-1 implements only categories derivable from current snapshot fields; the rest
are gated behind §5.5 expansion and emit a `MISSING_REQUIRED_TREND`-class note rather
than a silent miss. See the derivability column in §7.

### 6.2 — Quota ranking / overflow

**Counting unit (G2):** quotas count **distinct tickers**, not `stable_key` records (a
ticker may hold several category-keyed records). The ledger keeps all records; ranking
collapses each ticker to its **best** record (max `recent_edge_score`) for quota
purposes.

Rank tickers by their best record's `recent_edge_score` desc; tie-break `priority_tier`
(P1>P2>P3>P4) then ticker alpha (deterministic). Fill: top **500** → monitored (rest
excluded, counted in `run-status.source_universe_count` vs `accepted_trend_count`); of
those, top **75** with `source_quality=fresh` → refresh-eligible; of those, top **30**
with `human_action_required` → human-review output. `quotas.used_*` counters record
actual emitted counts; promote/review actions displaced by the 30-cap are flagged
`deferred` and counted in `quotas.deferred_*`.

**Quota tier is a ceiling on the action (G3 — resolves the §11.2 ↔ §6.2 conflict):**
the quota tier caps what action a record may carry, overriding §11.2 for overflow.
Monitored-but-not-top-75 → action capped at `WATCH_DAILY`, `readiness=monitor_only`,
`monitoring_cadence=daily` (no promote/refresh even if P1-accepted). Top-75-not-top-30 →
may be `WATCH_INTRADAY`/refresh; a promote/review the §11.2 rule assigned is recorded
with `deferred=true` rather than surfaced. Top-30 → the §11.2 action stands.

### 6.3 — Canonical freshness enum

Adopt the **Source Evidence Model** 5-value set (most authoritative, lives in the
locked artifact section): `same_day, fresh_cache, weekly_context, stale, unknown`.
Keep root-summary `source_quality` as its own enum (`fresh, partial, stale, failed`).
Drop the bottleneck-section `source_status` set (it was a suggestion, §549). Document
the freshness→source_quality mapping (e.g. `same_day|fresh_cache→fresh`,
`weekly_context→partial`, `stale→stale`, `unknown`+provider failure→`failed`).

### 6.4 — `recommended_next_workflow` mapping (all 8; names verified against `workflows/`)

| Action category | `recommended_next_workflow` |
| :--- | :--- |
| WATCH_DAILY | `none` |
| WATCH_INTRADAY | `none` |
| PROMOTE_TO_SIMULATION | `sim-ranked-candidate-workflow` |
| PROMOTE_TO_DEEP_DIVE | `deep-dive-workflow` |
| ADD_TO_CANDIDATE_POOL | `none` (manual `candidate_tracker.py` per write boundary) |
| RECOMMEND_WATCHLIST_REVIEW | `watchlist-fitness-workflow` |
| COOLDOWN_OR_DROP | `none` |
| NO_CHANGE | `none` |

### 6.5 — Schema migration policy

Greenfield / pre-production: change artifact shapes (incl. the list→keyed-object
snapshot) under `SCHEMA_VERSION = 1` now. Run-history copies are immutable and never
re-loaded, so no migration is required. Policy: validators accept only the current
version; a future v2 requires a one-time migration note. (No production trend data
exists yet — confirm this is true before relying on it.)

### 6.6 — Aging / cooldown / retire + transition computation *(JUDGMENT CALL on constants)*

New constants in `trend_contracts.py`: `STALE_AFTER_DAYS` (source no longer same-day →
`stale`), `COOLDOWN_DAYS = 5` (consecutive stale runs → `retired`),
`ABSENT_AGE_OUT_DAYS = 10` (absent from snapshot N runs → `retired`). Transition rule,
computed by matching the new record against the prior ledger by `stable_key`:

| Transition | Condition |
| :--- | :--- |
| `new` | `stable_key` absent in prior ledger |
| `persisting` | present, `priority_tier` unchanged, no blocking finding |
| `upgraded` | `priority_tier` improved or `monitoring_cadence` increased |
| `downgraded` | `priority_tier` worsened or `monitoring_cadence` decreased |
| `blocked` | any blocking validation finding this run |
| `stale` | no same-day evidence (freshness ≤ `weekly_context`) |
| `retired` | stale ≥ `COOLDOWN_DAYS` runs, or absent ≥ `ABSENT_AGE_OUT_DAYS` runs |

`first_seen` carried from prior by `stable_key`; `last_seen` = today if present in
snapshot, else carried.

### 6.7 — `stable_key` anchor algorithm

`f"{ticker}:{trend_category}:{anchor}"`, anchor normalized (lowercase, floats rounded
to 2 dp, spaces stripped):

| Category | Anchor |
| :--- | :--- |
| SUPPORT_RETEST, MEAN_REVERSION_PULLBACK | `support_{level:.2f}` |
| VOLATILITY_EXPANSION, BREAKOUT_ACCELERATION | `range_{band:.2f}` |
| RELATIVE_STRENGTH_ROTATION | `sector_{sector}` |
| EVENT_DRIVEN_SETUP | `event_{date}` |
| DORMANT_OR_NO_ACTION | carry prior anchor |

---

## 7. Locked Taxonomies (reproduced inline)

### Trend categories (§1082) + trigger + source

Single full-spec scope: all 7 are in scope. Trigger conditions are resolved in §11.1;
the data source for each required input is in §13 (Field Source Map).

| Category | Required inputs (§1082) | Trigger (§11.1) / source (§13) |
| :--- | :--- | :--- |
| SUPPORT_RETEST | price, support level, distance, freshness, ladder | `\|distance\|≤3%`; support_eval `opportunities` (§5.8) |
| MEAN_REVERSION_PULLBACK | swing/consistency + current pullback measure | `daily_change≤−2%` & `swing≥10%`; live fetch + screen cache |
| RELATIVE_STRENGTH_ROTATION | improving vs sector/market/peers | ticker 5D% > sector-ETF 5D% +3pts; `market_pulse` |
| VOLATILITY_EXPANSION | range/ATR/volume expansion + liquidity/risk | `atr_pct ≥ 1.3×` 60-day avg; `bounce_analyzer.compute_rolling_atr` |
| BREAKOUT_ACCELERATION | price leaving prior range w/ confirmation | `daily_change≥+3%` & price > 20-day high; `range_reset_analyzer` |
| EVENT_DRIVEN_SETUP | earnings/news/analyst/filing/catalyst | `earnings_gate` blocked or ≤14d; `earnings_gate.check_earnings_gate` |
| DORMANT_OR_NO_ACTION | previously monitored, no current trend | in prior ledger by `stable_key`, no current match (§5.2) |

### Validation finding categories (§1126)

`UNSUPPORTED_SOURCE_CLAIM`, `STALE_SOURCE_ARTIFACT`, `DATA_PROVIDER_GAP`,
`STRATEGY_GATE_CONFLICT`, `INSUFFICIENT_RECENT_EDGE`, `DUPLICATE_OR_FRAGMENTED_TREND`,
`MISSING_REQUIRED_TREND`.

### Monitoring action categories (§1158)

`WATCH_DAILY`, `WATCH_INTRADAY`, `PROMOTE_TO_SIMULATION`, `PROMOTE_TO_DEEP_DIVE`,
`ADD_TO_CANDIDATE_POOL`, `RECOMMEND_WATCHLIST_REVIEW`, `COOLDOWN_OR_DROP`, `NO_CHANGE`.
*(Code currently emits non-spec `MONITOR`; map to `WATCH_DAILY`/`NO_CHANGE`.)*

### Ledger transition states (§1250)

`new`, `persisting`, `upgraded`, `downgraded`, `blocked`, `stale`, `retired`.

### Derived-output enums (§1238)

- `readiness`: `accepted`, `monitor_only`, `blocked`, `needs_data`, `failed` (5)
- `priority_tier`: `P1`, `P2`, `P3`, `P4` (4)
- `monitoring_cadence`: `intraday`, `daily`, `weekly`, `cooldown` (4)
- `source_quality`: `fresh`, `partial`, `stale`, `failed` (4)
- `human_action_required`: boolean
- `freshness` (per source_ref, canonical §6.3): `same_day`, `fresh_cache`,
  `weekly_context`, `stale`, `unknown` (5)

---

## 8. Dependency Graph & Sequencing

Build order (edges = "must precede"):

```
Foundation
  A. Contract surface (§5.7): rename validate_daily_market_snapshot, add
     validate_critic_patches + 2 schema files + agreement test
  B. Canonical freshness enum + claim_field/source_quote (§5.10, §5.11, §6.3)
  C. Taxonomy enums (§7) into trend_contracts.py
        │
        ▼
Snapshot expansion
  D. Keyed-by-ticker snapshot + atr/sector/earnings/cache_status/provider_failures
     + run_id format (§5.5, §5.6 run_id)   ◀── A,B,C
        │
        ├──────────────► E. Liquidity penalty formula + ±25 delta (§5.1)  ◀── D
        │
        ▼
Scoring + classification
  F. trend_category classifier (§6.1)  ◀── C,D
  G. readiness/priority_tier/missing_edge_components + all-missing finding (§5.3) ◀── C,E
        │
        ▼
Identity + state
  H. stable_key (§6.7)  ◀── F
  I. cross-run merge + transitions + aging (§5.2, §6.6)  ◀── H
        │
        ▼
Selection + lifecycle
  J. quotas + ranking/overflow (§5.4, §6.2)  ◀── G,I
  K. run-status lifecycle helper + precedence + skipped synthesis (§5.6)  ◀── A,D
        │
        ▼
  L. support-shape normalization / key fix (§5.8, BLOCKER) — fold into D
  M. determinism seams for tests (§5.9) + run_id hash + runtime guard (§5.12) — with A
Snapshot data layer (part of D)
  N. live-fetch path + field source map (§5.5, §13): reuse fetch_history / batch
     download + ATR; populate atr/sector/earnings/overlaps/cache_status/provider_failures
        │
        ▼
Behavioral layer
  O. decision-rule module (§11): classifier triggers, action selection, cadence,
     human_action_required, source_quality aggregation, blocking rules  ◀── C,N
  P. strategy-gate subsystem (§12): earnings/liquidity/price/ladder/risk-off/
     concentration/overlap → STRATEGY_GATE_CONFLICT + readiness  ◀── N
  Q. cache-window gating (§5.13), duplicate-merge (§5.14),
     provider_failures→completed_with_gaps (§5.15)  ◀── N,K
```

Critical path: **A/B/C → D(+L,N) → F → H → I → J**, with **O,P** gating readiness and
action selection once N lands. E and G branch off D in parallel; K + Q parallel the
scoring work once D lands. The new behavioral layer (O,P) is the heaviest addition —
it depends on the live-fetch fields from N, so N is now on the critical path.

---

## 9. Fixture Inventory (new fixtures the implementation must add)

| Fixture | Purpose | Tests gap |
| :--- | :--- | :--- |
| Two-run set: prior `trend-ledger.json` + new keyed snapshot | cross-run merge, `first_seen` carry, transitions | §5.2, §6.6 |
| Record with all 4 score components missing | all-missing → null/needs_data/partial + finding | §5.3 |
| >30 / >75 / >500 ticker snapshot | quota caps + overflow status + `used_*` counters | §5.4, §6.2 |
| Records with `stale` / `weekly_context` freshness | cache-window gating, `source_quality` mapping | §5.10, §6.3 |
| Keyed-by-ticker snapshot (`/tickers/ABCD/...`) | new pointer shape + RFC-6901 resolution | §5.5, §5.11 |
| Real `opportunities` + scalar `support` shape | support component populates (regression for the live-data bug) | §5.8 |
| Forced ledger-`nonconverged` run | run-status precedence + synthesized `skipped` | §5.6 |
| Per-category trigger fixtures (one per the 7 categories) | classifier first-match-wins assigns the right `trend_category` | §11.1 |
| Strategy-gate-conflict record (earnings ≤14d / low vol / overlap) | hard gate → `blocked` + `STRATEGY_GATE_CONFLICT`; soft → `monitor_only` | §12 |
| Two same-`stable_key` records, same day | merge to one + one `DUPLICATE_OR_FRAGMENTED_TREND` warning | §5.14 |
| Injected-clock overrun past 90 min | `completed_with_gaps`/`failed` + `runtime_limit_exceeded` | §5.12 |
| Provider failure on one ticker, valid others | `completed_with_gaps` + `provider_failures[]` populated | §5.15 |
| Multi-ticker end-to-end run (golden) | full snapshot→ledger→actions→report on fixed clock + seeded `run_id`; assert `daily-trend-report.md` + terminal `run-status.json` byte-for-byte | §5.6, §5.9, integration |

All fixtures should use a fixed injected clock + seeded `run_id` so artifacts are
byte-reproducible (golden-file tests).

---

## 10. Implementation Guardrails for the Eventual Plan

- **Determinism seams:** thread an injectable `now`/`run_id` (default to real
  `utc_now()`/generated id) so tests can pin them and assert golden output. Replace
  `datetime.utcnow()` with `datetime.now(timezone.utc)`. These seams enable the §9
  end-to-end **golden test** (full pipeline → byte-for-byte report + run-status).
- **Run-status precedence (§1618):** honor `failed` > `nonconverged` >
  `completed_with_gaps` > `completed`; each phase owns only its entry and synthesizes
  `skipped` downstream entries on failure. Do **not** keep rebuilding all four phases
  per tool.
- **`run_id` format (§1569):** `<as_of_date>-<HHMMSS>-<short_hash>`, not `uuid4`.
- **Workflow YAML footguns** (project memory, repeat failures) — relevant only if/when
  the approval-gated YAML is built: `decision_marker: COMPLETE` (not just CLEAN/PASS);
  shell patterns must be `python3:*` (never `python3:tools/foo.py` — the `/` fails
  validation); silent agent-validation skips → validate with
  `workflow.agent(action="validate")`.
- **Write boundary (§1639):** only `data/trend_monitoring/`; `write_effect: none`;
  candidate writes stay manual through `candidate_tracker.py`.
- **Reuse, don't duplicate:** `compute_support_level_score` (`shared_utils`),
  `candidate_tracker.AGE_OUT_DAYS` (reference for trend aging constants), the existing
  `atomic_write_*`/`copy_to_run_history`/`phase_entry` helpers in `trend_contracts.py`.

---

## 11. Deterministic Decision Rules — `PROPOSED — confirm`

The spec defines the *enums* (§7) but leaves the *rules that select among them* absent
or partial. These are the resolved defaults; all numbers are trading-sensitive judgment
calls for your sign-off (§14).

### 11.1 Classifier trigger conditions (first-match-wins; precedence in §6.1)

| Category | Trigger condition |
| :--- | :--- |
| EVENT_DRIVEN_SETUP | `earnings_gate.check_earnings_gate` blocked OR `days_to_earnings ≤ 14` (reuses earnings_gate's 14-day rule) |
| SUPPORT_RETEST | support evidence present AND `\|distance_pct\| ≤ 3.0%` |
| MEAN_REVERSION_PULLBACK | `daily_change_pct ≤ −2.0%` AND `median_swing ≥ 10%` |
| BREAKOUT_ACCELERATION | `daily_change_pct ≥ +3.0%` AND price > 20-day high |
| VOLATILITY_EXPANSION | `atr_pct ≥ 1.3×` its 60-day average |
| RELATIVE_STRENGTH_ROTATION | ticker 5D% > sector-ETF 5D% by ≥ 3 pts; **monitoring-only** unless support/entry also present (§1101) |
| DORMANT_OR_NO_ACTION | in prior ledger by `stable_key` but no current category matches |

### 11.2 Action-category selection (state → 1 of 8)

| Condition | Action |
| :--- | :--- |
| `accepted` & P1, category=EVENT_DRIVEN_SETUP | PROMOTE_TO_DEEP_DIVE |
| `accepted` & P1 (other) | PROMOTE_TO_SIMULATION |
| `accepted` & P2 | ADD_TO_CANDIDATE_POOL |
| `monitor_only`, near-trigger (distance ≤ 3% / cadence intraday) | WATCH_INTRADAY |
| `monitor_only` (other) | WATCH_DAILY |
| transition ∈ {stale, retired} | COOLDOWN_OR_DROP |
| watchlist ticker, `watchlist_fitness_delta_pct ≤ −10%` | RECOMMEND_WATCHLIST_REVIEW |
| state unchanged vs prior ledger | NO_CHANGE |

**Monitoring-only cap (G6):** `RELATIVE_STRENGTH_ROTATION` (monitoring-only, §1101) and
`BREAKOUT_ACCELERATION` ("do not chase", §1113) cap their action at `WATCH_*` regardless
of score, unless the record also carries support/entry evidence (i.e. also matches
SUPPORT_RETEST/MEAN_REVERSION).

**Quota ceiling:** this table assigns the *intended* action; the §6.2 quota tier is a
**ceiling** that can downgrade it for overflow (monitored-but-not-top-75 → `WATCH_DAILY`;
displaced promote/review → `deferred`). §6.2 wins on conflict.

### 11.3 `monitoring_cadence`

P1 or near-trigger → `intraday`; P2–P3 → `daily`; `blocked`/`needs_data` → `weekly`;
`stale`/`retired` → `cooldown`.

### 11.4 `human_action_required`

`true` when action ∈ {PROMOTE_TO_SIMULATION, PROMOTE_TO_DEEP_DIVE,
RECOMMEND_WATCHLIST_REVIEW} OR `readiness == blocked` by a hard strategy gate. (These
are exactly the records surfaced in the top-30 review quota, §6.2.)

### 11.5 Record-level `source_quality` aggregation (worst-wins)

Across the source_refs backing scored components: any provider failure on a required
field → `failed`; else oldest backing ref `stale` → `stale`; else any `weekly_context`
ref or a missing required component → `partial`; else (`same_day`/`fresh_cache` only) →
`fresh`. Freshness→quality is the mapping from §6.3.

### 11.6 Which findings block (`blocks_readiness` → `readiness=blocked`)

| Finding category | Effect |
| :--- | :--- |
| UNSUPPORTED_SOURCE_CLAIM (error) | blocks → `blocked` |
| STRATEGY_GATE_CONFLICT (hard gate, §12) | blocks → `blocked` |
| STALE_SOURCE_ARTIFACT (when stale artifact is the category's required evidence) | blocks → `blocked` |
| DATA_PROVIDER_GAP | downgrade → `needs_data`/`partial` (not blocking unless all components missing) |
| INSUFFICIENT_RECENT_EDGE | → `monitor_only` |
| DUPLICATE_OR_FRAGMENTED_TREND | warning, non-blocking (triggers merge, §5.14) |
| MISSING_REQUIRED_TREND | info |

### 11.7 Cache-window enforcement (the §5.13 policy)

Violating same-day price → record cannot be `P1`/`accepted`; support evidence > 5
trading days → `STALE_SOURCE_ARTIFACT` finding + readiness downgrade; weekly-only
evidence caps readiness at `monitor_only` (§155).

### 11.8 Duplicate merge (the §5.14 procedure)

Same-day records sharing a `stable_key`: keep the one with the higher
`recent_edge_score`, union their `source_refs`, emit one warning-severity
`DUPLICATE_OR_FRAGMENTED_TREND` finding. Different `trend_category` on the same
`stable_key` should not occur (category is part of the key) — if it does, treat as
distinct keys.

### 11.9 Minor field generation

- `detail`: deterministic template `"{CATEGORY}: {one-line evidence summary}"` (no LLM).
- `expires_after` = `as_of_date` + cadence window in trading days (intraday→1, daily→3,
  weekly→7).
- `run_id` = `<as_of_date>-<HHMMSS>-<short_hash>` where `<short_hash>` = first 8 hex of
  `sha256(canonical snapshot JSON)` (deterministic; clock + hash injectable for tests).
- First-run bootstrap: no prior ledger → every record `new`, `transitions` empty.
- `summary` (locked roots §1286/§1302/§1322), deterministic counts: `ledger.summary` =
  counts by `readiness` + `trend_category` + transition tallies; `findings.summary` =
  counts by `finding_category` + `severity`; `actions.summary` = counts by
  `action_category` (+ `deferred`).

### 11.10 Missing-component re-normalization (G1 — verified scoring bug)

`compute_recent_edge_score` currently does `sum(norm·weight)` over present components
with **no denominator**, so a record missing the 0.40 support component caps at 60 and
can never reach P2 (≥65) or P1 (≥80). Spec §212 ("excluded from the denominator")
requires re-normalization:

```
present = [c for c in components if not c.missing]
recent_edge_score = round(Σ(c.norm · c.weight for c in present) / Σ(c.weight for c in present), 2)
```

- Priority/readiness thresholds (§5.3) apply to this **re-normalized** 0–100 score.
- All-missing (`present == []`) → `null` (unchanged; §5.3 needs_data path).
- Acceptance: only-support present (norm 80, w 0.40) → **80**, not 32; all four present
  with norms [80,60,50,100] → `0.4·80+0.25·60+0.2·50+0.15·100 = 72.0` (denominator 1.0,
  unchanged for full records).

---

## 12. Strategy-Gate Subsystem (`STRATEGY_GATE_CONFLICT`) — `PROPOSED — confirm`

Entirely absent from the implementation. Each gate emits a `STRATEGY_GATE_CONFLICT`
finding; **hard** gates set `readiness=blocked`, **soft** gates downgrade to
`monitor_only` (per §1025, risk-off downgrades rather than blocks). Thresholds reuse
existing repo constants where they exist.

| Gate | Type | Rule / source |
| :--- | :--- | :--- |
| Earnings blackout | hard | `earnings_gate.check_earnings_gate` blocked (≤14d) |
| Liquidity | hard | `avg_volume < 500_000` (`MIN_AVG_VOL`) |
| Price band | hard | outside `$3–$60` (universe gates) |
| Support-ladder depth | hard (SUPPORT_RETEST only) | `< 2` active-zone levels (`KPI_STRONG_LEVELS_MIN=2`) |
| Risk-off | soft | `market_pulse` regime == "Risk-Off", non-defensive sector |
| Sector concentration | soft | ≥ 5 monitored P1/P2 already in the sector (trend-specific cap; `SECTOR_CONCENTRATION_LIMIT=999` is disabled elsewhere) |
| Portfolio/pending overlap | flag | ticker already in `portfolio.json` positions/pending_orders → set `human_action_required`, do not re-promote |

---

## 13. Field Source Map (the §5.5 snapshot expansion)

Single full-spec scope means the snapshot gains a **live-fetch path** — reuse the
existing helpers below rather than building a new fetcher. Every field's source is
verified.

| Snapshot field | Source |
| :--- | :--- |
| price, volume, avg_volume | live batch `yf.download` (reuse `surgical_screener.py:45–165`) or `data/universe_screen_cache.json` |
| atr / atr_pct | `bounce_analyzer.compute_rolling_atr(hist, 14)` (`:235`) |
| daily_change_pct | `close[-1]/close[-2]−1` from `wick_offset_analyzer.fetch_history(ticker)` (`:406`) |
| monthly_swing, consistency | `data/universe_screen_cache.json` / `surgical_screener` compute |
| sector | `sector_registry.get_sector` / `get_broad_sector` (`:201` / `:249`) |
| earnings_status | `earnings_gate.check_earnings_gate(ticker, as_of_date)` (`:81`) → `{status, days_to_earnings, blocked}` |
| support_levels | `data/support_eval_latest.json` — **read `opportunities`, scalar `support`** (§5.8) + wick cache |
| portfolio/candidate/watchlist overlap | `portfolio.json` / `data/candidates.json` / portfolio watchlist |
| cache_status.age_trading_days | `trading_calendar.py` (`is_trading_day`/`last_trading_day`, iterate between source date and `as_of`) |
| provider_failures | capture per-ticker/field `yf.download` failures (§5.15) |
| market regime (risk-off gate, §12) | `market_pulse.py` — **flag: currently prints; needs a return-dict refactor** before it can be consumed programmatically |

Reusable live-fetch / compute helpers: `wick_offset_analyzer.fetch_history` (`:406`),
`bounce_screener.py:102–169` (batch download + inline ATR), `surgical_screener.py` /
`universe_screener.py` (batch download → avg_vol/median_swing/consistency).

---

## 14. Residual Open Questions (after §6 / §11 / §12 defaults)

1. Is this commit intended as **Phase 0 scaffolding** with spec conformance deferred,
   or as a first conformant slice? Changes whether the BLOCKER/HIGH items are "bugs" or
   "not-yet."
2. Confirm §6.5: is there genuinely **no production trend data** yet (so shape changes
   need no `SCHEMA_VERSION` bump)?
3. **Sign off the `PROPOSED` numbers** (all trading-sensitive judgment calls):
   - §11.1 classifier thresholds (3% distance, −2%/+3% daily change, 1.3× ATR, 3-pt RS).
   - §11.2 action-selection cutoffs and the −10% watchlist-review trigger.
   - §12 gate thresholds (14-day earnings, 500k vol, $3–60 band, 2-level ladder, 5-per-
     sector concentration cap).
   - §6.6 aging constants (`COOLDOWN_DAYS=5`, `ABSENT_AGE_OUT_DAYS=10`) and §6.1
     classifier precedence.
4. Confirm the `market_pulse.py` return-dict refactor (§13) is in scope, since the
   risk-off gate depends on it.

---

## 15. Next Step

This is the analysis artifact (per process: analysis → plan → implement → verify). The
follow-up **implementation plan** should execute §8's order, build §9's fixtures, target
each §5 gap's acceptance criteria, and apply the resolutions in §6 (structural), §11
(decision rules), §12 (strategy gates), and §13 (field sources) — pending your sign-off
of the `PROPOSED` items listed in §14. Optionally run the `verify-analysis` skill on
this brief for an iterative verify→critic→fix pass before planning.
