# Agentic Trading V2 Workflow Principles Research

Date: 2026-05-31

## Scope

Evaluate whether the workflow principles from the current local `mcp-agents-workflow`
phase-ledger harness can be brought into `agentic-trading` to create a V2 system
that:

- extracts stock trends daily instead of relying on weekly optimization cycles;
- monitors hundreds of stocks instead of a narrow approximately 30-ticker candidate
  set;
- remains grounded in the strategy's recent market-beat evidence rather than
  model intuition;
- preserves the existing operational safety boundaries around portfolio and trade
  state.

This is a research document only. It does not approve runtime workflow changes,
provider/model changes, persona rewrites, or live trading-state mutations.

## Evidence Anchors

Local checkout anchors used for this document:

- `agentic-trading`: branch `main`, commit `3d26f270a96de7f97c646e05bc5a176c18bbc9ed`
- `mcp-agents-workflow`: branch `main`, commit `dc492968b759a9ce56211c5dbcc77c79c1c9f51c`

The `mcp-agents-workflow` checkout was inspected locally. I did not fetch or pull
remote refs during this research pass, so "newest" means newest available in the
local checkout at the time of this document.

Primary `agentic-trading` anchors:

- `README.md:5-11` defines the repo as an operational trading workspace and warns
  that `portfolio.json` and `trade_history.json` are live state.
- `README.md:64-94` maps the current system into Python tools, YAML workflows,
  generated artifacts, ticker memory, and the learned graph policy.
- `README.md:80-89` identifies the key operational paths: bullet recommendations,
  portfolio-state mutation, daily analyzer, weekly reoptimization, backtests, and
  workflow YAML composition.
- `tools/daily_analyzer.py:1-16` shows the consolidated daily operational surface,
  including fills/sells, deployment recommendations, watchlist fitness, candidate
  screening, and reconciliation.
- `tools/daily_analyzer.py:1150-1233` shows current daily candidate screening as
  a `surgical_screener.py` plus `surgical_filter.py` flow, optionally using the
  dynamic universe cache.
- `tools/universe_screener.py:1-13` and `tools/universe_screener.py:34-44` show a
  full-universe daily-capable screen with chunking, yfinance data, strategy gates,
  and a three-day cache validity window.
- `tools/neural_candidate_discoverer.py:1-15` shows a universe-scale learned
  graph dip-policy path, but it still outputs top-N candidates after a heavy
  sweep/cross-validation pipeline.
- `tools/morning_gatherer_v2.py:1-14` and `tools/morning_gatherer_v2.py:42-44`
  show an existing scaled collection attempt for 100+ tickers through sector
  shards.
- `workflows/morning-briefing-workflow.yaml:1-69`, `workflows/status-workflow.yaml:1-50`,
  and `workflows/sim-ranked-candidate-workflow.yaml:1-47` show the current YAML
  workflow style.
- `tools/candidate_tracker.py:1-13` defines the supported candidate-pool command
  surface, while `tools/candidate_tracker.py:25-43`, `tools/candidate_tracker.py:92-120`,
  `tools/candidate_tracker.py:123-152`, and `tools/candidate_tracker.py:179-211`
  show that candidate writes are explicit operations and promotion routes through
  `batch_onboard.py`.
- `tools/portfolio_manager.py:1-14` states that all portfolio writes are
  mechanized so the LLM does not edit `portfolio.json` directly; `tools/portfolio_manager.py:31-34`,
  `tools/portfolio_manager.py:53-73`, `tools/portfolio_manager.py:91-111`, and
  `tools/portfolio_manager.py:161-179` show the live state paths, lock, atomic
  JSON write, and validation boundary that V2 must not bypass.
- `tools/neural_artifact_validator.py:1-6`, `tools/neural_artifact_validator.py:21-24`,
  `tools/neural_artifact_validator.py:39-56`, and `tools/neural_artifact_validator.py:149-160`
  show the existing pattern for generated artifact schema, freshness, and
  execution-mode validation.
- `tools/artifact_promoter.py:1-6`, `tools/artifact_promoter.py:33-39`, and
  `tools/artifact_promoter.py:178-238` show the existing incumbent/candidate
  promotion gate pattern for generated graph-policy artifacts.
- `tools/shared_utils.py:166-245` shows the existing support-level scoring
  components: target probability, break probability, fill likelihood, tier,
  zone, trend, dormant/frequency/confidence penalties, and expected edge.

Primary `mcp-agents-workflow` anchors:

- `src/workflow_orch/phase_ledger_loop.py:13-43` defines `phase_ledger_loop`,
  allowed input sources, convergence rules, source coverage modes, prompt assembly
  mode, lineage modes, and lineage rules.
- `src/workflow_orch/phase_ledger_loop.py:90-170` defines role configs and input
  source validation for producer, verifier, and critic roles.
- `src/workflow_orch/workflows/codebase-grounding-precode-workflow.yaml:13-59`
  shows a phase-ledger loop with `task_description` input, full-universe coverage,
  hollow producer/verifier/critic roles, universal contract prompt assembly, and
  empty-finding convergence.
- `src/workflow_orch/workflows/codebase-grounding-precode-workflow.yaml:60-109`
  shows a downstream phase consuming subscribed phase outputs and grouping final
  output through a composer policy.
- `src/workflow_orch/contracts/phase_ledger/phase-ledger-universal-orchestration-contract-wip.md:1-14`
  states the core harness principle: producer, manager, verifier, and critic work
  from one shared universal contract, while phase-specific behavior comes from
  the phase classification contract.
- `src/workflow_orch/contracts/phase_ledger/phase-ledger-universal-orchestration-contract-wip.md:21-65`
  defines source universe, source coverage, phase classification, derived outputs,
  and checkout-evidence boundaries.

## Research Coverage Matrix

This document now locks the research defaults required for a one-shot
implementation plan. Future hardening can still refine measured baselines, but
the first V2 prototype should use the decisions below unless the user explicitly
changes them.

| Area | Current coverage | Locked implementation decision |
| :--- | :--- | :--- |
| Current trading workflows | Expanded below with workflow families and operational purpose | Treat current workflows as consumers/inputs first; do not replace daily or weekly workflows in the first slice |
| Current Python tool surfaces | Expanded below by tool family and state boundary | Add new V2 tools under `tools/` and call existing tools through stable CLI/library boundaries |
| Current runtime artifacts | Expanded below by artifact class | Write only `data/trend_monitoring/*` in the first implementation |
| Current scaling constraints | Expanded below for universe, sharding, cache, sweep, and provider limits | Prototype with 500 monitored names max, 75 high-priority names max, 30 action-review names max |
| MCP workflow principles | Expanded below into a principle-to-trading mapping | Copy workflow principles into a local minimal trading harness; do not import the full `mcp-agents-workflow` runtime initially |
| Trading contract design | Expanded below with record categories and derived outputs | Contracts are code/data schemas first; no prompt/persona/provider contract change is approved by this document |
| Daily monitoring architecture | Expanded below into phases, artifacts, and action boundaries | Start with end-of-day daily extraction; pre-market/intraday are later extensions |
| Safety and state boundaries | Expanded below with allowed and forbidden writes | No automatic candidate, watchlist, portfolio, trade-history, or broker-state mutation in first slice |
| Test strategy | Expanded below by slice | Use exact pytest and smoke commands listed in the validation section |
| Open decisions | Reduced to deferrable choices | No blocking product/research decision remains for first implementation planning |

## Locked Implementation Decisions

These defaults turn the research into an implementation-ready target without
approving code changes by themselves.

1. **Market-beat analogue**: V2 should rank trends by a deterministic
   `recent_edge_score`, not by model intuition. The score should be a weighted
   blend of existing, source-backed evidence:
   - 40% recent support expected edge and support score components from
     `compute_support_level_score`;
   - 25% post-signal forward price reaction or simulation validation return when
     such evidence exists;
   - 20% watchlist/candidate fitness improvement or degradation over the most
     recent comparable artifact window;
   - 15% liquidity, volume, and freshness quality.
   Missing subcomponents should be recorded as `needs_data`, not inferred.
2. **Harness reuse**: first implementation should build a local
   `tools/trend_phase_ledger.py` mini harness that borrows principles from
   `mcp-agents-workflow`: shared contract, source coverage, manager-owned
   derived fields, verifier findings, critic patches, and convergence criteria.
   It should not import or vendor the full `mcp-agents-workflow` runtime.
3. **Schedule**: first implementation is end-of-day after market close. Morning
   and intraday monitoring should consume the ledger later but are not initial
   requirements.
4. **Scale target**: first dry-run implementation should support up to 500
   monitored tickers, cap expensive refreshes at 75 high-priority tickers, and
   cap human action-review output at 30 tickers per run.
5. **Runtime target**: normal dry-run target is 45 minutes or less on cached and
   mixed-cache runs. A run that exceeds 90 minutes should exit `completed_with_gaps`
   or `failed` with partial artifacts rather than silently continuing.
6. **Cache windows**: daily market snapshot data must be same trading day;
   universe screen cache may be up to three trading days old for broad gating;
   weekly graph/support artifacts may inform `recent_edge_score` but cannot make
   a trend actionable unless paired with same-day price/liquidity evidence.
7. **Write boundary**: first implementation writes only under
   `data/trend_monitoring/`. `ADD_TO_CANDIDATE_POOL` remains a recommendation,
   not an automatic `data/candidates.json` write. Candidate writes require a
   later explicit tool call through `tools/candidate_tracker.py`.
8. **Approval boundary**: this document approves no provider/model change, no
   persona rewrite, and no prompt-specific producer/verifier/critic contract.
   Initial contracts should be Python enums, JSON schemas, and deterministic
   tests only.

### Locked `recent_edge_score` Rules

`recent_edge_score` is a normalized `0.0` to `100.0` score.

- Each available component is converted to the `0.0` to `100.0` range with these
  formulas before weighting:
  - support component: use `compute_support_level_score(...).support_score`
    directly when source-backed support evidence exists;
  - post-signal or simulation component:
    `50 + clamp(return_pct, -20, 20) * 2.5`, so `-20% = 0`, `0% = 50`,
    and `+20% = 100`;
  - watchlist/candidate fitness component:
    `50 + clamp(delta_pct, -25, 25) * 2`, so `-25 = 0`, `0 = 50`,
    and `+25 = 100`;
  - liquidity/freshness component: start at `100`, subtract `30` for partial
    provider data, `30` for stale cache, `20` for below-target average volume,
    and `20` for missing ATR/volatility data, then clamp to `0..100`.
