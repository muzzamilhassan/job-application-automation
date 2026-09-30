#!/usr/bin/env python3
"""Daily orchestrator.

  python run_daily.py            -> collect + score + review report (SAFE: no logins,
                                    no emails, no drafts)
  python run_daily.py --auto     -> the full flow Windows runs at every logon:
                                    collect -> score -> tailor top N -> Gmail DRAFTS
                                    (for matches that carry a real employer email)
                                    -> tracker entries -> out/auto_summary_<date>.md
                                    Drafts are created, NEVER sent.

Gmail drafts need the one-time OAuth in README ("Gmail drafts setup"): once
token.json exists, the auto flow creates drafts silently on every run.
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"

JUNK_EMAIL = re.compile(r"(no[-.]?reply|noreply|example\.|ycombinator|donotreply)", re.I)
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def own_emails():
    """Candidate's own addresses (never draft to these) - from profile, not code."""
    p = json.loads((ROOT / "config" / "profile.json").read_text(encoding="utf-8"))
    vals = {p["contact"].get("application_email", ""), p["contact"].get("cv_email", "")}
    return {v.lower() for v in vals if v}


def run(script, *args):
    print(f"\n=== {Path(script).name} {' '.join(args)} ===")
    r = subprocess.run([sys.executable, str(ROOT / script), *args])
    if r.returncode != 0:
        sys.exit(f"{script} failed with code {r.returncode}")


def find_employer_email(job_dict):
    for m in EMAIL_RE.findall(job_dict.get("text") or ""):
        if m.lower() in own_emails() or JUNK_EMAIL.search(m):
            continue
        return m
    return None


def draft_body(job_dict):
    p = json.loads((ROOT / "config" / "profile.json").read_text(encoding="utf-8"))
    ai_note = ""
    ai = [s for s in p["skills"]["ai"] if s.lower() in (job_dict.get("text") or "").lower()]
    if ai:
        ai_note = f" Hands-on AI delivery with {' and '.join(ai[:2])}."
    return (
        f"Hello,\n\n"
        f"I'm {p['name']}, a Full Stack Developer (MERN / Next.js) building production "
        f"SaaS products end-to-end - React/Next.js frontends, Node.js/NestJS backends, "
        f"multi-database architectures (PostgreSQL, MySQL, MongoDB).{ai_note}\n\n"
        f"I'd love to be considered for the {job_dict['title']} role at "
        f"{job_dict['company']}. My tailored CV is attached.\n\n"
        f"Posting seen at: {job_dict.get('url') or 'job board'}\n\n"
        f"Best regards,\n{p['name']}\n"
        f"{p['contact']['application_email']} | {p['contact']['phone']}"
    )


