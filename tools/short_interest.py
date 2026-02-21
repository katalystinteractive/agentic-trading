import yfinance as yf
import sys
from pathlib import Path
from datetime import datetime

_ROOT = Path(__file__).resolve().parent.parent
TICKERS_DIR = _ROOT / "tickers"


def _write_cache(ticker, filename, report):
    ticker_dir = TICKERS_DIR / ticker
    ticker_dir.mkdir(parents=True, exist_ok=True)
    with open(ticker_dir / filename, "w") as f:
        f.write(report + "\n")


def fmt_shares(val):
    """Format share counts with M/K suffixes."""
    if val is None:
        return "N/A"
    val = float(val)
    if abs(val) >= 1e9:
        return f"{val/1e9:.2f}B"
    elif abs(val) >= 1e6:
        return f"{val/1e6:.2f}M"
    elif abs(val) >= 1e3:
        return f"{val/1e3:.0f}K"
    else:
        return f"{val:,.0f}"

def fmt_pct(val, is_fraction=True):
    """Format as percentage. If is_fraction=True, value is 0.05 meaning 5%."""
    if val is None:
        return "N/A"
    v = float(val)
    if is_fraction:
        return f"{v * 100:.2f}%"
    return f"{v:.2f}%"


def _compute_squeeze_score(r):
    """Compute squeeze risk score, rating, and factor descriptions for one result dict."""
    score = 0
    factors = []

    short_pct = r['short_pct_float']
    short_ratio = r['short_ratio']
    shares_short = r['shares_short']
    prior = r['shares_short_prior']

    # Score based on short % of float (convert fraction to percentage)
    if short_pct is not None:
        sp = float(short_pct)
        pct_val = sp * 100 if sp <= 0.99 else sp
        if pct_val >= 30:
            score += 60
            factors.append(f"Very high short% ({pct_val:.1f}%)")
        elif pct_val >= 20:
            score += 50
            factors.append(f"High short% ({pct_val:.1f}%)")
        elif pct_val >= 15:
            score += 40
            factors.append(f"Elevated short% ({pct_val:.1f}%)")
        elif pct_val >= 10:
            score += 30
            factors.append(f"Moderate short% ({pct_val:.1f}%)")
        elif pct_val >= 5:
            score += 15
            factors.append(f"Low short% ({pct_val:.1f}%)")
        else:
            factors.append(f"Minimal short% ({pct_val:.1f}%)")

    # Score based on days to cover (short ratio)
    if short_ratio is not None:
        if short_ratio >= 10:
            score += 25
            factors.append(f"Very high DTC ({short_ratio:.1f})")
        elif short_ratio >= 5:
            score += 15
            factors.append(f"High DTC ({short_ratio:.1f})")
        elif short_ratio >= 3:
            score += 10
            factors.append(f"Moderate DTC ({short_ratio:.1f})")
        else:
            factors.append(f"Low DTC ({short_ratio:.1f})")

    # Score modifier for trend (increasing shorts = higher squeeze potential)
    if shares_short is not None and prior is not None and prior > 0:
        change_pct = ((shares_short - prior) / prior) * 100
        if change_pct > 10:
            score += 15
            factors.append("Shorts increasing rapidly")
        elif change_pct > 0:
            score += 5
            factors.append("Shorts slowly increasing")
        elif change_pct < -10:
            score -= 10
            factors.append("Shorts covering rapidly")

    # Cap score
    score = max(0, min(100, score))

    # Rating
    if score >= 75:
        rating = "EXTREME"
    elif score >= 50:
        rating = "HIGH"
    elif score >= 25:
        rating = "MEDIUM"
    else:
        rating = "LOW"

    factors_str = "; ".join(factors) if factors else "No data"
    return score, rating, factors_str


def _analyze_single_ticker(r):
    """Build a per-ticker short interest report from one result dict."""
    lines = []
    lines.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    lines.append("")
    lines.append(f"## Short Interest: {r['name']} ({r['ticker']})")

    # Key metrics table
    lines.append("")
    lines.append("### Key Metrics")
    lines.append("| Metric | Value |")
    lines.append("| :--- | :--- |")

    ss_str = fmt_shares(r['shares_short'])
    sr_str = f"{r['short_ratio']:.2f}" if r['short_ratio'] is not None else "N/A"
    sp_str = fmt_pct(r['short_pct_float']) if r['short_pct_float'] is not None else "N/A"

    lines.append(f"| Shares Short | {ss_str} |")
    lines.append(f"| Short Ratio (DTC) | {sr_str} |")
    lines.append(f"| Short % Float | {sp_str} |")
    lines.append(f"| Float Shares | {fmt_shares(r['float_shares'])} |")
    lines.append(f"| Shares Outstanding | {fmt_shares(r['shares_outstanding'])} |")
    lines.append(f"| Avg Volume | {fmt_shares(r['avg_volume'])} |")

    # Change from prior
    shares_short = r['shares_short']
    prior = r['shares_short_prior']
    if shares_short is not None and prior is not None and prior > 0:
        change_pct = ((shares_short - prior) / prior) * 100
        change_str = f"{change_pct:+.1f}%"
        if change_pct > 0:
            change_str += " (increasing)"
        elif change_pct < 0:
            change_str += " (decreasing)"
        lines.append(f"| Change from Prior Month | {change_str} |")
    else:
        lines.append("| Change from Prior Month | N/A |")

    # Squeeze risk
    score, rating, factors_str = _compute_squeeze_score(r)
    lines.append("")
    lines.append("### Squeeze Risk")
    lines.append("| Metric | Value |")
    lines.append("| :--- | :--- |")
    lines.append(f"| Risk Rating | {rating} |")
    lines.append(f"| Score | {score}/100 |")
    lines.append(f"| Key Factors | {factors_str} |")

    return "\n".join(lines)


