"""
TEST SCRIPT: Simulates a booking detection and sends REAL notifications.
Run this to verify Telegram, SMS, and Voice Call all work correctly.
"""

import os
import sys
import logging
import requests

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("test")


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
    logger.info("=" * 50)
    logger.info("TEST MODE: Simulating booking detection")
    logger.info("=" * 50)

    fake_url = "https://jksasb.nic.in/onlineservices/helicopter_booking.aspx"

    # Test 1: Telegram
    logger.info("--- Test 1: Telegram Message ---")
    tg_ok = send_telegram(
        "<b>TEST ALERT: This is a test notification!</b>\n\n"
        "If you see this, Telegram notifications are working.\n"
        f"Simulated URL: {fake_url}"
    )

    # Test 2: SMS
    logger.info("--- Test 2: SMS ---")
    sms_ok = send_sms(
        "TEST ALERT: This is a test from Helicopter Monitor. "
        "If you receive this, SMS notifications are working!"
    )

    # Test 3: Voice Call
    logger.info("--- Test 3: Voice Call ---")
    call_ok = make_call(
        "This is a test call from the helicopter booking monitor. "
        "If you hear this message, voice call notifications are working correctly."
    )

    # Summary
    logger.info("=" * 50)
    logger.info("TEST RESULTS:")
    logger.info("  Telegram: %s", "PASS" if tg_ok else "FAIL")
    logger.info("  SMS:      %s", "PASS" if sms_ok else "FAIL")
    logger.info("  Call:     %s", "PASS" if call_ok else "FAIL")
    logger.info("=" * 50)

    if all([tg_ok, sms_ok, call_ok]):
        logger.info("ALL TESTS PASSED! You should receive 3 notifications on your phone.")
    else:
        logger.warning("Some tests failed. Check the logs above for details.")


if __name__ == "__main__":
    main()
