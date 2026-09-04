from __future__ import annotations

import re

from brand_enrichment import BrandEnricher
from discord_notifier import DiscordNotifier
from outreach_contact_policy import is_qualified_outreach_contact
from researched_sponsor_source import ResearchedSponsorSource
from run_sponsor_queue_dispatch import _is_dispatch_target_lead
from run_sponsor_scan import _enrich_lead, _is_recent_sponsorship
from sponsor_config import load_sponsor_config
from sponsor_monday_client import SponsorMondayClient
from sponsor_queue import (
    is_duplicate,
    load_duplicate_keys,
    load_sent_keys,
    mark_creator_used,
    mark_sent,
    save_sent_keys,
)
from tiktok_sponsor_scanner import TikTokSponsorScanner


TARGET_SENDS = 5
MAX_CREATOR_FOLLOWERS = 100_000
TIKTOK_USER_RE = re.compile(r"tiktok\.com/@([^/?#]+)", re.I)


def _username(lead) -> str:
    raw = (lead.creator_channel_id or "").strip().lstrip("@")
    if raw:
        return raw
    match = TIKTOK_USER_RE.search(lead.creator_url or "")
    return match.group(1) if match else ""


def _is_tiktok(lead) -> bool:
    platform = (lead.source_platform or "").strip().lower()
    return "tiktok" in platform or "tiktok.com/@" in (lead.creator_url or "").lower()


def _hydrate_followers(lead, scanner: TikTokSponsorScanner) -> int:
    followers = int(getattr(lead, "creator_subscribers", 0) or 0)
    if followers > 0:
        return followers
    username = _username(lead)
    if not username:
        return 0
    followers = scanner._profile_followers(username)
    lead.creator_subscribers = int(followers or 0)
    return lead.creator_subscribers


def run() -> None:
    config = load_sponsor_config()
    scanner = TikTokSponsorScanner(config.search_language, config.search_region)
    enricher = BrandEnricher()
    monday = SponsorMondayClient(config.monday_token, config.monday_board_id, config.monday_group_id)
    discord = DiscordNotifier(config.discord_webhook_url)

    sent_keys = load_sent_keys()
    duplicate_keys = load_duplicate_keys()
    pool = []

    try:
        researched = ResearchedSponsorSource().load()
    except Exception as exc:
        print(f"WARNING: researched TikTok source failed: {exc}")
        researched = []

    pool.extend(lead for lead in researched if _is_tiktok(lead))

    # Fresh TikTok-only discovery to fill beyond stored research inventory.
    try:
        posts = scanner.discover(lookback_days=min(30, config.max_sponsor_age_days), max_posts=120)
        pool.extend(scanner.to_lead(post) for post in posts)
        print(f"TIKTOK_FIVE_DISCOVERY: fresh_posts={len(posts)}")
    except Exception as exc:
        print(f"WARNING: fresh TikTok discovery failed: {exc}")

    candidates = []
    seen = set()
    for lead in pool:
        if not _is_tiktok(lead):
            continue
        followers = _hydrate_followers(lead, scanner)
        if followers <= 0 or followers > MAX_CREATOR_FOLLOWERS:
            print(f"TIKTOK_FIVE_SKIP_FOLLOWERS: {lead.brand_name} / {followers or 'unknown'}")
            continue

        try:
            lead = _enrich_lead(lead, enricher)
        except Exception as exc:
            print(f"TIKTOK_FIVE_SKIP_ENRICH: {lead.brand_name} / {exc}")
            continue

        if is_duplicate(lead, duplicate_keys):
            continue
        if not _is_recent_sponsorship(lead, config.max_sponsor_age_days):
            continue
        if not is_qualified_outreach_contact(lead):
            continue
        if lead.lead_score < config.min_lead_score:
            continue
        if not _is_dispatch_target_lead(lead):
            continue

        identity = (lead.brand_key or lead.brand_domain or lead.brand_name).strip().lower()
        if not identity or identity in seen:
            continue
        seen.add(identity)
        candidates.append(lead)

    # Smaller creators first, then hotter/recent leads.
    candidates.sort(
        key=lambda lead: (
            int(lead.creator_subscribers or 0),
            -int(lead.lead_score or 0),
            lead.sponsored_date or "",
        )
    )

    delivered = 0
    for lead in candidates:
        if delivered >= TARGET_SENDS:
            break
        try:
            result = monday.create_lead(lead)
            item = result.get("data", {}).get("create_item", {})
            item_id = str(item.get("id", ""))
            discord.send_new_lead(lead)
        except Exception as exc:
            print(f"TIKTOK_FIVE_DELIVERY_ERROR: {lead.brand_name} / {exc}")
            continue

        mark_sent(lead, sent_keys)
        mark_creator_used(lead, sent_keys)
        save_sent_keys(sent_keys)
        duplicate_keys.update(sent_keys)
        delivered += 1
        print(
            f"TIKTOK_FIVE_SENT: {delivered}/5 / {lead.brand_name} / "
            f"followers={lead.creator_subscribers:,} / monday={item_id or '?'}"
        )

    print(
        f"TIKTOK_FIVE_COMPLETE: delivered={delivered}; qualified={len(candidates)}; "
        f"rule=1-{MAX_CREATOR_FOLLOWERS} verified followers"
    )
    if delivered < TARGET_SENDS:
        raise RuntimeError(
            f"Only {delivered}/5 TikTok leads met the verified <=100K follower rule."
        )


if __name__ == "__main__":
    run()
