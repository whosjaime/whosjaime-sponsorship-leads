from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from brand_enrichment import BrandEnricher
from discord_notifier import DiscordNotifier
from outreach_contact_policy import is_qualified_outreach_contact
from researched_sponsor_source import ResearchedSponsorSource
from run_sponsor_scan import _enrich_lead, _is_recent_sponsorship, _is_target_lead
from sponsor_config import load_sponsor_config
from sponsor_dedupe import normalize_text
from sponsor_queue import is_duplicate, load_duplicate_keys
from tiktok_sponsor_scanner import TikTokSponsorScanner

TARGET = 5
MAX_FOLLOWERS = 100_000
DISCORD_SENT_PATH = Path("data/tiktok_discord_sent_keys.json")


def _load_discord_sent() -> set[str]:
    try:
        raw = json.loads(DISCORD_SENT_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return set()
    return {normalize_text(str(value)) for value in raw if str(value).strip()} if isinstance(raw, list) else set()


def _save_discord_sent(values: set[str]) -> None:
    DISCORD_SENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DISCORD_SENT_PATH.write_text(json.dumps(sorted(values), indent=2) + "\n", encoding="utf-8")


def _identity(lead) -> str:
    return normalize_text(lead.brand_key or lead.brand_domain or lead.brand_name)


def _username(lead) -> str:
    value = (lead.creator_url or "").strip()
    match = re.search(r"tiktok\.com/@([^/?#]+)", value, re.I)
    if match:
        return match.group(1)
    return (lead.creator_channel_id or "").strip("@ ")


def _eligible(lead, scanner, duplicate_keys, discord_sent, config, enricher):
    platform = normalize_text(lead.source_platform)
    if "tiktok" not in platform:
        return None
    identity = _identity(lead)
    if not identity or identity in discord_sent:
        return None
    if is_duplicate(lead, duplicate_keys):
        return None
    if not _is_recent_sponsorship(lead, min(config.max_sponsor_age_days, 60)):
        return None

    followers = int(getattr(lead, "creator_subscribers", 0) or 0)
    username = _username(lead)
    if followers <= 0 and username:
        followers = scanner._profile_followers(username)
        lead.creator_subscribers = followers
    if followers <= 0 or followers > MAX_FOLLOWERS:
        return None

    try:
        lead = _enrich_lead(lead, enricher)
    except Exception as exc:
        print(f"SKIP enrichment failed: {lead.brand_name}: {exc}")
        return None
    if not _is_target_lead(lead):
        return None
    if not is_qualified_outreach_contact(lead):
        return None
    if lead.lead_score < config.min_lead_score:
        return None
    return lead


def run() -> None:
    config = load_sponsor_config(require_monday=False)
    discord = DiscordNotifier(config.discord_webhook_url)
    if not discord.webhook_url:
        raise RuntimeError("DISCORD_WEBHOOK_URL is required")

    scanner = TikTokSponsorScanner(config.search_language, config.search_region)
    enricher = BrandEnricher()
    duplicate_keys = load_duplicate_keys()
    discord_sent = _load_discord_sent()

    raw = []
    try:
        raw.extend(ResearchedSponsorSource().load())
    except Exception as exc:
        print(f"WARNING researched TikTok inventory unavailable: {exc}")

    # Add fresh creator-side TikTok sponsor posts so we are not limited to old stored inventory.
    try:
        fresh_posts = scanner.discover(lookback_days=45, max_posts=140)
        raw.extend(scanner.to_lead(post) for post in fresh_posts)
    except Exception as exc:
        print(f"WARNING live TikTok discovery failed: {exc}")

    eligible = []
    seen = set()
    for lead in raw:
        identity = _identity(lead)
        if not identity or identity in seen:
            continue
        qualified = _eligible(lead, scanner, duplicate_keys, discord_sent, config, enricher)
        if qualified is None:
            continue
        seen.add(identity)
        eligible.append(qualified)

    # Smallest verified creator audiences first; newest sponsorship breaks ties.
    eligible.sort(key=lambda lead: (int(lead.creator_subscribers or 10**12), -(date.fromisoformat(lead.sponsored_date[:10]).toordinal())))

    sent = 0
    for lead in eligible:
        if sent >= TARGET:
            break
        discord.send_new_lead(lead)
        discord_sent.add(_identity(lead))
        _save_discord_sent(discord_sent)
        sent += 1
        print(f"DISCORD_TIKTOK_SENT {sent}/{TARGET}: {lead.brand_name} / @{_username(lead)} / {lead.creator_subscribers:,} followers")

    print(f"TIKTOK_DISCORD_COMPLETE: {sent}/{TARGET} sent; hard cap {MAX_FOLLOWERS:,} followers.")
    if sent < TARGET:
        raise RuntimeError(f"Only {sent} eligible TikTok leads found at <= {MAX_FOLLOWERS:,} followers")


if __name__ == "__main__":
    run()
