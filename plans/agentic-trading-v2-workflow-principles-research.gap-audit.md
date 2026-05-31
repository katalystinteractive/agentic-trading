# Agentic Trading V2 Research Gap Audit

Source document: `plans/agentic-trading-v2-workflow-principles-research.md`

Method: `doc-gap-closure-loop` full-document blocker audit. Blockers are gaps that would prevent a competent implementer from producing a deterministic one-shot implementation plan.

## Cycle 1 Assessment

### Section Inventory

The assessed source document had these heading units before Cycle 1 edits:

| Unit | Heading | Starting Line | Status |
| --- | --- | ---: | --- |
| U01 | Scope | 5 | Needs decisions locked |
| U02 | Evidence Anchors | 22 | Needs more repo-grounding refs |
| U03 | Research Coverage Matrix | 83 | Explicitly reports unresolved gaps |
| U04 | Current Agentic-Trading Shape | 101 | Mostly grounded |
| U05 | Current Daily Capabilities | 121 | Needs schedule/runtime lock |
| U06 | Current Universe-Scale Capabilities | 137 | Needs scale target lock |
| U07 | Current Workflow Gap | 155 | Mostly grounded |
| U08 | Current Workflow Inventory | 177 | Mostly grounded |
| U09 | Current Tool Surface Map | 267 | Needs v2 entry point mapping |
| U10 | Current Artifact and Data Map | 347 | Needs v2 schema mapping |
| U11 | Current Bottlenecks and Failure Modes | 373 | Needs idempotency and write-policy closure |
| U12 | MCP Harness Principles Worth Porting | 445 | Needs reuse/import decision |
| U13 | Feasibility Judgment | 586 | Needs harness decision locked |
| U14 | V2 Conceptual Architecture | 605 | Needs exact module/tool names |
| U15 | Proposed V2 Daily Trend Workflow | 678 | Needs exact commands and schema |
| U16 | Trading-Native Contract Design | 794 | Needs exact non-prompt contract boundaries |
| U17 | Scale Architecture | 967 | Needs hard prototype numbers |
| U18 | Proposed Artifact Model | 1022 | Needs full field contracts |
| U19 | State Boundary and Write Policy | 1047 | Needs initial write rule locked |
| U20 | Migration Plan Sketch | 1100 | Needs implementer-ready file names |
| U21 | Test and Verification Strategy | 1151 | Needs concrete test files and commands |
| U22 | Risks and Required Guardrails | 1203 | Needs resolved guardrail defaults |
| U23 | Open Questions | 1226 | Contains implementation blockers |
| U24 | Decision Ledger | 1239 | Contains deferred implementation blockers |
| U25 | Initial Recommendation | 1268 | Directionally clear but not implementer-ready |

### Assessment Lenses

All units were checked against these lenses:

| Lens | Question |
| --- | --- |
| L1 | Are implementation decisions explicit enough for a one-shot plan? |
| L2 | Are local repo references and line anchors sufficient? |
| L3 | Are referenced `mcp-agents-workflow` principles mapped to trading-specific equivalents? |
| L4 | Are contracts, schemas, and artifacts deterministic? |
| L5 | Are entry points, commands, and file/module names concrete? |
| L6 | Are state, idempotency, and write boundaries safe? |
| L7 | Are scale, runtime, and scheduling assumptions bounded? |
| L8 | Are validation commands and test scope executable? |
| L9 | Are approval-sensitive prompt/persona/provider choices out of scope or explicitly gated? |
| L10 | Are open questions non-blocking? |

### Coverage Matrix

| Unit | Lenses Applied | Result |
| --- | --- | --- |
| U01 | L1-L10 | Blocked by undefined market-beat objective and daily scale target. |
| U02 | L1-L10 | Partial: enough `mcp` anchors, missing trading repo anchors for write and validation safety. |
| U03 | L1-L10 | Blocked: matrix itself says hardening is incomplete. |
| U04 | L1-L10 | Pass with minor grounding needs. |
| U05 | L1-L10 | Blocked by no exact daily schedule/runtime expectation. |
| U06 | L1-L10 | Blocked by unresolved monitored-universe cap. |
| U07 | L1-L10 | Pass directionally; depends on later contract closure. |
| U08 | L1-L10 | Pass as inventory; no blocker. |
| U09 | L1-L10 | Blocked by no exact v2 tool surface. |
| U10 | L1-L10 | Blocked by missing artifact field-level schemas. |
| U11 | L1-L10 | Blocked by missing rerun/idempotency semantics. |
| U12 | L1-L10 | Blocked by no harness-import decision. |
| U13 | L1-L10 | Blocked by no copy-vs-reuse decision. |
| U14 | L1-L10 | Blocked by conceptual architecture without module boundaries. |
| U15 | L1-L10 | Blocked by insufficient phase input/output contracts. |
| U16 | L1-L10 | Blocked by schema-source evidence and approval-boundary ambiguity. |
| U17 | L1-L10 | Blocked by soft scale language. |
| U18 | L1-L10 | Blocked by artifact names without field contracts. |
| U19 | L1-L10 | Blocked by unresolved write allowance. |
| U20 | L1-L10 | Blocked by migration steps without exact files. |
| U21 | L1-L10 | Blocked by no exact validation commands. |
| U22 | L1-L10 | Partial: risks clear, default guardrails need locking. |
| U23 | L1-L10 | Blocked: open questions are implementation prerequisites. |
| U24 | L1-L10 | Blocked: decision ledger defers required decisions. |
| U25 | L1-L10 | Partial: recommendation must incorporate locked decisions. |

### Blocker Ledger

| ID | Severity | Source Evidence | Gap |
| --- | --- | --- | --- |
| GAP-001 | Blocker | `Scope` lines 14-15; `Open Questions` lines 1228-1230; `Decision Ledger` lines 1243-1245 | "Recent market beat" is undefined, so scoring and validation cannot be implemented deterministically. |
| GAP-002 | Blocker | `Research Coverage Matrix` line 94; `Feasibility Judgment` lines 588-590; `Migration Plan Sketch` lines 1121-1123 | Harness reuse/import decision is unresolved. |
| GAP-003 | Blocker | `Trading-Native Contract Design` lines 911-938 | Source evidence mechanism is unresolved. |
| GAP-004 | Blocker | `Proposed V2 Daily Trend Workflow` lines 720-728; `Proposed Artifact Model` lines 1026-1035; `Trading-Native Contract Design` lines 942-950 | Schemas are examples rather than field-level contracts. |
| GAP-005 | Blocker | `Migration Plan Sketch` lines 1102-1149 | Entry points and module names are generic. |
| GAP-006 | Blocker | No dedicated section | Resume, rerun, idempotency, and failure semantics are missing. |
| GAP-007 | Blocker | `Proposed V2 Daily Trend Workflow` lines 715-716; `Scale Architecture` lines 971-979 and 1006-1014; `Open Questions` line 1235 | Scale, runtime, and schedule values are vague. |
| GAP-008 | Blocker | `Test and Verification Strategy` lines 1151-1201 | Validation scenarios lack exact test files and commands. |
| GAP-009 | Blocker | `State Boundary and Write Policy` lines 1060-1066 | Initial write policy leaves candidate/portfolio mutation unresolved. |
| GAP-010 | Blocker | `Research Coverage Matrix` lines 88-99 | Matrix explicitly states unresolved hardening details. |
| GAP-011 | Blocker | `Trading-Native Contract Design` lines 796-798 | Approval-sensitive prompt/persona contract scope is not locked. |
| GAP-012 | Blocker | `Evidence Anchors` and current repo sections | Trading repo grounding lacks code refs for candidate writes, state safety, artifact validation, promotion, and support scoring. |

### Gap-To-Fix Map

| Gap | Required Fix |
| --- | --- |
| GAP-001 | Add a locked operational definition of market-beat analogue and initial scoring objective. |
| GAP-002 | Add a locked decision to copy principles into a local trading-native mini harness first, not import the full runtime. |
| GAP-003 | Lock JSON Pointer `source_refs` as primary evidence and define citation shape. |
| GAP-004 | Add field-level schema contracts for daily snapshot, trend ledger, validation finding, critic patch, monitoring action, and run status. |
| GAP-005 | Add exact proposed v2 modules, tools, config files, and workflow YAML names. |
| GAP-006 | Add resume/idempotency/failure semantics. |
| GAP-007 | Lock prototype scale, runtime, schedule, cache windows, and cap values. |
| GAP-008 | Add exact unit/integration/smoke validation commands. |
| GAP-009 | Lock initial allowed writes to `data/trend_monitoring/*` and prohibit automatic `data/candidates.json` or portfolio writes. |
| GAP-010 | Update research coverage matrix after fixes. |
| GAP-011 | Define initial contract as code/data schema only; prompt/persona/provider changes require separate approval. |
| GAP-012 | Add additional existing repo evidence references with line anchors. |

### Cleanup List

| Item | Action |
| --- | --- |
| Ambiguous "should decide" language | Replace with locked choices where it affects implementation. |
| Open questions that are blockers | Convert to decisions or mark as explicitly deferrable. |
| Soft scale values | Replace with prototype defaults and later tuning knobs. |
| Missing command names | Add exact filenames and CLI examples. |

## Cycle 1 Plan

1. Patch the source document with a "Locked Implementation Decisions" section.
2. Expand evidence anchors with existing repo code refs for candidate writes, portfolio safety, artifact validation/promotion, and support scoring.
3. Add v2 entry-point and workflow file names.
4. Add complete schema contracts and source-evidence contract.
5. Add resume, idempotency, write-boundary, scale, and runtime defaults.
6. Replace blocker open questions with deferrable questions.
7. Add concrete validation commands.
8. Run line-number and content validation after edits.

## Cycle 1 Edits

Cycle 1 changed the source document as follows:

