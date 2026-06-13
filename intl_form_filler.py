#!/usr/bin/env python3
"""
International Career Page Form Filler — General-purpose Playwright form automation.

Detects common ATS platforms (Workday, Greenhouse, Lever, SmartRecruiters)
and fills application forms heuristically using label-to-data mapping.
User data is sourced from resume_parser.py (PDF parsing) merged with config overrides.
"""

import re
import time
import random
from datetime import datetime
from pathlib import Path
from typing import Optional


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [intl-form] {message}")


def random_delay(lo: float = 0.5, hi: float = 1.5) -> None:
    time.sleep(random.uniform(lo, hi))


# ---------------------------------------------------------------------------
# ATS Detection
# ---------------------------------------------------------------------------

ATS_URL_PATTERNS = {
    "workday": [r"myworkdayjobs\.com", r"wd\d+\.myworkday"],
    "greenhouse": [r"boards\.greenhouse\.io", r"job-boards\.greenhouse"],
    "lever": [r"jobs\.lever\.co", r"lever\.co/"],
    "smartrecruiters": [r"jobs\.smartrecruiters\.com", r"smartrecruiters"],
    "bamboohr": [r"bamboohr\.com/careers", r"bamboohr\.com/jobs"],
    "icims": [r"icims\.com", r"careers-.*\.icims"],
    "taleo": [r"taleo\.net"],
}


def detect_ats_platform(page) -> str:
    """Identify ATS platform from URL and page content."""
    url = page.url.lower()
    for platform, patterns in ATS_URL_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, url):
                log(f"Detected ATS: {platform} (URL match)")
                return platform

    # Check page content for hints
    try:
        body = page.inner_text("body")[:3000].lower()
        if "workday" in body:
            return "workday"
        if "greenhouse" in body:
            return "greenhouse"
        if "lever" in body:
            return "lever"
    except Exception:
        pass

    return "unknown"


# ---------------------------------------------------------------------------
# Visa Question Handler
# ---------------------------------------------------------------------------

VISA_YES_PATTERNS = [
    r"require.*sponsor", r"need.*visa", r"visa.*sponsor",
    r"work.*authoris", r"work.*authoriz", r"right to work",
    r"immigration.*sponsor", r"require.*work.*permit",
]

VISA_NO_PATTERNS = [
    r"legally.*authorised", r"legally.*authorized",
    r"eligible.*to work.*without", r"work.*without.*sponsor",
]


def answer_visa_question(page, prefer_sponsorship: bool = True) -> int:
    """
    Find and answer visa/sponsorship related questions.
    Returns number of questions answered.
    """
    answered = 0

    # Handle radio buttons / dropdowns asking about visa
    try:
        labels = page.locator("label:visible").all()
        for label in labels:
            try:
                txt = label.inner_text().lower().strip()
                if len(txt) > 200 or len(txt) < 5:
                    continue

                is_visa_q = any(re.search(p, txt) for p in VISA_YES_PATTERNS + VISA_NO_PATTERNS)
                if not is_visa_q:
                    continue

                log(f"Found visa question: {txt[:80]}")

                # Check for associated select/dropdown
                label_for = label.get_attribute("for") or ""
                if label_for:
                    select = page.locator(f"select#{label_for}").first
                    if select.is_visible():
                        # Look for "Yes" option
                        options = select.locator("option").all()
                        for opt in options:
                            opt_text = opt.inner_text().lower()
                            if "yes" in opt_text:
                                select.select_option(label=opt.inner_text())
                                log(f"Selected 'Yes' for visa question")
                                answered += 1
                                break
                        continue

                # Check for radio buttons near this label
                parent = label.locator("..").first
                radios = parent.locator("input[type='radio']").all()
                if radios:
                    for radio in radios:
                        radio_label = ""
                        rid = radio.get_attribute("id") or ""
                        if rid:
                            rl = page.locator(f"label[for='{rid}']").first
                            try:
                                radio_label = rl.inner_text().lower()
                            except Exception:
                                pass
                        if "yes" in radio_label:
                            radio.click(force=True)
                            log("Clicked 'Yes' radio for visa question")
                            answered += 1
                            break

            except Exception:
                continue
    except Exception as e:
        log(f"Error in visa question handler: {e}")

    return answered


# ---------------------------------------------------------------------------
# Resume Upload
# ---------------------------------------------------------------------------

