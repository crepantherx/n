import os
import sys
import time
import random
from datetime import datetime
from playwright.sync_api import sync_playwright
from config_loader import load_config, get_data_dir
from playwright_helpers import launch_browser
from application_logger import log_application
from region_config import get_linkedin_location

# Load configuration from config.json or .env
config = load_config()
LINKEDIN_EMAIL = config.get("linkedin_email", "")
LINKEDIN_PASSWORD = config.get("linkedin_password", "")
LINKEDIN_PHONE = config.get("linkedin_phone", "")

# Configuration
_default_titles = config.get("job_titles") or "ML Engineer, AI Engineer, Software Engineer"
KEYWORDS = [t.strip() for t in _default_titles.split(",") if t.strip()] or ["ML Engineer", "AI Engineer", "Software Engineer"]
TARGET_APPLY_COUNT = 30  # Default target, can be overridden via command-line

DEBUG_DIR = get_data_dir() / "debug"

def debug_artifact_path(name: str) -> str:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    return str(DEBUG_DIR / name)

def log_file_path(name: str) -> str:
    logs_dir = get_data_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return str(logs_dir / name)

def log(message):
    """Log message to stdout and file"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    formatted_msg = f"[{timestamp}] {message}"
    
    # Write to stdout
    try:
        print(formatted_msg, flush=True)
    except Exception:
        pass
        
    # Write to file
    try:
        with open(log_file_path("linkedin_debug.log"), "a", encoding="utf-8") as f:
            f.write(formatted_msg + "\n")
    except Exception:
        pass


def random_delay(min_seconds=0.5, max_seconds=1.5):
    time.sleep(random.uniform(min_seconds, max_seconds))

def login(page):
    log("Navigating to LinkedIn login page...")
    page.goto("https://www.linkedin.com/login", timeout=60000)
    random_delay()

    try:
        log("Waiting for username/email field...")
        # LinkedIn heavily obfuscates their login page IDs now, and they have multiple hidden inputs.
        # We use the :visible pseudo-class to ensure we only target the actual visible inputs,
        # otherwise Playwright might latch onto the first hidden input and timeout waiting for it to become visible.
        email_loc = page.locator("input[type='email']:visible, input[type='text']:visible, #username:visible, #session_key:visible").first
        email_loc.fill(LINKEDIN_EMAIL, timeout=15000)
        
        random_delay(0.5, 1.5)
        
        pass_loc = page.locator("input[type='password']:visible, #password:visible, #session_password:visible").first
        pass_loc.fill(LINKEDIN_PASSWORD, timeout=5000)
            
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
        
        # Press Enter on the password field to submit the login form.
        # This is more robust than clicking the submit button because LinkedIn's
        # submit button is often obfuscated or re-rendered dynamically.
        log("Pressing Enter to submit login form...")
        pass_loc.press("Enter")

        
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
                    log("LinkedIn verification required. Please complete manually.")
                    page.screenshot(path=debug_artifact_path("linkedin_verification_required.png"))
                    input("Press Enter after completing verification...")
                else:
                    log("Login successful (alternative flow).")
        
        random_delay()
    except Exception as e:
        log(f"Login failed: {e}")
        page.screenshot(path=debug_artifact_path("linkedin_login_failure.png"))
        raise e

def search_jobs(page):
    """Search for jobs using the configured keywords"""
    query = " OR ".join(KEYWORDS)  # Use OR to search for any of the keywords
    log(f"Searching for: {query}")
    
    # Navigate directly to search results with Easy Apply filter
    # This is faster than loading /jobs and then searching
    encoded_query = query.replace(" ", "%20")
    
    # Map UI region choices to LinkedIn location strings using region_config
    region = config.get("region_linkedin", "Indian")
    location = get_linkedin_location(region)
    encoded_loc = location.replace(" ", "%20")
    
    search_url = f"https://www.linkedin.com/jobs/search/?f_AL=true&keywords={encoded_query}&location={encoded_loc}"
    
    log(f"Region: {region} → LinkedIn location: {location}")
    log(f"Navigating to: {search_url}")
    # Use domcontentloaded to avoid waiting for all resources (ads, tracking) to load
    page.goto(search_url, timeout=60000, wait_until="domcontentloaded")
    log("Page navigation finished (domcontentloaded).")
    random_delay(2, 3)
    
    # Wait for results to load - use shorter timeout and try generic selectors
    try:
        log("Waiting for results container...")
        # Try to find any result list container
        try:
            page.wait_for_selector(".jobs-search-results-list, .scaffold-layout__list, li.jobs-search-results__list-item", timeout=5000)
            log("Search results page loaded.")
        except:
            log("Wait for results container timed out, proceeding to check for jobs anyway...")
        
        # Count jobs
        try:
            log("Getting job count...")
            job_count_text = page.locator(".jobs-search-results-list__subtitle, .results-context-header__job-count").first.inner_text(timeout=2000)
            log(f"Search results: {job_count_text}")
        except:
            log("Could not get job count (timeout), continuing...")
            pass
            
    except Exception as e:
        log(f"Warning checking search results: {e}")
    
    log("Job search function finished.")


def apply_easy_apply_filter(page):
    """
    Filter is already applied via URL parameter f_AL=true
    This function is now a no-op but kept for compatibility
    """
    log("Easy Apply filter already applied via URL.")
    random_delay(0.5, 1)


def get_job_listings(page):
    """Get all job listings on the current page"""
    try:
        # Wait briefly for any job card to be visible - use any likely selector
        try:
            # Wait for either result list or individual items
            page.wait_for_selector(".jobs-search-results-list, .scaffold-layout__list, li.jobs-search-results__list-item, div.job-card-container", timeout=5000)
        except:
            pass
            
        # Try multiple selectors for job cards - iterate and return the first one that finds jobs
        selectors = [
            # Common desktop selectors
            "li.jobs-search-results__list-item", 
            ".jobs-search-results__list-item",
            "div.job-card-container",
            ".job-card-list__entity-lockup",
            # Fallback selectors
            ".scaffold-layout__list-item",
            "div[data-job-id]"
        ]
        
        for selector in selectors:
            try:
                # Get count first without waiting
                count = page.locator(selector).count()
                log(f"Checking selector '{selector}': Found {count} items")
                if count > 0:
                    log(f"✓ Using selector: {selector}")
                    return page.locator(selector).all()
            except Exception as e:
                log(f"Error checking {selector}: {e}")
                continue
        
        # If we got here, we didn't find any jobs
        log("Warning: No job listings found with any selector")
        
        # Dump page source to file for debugging
        try:
            with open(debug_artifact_path("linkedin_page_source.html"), "w", encoding="utf-8") as f:
                f.write(page.content())
            log(f"Dumped page source to {debug_artifact_path('linkedin_page_source.html')}")
            page.screenshot(path=debug_artifact_path("linkedin_no_jobs_debug.png"))
        except:
            pass
            
        return []
        
    except Exception as e:
        log(f"Error getting job listings: {e}")
        return []


def handle_easy_apply(page, job_card):
    """
    Handle the Easy Apply process for a single job.
    Returns True if successfully applied, False otherwise.
    """
    log("Entering handle_easy_apply...")
    try:
        # Get job title for logging
        try:
            # Look for title inside the card - use timeout to prevent hanging
            job_title_el = job_card.locator(".job-card-list__title, .artdeco-entity-lockup__title, strong").first
            job_title = job_title_el.inner_text(timeout=1000)
            log(f"Processing job: {job_title[:50]}...")
        except:
            job_title = "Unknown Job"
            log("Processing job (title not found)...")
        
        # Click on the job card to view details
        log("Clicking job card...")
        try:
            job_card.click(timeout=2000)
        except:
            log("Click failed, trying JS click...")
            job_card.evaluate("node => node.click()")
            
        random_delay(1, 1.5)  # Reduced from 2-3 seconds
        
        # Wait for job details to load
        try:
            # Wait for the details pane to update
            page.wait_for_selector(".jobs-details, .jobs-search__job-details--container", timeout=3000)
        except:
            log("Job details didn't load quickly, continuing anyway...")
        
        # Check for Easy Apply button with multiple selectors
        easy_apply_btn = None
        easy_apply_selectors = [
            "button.jobs-apply-button",
            "button:has-text('Easy Apply')",
            ".jobs-apply-button",
            "button[aria-label*='Easy Apply']"
        ]
        
        for selector in easy_apply_selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible():
                    easy_apply_btn = btn
                    log(f"Found Easy Apply button with selector: {selector}")
                    break
            except:
                continue
        
        if not easy_apply_btn:
            log("No Easy Apply button found. Skipping this job.")
            return False
        
        # Check if already applied
        try:
            if page.locator("button:has-text('Applied')").first.is_visible():
                log("Already applied to this job. Skipping.")
                return False
        except:
            pass
        
        # Click Easy Apply
        log("Clicking Easy Apply button...")
        try:
            easy_apply_btn.click(timeout=2000)
        except:
             easy_apply_btn.evaluate("node => node.click()")
             
        random_delay(1, 1.5)  # Reduced from 2-3 seconds
        
        # Handle the multi-step Easy Apply modal
        max_steps = 20  # Increased max steps just in case
        current_step = 0
        max_time = 25  # Reduced timeout to 25 seconds per job
        start_time = time.time()
        last_log_time = time.time()
        
        while current_step < max_steps:
            # Check timeout
            elapsed = time.time() - start_time
            if elapsed > max_time:
                log(f"Timeline exceeded ({int(elapsed)}s). Moving to next job...")
                # Try to close modal before leaving
                try:
                    page.keyboard.press("Escape")
                except:
                    pass
                return False
            
            # Log periodic status
            if time.time() - last_log_time > 5:
                log(f"Still processing application... ({int(elapsed)}s elapsed)")
                last_log_time = time.time()
            
            random_delay(0.5, 0.8)
            
            # Check if application is complete
            # Updated to handle "Your application was sent to..." pattern
            if page.locator("h3:has-text('Application sent')").is_visible() or \
               page.locator("h2:has-text('Application sent')").is_visible() or \
               page.locator("h2:has-text('Your application was sent')").is_visible() or \
               page.locator("span:has-text('Your application was sent')").is_visible():
                log("Application sent successfully!")
                
                # Close the modal
                try:
                    # Try detection of done button which is often present
                    done_btn = page.locator("button:has-text('Done')").first
                    if done_btn.is_visible():
                        done_btn.click()
                    else:
                        # Close using dismiss button (X)
                        close_btn = page.locator("button[aria-label='Dismiss']").first
                        if close_btn.is_visible():
                            close_btn.click()
                except:
                    pass
                
                return True
            
            # Find and click Next / Review / Submit button
            button_clicked = False  # Initialize here to prevent UnboundLocalError
            try:
                # Strategy: Identify the primary action button in the footer
                try:
                    # The footer usually contains the primary action buttons
                    footer_btn = page.locator(".jobs-easy-apply-footer__actions .artdeco-button--primary, .jobs-easy-apply-modal__footer .artdeco-button--primary").first
                    if footer_btn.is_visible() and footer_btn.is_enabled():
                        btn_text = footer_btn.inner_text().strip()
                        log(f"Found primary footer button: '{btn_text}'")
                        if btn_text in ["Next", "Review", "Submit application", "Submit"]:
                            try:
                                footer_btn.click(timeout=1000)
                            except:
                                footer_btn.evaluate("node => node.click()")
                            button_clicked = True
                            current_step += 1
                            random_delay(1, 2)
                    
                    if not button_clicked:
                         # Fallback to text matching if footer selector fails
                        action_buttons = [
                            "button[aria-label='Submit application']",
                            "button[aria-label='Review your application']", 
                            "button[aria-label='Continue to next step']",
                            "button.artdeco-button--primary"  # Catch-all for primary button
                        ]
                        
                        for selector in action_buttons:
                            btn = page.locator(selector).first
                            if btn.is_visible() and btn.is_enabled():
                                # Verify text content for catch-all
                                if "artdeco-button--primary" in selector:
                                    text = btn.inner_text().lower()
                                    if "save" in text or "cancel" in text:
                                        continue
                                
                                log(f"Clicking button: {selector}")
                                try:
                                    btn.click(timeout=1000)
                                except:
                                    btn.evaluate("node => node.click()")
                                button_clicked = True
                                current_step += 1
                                random_delay(1, 2)
                                break
                except Exception as e:
                    pass
                
                if not button_clicked:
                     # Check if we are stuck on privacy policy scroll
                     # Sometimes "Next" is disabled until you scroll
                     pass
            except Exception as e:
                log(f"Error clicking button: {e}")

            # Fill in phone number if requested
            phone_input = page.locator("input[id*='phoneNumber']").first
            if phone_input.is_visible() and not phone_input.input_value():
                if LINKEDIN_PHONE:
                    log("Filling phone number...")
                    phone_input.fill(LINKEDIN_PHONE)
                    random_delay(0.5, 1)
            
            # Handle dropdown/select menus
            try:
                selects = page.locator("select:visible").all()
                for select in selects:
                    try:
                        # Check if already selected
                        current_value = select.input_value()
                        if current_value and current_value != "" and "select" not in current_value.lower():
                            continue
                        
                        # Get all options
                        options = select.locator("option").all()
                        if len(options) > 1:
                            # Try to find a "Yes" option first
                            yes_option_value = None
                            for i, opt in enumerate(options):
                                text = opt.inner_text().lower()
                                val = opt.get_attribute("value")
                                if "yes" in text or "start" in text or "comfortable" in text:
                                    yes_option_value = val
                                    break
                            
                            if yes_option_value:
                                select.select_option(value=yes_option_value)
                                log(f"Selected 'Yes' dropdown option")
                            else:
                                # Fallback to second option (index 1)
                                select.select_option(index=1)
                                log(f"Selected generic dropdown option")
                            
                            
                            # Force event dispatch to ensure UI detects change
                            select.evaluate("e => e.dispatchEvent(new Event('change', {bubbles: true}))")
                            random_delay(0.3, 0.7)
                    except Exception as e:
                        pass
            except:
                pass
            
            
            # Handle text and number inputs
            # STRICTLY exclude hidden, disabled, or read-only inputs
            text_inputs = page.locator("input[type='text']:visible:not([disabled]):not([readonly]), input[type='number']:visible:not([disabled]):not([readonly]), input[type='tel']:visible:not([disabled]):not([readonly])").all()
            for inp in text_inputs:
                try:
                    # Skip if already filled
                    if inp.input_value():
                        continue
                    
                    placeholder = inp.get_attribute("placeholder") or ""
                    label_text = ""
                    
                    # Try to get associated label
                    try:
                        inp_id = inp.get_attribute("id")
                        if inp_id:
                            label = page.locator(f"label[for='{inp_id}']").first
                            if label.is_visible():
                                label_text = label.inner_text().lower()
                    except:
                        pass
                    
                    combined = (placeholder + " " + label_text).lower()
                    
                    # Fill based on context
                    if "phone" in combined or "mobile" in combined:
                        if LINKEDIN_PHONE:
                            inp.fill(LINKEDIN_PHONE)
                            log("Filled phone number")
                    elif "city" in combined or "location" in combined:
                        inp.fill("Bengaluru")
                        log("Filled location")
                    elif "year" in combined or "experience" in combined:
                        # Default to 4 years for experience questions
                        inp.fill("4")
                        log(f"Filled experience field: {combined[:30]}")
                    elif "notice" in combined:
                         # Notice period usually requires a number (days)
                        inp.fill("30")
                        log("Filled notice period (30)")
                    elif "salary" in combined or "compensation" in combined or "ctc" in combined:
                        # Check for "in Lacs" or "LPA"
                        if "lacs" in combined or "lpa" in combined:
                             # Expected format: 25.0
                            if "month" in combined:
                                inp.fill("3.0")
                                log("Filled monthly salary (Lacs)")
                            else:
                                inp.fill("45.0") # User requested 45-55 Lakhs
                                log("Filled annual salary (Lacs)")
                        
                        # Check if it asks for MONTHLY (full number)
                        elif "month" in combined:
                            inp.fill("300000") # 3 Lakhs monthly
                            log("Filled monthly salary expectation (3L)")
                        else:
                            # User requested 45-55 Lakhs
                            inp.fill("4500000") 
                            log("Filled annual salary expectation (45L)")
                    else:
                        # For any other empty required field, put a safe default
                        # BUT skip if it looks like a search box or filter
                        if "search" in combined or "filter" in combined:
                            continue
                            
                        try:
                            inp.fill("N/A", timeout=1000)
                            log(f"Filled field with N/A: {combined[:30]}")
                        except:
                            pass
                    
                    random_delay(0.3, 0.7)
                    
                except Exception as e:
                    log(f"Could not fill input: {e}")
            
            # Handle Text Areas (Open-ended questions)
            try:
                textareas = page.locator("textarea:visible").all()
                for ta in textareas:
                    # Skip if already filled
                    if ta.input_value():
                        continue
                        
                    label = ""
                    try:
                        uid = ta.get_attribute("id")
                        if uid:
                            label = page.locator(f"label[for='{uid}']").first.inner_text().lower()
                    except:
                        pass
                        
                    if "cover letter" in label:
                        # Skip cover letter or fill short one if required? Usually skip
                        pass
                    elif "summary" in label or "describe" in label or "experience" in label:
                        ta.fill("I have over 4 years of experience in AI/ML, focusing on Generative AI, LLMs, and Python. Validated and deployed models to production.")
                        log("Filled generic experience summary")
                    else:
                         ta.fill("Please refer to my attached resume for detailed information.")
                         log("Filled generic textarea response")
                    random_delay(0.5, 1)
            except:
                pass

            # Handle radio buttons - select "Yes" options
            try:
                yes_options = page.locator("label:has-text('Yes'):visible").all()
                for opt in yes_options[:3]:  # Limit to first 3 to avoid spam
                    try:
                        opt.click()
                        log("Selected 'Yes' radio button")
                        random_delay(0.3, 0.7)
                    except:
                        pass
            except:
                pass

            # Handle Next / Submit logic (Consolidated)
            # We already tried clicking the footer button at the start of the loop (lines 325-377)
            # If we clicked something there, we should have skipped the rest or checked success.
            # But the previous logic didn't 'continue'.
            
            if button_clicked:
                 # Check for success immediately after click
                random_delay(0.5, 1)
                
                # Check for "Done" button (Fast Path)
                done_btn = page.locator("button.artdeco-button--primary:has-text('Done'), button:has-text('Done')").first
                if done_btn.is_visible():
                    log("Found 'Done' button immediately! Clicking...")
                    try:
                        done_btn.click()
                    except:
                        done_btn.evaluate("node => node.click()")
                    
                    # Log success
                    log("Application successful (clicked Done).")
                    return True
                
                continue
            
            # If we didn't click a button at the start, maybe we needed to fill forms first (which we just did)
            # NOW try to find the button again if we missed it the first time (e.g., button became enabled after filling)
            
            try:
                # Try finding footer button again
                footer_btn = page.locator(".jobs-easy-apply-footer__actions .artdeco-button--primary").first
                if footer_btn.is_visible() and footer_btn.is_enabled():
                    btn_text = footer_btn.inner_text().strip()
                    if btn_text in ["Next", "Review", "Submit application", "Submit"]:
                        log(f"Clicking footer button (post-fill): {btn_text}")
                        try:
                            footer_btn.click(timeout=1000)
                        except:
                            footer_btn.evaluate("node => node.click()")
                        current_step += 1
                        
                        # Immediate Success Check
                        random_delay(0.5, 1)
                        if page.locator("button:has-text('Done')").is_visible():
                             page.locator("button:has-text('Done')").click()
                             log("Application successful (Done).")
                             return True
                        
                        continue
            except:
                pass
            
            # If no actionable button found, increment step and loop
            current_step += 1
            
            # Check if there's an error or we need to exit
            if current_step >= max_steps:
                log("Reached max steps without completing. May need manual intervention.")
                break
        
        # If we get here without seeing success, assume failure
        log("Application process incomplete or failed.")
        
        # Try to close modal
        try:
            dismiss_btn = page.locator("button[aria-label='Dismiss']").first
            if dismiss_btn.is_visible():
                dismiss_btn.click()
        except:
            pass
        
        return False
        
    except Exception as e:
        log(f"Error handling Easy Apply: {e}")
        return False

def run(target_count=None, keywords=None, headless: bool = False):
    """
    Main function to run the LinkedIn job application bot.
    
    Args:
        target_count: Number of jobs to apply to. If None, uses TARGET_APPLY_COUNT.
        keywords: List of job titles/keywords to search for. If None, uses KEYWORDS.
    """
    global KEYWORDS
    
    if target_count is None:
        target_count = TARGET_APPLY_COUNT
    
    if keywords is not None:
        KEYWORDS = keywords
        log(f"Using custom job titles: {KEYWORDS}")
    
    if not LINKEDIN_EMAIL or not LINKEDIN_PASSWORD:
        log("Error: Missing LinkedIn credentials. Please configure in settings.")
        sys.exit(1)

    log(f"Starting LinkedIn job applier with target: {target_count} applications")

    with sync_playwright() as p:
        preferred = ["webkit", "firefox", "chromium"] if headless else ["chromium", "webkit", "firefox"]
        engine, browser = launch_browser(p, headless=headless, preferred_engines=preferred, log=log)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720},
            locale="en-US"
        )
        page = context.new_page()
        
        try:
            # Login
            login(page)
            
            # Search for jobs
            search_jobs(page)
            
            # Apply Easy Apply filter
            apply_easy_apply_filter(page)
            
            # Track applications
            applications_count = 0
            pages_checked = 0
            max_pages = 10  # Limit to prevent infinite loop
            
            while applications_count < target_count and pages_checked < max_pages:
                # Get job listings on current page
                job_cards = get_job_listings(page)
                
                if not job_cards:
                    log("No more job listings found.")
                    break
                
                # Try to apply to each job
                for job_card in job_cards:
                    if applications_count >= target_count:
                        break
                    
                    try:
                        # Extract basic info for logging before clicking
                        try:
                            title_el = job_card.locator(".base-search-card__title, .job-card-list__title, strong").first
                            company_el = job_card.locator(".base-search-card__subtitle, .job-card-container__company-name").first
                            url_el = job_card.locator("a").first
                            job_title = title_el.inner_text().strip() if title_el.is_visible() else "Unknown Title"
                            company = company_el.inner_text().strip() if company_el.is_visible() else "Unknown Company"
                            job_url = url_el.get_attribute("href") or page.url
                        except Exception:
                            job_title = "Unknown Title"
                            company = "Unknown Company"
                            job_url = page.url

                        success = handle_easy_apply(page, job_card)
                        if success:
                            applications_count += 1
                            log(f"✓ Progress: {applications_count}/{target_count} applications")
                            try:
                                log_application("LinkedIn", company, job_title, job_url)
                            except Exception as e:
                                log(f"Failed to log application: {e}")
                        
                        random_delay(2, 4)
                        
                    except Exception as e:
                        log(f"Error processing job: {e}")
                        continue
                
                # Check if we need to go to next page
                if applications_count < target_count:
                    try:
                        next_page_btn = page.locator("button[aria-label='View next page']").first
                        if next_page_btn.is_visible() and next_page_btn.is_enabled():
                            log("Moving to next page of results...")
                            next_page_btn.click()
                            random_delay(3, 5)
                            pages_checked += 1
                        else:
                            log("No more pages available.")
                            break
                    except:
                        log("Could not navigate to next page.")
                        break
            
            log(f"Completed! Successfully applied to {applications_count} jobs.")
            
            # Update statistics
            from pathlib import Path
            import json
            
            stats_file = get_data_dir() / "linkedin_stats.json"
            
            # Load existing stats
            if stats_file.exists():
                with open(stats_file, 'r') as f:
                    stats = json.load(f)
            else:
                stats = {
                    "total_applications": 0,
                    "today_count": 0,
                    "last_run": None,
                    "success_count": 0,
                    "daily_history": {}
                }
            
            # Update stats. Check the previous last_run before overwriting it so
            # the daily counter resets correctly at midnight.
            today = str(datetime.now().date())
            previous_last_run = str(stats.get("last_run") or "")
            stats["total_applications"] = int(stats.get("total_applications", 0)) + applications_count
            stats["success_count"] = int(stats.get("success_count", 0)) + applications_count
            stats["today_count"] = (int(stats.get("today_count", 0)) if previous_last_run.startswith(today) else 0) + applications_count
            stats["last_run"] = str(datetime.now())
            stats.setdefault("daily_history", {})
            stats["daily_history"][today] = int(stats["daily_history"].get(today, 0)) + applications_count
            
            # Save stats
            with open(stats_file, 'w') as f:
                json.dump(stats, f, indent=2)
            
            log(f"Statistics updated: Total applications = {stats['total_applications']}")
            
        except Exception as e:
            log(f"An error occurred: {str(e)}")
            page.screenshot(path=debug_artifact_path("linkedin_error_screenshot.png"))
            raise e
        finally:
            log("Closing browser...")
            browser.close()
            log("Finished.")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='LinkedIn Easy Apply Job Automation')
    parser.add_argument('--target', type=int, default=TARGET_APPLY_COUNT,
                       help=f'Target number of applications (default: {TARGET_APPLY_COUNT})')
    parser.add_argument('--keywords', type=str, nargs='+',
                       help='Job keywords to search for (space-separated)')
    parser.add_argument(
        '--headless',
        action='store_true',
        help='Run browser in headless mode (no visible Chromium window). Recommended for scheduled/background runs.'
    )
    
    args = parser.parse_args()
    
    keywords = args.keywords if args.keywords else None
    run(target_count=args.target, keywords=keywords, headless=args.headless)
