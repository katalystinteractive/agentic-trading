import yfinance as yf
import pandas as pd
import numpy as np
import sys
from datetime import datetime

def sma(series, period):
    return series.rolling(window=period).mean()

def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calc_macd(series, fast=12, slow=26, signal=9):
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def calc_bollinger(series, period=20, std_dev=2):
    middle = sma(series, period)
    std = series.rolling(window=period).std()
    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)
    return upper, middle, lower

def calc_stochastic(high, low, close, k_period=14, d_period=3):
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    k = ((close - lowest_low) / (highest_high - lowest_low)) * 100
    d = k.rolling(window=d_period).mean()
    return k, d

def calc_atr(high, low, close, period=14):
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def find_support_resistance(df, window=10, cluster_pct=0.015):
    """Find support/resistance levels from local min/max."""
    levels = []
    highs = df['High'].values
    lows = df['Low'].values
    closes = df['Close'].values

    # Find local maxima (resistance)
    for i in range(window, len(highs) - window):
        if highs[i] == max(highs[i-window:i+window+1]):
            levels.append(('Resistance', highs[i], df.index[i]))

    # Find local minima (support)
    for i in range(window, len(lows) - window):
        if lows[i] == min(lows[i-window:i+window+1]):
            levels.append(('Support', lows[i], df.index[i]))

    # Cluster nearby levels
    if not levels:
        return []

    levels.sort(key=lambda x: x[1])
    clustered = []
    current_cluster = [levels[0]]

    for i in range(1, len(levels)):
        if abs(levels[i][1] - current_cluster[0][1]) / current_cluster[0][1] < cluster_pct:
            current_cluster.append(levels[i])
        else:
            # Average the cluster
            avg_price = np.mean([l[1] for l in current_cluster])
            role = max(set(l[0] for l in current_cluster), key=lambda x: sum(1 for l in current_cluster if l[0] == x))
            touches = len(current_cluster)
            latest_date = max(l[2] for l in current_cluster)
            clustered.append((role, avg_price, touches, latest_date))
            current_cluster = [levels[i]]

    # Last cluster
    if current_cluster:
        avg_price = np.mean([l[1] for l in current_cluster])
        role = max(set(l[0] for l in current_cluster), key=lambda x: sum(1 for l in current_cluster if l[0] == x))
        touches = len(current_cluster)
        latest_date = max(l[2] for l in current_cluster)
        clustered.append((role, avg_price, touches, latest_date))

    return clustered

