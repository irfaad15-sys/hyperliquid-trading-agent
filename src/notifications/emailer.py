"""Email alerter for loss events and daily digest.

Immediate alerts fire on: force-close, circuit breaker, unhandled loop errors.
Daily digest fires once per UTC day with minimal account summary.

All calls are fire-and-forget — a failed SMTP connection logs a warning
and never halts the trading loop.

Configuration (add to .env):
    ALERT_EMAIL_FROM      — sender address (e.g. you@gmail.com)
    ALERT_EMAIL_TO        — recipient address (can be the same)
    ALERT_EMAIL_PASSWORD  — Gmail App Password (not your main password)
    ALERT_SMTP_HOST       — optional, default smtp.gmail.com
    ALERT_SMTP_PORT       — optional, default 587
"""

import logging
import smtplib
import os
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


class Emailer:
    def __init__(self):
        self._from = os.getenv("ALERT_EMAIL_FROM", "").strip()
        self._to = os.getenv("ALERT_EMAIL_TO", "").strip()
        self._password = os.getenv("ALERT_EMAIL_PASSWORD", "").strip()
        self._host = os.getenv("ALERT_SMTP_HOST", "smtp.gmail.com").strip()
        self._port = int(os.getenv("ALERT_SMTP_PORT", "587"))
        self._enabled = bool(self._from and self._to and self._password)
        self._last_digest_date = None
        self._daily_trades = 0
        self._daily_risk_events: list[str] = []

        if not self._enabled:
            logging.warning(
                "Email alerter disabled — set ALERT_EMAIL_FROM, ALERT_EMAIL_TO, "
                "ALERT_EMAIL_PASSWORD in .env to enable"
            )

    def _send(self, subject: str, body: str) -> None:
        """Send a plain-text email. Swallows all errors."""
        if not self._enabled:
            return
        try:
            msg = MIMEMultipart()
            msg["From"] = self._from
            msg["To"] = self._to
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))
            with smtplib.SMTP(self._host, self._port, timeout=10) as server:
                server.starttls()
                server.login(self._from, self._password)
                server.sendmail(self._from, self._to, msg.as_string())
            logging.info("Email sent: %s", subject)
        except Exception as exc:
            logging.warning("Email send failed (%s): %s", subject, exc)

    def send_alert(self, subject: str, body: str) -> None:
        """Send an immediate [ALERT] email."""
        self._daily_risk_events.append(subject)
        self._send(f"[ALERT] {subject}", body)

    def record_trade(self) -> None:
        """Increment today's trade counter — call after each executed trade."""
        self._daily_trades += 1

    def maybe_send_digest(self, balance: float, daily_return_pct: float,
                           open_positions: int) -> None:
        """Send the daily digest once per UTC day. No-op if already sent today."""
        today = datetime.now(timezone.utc).date()
        if self._last_digest_date == today:
            return

        sign = "+" if daily_return_pct >= 0 else ""
        risk_summary = (
            "\n".join(f"  - {e}" for e in self._daily_risk_events)
            if self._daily_risk_events else "  none"
        )
        body = (
            f"Date: {today} (UTC)\n"
            f"Balance:        ${balance:,.2f}\n"
            f"Daily return:   {sign}{daily_return_pct:.2f}%\n"
            f"Open positions: {open_positions}\n"
            f"Trades today:   {self._daily_trades}\n"
            f"Risk events:\n{risk_summary}\n"
        )
        self._send(f"[DAILY] Trading Agent — {today}", body)
        self._last_digest_date = today
        self._daily_trades = 0
        self._daily_risk_events = []