- Scoring source fields are locked:
  - `return_pct` source precedence is `simulation_validation_return_pct`, then
    `post_signal_return_pct`; if neither exists, add `post_signal_return` to
    `missing_edge_components[]`;
  - `delta_pct` source precedence is `watchlist_fitness_delta_pct`, then
    `candidate_fitness_delta_pct`; if neither exists, add `fitness_delta` to
    `missing_edge_components[]`;
  - broad daily eligibility uses `universe_screener.MIN_AVG_VOL = 500_000` as
    the below-target average-volume threshold;
  - high-priority refresh eligibility may additionally use
    `velocity_scanner.MIN_AVG_VOLUME = 2_000_000`, but that higher threshold
    must not block broad trend extraction.
- Every scoring component must store the exact source field in `metrics` and
  cite it with `source_refs`.
- `tools/trend_extractor.py` owns the proposed `recent_edge_score` calculation
  before ledger merge. It must import `compute_support_level_score` from
  `tools/shared_utils.py` and must not duplicate support-score logic.
- `tools/daily_trend_snapshot.py` captures raw source/cache values;
  `tools/trend_extractor.py` copies the selected source values into each
  record's `metrics`; `tools/trend_validator.py` verifies the selected fields,
  normalized component scores, weights, and `source_refs` provenance.
- `metrics.recent_edge_score_inputs` is required for every non-null
  `recent_edge_score` and must include one entry per available or missing
  component: `component`, `source_field`, `raw_value`, `normalized_value`,
  `weight`, and `missing`.
- Component weights are: support expected edge/support score `0.40`,
  post-signal reaction or simulation validation return `0.25`,
  watchlist/candidate fitness delta `0.20`, and liquidity/freshness quality
  `0.15`.
- Missing components are excluded from the denominator and listed in
  `missing_edge_components[]`.
- If all components are missing, set `recent_edge_score: null`,
  `readiness: needs_data`, `source_quality: partial`, and include at least one
  `DATA_PROVIDER_GAP` or `INSUFFICIENT_RECENT_EDGE` validation finding.
- Priority thresholds are: `P1 >= 80` with `source_quality: fresh`, `P2 >= 65`,
  `P3 >= 50`, and `P4 < 50` or monitor-only.
- Readiness thresholds are: `accepted` for score `>= 65` with no blocking
  finding, `monitor_only` for score `>= 50` or informational categories,
  `blocked` for any hard strategy/data gate, `needs_data` for missing required
  evidence, and `failed` for schema or source-contract violation.

## Current Agentic-Trading Shape

The current project is already more than a prompt collection. It has:

- deterministic Python tools for daily status, screening, support analysis,
  backtesting, graph-policy scoring, order-state management, and artifact
  validation;
- workflow YAML definitions that chain gatherer, analyst, critic, validator, and
  fan-out phases;
- generated operational artifacts under `data/`, root reports, `morning-work/`,
  and ticker-specific folders;
- a live-state boundary around `portfolio.json` and `trade_history.json`;
- a documented learned graph policy that distinguishes live decision weights from
  diagnostic-only weights.

The strongest V2 foundation is already present: the system has deterministic
market-data collectors and strategy gates. The weakness is that the workflows do
not yet have the same contract-backed loop discipline as the `mcp-agents-workflow`
phase-ledger harness.

### Current Daily Capabilities

`daily_analyzer.py` is the current daily operations surface. It can process live
state changes, print market/portfolio status, recommend deployments, evaluate
watchlist fitness, run candidate screening, and reconcile broker state.

`status-workflow.yaml` and `morning-briefing-workflow.yaml` cover daily reporting
and morning analysis. The morning workflow already has parallel per-ticker
analysis with fan-out and partial completion tolerance. `morning_gatherer_v2.py`
adds an early 100+ ticker scaled data-collection design through sector shards.

These are useful pieces for V2, but they are still report-centric. They do not
persist a daily trend ledger with explicit categories, source coverage, verifier
findings, critic patches, convergence status, and durable lineage from raw market
signals to monitored trend state.

### Current Universe-Scale Capabilities

The repo already has multiple universe-scale paths:

- `universe_screener.py` scans the full US stock universe from `data/us_universe.json`
  with price, liquidity, swing, and consistency gates.
- `universe_prescreener.py` and tournament/backtest tooling rank support strategy
  candidates.
- `sim_ranked_screener.py` takes top universe passers and backtests a top-N set,
  currently defaulting around top 30.
- `neural_candidate_discoverer.py` can scan a large universe through learned
  graph dip policy and intraday sweeps, but the output is still a top-N discovery
  artifact.

The project can already look at hundreds or thousands of stocks mechanically.
The V2 gap is not raw screening breadth. The gap is durable daily trend
extraction and monitoring state that keeps more than the final top 30 alive.

### Current Workflow Gap

The current YAML workflows mostly execute a linear sequence:

1. gather or simulate;
2. analyze or validate;
3. produce reports and JSON artifacts;
4. sometimes run a critic or pre-critic.

They do not yet enforce:

- a phase classification contract for every emitted trend or monitoring record;
- a manager-owned ledger format with stable IDs and derived outputs;
- source coverage policies against raw market evidence;
- producer/verifier/critic convergence before a phase output is accepted;
- downstream subscribed phase outputs with lineage from each prior phase;
- structured loop failure reporting when a daily trend run cannot converge.

That means a report may be useful for human review, but it is not yet a durable
workflow primitive that can safely drive daily monitoring across hundreds of
symbols.

## Current Workflow Inventory

The current workflow set is broad and operationally useful, but each workflow is
still domain-specific and report/artifact oriented. None of the inspected
`agentic-trading` YAML workflows currently declares a contract-backed phase-ledger
loop like `mcp-agents-workflow`.

### Daily Operations Workflows

`morning-briefing-workflow.yaml`:

- gathers morning tool output and condensed data;
- fans out per-ticker analysis with concurrency 12 and partial completion allowed;
- assembles a unified morning briefing;
- runs a review phase for math, logic, and coverage;
- already contains the strongest local pattern for scaling human-readable per-ticker
  analysis.

`status-workflow.yaml`:

- collects live status data;
- uses deterministic pre-analysis before qualitative report text;
- uses deterministic pre-critic before qualitative review text;
- is useful as a reporting consumer for V2 trend deltas, but should not own the
  V2 trend ledger.

`market-context-workflow.yaml`:

- gathers market context;
- analyzes and reviews market regime;
- should become an input provider to V2 trend readiness, especially for regime
  conflict, sector rotation, and risk-off gating.

`news-sweep-workflow.yaml`:

- sweeps news, analyzes, and reviews;
- should be a source of event-driven trend flags, but not the sole evidence for
  numerical trend classification.

### Candidate and Watchlist Workflows

`surgical-candidate-workflow.yaml`:

- screens, verifies, critiques, and simulates candidates;
- has a more explicit verification/critic shape than most workflows;
- still lacks a shared manager-owned ledger and convergence contract.

`sim-ranked-candidate-workflow.yaml`:

- replaces score-first ranking with simulation-first candidate selection;
- simulates top universe passers and mechanically validates portfolio-level flags;
- narrows to a top set rather than maintaining a broad monitored trend pool.

`watchlist-fitness-workflow.yaml`:

- evaluates current watchlist fit and removal candidates;
- is likely the best existing consumer for V2 "deteriorated trend" records.

`deep-dive-workflow.yaml`:

- collects, compiles, and reviews one deeper ticker research packet;
- should remain a promoted-action workflow rather than the broad daily monitor.

### Position and Review Workflows

`exit-review-workflow.yaml`:

- gathers, analyzes, and reviews exit decisions;
- should consume V2 trend deterioration and event-risk context for active positions.

`cycle-timing-workflow.yaml`:

- gathers and analyzes cycle timing, then reviews;
- provides cycle efficiency evidence that should be normalized into trend validation.

`knowledge-consolidation-workflow.yaml`:

- consolidates generated findings and ticker memory;
- could consume accepted V2 trends after review, but should not be required for
  daily trend extraction to run.

### Backtest Workflows

`backtest-surgical-workflow.yaml` and `backtest-dip-workflow.yaml`:

- collect data, simulate, and report;
- provide evidence for recent market beats;
- are too expensive to run across hundreds of stocks daily unless V2 uses them
  selectively on promoted candidates.

## Current Tool Surface Map

The tool surface divides into six major families.

### Live State and Safety Tools

`portfolio_manager.py` is the supported writer for portfolio and trade state.
`portfolio_status.py`, `broker_reconciliation.py`, `order_proximity_monitor.py`,
`alignment_checker.py`, `bullet_drift_report.py`, and `daily_analyzer.py` read
or summarize live state. Any V2 workflow that writes to `portfolio.json` or
`trade_history.json` outside the supported manager boundary would violate the
current project contract.

Risk implication: V2 should write trend-monitoring artifacts, candidate artifacts,
or reports first. It should not place, fill, sell, cancel, pause, or unpause orders
without explicit operator workflow and existing state APIs.

### Market Data and Feature Tools

`market_pulse.py`, `shared_regime.py`, `technical_scanner.py`,
`daily_range_analyzer.py`, `relative_strength.py`, `volume_profile.py`,
`institutional_flow.py`, `options_flow.py`, `short_interest.py`,
`earnings_analyzer.py`, and `earnings_gate.py` provide raw market context and
strategy gates.

V2 should treat these as deterministic source producers. The LLM-facing workflow
should consume their normalized outputs, not re-derive indicators from prose.

### Support, Wick, and Bullet Tools

`wick_offset_analyzer.py`, `bullet_recommender.py`, `support_parameter_sweeper.py`,
`resistance_parameter_sweeper.py`, `bounce_parameter_sweeper.py`,
`entry_parameter_sweeper.py`, `sell_target_calculator.py`, `range_reset_analyzer.py`,
and `range_uplift_analyzer.py` produce support, resistance, entry, exit, and
ladder evidence.

V2 should reuse these outputs as source evidence for support retests and
mean-reversion pullbacks. It should not make a trend "actionable" unless the
support ladder, hold-rate, earnings, and regime constraints are consistent.

### Candidate Discovery and Ranking Tools

`universe_screener.py`, `universe_prescreener.py`, `surgical_screener.py`,
`surgical_filter.py`, `sim_ranked_screener.py`, `candidate_sim_gate.py`,
`candidate_tracker.py`, `velocity_scanner.py`, `velocity_candidate_research.py`,
and `watchlist_tournament.py` cover discovery, ranking, and promotion.

