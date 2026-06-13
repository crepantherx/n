#!/usr/bin/env python3
"""
International Indeed Applier

Dedicated scraper for European/International roles on Indeed.
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
from region_config import get_indeed_domain, get_indeed_location
from application_logger import log_application
from intl_career_page_crawler import load_intl_config as load_full_config, apply_direct

SCRIPT_DIR = Path(__file__).parent
INTL_STATS_FILE = get_data_dir() / "intl_stats.json"
LOG_DIR = get_data_dir() / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
INTL_LOG_FILE = LOG_DIR / "intl_indeed.log"

config = load_config()
TARGET_APPLY_COUNT = 15

def log(message):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    formatted = f"[{ts}] [intl-indeed] {message}"
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
    data["target_region"] = config.get("region_intl_indeed", "European")
    return data

def discover_and_apply(page, intl_config, target_count):
    applied_count = 0
    query = "+".join(intl_config["job_titles"][:3])

    # Use region_config for correct Indeed domain & location
    region = intl_config["target_region"]
    domain = get_indeed_domain(region)
    location = get_indeed_location(region)

    # Build URL with optional location parameter
    loc_param = f"&l={location}" if location else ""
    url = f"https://{domain}/jobs?q={query}{loc_param}"
    
    log(f"Region: {region} → Indeed domain: {domain}, location: {location or '(default)'}")
    log(f"Searching Indeed: {url}")
    try:
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        random_delay(3, 5)

        cards = []
        for sel in ["div.job_seen_beacon", "div.jobsearch-ResultsList div.result", "td.resultContent"]:
            if page.locator(sel).count() > 0:
                cards = page.locator(sel).all()
                break

        for card in cards:
            if applied_count >= target_count:
                break
                
            try:
                card.click(timeout=2000)
                random_delay(2, 3)
                
                apply_btn = page.locator("#indeedApplyButton").first
                if apply_btn.is_visible():
                    log("Found Indeed Apply button. (Integration requires complex auth, skipping for v1)")
                    # In a full implementation, you'd handle the Indeed iframe popup here
                    continue
                
                # Look for Apply on Company Site
                ext_btn = page.locator("a:has-text('Apply On Company Site'), button:has-text('Apply On Company Site')").first
                if ext_btn.is_visible():
                    ext_href = ext_btn.get_attribute("href")
                    if ext_href:
                        log(f"Found external link: {ext_href[:50]}...")
                        if apply_direct(page.context, ext_href, intl_config):
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
    intl_config = load_intl_config()
    with sync_playwright() as p:
        engine, browser = launch_browser(p, headless=headless, preferred_engines=["firefox", "webkit", "chromium"])
        context = browser.new_context(viewport={"width": 1280, "height": 720})
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
