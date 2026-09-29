# INTEGRATIONS.md — Platform Matrix & Safety Playbook
Research date: 2026-09-09 · Niche: MERN / Next.js / full-stack / AI-automation · Base: Islamabad (remote-first, USD $500+/mo or PKR 60k+/mo)

## The four tiers

### Tier 1 — LIVE NOW: official APIs, no login, no risk
The system already collects from these every day. Verified live 2026-09-09.

| Platform | Integration | Notes |
|---|---|---|
| Hacker News who's-hiring | public Algolia API | AI/startup heavy, often includes emails → drafts |
| RemoteOK | official public API | salary fields included |
| WeWorkRemotely | official RSS | top matches so far |
| **Remotive** | official public API | small but high quality |
| **Jobicy** | official public API (no key) | tech/design remote |
| **Arbeitnow** | official public API (no key) | ~250 jobs/run, EU-heavy |
| **Himalayas** | official public API | seniority tags |
| Greenhouse boards | public API per company | seeds: Vercel, Stripe, Datadog, Cloudflare, Figma, Airbnb |
| **Ashby boards** | public API per company | seeds: Linear, Ramp, Ashby |
| Lever boards | public API per company | seed: Duffel (add more) |
| **SmartRecruiters** | public API per company | seed: Gameloft (Spotify exposes 0) |

Dead/wrong tokens documented in `config/settings.json` → `sources_registry.*.known_bad` (openai, notion greenhouse tokens; supabase/netlify/linear lever tokens).

### Tier 2 — 15 MIN EACH: official/free-key APIs (register once, paste key into `.env`)
These stay read-only and legitimate — including a safe *window* into the big boards.

| Platform | What it gives you | Free tier | Get key |
|---|---|---|---|
| **Adzuna** | aggregator incl. **Pakistan** (`country=pk`) | free key, instant | developer.adzuna.com |
| **Jooble** | aggregator, covers Pakistan | free key (short form) | jooble.org/api/about |
| **TheMuse** | tech jobs + company profiles | free key, 3,600 req/hr | themuse.com/developers/api/v2 |
| **JSearch (OpenWeb Ninja)** | **read-only view of LinkedIn, Indeed, Glassdoor, ZipRecruiter via Google Jobs** | ~200 calls/mo, no card | openwebninja.com/api/jsearch |
| SerpApi Google Jobs | same idea, Google Jobs directly | ~100–250 searches/mo | serpapi.com |
| TheirStack | job postings intelligence | 200 credits/mo | theirstack.com |

**Why JSearch matters:** it answers "what about LinkedIn/Indeed/Glassdoor jobs?" *without* touching their terms of service — we read what Google Jobs already indexes. Scraping those sites directly is the risky part; reading an aggregator's licensed feed is not.

### Tier 3 — LOGIN REQUIRED → **BUILT, safe-assisted mode**
LinkedIn · Indeed+Glassdoor (one login since 2026 merger) · Wellfound (BUILT 2026-09-18, role-browse with salary parsing) · ZipRecruiter · Rozee.pk (no API; Pakistan's #1 board)

**The layer is coded and smoke-tested** (`browser/` package, Selenium + your real Chrome):
- `browser/session.py --login all` — one-time: opens each site, YOU type your login + 2FA, session saved to `browser/chrome_profile/` (gitignored; passwords never touch code). `--check` verifies sessions any time.
- `browser/browse.py` — read-only listing browse per site: caps (2 pages / 25 listings), random 5–12 s pauses, refuses to run outside 09:00–20:00, aborts on any CAPTCHA/security wall, refuses to run when not logged in.
- `browser/apply_assist.py <site> <url>` — assisted apply: opens the form, checks walls, maps fields, and hands the submit click to YOU (v1). v2 auto-fill is tuned together on live forms, still stopping at submit.
- Flipping them on: log in once, then set `linkedin_browse` / `indeed_browse` / `glassdoor_browse` to `"enabled": true` in `sources_registry` — the daily collector picks them up automatically.

### Tier 4 — APPLY-ONCE MARKETPLACES (highest leverage for a Pakistani MERN dev)
Apply once, get matched for months. The system treats these as *priority* applications.

| Platform | Why for you | Path |
|---|---|---|
| **Turing.com** | dedicated "Remote Jobs in Pakistan" page, USD pay, hires Pakistani devs actively | turing.com/jobs — browser-assist |
| **Arc.dev** | AI-matched remote dev roles, freelance + full-time | arc.dev — browser-assist |
| **Braintrust** | zero-fee talent network, 1,000+ companies | usebraintrust.com — browser-assist |
| **Wellfound** | startup roles, strong AI-startup density | wellfound.com — browser-assist |
| Toptal | highest pay, but 3–8 week vetting, top-3% bar | optional, your call |

## Login-safety playbook (how logins are handled — the professional way)

1. **No password ever touches code or config.** We use a *dedicated Chrome profile* (Playwright persistent context). You log in to each site **once, yourself, in that browser window**. The system reuses that session for as long as the site keeps it — typically weeks.
2. **2FA mandatory** on LinkedIn/Indeed/Wellfound before we enable the browser layer.
3. **Assisted by default:** the system opens the application, fills every field, attaches the tailored CV — and stops at the submit button for you. Full-auto submit only after you explicitly opt in, capped (≤15/day, randomized 3–25 min delays, only 09:00–20:00 PKT).
4. **Hard stops:** CAPTCHA, security challenge, unusual questionnaire → everything pauses, the item goes to your review queue, nothing is guessed or brute-forced.
5. **Never automated:** typing passwords, 2FA codes, changing account settings, anything monetary.
6. **Per-site risk budgets:** LinkedIn is treated as the most fragile (ToS bans, aggressive detection) → read-only browse + assisted apply only, low daily cap. Indeed/Glassdoor share one account → one combined cap. Wellfound/ZipRecruiter more relaxed.
7. **Session health checks:** before any browser run, the system verifies each site's session is alive; dead session → it asks you to re-login in the dedicated profile rather than failing silently.

## Scalable architecture (what makes this professional)

```
 sources/ (19 registry entries, adapter per platform, health-checked)
    → normalize to one Job schema
    → dedupe (URL + company/title hash)
    → enrich (full JD fetch for ATS boards)
    → score (keyword now; LLM re-score of borderline jobs when key is set)
    → tailor (per-job CV, .md + .docx, truth-only rules)
    → route:
        a) employer email present  → Gmail DRAFT (never sends)
        b) no email, public apply  → browser-assist queue (Tier 3)
        c) marketplace             → priority queue (Tier 4)
    → SQLite tracker (status per application)
    → follow-up drafts after 7–10 days
```

Already in place: registry-driven sources with per-run health report (`out/source_health.json`), graceful failure per source, dedupe across sources, idempotent daily runs, autostart at logon, secrets in `.env`.
Next upgrades on the path: git history (done), `sources/` package split per platform, LLM scoring via any OpenAI-compatible key (`TAILOR_API_BASE/KEY/MODEL`), local review dashboard, follow-up automation.

## Free-key registration checklist (you, ~15 min total)
1. developer.adzuna.com → register → put `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` in `.env`
2. jooble.org/api/about → form → `JOOBLE_API_KEY`
3. themuse.com/developers/api/v2 → register → `THEMUSE_API_KEY`
4. rapidapi.com → JSearch → `JSEARCH_API_KEY` (optional but recommended — the safe big-board window)

Each key instantly adds a new source: drop it in `.env`, flip `enabled: true` in `sources_registry`, and the next daily run picks it up.
