import yfinance as yf
import sys
import datetime

def get_prices(tickers):
    print(f"| Date | Ticker | Price | Day Low | Day High | Status |")
    print(f"| :--- | :--- | :--- | :--- | :--- | :--- |")
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            data = t.history(period="1d")
            if not data.empty:
                # Get the date of the last candle
                last_date = data.index[-1].strftime('%Y-%m-%d')
                price = data['Close'].iloc[-1]
                high = data['High'].iloc[-1]
                low = data['Low'].iloc[-1]
                
                # Check if market is open (basic check)
                today = datetime.datetime.now().strftime('%Y-%m-%d')
                status = "OPEN" if last_date == today else "CLOSED"
                
                print(f"| {last_date} | {ticker} | ${price:.2f} | ${low:.2f} | ${high:.2f} | {status} |")
            else:
                print(f"| N/A | {ticker} | N/A | N/A | N/A | N/A |")
        except Exception as e:
            print(f"| Error | {ticker} | - | - | - | - |")

if __name__ == "__main__":
    get_prices(sys.argv[1:])