The main V2 design issue is that several paths are top-N oriented. They are useful
for final promotion, but daily monitoring needs a larger persistent candidate
state where symbols can remain watchable without competing for immediate top-30
onboarding.

### Learned Graph Policy and Artifact Validation Tools

`neural_candidate_discoverer.py`, `neural_support_discoverer.py`,
`neural_support_evaluator.py`, `neural_watchlist_sweeper.py`,
`neural_dip_evaluator.py`, `neural_dip_backtester.py`, `neural_order_adjuster.py`,
`graph_builder.py`, `graph_engine.py`, `weight_learner.py`,
`neural_artifact_validator.py`, `artifact_promoter.py`, and `model_complexity_gate.py`
form the learned graph policy layer.

The existing policy contract is valuable: it separates live decision weights from
diagnostic weights and fails closed on malformed artifacts. V2 should copy that
discipline for trend-ledger artifacts. A daily trend record should not be accepted
just because an artifact exists; the artifact must be fresh, valid, and compatible
with the consuming decision.

### Backtest, Calibration, and Performance Tools

`backtest_engine.py`, `backtest_data_collector.py`, `backtest_reporter.py`,
`historical_trade_trainer.py`, `prediction_ledger.py`, `probability_calibrator.py`,
`multi_period_scorer.py`, `watchlist_tournament.py`, and `portfolio_stress_test.py`
produce evidence about whether a pattern has worked recently.

These tools are too expensive to run indiscriminately every day over hundreds of
tickers, but their outputs are exactly what "recent market beats" should be
grounded in. V2 needs a tiered policy: cheap daily features for broad monitoring,
selective backtest refresh for promoted candidates, and weekly/deeper refresh for
parameter-heavy artifacts.

## Current Artifact and Data Map

The current repo already persists many operational artifacts:

- live state: `portfolio.json`, `trade_history.json`, `.portfolio.lock`;
- active reports: `morning-briefing.md`, `status-report.md`, `watchlist-fitness.md`,
  `candidate-final.md`, `portfolio_status.md`, and similar root reports;
- universe artifacts: `data/us_universe.json`, `data/universe_screen_cache.json`,
  `data/universe_prescreen_results.json`, `data/.tier2_pool.json`;
- strategy sweep artifacts: `data/sweep_results.json`,
  `data/support_sweep_results.json`, `data/resistance_sweep_results.json`,
  `data/bounce_sweep_results.json`, `data/entry_sweep_results.json`,
  `data/regime_exit_sweep_results.json`, `data/sweep_support_levels.json`;
- graph artifacts: `data/synapse_weights.json`, `data/ticker_profiles.json`,
  `data/graph_state.json`, `data/neural_candidates.json`,
  `data/neural_support_candidates.json`, `data/neural_watchlist_profiles.json`;
- calibration and monitoring artifacts: `data/probability_calibration.json`,
  `data/prediction_ledger.json`, `data/proximity_alerts_state.json`,
  `data/reoptimize_history.json`, `data/tournament_results.json`;
- per-ticker artifacts: `tickers/<TICKER>/identity.md`, `memory.md`,
  `wick_analysis.md`, and cycle/support-derived files.

V2 should not scatter new trend state across root markdown files. It should add a
single coherent trend-monitoring namespace under `data/trend_monitoring/` and keep
human reports as derived views.

## Current Bottlenecks and Failure Modes

### Weekly Cadence Bottleneck

The current system has daily reports and some daily screening, but the heavier
optimization path is weekly. That creates a mismatch: support levels, swing
behavior, relative strength, volatility, and sector rotation can change daily,
while promotion artifacts may be refreshed weekly.

V2 should not try to run the whole weekly optimizer daily. It should define a
daily delta layer that detects when weekly assumptions are stale enough to trigger
focused refresh, monitoring, or promotion.

### Top-N Narrowing Bottleneck

The current discovery path repeatedly narrows to top 30 or top N candidates. That
is appropriate for watchlist size and human action, but not for monitoring. A
stock can be worth monitoring before it is worth onboarding.

V2 should separate:

- monitored universe: hundreds of candidates with lightweight daily state;
- promoted candidates: a smaller set needing simulation, deep dive, or watchlist
  action;
- actionable trade state: existing portfolio/watchlist/order workflows.

### Report-Only Output Bottleneck

Morning/status outputs are optimized for human review. They do not provide a
durable, structured, source-backed trend state that can be read by the next run.

V2 should make the structured ledger primary and markdown reports secondary.

### Expensive Sweep Bottleneck

Parameter sweeps, intraday discovery, simulation, and deep support analysis are
expensive. Running them blindly over hundreds of stocks daily will be slow and
data-provider fragile.

V2 should use staged gates:

1. cheap daily data freshness and eligibility;
2. cheap trend feature extraction;
3. medium-cost support and event validation;
4. expensive simulation or intraday graph policy only for promoted candidates.

### Data Provider and Cache Staleness Bottleneck

The README already warns that network-backed commands can fail or vary because
of provider throttling, empty data, or schema changes. `universe_screener.py`
also treats cache age as a first-class issue. V2 must model data quality as part
of the ledger instead of hiding it in logs.

Suggested data-quality fields:

- `source_status`: `fresh`, `cached`, `stale`, `partial`, `failed`;
- `source_age_days`;
- `missing_required_fields`;
- `provider_error`;
- `fallback_used`;
- `decision_allowed`: boolean manager-derived field.

### Automatic Write Risk

Some current tools can write portfolio/watchlist artifacts. `watchlist_tournament.py`
has action execution paths, and `batch_onboard.py` can add to the watchlist and
create ticker files. V2 must be explicit about which artifacts it may update
automatically.

The default V2 posture should be: detect and recommend broadly; mutate narrowly
and only through existing approved paths.

## MCP Harness Principles Worth Porting

The `mcp-agents-workflow` implementation is not just "more agents." The relevant
principles are structural.

### 1. Source Universe First

Each phase receives an explicit source universe and must account for it according
to a coverage mode. For trading V2, the source universe should be a daily market
snapshot, not a prose prompt. Candidate examples:

- daily OHLCV and intraday summaries;
- prior trend ledger state;
- current watchlist and position state;
- sector/regime context;
- earnings and event gates;
- recent backtest or sweep evidence;
- current opportunity labels produced by deterministic scanners.

### 2. Phase-Specific Category Contracts

The universal contract stays generic; phase-specific behavior lives in a category
contract. For trading, this avoids hard-coding every opportunity type into
prompts. It also makes the daily pipeline inspectable.

Candidate category contracts:

- `trend_extraction`: `BREAKOUT_ACCELERATION`, `MEAN_REVERSION_PULLBACK`,
  `SUPPORT_RETEST`, `VOLATILITY_EXPANSION`, `RELATIVE_STRENGTH_ROTATION`,
  `EVENT_DRIVEN_SETUP`, `DORMANT_OR_NO_ACTION`.
- `trend_validation`: `VALIDATED_EDGE`, `STALE_EDGE`, `INSUFFICIENT_LIQUIDITY`,
  `EARNINGS_BLOCKED`, `REGIME_CONFLICT`, `LADDER_DEPTH_FAILURE`,
  `OVERLAP_OR_CONCENTRATION`.
- `monitoring_action`: `WATCH_DAILY`, `WATCH_INTRADAY`, `PROMOTE_TO_DEEP_DIVE`,
  `PROMOTE_TO_SIMULATION`, `ADD_TO_CANDIDATE_POOL`, `COOLDOWN_OR_DROP`,
  `NO_CHANGE`.

### 3. Producer, Verifier, Critic Loop

The core loop should be adapted as:

- producer: emits structured trend records from deterministic source artifacts;
- manager: assigns stable IDs, validates schema/category/detail shape, enforces
  source coverage, computes derived outputs;
- verifier: checks missing records, unsupported claims, stale evidence, invalid
  category choices, and strategy-gate contradictions;
- critic: accepts or rejects verifier findings and emits repairs;
- loop stops only when verifier findings and critic patches are empty.

This is directly applicable to trading signals because false positives and stale
evidence are the main failure modes when scaling from 30 names to hundreds.

### 4. Derived Outputs Are Manager-Owned

The mcp contract separates source-backed producer records from manager-owned
derived outputs. That is important for trading. Examples of manager-owned derived
outputs:

- daily trend readiness: `ready`, `needs_more_data`, `blocked_by_event`,
  `monitor_only`;
- final priority tier;
- monitoring cadence;
- risk flags;
- max daily adds/promotions;
- top-N display slices for humans.

The producer should not invent those final decisions when they can be computed
mechanically from source-backed records.

### 5. Subscribed Phase Outputs

V2 should use explicit phase subscriptions rather than informal file chaining.
For example:

- daily universe snapshot feeds trend extraction;
- trend extraction feeds strategy validation;
- strategy validation feeds monitoring action planning;
- monitoring action planning feeds status/morning reporting;
- accepted monitoring actions feed the next day's prior-state input.

This mirrors the `subscribed_phase_outputs` pattern in the codebase-grounding
workflow and is a strong fit for daily market-state evolution.

### 6. Explicit Convergence and Failure Reporting

The mcp harness treats non-convergence as a first-class failure, not a vague bad
report. For trading V2, this matters because the absence of a clean daily signal
can mean:

- market data was incomplete;
- a ticker had conflicting signals;
- the verifier found unsupported trend claims;
- a critic could not repair the trend record from source evidence;
- source artifacts were stale or incompatible.

V2 should emit a structured daily run status:

```json
{
  "run_status": "completed_with_gaps",
  "as_of_date": "2026-05-31",
  "source_universe_count": 642,
  "accepted_trend_count": 117,
  "blocked_trend_count": 38,
  "failed_record_count": 9,
  "failure_classes": ["stale_support_artifact", "provider_partial_data"]
}
```

### 7. Role Capability Boundaries

The mcp harness distinguishes role capabilities. Code-project phases can allow
file read/search while forbidding writes. Trading V2 should use the same boundary:

- deterministic collectors can write daily snapshot artifacts;
- producers can write proposed trend records only;
- verifiers can read artifacts and produce findings;
- critics can produce patches to the trend ledger;
- only approved operational tools can mutate live portfolio or trade state.

### 8. Manager-Owned IDs and Patch Semantics

