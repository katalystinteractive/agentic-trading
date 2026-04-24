"""Ticker clusterer — group tickers by dip behavior, assign cluster IDs + confidence.

Reads sweep_results.json (from parameter_sweeper.py), extracts feature vectors,
clusters with K-means, computes confidence scores, writes updated ticker_profiles.json.

Usage:
    python3 tools/ticker_clusterer.py                     # cluster and write profiles
    python3 tools/ticker_clusterer.py --dry-run            # show results without writing
    python3 tools/ticker_clusterer.py --max-k 8            # max clusters to try
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

_ROOT = Path(__file__).resolve().parent.parent
SWEEP_RESULTS_PATH = _ROOT / "data" / "sweep_results.json"
PROFILES_PATH = _ROOT / "data" / "ticker_profiles.json"

# Feature columns used for clustering (order matters — must match extraction)
FEATURE_COLS = [
    "dip_frequency",
    "median_dip_depth_pct",
    "median_bounce_pct",
    "target_hit_rate",
    "stop_hit_rate",
    "eod_cut_rate",
    "eod_recovery_rate",
    "mean_pnl_pct",
]


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

def load_sweep_results(path=None):
    """Load sweep results JSON. Returns (meta, {ticker: result_dict})."""
    p = path or SWEEP_RESULTS_PATH
    if not p.exists():
        print(f"*Sweep results not found at {p}. Run parameter_sweeper.py first.*")
        return None, {}
    with open(p) as f:
        data = json.load(f)
    meta = data.pop("_meta", {})
    return meta, data


def build_feature_matrix(sweep_data, feature_cols=None):
    """Extract feature vectors from sweep results.

    Args:
        feature_cols: list of feature column names. Defaults to FEATURE_COLS.

    Returns: (tickers list, feature_matrix ndarray, features list of dicts)
    """
    cols = feature_cols or FEATURE_COLS
    tickers = []
    feature_dicts = []

    for tk, result in sorted(sweep_data.items()):
        features = result.get("features")
        if not features:
            continue
        tickers.append(tk)
        feature_dicts.append(features)

    if not tickers:
        return [], np.array([]), []

    # Build matrix from feature columns
    matrix = np.array([
        [fd.get(col, 0) for col in cols]
        for fd in feature_dicts
    ], dtype=float)

    return tickers, matrix, feature_dicts


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def find_optimal_clusters(X, max_k=8):
    """Find optimal K using silhouette score. Returns (best_k, best_score, labels)."""
    n_samples = len(X)
    if n_samples < 3:
        # Can't cluster fewer than 3 samples
        return 1, 0.0, np.zeros(n_samples, dtype=int)

    max_k = min(max_k, n_samples - 1)
    if max_k < 2:
        return 1, 0.0, np.zeros(n_samples, dtype=int)

    best_k = 2
    best_score = -1
    best_labels = None

    for k in range(2, max_k + 1):
        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = km.fit_predict(X)
        score = silhouette_score(X, labels)
        if score > best_score:
            best_k = k
            best_score = score
            best_labels = labels

    return best_k, round(best_score, 4), best_labels


def compute_cluster_profiles(tickers, labels, sweep_data, n_clusters):
    """Compute average params per cluster as default profile for new tickers."""
    cluster_profiles = {}
    for cid in range(n_clusters):
        cluster_tickers = [tickers[i] for i, l in enumerate(labels) if l == cid]
        if not cluster_tickers:
            continue

        dip_thresholds = []
        bounce_thresholds = []
        target_pcts = []
        stop_pcts = []

        for tk in cluster_tickers:
            params = sweep_data[tk].get("params", {})
            dip_thresholds.append(params.get("dip_threshold", 1.0))
            bounce_thresholds.append(params.get("bounce_threshold", 0.3))
            target_pcts.append(params.get("target_pct", 4.0))
            stop_pcts.append(params.get("stop_pct", -3.0))

        cluster_profiles[cid] = {
            "dip_threshold": round(float(np.median(dip_thresholds)), 2),
            "bounce_threshold": round(float(np.median(bounce_thresholds)), 2),
            "target_pct": round(float(np.median(target_pcts)), 1),
            "stop_pct": round(float(np.median(stop_pcts)), 1),
            "tickers": cluster_tickers,
            "size": len(cluster_tickers),
        }

    return cluster_profiles


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

def compute_confidence(tk, sweep_result, cluster_profiles, cluster_id,
                       feature_dict, scaler, X_scaled, tickers, labels):
    """Score how much we trust this ticker's profile (0-100).

    Components:
      - trade_count (0-30): more trades = higher confidence
      - profitability (0-30): positive best P/L
      - cluster_fit (0-20): how close to cluster centroid
      - consistency (0-20): low variance in exit reasons = more predictable
    """
    stats = sweep_result.get("stats", {})
    trade_count = stats.get("trades", 0)
    best_pnl = stats.get("total_pnl", 0)
    exits = stats.get("exits", {})

    # Trade count score (0-30)
    trade_score = min(trade_count / 10.0, 1.0) * 30

    # Profitability score (0-30)
    profit_score = 30.0 if best_pnl > 0 else 0.0

    # Cluster fit score (0-20): distance to cluster centroid
    tk_idx = tickers.index(tk)
    cluster_mask = labels == cluster_id
    cluster_points = X_scaled[cluster_mask]
    if len(cluster_points) > 1:
        centroid = cluster_points.mean(axis=0)
        tk_point = X_scaled[tk_idx]
        dist = float(np.linalg.norm(tk_point - centroid))
        # Normalize: dist=0 → 20pts, dist=3+ → 0pts
        cluster_fit = max(0, (1 - dist / 3.0)) * 20
    else:
        cluster_fit = 10.0  # single-member cluster, neutral

    # Consistency score (0-20): one dominant exit reason = more predictable
    total_exits = sum(exits.values())
    if total_exits > 0:
        max_exit_pct = max(exits.values()) / total_exits
        consistency = max_exit_pct * 20
    else:
        consistency = 0

    total = round(trade_score + profit_score + cluster_fit + consistency, 1)
    return {
        "total": total,
        "trade_score": round(trade_score, 1),
        "profit_score": round(profit_score, 1),
        "cluster_fit": round(cluster_fit, 1),
        "consistency": round(consistency, 1),
    }


# ---------------------------------------------------------------------------
# Profile builder
# ---------------------------------------------------------------------------

def build_profiles(tickers, labels, sweep_data, cluster_profiles,
                   confidence_scores, feature_dicts, n_clusters, silhouette):
    """Build final ticker_profiles.json with cluster IDs + confidence."""
    profiles = {
        "_meta": {
            "version": 3,
            "schema_version": 1,
            "source": "ticker_clusterer.py",
            "execution_mode": "intraday_5min_neural_replay",
            "updated": date.today().isoformat(),
            "clusters": n_clusters,
            "silhouette_score": silhouette,
            "cluster_profiles": {
                str(cid): {k: v for k, v in cp.items() if k != "tickers"}
                for cid, cp in cluster_profiles.items()
            },
        }
    }

    for i, tk in enumerate(tickers):
        cluster_id = int(labels[i])
        params = sweep_data[tk].get("params", {})
        stats = sweep_data[tk].get("stats", {})
        conf = confidence_scores.get(tk, {})
        features = feature_dicts[i] if i < len(feature_dicts) else {}

        profiles[tk] = {
            "dip_threshold": params.get("dip_threshold", 1.0),
            "bounce_threshold": params.get("bounce_threshold", 0.3),
            "target_pct": params.get("target_pct", 4.0),
            "stop_pct": params.get("stop_pct", -3.0),
            "cluster": cluster_id,
            "confidence": conf.get("total", 0),
            "_stats": stats,
            "_features": features,
            "_confidence_detail": conf,
        }

    return profiles


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Ticker Clusterer")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show results without writing profiles")
    parser.add_argument("--max-k", type=int, default=8,
                        help="Maximum number of clusters to try (default: 8)")
    parser.add_argument("--sweep-file", type=str, default=None,
                        help="Path to sweep_results.json")
    parser.add_argument("--feature-cols", type=str, default=None,
                        help="Comma-separated feature column names (default: dip strategy features)")
    args = parser.parse_args()

    custom_feature_cols = args.feature_cols.split(",") if args.feature_cols else None

    # Load sweep results
    sweep_path = Path(args.sweep_file) if args.sweep_file else None
    meta, sweep_data = load_sweep_results(sweep_path)
    if not sweep_data:
        return

    print(f"Ticker Clusterer")
    print(f"Sweep data: {len(sweep_data)} tickers, "
          f"{meta.get('trading_days', '?')} trading days\n")

    # Build feature matrix
    tickers, X, feature_dicts = build_feature_matrix(sweep_data, custom_feature_cols)
    if len(tickers) < 2:
        print("*Need at least 2 tickers with features to cluster.*")
        return

    print(f"Feature matrix: {X.shape[0]} tickers × {X.shape[1]} features")

    # Standardize
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Cluster
    n_clusters, silhouette, labels = find_optimal_clusters(X_scaled, args.max_k)
    print(f"Optimal clusters: K={n_clusters} (silhouette={silhouette})\n")

    # Cluster profiles (defaults for new tickers)
    cluster_profiles = compute_cluster_profiles(
        tickers, labels, sweep_data, n_clusters)

    # Print cluster summary
    print("### Cluster Summary\n")
    for cid, cp in sorted(cluster_profiles.items()):
        print(f"**Cluster {cid}** ({cp['size']} tickers): "
              f"dip>={cp['dip_threshold']}% target={cp['target_pct']}% "
              f"stop={cp['stop_pct']}%")
        print(f"  Tickers: {', '.join(cp['tickers'])}")

    # Confidence scoring
    print(f"\n### Confidence Scores\n")
    confidence_scores = {}
    for i, tk in enumerate(tickers):
        cluster_id = int(labels[i])
        conf = compute_confidence(
            tk, sweep_data[tk], cluster_profiles, cluster_id,
            feature_dicts[i], scaler, X_scaled, tickers, labels)
        confidence_scores[tk] = conf

    # Print per-ticker results
    print(f"| Ticker | Cluster | Confidence | Trades | P/L |")
    print(f"| :--- | :--- | :--- | :--- | :--- |")
    for i, tk in enumerate(tickers):
        cid = int(labels[i])
        conf = confidence_scores[tk]["total"]
        stats = sweep_data[tk].get("stats", {})
        trades = stats.get("trades", 0)
        pnl = stats.get("total_pnl", 0)
        print(f"| {tk} | {cid} | {conf} | {trades} | ${pnl:.2f} |")

    # Build and write profiles
    profiles = build_profiles(
        tickers, labels, sweep_data, cluster_profiles,
        confidence_scores, feature_dicts, n_clusters, silhouette)

    if args.dry_run:
        n_profiles = len([k for k in profiles if not k.startswith("_")])
        print(f"\n--- DRY RUN — would write {n_profiles} profiles ---")
    else:
        with open(PROFILES_PATH, "w") as f:
            json.dump(profiles, f, indent=2)
        n_profiles = len([k for k in profiles if not k.startswith("_")])
        print(f"\nWrote {n_profiles} profiles to {PROFILES_PATH}")

    # Flag low-confidence tickers
    low_conf = [tk for tk, c in confidence_scores.items() if c["total"] < 40]
    if low_conf:
        print(f"\n**Low confidence (<40):** {', '.join(low_conf)}")
        print("These tickers should use cluster defaults until more data is available.")


if __name__ == "__main__":
    main()
