from __future__ import annotations

import os
from collections import Counter
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sponsor_dedupe import normalize_text
from sponsor_models import SponsorLead


DAILY_TARGET = int(os.getenv("SPONSOR_DAILY_TARGET", "24"))
PLATFORM_TARGETS = {
    "youtube": int(os.getenv("SPONSOR_YOUTUBE_DAILY_TARGET", "8")),
    "tiktok": int(os.getenv("SPONSOR_TIKTOK_DAILY_TARGET", "8")),
    "instagram": int(os.getenv("SPONSOR_INSTAGRAM_DAILY_TARGET", "8")),
}
# Delivery priority: TikTok first, Instagram second, YouTube only as fallback.
PLATFORM_ORDER = ("tiktok", "instagram", "youtube")
DAILY_TIMEZONE = os.getenv("SPONSOR_DAILY_TIMEZONE", "America/Toronto")


def current_delivery_date() -> date:
    """Return the sponsor delivery day in the configured business timezone."""
    try:
        timezone = ZoneInfo(DAILY_TIMEZONE)
    except Exception:
        timezone = ZoneInfo("America/Toronto")
    return datetime.now(timezone).date()


def platform_key(value: str) -> str:
    key = normalize_text(value)
    if "youtube" in key:
        return "youtube"
    if "tiktok" in key:
        return "tiktok"
    if "instagram" in key:
        return "instagram"
    return key or "other"


def delivery_history_key(lead: SponsorLead, delivered_on: date | None = None) -> str:
    day = delivered_on or current_delivery_date()
    platform = platform_key(lead.source_platform)
    brand = normalize_text(lead.brand_key or lead.brand_domain or lead.brand_name)
    return f"delivery-used:{day.isoformat()}:{platform}:{brand}"


def delivery_counts(sent_keys: set[str], delivered_on: date | None = None) -> Counter:
    day = (delivered_on or current_delivery_date()).isoformat()
    prefix = f"delivery-used:{day}:"
    counts: Counter = Counter()
    for raw in sent_keys:
        value = normalize_text(raw)
        if not value.startswith(prefix):
            continue
        rest = value[len(prefix):]
        platform = rest.split(":", 1)[0]
        counts[platform] += 1
    return counts


def total_delivered_today(sent_keys: set[str], delivered_on: date | None = None) -> int:
    return sum(delivery_counts(sent_keys, delivered_on).values())


def choose_next_platform(sent_keys: set[str], available: set[str]) -> str:
    """Fill TikTok first, Instagram second, and YouTube only when social inventory is unavailable."""
    counts = delivery_counts(sent_keys)

    for platform in PLATFORM_ORDER:
        if platform in available and counts.get(platform, 0) < PLATFORM_TARGETS.get(platform, 0):
            return platform

    for platform in PLATFORM_ORDER:
        if platform in available:
            return platform
    return next(iter(available), "")


def balance_platforms(leads: list[SponsorLead], limit: int = DAILY_TARGET) -> list[SponsorLead]:
    """Build a TikTok-first queue, then Instagram, then YouTube fallback."""
    by_platform: dict[str, list[SponsorLead]] = {platform: [] for platform in PLATFORM_ORDER}
    other: list[SponsorLead] = []
    seen: set[str] = set()

    for lead in leads:
        identity = normalize_text(lead.brand_key or lead.brand_domain or lead.brand_name)
        if not identity or identity in seen:
            continue
        seen.add(identity)
        platform = platform_key(lead.source_platform)
        if platform in by_platform:
            by_platform[platform].append(lead)
        else:
            other.append(lead)

    selected: list[SponsorLead] = []
    consumed: dict[str, int] = {platform: 0 for platform in PLATFORM_ORDER}

    for platform in PLATFORM_ORDER:
        target = PLATFORM_TARGETS.get(platform, 0)
        take = min(target, len(by_platform[platform]), max(0, limit - len(selected)))
        if take <= 0:
            continue
        selected.extend(by_platform[platform][:take])
        consumed[platform] = take
        if len(selected) >= limit:
            return selected[:limit]

    remaining: list[SponsorLead] = []
    for platform in PLATFORM_ORDER:
        remaining.extend(by_platform[platform][consumed[platform]:])
    remaining.extend(other)
    selected.extend(remaining[: max(0, limit - len(selected))])
    return selected[:limit]
