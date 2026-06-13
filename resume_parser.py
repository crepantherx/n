#!/usr/bin/env python3
"""
Resume Parser — Extracts structured candidate data from PDF resumes.

Uses pypdf for text extraction and regex-based parsing to pull out:
- Name, email, phone, location
- Work experience (companies, titles, dates, descriptions)
- Education (degrees, institutions)
- Skills
- LinkedIn URL
- Total years of experience (calculated)

The parsed data is cached as a JSON sidecar file next to the PDF for fast reuse.
"""

import re
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from pypdf import PdfReader
except ImportError:
    from PyPDF2 import PdfReader


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [resume-parser] {msg}")


# ---------------------------------------------------------------------------
# Text Extraction
# ---------------------------------------------------------------------------

def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract all text from a PDF file."""
    reader = PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"
    return text


# ---------------------------------------------------------------------------
# Field Extractors
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s\-]?)?(?:\(?\d{2,5}\)?[\s\-]?)?\d{5,10}")
_LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w\-]+/?")
_GITHUB_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[\w\-]+/?")

# Common month patterns for date parsing
_MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
_DATE_RANGE_RE = re.compile(
    rf"({_MONTHS})\s*['.]?\s*(\d{{2,4}})\s*[-–—to]+\s*(?:({_MONTHS})\s*['.]?\s*(\d{{2,4}})|present|current|now)",
    re.IGNORECASE,
)

# Section header patterns
_SECTION_HEADERS = {
    "experience": re.compile(
        r"^(?:work\s+)?experience|employment|professional\s+experience|work\s+history",
        re.IGNORECASE,
    ),
    "education": re.compile(
        r"^education|academic|qualifications|degrees?",
        re.IGNORECASE,
    ),
    "skills": re.compile(
        r"^(?:technical\s+)?skills|technologies|competenc",
        re.IGNORECASE,
    ),
    "summary": re.compile(
        r"^(?:professional\s+)?summary|objective|profile|about\s+me",
        re.IGNORECASE,
    ),
    "certifications": re.compile(
        r"^certifications?|licenses?|accreditations?",
        re.IGNORECASE,
    ),
    "projects": re.compile(
        r"^projects?|portfolio",
        re.IGNORECASE,
    ),
}


def _extract_email(text: str) -> str:
    m = _EMAIL_RE.search(text)
    return m.group(0) if m else ""


def _extract_phone(text: str) -> str:
    # Take the first match that looks like a real phone (7+ digits)
    for m in _PHONE_RE.finditer(text[:1500]):
        digits = re.sub(r"\D", "", m.group(0))
        if 7 <= len(digits) <= 15:
            return m.group(0).strip()
    return ""


def _extract_linkedin(text: str) -> str:
    m = _LINKEDIN_RE.search(text)
    return m.group(0) if m else ""


def _extract_github(text: str) -> str:
    m = _GITHUB_RE.search(text)
    return m.group(0) if m else ""


# Words that are NEVER a person's name — common section headers
_NAME_BLACKLIST = {
    "about", "summary", "objective", "profile", "skills", "experience",
    "education", "projects", "certifications", "contact", "references",
    "employment", "qualifications", "achievements", "interests", "hobbies",
    "languages", "awards", "publications", "volunteer", "professional",
    "technical", "portfolio", "work", "history", "details",
}


def _extract_name(text: str, email: str, pdf_path: str = "") -> str:
    """
    Heuristic name extraction:
    1. Try extracting from the very first line (even if it has contact info mixed in).
    2. Check the first few lines for standalone name.
    3. Try extracting from the PDF filename.
    4. Fall back to the email local part.
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()][:10]

    # Strategy 1: Parse the first line, which often has "Name <email> <phone>"
    # Split on common separators: |, •, email addresses, phone patterns
    if lines:
        first_line = lines[0]
        # Remove email addresses, URLs, phone numbers, and special chars
        cleaned = re.sub(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", " ", first_line)
        cleaned = re.sub(r"(?:https?://)?(?:www\.)?[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}[/\w\-]*", " ", cleaned)
        cleaned = re.sub(r"(?:\+?\d[\d\s\-()]{6,15})", " ", cleaned)
        # Split on separators: |, •, ·, ,, Л (special chars from PDF)
        parts = re.split(r"[|•·,\u041b\uf0b7\uf0a7\u00e7\u00e0]+", cleaned)
        if parts:
            candidate = parts[0].strip()
            # Remove any remaining non-name characters
            candidate = re.sub(r"[^A-Za-z\s.\-']", "", candidate).strip()
            words = candidate.split()
            if 2 <= len(words) <= 5 and all(len(w) > 1 for w in words):
                if words[0].lower() not in _NAME_BLACKLIST:
                    return candidate

    # Strategy 2: Look for standalone name lines in the first few lines
    for line in lines[:6]:
        if "@" in line or "http" in line.lower():
            continue
        if re.search(r"\d{5,}", line):
            continue

        # Blacklist section headers
        if line.lower().strip() in _NAME_BLACKLIST:
            continue
        if any(line.lower().startswith(h) for h in ["resume", "curriculum", "cv", "page"]):
            continue

        words = line.split()
        if 2 <= len(words) <= 4 and all(re.match(r"^[A-Za-z.\-']+$", w) for w in words):
            if words[0].lower() not in _NAME_BLACKLIST:
                return line

    # Strategy 3: Extract from PDF filename (e.g., "Sudhir_Singh_AI_ML_Resume.pdf")
    if pdf_path:
        fname = Path(pdf_path).stem  # "Sudhir_Singh_AI_ML_Engineer_Resume"
        # Split on underscores/hyphens and take leading name-like words
        fname_parts = re.split(r"[_\-\s]+", fname)
        name_words = []
        for p in fname_parts:
            if p.lower() in {"resume", "cv", "engineer", "developer", "senior",
                             "junior", "lead", "data", "ml", "ai", "software",
                             "full", "stack", "updated", "final", "new", "latest"}:
                break
            if re.match(r"^[A-Za-z]+$", p) and len(p) > 1:
                name_words.append(p.capitalize())
        if 2 <= len(name_words) <= 4:
            return " ".join(name_words)

    # Strategy 4: Derive from email
    if email:
        local = email.split("@")[0]
        # Remove common prefixes like "hire.", "contact.", etc.
        local = re.sub(r"^(hire|contact|info|work|job|apply)[.\-_]", "", local)
        parts = re.split(r"[._\-]", local)
        name_parts = [p.capitalize() for p in parts if p.isalpha() and len(p) > 1]
        if name_parts:
            return " ".join(name_parts)

    return ""


def _extract_location(text: str) -> str:
    """Extract location from the header area of the resume."""
    header = text[:1000]

    # Common patterns: "City, State", "City, Country"
    loc_patterns = [
        re.compile(r"(?:location|address|based in|residing)[:\s]+(.+)", re.IGNORECASE),
        re.compile(r"([A-Z][a-z]+(?:\s[A-Z][a-z]+)*,\s*(?:India|UK|USA|US|Germany|Canada|Australia|Remote|[A-Z]{2}))"),
    ]

    for pat in loc_patterns:
        m = pat.search(header)
        if m:
            return m.group(1).strip()[:80]

    return ""


def _month_to_num(month_str: str) -> int:
    months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    s = month_str[:3].lower()
    return months.index(s) + 1 if s in months else 1


def _parse_year(y: str) -> int:
    y = int(y)
    return y if y > 100 else (1900 + y if y > 50 else 2000 + y)


def _calculate_experience_years(text: str) -> float:
    """Calculate total years of experience from date ranges found in resume."""
    total_months = 0

    for m in _DATE_RANGE_RE.finditer(text):
        try:
            start_month = _month_to_num(m.group(1))
            start_year = _parse_year(m.group(2))

            if m.group(3):
                end_month = _month_to_num(m.group(3))
                end_year = _parse_year(m.group(4))
            else:
                # "present" / "current"
                now = datetime.now()
                end_month = now.month
                end_year = now.year

            months = (end_year - start_year) * 12 + (end_month - start_month)
            if 0 < months < 360:  # sanity check
                total_months += months
        except Exception:
            continue

    return round(total_months / 12, 1)


def _split_sections(text: str) -> dict:
    """Split resume text into sections based on common headers."""
    sections = {}
    current_section = "header"
    current_lines = []

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            current_lines.append("")
            continue

        matched = False
        for section_name, pattern in _SECTION_HEADERS.items():
            if pattern.match(stripped):
                if current_lines:
                    sections[current_section] = "\n".join(current_lines)
                current_section = section_name
                current_lines = []
                matched = True
                break

        if not matched:
            current_lines.append(line)

    if current_lines:
        sections[current_section] = "\n".join(current_lines)

    return sections


def _extract_skills(skills_text: str) -> list:
    """Extract individual skills from skills section."""
    # Common separators: comma, pipe, bullet, newline
    raw = re.split(r"[,|•·●▪\n]", skills_text)
    skills = []
    for s in raw:
        s = s.strip().strip("-–—").strip()
        if 2 <= len(s) <= 50 and not s[0].isdigit():
            skills.append(s)
    return skills


def _extract_experience_entries(exp_text: str) -> list:
    """Extract individual work experience entries."""
    entries = []
    lines = exp_text.split("\n")
    current_entry = {}
    current_desc_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current_entry:
                current_entry["description"] = " ".join(current_desc_lines).strip()
                entries.append(current_entry)
                current_entry = {}
                current_desc_lines = []
            continue

        # Check for date range (signals new entry)
        date_match = _DATE_RANGE_RE.search(stripped)
        if date_match:
            if current_entry:
                current_entry["description"] = " ".join(current_desc_lines).strip()
                entries.append(current_entry)
                current_desc_lines = []
            current_entry = {"dates": date_match.group(0)}
            # The rest of the line (or the line before) is likely the title/company
            remaining = stripped[:date_match.start()].strip().rstrip("|–—-,").strip()
            if remaining:
                current_entry["title_company"] = remaining
        elif current_entry:
            if "title_company" not in current_entry and len(stripped) < 80:
                current_entry["title_company"] = stripped
            else:
                current_desc_lines.append(stripped)

    if current_entry:
        current_entry["description"] = " ".join(current_desc_lines).strip()
        entries.append(current_entry)

    return entries


def _extract_education_entries(edu_text: str) -> list:
    """Extract education entries."""
    entries = []
    lines = [l.strip() for l in edu_text.split("\n") if l.strip()]

    current = {}
    for line in lines:
        # Check for degree keywords
        if re.search(r"\b(?:B\.?(?:Tech|Sc|E|A)|M\.?(?:Tech|Sc|S|A)|Ph\.?D|MBA|Bachelor|Master|Doctor|Diploma)\b",
                      line, re.IGNORECASE):
            if current:
                entries.append(current)
            current = {"degree": line}
        elif current and "institution" not in current and len(line) < 100:
            current["institution"] = line
        elif re.search(r"\d{4}", line) and current:
            current["dates"] = line

    if current:
        entries.append(current)

    return entries


# ---------------------------------------------------------------------------
# Main Parser
# ---------------------------------------------------------------------------

def parse_resume(pdf_path: str, force_reparse: bool = False) -> dict:
    """
    Parse a resume PDF and return structured data.
    Results are cached in a .resume_parsed.json sidecar file.
    """
    pdf_path = str(Path(pdf_path).expanduser().resolve())
    cache_path = Path(pdf_path).with_suffix(".resume_parsed.json")

    # Check cache
    if not force_reparse and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text())
            if cached.get("_source_mtime") == Path(pdf_path).stat().st_mtime:
                log(f"Using cached resume data from {cache_path.name}")
                return cached
        except Exception:
            pass

    log(f"Parsing resume: {pdf_path}")
    raw_text = extract_text_from_pdf(pdf_path)

    if not raw_text.strip():
        log("WARNING: No text extracted from PDF. It may be image-based.")
        return {"_error": "No text extracted", "raw_text": ""}

    # Extract contact info
    email = _extract_email(raw_text)
    phone = _extract_phone(raw_text)
    full_name = _extract_name(raw_text, email, pdf_path)
    location = _extract_location(raw_text)
    linkedin_url = _extract_linkedin(raw_text)
    github_url = _extract_github(raw_text)

    # Split into sections
    sections = _split_sections(raw_text)

    # Extract structured data
    experience_years = _calculate_experience_years(raw_text)
    skills = _extract_skills(sections.get("skills", ""))
    experience = _extract_experience_entries(sections.get("experience", ""))
    education = _extract_education_entries(sections.get("education", ""))
    summary = sections.get("summary", "")

    # Derive first/last name
    name_parts = full_name.split() if full_name else []
    first_name = name_parts[0] if name_parts else ""
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

    result = {
        "full_name": full_name,
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "location": location,
        "linkedin_url": linkedin_url,
        "github_url": github_url,
        "experience_years": experience_years,
        "experience_years_str": str(int(experience_years)) if experience_years else "5",
        "skills": skills,
        "skills_text": ", ".join(skills[:20]),
        "experience": experience,
        "education": education,
        "summary": summary.strip()[:500],
        "raw_text": raw_text[:5000],  # Keep first 5k chars for context
        "_source_path": pdf_path,
        "_source_mtime": Path(pdf_path).stat().st_mtime,
        "_parsed_at": str(datetime.now()),
    }

    # Cache result
    try:
        cache_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        log(f"Cached parsed data → {cache_path.name}")
    except Exception as e:
        log(f"Warning: Could not cache: {e}")

    # Summary log
    log(f"  Name:       {full_name}")
    log(f"  Email:      {email}")
    log(f"  Phone:      {phone}")
    log(f"  Location:   {location}")
    log(f"  Experience: {experience_years} years ({len(experience)} entries)")
    log(f"  Education:  {len(education)} entries")
    log(f"  Skills:     {len(skills)} found")
    log(f"  LinkedIn:   {linkedin_url}")

    return result