The producer should not choose final IDs. A manager should allocate IDs such as
`TRD-001`, `VAL-001`, and `ACT-001`, validate detail shapes, and apply patches
deterministically. This matters when hundreds of ticker records are updated daily:
stable IDs, status transitions, and patch history are required for trend aging.

### Principle-to-Trading Mapping

| MCP harness principle | Trading V2 equivalent | Why it matters |
| :--- | :--- | :--- |
| Source universe | Daily market snapshot plus prior trend state | Prevents trend claims from being detached from current market evidence |
| Phase classification contract | Trend, validation, and monitoring category contracts | Keeps opportunity types explicit and testable |
| Producer ledger | Proposed trend records | Captures broad daily discoveries without immediate action |
| Verifier findings | Unsupported, stale, missing, or contradictory trend findings | Controls false positives at scale |
| Critic patches | Accepted repairs to trend records | Avoids rerunning full extraction for small defects |
| Manager-owned derived outputs | readiness, priority, cadence, action tier | Keeps final decisions mechanical and auditable |
| Subscribed phase outputs | snapshot -> trends -> validation -> actions -> reports | Creates durable lineage across daily phases |
| Convergence rule | no verifier findings and no critic patches | Prevents accepting an unverified daily trend ledger |
| Failure class | data quality, stale artifact, nonconvergence, contract violation | Makes operational failures actionable |

## Feasibility Judgment

Yes, the workflow principles can be brought into `agentic-trading`, but the right
move is to port the principles and a minimal harness shape, not copy the full
software-delivery workflow domain.

The current trading codebase already has:

- broad market scanners;
- report generation;
- stateful portfolio tools;
- artifact validators;
- trend-adjacent scoring and graph-policy tools;
- a scaled gatherer prototype;
- enough tests to support incremental hardening.

The missing layer is a trading-native phase-ledger harness that turns daily
screening output into durable, source-backed, verified trend records.

## V2 Conceptual Architecture

V2 should be a monitoring system layered on top of the existing trading system,
not a replacement for the current strategy tools.

### Layer 1: Source Collection

Collects normalized, cheap, daily source evidence:

- ticker universe and eligibility;
- current price, volume, volatility, and daily/intraday movement;
- monthly swing and consistency;
- sector and regime;
- earnings/event status;
- current support/resistance metadata where available;
- current portfolio/watchlist/candidate overlap;
- prior trend status.

This layer can be mostly deterministic Python.

### Layer 2: Trend Extraction

Classifies daily trend candidates from source evidence. This should start
mechanical and narrow:

- support retest near known active levels;
- fresh mean-reversion pullback inside strategy bands;
- relative-strength breakout from the monitored pool;
- volatility expansion with volume confirmation;
- event-driven setup requiring review;
- trend deterioration for existing monitored names.

This layer writes trend records, not trade decisions.

### Layer 3: Validation and Contract Enforcement

Checks each trend record against strategy gates and data quality:

- source evidence present;
- data fresh enough;
- liquidity still valid;
- earnings/event gate clear or explicitly blocked;
- current regime does not contradict the action;
- support ladder exists when the trend claims bullet-strategy fit;
- recent evidence supports priority;
- no forbidden overlap or concentration issue.

### Layer 4: Monitoring Action Planning

Turns validated trends into monitoring actions:

- keep in broad monitored pool;
- watch daily;
- watch intraday;
- run focused simulation;
- run deep dive;
- add to candidate pool;
- recommend human review for watchlist onboarding;
- cool down or drop from monitoring.

### Layer 5: Reporting and Human Review

Produces human-readable markdown for morning/status workflows:

- top new opportunities;
- strongest upgrades;
- blocked opportunities and why;
- deteriorating watchlist names;
- trend deltas since prior run;
- recommended next workflow for each promoted ticker.

The report should be a view of the ledger, not the primary data source.

### Initial V2 Module and Entry-Point Map

The first follow-up implementation plan should target the deterministic tools,
schemas, fixtures, tests, and standalone reports in this map. Workflow YAML and
`.workflow/agents/*` files remain approval-gated targets for a later slice.

| File | Responsibility |
| :--- | :--- |
| `tools/trend_contracts.py` | Enum values, schema constants, stable status/action/category names, and validation helpers |
| `tools/daily_trend_snapshot.py` | Build `daily-market-snapshot.json` from current data, cache artifacts, and portfolio/watchlist/candidate state |
| `tools/trend_ledger.py` | Load prior ledger, allocate stable IDs, merge daily records, apply transitions, and write run history |
| `tools/trend_extractor.py` | Produce source-backed proposed trend records from the snapshot and prior ledger; compute `recent_edge_score` using `tools/shared_utils.py::compute_support_level_score` for support evidence |
| `tools/trend_validator.py` | Produce validation findings for unsupported, stale, contradictory, duplicate, missing, or score-provenance-invalid records |
| `tools/trend_critic.py` | Convert actionable validation findings into deterministic patch operations |
| `tools/trend_phase_ledger.py` | Run the local producer/verifier/critic loop and enforce convergence or structured nonconvergence |
| `tools/trend_action_planner.py` | Convert accepted trends into monitoring actions without mutating candidate, watchlist, portfolio, or trade state |
| `tools/trend_reporter.py` | Render markdown reports from ledger/actions without recomputing decisions |
| `workflows/daily-trend-monitoring-workflow.yaml` | Deferred approval-gated target for chaining snapshot, extraction, validation, action planning, and report generation |
| `.workflow/agents/trend-snapshot-builder.md` | Deferred approval-gated workflow agent instructions for running the snapshot tool without adding qualitative judgment |
| `.workflow/agents/trend-ledger-manager.md` | Deferred approval-gated workflow agent instructions for running the deterministic ledger loop |
| `.workflow/agents/trend-action-planner.md` | Deferred approval-gated workflow agent instructions for rendering recommendation-only monitoring actions |
| `.workflow/agents/trend-reporter.md` | Deferred approval-gated workflow agent instructions for rendering reports from existing artifacts only |
| `schemas/trend_monitoring/daily-market-snapshot.schema.json` | Schema for normalized source universe snapshots |
| `schemas/trend_monitoring/trend-ledger.schema.json` | Schema for accepted, blocked, stale, and retired trend records |
| `schemas/trend_monitoring/validation-findings.schema.json` | Schema for verifier findings |
| `schemas/trend_monitoring/critic-patches.schema.json` | Schema for deterministic repair patches |
| `schemas/trend_monitoring/monitoring-actions.schema.json` | Schema for recommendation-only monitoring actions |
| `schemas/trend_monitoring/run-status.schema.json` | Schema for phase/run status and failure classes |

Initial CLI shape:

```bash
python3 tools/daily_trend_snapshot.py --as-of 2026-05-31 --output-dir data/trend_monitoring
python3 tools/trend_phase_ledger.py --as-of 2026-05-31 --snapshot data/trend_monitoring/daily-market-snapshot.json --output-dir data/trend_monitoring
python3 tools/trend_action_planner.py --as-of 2026-05-31 --ledger data/trend_monitoring/trend-ledger.json --output-dir data/trend_monitoring
python3 tools/trend_reporter.py --as-of 2026-05-31 --ledger data/trend_monitoring/trend-ledger.json --output-dir data/trend_monitoring
```

Production/default output is `data/trend_monitoring/`. Offline tests and smoke
runs must pass `--output-dir` pointing at a temp directory to avoid local
workspace noise.

Locked CLI behavior:

- `--fixture <dir>` disables all live/provider reads and reads only fixture files
  under the provided directory;
- `--output-dir <dir>` is created if missing and is the only write root for V2
  artifacts in that invocation;
- existing files in `--output-dir` may be atomically replaced for the same
  `as_of_date`;
- exit code `0`: current phase completed, completed with gaps, or validly left
  the aggregate run in `running` for downstream phases;
- exit code `1`: schema/source validation failure or nonconvergence;
- exit code `2`: CLI usage or configuration error;
- human summaries go to stdout;
- validation and runtime errors go to stderr.

## Proposed V2 Daily Trend Workflow

### Workflow Name

`daily-trend-monitoring-workflow`

### Workflow YAML Contract

This contract is a deferred approval-gated design target. It should not be part
of the first follow-up implementation plan unless the user separately approves
workflow YAML and `.workflow/agents/*` changes.

`workflows/daily-trend-monitoring-workflow.yaml` should follow the existing repo
workflow shape: command execution lives in phase descriptions, and phases declare
agents, artifacts, dependencies, requirements, and timeouts.

```yaml
name: daily-trend-monitoring-workflow
description: >
  End-of-day trend monitoring dry run. Builds a source-backed market snapshot,
  produces and validates a trend ledger, plans recommendation-only monitoring
  actions, and renders a report without mutating portfolio, trade, candidate, or
  watchlist state.

version: "1.0.0"

phases:
  - id: snapshot
    name: Daily Trend Snapshot
    description: Run daily_trend_snapshot.py to build data/trend_monitoring/daily-market-snapshot.json and daily-market-snapshot.md.
    agent: trend-snapshot-builder
    artifacts:
      - data/trend_monitoring/daily-market-snapshot.json
      - data/trend_monitoring/daily-market-snapshot.md
      - data/trend_monitoring/run-status.json
    timeout_minutes: 20

  - id: ledger
    name: Trend Ledger Validation
    description: Run trend_phase_ledger.py to extract, validate, patch, and converge trend-ledger.json from the snapshot.
    agent: trend-ledger-manager
    depends_on:
      - snapshot
    requires:
      - data/trend_monitoring/daily-market-snapshot.json
    artifacts:
      - data/trend_monitoring/trend-ledger.json
      - data/trend_monitoring/validation-findings.json
      - data/trend_monitoring/critic-patches.json
      - data/trend_monitoring/run-status.json
    timeout_minutes: 45

  - id: actions
    name: Monitoring Action Planning
    description: Run trend_action_planner.py to create recommendation-only monitoring-actions.json and monitoring-actions.md.
    agent: trend-action-planner
    depends_on:
      - ledger
    requires:
      - data/trend_monitoring/trend-ledger.json
    artifacts:
      - data/trend_monitoring/monitoring-actions.json
      - data/trend_monitoring/monitoring-actions.md
      - data/trend_monitoring/run-status.json
    timeout_minutes: 10

  - id: report
    name: Trend Monitoring Report
    description: Run trend_reporter.py to render trend-ledger.md and final human review summary from ledger/actions.
    agent: trend-reporter
    depends_on:
      - actions
    requires:
      - data/trend_monitoring/trend-ledger.json
      - data/trend_monitoring/monitoring-actions.json
    artifacts:
      - data/trend_monitoring/trend-ledger.md
      - data/trend_monitoring/monitoring-actions.md
      - data/trend_monitoring/run-status.json
    timeout_minutes: 10

settings:
  max_fix_iterations: 0
  require_approval: false
  timeout_minutes: 90
```