def upload_resume(page, resume_path: str) -> bool:
    """Find file input and upload resume."""
    if not resume_path or not Path(resume_path).exists():
        log(f"Resume not found: {resume_path}")
        return False

    try:
        file_inputs = page.locator("input[type='file']").all()
        for fi in file_inputs:
            try:
                # Check if this looks like a resume upload
                accept = (fi.get_attribute("accept") or "").lower()
                name = (fi.get_attribute("name") or "").lower()
                aria = (fi.get_attribute("aria-label") or "").lower()
                combined = f"{accept} {name} {aria}"

                if any(k in combined for k in ["resume", "cv", "pdf", "doc", "file"]) or not combined.strip():
                    fi.set_input_files(resume_path)
                    log(f"Uploaded resume: {Path(resume_path).name}")
                    random_delay(1, 2)
                    return True
            except Exception:
                continue

        # Fallback: just use the first file input
        if file_inputs:
            file_inputs[0].set_input_files(resume_path)
            log("Uploaded resume via first file input (fallback)")
            return True

    except Exception as e:
        log(f"Resume upload failed: {e}")

    return False


# ---------------------------------------------------------------------------
# Field Mapping & Filling
# ---------------------------------------------------------------------------

def _match_field(combined_text: str, field_key: str) -> bool:
    """Check if combined label/placeholder text matches a field type."""
    patterns = {
        "name": [r"\bname\b", r"\bfull.?name\b"],
        "first_name": [r"\bfirst.?name\b", r"\bgiven.?name\b"],
        "last_name": [r"\blast.?name\b", r"\bsurname\b", r"\bfamily.?name\b"],
        "email": [r"\bemail\b", r"\be.?mail\b"],
        "phone": [r"\bphone\b", r"\bmobile\b", r"\btelephone\b", r"\bcontact.?number\b"],
        "location": [r"\blocation\b", r"\bcity\b", r"\baddress\b", r"\bwhere.*based\b"],
        "experience": [r"\byears?\b.*\bexperience\b", r"\bexperience\b.*\byears?\b", r"\btotal.*experience\b"],
        "salary": [r"\bsalary\b", r"\bcompensation\b", r"\bctc\b", r"\bexpected.*pay\b"],
        "notice": [r"\bnotice\b.*\bperiod\b", r"\bavailab\b", r"\bstart.*date\b", r"\bjoin.*date\b"],
        "linkedin_url": [r"\blinkedin\b", r"\blinked.?in\b.*\burl\b", r"\blinked.?in\b.*\bprofile\b"],
        "github_url": [r"\bgithub\b", r"\bgit.?hub\b.*\burl\b", r"\bgit.?hub\b.*\bprofile\b"],
        "website": [r"\bwebsite\b", r"\bportfolio\b", r"\bpersonal.*url\b", r"\burl\b"],
        "cover_letter": [r"\bcover.?letter\b"],
        "visa": [r"\bvisa\b", r"\bsponsor\b", r"\bright.?to.?work\b", r"\bwork.?permit\b"],
        "current_company": [r"\bcurrent.*company\b", r"\bcurrent.*employer\b", r"\bpresent.*company\b"],
        "current_title": [r"\bcurrent.*title\b", r"\bcurrent.*role\b", r"\bjob.*title\b", r"\bdesignation\b"],
    }
    for pat in patterns.get(field_key, []):
        if re.search(pat, combined_text):
            return True
    return False


