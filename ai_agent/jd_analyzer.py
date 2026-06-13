#!/usr/bin/env python3
"""
JD Analyzer — Uses the local LLM to deeply analyze job descriptions.

Compares job descriptions against the candidate's resume to produce:
  - Match score (0-100)
  - Key requirements extracted
  - Missing skills
  - Salary estimate
  - Red flags
  - Recommendation (APPLY / SKIP / REVIEW)
"""

import json
from datetime import datetime
from typing import Any, Optional

from .llm_client import LLMClient, SYSTEM_PROMPTS, get_client


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [jd-analyzer] {msg}")


# ---------------------------------------------------------------------------
# Data class for analysis results
# ---------------------------------------------------------------------------

class JobAnalysis:
    """Structured result from JD analysis."""

    def __init__(self, data: dict):
        self.match_score: float = data.get("match_score", 0)
        self.recommendation: str = data.get("recommendation", "REVIEW").upper()
        self.reasoning: str = data.get("reasoning", "")
        self.key_requirements: list[str] = data.get("key_requirements", [])
        self.matching_skills: list[str] = data.get("matching_skills", [])
        self.missing_skills: list[str] = data.get("missing_skills", [])
        self.salary_range: str = data.get("salary_range", "Not mentioned")
        self.experience_required: str = data.get("experience_required", "Not specified")
        self.location: str = data.get("location", "Not specified")
        self.remote_friendly: bool = data.get("remote_friendly", False)
        self.red_flags: list[str] = data.get("red_flags", [])
        self.job_type: str = data.get("job_type", "Full-time")
        self._raw = data

    def should_apply(self, min_score: int = 60) -> bool:
        """Whether the agent should proceed with application."""
        return self.recommendation == "APPLY" and self.match_score >= min_score

    def to_dict(self) -> dict:
        return {
            "match_score": self.match_score,
            "recommendation": self.recommendation,
            "reasoning": self.reasoning,
            "key_requirements": self.key_requirements,
            "matching_skills": self.matching_skills,
            "missing_skills": self.missing_skills,
            "salary_range": self.salary_range,
            "experience_required": self.experience_required,
            "location": self.location,
            "remote_friendly": self.remote_friendly,
            "red_flags": self.red_flags,
            "job_type": self.job_type,
        }

    def __repr__(self) -> str:
        return (
            f"JobAnalysis(score={self.match_score}, rec={self.recommendation}, "
            f"skills_match={len(self.matching_skills)}, "
            f"missing={len(self.missing_skills)}, "
            f"flags={len(self.red_flags)})"
        )


# ---------------------------------------------------------------------------
# Analysis prompt builder
# ---------------------------------------------------------------------------

def _build_analysis_prompt(
    jd_text: str,
    resume_data: dict,
    preferences: dict,
) -> str:
    """Build the prompt for JD analysis."""

    # Summarize resume for the LLM
    skills = resume_data.get("skills_text", "") or ", ".join(resume_data.get("skills", []))
    experience = resume_data.get("experience_years", "5")
    summary = resume_data.get("summary", "")
    job_titles = preferences.get("job_titles", "ML Engineer, AI Engineer, Software Engineer")
    min_salary = preferences.get("min_salary_lpa", "45")

    # Build experience entries summary
    exp_entries = resume_data.get("experience", [])
    exp_summary = ""
    if exp_entries and isinstance(exp_entries, list):
        for entry in exp_entries[:3]:  # Top 3 most recent
            title_company = entry.get("title_company", "")
            dates = entry.get("dates", "")
            if title_company:
                exp_summary += f"  - {title_company} ({dates})\n"

    return f"""Analyze this job description against the candidate's profile and provide a structured assessment.

## JOB DESCRIPTION:
{jd_text[:3000]}

## CANDIDATE PROFILE:
- Target Roles: {job_titles}
- Total Experience: {experience} years
- Key Skills: {skills[:500]}
- Summary: {summary[:300]}
- Recent Experience:
{exp_summary or '  (Not available)'}
- Minimum Acceptable Salary: {min_salary} LPA (Indian Rupees) or equivalent

## INSTRUCTIONS:
Respond with a JSON object containing these fields:
{{
    "match_score": <number 0-100>,
    "recommendation": "APPLY" or "SKIP" or "REVIEW",
    "reasoning": "<1-2 sentence explanation>",
    "key_requirements": ["<list of top 5 requirements from JD>"],
    "matching_skills": ["<candidate skills that match JD>"],
    "missing_skills": ["<JD requirements candidate lacks>"],
    "salary_range": "<salary range if mentioned, else 'Not mentioned'>",
    "experience_required": "<years required>",
    "location": "<job location>",
    "remote_friendly": <true/false>,
    "red_flags": ["<any concerns, e.g., 'requires 15+ years'>"],
    "job_type": "<Full-time/Part-time/Contract>"
}}

RULES:
- Score 80+: Strong match, recommend APPLY
- Score 60-79: Moderate match, recommend APPLY with caveats
- Score 40-59: Weak match, recommend REVIEW
- Score <40: Poor match, recommend SKIP
- If salary is below {min_salary} LPA, add a red flag
- If experience required is much higher than {experience} years, add a red flag
- Be honest and conservative with the score"""


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

