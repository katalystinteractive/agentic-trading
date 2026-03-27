"""Shared configuration for backtesting simulators.

Two dataclasses:
- DipSimConfig: daily dip/fluctuation strategy (30 params)
- SurgicalSimConfig: surgical mean-reversion strategy (46 params)

Both support JSON serialization for reproducibility and CLI generation via argparse.
"""
import argparse
import json
from dataclasses import dataclass, field, asdict
from itertools import product
from pathlib import Path


@dataclass
class DipSimConfig:
    """All tunable parameters for the daily dip/fluctuation simulator."""

    # Budget
    budget: float = 100.0
    total_daily_cap: float = 500.0

    # Entry thresholds
    dip_threshold: float = 1.0          # % dip from open to qualify
    bounce_threshold: float = 0.3       # % bounce for confirmation
    breadth_ratio: float = 0.5          # fraction of tickers that must dip
    bounce_ratio: float = 0.5           # fraction that must bounce

    # Exit thresholds
    sell_target_pct: float = 4.0        # +% target (optimized from 3% via backtest sweep)
    stop_loss_pct: float = -3.0         # -% stop
    max_hold_days: int = 1              # EOD cut

    # Selection
    max_tickers_per_signal: int = 5     # top N dippers
    rank_method: str = "dip"            # "dip" or "recovery"

    # Eligibility
    min_daily_range: float = 3.0        # min median daily range %
    min_recovery_rate: float = 60.0     # min % of days with 2%+ recovery

    # Market regime
    vix_risk_off: float = 25.0          # VIX threshold for Risk-Off
    risk_off_action: str = "skip"       # "skip" or "half"

    # PDT
    pdt_limit: int = 3                  # max day trades per window
    pdt_window: int = 5                 # rolling window days
    account_size: float = 25000.0       # PDT rule threshold

    # Timing (ET decimal hours)
    fh_end_et: float = 10.5             # first-hour end
    sh_end_et: float = 11.0             # second-hour end

    # Slippage
    entry_slippage_pct: float = 0.0
    exit_slippage_pct: float = 0.0

    # Earnings
    earnings_buffer_days: int = 7       # skip entries within N days of earnings

    # Period
    start: str = ""                     # YYYY-MM-DD or empty for auto
    end: str = ""                       # YYYY-MM-DD or empty for today
    interval: str = "5m"                # 5m, 30m, 1h

    # Tickers
    tickers: list = field(default_factory=list)  # empty = use watchlist

    # Output
    output_dir: str = "dip-sim-results"
    csv_output: bool = False
    json_output: bool = False

    # Compounding
    compound: bool = False              # reinvest profits into budget for next trade

    # Sweep
    sweep: bool = False
    sweep_params: str = ""              # e.g. "dip_threshold=0.5:0.5:3.0,sell_target_pct=1:1:5"

    # Workflow
    workflow_mode: bool = False         # read config from sim-data.json, write JSON outputs

    def to_json(self):
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, s):
        return cls(**json.loads(s))

    @classmethod
    def from_dict(cls, d):
        """Create from dict, ignoring unknown keys."""
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in valid})


