# Neural Graph Policy Contract

The "neural" layer is an explainable graph policy, not a trained neural network.
It combines deterministic graph gates, swept per-ticker parameters, and learned
edge weights where those weights are actual live decision inputs.

## Live Policy Weights

Only these synapse weight groups are live policy inputs:

- `*:dip_gate`
- `*:bounce_gate`
- `*:candidate`

These are stored in `data/synapse_weights.json` under `weights` and are loaded by
the neural dip evaluator.

## Diagnostic Weights

Support outcome gates are diagnostic only:

- `*:profit_gate`
- `*:hold_gate`
- `*:stop_gate`

These are reconstructed from trade outcomes such as P/L, days held, or stop
behavior. They are useful for analysis, but they are not live input signals and
must not affect live support recommendations, pool sizing, order adjustment, or
dip decisions. `weight_learner.save_weights()` stores them under
`diagnostic_weights`, not `weights`.

The artifact validator rejects diagnostic support gates if they appear in the
live `weights` map.

## What Is Learned, Swept, And Static

| Category | Fields / Artifacts | Live Consumer | Notes |
| :--- | :--- | :--- | :--- |
| Learned policy weights | `synapse_weights.json:weights` for `*:dip_gate`, `*:bounce_gate`, `*:candidate` | `neural_dip_evaluator.py` | Reward-modulated Hebbian updates attenuate or retain graph inputs. Weights are clamped to `[0, 1]`; there are no negative/inhibitory weights. |
| Diagnostic weights | `synapse_weights.json:diagnostic_weights` for `*:profit_gate`, `*:hold_gate`, `*:stop_gate` | None for live decisions | Stored for analysis only. These gates are reconstructed from outcomes and are not valid live inputs. |
| Swept dip parameters | `ticker_profiles.json` fields `dip_threshold`, `bounce_threshold`, `target_pct`, `stop_pct` | `neural_dip_evaluator.py` | Produced by sweep/cluster tooling and validated before use. |
| Swept support parameters | `neural_support_candidates.json`, `neural_watchlist_profiles.json`, and support sweep params such as `sell_default`, pools, bullets, and tier thresholds | Support/reporting/order tools after artifact validation | These are profile/config outputs, not neural-network weights. |
| Deterministic static gates | catastrophic status, verdict, earnings gate, historical range viability, PDT availability, capital availability, sector/correlation filters | Graph builders and support tools | These remain hard safety or strategy gates and are not learnable. |
| Generated artifacts | neural candidates, support candidates, watchlist profiles, sweep results, ticker profiles, synapse weights | Loaded through `neural_artifact_validator.py` where used live/reporting | Stale, malformed, or incompatible artifacts fail closed. |

## Naming Rule

Existing filenames and commands keep the `neural_` prefix for compatibility.
Operator-facing docs should describe the implementation as a learned graph policy
unless a true model-training path is introduced.