def analyze_job(
    jd_text: str,
    resume_data: dict,
    preferences: Optional[dict] = None,
    client: Optional[LLMClient] = None,
) -> JobAnalysis:
    """
    Analyze a job description against the candidate's resume.

    Args:
        jd_text: The job description text (extracted from the page)
        resume_data: Parsed resume data from resume_parser.py
        preferences: User preferences (min_salary, target_roles, etc.)
        client: LLM client (uses default if None)

    Returns:
        JobAnalysis with match score, recommendation, and details.
    """
    if not jd_text or len(jd_text.strip()) < 50:
        _log("JD text too short for analysis, defaulting to REVIEW")
        return JobAnalysis({"match_score": 50, "recommendation": "REVIEW",
                           "reasoning": "JD text was too short for reliable analysis"})

    prefs = preferences or {}
    llm = client or get_client()

    prompt = _build_analysis_prompt(jd_text, resume_data, prefs)

    try:
        result = llm.ask_json(
            prompt,
            system=SYSTEM_PROMPTS["jd_analyzer"],
            temperature=0.2,  # Low temp for consistent scoring
        )

        if "_error" in result:
            _log(f"LLM returned unparseable response, falling back to REVIEW")
            return JobAnalysis({"match_score": 50, "recommendation": "REVIEW",
                               "reasoning": "LLM response could not be parsed"})

        analysis = JobAnalysis(result)
        _log(f"Analysis: score={analysis.match_score}, rec={analysis.recommendation}")
        return analysis

    except ConnectionError:
        pass
        return JobAnalysis({
            "match_score": 70,
            "recommendation": "APPLY",
            "reasoning": "LLM unavailable — applying by default",
        })
    except Exception as e:
        _log(f"Analysis error: {e}")
        return JobAnalysis({
            "match_score": 50,
            "recommendation": "REVIEW",
            "reasoning": f"Analysis error: {str(e)[:100]}",
        })


def extract_jd_text(page) -> str:
    """
    Extract job description text from a Playwright page.
    Works across Naukri, LinkedIn, and other job boards.
    """
    # Platform-specific selectors in priority order
    selectors = [
        # Naukri
        ".job-desc", ".other-details", ".job-info-container",
        "section.job-desc", "div[class*='jobDescription']",
        # LinkedIn
        ".jobs-description-content", ".description__text",
        ".jobs-unified-top-card", ".jobs-description",
        # Indeed
        "#jobDescriptionText", ".jobsearch-jobDescriptionText",
        # Reed
        ".description", ".job-description",
        # Generic
        "[data-testid='job-description']", ".job-description",
        "article", "main",
    ]

    for selector in selectors:
        try:
            el = page.locator(selector).first
            if el.is_visible():
                text = el.inner_text()
                if len(text) > 100:
                    return text[:4000]  # Cap at 4k chars for LLM context
        except Exception:
            continue

    # Fallback: grab main body text
    try:
        body_text = page.inner_text("body")
        if body_text:
            return body_text[:3000]
    except Exception:
        pass

    return ""


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sample_jd = """
    Senior ML Engineer at TechCorp
    
    We're looking for a Senior Machine Learning Engineer with 5+ years of experience 
    to join our AI team. You'll design and deploy production ML systems.
    
    Requirements:
    - 5+ years ML/Deep Learning experience
    - Python, TensorFlow/PyTorch
    - Experience with LLMs and NLP
    - Production ML pipelines (MLflow, Kubeflow)
    - Strong CS fundamentals
    
    Salary: 45-60 LPA
    Location: Bengaluru (Hybrid)
    """

    sample_resume = {
        "skills_text": "Python, TensorFlow, PyTorch, NLP, LLMs, MLflow, Docker, Kubernetes",
        "experience_years": "5",
        "summary": "ML Engineer with 5 years building production ML systems",
        "experience": [
            {"title_company": "ML Engineer at DataCo", "dates": "2021-Present"},
            {"title_company": "Data Scientist at StartupX", "dates": "2019-2021"},
        ],
    }

    analysis = analyze_job(sample_jd, sample_resume)
    print(json.dumps(analysis.to_dict(), indent=2))
