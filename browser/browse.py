"""READ-ONLY job listing browse for LinkedIn / Indeed / Glassdoor.

Safety rules enforced here (settings.browser_layer):
  * read-only: search pages only, never clicks Apply
  * max_pages_per_site / max_listings_per_site caps
  * randomized human pauses between every action
  * refuses to run outside operating hours
  * refuses to run when a CAPTCHA/security wall is detected
  * refuses to run when the site session is not logged in

These collectors are slower (minutes) than the API sources, so run_daily only
calls them when the matching sources_registry entries are enabled.
"""
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_core import SAFETY, human_pause, detect_block  # noqa: E402
from session import session_ok  # noqa: E402


def _norm(source, key, title, company, location, url, text=""):
    if not title:
        return None
    remote = bool(re.search(r"\bremote\b", f"{location} {title}".lower()))
    return {"id": re.sub(r"[^a-z0-9]+", "-", f"{source}-{key}".lower())[:90],
            "source": source, "title": title.strip(), "company": (company or "").strip(),
            "location": (location or "").strip(), "remote": remote, "url": url,
            "date": str(int(time.time())), "salary_min": None, "salary_max": None,
            "text": (text or "")[:3000]}


def _first_text(el, selectors, attr=None):
    for sel in selectors:
        try:
            sub = el.find_element("css selector", sel)
            return (sub.get_attribute(attr) if attr else sub.text).strip()
        except Exception:
            continue
    return ""


# ------------------------------------------------------------------ linkedin
def collect_linkedin(driver):
    kw = SAFETY["search_keywords"][0]
    out, page = [], 1
    while page <= SAFETY["max_pages_per_site"]:
        url = (f"https://www.linkedin.com/jobs/search/?keywords={quote(kw)}"
               f"&f_WT=2&position={page}&pageNum={page}")
        driver.get(url)
        human_pause(6, 12)
        block = detect_block(driver)
        if block:
            print(f"  ! linkedin: security wall detected ({block}) - stopping, nothing touched")
            break
        cards = driver.find_elements("css selector",
                                     "ul.jobs-search__results-list li, .base-card")
        if not cards:
            break
        for c in cards[:SAFETY["max_listings_per_site"]]:
            title = _first_text(c, ["h3.base-search-card__title", "h3"])
            company = _first_text(c, ["h4.base-search-card__subtitle", "h4"])
            loc = _first_text(c, [".job-search-card__location", ".job-search-card__list-footer"])
            link = _first_text(c, ["a.base-card__full-link", "a"], attr="href")
            out.append(_norm("linkedin_browse", link or title, title, company, loc, link))
        page += 1
        human_pause()
    return [j for j in out if j]


# ------------------------------------------------------------------- indeed
def collect_indeed(driver):
    kw = SAFETY["search_keywords"][0]
    out, page = [], 0
    while page < SAFETY["max_pages_per_site"]:
        url = f"https://www.indeed.com/jobs?q={quote(kw)}&l=Remote&fromage=3&start={page * 10}"
        driver.get(url)
        human_pause(6, 12)
        block = detect_block(driver)
        if block:
            print(f"  ! indeed: security wall detected ({block}) - stopping, nothing touched")
            break
        cards = driver.find_elements("css selector", "div.job_seen_beacon")
        if not cards:
            break
        for c in cards[:SAFETY["max_listings_per_site"]]:
            title = _first_text(c, ["h2.jobTitle span", "h2.jobTitle", "[data-testid='jobTitle']"])
            company = _first_text(c, ["span.companyName", "[data-testid='company-name']"])
            loc = _first_text(c, ["div.companyLocation", "[data-testid='text-location']"])
            link = _first_text(c, ["h2 a", "a.jcs-JobTitle"], attr="href")
            if link and link.startswith("/"):
                link = "https://www.indeed.com" + link
            out.append(_norm("indeed_browse", link or title, title, company, loc, link))
        page += 1
        human_pause()
    return [j for j in out if j]


