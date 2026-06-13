#!/usr/bin/env python3
"""
International Reed Applier

Dedicated scraper for Reed.co.uk roles.
"""

import os
import sys
import time
import json
import random
from datetime import datetime, date
from pathlib import Path
from playwright.sync_api import sync_playwright
from config_loader import load_config, get_data_dir
from playwright_helpers import launch_browser
from region_config import is_reed_supported
from application_logger import log_application
from intl_career_page_crawler import load_intl_config as load_full_config, apply_direct

SCRIPT_DIR = Path(__file__).parent
INTL_STATS_FILE = get_data_dir() / "intl_stats.json"
LOG_DIR = get_data_dir() / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
INTL_LOG_FILE = LOG_DIR / "intl_reed.log"

config = load_config()
TARGET_APPLY_COUNT = 15

def log(message):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    formatted = f"[{ts}] [intl-reed] {message}"
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
    data = load_full_config()
    data["target_region"] = config.get("region_intl_reed", "European")
    return data

def login_reed(page, email, password):
    log(f"Attempting to log into Reed as {email}...")
    try:
        page.goto("https://www.reed.co.uk/account/signin", timeout=60000, wait_until="domcontentloaded")
        random_delay(2, 4)
        
        # Accept cookies if the prompt appears
        try:
            accept_btn = page.locator("button:has-text('Accept All'), button:has-text('Accept cookies'), button#onetrust-accept-btn-handler").first
            if accept_btn.is_visible():
                accept_btn.click(timeout=3000)
                random_delay(1, 2)
        except Exception:
            pass

        # Fill credentials
        page.fill("input[type='email'], input[name*='email']", email)
        
        if password and password != "PleaseChangeMe123!":
            page.fill("input[type='password'], input[name*='password']", password)
            
            login_btn = None
            for sel in ["button:has-text('Continue')", "button:has-text('Sign in')", "button.submit-btn", "button[type='submit']"]:
                for btn in page.locator(sel).all():
                    if btn.is_visible() and btn.is_enabled():
                        txt = btn.inner_text().lower()
                        if "apple" not in txt and "google" not in txt:
                            login_btn = btn
                            break
                if login_btn:
                    break
            
            if login_btn:
                login_btn.click()
            else:
                log("Warning: Could not find a valid login button to click!")
        else:
            log("No valid password provided. Pausing for 60s to allow manual login/SSO if browser is visible...")
            try:
                # Wait for user to manually click Continue and enter password/SSO
                page.wait_for_url(lambda url: "login" not in url.lower() and "signin" not in url.lower() and "sign-in" not in url.lower(), timeout=60000)
            except Exception:
                pass
        
        # Wait for navigation or error
        page.wait_for_load_state("domcontentloaded", timeout=10000)
        random_delay(2, 4)
        
        url_lower = page.url.lower()
        if "login" not in url_lower and "signin" not in url_lower and "sign-in" not in url_lower:
            log("✓ Successfully logged into Reed!")
            return True
        else:
            log("✗ Failed to log into Reed. Check credentials or Captcha.")
            return False
    except Exception as e:
        log(f"Login failed: {e}")
        return False

def discover_and_apply(page, intl_config, target_count):
    applied_count = 0
    keywords = "-".join(intl_config["job_titles"][0].lower().split())
    url = f"https://www.reed.co.uk/jobs/{keywords}-jobs"
    
    log(f"Searching Reed: {url}")
    try:
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        random_delay(3, 5)

        # Accept cookies if the prompt appears
        try:
            accept_btn = page.locator("button:has-text('Accept All'), button:has-text('Accept cookies'), button#onetrust-accept-btn-handler").first
            if accept_btn.is_visible():
                accept_btn.click(timeout=3000)
                random_delay(1, 2)
        except Exception:
            pass

        cards = []
        for sel in ["article.job-result-card", "div.job-result-card", "article[data-qa='job-card']"]:
            if page.locator(sel).count() > 0:
                cards = page.locator(sel).all()
                break

        for card in cards:
            if applied_count >= target_count:
                break
                
            try:
                title_el = card.locator("h2 a, h3 a, a.job-result-heading__title").first
                href = title_el.get_attribute("href")
                if href:
                    job_url = f"https://www.reed.co.uk{href}" if href.startswith("/") else href
                    log(f"Found Job URL: {job_url}")
                    if apply_direct(page.context, job_url, intl_config):
                        applied_count += 1
            except Exception as e:
                log(f"Failed to process card: {e}")
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
    # ---- Region guard: Reed is UK/Europe-only ----
    region = config.get("region_intl_reed", "European")
    if not is_reed_supported(region):
        log(f"⚠ Reed.co.uk is UK/Europe-only. Skipping for region: {region}")
        log("Select 'European' region for the Reed agent, or use LinkedIn/Indeed/Crawler for this region.")
        return

    log(f"Starting Reed applier (region: {region})")
    intl_config = load_intl_config()
    with sync_playwright() as p:
        engine, browser = launch_browser(p, headless=headless, preferred_engines=["firefox", "webkit", "chromium"])
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()
        
        # Attempt Login if email is provided (password can be empty for manual/SSO login)
        reed_email = config.get("reed_email")
        reed_password = config.get("reed_password")
        if reed_email:
            login_reed(page, reed_email, reed_password)
        else:
            log("No Reed credentials found. Running unauthenticated (external applications only).")
        
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
