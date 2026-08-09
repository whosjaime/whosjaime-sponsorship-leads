from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from sponsor_models import SponsorLead


CORPORATE_SUFFIXES = {
    "inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation",
    "company", "co", "plc", "gmbh", "group", "holdings",
}

MARKETING_SUBDOMAIN_PREFIXES = {
    "www", "go", "try", "get", "shop", "link", "links", "partner", "partners",
    "affiliate", "affiliates", "promo", "offer", "offers", "creator", "creators",
}


def normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def normalize_brand_name(value: str) -> str:
    text = normalize_text(value)
    text = text.replace("&", " and ")
    words = re.findall(r"[a-z0-9]+", text)
    words = [word for word in words if word not in CORPORATE_SUFFIXES]
    return "".join(words)


def normalize_domain(value: str) -> str:
    raw = normalize_text(value)
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = parsed.netloc.lower().split(":")[0].strip(".")
    parts = host.split(".")
    while len(parts) >= 3 and parts[0] in MARKETING_SUBDOMAIN_PREFIXES:
        parts.pop(0)
    return ".".join(parts)


def normalize_email(value: str) -> str:
    return normalize_text(value)


def email_domain(value: str) -> str:
    email = normalize_email(value)
    if "@" not in email:
        return ""
    return normalize_domain(email.rsplit("@", 1)[-1])


def make_brand_key(brand_name: str, brand_domain: str = "") -> str:
    domain = normalize_domain(brand_domain)
    if domain:
        return f"domain:{domain}"
    name = normalize_brand_name(brand_name)
    return f"brand:{name}" if name else ""


def make_sponsorship_key(platform: str, video_id: str, brand_name: str, brand_domain: str = "") -> str:
    identity = normalize_domain(brand_domain) or normalize_brand_name(brand_name)
    return f"{normalize_text(platform)}:{normalize_text(video_id)}:{identity}"


def lead_brand_keys(lead: SponsorLead) -> set[str]:
    keys = set()
    name = normalize_brand_name(lead.brand_name)
    domain = normalize_domain(lead.brand_domain)
    email = normalize_email(lead.contact_email)
    e_domain = email_domain(email)

    if name:
        keys.add(f"brand:{name}")
    if domain:
        keys.add(f"domain:{domain}")
    if email:
        keys.add(f"email:{email}")
    if e_domain:
        keys.add(f"domain:{e_domain}")
    if lead.brand_key:
        keys.add(normalize_text(lead.brand_key))
    return keys


@dataclass
class ExistingSponsorIndex:
    brand_keys: set[str] = field(default_factory=set)
    event_keys: set[str] = field(default_factory=set)
    protected_brand_keys: set[str] = field(default_factory=set)

    def is_duplicate_brand(self, lead: SponsorLead) -> bool:
        return bool(lead_brand_keys(lead) & self.brand_keys)

    def is_duplicate_event(self, lead: SponsorLead) -> bool:
        key = normalize_text(lead.sponsorship_key)
        return bool(key and key in self.event_keys)

    def is_protected(self, lead: SponsorLead) -> bool:
        return bool(lead_brand_keys(lead) & self.protected_brand_keys)

    def add(self, lead: SponsorLead, protected: bool = False) -> None:
        keys = lead_brand_keys(lead)
        self.brand_keys.update(keys)
        if protected:
            self.protected_brand_keys.update(keys)
        if lead.sponsorship_key:
            self.event_keys.add(normalize_text(lead.sponsorship_key))
