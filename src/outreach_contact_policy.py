from __future__ import annotations

from sponsor_dedupe import normalize_text
from sponsor_models import SponsorLead


# These are the functions we actually want to contact for creator sponsorship outreach.
OUTREACH_ROLE_TERMS = {
    "sponsor",
    "sponsorship",
    "partnership",
    "partner",
    "creator",
    "influencer",
    "collab",
    "ambassador",
    "affiliate",
    "brand",
    "marketing",
    "bizdev",
    "businessdevelopment",
    "business-development",
    "business development",
    "athlete",
    "athletes",
}

OUTREACH_EMAIL_TYPES = {
    "sponsorships",
    "partnerships",
    "creator partnerships",
    "creator marketing",
    "influencer marketing",
    "affiliate partnerships",
    "brand partnerships",
    "marketing",
    "business development",
    "partnership page contact",
}

# Generic service / PR inboxes are not useful sponsorship outreach contacts.
BLOCKED_GENERIC_LOCALPARTS = {
    "support",
    "customersupport",
    "customer-support",
    "customer.service",
    "customerservice",
    "customer-service",
    "service",
    "help",
    "helpdesk",
    "hello",
    "info",
    "contact",
    "care",
    "customercare",
    "customer-care",
    "press",
    "media",
    "pr",
    "newsroom",
    "sales",
}

DIRECT_SOURCE_TERMS = {
    "sponsor",
    "partnership",
    "partner",
    "creator",
    "influencer",
    "collab",
    "ambassador",
    "affiliate",
    "brand-partnership",
    "brand_partnership",
    "marketing",
}


def _localpart(email: str) -> str:
    normalized = normalize_text(email)
    if "@" not in normalized:
        return ""
    return normalized.split("@", 1)[0]


def _normalized_compact(value: str) -> str:
    return normalize_text(value).replace("_", "").replace(".", "").replace("-", "").replace(" ", "")


def is_qualified_outreach_contact(lead: SponsorLead) -> bool:
    """Return True only for actionable sponsorship/partnership/brand outreach contacts."""
    email = normalize_text(lead.contact_email)
    if "@" not in email:
        return False

    local = _localpart(email)
    compact_local = _normalized_compact(local)
    blocked_compact = {_normalized_compact(value) for value in BLOCKED_GENERIC_LOCALPARTS}
    if compact_local in blocked_compact:
        return False

    email_type = normalize_text(lead.email_type)
    if email_type in OUTREACH_EMAIL_TYPES:
        return True

    # Role-based inboxes are acceptable even if enrichment did not label the type.
    padded_local = f" {local.replace('.', ' ').replace('_', ' ').replace('-', ' ')} "
    if any(term in padded_local or _normalized_compact(term) in compact_local for term in OUTREACH_ROLE_TERMS):
        return True

    # Common shorthand business/marketing inboxes.
    if compact_local in {"bd", "bizdev", "mktg", "business", "brand", "brands"}:
        return True

    # A named person's email is acceptable only when their title or the page it came
    # from clearly identifies sponsorship/creator/partnership responsibility.
    title = normalize_text(lead.contact_title)
    if title and any(term in title for term in OUTREACH_ROLE_TERMS):
        return True

    source = normalize_text(lead.contact_source)
    if source and any(term in source for term in DIRECT_SOURCE_TERMS):
        return True

    return False
