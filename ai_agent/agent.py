#!/usr/bin/env python3
"""
Agent Core — The autonomous job application agent orchestrator.

This is the "brain" that ties together all AI components:
  - LLM Client (Ollama)
  - Agent Memory (SQLite)
  - JD Analyzer (job screening)
  - Smart Answerer (form filling)
  - Cover Letter Generator
  - Existing Playwright scripts (browser automation)

The agent operates in a loop:
  1. PERCEIVE: Browse job listings, extract JD text
  2. REASON: Analyze JD vs resume, decide APPLY/SKIP/REVIEW
  3. ACT: Fill forms, upload resume, answer questions, submit
  4. REFLECT: Log results, update memory, move to next job
"""

import os
import re
import sys
import time
import json
import random
import signal
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai_agent.llm_client import LLMClient, get_client
from ai_agent.agent_memory import AgentMemory
from ai_agent.jd_analyzer import analyze_job, extract_jd_text, JobAnalysis
from ai_agent.smart_answerer import answer_form_question, answer_chatbot_question
from ai_agent.cover_letter_gen import generate_cover_letter


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [agent] {msg}")


def _random_delay(lo: float = 1.0, hi: float = 3.0) -> None:
    time.sleep(random.uniform(lo, hi))


# ---------------------------------------------------------------------------
# Agent Configuration
# ---------------------------------------------------------------------------

DEFAULT_AGENT_CONFIG = {
    "agent_mode": "auto",            # "auto" | "review"
    "agent_min_match_score": 60,     # Skip below this
    "agent_platforms": ["naukri", "linkedin"],
    "agent_target_per_cycle": 20,
    "agent_ollama_model": "qwen3:8b",
    "agent_ollama_url": "http://localhost:11434",
    "agent_schedule_times": ["09:00", "14:00", "20:00"],
    "agent_dry_run": False,          # If True, don't actually submit
}


def load_agent_config() -> dict:
    """Load agent config from the main config.json."""
    config = dict(DEFAULT_AGENT_CONFIG)

    try:
        from config_loader import load_config, CONFIG_FILE
        main_config = load_config()

        # Merge agent-specific keys
        for key in DEFAULT_AGENT_CONFIG:
            if key in main_config:
                config[key] = main_config[key]

        # Also carry over credentials and resume path
        config["email"] = main_config.get("email", "")
        config["password"] = main_config.get("password", "")
        config["resume_path"] = main_config.get("resume_path", "")
        config["job_titles"] = main_config.get("job_titles", "ML Engineer, AI Engineer, Software Engineer")
        config["linkedin_email"] = main_config.get("linkedin_email", "")
        config["linkedin_password"] = main_config.get("linkedin_password", "")
        config["linkedin_phone"] = main_config.get("linkedin_phone", "")
        config["ctc_inr"] = main_config.get("ctc_inr", "2500000")

    except Exception as e:
        _log(f"Warning: Could not load main config: {e}")

    return config


# ---------------------------------------------------------------------------
# The Agent
# ---------------------------------------------------------------------------

