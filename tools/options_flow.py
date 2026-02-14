import yfinance as yf
import pandas as pd
import numpy as np
import sys

def fmt_number(val):
    """Format numbers with K/M suffixes."""
    if pd.isna(val) or val is None:
        return "N/A"
    val = float(val)
    if abs(val) >= 1e6:
        return f"{val/1e6:.1f}M"
    elif abs(val) >= 1e3:
        return f"{val/1e3:.0f}K"
    else:
        return f"{val:,.0f}"

def calc_max_pain(calls_df, puts_df, current_price):
    """Calculate max pain: strike where total option holder losses are minimized."""
    all_strikes = sorted(set(calls_df['strike'].tolist() + puts_df['strike'].tolist()))

    if not all_strikes:
        return None

    min_pain = float('inf')
    max_pain_strike = None

    for test_strike in all_strikes:
        total_pain = 0

        # Call holder pain: calls are ITM when price > strike
        for _, row in calls_df.iterrows():
            if test_strike > row['strike']:
                total_pain += (test_strike - row['strike']) * row.get('openInterest', 0)

        # Put holder pain: puts are ITM when price < strike
        for _, row in puts_df.iterrows():
            if test_strike < row['strike']:
                total_pain += (row['strike'] - test_strike) * row.get('openInterest', 0)

        if total_pain < min_pain:
            min_pain = total_pain
            max_pain_strike = test_strike

    return max_pain_strike

