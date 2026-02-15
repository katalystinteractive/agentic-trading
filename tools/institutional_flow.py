import yfinance as yf
import pandas as pd
import sys
from pathlib import Path
from datetime import datetime, timedelta

_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = _ROOT / "agents"


def _write_cache(ticker, filename, report):
    agent_dir = AGENTS_DIR / ticker
    agent_dir.mkdir(parents=True, exist_ok=True)
    with open(agent_dir / filename, "w") as f:
        f.write(report + "\n")


def fmt_value(val):
    """Format large numbers with M/B suffixes."""
    if pd.isna(val) or val is None:
        return "N/A"
    val = float(val)
    if abs(val) >= 1e9:
        return f"${val/1e9:.2f}B"
    elif abs(val) >= 1e6:
        return f"${val/1e6:.1f}M"
    elif abs(val) >= 1e3:
        return f"${val/1e3:.0f}K"
    else:
        return f"${val:,.0f}"

def fmt_shares(val):
    """Format share counts with M/K suffixes."""
    if pd.isna(val) or val is None:
        return "N/A"
    val = float(val)
    if abs(val) >= 1e6:
        return f"{val/1e6:.2f}M"
    elif abs(val) >= 1e3:
        return f"{val/1e3:.0f}K"
    else:
        return f"{val:,.0f}"

def fmt_pct(val):
    """Format percentage values."""
    if pd.isna(val) or val is None:
        return "N/A"
    return f"{float(val)*100:.2f}%" if abs(float(val)) < 1 else f"{float(val):.2f}%"

