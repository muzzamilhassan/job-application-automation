#!/usr/bin/env python3
"""Stage 2 - Score collected jobs against the profile.

User rules (2026-09-09):
  * Salary: PKR jobs need 60k+/month; USD companies need $500+/month.
    Unlisted salary = neutral (job stays in queue).
  * Experience: NO filter - any job in the target fields applies, junior to senior.

Dry-run scorer: pure Python, no API key needed. An LLM re-score can be layered
later without changing the interface: score(job) -> (int, [reasons]).
"""
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
SETTINGS = json.loads((ROOT / "config" / "settings.json").read_text(encoding="utf-8"))

ROLE_STRONG = ["mern", "pern", "full stack", "full-stack", "fullstack",
               "front end", "front-end", "frontend",
               "back end", "back-end", "backend",
               "react", "next.js", "nextjs", "node", "node.js",
               "javascript", "typescript", "web developer",
               "software engineer", "software developer", "developer",
               "saas", "postgres", "postgresql", "mysql", "sqlite"]
AI_WORDS = ["ai", "a.i.", "langchain", "langgraph", "openai", "llm", "gpt",
            "automation", "agent", "copilot", "vibe cod", "ai-native",
            "artificial intelligence", "machine learning"]
STACK_WORDS = ["express", "nestjs", "nest.js", "mongodb", "sql", "drizzle",
               "supabase", "firebase", "tailwind", "stripe", "rest api",
               "graphql", "aws", "docker", "cms"]
SENIORITY = ["senior", "sr.", "lead", "principal", "staff", "junior", "jr.",
             "entry level", "entry-level", "intern", "mid-level", "mid level"]

SAL = SETTINGS["salary"]
PKR_FLOOR_PK = SAL["pkr_monthly_min"]           # Pakistan companies
PKR_FLOOR_FOREIGN = SAL["foreign_pkr_monthly_min"]  # foreign companies, PKR-equivalent
# approx monthly FX to PKR (edit here when rates move meaningfully)
FX_TO_PKR = {"USD": 278.0, "EUR": 300.0, "GBP": 330.0, "INR": 3.35}
PK_MARKERS = ["pakistan", "islamabad", "karachi", "lahore", "rawalpindi",
              "faisalabad", "multan", "peshawar", "hyderabad, pk", "gujranwala"]


def _hits(words, blob):
    if any(w.startswith(" ") or w.endswith(" ") for w in words):
        return [w for w in words if re.search(rf"(?<![a-z]){re.escape(w.strip())}(?![a-z])", blob)]
    return [w for w in words if w in blob]


def salary_monthly(j):
    """Normalize a posting's salary to (monthly_amount, currency, note) or None."""
    sal = j.get("salary_max") or j.get("salary_min")
    if sal:  # source field (RemoteOK) = USD per year
        return (sal / 12.0, "USD", "listed yearly")
    t = (j.get("text") or "").lower()
    m = re.search(r"pkr\s?([\d,]+)\s?(k)?", t) or re.search(r"([\d,]+)\s?(k)?\s?pkr", t)
    if m:
        val = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
        return (val, "PKR", "in text")
    m = re.search(r"\$\s?([\d,]+)\s?(k)?\s*(?:/|per\s+)?\s*(month|mo\b|yr\b|year|annum)?", t)
    if m:
        val = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
        period = m.group(3)
        if period in ("month", "mo"):
            return (val, "USD", "monthly in text")
        if period in ("yr", "year", "annum"):
            return (val / 12.0, "USD", "yearly in text")
        if val >= 10000:  # bare $ amount heuristic
            return (val / 12.0, "USD", "assumed yearly")
        return (val, "USD", "assumed monthly")
    return None


def score(j):
    title = (j.get("title") or "").lower()
    text = (j.get("text") or "").lower()
    blob = title + " \n " + text
    why, s = [], 0

    t_hits = _hits(ROLE_STRONG, title)
    b_hits = [w for w in _hits(ROLE_STRONG, text) if w not in t_hits]
    s += min(45, 15 * len(t_hits)) + min(15, 3 * len(b_hits))
    if t_hits:
        why.append("role in title: " + ", ".join(sorted(set(t_hits))[:6]))

    ai_hits = _hits(AI_WORDS, blob)
    s += min(20, 7 * len(ai_hits))
    if ai_hits:
        why.append("AI/automation: " + ", ".join(sorted(set(ai_hits))[:6]))

    stack_hits = _hits(STACK_WORDS, blob)
    s += min(15, 3 * len(stack_hits))
    if stack_hits:
        why.append("stack: " + ", ".join(sorted(set(stack_hits))[:8]))

    if j.get("remote"):
        s += 10; why.append("remote")
    else:
        s += 5; why.append("on-site ok")

    info = salary_monthly(j)
    if info:
        amount, cur, note = info
        is_pk = cur == "PKR" or any(m in (j.get("location") or "").lower() + " " + text
                                    for m in PK_MARKERS)
        floor = PKR_FLOOR_PK if is_pk else PKR_FLOOR_FOREIGN
        amount_pkr = amount if cur == "PKR" else amount * FX_TO_PKR.get(cur, 278.0)
        if amount_pkr >= floor:
            s += 10
            why.append(f"salary ~{amount:,.0f} {cur}/mo (~{amount_pkr:,.0f} PKR) >= floor {floor:,} ({note})")
        else:
            s -= 5
            why.append(f"salary ~{amount:,.0f} {cur}/mo (~{amount_pkr:,.0f} PKR) below {floor:,} floor ({note})")
    else:
        s += 5; why.append("salary unlisted (neutral)")

    seniority = [w for w in SENIORITY if w in title]
    if seniority:
        why.append(f"seniority '{seniority[0]}' - no filter applied per your rule")

    return max(0, min(100, s)), why


def main():
    files = sorted(OUT.glob("jobs_raw_*.json"))
    if not files:
        raise SystemExit("No jobs_raw_*.json found - run collector/collect.py first.")
    jobs = json.loads(files[-1].read_text(encoding="utf-8"))

    threshold = SETTINGS["matching"]["threshold"]
    scored = []
    for j in jobs:
        s, why = score(j)
        scored.append(dict(j, score=s, reasons=why))
    scored.sort(key=lambda x: (-x["score"], x["company"]))

    matches = [j for j in scored if j["score"] >= threshold]
    today = date.today().isoformat()
    (OUT / f"matches_{today}.json").write_text(json.dumps(matches, indent=1), encoding="utf-8")

    lines = [f"# Dry-run match report - {today}", "",
             f"Collected: {len(jobs)} | Above threshold ({threshold}): {len(matches)}", "",
             "Rules: experience ignored | PK companies PKR 70k+/mo, foreign PKR 100k+/mo equiv, unlisted = neutral", ""]
    for j in matches[:40]:
        lines.append(f"## [{j['score']}] {j['title']} - {j['company']} ({j['source']})")
        lines.append(f"- Location: {j['location'] or '-'} | Remote: {j['remote']}")
        if j["url"]:
            lines.append(f"- Apply: {j['url']}")
        lines.append(f"- Why: {'; '.join(j['reasons'])}")
        lines.append("")
    (OUT / f"dry_run_report_{today}.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"Scored {len(scored)} jobs | {len(matches)} above threshold {threshold}")
    print(f"  -> out/matches_{today}.json")
    print("\nTop 10:")
    for j in matches[:10]:
        print(f"  [{j['score']:3d}] {j['title'][:60]:60s} | {j['company'][:25]:25s} | {j['source']}")


if __name__ == "__main__":
    main()