def fill_text_inputs(page, user_data: dict, container=None) -> int:
    """Fill visible text inputs using heuristic label matching. Returns count filled."""
    filled = 0
    scope = container if container else page

    try:
        inputs = scope.locator(
            "input[type='text']:visible, input[type='email']:visible, "
            "input[type='tel']:visible, input[type='number']:visible, "
            "input:not([type]):visible"
        ).all()

        for inp in inputs:
            try:
                if inp.input_value():
                    continue  # Already filled

                placeholder = (inp.get_attribute("placeholder") or "").lower()
                name = (inp.get_attribute("name") or "").lower()
                aria = (inp.get_attribute("aria-label") or "").lower()
                inp_id = inp.get_attribute("id") or ""

                label_text = ""
                if inp_id:
                    try:
                        lbl = page.locator(f"label[for='{inp_id}']").first
                        label_text = lbl.inner_text().lower()
                    except Exception:
                        pass

                combined = f"{placeholder} {name} {aria} {label_text}"

                # Skip search boxes
                if any(k in combined for k in ["search", "filter", "keyword"]):
                    continue

                value = None
                if _match_field(combined, "first_name"):
                    value = user_data.get("first_name") or (user_data.get("full_name", "").split()[0] if user_data.get("full_name") else None)
                elif _match_field(combined, "last_name"):
                    full = user_data.get("full_name", "")
                    value = user_data.get("last_name") or (" ".join(full.split()[1:]) if len(full.split()) > 1 else None)
                elif _match_field(combined, "name"):
                    value = user_data.get("full_name")
                elif _match_field(combined, "email"):
                    value = user_data.get("email")
                elif _match_field(combined, "phone"):
                    value = user_data.get("phone")
                elif _match_field(combined, "location"):
                    value = user_data.get("location", "Bengaluru, India")
                elif _match_field(combined, "experience"):
                    value = user_data.get("experience_years", "5")
                elif _match_field(combined, "salary"):
                    value = user_data.get("expected_salary_gbp", "60000")
                elif _match_field(combined, "notice"):
                    value = user_data.get("notice_period", "60 days")
                elif _match_field(combined, "linkedin_url"):
                    value = user_data.get("linkedin_url", "")
                elif _match_field(combined, "github_url"):
                    value = user_data.get("github_url", "")
                elif _match_field(combined, "website"):
                    value = user_data.get("github_url") or user_data.get("linkedin_url", "")
                elif _match_field(combined, "current_company"):
                    # Extract from most recent experience entry
                    exp = user_data.get("experience", [])
                    if exp and isinstance(exp, list) and exp[0].get("title_company"):
                        value = exp[0]["title_company"]
                elif _match_field(combined, "current_title"):
                    value = user_data.get("job_titles_text", "").split(",")[0].strip() if user_data.get("job_titles_text") else None
                elif _match_field(combined, "visa"):
                    value = "Yes - require sponsorship"

                if value:
                    inp.fill(value)
                    log(f"Filled field ({combined[:40]}): {value[:30]}")
                    filled += 1
                    random_delay(0.3, 0.7)

            except Exception:
                continue
    except Exception as e:
        log(f"Error filling text inputs: {e}")

    return filled


def fill_textareas(page, user_data: dict, container=None) -> int:
    """Fill visible textareas. Returns count filled."""
    filled = 0
    scope = container if container else page

    try:
        textareas = scope.locator("textarea:visible").all()
        for ta in textareas:
            try:
                if ta.input_value():
                    continue

                label_text = ""
                ta_id = ta.get_attribute("id") or ""
                if ta_id:
                    try:
                        lbl = page.locator(f"label[for='{ta_id}']").first
                        label_text = lbl.inner_text().lower()
                    except Exception:
                        pass

                combined = label_text + " " + (ta.get_attribute("placeholder") or "").lower()

                if _match_field(combined, "cover_letter") or "cover" in combined:
                    cover = user_data.get("cover_letter", "")
                    if cover:
                        ta.fill(cover)
                        log("Filled cover letter textarea")
                        filled += 1
                elif "summary" in combined or "about" in combined or "describe" in combined:
                    summary = user_data.get("summary", "")
                    if summary:
                        ta.fill(summary[:1000])
                    else:
                        ta.fill(
                            f"I have {user_data.get('experience_years', '5')} years of experience "
                            f"in {user_data.get('skills_text') or user_data.get('job_titles_text', 'software engineering')}. "
                            f"I am seeking international opportunities and would require visa sponsorship. "
                            f"Please refer to my attached resume for detailed information."
                        )
                    log("Filled summary textarea")
                    filled += 1
                else:
                    ta.fill("Please refer to my attached resume for detailed information.")
                    filled += 1

                random_delay(0.3, 0.7)
            except Exception:
                continue
    except Exception as e:
        log(f"Error filling textareas: {e}")

    return filled


