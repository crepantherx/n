import os
import sys
import time
import random
import json
from datetime import datetime
from playwright.sync_api import sync_playwright
from config_loader import load_config, get_data_dir
from playwright_helpers import launch_browser

# Load configuration from config.json or .env
config = load_config()
EMAIL = config["email"]
PASSWORD = config["password"]
RESUME_PATH = config["resume_path"]

DEBUG_DIR = get_data_dir() / "debug"

def debug_artifact_path(name: str) -> str:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    return str(DEBUG_DIR / name)

def log(message):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")

def random_delay(min_seconds=1, max_seconds=3):
    time.sleep(random.uniform(min_seconds, max_seconds))

def update_bot_stats(success: bool) -> None:
    stats_file = get_data_dir() / "naukri_bot_stats.json"
    stats = {"total_runs": 0, "success_count": 0, "failure_count": 0, "last_run": None, "last_status": None}
    if stats_file.exists():
        try:
            loaded = json.loads(stats_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                stats.update(loaded)
        except Exception:
            pass

    stats["total_runs"] = int(stats.get("total_runs", 0)) + 1
    if success:
        stats["success_count"] = int(stats.get("success_count", 0)) + 1
        stats["last_status"] = "success"
    else:
        stats["failure_count"] = int(stats.get("failure_count", 0)) + 1
        stats["last_status"] = "failure"
    stats["last_run"] = str(datetime.now())

    stats_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = stats_file.with_suffix(stats_file.suffix + ".tmp")
    tmp.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    tmp.replace(stats_file)


def run(headless: bool = False):
    if not EMAIL or not PASSWORD or not RESUME_PATH:
        log("Error: Missing configuration. Please set NAUKRI_EMAIL, NAUKRI_PASSWORD, and RESUME_PATH in settings.")
        sys.exit(1)

    if not os.path.exists(RESUME_PATH):
        log(f"Error: Resume file not found at {RESUME_PATH}")
        sys.exit(1)

    log("Starting Naukri profile update...")
    success = False

    with sync_playwright() as p:
        # Naukri blocks headless Chromium with HTTP 403 ("Access Denied") very often.
        # On macOS, headless WebKit/Firefox tend to work reliably, so we prefer those.
        preferred = ["webkit", "firefox", "chromium"] if headless else ["chromium", "webkit", "firefox"]
        engine, browser = launch_browser(p, headless=headless, preferred_engines=preferred, log=log)

        context_kwargs = {
            "viewport": {"width": 1280, "height": 720},
            "locale": "en-IN",
        }
        if engine == "chromium":
            context_kwargs["user_agent"] = (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )

        context = browser.new_context(**context_kwargs)
        page = context.new_page()

        try:
            # 1. Login
            log("Navigating to login page...")
            resp = page.goto("https://www.naukri.com/nlogin/login", timeout=60000)
            # If we ever fall back to Chromium headless, we want a clear error (not a selector timeout).
            if resp is not None and resp.status == 403:
                page.screenshot(path=debug_artifact_path("login_access_denied.png"))
                raise Exception(
                    "Naukri returned HTTP 403 (Access Denied). "
                    "This usually happens with headless Chromium. "
                    "Try installing WebKit/Firefox browsers (python3 -m playwright install webkit firefox) "
                    "or run without --headless."
                )
            random_delay()

            # Wait for login form - generic wait for input
            log("Waiting for username field...")
            try:
                # Try standard selector first
                page.wait_for_selector("#usernameField", state="visible", timeout=10000)
                page.fill("#usernameField", EMAIL)
                random_delay(0.5, 1.5)
                page.fill("#passwordField", PASSWORD)
                random_delay(0.5, 1.5)
                page.click("button[type='submit'], button.blue-btn")
            except Exception:
                log("Standard login form not found immediately. Checking for alternative or potential captcha...")
                # Sometimes it asks for OTP login or different UI. 
                # Taking a screenshot for debugging if this fails again.
                page.screenshot(path=debug_artifact_path("login_debug.png"))
                raise Exception(f"Could not find login fields. See {debug_artifact_path('login_debug.png')}")
            
            # Wait for login to complete
            log("Waiting for dashboard...")
            # successful login usually redirects to homepage or dashboard
            page.wait_for_url("**/mnjuser/homepage**", timeout=30000)
            log("Login successful.")
            random_delay()

            # 2. Go to Profile
            log("Navigating to profile...")
            page.goto("https://www.naukri.com/mnjuser/profile", timeout=60000)
            random_delay(2, 4)

            # 3. Upload Resume
            log(f"Uploading resume from {RESUME_PATH}...")
            # Provide a more robust wait for the file input
            # Naukri "Update resume" link usually triggers a hidden file input
            # We can force the file input to appear or just set it if it exists in DOM
            
            try:
                # Sometimes the input is directly available
                file_input = page.wait_for_selector("input[type='file']", state="attached", timeout=10000)
                file_input.set_input_files(RESUME_PATH)
                log("Resume file set.")
                
                # Wait for upload processing
                # There is usually a "Success" toast or text update
                # We'll wait a bit conservatively
                time.sleep(5)
                log("Waited for upload to complete.")
            except Exception as e:
                log(f"Resume upload failed: {e}")

            # 4. Update Profile Heading (Resume Headline)
            log("Updating Resume Headline...")
            try:
                # Locate the Resume Headline section "Edit" button
                edit_btn = page.locator("div.resume-headline-container span.edit, span:has-text('Resume Headline') + span.edit").first
                
                if edit_btn.is_visible():
                    edit_btn.click()
                    random_delay()
                    
                    # The text area for headline
                    textarea = page.locator("textarea#resumeHeadlineTxt")
                    if textarea.is_visible():
                        original_text = textarea.input_value()
                        log(f"Current headline: {original_text[:20]}...")
                        
                        # Dot toggle logic
                        if original_text.strip().endswith("."):
                            new_text = original_text.strip()[:-1]
                            log("Removing trailing dot.")
                        else:
                            new_text = original_text.strip() + "."
                            log("Adding trailing dot.")
                        
                        page.fill("textarea#resumeHeadlineTxt", new_text)
                        random_delay(0.5, 1)
                        
                        # Click Save - specific selector to avoid hidden buttons
                        # Filter for visible 'Save' buttons
                        save_btn = page.locator("button:has-text('Save')").locator("visible=true").first
                        if save_btn.is_visible():
                            save_btn.click()
                            log("Heading updated and saved.")
                            time.sleep(3)
                        else:
                             log("Could not find a visible Save button.")
                    else:
                        log("Headline text area not found.")
                else:
                    log("Resume Headline edit button not found. Skipping headline update.")
                    
            except Exception as e:
                log(f"Headline update failed: {e}")

            success = True

        except Exception as e:
            log(f"An error occurred: {str(e)}")
            page.screenshot(path=debug_artifact_path("error_screenshot_v2.png"))
            raise e
        finally:
            update_bot_stats(success)
            log("Closing browser...")
            browser.close()
            log("Finished.")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Naukri Profile Updater (Bot)")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode (no visible Chromium window). Recommended for scheduled/background runs."
    )
    args = parser.parse_args()

    run(headless=args.headless)
