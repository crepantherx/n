#!/usr/bin/env python3
"""
International Career Page Crawler

A powerful standalone module designed to find jobs directly on company career pages
across the internet (focusing on Europe and remote roles) and apply using the form filler.
"""

import os
import sys
import time
import time
import random
import urllib.parse
from datetime import datetime, date
from pathlib import Path
from playwright.sync_api import sync_playwright
from config_loader import load_config, get_data_dir
from playwright_helpers import launch_browser
from intl_form_filler import fill_career_form
from region_config import get_crawler_countries
from application_logger import log_application

SCRIPT_DIR = Path(__file__).parent
INTL_STATS_FILE = get_data_dir() / "intl_stats.json"
LOG_DIR = get_data_dir() / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
CRAWLER_LOG_FILE = LOG_DIR / "intl_career_crawler.log"

config = load_config()
TARGET_APPLY_COUNT = 10

def log(message):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    formatted = f"[{ts}] [career-crawler] {message}"
    try:
        print(formatted, flush=True)
    except Exception:
        pass
    try:
        with open(CRAWLER_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass

def random_delay(lo=1.0, hi=3.0):
    time.sleep(random.uniform(lo, hi))

def load_intl_config():
    """Build form-fill data by parsing the resume and merging with config overrides."""
    resume_path = config.get("resume_path", "")

    # Salary: read INR CTC and convert to target region currency via PPP
    target_region = config.get("region_intl_crawler", "European")
    try:
        ctc_inr = float(config.get("ctc_inr", "2500000"))
    except (ValueError, TypeError):
        ctc_inr = 2500000.0

    try:
        from ppp_converter import get_salary_for_form, convert_inr_to_region
        salary_str = get_salary_for_form(ctc_inr, target_region)
        salary_info = convert_inr_to_region(ctc_inr, target_region)
        log(f"PPP salary: ₹{ctc_inr:,.0f} INR → {salary_info['formatted']} ({target_region})")
    except Exception:
        salary_str = "60000"

    config_overrides = {
        "full_name": config.get("intl_full_name", ""),
        "email": config.get("linkedin_email", ""),
        "phone": config.get("linkedin_phone", ""),
        "location": config.get("intl_location", "Bengaluru, India"),
        "expected_salary": salary_str,
        "expected_salary_gbp": salary_str,  # backward compat key
        "notice_period": config.get("intl_notice_period", "60 days"),
        "visa_status": config.get("intl_visa_status", "Require Sponsorship"),
        "job_titles_text": config.get("job_titles", ""),
    }

    # Parse resume if available — parsed data fills in any blanks
    if resume_path and Path(resume_path).exists():
        try:
            from resume_parser import get_form_data
            form_data = get_form_data(resume_path, config_overrides)
            # Add job titles list for search dorks
            form_data["target_region"] = target_region
            form_data["job_titles"] = [
                t.strip() for t in
                (config.get("job_titles") or
                 "ML Engineer, AI Engineer, Software Engineer").split(",")
                if t.strip()
            ]
            return form_data
        except Exception as e:
            log(f"Resume parsing failed, falling back to config: {e}")

    # Fallback: use config values directly
    return {
        "full_name": config_overrides["full_name"],
        "email": config_overrides["email"],
        "phone": config_overrides["phone"],
        "location": config_overrides["location"],
        "expected_salary_gbp": salary_str,
        "notice_period": config_overrides["notice_period"],
        "resume_path": resume_path,
        "target_region": target_region,
        "job_titles": [
            t.strip() for t in
            (config.get("job_titles") or
             "ML Engineer, AI Engineer, Software Engineer").split(",")
            if t.strip()
        ],
    }

def generate_search_dorks(job_titles, region):
    """Generate search engine queries (Google/Bing dorks) to find ATS pages.
    Uses specific country names from region_config for better results.
    """
    title = job_titles[0] if job_titles else "Software Engineer"
    countries = get_crawler_countries(region or "European")
    
    platforms = [
        "site:boards.greenhouse.io",
        "site:jobs.lever.co",
        "site:myworkdayjobs.com",
    ]
    
    dorks = []
    for p in platforms:
        # Generate a dork per country (first 2 countries to avoid over-spamming)
        for country in countries[:2]:
            query = f'{p} "{title}" "{country}"'
            dorks.append(query)
    
    return dorks

def search_duckduckgo(page, dork, max_results=5):
    """
    Use DuckDuckGo HTML-only version — no JS required, no CAPTCHAs.
    """
    results = []
    encoded_query = urllib.parse.quote_plus(dork)
    search_url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
    
    log(f"Executing DuckDuckGo search: {dork}")
    
    try:
        page.goto(search_url, timeout=30000)
        random_delay(1.5, 3)
        
        # DuckDuckGo HTML results are in <a class="result__a"> tags
        anchors = page.locator("a.result__a").all()
        seen = set()
        for anchor in anchors:
            href = anchor.get_attribute("href")
            if href and href.startswith("http") and href not in seen:
                if "duckduckgo.com" in href:
                    continue
                seen.add(href)
                results.append(href)
                log(f"Found: {href}")
                if len(results) >= max_results:
                    break
                
    except Exception as e:
        log(f"DuckDuckGo search failed: {e}")
        
    return results

def crawl_ats_platforms_directly(page, job_titles, region, max_results=10):
    """
    Skip search engines entirely — browse ATS job boards directly.
    Tries both Greenhouse and Lever platforms with 404/dead-page detection.
    """
    results = []
    title_words = set()
    for t in job_titles:
        for w in t.lower().split():
            if len(w) > 2:
                title_words.add(w)
    # Add common related keywords
    title_words.update(["data", "engineer", "software", "developer", "ml", "ai", "backend", "platform"])
    
    log(f"Searching ATS boards for keywords: {title_words}")
    
    # --- Greenhouse companies (verified active as of 2024-2025) ---
    greenhouse_slugs = [
        "embed/job_board/js?for=figma",
        "embed/job_board/js?for=stripe", 
        "embed/job_board/js?for=cloudflare",
        "embed/job_board/js?for=datadog",
    ]
    
    # Direct Greenhouse board URLs
    greenhouse_companies = [
        "gitlab", "hashicorp", "snyk", "grafanalabs",
        "intercom", "mongodb", "elastic", "twilio",
        "deepmind", "revolut", "wise", "checkout",
        "deliveroo", "monzo", "onfido", "improbable",
        "speechmatics", "babylonhealth", "thought-machine",
        "ovo", "starlingbank", "form3",
        "palantir", "databricks", "confluent",
        "cockroachlabs", "timescale", "dbt-labs",
    ]
    
    # Lever companies
    lever_companies = [
        "netflix", "spotify", "figma", "notion",
        "airtable", "linear", "vercel",
        "postman", "miro", "supabase",
    ]
    
    def _is_dead_page(pg):
        """Check if the page is a 404 or dead board."""
        try:
            body = pg.inner_text("body")[:500].lower()
            dead_signals = [
                "page not found", "no longer active", "404",
                "not found", "does not exist", "no jobs",
                "no open positions", "no current openings",
            ]
            return any(s in body for s in dead_signals)
        except Exception:
            return True
    
    def _matches_title(text):
        """Check if job listing text matches any of our title keywords."""
        text_lower = text.lower()
        return any(word in text_lower for word in title_words)

    # --- Phase A: Greenhouse boards ---
    log("Scanning Greenhouse boards...")
    for company in greenhouse_companies:
        if len(results) >= max_results:
            break
        url = f"https://boards.greenhouse.io/{company}"
        try:
            page.goto(url, timeout=12000)
            random_delay(0.3, 0.8)
            
            if _is_dead_page(page):
                continue
            
            job_links = page.locator("a[href*='/jobs/']").all()
            for link in job_links[:3]:
                href = link.get_attribute("href")
                text = link.inner_text()
                if href and _matches_title(text):
                    full_url = href if href.startswith("http") else f"https://boards.greenhouse.io{href}"
                    if full_url not in results:
                        results.append(full_url)
                        log(f"✓ Greenhouse [{company}]: {text.strip()[:60]}")
        except Exception:
            continue

    # --- Phase B: Lever boards ---
    log("Scanning Lever boards...")
    for company in lever_companies:
        if len(results) >= max_results:
            break
        url = f"https://jobs.lever.co/{company}"
        try:
            page.goto(url, timeout=12000)
            random_delay(0.3, 0.8)
            
            if _is_dead_page(page):
                continue
            
            job_links = page.locator("a.posting-title").all()
            if not job_links:
                job_links = page.locator("a[href*='/jobs/'], a[href*='/apply/']").all()
            
            for link in job_links[:3]:
                href = link.get_attribute("href")
                text = link.inner_text()
                if href and _matches_title(text):
                    full_url = href if href.startswith("http") else f"https://jobs.lever.co{href}"
                    if full_url not in results:
                        results.append(full_url)
                        log(f"✓ Lever [{company}]: {text.strip()[:60]}")
        except Exception:
            continue

    log(f"Direct ATS scan complete: {len(results)} matching jobs found.")
    return results

def apply_direct(context, url, intl_config):
    """Navigate to the ATS URL and use the form filler."""
    log(f"\nAttempting application at: {url}")
    new_page = context.new_page()
    
    try:
        new_page.goto(url, timeout=45000, wait_until="domcontentloaded")
        random_delay(2, 3)
        
        # Check for dead/error pages before wasting time
        try:
            body = new_page.inner_text("body")[:800].lower()
            dead_signals = [
                "page not found", "no longer active", "404", "not found",
                "does not exist", "this job is no longer", "position has been filled",
                "expired", "no longer accepting", "job has been removed",
                "this posting has closed", "sorry", "no longer available",
            ]
            if any(s in body for s in dead_signals):
                log(f"⊘ Skipping dead/closed page: {url[:80]}")
                new_page.close()
                return False
        except Exception:
            pass

        # Accept cookies if the prompt appears
        try:
            accept_btn = new_page.locator("button:has-text('Accept All'), button:has-text('Accept cookies'), button#onetrust-accept-btn-handler").first
            if accept_btn.is_visible():
                accept_btn.click(timeout=2000)
                random_delay(1, 2)
        except Exception:
            pass
        
        # Look for Apply button
        apply_btns = [
            "a:has-text('Apply')", "button:has-text('Apply')",
            "a:has-text('Apply Now')", "button:has-text('Apply Now')",
            "a:has-text('Apply for this job')", "button:has-text('Apply for this job')",
            "a[href*='apply']",
        ]

        clicked_apply = False
        try:
            # Wait a moment for dynamic buttons
            btn_selector = ", ".join(apply_btns)
            btn = new_page.locator(btn_selector).first
            btn.wait_for(state="visible", timeout=4000)
            btn.click()
            random_delay(2, 3)
            clicked_apply = True
        except Exception:
            pass
                
        if not clicked_apply:
            log("No apply button found immediately, assuming we are on the form page.")
            
        # Try to extract title and company for logging
        try:
            # Simple heuristic for ATS pages
            job_title = new_page.locator("h1, h2.app-title, .posting-headline h2").first.inner_text(timeout=1000).strip()
        except Exception:
            job_title = "Unknown Role"
            
        try:
            company = new_page.locator(".company-name, .logo-text, header h1").first.inner_text(timeout=1000).strip()
        except Exception:
            company = urllib.parse.urlparse(url).netloc
            
        # Use the heuristic form filler
        success = fill_career_form(new_page, intl_config)
        
        if success:
            log(f"✓ Successfully applied!")
            try:
                log_application("Crawler", company, job_title, url)
            except Exception as e:
                log(f"Failed to log application: {e}")
        else:
            log(f"✗ Failed to complete application form.")
            
        new_page.close()
        return success
        
    except Exception as e:
        log(f"Error during direct application: {e}")
        try:
            new_page.close()
        except Exception:
            pass
        return False

def update_stats(applied_count):
    stats = {"total_applications": 0, "today_count": 0, "last_run": None}
    if INTL_STATS_FILE.exists():
        try:
            with open(INTL_STATS_FILE, "r") as f: stats = json.load(f)
        except: pass

    today = str(date.today())
    previous_last_run = str(stats.get("last_run") or "")
    stats["total_applications"] = int(stats.get("total_applications", 0)) + applied_count
    stats["today_count"] = (int(stats.get("today_count", 0)) if previous_last_run.startswith(today) else 0) + applied_count
    stats["last_run"] = str(datetime.now())

    with open(INTL_STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)

def run(target_count=TARGET_APPLY_COUNT, headless=False):
    intl_config = load_intl_config()
    log(f"Starting Career Page Crawler. Target: {target_count} SUCCESSFUL applications.")
    log(f"Region: {intl_config.get('target_region', 'Europe')}")
    log(f"Job titles: {intl_config.get('job_titles', [])}")
    log(f"Candidate: {intl_config.get('full_name', 'N/A')} ({intl_config.get('email', 'N/A')})")
    
    dorks = generate_search_dorks(intl_config["job_titles"], intl_config.get("target_region", "Europe"))
    
    MAX_ROUNDS = 5          # max discovery rounds before giving up
    MAX_TOTAL_ATTEMPTS = target_count * 10  # absolute safety cap
    
    with sync_playwright() as p:
        engine, browser = launch_browser(p, headless=headless, preferred_engines=["chromium"])
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()
        
        applied_count = 0
        total_attempts = 0
        tried_urls = set()   # never retry the same URL
        round_num = 0
        
        while applied_count < target_count and round_num < MAX_ROUNDS and total_attempts < MAX_TOTAL_ATTEMPTS:
            round_num += 1
            log(f"\n{'='*60}")
            log(f"ROUND {round_num} — {applied_count}/{target_count} successful so far")
            log(f"{'='*60}")
            
            all_ats_links = []
            
            # Phase 1A: Direct ATS crawling
            log("--- Crawling ATS Platforms Directly ---")
            direct_links = crawl_ats_platforms_directly(
                page, intl_config["job_titles"], intl_config.get("target_region", "Europe"),
                max_results=target_count * 3  # get extra since many will be dead
            )
            all_ats_links.extend(direct_links)
            
            # Phase 1B: DuckDuckGo fallback
            if len(all_ats_links) < target_count * 2:
                log("--- Discovering via DuckDuckGo ---")
                for dork in dorks:
                    links = search_duckduckgo(page, dork, max_results=5)
                    all_ats_links.extend(links)
                    random_delay(3, 6)
                    if len(all_ats_links) >= target_count * 3:
                        break
                        
                # Also try additional dorks with different titles
                if len(intl_config.get("job_titles", [])) > 1:
                    extra_dorks = generate_search_dorks(
                        intl_config["job_titles"][1:], intl_config.get("target_region", "Europe")
                    )
                    for dork in extra_dorks:
                        links = search_duckduckgo(page, dork, max_results=3)
                        all_ats_links.extend(links)
                        random_delay(3, 6)
                        if len(all_ats_links) >= target_count * 3:
                            break
            
            # Deduplicate and remove already-tried URLs
            new_links = [u for u in set(all_ats_links) if u not in tried_urls]
            log(f"Discovery: {len(new_links)} new unique URLs (filtered {len(all_ats_links) - len(new_links)} already tried)")
            
            if not new_links:
                log("No new URLs found. Stopping.")
                break
            
            # Phase 2: Apply to each link
            log(f"--- Applying ({len(new_links)} candidates) ---")
            for url in new_links:
                if applied_count >= target_count:
                    break
                if total_attempts >= MAX_TOTAL_ATTEMPTS:
                    log(f"Safety cap reached ({MAX_TOTAL_ATTEMPTS} attempts). Stopping.")
                    break
                    
                tried_urls.add(url)
                total_attempts += 1
                
                success = apply_direct(context, url, intl_config)
                if success:
                    applied_count += 1
                    log(f"✓ Progress: {applied_count}/{target_count}")
                    update_stats(1)  # update stats incrementally
                    
                random_delay(3, 6)
        
        log(f"\n{'='*60}")
        log(f"FINISHED — {applied_count}/{target_count} successful applications")
        log(f"Total attempts: {total_attempts}, Rounds: {round_num}")
        log(f"{'='*60}")
        browser.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=TARGET_APPLY_COUNT)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    run(target_count=args.target, headless=args.headless)

