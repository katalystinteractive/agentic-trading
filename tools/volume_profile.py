import yfinance as yf
import pandas as pd
import numpy as np
import sys
import argparse
from datetime import datetime, timedelta

def fetch_data(ticker, days=365):
    """
    Fetches historical data. 
    Tries to get hourly data for better granularity if within 730 days.
    Otherwise falls back to daily.
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    # yfinance limitation: 1h data only available for last 730 days
    interval = "1h" if days <= 730 else "1d"
    
    # Fetch silently — markdown-only output convention

    
    try:
        df = yf.download(ticker, start=start_date, end=end_date, interval=interval, progress=False)
        if df.empty:
            print(f"Error: No data found for {ticker}")
            return None
        
        # Flatten MultiIndex if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        return df
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None

def calculate_vwap(df):
    """Calculates Volume Weighted Average Price."""
    v = df['Volume'].values
    tp = (df['High'] + df['Low'] + df['Close']) / 3
    return (tp * v).cumsum() / v.cumsum()

def get_volume_profile(df, price_bins=50):
    """
    Calculates Volume Profile with Buy/Sell approximation.
    """
    # 1. Determine Price Range
    min_price = df['Low'].min()
    max_price = df['High'].max()
    
    # 2. Create Bins
    bins = np.linspace(min_price, max_price, price_bins + 1)
    
    # 3. Assign volume to bins
    # We use the 'Typical Price' of the candle to assign its volume to a bin
    df['Typical_Price'] = (df['High'] + df['Low'] + df['Close']) / 3
    
    # Buy/Sell classification (Approximation: Close > Open = Buy)
    # Note: For flat candles, we assume neutral (or split, but here we ignore for simplicity or treat as neutral)
    df['Direction'] = np.where(df['Close'] >= df['Open'], 'Buy', 'Sell')
    
    df['Bin'] = pd.cut(df['Typical_Price'], bins=bins, labels=False, include_lowest=True)
    
    # Aggregate
    profile = df.groupby(['Bin', 'Direction'])['Volume'].sum().unstack(fill_value=0)
    
    # Ensure both columns exist
    if 'Buy' not in profile.columns: profile['Buy'] = 0
    if 'Sell' not in profile.columns: profile['Sell'] = 0
    
    profile['Total'] = profile['Buy'] + profile['Sell']
    
    # Map bins back to price ranges
    bin_mapping = {i: (bins[i], bins[i+1]) for i in range(len(bins)-1)}
    
    result = []
    for bin_idx in profile.index:
        if bin_idx not in bin_mapping: continue # Should not happen
        
        lower, upper = bin_mapping[bin_idx]
        mid = (lower + upper) / 2
        buy_vol = profile.loc[bin_idx, 'Buy']
        sell_vol = profile.loc[bin_idx, 'Sell']
        total_vol = profile.loc[bin_idx, 'Total']
        
        result.append({
            'bin_mid': mid,
            'price_range': f"{lower:.2f}-{upper:.2f}",
            'buy_vol': buy_vol,
            'sell_vol': sell_vol,
            'total_vol': total_vol
        })
        
    return pd.DataFrame(result).sort_values('bin_mid', ascending=False)

def fmt_vol(val):
    """Format volume with M/K suffixes."""
    if val is None or (hasattr(val, '__class__') and val != val):
        return "N/A"
    val = float(val)
    if val >= 1e6:
        return f"{val/1e6:.1f}M"
    elif val >= 1e3:
        return f"{val/1e3:.0f}K"
    return f"{val:,.0f}"

def print_profile(profile_df, current_price, vwap_price):
    """Prints a markdown Volume Profile report."""
    if profile_df.empty:
        print("*No volume profile data to display.*")
        return

    max_vol = profile_df['total_vol'].max()
    if max_vol == 0:
        return

    # Find POC (Point of Control)
    poc_row = profile_df.loc[profile_df['total_vol'].idxmax()]
    poc_price = poc_row['bin_mid']

    print(f"\n## Volume Profile & Order Flow Audit")

    # --- Table 1: Key Levels ---
    print(f"\n### Key Levels")
    print("| Metric | Value |")
    print("| :--- | :--- |")
    print(f"| Current Price | ${current_price:.2f} |")
    print(f"| VWAP (Period) | ${vwap_price:.2f} |")
    print(f"| POC (High Vol Node) | ${poc_price:.2f} |")
    dist_poc = ((poc_price - current_price) / current_price) * 100
    print(f"| Distance to POC | {dist_poc:+.1f}% |")

    # --- Table 2: Volume Profile (top nodes only) ---
    # Filter to non-zero bins and show top 15 by volume
    active = profile_df[profile_df['total_vol'] > 0]
    top_nodes = active.nlargest(15, 'total_vol').sort_values('bin_mid', ascending=False)

    print(f"\n### Volume Distribution (Top Nodes)")
    print("| Price Range | Volume | Buy % | Sell % | Note |")
    print("| :--- | :--- | :--- | :--- | :--- |")

    for _, row in top_nodes.iterrows():
        total = row['total_vol']
        buy = row['buy_vol']
        sell = row['sell_vol']
        buy_pct = (buy / total * 100) if total > 0 else 0
        sell_pct = (sell / total * 100) if total > 0 else 0

        note = ""
        if row['bin_mid'] <= current_price * 1.01 and row['bin_mid'] >= current_price * 0.99:
            note = "**CURRENT**"
        elif row['bin_mid'] <= poc_price * 1.01 and row['bin_mid'] >= poc_price * 0.99:
            note = "**POC**"
        elif total >= max_vol * 0.7:
            note = "HVN"

        print(f"| {row['price_range']} | {fmt_vol(total)} | {buy_pct:.0f}% | {sell_pct:.0f}% | {note} |")

def main():
    parser = argparse.ArgumentParser(description="Detailed Volume Profile Analysis")
    parser.add_argument("ticker", type=str, help="Stock Ticker (e.g., NU)")
    parser.add_argument("--days", type=int, default=180, help="Lookback days (default: 180)")
    parser.add_argument("--bins", type=int, default=25, help="Number of price bins (default: 25)")
    
    args = parser.parse_args()
    
    df = fetch_data(args.ticker, args.days)
    if df is not None:
        # Calculate Current Price & VWAP
        current_price = df['Close'].iloc[-1]
        df['VWAP'] = calculate_vwap(df)
        last_vwap = df['VWAP'].iloc[-1]
        
        # Calculate Profile
        profile = get_volume_profile(df, price_bins=args.bins)
        
        # Print Report
        print_profile(profile, current_price, last_vwap)

if __name__ == "__main__":
    main()
