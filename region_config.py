"""
Region Configuration — Centralised mapping from UI region labels to
site-specific location data for every agent.

Each job platform has its own notion of "location" (URL params, domains,
city names, geoIds, etc.).  This module maps the broad UI labels
("Indian", "European", …) to the concrete values each agent needs.

Usage:
    from region_config import get_region_config
    cfg = get_region_config("European")
    print(cfg["linkedin_location"])  # "United Kingdom"
"""

from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
#  Master mapping
# ---------------------------------------------------------------------------

REGION_MAP: Dict[str, Dict[str, Any]] = {
    # ----- Indian -----
    "Indian": {
        # Naukri.com — location parameter uses city/country names.
        # We leave it as None to show ALL India jobs (no location filter).
        # Users who want specific cities can set job-title + city combos.
        "naukri_location": None,
        "naukri_supported": True,

        # LinkedIn — search location
        "linkedin_location": "India",

        # Indeed — country-specific domain
        "indeed_domain": "www.indeed.co.in",
        "indeed_location": "",

        # Reed — UK-only portal
        "reed_supported": False,

        # Career Page Crawler — country search terms
        "crawler_countries": ["India", "Bengaluru", "Remote"],

        # Browser context hints
        "geolocation": {"latitude": 12.9716, "longitude": 77.5946},
        "locale": "en-IN",
    },

    "European": {
        "naukri_location": "United Kingdom (UK)",
        "naukri_supported": True,

        "linkedin_location": "United Kingdom",

        "indeed_domain": "uk.indeed.com",
        "indeed_location": "",

        "reed_supported": True,      # Reed is UK-focused
        "reed_location": "",         # empty = UK-wide

        "crawler_countries": ["United Kingdom", "Germany", "Netherlands",
                              "Ireland", "Europe", "Remote"],

        "geolocation": {"latitude": 51.5074, "longitude": -0.1278},
        "locale": "en-GB",
    },

    "North American": {
        "naukri_location": "United States (USA)",
        "naukri_supported": True,

        "linkedin_location": "United States",

        "indeed_domain": "www.indeed.com",
        "indeed_location": "Remote",

        "reed_supported": False,

        "crawler_countries": ["United States", "Canada", "US", "Remote"],

        "geolocation": {"latitude": 37.7749, "longitude": -122.4194},
        "locale": "en-US",
    },

    "Australian": {
        "naukri_location": "Australia",
        "naukri_supported": True,

        "linkedin_location": "Australia",

        "indeed_domain": "au.indeed.com",
        "indeed_location": "",

        "reed_supported": False,

        "crawler_countries": ["Australia", "Remote"],

        "geolocation": {"latitude": -33.8688, "longitude": 151.2093},
        "locale": "en-AU",
    },

    "Asian": {
        "naukri_location": "Singapore",
        "naukri_supported": True,

        "linkedin_location": "Singapore",

        "indeed_domain": "sg.indeed.com",
        "indeed_location": "",

        "reed_supported": False,

        "crawler_countries": ["Singapore", "Japan", "Hong Kong", "Remote"],

        "geolocation": {"latitude": 1.3521, "longitude": 103.8198},
        "locale": "en-SG",
    },

    "Middle East": {
        "naukri_location": "United Arab Emirates",
        "naukri_supported": True,

        "linkedin_location": "United Arab Emirates",

        "indeed_domain": "www.indeed.com",
        "indeed_location": "Dubai",

        "reed_supported": False,

        "crawler_countries": ["UAE", "Dubai", "Saudi Arabia",
                              "Middle East", "Remote"],

        "geolocation": {"latitude": 25.2048, "longitude": 55.2708},
        "locale": "en-AE",
    },
}


# ---------------------------------------------------------------------------
#  Helper functions
# ---------------------------------------------------------------------------

def get_region_config(region: str) -> Dict[str, Any]:
    """Return the mapping dict for *region*, falling back to Indian."""
    return REGION_MAP.get(region, REGION_MAP["Indian"])


def get_linkedin_location(region: str) -> str:
    """Return the LinkedIn location string for the given region."""
    return get_region_config(region).get("linkedin_location", "India")


def get_indeed_domain(region: str) -> str:
    """Return the Indeed domain for the given region."""
    return get_region_config(region).get("indeed_domain", "www.indeed.com")


def get_indeed_location(region: str) -> str:
    """Return the Indeed location query parameter for the given region."""
    return get_region_config(region).get("indeed_location", "")


def is_naukri_supported(region: str) -> bool:
    """Naukri.com is supported for all mapped regions."""
    return get_region_config(region).get("naukri_supported", True)


def is_reed_supported(region: str) -> bool:
    """Reed.co.uk is UK-only. Returns True only for European."""
    return get_region_config(region).get("reed_supported", False)


def get_crawler_countries(region: str) -> List[str]:
    """Country names used in Google dork queries."""
    return get_region_config(region).get("crawler_countries", ["Europe"])


def get_geolocation(region: str) -> Dict[str, float]:
    """Browser geolocation hint for the region."""
    return get_region_config(region).get(
        "geolocation", {"latitude": 12.9716, "longitude": 77.5946}
    )


def get_locale(region: str) -> str:
    """Browser locale hint for the region."""
    return get_region_config(region).get("locale", "en-IN")
