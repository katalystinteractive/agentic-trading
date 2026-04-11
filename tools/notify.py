"""Email notification for neural dip evaluator alerts.

Usage:
    from notify import send_dip_alert
    send_dip_alert("CLSK", 8.81, 9.16, 8.55, "reason chain", "Neutral", 100)

Test:
    python3 tools/notify.py
"""
import os
from datetime import datetime

# Fix SSL certificate verification on macOS
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except ImportError:
    pass


def send_dip_alert(ticker, entry_price, target, stop, reason_chain,
                   regime, budget, shares=0):
    """Send email when BUY_DIP neuron fires. Returns True on success."""
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
    except ImportError:
        print("*Warning: sendgrid not installed. pip install sendgrid*")
        return False

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass  # dotenv optional if env vars set externally

    api_key = os.environ.get("SENDGRID_API_KEY")
    recipient = os.environ.get("ALERT_EMAIL")
    sender = os.environ.get("SENDGRID_FROM_EMAIL")

    if not all([api_key, recipient, sender]):
        missing = [v for v, val in [("SENDGRID_API_KEY", api_key),
                   ("ALERT_EMAIL", recipient), ("SENDGRID_FROM_EMAIL", sender)]
                   if not val]
        print(f"*Warning: missing env vars: {missing}. Skipping email.*")
        return False

    subject = f"DIP ALERT: BUY {shares} {ticker} at ${entry_price:.2f}" if shares else f"DIP ALERT: BUY {ticker} at ${entry_price:.2f}"
    _sizing = (f"Shares: {shares}\n"
               f"Cost:   ${shares * entry_price:.2f}\n") if shares else ""
    body = (f"Ticker: {ticker}\n"
            f"Entry:  ${entry_price:.2f}\n"
            f"{_sizing}"
            f"Target: ${target:.2f} (+{(target - entry_price) / entry_price * 100:.1f}%)\n"
            f"Stop:   ${stop:.2f} ({(stop - entry_price) / entry_price * 100:.1f}%)\n"
            f"Budget: ${budget:.0f}\n"
            f"Regime: {regime}\n\n"
            f"REASON CHAIN:\n{reason_chain}\n\n"
            f"-- Neural Dip Evaluator at "
            f"{datetime.now().strftime('%H:%M:%S ET %Y-%m-%d')}")

    message = Mail(from_email=sender, to_emails=recipient,
                   subject=subject, plain_text_content=body)
    try:
        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        if response.status_code not in (200, 202):
            print(f"*Warning: SendGrid returned {response.status_code}*")
            return False
        print(f"Email sent to {recipient}: {subject}")
        return True
    except Exception as e:
        print(f"*Warning: email send failed: {e}*")
        return False


def send_support_alert(opportunities):
    """Send email listing support buy opportunities from neural evaluator."""
    if not opportunities:
        return False
    lines = [f"{len(opportunities)} tickers near support levels:\n"]
    for opp in opportunities:
        lines.append(f"{opp['ticker']}: ${opp['price']:.2f}, "
                     f"support at ${opp['support']:.2f} "
                     f"({opp['distance_pct']}% away)")
        lines.append(f"  Neural: sell at +{opp['sell_target_pct']}%, "
                     f"${opp['pool']} pool, {opp['shares']} shares")
        lines.append(f"  Action: Place limit buy at ${opp['support']:.2f}\n")
    body = "\n".join(lines)
    body += (f"\n-- Neural Support Evaluator at "
             f"{datetime.now().strftime('%H:%M:%S %Y-%m-%d')}")
    return send_summary_email(
        f"Morning Support Scan — {datetime.now().strftime('%Y-%m-%d')}", body)


def send_summary_email(subject, body):
    """Send a plain-text summary email via SendGrid.

    Generic version of send_dip_alert() for pipeline notifications.
    Returns True on success.
    """
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
    except ImportError:
        print("*Warning: sendgrid not installed. pip install sendgrid*")
        return False

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    api_key = os.environ.get("SENDGRID_API_KEY")
    recipient = os.environ.get("ALERT_EMAIL")
    sender = os.environ.get("SENDGRID_FROM_EMAIL")

    if not all([api_key, recipient, sender]):
        missing = [v for v, val in [("SENDGRID_API_KEY", api_key),
                   ("ALERT_EMAIL", recipient), ("SENDGRID_FROM_EMAIL", sender)]
                   if not val]
        print(f"*Warning: missing env vars: {missing}. Skipping email.*")
        return False

    message = Mail(from_email=sender, to_emails=recipient,
                   subject=subject, plain_text_content=body)
    try:
        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        if response.status_code not in (200, 202):
            print(f"*Warning: SendGrid returned {response.status_code}*")
            return False
        print(f"Email sent to {recipient}: {subject}")
        return True
    except Exception as e:
        print(f"*Warning: email send failed: {e}*")
        return False


def send_fill_cascade_alert(auto_fills):
    """Send consolidated email for auto-detected fills with cascade info.

    auto_fills: list of dicts with ticker, price, shares, success, summary, next_bullet
    """
    if not auto_fills:
        return False

    successful = [f for f in auto_fills if f["success"]]
    failed = [f for f in auto_fills if not f["success"]]

    lines = []
    for f in successful:
        lines.append(f"FILL RECORDED: {f['ticker']} BUY {f['shares']} @ ${f['price']:.2f}")
        lines.append("")
        if f.get("summary"):
            lines.append(f["summary"].strip())
            lines.append("")
        nb = f.get("next_bullet")
        if nb:
            lines.append(f"Next Bullet: {nb['level']} @ ${nb['price']:.2f} ({nb['shares']} shares)")
            lines.append(f"Action: Place limit BUY {nb['shares']} {f['ticker']} @ ${nb['price']:.2f}")
            lines.append("")
        lines.append("---")
        lines.append("")

    for f in failed:
        lines.append(f"FILL FAILED: {f.get('summary', 'unknown error')}")
        lines.append("")

    body = "\n".join(lines)

    if len(successful) == 1:
        f = successful[0]
        subject = f"FILL: {f['ticker']} BUY {f['shares']} @ ${f['price']:.2f}"
    elif successful:
        tickers = ", ".join(f["ticker"] for f in successful)
        subject = f"FILLS: {tickers}"
    else:
        subject = "FILL ERRORS"

    return send_summary_email(subject, body)


if __name__ == "__main__":
    print("Testing SendGrid notification...")
    success = send_dip_alert(
        "TEST", 10.00, 10.40, 9.70,
        "This is a test firing chain:\n"
        "MARKET_OPEN → TIME_WINDOW_2 → BREADTH_DIP → SIGNAL_CONFIRMED → TEST:BUY_DIP",
        "Neutral", 100)
    print(f"Result: {'SUCCESS' if success else 'FAILED'}")
