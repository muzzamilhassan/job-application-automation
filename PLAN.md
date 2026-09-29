# Job Application Automation — Plan

## 1. What this system does (one paragraph)

Every day, the system collects jobs matching your field from multiple sources, scores each one against your profile, tailors your CV to that specific job (without inventing anything), and prepares the application two ways: **email applications become Gmail drafts (never sent automatically)** and **portal applications (LinkedIn Easy Apply / Indeed / Glassdoor / +1) get pre-filled in your logged-in browser with the tailored CV ready to upload**, pausing for you at the final submit step (or at anything unusual like a CAPTCHA). You get a short daily review queue, approve what you like, and everything is tracked in one place with follow-up drafts prepared automatically.

## 2. Honest reality check (from research, Sept 2026)

- **Fully safe / officially supported:** job discovery via public ATS job-board APIs (Greenhouse, Lever, Ashby, Workable, SmartRecruiters — no login needed), official email job alerts, CV tailoring, **Gmail drafts via Gmail API** (`drafts.create` — a first-class feature), tracking, follow-up drafts.
- **Gray area / real risk:** bot-submitting applications on LinkedIn, Indeed, Glassdoor. LinkedIn's User Agreement (updated Nov 3, 2025) explicitly prohibits "bots or other unauthorized automated methods"; documented consequences range from temporary restrictions to permanent bans, and detection has gotten more aggressive. Indeed and Glassdoor merged under one login in 2026 — an account flag on one can affect both.
- **Consequence for design:** the system treats *searching* as low-risk (it mimics what you'd do by hand, read-only, slow, human-paced) and treats *submitting* as the risk point. Default mode = **human-in-the-loop**: the bot fills everything, you click submit. Semi-auto mode is available later with strict daily caps (10–20/day, randomized delays).
- **Existing tools** (for reference): Simplify, Jobright, LazyApply, Sonara. Mass-apply tools report poor callback rates (~500 applications → ~1 interview in one user report). Quality beats quantity — this system is built around tailoring, not volume.

## 3. Pipeline (6 stages)

### Stage 1 — Collect jobs (daily)
1. Public ATS feeds for your target companies (Greenhouse/Lever/Ashby/Workable/SmartRecruiters JSON — legitimate, no auth, freshest listings).
2. Official email job alerts from LinkedIn/Indeed/Glassdoor (they email you matches; the system reads those emails — completely safe).
3. Read-only browsing of LinkedIn/Indeed/Glassdoor search results with your logged-in session, human-paced (gray area, kept minimal).

Deduplicate across all sources (same job posted on 3 sites = 1 entry).

### Stage 2 — Score & filter
An LLM reads each posting against your **master profile** (fields, skills, years, locations, work authorization, salary) and returns a 0–100 match score with reasons. Only jobs above your threshold (e.g., 70) move forward.

### Stage 3 — Tailor CV per job
- One master CV is the source of truth. For each job: reorder/reword bullet points, adjust the summary, mirror the posting's keywords — **never fabricate experience, employers, or dates**.
- Output: tailored PDF/DOCX per job + a short cover letter / application note.

### Stage 4 — Apply
- **Email route:** Gmail API creates a **draft** addressed to the employer with the tailored CV attached. Never sends. (Outlook also possible later via Microsoft Graph drafts.)
- **Portal route:** browser automation (Playwright, persistent profile — you log in once) opens the application, pre-fills every field from your profile, attaches the tailored CV. Hard stops: CAPTCHA, unusual questions, payment/identity steps. Then either (a) assisted — you review and click submit, or (b) semi-auto — it submits, capped at N per day with randomized delays.

### Stage 5 — Your review gate
Each day you get a queue (spreadsheet or simple local dashboard): job link, score, why it matched, the tailored CV, the drafted email. Approve → email gets sent (by you or on approval) / portal app gets submitted. Reject → logged, never re-suggested.

### Stage 6 — Track & follow up
SQLite/spreadsheet tracker: every application, date, status, CV version used. After 7–10 days of silence, it prepares a polite follow-up email **as a draft**.

## 4. Tech stack

- Python 3 + Playwright (persistent Chrome profile)
- Gmail API (OAuth, `gmail.compose` scope — drafts only)
- LLM for matching + CV tailoring
- python-docx + PDF export
- SQLite tracker (or Google Sheet)
- Windows Task Scheduler for the daily run
- `.env` file for credentials — never hard-coded, never shared in chat

## 5. Rules that keep you safe

1. Nothing is ever sent or submitted without passing the review gate (until you explicitly unlock semi-auto).
2. Daily caps: max ~15 applications/day, randomized timing.
3. CV tailoring only reweights truth; fabrication is forbidden in the prompts.
4. Job-site accounts stay yours; automation uses your real logged-in browser profile at human speed.
5. All secrets stay in `.env` on your machine.

## 6. What I need from you (Phase 0)

1. Your CV (PDF/DOCX) placed in this folder
2. Target job titles / fields + keywords
3. Location(s), remote or on-site, work authorization
4. Salary range (for filtering only)
5. Email provider — Gmail assumed (Outlook possible)
6. Choice of the 4th site: ZipRecruiter / Wellfound (startups) / Bayt or Naukrigulf (Gulf) / direct company career pages (recommended — best quality)
7. Review-gate preference: approve everything (safest) vs. auto-apply above a score threshold

## 7. Build order

- **Week 1 (dry run, zero risk):** job collector + matcher + CV tailoring + Gmail drafts. No job-site logins, no applications. You inspect 10 sample tailored applications as drafts.
- **Week 2:** browser automation for Easy Apply / Indeed / Glassdoor in assisted mode + tracker + daily scheduler.
- **Week 3+:** tune thresholds, unlock semi-auto if you're comfortable, add the 4th site.

## Sources (research, Sept 2026)

- LinkedIn: [Prohibited software and extensions](https://www.linkedin.com/help/linkedin/answer/a1341387), [LinkedIn User Agreement](https://www.linkedin.com/legal/user-agreement)
- Indeed+Glassdoor unified login: [glassdoor.com](https://www.glassdoor.com/index.htm)
- Existing tools: [Simplify](https://simplify.jobs/), Jobright, LazyApply, Sonara
- Public ATS APIs: [Greenhouse Job Board API](https://www.greenhouse.com/api), [Lever postings API](https://fantastic.jobs/ats/lever.co), [Apify ATS aggregator](https://apify.com/apeye/job-postings-api)