| Gap | Edit Evidence |
| --- | --- |
| GAP-001 | Added `recent_edge_score` market-beat analogue and weights at source lines 123-136 and locked it in the decision ledger at lines 1516-1520. |
| GAP-002 | Locked the local minimal harness decision at lines 137-142 and 1525-1527. |
| GAP-003 | Locked `source_refs` JSON Pointers as primary evidence at lines 1032-1043. |
| GAP-004 | Added field-level artifact schemas at lines 1072-1144. |
| GAP-005 | Added exact modules, tools, schema paths, workflow name, and CLI shape at lines 743-769 and 1326-1385. |
| GAP-006 | Added resume/idempotency/failure semantics at lines 1237-1265. |
| GAP-007 | Locked scale and runtime defaults at lines 147-153, 802-812, and 1148-1203. |
| GAP-008 | Added exact validation commands at lines 1439-1475. |
| GAP-009 | Locked initial writes to `data/trend_monitoring/*` and prohibited automatic candidate/watchlist/portfolio/trade writes at lines 1267-1303. |
| GAP-010 | Updated the research coverage matrix to locked implementation decisions at lines 103-121. |
| GAP-011 | Locked initial contracts to Python enums, JSON schemas, and deterministic tests at lines 162-164. |
| GAP-012 | Added repo evidence anchors for candidate tracker, portfolio manager, artifact validator/promoter, and support scoring at lines 55-75. |

## Cycle 1 Validation

Commands run:

```bash
rg -n "Hardening should decide|Needs user decisions|Potentially allowed|Blocking Before Implementation|likely 300-800|Needs exact|Remaining hardening concern|copy, adapt, or build" plans/agentic-trading-v2-workflow-principles-research.md plans/agentic-trading-v2-workflow-principles-research.gap-audit.md
rg -n "^## |^### " plans/agentic-trading-v2-workflow-principles-research.md
rg -n "trend_contracts|daily_trend_snapshot|trend_phase_ledger|recent_edge_score|source_refs|run-status|run_id|500|45 minutes|90 minutes|data/candidates.json" plans/agentic-trading-v2-workflow-principles-research.md
rg -n "[^\x00-\x7F]" plans/agentic-trading-v2-workflow-principles-research.md plans/agentic-trading-v2-workflow-principles-research.gap-audit.md
```

Results:

- unresolved-blocker phrase scan found no matches in the source document; matches were only the pre-edit audit inventory;
- heading inventory showed the source document now includes `Locked Implementation Decisions`, `Initial V2 Module and Entry-Point Map`, `Locked Artifact Schemas`, `Resume, Idempotency, and Failure Semantics`, and `Exact Initial Validation Commands`;
- targeted term scan found the locked tool names, score, source evidence, run status, runtime caps, scale caps, and candidate-write boundary;
- ASCII scan returned no non-ASCII characters.

Post-edit new-gap pass:

| Check | Result |
| --- | --- |
| Did edits introduce implementation scope beyond research? | No; source line 18 still states no runtime workflow changes, provider/model changes, persona rewrites, or live trading-state mutations are approved. |
| Did edits create automatic candidate or portfolio mutation? | No; source lines 1267-1303 restrict automatic writes to `data/trend_monitoring/*` and forbid candidate/watchlist/portfolio/trade writes. |
| Did edits require full `mcp-agents-workflow` import? | No; source lines 137-142 and 1525-1527 lock a local minimal harness. |
| Did edits leave blocking decisions in Open Questions? | No; source lines 1501-1512 mark open questions as deferrable. |

## Cycle 2 Assessment

Fresh full-document assessment after Cycle 1 edits.

### Section Inventory

| Unit | Heading | Starting Line | Status |
| --- | --- | ---: | --- |
| U01 | Scope | 5 | Pass |
| U02 | Evidence Anchors | 22 | Pass |
| U03 | Research Coverage Matrix | 103 | Pass |
| U04 | Locked Implementation Decisions | 123 | Pass |
| U05 | Current Agentic-Trading Shape | 166 | Pass |
| U06 | Current Daily Capabilities | 186 | Pass |
| U07 | Current Universe-Scale Capabilities | 202 | Pass |
| U08 | Current Workflow Gap | 220 | Pass |
| U09 | Current Workflow Inventory | 242 | Pass |
| U10 | Daily Operations Workflows | 249 | Pass |
| U11 | Candidate and Watchlist Workflows | 281 | Pass |
| U12 | Position and Review Workflows | 305 | Pass |
| U13 | Backtest Workflows | 323 | Pass |
| U14 | Current Tool Surface Map | 332 | Pass |
| U15 | Live State and Safety Tools | 336 | Pass |
| U16 | Market Data and Feature Tools | 349 | Pass |
| U17 | Support, Wick, and Bullet Tools | 360 | Pass |
| U18 | Candidate Discovery and Ranking Tools | 372 | Pass |
| U19 | Learned Graph Policy and Artifact Validation Tools | 384 | Pass |
| U20 | Backtest, Calibration, and Performance Tools | 399 | Pass |
| U21 | Current Artifact and Data Map | 412 | Pass |
| U22 | Current Bottlenecks and Failure Modes | 438 | Pass |
| U23 | Weekly Cadence Bottleneck | 440 | Pass |
| U24 | Top-N Narrowing Bottleneck | 451 | Pass |
| U25 | Report-Only Output Bottleneck | 464 | Pass |
| U26 | Expensive Sweep Bottleneck | 471 | Pass |
| U27 | Data Provider and Cache Staleness Bottleneck | 484 | Pass |
| U28 | Automatic Write Risk | 500 | Pass |
| U29 | MCP Harness Principles Worth Porting | 510 | Pass |
| U30 | Source Universe First | 515 | Pass |
| U31 | Phase-Specific Category Contracts | 529 | Pass |
| U32 | Producer, Verifier, Critic Loop | 547 | Pass |
| U33 | Derived Outputs Are Manager-Owned | 562 | Pass |
| U34 | Subscribed Phase Outputs | 579 | Pass |
| U35 | Explicit Convergence and Failure Reporting | 593 | Pass |
| U36 | Role Capability Boundaries | 619 | Pass |
| U37 | Manager-Owned IDs and Patch Semantics | 630 | Pass |
| U38 | Principle-to-Trading Mapping | 637 | Pass |
| U39 | Feasibility Judgment | 651 | Pass |
| U40 | V2 Conceptual Architecture | 670 | Pass |
| U41 | Layer 1: Source Collection | 675 | Pass |
| U42 | Layer 2: Trend Extraction | 690 | Pass |
| U43 | Layer 3: Validation and Contract Enforcement | 704 | Pass |
| U44 | Layer 4: Monitoring Action Planning | 717 | Pass |
| U45 | Layer 5: Reporting and Human Review | 730 | Pass |
| U46 | Initial V2 Module and Entry-Point Map | 743 | Pass |
| U47 | Proposed V2 Daily Trend Workflow | 771 | Pass |
| U48 | Workflow Name | 773 | Pass |
| U49 | Phase 1: Build Daily Market Snapshot | 777 | Pass |
| U50 | Phase 2: Extract Trend Candidates | 802 | Pass |
| U51 | Phase 3: Validate Strategy Fit | 828 | Pass |
| U52 | Phase 4: Plan Monitoring Actions | 850 | Pass |
| U53 | Phase 5: Daily Reporting Slice | 873 | Pass |
| U54 | Trading-Native Contract Design | 889 | Pass |
| U55 | Trend Extraction Categories | 895 | Pass |
| U56 | Validation Finding Categories | 939 | Pass |
| U57 | Monitoring Action Categories | 971 | Pass |
| U58 | Source Evidence Model | 1006 | Pass |
| U59 | Derived Outputs | 1045 | Pass |
| U60 | Ledger Status Transitions | 1057 | Pass |
| U61 | Locked Artifact Schemas | 1072 | Pass |
| U62 | Scale Architecture | 1146 | Pass |
| U63 | Universe Tiers | 1148 | Pass |
| U64 | Daily Runtime Strategy | 1160 | Pass |
| U65 | Sharding and Batching | 1172 | Pass |
| U66 | Cache Policy | 1183 | Pass |
| U67 | Cost Control | 1205 | Pass |
| U68 | Proposed Artifact Model | 1211 | Pass |
| U69 | Resume, Idempotency, and Failure Semantics | 1237 | Pass |
| U70 | State Boundary and Write Policy | 1267 | Pass |
| U71 | Allowed Automatic Writes | 1269 | Pass |
| U72 | Forbidden Automatic Writes | 1294 | Pass |
| U73 | Human Approval Boundary | 1305 | Pass |
| U74 | Migration Plan Sketch | 1326 | Pass |
| U75 | Slice 1: Trend Ledger Data Contract | 1328 | Pass |
| U76 | Slice 2: Daily Snapshot Builder | 1335 | Pass |
| U77 | Slice 3: Mechanical Trend Extractor | 1342 | Pass |
| U78 | Slice 4: Verifier/Critic Harness | 1348 | Pass |
| U79 | Slice 5: Monitoring Actions | 1355 | Pass |
| U80 | Slice 6: Workflow Integration | 1362 | Pass |
| U81 | Slice 7: Report Integration | 1368 | Pass |
| U82 | Slice 8: Promotion Gates | 1373 | Pass |
| U83 | Test and Verification Strategy | 1387 | Pass |
| U84 | Contract Tests | 1389 | Pass |
| U85 | Snapshot Builder Tests | 1397 | Pass |
| U86 | Trend Extractor Tests | 1405 | Pass |
| U87 | Validation Tests | 1414 | Pass |
| U88 | Workflow/Harness Tests | 1423 | Pass |
| U89 | Regression Tests | 1431 | Pass |
| U90 | Exact Initial Validation Commands | 1439 | Pass |
| U91 | Risks and Required Guardrails | 1478 | Pass |
| U92 | Open Questions | 1501 | Pass |
| U93 | Decision Ledger | 1514 | Pass |
| U94 | Locked For First Implementation Planning | 1516 | Pass |
| U95 | Deferrable Until After Prototype | 1530 | Pass |
| U96 | Explicit Non-Goals For First Implementation | 1538 | Pass |
| U97 | Initial Recommendation | 1546 | Pass |

### Coverage Matrix

The same L1-L10 lens set from Cycle 1 was applied to every Cycle 2 section unit.

| Unit Range | L1 Decisions | L2 Repo Evidence | L3 MCP Mapping | L4 Contracts | L5 Entry Points | L6 State Safety | L7 Scale Runtime | L8 Validation | L9 Approval Gates | L10 Open Questions |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| U01-U04 | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
| U05-U28 | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
| U29-U39 | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
| U40-U53 | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
| U54-U61 | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
| U62-U73 | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
| U74-U90 | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
| U91-U97 | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass |

### Blocker Ledger

No blocker gaps remain.

