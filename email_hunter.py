#!/usr/bin/env python3
"""Email Hunter - finds real recruiter/company emails for form-apply jobs.

Pipeline (per job, max ~7 polite HTTP requests, everything time-capped):
  1. fetch the actual job posting page  -> emails in the full description
  2. collect candidate company domains  -> external links on that page,
     ranked by company-name match
  3. scan the company site              -> /careers /contact /about /jobs
  4. optional: Hunter.io domain search  -> only if HUNTER_API_KEY in .env
                                           (free tier 25/month; NOT required)

Acceptance gate (never sends a guessed address):
  * email found on the company's own site, OR generic role mailbox
    (careers/jobs/hr/talent/recruit/hiring) on the official domain, OR
    Hunter result with confidence >= 80
  * board/SaaS/junk domains always rejected

Found email => REAL application draft addressed to the company
(subject "Application: ...", letter, CV attached) + tracker updated.
Nothing is ever auto-sent.

Usage:
  python email_hunter.py              # hunt for queued jobs (capped)
  python email_hunter.py --limit 3
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent

# local .env parity (same keys CI gets from Secrets)
_envf = ROOT / ".env"
if _envf.exists():
    for _line in _envf.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,}")
HREF_RE = re.compile(r'href=["\'](https?://[^"\']+)', re.I)
MAILTO_RE = re.compile(r'mailto:([^"\'?>]+)', re.I)

BOARD_DOMAINS = {
    "weworkremotely.com", "remoteok.com", "glassdoor.com", "glassdoor.co.uk",
    "indeed.com", "bebee.com", "linkedin.com", "wellfound.com", "angel.co",
    "rozee.pk", "hn.algolia.com", "news.ycombinator.com", "jobicy.com",
    "tinyboards.co",
    "remotive.com", "arbeitnow.com", "himalayas.app", "themuse.com",
    "boards.greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com",
    "jobs.smartrecruiters.com", "apply.workable.com", "recruitee.com",
}
SOCIAL_DOMAINS = {
    "twitter.com", "x.com", "facebook.com", "instagram.com", "youtube.com",
    "tiktok.com", "reddit.com", "medium.com", "t.me", "wa.me", "whatsapp.com",
    "play.google.com", "apps.apple.com", "google.com", "googleapis.com",
    "apple.com", "gstatic.com", "cloudflare.com", "cloudflareinsights.com",
    "sentry.io", "sentry-cdn.com", "wix.com", "wixstatic.com", "shopify.com",
}
EXACT_JUNK_LOCALS = {"you", "your", "mail", "address", "emailaddress", "candidate",
                     "login", "signup", "subscribe", "hello2"}
JUNK_LOCALS = {
    "noreply", "no-reply", "donotreply", "do-not-reply", "example", "test",
    "user", "username", "email", "youremail", "your-email", "name", "yourname",
    "john.doe", "jane.doe", "johndoe", "janedoe", "sample", "info@2x", "help",
    "privacy", "support-ticket", "abuse", "postmaster", "webmaster",
}
PLACEHOLDER_DOMAINS = {"example.com", "example.net", "example.org",
                       "yourdomain.com", "yourcompany.com", "domain.com",
                       "email.com", "test.com", "website.com", "site.com"}
LEGAL_SUFFIXES = {"ab", "inc", "llc", "ltd", "limited", "gmbh", "co", "corp",
                  "corporation", "team", "solutions", "technologies",
                  "technology", "group", "labs", "studio", "systems",
                  "services", "software", "ventures", "holdings"}
GENERIC_ROLE_LOCALS = {"careers", "jobs", "hr", "talent", "recruit", "recruitment",
                       "hiring", "recruiting", "people", "work", "apply"}
ROLE_TITLE_WORDS = re.compile(
    r"recruit|talent|hiring|people|human resource|\bhr\b|acquisition", re.I)


def fetch(url: str, timeout: int = 12, max_bytes: int = 400_000) -> str | None:
    """Polite GET. Returns text or None on any failure."""
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(max_bytes)
        return data.decode("utf-8", "replace")
    except Exception:
        return None


def clean_email(addr: str, our_emails: set[str]) -> str | None:
    a = addr.strip().strip(".").lower()
    if "@" not in a or a.count("@") != 1:
        return None
    local, domain = a.split("@", 1)
    if len(a) > 80 or len(local) < 2:
        return None
    if local in EXACT_JUNK_LOCALS or any(j in local for j in JUNK_LOCALS):
        return None
    if any(local.endswith(p) for p in (".png", ".jpg", ".webp", ".gif", ".svg")):
        return None
    if any(domain == b or domain.endswith("." + b) for b in BOARD_DOMAINS | SOCIAL_DOMAINS):
        return None
    if domain in PLACEHOLDER_DOMAINS:
        return None
    if a in our_emails:
        return None
    if domain.endswith((".png", ".jpg", ".webp", ".svg", ".js", ".css")):
        return None
    return a


def extract_emails(html: str, our_emails: set[str]) -> list[str]:
    """Emails from visible text + mailto links, cleaned and deduped."""
    found = []
    for m in EMAIL_RE.findall(re.sub(r"<[^>]+>", " ", html)):
        c = clean_email(m, our_emails)
        if c:
            found.append(c)
    for m in MAILTO_RE.findall(html):
        c = clean_email(m.split("?")[0], our_emails)
        if c:
            found.append(c)
    out, seen = [], set()
    for e in found:
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


def is_role_mailbox(addr: str) -> bool:
    return addr.split("@")[0] in GENERIC_ROLE_LOCALS


def company_slugs(name: str) -> list[str]:
    """Company name -> candidate slugs. 'Proxify AB' -> ['proxify', 'proxifyab'].
    Legal suffixes stripped so domain matching survives company-name noise."""
    tokens = [t for t in re.split(r"[^a-z0-9]+", (name or "").lower()) if t]
    while len(tokens) > 1 and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    full = "".join(tokens)
    return list({full, tokens[0]} - {""})


def candidate_domains(html: str, company: str) -> list[str]:
    """ONLY domains whose name matches the company (slug match). Unrelated
    links (ads, partners, competitors) are ignored - that is the whole point."""
    slugs = company_slugs(company)
    found = []
    for link in HREF_RE.findall(html or ""):
        try:
            netloc = urlparse(link).netloc.lower().removeprefix("www.")
        except Exception:
            continue
        bare = netloc.split(".")[0] + "".join(netloc.split(".")[1:-1])
        if not netloc or "." not in netloc:
            continue
        if any(netloc == b or netloc.endswith("." + b)
               for b in BOARD_DOMAINS | SOCIAL_DOMAINS | PLACEHOLDER_DOMAINS):
            continue
        compact = netloc.replace(".", "")
        if any(s and (s in compact or compact in s) and abs(len(s) - len(compact)) <= 6
               for s in slugs):
            if netloc not in found:
                found.append(netloc)
    return found[:2]


def site_scan(domain: str) -> tuple[list[str], bool]:
    """Scan a company site's home + careers/contact pages.
    Returns (emails, is_official_source)."""
    emails: list[str] = []
    for path in ("/", "/careers", "/contact", "/about", "/jobs"):
        html = fetch(f"https://{domain}{path}")
        if html:
            emails.extend(extract_emails(html, set()))
        time.sleep(0.6)
        if emails:
            break  # found on the first page that yields anything - stay polite
    seen = set()
    uniq = [e for e in emails if not (e in seen or seen.add(e))]
    return uniq, True


def hunter_domain_search(domain: str) -> list[dict]:
    """Optional: Hunter.io domain-search (free 25/month). Requires HUNTER_API_KEY."""
    key = os.environ.get("HUNTER_API_KEY")
    if not key:
        return []
    try:
        req = urllib.request.Request(
            f"https://api.hunter.io/v2/domain-search?domain={domain}&limit=5&api_key={key}")
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode()).get("data", {}).get("emails", [])
        return [e for e in data if e.get("confidence", 0) >= 80]
    except Exception:
        return []


def hunt(url: str, company: str, our_emails: set[str]) -> tuple[str | None, str]:
    """Returns (email | None, source_description)."""
    # 1) the job page itself - accept only emails on company-matched domains
    html = fetch(url)
    domains = candidate_domains(html, company)
    if html:
        for e in extract_emails(html, our_emails):
            ed = e.split("@")[1]
            if any(s and (s in ed.replace(".", "") or ed.replace(".", "") in s)
                   for s in company_slugs(company)):
                return e, "job-page"

    # 2) company site scan (homepage/careers/contact)
    for d in domains:
        emails, _ = site_scan(d)
        if emails:
            role = next((e for e in emails if is_role_mailbox(e)), None)
            return (role or emails[0]), f"company-site:{d}"

    # 3) optional finder API (only with a key present)
    for d in domains[:1]:
        for e in hunter_domain_search(d):
            addr = (e.get("value") or "").lower()
            if clean_email(addr, our_emails):
                pos = (e.get("position") or "")
                if e.get("type") == "generic" or ROLE_TITLE_WORDS.search(pos):
                    return addr, f"hunter:{d}"

    return None, "not-found"


# ---------------------------------------------------------------- queue run
def process_queue(limit: int, settings: dict, prof: dict) -> list[dict]:
    """Hunt emails for queued jobs; create company-addressed drafts on hits."""
    import tailor
    from gmail_drafts import create_draft

    our = {prof["contact"].get("application_email", "").lower(),
           prof["contact"].get("cv_email", "").lower()} - {""}
    tdb = sqlite3.connect(ROOT / "data" / "tracker.db")
    tdb.row_factory = sqlite3.Row
    rows = tdb.execute(
        "SELECT rowid_hint, job_id, title, company, source, url, score, status, cv_path, notes "
        "FROM applications WHERE status='queued-browser-assist' "
        "AND (notes IS NULL OR notes NOT LIKE '%hunter-email=%') "
        "ORDER BY score DESC LIMIT ?", (limit,)).fetchall()
    results = []
    for r in rows:
        if not r["url"]:
            continue
        print(f"[{r['score']}] hunting: {r['title'][:45]:45s} | {r['company'][:25]}")
        email, source = hunt(r["url"], r["company"], our)
        if not email:
            tdb.execute("UPDATE applications SET notes = COALESCE(notes,'') || ? "
                        "WHERE rowid_hint=?",
                        (f" | hunter-email=none({date.today().isoformat()})", r["rowid_hint"]))
            tdb.commit()
            print("    - no email found")
            results.append({"job": r["title"], "email": None})
            time.sleep(1.5)
            continue
        # found: create the REAL application draft addressed to the company
        cv = tailor.clean_cv(Path(r["cv_path"]).with_suffix(".docx") if r["cv_path"] else None)
        jm = {}
        mfile = ROOT / "out" / f"matches_{date.today().isoformat()}.json"
        if mfile.exists():
            for mm in json.loads(mfile.read_text(encoding="utf-8")):
                if mm["id"] == r["job_id"]:
                    jm = mm
                    break
        letter = tailor.cover_letter({"title": r["title"], "company": r["company"],
                                      "text": jm.get("text", "")})
        c = prof["contact"]
        body = (f"Dear Hiring Team,\n\n"
                f"I am applying for the {r['title']} role at {r['company']}.\n\n"
                f"{letter}\n\n"
                f"My CV is attached. I am available for remote or on-site work and can "
                f"join within two weeks (immediately if needed).\n\n"
                f"Best regards,\n{prof['name']}\n"
                f"{c['application_email']} | {c['phone']}\n"
                f"{c.get('linkedin_url', '')} | {c.get('github_url', '')} | "
                f"{c.get('portfolio_url', '')}")
        subject = f"Application: {r['title']} at {r['company']} - CV attached"
        draft_id = create_draft(email, subject, body,
                                attachments=[cv] if cv and cv.exists() else None)
        tdb.execute("UPDATE applications SET status='drafted', notes = COALESCE(notes,'') || ? "
                    "WHERE rowid_hint=?",
                    (f" | hunter-email={email} via {source} draft={draft_id}", r["rowid_hint"]))
        tdb.commit()
        print(f"    + FOUND {email} ({source}) -> draft {draft_id} ready for your review")
        results.append({"job": r["title"], "email": email, "source": source,
                        "draft_id": draft_id})
        time.sleep(1.5)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    settings = json.loads((ROOT / "config" / "settings.json").read_text(encoding="utf-8"))
    prof = json.loads((ROOT / "config" / "profile.json").read_text(encoding="utf-8"))
    cap = a.limit or settings.get("email_hunter", {}).get("daily_cap", 5)
    res = process_queue(cap, settings, prof)
    found = [x for x in res if x.get("email")]
    print(f"\nHunter done: {len(found)}/{len(res)} company emails found -> drafts ready for review")


if __name__ == "__main__":
    main()
