from __future__ import annotations

from creator_classifier import classify_creator
from creatordb_active_sponsors import CreatorDBActiveSponsorSource
from brand_enrichment import BrandEnricher
from researched_sponsor_source import ResearchedSponsorSource
from run_sponsor_scan import (
    MAX_NATIVE_YOUTUBE_LOOKBACK_DAYS,
    _blocked,
    _enrich_lead,
    _is_recent_sponsorship,
    _is_target_lead,
    _priority_score,
)
from sponsor_config import load_sponsor_config
from sponsor_detector import detect_sponsors, to_sponsor_lead
from sponsor_models import SponsorLead
from sponsor_monday_client import SponsorMondayClient
from sponsor_queue import MAX_QUEUE_SIZE, load_queue, save_queue
from youtube_sponsor_scanner import SEARCH_LANES, YouTubeSponsorScanner


def _identity(lead: SponsorLead) -> str:
    return (lead.brand_key or lead.brand_domain or lead.brand_name).strip().lower()


def run() -> None:
    # Discovery does not send Discord messages. The hourly dispatcher owns the webhook.
    config = load_sponsor_config(require_discord=False)
    monday = SponsorMondayClient(config.monday_token, config.monday_board_id, config.monday_group_id)
    youtube = YouTubeSponsorScanner(config.youtube_api_key, config.search_region, config.search_language)
    researched = ResearchedSponsorSource()
    creatordb = (
        CreatorDBActiveSponsorSource(config.creatordb_api_key, config.creatordb_page_size)
        if config.creatordb_api_key
        else None
    )
    enricher = BrandEnricher()

    monday_index = monday.load_existing_index()
    existing_queue = load_queue()

    # Revalidate leftovers before topping the queue up. Nothing in the queue is allowed
    # to bypass freshness, email, niche, Monday, or permanent-blocklist rules.
    valid_existing: list[SponsorLead] = []
    existing_ids: set[str] = set()
    for lead in existing_queue:
        identity = _identity(lead)
        if not identity or identity in existing_ids:
            continue
        if not _is_recent_sponsorship(lead, config.max_sponsor_age_days):
            continue
        if not lead.contact_email:
            continue
        if not _is_target_lead(lead):
            continue
        if _blocked(monday_index, lead):
            continue
        valid_existing.append(lead)
        existing_ids.add(identity)

    candidates: dict[str, SponsorLead] = {}
    rejected_count = 0
    duplicate_count = 0
    scanned_video_ids: set[str] = set()

    def consider(lead: SponsorLead, source: str) -> None:
        nonlocal rejected_count, duplicate_count
        try:
            lead = _enrich_lead(lead, enricher)
        except Exception as exc:
            rejected_count += 1
            print(f"Batch enrichment skipped {lead.brand_name}: {exc}")
            return

        if not _is_recent_sponsorship(lead, config.max_sponsor_age_days):
            rejected_count += 1
            return
        if not lead.contact_email:
            rejected_count += 1
            print(f"Batch email required; skipped: {lead.brand_name}")
            return
        if _blocked(monday_index, lead):
            duplicate_count += 1
            return
        if lead.lead_score < config.min_lead_score:
            rejected_count += 1
            return
        if not _is_target_lead(lead):
            rejected_count += 1
            return

        identity = _identity(lead)
        if not identity or identity in existing_ids:
            duplicate_count += 1
            return
        current = candidates.get(identity)
        if current is None or (
            _priority_score(lead), lead.lead_score, lead.sponsored_date
        ) > (
            _priority_score(current), current.lead_score, current.sponsored_date
        ):
            candidates[identity] = lead
            print(f"Queued candidate via {source}: {lead.brand_name} / score {lead.lead_score}")

    # Keep the manually researched source in the same queue, but do not let it bypass gates.
    try:
        researched_leads = researched.load()
    except Exception as exc:
        print(f"WARNING: Researched sponsor queue failed: {exc}")
        researched_leads = []
    for lead in researched_leads:
        consider(lead, "Daily Research")

    # Main discovery: exactly 3 search.list calls, each asking for up to 50 results,
    # across the full active-sponsor freshness window. A YouTube outage/quota issue must
    # not erase otherwise-qualified researched sponsors that are already ready to queue.
    search_days = min(config.max_sponsor_age_days, MAX_NATIVE_YOUTUBE_LOOKBACK_DAYS)
    lookback_hours = max(24, search_days * 24)
    print(
        f"Building sponsor queue from up to {len(SEARCH_LANES) * 50} YouTube search results "
        f"across the last {search_days} days..."
    )
    try:
        videos, channels = youtube.discover_batch(lookback_hours)
    except Exception as exc:
        print(f"WARNING: YouTube daily sponsor discovery failed: {exc}")
        videos, channels = [], {}

    for video in videos:
        if video.video_id in scanned_video_ids:
            continue
        scanned_video_ids.add(video.video_id)
        creator = channels.get(video.channel_id)
        genre, tags = classify_creator(video, creator)
        for detection in detect_sponsors(video, channels):
            consider(to_sponsor_lead(video, creator, detection, genre, tags), "YouTube")

    # Optional extra coverage only if the queue is still under a full day.
    needed = max(0, MAX_QUEUE_SIZE - len(valid_existing) - len(candidates))
    if needed and creatordb is not None:
        try:
            for lead in creatordb.discover(config.max_sponsor_age_days):
                consider(lead, "CreatorDB")
                if len(candidates) >= needed:
                    break
        except Exception as exc:
            print(f"WARNING: CreatorDB sponsor coverage failed: {exc}")

    incoming = sorted(
        candidates.values(),
        key=lambda lead: (_priority_score(lead), lead.lead_score, lead.sponsored_date),
        reverse=True,
    )
    combined = [*valid_existing, *incoming]
    combined.sort(
        key=lambda lead: (_priority_score(lead), lead.lead_score, lead.sponsored_date),
        reverse=True,
    )

    final_queue: list[SponsorLead] = []
    seen: set[str] = set()
    for lead in combined:
        identity = _identity(lead)
        if not identity or identity in seen:
            continue
        seen.add(identity)
        final_queue.append(lead)
        if len(final_queue) >= MAX_QUEUE_SIZE:
            break

    save_queue(final_queue)
    print(
        f"SPONSOR_QUEUE_READY: {len(final_queue)} queued, "
        f"{len(scanned_video_ids)} YouTube videos hydrated, "
        f"{duplicate_count} duplicate/blocked, {rejected_count} rejected."
    )


if __name__ == "__main__":
    run()
