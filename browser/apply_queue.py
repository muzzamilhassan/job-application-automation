"""Assisted-apply queue: walks you through queued apply-URL jobs one by one.

For each job (highest score first):
  1. opens the application page in the dedicated browser
  2. aborts if a CAPTCHA/security wall appears (nothing is touched)
  3. auto-fills known fields from your profile + attaches the tailored CV
  4. YOU review, answer anything left, and click Submit yourself
  5. confirm in the terminal -> tracker marks it applied

Usage:
  python browser/apply_queue.py              # up to the daily cap
  python browser/apply_queue.py --limit 3    # just a few
"""
import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_core import make_driver, detect_block, human_pause, SAFETY  # noqa: E402
from ats_fillers import detect_ats, fill_form  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def resolve_cv(tracker_row) -> Path | None:
    """CV docx for this job: reuse tracked one, convert md->docx, else None."""
    import tailor
    cv_md = tracker_row["cv_path"]
    if cv_md:
        md = ROOT / cv_md
        if md.exists():
            dx = md.with_suffix(".docx")
            if not dx.exists():
                tailor.md_to_docx(md.read_text(encoding="utf-8"), dx)
            if dx.exists():
                return dx
    # nothing tracked - regenerate from today's matches if present
    mfile = ROOT / "out" / f"matches_{date.today().isoformat()}.json"
    if mfile.exists():
        for j in load_json(mfile):
            if j["id"] == tracker_row["job_id"]:
                _, dx = tailor.tailor(j)
                return dx if dx.exists() else None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    cap = args.limit or SAFETY.get("assisted_daily_cap", 10)
    profile = load_json(ROOT / "config" / "profile.json")
    settings = load_json(ROOT / "config" / "settings.json")

    import tracker
    c = tracker.conn()
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT rowid_hint, job_id, title, company, source, url, score, cv_path "
        "FROM applications WHERE status='queued-browser-assist' "
        "ORDER BY score DESC LIMIT ?", (cap,)).fetchall()
    if not rows:
        print("Queue empty - nothing waiting for assisted apply.")
        return

    print(f"Assisted-apply queue: {len(rows)} job(s) "
          f"(cap {cap}, hours {SAFETY['operating_hours']})\n")
    driver = make_driver(headless=False)
    applied = skipped = 0
    try:
        for r in rows:
            print("=" * 70)
            print(f"[{r['score']}] {r['title']}")
            print(f"  {r['company']} | {r['source']} | {r['url']}")
            ats = detect_ats(r["url"] or "", r["source"] or "")
            import tailor
            cv = tailor.clean_cv(resolve_cv(r))
            print(f"  ATS: {ats} | CV: {cv.name if cv else 'NONE (will fill without upload)'}")

            driver.get(r["url"])
            human_pause(5, 8)
            block = detect_block(driver)
            if block:
                print(f"  !! security wall ({block}) - SKIPPING this job, nothing touched")
                skipped += 1
                continue

            try:
                report = fill_form(driver, profile, settings, cv,
                                   r["title"], r["company"])
            except Exception as e:
                print(f"  !! fill failed ({e.__class__.__name__}: {str(e)[:80]}) - skip")
                skipped += 1
                continue

            print("  --- auto-filled ---")
            for f in report["filled"]:
                print(f"    + {f}")
            if report["uploaded"]:
                print(f"    + CV uploaded: {report['uploaded']}")
            if report["left_for_human"]:
                print("  --- needs you ---")
                for f in report["left_for_human"][:8]:
                    print(f"    ? {f}")
            if report["unknown_selects"]:
                print(f"  --- unanswered questions (answer in browser): {', '.join(report['unknown_selects'][:6])}")

            ans = input("  Review in browser, click SUBMIT yourself.\n"
                        "  [Enter]=submitted  s=skip  q=quit > ").strip().lower()
            if ans == "q":
                break
            if ans == "s":
                skipped += 1
                c.execute("UPDATE applications SET notes = COALESCE(notes,'') || ? "
                          "WHERE rowid_hint=?", (f" | skipped {date.today().isoformat()}", r["rowid_hint"]))
                c.commit()
            else:
                applied += 1
                c.execute("UPDATE applications SET status='applied', applied_on=? "
                          "WHERE rowid_hint=?", (date.today().isoformat(), r["rowid_hint"]))
                c.commit()
                print("  tracked as APPLIED")
            human_pause(4, 9)
    finally:
        driver.quit()
        print(f"\nSession done: {applied} applied, {skipped} skipped/kept in queue.")


if __name__ == "__main__":
    main()
