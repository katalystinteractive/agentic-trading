import yfinance as yf
import pandas as pd
import sys
from datetime import datetime, timedelta

def fmt_value(val):
    """Format large numbers with M/B suffixes."""
    if pd.isna(val) or val is None:
        return "N/A"
    val = float(val)
    if abs(val) >= 1e9:
        return f"${val/1e9:.2f}B"
    elif abs(val) >= 1e6:
        return f"${val/1e6:.1f}M"
    else:
        return f"${val:,.0f}"

def quarter_label(dt):
    """Convert a date to Q1-Q4 YYYY format."""
    if isinstance(dt, pd.Timestamp):
        q = (dt.month - 1) // 3 + 1
        return f"Q{q} {dt.year}"
    return str(dt)

def get_price_reaction(ticker_symbol, earnings_date):
    """Calculate 1-day and 5-day price reaction around earnings date."""
    try:
        start = earnings_date - timedelta(days=7)
        end = earnings_date + timedelta(days=12)
        df = yf.download(ticker_symbol, start=start, end=end, progress=False)
        if df.empty:
            return None, None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Find the last trading day before/on earnings and after
        ed_ts = pd.Timestamp(earnings_date)
        pre = df[df.index <= ed_ts]
        post = df[df.index > ed_ts]

        if pre.empty or post.empty:
            return None, None

        pre_close = pre['Close'].iloc[-1]

        # 1-day reaction
        day1_pct = None
        if len(post) >= 1:
            day1_pct = ((post['Close'].iloc[0] - pre_close) / pre_close) * 100

        # 5-day reaction
        day5_pct = None
        if len(post) >= 5:
            day5_pct = ((post['Close'].iloc[4] - pre_close) / pre_close) * 100
        elif len(post) >= 1:
            day5_pct = ((post['Close'].iloc[-1] - pre_close) / pre_close) * 100

        return day1_pct, day5_pct
    except Exception:
        return None, None

