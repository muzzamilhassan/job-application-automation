#!/usr/bin/env python3
"""Stage 1 - Job collectors, registry-driven and health-monitored.

ALL sources here are public, login-free, and legitimate:
  - Official job-board APIs: Remotive, Jobicy, Arbeitnow, Himalayas, RemoteOK,
    WeWorkRemotely (RSS), Hacker News who's-hiring (Algolia)
  - Public ATS board APIs: Greenhouse, Lever, Ashby, SmartRecruiters, Recruitee
    (direct company career pages = the chosen 4th source)

LinkedIn / Indeed / Glassdoor are NOT here: they need login and are handled by
the Week-2 browser-assist layer (see INTEGRATIONS.md for the safety playbook).

Config: config/settings.json -> sources_registry (enabled flag + seed companies
per ATS). Health: out/source_health.json after every run.

Output: out/jobs_raw_<date>.json, one dict per job:
  {id, source, title, company, location, remote, url, date, salary_min, salary_max, text}
"""
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
SETTINGS = json.loads((ROOT / "config" / "settings.json").read_text(encoding="utf-8"))

UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")}
TIMEOUT = 30


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def get_json(url: str):
    return json.loads(http_get(url).decode("utf-8", "replace"))


def strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return html.unescape(re.sub(r"\s+", " ", s)).strip()


