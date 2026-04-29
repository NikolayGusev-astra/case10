"""
notifier.py — Multi-channel notification dispatcher.

Supports Telegram, Mattermost, and Email (SMTP) out of the box.
Extend by adding new ``send_*`` functions and registering them in ``NOTIFIERS``.

Usage:
  from tools.notifier import notify_all
  notify_all("Task #42 assigned to you", channels=["telegram", "email"],
             telegram_chat_id="123", email_to="user@example.com")
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

try:
    import requests as req
except ImportError:
    req = None  # type: ignore[assignment]


def send_telegram(message: str, chat_id: str | None = None) -> bool:
    """Send a plain-text message via a Telegram bot.

    Credentials:
        ``TELEGRAM_BOT_TOKEN`` — bot token from @BotFather
        ``TELEGRAM_CHAT_ID``   — default chat/group ID (overridable via arg)
    """
    if req is None:
        logger.error("requests library not installed — cannot send Telegram")
        return False

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    cid = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not cid:
        logger.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = req.post(url, json={"chat_id": cid, "text": message, "parse_mode": "HTML"})
    if not resp.ok:
        logger.error("Telegram send failed: %s %s", resp.status_code, resp.text)
        return False

    logger.info("Telegram message sent to chat %s", cid)
    return True


# ---------------------------------------------------------------------------
# Mattermost
# ---------------------------------------------------------------------------

def send_mattermost(message: str, channel: str | None = None) -> bool:
    """Send a message via a Mattermost incoming webhook.

    Credentials:
        ``MATTERMOST_WEBHOOK_URL`` — full incoming webhook URL
    """
    if req is None:
        logger.error("requests library not installed — cannot send Mattermost")
        return False

    webhook = os.environ.get("MATTERMOST_WEBHOOK_URL")
    if not webhook:
        logger.warning("MATTERMOST_WEBHOOK_URL not set")
        return False

    payload: dict[str, Any] = {"text": message}
    if channel:
        payload["channel"] = channel

    resp = req.post(webhook, json=payload)
    if not resp.ok:
        logger.error("Mattermost send failed: %s %s", resp.status_code, resp.text)
        return False

    logger.info("Mattermost message sent%s", f" to channel {channel}" if channel else "")
    return True


# ---------------------------------------------------------------------------
# Email (SMTP)
# ---------------------------------------------------------------------------

def send_email(subject: str, body: str, to: str | list[str]) -> bool:
    """Send an HTML email via SMTP.

    Credentials (env vars):
        ``SMTP_HOST``, ``SMTP_PORT`` (default 587), ``SMTP_USER``, ``SMTP_PASSWORD``,
        ``SMTP_FROM`` — from-address (defaults to SMTP_USER).
    """
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    from_addr = os.environ.get("SMTP_FROM", user)

    if not all([host, user, password]):
        logger.warning("SMTP credentials not fully configured")
        return False

    recipients = [to] if isinstance(to, str) else to

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(body, "html", "utf-8"))

    try:
        with smtplib.SMTP(host, port) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(from_addr, recipients, msg.as_string())
    except Exception as exc:
        logger.error("Email send failed: %s", exc)
        return False

    logger.info("Email '%s' sent to %s", subject, recipients)
    return True


# ---------------------------------------------------------------------------
# Registry / dispatcher
# ---------------------------------------------------------------------------

NOTIFIERS: dict[str, Any] = {
    "telegram": send_telegram,
    "mattermost": send_mattermost,
    "email": send_email,
}


def notify_all(message: str, channels: list[str] | None = None, **kwargs: Any) -> dict[str, bool]:
    """Send *message* on every requested *channel*.

    Args:
        message: The notification text.
        channels: List of channel names (e.g. ``["telegram", "email"]``).
                  Defaults to all registered channels.
        **kwargs: Per-channel arguments forwarded to the handler
                  (e.g. ``chat_id=..., to=...``).

    Returns:
        Dict mapping channel name -> success bool.
    """
    if channels is None:
        channels = list(NOTIFIERS.keys())

    results: dict[str, bool] = {}
    for ch in channels:
        handler = NOTIFIERS.get(ch)
        if handler is None:
            logger.warning("Unknown notification channel: %s", ch)
            results[ch] = False
            continue

        # Forward only the kwargs the handler accepts
        import inspect
        sig = inspect.signature(handler)
        filtered = {k: v for k, v in kwargs.items() if k in sig.parameters}
        try:
            ok = handler(message, **filtered)
        except Exception as exc:
            logger.error("Notifier %s raised: %s", ch, exc)
            ok = False
        results[ch] = ok

    return results