| Former Gap | Status | Closure Evidence |
| --- | --- | --- |
| GAP-001 | Closed | `recent_edge_score` locked at source lines 123-136 and 1516-1520. |
| GAP-002 | Closed | Local minimal harness locked at source lines 137-142 and 1525-1527. |
| GAP-003 | Closed | JSON Pointer source evidence locked at source lines 1032-1043. |
| GAP-004 | Closed | Artifact schemas locked at source lines 1072-1144. |
| GAP-005 | Closed | V2 file/CLI/workflow map locked at source lines 743-769 and 1326-1385. |
| GAP-006 | Closed | Idempotency/failure semantics locked at source lines 1237-1265. |
| GAP-007 | Closed | Scale/runtime/cache defaults locked at source lines 147-156 and 1148-1203. |
| GAP-008 | Closed | Validation commands locked at source lines 1439-1475. |
| GAP-009 | Closed | Write boundary locked at source lines 1267-1303. |
| GAP-010 | Closed | Coverage matrix updated at source lines 103-121. |
| GAP-011 | Closed | Approval boundary locked at source lines 162-164. |
| GAP-012 | Closed | Additional repo evidence anchors added at source lines 55-75. |

### Cleanup List

No cleanup items remain before implementation planning.

## Cycle 2 Plan

No source-document edits are required. The next artifact can be a one-shot
implementation plan derived from the hardened research document.

## Cycle 2 Edits

None.

## Cycle 2 Validation

Cycle 2 performed no edits and therefore satisfies the loop rule that convergence
must be declared only after a fresh no-edit assessment.

## Final Convergence Check

Final readiness proof:

- source document has locked first-implementation decisions for market-beat
  scoring, harness reuse, schedule, scale, runtime, cache windows, write
  boundaries, and approval boundaries;
- source document has exact proposed tool files, workflow file, schema directory,
  and CLI smoke commands;
- source document has field-level schemas for the primary V2 artifacts;
- source document has resume/idempotency/failure semantics;
- source document has no blocking open questions;
- audit blocker ledger is closed with line evidence;
- no source-document edits were made in Cycle 2.

Conclusion: the research document is ready to harden into a one-shot
implementation plan.

## Cycle 3 Assessment

Fresh follow-up assessment found seven remaining one-shot implementation-plan
gaps:

| ID | Severity | Gap |
| --- | --- | --- |
| GAP-013 | Blocker | Validation commands referenced `tests/test_portfolio_manager.py`, which does not exist; candidate-tracker test ownership was unclear. |
| GAP-014 | Blocker | Schema coverage was inconsistent: six artifacts were named, but only three schema files were assigned to migration slices. |
| GAP-015 | Blocker | Contract names drifted between `record_type` and `trend_category`, and between cooldown action labels. |
| GAP-016 | Blocker | Source pointer examples used keyed ticker paths while the snapshot schema described `tickers[]` as an array. |
| GAP-017 | Blocker | `recent_edge_score` lacked score range, normalization, missing-component handling, and readiness/priority thresholds. |
| GAP-018 | Blocker | Workflow YAML was not concrete enough to preserve the existing repo workflow style. |
| GAP-019 | Blocker | Fixture directory and scenario requirements were not defined. |

## Cycle 3 Plan

1. Correct validation commands and explicitly distinguish new V2 tests from existing regression tests.
2. Replace wildcard schema references with the exact six schema files and assign all six to migration slices.
3. Normalize contract names to `trend_category`, `DORMANT_OR_NO_ACTION`, and `COOLDOWN_OR_DROP`.
4. Lock `daily-market-snapshot.json` `tickers` as an object keyed by ticker and update source pointer examples.
5. Add implementable `recent_edge_score` rules.
6. Add exact workflow YAML structure with phase IDs, agents, artifacts, dependencies, requirements, and timeouts.
7. Add fixture layout and required scenarios.

## Cycle 3 Edits

| Gap | Closure Evidence |
| --- | --- |
| GAP-013 | Validation command now uses `tests/test_portfolio_manager_safety.py` and states that `tests/test_candidate_tracker.py` must be created if included; source lines 1596-1635. |
| GAP-014 | Exact schema files are listed in the module map and migration slices; source lines 781-786 and 1458-1495. |
| GAP-015 | Phase example now uses `trend_category`, category contracts use `DORMANT_OR_NO_ACTION`, and action names use `COOLDOWN_OR_DROP`; source lines 558-566, 923, and 983. |
| GAP-016 | Source refs and snapshot schema now use stable keyed ticker pointers such as `/tickers/ABCD/price`; source lines 1128-1169 and 1208-1212. |
| GAP-017 | `recent_edge_score` normalization, missing-component handling, and thresholds are locked; source lines 166-185. |
| GAP-018 | Workflow YAML contract is concrete and follows existing repo style; source lines 803-878. |
| GAP-019 | Fixture layout and scenario list are defined; source lines 1573-1594. |

## Cycle 3 Validation

Planned validation commands:

```bash
rg -n "record_type|COOLDOWN\b|tests/test_portfolio_manager.py|tickers\[\]|\*\.schema\.json" plans/agentic-trading-v2-workflow-principles-research.md
rg -n "daily-market-snapshot.schema.json|validation-findings.schema.json|critic-patches.schema.json|run-status.schema.json|recent_edge_score|missing_edge_components|tests/fixtures/trend_monitoring|daily-trend-monitoring-workflow" plans/agentic-trading-v2-workflow-principles-research.md
test -f tests/test_portfolio_manager_safety.py
rg -n "[^\x00-\x7F]" plans/agentic-trading-v2-workflow-principles-research.md plans/agentic-trading-v2-workflow-principles-research.gap-audit.md
```

Cycle 3 post-edit check found no new implementation-scope expansion: provider,
model, persona, prompt, candidate, portfolio, and trade-state changes remain
explicitly out of scope.

## Cycle 4 Assessment

Fresh no-edit assessment after Cycle 3 edits:

| Lens | Result |
| --- | --- |
| Validation reproducibility | Pass: commands distinguish new V2 tests from existing regression tests. |
| Schema completeness | Pass: all six primary artifact schemas are named and assigned. |
| Contract naming consistency | Pass: first-implementation category/action names are consistent. |
| Source evidence determinism | Pass: keyed ticker source refs are stable. |
| Score/action determinism | Pass: score range, normalization, missing data, priority, and readiness thresholds are locked. |
| Workflow handoff | Pass: YAML contract follows current repo fields and does not invent a runner command field. |
| Fixture reproducibility | Pass: fixture files and scenarios are named. |

No blocker gaps remain.

## Cycle 4 Plan

No source-document edits are required.

## Cycle 4 Edits

None.

## Cycle 4 Validation

Cycle 4 performed no edits and therefore satisfies the no-edit convergence rule.

## Final Convergence Check

Final readiness proof:

- all previously identified follow-up gaps are closed with source-line evidence;
- implementation-plan validation commands no longer name a missing portfolio test;
- schema, enum, source pointer, scoring, workflow YAML, and fixture contracts are
  decision complete;
- no Cycle 4 edits were needed.

Conclusion: the research document is again ready to produce a one-shot
implementation plan.

## Cycle 5 Assessment

Fresh follow-up assessment found five remaining blockers for a one-shot
implementation plan.

### Section Inventory

The full current document inventory was rechecked from `Scope` through `Initial
Recommendation`. The blocker-relevant units were:

| unit_id | section/title | unit type | implementation relevance |
| --- | --- | --- | --- |
| U04 | Locked Implementation Decisions / Locked `recent_edge_score` Rules | locked decision list | Defines score behavior used by ranking and action planning |
| U46 | Initial V2 Module and Entry-Point Map | table and CLI examples | Defines files, workflow agents, schema files, and tool entry points |
| U49 | Workflow YAML Contract | YAML example | Defines workflow integration shape |
| U61 | Locked Artifact Schemas | schema field lists | Defines artifact contracts |
| U62 | Schema Validation Mechanism | missing section before edit | Needed to lock validator dependency and helper behavior |
| U75 | Slice 1: Trend Ledger Data Contract | migration slice | Needed to lock schema/version helper ownership |
| U80 | Slice 6: Workflow Integration | migration slice | Needed to lock workflow agent-file requirements |
| U90 | Exact Initial Validation Commands | command list | Needed to avoid dirty smoke output and conditional tests |

All other heading sections were rechecked against the same lenses and had no new
blocker gaps.

### Coverage Matrix

| unit_id | lens | status | evidence |
| --- | --- | --- | --- |
| U04 | implementation decision completeness | gap found | Score formulas were weighted but component normalization was not fully defined. |
| U46 | runtime entry points and data flow | gap found | CLI examples lacked `--output-dir`; workflow agent files were not named. |
| U49 | repo grounding | gap found | YAML agents had no corresponding `.workflow/agents/*.md` requirement. |
| U61 | schema/helper/API semantics | gap found | Schema files were named but validation mechanism and dependency policy were not locked. |
| U62 | schema/helper/API semantics | gap found | No validation-mechanism section existed before the edit. |
| U75 | implementation planner handoff readiness | gap found | `SCHEMA_VERSION` and validator ownership were not named. |
| U80 | approval boundaries | gap found | Agent-file instructions were not constrained to deterministic command behavior. |
| U90 | validation commands and acceptance criteria | gap found | Smoke commands wrote to production output paths and candidate test was conditional. |

### Blocker Gap Ledger

| gap_id | severity | unit_id | lens | evidence | why blocker | planned fix | closure evidence | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GAP-020 | blocker | U04 | implementation decision completeness | `recent_edge_score` had weights and thresholds but no exact component formulas | Planner would invent scoring conversions | Add exact support, return, fitness, and liquidity/freshness formulas | Source lines 170-183 | closed |
| GAP-021 | blocker | U61/U62/U75 | schema/helper/API semantics | Schema files existed, but validation mechanism and dependency choice were not locked | Planner would choose between local validation, `jsonschema`, or `pydantic` | Add local Python validation policy, `SCHEMA_VERSION = 1`, helper names, and no-new-dependency rule | Source lines 1296-1311 | closed |
| GAP-022 | blocker | U46/U49/U80 | runtime entry points and repo grounding | Workflow YAML named new agents without agent-file requirements | Workflow plan could omit required `.workflow/agents` files | Add four agent instruction files and command-only constraints | Source lines 793-796 and 1533-1540 | closed |
| GAP-023 | blocker | U46/U90 | validation commands and workspace safety | Smoke commands wrote to `data/trend_monitoring/*` | Smoke run could dirty local operational/generated state | Add `--output-dir` and temp smoke directory | Source lines 807-814 and 1662-1666 | closed |
| GAP-024 | blocker | U90 | validation commands | `tests/test_candidate_tracker.py` remained conditional while command required it | Plan could produce a failing validation command | Make candidate tracker test mandatory and define coverage | Source lines 1673-1679 | closed |

