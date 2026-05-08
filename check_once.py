"""
Single-shot booking check — used by GitHub Actions.
Checks the helicopter link once and sends notifications if bookings are open.
Exits immediately after.
"""

import os
import re
import sys
import logging
import requests

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("check_once")

TARGET_URL = "https://jksasb.nic.in/onlineservices/"
INACTIVE_PATTERNS = {"#", "", "javascript:void(0)", "javascript:void(0);", "javascript:;"}


def check_helicopter_link() -> str | None:
    """Fetch page and check if helicopter link is active. Returns URL or None."""
    try:
        resp = requests.get(TARGET_URL, timeout=30, headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            )
        })
        resp.raise_for_status()
        html = resp.text

        pattern = re.compile(
            r'<a\b[^>]*\bhref\s*=\s*["\']([^"\']*)["\'][^>]*>([^<]*Helicopter[^<]*Ticket[^<]*Booking[^<]*)',
            re.IGNORECASE | re.DOTALL,
        )
        match = pattern.search(html)

        if match:
            href = match.group(1).strip()
            logger.info("Found helicopter link: href='%s'", href)
            if href.lower() in INACTIVE_PATTERNS:
                logger.info("Link is still inactive.")
                return None
            else:
                logger.info("ACTIVE link detected: %s", href)
                return href

        # Broader search
        broad = re.compile(r'href\s*=\s*["\']([^"\']+)["\'][^>]*>[^<]*?Helicopter', re.IGNORECASE)
        broad_match = broad.search(html)
        if broad_match:
            href = broad_match.group(1).strip()
            if href.lower() not in INACTIVE_PATTERNS:
                logger.info("Broad match active link: %s", href)
                return href

        logger.info("Helicopter link not found or not in <a> tag.")
        return None

    except requests.RequestException as e:
        logger.error("HTTP request failed: %s", e)
        return None


def send_telegram(message: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.warning("Telegram not configured")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=15,
        )
        ok = resp.status_code == 200 and resp.json().get("ok")
        logger.info("Telegram: %s", "OK" if ok else f"FAIL ({resp.text})")
        return ok
    except Exception as e:
        logger.error("Telegram failed: %s", e)
        return False


def send_sms(message: str) -> bool:
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_num = os.getenv("TWILIO_PHONE_NUMBER")
    to_num = os.getenv("USER_PHONE_NUMBER")
    if not all([sid, token, from_num, to_num]):
        logger.warning("Twilio SMS not configured")
        return False
    try:
        from twilio.rest import Client
        msg = Client(sid, token).messages.create(body=message, from_=from_num, to=to_num)
        logger.info("SMS sent: %s", msg.sid)
        return True
    except Exception as e:
        logger.error("SMS failed: %s", e)
        return False


def make_call(spoken: str) -> bool:
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_num = os.getenv("TWILIO_PHONE_NUMBER")
    to_num = os.getenv("USER_PHONE_NUMBER")
    if not all([sid, token, from_num, to_num]):
        logger.warning("Twilio Voice not configured")
        return False
    try:
        from twilio.rest import Client
        twiml = (
            f'<Response><Say voice="alice" language="en-IN">{spoken}</Say>'
            f'<Pause length="2"/><Say voice="alice" language="en-IN">{spoken}</Say></Response>'
        )
        call = Client(sid, token).calls.create(twiml=twiml, from_=from_num, to=to_num)
        logger.info("Call initiated: %s", call.sid)
        return True
    except Exception as e:
        logger.error("Call failed: %s", e)
        return False


def main():
    logger.info("=== Single check started ===")
    redirect_url = check_helicopter_link()

    if redirect_url is None:
        logger.info("No booking detected. Done.")
        sys.exit(0)

    # Bookings detected!
    logger.info("*** BOOKING DETECTED: %s ***", redirect_url)

    send_telegram(
        f"<b>ALERT: Helicopter Bookings OPEN!</b>\n\n"
        f"URL: {redirect_url}\n\n"
        f"Book your tickets NOW!"
    )
    send_sms(
        f"ALERT: Amarnath Helicopter Bookings NOW OPEN!\n"
        f"URL: {redirect_url}\nBook immediately!"
    )
    make_call(
        "Alert! Amarnath helicopter ticket bookings are now open. "
        "Please open the website and book your tickets immediately."
    )

    logger.info("=== Notifications sent. Done. ===")


if __name__ == "__main__":
    main()
