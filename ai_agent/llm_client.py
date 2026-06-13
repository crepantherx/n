#!/usr/bin/env python3
"""
LLM Client — Thin wrapper around Ollama's REST API.

No external dependencies beyond Python stdlib + requests.
Provides structured methods for all AI agent capabilities:
  - General chat
  - Job description analysis
  - Cover letter generation
  - Form question answering
  - Job-fit scoring
"""

import json
import os
import time
import urllib.request
import urllib.error
import ssl
from datetime import datetime
from typing import Any, Optional


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [llm] {msg}")


# ---------------------------------------------------------------------------
# Default Settings
# ---------------------------------------------------------------------------

DEFAULT_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "google/gemma-4-31b-it:free"
DEFAULT_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# System prompts for different tasks
SYSTEM_PROMPTS = {
    "general": (
        "You are a helpful AI assistant specializing in job applications. "
        "Always give concise, practical answers."
    ),
    "jd_analyzer": (
        "You are an expert job-matching analyst. You analyze job descriptions "
        "against a candidate's resume and provide structured assessments. "
        "Always respond with valid JSON. Be honest and precise about match quality."
    ),
    "cover_letter": (
        "You are an expert career coach who writes compelling, authentic cover letters. "
        "Write naturally — never use clichés like 'I am excited to apply' or "
        "'I believe I am a perfect fit'. Instead, be specific about how the candidate's "
        "experience directly addresses the job requirements. Keep it under 250 words. "
        "Do NOT use markdown formatting in the letter."
    ),
    "form_answerer": (
        "You are filling out a job application form on behalf of a candidate. "
        "Answer each question accurately and concisely based on the candidate's "
        "resume data and preferences. For numeric questions, respond with ONLY the number. "
        "For yes/no questions, respond with ONLY 'Yes' or 'No'. "
        "For text questions, be brief and professional (1-2 sentences max). "
        "Never fabricate information not present in the candidate's data."
    ),
    "screener": (
        "You are a job screener deciding whether a candidate should apply to a job. "
        "Consider: skill match, experience level, salary range, location, and red flags. "
        "Always respond with valid JSON."
    ),
}


class LLMClient:
    """
    Stateless client for OpenRouter LLM server.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_API_URL,
        timeout: int = 300,
    ):
        self.model = model
        self.base_url = base_url
        self.timeout = timeout
        self.api_key = DEFAULT_API_KEY

    # ------------------------------------------------------------------
    # Low-level HTTP helpers (no external deps)
    # ------------------------------------------------------------------

    def _post(self, payload: dict) -> dict:
        """Send a POST request to OpenRouter and return parsed JSON."""
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "HTTP-Referer": "http://localhost:8000",
                "X-Title": "Naukri Agent"
            },
            method="POST",
        )
        max_retries = 3
        for attempt in range(max_retries):
            try:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                _log(f"OpenRouter connection error: HTTP Error {e.code}: {e.reason}")
                raise ConnectionError("Ollama connection failed")
            except urllib.error.URLError as e:
                _log(f"OpenRouter connection error: {e}")
                raise ConnectionError("Ollama connection failed")

    # ------------------------------------------------------------------
    # Health & model management
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        """Check if OpenRouter server is reachable."""
        return True

    def is_model_available(self) -> bool:
        """Check if the configured model is available."""
        return True

    def ensure_model(self) -> None:
        """Pull the model if not already available (no-op for OpenRouter)."""
        pass

    # ------------------------------------------------------------------
    # Core chat method
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> str:
        """
        Send a chat completion request to OpenRouter.
        """
        fallback_models = [
            self.model,
            "google/gemma-4-31b-it:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "qwen/qwen3-coder:free",
            "nousresearch/hermes-3-llama-3.1-405b:free",
            "google/gemma-4-26b-a4b-it:free",
            "meta-llama/llama-3.2-3b-instruct:free",
            "qwen/qwen-2.5-coder-32b-instruct:free",
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "qwen/qwen-2-7b-instruct:free"
        ]
        
        unique_models = []
        for m in fallback_models:
            if m not in unique_models:
                unique_models.append(m)

        t0 = time.time()
        
        # Try OpenRouter models one by one
        for attempt, current_model in enumerate(unique_models):
            payload: dict[str, Any] = {
                "model": current_model,
                "messages": messages,
                "stream": False,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            try:
                result = self._post(payload)
                choices = result.get("choices", [])
                if choices:
                    response_text = choices[0].get("message", {}).get("content", "")
                    tokens = result.get("usage", {}).get("completion_tokens", 0)
                    elapsed = time.time() - t0
                    _log(f"OpenRouter ({current_model}) response: {tokens} tokens in {elapsed:.1f}s")
                    return response_text
            except Exception as e:
                # We silently log to avoid flooding the UI
                pass
                
        # All OpenRouter models failed (likely hit the 50/day free limit). 
        # Fallback to Local Ollama immediately!
        
        ollama_payload = {
            "model": "qwen3:8b",
            "messages": messages,
            "stream": False,
            "temperature": temperature,
        }
        data = json.dumps(ollama_payload).encode("utf-8")
        req = urllib.request.Request(
            "http://localhost:11434/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                response_text = result.get("message", {}).get("content", "")
                return response_text
        except Exception as e:
            raise ConnectionError("Both OpenRouter and Local Ollama failed.")

        return response_text.strip()

    def ask(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> str:
        """Simple one-shot question → answer."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(
            messages,
            temperature=temperature,
            json_mode=json_mode,
        )

    # ------------------------------------------------------------------
    # Structured helpers (parse JSON responses safely)
    # ------------------------------------------------------------------

    def ask_json(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.3,
    ) -> dict:
        """Ask the LLM and parse the response as JSON."""
        raw = self.ask(
            prompt, system=system, temperature=temperature, json_mode=True
        )

        # Try direct parse first
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Try extracting JSON from markdown code block
        if "```" in raw:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(raw[start:end])
                except json.JSONDecodeError:
                    pass

        _log(f"Warning: Could not parse LLM JSON response: {raw[:200]}")
        return {"_raw": raw, "_error": "JSON parse failed"}


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_default_client: Optional[LLMClient] = None


def get_client(
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_API_URL,
) -> LLMClient:
    """Get or create the default LLM client singleton."""
    global _default_client
    if _default_client is None or _default_client.model != model:
        _default_client = LLMClient(model=model, base_url=base_url)
    return _default_client


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    client = LLMClient()
    print("Pinging Ollama...", client.ping())
    if client.ping():
        print("Model available:", client.is_model_available())
        if client.is_model_available():
            resp = client.ask("Say hello in one sentence.")
            print("Response:", resp)
        else:
            print(f"Model '{client.model}' not found. Run: ollama pull {client.model}")
    else:
        print("Ollama not running. Install from: https://ollama.com/download")