# ---------------------------------------------------------------- glassdoor
def collect_glassdoor(driver):
    kw = SAFETY["search_keywords"][0]
    out = []
    url = f"https://www.glassdoor.com/Job/index.htm?sc.keyword={quote(kw)}"
    driver.get(url)
    human_pause(6, 12)
    block = detect_block(driver)
    if block:
        print(f"  ! glassdoor: security wall detected ({block}) - stopping, nothing touched")
        return []
    cards = driver.find_elements("css selector",
                                 "li[data-test='jobListing'], li.react-job-listing")
    for c in cards[:SAFETY["max_listings_per_site"]]:
        title = _first_text(c, ["[data-test='job-title']", "a.jobLink", "h2"])
        company = _first_text(c, ["[data-test='employer-name']", "a.jobLink span", ".employer-name"])
        loc = _first_text(c, ["[data-test='emp-location']", ".loc"])
        link = _first_text(c, ["a.jobLink", "a"], attr="href")
        if link and link.startswith("/"):
            link = "https://www.glassdoor.com" + link
        out.append(_norm("glassdoor_browse", link or title, title, company, loc, link))
    return [j for j in out if j]


# ---------------------------------------------------------------- wellfound
_WF_CARD_JS = """
() => {
  const out = [];
  const seen = new Set();
  document.querySelectorAll('a[href^="/jobs/"]').forEach(a => {
    const href = a.getAttribute('href');
    if (!/^\\/jobs\\/\\d+/.test(href) || seen.has(href)) return;
    // walk up to the smallest ancestor that holds a company link and a button
    let el = a, card = null;
    for (let i = 0; i < 6 && el; i++) {
      el = el.parentElement;
      if (!el) break;
      if (el.querySelector('a[href^="/company/"]') && el.querySelector('button')) { card = el; break; }
    }
    if (!card) card = a.parentElement;
    const coLink = card.querySelector('a[href^="/company/"]');
    const title = (a.innerText || '').trim();
    if (!title) return;
    seen.add(href);
    out.push({
      title: title.split('\\n')[0],
      url: location.origin + href,
      company: coLink ? (coLink.innerText || '').trim().split('\\n')[0] : '',
      meta: (card.innerText || '').replace(/\\s+/g, ' ').slice(0, 400),
    });
  });
  return out;
}
"""


def collect_wellfound(driver):
    """Role browse on Wellfound. Read-only; no Apply clicks. Salary in card
    meta ('Remote only • Europe • $80k – $100k') is parsed as annual USD."""
    role_slugs = []
    for kw in SAFETY["search_keywords"]:
        slug = re.sub(r"[^a-z0-9]+", "-", kw.lower()).strip("-")
        if slug and slug not in role_slugs:
            role_slugs.append(slug)
    out = []
    for slug in role_slugs[:3]:  # cap attempts per run
        driver.get(f"https://wellfound.com/role/r/{slug}")
        human_pause(6, 12)
        if detect_block(driver):
            print(f"  ! wellfound: security wall on {slug} - stopping, nothing touched")
            break
        try:
            cards = driver.execute_script(_WF_CARD_JS) or []
        except Exception:
            continue  # bad role slug / empty page -> next keyword
        for c in cards[:SAFETY["max_listings_per_site"]]:
            meta = c.get("meta") or ""
            remote = "remote" in meta.lower()
            smin = smax = None
            m = re.search(r"\$(\d+)\s*[kK]?\s*[–-]\s*\$?(\d+)\s*[kK]?", meta)
            if m:
                scale = lambda v: int(v) * 1000 if int(v) < 10000 else int(v)
                smin, smax = scale(m.group(1)), scale(m.group(2))
            j = _norm("wellfound", c["url"], c["title"], c.get("company") or "",
                      "Remote" if remote else "", c["url"], text=meta)
            j.update(salary_min=smin, salary_max=smax, remote=remote)
            out.append(j)
        if len(out) >= SAFETY["max_listings_per_site"]:
            break
    return out[:SAFETY["max_listings_per_site"]]