@dataclass
class SurgicalSimConfig:
    """All tunable parameters for the surgical mean-reversion simulator."""

    # Pool sizing
    active_pool: float = 300.0
    reserve_pool: float = 300.0
    active_bullets_max: int = 5
    reserve_bullets_max: int = 3

    # Tier thresholds (hold rate %)
    tier_full: int = 50
    tier_std: int = 30
    tier_half: int = 15
    confidence_min_approaches: int = 3

    # Sell targets
    sell_default: float = 6.0
    sell_fast_cycler: float = 8.0
    sell_exceptional: float = 10.0
    fast_cycler_min_cycles: int = 3
    fast_cycler_max_median_days: int = 3
    exceptional_min_cycles: int = 5
    exceptional_max_median_days: int = 2
    exceptional_min_capture: int = 50
    sell_mode: str = "flat"             # "flat" or "resistance"

    # Time stops
    time_stop_days: int = 60
    time_stop_riskoff_ext: int = 14

    # Catastrophic stops (%)
    cat_warning: float = 15.0
    cat_hard_stop: float = 25.0
    cat_exit: float = 40.0

    # Zone config
    active_radius_cap: float = 20.0
    frequency_weighting: bool = True
    pool_max_fraction: float = 0.60

    # Regime thresholds
    vix_risk_on: float = 20.0
    vix_risk_off: float = 25.0

    # Wick analysis
    wick_lookback_months: int = 13
    recompute_levels: str = "weekly"    # "daily", "weekly", "monthly"
    min_hold_rate: int = 15
    decay_half_life: int = 90
    vol_profile_bins: int = 40
    pa_min_touches: int = 3
    approach_proximity: float = 8.0

    # Same-day exit
    same_day_exit: bool = True
    same_day_exit_pct: float = 4.0

    # Earnings
    earnings_gate: bool = False

    # Regime behavior
    riskoff_suppress_upgrades: bool = True
    conservative_exit_order: bool = True

    # Compounding
    compound: bool = False              # reinvest profits into pools after each sell

    # Period
    start: str = ""
    end: str = ""

    # Tickers
    tickers: list = field(default_factory=list)

    # Output
    output_dir: str = "data/backtest"
    json_output: bool = False

    # Sweep
    sweep: bool = False
    sweep_params: str = ""
    parallel: int = 1

    def to_json(self):
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, s):
        return cls(**json.loads(s))

    @classmethod
    def from_dict(cls, d):
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in valid})

    def to_wick_config(self):
        """Convert surgical config to WickConfig for wick_offset_analyzer."""
        from wick_offset_analyzer import WickConfig
        return WickConfig(
            tier_full=self.tier_full,
            tier_std=self.tier_std,
            tier_half=self.tier_half,
            confidence_min_approaches=self.confidence_min_approaches,
            decay_half_life=self.decay_half_life,
            hvn_bins=self.vol_profile_bins,
            pa_min_touches=self.pa_min_touches,
            approach_proximity_pct=self.approach_proximity,
        )

    def to_capital_config(self):
        """Convert surgical config to capital config dict for _compute_bullet_plan."""
        return {
            "active_pool": self.active_pool,
            "reserve_pool": self.reserve_pool,
            "active_bullets_max": self.active_bullets_max,
            "reserve_bullets_max": self.reserve_bullets_max,
        }


# ---------------------------------------------------------------------------
# Sweep helpers
# ---------------------------------------------------------------------------

def parse_sweep_spec(spec_str):
    """Parse sweep specification string into parameter grid.

    Format: "param1=start:step:end,param2=val1:val2:val3"
    Returns: list of dicts, one per combination (Cartesian product).

    Examples:
        "sell_target_pct=2:1:5"  → [{sell_target_pct: 2}, {3}, {4}, {5}]
        "dip_threshold=0.5:0.5:2.0,sell_target_pct=2:1:4"  → 4×3 = 12 combos
    """
    if not spec_str:
        return [{}]

    param_ranges = {}
    for part in spec_str.split(","):
        part = part.strip()
        if "=" not in part:
            continue
        name, values_str = part.split("=", 1)
        name = name.strip()
        vals = [v.strip() for v in values_str.split(":")]

        if len(vals) == 3:
            # start:step:end format (handles both ascending and descending)
            start, step, end = float(vals[0]), float(vals[1]), float(vals[2])
            generated = []
            v = start
            if step > 0:
                while v <= end + 1e-9:
                    generated.append(round(v, 4))
                    v += step
            elif step < 0:
                while v >= end - 1e-9:
                    generated.append(round(v, 4))
                    v += step
            if not generated:
                generated = [start]
            param_ranges[name] = generated
        else:
            # explicit values
            param_ranges[name] = [float(v) if "." in v else int(v) for v in vals]

    if not param_ranges:
        return [{}]

    # Cartesian product
    keys = list(param_ranges.keys())
    value_lists = [param_ranges[k] for k in keys]
    combos = []
    for values in product(*value_lists):
        combos.append(dict(zip(keys, values)))
    return combos


