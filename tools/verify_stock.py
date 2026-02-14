import yfinance as yf
import pandas as pd
import sys
import datetime
from dateutil.relativedelta import relativedelta

def analyze_stock(ticker):
    # 1. Fetch Data (13 months + buffer)
    end_date = datetime.datetime.now()
    start_date = end_date - relativedelta(months=14)
    
    try:
        df = yf.download(ticker, start=start_date, end=end_date, progress=False)
        if df.empty:
            print(f"Error: No data found for {ticker}")
            return
    except Exception as e:
        print(f"Error fetching data: {e}")
        return

    # Flatten MultiIndex columns if present (yfinance update)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # 2. Monthly Cycle Audit
    print(f"\n### 2. The 13-Month Cycle Audit Table ({ticker})")
    print("| Month | Low ($) & Date | High ($) & Date | Swing % | Drop from Prev High | Bottom Timing |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- |")

    # Resample to monthly to find high/low info, but we need exact dates
    # So we iterate month by month
    
    # We will store monthly stats to calc "Drop from Prev High"
    monthly_stats = []

    current_month = end_date.replace(day=1)
    for i in range(13):
        # Calculate window
        month_start = (current_month - relativedelta(months=i)).replace(day=1)
        month_end = month_start + relativedelta(months=1) - relativedelta(days=1)
        
        # Filter data
        mask = (df.index >= pd.Timestamp(month_start)) & (df.index <= pd.Timestamp(month_end))
        month_data = df.loc[mask]
        
        if month_data.empty:
            continue

        low_price = month_data['Low'].min()
        low_date = month_data['Low'].idxmin().day
        high_price = month_data['High'].max()
        high_date = month_data['High'].idxmax().day
        
        swing_pct = ((high_price - low_price) / low_price) * 100
        
        # Determine Timing
        if low_date <= 10: timing = "Early"
        elif low_date >= 20: timing = "Late"
        else: timing = "Mid"
        
        monthly_stats.append({
            'month': month_start.strftime("%b %Y"),
            'low': low_price,
            'low_date': low_date,
            'high': high_price,
            'high_date': high_date,
            'swing': swing_pct,
            'timing': timing,
            'raw_high': high_price # for calculation
        })

    # Print Table (Reverse order to show newest first)
    prev_high = None
    for stat in monthly_stats:
        drop_str = "-"
        # We need the "Previous Month's High" (which is the next item in this reversed list, 
        # but logically the previous month in time). 
        # Actually, let's reverse the list first to process chronologically, then print reversed.
        pass

    monthly_stats.reverse() # Now Chronological (Oldest -> Newest) 
    
    processed_stats = []
    for i, stat in enumerate(monthly_stats):
        drop_pct = 0.0
        if i > 0:
            prev_high = monthly_stats[i-1]['raw_high']
            curr_low = stat['low']
            drop_pct = ((prev_high - curr_low) / prev_high) * 100
            drop_str = f"-{drop_pct:.1f}%"
        else:
            drop_str = "-"
            
        stat['drop_str'] = drop_str
        processed_stats.append(stat)

    processed_stats.reverse() # Newest first for display

    for stat in processed_stats:
        print(f"| {stat['month']} | ${stat['low']:.2f} ({stat['low_date']}) | ${stat['high']:.2f} ({stat['high_date']}) | {stat['swing']:.1f}% | {stat['drop_str']} | {stat['timing']} |")

    # 3. Volume Profile Audit (6 Months)
    print(f"\n### 3. The High Volume Node (HVN) Audit Table (Last 6 Months)")
    print("| Price Zone ($) | Volume Intensity | Role | Approx Date |")
    print("| :--- | :--- | :--- | :--- |")
    
    # Filter last 6 months
    six_mo_start = end_date - relativedelta(months=6)
    recent_data = df.loc[df.index >= pd.Timestamp(six_mo_start)].copy()
    
    # Simple Volume Profile: Bin prices and sum volume
    # Create price bins (e.g., $0.50 increments)
    min_p = int(recent_data['Low'].min())
    max_p = int(recent_data['High'].max()) + 1
    
    bins = range(min_p, max_p + 1)
    # Use 'Close' for binning volume
    recent_data['PriceBin'] = pd.cut(recent_data['Close'], bins=len(bins)*2) 
    
    # Group by bin
    vol_profile = recent_data.groupby('PriceBin', observed=True)['Volume'].sum().reset_index()
    vol_profile = vol_profile.sort_values('Volume', ascending=False).head(5)
    
    for index, row in vol_profile.iterrows():
        interval = row['PriceBin']
        vol_m = row['Volume'] / 1_000_000
        
        # Find dates where price was in this bin
        mask_bin = (recent_data['Close'] >= interval.left) & (recent_data['Close'] <= interval.right)
        dates_in_bin = recent_data.loc[mask_bin].index
        if not dates_in_bin.empty:
            date_str = dates_in_bin[0].strftime("%b") # Just first month for context
        else:
            date_str = "N/A"

        print(f"| ${interval.left:.2f} - ${interval.right:.2f} | {vol_m:.1f}M | HVN | {date_str} |")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python verify_stock.py <TICKER>")
    else:
        analyze_stock(sys.argv[1])
