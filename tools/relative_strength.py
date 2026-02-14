import yfinance as yf
import pandas as pd
import numpy as np
import sys
from datetime import datetime
from dateutil.relativedelta import relativedelta

SECTOR_MAP = {
    'Technology': 'XLK',
    'Financial Services': 'XLF',
    'Energy': 'XLE',
    'Healthcare': 'XLV',
    'Industrials': 'XLI',
    'Communication Services': 'XLC',
    'Consumer Cyclical': 'XLY',
    'Consumer Defensive': 'XLP',
    'Real Estate': 'XLRE',
    'Utilities': 'XLU',
    'Basic Materials': 'XLB',
}

# Trading day equivalents
PERIODS = {
    '1W': 5,
    '1M': 21,
    '3M': 63,
    '6M': 126,
}

def calc_return(series, days):
    """Calculate return over N trading days."""
    if len(series) <= days:
        return None
    return ((series.iloc[-1] - series.iloc[-days-1]) / series.iloc[-days-1]) * 100

def analyze_relative_strength(ticker_symbol):
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
    sector = info.get('sector', None)

    # Map sector to ETF
    sector_etf = SECTOR_MAP.get(sector, 'XLK')  # Default to XLK if unknown
    if sector is None:
        sector = "Unknown"
        print(f"*Warning: Could not detect sector, using XLK as default benchmark.*")

    print(f"\n## Relative Strength: {company_name} ({ticker_symbol})")
    print(f"**Sector: {sector} ({sector_etf}) | Benchmark: SPY**")

    # Download comparative data
    end_date = datetime.now()
    start_date = end_date - relativedelta(months=7)  # Extra buffer for 6M calculation

    try:
        tickers_to_download = [ticker_symbol, sector_etf, 'SPY']
        data = yf.download(tickers_to_download, start=start_date, end=end_date, progress=False, group_by='ticker')
    except Exception as e:
        print(f"Error downloading data: {e}")
        return

    def get_close(symbol):
        """Extract close series for a ticker."""
        try:
            if isinstance(data.columns, pd.MultiIndex):
                if symbol in data.columns.get_level_values(0):
                    td = data[symbol]
                    return td['Close'].dropna() if 'Close' in td.columns else pd.Series(dtype=float)
            elif 'Close' in data.columns:
                return data['Close'].dropna()
        except Exception:
            pass
        return pd.Series(dtype=float)

    stock_close = get_close(ticker_symbol)
    sector_close = get_close(sector_etf)
    spy_close = get_close('SPY')

    if stock_close.empty:
        print(f"Error: No price data for {ticker_symbol}")
        return

    # --- Table 1: Performance Comparison ---
    print(f"\n### Performance Comparison")
    print(f"| Period | {ticker_symbol}% | {sector_etf}% | SPY% | vs Sector | vs SPY |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- |")

    stock_returns = {}
    sector_returns = {}
    spy_returns = {}

    for period_name, days in PERIODS.items():
        stock_ret = calc_return(stock_close, days)
        sect_ret = calc_return(sector_close, days)
        spy_ret = calc_return(spy_close, days)

        stock_returns[period_name] = stock_ret
        sector_returns[period_name] = sect_ret
        spy_returns[period_name] = spy_ret

        stock_str = f"{stock_ret:+.2f}%" if stock_ret is not None else "N/A"
        sect_str = f"{sect_ret:+.2f}%" if sect_ret is not None else "N/A"
        spy_str = f"{spy_ret:+.2f}%" if spy_ret is not None else "N/A"

        # Relative performance
        if stock_ret is not None and sect_ret is not None:
            vs_sector = stock_ret - sect_ret
            vs_sector_str = f"{vs_sector:+.2f}%"
        else:
            vs_sector_str = "N/A"

        if stock_ret is not None and spy_ret is not None:
            vs_spy = stock_ret - spy_ret
            vs_spy_str = f"{vs_spy:+.2f}%"
        else:
            vs_spy_str = "N/A"

        print(f"| {period_name} | {stock_str} | {sect_str} | {spy_str} | {vs_sector_str} | {vs_spy_str} |")

    # --- Table 2: RS Rating ---
    print(f"\n### Relative Strength Rating")
    print("| Metric | Value |")
    print("| :--- | :--- |")

    # RS Rating based on 3M relative performance vs SPY
    stock_3m = stock_returns.get('3M')
    spy_3m = spy_returns.get('3M')

    if stock_3m is not None and spy_3m is not None:
        relative_3m = stock_3m - spy_3m

        # Linear interpolation: -20% relative = 0, +20% relative = 100
        rs_rating = max(0, min(100, 50 + (relative_3m * 2.5)))

        if rs_rating >= 80:
            interp = "Strong Outperformer"
        elif rs_rating >= 60:
            interp = "Moderate Outperformer"
        elif rs_rating >= 40:
            interp = "In-Line"
        elif rs_rating >= 20:
            interp = "Moderate Underperformer"
        else:
            interp = "Strong Underperformer"

        print(f"| RS Rating | {rs_rating:.0f}/100 |")
        print(f"| 3M Relative vs SPY | {relative_3m:+.2f}% |")
        print(f"| Interpretation | {interp} |")
    else:
        print("| RS Rating | Insufficient data |")

    # --- Table 3: Money Flow Signal ---
    print(f"\n### Money Flow Signal")
    print("| Metric | Value |")
    print("| :--- | :--- |")

    outperform_count = 0
    underperform_count = 0
    total_periods = 0

    for period_name in PERIODS:
        stock_ret = stock_returns.get(period_name)
        sect_ret = sector_returns.get(period_name)
        if stock_ret is not None and sect_ret is not None:
            total_periods += 1
            if stock_ret > sect_ret:
                outperform_count += 1
            else:
                underperform_count += 1

    if total_periods > 0:
        if outperform_count > total_periods / 2:
            flow_signal = "INFLOW"
            flow_detail = f"Outperforms sector in {outperform_count}/{total_periods} timeframes"
        else:
            flow_signal = "OUTFLOW"
            flow_detail = f"Underperforms sector in {underperform_count}/{total_periods} timeframes"

        print(f"| Signal | **{flow_signal}** |")
        print(f"| Detail | {flow_detail} |")
    else:
        print("| Signal | Insufficient data |")

    # --- Table 4: Rotation Status ---
    print(f"\n### Rotation Status")
    print("| Metric | Value |")
    print("| :--- | :--- |")

    stock_3m = stock_returns.get('3M')
    stock_1m = stock_returns.get('1M')
    sect_3m = sector_returns.get('3M')
    sect_1m = sector_returns.get('1M')
    spy_3m_val = spy_returns.get('3M')
    spy_1m = spy_returns.get('1M')

    if all(v is not None for v in [stock_3m, stock_1m, sect_3m, sect_1m, spy_3m_val, spy_1m]):
        beats_sector_3m = stock_3m > sect_3m
        beats_spy_3m = stock_3m > spy_3m_val
        beats_sector_1m = stock_1m > sect_1m
        beats_spy_1m = stock_1m > spy_1m

        if beats_sector_3m and beats_spy_3m:
            if beats_sector_1m and beats_spy_1m:
                status = "Leading"
                implication = "Strong momentum — continue to hold/add"
            else:
                status = "Weakening"
                implication = "Was leading, losing momentum — watch closely"
        elif not beats_sector_3m and not beats_spy_3m:
            if beats_sector_1m or beats_spy_1m:
                status = "Improving"
                implication = "Was lagging, gaining momentum — potential entry"
            else:
                status = "Lagging"
                implication = "Underperforming on all timeframes — avoid/reduce"
        else:
            # Mixed: check momentum direction
            momentum_improving = (stock_1m - sect_1m) > (stock_3m / 3 - sect_3m / 3)
            if momentum_improving:
                status = "Improving"
                implication = "Mixed signals but momentum improving"
            else:
                status = "Weakening"
                implication = "Mixed signals with fading momentum"

        print(f"| Rotation Status | **{status}** |")
        print(f"| Implication | {implication} |")
    else:
        print("| Rotation Status | Insufficient data |")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 relative_strength.py <TICKER>")
    else:
        analyze_relative_strength(sys.argv[1].upper())