### Gap-To-Fix Map

| gap_id | target unit | exact decision to lock | edit summary | validation check |
| --- | --- | --- | --- | --- |
| GAP-020 | U04 | Exact `recent_edge_score` formulas | Add support, return, fitness, and liquidity/freshness formulas | Search for `support component` and `50 + clamp` |
| GAP-021 | U61/U62/U75 | Local Python validation, no new dependency | Add schema validation mechanism section | Search for `SCHEMA_VERSION = 1` and helper names |
| GAP-022 | U46/U80 | Four workflow agent files required | Add agent files to module map and migration slice | Search for `trend-snapshot-builder.md` |
| GAP-023 | U46/U90 | Smoke output uses temp dir | Add `--output-dir` and `/tmp/agentic-trading-trend-monitoring-smoke` | Search for `/tmp/agentic-trading-trend-monitoring-smoke` |
| GAP-024 | U90 | Candidate tracker test required | Remove conditional wording and define coverage | Search for `tests/test_candidate_tracker.py` |

### Cleanup List

| item_id | unit_id | issue | optional fix |
| --- | --- | --- | --- |
| CLEAN-001 | U90 | Validation grep in the plan needed to distinguish production workflow paths from smoke output paths | Use targeted validation scans |

## Cycle 5 Plan

1. Add concrete `recent_edge_score` formulas to the locked scoring rules.
2. Add a schema validation mechanism section that locks local Python validators,
   `SCHEMA_VERSION = 1`, helper names, and no new `jsonschema`/`pydantic`
   dependency for first implementation.
3. Add required `.workflow/agents/trend-*.md` files to the module map and workflow
   integration slice.
4. Add `--output-dir` to CLI examples and convert smoke commands to a temp output
   directory.
5. Make `tests/test_candidate_tracker.py` mandatory and define its required
   coverage.

## Cycle 5 Edits

| gap_id | closure evidence |
| --- | --- |
| GAP-020 | Source lines 170-183 define exact component formulas and clamps. |
| GAP-021 | Source lines 1296-1311 define local Python validation, `SCHEMA_VERSION = 1`, helper names, and no new `jsonschema`/`pydantic` dependency. |
| GAP-022 | Source lines 793-796 name the four agent files; lines 1533-1540 constrain agent behavior. |
| GAP-023 | Source lines 807-814 add `--output-dir`; lines 1662-1666 route smoke outputs to `/tmp/agentic-trading-trend-monitoring-smoke`. |
| GAP-024 | Source lines 1673-1679 require `tests/test_candidate_tracker.py` and define its coverage. |

## Cycle 5 Validation

Commands run:

```bash
rg -n 'support component|post-signal or simulation component|fitness component|liquidity/freshness component|SCHEMA_VERSION = 1|validate_daily_market_snapshot|trend-snapshot-builder.md|--output-dir|/tmp/agentic-trading-trend-monitoring-smoke|tests/test_candidate_tracker.py|jsonschema|pydantic' plans/agentic-trading-v2-workflow-principles-research.md
rg -n 'if candidate-pool safety is included|tests/test_portfolio_manager.py|normalized to `0.0` to `100.0` before weighting' plans/agentic-trading-v2-workflow-principles-research.md
rg -n '^## |^### ' plans/agentic-trading-v2-workflow-principles-research.md
```

Results:

- Required locked decisions were present.
- No conditional candidate-test wording or obsolete portfolio test path remained.
- The `jsonschema` and `pydantic` matches were in the explicit no-new-dependency
  sentence, not a dependency requirement.

Post-Edit New-Gap Pass:

| changed unit | checked against | result | new gap id |
| --- | --- | --- | --- |
| U04 | score determinism | formulas now deterministic | none |
| U46 | runtime entry points | production and smoke output paths are distinct | none |
| U61/U62 | schema validation | dependency and helper ownership are locked | none |
| U80 | approval boundaries | agent files are command-only and deterministic | none |
| U90 | validation commands | required tests and temp smoke output are explicit | none |

## Cycle 6 Assessment

Fresh no-edit full-document assessment after Cycle 5 edits.

### Section Inventory

All deterministic document units from the current heading inventory were assessed:
Scope, Evidence Anchors, Research Coverage Matrix, Locked Implementation
Decisions, all current-state sections, all MCP principle sections, Feasibility
Judgment, V2 Conceptual Architecture, module/entry-point map, workflow contract,
daily trend phases, trading-native contracts, source evidence model, derived
outputs, ledger transitions, locked artifact schemas, schema validation
mechanism, scale architecture, artifact model, resume/idempotency semantics,
state/write policy, migration slices, test strategy, fixture contract, validation
commands, risks, open questions, decision ledger, and initial recommendation.

### Coverage Matrix

| lens | status | evidence |
| --- | --- | --- |
| implementation decision completeness | checked | Score formulas, schema validation, agents, smoke output, and candidate tests are locked. |
| runtime entry points and data flow | checked | Tool CLIs, workflow YAML, output dirs, and agent files are named. |
| schema, field, helper, artifact, and API semantics | checked | Six schemas plus Python validator helpers are defined. |
| edge cases, failure behavior, resume behavior, and idempotency | checked | Existing failure/idempotency sections remain intact and no new contradictions were introduced. |
| validation commands, test scenarios, and acceptance criteria | checked | Required V2 tests, candidate tracker test, fixtures, smoke, and safety commands are named. |
| repo grounding for runtime claims | checked | Agent-file convention, pytest config, ignored data outputs, and current tests were inspected before edits. |
| approval boundaries and out-of-scope slices | checked | Provider/model/persona/prompt changes remain out of scope. |
| contradictions between sections | checked | Names remain aligned: `trend_category`, `DORMANT_OR_NO_ACTION`, `COOLDOWN_OR_DROP`, keyed ticker pointers. |
| vague wording hiding implementation choices | checked | Remaining open questions are explicitly deferrable. |
| implementation planner handoff readiness | checked | No blocker gaps remain. |

### Blocker Gap Ledger

All prior gaps GAP-001 through GAP-024 are closed. No new blocker gaps remain.

### Cleanup List

No cleanup findings block implementation planning.

## Cycle 6 Plan

No source-document edits are required.

## Cycle 6 Edits

None.

## Cycle 6 Validation

Cycle 6 performed no edits and therefore satisfies the no-edit convergence rule.

## Final Convergence Check

Final Readiness Proof:

| category | status | evidence |
| --- | --- | --- |
| runtime entry points and data flow | ready | Tool CLIs, workflow YAML, output dirs, and agent files are named in source lines 793-814 and 1533-1540. |
| schema, fields, interfaces, helpers, and artifacts | ready | Six schemas and local Python validator helpers are locked in source lines 781-786 and 1296-1311. |
| edge cases and failure behavior | ready | Existing validation, provider failure, and nonconvergence behavior remains intact. |
| resume behavior and idempotency | ready | Existing resume/idempotency section remains unchanged and compatible with output-dir changes. |
| validation commands, test scenarios, and acceptance criteria | ready | Fixture, smoke, candidate tracker, and safety checks are specified in source lines 1613-1679. |
| repo grounding | ready | Agent-file, pytest, and ignore conventions were inspected before the edits. |
| approval boundaries | ready | No provider/model/persona/prompt changes are approved. |
| out-of-scope boundaries | ready | Candidate, portfolio, trade-history, broker, and live-state writes remain excluded. |

Conclusion: the research document is ready for a one-shot implementation plan.

## Cycle 7 Assessment

Fresh follow-up assessment found five remaining blockers for a one-shot
implementation plan.

### Section Inventory

The full document was re-inventoried from `Scope` through `Initial
Recommendation`. The blocker-relevant units were:

| unit_id | section/title | unit type | implementation relevance |
| --- | --- | --- | --- |
| U04 | Locked `recent_edge_score` Rules | locked decision list | Defines ranking math and source inputs |
| U46 | Initial V2 Module and Entry-Point Map | table and CLI examples | Defines tool interfaces and output roots |
| U62 | Schema Validation Mechanism | helper/API contract | Defines validation dependency and helper behavior |
| U63 | Schema Contract Shape | missing section before edit | Needed to define `.schema.json` file shape |
| U80 | Slice 6: Workflow Integration | migration slice | Defines workflow agent files and behavior |
| U90 | Exact Initial Validation Commands | command list | Depends on CLI semantics and smoke output behavior |

All other document units were checked against the standard implementation
planning lenses and had no new blocker gap.

### Coverage Matrix

| unit_id | lens | status | evidence |
| --- | --- | --- | --- |
| U04 | implementation decision completeness | gap found | `return_pct`, `delta_pct`, and average-volume threshold sources were not locked. |
| U46 | runtime entry points and data flow | gap found | CLI examples had `--output-dir`, but not exit codes, fixture isolation, or stdout/stderr behavior. |
| U62 | schema/helper/API semantics | gap found | Validator helper names existed, but return/raise behavior and mutation policy were not locked. |
| U63 | schema/helper/API semantics | gap found | `.schema.json` file shape, required/optional fields, and enum mapping were not defined. |
| U80 | approval boundaries | gap found | Workflow agent files were named, but their required content and forbidden actions were not fully bounded. |
| U90 | validation commands | gap found | Smoke commands depended on undefined CLI semantics. |

### Blocker Gap Ledger

| gap_id | severity | unit_id | lens | evidence | why blocker | planned fix | closure evidence | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GAP-025 | blocker | U04 | implementation decision completeness | Scoring formulas used `return_pct`, `delta_pct`, and below-target average volume without source precedence | Planner could choose different source windows and liquidity gates | Lock source precedence and volume thresholds | Source lines 184-196 | closed |
| GAP-026 | blocker | U63 | schema/helper/API semantics | Schema files were named, but file contract shape was missing | Planner could invent incompatible schema docs | Add `Schema Contract Shape` with root fields, item fields, enum fields, and field types | Source lines 1350-1412 | closed |
| GAP-027 | blocker | U62 | schema/helper/API semantics | Validator helpers lacked return/raise/mutation/unknown-field behavior | Planner could implement incompatible validators | Add `TrendValidationIssue`, helper return behavior, no mutation, unknown-field policy, and loader error behavior | Source lines 1324-1349 | closed |
| GAP-028 | blocker | U46/U90 | runtime entry points and validation | CLI behavior lacked fixture isolation, exit codes, overwrite, and stdout/stderr semantics | Smoke and workflow commands could differ | Add locked CLI behavior | Source lines 831-843 | closed |
| GAP-029 | blocker | U80 | approval boundaries | Agent instruction files lacked required headings and command boundaries | Workflow agents could add qualitative behavior | Add required headings, forbidden actions, and one allowed command per agent | Source lines 1634-1658 | closed |