def analyze_institutional_flow(ticker_symbol):
    lines = []
    try:
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info
        if not info or info.get('regularMarketPrice') is None:
            print(f"*Error: Could not fetch data for {ticker_symbol}*")
            return None
    except Exception as e:
        print(f"*Error: {e}*")
        return None

    lines.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    lines.append("")

    company_name = info.get('shortName', ticker_symbol)
    lines.append(f"## Institutional & Insider Flow: {company_name} ({ticker_symbol})")

    # --- Table 1: Top Institutional Holders ---
    lines.append("")
    lines.append("### Top Institutional Holders")
    inst = None
    try:
        inst = ticker.institutional_holders
        if inst is not None and not inst.empty:
            lines.append("| # | Holder | Shares | Value | % Out | % Change | Date Reported |")
            lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
            for i, row in inst.head(10).iterrows():
                holder = row.get('Holder', 'N/A')
                shares = fmt_shares(row.get('Shares'))
                value = fmt_value(row.get('Value'))
                pct_held = fmt_pct(row.get('pctHeld', row.get('% Out', None)))
                pct_change = fmt_pct(row.get('pctChange', row.get('% Change', None)))
                date_rep = row.get('Date Reported', 'N/A')
                if isinstance(date_rep, pd.Timestamp):
                    date_rep = date_rep.strftime('%Y-%m-%d')
                lines.append(f"| {i+1} | {holder} | {shares} | {value} | {pct_held} | {pct_change} | {date_rep} |")
        else:
            lines.append("*No institutional holder data available.*")
    except Exception as e:
        lines.append(f"*Error fetching institutional holders: {e}*")

    # --- Table 2: Top Mutual Fund Holders ---
    lines.append("")
    lines.append("### Top Mutual Fund Holders")
    try:
        mf = ticker.mutualfund_holders
        if mf is not None and not mf.empty:
            lines.append("| # | Fund | Shares | Value | % Out | % Change | Date Reported |")
            lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
            for i, row in mf.head(10).iterrows():
                fund = row.get('Holder', 'N/A')
                shares = fmt_shares(row.get('Shares'))
                value = fmt_value(row.get('Value'))
                pct_held = fmt_pct(row.get('pctHeld', row.get('% Out', None)))
                pct_change = fmt_pct(row.get('pctChange', row.get('% Change', None)))
                date_rep = row.get('Date Reported', 'N/A')
                if isinstance(date_rep, pd.Timestamp):
                    date_rep = date_rep.strftime('%Y-%m-%d')
                lines.append(f"| {i+1} | {fund} | {shares} | {value} | {pct_held} | {pct_change} | {date_rep} |")
        else:
            lines.append("*No mutual fund holder data available.*")
    except Exception as e:
        lines.append(f"*Error fetching mutual fund holders: {e}*")

    # --- Table 3: Recent Insider Transactions ---
    lines.append("")
    lines.append("### Recent Insider Transactions")
    try:
        insiders = ticker.insider_transactions
        if insiders is not None and not insiders.empty:
            lines.append("| Date | Insider | Title | Type | Shares | Value | Signal |")
            lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

            buy_dates = []
            buy_insiders = set()
            net_shares = 0
            total_buys = 0
            total_sells = 0

            cutoff_90d = datetime.now() - timedelta(days=90)

            for _, row in insiders.head(20).iterrows():
                insider_name = str(row.get('Insider', row.get('Insider Trading', 'N/A')))
                title = str(row.get('Position', ''))
                text = str(row.get('Text', ''))
                shares = row.get('Shares', 0)
                value = row.get('Value', 0)
                start_date = row.get('Start Date', None)

                # Parse transaction type from Text field
                text_lower = text.lower()
                if 'purchase' in text_lower or 'buy' in text_lower:
                    txn_type = "BUY"
                    signal = "Bullish"
                elif 'sale' in text_lower or 'sell' in text_lower:
                    txn_type = "SELL"
                    signal = "—"
                elif 'option' in text_lower and 'exercise' in text_lower:
                    txn_type = "OPT EX"
                    signal = "—"
                else:
                    txn_type = "OTHER"
                    signal = "—"

                # Track for summary
                if isinstance(start_date, pd.Timestamp):
                    if start_date >= pd.Timestamp(cutoff_90d):
                        if txn_type == "BUY":
                            net_shares += (shares if shares else 0)
                            total_buys += 1
                            buy_dates.append(start_date)
                            buy_insiders.add(insider_name)
                        elif txn_type == "SELL":
                            net_shares -= (shares if shares else 0)
                            total_sells += 1

                date_str = start_date.strftime('%Y-%m-%d') if isinstance(start_date, pd.Timestamp) else str(start_date)
                shares_str = fmt_shares(shares)
                value_str = fmt_value(value)

                # Truncate long names
                if len(insider_name) > 30:
                    insider_name = insider_name[:28] + ".."
                if len(title) > 20:
                    title = title[:18] + ".."

                lines.append(f"| {date_str} | {insider_name} | {title} | {txn_type} | {shares_str} | {value_str} | {signal} |")

            # --- Table 4: Flow Summary ---
            lines.append("")
            lines.append("### Flow Summary (Last 90 Days)")
            lines.append("| Metric | Value |")
            lines.append("| :--- | :--- |")

            lines.append(f"| Net Insider Activity | {total_buys} buys, {total_sells} sells |")
            lines.append(f"| Net Shares | {fmt_shares(net_shares)} |")

            # Cluster buy detection: 2+ unique insiders buying within 14 days
            cluster_signal = "No"
            if len(buy_dates) >= 2:
                buy_dates_sorted = sorted(buy_dates)
                for i in range(len(buy_dates_sorted) - 1):
                    diff = (buy_dates_sorted[i+1] - buy_dates_sorted[i]).days
                    if diff <= 14 and len(buy_insiders) >= 2:
                        cluster_signal = "YES — Bullish"
                        break

            lines.append(f"| Cluster Buy Signal | {cluster_signal} |")

            # Largest position changes from institutional holders
            try:
                if inst is not None and not inst.empty:
                    pct_col = 'pctChange' if 'pctChange' in inst.columns else '% Change'
                    if pct_col in inst.columns:
                        inst_sorted = inst.dropna(subset=[pct_col])
                        if not inst_sorted.empty:
                            largest = inst_sorted.iloc[0]
                            holder = largest.get('Holder', 'N/A')
                            change = largest.get(pct_col, 0)
                            change_str = fmt_pct(change)
                            lines.append(f"| Largest Inst. Change | {holder}: {change_str} |")
            except Exception:
                pass

        else:
            lines.append("*No insider transaction data available.*")

            # Still print summary even without insider data
            lines.append("")
            lines.append("### Flow Summary")
            lines.append("| Metric | Value |")
            lines.append("| :--- | :--- |")
            lines.append("| Net Insider Activity | No data available |")
            lines.append("| Cluster Buy Signal | N/A |")
    except Exception as e:
        lines.append(f"*Error fetching insider transactions: {e}*")

    # --- Table 5: Smart Money Signal (from institutional holders) ---
    try:
        if inst is not None and not inst.empty:
            pct_col = 'pctChange' if 'pctChange' in inst.columns else '% Change'
            if pct_col in inst.columns:
                valid = inst.dropna(subset=[pct_col])
                if not valid.empty:
                    increasing = valid[valid[pct_col] > 0]
                    decreasing = valid[valid[pct_col] < 0]
                    total = len(valid)
                    inc_count = len(increasing)
                    avg_change = valid[pct_col].mean()

                    # Rating
                    ratio = inc_count / total if total > 0 else 0
                    if ratio >= 0.8:
                        signal = "STRONG ACCUMULATION"
                    elif ratio >= 0.6:
                        signal = "ACCUMULATION"
                    elif ratio >= 0.4:
                        signal = "MIXED"
                    elif ratio >= 0.2:
                        signal = "DISTRIBUTION"
                    else:
                        signal = "STRONG DISTRIBUTION"

                    lines.append("")
                    lines.append("### Smart Money Signal")
                    lines.append("| Metric | Value |")
                    lines.append("| :--- | :--- |")
                    lines.append(f"| Signal | **{signal}** |")
                    lines.append(f"| Holders Increasing | {inc_count}/{total} |")
                    lines.append(f"| Holders Decreasing | {len(decreasing)}/{total} |")
                    lines.append(f"| Avg Position Change | {avg_change * 100:+.1f}% |")

                    # Top accumulators (sorted by % change, >20% only)
                    big_movers = valid[valid[pct_col] > 0.20].sort_values(pct_col, ascending=False)
                    if not big_movers.empty:
                        lines.append("")
                        lines.append("### Aggressive Accumulators (>20% increase)")
                        lines.append("| Holder | % Change | Shares | Value |")
                        lines.append("| :--- | :--- | :--- | :--- |")
                        for _, row in big_movers.iterrows():
                            holder = row.get('Holder', 'N/A')
                            pct_val = row.get(pct_col, 0)
                            change_str = f"{float(pct_val) * 100:+.1f}%"
                            shares = fmt_shares(row.get('Shares'))
                            value = fmt_value(row.get('Value'))
                            lines.append(f"| {holder} | {change_str} | {shares} | {value} |")
    except Exception:
        pass

    return "\n".join(lines)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 institutional_flow.py <TICKER>")
    else:
        ticker = sys.argv[1].upper()
        report = analyze_institutional_flow(ticker)
        if report:
            print(report)
            _write_cache(ticker, "institutional.md", report)