def scan_technicals(ticker_symbol):
    try:
        df = yf.download(ticker_symbol, period="1y", interval="1d", progress=False)
        if df.empty:
            print(f"Error: No data for {ticker_symbol}")
            return
    except Exception as e:
        print(f"Error: {e}")
        return

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    close = df['Close']
    high = df['High']
    low = df['Low']
    current_price = close.iloc[-1]

    ticker = yf.Ticker(ticker_symbol)
    company_name = ticker.info.get('shortName', ticker_symbol) if ticker.info else ticker_symbol

    print(f"\n## Technical Scan: {company_name} ({ticker_symbol})")
    print(f"**Current Price: ${current_price:.2f}** | Date: {df.index[-1].strftime('%Y-%m-%d')}")

    # Calculate all indicators
    sma_20 = sma(close, 20).iloc[-1]
    sma_50 = sma(close, 50).iloc[-1]
    sma_200 = sma(close, 200).iloc[-1]
    ema_9 = ema(close, 9).iloc[-1]
    ema_21 = ema(close, 21).iloc[-1]

    rsi_val = calc_rsi(close).iloc[-1]
    macd_line, signal_line, histogram = calc_macd(close)
    macd_val = macd_line.iloc[-1]
    signal_val = signal_line.iloc[-1]
    hist_val = histogram.iloc[-1]

    bb_upper, bb_middle, bb_lower = calc_bollinger(close)
    bb_upper_val = bb_upper.iloc[-1]
    bb_lower_val = bb_lower.iloc[-1]
    bb_middle_val = bb_middle.iloc[-1]

    stoch_k, stoch_d = calc_stochastic(high, low, close)
    stoch_k_val = stoch_k.iloc[-1]
    stoch_d_val = stoch_d.iloc[-1]

    atr_val = calc_atr(high, low, close).iloc[-1]

    # Signal scoring
    score = 0
    reasons = []

    # --- Table 1: Trend Indicators ---
    print(f"\n### Trend Indicators")
    print("| Indicator | Value | Price Position | Signal |")
    print("| :--- | :--- | :--- | :--- |")

    def ma_signal(price, ma_val, name):
        nonlocal score, reasons
        if pd.isna(ma_val):
            return "N/A", "N/A"
        pos = "Above" if price > ma_val else "Below"
        sig = "Bullish" if price > ma_val else "Bearish"
        if sig == "Bullish":
            score += 1
            reasons.append(f"Above {name}")
        else:
            score -= 1
            reasons.append(f"Below {name}")
        return pos, sig

    for name, val in [("SMA 20", sma_20), ("SMA 50", sma_50), ("SMA 200", sma_200),
                       ("EMA 9", ema_9), ("EMA 21", ema_21)]:
        pos, sig = ma_signal(current_price, val, name)
        val_str = f"${val:.2f}" if not pd.isna(val) else "N/A"
        print(f"| {name} | {val_str} | {pos} | {sig} |")

    # Golden/Death Cross
    sma_50_series = sma(close, 50)
    sma_200_series = sma(close, 200)
    if len(sma_50_series.dropna()) > 1 and len(sma_200_series.dropna()) > 1:
        cross_diff = sma_50_series - sma_200_series
        cross_diff = cross_diff.dropna()
        if len(cross_diff) >= 2:
            if cross_diff.iloc[-1] > 0 and cross_diff.iloc[-2] <= 0:
                print(f"| **Golden Cross** | SMA50 > SMA200 | Just crossed | **Bullish** |")
                score += 2
                reasons.append("Golden Cross")
            elif cross_diff.iloc[-1] < 0 and cross_diff.iloc[-2] >= 0:
                print(f"| **Death Cross** | SMA50 < SMA200 | Just crossed | **Bearish** |")
                score -= 2
                reasons.append("Death Cross")

    # --- Table 2: Momentum ---
    print(f"\n### Momentum Indicators")
    print("| Indicator | Value | Zone | Signal |")
    print("| :--- | :--- | :--- | :--- |")

    # RSI
    if not pd.isna(rsi_val):
        if rsi_val > 70:
            rsi_zone, rsi_sig = "Overbought", "Bearish"
            score -= 1
            reasons.append("RSI overbought")
        elif rsi_val < 30:
            rsi_zone, rsi_sig = "Oversold", "Bullish"
            score += 1
            reasons.append("RSI oversold")
        elif rsi_val > 50:
            rsi_zone, rsi_sig = "Bullish zone", "Neutral-Bull"
        else:
            rsi_zone, rsi_sig = "Bearish zone", "Neutral-Bear"
        print(f"| RSI (14) | {rsi_val:.1f} | {rsi_zone} | {rsi_sig} |")

    # MACD
    if not pd.isna(macd_val):
        macd_zone = "Above signal" if macd_val > signal_val else "Below signal"
        macd_sig = "Bullish" if hist_val > 0 else "Bearish"
        if hist_val > 0:
            score += 1
            reasons.append("MACD bullish")
        else:
            score -= 1
            reasons.append("MACD bearish")
        print(f"| MACD | {macd_val:.3f} | {macd_zone} | {macd_sig} |")
        print(f"| MACD Signal | {signal_val:.3f} | Histogram: {hist_val:+.3f} | — |")

    # Stochastic
    if not pd.isna(stoch_k_val):
        if stoch_k_val > 80:
            stoch_zone = "Overbought"
        elif stoch_k_val < 20:
            stoch_zone = "Oversold"
        else:
            stoch_zone = "Neutral"
        stoch_sig = "Bullish" if stoch_k_val > stoch_d_val else "Bearish"
        print(f"| Stochastic %K/%D | {stoch_k_val:.1f}/{stoch_d_val:.1f} | {stoch_zone} | {stoch_sig} |")

    # --- Table 3: Volatility ---
    print(f"\n### Volatility")
    print("| Indicator | Value | Position | Signal |")
    print("| :--- | :--- | :--- | :--- |")

    if not pd.isna(bb_upper_val):
        bb_width = bb_upper_val - bb_lower_val
        if current_price > bb_upper_val:
            bb_pos, bb_sig = "Above upper band", "Overbought"
            score -= 1
        elif current_price < bb_lower_val:
            bb_pos, bb_sig = "Below lower band", "Oversold"
            score += 1
        else:
            pct_b = (current_price - bb_lower_val) / bb_width * 100 if bb_width > 0 else 50
            bb_pos = f"{pct_b:.0f}% of band"
            bb_sig = "Neutral"
        print(f"| Bollinger Upper | ${bb_upper_val:.2f} | {bb_pos} | {bb_sig} |")
        print(f"| Bollinger Lower | ${bb_lower_val:.2f} | Width: ${bb_width:.2f} | — |")

    if not pd.isna(atr_val):
        atr_pct = (atr_val / current_price) * 100
        vol_label = "High" if atr_pct > 3 else "Normal" if atr_pct > 1.5 else "Low"
        print(f"| ATR (14) | ${atr_val:.2f} ({atr_pct:.1f}%) | {vol_label} volatility | — |")

    # --- Table 4: Key Levels ---
    print(f"\n### Key Support/Resistance Levels")
    print("| Level | Price | Type | Touches | Last Tested |")
    print("| :--- | :--- | :--- | :--- | :--- |")

    levels = find_support_resistance(df)
    if levels:
        # Sort by distance from current price
        levels.sort(key=lambda x: abs(x[1] - current_price))
        for i, (role, price, touches, last_date) in enumerate(levels[:8]):
            dist_pct = ((price - current_price) / current_price) * 100
            date_str = last_date.strftime('%Y-%m-%d') if hasattr(last_date, 'strftime') else str(last_date)
            print(f"| {role} | ${price:.2f} ({dist_pct:+.1f}%) | {role} | {touches} | {date_str} |")
    else:
        print("| — | No clear levels detected | — | — | — |")

    # --- Table 5: Signal Summary ---
    print(f"\n### Signal Summary")
    print("| Metric | Value |")
    print("| :--- | :--- |")

    if score >= 4:
        overall = "Strong Bullish"
    elif score >= 2:
        overall = "Bullish"
    elif score >= 0:
        overall = "Neutral-Bullish"
    elif score >= -2:
        overall = "Neutral-Bearish"
    elif score >= -4:
        overall = "Bearish"
    else:
        overall = "Strong Bearish"

    print(f"| Overall Signal | **{overall}** |")
    print(f"| Score | {score:+d} |")

    bull_reasons = [r for r in reasons if any(w in r.lower() for w in ['above', 'bullish', 'oversold', 'golden'])]
    bear_reasons = [r for r in reasons if any(w in r.lower() for w in ['below', 'bearish', 'overbought', 'death'])]
    if bull_reasons:
        print(f"| Bullish Factors | {', '.join(bull_reasons)} |")
    if bear_reasons:
        print(f"| Bearish Factors | {', '.join(bear_reasons)} |")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 technical_scanner.py <TICKER>")
    else:
        scan_technicals(sys.argv[1].upper())
