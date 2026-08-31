from __future__ import annotations

import re
from datetime import date, datetime, timezone

from brand_enrichment import BrandEnricher
from sponsor_dedupe import normalize_domain
from sponsor_models import SponsorLead


TARGET_SPONSOR_CATEGORIES = {
    "Gaming",
    "Consumer Tech",
    "Physical Consumer Tech",
    "Food & Beverage",
    "Food/Drink",
    "Fashion",
    "Home",
    "Home & Garden",
    "Health & Wellness",
    "Wellness",
    "Travel",
    "Pet",
    "Pets",
    "Fragrance",
    "Beauty",
    "Music",
    "Entertainment",
    "Lifestyle",
    "Sports",
    "Fitness",
}

DIGITAL_TECH_CATEGORIES = {
    "Software / SaaS",
    "Cybersecurity / VPN",
    "AI Software",
    "Developer Tools",
    "Web Hosting",
    "Cloud Software",
}

EXCLUDED_SPONSOR_KEYWORDS = {
    " vpn ",
    "saas",
    "software platform",
    "developer tool",
    "coding tool",
    "code assistant",
    "web hosting",
    "cloud platform",
    "password manager",
    "cybersecurity",
    "browser extension",
    "productivity app",
    "festival",
    "music festival",
}

PHYSICAL_TECH_KEYWORDS = {
    "headphone", "headset", "earbud", "speaker", "microphone", "camera",
    "keyboard", "mouse", "monitor", "display", "projector", "router", "charger",
    "power station", "power bank", "battery", "smartwatch", "watch", "wearable",
    "phone", "tablet", "laptop", "computer", "pc", "console", "controller",
    "drone", "printer", "vacuum", "robot", "appliance", "hardware", "device",
    "lighting", "light", "tripod", "gimbal", "dock", "hub", "ssd", "storage",
}

TARGET_BRAND_KEYWORDS = {
    "gaming", "game", "stream", "food", "snack", "drink", "beverage", "coffee",
    "hydration", "supplement", "wellness", "fitness", "apparel", "clothing",
    "fashion", "shoe", "footwear", "home", "furniture", "mattress", "sleep",
    "cookware", "kitchen", "travel", "hotel", "resort", "luggage", "pet", "dog",
    "cat", "fragrance", "perfume", "cologne", "beauty", "skincare", "makeup",
    "music", "instrument", "guitar", "audio", "sports", "outdoor",
}


SPONSOR_DISCLOSURE_RE = re.compile(
    r"(?:sponsored by|sponsor(?:ed)? by|thanks? to .{0,40}?for sponsoring|paid partnership with|"
    r"in partnership with|partnered with|presented by|brought to you by|#ad\b|#sponsored\b|"
    r"#paidpartnership\b|#paid_partnership\b)",
    re.I,
)


def _sponsorship_age_days(lead: SponsorLead) -> int | None:
    raw = str(getattr(lead, "sponsored_date", "") or "").strip()[:10]
    if not raw:
        return None
    try:
        return (date.today() - date.fromisoformat(raw)).days
    except ValueError:
        return None


def _is_recent_sponsorship(lead: SponsorLead, max_age_days: int) -> bool:
    age = _sponsorship_age_days(lead)
    return age is not None and 0 <= age <= max_age_days


def _score_lead(lead: SponsorLead) -> int:
    score = 0
    evidence = str(getattr(lead, "evidence", "") or "")
    signals = [str(signal) for signal in (getattr(lead, "signals", []) or [])]
    combined = " ".join([evidence, *signals])
    if SPONSOR_DISCLOSURE_RE.search(combined):
        score += 35
    if bool(getattr(lead, "paid_product_placement", False)):
        score += 20
    if getattr(lead, "brand_domain", ""):
        score += 10
    if getattr(lead, "contact_email", "") or getattr(lead, "contact_name", ""):
        score += 20
    if getattr(lead, "creator_name", ""):
        score += 5

    age_days = _sponsorship_age_days(lead)
    if age_days is not None:
        if 0 <= age_days <= 7:
            score += 15
        elif age_days <= 30:
            score += 8

    return min(100, score)


def _target_text(lead: SponsorLead) -> str:
    """Build classification text safely for both full SponsorLead and test/partial objects."""
    return " ".join(
        [
            str(getattr(lead, "brand_name", "") or ""),
            str(getattr(lead, "brand_domain", "") or ""),
            str(getattr(lead, "sponsor_category", "") or ""),
            str(getattr(lead, "sponsor_subcategory", "") or ""),
            str(getattr(lead, "evidence", "") or ""),
        ]
    ).lower()


def _is_physical_tech_product(lead: SponsorLead) -> bool:
    text = _target_text(lead)
    return any(keyword in text for keyword in PHYSICAL_TECH_KEYWORDS)


def _is_target_lead(lead: SponsorLead) -> bool:
    """Allow approved consumer niches while hard-rejecting digital tech/services."""
    text = _target_text(lead)
    if any(keyword in text for keyword in EXCLUDED_SPONSOR_KEYWORDS):
        return False
    category = str(getattr(lead, "sponsor_category", "") or "")
    if category in DIGITAL_TECH_CATEGORIES:
        return False
    if category in TARGET_SPONSOR_CATEGORIES:
        return True
    if _is_physical_tech_product(lead):
        return True
    return any(keyword in text for keyword in TARGET_BRAND_KEYWORDS)


def _priority_score(lead: SponsorLead) -> int:
    score = 0
    category = str(getattr(lead, "sponsor_category", "") or "")
    if category in TARGET_SPONSOR_CATEGORIES or _is_physical_tech_product(lead):
        score += 100
    text = _target_text(lead)
    if any(keyword in text for keyword in TARGET_BRAND_KEYWORDS):
        score += 50
    if getattr(lead, "contact_email", "") and getattr(lead, "contact_name", ""):
        score += 25
    elif getattr(lead, "contact_email", "") or getattr(lead, "contact_name", ""):
        score += 5
    age_days = _sponsorship_age_days(lead)
    if age_days is not None:
        if 0 <= age_days <= 7:
            score += 30
        elif age_days <= 30:
            score += 15
    return score


def _temperature(score: int) -> str:
    if score >= 90:
        return "Very Hot"
    if score >= 80:
        return "Hot"
    if score >= 70:
        return "Warm"
    return "Needs Review"


def _enrich_lead(lead: SponsorLead, enricher: BrandEnricher) -> SponsorLead:
    enrichment = enricher.enrich(lead.brand_domain)
    if enrichment.company_name and not lead.brand_name:
        lead.brand_name = enrichment.company_name
    if enrichment.domain:
        lead.brand_domain = normalize_domain(enrichment.domain)
    if enrichment.sponsor_category:
        lead.sponsor_category = enrichment.sponsor_category
    if enrichment.sponsor_subcategory:
        lead.sponsor_subcategory = enrichment.sponsor_subcategory

    # Never downgrade a verified research contact with generic website enrichment.
    if not lead.contact_email and enrichment.contact_email:
        lead.contact_email = enrichment.contact_email
        lead.email_type = enrichment.email_type
        lead.contact_source = enrichment.contact_source
        lead.contact_source_url = enrichment.contact_source_url
    if not lead.contact_name and enrichment.contact_name:
        lead.contact_name = enrichment.contact_name
    if not lead.contact_title and enrichment.contact_title:
        lead.contact_title = enrichment.contact_title

    lead.lead_score = _score_lead(lead)
    lead.lead_temperature = _temperature(lead.lead_score)
    return lead