def analyze_earnings(ticker_symbol):
    try:
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info
        if not info or info.get('regularMarketPrice') is None:
            print(f"Error: Could not fetch data for {ticker_symbol}")
            return
    except Exception as e:
        print(f"Error: {e}")
        return

    company_name = info.get('shortName', ticker_symbol)
    print(f"\n## Earnings Analysis: {company_name} ({ticker_symbol})")

    # --- Table 1: Next Earnings ---
    print(f"\n### Next Earnings")
    print("| Metric | Value |")
    print("| :--- | :--- |")

    try:
        cal = ticker.calendar
        if cal is not None and isinstance(cal, dict):
            earnings_dates = cal.get('Earnings Date', [])
            if isinstance(earnings_dates, list) and len(earnings_dates) > 0:
                next_date = earnings_dates[0]
                if isinstance(next_date, pd.Timestamp):
                    next_date_dt = next_date.to_pydatetime()
                else:
                    next_date_dt = pd.Timestamp(next_date).to_pydatetime()

                days_until = (next_date_dt.date() - datetime.now().date()).days
                print(f"| Earnings Date | {next_date_dt.strftime('%Y-%m-%d')} |")
                print(f"| Days Until | {days_until} |")

                eps_est = cal.get('EPS Estimate', cal.get('Earnings Average', None))
                rev_est = cal.get('Revenue Estimate', cal.get('Revenue Average', None))
                if eps_est is not None:
                    print(f"| EPS Estimate | ${eps_est} |")
                if rev_est is not None:
                    print(f"| Revenue Estimate | {fmt_value(rev_est)} |")

                if 0 < days_until <= 14:
                    print(f"| **Earnings Rule** | **WARNING: <14 days — avoid new entries** |")
                elif days_until <= 0:
                    print(f"| Earnings Rule | Recently reported |")
                else:
                    print(f"| Earnings Rule | Clear (>{days_until}d out) |")

                if len(earnings_dates) > 1:
                    end_date = earnings_dates[1]
                    if isinstance(end_date, pd.Timestamp):
                        print(f"| Date Range | {next_date_dt.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')} |")
            else:
                print("| Earnings Date | Not available |")
        else:
            print("| Earnings Date | Not available |")
    except Exception as e:
        print(f"| Error | {e} |")

    # --- Table 2: Earnings History ---
    print(f"\n### Earnings History")
    print("| Quarter | EPS Est | EPS Actual | Surprise% | 1-Day% | 5-Day% | Reaction |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    earnings_data = None

    # Try earnings_dates first (requires lxml, has more data)
    try:
        ed = ticker.earnings_dates
        if ed is not None and not ed.empty:
            earnings_data = ed
    except Exception:
        pass

    if earnings_data is not None and not earnings_data.empty:
        # Filter to past dates only (handle timezone-aware index)
        if earnings_data.index.tz is not None:
            now = pd.Timestamp.now(tz=earnings_data.index.tz)
        else:
            now = pd.Timestamp.now()
        past_earnings = earnings_data[earnings_data.index <= now].head(8)

        for date_idx, row in past_earnings.iterrows():
            q_label = quarter_label(date_idx)
            eps_est = row.get('EPS Estimate', None)
            eps_actual = row.get('Reported EPS', None)
            surprise = row.get('Surprise(%)', None)

            eps_est_str = f"${eps_est:.2f}" if pd.notna(eps_est) else "N/A"
            eps_actual_str = f"${eps_actual:.2f}" if pd.notna(eps_actual) else "N/A"
            surprise_str = f"{surprise:.1f}%" if pd.notna(surprise) else "N/A"

            # Price reaction — strip timezone for yf.download compatibility
            naive_date = date_idx.tz_localize(None) if date_idx.tz else date_idx
            day1, day5 = get_price_reaction(ticker_symbol, naive_date.to_pydatetime())
            day1_str = f"{day1:+.1f}%" if day1 is not None else "N/A"
            day5_str = f"{day5:+.1f}%" if day5 is not None else "N/A"

            # Reaction label
            if day1 is not None:
                if day1 > 3:
                    reaction = "Strong Bull"
                elif day1 > 0:
                    reaction = "Bullish"
                elif day1 > -3:
                    reaction = "Bearish"
                else:
                    reaction = "Strong Bear"
            else:
                reaction = "N/A"

            print(f"| {q_label} | {eps_est_str} | {eps_actual_str} | {surprise_str} | {day1_str} | {day5_str} | {reaction} |")
    else:
        # Fallback: try earnings_history (no lxml needed, limited to 4 quarters)
        try:
            eh = ticker.earnings_history
            if eh is not None and not eh.empty:
                for _, row in eh.iterrows():
                    q_label = quarter_label(row.name) if hasattr(row, 'name') else "N/A"
                    eps_est = row.get('epsEstimate', None)
                    eps_actual = row.get('epsActual', None)
                    surprise = row.get('surprisePercent', None)

                    eps_est_str = f"${eps_est:.2f}" if pd.notna(eps_est) else "N/A"
                    eps_actual_str = f"${eps_actual:.2f}" if pd.notna(eps_actual) else "N/A"
                    surprise_str = f"{surprise:.1f}%" if pd.notna(surprise) else "N/A"

                    print(f"| {q_label} | {eps_est_str} | {eps_actual_str} | {surprise_str} | N/A | N/A | N/A |")
            else:
                print("| — | No earnings history available | — | — | — | — | — |")
        except Exception:
            print("| — | No earnings history available | — | — | — | — | — |")

    # --- Table 3: Revenue Trend ---
    print(f"\n### Revenue Trend")
    print("| Quarter | Revenue | QoQ Growth% | YoY Growth% |")
    print("| :--- | :--- | :--- | :--- |")

    try:
        qf = ticker.quarterly_financials
        if qf is not None and not qf.empty:
            # quarterly_financials has dates as columns, metrics as rows
            rev_row = None
            for label in ['Total Revenue', 'Revenue', 'Operating Revenue']:
                if label in qf.index:
                    rev_row = qf.loc[label]
                    break

            if rev_row is not None:
                revenues = rev_row.dropna().sort_index(ascending=False).head(8)

                rev_list = []
                for date_col in revenues.index:
                    rev_list.append({
                        'date': date_col,
                        'quarter': quarter_label(date_col),
                        'revenue': revenues[date_col]
                    })

                for i, item in enumerate(rev_list):
                    rev_str = fmt_value(item['revenue'])

                    # QoQ: compare to next item (previous quarter chronologically)
                    qoq_str = "N/A"
                    if i + 1 < len(rev_list) and rev_list[i+1]['revenue'] != 0:
                        qoq = ((item['revenue'] - rev_list[i+1]['revenue']) / abs(rev_list[i+1]['revenue'])) * 100
                        qoq_str = f"{qoq:+.1f}%"

                    # YoY: compare to item 4 quarters back
                    yoy_str = "N/A"
                    if i + 4 < len(rev_list) and rev_list[i+4]['revenue'] != 0:
                        yoy = ((item['revenue'] - rev_list[i+4]['revenue']) / abs(rev_list[i+4]['revenue'])) * 100
                        yoy_str = f"{yoy:+.1f}%"

                    print(f"| {item['quarter']} | {rev_str} | {qoq_str} | {yoy_str} |")
            else:
                print("| — | No revenue data available | — | — |")
        else:
            print("| — | No quarterly financials available | — | — |")
    except Exception as e:
        print(f"| Error | {e} | — | — |")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 earnings_analyzer.py <TICKER>")
    else:
        analyze_earnings(sys.argv[1].upper())