def fill_dropdowns(page, user_data: dict, container=None) -> int:
    """Fill visible dropdowns heuristically. Returns count filled."""
    filled = 0
    scope = container if container else page

    try:
        selects = scope.locator("select:visible").all()
        for select in selects:
            try:
                current = select.input_value()
                if current and "select" not in current.lower():
                    continue

                options = select.locator("option").all()
                if len(options) <= 1:
                    continue

                # Try to select "Yes" for generic questions
                for opt in options:
                    txt = opt.inner_text().lower()
                    if "yes" in txt:
                        select.select_option(label=opt.inner_text())
                        log(f"Selected 'Yes' in dropdown")
                        filled += 1
                        break
                else:
                    # Select second option as fallback (first is usually placeholder)
                    if len(options) > 1:
                        select.select_option(index=1)
                        filled += 1

                random_delay(0.3, 0.5)
            except Exception:
                continue
    except Exception as e:
        log(f"Error filling dropdowns: {e}")

    return filled


# ---------------------------------------------------------------------------
# Mandatory Field Detection & Fallback
# ---------------------------------------------------------------------------

def _is_mandatory(element, page) -> bool:
    """Check if a form element is mandatory/required."""
    try:
        if element.get_attribute("required") is not None:
            return True
        if element.get_attribute("aria-required") == "true":
            return True
        eid = element.get_attribute("id") or ""
        if eid:
            try:
                lbl = page.locator(f"label[for='{eid}']").first
                lbl_text = lbl.inner_html()
                if "*" in lbl_text or "required" in lbl_text.lower():
                    return True
            except Exception:
                pass
        # Check parent for asterisk
        try:
            parent_html = element.locator("..").first.inner_html()[:200]
            if "*" in parent_html:
                return True
        except Exception:
            pass
    except Exception:
        pass
    return False


def _get_field_context(element, page) -> str:
    """Get all text context around a field (label, placeholder, name, aria)."""
    parts = []
    for attr in ["placeholder", "name", "aria-label", "id", "autocomplete"]:
        v = element.get_attribute(attr) or ""
        if v:
            parts.append(v.lower())
    eid = element.get_attribute("id") or ""
    if eid:
        try:
            lbl = page.locator(f"label[for='{eid}']").first
            parts.append(lbl.inner_text().lower())
        except Exception:
            pass
    return " ".join(parts)


def _smart_fallback_value(context: str, user_data: dict) -> str:
    """For unrecognized mandatory fields, guess a reasonable value from context."""
    c = context.lower()
    
    # URL-type fields
    if any(k in c for k in ["url", "website", "portfolio", "http"]):
        return user_data.get("linkedin_url") or user_data.get("github_url") or "N/A"
    # Country
    if any(k in c for k in ["country", "nationality"]):
        return "India"
    # State/province
    if any(k in c for k in ["state", "province", "region"]):
        return user_data.get("location", "").split(",")[0].strip() or "Delhi"
    # Zip/postal
    if any(k in c for k in ["zip", "postal", "pin"]):
        return "110001"
    # Age / DOB
    if any(k in c for k in ["age", "birth", "dob"]):
        return "30"
    # Gender
    if "gender" in c:
        return "Prefer not to say"
    # How did you hear
    if any(k in c for k in ["hear", "source", "referr", "how did"]):
        return "Job Board"
    # Anything with "years"
    if "year" in c:
        return user_data.get("experience_years", "9")
    # Anything with "number"
    if "number" in c and "phone" not in c:
        return "0"
    # Generic fallback
    return "N/A"


def fill_mandatory_remaining(page, user_data: dict) -> int:
    """Find any still-empty mandatory fields and fill them with fallback values."""
    filled = 0
    try:
        inputs = page.locator(
            "input[type='text']:visible, input[type='email']:visible, "
            "input[type='tel']:visible, input[type='number']:visible, "
            "input[type='url']:visible, input:not([type]):visible"
        ).all()

        for inp in inputs:
            try:
                if inp.input_value():
                    continue
                if not _is_mandatory(inp, page):
                    continue
                ctx = _get_field_context(inp, page)
                if any(k in ctx for k in ["search", "filter", "keyword"]):
                    continue
                value = _smart_fallback_value(ctx, user_data)
                inp.fill(value)
                log(f"[mandatory-fallback] Filled ({ctx[:40]}): {value[:30]}")
                filled += 1
                random_delay(0.2, 0.5)
            except Exception:
                continue
    except Exception:
        pass
    return filled