def auto_flow(matches_file):
    import sqlite3
    import tracker
    settings = json.loads((ROOT / "config" / "settings.json").read_text(encoding="utf-8"))
    import tailor
    matches = json.loads(matches_file.read_text(encoding="utf-8"))

    # never re-draft a job that is already tracked (any status)
    c = tracker.conn()  # creates data/ + schema on fresh CI checkouts
    seen = {r[0] for r in c.execute("SELECT job_id FROM applications")}

    top = [j for j in matches if j["id"] not in seen][: settings["auto"]["drafts_per_run"]]
    skipped = sum(1 for j in matches[: settings["auto"]["drafts_per_run"]] if j["id"] in seen)
    token_ready = (ROOT / "token.json").exists()
    lines = [f"# Auto-run summary - {date.today().isoformat()}",
             f"Gmail connected: {token_ready} | already-tracked skipped: {skipped}", ""]
    today = date.today().isoformat()

    for j in top:
        md, dx = tailor.tailor(j)
        email = find_employer_email(j)
        if not email:
            status = "queued-browser-assist"
            note = "no employer email in posting - goes to browser-assist queue (Week 2 layer)"
        elif not token_ready:
            status = "pending-gmail-setup"
            note = f"employer email {email} found, but Gmail OAuth not done yet (README step)"
        else:
            from gmail_drafts import create_draft
            subject = settings["email_draft_rules"]["subject_template"].format(
                job_title=j["title"], candidate_name=settings["candidate_name"])
            draft_id = create_draft(email, subject, draft_body(j), dx if dx.exists() else None)
            status, note = "drafted", f"Gmail draft to {email} (id={draft_id}) - NOT sent"
        c.execute("INSERT INTO applications (job_id,title,company,source,url,score,status,cv_path,notes) "
                  "VALUES (?,?,?,?,?,?,?,?,?)",
                  (j["id"], j["title"], j["company"], j["source"], j["url"], j["score"],
                   status, str(md.relative_to(ROOT)), note))
        c.commit()
        lines.append(f"## [{j['score']}] {j['title']} - {j['company']}")
        lines.append(f"- {note}")
        if j["url"]:
            lines.append(f"- {j['url']}")
        lines.append("")

    if not top:
        lines.append("- nothing new above threshold; all candidates already tracked")

    # ---- per-job drafts: ONE draft per matched job, addressed to the user,
    # each carrying THAT job's own tailored CV. Form-apply jobs become a
    # personal launchpad (link + reusable pitch + CV); employer-email jobs get
    # a real addressed draft earlier in the loop above.
    per_job_drafts = 0
    try:
        from gmail_drafts import create_draft
        import tailor as _tailor
        import sqlite3 as _sq
        tdb = _sq.connect(ROOT / "data" / "tracker.db")
        tdb.row_factory = _sq.Row
        for j in matches[: settings["auto"]["drafts_per_run"]]:
            row = tdb.execute("SELECT rowid_hint, status, cv_path, notes FROM applications "
                              "WHERE job_id=?", (j["id"],)).fetchone()
            if row is None:
                continue
            if "self-draft id=" in (row["notes"] or ""):
                continue  # already drafted for this job on a previous run
            cv = None
            if row["cv_path"]:
                md = ROOT / row["cv_path"]
                if md.exists():
                    cv = md.with_suffix(".docx")
                    if not cv.exists():
                        _tailor.md_to_docx(md.read_text(encoding="utf-8"), cv)
            if cv is None or not cv.exists():
                _, cv = _tailor.tailor(j)
            letter = _tailor.cover_letter(j)
            prof = json.loads((ROOT / "config" / "profile.json").read_text(encoding="utf-8"))
            contact = prof["contact"]
            body = (
                f"Dear Hiring Team,\n\n"
                f"I am applying for the {j['title']} role at {j['company']}.\n\n"
                f"{letter}\n\n"
                f"My CV is attached. I am available for remote or on-site work and can "
                f"join within two weeks (immediately if needed).\n\n"
                f"Best regards,\n"
                f"{prof['name']}\n"
                f"{contact.get('application_email', '')} | {contact.get('phone', '')}\n"
                f"{contact.get('linkedin_url', '')} | {contact.get('github_url', '')} | "
                f"{contact.get('portfolio_url', '')}\n"
                f"\n------------------------------\n"
                f"Apply online: {j.get('url') or 'see posting'}\n"
                f"Source: {j['source']} · Match: {j['score']}/100 · {row['status']}\n"
                f"(Form-apply job: the Apply-Assist window opens this form pre-filled at logon.)")
            did = create_draft(
                to=settings["application_email"],
                subject=f"Application: {j['title']} at {j['company']} — CV attached",
                body=body,
                attachments=[cv] if cv and cv.exists() else None)
            per_job_drafts += 1
            tdb.execute("UPDATE applications SET notes = COALESCE(notes,'') || ? "
                        "WHERE rowid_hint=?",
                        (f" | self-draft id={did}", row["rowid_hint"]))
            tdb.commit()
            lines.append(f"## Per-job draft: {j['title']} @ {j['company']} (id={did}, CV: {cv.name if cv else 'none'})")
    except Exception as e:
        lines.append(f"## Per-job drafts FAILED: {e.__class__.__name__}: {str(e)[:120]}")

    drafted_n = sum(1 for ln in lines if "Gmail draft to" in ln)
    digest_note = f"employer-email drafts: {drafted_n} | per-job drafts: {per_job_drafts} | " \
                  f"form-apply queue: {sum(1 for ln in lines if 'browser-assist queue' in ln)}"
    summary = OUT / f"auto_summary_{today}.md"
    lines.insert(2, digest_note)
    summary.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nAuto flow done -> {summary.name} ({digest_note})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--auto", action="store_true",
                    help="full flow: collect, score, tailor top N, create Gmail drafts")
    ap.add_argument("--tailor", type=int, metavar="N", help="tailor match N then stop")
    a = ap.parse_args()

    run("collector/collect.py")
    run("matcher.py")
    today = date.today().isoformat()
    matches_file = OUT / f"matches_{today}.json"

    if a.tailor is not None:
        run("tailor.py", str(matches_file), str(a.tailor))
    elif a.auto:
        auto_flow(matches_file)

    print(f"\nDone. Review queue: out/dry_run_report_{today}.md")


if __name__ == "__main__":
    main()
