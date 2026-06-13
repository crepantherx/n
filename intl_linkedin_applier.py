#!/usr/bin/env python3
"""
International LinkedIn Applier

Dedicated scraper for European/International roles on LinkedIn.
Applies visa sponsorship keyword filtering to the job description before Easy Apply.
"""

import os
import sys
import time
import json
import random
import urllib.parse
from datetime import datetime, date
from pathlib import Path
from playwright.sync_api import sync_playwright
from config_loader import load_config, get_data_dir
from playwright_helpers import launch_browser
from region_config import get_linkedin_location, get_geolocation, get_locale

SCRIPT_DIR = Path(__file__).parent
INTL_STATS_FILE = get_data_dir() / "intl_stats.json"
LOG_DIR = get_data_dir() / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
INTL_LOG_FILE = LOG_DIR / "intl_linkedin.log"

config = load_config()
TARGET_APPLY_COUNT = 20

def log(message):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    formatted = f"[{ts}] [intl-linkedin] {message}"
    try:
        print(formatted, flush=True)
    except Exception:
        pass
    try:
        with open(INTL_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass

def random_delay(lo=0.5, hi=1.5):
    time.sleep(random.uniform(lo, hi))

def load_intl_config():
    return {
        "email": config.get("linkedin_email", ""),
        "password": config.get("linkedin_password", ""),
        "phone": config.get("linkedin_phone", ""),
        "target_region": config.get("region_intl_linkedin") or config.get("intl_target_region") or "European",
        "job_titles": [
            t.strip() for t in
            (config.get("intl_job_titles") or config.get("job_titles") or
             "ML Engineer, AI Engineer, Software Engineer").split(",")
            if t.strip()
        ],
    }

def discover_and_apply(page, intl_config, target_count):
    applied_count = 0
    email = intl_config["email"]
    password = intl_config["password"]

    if not email or not password:
        log("LinkedIn credentials missing.")
        return 0

    try:
        page.goto("https://www.linkedin.com/login", timeout=60000)
        page.fill("#username", email)
        page.fill("#password", password)
        page.click("button[type='submit']")
        page.wait_for_url("**/feed/**", timeout=15000)
        log("LinkedIn login successful.")
    except Exception as e:
        log(f"Login failed: {e}")
        return 0

    query = " OR ".join(intl_config["job_titles"])
    encoded = urllib.parse.quote(query)
    location = get_linkedin_location(intl_config["target_region"])
    region_encoded = urllib.parse.quote(location)

    search_url = f"https://www.linkedin.com/jobs/search/?f_AL=true&keywords={encoded}&location={region_encoded}"
    log(f"Region: {intl_config['target_region']} -> LinkedIn location: {location}")
    log(f"Searching: {search_url}")

    try:
        page.goto(search_url, timeout=60000, wait_until="domcontentloaded")
        random_delay(3, 5)

        selectors = ["li.jobs-search-results__list-item", ".jobs-search-results__list-item"]
        
        cards = []
        for sel in selectors:
            count = page.locator(sel).count()
            if count > 0:
                cards = page.locator(sel).all()
                break

        for card in cards:
            if applied_count >= target_count:
                break

            try:
                card.click(timeout=2000)
                random_delay(2, 3)

                # Visa Check (Quick heuristic)
                desc = page.locator("#job-details").inner_text(timeout=2000).lower()
                from intl_visa_filters import is_licensed_sponsor
                
                # Check visa negatives
                if "no visa sponsorship" in desc or "no sponsorship" in desc:
                    log("Job explicitly states no sponsorship. Skipping.")
                    continue

                # Proceed to Easy Apply
                btn = page.locator("button.jobs-apply-button").first
                if btn.is_visible():
                    btn.click(timeout=2000)
                    random_delay(1, 2)
                    
                    # Very simple Next/Submit loop (reusing logic pattern)
                    for step in range(15):
                        success_sel = "h3:has-text('Application sent')"
                        if page.locator(success_sel).is_visible():
                            log("Application sent!")
                            applied_count += 1
                            try:
                                page.locator("button:has-text('Done')").first.click()
                            except: pass
                            break
                        
                        try:
                            footer_btn = page.locator(".jobs-easy-apply-footer__actions .artdeco-button--primary").first
                            if footer_btn.is_visible():
                                btn_txt = footer_btn.inner_text()
                                if btn_txt in ["Next", "Review", "Submit application", "Submit"]:
                                    footer_btn.click()
                                    random_delay(1, 2)
                        except: pass
            except Exception:
                continue

    except Exception as e:
        log(f"Search failed: {e}")

    return applied_count

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
    with sync_playwright() as p:
        engine, browser = launch_browser(p, headless=headless, preferred_engines=["chromium"])
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale=get_locale(intl_config["target_region"]),
            geolocation=get_geolocation(intl_config["target_region"]),
            permissions=["geolocation"],
        )
        page = context.new_page()
        
        applied = discover_and_apply(page, intl_config, target_count)
        update_stats(applied)
        browser.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=TARGET_APPLY_COUNT)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    run(target_count=args.target, headless=args.headless)
