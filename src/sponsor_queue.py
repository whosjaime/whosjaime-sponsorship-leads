from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from outreach_contact_policy import is_qualified_outreach_contact
from sponsor_dedupe import lead_brand_keys, normalize_text, permanent_blocked_brand_keys
from sponsor_models import SponsorLead

QUEUE_PATH = Path("data/sponsor_queue.json")
SENT_KEYS_PATH = Path("data/sent_sponsor_keys.json")
MAX_QUEUE_SIZE = 24

# Diversity rules. Brand dedupe remains permanent; creator reuse is only temporary.
CREATOR_COOLDOWN_DAYS = 7
SOFTWARE_QUEUE_LIMIT = 4
TECH_FAMILY_QUEUE_LIMIT = 8
CODING_QUEUE_LIMIT = 2

TECH_FAMILY_CATEGORIES = {
    "software / saas",
    "cybersecurity / vpn",
    "consumer tech",
}

CODING_DEV_TERMS = {
    " coding ",
    " code ",
    " developer ",
    " developers ",
    " devtool ",
    " dev tool ",
    " programming ",
    " software engineer ",
    " github ",
    " api ",
    " llm ",
    " gpt ",
    " claude ",
    " cursor ",
    " ai automation ",
    " cloud spending ",
}


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


def _creator_identity(lead: SponsorLead) -> str:
    """Stable creator identity for queue diversity/cooldown, preferring YouTube channel ID."""
    raw = lead.creator_channel_id or lead.creator_url or lead.creator_name
    return normalize_text(raw)


def _creator_history_key(lead: SponsorLead, used_on: date | None = None) -> str:
    identity = _creator_identity(lead)
    if not identity:
        return ""
    day = used_on or date.today()
    return f"creator-used:{day.isoformat()}:{identity}"


def _parse_creator_history_key(value: str) -> tuple[date, str] | None:
    value = normalize_text(value)
    if not value.startswith("creator-used:"):
        return None
    parts = value.split(":", 2)
    if len(parts) != 3:
        return None
    try:
        used_on = date.fromisoformat(parts[1])
    except ValueError:
        return None
    identity = normalize_text(parts[2])
    return (used_on, identity) if identity else None


def recent_creator_identities(
    sent_keys: set[str],
    cooldown_days: int = CREATOR_COOLDOWN_DAYS,
    today: date | None = None,
) -> set[str]:
    reference = today or date.today()
    recent: set[str] = set()
    for key in sent_keys:
        parsed = _parse_creator_history_key(key)
        if parsed is None:
            continue
        used_on, identity = parsed
        age = (reference - used_on).days
        if 0 <= age < max(1, cooldown_days):
            recent.add(identity)
    return recent


def is_creator_on_cooldown(
    lead: SponsorLead,
    sent_keys: set[str],
    cooldown_days: int = CREATOR_COOLDOWN_DAYS,
    today: date | None = None,
) -> bool:
    identity = _creator_identity(lead)
    if not identity:
        return False
    return identity in recent_creator_identities(sent_keys, cooldown_days, today)


def mark_creator_used(lead: SponsorLead, sent_keys: set[str], used_on: date | None = None) -> None:
    key = _creator_history_key(lead, used_on)
    if key:
        sent_keys.add(key)


def _lead_text(lead: SponsorLead) -> str:
    return " ".join(
        [
            lead.brand_name or "",
            lead.brand_domain or "",
            lead.sponsor_category or "",
            lead.sponsor_subcategory or "",
            lead.creator_name or "",
            lead.video_title or "",
            lead.evidence or "",
        ]
    ).lower()


def _is_coding_or_dev_lead(lead: SponsorLead) -> bool:
    padded = f" {_lead_text(lead)} "
    return any(term in padded for term in CODING_DEV_TERMS)


def _queue_bucket(lead: SponsorLead) -> str:
    category = normalize_text(lead.sponsor_category)
    genre = normalize_text(lead.creator_genre)
    tags = {normalize_text(tag) for tag in (lead.creator_tags or [])}

    # Creator-side variety gets an intentional lane so reactions/streaming/vlogs are
    # not buried by high-scoring developer sponsors.
    if "streaming" in tags or "reactions" in tags or genre == "streaming":
        return "creator-variety"
    if "lifestyle" in tags or genre in {"lifestyle", "fashion", "family", "travel"}:
        return "lifestyle"

    if category == "gaming":
        return "gaming"
    if category == "food & beverage":
        return "food"
    if category == "beauty":
        return "beauty"
    if category == "music":
        return "music"
    if category in {"fashion", "health & wellness", "travel", "home", "entertainment"}:
        return "lifestyle"
    if category == "software / saas":
        return "software"
    if category in {"consumer tech", "cybersecurity / vpn"}:
        return "tech"
    return "other"