### Phase 1: Build Daily Market Snapshot

Purpose: mechanically gather and normalize the market source universe.

Inputs:

- `data/us_universe.json`
- `data/universe_screen_cache.json` or a refreshed scan
- portfolio/watchlist state
- sector and regime data
- earnings/event gates
- recent support and sweep artifacts
- prior `data/trend_monitoring/trend-ledger.json`

Outputs:

- `data/trend_monitoring/daily-market-snapshot.json`
- `data/trend_monitoring/daily-market-snapshot.md`

Notes:

- This phase should be deterministic Python first.
- It should fail closed when required market data is missing or stale.
- It should not mutate `portfolio.json` or `trade_history.json`.

### Phase 2: Extract Trend Candidates

Purpose: classify source-backed trend records across hundreds of symbols.

Candidate input size:

- broad universe passers after cheap mechanical gates;
- maximum 500 monitored symbols after cheap gates;
- maximum 75 high-priority symbols eligible for expensive refresh;
- maximum 30 symbols in human action-review output.

Output record shape:

```json
{
  "id": "TRD-001",
  "stable_key": "ABCD:MEAN_REVERSION_PULLBACK:support_12.30",
  "ticker": "ABCD",
  "trend_category": "MEAN_REVERSION_PULLBACK",
  "trend_status": "new",
  "detail": "MEAN_REVERSION_PULLBACK: current price is near decayed support while monthly swing and liquidity gates remain valid",
  "metrics": {
    "price": 12.34,
    "support": 12.3,
    "monthly_swing": 18.7
  },
  "recent_edge_score": 72.5,
  "missing_edge_components": [],
  "source_refs": [
    {
      "artifact": "data/trend_monitoring/daily-market-snapshot.json",
      "json_pointer": "/tickers/ABCD/price",
      "value": 12.34,
      "as_of_date": "2026-05-31",
      "freshness": "same_day",
      "claim_field": "/records/0/metrics/price"
    }
  ],
  "source_quote": ["ABCD price=12.34 as_of=2026-05-31"],
  "reason": "Source-backed daily trend candidate"
}
```

This phase should be a trading-native equivalent of a phase-ledger producer pass.

### Phase 3: Validate Strategy Fit

Purpose: reject or mark trends that do not fit the strategy today.

Validation categories:

- stale market data;
- stale support level;
- insufficient support ladder depth;
- earnings blackout;
- current risk-off conflict;
- poor liquidity;
- sector/correlation concentration;
- existing exposure overlap;
- insufficient recent cycle evidence;
- inconsistent intraday/daily evidence.

Output:

- patched/verified trend ledger;
- manager-owned derived readiness and risk flags.

### Phase 4: Plan Monitoring Actions

Purpose: convert verified trends into monitoring state, not immediate trades.

Action categories:

- `WATCH_DAILY`
- `WATCH_INTRADAY`
- `PROMOTE_TO_DEEP_DIVE`
- `PROMOTE_TO_SIMULATION`
- `ADD_TO_CANDIDATE_POOL`
- `COOLDOWN_OR_DROP`
- `NO_CHANGE`

Output:

- `data/trend_monitoring/monitoring-actions.json`
- `data/trend_monitoring/monitoring-actions.md`

This phase should keep portfolio mutation outside the workflow. Adding a ticker
to candidate tracking can remain explicit and auditable, but broker-state changes
must remain behind the existing portfolio manager boundary.

### Phase 5: Daily Reporting Slice

Purpose: summarize only the human-relevant deltas from the verified ledger.

Outputs:

- new trends by type;
- upgraded trends;
- deteriorated trends;
- event-blocked trends;
- watchlist promotions;
- stale candidates to drop;
- "why this changed today" lineage.

This should feed morning/status workflows rather than replace them.

## Trading-Native Contract Design

This section is approved for deterministic code, schema, fixture, and test
planning. Runtime workflow YAML, `.workflow/agents/*`, prompt, persona,
provider, or model changes still require separate approval before implementation.

### Trend Extraction Categories

`SUPPORT_RETEST`:

- source-backed claim that price is approaching, touching, or recovering from a
  known support level;
- requires current price, support level, distance, support freshness, and ladder
  metadata if available.

`MEAN_REVERSION_PULLBACK`:

- source-backed claim that price has pulled back within a historically tradable
  fluctuation band;
- requires swing/consistency evidence and a current pullback measure.

`RELATIVE_STRENGTH_ROTATION`:

- source-backed claim that the ticker is improving relative to sector, market, or
  monitored peers;
- should remain monitoring-only unless support/entry evidence also exists.

`VOLATILITY_EXPANSION`:

- source-backed claim that range/ATR/volume has expanded enough to become worth
  monitoring;
- requires liquidity and risk checks because volatility alone is not a buy signal.

`BREAKOUT_ACCELERATION`:

- source-backed claim that price is moving away from prior range with confirmation;
- likely outside the core mean-reversion action path, but useful as a watch or
  "do not chase" classification.

`EVENT_DRIVEN_SETUP`:

- source-backed claim tied to earnings, news, analyst action, filings, or sector
  catalysts;
- should default to review, not automatic promotion.

`DORMANT_OR_NO_ACTION`:

- explicit record for previously monitored symbols that no longer show a current
  trend; prevents silent disappearance from the daily ledger.

### Validation Finding Categories

`UNSUPPORTED_SOURCE_CLAIM`:

- trend detail references a price, support level, indicator, or event not present
  in source evidence.

`STALE_SOURCE_ARTIFACT`:

- trend depends on an artifact older than the allowed freshness window.

`DATA_PROVIDER_GAP`:

- required market data failed, returned empty, or was partial.

`STRATEGY_GATE_CONFLICT`:

- trend conflicts with earnings, risk-off, liquidity, price, support ladder,
  concentration, or overlap constraints.

`INSUFFICIENT_RECENT_EDGE`:

- trend has a shape but lacks recent market-beat evidence or recent validation.

`DUPLICATE_OR_FRAGMENTED_TREND`:

- multiple records describe the same ticker/trend without a clear reason.

`MISSING_REQUIRED_TREND`:

- source evidence clearly supports a trend category but producer omitted it.

### Monitoring Action Categories

`WATCH_DAILY`:

- keep symbol in broad daily monitoring; no immediate expensive refresh.

`WATCH_INTRADAY`:

- monitor more frequently because the trend is near a trigger.

`PROMOTE_TO_SIMULATION`:

- run focused simulation/backtest because cheap evidence crossed a threshold.

`PROMOTE_TO_DEEP_DIVE`:

- run qualitative research because event, thesis, or structural change matters.

`ADD_TO_CANDIDATE_POOL`:

- add to a candidate artifact for future review, not directly to live watchlist
  unless separately approved.

`RECOMMEND_WATCHLIST_REVIEW`:

- ask human/operator to consider onboarding, replacement, or drop.

`COOLDOWN_OR_DROP`:

- reduce monitoring priority because the edge went stale or failed validation.

`NO_CHANGE`:

- preserve prior monitoring state.

### Source Evidence Model

The mcp harness uses `source_quote`. Trading artifacts often have structured JSON
fields rather than prose quotes. V2 should support both:

```json
{
  "source_refs": [
    {
      "artifact": "data/trend_monitoring/daily-market-snapshot.json",
      "json_pointer": "/tickers/ABCD/price",
      "value": 12.34,
      "as_of_date": "2026-05-31",
      "freshness": "same_day",
      "claim_field": "/records/0/metrics/price"
    },
    {
      "artifact": "data/universe_screen_cache.json",
      "json_pointer": "/passers/123/median_swing",
      "value": 18.7,
      "as_of_date": "2026-05-30",
      "freshness": "fresh_cache",
      "claim_field": "/records/0/metrics/monthly_swing"
    }
  ],
  "source_quote": [
    "ABCD price=12.34 as_of=2026-05-31",
    "ABCD median_swing=18.7 consistency=91.0 avg_vol=2300000"
  ]
}
```

Locked evidence rule: `source_refs` JSON Pointers are the primary evidence
mechanism. `source_quote` is a human-readable mirror for operator review and
must not be the only evidence for a numerical claim.

Each `source_refs[]` item must include:

- `artifact`: repository-relative path;
- `json_pointer`: RFC 6901 pointer into the artifact;
- `value`: copied scalar or small object used by the claim;
- `as_of_date`: date attached to the source value when available;
- `freshness`: `same_day`, `fresh_cache`, `weekly_context`, `stale`, or `unknown`;
- `claim_field`: record field supported by the reference.

### Derived Outputs

Manager-owned derived outputs should include:

- `readiness`: `accepted`, `monitor_only`, `blocked`, `needs_data`, `failed`;
- `priority_tier`: `P1`, `P2`, `P3`, `P4`;
- `monitoring_cadence`: `intraday`, `daily`, `weekly`, `cooldown`;
- `recommended_next_workflow`: one of the existing workflow names or `none`;
- `blocked_reasons`: normalized list;
- `source_quality`: `fresh`, `partial`, `stale`, `failed`;
- `human_action_required`: boolean.

### Ledger Status Transitions

Each trend should have state transitions:

- `new`: first seen today;
- `persisting`: still valid from prior runs;
- `upgraded`: priority/cadence increased;
- `downgraded`: priority/cadence decreased;
- `blocked`: strategy/data gate blocks action;
- `stale`: no longer fresh enough;
- `retired`: removed after cooldown/aging rules.

This transition model is what lets V2 monitor hundreds of stocks without
reintroducing a top-30 bottleneck.

### Locked Artifact Schemas

`daily-market-snapshot.json`:

- root fields: `schema_version`, `run_id`, `as_of_date`, `generated_at`,
  `source_artifacts`, `universe`, `tickers`, `provider_failures`, `cache_status`;
- `universe`: `source`, `requested_count`, `eligible_count`, `excluded_count`,
  `exclusion_reasons`;
- `tickers.<TICKER>`: `ticker`, `sector`, `price`, `volume`, `avg_volume`, `atr`,
  `daily_change_pct`, `monthly_swing`, `consistency`, `liquidity_status`,
  `support_levels`, `earnings_status`, `portfolio_overlap`, `candidate_overlap`,
  `watchlist_overlap`, `source_refs`;
  `tickers` is an object keyed by ticker symbol, so source refs can use stable
  pointers such as `/tickers/ABCD/price`;