def analyze_options(ticker_symbol):
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
    current_price = info.get('regularMarketPrice', info.get('currentPrice', 0))

    print(f"\n## Options Flow: {company_name} ({ticker_symbol})")
    print(f"**Current Price: ${current_price:.2f}**")

    # Get expiration dates
    try:
        expirations = ticker.options
    except Exception as e:
        print(f"Error: No options data available for {ticker_symbol}: {e}")
        return

    if not expirations:
        print("\n*No options data available.*")
        return

    # --- Table 1: Options Overview (nearest 3 expirations) ---
    print(f"\n### Options Overview")
    print("| Expiration | Call Vol | Put Vol | Total Vol | Put/Call Ratio |")
    print("| :--- | :--- | :--- | :--- | :--- |")

    all_calls = pd.DataFrame()
    all_puts = pd.DataFrame()

    for exp in expirations[:3]:
        try:
            chain = ticker.option_chain(exp)
            calls = chain.calls
            puts = chain.puts

            call_vol = calls['volume'].sum() if 'volume' in calls.columns else 0
            put_vol = puts['volume'].sum() if 'volume' in puts.columns else 0
            total_vol = call_vol + put_vol
            pc_ratio = put_vol / call_vol if call_vol > 0 else 0

            if pd.isna(call_vol):
                call_vol = 0
            if pd.isna(put_vol):
                put_vol = 0

            print(f"| {exp} | {fmt_number(call_vol)} | {fmt_number(put_vol)} | {fmt_number(total_vol)} | {pc_ratio:.2f} |")

            # Accumulate for analysis
            calls_copy = calls.copy()
            calls_copy['expiration'] = exp
            calls_copy['type'] = 'Call'
            puts_copy = puts.copy()
            puts_copy['expiration'] = exp
            puts_copy['type'] = 'Put'
            all_calls = pd.concat([all_calls, calls_copy], ignore_index=True)
            all_puts = pd.concat([all_puts, puts_copy], ignore_index=True)

        except Exception as e:
            print(f"| {exp} | Error: {e} | — | — | — |")

    if all_calls.empty and all_puts.empty:
        print("\n*No options chain data to analyze.*")
        return

    # --- Table 2: Unusual Activity ---
    print(f"\n### Unusual Activity (Vol/OI > 3x)")
    print("| Strike | Type | Exp | Volume | OI | Vol/OI | IV | Flag |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    combined = pd.concat([all_calls, all_puts], ignore_index=True)

    # Filter for meaningful data
    combined = combined.dropna(subset=['volume', 'openInterest'])
    combined = combined[combined['openInterest'] > 0]
    combined['vol_oi'] = combined['volume'] / combined['openInterest']

    unusual = combined[combined['vol_oi'] > 1.0].sort_values('vol_oi', ascending=False).head(10)

    if unusual.empty:
        print("| — | No unusual activity detected | — | — | — | — | — | — |")
    else:
        for _, row in unusual.iterrows():
            strike = row.get('strike', 0)
            opt_type = row.get('type', '?')
            exp = row.get('expiration', '?')
            vol = row.get('volume', 0)
            oi = row.get('openInterest', 0)
            vol_oi = row.get('vol_oi', 0)
            iv = row.get('impliedVolatility', 0)

            flag = "UNUSUAL" if vol_oi > 3.0 else "Notable" if vol_oi > 2.0 else "—"
            iv_str = f"{iv*100:.1f}%" if pd.notna(iv) else "N/A"

            print(f"| ${strike:.2f} | {opt_type} | {exp} | {fmt_number(vol)} | {fmt_number(oi)} | {vol_oi:.1f}x | {iv_str} | {flag} |")

    # --- Table 3: IV Analysis ---
    print(f"\n### Implied Volatility Analysis")
    print("| Metric | Value |")
    print("| :--- | :--- |")

    try:
        # ATM options: closest strike to current price from nearest expiration
        nearest_calls = all_calls[all_calls['expiration'] == expirations[0]] if not all_calls.empty else pd.DataFrame()
        nearest_puts = all_puts[all_puts['expiration'] == expirations[0]] if not all_puts.empty else pd.DataFrame()

        if not nearest_calls.empty and 'impliedVolatility' in nearest_calls.columns:
            atm_idx = (nearest_calls['strike'] - current_price).abs().idxmin()
            atm_call_iv = nearest_calls.loc[atm_idx, 'impliedVolatility']
            if pd.notna(atm_call_iv):
                print(f"| ATM Call IV | {atm_call_iv*100:.1f}% |")

        if not nearest_puts.empty and 'impliedVolatility' in nearest_puts.columns:
            atm_idx = (nearest_puts['strike'] - current_price).abs().idxmin()
            atm_put_iv = nearest_puts.loc[atm_idx, 'impliedVolatility']
            if pd.notna(atm_put_iv):
                print(f"| ATM Put IV | {atm_put_iv*100:.1f}% |")

        # IV range across all options
        all_iv = combined['impliedVolatility'].dropna()
        if not all_iv.empty:
            print(f"| IV Range | {all_iv.min()*100:.1f}% - {all_iv.max()*100:.1f}% |")
            print(f"| Median IV | {all_iv.median()*100:.1f}% |")
    except Exception as e:
        print(f"| Error | {e} |")

    # --- Table 4: Max Pain ---
    print(f"\n### Max Pain Analysis")
    print("| Metric | Value |")
    print("| :--- | :--- |")

    try:
        # Use nearest expiration for max pain
        nearest_chain = ticker.option_chain(expirations[0])
        mp = calc_max_pain(nearest_chain.calls, nearest_chain.puts, current_price)
        if mp is not None:
            distance = ((mp - current_price) / current_price) * 100
            print(f"| Max Pain ({expirations[0]}) | ${mp:.2f} |")
            print(f"| Current Price | ${current_price:.2f} |")
            print(f"| Distance | {distance:+.1f}% |")

            if abs(distance) < 2:
                print(f"| Implication | Near max pain — likely pin |")
            elif distance > 0:
                print(f"| Implication | Below max pain — upward pressure |")
            else:
                print(f"| Implication | Above max pain — downward pressure |")
        else:
            print("| Max Pain | Could not calculate |")
    except Exception as e:
        print(f"| Error | {e} |")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 options_flow.py <TICKER>")
    else:
        analyze_options(sys.argv[1].upper())
