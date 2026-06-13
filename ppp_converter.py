"""
Purchasing Power Parity (PPP) salary conversion utility.

Converts an annual CTC in INR to approximate equivalent salaries in
regional currencies, accounting for purchasing power differences.

These ratios are approximate PPP-based multipliers (not raw exchange rates)
so the resulting salary "feels" equivalent in the target market.
"""

# PPP conversion factors: 1 INR → regional currency
# These are PPP-adjusted, NOT market exchange rates.
# E.g. ₹25,00,000 INR ≈ £30,000 GBP (PPP-adjusted)
PPP_FACTORS = {
    "UK":        {"currency": "GBP", "symbol": "£",  "factor": 0.012},
    "Europe":    {"currency": "EUR", "symbol": "€",  "factor": 0.014},
    "US":        {"currency": "USD", "symbol": "$",  "factor": 0.018},
    "Canada":    {"currency": "CAD", "symbol": "C$", "factor": 0.020},
    "Australia": {"currency": "AUD", "symbol": "A$", "factor": 0.022},
    "Singapore": {"currency": "SGD", "symbol": "S$", "factor": 0.020},
    "India":     {"currency": "INR", "symbol": "₹",  "factor": 1.0},
    "UAE":       {"currency": "AED", "symbol": "AED", "factor": 0.060},
    "Japan":     {"currency": "JPY", "symbol": "¥",  "factor": 2.0},
}

# Region → list of target countries for salary conversion
REGION_COUNTRIES = {
    "European":    ["UK", "Europe"],
    "North American": ["US", "Canada"],
    "Australian":  ["Australia"],
    "Asian":       ["Singapore", "Japan", "India"],
    "Middle East": ["UAE"],
    "All":         list(PPP_FACTORS.keys()),
}


def convert_inr_to_region(ctc_inr: float, region: str = "European") -> dict:
    """Convert INR CTC to the primary currency for a given region.

    Returns dict with 'amount', 'currency', 'symbol', 'formatted'.
    """
    countries = REGION_COUNTRIES.get(region, REGION_COUNTRIES["European"])
    # Use the first country in the region as the primary
    country = countries[0]
    info = PPP_FACTORS.get(country, PPP_FACTORS["UK"])

    amount = round(ctc_inr * info["factor"])
    return {
        "amount": amount,
        "currency": info["currency"],
        "symbol": info["symbol"],
        "formatted": f"{info['symbol']}{amount:,}",
    }


def get_salary_for_form(ctc_inr: float, target_region: str = "European") -> str:
    """Return a plain salary string suitable for filling into ATS forms."""
    result = convert_inr_to_region(ctc_inr, target_region)
    return str(result["amount"])


def get_all_conversions(ctc_inr: float) -> dict:
    """Return salary conversions for all known regions."""
    conversions = {}
    for country, info in PPP_FACTORS.items():
        amount = round(ctc_inr * info["factor"])
        conversions[country] = {
            "amount": amount,
            "currency": info["currency"],
            "formatted": f"{info['symbol']}{amount:,}",
        }
    return conversions
