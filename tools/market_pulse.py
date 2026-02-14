import yfinance as yf
import pandas as pd
import numpy as np
import sys
from datetime import datetime

INDICES = {
    'S&P 500': 'SPY',
    'Nasdaq 100': 'QQQ',
    'Russell 2000': 'IWM',
}

VOLATILITY_RATES = {
    'VIX': '^VIX',
    '10Y Yield': '^TNX',
}

SECTORS = {
    'Technology': 'XLK',
    'Financial': 'XLF',
    'Energy': 'XLE',
    'Healthcare': 'XLV',
    'Industrial': 'XLI',
    'Comm Services': 'XLC',
    'Cons Cyclical': 'XLY',
    'Cons Defensive': 'XLP',
    'Real Estate': 'XLRE',
    'Utilities': 'XLU',
    'Materials': 'XLB',
}

def safe_pct_change(series, periods):
    """Calculate percentage change safely."""
    if len(series) <= periods:
        return None
    return ((series.iloc[-1] - series.iloc[-periods-1]) / series.iloc[-periods-1]) * 100

def sma(series, period):
    return series.rolling(window=period).mean()

def market_pulse():
    print(f"\n## Market Pulse")
    print(f"*{datetime.now().strftime('%Y-%m-%d %H:%M')}*")

    # Download all tickers at once for efficiency
    all_tickers = list(INDICES.values()) + list(VOLATILITY_RATES.values()) + list(SECTORS.values())
    try:
        data = yf.download(all_tickers, period="3mo", interval="1d", progress=False, group_by='ticker')
    except Exception as e:
        print(f"Error downloading market data: {e}")
        return

    def get_close(ticker_data):
        """Extract close prices from downloaded data."""
        if isinstance(ticker_data, pd.DataFrame):
            if isinstance(ticker_data.columns, pd.MultiIndex):
                ticker_data.columns = ticker_data.columns.get_level_values(0)
            if 'Close' in ticker_data.columns:
                return ticker_data['Close'].dropna()
        return pd.Series(dtype=float)

    def get_ticker_data(symbol):
        """Extract data for a specific ticker from grouped download."""
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

    # --- Table 1: Major Indices ---
    print(f"\n### Major Indices")
    print("| Index | ETF | Price | Day% | 5D% | Trend (50-SMA) |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- |")

    indices_above_sma = 0
    indices_total = 0

    for name, symbol in INDICES.items():
        closes = get_ticker_data(symbol)
        if closes.empty:
            print(f"| {name} | {symbol} | N/A | N/A | N/A | N/A |")
            continue

        price = closes.iloc[-1]
        day_chg = safe_pct_change(closes, 1)
        five_d_chg = safe_pct_change(closes, 5)
        sma_50 = sma(closes, 50).iloc[-1] if len(closes) >= 50 else None

        day_str = f"{day_chg:+.2f}%" if day_chg is not None else "N/A"
        five_d_str = f"{five_d_chg:+.2f}%" if five_d_chg is not None else "N/A"

        if sma_50 is not None and not pd.isna(sma_50):
            trend = "Above 50-SMA" if price > sma_50 else "Below 50-SMA"
            indices_total += 1
            if price > sma_50:
                indices_above_sma += 1
        else:
            trend = "N/A"

        print(f"| {name} | {symbol} | ${price:.2f} | {day_str} | {five_d_str} | {trend} |")

    # --- Table 2: Volatility & Rates ---
    print(f"\n### Volatility & Rates")
    print("| Indicator | Value | Interpretation |")
    print("| :--- | :--- | :--- |")

    vix_val = None
    for name, symbol in VOLATILITY_RATES.items():
        closes = get_ticker_data(symbol)
        if closes.empty:
            print(f"| {name} | N/A | N/A |")
            continue

        val = closes.iloc[-1]

        if name == 'VIX':
            vix_val = val
            if val < 15:
                interp = "Low — Complacency"
            elif val < 20:
                interp = "Normal — Stable"
            elif val < 30:
                interp = "Elevated — Caution"
            else:
                interp = "High — Fear"
            print(f"| {name} | {val:.2f} | {interp} |")
        elif name == '10Y Yield':
            day_chg = safe_pct_change(closes, 1)
            chg_str = f" ({day_chg:+.2f}% day)" if day_chg is not None else ""
            print(f"| {name} | {val:.2f}%{chg_str} | Treasury benchmark |")

    # --- Table 3: Sector Performance ---
    print(f"\n### Sector Performance (Ranked by Daily)")
    print("| Sector | ETF | Day% | 5D% | 20D% |")
    print("| :--- | :--- | :--- | :--- | :--- |")

    sector_data = []
    for name, symbol in SECTORS.items():
        closes = get_ticker_data(symbol)
        if closes.empty:
            continue

        day_chg = safe_pct_change(closes, 1)
        five_d_chg = safe_pct_change(closes, 5)
        twenty_d_chg = safe_pct_change(closes, 20)

        sector_data.append({
            'name': name,
            'symbol': symbol,
            'day': day_chg,
            'five_d': five_d_chg,
            'twenty_d': twenty_d_chg,
        })

    # Sort by daily performance
    sector_data.sort(key=lambda x: x['day'] if x['day'] is not None else -999, reverse=True)

    for s in sector_data:
        day_str = f"{s['day']:+.2f}%" if s['day'] is not None else "N/A"
        five_str = f"{s['five_d']:+.2f}%" if s['five_d'] is not None else "N/A"
        twenty_str = f"{s['twenty_d']:+.2f}%" if s['twenty_d'] is not None else "N/A"
        print(f"| {s['name']} | {s['symbol']} | {day_str} | {five_str} | {twenty_str} |")

    # --- Table 4: Market Regime ---
    print(f"\n### Market Regime")
    print("| Metric | Value |")
    print("| :--- | :--- |")

    if indices_total > 0 and vix_val is not None:
        majority_above = indices_above_sma > indices_total / 2

        if majority_above and vix_val < 20:
            regime = "Risk-On"
            reasoning = f"{indices_above_sma}/{indices_total} indices above 50-SMA, VIX {vix_val:.1f} (low)"
        elif not majority_above and vix_val > 25:
            regime = "Risk-Off"
            reasoning = f"{indices_above_sma}/{indices_total} indices above 50-SMA, VIX {vix_val:.1f} (elevated)"
        else:
            regime = "Neutral/Transitional"
            reasoning = f"{indices_above_sma}/{indices_total} indices above 50-SMA, VIX {vix_val:.1f}"

        print(f"| Regime | **{regime}** |")
        print(f"| Reasoning | {reasoning} |")
    else:
        print("| Regime | Insufficient data |")
        print("| Reasoning | Could not determine market regime |")

    # Leading/Lagging sectors
    if sector_data:
        leaders = [s['name'] for s in sector_data[:3] if s['day'] is not None and s['day'] > 0]
        laggards = [s['name'] for s in sector_data[-3:] if s['day'] is not None and s['day'] < 0]
        if leaders:
            print(f"| Leading Sectors | {', '.join(leaders)} |")
        if laggards:
            print(f"| Lagging Sectors | {', '.join(laggards)} |")

if __name__ == "__main__":
    market_pulse()
