import os
import re
import sys
import time
import signal
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

from notifier import notify_all

# --- Config ---
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "120"))
TARGET_URL = "https://jksasb.nic.in/onlineservices/"
HELI_LINK_TEXT = "Helicopter Ticket Booking"

# Known "inactive" href patterns — booking is NOT open if href matches any of these
INACTIVE_PATTERNS = {"#", "", "javascript:void(0)", "javascript:void(0);", "javascript:;"}

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("monitor.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("monitor")

# Graceful shutdown
shutdown = False


def handle_signal(signum, frame):
    global shutdown
    logger.info("Shutdown signal received, exiting gracefully...")
    shutdown = True


signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


def tier1_http_check() -> str | None:
    """
    Tier 1: Lightweight HTTP GET to fetch the page HTML and look for the
    helicopter booking link's href. Returns the new href if it looks like
    a real booking URL, or None if still inactive.
    """
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

        # Look for anchor tags containing the helicopter text
        # Pattern matches <a ... href="..." ...>...Helicopter Ticket Booking...</a>
        pattern = re.compile(
            r'<a\b[^>]*\bhref\s*=\s*["\']([^"\']*)["\'][^>]*>([^<]*Helicopter[^<]*Ticket[^<]*Booking[^<]*)',
            re.IGNORECASE | re.DOTALL,
        )
        match = pattern.search(html)

        if match:
            href = match.group(1).strip()
            link_text = match.group(2).strip()
            logger.info("Found helicopter link: href='%s' text='%s'", href, link_text)

            if href.lower() in INACTIVE_PATTERNS:
                logger.info("Tier 1: Link is still inactive (href='%s')", href)
                return None
            else:
                logger.info("Tier 1: ACTIVE link detected! href='%s'", href)
                return href
        else:
            # Try alternative: look for the text and check if it's wrapped
            # in an anchor or if the page structure changed
            if "helicopter" in html.lower() and "booking" in html.lower():
                # Check for any link near the helicopter text with broader pattern
                broad_pattern = re.compile(
                    r'href\s*=\s*["\']([^"\']+)["\'][^>]*>[^<]*?Helicopter',
                    re.IGNORECASE,
                )
                broad_match = broad_pattern.search(html)
                if broad_match:
                    href = broad_match.group(1).strip()
                    if href.lower() not in INACTIVE_PATTERNS:
                        logger.info("Tier 1: Broad match found active link: '%s'", href)
                        return href

            logger.info("Tier 1: Helicopter link not found or not in an <a> tag")
            return None

    except requests.RequestException as e:
        logger.error("Tier 1: HTTP request failed — %s", e)
        return None


def tier2_selenium_check(detected_href: str) -> str | None:
    """
    Tier 2: Selenium confirmation. Opens a headless browser, navigates to the
    page, clicks the helicopter link, and checks if it redirects to a new page.
    Returns the confirmed redirect URL, or None if it was a false positive.
    """
    logger.info("Tier 2: Launching Selenium for confirmation...")

    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from webdriver_manager.chrome import ChromeDriverManager

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        )

        # Try to use system chromium first (for Docker/Render), fallback to webdriver-manager
        chrome_path = os.getenv("CHROME_BINARY")
        if chrome_path:
            options.binary_location = chrome_path

        chromedriver_path = os.getenv("CHROMEDRIVER_PATH")
        if chromedriver_path:
            service = Service(executable_path=chromedriver_path)
        else:
            service = Service(ChromeDriverManager().install())

        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(45)

        try:
            driver.get(TARGET_URL)
            logger.info("Tier 2: Page loaded — current URL: %s", driver.current_url)

            # Wait for page content to load
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            initial_url = driver.current_url

            # Try to find and click the helicopter link
            heli_element = None

            # Strategy 1: Find by partial link text
            try:
                heli_element = driver.find_element(
                    By.PARTIAL_LINK_TEXT, "Helicopter"
                )
            except Exception:
                pass

            # Strategy 2: Find by XPath containing the text
            if not heli_element:
                try:
                    heli_element = driver.find_element(
                        By.XPATH,
                        "//a[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'helicopter')]"
                    )
                except Exception:
                    pass

            # Strategy 3: Find any element with helicopter text
            if not heli_element:
                try:
                    heli_element = driver.find_element(
                        By.XPATH,
                        "//*[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'helicopter ticket')]"
                    )
                except Exception:
                    pass

            if heli_element:
                href_attr = heli_element.get_attribute("href") or ""
                tag_name = heli_element.tag_name
                logger.info(
                    "Tier 2: Found element <%s> href='%s'", tag_name, href_attr
                )

                # Check if href itself is a real URL
                if href_attr and href_attr.lower().rstrip("/") != TARGET_URL.rstrip("/"):
                    stripped = href_attr.strip().lower()
                    if stripped not in INACTIVE_PATTERNS and not stripped.startswith("javascript:"):
                        logger.info("Tier 2: CONFIRMED — href points to: %s", href_attr)
                        return href_attr

                # Try clicking and see if URL changes
                try:
                    heli_element.click()
                    time.sleep(3)
                    new_url = driver.current_url

                    if new_url != initial_url and new_url.rstrip("/") != TARGET_URL.rstrip("/"):
                        logger.info("Tier 2: CONFIRMED — redirected to: %s", new_url)
                        return new_url
                    else:
                        logger.info("Tier 2: Click did not redirect. URL unchanged.")
                except Exception as click_err:
                    logger.warning("Tier 2: Click failed — %s", click_err)

                # Check if a new window/tab opened
                if len(driver.window_handles) > 1:
                    driver.switch_to.window(driver.window_handles[-1])
                    new_url = driver.current_url
                    if new_url != initial_url:
                        logger.info("Tier 2: CONFIRMED — new tab opened: %s", new_url)
                        return new_url

            else:
                logger.warning("Tier 2: Could not find helicopter element on page")

            # If we got here with a detected_href from Tier 1, trust it
            if detected_href and detected_href.startswith("http"):
                logger.info("Tier 2: Trusting Tier 1 detected href: %s", detected_href)
                return detected_href

            logger.info("Tier 2: Could not confirm redirect — possible false positive")
            return None

        finally:
            driver.quit()
            logger.info("Tier 2: Browser closed")

    except Exception as e:
        logger.error("Tier 2: Selenium check failed — %s", e)
        # If Tier 1 found a real-looking URL, trust it even if Selenium fails
        if detected_href and detected_href.startswith("http"):
            logger.info("Tier 2: Selenium failed but trusting Tier 1 href: %s", detected_href)
            return detected_href
        return None


