# MERN Job Application Automation — working system

Status: **FULLY AUTOMATED DAILY FLOW IS INSTALLED.** Every time you log into
Windows, the system runs hidden: collects fresh jobs → scores them against your
profile → tailors your CV for the top 5 → creates **Gmail drafts** for matches
that carry a real employer email (never sends) → logs everything to the tracker.
The only thing not live yet: the one-time Gmail OAuth (below).

## Your rules (baked into config/settings.json)

- **Roles:** MERN / full-stack / frontend / backend / SaaS / AI-automation / vibe-coding
- **Salary:** Pakistan-based jobs need PKR 60,000+/month; USD-based companies need
  $500+/month. Unlisted salary = neutral (job stays in the queue).
- **Experience: NO filter.** Any job in your fields applies — junior, mid, or senior.
- **Safety:** drafts only, never send; no guessed email addresses (jobs without an
  employer email wait for the Week-2 browser-assist layer); CV email is now
  `your.email@gmail.com` on every generated CV.

## The daily flow (automatic at logon)

`Startup\job_automation.vbs` → `run_auto.bat` → `python run_daily.py --auto`:
1. `collector/collect.py` — HN who's-hiring, RemoteOK, WeWorkRemotely, Greenhouse company boards
2. `matcher.py` — scores every job; threshold 70
3. `tailor.py` — top 5 matches get a tailored CV (.md + .docx) in `tailored/`
4. Gmail drafts with the tailored CV attached for matches that include an employer email
5. Everything logged to `tracker.py` (SQLite) and `out/auto_summary_<date>.md`; raw log in `out/auto_log.txt`

Run any piece manually: `python run_daily.py` (report only), `python run_daily.py --auto`,
`python tracker.py list`.

**Assisted apply (apply-URL jobs):** `python browser/apply_queue.py` — walks the
queued jobs one by one: opens the ATS form, auto-fills name/email/phone/links/cover
note from your profile, uploads the tailored CV, and leaves the SUBMIT click to you.
One-time setup for full autofill: real `linkedin_url`/`github_url` in
config/profile.json, and your standard answers in settings → browser_layer.auto_answers. Optional fixed daily time (needs one admin command):
`schtasks /Create /TN "MERN Job Automation" /TR "C:\Users\Revnix\Desktop\personal\automation\run_auto.bat" /SC DAILY /ST 09:00 /F`

## Gmail drafts setup (one time, ~10 min — the ONLY remaining step)

1. https://console.cloud.google.com → create project "job-automation"
2. APIs & Services → Library → enable **Gmail API**
3. OAuth consent screen → External → add `your.email@gmail.com` as test user
4. Credentials → Create credentials → OAuth client ID → **Desktop app** → download JSON
   → save as `credentials.json` in this folder
5. `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib` (already done if I installed it)
6. `python gmail_drafts.py --auth` → browser opens once → `token.json` saved.

From the next auto-run onward, drafts appear in your Gmail automatically. The token
refreshes silently; the scope is `gmail.compose` — this system physically cannot send mail.

## Results so far

- 2026-09-09: first dry run — 2,403 jobs, 15 matches, 5 tailored CVs, tracker rows #1–#5.
- 2026-09-11: **professional upgrade** — 12 live sources (added Remotive, Jobicy,
  Arbeitnow, Himalayas, Ashby, SmartRecruiters boards), registry-driven collector with
  per-source health report (`out/source_health.json`), cross-source dedupe,
  **2,790 jobs/run**, 15 matches. Project is now a git repo.

## Platform strategy — read INTEGRATIONS.md

The full research lives in [INTEGRATIONS.md](INTEGRATIONS.md): all platforms relevant to
your niche in 4 tiers, the login-safety playbook (dedicated browser profile, no passwords
in code, assisted submit, hard stops on CAPTCHA), and the 15-minute free-key registration
checklist (Adzuna/Jooble/TheMuse/JSearch — JSearch gives a *read-only, ToS-safe* window
into LinkedIn/Indeed/Glassdoor/ZipRecruiter listings).

