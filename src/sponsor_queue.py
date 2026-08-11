from __future__ import annotations

import json
from pathlib import Path

from sponsor_dedupe import lead_brand_keys, normalize_text, permanent_blocked_brand_keys
from sponsor_models import SponsorLead

QUEUE_PATH = Path("data/sponsor_queue.json")
SENT_KEYS_PATH = Path("data/sent_sponsor_keys.json")
MAX_QUEUE_SIZE = 24


def load_queue(path: Path = QUEUE_PATH) -> list[SponsorLead]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, list):
        return []

    leads: list[SponsorLead] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            leads.append(SponsorLead(**item))
        except TypeError:
            continue
    return leads


def save_queue(leads: list[SponsorLead], path: Path = QUEUE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [lead.as_dict() for lead in leads[:MAX_QUEUE_SIZE]]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_sent_keys(path: Path = SENT_KEYS_PATH) -> set[str]:
    """Load the GitHub source-of-truth record of sponsor identities already delivered."""
    if not path.exists():
        return set()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    if not isinstance(raw, list):
        return set()
    return {
        normalized
        for value in raw
        if (normalized := normalize_text(value))
    }


def load_duplicate_keys(path: Path = SENT_KEYS_PATH) -> set[str]:
    """Authoritative duplicate keys: sent history plus the permanent GitHub blocklist."""
    return load_sent_keys(path) | permanent_blocked_brand_keys()


def save_sent_keys(keys: set[str], path: Path = SENT_KEYS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = sorted({normalize_text(key) for key in keys if normalize_text(key)})
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def is_duplicate(lead: SponsorLead, duplicate_keys: set[str]) -> bool:
    return bool(lead_brand_keys(lead) & duplicate_keys)


def is_already_sent(lead: SponsorLead, sent_keys: set[str]) -> bool:
    return bool(lead_brand_keys(lead) & sent_keys)


def mark_sent(lead: SponsorLead, sent_keys: set[str]) -> None:
    sent_keys.update(lead_brand_keys(lead))


def merge_unique(existing: list[SponsorLead], incoming: list[SponsorLead]) -> list[SponsorLead]:
    merged: list[SponsorLead] = []
    seen: set[str] = set()
    for lead in [*existing, *incoming]:
        identity = (lead.brand_key or lead.brand_domain or lead.brand_name).strip().lower()
        if not identity or identity in seen:
            continue
        seen.add(identity)
        merged.append(lead)
        if len(merged) >= MAX_QUEUE_SIZE:
            break
    return merged
