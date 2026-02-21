# Ticker Data Access

Structured interface for querying stock ticker data from the agentic-trading project. Use this skill when you need to access ticker identity, wick-adjusted buy levels, trade history, or portfolio state.

## Quick Reference

| Action | Command |
| :--- | :--- |
| Full ticker summary | `python3 tools/ticker_query.py CLSK` |
| Identity only | `python3 tools/ticker_query.py CLSK --section identity` |
| Wick-adjusted levels | `python3 tools/ticker_query.py CLSK --section levels` |
| Trade log | `python3 tools/ticker_query.py CLSK --section memory` |
| All tickers' levels | `python3 tools/ticker_query.py --all --section levels` |
| Portfolio summary | `python3 tools/ticker_query.py --portfolio-summary` |

## Data Sources

The tool reads from these locations:

| Source | Path | Contents |
| :--- | :--- | :--- |
| Identity | `tickers/<TICKER>/identity.md` | Persona, strategy cycle, key levels, wick-adjusted buy table, bullet plan, status |
| Memory | `tickers/<TICKER>/memory.md` | Narrative trade log, observations, lessons |
| Wick cache | `tickers/<TICKER>/wick_analysis.md` | Auto-generated per-level buy recommendations (fallback if not in identity) |
| Portfolio | `portfolio.json` | Positions, pending orders, watchlist, capital allocation |

## Data Architecture

- **`portfolio.json`** is the single source of truth for transactional state (shares, avg cost, pending orders, capital).
- **`tickers/<TICKER>/`** holds structural data (persona, support levels, trade narrative).
- These two systems are intentionally separate: portfolio.json is machine-readable state, ticker files are structural context.

## Output Format

All output uses markdown tables with `| :--- |` alignment, following project conventions. Errors are wrapped in `*italics*`.

## When NOT to Use This Tool

- For live prices, use `python3 tools/get_prices.py <TICKER>` instead.
- For technical analysis, use `python3 tools/technical_scanner.py <TICKER>`.
- For full portfolio status with live prices, use `python3 tools/portfolio_status.py`.
- This tool reads cached/structural data only. It does not fetch live market data.
