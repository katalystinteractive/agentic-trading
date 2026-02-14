import json
import datetime
from pathlib import Path
import yfinance as yf

_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = _ROOT / "portfolio.json"
OUTPUT_PATH = _ROOT / "portfolio_status.md"


def load_portfolio():
    with open(PORTFOLIO_PATH, "r") as f:
        return json.load(f)


def fetch_prices(tickers):
    """Fetch current prices for a list of tickers. Returns dict {TICKER: {price, day_pct, stale}}."""
    prices = {}
    today = datetime.date.today()
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            data = t.history(period="5d")
            if not data.empty:
                current = data["Close"].iloc[-1]
                prev = data["Close"].iloc[-2] if len(data) > 1 else current
                day_pct = ((current - prev) / prev) * 100
                last_date = data.index[-1].date()
                stale = (today - last_date).days > 1
                prices[ticker] = {"price": current, "day_pct": day_pct, "stale": stale}
            else:
                prices[ticker] = {"price": None, "day_pct": None, "stale": True}
        except Exception:
            prices[ticker] = {"price": None, "day_pct": None, "stale": True}
    return prices


def fmt_dollar(val):
    if val is None:
        return "N/A"
    return f"${val:.2f}"


def fmt_pct(val):
    if val is None:
        return "N/A"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.1f}%"


def fmt_distance(current, target):
    if current is None or target is None:
        return "N/A"
    pct = ((target - current) / current) * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def build_report(portfolio, prices):
    lines = []
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    any_stale = any(p.get("stale") for p in prices.values())
    lines.append(f"# Portfolio Status — {now}")
    if any_stale:
        lines.append("*Note: Market closed — prices may be from last trading day.*")
    lines.append("")

    # --- Active Positions ---
    lines.append("## Active Positions")
    if portfolio["positions"]:
        lines.append("| Ticker | Shares | Avg Cost | Current | P/L $ | P/L % | Target | Dist to Target |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for ticker, pos in portfolio["positions"].items():
            p = prices.get(ticker, {})
            current = p.get("price")
            avg = pos["avg_cost"]
            shares = pos["shares"]
            target = pos.get("target_exit")
            if current is not None:
                pl_dollar = (current - avg) * shares
                pl_pct = ((current - avg) / avg) * 100
            else:
                pl_dollar = None
                pl_pct = None
            lines.append(
                f"| {ticker} | {shares} | {fmt_dollar(avg)} | {fmt_dollar(current)} "
                f"| {fmt_dollar(pl_dollar)} | {fmt_pct(pl_pct)} "
                f"| {fmt_dollar(target)} | {fmt_distance(current, target)} |"
            )
    else:
        lines.append("*(no active positions)*")
    lines.append("")

    # --- Pending Orders ---
    lines.append("## Pending Orders")
    all_orders = portfolio.get("pending_orders", {})
    has_orders = any(len(v) > 0 for v in all_orders.values())
    if has_orders:
        lines.append("| Ticker | Type | Price | Current | Distance | Note |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for ticker, orders in all_orders.items():
            p = prices.get(ticker, {})
            current = p.get("price")
            for order in orders:
                dist = fmt_distance(current, order["price"])
                lines.append(
                    f"| {ticker} | {order['type']} | {fmt_dollar(order['price'])} "
                    f"| {fmt_dollar(current)} | {dist} | {order.get('note', '')} |"
                )
    else:
        lines.append("*(no pending orders)*")
    lines.append("")

    # --- Watchlist ---
    lines.append("## Watchlist")
    watchlist = portfolio.get("watchlist", [])
    if watchlist:
        lines.append("| Ticker | Price | Day % |")
        lines.append("| :--- | :--- | :--- |")
        for ticker in watchlist:
            p = prices.get(ticker, {})
            lines.append(
                f"| {ticker} | {fmt_dollar(p.get('price'))} | {fmt_pct(p.get('day_pct'))} |"
            )
    else:
        lines.append("*(empty watchlist)*")
    lines.append("")

    # --- Capital Summary ---
    cap = portfolio.get("capital", {})
    positions = portfolio.get("positions", {})
    deployed = sum(
        pos["shares"] * pos["avg_cost"] for pos in positions.values()
    )
    lines.append("## Capital Summary")
    lines.append(f"| Metric | Value |")
    lines.append(f"| :--- | :--- |")
    lines.append(f"| Deployed | {fmt_dollar(deployed)} |")
    lines.append(f"| Per-Stock Budget | {fmt_dollar(cap.get('per_stock_total'))} |")
    lines.append(f"| Bullet Size | {fmt_dollar(cap.get('bullet_size'))} |")
    lines.append("")

    return "\n".join(lines)


def main():
    portfolio = load_portfolio()

    # Collect all tickers that need prices
    tickers = set()
    tickers.update(portfolio.get("positions", {}).keys())
    tickers.update(portfolio.get("pending_orders", {}).keys())
    tickers.update(portfolio.get("watchlist", []))

    prices = fetch_prices(sorted(tickers))
    report = build_report(portfolio, prices)

    # Write to file
    with open(OUTPUT_PATH, "w") as f:
        f.write(report + "\n")

    # Print to stdout
    print(report)


if __name__ == "__main__":
    main()
