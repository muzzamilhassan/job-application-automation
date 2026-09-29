"""ATS form auto-fill for the assisted-apply queue.

Fills what it knows from the profile (name, email, phone, links, cover note,
CV upload), leaves everything else untouched for the human:
  * unknown dropdowns / radio questions (work auth, salary, etc.) are reported,
    answered only when settings.browser_layer.auto_answers covers them
  * the SUBMIT button is never clicked - that stays human, by design
  * any CAPTCHA aborts before a single field is touched (checked by caller)

ATS detection is from the URL / tracker source since collectors already know it.
"""
import re
import time
from pathlib import Path

# keyword groups -> profile value key (first match wins per element)
FIELD_MAP = [
    (["first name", "firstname", "given name", "job_application[first_name]"], "first_name"),
    (["last name", "lastname", "surname", "family name", "job_application[last_name]"], "last_name"),
    (["full name", "your name", "job_application[full_name]"], "full_name"),
    (["email", "e-mail"], "email"),
    (["phone", "mobile", "telephone"], "phone"),
    (["linkedin"], "linkedin"),
    (["github", "git hub"], "github"),
    (["portfolio", "personal website", "website"], "website"),
    (["cover letter", "why do you want", "why are you", "anything else",
      "additional information", "additional comments", "anything you would like"], "cover_note"),
]
FILE_HINTS = ["resume", "cv", "attach", "upload"]
SELECT_MAP = [
    (["sponsor", "visa", "work authorization", "authorized to work", "legally allowed"], "work_authorization"),
    (["years of experience", "years experience", "experience level"], "years_experience"),
    (["relocate", "relocation"], "relocation"),
    (["salary", "compensation expectation", "expected compensation"], "salary_expectation"),
    (["notice period", "available from", "availability", "when can you start"], "availability"),
]
REVEAL_BUTTONS = ["apply here", "apply for this job", "apply now", "apply to this job"]
NEVER_CLICK = ["submit", "send application", "confirm application"]


def detect_ats(url: str, source: str = "") -> str:
    u = (url or "").lower()
    if "boards.greenhouse.io" in u or source.startswith("gh_") or "greenhouse" in u:
        return "greenhouse"
    if "jobs.ashbyhq.com" in u or source.startswith("ashby"):
        return "ashby"
    if "jobs.lever.co" in u or source.startswith("lever"):
        return "lever"
    if "jobs.smartrecruiters.com" in u or source.startswith("sr_"):
        return "smartrecruiters"
    if "weworkremotely.com" in u:
        return "wwr"
    return "generic"


def _profile_values(profile: dict, settings: dict, job_title: str, company: str) -> dict:
    name = profile.get("name", "")
    parts = name.split(" ", 1)
    contact = profile.get("contact", {})
    note = (f"I'm {name}, a {profile.get('title', 'Full Stack Developer')}. "
            f"My experience maps directly to the {job_title} role at {company}: "
            f"production SaaS delivery end-to-end with React/Next.js and Node.js/NestJS, "
            f"strong SQL (PostgreSQL/MySQL/SQLite) plus MongoDB, and AI integrations "
            f"(LangChain, OpenAI API). My tailored CV is attached - happy to share more.")
    return {
        "first_name": parts[0],
        "last_name": parts[1] if len(parts) > 1 else "",
        "full_name": name,
        "email": contact.get("application_email", ""),
        "phone": contact.get("phone", ""),
        "linkedin": contact.get("linkedin_url", ""),   # real URL needed in profile
        "github": contact.get("github_url", ""),
        "website": contact.get("portfolio_url", ""),
        "location": profile.get("location", ""),
        "cover_note": note,
    }


def _element_haystack(driver, el) -> str:
    """All identifying text of an element, lowercased, for keyword matching."""
    parts = []
    for attr in ("name", "id", "placeholder", "aria-label", "data-qa", "autocomplete"):
        v = el.get_attribute(attr)
        if v:
            parts.append(v)
    try:
        eid = el.get_attribute("id")
        if eid:
            for lbl in driver.find_elements("css selector", f"label[for='{eid}']"):
                parts.append(lbl.text)
        # label wrapping the input
        parent_label = el.find_element("xpath", "./ancestor::label[1]")
        parts.append(parent_label.text)
    except Exception:
        pass
    return " ".join(parts).lower().replace("_", " ").replace("-", " ")