def run_check() -> str | None:
    """
    Run the two-tier check. Returns the confirmed booking URL if detected,
    or None if no change.
    """
    logger.info("--- Starting check cycle ---")

    # Tier 1: Fast HTTP check
    tier1_result = tier1_http_check()

    if tier1_result is None:
        logger.info("Tier 1 says no change. Skipping Tier 2.")
        return None

    # Tier 2: Selenium confirmation
    confirmed_url = tier2_selenium_check(tier1_result)
    return confirmed_url


def main():
    logger.info("=" * 60)
    logger.info("Amarnath Helicopter Booking Monitor — STARTED")
    logger.info("Target: %s", TARGET_URL)
    logger.info("Check interval: %d seconds", CHECK_INTERVAL)
    logger.info("=" * 60)

    check_count = 0

    while not shutdown:
        check_count += 1
        logger.info("Check #%d", check_count)

        redirect_url = run_check()

        if redirect_url:
            logger.info("*" * 60)
            logger.info("BOOKING DETECTED! URL: %s", redirect_url)
            logger.info("*" * 60)

            # Fire all notifications with retry
            notify_all(redirect_url)

            logger.info("Monitoring complete. Exiting.")
            break

        if shutdown:
            break

        logger.info(
            "No change detected. Next check in %d seconds...\n", CHECK_INTERVAL
        )
        # Sleep in small chunks so we can respond to shutdown signals quickly
        for _ in range(CHECK_INTERVAL):
            if shutdown:
                break
            time.sleep(1)

    logger.info("Monitor stopped.")


if __name__ == "__main__":
    main()