def apply_sweep_overrides(base_config, overrides):
    """Create a new config with sweep overrides applied.

    Args:
        base_config: DipSimConfig or SurgicalSimConfig instance
        overrides: dict of {param_name: value} to override

    Returns: new config instance with overrides applied
    """
    d = asdict(base_config)
    for k, v in overrides.items():
        if k in d:
            # Preserve type
            orig_type = type(d[k])
            if orig_type == int:
                d[k] = int(v)
            elif orig_type == float:
                d[k] = float(v)
            elif orig_type == bool:
                d[k] = bool(v)
            else:
                d[k] = v
    return type(base_config).from_dict(d)


# ---------------------------------------------------------------------------
# CLI builders
# ---------------------------------------------------------------------------

def build_dip_argparse():
    """Build argparse for dip simulator CLI."""
    p = argparse.ArgumentParser(description="Daily Dip Strategy Simulator")

    # Budget
    p.add_argument("--budget", type=float, default=100.0)
    p.add_argument("--daily-cap", type=float, default=500.0, dest="total_daily_cap")

    # Entry
    p.add_argument("--dip-threshold", type=float, default=1.0, dest="dip_threshold")
    p.add_argument("--bounce-threshold", type=float, default=0.3, dest="bounce_threshold")
    p.add_argument("--breadth-ratio", type=float, default=0.5, dest="breadth_ratio")
    p.add_argument("--bounce-ratio", type=float, default=0.5, dest="bounce_ratio")

    # Exit
    p.add_argument("--sell-target", type=float, default=4.0, dest="sell_target_pct")
    p.add_argument("--stop-loss", type=float, default=-3.0, dest="stop_loss_pct")
    p.add_argument("--max-hold", type=int, default=1, dest="max_hold_days")

    # Selection
    p.add_argument("--max-tickers", type=int, default=5, dest="max_tickers_per_signal")
    p.add_argument("--rank-by", choices=["dip", "recovery"], default="dip", dest="rank_method")

    # Eligibility
    p.add_argument("--min-range", type=float, default=3.0, dest="min_daily_range")
    p.add_argument("--min-recovery", type=float, default=60.0, dest="min_recovery_rate")

    # Regime
    p.add_argument("--vix-threshold", type=float, default=25.0, dest="vix_risk_off")
    p.add_argument("--risk-off-action", choices=["skip", "half"], default="skip", dest="risk_off_action")

    # PDT
    p.add_argument("--pdt-limit", type=int, default=3, dest="pdt_limit")
    p.add_argument("--pdt-window", type=int, default=5, dest="pdt_window")
    p.add_argument("--account-size", type=float, default=25000.0, dest="account_size")

    # Timing
    p.add_argument("--fh-end", type=float, default=10.5, dest="fh_end_et")
    p.add_argument("--sh-end", type=float, default=11.0, dest="sh_end_et")

    # Slippage
    p.add_argument("--entry-slippage", type=float, default=0.0, dest="entry_slippage_pct")
    p.add_argument("--exit-slippage", type=float, default=0.0, dest="exit_slippage_pct")

    # Earnings
    p.add_argument("--earnings-buffer", type=int, default=7, dest="earnings_buffer_days")

    # Period
    p.add_argument("--start", type=str, default="")
    p.add_argument("--end", type=str, default="")
    p.add_argument("--interval", choices=["5m", "15m", "30m", "1h"], default="5m")

    # Tickers
    p.add_argument("--tickers", nargs="*", type=str.upper, default=[])

    # Output
    p.add_argument("--output-dir", default="dip-sim-results", dest="output_dir")
    p.add_argument("--csv", action="store_true", dest="csv_output")
    p.add_argument("--json", action="store_true", dest="json_output")

    # Compounding
    p.add_argument("--compound", action="store_true", help="Reinvest profits into budget")

    # Sweep
    p.add_argument("--sweep", action="store_true")
    p.add_argument("--sweep-params", type=str, default="", dest="sweep_params")

    # Workflow
    p.add_argument("--workflow-mode", action="store_true", dest="workflow_mode")

    return p


def args_to_dip_config(args):
    """Convert parsed argparse namespace to DipSimConfig."""
    d = vars(args)
    return DipSimConfig.from_dict(d)