def _scroll_into(driver, el):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.4)
    except Exception:
        pass


def _fill_text(el, value: str):
    _scroll_into(_EL_DRIVER[0], el)
    el.clear()
    el.send_keys(value)


# module-level driver handle so nested helpers can scroll (kept simple)
_EL_DRIVER = [None]


def reveal_application_form(driver):
    """Click 'Apply' reveal buttons (never submit buttons) so hidden forms show."""
    for text in REVEAL_BUTTONS:
        for b in driver.find_elements("xpath",
                f"//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{text}')] | "
                f"//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{text}')]"):
            if any(nv in (b.text or "").lower() for nv in NEVER_CLICK):
                continue
            try:
                if b.is_displayed():
                    _scroll_into(driver, b)
                    b.click()
                    time.sleep(1.5)
                    return True
            except Exception:
                continue
    return False


def fill_form(driver, profile: dict, settings: dict, cv_path: Path,
              job_title: str, company: str) -> dict:
    """Fill the current page's application form. Returns a report dict.
    Never clicks submit. Unknown questions are listed for the human."""
    _EL_DRIVER[0] = driver
    report = {"filled": [], "uploaded": None, "left_for_human": [], "unknown_selects": []}
    values = _profile_values(profile, settings, job_title, company)
    auto_answers = settings.get("browser_layer", {}).get("auto_answers", {})

    reveal_application_form(driver)
    time.sleep(1.0)

    # text inputs + textareas
    for el in driver.find_elements("css selector", "input[type='text'], input[type='email'], input[type='tel'], input:not([type]), textarea"):
        try:
            if not el.is_displayed() or not el.is_enabled():
                continue
            if el.get_attribute("value"):
                continue  # already has content - leave it
            hay = _element_haystack(driver, el)
            if any(h in hay for h in FILE_HINTS) and el.get_attribute("type") != "file":
                continue
            matched = None
            for keys, key in FIELD_MAP:
                if any(k.replace("_", " ") in hay or k in hay for k in keys):
                    matched = key
                    break
            if not matched:
                if el.tag_name == "textarea":
                    matched = "cover_note"  # unnamed textarea on an application page = motivation box
                else:
                    report["left_for_human"].append(f"text field: {hay[:60] or '(unlabeled)'}")
                    continue
            val = values.get(matched, "")
            if not val:
                report["left_for_human"].append(f"{matched} (no value in profile)")
                continue
            _fill_text(el, val)
            report["filled"].append(f"{matched} <- '{val[:40]}'")
            time.sleep(0.3)
        except Exception:
            continue

    # file upload (tailored CV)
    try:
        for el in driver.find_elements("css selector", "input[type='file']"):
            if cv_path and Path(cv_path).exists():
                _scroll_into(driver, el)
                el.send_keys(str(Path(cv_path).resolve()))
                report["uploaded"] = Path(cv_path).name
                time.sleep(1.0)
                break
    except Exception as e:
        report["left_for_human"].append(f"CV upload failed ({e.__class__.__name__}) - attach manually")

    # selects - only answer when auto_answers covers the question
    for el in driver.find_elements("css selector", "select"):
        try:
            if not el.is_displayed():
                continue
            hay = _element_haystack(driver, el)
            answer_key = None
            for keys, key in SELECT_MAP:
                if any(k in hay for k in keys):
                    answer_key = key
                    break
            answer = auto_answers.get(answer_key, "") if answer_key else ""
            if not answer:
                label = answer_key or hay[:40] or "unlabeled"
                report["unknown_selects"].append(label)
                continue
            from selenium.webdriver.support.ui import Select
            sel = Select(el)
            for opt in sel.options:
                if answer.lower() in opt.text.lower():
                    sel.select_by_visible_text(opt.text)
                    report["filled"].append(f"select[{answer_key}] <- '{opt.text}'")
                    break
        except Exception:
            continue

    # required fields still empty = human must handle
    try:
        for el in driver.find_elements("css selector", "[required]"):
            if el.tag_name in ("input", "textarea") and el.is_displayed() and not el.get_attribute("value"):
                hay = _element_haystack(driver, el)
                if hay and not any(hay[:30] in f for f in report["left_for_human"]):
                    report["left_for_human"].append(f"REQUIRED: {hay[:60]}")
    except Exception:
        pass

    return report
