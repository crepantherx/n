# Naukri Automation Suite

A local web dashboard for managing Naukri profile updates, Naukri applications, LinkedIn Easy Apply, international LinkedIn/Indeed/Reed/career-page crawlers, lead scraping, schedules, logs, and resume/config storage.

## What changed in this repaired build

- Added signed session authentication and removed bundled default passwords from the distributable app.
- Moved settings, uploaded resumes, logs, stats, agent memory, and debug artifacts into portable per-user folders under `data/users/<email>/`.
- Fixed resume uploads so saved paths are relative to the user data folder and survive moving the project to another PC.
- Added a portable in-app scheduler that works on Windows, macOS, and Linux while the dashboard is running.
- Kept system cron sync as an optional Linux/macOS enhancement instead of a requirement.
- Added the missing International LinkedIn schedule/task wiring in both backend and UI.
- Split international schedules so LinkedIn, Indeed, Reed, and Career Crawler no longer overwrite each other.
- Hardened Google login token verification and Google Drive settings restore.
- Isolated AI-agent config and memory by logged-in user.
- Redirected logs/screenshots/page dumps out of the source tree and into runtime data folders.
- Improved first-run setup scripts for macOS/Linux and Windows.
- Added emergency Stop All controls plus `stop_all.sh` / `stop_all.bat` to kill dashboard/task processes, free port 8787, remove suite cron entries, and disable/clear saved schedules.
- Reduced login/dashboard polling and heavy blur effects to prevent the high-frequency stutter/refresh behavior.

## Requirements

- Python 3.10, 3.11, or 3.12.
- A modern browser.
- Internet access for Playwright browser installation and for the job sites themselves.
- Job-site credentials entered through the dashboard settings.

The app can run with Python 3.13 in many environments, but Playwright and some dependencies are usually most stable on Python 3.10 to 3.12.

## Quick start on macOS/Linux

```bash
cd /path/to/naukri-automation-suite
./install.sh
./start.sh
```

Then open the printed local URL, usually:

```text
http://127.0.0.1:8787
```

To stop the running dashboard/tasks and free port 8787:

```bash
./stop.sh
```

To panic-stop everything, including saved schedules and system cron entries:

```bash
./stop_all.sh
```

On macOS, you can also double-click `LaunchWebDashboard.command`.

## Quick start on Windows

Double-click:

```text
start.bat
```

Or run from Command Prompt/PowerShell inside the project folder:

```bat
install.bat
start.bat
```

The scripts create a local `.venv`, install Python requirements, install Playwright browsers when possible, start the dashboard, and open the local URL. Use `stop.bat` to stop the dashboard/tasks and free port 8787. Use `stop_all.bat` to also disable/clear saved schedules and clear suite cron/task launchers.

## First login

On a fresh install there are no bundled users. The first successful email/password login creates the local admin account. Use a real email-format username and a password of at least 8 characters. After that, only existing users can log in unless you delete `data/users.json` to reset local accounts.

For stronger production deployments, set a stable secret in `.env`:

```env
NAUKRI_SECRET_KEY=replace-with-a-long-random-string
```

## Runtime data and portability

All local runtime data is intentionally kept out of the source code:

```text
data/users/<your-email>/config.json
data/users/<your-email>/files/
data/users/<your-email>/logs/
data/users/<your-email>/debug/
data/users/<your-email>/agent_memory.db
```

To move the app to another PC, copy the whole project folder including `data/`. Resume paths saved through the dashboard are stored relative to the user folder, so they continue to work after moving the folder.

To create a clean copy without personal data, delete the contents of `data/` except `data/.gitkeep` and `data/README.md`.


## Stop All / panic stop

The dashboard now has a red **Stop All** control in the top bar. It stops all known running task processes for the logged-in user, stops the AI Agent, disables/clears saved schedules, and removes this app's system cron entries. The dashboard itself stays open so you can confirm the status. The **Quit** button next to it performs the same cleanup and then shuts down the dashboard server on the configured port.

For OS-level cleanup, use the scripts from the project folder:

```bash
./stop.sh        # stop dashboard/task processes and free port 8787
./stop_all.sh    # also clear app schedules and suite cron entries
```

```bat
stop.bat
stop_all.bat
```

`stop.sh --port=8787` can be used if you changed `NAUKRI_WEB_PORT`.

## Scheduling

There are two scheduling modes:

1. **Portable in-app scheduler**: works on all operating systems while the dashboard is running. This is enabled automatically by the server and reads the schedule settings from the dashboard.
2. **System cron sync**: optional on macOS/Linux machines that have `crontab`. The UI can install cron entries for more persistent scheduled runs. If cron is unavailable, the app still saves schedules and uses the in-app scheduler.

Each task now has its own independent schedule keys:

- Naukri Job Applier
- Naukri Profile Bot
- LinkedIn Easy Apply
- International LinkedIn
- International Indeed
- International Reed
- International Career Page Crawler
- Lead Scraper

## Playwright browser notes

The scripts use Playwright. The start scripts attempt to install Chromium, Firefox, and WebKit:

```bash
python -m playwright install chromium firefox webkit
```

Naukri may block headless Chromium with HTTP 403. For scheduled/headless Naukri runs, WebKit or Firefox is usually a better fallback. Some sites may still ask for captcha, OTP, or manual verification.

## Optional Google login / Google Drive sync

Create a `.env` file from `.env.example` and set:

```env
GOOGLE_CLIENT_ID=your-google-oauth-client-id
GOOGLE_CLIENT_SECRET=your-google-oauth-client-secret
```

Google login accepts only the same email as an existing local user, unless it is the first login on a fresh install.


## Vercel hosting and no-PC scheduled runs

This package now includes Vercel compatibility while preserving the existing macOS and Windows scheduling behavior. Vercel hosts the FastAPI dashboard through `api/index.py` and automatically disables desktop-only features in cloud mode, such as local subprocess launches, system cron edits, WebSockets, and server shutdown.

For real scheduled automation without keeping a local PC running, use the included GitHub Actions workflow at `.github/workflows/scheduled-run.yml`. See `README_VERCEL.md` for Vercel environment variables, cloud-mode limits, and GitHub Actions secrets.

## Docker

```bash
docker build -t naukri-automation-suite .
docker run --rm -p 8787:8787 -v "$PWD/data:/app/data" --env-file .env naukri-automation-suite
```

The Docker image uses the official Playwright Python base image. Mount `data/` as a volume if you want settings and logs to persist.

## Important operational notes

This project automates third-party websites. Those websites can change selectors, add verification, block automation, or change terms. Live application runs require your own credentials and may need manual intervention. Use the task logs in the dashboard to diagnose site-specific failures.
