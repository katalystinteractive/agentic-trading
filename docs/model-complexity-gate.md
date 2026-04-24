# Model Complexity Gate

The trading system may use generated graph-policy artifacts in live tools after
schema validation, freshness checks, and artifact promotion. True neural or
black-box model artifacts are different: they are advisory until they pass this
gate.

## Live Eligibility

Graph-policy artifacts are live-eligible when they pass the existing artifact
validator and promotion flow.

Black-box model artifacts are live-eligible only when `_meta` includes:

- `model_family`: `neural_model`, `black_box_model`, `ml_model`, or
  `deep_learning_model`
- `promotion_status`: `promoted`, `approved`, or `live`
- `promotion.baseline_family`: a graph-policy family
- `promotion.out_of_sample_lift_pct`: positive
- `promotion.risk_adjusted_lift_pct`: positive
- `promotion.approved`: not `false`

Without those fields, black-box output remains advisory and must not affect
tournament ranking, live recommendations, bullet sizing, or order adjustment.

## Comparison Protocol

Before a true model can move from advisory to live:

1. Compare graph baseline vs calibrated graph-policy vs candidate model.
2. Use walk-forward or out-of-sample results after costs.
3. Require positive risk-adjusted lift over the graph baseline.
4. Confirm drawdown and operational risk remain acceptable.
5. Keep explanations/reporting sufficient for operator review.
6. Promote the artifact only after the above evidence is recorded in `_meta`.

The point of simulations is still to improve live decisions. The gate only
prevents unproven model output from bypassing the graph-policy promotion process.
