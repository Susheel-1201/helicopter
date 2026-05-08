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


def make_call(spoken_message: str) -> str | None:
    """
    Make a voice call via Twilio with TwiML <Say>.
    Returns the call SID if initiated, or None on failure.
    """
    if not all([TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM, USER_PHONE]):
        logger.warning("Twilio Voice not configured — skipping")
        return None
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
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
        return call.sid
    except Exception as e:
        logger.error("Voice call failed: %s", e)
        return None


def was_call_answered(call_sid: str) -> bool:
    """
    Check if a Twilio call was answered by polling its status.
    Waits up to 60 seconds for the call to complete.
    'completed' = user picked up. 'no-answer'/'busy'/'failed'/'canceled' = not picked up.
    """
    if not all([TWILIO_SID, TWILIO_TOKEN]):
        return False
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        # Poll every 5 seconds for up to 60 seconds
        for i in range(12):
            call = client.calls(call_sid).fetch()
            status = call.status
            logger.info("Call %s status: %s", call_sid, status)

            if status == "completed":
                logger.info("User ANSWERED the call!")
                return True
            elif status in ("no-answer", "busy", "failed", "canceled"):
                logger.info("User did NOT answer (status: %s)", status)
                return False

            # Still ringing or in-progress — wait and check again
            time.sleep(5)

        logger.warning("Call status check timed out after 60 seconds")
        return False
    except Exception as e:
        logger.error("Failed to check call status: %s", e)
        return False


def notify_all(redirect_url: str) -> None:
    """
    Notification sequence with 1-minute gaps:
      1. Send Telegram message
      2. Wait 1 minute
      3. Send SMS
      4. Wait 1 minute
      5. Make voice call — if user answers, STOP
      6. If not answered, retry the whole sequence (max 2 retries)
    """
    max_attempts = 2
    gap_seconds = 60

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

    for attempt in range(1, max_attempts + 1):
        logger.info("=== Notification attempt %d of %d ===", attempt, max_attempts)

        # Step 1: Telegram
        logger.info("Step 1: Sending Telegram message...")
        send_telegram(tg_text)

        # Wait 1 minute
        logger.info("Waiting %d seconds before SMS...", gap_seconds)
        time.sleep(gap_seconds)

        # Step 2: SMS
        logger.info("Step 2: Sending SMS...")
        send_sms(sms_text)

        # Wait 1 minute
        logger.info("Waiting %d seconds before voice call...", gap_seconds)
        time.sleep(gap_seconds)

        # Step 3: Voice call + check if answered
        logger.info("Step 3: Making voice call...")
        call_sid = make_call(call_text)

        if call_sid:
            answered = was_call_answered(call_sid)
            if answered:
                logger.info("User answered the call — STOPPING notifications.")
                return

            logger.info("User did not answer the call.")
        else:
            logger.warning("Call could not be initiated.")

        if attempt < max_attempts:
            logger.info("Retrying full notification sequence...")
        else:
            logger.info("All %d attempts exhausted. User may not have responded.", max_attempts)

    logger.info("Notification sequence complete.")


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