### Gap-To-Fix Map

| gap_id | target unit | exact decision to lock | edit summary | validation check |
| --- | --- | --- | --- | --- |
| GAP-025 | U04 | Source precedence and volume thresholds | Add `simulation_validation_return_pct`, `post_signal_return_pct`, fitness delta fields, 500k broad gate, and 2M high-priority gate | Search locked source field names |
| GAP-026 | U63 | `.schema.json` shape | Add schema contract object fields and enum lists | Search `required_root_fields`, `enum_fields`, `field_types` |
| GAP-027 | U62 | Validator behavior | Add `TrendValidationIssue`, issue-list returns, no mutation, unknown fields allowed, loader raise behavior | Search `TrendValidationIssue` and `load_validated_trend_json` |
| GAP-028 | U46/U90 | CLI semantics | Add fixture isolation, output-root, overwrite, exit-code, stdout/stderr behavior | Search exit code and fixture wording |
| GAP-029 | U80 | Agent instruction boundaries | Add required headings and allowed command per agent | Search `Behavior Boundaries` |

### Cleanup List

No cleanup-only items blocked implementation planning.

## Cycle 7 Plan

1. Add scoring source precedence and liquidity thresholds to the locked score
   rules.
2. Add schema contract shape and enum/required-field details.
3. Add validator issue type, return/raise behavior, no-mutation rule, and
   unknown-field policy.
4. Add CLI fixture, output-dir, overwrite, exit-code, stdout, and stderr
   semantics.
5. Add workflow agent instruction headings, forbidden writes, behavior boundaries,
   and one allowed command per agent.

## Cycle 7 Edits

| gap_id | closure evidence |
| --- | --- |
| GAP-025 | Source lines 184-196 lock scoring source precedence and volume thresholds. |
| GAP-026 | Source lines 1350-1412 define `.schema.json` shape, required fields, field types, and enum fields. |
| GAP-027 | Source lines 1324-1349 define local validator behavior, `TrendValidationIssue`, and `load_validated_trend_json`. |
| GAP-028 | Source lines 831-843 define CLI fixture, output-dir, overwrite, exit-code, stdout, and stderr behavior. |
| GAP-029 | Source lines 1634-1658 define workflow-agent headings, behavior boundaries, forbidden writes, and allowed commands. |

## Cycle 7 Validation

Commands run:

```bash
rg -n 'simulation_validation_return_pct|post_signal_return_pct|watchlist_fitness_delta_pct|candidate_fitness_delta_pct|MIN_AVG_VOL = 500_000|MIN_AVG_VOLUME = 2_000_000|TrendValidationIssue|load_validated_trend_json|exit code `0`|--fixture .*disables all live/provider reads|do not add qualitative judgment' plans/agentic-trading-v2-workflow-principles-research.md
rg -n 'return_pct.*source precedence|delta_pct.*source precedence|unknown fields|severity = "ERROR"|required_root_fields|required_item_fields|enum_fields|field_types|Required Inputs|Forbidden Writes|Behavior Boundaries' plans/agentic-trading-v2-workflow-principles-research.md
rg -n '^## |^### ' plans/agentic-trading-v2-workflow-principles-research.md
```

Results:

- Scoring source fields and volume thresholds are present.
- Schema contract shape, validator behavior, and workflow-agent boundaries are
  present.
- Heading inventory includes the new `Schema Contract Shape` section.

Post-Edit New-Gap Pass:

| changed unit | checked against | result | new gap id |
| --- | --- | --- | --- |
| U04 | scoring determinism | source fields and thresholds are locked | none |
| U46/U90 | CLI determinism | fixture isolation and exit-code semantics are locked | none |
| U62/U63 | schema/validator handoff | file shape and helper behavior are locked | none |
| U80 | approval boundaries | agent behavior is command-only and bounded | none |

## Cycle 8 Assessment

Fresh no-edit full-document assessment after Cycle 7 edits.

### Section Inventory

All deterministic document units were assessed: scope, evidence anchors, coverage
matrix, locked decisions, scoring rules, current-state sections, MCP principle
mapping, feasibility, V2 architecture, module/entry point map, workflow contract,
daily workflow phases, trading-native categories, source evidence, derived
outputs, ledger transitions, artifact schemas, schema validation mechanism,
schema contract shape, scale architecture, artifact model, resume/idempotency,
state/write policy, migration slices, tests, fixture contract, validation
commands, risks, open questions, decision ledger, and initial recommendation.

### Coverage Matrix

| lens | status | evidence |
| --- | --- | --- |
| implementation decision completeness | checked | Scoring source precedence, thresholds, schema shape, validator behavior, CLI semantics, and agent boundaries are locked. |
| runtime entry points and data flow | checked | Tool CLIs, output-dir semantics, workflow YAML, and agent files are named. |
| schema, field, helper, artifact, and API semantics | checked | Six artifacts, schema docs, enum lists, required fields, and validation helpers are defined. |
| edge cases, failure behavior, resume behavior, and idempotency | checked | CLI exit codes, nonconvergence, partial providers, idempotency, and run-history rules are defined. |
| validation commands, test scenarios, and acceptance criteria | checked | Fixture, unit, harness, smoke, candidate tracker, and safety commands are specified. |
| repo grounding for runtime claims | checked | Volume thresholds, validator patterns, agent-file convention, pytest config, and ignore rules were inspected. |
| approval boundaries and out-of-scope slices | checked | Provider/model/persona/prompt and live-state writes remain out of scope. |
| contradictions between sections | checked | Category names, action names, keyed source refs, output roots, and validator policy are consistent. |
| vague wording hiding implementation choices | checked | Remaining open questions are explicitly deferrable and not first-implementation blockers. |
| implementation planner handoff readiness | checked | No blocker gaps remain. |

### Blocker Gap Ledger

All prior gaps GAP-001 through GAP-029 are closed. No new blocker gaps remain.

### Cleanup List

No cleanup findings block implementation planning.

## Cycle 8 Plan

No source-document edits are required.

## Cycle 8 Edits

None.

## Cycle 8 Validation

Cycle 8 performed no edits and therefore satisfies the no-edit convergence rule.

## Final Convergence Check

Final Readiness Proof:

| category | status | evidence |
| --- | --- | --- |
| runtime entry points and data flow | ready | CLIs and output-dir behavior are locked in source lines 807-843; workflow agents are bounded in source lines 1634-1658. |
| schema, fields, interfaces, helpers, and artifacts | ready | Artifact schemas, schema contract shape, and validator behavior are locked in source lines 1220-1412. |
| edge cases and failure behavior | ready | CLI exit codes, validation errors, nonconvergence, partial providers, and missing data behavior are defined. |
| resume behavior and idempotency | ready | Existing run-id, atomic replace, and run-history rules remain compatible with output-dir semantics. |
| validation commands, test scenarios, and acceptance criteria | ready | Fixture, unit, harness, smoke, candidate tracker, and safety checks are specified. |
| repo grounding | ready | Thresholds and conventions were grounded in local tool/config files before edits. |
| approval boundaries | ready | No provider/model/persona/prompt changes are approved. |
| out-of-scope boundaries | ready | Candidate, portfolio, trade-history, broker, and live-state writes remain excluded. |

Conclusion: the research document is ready for a one-shot implementation plan.

## Cycle 9 Assessment

Fresh full-document assessment after the user-requested post-convergence gap
review. Cycle 8's convergence claim is superseded by this assessment because
new blocker gaps were found after the no-edit pass.

### Section Inventory

All deterministic document units were reassessed with focus on the reopened
blocker areas: locked scoring rules, module/entry-point map, workflow contract,
artifact schemas, schema validation mechanism, schema contract shape, resume and
idempotency semantics, state/write policy, migration slices, tests, and decision
ledger.

### Coverage Matrix

| lens | status | evidence |
| --- | --- | --- |
| implementation decision completeness | gap found | `run-status.json` appeared in multiple phases but lacked phase merge semantics. |
| runtime entry points and data flow | gap found | `recent_edge_score` named source fields and helpers but did not assign scoring ownership. |
| schema, field, helper, artifact, and API semantics | gap found | Field types lacked nullable syntax and bounds; `validation-findings[].source_refs` was listed but not required. |
| edge cases, failure behavior, resume behavior, and idempotency | gap found | Status aggregation and phase rerun behavior were not explicitly locked. |
| validation commands, test scenarios, and acceptance criteria | checked | Existing validation strategy remained usable after adding schema and status semantics. |
| repo grounding for runtime claims | checked | `tools/shared_utils.py:166` provides `compute_support_level_score`; `pyproject.toml:11-23` has no schema validation dependency. |
| approval boundaries and out-of-scope slices | checked | New changes remain document-only and do not approve provider/model/persona/prompt changes. |
| contradictions between sections | gap found | `source_refs` was present in validation finding schema fields but absent from required item fields. |
| vague wording hiding implementation choices | gap found | Status update, type grammar, numeric bounds, and scoring provenance left implementer decisions open. |
| implementation planner handoff readiness | gap found | Follow-up implementation planning would still need to decide these contracts. |

### Blocker Gap Ledger

| gap_id | severity | unit_id | lens | evidence | why blocker | planned fix | closure evidence | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GAP-030 | blocker | resume/idempotency + workflow contract | status merge semantics | `run-status.json` is emitted by multiple phases, while `phase_statuses[]` exists without update rules. | Implementer would need to decide whether phase tools append, merge, replace, or rewrite status entries. | Add run-status update semantics with phase-owned entries, aggregate status precedence, failure behavior, and atomic replace. | Source lines 1566-1590 lock the update and aggregate semantics. | closed |
| GAP-031 | blocker | schema contract shape | type/nullability/bounds | `recent_edge_score` could be `null`, but field types were only simple labels. | Validator implementation would need to invent nullable syntax and numeric bound enforcement. | Add local type grammar, nullable array syntax, `numeric_bounds`, and initial score/count bounds. | Source lines 1374-1390 define type grammar and numeric bounds. | closed |
| GAP-032 | blocker | validation findings schema | required source refs | `source_refs` was in the finding shape but absent from required finding fields. | Validator and fixture writers could disagree on whether findings need evidence refs. | Add `source_refs` to required finding fields and define missing-source citation behavior. | Source lines 1400-1414 require `source_refs` and define citation fallback. | closed |
| GAP-033 | blocker | scoring rules + module map | scoring ownership/provenance | `compute_support_level_score` and source precedence were locked, but ownership and provenance validation were not. | Implementer would need to decide where scoring lives and how metric source fields are audited. | Assign extractor ownership, shared-utils import, snapshot/extractor/validator provenance responsibilities, and `metrics.recent_edge_score_inputs`. | Source lines 197-207 and 811-812 lock ownership and provenance. | closed |