def get_form_data(pdf_path: str, config_overrides: Optional[dict] = None) -> dict:
    """
    Build form-fill data by parsing the resume and merging with config overrides.
    Config overrides take precedence (user can override parsed values).
    """
    parsed = parse_resume(pdf_path)
    overrides = config_overrides or {}

    data = {
        "full_name": overrides.get("full_name") or parsed.get("full_name", ""),
        "first_name": overrides.get("first_name") or parsed.get("first_name", ""),
        "last_name": overrides.get("last_name") or parsed.get("last_name", ""),
        "email": overrides.get("email") or parsed.get("email", ""),
        "phone": overrides.get("phone") or parsed.get("phone", ""),
        "location": overrides.get("location") or parsed.get("location", ""),
        "linkedin_url": parsed.get("linkedin_url", ""),
        "github_url": parsed.get("github_url", ""),
        "experience_years": parsed.get("experience_years_str", "5"),
        "expected_salary_gbp": overrides.get("expected_salary_gbp", "60000"),
        "notice_period": overrides.get("notice_period", "60 days"),
        "visa_status": overrides.get("visa_status", "Require Sponsorship"),
        "resume_path": pdf_path,
        "skills_text": parsed.get("skills_text", ""),
        "summary": parsed.get("summary", ""),
        "job_titles_text": overrides.get("job_titles_text", ""),
        "cover_letter": (
            f"Dear Hiring Manager,\n\n"
            f"I am {parsed.get('full_name', 'a professional')} with "
            f"{parsed.get('experience_years_str', 'several')} years of experience. "
            f"I am enthusiastic about this opportunity and believe my skills in "
            f"{parsed.get('skills_text', 'software engineering')[:100]} "
            f"make me an excellent fit.\n\n"
            f"I am seeking opportunities in Europe/Remote and would require visa sponsorship.\n\n"
            f"Best regards,\n{parsed.get('full_name', '')}"
        ),
    }

    return data


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Parse a resume PDF into structured JSON")
    parser.add_argument("pdf", help="Path to resume PDF")
    parser.add_argument("--force", action="store_true", help="Force re-parse (ignore cache)")
    args = parser.parse_args()

    result = parse_resume(args.pdf, force_reparse=args.force)
    print(json.dumps(result, indent=2, ensure_ascii=False))
