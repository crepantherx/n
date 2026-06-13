#!/usr/bin/env python3
"""
Smart Answerer — LLM-powered form question answering.

Replaces hardcoded if/elif chains with intelligent reasoning.
The LLM reads the question, considers the candidate's resume and
job context, and provides the best answer.
"""

import re
from datetime import datetime
from typing import Optional

from .llm_client import LLMClient, SYSTEM_PROMPTS, get_client


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [answerer] {msg}")


# ---------------------------------------------------------------------------
# Fast-path answers (no LLM needed for common patterns)
# ---------------------------------------------------------------------------

# These are deterministic answers that don't need AI reasoning.
# Speeds up form filling by avoiding LLM calls for trivial questions.

FAST_PATH_PATTERNS = {
    # Experience (numeric)
    r"(?:years?|yrs?)\s*(?:of\s+)?(?:exp|experience)": lambda data: data.get("experience_years", "5"),
    r"(?:total|overall)\s*(?:exp|experience)": lambda data: data.get("experience_years", "5"),

    # Phone / mobile
    r"\b(?:phone|mobile|cell|contact)\s*(?:number|no)?": lambda data: data.get("phone", ""),

    # Email
    r"\bemail\b": lambda data: data.get("email", ""),

    # Name
    r"\bfull\s*name\b": lambda data: data.get("full_name", ""),
    r"\bfirst\s*name\b": lambda data: data.get("first_name", ""),
    r"\blast\s*name\b": lambda data: data.get("last_name", ""),

    # Location / city
    r"\b(?:current\s+)?(?:city|location|residing)\b": lambda data: data.get("location", "Bengaluru"),

    # Notice period
    r"\bnotice\s*period\b": lambda data: data.get("notice_period", "60 days"),

    # LinkedIn
    r"\blinkedin\b": lambda data: data.get("linkedin_url", ""),

    # GitHub
    r"\bgithub\b": lambda data: data.get("github_url", ""),
}


def _try_fast_path(question: str, user_data: dict) -> Optional[str]:
    """Try to answer without LLM using pattern matching."""
    q = question.lower().strip()

    for pattern, resolver in FAST_PATH_PATTERNS.items():
        if re.search(pattern, q, re.IGNORECASE):
            value = resolver(user_data)
            if value:
                _log(f"Fast-path answer for '{q[:40]}': {str(value)[:30]}")
                return str(value)

    return None


# ---------------------------------------------------------------------------
# Option selection (radio/dropdown)
# ---------------------------------------------------------------------------

def _select_best_option(
    question: str,
    options: list[str],
    user_data: dict,
    client: Optional[LLMClient] = None,
) -> str:
    """Use LLM to select the best option from a list."""
    llm = client or get_client()

    skills = user_data.get("skills_text", "")
    experience = user_data.get("experience_years", "5")

    prompt = f"""You are filling a job application form. Select the BEST option for this question.

QUESTION: {question}

OPTIONS:
{chr(10).join(f'  {i+1}. {opt}' for i, opt in enumerate(options))}

CANDIDATE INFO:
- Experience: {experience} years
- Skills: {skills[:200]}
- Location: {user_data.get('location', 'Bengaluru, India')}
- Notice Period: {user_data.get('notice_period', '60 days')}
- Visa: {user_data.get('visa_status', 'Require Sponsorship')}

Respond with ONLY the exact text of the best option. Nothing else."""

    try:
        response = llm.ask(
            prompt,
            system=SYSTEM_PROMPTS["form_answerer"],
            temperature=0.1,
        )

        # Try to match response to an option (fuzzy)
        response_clean = response.strip().strip('"').strip("'").lower()

        # Exact match
        for opt in options:
            if opt.lower() == response_clean:
                return opt

        # Partial match
        for opt in options:
            if response_clean in opt.lower() or opt.lower() in response_clean:
                return opt

        # Number match (LLM might respond with "1" or "Option 1")
        try:
            idx = int(re.search(r'\d+', response_clean).group()) - 1
            if 0 <= idx < len(options):
                return options[idx]
        except (AttributeError, ValueError):
            pass

        # Fallback: return first option that contains "yes" if any
        for opt in options:
            if "yes" in opt.lower():
                return opt

        # Last resort: return the LLM response directly
        _log(f"Could not match LLM response '{response[:50]}' to options, using first option")
        return options[0] if options else response

    except Exception as e:
        _log(f"LLM option selection failed: {e}")
        # Fallback heuristics
        for opt in options:
            if "yes" in opt.lower():
                return opt
        return options[0] if options else "Yes"


# ---------------------------------------------------------------------------
# Main answering function
# ---------------------------------------------------------------------------

