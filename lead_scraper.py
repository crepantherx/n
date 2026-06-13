#!/usr/bin/env python3
import os
import sys
import time
import random
import urllib.parse
import re
import json
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright
from config_loader import load_config, get_data_dir

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = get_data_dir()
OUTREACH_LEADS_FILE = DATA_DIR / "outreach_leads.json"
LOG_FILE = DATA_DIR / "lead_scraper.log"
DEBUG_DIR = DATA_DIR / "debug"

def debug_artifact_path(name: str) -> str:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    return str(DEBUG_DIR / name)

config = load_config()
LINKEDIN_EMAIL = config.get("linkedin_email", "")
LINKEDIN_PASSWORD = config.get("linkedin_password", "")

def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    formatted = f"[{ts}] [lead-scraper] {msg}"
    print(formatted, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass

def random_delay(lo=1.0, hi=3.0):
    time.sleep(random.uniform(lo, hi))

def extract_emails(text):
    return re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)

def load_leads():
    if OUTREACH_LEADS_FILE.exists():
        try:
            with open(OUTREACH_LEADS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_leads(leads):
    try:
        with open(OUTREACH_LEADS_FILE, "w") as f:
            json.dump(leads, f, indent=2)
    except Exception as e:
        log(f"Error saving leads: {e}")

def login(page):
    log("Navigating to LinkedIn login page...")
    page.goto("https://www.linkedin.com/login", timeout=60000)
    random_delay()

    log("Waiting for username/email field...")
    try:
        username_selectors = ["#username", "#session_key", "[name='session_key']", "[type='email']", "[type='text']"]
        username_found = False
        
        # Poll all elements for a visible one
        for _ in range(15):
            for selector in username_selectors:
                for el in page.locator(selector).all():
                    if el.is_visible():
                        el.fill(LINKEDIN_EMAIL)
                        username_found = True
                        log(f"Found username field using: {selector}")
                        break
                if username_found: break
            if username_found: break
            page.wait_for_timeout(1000)
                
        if not username_found:
            raise Exception("Could not find a visible username/email input field.")
            
        random_delay(0.5, 1.5)
        
        password_selectors = ["#password", "#session_password", "[name='session_password']", "[type='password']"]
        password_found = False
        
        for _ in range(10):
            for selector in password_selectors:
                for el in page.locator(selector).all():
                    if el.is_visible():
                        el.fill(LINKEDIN_PASSWORD)
                        password_found = True
                        break
                if password_found: break
            if password_found: break
            page.wait_for_timeout(1000)
                
        if not password_found:
            raise Exception("Could not find a visible password input field.")
            
        random_delay(0.5, 1.5)
        
        # Uncheck "Keep me logged in" checkbox using JavaScript to avoid page interference
        try:
            page.evaluate("""
                const checkbox = document.getElementById('rememberMeOptIn-checkbox');
                if (checkbox && checkbox.checked) {
                    checkbox.checked = false;
                }
            """)
            log("✓ Unchecked 'Keep me logged in' checkbox")
            random_delay(0.3, 0.5)
        except Exception as e:
            log(f"Could not uncheck checkbox (continuing): {e}")
        
        # Click the Sign in button
        log("Clicking Sign in button...")
        try:
            page.click("button[type='submit']", timeout=3000)
        except:
            log("Submit button not found (possibly hidden), falling back to pressing Enter...")
            page.keyboard.press("Enter")

        
        # Wait for login to complete (feed or jobs page)
        # LinkedIn may redirect to /feed or /jobs after login
        try:
            page.wait_for_url("**/feed/**", timeout=15000)
            log("Login successful - redirected to feed.")
        except:
            try:
                page.wait_for_url("**/jobs/**", timeout=5000)
                log("Login successful - redirected to jobs.")
            except:
                # Check if we're on checkpoint (verification required)
                if "checkpoint" in page.url:
                    log("LinkedIn verification required. Waiting 60 seconds for manual resolution...")
                    page.screenshot(path=debug_artifact_path("linkedin_verification_required.png"))
                    page.wait_for_timeout(60000)
                else:
                    log("Login successful (alternative flow).")
        
        random_delay()
    except Exception as e:
        log(f"Login failed: {e}")
        page.screenshot(path=debug_artifact_path("linkedin_login_failure.png"))
        raise e

def main():
    if not LINKEDIN_EMAIL or not LINKEDIN_PASSWORD:
        log("ERROR: LinkedIn credentials missing in config.json")
        sys.exit(1)

    target = 20
    if len(sys.argv) > 1 and sys.argv[1] == "--target":
        try:
            target = int(sys.argv[2])
        except Exception:
            pass

    headless = "--headless" in sys.argv
    job_titles_str = config.get("job_titles") or "Software Engineer"
    job_titles = [t.strip() for t in job_titles_str.split(",") if t.strip()]
    title_query = " OR ".join([f'"{t}"' for t in job_titles])

    query = f'hiring ({title_query}) "@gmail.com" OR "@company.com"'
    encoded_query = urllib.parse.quote(query)
    # Added "Past 24 hours" filter using datePosted="%22past-24h%22"
    search_url = f"https://www.linkedin.com/search/results/content/?keywords={encoded_query}&datePosted=%22past-24h%22"

    leads = load_leads()
    existing_content = {lead.get("content", "")[:100] for lead in leads} # Deduplicate by content prefix

    from playwright_helpers import launch_browser
    
    with sync_playwright() as p:
        engine, browser = launch_browser(
            p,
            headless=headless,
            preferred_engines=["chromium"],
            log=log
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720},
            locale="en-US"
        )
        page = context.new_page()

        try:
            login(page)
        except Exception as e:
            log("Aborting due to login failure.")
            browser.close()
            sys.exit(1)

        found_count = 0
        log(f"Searching native LinkedIn content: {query}")

        try:
            page.goto(search_url, timeout=30000)
            # Wait for page to fully render (LinkedIn uses heavy JS)
            page.wait_for_timeout(5000)
            # Scroll partway to trigger lazy loading
            page.evaluate("window.scrollTo(0, document.body.scrollHeight/3)")
            page.wait_for_timeout(2000)

            # Wait for the actual post text elements using stable data-testid attributes
            # LinkedIn has fully obfuscated all CSS class names with random hashes,
            # but data-testid attributes remain stable across deployments
            try:
                page.wait_for_selector('[data-testid="expandable-text-box"]', timeout=15000)
                log("Found post elements on page.")
            except Exception:
                log("Timeout waiting for post elements, will try to proceed anyway...")

            # Scroll and scrape loop
            max_scrolls = 10
            for scroll in range(max_scrolls):
                if found_count >= target:
                    break

                # Step 1: Click ALL "see more" buttons on the page to expand truncated posts
                # The "see more" buttons have data-testid="expandable-text-button"
                # They have pointer-events:none and aria-hidden:true, so we must use JS clicks
                try:
                    see_more_count = page.evaluate("""() => {
                        const buttons = document.querySelectorAll('[data-testid="expandable-text-button"]');
                        let clicked = 0;
                        buttons.forEach(btn => {
                            btn.click();
                            clicked++;
                        });
                        return clicked;
                    }""")
                    if see_more_count > 0:
                        log(f"Expanded {see_more_count} truncated posts.")
                        page.wait_for_timeout(1000)
                except Exception as e:
                    log(f"Could not expand posts: {e}")

                # Step 2: Extract all post text using data-testid="expandable-text-box"
                text_boxes = page.locator('[data-testid="expandable-text-box"]').all()
                
                if not text_boxes:
                    log("No post text boxes found on this page.")
                    break

                log(f"Found {len(text_boxes)} posts on scroll {scroll + 1}.")

                for i, text_box in enumerate(text_boxes):
                    if found_count >= target:
                        break

                    try:
                        full_text = text_box.inner_text().strip()
                        if not full_text:
                            continue

                        content_prefix = full_text[:100]
                        if content_prefix in existing_content:
                            continue

                        # Check if this post is hiring-related
                        text_lower = full_text.lower()
                        hiring_keywords = ["hiring", "job", "opening", "opportunity", "looking for", "we are", "position", "role", "vacancy", "recruit"]
                        is_hiring = any(kw in text_lower for kw in hiring_keywords)
                        if not is_hiring:
                            continue

                        emails = extract_emails(full_text)
                        if not emails:
                            continue

                        email = emails[0]
                        company = "LinkedIn"
                        name = "Recruiter"
                        link = search_url

                        # Try to extract author name and post link from the parent container via JS
                        try:
                            author_info = page.evaluate("""(el) => {
                                let node = el;
                                for (let i = 0; i < 15; i++) {
                                    node = node.parentElement;
                                    if (!node) break;
                                    const menuBtn = node.querySelector('[aria-label^="Open control menu for post by"]');
                                    if (menuBtn) {
                                        const label = menuBtn.getAttribute('aria-label');
                                        const match = label.match(/Open control menu for post by (.+)/);
                                        const authorName = match ? match[1] : null;
                                        // Look for the author's profile link
                                        const profileLink = node.querySelector('a[href*="/in/"]');
                                        const profileUrl = profileLink ? profileLink.getAttribute('href') : null;
                                        // Look for the post link (pulse article or timestamp link)
                                        const postLink = node.querySelector('a[href*="/pulse/"], a[href*="/feed/update/"], a[href*="/posts/"]');
                                        const postUrl = postLink ? postLink.getAttribute('href') : null;
                                        return { name: authorName, profileLink: profileUrl, postLink: postUrl };
                                    }
                                }
                                return null;
                            }""", text_box.element_handle())
                            if author_info:
                                if author_info.get("name"):
                                    name = author_info["name"]
                                if author_info.get("postLink"):
                                    link = author_info["postLink"]
                                    if link.startswith("/"):
                                        link = "https://www.linkedin.com" + link
                                elif author_info.get("profileLink"):
                                    link = author_info["profileLink"]
                                    if link.startswith("/"):
                                        link = "https://www.linkedin.com" + link
                        except Exception:
                            pass

                        lead = {
                            "id": str(int(time.time() * 1000) + random.randint(0, 1000)),
                            "date": datetime.now().isoformat(),
                            "company": company,
                            "name": name,
                            "link": link,
                            "email": email,
                            "content": full_text,
                            "status": "Reachout"
                        }

                        leads.insert(0, lead)
                        existing_content.add(content_prefix)
                        found_count += 1
                        log(f"Found new lead: {email} from {name}")

                    except Exception as e:
                        continue

                if found_count < target:
                    log("Scrolling down to load more posts...")
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(4000)

        except Exception as e:
            log(f"Search error: {e}")

        save_leads(leads)
        log(f"Scraping complete. Found {found_count} new leads.")
        browser.close()

if __name__ == "__main__":
    main()