- `cache_status[]`: `artifact`, `as_of_date`, `age_trading_days`, `freshness`,
  `usable_for`;
- `provider_failures[]`: `provider`, `ticker`, `field`, `severity`, `message`.

`trend-ledger.json`:

- root fields: `schema_version`, `run_id`, `as_of_date`, `generated_at`,
  `prior_ledger_run_id`, `run_status`, `records`, `transitions`, `summary`;
- `records[]`: `id`, `stable_key`, `ticker`, `trend_category`, `trend_status`,
  `first_seen`, `last_seen`, `last_updated`, `detail`, `metrics`,
  `recent_edge_score`, `missing_edge_components`, `readiness`, `priority_tier`,
  `monitoring_cadence`, `recommended_next_workflow`, `blocked_reasons`, `source_quality`,
  `human_action_required`, `source_refs`, `source_quote`, `patch_history`;
- `stable_key`: deterministic key built from `ticker`, `trend_category`, and
  normalized setup anchor, for example `ABCD:SUPPORT_RETEST:support_12.30`;
- `metrics`: category-specific numerical evidence copied from snapshot/source
  artifacts, never invented by an LLM;
- `patch_history[]`: `patch_id`, `applied_at`, `source_finding_id`, `operation`,
  `field`, `old_value`, `new_value`.

`validation-findings.json`:

- root fields: `schema_version`, `run_id`, `as_of_date`, `generated_at`,
  `findings`, `summary`;
- `findings[]`: `id`, `record_id`, `ticker`, `finding_category`, `severity`,
  `field_path`, `message`, `source_refs`, `repairable`, `required_patch`,
  `blocks_readiness`;
- `severity`: `error`, `warning`, or `info`;
- `repairable`: true only when the corrected value is present in source evidence.

`critic-patches.json`:

- root fields: `schema_version`, `run_id`, `as_of_date`, `generated_at`,
  `patches`, `unrepaired_findings`;
- `patches[]`: `id`, `finding_id`, `record_id`, `operation`, `field_path`,
  `old_value`, `new_value`, `source_refs`, `applied`;
- `operation`: `replace`, `append_blocked_reason`, `downgrade_readiness`,
  `merge_duplicate`, `retire_record`, or `mark_needs_data`;
- `unrepaired_findings[]`: `finding_id`, `reason`.

`monitoring-actions.json`:

- root fields: `schema_version`, `run_id`, `as_of_date`, `generated_at`,
  `actions`, `summary`, `quotas`;
- `actions[]`: `id`, `trend_id`, `ticker`, `action_category`, `priority_tier`,
  `reason`, `next_workflow`, `human_approval_required`, `write_effect`,
  `source_refs`, `expires_after`;
- `write_effect`: always `none` in the first implementation;
- `quotas`: `max_review_actions`, `max_high_priority_refreshes`,
  `max_monitored_tickers`, `used_review_actions`, `used_high_priority_refreshes`.

`run-status.json`:

- root fields: `schema_version`, `run_id`, `as_of_date`, `started_at`,
  `finished_at`, `run_status`, `phase_statuses`, `source_universe_count`,
  `accepted_trend_count`, `blocked_trend_count`, `failed_record_count`,
  `failure_classes`, `artifact_paths`;
- `run_status`: `running`, `completed`, `completed_with_gaps`, `failed`, or
  `nonconverged`;
- `phase_statuses[]`: `phase`, `status`, `started_at`, `finished_at`,
  `input_artifacts`, `output_artifacts`, `errors`.

### Schema Validation Mechanism

V2 should use repository-local Python validation first, not a new runtime
dependency.

- `tools/trend_contracts.py` owns `SCHEMA_VERSION = 1`, enum sets, required-field
  definitions, score thresholds, and shared source-ref validation.
- Required helper functions are `validate_daily_market_snapshot`,
  `validate_trend_ledger`, `validate_validation_findings`,
  `validate_critic_patches`, `validate_monitoring_actions`, and
  `validate_run_status`.
- Each `validate_*` helper returns `list[TrendValidationIssue]`, does not mutate
  or coerce payloads, requires all required fields, validates enum values, and
  allows unknown fields for forward-compatible artifact extension.
- `TrendValidationIssue` has fields: `artifact`, `path`, `message`, and
  `severity = "ERROR"`. Error messages must include the artifact name and a
  JSON-style field path.
- `load_validated_trend_json(path, artifact_type)` loads a payload and raises
  `TrendValidationError` when any returned validation issue has severity
  `ERROR`.
- The six `.schema.json` files are documentation and test fixtures for the first
  implementation; they should mirror the Python validators but should not require
  adding `jsonschema` or `pydantic` to `pyproject.toml`.
- Tests must verify the Python validators and `.schema.json` files agree on
  required fields, enum values, and `schema_version`.

### Schema Contract Shape

Each `.schema.json` file should be a plain repository-local JSON object, not a
dependency-specific JSON Schema draft. Required top-level fields:

- `schema_version`: `1`;
- `artifact`: one of `daily-market-snapshot`, `trend-ledger`,
  `validation-findings`, `critic-patches`, `monitoring-actions`, or
  `run-status`;
- `required_root_fields`: list of required root field names;
- `required_item_fields`: object mapping collection fields to required fields
  for each item, for example `records`, `findings`, `patches`, or `actions`;
- `enum_fields`: object mapping field paths to allowed enum values;
- `field_types`: object mapping field paths to a local type grammar. A value is
  either a single type label such as `"number"` or an array of allowed labels
  such as `["number", "null"]` for nullable fields. Allowed labels are
  `object`, `array`, `string`, `number`, `integer`, `boolean`, and `null`.
- `numeric_bounds`: optional object mapping numeric field paths to inclusive
  `min` and `max` values.

Validators must reject wrong types and out-of-range bounded numbers without
coercing values. Initial numeric bounds:

- `trend-ledger.records[].recent_edge_score`: `0.0` to `100.0`, with
  `["number", "null"]` as its field type;
- `trend-ledger.records[].metrics.recent_edge_score_inputs[].normalized_value`:
  `0.0` to `100.0`, with `["number", "null"]` as its field type;
- `trend-ledger.records[].metrics.recent_edge_score_inputs[].weight`: `0.0` to
  `1.0`;
- count fields in `summary`, `quotas`, and `run-status`: integer `min: 0`.

Initial nullable field types:

- `trend-ledger.prior_ledger_run_id`: `["string", "null"]`; first run uses
  `null`;
- `validation-findings.findings[].record_id`: `["string", "null"]`; use `null`
  only for artifact-level findings or findings for a missing record that has no
  ledger record ID yet;
- `source_refs[].as_of_date`: `["string", "null"]`; use `null` when the source
  artifact has no date field;
- `run-status.finished_at`: `["string", "null"]`; use `null` while aggregate
  `run_status` is `running`;
- `run-status.phase_statuses[].started_at`: `["string", "null"]`; use `null`
  only for synthesized downstream `skipped` entries after an upstream `failed`
  or `nonconverged` status;
- `run-status.phase_statuses[].finished_at`: `["string", "null"]`; use `null`
  while that phase status is `running`.

Required nullable fields must be present with an explicit `null` value when
unknown or not applicable; they must not be omitted.

Initial required root fields match the lists in `Locked Artifact Schemas`.
Initial required item fields:

- `daily-market-snapshot`: `tickers.<TICKER>` requires `ticker`, `price`,
  `avg_volume`, `liquidity_status`, and `source_refs`;
- `trend-ledger`: `records[]` requires `id`, `stable_key`, `ticker`,
  `trend_category`, `trend_status`, `metrics`, `readiness`, `priority_tier`,
  `source_quality`, and `source_refs`;
- `validation-findings`: `findings[]` requires `id`, `record_id`,
  `finding_category`, `severity`, `field_path`, `message`, `source_refs`, and
  `blocks_readiness`;
- `critic-patches`: `patches[]` requires `id`, `finding_id`, `record_id`,
  `operation`, `field_path`, `source_refs`, and `applied`;
- `monitoring-actions`: `actions[]` requires `id`, `trend_id`, `ticker`,
  `action_category`, `priority_tier`, `human_approval_required`, `write_effect`,
  and `source_refs`;
- `run-status`: `phase_statuses[]` requires `phase`, `status`, `started_at`,
  `finished_at`, `input_artifacts`, `output_artifacts`, and `errors`.

Validation findings about missing source evidence must still include
`source_refs`. When the missing value itself has no source pointer, the finding
must cite the offending trend record path, source artifact path, or input
artifact path that proves the source gap.

Initial enum fields:

- `trend_category`: `SUPPORT_RETEST`, `MEAN_REVERSION_PULLBACK`,
  `RELATIVE_STRENGTH_ROTATION`, `VOLATILITY_EXPANSION`,
  `BREAKOUT_ACCELERATION`, `EVENT_DRIVEN_SETUP`, `DORMANT_OR_NO_ACTION`;
- `trend_status`: `new`, `persisting`, `upgraded`, `downgraded`, `blocked`,
  `stale`, `retired`;
- `readiness`: `accepted`, `monitor_only`, `blocked`, `needs_data`, `failed`;
- `priority_tier`: `P1`, `P2`, `P3`, `P4`;
- `monitoring_cadence`: `intraday`, `daily`, `weekly`, `cooldown`;
- `source_quality`: `fresh`, `partial`, `stale`, `failed`;
- `finding_category`: `UNSUPPORTED_SOURCE_CLAIM`, `STALE_SOURCE_ARTIFACT`,
  `DATA_PROVIDER_GAP`, `STRATEGY_GATE_CONFLICT`,
  `INSUFFICIENT_RECENT_EDGE`, `DUPLICATE_OR_FRAGMENTED_TREND`,
  `MISSING_REQUIRED_TREND`;
- `severity`: `error`, `warning`, `info`;
- `patch_operation`: `replace`, `append_blocked_reason`,
  `downgrade_readiness`, `merge_duplicate`, `retire_record`,
  `mark_needs_data`;
- `action_category`: `WATCH_DAILY`, `WATCH_INTRADAY`,
  `PROMOTE_TO_SIMULATION`, `PROMOTE_TO_DEEP_DIVE`,
  `ADD_TO_CANDIDATE_POOL`, `RECOMMEND_WATCHLIST_REVIEW`,
  `COOLDOWN_OR_DROP`, `NO_CHANGE`;