# -------------------------------------------------------------------- rozee
# Rozee.pk = Pakistan's #1 job board. Search results load via AJAX; listings
# work logged-out, so no session check is needed for this source.
ROZEE_CARD_JS = """
() => {
  const out = [];
  const seen = new Set();
  document.querySelectorAll('a[href*="-jobs-"]').forEach(a => {
    const href = a.getAttribute('href') || '';
    const m = href.match(/-jobs-(\\d+)/);
    if (!m || seen.has(m[1])) return;
    const title = (a.innerText || '').trim();
    if (!title) return;
    seen.add(m[1]);
    let el = a, company = '', meta = '';
    for (let i = 0; i < 5 && el; i++) {
      el = el.parentElement;
      if (!el) break;
      const co = Array.from(el.querySelectorAll('a')).find(x =>
        /javascript:;|^#$/.test(x.getAttribute('href') || '') &&
        (x.innerText || '').trim().length > 2);
      if (co) { company = co.innerText.trim().replace(/,\\s*$/, ''); break; }
    }
    let card = a.closest('li, article, div');
    meta = card ? (card.innerText || '').replace(/\\s+/g, ' ').slice(0, 300) : '';
    const clean = 'https://www.rozee.pk' + href.replace(/^\\s*\\/\\//, '/').replace(/^https?:\\/\\/[^/]*$/, '');
    const url = href.startsWith('//') ? 'https:' + href
              : href.startsWith('http') ? href
              : 'https://www.rozee.pk' + (href.startsWith('/') ? href : '/' + href);
    out.push({ title, id: m[1], url, company, meta });
  });
  return out;
}
"""


def collect_rozee(driver):
    """Read-only Rozee search browse. No login, no Apply clicks.
    Warms up on the homepage first - Rozee's invisible check challenges
    cold first-visits to the search URL."""
    driver.get("https://www.rozee.pk/")
    human_pause(6, 10)
    if detect_block(driver):
        print("  ! rozee: security wall on homepage - stopping, nothing touched")
        return []
    out = []
    for kw in SAFETY["search_keywords"][:3]:
        url = f"https://www.rozee.pk/job/jsearch/q/{quote(kw)}"
        driver.get(url)
        human_pause(8, 14)  # extra pause: AJAX results load after page load
        block = detect_block(driver)
        if block:
            print(f"  ! rozee: security wall detected ({block}) - stopping, nothing touched")
            break
        try:
            cards = driver.execute_script(ROZEE_CARD_JS) or []
        except Exception:
            continue
        for c in cards[:SAFETY["max_listings_per_site"]]:
            j = _norm("rozee", c["id"], c["title"], c.get("company") or "",
                      c.get("meta", "")[:80], c["url"], text=c.get("meta", ""))
            j["remote"] = "remote" in c.get("meta", "").lower()
            out.append(j)
        if len(out) >= SAFETY["max_listings_per_site"]:
            break
    return out[:SAFETY["max_listings_per_site"]]


COLLECTORS = {"linkedin": collect_linkedin, "indeed": collect_indeed,
              "glassdoor": collect_glassdoor, "wellfound": collect_wellfound,
              "rozee": collect_rozee}
# sources that work without any login (read-only)
NO_LOGIN_REQUIRED = {"rozee"}


def run_browser_sources() -> tuple[list[dict], dict]:
    """Run every enabled *_browse source. Returns (jobs, health-entries)."""
    from browser_core import make_driver
    settings = __import__("json").loads(
        (Path(__file__).resolve().parents[1] / "config" / "settings.json").read_text(encoding="utf-8"))
    reg = settings["sources_registry"]
    enabled = [s for s in COLLECTORS if reg.get(f"{s}_browse", {}).get("enabled")]
    jobs, health = [], {}
    if not enabled:
        return jobs, health
    if not SAFETY["assisted_submit_only"]:
        print("  ! browser layer disabled by safety config"); return jobs, health

    driver = make_driver(headless=False)  # always headed: human-visible, less bot-like
    try:
        for site in enabled:
            name = f"{site}_browse"
            if site not in NO_LOGIN_REQUIRED and not session_ok(driver, site):
                health[name] = {"ok": False, "jobs": 0, "secs": 0,
                                "error": "not logged in - run: python browser/session.py --login " + site}
                continue
            t0 = time.time()
            try:
                found = COLLECTORS[site](driver)
                jobs.extend(found)
                health[name] = {"ok": True, "jobs": len(found),
                                "secs": round(time.time() - t0, 1), "error": None}
            except Exception as e:
                health[name] = {"ok": False, "jobs": 0,
                                "secs": round(time.time() - t0, 1), "error": str(e)[:200]}
    finally:
        driver.quit()
    return jobs, health


if __name__ == "__main__":
    js, hs = run_browser_sources()
    for k, v in hs.items():
        print(k, "->", v)
    print(f"{len(js)} listings")
