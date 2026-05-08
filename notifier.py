import os
import time
import logging
import requests
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("notifier")

# --- Twilio Config ---
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM = os.getenv("TWILIO_PHONE_NUMBER")
USER_PHONE = os.getenv("USER_PHONE_NUMBER")

# --- Telegram Config ---
TG_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- Retry Config ---
MAX_RETRIES = int(os.getenv("MAX_NOTIFICATION_RETRIES", "3"))
RETRY_DELAY = int(os.getenv("NOTIFICATION_RETRY_DELAY", "30"))


def send_telegram(message: str) -> bool:
    """Send a Telegram message. Returns True on success."""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        logger.warning("Telegram not configured — skipping")
        return False
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": TG_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
        }, timeout=15)
        if resp.status_code == 200 and resp.json().get("ok"):
            logger.info("Telegram message sent successfully")
            return True
        logger.error("Telegram API error: %s", resp.text)
        return False
    except Exception as e:
        logger.error("Telegram send failed: %s", e)
        return False


def send_sms(message: str) -> bool:
    """Send an SMS via Twilio. Returns True on success."""
    if not all([TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM, USER_PHONE]):
        logger.warning("Twilio SMS not configured — skipping")
        return False
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        msg = client.messages.create(
            body=message,
            from_=TWILIO_FROM,
            to=USER_PHONE,
        )
        logger.info("SMS sent — SID: %s", msg.sid)
        return True
    except Exception as e:
        logger.error("SMS send failed: %s", e)
        return False


def make_call(spoken_message: str) -> bool:
    """Make a voice call via Twilio with TwiML <Say>. Returns True on success."""
    if not all([TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM, USER_PHONE]):
        logger.warning("Twilio Voice not configured — skipping")
        return False
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        # TwiML to speak the message twice for clarity
        twiml = (
            '<Response>'
            f'<Say voice="alice" language="en-IN">{spoken_message}</Say>'
            '<Pause length="2"/>'
            f'<Say voice="alice" language="en-IN">{spoken_message}</Say>'
            '</Response>'
        )
        call = client.calls.create(
            twiml=twiml,
            from_=TWILIO_FROM,
            to=USER_PHONE,
        )
        logger.info("Voice call initiated — SID: %s", call.sid)
        return True
    except Exception as e:
        logger.error("Voice call failed: %s", e)
        return False


def notify_all(redirect_url: str) -> None:
    """
    Send notifications via all channels with retry logic.
    Fires Telegram (fastest) first, then SMS, then voice call.
    Repeats the full cycle up to MAX_RETRIES times.
    """
    sms_text = (
        f"ALERT: Amarnath Helicopter Bookings are NOW OPEN!\n"
        f"URL: {redirect_url}\n"
        f"Book immediately!"
    )
    tg_text = (
        f"<b>ALERT: Helicopter Bookings OPEN!</b>\n\n"
        f"Amarnath Helicopter Ticket Booking page is now redirecting.\n"
        f"<b>URL:</b> {redirect_url}\n\n"
        f"Book your tickets immediately!"
    )
    call_text = (
        "Alert! Amarnath helicopter ticket bookings are now open. "
        "Please open the website and book your tickets immediately."
    )

    for attempt in range(1, MAX_RETRIES + 1):
        logger.info("=== Notification attempt %d of %d ===", attempt, MAX_RETRIES)

        tg_ok = send_telegram(tg_text)
        sms_ok = send_sms(sms_text)
        call_ok = make_call(call_text)

        logger.info(
            "Attempt %d results — Telegram: %s | SMS: %s | Call: %s",
            attempt,
            "OK" if tg_ok else "FAIL",
            "OK" if sms_ok else "FAIL",
            "OK" if call_ok else "FAIL",
        )

        if attempt < MAX_RETRIES:
            logger.info("Waiting %d seconds before next attempt...", RETRY_DELAY)
            time.sleep(RETRY_DELAY)

    logger.info("All %d notification attempts completed.", MAX_RETRIES)


if __name__ == "__main__":
    # Quick test — run this file directly to test notifications
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    print("--- Testing Notifications ---")
    print("Sending test Telegram message...")
    send_telegram("Test: Helicopter Monitor is working!")
    print("Sending test SMS...")
    send_sms("Test: Helicopter Monitor is working!")
    print("Making test voice call...")
    make_call("This is a test call from the helicopter booking monitor.")
    print("--- Test Complete ---")