### Cleanup List

No cleanup-only findings were opened; all Cycle 9 findings were blocker-class
handoff gaps.

## Cycle 9 Plan

| gap_id | target unit | exact decision to lock | edit summary | validation check |
| --- | --- | --- | --- | --- |
| GAP-030 | Resume, Idempotency, and Failure Semantics | Per-phase `run-status.json` update/merge and aggregate status precedence | Add `Run Status Update Semantics` subsection. | Search for `Run Status Update Semantics`, `phase_statuses`, and aggregate `run_status`. |
| GAP-031 | Schema Contract Shape | Nullable type grammar and numeric bounds | Revise `field_types` and add `numeric_bounds`. | Search for `numeric_bounds` and nullable array syntax. |
| GAP-032 | Schema Contract Shape | `validation-findings[].source_refs` requiredness | Add `source_refs` to required finding fields and fallback source-ref rule. | Search required item fields and source-ref rule. |
| GAP-033 | Locked scoring rules and module map | Scoring owner, support helper import, and provenance payload | Add extractor/validator ownership bullets and update module responsibility rows. | Search for `recent_edge_score_inputs` and `compute_support_level_score`. |

## Cycle 9 Edits

Applied source-document edits only:

- Added scoring ownership, provenance responsibilities, and
  `metrics.recent_edge_score_inputs` requirements to locked score rules.
- Updated `tools/trend_extractor.py` and `tools/trend_validator.py` module-map
  responsibilities.
- Replaced simple-only schema field typing with a local nullable type grammar
  and `numeric_bounds`.
- Required `validation-findings[].source_refs` and documented how missing-source
  findings cite evidence.
- Added `Run Status Update Semantics` for per-phase status updates, aggregate
  status precedence, missing-prior-artifact behavior, and atomic replacement.

## Cycle 9 Validation

Commands run:

```bash
rg -n 'recent_edge_score_inputs|compute_support_level_score|numeric_bounds|Validation findings about missing source evidence|Run Status Update Semantics|aggregate `run_status`|validation-findings.*requires|source_refs' plans/agentic-trading-v2-workflow-principles-research.md
rg -n 'jsonschema|pydantic' pyproject.toml
rg -n 'def compute_support_level_score' tools/shared_utils.py
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '188,210p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1368,1416p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1560,1592p'
```

Results:

- Scoring ownership and `metrics.recent_edge_score_inputs` are present in source
  lines 197-207.
- Schema type grammar, nullable syntax, and numeric bounds are present in source
  lines 1374-1390.
- `validation-findings[].source_refs` is required and missing-source evidence
  behavior is defined in source lines 1400-1414.
- Run-status phase merge and aggregate status behavior are present in source
  lines 1566-1590.
- Repo grounding remains valid: `compute_support_level_score` exists at
  `tools/shared_utils.py:166`, and `rg -n 'jsonschema|pydantic' pyproject.toml`
  returned no matches.

Post-Edit New-Gap Pass:

| changed unit | checked against | result | new gap id |
| --- | --- | --- | --- |
| Locked `recent_edge_score` Rules | ownership, provenance, helper reuse | extractor ownership and validator provenance checks are locked | none |
| Initial V2 Module and Entry-Point Map | runtime owner clarity | extractor and validator rows now identify score and provenance responsibilities | none |
| Schema Contract Shape | nullable fields, bounds, required refs | type grammar, numeric bounds, and finding source refs are locked | none |
| Resume, Idempotency, and Failure Semantics | phase reruns and status aggregation | run-status update, preserve/replace behavior, and precedence are locked | none |

Cycle 9 performed document edits, so it must not claim final convergence. The
next required artifact is a fresh Cycle 10 no-edit full-document assessment.

## Cycle 10 Assessment

Fresh no-edit full-document assessment after Cycle 9 edits. This pass did not
modify the research document.

### Section Inventory

All deterministic document units were reassessed: scope, evidence anchors,
coverage matrix, locked decisions, scoring rules, current-state sections, MCP
principle mapping, feasibility, V2 architecture, module/entry-point map,
workflow contract, daily workflow phases, trading-native categories, source
evidence, derived outputs, ledger transitions, artifact schemas, schema
validation mechanism, schema contract shape, scale architecture, artifact model,
resume/idempotency, run-status semantics, state/write policy, migration slices,
tests, fixture contract, validation commands, risks, open questions, decision
ledger, and initial recommendation.

### Coverage Matrix

| lens | status | evidence |
| --- | --- | --- |
| implementation decision completeness | gap found | Status lifecycle and next-plan scope still leave implementer choices. |
| runtime entry points and data flow | checked | Tool CLIs, output-dir behavior, module ownership, and workflow YAML targets are named. |
| schema, field, helper, artifact, and API semantics | gap found | Several required fields have first-run or missing-record nullability that is not locked. |
| edge cases, failure behavior, resume behavior, and idempotency | gap found | `run-status.json` initial creation conflicts with required `finished_at` and terminal-only statuses. |
| validation commands, test scenarios, and acceptance criteria | checked | Contract, snapshot, extractor, validator, harness, smoke, and safety commands are listed. |
| repo grounding for runtime claims | checked | Existing workflow names and shared support scorer were inspected. |
| approval boundaries and out-of-scope slices | gap found | The document both defers contract approval before workflow changes and includes workflow integration in the migration sketch. |
| contradictions between sections | gap found | Runtime workflow scope and status lifecycle contain unresolved contradictions. |
| vague wording hiding implementation choices | gap found | First-run nullable values and implementation-plan slice boundaries are not explicit enough. |
| implementation planner handoff readiness | gap found | A one-shot follow-up implementation plan would still need to decide the gaps below. |

### Blocker Gap Ledger

| gap_id | severity | unit_id | lens | evidence | why blocker | planned fix | closure evidence | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GAP-034 | blocker | Run Status Update Semantics + run-status schema | lifecycle/schema contradiction | Source lines 1326-1333 require `finished_at` fields and define terminal status fields; source lines 1440-1443 enumerate only terminal/skipped/nonconverged phase statuses; source line 1571 says snapshot creates the initial status file when it starts a run. | An implementer must decide whether to add `running`, allow nullable `finished_at`, write status only after phase completion, or violate the schema during execution. | Lock run-status lifecycle: either write only terminal phase entries after each phase, or add `running`/nullable timestamp semantics. Also align required item fields with the locked lifecycle. | pending | open |
| GAP-035 | blocker | Schema Contract Shape + artifact schemas | first-run and missing-record nullability | Source line 1280 requires `prior_ledger_run_id`; source lines 1297 and 1400 require `record_id` on validation findings; source line 1228 says source-ref `as_of_date` exists only when available; source lines 1374-1390 define nullable grammar but only lock nullability for score fields. | First run, missing-trend findings, and source refs without source dates require explicit `null`, sentinel, or omission behavior. The implementation plan would otherwise invent incompatible schema choices. | Add initial field type/nullability decisions for `prior_ledger_run_id`, `validation-findings[].record_id`, `source_refs[].as_of_date`, run-status timestamps, and any nullable optional fields used in fixtures. | pending | open |
| GAP-036 | blocker | Trading-native contract approval + migration plan + decision ledger | implementation scope contradiction | Source lines 1072-1074 say exact contract text requires separate approval before runtime prompt or workflow changes; source lines 1691-1715 include workflow YAML and agent instruction files in the migration; source lines 1905-1906 say prompt/persona/provider/model changes require separate approval. | A follow-up implementation plan cannot know whether to include Slice 6 workflow/agent files or stop at deterministic code/schema artifacts. | Lock the next implementation-plan scope: either exclude workflow/agent files until a later approval, or explicitly approve minimal command-only workflow/agent files as non-prompt/persona behavior changes. | pending | open |

### Cleanup List

No cleanup-only findings were recorded. The open items are blocker-class because
they force implementation-plan decisions.

### Assessment Validation

Commands run:

```bash
rg -n '^## |^### ' plans/agentic-trading-v2-workflow-principles-research.md
rg -n 'TODO|TBD|maybe|should decide|or equivalent|such as|for example|when available|where feasible|should support|could|may|Deferrable|Open Questions|exact contract text should be approved separately|source_refs|SCHEMA_VERSION|TrendValidationIssue|recent_edge_score|recent_edge_score_inputs|numeric_bounds|Run Status Update Semantics|run-status\\.json|phase_statuses|completed_with_gaps|jsonschema|pydantic' plans/agentic-trading-v2-workflow-principles-research.md
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1320,1445p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1536,1591p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1068,1078p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1648,1725p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1892,1908p'
```

Result: Cycle 10 found three open blocker gaps and cannot claim readiness or
final convergence.

## Cycle 10 Plan

| gap_id | target unit | exact decision to lock | edit summary | validation check |
| --- | --- | --- | --- | --- |
| GAP-034 | run-status schema and update semantics | `running` is a valid lifecycle status; `finished_at` is nullable until terminal; snapshot creates schema-valid running status | Add `running` enum values, nullable timestamp rules, root/phase running lifecycle, and CLI success semantics for downstream-running runs. | Search for `running`, `finished_at`, and aggregate run-status rules. |
| GAP-035 | schema contract shape | Required nullable fields must be present as `null`; first-run and missing-record fields have explicit nullable types | Add initial nullable field list for `prior_ledger_run_id`, finding `record_id`, source-ref `as_of_date`, and run-status timestamps. | Search for nullable field names and required-null rule. |
| GAP-036 | module map, workflow contract, migration plan, validation commands, decision ledger, initial recommendation | First implementation excludes workflow YAML and `.workflow/agents/*`; those require separate approval | Mark workflow files as deferred approval-gated targets, rename Slice 6, split workflow-contract test, and update decision ledger. | Search for `Deferred Workflow Integration`, `separate approval`, and workflow-gated lines. |

