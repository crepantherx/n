#!/usr/bin/env python3
"""
Cover Letter Generator — Creates unique, tailored cover letters per job.

Uses the local LLM to generate authentic cover letters that:
  - Reference specific requirements from the job description
  - Highlight matching skills from the candidate's resume
  - Sound human and natural (not template-y)
  - Are unique per application
"""

from datetime import datetime
from typing import Optional

from .llm_client import LLMClient, SYSTEM_PROMPTS, get_client


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [cover-letter] {msg}")


def generate_cover_letter(
    job_title: str,
    company: str,
    jd_text: str,
    resume_data: dict,
    *,
    tone: str = "professional",
    max_words: int = 250,
    client: Optional[LLMClient] = None,
) -> str:
    """
    Generate a tailored cover letter for a specific job.

    Args:
        job_title: The job title (e.g., "Senior ML Engineer")
        company: The company name
        jd_text: The job description text
        resume_data: Parsed resume data from resume_parser.py
        tone: "professional", "conversational", or "formal"
        max_words: Maximum word count
        client: LLM client (uses default if None)

    Returns:
        The generated cover letter text (plain text, no markdown).
    """
    llm = client or get_client()

    skills = resume_data.get("skills_text", "")
    experience = resume_data.get("experience_years", "5")
    full_name = resume_data.get("full_name", "")
    summary = resume_data.get("summary", "")

    # Recent experience for context
    exp_entries = resume_data.get("experience", [])
    recent_exp = ""
    if exp_entries and isinstance(exp_entries, list):
        for entry in exp_entries[:2]:
            tc = entry.get("title_company", "")
            desc = entry.get("description", "")
            if tc:
                recent_exp += f"  - {tc}: {desc[:100]}\n"

    tone_instruction = {
        "professional": "Write in a professional but warm tone. Be confident without being arrogant.",
        "conversational": "Write in a friendly, conversational tone. Be approachable and genuine.",
        "formal": "Write in a formal, traditional business letter tone.",
    }.get(tone, "Write in a professional tone.")

    prompt = f"""Write a cover letter for this job application.

JOB:
- Title: {job_title}
- Company: {company}
- Description: {jd_text[:1500]}

CANDIDATE:
- Name: {full_name}
- Experience: {experience} years
- Key Skills: {skills[:300]}
- Summary: {summary[:200]}
- Recent Work:
{recent_exp or '  (Not provided)'}

REQUIREMENTS:
1. {tone_instruction}
2. Maximum {max_words} words.
3. Start with "Dear Hiring Manager," (or the team name if known from the JD).
4. DO NOT use any of these clichés:
   - "I am excited to apply"
   - "I believe I am a perfect fit"
   - "I am writing to express my interest"
   - "With great enthusiasm"
5. Instead, OPEN with something specific — reference a project, technology, or aspect of the job that genuinely connects to the candidate's experience.
6. Mention 2-3 specific skills from the candidate's profile that match the JD requirements.
7. End with a confident closing (not "I look forward to hearing from you").
8. Sign off with just the candidate's name.
9. Output ONLY the cover letter text. No markdown, no subject line, no extra formatting."""

    try:
        letter = llm.ask(
            prompt,
            system=SYSTEM_PROMPTS["cover_letter"],
            temperature=0.8,  # Higher creativity for unique letters
        )

        # Clean up
        letter = letter.strip()

        # Remove any markdown formatting the LLM might add
        letter = letter.replace("**", "").replace("*", "")
        if letter.startswith("```"):
            lines = letter.split("\n")
            letter = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

        _log(f"Generated cover letter for {company} ({len(letter.split())} words)")
        return letter

    except ConnectionError:
        pass
        return _template_cover_letter(job_title, company, resume_data)
    except Exception as e:
        _log(f"Cover letter generation failed: {e}")
        return _template_cover_letter(job_title, company, resume_data)


def _template_cover_letter(
    job_title: str,
    company: str,
    resume_data: dict,
) -> str:
    """Fallback template when LLM is unavailable."""
    name = resume_data.get("full_name", "")
    exp = resume_data.get("experience_years", "5")
    skills = resume_data.get("skills_text", "software engineering")[:150]

    return (
        f"Dear Hiring Manager,\n\n"
        f"I am applying for the {job_title} position at {company}. "
        f"With {exp} years of experience in {skills}, "
        f"I bring a strong technical foundation that aligns with your team's needs.\n\n"
        f"My recent work has focused on building production-grade systems, "
        f"and I am keen to bring this expertise to {company}. "
        f"I am available to discuss my background in more detail at your convenience.\n\n"
        f"Best regards,\n{name}"
    )


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    resume = {
        "full_name": "Sudhir Singh",
        "experience_years": "5",
        "skills_text": "Python, TensorFlow, PyTorch, NLP, LLMs, MLflow",
        "summary": "ML Engineer building production ML systems",
        "experience": [
            {"title_company": "ML Engineer at DataCo", "description": "Built ML pipelines"},
        ],
    }

    letter = generate_cover_letter(
        "Senior ML Engineer",
        "TechCorp",
        "Looking for experienced ML engineer with Python and LLM experience",
        resume,
    )
    print(letter)
