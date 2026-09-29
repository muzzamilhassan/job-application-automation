#!/usr/bin/env python3
"""Stage 3 - Per-job CV tailoring. Reads one matched job, writes a tailored CV
as .md and .docx (the docx is what gets attached to Gmail drafts).

Two modes:
  * LLM mode (preferred): set TAILOR_API_BASE, TAILOR_API_KEY, TAILOR_MODEL
    (any OpenAI-compatible endpoint).
  * Fallback mode (no key): deterministic template - picks the most relevant
    projects/skills for the job. Good enough for the dry run.

Hard rule in both modes: only facts from config/profile.json; never invent
employers, dates, titles, or skills.

Usage: python tailor.py out/matches_2026-09-09.json 0
"""
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROFILE = json.loads((ROOT / "config" / "profile.json").read_text(encoding="utf-8"))
SETTINGS = json.loads((ROOT / "config" / "settings.json").read_text(encoding="utf-8"))
OUT = ROOT / "tailored"

SYSTEM_RULES = (
    "You tailor resumes. Hard rules: use ONLY facts present in the profile; never invent "
    "employers, dates, titles, or skills; keep it truthful. Output the full tailored CV as "
    "plain text/markdown. Reorder and reword to mirror the job posting's keywords, lead with "
    "the most relevant experience, keep length to one page of content. Contact email must be "
    f"{SETTINGS['application_email']}."
)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


def llm_tailor(job_dict) -> str | None:
    base = os.environ.get("TAILOR_API_BASE")
    key = os.environ.get("TAILOR_API_KEY")
    model = os.environ.get("TAILOR_MODEL", "gpt-4o-mini")
    if not (base and key):
        return None
    user = (
        f"MASTER PROFILE:\n{json.dumps(PROFILE, indent=1)}\n\n"
        f"JOB POSTING:\nTitle: {job_dict['title']}\nCompany: {job_dict['company']}\n"
        f"Text: {job_dict['text'][:3000]}\n\n"
        "Write the tailored CV now."
    )
    req = urllib.request.Request(
        f"{base.rstrip('/')}/chat/completions",
        data=json.dumps({
            "model": model,
            "messages": [{"role": "system", "content": SYSTEM_RULES},
                         {"role": "user", "content": user}],
            "temperature": 0.3,
        }).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"]


def fallback_tailor(job_dict) -> str:
    blob = f"{job_dict['title']} {job_dict['text']}".lower()
    p = PROFILE
    scored_projects = sorted(
        p["projects"],
        key=lambda pr: sum(1 for t in pr.get("stack", []) if t.lower() in blob),
        reverse=True)
    top_projects = scored_projects[:4]
    skills = {k: v for k, v in p["skills"].items() if any(s.lower() in blob for s in v)} or p["skills"]
    ai_hits = [s for s in p["skills"]["ai"] if s.lower() in blob]
    lines = [
        f"# {p['name']} - {p['title']}",
        f"{p['location']} | {SETTINGS['application_email']} | {p['contact']['phone']}",
        "",
    ]
    focus = job_dict["title"]
    lines += [
        "## Summary",
        f"{p['summary']} Focused on roles like {focus}: shipping production features "
        f"end-to-end with React/Next.js frontends and Node.js/NestJS backends."
        + (f" Direct hands-on delivery with {' ,'.join(ai_hits)}." if ai_hits else ""),
        "",
        "## Skills",
    ]
    for k, v in skills.items():
        lines.append(f"- {k.replace('_', ' ').title()}: {', '.join(v)}")
    lines += ["", "## Experience"]
    for e in p["experience"]:
        lines += [f"### {e['role']} - {e['company']} ({e['period']}, {e['work_type']})"]
        lines += [f"- {h}" for h in e["highlights"]]
    lines += ["", "## Selected Projects"]
    for pr in top_projects:
        lines.append(f"### {pr['name']} - {pr['kind']}")
        lines.append(f"Stack: {', '.join(pr['stack'])}")
        lines += [f"- {h}" for h in pr.get("highlights", [])][:3]
    ed = p["education"]
    lines += ["", "## Education", f"{ed['degree']}, {ed['school']} ({ed['period']})"]
    return "\n".join(lines)


def md_to_docx(md_text: str, out_path: Path) -> None:
    try:
        from docx import Document
    except ImportError:
        return  # docx optional; md still written
    doc = Document()
    for line in md_text.splitlines():
        if not line.strip():
            continue
        if line.startswith("### "):
            doc.add_heading(line[4:], level=3)
        elif line.startswith("## "):
            doc.add_heading(line[3:], level=2)
        elif line.startswith("# "):
            doc.add_heading(line[2:], level=1)
        elif line.startswith("- "):
            doc.add_paragraph(line[2:], style="List Bullet")
        else:
            doc.add_paragraph(line)
    doc.save(str(out_path))


def tailor(job_dict) -> tuple[Path, Path]:
    """Tailor and return (md_path, docx_path)."""
    OUT.mkdir(exist_ok=True)
    body = llm_tailor(job_dict) or fallback_tailor(job_dict)
    md = OUT / f"cv_{slug(job_dict['company'])}_{slug(job_dict['title'])}.md"
    md.write_text(body, encoding="utf-8")
    dx = md.with_suffix(".docx")
    md_to_docx(body, dx)
    return md, dx


def main():
    matches_file, idx = sys.argv[1], int(sys.argv[2])
    job_dict = json.loads(Path(matches_file).read_text(encoding="utf-8"))[idx]
    md, dx = tailor(job_dict)
    mode = "llm" if os.environ.get("TAILOR_API_KEY") else "fallback-template"
    print(f"Tailored CV ({mode}) -> {md.name}" + (" + .docx" if dx.exists() else ""))


if __name__ == "__main__":
    main()