## Cycle 10 Edits

Applied source-document edits only:

- Added `running` to root and phase status enums and clarified that exit code
  `0` may leave the aggregate run in `running` for downstream phases.
- Added nullable field policy for first-run and missing-record cases, including
  `prior_ledger_run_id`, `validation-findings[].record_id`,
  `source_refs[].as_of_date`, and run-status `finished_at` fields.
- Clarified run-status lifecycle: snapshot creates a schema-valid running file,
  phases update their own entries from `running` to terminal, and the report
  phase finalizes root `finished_at`.
- Reframed workflow YAML and `.workflow/agents/*` as deferred approval-gated
  targets, including module map, workflow contract note, Slice 6, validation
  commands, decision ledger, and initial recommendation.

## Cycle 10 Validation

Commands run:

```bash
rg -n 'running|finished_at|prior_ledger_run_id|record_id|as_of_date|nullable|required nullable|Deferred Workflow Integration|separate approval|workflow YAML|workflow-contract|current phase completed' plans/agentic-trading-v2-workflow-principles-research.md
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1330,1468p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1589,1624p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '801,868p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1724,1740p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1865,1875p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1944,1951p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1972,1980p'
```

Results:

- GAP-034 closed: source lines 1336-1339 and 1463-1466 add `running` status
  enums; lines 1594-1620 lock schema-valid running creation, phase terminal
  updates, and final aggregate completion.
- GAP-035 closed: source lines 1398-1413 define required nullable fields and
  explicit-null behavior for first-run and missing-record cases.
- GAP-036 closed: source lines 803-805, 866-868, 1724-1735, 1871-1875,
  1948-1950, and 1977-1978 lock workflow YAML and `.workflow/agents/*` as
  separate-approval work outside the first implementation plan.

Post-Edit New-Gap Pass:

| changed unit | checked against | result | new gap id |
| --- | --- | --- | --- |
| run-status schema and semantics | lifecycle/schema consistency | running root/phase entries are schema-valid and terminal completion is defined | none |
| schema contract shape | first-run and nullable field determinism | nullable required fields and explicit-null behavior are locked | none |
| module map/workflow/migration/test/decision sections | implementation scope and approval boundary | first implementation scope excludes workflow YAML and agents; deferred approval path remains documented | none |

Cycle 10 performed document edits, so it must not claim final convergence. The
next required artifact is a fresh Cycle 11 no-edit full-document assessment.

## Cycle 11 Assessment

Fresh no-edit full-document assessment after Cycle 10 edits. This pass did not
modify the research document.

### Section Inventory

All deterministic document units were reassessed: scope, evidence anchors,
coverage matrix, locked decisions, scoring rules, current-state sections, MCP
principle mapping, feasibility, V2 architecture, module/entry-point map,
workflow contract, daily workflow phases, trading-native categories, source
evidence, derived outputs, ledger transitions, artifact schemas, schema
validation mechanism, schema contract shape, scale architecture, artifact model,
resume/idempotency, run-status semantics, state/write policy, migration slices,
tests, fixture contract, validation commands, risks, open questions, decision
ledger, and initial recommendation.

### Coverage Matrix

| lens | status | evidence |
| --- | --- | --- |
| implementation decision completeness | gap found | Failure/nonconvergence status precedence still conflicts with downstream-running behavior. |
| runtime entry points and data flow | checked | First implementation tool CLIs are named; workflow YAML and agents are approval-gated. |
| schema, field, helper, artifact, and API semantics | checked | Required nullable fields and running status enums are now locked. |
| edge cases, failure behavior, resume behavior, and idempotency | gap found | Upstream terminal failure with downstream phases not run has no unambiguous aggregate status outcome. |
| validation commands, test scenarios, and acceptance criteria | checked | First implementation and deferred workflow validation commands are separated. |
| repo grounding for runtime claims | checked | Local tool and workflow file references remain path-grounded. |
| approval boundaries and out-of-scope slices | checked | Workflow YAML, agents, prompt/persona/provider/model changes are separate-approval work. |
| contradictions between sections | gap found | Aggregate status precedence says `failed`/`nonconverged` wins, while the running rule says root remains `running` until required downstream phases have terminal entries. |
| vague wording hiding implementation choices | gap found | The document allows `skipped` downstream phases after upstream failure/nonconvergence but does not state whether they must be synthesized before aggregate status finalizes. |
| implementation planner handoff readiness | gap found | A one-shot implementation plan would still need to choose the failure/nonconvergence finalization behavior. |

### Blocker Gap Ledger

| gap_id | severity | unit_id | lens | evidence | why blocker | planned fix | closure evidence | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GAP-037 | blocker | Run Status Update Semantics | failure/nonconvergence finalization | Source lines 1612-1616 say aggregate `run_status` is `failed` if any phase failed and `nonconverged` if ledger is nonconverged; source lines 1617-1620 say root `run_status` remains `running` while any required downstream phase has no terminal entry; source lines 1621-1623 allow downstream `skipped` entries after upstream `failed` or `nonconverged` but do not require who writes them or when. | If ledger fails or nonconverges before actions/report run, the implementer must decide whether root status is immediately terminal, remains running, or first requires synthesized skipped entries. | Lock failure/nonconvergence finalization: require the failing phase tool to synthesize terminal `skipped` entries for all downstream required phases before setting root `failed` or `nonconverged`, or explicitly make upstream terminal status override missing downstream entries. | pending | open |

### Cleanup List

No cleanup-only findings were recorded. The open item is blocker-class because it
forces status finalization behavior in the implementation plan.

### Assessment Validation

Commands run:

```bash
rg -n '^## |^### ' plans/agentic-trading-v2-workflow-principles-research.md
rg -n 'TODO|TBD|maybe|should decide|or equivalent|such as|for example|when available|where feasible|should support|could|may|Deferrable|Open Questions|exact contract text|separate approval|workflow YAML|\\.workflow/agents|running|finished_at|prior_ledger_run_id|record_id|source_refs\\[\\]\\.as_of_date|required nullable|run_status|phase_statuses|completed_with_gaps|failed|nonconverged|skipped|first implementation|follow-up implementation plan|Initial Recommendation' plans/agentic-trading-v2-workflow-principles-research.md
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1589,1624p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1330,1340p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1460,1467p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '803,868p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1724,1735p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1948,1950p'
```

Result: Cycle 11 found one open blocker gap and cannot claim readiness or final
convergence.

## Cycle 11 Plan

| gap_id | target unit | exact decision to lock | edit summary | validation check |
| --- | --- | --- | --- | --- |
| GAP-037 | Run Status Update Semantics and Schema Contract Shape | Failure/nonconvergence finalization requires synthesizing terminal downstream `skipped` entries before root status becomes terminal. | Add required phase order, downstream skipped-entry synthesis, terminal aggregate status behavior, and `started_at: null` policy for synthesized skipped entries. | Search for required phase order, synthesized skipped entries, aggregate finalization, and nullable `started_at`. |

## Cycle 11 Edits

Applied source-document edits only:

- Added the required status-finalization phase order: `snapshot`, `ledger`,
  `actions`, `report`.
- Clarified that root `run_status` remains `running` only when no phase has
  `failed` or `nonconverged` and a required downstream phase lacks a terminal
  entry.
- Required a failed phase, or nonconverged ledger phase, to synthesize terminal
  `skipped` entries for every downstream required phase before final status
  write.
- Defined synthesized `skipped` entry shape, including `started_at: null`,
  upstream terminal `finished_at`, empty downstream outputs, and an `errors[]`
  entry naming the upstream phase, status, and reason.
- Added nullable `run-status.phase_statuses[].started_at` policy restricted to
  synthesized downstream `skipped` entries.

## Cycle 11 Validation

Commands run:

```bash
rg -n 'required phase order|synthesized|skipped|upstream|failed|nonconverged|running|finished_at|started_at|aggregate `run_status`|terminal timestamp' plans/agentic-trading-v2-workflow-principles-research.md
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1398,1418p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1589,1634p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1634,1642p'
```

Results:

- GAP-037 closed: source lines 1597-1599 define required phase order; lines
  1623-1633 define running-vs-terminal aggregate behavior and downstream
  skipped-entry synthesis after failure/nonconvergence; lines 1634-1637 define
  the synthesized skipped entry shape.
- Source lines 1409-1413 define nullable `phase_statuses[].started_at` and
  `phase_statuses[].finished_at` behavior for skipped and running entries.

Post-Edit New-Gap Pass:

| changed unit | checked against | result | new gap id |
| --- | --- | --- | --- |
| Run Status Update Semantics | snapshot failure before ledger/actions/report | failing snapshot synthesizes downstream skipped entries and root status becomes `failed` | none |
| Run Status Update Semantics | ledger nonconvergence before actions/report | nonconverged ledger synthesizes downstream skipped entries and root status becomes `nonconverged` | none |
| Run Status Update Semantics | actions failure before report | failed actions phase synthesizes report skipped entry and root status becomes `failed` | none |
| Schema Contract Shape | skipped entry timestamp validity | synthesized skipped entries may use `started_at: null`; running entries may use `finished_at: null` | none |

Cycle 11 performed document edits, so it must not claim final convergence. The
next required artifact is a fresh Cycle 12 no-edit full-document assessment.

## Cycle 12 Assessment

Fresh no-edit full-document assessment after Cycle 11 edits. This pass did not
modify the research document.

### Section Inventory

All deterministic document units were reassessed: scope, evidence anchors,
coverage matrix, locked decisions, scoring rules, current-state sections, MCP
principle mapping, feasibility, V2 architecture, module/entry-point map,
workflow contract, daily workflow phases, trading-native categories, source
evidence, derived outputs, ledger transitions, artifact schemas, schema
validation mechanism, schema contract shape, scale architecture, artifact model,
resume/idempotency, run-status semantics, state/write policy, migration slices,
tests, fixture contract, validation commands, risks, open questions, decision
ledger, and initial recommendation.

### Coverage Matrix

