"""One-time login + session health for LinkedIn / Indeed / Glassdoor.

You log in YOURSELF, once, in the window that opens (password + 2FA typed by
you, never by code). Sessions are then stored in browser/chrome_profile/ and
reused by the daily automation until the site expires them.

  python browser/session.py --login all          # open all three, log in one by one
  python browser/session.py --login linkedin     # just one site
  python browser/session.py --check              # is each session still alive?
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_core import make_driver, detect_block  # noqa: E402

LOGIN_URLS = {
    "linkedin": "https://www.linkedin.com/login",
    "indeed": "https://secure.indeed.com/account/login",
    "glassdoor": "https://www.glassdoor.com/profile/logIn.htm",
    "wellfound": "https://wellfound.com/login",
}
CHECK_URLS = {
    "linkedin": "https://www.linkedin.com/jobs/",
    "indeed": "https://www.indeed.com/",
    "glassdoor": "https://www.glassdoor.com/member/home.htm",
    "wellfound": "https://wellfound.com/",
}
MARKER = Path(__file__).resolve().parent / "sessions.json"


def load_marker() -> dict:
    return json.loads(MARKER.read_text()) if MARKER.exists() else {}


def session_ok(driver, site: str) -> bool:
    """Conservative check: page loads, no login redirect/wall, no security block."""
    try:
        driver.get(CHECK_URLS[site])
        driver.implicitly_wait(5)
        if detect_block(driver):
            return False
        url = driver.current_url.lower()
        if site == "linkedin":
            return "/login" not in url and "authwall" not in url
        if site == "indeed":
            return "login" not in url
        if site == "glassdoor":
            return "login" not in url and "auth" not in url
        if site == "wellfound":
            # logged-out pages show a nav "Log in" link; logged-in pages don't
            return not driver.find_elements("css selector", 'a[href="/login"]')
    except Exception:
        return False
    return False


def main():
    arg = next((a for a in sys.argv[1:] if a.startswith("--")), "--check")
    marker = load_marker()

    if arg == "--check":
        driver = make_driver(headless=False)
        try:
            for site in CHECK_URLS:
                ok = session_ok(driver, site)
                marker[site] = {"ok": ok, "checked": datetime.now().isoformat(timespec="minutes")}
                print(f"  {site:10s} {'LOGGED IN' if ok else 'NOT logged in  -> run: python browser/session.py --login ' + site}")
        finally:
            driver.quit()
        MARKER.write_text(json.dumps(marker, indent=1))
        return

    sites = list(LOGIN_URLS) if arg.split()[1] == "all" else [arg.split()[1]]
    driver = make_driver(headless=False)
    try:
        for site in sites:
            driver.get(LOGIN_URLS[site])
            input(f"\nLog in to {site.upper()} in the opened window (email + password + 2FA, yourself).\n"
                  f"Press Enter HERE when you can see your feed/dashboard... ")
            ok = session_ok(driver, site)
            marker[site] = {"ok": ok, "logged_in_at": datetime.now().isoformat(timespec="minutes")}
            print(f"  {site}: {'session saved' if ok else 'still not logged in - run --check to inspect'}")
        MARKER.write_text(json.dumps(marker, indent=1))
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
