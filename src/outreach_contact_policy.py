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
    "paid media",
    "social media",
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
    "named public work email",
    "public work email",
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


def _role_linked_title(lead: SponsorLead) -> bool:
    title = normalize_text(lead.contact_title)
    return bool(title and any(term in title for term in OUTREACH_ROLE_TERMS))


def _verified_named_contact(lead: SponsorLead) -> bool:
    """Named people are valid even without a public email when role + source are verified."""
    name = (lead.contact_name or "").strip()
    source = (lead.contact_source_url or lead.contact_source or "").strip()
    return bool(name and source and _role_linked_title(lead))


def is_qualified_outreach_contact(lead: SponsorLead) -> bool:
    """Return True only for actionable sponsorship/partnership/brand outreach contacts.

    The research policy explicitly allows either a qualified email OR a verified named
    person whose current title/source ties them to sponsorship, creator, influencer,
    affiliate, partnerships, marketing, paid/social media, or business development.
    """
    email = normalize_text(lead.contact_email)

    # A verified named role-linked person is independently sufficient.
    if _verified_named_contact(lead):
        return True

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

    # A named person's email is acceptable when their title or the page it came from
    # clearly identifies sponsorship/creator/partnership responsibility.
    if _role_linked_title(lead):
        return True

    source = normalize_text(lead.contact_source_url or lead.contact_source)
    if source and any(term in source for term in DIRECT_SOURCE_TERMS):
        return True

    return False
