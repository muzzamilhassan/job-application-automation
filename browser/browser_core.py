"""Shared browser layer: dedicated Chrome profile + safety helpers.

Safety model (INTEGRATIONS.md):
  * Your logins live ONLY in browser/chrome_profile/ (gitignored). Passwords
    never touch code, config, or logs.
  * Human-like pacing from settings.browser_layer: randomized delays,
    page/listing caps, operating hours.
  * Automation flags hidden; real installed Chrome used (Edge fallback).
"""
import json
import random
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "browser" / "chrome_profile"
SETTINGS = json.loads((ROOT / "config" / "settings.json").read_text(encoding="utf-8"))
SAFETY = SETTINGS["browser_layer"]


def make_driver(headless: bool | None = None):
    """Launch the dedicated-profile browser. Chrome first, Edge fallback."""
    from selenium import webdriver

    headless = SAFETY["headless"] if headless is None else headless
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        opts = webdriver.ChromeOptions()
        opts.add_argument(f"--user-data-dir={PROFILE_DIR}")
        opts.add_argument("--profile-directory=Default")
        opts.add_argument("--window-size=1366,900")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        if headless:
            opts.add_argument("--headless=new")
        driver = webdriver.Chrome(options=opts)  # Selenium Manager fits the driver
    except Exception:
        eopts = webdriver.EdgeOptions()
        eopts.add_argument(f"--user-data-dir={PROFILE_DIR}_edge")
        eopts.add_argument("--window-size=1366,900")
        eopts.add_argument("--disable-blink-features=AutomationControlled")
        if headless:
            eopts.add_argument("--headless=new")
        driver = webdriver.Edge(options=eopts)

    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
    })
    return driver


def human_pause(lo: float | None = None, hi: float | None = None):
    lo = SAFETY["delay_between_actions_seconds"][0] if lo is None else lo
    hi = SAFETY["delay_between_actions_seconds"][1] if hi is None else hi
    time.sleep(random.uniform(lo, hi))


def within_operating_hours() -> bool:
    start, end = SAFETY["operating_hours"].split("-")
    hour = datetime.now().hour
    return int(start.split(":")[0]) <= hour < int(end.split(":")[0])


CAPTCHA_HINTS = ["captcha", "are you a human", "security verification",
                 "unusual activity", "verify it's you", "help us protect"]


def detect_block(driver) -> str | None:
    """Return a reason string if the page shows a CAPTCHA/security wall."""
    try:
        low = driver.page_source.lower()
        for hint in CAPTCHA_HINTS:
            if hint in low:
                return hint
    except Exception:
        pass
    return None