def fill_checkboxes(page) -> int:
    """Check all mandatory/terms checkboxes."""
    filled = 0
    try:
        checkboxes = page.locator("input[type='checkbox']:visible").all()
        for cb in checkboxes:
            try:
                if cb.is_checked():
                    continue
                ctx = _get_field_context(cb, page)
                # Always check: terms, agree, consent, acknowledge, confirm, privacy
                if any(k in ctx for k in ["agree", "terms", "consent", "acknowledge",
                                           "confirm", "privacy", "accept", "policy"]):
                    cb.check(force=True)
                    log(f"Checked checkbox: {ctx[:50]}")
                    filled += 1
                elif _is_mandatory(cb, page):
                    cb.check(force=True)
                    log(f"[mandatory] Checked checkbox: {ctx[:50]}")
                    filled += 1
            except Exception:
                continue
    except Exception:
        pass
    return filled


def fill_radio_groups(page, user_data: dict) -> int:
    """Handle all radio button groups — pick the best option."""
    filled = 0
    handled_names = set()
    try:
        radios = page.locator("input[type='radio']:visible").all()
        for radio in radios:
            try:
                name = radio.get_attribute("name") or ""
                if not name or name in handled_names:
                    continue
                # Get all radios in this group
                group = page.locator(f"input[type='radio'][name='{name}']").all()
                # Skip if one is already selected
                if any(r.is_checked() for r in group):
                    handled_names.add(name)
                    continue
                
                # Build option labels
                options = []
                for r in group:
                    rid = r.get_attribute("id") or ""
                    label = ""
                    if rid:
                        try:
                            label = page.locator(f"label[for='{rid}']").first.inner_text().strip()
                        except Exception:
                            pass
                    if not label:
                        label = r.get_attribute("value") or ""
                    options.append((r, label.lower()))
                
                # Pick best option
                selected = False
                # Prefer "Yes" for visa/sponsorship/authorization questions
                group_ctx = _get_field_context(group[0], page)
                
                for r, lbl in options:
                    if "yes" in lbl:
                        r.click(force=True)
                        log(f"Radio [{name}]: selected 'Yes' ({lbl})")
                        selected = True
                        break
                
                if not selected:
                    # Just pick first option
                    group[0].click(force=True)
                    log(f"Radio [{name}]: selected first option ({options[0][1]})")
                
                handled_names.add(name)
                filled += 1
                random_delay(0.2, 0.4)
            except Exception:
                continue
    except Exception:
        pass
    return filled


def fill_mandatory_textareas(page, user_data: dict) -> int:
    """Fill any still-empty mandatory textareas."""
    filled = 0
    try:
        textareas = page.locator("textarea:visible").all()
        for ta in textareas:
            try:
                if ta.input_value():
                    continue
                if not _is_mandatory(ta, page):
                    continue
                ta.fill("Please refer to my attached resume for detailed information.")
                log("[mandatory-fallback] Filled required textarea")
                filled += 1
            except Exception:
                continue
    except Exception:
        pass
    return filled


def fill_mandatory_dropdowns(page) -> int:
    """Select a value for any still-empty mandatory dropdowns."""
    filled = 0
    try:
        selects = page.locator("select:visible").all()
        for select in selects:
            try:
                current = select.input_value()
                if current and "select" not in current.lower() and current.strip():
                    continue
                if not _is_mandatory(select, page):
                    continue
                options = select.locator("option").all()
                if len(options) <= 1:
                    continue
                # Skip placeholder option (index 0), pick second
                for i, opt in enumerate(options):
                    txt = opt.inner_text().strip().lower()
                    if txt and "select" not in txt and "--" not in txt and txt != "":
                        select.select_option(index=i)
                        log(f"[mandatory-fallback] Selected dropdown option: {opt.inner_text().strip()[:40]}")
                        filled += 1
                        break
                random_delay(0.2, 0.4)
            except Exception:
                continue
    except Exception:
        pass
    return filled


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