- `write_effect`: `none`;
- `run_status`: `running`, `completed`, `completed_with_gaps`, `failed`,
  `nonconverged`;
- `phase_statuses[].status`: `running`, `completed`, `completed_with_gaps`,
  `failed`, `skipped`, `nonconverged`.

## Scale Architecture

### Universe Tiers

V2 should not treat all symbols equally each day. First implementation tiers:

| Tier | Size target | Refresh cadence | Purpose |
| :--- | :--- | :--- | :--- |
| Full universe | Thousands | Weekly or on demand | Maintain broad eligibility list |
| Daily eligible universe | Up to 1,500 | Daily cheap refresh | Liquidity, swing, price, data quality gates |
| Monitored trend pool | Up to 500 | Daily ledger update | Persistent trend state |
| High-priority trend pool | Up to 75 | Daily expensive refresh only | Candidate promotions and alerts |
| Action review set | Up to 30 | Human review | Deep dive, simulation, watchlist decisions |

### Daily Runtime Strategy

The daily path should aim for cheap broad coverage first:

1. read current universe/cache and prior trend ledger;
2. batch-fetch price/volume features where feasible;
3. apply cheap gates and stale-data labels;
4. update trend records;
5. run support/earnings/regime validation for only names that remain relevant;
6. run expensive simulation/intraday only for promoted names;
7. publish a compact human report.

### Sharding and Batching

The existing `morning_gatherer_v2.py` sector-sharded approach is directionally
right. V2 should generalize it:

- shard by sector or liquidity bucket to avoid one sector dominating;
- cap per-provider batch sizes;
- record per-shard success/failure;
- allow partial source snapshots with explicit `partial` status;
- avoid running LLM analysis per ticker for hundreds of names.

### Cache Policy

Locked cache windows:

- live price/volume snapshot: same trading day;
- universe eligibility: up to 3 trading days;
- support/wick analysis: stale warning after 5 trading days unless price moved
  materially;
- weekly sweeps: usable for context, not enough alone for daily readiness;
- backtest/simulation evidence: recent enough only if market regime and ticker
  behavior have not drifted materially.

Runtime limits:

- target runtime: 45 minutes or less;
- hard runtime threshold: 90 minutes;
- beyond the hard threshold, the run should emit `completed_with_gaps` or
  `failed` with current partial artifacts and a `runtime_limit_exceeded` failure
  class;
- no expensive intraday/simulation refresh is allowed until cheap-gate output is
  available.

### Cost Control

V2 should be designed so that LLM calls scale with promoted records, not with the
full monitored universe. The first producer can be deterministic Python; LLM roles
should focus on ambiguous validation and reporting once a structured ledger exists.

## Proposed Artifact Model

Locked new directory:

```text
data/trend_monitoring/
  daily-market-snapshot.json
  trend-ledger.json
  trend-ledger.md
  validation-findings.json
  critic-patches.json
  monitoring-actions.json
  monitoring-actions.md
  run-status.json
  run-history/
```

Suggested record invariants:

- every trend record has a stable ID and ticker;
- every non-derived claim has source evidence;
- every derived decision names the mechanical rules that produced it;
- every record has `as_of_date`;
- every trend has `last_seen`, `first_seen`, and `trend_status`;
- no trend record directly mutates live portfolio or trade state.

### Resume, Idempotency, and Failure Semantics

V2 should be rerunnable for the same `as_of_date` without duplicating trends,
actions, or run-history entries.

Required semantics:

- every run has `run_id = <as_of_date>-<HHMMSS>-<short_hash>` and every artifact
  records both `run_id` and `as_of_date`;
- current artifacts at `data/trend_monitoring/*.json` represent the latest run
  for the trading date;
- immutable run copies are written under
  `data/trend_monitoring/run-history/<as_of_date>/<run_id>/`;
- writes use temp files plus atomic replace for current artifacts;
- same-day rerun replaces the current daily snapshot, ledger, findings, patches,
  actions, reports, and run-status files, while preserving prior copies in
  run-history;
- `trend_ledger.py` merges against the previous accepted ledger by `stable_key`,
  not by producer-created IDs;
- existing trend IDs remain stable when the same `stable_key` persists;
- new IDs are manager-owned and allocated only after schema validation;
- duplicate same-day `stable_key` records are merged or rejected before action
  planning;
- partial provider failures produce `completed_with_gaps` when at least one
  source-backed ledger can be emitted;
- unsupported claims that remain after critic repair produce `nonconverged`
  unless they are downgraded to `needs_data` or `monitor_only` by deterministic
  rule;
- no phase may delete prior run-history.

### Run Status Update Semantics

`run-status.json` is a single current-run status document keyed by `run_id` and
`as_of_date`.

- Required phase order for status finalization is `snapshot`, `ledger`,
  `actions`, then `report`. These names define deterministic CLI-chain status
  semantics even while workflow YAML remains approval-gated.
- The snapshot phase creates the initial file when it starts a new run.
- The initial file must be schema-valid with root `run_status: running`, root
  `finished_at: null`, and a `snapshot` phase entry with `status: running`,
  `started_at` set, and `finished_at: null`.
- Later phases must load the existing `run-status.json` from `--output-dir`,
  validate it, and fail with exit code `1` if the file or required prior
  artifacts are missing.
- Each phase updates only its own `phase_statuses[]` entry matched by `phase`.
  It must preserve prior phase entries and may replace an existing entry for
  the same phase during same-day reruns.
- Each phase starts by writing or replacing its own `running` phase entry, then
  updates that same entry to a terminal status and non-null `finished_at` before
  the phase command exits.
- After each phase update, the tool recomputes aggregate counts,
  `failure_classes`, `artifact_paths`, `finished_at`, and `run_status`, then
  writes the file with temp-file plus atomic replace.
- `artifact_paths` is cumulative for the run. A phase-owned output replaces the
  same path entry if rerun; unrelated phase output paths are preserved.
- Aggregate `run_status` precedence is deterministic: `failed` if any phase
  status is `failed`; otherwise `nonconverged` if the ledger phase status is
  `nonconverged`; otherwise `completed_with_gaps` if any phase status is
  `completed_with_gaps` or provider failures were recorded; otherwise
  `completed`.
- Root `run_status` remains `running` only when no phase is `failed` or
  `nonconverged` and at least one required downstream phase has no terminal
  phase entry. The report phase is the final required phase and is responsible
  for setting root `finished_at` to a non-null timestamp and leaving the
  aggregate status terminal on successful or completed-with-gaps runs.
- If any phase exits `failed`, or if the ledger phase exits `nonconverged`, that
  same phase tool must synthesize terminal `skipped` entries for every downstream
  required phase before writing final run status. After skipped entries are
  synthesized, aggregate `run_status` becomes terminal using the precedence
  above, and root `finished_at` is set to the failed or nonconverged phase's
  terminal timestamp.
- A synthesized `skipped` entry must include `phase`, `status: skipped`,
  `started_at: null`, `finished_at` equal to the upstream terminal timestamp,
  preserved or empty `input_artifacts`, empty `output_artifacts`, and an
  `errors[]` entry naming the upstream phase, upstream status, and reason.

## State Boundary and Write Policy

### Allowed Automatic Writes

These are the only files V2 may write automatically in the first implementation
after tests exist:

- `data/trend_monitoring/daily-market-snapshot.json`
- `data/trend_monitoring/trend-ledger.json`
- `data/trend_monitoring/validation-findings.json`
- `data/trend_monitoring/critic-patches.json`
- `data/trend_monitoring/monitoring-actions.json`
- `data/trend_monitoring/run-status.json`
- `data/trend_monitoring/*.md` derived reports
- `data/trend_monitoring/run-history/<date-or-run-id>/*`

Not allowed automatically in the first implementation:

- `data/candidates.json`;
- per-ticker generated analysis files outside `data/trend_monitoring/`;
- notification/report artifacts outside `data/trend_monitoring/`;
- any watchlist, portfolio, pending-order, broker, or trade-history state.

Later candidate-pool writes may be designed as a separate manual execution step
that shells through `tools/candidate_tracker.py`; they are not part of the first
V2 monitor.

### Forbidden Automatic Writes

V2 should not directly write:

- `portfolio.json`;
- `trade_history.json`;
- broker fill/sell state;
- active pending-order changes;
- watchlist additions/removals unless explicitly routed through existing approved
  onboarding/watchlist tooling and operator approval.

### Human Approval Boundary

The initial V2 system should recommend:

- candidate pool additions;
- deep-dive runs;
- simulation runs;
- watchlist review;
- order review;
- exits or wind-down review.

It should not autonomously execute:

- buys;
- sells;
- fills;
- cancels;
- order placements;
- watchlist swaps;
- recovery-position changes.

## Migration Plan Sketch

### Slice 1: Trend Ledger Data Contract

Add `tools/trend_contracts.py`, `tools/trend_ledger.py`, and
`schemas/trend_monitoring/trend-ledger.schema.json` without changing current
workflows. Also add shared schema definitions used by all V2 artifacts. Define
record categories, ID allocation, source evidence, derived fields, score
thresholds, status transitions, and atomic write behavior.

### Slice 2: Daily Snapshot Builder

Create `tools/daily_trend_snapshot.py` and
`schemas/trend_monitoring/daily-market-snapshot.schema.json` using existing tools
and caches. Start with cached/offline fixtures in tests. Do not call live market
data in unit tests.

### Slice 3: Mechanical Trend Extractor

Implement `tools/trend_extractor.py` for obvious source-backed trends. Keep the
first version narrow: support retests, relative strength, volatility expansion,
and recent high-conviction mean-reversion pullbacks.

### Slice 4: Verifier/Critic Harness

Add `tools/trend_validator.py`, `tools/trend_critic.py`, and
`tools/trend_phase_ledger.py`. Add
`schemas/trend_monitoring/validation-findings.schema.json`,
`schemas/trend_monitoring/critic-patches.schema.json`, and
`schemas/trend_monitoring/run-status.schema.json`. Start with deterministic
verifier/critic code and mocked harness tests. LLM producer/verifier/critic roles
are out of scope until the schema and deterministic loop pass.

### Slice 5: Monitoring Actions

Add `tools/trend_action_planner.py` and
`schemas/trend_monitoring/monitoring-actions.schema.json`. Convert verified
trends into monitoring actions with `write_effect: none`. Preserve current human
approval boundaries for onboarding, orders, fills, sells, and portfolio changes.

### Slice 6: Deferred Workflow Integration