def mkid(source: str, key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", f"{source}-{key}".lower()).strip("-")[:90]


def job(source, key, title, company, location="", url="", date_str="",
        text="", remote=None, salary_min=None, salary_max=None):
    if not title:
        return None
    if remote is None:
        remote = bool(re.search(r"\bremote\b", f"{location} {title}".lower()))
    return {
        "id": mkid(source, key),
        "source": source,
        "title": title.strip(),
        "company": (company or "").strip(),
        "location": (location or "").strip(),
        "remote": remote,
        "url": url,
        "date": str(date_str or ""),
        "salary_min": salary_min,
        "salary_max": salary_max,
        "text": (text or "")[:4000],
    }


# ------------------------------------------------- official job-board APIs
def collect_hn():
    """Latest 'Ask HN: Who is hiring?' thread. Each comment = one company post."""
    q = urllib.parse.quote('"Ask HN: Who is hiring?"')
    hits = get_json(f"https://hn.algolia.com/api/v1/search_by_date?tags=story&query={q}&hitsPerPage=5")["hits"]
    hit = next((h for h in hits if "who is hiring" in h["title"].lower()), None)
    if not hit:
        return []
    month = hit["title"].replace("Ask HN: Who is hiring?", "").strip(" ()")
    comments = get_json(
        f"https://hn.algolia.com/api/v1/search_by_date?tags=comment,story_{hit['objectID']}&hitsPerPage=400"
    )["hits"]
    out = []
    for c in comments:
        text = strip_html(c.get("comment_text") or "")
        if len(text) < 40:
            continue
        first = re.split(r"[|:\n]", text, maxsplit=1)[0]
        company = first.strip()[:60] if 2 < len(first.strip()) <= 60 else (c.get("author") or "")
        out.append(job("hn_whos_hiring", f"{hit['objectID']}-{c.get('objectID')}",
                       f"Who's Hiring post - {month}", company,
                       url=f"https://news.ycombinator.com/item?id={c['objectID']}",
                       date_str=month, text=text))
    return out


def collect_remoteok():
    data = get_json("https://remoteok.com/api")
    out = []
    for row in data:
        if not isinstance(row, dict) or not row.get("position"):
            continue  # first array element is a legal notice
        tags = ", ".join(row.get("tags") or [])
        out.append(job("remoteok", row.get("slug") or row.get("id"), row["position"],
                       row.get("company"), location=row.get("location") or "Remote",
                       url=row.get("url") or f"https://remoteok.com/remote-jobs/{row.get('slug')}",
                       date_str=row.get("date"),
                       text=f"{row.get('position')} | {tags} | {strip_html(row.get('description') or '')}",
                       remote=True,
                       salary_min=row.get("salary_min") or None,
                       salary_max=row.get("salary_max") or None))
    return out


def collect_wwr():
    cats = ["remote-full-stack-programming-jobs",
            "remote-back-end-programming-jobs",
            "remote-front-end-programming-jobs"]
    out = []
    for cat in cats:
        try:
            root = ET.fromstring(http_get(f"https://weworkremotely.com/categories/{cat}.rss"))
        except Exception as e:
            print(f"  ! weworkremotely/{cat}: {e}")
            continue
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = strip_html(item.findtext("description") or "")
            company, _, role = title.partition(":")
            out.append(job("weworkremotely", link or title, role.strip() or title,
                           company.strip(), location="Remote", url=link,
                           date_str=item.findtext("pubDate") or "",
                           text=f"{title} | {desc}", remote=True))
    return out


def collect_remotive():
    data = get_json("https://remotive.com/api/remote-jobs?limit=60")["jobs"]
    return [job("remotive", r.get("id"), r.get("title"), r.get("company_name"),
                location=r.get("candidate_required_location") or "Remote",
                url=r.get("url"), date_str=r.get("publication_date"),
                text=f"{r.get('title')} | {r.get('category') or ''} | {r.get('salary') or ''} | "
                     f"{' '.join(r.get('tags') or [])} | {strip_html(r.get('description') or '')[:2500]}",
                remote=True)
           for r in data]


def collect_jobicy():
    data = get_json("https://jobicy.com/api/v2/remote-jobs?count=50")["jobs"]
    return [job("jobicy", r.get("id"), r.get("jobTitle"), r.get("companyName"),
                location=r.get("jobGeo") or "Remote",
                url=r.get("url"), date_str=r.get("pubDate"),
                text=f"{r.get('jobTitle')} | {r.get('jobLevel') or ''} | "
                     f"{' '.join(r.get('jobIndustry') or [])} | {strip_html(r.get('jobExcerpt') or '')}",
                remote=True)
           for r in data]


def collect_arbeitnow():
    data = get_json("https://www.arbeitnow.com/api/job-board-api")["data"]
    return [job("arbeitnow", r.get("slug"), r.get("title"), r.get("company_name"),
                location=r.get("location") or "",
                url=r.get("url"), date_str=r.get("created_at"),
                text=f"{r.get('title')} | {' '.join(r.get('tags') or [])} | "
                     f"{strip_html(r.get('description') or '')[:2000]}",
                remote=r.get("remote"))
           for r in data]


def collect_himalayas():
    data = get_json("https://himalayas.app/jobs/api?limit=50")["jobs"]
    out = []
    for r in data:
        loc = ", ".join(r.get("location_restrictions") or []) or "Remote"
        out.append(job("himalayas", r.get("id"), r.get("title"), r.get("company_name"),
                       location=loc,
                       url=r.get("application_link") or r.get("guid") or r.get("url"),
                       date_str=r.get("pubDate"),
                       text=f"{r.get('title')} | {' '.join(r.get('seniority') or [])} | "
                            f"{strip_html(r.get('description') or '')[:2000]}",
                       remote=True))
    return out


def collect_wats():
    """Y Combinator 'Work at a Startup' - the startup source. Jobs are embedded
    in the page's Inertia data-page JSON (server-rendered, 30 per fetch)."""
    req = urllib.request.Request(
        "https://www.workatastartup.com/jobs",
        headers={**UA, "Accept": "text/html,application/xhtml+xml"})
    raw = urllib.request.urlopen(req, timeout=TIMEOUT).read().decode("utf-8", "replace")
    m = re.search(r'data-page="([^"]+)"', raw)
    if not m:
        return []
    import html as _html
    data = json.loads(_html.unescape(m.group(1)))
    out = []
    for r in data.get("props", {}).get("jobs", []):
        slug = r.get("companySlug") or "company"
        sal = (r.get("salary") or "").replace("\u2013", "-")
        smin = smax = None
        ms = re.search(r"\$(\d+)\s*k?\s*-\s*\$?(\d+)\s*k?", sal, re.I)
        if ms:
            scale = lambda v: int(v) * 1000 if int(v) < 10000 else int(v)
            smin, smax = scale(ms.group(1)), scale(ms.group(2))
        loc = r.get("location") or ""
        out.append(job("wats", r.get("id"), r.get("title"), r.get("companyName"),
                       location=loc,
                       url=f"https://www.workatastartup.com/companies/{slug}/jobs/{r.get('id')}",
                       date_str=r.get("companyLastActiveAt") or "",
                       text=f"{r.get('title')} | {r.get('jobType') or ''} | {r.get('roleType') or ''} | "
                            f"YC {r.get('companyBatch') or ''} | {r.get('companyOneLiner') or ''} | "
                            f"{loc} | {sal}",
                       remote="remote" in (loc or "").lower() or "remote" in sal.lower(),
                       salary_min=smin, salary_max=smax))
    return out


# ----------------------------------------------- key-unlocked aggregators
# Each of these self-disables until its API key appears in the environment.
# Keys come from .env locally or GitHub Secrets in CI - never the repo.

def _collect_adzuna():
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        print("  - adzuna: no ADZUNA_APP_ID/KEY in env - skipped")
        return []
    out = []
    # NOTE: Adzuna has NO Pakistan coverage (UNSUPPORTED_COUNTRY) - supported:
    # at au be br ca ch de es fr gb in it mx nl nz pl sg us za
    # in = nearest Asian market (many India-remote roles); us = USD remote market
    for country, what in (("in", "mern stack developer"),
                          ("in", "full stack developer"),
                          ("us", "mern developer remote")):
        u = (f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
             f"?app_id={app_id}&app_key={app_key}&results_per_page=50"
             f"&what={urllib.parse.quote(what)}&content-type=application/json")
        try:
            for r in get_json(u).get("results", []):
                out.append(job(f"adzuna_{country}", r.get("id"), r.get("title"),
                               (r.get("company") or {}).get("display_name", ""),
                               location=r.get("location") or country.upper(),
                               url=r.get("redirect_url") or "",
                               date_str=r.get("created") or "",
                               text=f"{r.get('title')} | {strip_html(r.get('description') or '')[:2200]}",
                               remote="remote" in (r.get("description") or "").lower()[:500].lower(),
                               salary_min=r.get("salary_min"), salary_max=r.get("salary_max")))
        except Exception as e:
            print(f"  ! adzuna/{country}: {e}")
    return out


def _collect_jooble():
    key = os.environ.get("JOOBLE_API_KEY")
    if not key:
        print("  - jooble: no JOOBLE_API_KEY in env - skipped")
        return []
    out = []
    for kw in ("full stack developer", "react developer", "node js developer"):
        try:
            req = urllib.request.Request(
                f"https://jooble.org/api/{key}",
                data=json.dumps({"keywords": kw, "location": "Pakistan", "page": 1}).encode(),
                headers={"Content-Type": "application/json"})
            data = json.loads(urllib.request.urlopen(req, timeout=TIMEOUT).read().decode())
        except Exception as e:
            print(f"  ! jooble: {e}")
            continue
        for r in data.get("jobs", []):
            out.append(job("jooble", r.get("id") or r.get("link"), r.get("title"),
                           r.get("company", ""),
                           location=r.get("location") or "Pakistan",
                           url=r.get("link") or "",
                           date_str=r.get("updated") or "",
                           text=f"{r.get('title')} | {r.get('snippet') or ''} | {r.get('salary') or ''}"))
    return out


def _collect_themuse():
    base = "https://www.themuse.com/api/public/jobs?page=1"
    key = os.environ.get("THEMUSE_API_KEY")
    if key:
        base += f"&api_key={key}"  # optional: raises rate limits
    try:
        data = get_json(base)
    except Exception as e:
        print(f"  ! themuse: {e}")
        return []
    out = []
    for r in data.get("results", []):
        loc = ", ".join(f"{l.get('name')}" for l in (r.get("locations") or []))
        out.append(job("themuse", r.get("id"), r.get("name"), (r.get("company") or {}).get("name", ""),
                       location=loc or "Remote",
                       url=r.get("refs", {}).get("landing_page", ""),
                       date_str=r.get("publication_date") or "",
                       text=f"{r.get('name')} | {strip_html(r.get('contents') or '')[:2000]}"))
    return out


def _collect_jsearch():
    key = os.environ.get("JSEARCH_API_KEY")
    if not key:
        print("  - jsearch: no JSEARCH_API_KEY in env - skipped "
              "(this is the safe read-window into LinkedIn/Indeed/Glassdoor/Rozee listings)")
        return []
    out = []
    for q in ("mern stack developer Pakistan",
              "full stack developer remote"):
        try:
            req = urllib.request.Request(
                "https://jsearch.p.rapidapi.com/search-v2?query="
                + urllib.parse.quote(q) + "&num_pages=1",
                headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"})
            payload = json.loads(urllib.request.urlopen(req, timeout=TIMEOUT).read().decode())
        except Exception as e:
            print(f"  ! jsearch: {e}")
            continue
        for r in payload.get("data", {}).get("jobs", []):
            out.append(job("jsearch", r.get("job_id"), r.get("job_title"), r.get("employer_name"),
                           location=r.get("job_location") or r.get("job_country") or "",
                           url=r.get("job_apply_link") or r.get("job_google_link") or "",
                           date_str=r.get("job_posted_at_datetime_utc") or r.get("job_posted_at") or "",
                           text=f"{r.get('job_title')} | {r.get('job_employment_type') or ''} | "
                                f"{strip_html(r.get('job_description') or '')[:2200]}",
                           remote=r.get("job_is_remote"),
                           salary_min=r.get("job_min_salary"), salary_max=r.get("job_max_salary")))
    return out


# ------------------------------------------------- public ATS board APIs
def collect_greenhouse(tokens):
    out = []
    for token in tokens:
        try:
            data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs")
        except Exception as e:
            print(f"  ! greenhouse/{token}: skipped ({e.__class__.__name__})")
            continue
        for j in data.get("jobs", []):
            loc = (j.get("location") or {}).get("name", "")
            out.append(job(f"gh_{token}", j.get("id"), j.get("title"), token,
                           location=loc, url=j.get("absolute_url") or "",
                           date_str=j.get("updated_at") or "",
                           text=f"{j.get('title')} | {loc}"))
    return out


def collect_lever(companies):
    out = []
    for co in companies:
        try:
            data = get_json(f"https://api.lever.co/v0/postings/{co}?mode=json")
        except Exception as e:
            print(f"  ! lever/{co}: skipped ({e.__class__.__name__})")
            continue
        for j in data:
            loc = (j.get("categories") or {}).get("location") or ""
            out.append(job(f"lever_{co}", j.get("id"), j.get("text"), co,
                           location=loc, url=j.get("hostedUrl") or "",
                           date_str=j.get("createdAt") or "",
                           text=f"{j.get('text')} | {loc}"))
    return out


def collect_ashby(orgs):
    out = []
    for org in orgs:
        try:
            data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{org}")
        except Exception as e:
            print(f"  ! ashby/{org}: skipped ({e.__class__.__name__})")
            continue
        for j in data.get("jobs", []):
            loc = j.get("location") or ""
            out.append(job(f"ashby_{org}", j.get("id"), j.get("title"), org,
                           location=loc,
                           url=j.get("jobUrl") or j.get("applyUrl") or f"https://jobs.ashbyhq.com/{org}",
                           date_str=j.get("publishedAt") or "",
                           text=f"{j.get('title')} | {j.get('department') or ''} | {loc} | "
                                f"{strip_html(j.get('descriptionPlain') or '')[:1500]}",
                           remote=j.get("isRemote")))
    return out


def collect_smartrecruiters(companies):
    out = []
    for co in companies:
        try:
            data = get_json(f"https://api.smartrecruiters.com/v1/companies/{co}/postings?limit=100")
        except Exception as e:
            print(f"  ! smartrecruiters/{co}: skipped ({e.__class__.__name__})")
            continue
        for j in data.get("content", []):
            loc = j.get("location") or {}
            loc_s = ", ".join(x for x in (loc.get("city"), loc.get("country")) if x)
            out.append(job(f"sr_{co}", j.get("id"), j.get("name"), co,
                           location=loc_s,
                           url=f"https://jobs.smartrecruiters.com/{co}/{j.get('id')}",
                           date_str=j.get("releasedDate") or "",
                           text=f"{j.get('name')} | {loc_s}",
                           remote=j.get("remote")))
    return out


def collect_recruitee(companies):
    out = []
    for co in companies:
        try:
            data = get_json(f"https://{co}.recruitee.com/api/offers/")
        except Exception as e:
            print(f"  ! recruitee/{co}: skipped ({e.__class__.__name__})")
            continue
        for j in data.get("offers", []):
            out.append(job(f"rt_{co}", j.get("id"), j.get("title"), co,
                           location=j.get("location") or "",
                           url=j.get("careers_url") or j.get("url") or "",
                           date_str=j.get("published_at") or "",
                           text=f"{j.get('title')} | {strip_html(j.get('description') or '')[:1500]}"))
    return out


# ------------------------------------------------- registry runner
def run_registry():
    reg = SETTINGS["sources_registry"]
    jobs, health = [], {}

    def run_source(name, fn):
        if not reg.get(name, {}).get("enabled", False):
            return
        t0 = time.time()
        try:
            items = [j for j in (fn() or []) if j]
            jobs.extend(items)
            health[name] = {"ok": True, "jobs": len(items),
                            "secs": round(time.time() - t0, 1), "error": None}
        except Exception as e:
            health[name] = {"ok": False, "jobs": 0,
                            "secs": round(time.time() - t0, 1), "error": str(e)[:200]}
            print(f"  ! {name}: {e}")

    ats = SETTINGS["sources_registry"]

    run_source("hn_whos_hiring", collect_hn)
    run_source("remoteok", collect_remoteok)
    run_source("weworkremotely", collect_wwr)
    run_source("remotive", collect_remotive)
    run_source("jobicy", collect_jobicy)
    run_source("arbeitnow", collect_arbeitnow)
    run_source("himalayas", collect_himalayas)
    run_source("wats", collect_wats)
    run_source("adzuna", _collect_adzuna)
    run_source("jooble", _collect_jooble)
    run_source("themuse", _collect_themuse)
    run_source("jsearch", _collect_jsearch)
    run_source("greenhouse", lambda: collect_greenhouse(ats["greenhouse"]["seeds"]))
    run_source("lever", lambda: collect_lever(ats["lever"]["seeds"]))
    run_source("ashby", lambda: collect_ashby(ats["ashby"]["seeds"]))
    run_source("smartrecruiters", lambda: collect_smartrecruiters(ats["smartrecruiters"]["seeds"]))
    run_source("recruitee", lambda: collect_recruitee(ats["recruitee"]["seeds"]))

    # Tier-3 safe browser sources (LinkedIn / Indeed / Glassdoor / Wellfound /
    # Rozee) - only when enabled in the registry; Rozee works logged-out,
    # the others need browser/session.py logins
    if any(ats.get(f"{s}_browse", {}).get("enabled")
           for s in ("linkedin", "indeed", "glassdoor", "wellfound", "rozee")):
        try:
            sys.path.insert(0, str(ROOT))
            from browser.browse import run_browser_sources
            bjobs, bhealth = run_browser_sources()
            jobs.extend(bjobs)
            health.update(bhealth)
        except Exception as e:
            print(f"  ! browser layer: {e}")

    return jobs, health


def main():
    OUT.mkdir(exist_ok=True)
    jobs, health = run_registry()

    # dedupe: URL, then company+normalized title (catches cross-posted jobs)
    seen_url, seen_ct, deduped = set(), set(), []
    for j in jobs:
        ct = (re.sub(r"[^a-z0-9]+", "", j["company"].lower()) + "|" +
              re.sub(r"[^a-z0-9]+", "", j["title"].lower()))
        if (j["url"] and j["url"] in seen_url) or ct in seen_ct:
            continue
        if j["url"]:
            seen_url.add(j["url"])
        seen_ct.add(ct)
        deduped.append(j)

    today = date.today().isoformat()
    (OUT / f"jobs_raw_{today}.json").write_text(json.dumps(deduped, indent=1), encoding="utf-8")
    (OUT / "source_health.json").write_text(json.dumps(health, indent=1), encoding="utf-8")

    print(f"\nCollected {len(deduped)} unique jobs -> out/jobs_raw_{today}.json")
    for name, h in health.items():
        status = "ok " if h["ok"] else "ERR"
        print(f"  [{status}] {name:18s} {h['jobs']:5d} jobs  {h['secs']:6.1f}s  {h['error'] or ''}")


if __name__ == "__main__":
    main()