def fill_career_form(page, user_data: dict) -> bool:
    """
    Main entry: detect ATS and fill the career page form.
    Fills ALL mandatory fields — known ones by heuristic, unknown ones by fallback.
    Returns True if form was submitted (or appeared to be), False otherwise.
    """
    ats = detect_ats_platform(page)
    log(f"Filling career form (ATS: {ats})")

    # Multi-step handling loop
    max_steps = 5
    for step in range(max_steps):
        log(f"--- Form Step {step + 1} ---")
        
        # Step 1: Upload resume first (only on first step or if visible)
        resume_path = user_data.get("resume_path", "")
        if resume_path:
            upload_resume(page, resume_path)

        # Step 2: Fill known text inputs by heuristic
        filled = fill_text_inputs(page, user_data)
        filled += fill_textareas(page, user_data)
        filled += fill_dropdowns(page, user_data)

        # Step 3: Handle visa questions
        filled += answer_visa_question(page)

        # Step 4: Handle checkboxes (terms, consent, etc.)
        filled += fill_checkboxes(page)

        # Step 5: Handle radio button groups
        filled += fill_radio_groups(page, user_data)

        # Step 6: Fill any REMAINING mandatory fields we missed
        filled += fill_mandatory_remaining(page, user_data)
        filled += fill_mandatory_textareas(page, user_data)
        filled += fill_mandatory_dropdowns(page)

        log(f"Filled {filled} fields in step {step + 1}.")

        # Step 7: Try to submit or next
        status = _click_submit(page)
        
        if status == "SUCCESS":
            return True
        elif status == "FAILED":
            log("Validation errors or failed to submit. Stopping form filler.")
            return False
        elif status == "NEXT":
            log("Moving to next step of the form...")
            random_delay(2, 4)
            continue
        else:
            log("Could not find a submit or next button.")
            return False
            
    log("Exceeded maximum form steps.")
    return False


def _click_submit(page) -> str:
    """Find and click submit/next button. Returns 'SUCCESS', 'NEXT', 'FAILED', or 'NONE'."""
    submit_selectors = [
        "button[type='submit']",
        "button.submit-btn",
        "button[class*='submit']",
        "button[id='submit_app']",
        "button[id*='submit']",
        "button[data-qa='btn-submit']",
        "button:has-text('Submit')",
        "button:has-text('Submit Application')",
        "button:has-text('Apply')",
        "button:has-text('Apply Now')",
        "button:has-text('Send')",
        "button:has-text('Send application')",
        "button:has-text('Send CV')",
        "button:has-text('Submit CV')",
        "button:has-text('Next')",
        "button:has-text('Continue')",
        "button:has-text('Proceed')",
        "button:has-text('Complete')",
        "button:has-text('Finish')",
        "button:has-text('Save and Continue')",
        "input[type='submit']",
        "input[value*='Submit']",
        "input[value*='Send']",
        "input[value*='Apply']",
        "a:has-text('Submit Application')",
        "a:has-text('Apply')",
        "a:has-text('Next')",
        "a:has-text('Continue')",
        "a:has-text('Send')",
    ]

    try:
        combined = ", ".join(submit_selectors)
        page.wait_for_selector(combined, state="visible", timeout=4000)
    except Exception:
        pass

    for selector in submit_selectors:
        try:
            for btn in page.locator(selector).all():
                if btn.is_visible() and btn.is_enabled():
                    txt = btn.inner_text() if btn.evaluate("el => el.tagName") != "INPUT" else btn.get_attribute("value")
                    if txt and "save" in txt.lower() and "submit" not in txt.lower():
                        continue
                    
                    is_next = txt and any(k in txt.lower() for k in ["next", "continue"])
                    
                    log(f"Clicking submit/next button: {txt or selector}")
                    btn.click()
                    random_delay(3, 5)

                    # Check for success indicators
                    try:
                        body_text = page.inner_text("body")[:2000].lower()
                        if any(s in body_text for s in [
                            "thank you", "application received", "submitted",
                            "application sent", "successfully applied",
                            "we have received", "confirmation"
                        ]):
                            log("Application appears successful!")
                            return "SUCCESS"
                    except Exception:
                        pass

                    # Check for validation errors
                    try:
                        error_locators = [
                            ".error-message", ".field-error", ".has-error", 
                            "[aria-invalid='true']", ".parsley-error", ".is-invalid",
                            ".application-error", "text='is required'", "text='must be'",
                            "text='invalid'"
                        ]
                        for err_sel in error_locators:
                            if page.locator(err_sel).first.is_visible():
                                log(f"Validation error detected on page! (Matched: {err_sel})")
                                return "FAILED"
                    except Exception:
                        pass
                        
                    if is_next:
                        return "NEXT"

                    # If it's a submit button and URL changed significantly or success didn't match, 
                    # but no obvious errors, assume success if the form disappeared
                    if not btn.is_visible():
                        log("Submit button disappeared and no errors found. Assuming success.")
                        return "SUCCESS"
                return "FAILED"
        except Exception:
            continue

    log("No submit/next button found.")
    return "NONE"

