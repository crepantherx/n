# Vercel + free cloud scheduling guide

This build keeps the original macOS/Windows desktop behavior intact and adds a Vercel-safe serverless mode.

## What runs on Vercel

Vercel can host the FastAPI dashboard through `api/index.py`. In Vercel mode the app automatically switches to safe serverless behavior:

- dashboard login, settings UI, task/schedule forms, runtime status, and static UI work;
- local process launch, WebSockets, system cron, and dashboard shutdown are disabled in the hosted UI;
- `/api/cloud/cron` is available for Vercel Cron health triggers;
- `/api/cloud/run` is off by default and can be enabled only with `NAUKRI_ENABLE_VERCEL_RUNS=1` plus `CRON_SECRET`.

Browser automation is long-running, stateful work. Vercel Functions are best for short HTTP requests, so the package also includes a GitHub Actions worker that can run scheduled jobs for free without keeping your PC on.

## Deploy the dashboard on Vercel

1. Push this project to a private GitHub repository.
2. Create a new Vercel project from that repository.
3. Add environment variables in Vercel Project Settings.
4. Deploy.

Required Vercel variables:

```env
NAUKRI_CLOUD_MODE=1
NAUKRI_ADMIN_EMAIL=you@example.com
NAUKRI_ADMIN_PASSWORD=use-a-long-password
NAUKRI_SECRET_KEY=use-a-long-random-secret
```

Optional Vercel variables:

```env
GOOGLE_CLIENT_ID=your-google-oauth-client-id
GOOGLE_CLIENT_SECRET=your-google-oauth-client-secret
GOOGLE_ALLOWED_EMAILS=you@example.com
NAUKRI_ENABLE_VERCEL_RUNS=0
# Required if NAUKRI_ENABLE_VERCEL_RUNS=1.
CRON_SECRET=use-a-random-cron-secret
NAUKRI_VERCEL_TASK=naukri
NAUKRI_VERCEL_TARGET=5
```

The included `vercel.json` routes every request to the FastAPI entrypoint and installs a daily cron trigger at `/api/cloud/cron`.

## Recommended free no-PC scheduler: GitHub Actions

Use `.github/workflows/scheduled-run.yml` for real scheduled automation runs without running the app locally.

Add these repository secrets in GitHub:

```env
NAUKRI_EMAIL=your-naukri-email
NAUKRI_PASSWORD=your-naukri-password
LINKEDIN_EMAIL=your-linkedin-email
LINKEDIN_PASSWORD=your-linkedin-password
LINKEDIN_PHONE=your-phone
REED_EMAIL=your-reed-email
REED_PASSWORD=your-reed-password
RESUME_BASE64=base64-of-your-resume-file
RESUME_FILENAME=resume.pdf
```

Optional workflow variables/secrets:

```env
RUN_TASKS=naukri
RUN_TARGET=30
CTC_INR=2500000
JOB_TITLES=ML Engineer, AI Engineer, Software Engineer
```

`RUN_TASKS` accepts a comma-separated list:

```text
naukri,bot,linkedin,intl_linkedin,intl_indeed,intl_reed,intl_crawler,lead_scraper
```

To create the resume secret locally:

macOS/Linux:

```bash
base64 -i resume.pdf | pbcopy
```

Windows PowerShell:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("resume.pdf")) | Set-Clipboard
```

The workflow is set to run daily and also supports manual runs from the GitHub Actions tab.

## Local behavior is unchanged

Without `NAUKRI_CLOUD_MODE=1` or Vercel's `VERCEL=1`, the original desktop behavior remains:

- in-app scheduler runs while the local dashboard is open;
- macOS/Linux cron sync remains available when `crontab` exists;
- Windows start/stop scripts remain available;
- task processes launch locally with Playwright;
- Stop All and Quit still clean up background services and port `8787`.

## Production notes

Use a private repository because automation credentials and resume secrets are sensitive. Keep Vercel and GitHub secrets encrypted in their project settings, not in source files.
