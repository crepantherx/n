#!/usr/bin/env python3
"""
UK Licensed Sponsor List — Cache and Lookup

Downloads the UK Government register of licensed sponsors (Skilled Worker route)
and provides fast company-name lookup to boost visa-sponsorship confidence.

Source: https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers
"""

import csv
import io
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Set

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

SCRIPT_DIR = Path(__file__).parent
CACHE_DIR = SCRIPT_DIR / "files"
CACHE_FILE = CACHE_DIR / "uk_sponsors.csv"
CACHE_MAX_AGE_DAYS = 7

# GOV.UK publishes the register as a CSV download. The URL occasionally changes
# when they update the page. We try the most recent known URL first, then fall
# back to the landing page to find the download link.
SPONSOR_CSV_URL = (
    "https://assets.publishing.service.gov.uk/media/"
    "67a30d9de2b2c64b252a3b44/2025-02-04_-_Worker_and_Temporary_Worker.csv"
)
SPONSOR_LANDING_URL = (
    "https://www.gov.uk/government/publications/"
    "register-of-licensed-sponsors-workers"
)


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [uk-sponsors] {message}")


def _normalise(name: str) -> str:
    """
    Normalise a company name for fuzzy matching.
    - lowercase
    - strip common suffixes (Ltd, Limited, PLC, Inc, etc.)
    - collapse whitespace
    """
    s = name.lower().strip()
    # Remove common legal suffixes
    s = re.sub(
        r"\b(ltd|limited|plc|llp|inc|incorporated|corp|corporation|"
        r"group|holdings|uk|international)\b",
        "",
        s,
    )
    # Remove punctuation
    s = re.sub(r"[^\w\s]", "", s)
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _cache_is_fresh() -> bool:
    """Check if the cached sponsor list is recent enough."""
    if not CACHE_FILE.exists():
        return False
    try:
        age_seconds = time.time() - CACHE_FILE.stat().st_mtime
        return age_seconds < CACHE_MAX_AGE_DAYS * 86400
    except Exception:
        return False


def download_sponsor_list(force: bool = False) -> Optional[Path]:
    """
    Download the UK licensed sponsor CSV and cache it locally.
    Returns the path to the cached file, or None on failure.
    """
    if not force and _cache_is_fresh():
        log(f"Sponsor list cache is fresh ({CACHE_FILE})")
        return CACHE_FILE

    if requests is None:
        log("Warning: 'requests' library not installed. Cannot download sponsor list.")
        log("Install with: pip install requests")
        # Still return cache if it exists (even if stale)
        return CACHE_FILE if CACHE_FILE.exists() else None

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Try direct CSV URL first
    log("Downloading UK licensed sponsor list from GOV.UK...")
    try:
        resp = requests.get(SPONSOR_CSV_URL, timeout=30)
        if resp.status_code == 200 and len(resp.content) > 1000:
            CACHE_FILE.write_bytes(resp.content)
            log(f"Sponsor list cached: {CACHE_FILE} ({len(resp.content)} bytes)")
            return CACHE_FILE
        else:
            log(f"Direct CSV download returned status {resp.status_code}, trying landing page...")
    except Exception as e:
        log(f"Direct CSV download failed: {e}, trying landing page...")

    # Fallback: scrape the landing page for the CSV link
    try:
        resp = requests.get(SPONSOR_LANDING_URL, timeout=30)
        if resp.status_code == 200:
            # Look for CSV download link in the page
            csv_links = re.findall(
                r'href="(https://assets\.publishing\.service\.gov\.uk/[^"]+\.csv)"',
                resp.text,
            )
            if csv_links:
                csv_url = csv_links[0]
                log(f"Found CSV link: {csv_url}")
                csv_resp = requests.get(csv_url, timeout=30)
                if csv_resp.status_code == 200 and len(csv_resp.content) > 1000:
                    CACHE_FILE.write_bytes(csv_resp.content)
                    log(f"Sponsor list cached: {CACHE_FILE} ({len(csv_resp.content)} bytes)")
                    return CACHE_FILE
    except Exception as e:
        log(f"Landing page fallback failed: {e}")

    log("Could not download sponsor list. Using cached version if available.")
    return CACHE_FILE if CACHE_FILE.exists() else None


def load_sponsors(cache_path: Optional[Path] = None) -> Set[str]:
    """
    Load normalised company names from the sponsor CSV into a set for O(1) lookup.
    """
    path = cache_path or CACHE_FILE
    if not path or not path.exists():
        log("No sponsor list available.")
        return set()

    sponsors: Set[str] = set()
    try:
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(raw))

        # Skip header row
        header = next(reader, None)
        if header is None:
            return set()

        # The CSV typically has: Organisation Name, Town/City, County, Type & Rating, Route
        # We want column 0 (Organisation Name)
        name_col = 0
        for row in reader:
            if len(row) > name_col and row[name_col].strip():
                normalised = _normalise(row[name_col])
                if normalised:
                    sponsors.add(normalised)

        log(f"Loaded {len(sponsors)} licensed sponsors from cache.")
    except Exception as e:
        log(f"Error reading sponsor list: {e}")

    return sponsors


# Module-level cached set (lazy-loaded)
_sponsors_cache: Optional[Set[str]] = None
_sponsors_loaded_at: float = 0


def is_licensed_sponsor(company_name: str) -> bool:
    """
    Check if a company name matches the UK licensed sponsors register.
    Uses normalised fuzzy matching to handle name variations.
    """
    global _sponsors_cache, _sponsors_loaded_at

    # Lazy load / refresh
    if _sponsors_cache is None or (time.time() - _sponsors_loaded_at > 3600):
        path = download_sponsor_list()
        _sponsors_cache = load_sponsors(path)
        _sponsors_loaded_at = time.time()

    if not _sponsors_cache:
        return False

    normalised = _normalise(company_name)
    if not normalised:
        return False

    # Exact normalised match
    if normalised in _sponsors_cache:
        return True

    # Partial match: if the normalised company name is a substring of any sponsor
    # (or vice versa), consider it a match. This handles cases like
    # "Google" matching "Google UK" or "Deloitte LLP" matching "Deloitte".
    for sponsor in _sponsors_cache:
        if len(normalised) >= 4 and len(sponsor) >= 4:
            if normalised in sponsor or sponsor in normalised:
                return True

    return False


if __name__ == "__main__":
    # Quick test
    path = download_sponsor_list(force=True)
    if path:
        sponsors = load_sponsors(path)
        print(f"\nLoaded {len(sponsors)} sponsors.")

        # Test a few well-known sponsors
        test_companies = [
            "Google",
            "Amazon",
            "Microsoft",
            "Deloitte",
            "KPMG",
            "Tata Consultancy Services",
            "Infosys",
            "Some Random Company That Doesn't Exist XYZ",
        ]
        for company in test_companies:
            result = is_licensed_sponsor(company)
            print(f"  {company}: {'✓ Licensed Sponsor' if result else '✗ Not found'}")