def diversify_queue(leads: list[SponsorLead], sent_keys: set[str] | None = None) -> list[SponsorLead]:
    """Apply contact quality, creator/category caps, then round-robin visible variety."""
    history = sent_keys if sent_keys is not None else load_sent_keys()
    recent_creators = recent_creator_identities(history)

    seen_brands: set[str] = set()
    seen_creators: set[str] = set()
    software_count = 0
    tech_family_count = 0
    coding_count = 0

    bucket_order = [
        "gaming",
        "food",
        "creator-variety",
        "lifestyle",
        "tech",
        "software",
        "beauty",
        "music",
        "other",
    ]
    buckets: dict[str, list[SponsorLead]] = {name: [] for name in bucket_order}

    for lead in leads:
        # Hard outreach policy: a public email is not enough. Only sponsor,
        # partnership, creator/influencer, brand, ambassador/affiliate, marketing,
        # business-development, or clearly role-linked named contacts may enter.
        if not is_qualified_outreach_contact(lead):
            continue

        brand_identity = (lead.brand_key or lead.brand_domain or lead.brand_name).strip().lower()
        if not brand_identity or brand_identity in seen_brands:
            continue

        creator_identity = _creator_identity(lead)
        if creator_identity and (creator_identity in seen_creators or creator_identity in recent_creators):
            continue

        category = normalize_text(lead.sponsor_category)
        is_software = category == "software / saas"
        is_tech_family = category in TECH_FAMILY_CATEGORIES
        is_coding = _is_coding_or_dev_lead(lead)

        if is_software and software_count >= SOFTWARE_QUEUE_LIMIT:
            continue
        if is_tech_family and tech_family_count >= TECH_FAMILY_QUEUE_LIMIT:
            continue
        if is_coding and coding_count >= CODING_QUEUE_LIMIT:
            continue

        seen_brands.add(brand_identity)
        if creator_identity:
            seen_creators.add(creator_identity)
        if is_software:
            software_count += 1
        if is_tech_family:
            tech_family_count += 1
        if is_coding:
            coding_count += 1

        bucket = _queue_bucket(lead)
        buckets.setdefault(bucket, []).append(lead)

    diversified: list[SponsorLead] = []
    while len(diversified) < MAX_QUEUE_SIZE and any(buckets.get(name) for name in bucket_order):
        for name in bucket_order:
            bucket = buckets.get(name) or []
            if not bucket:
                continue
            diversified.append(bucket.pop(0))
            if len(diversified) >= MAX_QUEUE_SIZE:
                break

    return diversified


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
    # Old queue files are policy-filtered at read time, so generic customer-service
    # contacts, repeated creators, and overrepresented categories cannot dispatch.
    return diversify_queue(leads, load_sent_keys())


def save_queue(leads: list[SponsorLead], path: Path = QUEUE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    diversified = diversify_queue(leads, load_sent_keys())
    payload = [lead.as_dict() for lead in diversified[:MAX_QUEUE_SIZE]]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_duplicate_keys(path: Path = SENT_KEYS_PATH) -> set[str]:
    """Authoritative duplicate keys: sent history plus the permanent GitHub blocklist."""
    return load_sent_keys(path) | permanent_blocked_brand_keys()


def save_sent_keys(keys: set[str], path: Path = SENT_KEYS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    # Keep brand/email/domain history forever, but prune old creator-use records after
    # 30 days because creator reuse is only a temporary diversity concern.
    cutoff = date.today() - timedelta(days=30)
    cleaned: set[str] = set()
    for key in keys:
        normalized = normalize_text(key)
        if not normalized:
            continue
        parsed = _parse_creator_history_key(normalized)
        if parsed is not None and parsed[0] < cutoff:
            continue
        cleaned.add(normalized)

    path.write_text(json.dumps(sorted(cleaned), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def is_duplicate(lead: SponsorLead, duplicate_keys: set[str]) -> bool:
    return bool(lead_brand_keys(lead) & duplicate_keys)


def is_already_sent(lead: SponsorLead, sent_keys: set[str]) -> bool:
    return bool(lead_brand_keys(lead) & sent_keys)


def mark_sent(lead: SponsorLead, sent_keys: set[str]) -> None:
    sent_keys.update(lead_brand_keys(lead))


def merge_unique(existing: list[SponsorLead], incoming: list[SponsorLead]) -> list[SponsorLead]:
    return diversify_queue([*existing, *incoming], load_sent_keys())[:MAX_QUEUE_SIZE]