class JobApplicationAgent:
    """
    The AI Agent. Runs autonomously in a loop:

    1. PERCEIVE: Browse job listings, extract JD text
    2. REASON: Analyze JD vs resume, decide APPLY/SKIP
    3. ACT: Fill forms, upload resume, answer questions, submit
    4. REFLECT: Log results, update memory, learn from errors
    """

    def __init__(
        self,
        config: Optional[dict] = None,
        memory: Optional[AgentMemory] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ):
        self.config = config or load_agent_config()
        self.memory = memory or AgentMemory()
        self._on_log = on_log

        # LLM client
        self.llm = LLMClient()

        # Resume data (parsed once)
        self._resume_data: Optional[dict] = None

        # State
        self._running = False
        self._stop_event = threading.Event()
        self._current_status = "idle"
        self._current_activity = ""

        # Stats for current run
        self._run_stats = {
            "jobs_found": 0,
            "jobs_analyzed": 0,
            "jobs_applied": 0,
            "jobs_skipped": 0,
            "jobs_error": 0,
        }

    def log(self, msg: str) -> None:
        """Log to stdout and optional callback."""
        _log(msg)
        if self._on_log:
            try:
                self._on_log(msg)
            except Exception:
                pass

    @property
    def status(self) -> dict:
        """Current agent status for the dashboard."""
        return {
            "running": self._running,
            "status": self._current_status,
            "activity": self._current_activity,
            "stats": dict(self._run_stats),
            "model": self.llm.model,
            "ollama_connected": self.llm.ping(),
        }

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _ensure_setup(self) -> bool:
        """Check that Ollama is running and model is available."""
        self.log("Checking Ollama connection...")
        if not self.llm.ping():
            self.log("ERROR: Ollama is not running! Start it with: ollama serve")
            self.log("Download from: https://ollama.com/download")
            return False

        self.log(f"Ollama connected. Checking model '{self.llm.model}'...")
        try:
            self.llm.ensure_model()
        except Exception as e:
            self.log(f"ERROR: Failed to load model: {e}")
            return False

        return True

    def _load_resume(self) -> dict:
        """Parse resume and cache the result."""
        if self._resume_data:
            return self._resume_data

        resume_path = self.config.get("resume_path", "")
        if not resume_path or not Path(resume_path).exists():
            self.log("WARNING: No resume path configured. Using empty resume data.")
            self._resume_data = {
                "full_name": "",
                "skills_text": self.config.get("job_titles", ""),
                "experience_years": "5",
            }
            return self._resume_data

        try:
            from resume_parser import parse_resume, get_form_data
            self._resume_data = parse_resume(resume_path)

            # Merge config overrides
            self._resume_data["ctc_inr"] = self.config.get("ctc_inr", "2500000")
            self._resume_data["notice_period"] = self.config.get("intl_notice_period", "60 days")
            self._resume_data["visa_status"] = self.config.get("intl_visa_status", "Require Sponsorship")
            self._resume_data["job_titles_text"] = self.config.get("job_titles", "")

            self.log(f"Resume loaded: {self._resume_data.get('full_name', 'Unknown')}")
            return self._resume_data
        except Exception as e:
            self.log(f"Resume parse error: {e}")
            self._resume_data = {"full_name": "", "skills_text": "", "experience_years": "5"}
            return self._resume_data

    # ------------------------------------------------------------------
    # Platform Runners
    # ------------------------------------------------------------------

    def run_cycle(
        self,
        platform: str = "naukri",
        target: int = 20,
        headless: bool = True,
        dry_run: bool = False,
    ) -> dict:
        """
        Run a single application cycle on one platform.

        Returns stats dict.
        """
        self._running = True
        self._current_status = "running"
        self._stop_event.clear()
        self._run_stats = {
            "jobs_found": 0, "jobs_analyzed": 0,
            "jobs_applied": 0, "jobs_skipped": 0, "jobs_error": 0,
        }

        run_id = self.memory.start_run(platform)

        try:
            # Setup
            if not self._ensure_setup():
                self.memory.end_run(run_id, status="failed")
                return self._run_stats

            resume_data = self._load_resume()

            self.log(f"Starting AI Agent cycle: platform={platform}, target={target}, "
                     f"mode={'dry_run' if dry_run else self.config.get('agent_mode', 'auto')}")

            # Dispatch to platform-specific runner
            if platform == "naukri":
                self._run_naukri_cycle(resume_data, target, headless, dry_run)
            elif platform == "linkedin":
                self._run_linkedin_cycle(resume_data, target, headless, dry_run)
            else:
                self.log(f"Platform '{platform}' not yet supported by AI agent")

            self.memory.end_run(
                run_id,
                jobs_found=self._run_stats["jobs_found"],
                jobs_analyzed=self._run_stats["jobs_analyzed"],
                jobs_applied=self._run_stats["jobs_applied"],
                jobs_skipped=self._run_stats["jobs_skipped"],
                jobs_error=self._run_stats["jobs_error"],
            )

        except Exception as e:
            self.log(f"Agent cycle error: {e}")
            self.memory.end_run(run_id, status="error")
        finally:
            self._running = False
            self._current_status = "idle"
            self._current_activity = ""

        self.log(f"Cycle complete: {json.dumps(self._run_stats)}")
        return self._run_stats

    # ------------------------------------------------------------------
    # Naukri Platform
    # ------------------------------------------------------------------

    def _run_naukri_cycle(
        self,
        resume_data: dict,
        target: int,
        headless: bool,
        dry_run: bool,
    ) -> None:
        """Run AI-powered application cycle on Naukri."""
        from playwright.sync_api import sync_playwright
        from playwright_helpers import launch_browser
        config = self.config
        email = config.get("email", "")
        password = config.get("password", "")

        if not email or not password:
            self.log("ERROR: Naukri credentials not configured")
            return

        job_titles = config.get("job_titles", "ML Engineer, AI Engineer")
        keywords = [t.strip() for t in job_titles.split(",") if t.strip()]

        with sync_playwright() as p:
            preferred = ["firefox", "webkit", "chromium"]
            engine, browser = launch_browser(p, headless=headless, preferred_engines=preferred, log=self.log)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()

            try:
                # Login
                self._current_activity = "Logging in to Naukri..."
                self.log("Logging in to Naukri...")
                self._naukri_login(page, email, password)

                # Search
                self._current_activity = "Searching for jobs..."
                self.log(f"Searching for: {', '.join(keywords)}")
                self._naukri_search(page, keywords)

                # Process jobs
                applied = 0
                page_num = 0
                max_pages = 10

                while applied < target and page_num < max_pages:
                    if self._stop_event.is_set():
                        self.log("Stop requested — ending cycle")
                        break

                    # Get job links on current page
                    job_urls = self._naukri_get_job_urls(page)
                    self._run_stats["jobs_found"] += len(job_urls)
                    self.log(f"Found {len(job_urls)} jobs on page {page_num + 1}")

                    for job_url in job_urls:
                        if applied >= target or self._stop_event.is_set():
                            break

                        # Dedup check
                        if self.memory.was_already_applied(job_url):
                            self.log(f"Already applied (skipping): {job_url[:60]}")
                            self._run_stats["jobs_skipped"] += 1
                            continue

                        # Open job in new tab and analyze
                        result = self._process_single_job(
                            context, job_url, resume_data,
                            platform="naukri", dry_run=dry_run,
                        )

                        if result == "applied":
                            applied += 1
                            self._run_stats["jobs_applied"] = applied
                            self.log(f"✓ Progress: {applied}/{target}")
                        elif result == "skipped":
                            self._run_stats["jobs_skipped"] += 1
                        elif result == "queued":
                            pass  # review mode
                        else:
                            self._run_stats["jobs_error"] += 1

                        _random_delay(2, 4)

                    # Next page
                    page_num += 1
                    if applied < target:
                        if not self._naukri_next_page(page, page_num):
                            self.log("No more pages")
                            break

            except Exception as e:
                self.log(f"Naukri cycle error: {e}")
            finally:
                browser.close()

    def _naukri_login(self, page, email: str, password: str) -> None:
        """Login to Naukri."""
        try:
            resp = page.goto("https://www.naukri.com/nlogin/login", timeout=60000, wait_until="domcontentloaded")
            if resp and resp.status == 403:
                raise Exception("Naukri returned HTTP 403. Use WebKit/Firefox for headless.")
        except Exception as e:
            if "NS_BINDING_ABORTED" not in str(e):
                self.log(f"Login navigation error: {e}")

        _random_delay(1, 2)
        page.wait_for_selector("#usernameField", state="visible", timeout=10000)
        page.fill("#usernameField", email)
        _random_delay(0.5, 1)
        page.fill("#passwordField", password)
        _random_delay(0.5, 1)
        page.click("button[type='submit'], button.blue-btn")
        
        try:
            page.wait_for_url("**/mnjuser/homepage**", timeout=30000)
        except Exception:
            self.log("Wait for homepage timeout, proceeding anyway...")
        self.log("Login successful")
        _random_delay(1, 2)

    def _naukri_search(self, page, keywords: list[str]) -> None:
        """Search for jobs on Naukri."""
        import urllib.parse
        encoded_query = "-".join([kw.lower().replace(" ", "-") for kw in keywords])
        search_url = f"https://www.naukri.com/{encoded_query}-jobs?k={encoded_query}&experience=5"
        
        try:
            page.goto(search_url, timeout=60000, wait_until="domcontentloaded")
        except Exception as e:
            if "NS_BINDING_ABORTED" not in str(e):
                self.log(f"Search navigation error: {e}")

        try:
            page.wait_for_selector(".srp-container", timeout=20000)
        except Exception:
            self.log("Warning: Could not verify search results loaded")
        _random_delay(2, 3)

    def _naukri_get_job_urls(self, page) -> list[str]:
        """Extract job URLs from search results page."""
        urls = []
        try:
            job_cards = page.locator("div.srp-jobtuple-wrapper a.title").all()
            for card in job_cards:
                try:
                    href = card.get_attribute("href")
                    if href and "naukri.com" in href:
                        urls.append(href)
                except Exception:
                    continue
        except Exception as e:
            self.log(f"Error getting job URLs: {e}")

        # Fallback: try other selectors
        if not urls:
            try:
                links = page.locator("a[class*='title']").all()
                for link in links:
                    href = link.get_attribute("href")
                    if href and "/job-listings" in href:
                        urls.append(href)
            except Exception:
                pass

        return urls

    def _naukri_next_page(self, page, page_num: int) -> bool:
        """Navigate to next page of results."""
        try:
            next_btn = page.locator(f"a.fright:has-text('{page_num + 1}')").first
            if next_btn.is_visible():
                next_btn.click()
                _random_delay(2, 4)
                return True
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------
    # LinkedIn Platform
    # ------------------------------------------------------------------

    def _run_linkedin_cycle(
        self,
        resume_data: dict,
        target: int,
        headless: bool,
        dry_run: bool,
    ) -> None:
        """Run AI-powered application cycle on LinkedIn."""
        from playwright.sync_api import sync_playwright
        config = self.config
        linkedin_email = config.get("linkedin_email", "")
        linkedin_password = config.get("linkedin_password", "")

        if not linkedin_email or not linkedin_password:
            self.log("ERROR: LinkedIn credentials not configured")
            return

        job_titles = config.get("job_titles", "ML Engineer, AI Engineer")
        keywords = [t.strip() for t in job_titles.split(",") if t.strip()]

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720},
                locale="en-US",
            )
            page = context.new_page()

            try:
                # Login
                self._current_activity = "Logging in to LinkedIn..."
                self._linkedin_login(page, linkedin_email, linkedin_password)

                # Search (Easy Apply filter via URL)
                self._current_activity = "Searching for jobs..."
                query = " OR ".join(keywords)
                encoded_query = query.replace(" ", "%20")
                search_url = (
                    f"https://www.linkedin.com/jobs/search/"
                    f"?f_AL=true&keywords={encoded_query}&location=India"
                )
                page.goto(search_url, timeout=60000, wait_until="domcontentloaded")
                _random_delay(3, 5)

                # Process jobs
                applied = 0
                pages_checked = 0

                while applied < target and pages_checked < 10:
                    if self._stop_event.is_set():
                        break

                    # Get job cards
                    job_cards = self._linkedin_get_job_cards(page)
                    self._run_stats["jobs_found"] += len(job_cards)

                    for card in job_cards:
                        if applied >= target or self._stop_event.is_set():
                            break

                        try:
                            # Click card to load details
                            card.click(timeout=2000)
                            _random_delay(1, 2)

                            # Extract JD text
                            jd_text = ""
                            try:
                                jd_el = page.locator(".jobs-description-content, .jobs-description").first
                                if jd_el.is_visible():
                                    jd_text = jd_el.inner_text()
                            except Exception:
                                pass

                            # Get job URL for dedup
                            job_url = page.url

                            if self.memory.was_already_applied(job_url):
                                self._run_stats["jobs_skipped"] += 1
                                continue

                            # REASON: Analyze with AI
                            self._current_activity = f"Analyzing job..."
                            self._run_stats["jobs_analyzed"] += 1

                            analysis = analyze_job(jd_text, resume_data, self.config, self.llm)

                            # Get job info for logging
                            job_title = ""
                            company = ""
                            try:
                                title_el = card.locator(".job-card-list__title, strong").first
                                job_title = title_el.inner_text(timeout=1000)
                            except Exception:
                                pass
                            try:
                                comp_el = card.locator(".job-card-container__company-name").first
                                company = comp_el.inner_text(timeout=1000)
                            except Exception:
                                pass

                            # Decision
                            min_score = self.config.get("agent_min_match_score", 60)
                            mode = self.config.get("agent_mode", "auto")

                            if analysis.match_score < min_score:
                                self.log(f"SKIP [{analysis.match_score}%]: {company} — {job_title}")
                                self.log(f"  Reason: {analysis.reasoning}")
                                self.memory.log_decision(
                                    job_url, "SKIP",
                                    job_title=job_title, company=company,
                                    platform="linkedin", match_score=analysis.match_score,
                                    reasoning=analysis.reasoning,
                                )
                                self._run_stats["jobs_skipped"] += 1
                                continue

                            if mode == "review":
                                self.log(f"QUEUE [{analysis.match_score}%]: {company} — {job_title}")
                                cover = generate_cover_letter(
                                    job_title, company, jd_text, resume_data, client=self.llm
                                )
                                self.memory.queue_for_review(
                                    job_url, job_title=job_title, company=company,
                                    platform="linkedin", match_score=analysis.match_score,
                                    reasoning=analysis.reasoning, jd_text=jd_text[:2000],
                                    cover_letter=cover,
                                )
                                continue

                            # AUTO mode: Apply
                            self.log(f"APPLY [{analysis.match_score}%]: {company} — {job_title}")
                            self.memory.log_decision(
                                job_url, "APPLY",
                                job_title=job_title, company=company,
                                platform="linkedin", match_score=analysis.match_score,
                                reasoning=analysis.reasoning,
                            )

                            if dry_run:
                                self.log(f"  [DRY RUN] Would apply to: {job_title}")
                                applied += 1
                                self._run_stats["jobs_applied"] = applied
                                continue

                            # ACT: Click Easy Apply and fill form
                            self._current_activity = f"Applying to {company}..."
                            success = self._linkedin_easy_apply(page, resume_data)

                            if success:
                                cover = generate_cover_letter(
                                    job_title, company, jd_text, resume_data, client=self.llm
                                )
                                self.memory.log_application(
                                    job_url, title=job_title, company=company,
                                    platform="linkedin", match_score=analysis.match_score,
                                    cover_letter=cover,
                                )
                                applied += 1
                                self._run_stats["jobs_applied"] = applied
                                self.log(f"✓ Applied: {applied}/{target}")
                            else:
                                self._run_stats["jobs_error"] += 1

                            _random_delay(2, 4)

                        except Exception as e:
                            self.log(f"Error processing LinkedIn job: {e}")
                            self._run_stats["jobs_error"] += 1
                            continue

                    # Next page
                    pages_checked += 1
                    try:
                        next_btn = page.locator("button[aria-label='View next page']").first
                        if next_btn.is_visible() and next_btn.is_enabled():
                            next_btn.click()
                            _random_delay(3, 5)
                        else:
                            break
                    except Exception:
                        break

            except Exception as e:
                self.log(f"LinkedIn cycle error: {e}")
            finally:
                browser.close()

    def _linkedin_login(self, page, email: str, password: str) -> None:
        """Login to LinkedIn."""
        page.goto("https://www.linkedin.com/login", timeout=60000)
        _random_delay(1, 2)

        for selector in ["#username", "#session_key", "[name='session_key']"]:
            try:
                page.wait_for_selector(selector, state="visible", timeout=3000)
                page.fill(selector, email)
                break
            except Exception:
                continue

        _random_delay(0.5, 1)

        for selector in ["#password", "#session_password", "[type='password']"]:
            try:
                page.fill(selector, password)
                break
            except Exception:
                continue

        _random_delay(0.5, 1)
        page.click("button[type='submit']")

        try:
            page.wait_for_url("**/feed/**", timeout=15000)
        except Exception:
            try:
                page.wait_for_url("**/jobs/**", timeout=5000)
            except Exception:
                if "checkpoint" in page.url:
                    self.log("LinkedIn verification required — please complete manually")

        self.log("LinkedIn login successful")
        _random_delay(1, 2)

    def _linkedin_get_job_cards(self, page) -> list:
        """Get job card elements from LinkedIn search results."""
        selectors = [
            "li.jobs-search-results__list-item",
            ".scaffold-layout__list-item",
            "div[data-job-id]",
        ]
        for selector in selectors:
            try:
                count = page.locator(selector).count()
                if count > 0:
                    return page.locator(selector).all()
            except Exception:
                continue
        return []

    def _linkedin_easy_apply(self, page, resume_data: dict) -> bool:
        """Handle LinkedIn Easy Apply with AI-powered form filling."""
        # Find Easy Apply button
        easy_apply_btn = None
        for sel in ["button.jobs-apply-button", "button:has-text('Easy Apply')"]:
            try:
                btn = page.locator(sel).first
                if btn.is_visible():
                    easy_apply_btn = btn
                    break
            except Exception:
                continue

        if not easy_apply_btn:
            return False

        # Check already applied
        try:
            if page.locator("button:has-text('Applied')").first.is_visible():
                return False
        except Exception:
            pass

        easy_apply_btn.click()
        _random_delay(1, 2)

        # Multi-step form handler
        start_time = time.time()
        max_time = 30

        for step in range(20):
            if time.time() - start_time > max_time:
                self.log("Timeline exceeded. Closing modal.")
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                return False

            _random_delay(0.5, 1)

            # Check success
            if (page.locator("h3:has-text('Application sent')").is_visible() or
                page.locator("span:has-text('Your application was sent')").is_visible()):
                try:
                    done_btn = page.locator("button:has-text('Done')").first
                    if done_btn.is_visible():
                        done_btn.click()
                except Exception:
                    pass
                return True

            # Fill form fields using AI
            self._ai_fill_form_fields(page, resume_data)

            # Click primary action button
            try:
                footer_btn = page.locator(
                    ".jobs-easy-apply-footer__actions .artdeco-button--primary"
                ).first
                if footer_btn.is_visible() and footer_btn.is_enabled():
                    btn_text = footer_btn.inner_text().strip()
                    footer_btn.click(timeout=1000)
                    _random_delay(1, 2)

                    # Quick success check after submit
                    if page.locator("button:has-text('Done')").is_visible():
                        page.locator("button:has-text('Done')").click()
                        return True
                    continue
            except Exception:
                pass

        # Close modal if still open
        try:
            page.locator("button[aria-label='Dismiss']").first.click()
        except Exception:
            pass

        return False

    # ------------------------------------------------------------------
    # AI-Powered Form Filling (used by all platforms)
    # ------------------------------------------------------------------

    def _ai_fill_form_fields(self, page, resume_data: dict) -> int:
        """Use AI to fill all visible form fields on the current page."""
        filled = 0

        # Text inputs
        try:
            inputs = page.locator(
                "input[type='text']:visible:not([disabled]),"
                "input[type='number']:visible:not([disabled]),"
                "input[type='tel']:visible:not([disabled]),"
                "input[type='email']:visible:not([disabled])"
            ).all()

            for inp in inputs:
                try:
                    if inp.input_value():
                        continue

                    # Build context
                    placeholder = (inp.get_attribute("placeholder") or "").strip()
                    label_text = ""
                    inp_id = inp.get_attribute("id") or ""
                    if inp_id:
                        try:
                            lbl = page.locator(f"label[for='{inp_id}']").first
                            if lbl.is_visible():
                                label_text = lbl.inner_text().strip()
                        except Exception:
                            pass

                    question = label_text or placeholder
                    if not question or "search" in question.lower():
                        continue

                    # Get AI answer
                    answer = answer_form_question(question, resume_data, client=self.llm)
                    if answer:
                        inp.fill(answer)
                        self.log(f"AI filled: '{question[:30]}' → '{answer[:30]}'")
                        filled += 1
                        _random_delay(1.5, 2.5)

                except Exception:
                    continue
        except Exception:
            pass

        # Textareas
        try:
            textareas = page.locator("textarea:visible").all()
            for ta in textareas:
                try:
                    if ta.input_value():
                        continue
                    label_text = ""
                    ta_id = ta.get_attribute("id") or ""
                    if ta_id:
                        try:
                            lbl = page.locator(f"label[for='{ta_id}']").first
                            label_text = lbl.inner_text().strip()
                        except Exception:
                            pass

                    question = label_text or (ta.get_attribute("placeholder") or "")
                    answer = answer_form_question(question, resume_data, client=self.llm)
                    if answer:
                        ta.fill(answer)
                        filled += 1
                except Exception:
                    continue
        except Exception:
            pass

        # Dropdowns
        try:
            selects = page.locator("select:visible").all()
            for select in selects:
                try:
                    current = select.input_value()
                    if current and "select" not in current.lower():
                        continue

                    options = [opt.inner_text().strip() for opt in select.locator("option").all()]
                    if len(options) <= 1:
                        continue

                    label_text = ""
                    sel_id = select.get_attribute("id") or ""
                    if sel_id:
                        try:
                            lbl = page.locator(f"label[for='{sel_id}']").first
                            label_text = lbl.inner_text().strip()
                        except Exception:
                            pass

                    question = label_text or "Select an option"
                    best_option = answer_form_question(
                        question, resume_data, options=options, client=self.llm
                    )
                    if best_option:
                        select.select_option(label=best_option)
                        filled += 1
                except Exception:
                    continue
        except Exception:
            pass

        # Radio buttons — select "Yes" for standard questions
        try:
            yes_labels = page.locator("label:has-text('Yes'):visible").all()
            for lbl in yes_labels[:3]:
                try:
                    lbl.click()
                    filled += 1
                except Exception:
                    pass
        except Exception:
            pass

        return filled

    # ------------------------------------------------------------------
    # General job processor (cross-platform)
    # ------------------------------------------------------------------

    def _process_single_job(
        self,
        context,
        job_url: str,
        resume_data: dict,
        platform: str = "naukri",
        dry_run: bool = False,
    ) -> str:
        """
        Process a single job: open → analyze → decide → act.

        Returns: "applied", "skipped", "queued", or "error"
        """
        new_page = None
        try:
            new_page = context.new_page()
            try:
                new_page.goto(job_url, timeout=45000, wait_until="domcontentloaded")
            except Exception as e:
                if "NS_BINDING_ABORTED" not in str(e):
                    raise
            _random_delay(1, 2)

            # PERCEIVE: Extract JD text
            self._current_activity = "Reading job description..."
            jd_text = extract_jd_text(new_page)
            self._run_stats["jobs_analyzed"] += 1

            # Get job title and company
            job_title = ""
            company = ""
            try:
                # Naukri selectors
                title_el = new_page.locator("h1, .jd-header-title").first
                if title_el.is_visible():
                    job_title = title_el.inner_text().strip()[:100]
            except Exception:
                pass
            try:
                comp_el = new_page.locator(".jd-header-comp-name a, .comp-name").first
                if comp_el.is_visible():
                    company = comp_el.inner_text().strip()[:50]
            except Exception:
                pass

            self.log(f"Analyzing: {company} — {job_title}")

            # REASON: AI analysis
            self._current_activity = f"AI analyzing: {company}"
            analysis = analyze_job(jd_text, resume_data, self.config, self.llm)

            min_score = self.config.get("agent_min_match_score", 60)
            mode = self.config.get("agent_mode", "auto")

            if analysis.match_score < min_score:
                self.log(f"SKIP [{analysis.match_score}%]: {company} — {job_title}")
                self.log(f"  Reason: {analysis.reasoning[:100]}")
                self.memory.log_decision(
                    job_url, "SKIP",
                    job_title=job_title, company=company,
                    platform=platform, match_score=analysis.match_score,
                    reasoning=analysis.reasoning,
                )
                new_page.close()
                return "skipped"

            if mode == "review":
                self.log(f"QUEUE [{analysis.match_score}%]: {company} — {job_title}")
                cover = generate_cover_letter(
                    job_title, company, jd_text, resume_data, client=self.llm
                )
                self.memory.queue_for_review(
                    job_url, job_title=job_title, company=company,
                    platform=platform, match_score=analysis.match_score,
                    reasoning=analysis.reasoning, jd_text=jd_text[:2000],
                    cover_letter=cover,
                )
                new_page.close()
                return "queued"

            # APPLY
            self.log(f"APPLY [{analysis.match_score}%]: {company} — {job_title}")
            self.memory.log_decision(
                job_url, "APPLY",
                job_title=job_title, company=company,
                platform=platform, match_score=analysis.match_score,
                reasoning=analysis.reasoning,
            )

            if dry_run:
                self.log(f"  [DRY RUN] Would apply to: {job_title}")
                new_page.close()
                return "applied"

            # ACT: Click Apply and fill the form
            self._current_activity = f"Applying to {company}..."

            # Find apply button
            apply_btn = None
            for sel in ["button.apply-button", "button#apply-button",
                        "button:has-text('Apply')"]:
                try:
                    btn = new_page.locator(sel).first
                    if btn.is_visible():
                        apply_btn = btn
                        break
                except Exception:
                    continue

            if not apply_btn:
                # Check already applied
                try:
                    if (new_page.locator("button:has-text('Already Applied')").first.is_visible() or
                        new_page.locator("button:has-text('Applied')").first.is_visible()):
                        self.log("Already applied")
                        new_page.close()
                        return "skipped"
                except Exception:
                    pass
                self.log("No Apply button found")
                new_page.close()
                return "error"

            # Check for external apply
            btn_text = apply_btn.inner_text().lower()
            if "company" in btn_text or "website" in btn_text:
                self.log("External apply — using form filler...")
                try:
                    from intl_form_filler import fill_career_form
                    user_data = dict(resume_data or {})
                    job_titles_text = self.config.get("job_titles", "")
                    try:
                        from ppp_converter import get_salary_for_form
                        expected_salary = get_salary_for_form(
                            float(self.config.get("ctc_inr", 2500000) or 2500000),
                            self.config.get("region_intl_crawler", "European"),
                        )
                    except Exception:
                        expected_salary = str(self.config.get("intl_expected_salary_gbp", "60000"))
                    user_data.update({
                        "full_name": user_data.get("full_name") or self.config.get("intl_full_name", ""),
                        "email": self.config.get("linkedin_email") or self.config.get("email", ""),
                        "phone": self.config.get("linkedin_phone", ""),
                        "location": self.config.get("intl_location", "Bengaluru, India"),
                        "expected_salary": expected_salary,
                        "expected_salary_gbp": expected_salary,
                        "notice_period": self.config.get("intl_notice_period", "60 days"),
                        "visa_status": self.config.get("intl_visa_status", "Require Sponsorship"),
                        "job_titles_text": job_titles_text,
                        "job_titles": [t.strip() for t in job_titles_text.split(",") if t.strip()],
                        "resume_path": self.config.get("resume_path", ""),
                    })
                    
                    # Try to get href directly
                    href = apply_btn.get_attribute("href")
                    if not href:
                        href = apply_btn.evaluate("el => el.closest('a') ? el.closest('a').href : null")
                    
                    if href:
                        self.log(f"Found external link: {href[:60]}...")
                        external_page = context.new_page()
                        try:
                            external_page.goto(href, timeout=45000, wait_until="domcontentloaded")
                        except Exception:
                            pass
                    else:
                        self.log("No href found, falling back to click()...")
                        pages_before = context.pages
                        apply_btn.click()
                        _random_delay(3, 4)
                        pages_after = context.pages
                        
                        if len(pages_after) > len(pages_before):
                            external_page = pages_after[-1]
                            self.log("Successfully detected new tab for external site.")
                        else:
                            external_page = new_page
                            self.log("No new tab detected. Checking if redirected...")

                        try:
                            external_page.wait_for_load_state("domcontentloaded", timeout=15000)
                        except Exception:
                            pass
                    _random_delay(2, 3)
                    success = fill_career_form(external_page, user_data)
                    if external_page != new_page:
                        external_page.close()
                        
                    if success:
                        cover = generate_cover_letter(
                            job_title, company, jd_text, resume_data, client=self.llm
                        )
                        self.memory.log_application(
                            job_url, title=job_title, company=company,
                            platform=platform, match_score=analysis.match_score,
                            cover_letter=cover,
                        )
                        new_page.close()
                        return "applied"
                except Exception as e:
                    self.log(f"External apply failed: {e}")
                new_page.close()
                return "error"

            # Native apply
            apply_btn.click()
            _random_delay(1, 2)

            # Handle chatbot / modal with AI
            success = self._handle_naukri_modal(new_page, context, resume_data)

            if success:
                cover = generate_cover_letter(
                    job_title, company, jd_text, resume_data, client=self.llm
                )
                self.memory.log_application(
                    job_url, title=job_title, company=company,
                    platform=platform, match_score=analysis.match_score,
                    cover_letter=cover,
                )
                new_page.close()
                return "applied"

            new_page.close()
            return "error"

        except Exception as e:
            self.log(f"Error processing job: {e}")
            if new_page:
                try:
                    new_page.close()
                except Exception:
                    pass
            return "error"

    def _handle_naukri_modal(self, page, context, resume_data: dict) -> bool:
        """Handle Naukri's apply modal/chatbot with AI-powered answers."""
        start_time = time.time()
        max_time = 30

        for attempt in range(15):
            if time.time() - start_time > max_time:
                self.log("Modal timeout")
                return False

            _random_delay(1, 2)

            # Check success
            if (page.locator("text=applied successfully").is_visible() or
                page.locator("text=Application sent").is_visible()):
                self.log("Application successful!")
                return True

            # Check for Applied status
            if page.locator("button:has-text('Applied')").first.is_visible():
                return True

            # Get conversation context for chatbot
            full_context = ""
            try:
                chat_el = page.locator("div[class*='chatbot']").first
                if chat_el.is_visible():
                    full_context = chat_el.inner_text()
            except Exception:
                pass

            # AI-powered chatbot input
            chatbot_input = None
            for sel in ["input[placeholder*='Type message']",
                        "div[class*='chatbot'] input",
                        "div[class*='chatbot'] textarea",
                        "[contenteditable]"]:
                try:
                    inp = page.locator(sel).first
                    if inp.is_visible():
                        chatbot_input = inp
                        break
                except Exception:
                    continue

            if chatbot_input:
                is_empty = True
                try:
                    tag = chatbot_input.evaluate("el => el.tagName")
                    if tag in ["INPUT", "TEXTAREA"]:
                        is_empty = not chatbot_input.input_value()
                    else:
                        is_empty = not chatbot_input.inner_text().strip()
                except Exception:
                    pass

                if is_empty and full_context:
                    answer = answer_chatbot_question(
                        full_context, resume_data, client=self.llm
                    )
                    if answer:
                        try:
                            chatbot_input.click(force=True)
                            chatbot_input.fill(answer)
                            self.log(f"AI chatbot answer: {answer[:50]}")
                        except Exception:
                            try:
                                chatbot_input.click(force=True)
                                page.keyboard.type(answer)
                            except Exception:
                                pass

            # Fill other form fields
            self._ai_fill_form_fields(page, resume_data)

            # Handle radio/chip options in chatbot
            try:
                chatbot_layer = page.locator("div[class*='chatbot']").first
                if chatbot_layer.is_visible():
                    # Get all option-like elements
                    option_els = chatbot_layer.locator(
                        "label, div[class*='chip'], div[class*='option']"
                    ).all()

                    visible_options = []
                    for opt in option_els:
                        if opt.is_visible():
                            txt = opt.inner_text().strip()
                            if txt and len(txt) < 30:
                                visible_options.append((opt, txt))

                    if visible_options:
                        # Use AI to pick the best option
                        option_texts = [t for _, t in visible_options]
                        best = answer_form_question(
                            full_context[-200:] if full_context else "Select the best option",
                            resume_data,
                            options=option_texts,
                            client=self.llm,
                        )
                        # Click the matching option
                        for opt_el, opt_txt in visible_options:
                            if opt_txt == best:
                                opt_el.click(force=True)
                                self.log(f"AI selected option: {opt_txt}")
                                break
            except Exception:
                pass

            # Click send/submit/save buttons
            send_btn = page.locator("div.sendMsg").first
            if send_btn.is_visible():
                try:
                    send_btn.click(force=True)
                    _random_delay(2, 3)
                except Exception:
                    pass

            for sel in ["button:has-text('Save')", "button:has-text('Submit')",
                        "button:has-text('Continue')", "button:has-text('Apply')",
                        "button:has-text('Apply without update')"]:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible():
                        cls = btn.get_attribute("class") or ""
                        if "save-job" in cls.lower() or "savejob" in cls.lower():
                            continue
                        btn.click()
                        _random_delay(1, 2)
                        break
                except Exception:
                    continue

        return False

    # ------------------------------------------------------------------
    # Stop / Daemon
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Request the agent to stop after current job."""
        self._stop_event.set()
        self._current_status = "stopping"
        self.log("Stop requested — will finish current job and stop")

    def run_daemon(
        self,
        schedule_times: Optional[list[str]] = None,
        headless: bool = True,
    ) -> None:
        """
        Run as a daemon with scheduled cycles.
        Blocks indefinitely until Ctrl+C.
        """
        times = schedule_times or self.config.get(
            "agent_schedule_times", ["09:00", "14:00", "20:00"]
        )
        platforms = self.config.get("agent_platforms", ["naukri", "linkedin"])
        target = self.config.get("agent_target_per_cycle", 20)

        self.log(f"Starting daemon: platforms={platforms}, schedule={times}")
        self.log("Press Ctrl+C to stop")

        # Handle graceful shutdown
        def _signal_handler(sig, frame):
            self.log("Shutdown signal received")
            self.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        while not self._stop_event.is_set():
            now = datetime.now()
            current_time = now.strftime("%H:%M")

            if current_time in times:
                self.log(f"Scheduled run at {current_time}")
                for platform in platforms:
                    if self._stop_event.is_set():
                        break
                    self.run_cycle(
                        platform=platform,
                        target=target,
                        headless=headless,
                    )
                # Sleep past this minute to avoid re-triggering
                time.sleep(65)
            else:
                # Check every 30 seconds
                time.sleep(30)
