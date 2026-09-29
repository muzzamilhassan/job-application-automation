"""Assisted application layer - the safety gate is NOT optional.

Current version (v1): opens a job application in the dedicated-profile browser,
checks for CAPTCHA/security walls, verifies your session, maps the form fields,
and hands control to YOU - you review and click submit yourself. The system
types nothing into forms yet: v2 auto-fill gets tuned together on real forms
(one site at a time), always stopping before the submit button.

  python browser/apply_assist.py linkedin https://www.linkedin.com/jobs/view/XXXX
  python browser/apply_assist.py indeed   https://www.indeed.com/viewjob?jk=XXXX
  python browser/apply_assist.py glassdoor <url>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_core import make_driver, detect_block, human_pause  # noqa: E402


def assisted_apply(site: str, url: str):
    driver = make_driver(headless=False)
    try:
        driver.get(url)
        human_pause(5, 8)
        block = detect_block(driver)
        if block:
            print(f"ABORT: security wall detected ({block}). Nothing will be filled.")
            return
        fields = driver.find_elements("css selector",
                                      "input, textarea, select, button[type='submit']")
        print(f"\n{site} application page loaded. Session OK, no security walls.")
        print(f"Form elements found: {len(fields)}")
        for f in fields[:15]:
            print(f"  - <{f.tag_name}> name={f.get_attribute('name')!r} "
                  f"type={f.get_attribute('type')!r} placeholder={f.get_attribute('placeholder')!r}")
        input("\nReview the page in the browser window. Apply YOURSELF now.\n"
              "Press Enter here when done (or Ctrl+C to leave it open)... ")
        print("Done. Log this in the tracker: python tracker.py add ...")
    finally:
        driver.quit()


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("linkedin", "indeed", "glassdoor"):
        raise SystemExit(__doc__)
    assisted_apply(sys.argv[1], sys.argv[2])