def analyze_short_interest(tickers):
    lines = []
    lines.append("")
    lines.append("## Short Interest Analysis")

    results = []
    for ticker_symbol in tickers:
        try:
            ticker = yf.Ticker(ticker_symbol)
            info = ticker.info
            if not info:
                lines.append(f"*Warning: No data for {ticker_symbol}*")
                continue

            results.append({
                'ticker': ticker_symbol,
                'name': info.get('shortName', ticker_symbol),
                'shares_short': info.get('sharesShort'),
                'short_ratio': info.get('shortRatio'),
                'short_pct_float': info.get('shortPercentOfFloat'),
                'shares_short_prior': info.get('sharesShortPriorMonth'),
                'float_shares': info.get('floatShares'),
                'shares_outstanding': info.get('sharesOutstanding'),
                'avg_volume': info.get('averageVolume'),
                'price': info.get('regularMarketPrice', info.get('currentPrice')),
            })
        except Exception as e:
            lines.append(f"*Error fetching {ticker_symbol}: {e}*")

    if not results:
        lines.append("*No short interest data available.*")
        return "\n".join(lines)

    # Write per-ticker cache files
    for r in results:
        single_report = _analyze_single_ticker(r)
        _write_cache(r['ticker'], "short_interest.md", single_report)

    # --- Table 1: Short Interest Summary ---
    lines.append("")
    lines.append("### Short Interest Summary")
    lines.append("| Ticker | Shares Short | Short Ratio | Short % Float | Change from Prior |")
    lines.append("| :--- | :--- | :--- | :--- | :--- |")

    for r in results:
        shares_short = r['shares_short']
        short_ratio = r['short_ratio']
        short_pct = r['short_pct_float']
        prior = r['shares_short_prior']

        ss_str = fmt_shares(shares_short)
        sr_str = f"{short_ratio:.2f}" if short_ratio is not None else "N/A"
        sp_str = fmt_pct(short_pct) if short_pct is not None else "N/A"

        # Change from prior month
        if shares_short is not None and prior is not None and prior > 0:
            change_pct = ((shares_short - prior) / prior) * 100
            change_str = f"{change_pct:+.1f}%"
            if change_pct > 0:
                change_str += " (increasing)"
            elif change_pct < 0:
                change_str += " (decreasing)"
        else:
            change_str = "N/A"

        lines.append(f"| {r['ticker']} | {ss_str} | {sr_str} | {sp_str} | {change_str} |")

    # --- Table 2: Squeeze Risk Assessment ---
    lines.append("")
    lines.append("### Squeeze Risk Assessment")
    lines.append("| Ticker | Risk Rating | Score (/100) | Key Factors |")
    lines.append("| :--- | :--- | :--- | :--- |")

    for r in results:
        score, rating, factors_str = _compute_squeeze_score(r)
        lines.append(f"| {r['ticker']} | {rating} | {score} | {factors_str} |")

    # --- Table 3: Context ---
    lines.append("")
    lines.append("### Context")
    lines.append("| Ticker | Float | Shares Outstanding | Avg Volume | Days to Cover |")
    lines.append("| :--- | :--- | :--- | :--- | :--- |")

    for r in results:
        float_str = fmt_shares(r['float_shares'])
        outstanding_str = fmt_shares(r['shares_outstanding'])
        avg_vol_str = fmt_shares(r['avg_volume'])
        dtc_str = f"{r['short_ratio']:.1f}" if r['short_ratio'] is not None else "N/A"

        lines.append(f"| {r['ticker']} | {float_str} | {outstanding_str} | {avg_vol_str} | {dtc_str} |")

    return "\n".join(lines)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 short_interest.py <TICKER> [TICKER2 ...]")
    else:
        report = analyze_short_interest([t.upper() for t in sys.argv[1:]])
        if report:
            print(report)
