"""
Single-shot booking check — used by GitHub Actions.
Checks the helicopter link once and sends notifications if bookings are open.
Exits immediately after.
"""

import os
import re
import sys
import time
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


def make_call(spoken: str) -> str | None:
    """Make a voice call. Returns call SID if initiated, None on failure."""
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_num = os.getenv("TWILIO_PHONE_NUMBER")
    to_num = os.getenv("USER_PHONE_NUMBER")
    if not all([sid, token, from_num, to_num]):
        logger.warning("Twilio Voice not configured")
        return None
    try:
        from twilio.rest import Client
        twiml = (
            f'<Response><Say voice="alice" language="en-IN">{spoken}</Say>'
            f'<Pause length="2"/><Say voice="alice" language="en-IN">{spoken}</Say></Response>'
        )
        call = Client(sid, token).calls.create(twiml=twiml, from_=from_num, to=to_num)
        logger.info("Call initiated: %s", call.sid)
        return call.sid
    except Exception as e:
        logger.error("Call failed: %s", e)
        return None


def was_call_answered(call_sid: str) -> bool:
    """Poll Twilio call status. Returns True if user answered."""
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    if not all([sid, token]):
        return False
    try:
        from twilio.rest import Client
        client = Client(sid, token)
        for _ in range(12):  # Poll every 5s for up to 60s
            call = client.calls(call_sid).fetch()
            logger.info("Call status: %s", call.status)
            if call.status == "completed":
                logger.info("User ANSWERED the call!")
                return True
            if call.status in ("no-answer", "busy", "failed", "canceled"):
                logger.info("User did NOT answer (status: %s)", call.status)
                return False
            time.sleep(5)
        logger.warning("Call status check timed out")
        return False
    except Exception as e:
        logger.error("Call status check failed: %s", e)
        return False


def main():
    logger.info("=== Single check started ===")
    redirect_url = check_helicopter_link()

    if redirect_url is None:
        logger.info("No booking detected. Done.")
        sys.exit(0)

    # Bookings detected!
    logger.info("*** BOOKING DETECTED: %s ***", redirect_url)

    max_attempts = 2
    gap_seconds = 60

    tg_text = (
        f"<b>ALERT: Helicopter Bookings OPEN!</b>\n\n"
        f"URL: {redirect_url}\n\n"
        f"Book your tickets NOW!"
    )
    sms_text = (
        f"ALERT: Amarnath Helicopter Bookings NOW OPEN!\n"
        f"URL: {redirect_url}\nBook immediately!"
    )
    call_text = (
        "Alert! Amarnath helicopter ticket bookings are now open. "
        "Please open the website and book your tickets immediately."
    )

    for attempt in range(1, max_attempts + 1):
        logger.info("=== Notification attempt %d of %d ===", attempt, max_attempts)

        # Step 1: Telegram
        logger.info("Step 1: Sending Telegram...")
        send_telegram(tg_text)

        # Wait 1 minute
        logger.info("Waiting %d seconds before SMS...", gap_seconds)
        time.sleep(gap_seconds)

        # Step 2: SMS
        logger.info("Step 2: Sending SMS...")
        send_sms(sms_text)

        # Wait 1 minute
        logger.info("Waiting %d seconds before call...", gap_seconds)
        time.sleep(gap_seconds)

        # Step 3: Voice call + check if answered
        logger.info("Step 3: Making voice call...")
        call_sid = make_call(call_text)

        if call_sid:
            if was_call_answered(call_sid):
                logger.info("User answered — STOPPING notifications.")
                break
            logger.info("User did not answer.")

        if attempt < max_attempts:
            logger.info("Retrying full sequence...")

    logger.info("=== Notification sequence complete. ===")

    logger.info("=== Notifications sent. Done. ===")


if __name__ == "__main__":
    main()
