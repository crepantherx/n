import os
import sys
import time
import random
import urllib.parse
import json
from datetime import datetime
from playwright.sync_api import sync_playwright
from config_loader import load_config, get_data_dir
from application_logger import log_application
from playwright_helpers import launch_browser
from region_config import get_region_config, is_naukri_supported, get_geolocation, get_locale

# Load configuration from config.json or .env
config = load_config()
EMAIL = config["email"]
PASSWORD = config["password"]

# Configuration
_default_titles = config.get("job_titles") or "ML Engineer, AI Engineer, Software Engineer"
KEYWORDS = [t.strip() for t in _default_titles.split(",") if t.strip()] or ["ML Engineer", "AI Engineer", "Software Engineer"]
MIN_SALARY_LPA = 45 # We will look for filters that match this roughly or higher
TARGET_APPLY_COUNT = 30  # Default target, can be overridden via command-line

DEBUG_DIR = get_data_dir() / "debug"

def debug_artifact_path(name: str) -> str:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    return str(DEBUG_DIR / name)

def log(message):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")

def random_delay(min_seconds=0.5, max_seconds=1.5):
    time.sleep(random.uniform(min_seconds, max_seconds))

def update_stats(applied_count: int) -> None:
    stats_file = get_data_dir() / "stats.json"
    stats = {"total_applications": 0, "today_count": 0, "last_run": None, "success_count": 0, "daily_history": {}}
    if stats_file.exists():
        try:
            loaded = json.loads(stats_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                stats.update(loaded)
        except Exception:
            pass

    today = str(datetime.now().date())
    previous_last_run = str(stats.get("last_run") or "")
    stats["total_applications"] = int(stats.get("total_applications", 0)) + applied_count
    stats["success_count"] = int(stats.get("success_count", 0)) + applied_count
    stats["today_count"] = (int(stats.get("today_count", 0)) if previous_last_run.startswith(today) else 0) + applied_count
    stats["last_run"] = str(datetime.now())
    stats.setdefault("daily_history", {})
    stats["daily_history"][today] = int(stats["daily_history"].get(today, 0)) + applied_count

    stats_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = stats_file.with_suffix(stats_file.suffix + ".tmp")
    tmp.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    tmp.replace(stats_file)


def login(page):
    log("Navigating to login page...")
    resp = page.goto("https://www.naukri.com/nlogin/login", timeout=60000)
    if resp is not None and resp.status == 403:
        page.screenshot(path=debug_artifact_path("login_access_denied.png"))
        raise Exception(
            "Naukri returned HTTP 403 (Access Denied). "
            "This usually happens with headless Chromium. "
            "Install WebKit/Firefox browsers (python3 -m playwright install webkit firefox) "
            "or run without --headless."
        )
    random_delay()

    log("Waiting for username field...")
    try:
        page.wait_for_selector("#usernameField", state="visible", timeout=10000)
        page.fill("#usernameField", EMAIL)
        random_delay(0.5, 1.5)
        page.fill("#passwordField", PASSWORD)
        random_delay(0.5, 1.5)
        page.click("button[type='submit'], button.blue-btn")
        
        # Wait for login to complete (homepage or dashboard)
        page.wait_for_url("**/mnjuser/homepage**", timeout=30000)
        log("Login successful.")
        random_delay()
    except Exception as e:
        log(f"Login failed: {e}")
        page.screenshot(path=debug_artifact_path("login_failure.png"))
        raise e

def search_jobs(page):
    query = ", ".join(KEYWORDS)
    log(f"Searching for: {query}")
    
    # Read the region filter from config
    region = config.get("region_naukri", "Indian")
    region_cfg = get_region_config(region)
    naukri_location = region_cfg.get("naukri_location")  # None = no location filter (all India)
    if naukri_location:
        log(f"Location filter: {naukri_location}")
    
    # Always use direct URL navigation. It's more robust and allows us to easily inject the location parameter.
    encoded_query = "-".join([kw.lower().replace(" ", "-") for kw in KEYWORDS])
    
    if naukri_location:
        # Construct the complex URL path required by Naukri for specific locations
        # e.g., "United Kingdom (UK)" -> "united-kingdom-uk"
        loc_path = naukri_location.lower().replace(" ", "-").replace("(", "").replace(")", "")
        loc_url_param = urllib.parse.quote(naukri_location.lower())
        search_url = f"https://www.naukri.com/{encoded_query}-jobs-in-{loc_path}?k={encoded_query}&l={loc_url_param}"
    else:
        search_url = f"https://www.naukri.com/{encoded_query}-jobs?k={encoded_query}"
        
    log(f"Navigating to search results: {search_url}")
    
    page.goto(search_url, timeout=60000)
    try:
        page.wait_for_selector(".srp-container", timeout=20000) # Wait for results
        log("Search results loaded.")
    except Exception:
        log("Warning: Could not verify search results container loaded.")

    random_delay(2, 4)

def apply_filters(page):
    """
    Apply filters: Use URL for experience, then click salary checkboxes for all ranges.
    """
    log("Applying experience filter via URL...")
    
    # Get the current URL
    current_url = page.url
    
    # Check if URL already has parameters
    separator = "&" if "?" in current_url else "?"
    
    # Experience: 5 years minimum (URL parameter approach works reliably)
    filter_params = "experience=5"
    
    # Construct the new URL with experience filter
    filtered_url = current_url + separator + filter_params
    
    log(f"Navigating to filtered URL: {filtered_url}")
    
    try:
        page.goto(filtered_url, timeout=60000)
        log("Experience filter applied via URL")
        random_delay(2, 4)
        
        # Wait for results to load
        try:
            page.wait_for_selector("div.srp-jobtuple-wrapper", timeout=10000)
            log("Page loaded with experience filter")
        except:
            log("Warning: Job results may not have loaded completely")
            
    except Exception as e:
        log(f"Error applying experience filter via URL: {e}")
    
    # Now apply ALL salary filters by clicking checkboxes
    # Include: 25-50 Lakhs, 50-75 Lakhs, 75-100 Lakhs, 1-5 Cr, 5 Cr+
    log("Applying salary filters (all ranges from 25 LPA onwards)...")
    
    salary_targets = [
        "25-50 Lakhs",
        "50-75 Lakhs", 
        "75-100 Lakhs", 
        "1-5 Cr", 
        "5 Cr+",
        "5Cr+",  # Alternative format
    ]
    
    # Also try lower ranges if available (20-25, etc.)
    additional_targets = ["20-25 Lakhs", "20-30 Lakhs", "30-35 Lakhs", "35-40 Lakhs", "40-50 Lakhs"]
    
    all_targets = additional_targets + salary_targets
    
    clicked_count = 0
    for target in all_targets:
        try:
            # Look for label containing text
            filter_item = page.locator(f"label:has-text('{target}')").first
            if filter_item.is_visible():
                # Check if already checked to avoid unchecking
                try:
                    checkbox = filter_item.locator("..").locator("input[type='checkbox']").first
                    if checkbox.is_checked():
                        log(f"Salary filter already checked: {target}")
                        clicked_count += 1
                        continue
                except:
                    pass
                
                filter_item.click()
                log(f"Clicked salary filter: {target}")
                clicked_count += 1
                random_delay(1, 2)
        except Exception:
            pass
    
    if clicked_count > 0:
        log(f"Applied {clicked_count} salary filters")
    else:
        log("Warning: No salary filters found or clickable")
    
    random_delay(1, 2)

def handle_apply(context, job_url):
    """
    Handles the application process for a single job safely.
    Returns True if successfully applied, False otherwise.
    """
    try:
        # Create new page manually and navigate (Faster/More reliable than clicking)
        t_start = time.time()
        new_page = context.new_page()
        
        try:
            log(f"Navigating to job (Time: {time.time() - t_start:.2f}s)...")
            # 'commit' returns as soon as server responds. We don't wait for parsing.
            new_page.goto(job_url, timeout=45000, wait_until="commit")
            log(f"Navigation/Commit done (Time: {time.time() - t_start:.2f}s). Checking content...")
        except:
            log("Navigation timeout or error. Proceeding...")
        
        # We don't wait for 'domcontentloaded' explicitly anymore.
        # We will just look for the Apply button immediately.
        # This effectively makes it: "Load as much as needed to see the button"
        
        # Check for "Apply" on the job page with a short timeout to avoid delays
        # Strict Check: If it says "Apply on Company Website", we SKIP.
        
        # Try to find apply button with explicit short timeout
        try:
            job_apply_btn = new_page.locator("button.apply-button, button#apply-button, button:has-text('Apply')").first
            # Wait max 2 seconds for apply button to appear
            job_apply_btn.wait_for(state="visible", timeout=2000)
            apply_btn_visible = True
        except:
            apply_btn_visible = False
        
        def handle_external_apply(btn) -> bool:
            log("Button indicates external site. Intercepting new tab to apply via intl_form_filler...")
            try:
                from intl_career_page_crawler import load_intl_config
                from intl_form_filler import fill_career_form
                user_data = load_intl_config()
                
                # Check if clicking the button opens a new tab
                try:
                    with context.expect_page(timeout=10000) as ext_page_info:
                        btn.click()
                    ext_page = ext_page_info.value
                except Exception:
                    # Maybe it navigated in the same tab?
                    log("No new tab opened. Using the same page.")
                    ext_page = new_page
                
                ext_page.wait_for_load_state("domcontentloaded", timeout=15000)
                log(f"Intercepted external page: {ext_page.url}")
                
                # Look for Apply button on the external job description page
                apply_btns = [
                    "a:has-text('Apply')", "button:has-text('Apply')",
                    "a:has-text('Apply Now')", "button:has-text('Apply Now')",
                    "a:has-text('Apply for this job')", "button:has-text('Apply for this job')",
                    "a[href*='apply']",
                ]
                clicked_apply = False
                for sel in apply_btns:
                    try:
                        ext_btn_local = ext_page.locator(sel).first
                        if ext_btn_local.is_visible():
                            log("Clicking Apply button on external site...")
                            try:
                                with context.expect_page(timeout=5000) as ext_form_page_info:
                                    ext_btn_local.click()
                                form_page = ext_form_page_info.value
                                log("Apply button opened a new tab.")
                                ext_page.close()
                                ext_page = form_page
                            except Exception:
                                # Navigated in same tab or just opened a modal
                                log("Apply button did not open a new tab.")
                                try:
                                    ext_page.wait_for_load_state("domcontentloaded", timeout=10000)
                                except Exception:
                                    pass
                                random_delay(2, 3)
                                
                            clicked_apply = True
                            break
                    except Exception:
                        continue
                        
                if not clicked_apply:
                    log("No apply button found on external site immediately, assuming we are on the form page.")
                
                # Give JS frameworks (Workday/Lever) a moment to render the form fields
                try:
                    ext_page.wait_for_selector("input, textarea, select, [role='combobox']", state="visible", timeout=10000)
                except Exception:
                    log("Warning: No form inputs appeared after 10s. Trying to proceed anyway...")

                success = fill_career_form(ext_page, user_data)
                
                # If we opened a new tab, close it. If it's the same tab, we'll close it later anyway.
                if ext_page != new_page:
                    ext_page.close()
                    
                return success
            except Exception as e:
                log(f"Failed to handle external apply: {e}")
                return False

        if not apply_btn_visible:
            # Check for Already Applied with short timeout
            try:
                new_page.locator("button:has-text('Already Applied')").first.wait_for(state="visible", timeout=1000)
                log("Already applied.")
                new_page.close()
                return False
            except:
                pass
            
            # Check for Company Website explicitly with short timeout
            try:
                ext_btn = new_page.locator("text=Company Website, text=Apply on company website").first
                ext_btn.wait_for(state="visible", timeout=1000)
                success = handle_external_apply(ext_btn)
                new_page.close()
                return success
            except:
                pass

            log("Apply button not found or it's external.")
            new_page.close()
            return False
            
        # Double check button text just in case
        btn_text = job_apply_btn.inner_text().lower()
        if "company" in btn_text or "website" in btn_text:
             success = handle_external_apply(job_apply_btn)
             new_page.close()
             return success

        # Click Apply
        log("Clicking Apply button...")
        job_apply_btn.click()
        random_delay()
        
        # Handle Chatbot / Questionnaire / Modal
        # Common inputs: Experience, Location, Radio buttons (Yes/No), Notice Period, Chatbot text inputs
        
        attempts = 0
        while attempts < 15: # Increased attempts
            random_delay(1, 2)
            
            # Check for Success first
            if new_page.locator("text=applied successfully").is_visible() or new_page.locator("text=Application sent").is_visible():
                log("Application successful!")
                new_page.close()
                return True

            # 1. Text Inputs (Years, Location, Notice Period, Chatbot generic, Explanations)
            
            # DEBUG: Log all visible inputs to be sure (including contenteditable)
            if attempts == 0:
                try:
                    # Check standard inputs and contenteditable divs
                    inps = new_page.locator("input, textarea, [contenteditable]").all()
                    log(f"--- DEBUG: Visible Inputs ({len(inps)}) ---")
                    for x in inps:
                        if x.is_visible():
                            ph = x.get_attribute("placeholder") or "No Placeholder"
                            val = x.input_value() if x.evaluate("el => el.tagName") in ["INPUT", "TEXTAREA"] else x.inner_text()
                            tag = x.evaluate("el => el.tagName")
                            log(f"   [{tag}] Placeholder: '{ph}' | Value: '{val}'")
                    log("--- END DEBUG ---")
                except: pass

            # Read context from the chatbot container to understand the question
            # The question is usually in a previous message bubble
            # We do this EARLY so both Text Input and Radio Logic can use it.
            full_context = ""
            try:
                # Get all text inside chatbot drawer/layer
                chat_context = new_page.locator("div[class*='chatbot']").all_inner_texts()
                full_context = " ".join(chat_context).lower()
            except:
                try:
                    full_context = new_page.inner_text().lower()
                except: pass

            # Only check the last part of the conversation (last 400 chars)
            # to avoid matching old questions
            recent_context = ""
            if len(full_context) > 400:
                recent_context = full_context[-400:]
            else:
                recent_context = full_context
                
            log(f"Chatbot recent context: ...{recent_context[-150:].replace(chr(10), ' ')}") 
            
            # Determine Answer Preference based on Context
            prefer_yes = False
            prefer_no = False
            
            # Negative Keywords (Prefer No)
            if "competitor" in recent_context or "employed by a client" in recent_context or "partner" in recent_context:
                prefer_no = True
                log("Context implies Negative answer (Competitor/Partner). Preferring 'No'.")
            
            # Positive Keywords (Prefer Yes)
            elif "authorized" in recent_context or "visa" in recent_context or "relocate" in recent_context or "relocation" in recent_context or "18 years" in recent_context:
                prefer_yes = True
                log("Context implies Positive answer (Authorized/Relocation/Age). Preferring 'Yes'.")

            # Prioritize Chatbot specific text input if present
            chatbot_input = new_page.locator("input[placeholder*='Type message'], textarea[placeholder*='Type message']").first
            if not chatbot_input.is_visible():
                 chatbot_input = new_page.locator("div[class*='chatbot'] input, div[class*='chatbot'] textarea").first
            if not chatbot_input.is_visible():
                 chatbot_input = new_page.locator("div[class*='chatbot'] [contenteditable]").first
            if not chatbot_input.is_visible():
                 chatbot_input = new_page.locator("[contenteditable]").first

            if chatbot_input.is_visible():
                # Check if empty.
                is_empty = False
                try:
                    if chatbot_input.evaluate("el => el.tagName") in ["INPUT", "TEXTAREA"]:
                        if not chatbot_input.input_value(): is_empty = True
                    else:
                        if not chatbot_input.inner_text().strip(): is_empty = True
                except: is_empty = True 

                if is_empty:
                    log(f"Chatbot recent context: ...{recent_context[-150:].replace(chr(10), ' ')}") 
                    
                    # Determine Active Topic by finding which keyword appears LATEST in the context
                    # This prevents answering an old question (e.g. "notice") when the new one is "salary"
                    
                    topic_keywords = {
                        "experience": ["experience", "years", "exp"],
                        "location": ["location", "city", "residing", "relocate"],
                        "notice": ["notice", "joining", "soon"],
                        "salary": ["ctc", "salary", "expectations", "budget"],
                        "auth": ["authorized", "visa"],
                        "competencies": ["competencies", "competency", "skills", "strengths"]
                    }
                    
                    best_topic = None
                    max_idx = -1
                    
                    # Check each topic
                    for topic, keys in topic_keywords.items():
                        for k in keys:
                            idx = recent_context.rfind(k)
                            if idx > max_idx:
                                max_idx = idx
                                best_topic = topic
                    
                    answer = ""
                    
                    # Generate Answer based on Best Topic
                    if best_topic == "experience":
                         answer = "5"
                         log(f"Chatbot asking for Experience (Context idx {max_idx}). Filling 5.")
                    elif best_topic == "location":
                         if "relocate" in recent_context[max_idx:]:
                             answer = "Yes"
                             log(f"Chatbot asking for Relocation (idx {max_idx}). Filling Yes.")
                         else:
                             answer = "Bengaluru"
                             log(f"Chatbot asking for Location (idx {max_idx}). Filling Bengaluru.")
                    elif best_topic == "notice":
                         answer = "60 days"
                         log(f"Chatbot asking for Notice Period (idx {max_idx}). Filling 60 days.")
                    elif best_topic == "salary":
                         # User requested 45-60 LPA. "50 LPA" or "5000000".
                         # Checking if text or number. Start with text-friendly "50 LPA" if generic, 
                         # but usually "5000000" works for numeric parsers. 
                         # Let's try "5000000" as it is standard.
                         answer = "5000000"
                         log(f"Chatbot asking for Salary (idx {max_idx}). Filling 5000000.")
                    elif best_topic == "auth":
                         answer = "Yes"
                         log(f"Chatbot asking for Authorization (idx {max_idx}). Filling Yes.")
                    elif best_topic == "competencies":
                         answer = "End-to-end ML model development, Data engineering and feature design, Production ML systems, Research related work"
                         log(f"Chatbot asking for Competencies (idx {max_idx}). Filling competencies list.")
                    
                    # Fallback if no specific topic found but input is empty
                    if not answer:
                        if prefer_yes: answer = "Yes"
                        elif prefer_no: answer = "No"
                    
                    filled = False
                    if answer:
                         try:
                             chatbot_input.click(force=True)
                             chatbot_input.fill(answer)
                             filled = True
                         except:
                             try:
                                 chatbot_input.click(force=True)
                                 new_page.keyboard.type(answer)
                                 filled = True
                             except: pass

                    if not filled:
                         # Generic catch-all
                         try:
                             log("Chatbot question unclear. Filling default summary.")
                             chatbot_input.fill("8 years exp in ML/Python. Bengaluru. Immediate joiner. 50 LPA.")
                         except: pass
            
            # Detect other generic inputs IF we are in a modal/drawer AND not text/chatbot input
            # This prevents filling the main search bar on the underlying page
            # We must scope the search to the modal container
            
            modal_container = None
            if new_page.locator("div.layer").is_visible(): modal_container = new_page.locator("div.layer").first
            elif new_page.locator("div.drawer").is_visible(): modal_container = new_page.locator("div.drawer").first
            elif new_page.locator("div.modal").is_visible(): modal_container = new_page.locator("div.modal").first
            elif new_page.locator("div.chatbot_Overlay").is_visible(): modal_container = new_page.locator("div.chatbot_Overlay").first
            elif new_page.locator("div[class*='chatbot']").is_visible(): modal_container = new_page.locator("div[class*='chatbot']").first

            if modal_container:
                text_inputs = modal_container.locator("input[type='text'], textarea, input:not([type])")
                count = text_inputs.count()
                
                for i in range(count):
                    inp = text_inputs.nth(i)
                    # Skip if it's the chatbot input we just handled (by checking value)
                    if inp.is_visible() and not inp.input_value():
                        # Check context (placeholder or nearby text)
                        try:
                            placeholder = inp.get_attribute("placeholder") or ""
                            # strict skip search bar - though scoping should fix this mostly
                            if "search" in placeholder.lower() or "keyword" in placeholder.lower(): continue
                            
                            parent_text = inp.locator("..").inner_text() or "" # Text of parent container
                            combined_text = (placeholder + " " + parent_text).lower()
                            
                            # Already handled?
                            if "years" in combined_text or "experience" in combined_text:
                                 if not inp.input_value():
                                     log("Answering Experience (Generic): 5") 
                                     # If it says 'Select', it might be a dropdown
                                     if "select" in placeholder.lower():
                                          inp.click()
                                          random_delay(0.5, 1)
                                          try:
                                              new_page.keyboard.type("5")
                                              new_page.keyboard.press("Enter")
                                          except: pass
                                     else:
                                          inp.fill("5")
                            elif "location" in combined_text or "city" in combined_text:
                                 if not inp.input_value():
                                     log("Answering Location (Generic): Bengaluru")
                                     inp.fill("Bengaluru")
                            elif "notice" in combined_text:
                                 if not inp.input_value():
                                     log("Answering Notice: 60 days")
                                     inp.fill("60 days")
                            elif "ctc" in combined_text or "salary" in combined_text:
                                 if not inp.input_value():
                                     inp.fill("5000000")
                            # Add preferences here too if generic inputs ask these
                            elif "authorized" in combined_text:
                                 inp.fill("Yes")
                            elif "competitor" in combined_text:
                                 inp.fill("No")
                            else:
                                 # Generic catch-all
                                 if "mobile" in combined_text or "name" in combined_text: continue
                                 log(f"Found generic text input ({placeholder}). Filling default.")
                                 inp.fill("I have 5 years of experience in Machine Learning and Python. I am based in Bengaluru.")
                        except:
                            pass
            else:
                # If no modal open, maybe we succeeded? Check for "Applied" status
                if new_page.locator("text=Applied").first.is_visible():
                    log("Job status is Applied. Success!")
                    new_page.close()
                    return True
                if new_page.locator("button:has-text('Applied')").first.is_visible():
                    log("Button says Applied. Success!")
                    new_page.close()
                    return True
            
            # 2. Radio Buttons / Yes-No questions
            # Example: "Previously Employed by Cognizant" -> No
            if new_page.locator("text=Previously Employed").is_visible():
                no_radio = new_page.locator("label:has-text('No')").first
                if no_radio.is_visible():
                    no_radio.click() # Just click, don't log every time to reduce noise
            # 2. Radio Buttons / Checkboxes / Chips / Options
            # Chatbot often uses Chips (Yes/No) or Radio Options (2+, 5+, etc)
            
            try:
                chatbot_layer = new_page.locator("div[class*='chatbot']").first
                if chatbot_layer.is_visible():
                    # 2a. Check for standard radio inputs AND checkboxes
                    # Use a combined list or separate? Separate is safer logic-wise.
                    
                    # --- CHECKBOXES (Select All That Apply) ---
                    checkboxes = chatbot_layer.locator("input[type='checkbox']")
                    checkboxes_clicked = False
                    if checkboxes.count() > 0:
                        log(f"Found {checkboxes.count()} checkboxes. Selecting positive options...")
                        count = checkboxes.count()
                        for i in range(count):
                            cb = checkboxes.nth(i)
                            if cb.is_visible() or True: 
                                id_val = cb.get_attribute("id")
                                label_text = ""
                                el_to_click = cb
                                
                                if id_val:
                                    lbl = chatbot_layer.locator(f"label[for='{id_val}']")
                                    if lbl.count() > 0:
                                        label_text = lbl.inner_text().strip()
                                        el_to_click = lbl.first
                                
                                if not label_text:
                                    parent = cb.locator("..")
                                    label_text = parent.inner_text().strip()
                                    el_to_click = parent

                                txt = label_text.lower()
                                # Skip negative options
                                if "not " in txt or "none" in txt or "i have not" in txt:
                                     log(f"Skipping negative checkbox: {label_text}")
                                     continue
                                
                                try:
                                    if not cb.is_checked():
                                        log(f"Selecting checkbox: {label_text}")
                                        el_to_click.click(force=True)
                                        checkboxes_clicked = True
                                        random_delay(0.2, 0.5)
                                except: pass

                        if checkboxes_clicked:
                            log("Checkboxes selected. Skipping fallback chip logic.")

                    # --- RADIO BUTTONS (Select One) ---
                    # Only proceed if we haven't already handled the question via checkboxes
                    if not checkboxes_clicked:
                        radios = chatbot_layer.locator("input[type='radio']")
                        best_el_to_click = None # Reset

                        if radios.count() > 0:
                            log(f"Found {radios.count()} radio buttons. Analyzing...")
                            # Find the "best" radio to click
                            # We want max experience (e.g. 5+ over 2+)
                            best_radio = None
                            best_el_to_click = None
                            max_val = -1

                            count = radios.count()
                            for i in range(count):
                                r = radios.nth(i)
                                if r.is_visible() or True:
                                    id_val = r.get_attribute("id")
                                    label_text = ""
                                    el_to_click = r

                                    if id_val:
                                        lbl = chatbot_layer.locator(f"label[for='{id_val}']")
                                        if lbl.count() > 0:
                                            label_text = lbl.inner_text().strip()
                                            el_to_click = lbl.first

                                    if not label_text:
                                        parent = r.locator("..")
                                        label_text = parent.inner_text().strip()
                                        el_to_click = parent

                                    log(f"Found Chatbot Radio Option: '{label_text}'")

                                    # Analyze text with CONTEXT PREFERENCE
                                    val = 0
                                    txt = label_text.lower()

                                    # Extract numbers to find the "max" value (for years of exp)
                                    import re
                                    numbers = re.findall(r'\d+', txt)
                                    if numbers:
                                        try:
                                            val = max([int(n) for n in numbers])
                                        except: pass

                                    # Specific overrides
                                    if "yes" in txt:
                                        if prefer_no: val = -100 # Strongly dislike Yes if prefer_no
                                        else: val = 100 # Default priority
                                    elif "no" in txt:
                                        if prefer_no: val = 100 # Strongly prefer No if prefer_no
                                        else: val = 1 # Default low priority

                                    # Boost "plus" or "+" options
                                    if "+" in txt:
                                        val += 0.5

                                    if val > max_val:
                                        max_val = val
                                        best_radio = r
                                        best_el_to_click = el_to_click

                            # Click the best one found
                            if best_el_to_click:
                                 log(f"Clicking best radio option element: {best_el_to_click} (Val: {max_val})")
                                 best_el_to_click.click(force=True)
                            elif count > 0:
                                 radios.last.click(force=True)

                        # 2b. Check for "Chips" or custom clickable divs/labels
                        else:
                            # Stricter locator: must have some text.
                            # We check visibility and text length inside loop, but explicit filter might be better.
                            potential_options = chatbot_layer.locator("label, div[class*='chip'], div[class*='option']").all()
                            best_opt = None
                            max_val = -1

                            for opt in potential_options:
                                 # Check visibility
                                 if not opt.is_visible(): continue

                                 txt = opt.inner_text().strip().lower()
                                 if not txt: continue # SKIP EMPTY TEXT
                                 if len(txt) > 30: continue # Skip long text (likely description or message)

                                 # Logic for finding best option
                                 val = 5 # Default value (prefer generic text over "No")
                                    
                                 import re
                                 numbers = re.findall(r'\d+', txt)
                                 if numbers:
                                      try:
                                          val = max([int(n) for n in numbers])
                                      except: pass

                                 if "yes" in txt: 
                                     if prefer_no: val = -100
                                     else: val = 100
                                 elif "no" in txt: 
                                     if prefer_no: val = 100
                                     else: val = 1
                                     
                                 if "+" in txt:
                                     val += 0.5

                                 log(f"Found Chatbot Chip/Option: '{txt}' (Val: {val})")

                                 if val > max_val:
                                     max_val = val
                                     best_opt = opt

                            if best_opt:
                                log(f"Clicking best Chip/Option: '{best_opt.inner_text()}' (Val: {max_val}).")
                                best_opt.click(force=True)
            except Exception as e:
                pass

            # General Radio/Checkbox Fallback (Outside Chatbot or if Chatbot logic failed)
            # Default to "Yes" for authorization/relocation
            yes_radio = new_page.locator("label").filter(has_text="Yes").or_(
                        new_page.locator("span").filter(has_text="Yes")
            ).first
            
            if yes_radio.is_visible():
                 # check if unselected (hard to tell for customs)
                 try:
                     yes_radio.click()
                 except: pass

            # 3. Submit / Save / Continue Buttons
            
            # Priority: Chatbot 'sendMsg' button
            # Debug logs showed: [DIV] Text: 'Save' | Class: 'sendMsg'
            # Click intercepted by container? Use force=True
            send_msg_btn = new_page.locator("div.sendMsg").first
            if send_msg_btn.is_visible():
                log("Found chatbot 'sendMsg' button. Clicking with force=True...")
                try:
                    send_msg_btn.click(force=True)
                    random_delay(2, 3)
                except Exception as e:
                    log(f"Failed to click sendMsg: {e}")
                    # Try clicking the container if inner failed
                    try:
                        new_page.locator("div.sendMsgbtn_container").first.click(force=True)
                    except: pass
            
            potential_btns = new_page.locator("button").filter(has_text="Save").or_(
                new_page.locator("button").filter(has_text="Submit")
            ).or_(
                new_page.locator("button").filter(has_text="Continue")
            )
            
            submit_clicked = False
            count = potential_btns.count()
            
            # Iterate
            for i in range(count):
                btn = potential_btns.nth(i)
                if btn.is_visible():
                    txt = btn.inner_text().strip()
                    cls = btn.get_attribute("class") or ""
                    
                    # Strict skip
                    if "save-job" in cls.lower() or "savejob" in cls.lower() or "star-icon" in cls.lower() or "saved-button" in cls.lower():
                        continue
                    if txt.lower() == "saved": 
                        continue
                    
                    # Log candidate
                    log(f"Candidate button: {txt} | Class: {cls}")
                    
                    # Identify the "best" one. 
                    # If we are in a modal, the button ideally shouldn't be the navbar search button (if that has 'save'?)
                    # Let's try clicking it.
                    try:
                        log(f"Clicking button: {txt} (Class: {cls})")
                        btn.click()
                        submit_clicked = True
                        break # Only click one per loop iteration to check results
                    except Exception as e:
                         log(f"Click failed: {e}")

            if not submit_clicked:
                 # Fallback to non-button elements (divs acting as buttons)
                 # Same logic: strict skip "save-job"
                 potential_divs = new_page.locator("div[role='button'], a[role='button'], span[role='button'], div.btn, span.btn").filter(has_text="Save").or_(
                     new_page.locator("div[role='button'], a[role='button'], span[role='button'], div.btn, span.btn").filter(has_text="Submit")
                 ).or_(
                     new_page.locator("div[role='button'], a[role='button'], span[role='button'], div.btn, span.btn").filter(has_text="Continue")
                 )
                 
                 d_count = potential_divs.count()
                 for i in range(d_count):
                     elem = potential_divs.nth(i)
                     if elem.is_visible():
                         txt = elem.inner_text().strip()
                         cls = elem.get_attribute("class") or ""
                         if "save-job" in cls.lower(): continue
                         if txt.lower() in ["save", "submit", "continue", "next"]:
                             try:
                                 log(f"Clicking non-button: {txt} (Class: {cls})")
                                 elem.click()
                                 break
                             except: pass

            random_delay(2, 3) # Wait for processing
            
            # Check success again
            if new_page.locator("text=applied successfully").is_visible() or new_page.locator("text=Application sent").is_visible():
                 log("Application successful!")
                 new_page.close()
                 return True
                 
            attempts += 1
        
        # Final check
        if new_page.locator("text=applied successfully").is_visible() or new_page.locator("text=Application sent").is_visible():
            log("Application successful!")
            new_page.close()
            return True
            
        log("Application flow finished without confirmation. Closing.")
        new_page.close()
        return False

    except Exception as e:
        log(f"Error handling job: {e}")
        return False

def run(target_count=None, keywords=None, headless: bool = False):
    """
    Main function to run the job application bot.
    
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
    
    if not EMAIL or not PASSWORD:
        log("Error: Missing credentials.")
        sys.exit(1)

    region = config.get("region_naukri", "Indian")
    log(f"Starting job applier with target: {target_count} applications (region: {region})")

    # Get region-specific browser context hints
    geo = get_geolocation(region)
    locale = get_locale(region)

    with sync_playwright() as p:
        # Naukri blocks headless Chromium with HTTP 403 ("Access Denied") very often.
        # On macOS, headless WebKit/Firefox tend to work reliably, so we prefer those.
        preferred = ["webkit", "firefox", "chromium"] if headless else ["chromium", "webkit", "firefox"]
        engine, browser = launch_browser(p, headless=headless, preferred_engines=preferred, log=log)
        # Configure context to deny geolocation and notifications
        context_kwargs = {
            "viewport": {"width": 1280, "height": 720},
            "permissions": [],  # deny all
            "geolocation": geo,
            "locale": locale,
        }
        if engine == "chromium":
            context_kwargs["user_agent"] = (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )

        context = browser.new_context(**context_kwargs)
        # Grant permissions logic
        context.grant_permissions([], origin="https://www.naukri.com") 
        
        # Removed resource blocking as it caused net::ERR_ABORTED
        # context.route("**/*.{png,jpg,jpeg,svg,gif,webp,woff,woff2}", lambda route: route.abort())
        
        page = context.new_page()
        
        try:
            login(page)
            search_jobs(page)
            apply_filters(page)
            
            log("Starting application loop...")
            applied_count = 0
            
            # Use specific wait for job tuples to ensure filter reload is done
            try:
                page.wait_for_selector("div.srp-jobtuple-wrapper", timeout=10000)
            except:
                log("Job tuples not found immediately. Waiting a bit more...")
                random_delay(2, 4)
            
            # Loop through job cards
            # In Naukri search results, job cards are usually 'article.jobTuple' or 'div.srp-jobtuple-wrapper'
            
            job_cards = page.locator("div.srp-jobtuple-wrapper")
            count = job_cards.count()
            log(f"Found {count} jobs on first page.")
            
            for i in range(count):
                if applied_count >= target_count:
                    break
                    
                log(f"Processing job {i+1}...")
                card = job_cards.nth(i)
                
                title = "Unknown Title"
                company = "Unknown Company"
                # Extract title/company using evaluate for instant access (no waiting)
                try:
                    title_el = card.locator("a.title").first
                    company_el = card.locator("a.comp-name, a.subTitle, .companyinfo, .company-name").first
                    title = title_el.evaluate("el => el.innerText", timeout=500)
                    company = company_el.evaluate("el => el.innerText", timeout=500)
                    if not company or company.strip() == "":
                        company = "Unknown Company"
                    log(f"Checking: {title} at {company}")
                except:
                    pass

                # Ideally we want "Apply" or similar; Naukri search results just click the title to open.
                # Let's extract the URL directly using JS evaluation (instant, no wait)
                link_el = card.locator("a.title").first
                
                try:
                    # Use evaluate to get href instantly without waiting for stability
                    job_href = link_el.evaluate("el => el.href", timeout=1000)
                except:
                    job_href = None
                
                if job_href:
                    if handle_apply(context, job_href):
                        applied_count += 1
                        try:
                            log_application("Naukri", company, title, job_href)
                        except Exception as e:
                            log(f"Failed to log application: {e}")
                else:
                    log("Could not find job URL. Skipping.")
                    
                random_delay(1, 2)
                
            log(f"Total Applied: {applied_count}")
            update_stats(applied_count)
            
        except Exception as e:
            log(f"Error in main run: {e}")
            page.screenshot(path=debug_artifact_path("main_error.png"))
            raise
        finally:
            browser.close()

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Naukri Job Application Bot")
    parser.add_argument(
        "--target",
        type=int,
        default=TARGET_APPLY_COUNT,
        help=f"Number of jobs to apply to (default: {TARGET_APPLY_COUNT})"
    )
    parser.add_argument(
        "--job-titles",
        type=str,
        default=None,
        help="Comma-separated job titles to search for (e.g., 'Data Scientist,ML Engineer')"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode (no visible Chromium window). Recommended for scheduled/background runs."
    )
    
    args = parser.parse_args()
    
    # Parse job titles if provided
    keywords = None
    if args.job_titles:
        keywords = [title.strip() for title in args.job_titles.split(',') if title.strip()]
    
    run(target_count=args.target, keywords=keywords, headless=args.headless)