def answer_form_question(
    question_text: str,
    user_data: dict,
    job_context: Optional[dict] = None,
    options: Optional[list[str]] = None,
    client: Optional[LLMClient] = None,
) -> str:
    """
    Answer a job application form question intelligently.

    Args:
        question_text: The question from the form (label, placeholder, etc.)
        user_data: Parsed resume data + config overrides
        job_context: Optional context about the job being applied to
        options: If provided, select from these options (radio/dropdown)
        client: LLM client (uses default if None)

    Returns:
        The answer string to fill into the form field.
    """
    if not question_text or not question_text.strip():
        return ""

    # If options are provided, use option selection
    if options and len(options) > 0:
        return _select_best_option(question_text, options, user_data, client)

    # Try fast path first (no LLM call needed)
    fast_answer = _try_fast_path(question_text, user_data)
    if fast_answer:
        return fast_answer

    # Use LLM for complex questions
    llm = client or get_client()
    job_ctx = job_context or {}

    skills = user_data.get("skills_text", "")
    experience = user_data.get("experience_years", "5")
    summary = user_data.get("summary", "")
    salary = user_data.get("expected_salary_gbp", "60000")
    ctc = user_data.get("ctc_inr", "2500000")

    prompt = f"""Answer this job application question for the candidate.

QUESTION: {question_text}

CANDIDATE PROFILE:
- Name: {user_data.get('full_name', '')}
- Experience: {experience} years
- Skills: {skills[:300]}
- Summary: {summary[:200]}
- Location: {user_data.get('location', 'Bengaluru, India')}
- Notice Period: {user_data.get('notice_period', '60 days')}
- Expected CTC: {ctc} INR / {salary} GBP annually
- Visa Status: {user_data.get('visa_status', 'Require Sponsorship')}

JOB CONTEXT:
- Title: {job_ctx.get('title', 'Not specified')}
- Company: {job_ctx.get('company', 'Not specified')}

RULES:
- If the question asks for a NUMBER, respond with ONLY the number.
- If the question is YES/NO, respond with ONLY "Yes" or "No".
- For text answers, be concise (1-2 sentences max).
- Never fabricate information not present in the candidate's profile.
- If the question asks about willingness to relocate, answer "Yes".
- If the question asks about authorization to work, answer "Yes".
- If the question asks about competitors/conflicts, answer "No".
- For salary questions: provide the CTC number unless the format is clear."""

    try:
        response = llm.ask(
            prompt,
            system=SYSTEM_PROMPTS["form_answerer"],
            temperature=0.2,
        )

        answer = response.strip()

        # Post-process: clean up common LLM response artifacts
        # Remove markdown, quotes, etc.
        answer = answer.strip('"').strip("'").strip("`")
        if answer.startswith("Answer:"):
            answer = answer[7:].strip()

        _log(f"LLM answer for '{question_text[:40]}': {answer[:50]}")
        return answer

    except ConnectionError:
        return _fallback_answer(question_text, user_data)
    except Exception as e:
        _log(f"Smart answer failed: {e}")
        return _fallback_answer(question_text, user_data)


def _fallback_answer(question: str, user_data: dict) -> str:
    """Hardcoded fallback when LLM is unavailable."""
    q = question.lower()

    if any(k in q for k in ["salary", "ctc", "compensation"]):
        return user_data.get("ctc_inr", "2500000")
    elif any(k in q for k in ["experience", "years"]):
        return user_data.get("experience_years", "5")
    elif any(k in q for k in ["location", "city"]):
        return user_data.get("location", "Bengaluru")
    elif any(k in q for k in ["notice"]):
        return user_data.get("notice_period", "60 days")
    elif any(k in q for k in ["relocate", "authorized", "willing"]):
        return "Yes"
    elif any(k in q for k in ["competitor", "conflict"]):
        return "No"
    else:
        summary = user_data.get("summary", "")
        if summary:
            return summary[:200]
        return f"I have {user_data.get('experience_years', '5')} years of experience in {user_data.get('skills_text', 'software engineering')[:100]}."


# ---------------------------------------------------------------------------
# Bulk answerer for chatbot-style forms
# ---------------------------------------------------------------------------

def answer_chatbot_question(
    conversation_context: str,
    user_data: dict,
    client: Optional[LLMClient] = None,
) -> str:
    """
    Answer a chatbot-style question where the question is embedded
    in a conversation context (like Naukri's chatbot).

    Args:
        conversation_context: The recent conversation text from the chatbot
        user_data: Candidate data

    Returns:
        The answer to type into the chatbot.
    """
    llm = client or get_client()

    prompt = f"""You are filling out a chatbot-style job application form.
Read the conversation below and provide the NEXT answer the candidate should give.

CONVERSATION:
{conversation_context[-800:]}

CANDIDATE PROFILE:
- Experience: {user_data.get('experience_years', '5')} years
- Skills: {user_data.get('skills_text', '')[:200]}
- Location: {user_data.get('location', 'Bengaluru')}
- Notice Period: {user_data.get('notice_period', '60 days')}
- Expected CTC: {user_data.get('ctc_inr', '2500000')} INR annually
- Visa: {user_data.get('visa_status', 'Require Sponsorship')}

RULES:
- Read the LAST question/message in the conversation carefully.
- If asking for a number (years, salary), respond with ONLY the number.
- If asking yes/no, respond with ONLY "Yes" or "No".
- For text, keep it brief (1-2 sentences).
- Respond with ONLY the answer text, nothing else."""

    try:
        response = llm.ask(
            prompt,
            system=SYSTEM_PROMPTS["form_answerer"],
            temperature=0.2,
        )
        answer = response.strip().strip('"').strip("'")
        _log(f"Chatbot answer: {answer[:60]}")
        return answer

    except Exception as e:
        _log(f"Chatbot answer failed: {e}")
        # Analyze context for fallback
        ctx = conversation_context.lower()
        if "experience" in ctx or "years" in ctx:
            return user_data.get("experience_years", "5")
        elif "salary" in ctx or "ctc" in ctx:
            return user_data.get("ctc_inr", "2500000")
        elif "notice" in ctx or "joining" in ctx:
            return user_data.get("notice_period", "60 days")
        elif "location" in ctx or "city" in ctx:
            return user_data.get("location", "Bengaluru")
        return "Yes"


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    user = {
        "full_name": "Sudhir Singh",
        "experience_years": "5",
        "skills_text": "Python, ML, TensorFlow, PyTorch",
        "location": "Bengaluru, India",
        "notice_period": "60 days",
        "ctc_inr": "2500000",
    }

    # Test fast path
    print("Experience:", answer_form_question("How many years of experience do you have?", user))
    print("Location:", answer_form_question("What is your current city?", user))

    # Test option selection
    print("Relocate:", answer_form_question(
        "Are you willing to relocate?", user, options=["Yes", "No"]
    ))
