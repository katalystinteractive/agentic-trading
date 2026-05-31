"""Data-source helpers for the V2 daily market snapshot (brief §13).

Reuses existing repo tools rather than re-implementing fetch/ATR/sector/earnings.
The single network seam is ``download_ohlcv`` — tests inject a fake via the
``downloader`` argument so the snapshot stays deterministic.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent


# --- network seam (the only place yfinance is touched) -----------------------
def download_ohlcv(tickers: list[str], *, period: str = "400d", interval: str = "1d"):
    """Batch OHLCV download. Isolated so callers can inject a fake in tests."""
    import yfinance as yf  # local import keeps module import cheap/offline-safe

    return yf.download(
        tickers, period=period, interval=interval, progress=False,
        threads=True, group_by="ticker",
    )


def _frame_for(raw, ticker: str):
    """Extract a single ticker's OHLCV frame from a (possibly multi-index) download."""
    if raw is None:
        return None
    try:
        if hasattr(raw, "columns") and getattr(raw.columns, "nlevels", 1) > 1:
            if ticker in raw.columns.get_level_values(0):
                return raw[ticker].dropna(how="all")
            return None
        return raw.dropna(how="all")  # single-ticker frame
    except Exception:
        return None


def _pct(a: float, b: float) -> float | None:
    if b in (0, None) or a is None:
        return None
    return round((a - b) / b * 100.0, 2)


def compute_price_features(frame) -> dict[str, Any]:
    """Per-ticker price/liquidity/volatility features from an OHLCV frame."""
    from bounce_analyzer import compute_rolling_atr

    if frame is None or len(frame) < 2:
        return {}
    close = frame["Close"]
    high, low, volume = frame["High"], frame["Low"], frame["Volume"]
    price = float(close.iloc[-1])
    feats: dict[str, Any] = {
        "price": round(price, 4),
        "volume": float(volume.iloc[-1]),
        "avg_volume": float(volume.tail(20).mean()),
        "daily_change_pct": _pct(price, float(close.iloc[-2])),
    }
    try:
        atr_series = compute_rolling_atr(frame, period=14)
        atr = atr_series.dropna()
        if len(atr):
            atr_val = float(atr.iloc[-1])
            feats["atr"] = round(atr_val, 4)
            feats["atr_pct"] = round(atr_val / price * 100.0, 2) if price else None
            # 60-day average ATR for the volatility-expansion trigger (§11.1).
            feats["atr_pct_avg_60d"] = round(
                float((atr / close).tail(60).mean()) * 100.0, 2
            ) if len(atr) >= 5 else None
    except Exception:
        pass
    # 20-day high for the breakout trigger (§11.1).
    try:
        feats["high_20d"] = round(float(high.tail(20).max()), 4)
    except Exception:
        pass
    return feats


def fetch_price_features(
    tickers: list[str],
    *,
    downloader: Callable | None = None,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Return ({ticker: features}, provider_failures[]). Network-isolated via downloader."""
    features: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    if not tickers:
        return features, failures
    fn = downloader or download_ohlcv
    try:
        raw = fn(list(tickers))
    except Exception as exc:  # whole-batch failure
        for t in tickers:
            failures.append({"provider": "yfinance", "ticker": t, "field": "ohlcv",
                             "severity": "error", "message": str(exc)})
        return features, failures
    for t in tickers:
        frame = _frame_for(raw, t)
        feats = compute_price_features(frame)
        if not feats:
            failures.append({"provider": "yfinance", "ticker": t, "field": "ohlcv",
                             "severity": "warning", "message": "no price data"})
            continue
        features[t] = feats
    return features, failures


# --- non-network sources (cheap, deterministic) ------------------------------
def get_sector(ticker: str) -> dict[str, str | None]:
    try:
        from sector_registry import get_sector as _fine, get_broad_sector as _broad
        return {"sector": _fine(ticker), "broad_sector": _broad(ticker)}
    except Exception:
        return {"sector": None, "broad_sector": None}


def get_earnings_status(ticker: str, as_of_date: str | None = None) -> dict[str, Any]:
    try:
        from earnings_gate import check_earnings_gate
        res = check_earnings_gate(ticker, as_of_date) or {}
        return {
            "earnings_status": res.get("status"),
            "earnings_blocked": bool(res.get("blocked")),
            "days_to_earnings": res.get("days_to_earnings"),
        }
    except Exception:
        return {"earnings_status": None, "earnings_blocked": False, "days_to_earnings": None}


def age_trading_days(source_date: str | None, as_of_date: str) -> int | None:
    """Trading-day age between a source date and as_of (inclusive of neither end)."""
    if not source_date:
        return None
    try:
        import datetime as _dt
        from trading_calendar import is_trading_day
        start = _dt.date.fromisoformat(str(source_date)[:10])
        end = _dt.date.fromisoformat(str(as_of_date)[:10])
        if start > end:
            return 0
        days = 0
        cur = start
        while cur < end:
            cur += _dt.timedelta(days=1)
            if is_trading_day(cur):
                days += 1
        return days
    except Exception:
        return None


def compute_overlaps(ticker: str) -> dict[str, bool]:
    """Portfolio / candidate / watchlist overlap flags (brief §13)."""
    import json
    out = {"portfolio_overlap": False, "candidate_overlap": False, "watchlist_overlap": False}
    try:
        pf = json.loads((ROOT / "portfolio.json").read_text())
        positions = {str(p.get("ticker", "")).upper() for p in pf.get("positions", [])}
        pending = {str(o.get("ticker", "")).upper() for o in pf.get("pending_orders", [])}
        watch = {str(w).upper() if isinstance(w, str) else str(w.get("ticker", "")).upper()
                 for w in pf.get("watchlist", [])}
        out["portfolio_overlap"] = ticker in positions or ticker in pending
        out["watchlist_overlap"] = ticker in watch
    except Exception:
        pass
    try:
        cands = json.loads((ROOT / "data" / "candidates.json").read_text())
        ctix = {str(c.get("ticker", "")).upper() for c in cands.get("candidates", [])}
        out["candidate_overlap"] = ticker in ctix
    except Exception:
        pass
    return out


def get_market_regime(*, downloader: Callable | None = None) -> str | None:
    """Best-effort market regime for the risk-off gate (brief §13 / §12).

    Returns 'Risk-On' | 'Risk-Off' | 'Neutral', or None when data is unavailable
    (offline/test paths). Network-isolated via the same ``downloader`` seam.
    """
    syms = ["SPY", "QQQ", "IWM", "^VIX"]
    fn = downloader or (lambda t, **kw: download_ohlcv(t, period="80d"))
    try:
        raw = fn(syms)
    except Exception:
        return None
    above = 0
    total = 0
    for sym in ("SPY", "QQQ", "IWM"):
        frame = _frame_for(raw, sym)
        if frame is None or len(frame) < 50:
            continue
        total += 1
        sma50 = float(frame["Close"].tail(50).mean())
        if float(frame["Close"].iloc[-1]) > sma50:
            above += 1
    if total == 0:
        return None
    vix = None
    vframe = _frame_for(raw, "^VIX")
    if vframe is not None and len(vframe):
        vix = float(vframe["Close"].iloc[-1])
    if vix is not None and vix >= 25 and above <= 1:
        return "Risk-Off"
    if above == total and (vix is None or vix < 20):
        return "Risk-On"
    return "Neutral"
