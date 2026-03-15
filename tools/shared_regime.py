"""Shared regime fetcher — fetches market regime (Risk-On/Neutral/Risk-Off).

Single implementation used by fill_probability.py and deployment_advisor.py
to avoid duplicating the regime classification logic across tools.
"""

import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from market_context_pre_analyst import classify_regime
except ImportError as e:
    print(f"*Warning: classify_regime import failed ({e}), using Neutral regime*")
    def classify_regime(indices, vix):
        return {"regime": "Neutral", "indices_above": 0, "indices_total": 0,
                "vix_value": None, "reasoning": "Import fallback"}


def fetch_regime():
    """Fetch market regime using classify_regime. Returns regime string."""
    try:
        indices = []
        for sym in ["SPY", "QQQ", "IWM"]:
            try:
                df = yf.download(sym, period="6mo", auto_adjust=True, progress=False)
                close = df["Close"]
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                sma50 = close.rolling(50).mean().iloc[-1]
                current = close.iloc[-1]
                vs_50sma = "Above 50-SMA" if current >= sma50 else "Below 50-SMA"
                indices.append({"vs_50sma": vs_50sma})
            except Exception:
                print(f"*Warning: Failed to fetch {sym} for regime, skipping*")
        vix_df = yf.download("^VIX", period="5d", auto_adjust=True, progress=False)
        vix_close = vix_df["Close"]
        if isinstance(vix_close, pd.DataFrame):
            vix_close = vix_close.iloc[:, 0]
        vix_val = float(vix_close.iloc[-1])
        result = classify_regime(indices, {"value": vix_val})
        return result["regime"]
    except Exception as e:
        print(f"*Warning: Regime fetch failed ({e}), using Neutral*")
        return "Neutral"