Do not include workflow YAML or `.workflow/agents/*` files in the first
follow-up implementation plan. After deterministic tools, schemas, fixtures,
tests, and standalone reports pass, a later approval-gated implementation may
wire `workflows/daily-trend-monitoring-workflow.yaml` and add the four matching
agent instruction files under `.workflow/agents/`.

When separately approved, keep the agents minimal and command-oriented: run the
named deterministic tool, inspect the declared output, and do not add
qualitative provider/model/persona behavior. The workflow should call the new
tool entry points and write only `data/trend_monitoring/*` in production mode.

Each new workflow agent instruction file must include these headings: `Purpose`,
`Command`, `Required Inputs`, `Expected Artifacts`, `Forbidden Writes`, and
`Behavior Boundaries`. `Behavior Boundaries` must state: do not add qualitative
judgment, do not alter provider/model/persona behavior, do not edit portfolio,
trade-history, candidate, watchlist, broker, or ticker-memory state.

Allowed command per agent:

- `.workflow/agents/trend-snapshot-builder.md`: only
  `python3 tools/daily_trend_snapshot.py ...`;
- `.workflow/agents/trend-ledger-manager.md`: only
  `python3 tools/trend_phase_ledger.py ...`;
- `.workflow/agents/trend-action-planner.md`: only
  `python3 tools/trend_action_planner.py ...`;
- `.workflow/agents/trend-reporter.md`: only
  `python3 tools/trend_reporter.py ...`.

### Slice 7: Report Integration

Add `tools/trend_reporter.py`. Update morning/status consumers only after the V2
ledger has several successful dry-run days; until then, the report is standalone.

### Slice 8: Promotion Gates

Add explicit promotion hooks from `monitoring-actions.json` to existing workflows:

- `PROMOTE_TO_SIMULATION` -> `sim-ranked-candidate-workflow` or focused candidate
  simulation;
- `PROMOTE_TO_DEEP_DIVE` -> `deep-dive-workflow`;
- `RECOMMEND_WATCHLIST_REVIEW` -> human review packet;
- `COOLDOWN_OR_DROP` -> watchlist fitness or candidate aging review.

These hooks should produce recommendations only. They must not execute
`candidate_tracker.py`, onboarding, simulation, or deep-dive commands without a
separate operator step.

## Test and Verification Strategy

### Contract Tests

- trend-ledger schema accepts valid records and rejects malformed ones;
- manager allocates stable IDs and does not let producers invent IDs;
- derived outputs are computed by manager logic only;
- category values are restricted to approved contract enums;
- state transitions are deterministic.

### Snapshot Builder Tests

- builds a daily snapshot from fixture portfolio, universe cache, and market data;
- marks stale caches correctly;
- marks partial provider failures without crashing the full run;
- excludes or blocks records with missing required fields;
- never writes live portfolio/trade state.

### Trend Extractor Tests

- extracts support retest from fixture support/current-price evidence;
- extracts mean-reversion pullback from fixture swing/current-price evidence;
- extracts relative strength only when comparison evidence exists;
- emits `DORMANT_OR_NO_ACTION` for prior monitored names without current trend;
- avoids duplicate records for the same ticker/category unless source supports
  distinct trends.

### Validation Tests

- rejects stale support evidence;
- blocks earnings-window candidates;
- blocks insufficient ladder depth for support-based actionability;
- downgrades risk-off conflicts;
- preserves monitor-only trend records when actionability fails;
- reports missing required source refs.

### Workflow/Harness Tests

- mocked producer/verifier/critic loop converges cleanly;
- verifier finding plus critic patch updates the ledger;
- repeated unsupported claims fail with structured nonconvergence;
- partial source snapshots produce completed-with-gaps status, not clean success;
- report generation reads ledger output rather than recomputing decisions.

### Regression Tests

- existing unit suite remains green;
- representative command smoke tests from README still work;
- no test mutates real `portfolio.json` or `trade_history.json`;
- generated V2 artifacts are ignored or handled consistently by source control
  policy.

### Fixture Contract

Create `tests/fixtures/trend_monitoring/` with these files:

- `portfolio.json`: one active position, one watchlist ticker, and one pending
  order ticker for overlap checks;
- `trade_history.json`: at least one realized trade to support recent edge
  fixtures;
- `candidates.json`: one current candidate and one stale candidate;
- `universe_screen_cache.json`: passers for support retest, mean-reversion
  pullback, relative strength, and volatility expansion cases;
- `prior-trend-ledger.json`: one persisting trend, one dormant prior trend, and
  one trend that should be retired;
- `market-data.json`: same-day price, volume, ATR, daily change, and one
  provider partial failure;
- `support-artifacts.json`: one fresh support level, one stale support level, and
  one insufficient-ladder-depth case.

The fixtures must cover these scenarios: support retest, mean-reversion
pullback, relative strength, stale support, provider partial failure, duplicate
trend, dormant prior trend, blocked earnings window, missing source ref, and
recommendation-only `ADD_TO_CANDIDATE_POOL`.

### Exact Initial Validation Commands

New V2 tests to create and run:

```bash
python3 -m pytest \
  tests/test_trend_contracts.py \
  tests/test_trend_ledger.py \
  tests/test_daily_trend_snapshot.py \
  tests/test_trend_extractor.py \
  tests/test_trend_validator.py \
  tests/test_trend_critic.py \
  tests/test_trend_action_planner.py \
  tests/test_trend_reporter.py \
  -q
```

Harness tests for the first implementation:

```bash
python3 -m pytest tests/test_trend_phase_ledger.py -q
```

Deferred workflow-contract test after separate workflow approval:

```bash
python3 -m pytest tests/test_daily_trend_workflow_contract.py -q
```

Offline smoke run against fixtures:

```bash
TREND_SMOKE_DIR=/tmp/agentic-trading-trend-monitoring-smoke
python3 tools/daily_trend_snapshot.py --as-of 2026-05-31 --fixture tests/fixtures/trend_monitoring --output-dir "$TREND_SMOKE_DIR"
python3 tools/trend_phase_ledger.py --as-of 2026-05-31 --snapshot "$TREND_SMOKE_DIR/daily-market-snapshot.json" --fixture tests/fixtures/trend_monitoring --output-dir "$TREND_SMOKE_DIR"
python3 tools/trend_action_planner.py --as-of 2026-05-31 --ledger "$TREND_SMOKE_DIR/trend-ledger.json" --output-dir "$TREND_SMOKE_DIR"
python3 tools/trend_reporter.py --as-of 2026-05-31 --ledger "$TREND_SMOKE_DIR/trend-ledger.json" --output-dir "$TREND_SMOKE_DIR"
```

Safety checks:

```bash
git diff -- portfolio.json trade_history.json data/candidates.json
python3 -m pytest tests/test_portfolio_manager_safety.py tests/test_candidate_tracker.py -q
```

The V2 implementation plan must add `tests/test_candidate_tracker.py`. Required
coverage: `add` skips duplicate tickers, `add` skips portfolio/watchlist/pending
tickers, `import-screening` skips existing tickers, `age-out` removes stale
entries, and `promote --dry-run` does not mutate candidates.

## Risks and Required Guardrails

- Live state risk: V2 must not write `portfolio.json` or `trade_history.json`
  except through the existing supported `portfolio_manager.py` APIs.
- Data-provider risk: yfinance failures and schema drift must remain expected
  operational states, not silent false negatives.
- Scale risk: monitoring hundreds of tickers daily requires staged cheap gates
  before expensive intraday sweeps.
- Staleness risk: weekly artifacts can inform V2, but daily trend readiness must
  include `as_of_date` and cache-age checks.
- Prompt risk: do not let LLM output become the source of truth for numerical
  indicators, prices, or gates.
- Contract drift risk: trading category contracts should be versioned and tested
  before workflow rollout.
- Data snooping risk: recent market-beat scoring must avoid training and validating
  on the same window without clear labeling.
- Overfitting risk: high-frequency trend categories can overfit to short-lived
  volatility unless validation separates "monitor" from "action."
- Alert fatigue risk: hundreds of monitored names can create too many daily
  promotions unless action tiers and quotas are manager-owned.
- Operational latency risk: pre-market and end-of-day runs have different data
  availability, so the schedule must be explicit.

## Open Questions

These questions are deferrable and should not block the first implementation
plan:

1. Whether to add intraday monitoring after the end-of-day ledger proves stable.
2. Whether to expose trend data in a dashboard.
3. Whether to integrate notifications.
4. Whether event-driven/news categories should become action-producing or remain
   review-only.
5. Whether repeated validated recommendations should later be allowed to call
   `tools/candidate_tracker.py` through an explicit manual execution command.

## Decision Ledger

### Locked For First Implementation Planning

1. `recent_edge_score` is the market-beat analogue and uses the weighted
   deterministic inputs listed in `Locked Implementation Decisions`.
2. Initial monitored pool cap is 500 tickers.
3. Initial high-priority expensive-refresh cap is 75 tickers.
4. Initial action-review cap is 30 tickers.
5. Initial schedule is end-of-day after market close.
6. Initial automatic write set is only `data/trend_monitoring/*`.
7. V2 copies `mcp-agents-workflow` principles into a local minimal trading
   harness instead of importing the full runtime.
8. Initial contracts are code/data schemas and deterministic tests only; prompt,
   persona, provider, model, workflow YAML, `.workflow/agents/*`, and runtime
   workflow wiring changes require separate approval.

### Deferrable Until After Prototype

1. Whether to add intraday monitoring in the first release.
2. Whether to include event-driven/news categories in V1 of V2.
3. Whether to expose trend data in a dashboard.
4. Whether to integrate notifications.
5. Whether to auto-add candidates after repeated validation.

### Explicit Non-Goals For First Implementation

1. No autonomous trading.
2. No direct broker integration.
3. No direct portfolio or trade-history mutation from trend extraction.
4. No full daily replacement for weekly reoptimization.
5. No LLM-only numerical signal generation.

## Initial Recommendation

Proceed with a V2 research-to-plan track. The first implementation-ready target
should not be "replace the current workflows." It should be:

1. define the trend-ledger contract;
2. build a deterministic daily snapshot;
3. produce a source-backed trend ledger for a bounded universe sample;
4. verify it with deterministic tests;
5. only then introduce producer/verifier/critic convergence, and defer workflow
   YAML until separate approval.

That path brings the mcp harness principles into `agentic-trading` while respecting
the current trading system's biggest asset: deterministic market tools and explicit
live-state boundaries.