| lens | status | evidence |
| --- | --- | --- |
| implementation decision completeness | gap found | Phase timestamp requiredness is inconsistent between schema shape and status lifecycle. |
| runtime entry points and data flow | checked | First implementation CLIs and deferred workflow boundary remain locked. |
| schema, field, helper, artifact, and API semantics | gap found | `phase_statuses[]` shape includes timestamp fields, but required item fields omit them. |
| edge cases, failure behavior, resume behavior, and idempotency | checked | Failure/nonconvergence finalization now synthesizes downstream skipped entries. |
| validation commands, test scenarios, and acceptance criteria | checked | First implementation and deferred workflow validation commands remain separated. |
| repo grounding for runtime claims | checked | Local references and path claims remain grounded. |
| approval boundaries and out-of-scope slices | checked | Workflow YAML, agents, prompt/persona/provider/model changes remain separate-approval work. |
| contradictions between sections | gap found | Timestamp fields are required by lifecycle rules but not by the schema required-item list. |
| vague wording hiding implementation choices | gap found | Validator authors must decide whether omitted phase timestamps are valid. |
| implementation planner handoff readiness | gap found | A one-shot implementation plan would still need to decide phase timestamp requiredness. |

### Blocker Gap Ledger

| gap_id | severity | unit_id | lens | evidence | why blocker | planned fix | closure evidence | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GAP-038 | blocker | Schema Contract Shape + Run Status Update Semantics | phase timestamp requiredness | Source lines 1338-1339 define `phase_statuses[]` as including `started_at` and `finished_at`; source lines 1409-1413 define nullable rules for phase `started_at` and `finished_at`; source lines 1601-1611 and 1634-1637 require phase entries to carry these timestamps; source lines 1434-1435 list required `phase_statuses[]` item fields but omit `started_at` and `finished_at`. | Validator and fixture authors must decide whether phase timestamps can be omitted despite lifecycle rules, which would make run-status artifacts inconsistent across implementations. | Add `started_at` and `finished_at` to the required `run-status.phase_statuses[]` item fields, with nullable behavior already governed by the existing field-type rules. | pending | open |

### Cleanup List

No cleanup-only findings were recorded. The open item is blocker-class because it
affects validator behavior and fixture shape.

### Assessment Validation

Commands run:

```bash
rg -n '^## |^### ' plans/agentic-trading-v2-workflow-principles-research.md
rg -n 'TODO|TBD|maybe|should decide|or equivalent|such as|for example|when available|where feasible|should support|could|may|Deferrable|Open Questions|exact contract text|separate approval|workflow YAML|\\.workflow/agents|running|finished_at|started_at|prior_ledger_run_id|record_id|source_refs\\[\\]\\.as_of_date|required nullable|run_status|phase_statuses|completed_with_gaps|failed|nonconverged|skipped|synthesized|required phase order|first implementation|follow-up implementation plan|Initial Recommendation' plans/agentic-trading-v2-workflow-principles-research.md
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1328,1472p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1592,1638p'
rg -n 'phase_statuses\\[\\].*requires|started_at|finished_at|must include `phase`|phase_statuses\\[\\]:|required_item_fields' plans/agentic-trading-v2-workflow-principles-research.md
```

Result: Cycle 12 found one open blocker gap and cannot claim readiness or final
convergence.

## Cycle 12 Plan

| gap_id | target unit | exact decision to lock | edit summary | validation check |
| --- | --- | --- | --- | --- |
| GAP-038 | Schema Contract Shape | `run-status.phase_statuses[]` requires `started_at` and `finished_at`; nullable timestamp rules govern allowed `null` values. | Add `started_at` and `finished_at` to the required `run-status.phase_statuses[]` item fields. | Search required run-status item fields and timestamp nullable rules. |

## Cycle 12 Edits

Applied source-document edits only:

- Updated `Schema Contract Shape` so `run-status.phase_statuses[]` required item
  fields include `started_at` and `finished_at`.
- Left existing nullable timestamp semantics unchanged: synthesized downstream
  `skipped` entries may use `started_at: null`; running entries may use
  `finished_at: null`.

## Cycle 12 Validation

Commands run:

```bash
rg -n 'run-status.*phase_statuses\\[\\] requires|started_at|finished_at|synthesized downstream|phase status is `running`|phase_statuses\\[\\]:|Initial required item fields' plans/agentic-trading-v2-workflow-principles-research.md
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1398,1438p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1598,1638p'
```

Results:

- GAP-038 closed: source lines 1434-1435 require `started_at` and `finished_at`
  on every `run-status.phase_statuses[]` item.
- Nullable timestamp behavior remains locked in source lines 1407-1413.
- Lifecycle behavior remains locked in source lines 1601-1611 and 1634-1637.

Post-Edit New-Gap Pass:

| changed unit | checked against | result | new gap id |
| --- | --- | --- | --- |
| Schema Contract Shape | running phase entry timestamp validity | `started_at` and `finished_at` are required; `finished_at` may be `null` while running | none |
| Schema Contract Shape | synthesized skipped entry timestamp validity | `started_at` and `finished_at` are required; `started_at` may be `null` for synthesized skipped entries | none |
| Run Status Update Semantics | terminal completed/failed/nonconverged entries | timestamp fields are required and terminal `finished_at` is non-null by lifecycle rule | none |

Cycle 12 performed document edits, so it must not claim final convergence. The
next required artifact is a fresh Cycle 13 no-edit full-document assessment.

## Cycle 13 Assessment

Fresh no-edit full-document assessment after Cycle 12 edits. This pass did not
modify the research document.

### Section Inventory

All deterministic document units were reassessed: scope, evidence anchors,
coverage matrix, locked decisions, scoring rules, current-state sections, MCP
principle mapping, feasibility, V2 architecture, module/entry-point map,
workflow contract, daily workflow phases, trading-native categories, source
evidence, derived outputs, ledger transitions, artifact schemas, schema
validation mechanism, schema contract shape, scale architecture, artifact model,
resume/idempotency, run-status semantics, state/write policy, migration slices,
tests, fixture contract, validation commands, risks, open questions, decision
ledger, and initial recommendation.

### Coverage Matrix

| lens | status | evidence |
| --- | --- | --- |
| implementation decision completeness | checked | First implementation scope, deferred workflow scope, scale caps, write boundaries, run lifecycle, and validation commands are locked. |
| runtime entry points and data flow | checked | Source lines 803-856 define deterministic tool targets, CLI shape, output-dir rules, and exit semantics; source lines 866-868 defer workflow YAML and agents. |
| schema, field, helper, artifact, and API semantics | checked | Source lines 1367-1470 define schema contract shape, nullable field types, required item fields, enum values, and run-status timestamp requiredness. |
| edge cases, failure behavior, resume behavior, and idempotency | checked | Source lines 1562-1637 define rerun behavior, atomic writes, status lifecycle, skipped downstream entries, and aggregate finalization. |
| validation commands, test scenarios, and acceptance criteria | checked | Source lines 1787-1910 define contract, snapshot, extractor, validation, harness, fixture, smoke, and safety checks. |
| repo grounding for runtime claims | checked | Source lines 22-101 provide evidence anchors for current repo workflows, tools, artifacts, and MCP harness references. |
| approval boundaries and out-of-scope slices | checked | Source lines 1738-1766, 1936-1980 separate deferred workflow/agent changes and explicit non-goals from the first implementation. |
| contradictions between sections | checked | Run-status shape, required fields, nullable timestamps, lifecycle rules, and implementation-scope boundaries are aligned. |
| vague wording hiding implementation choices | checked | Remaining open questions in source lines 1936-1947 are explicitly deferrable and not first-implementation blockers. |
| implementation planner handoff readiness | checked | No blocker gaps remain for a follow-up one-shot implementation plan. |

### Blocker Gap Ledger

All prior gaps GAP-001 through GAP-038 are closed or superseded by later
closures. No new blocker gaps remain.

### Cleanup List

No cleanup-only findings block implementation planning.

### Assessment Validation

Commands run:

```bash
rg -n '^## |^### ' plans/agentic-trading-v2-workflow-principles-research.md
rg -n 'TODO|TBD|maybe|should decide|or equivalent|such as|for example|when available|where feasible|should support|could|may|Deferrable|Open Questions|exact contract text|separate approval|workflow YAML|\\.workflow/agents|running|finished_at|started_at|prior_ledger_run_id|record_id|source_refs\\[\\]\\.as_of_date|required nullable|run_status|phase_statuses|completed_with_gaps|failed|nonconverged|skipped|synthesized|required phase order|first implementation|follow-up implementation plan|Initial Recommendation|source lines|pending|open' plans/agentic-trading-v2-workflow-principles-research.md
rg -n '^## |GAP-038|Cycle 13|Final Convergence Check|next required artifact|open \\|' plans/agentic-trading-v2-workflow-principles-research.gap-audit.md
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '801,875p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1367,1470p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1592,1638p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1738,1767p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1862,1898p'
nl -ba plans/agentic-trading-v2-workflow-principles-research.md | sed -n '1936,1994p'
```

Results:

- Required timestamp fields and nullable timestamp behavior are aligned in source
  lines 1407-1416 and 1434-1435.
- Run-status lifecycle and downstream skipped-entry finalization are aligned in
  source lines 1597-1637.
- First implementation scope excludes workflow YAML and `.workflow/agents/*`
  changes, which remain separate-approval work in source lines 803-805,
  866-868, 1738-1766, and 1962-1964.
- Validation commands and fixtures are explicit in source lines 1787-1910.

## Final Convergence Check

Final Readiness Proof:

| category | status | evidence |
| --- | --- | --- |
| implementation decision completeness | ready | Locked decisions, implementation scope, schedule, scale caps, write boundaries, and deferrals are explicit. |
| runtime entry points and data flow | ready | Tool files, CLI commands, output directory behavior, and phase order are specified. |
| schema, fields, interfaces, helpers, and artifacts | ready | Artifact schemas, required fields, nullable fields, enum values, validators, and helper ownership are specified. |
| edge cases and failure behavior | ready | Provider partial failures, nonconvergence, skipped downstream phases, timeout behavior, and exit codes are specified. |
| resume behavior and idempotency | ready | Run IDs, same-day replacement, run-history preservation, atomic writes, stable keys, and manager-owned IDs are specified. |
| validation commands, test scenarios, and acceptance criteria | ready | Unit, harness, fixture, smoke, safety, and deferred workflow tests are listed with commands. |
| repo grounding | ready | Evidence anchors cite current repo workflows, tools, artifacts, and MCP harness patterns. |
| approval boundaries | ready | Workflow YAML, `.workflow/agents/*`, prompt/persona/provider/model, live-state writes, and candidate mutations are approval-gated or out of scope. |

Conclusion: the research document is ready for a one-shot implementation plan.
