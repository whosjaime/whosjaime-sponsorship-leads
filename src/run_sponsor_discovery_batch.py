from __future__ import annotations

from creator_classifier import classify_creator
from creatordb_active_sponsors import CreatorDBActiveSponsorSource
from brand_enrichment import BrandEnricher
from researched_sponsor_source import ResearchedSponsorSource
from run_sponsor_scan import (
    MAX_NATIVE_YOUTUBE_LOOKBACK_DAYS,
    _enrich_lead,
    _is_recent_sponsorship,
    _is_target_lead,
    _priority_score,
)
from sponsor_config import load_sponsor_config
from sponsor_detector import detect_sponsors, to_sponsor_lead
from sponsor_models import SponsorLead
from sponsor_queue import (
    MAX_QUEUE_SIZE,
    is_duplicate,
    load_duplicate_keys,
    load_queue,
    save_queue,
)
from video_language_filter import is_english_video
from youtube_sponsor_scanner import SEARCH_LANES, YouTubeSponsorScanner


BEAUTY_QUEUE_LIMIT = 2
BEAUTY_QUEUE_POSITIONS = (5, 15)
BEAUTY_KEYWORDS = {
    "beauty",
    "skincare",
    "skin care",
    "cosmetics",
    "makeup",
    "haircare",
    "hair care",
}

MUSIC_QUEUE_LIMIT = 2
MUSIC_QUEUE_POSITIONS = (9, 19)
MUSIC_KEYWORDS = {
    "music gear",
    "musical instrument",
    "musical instruments",
    "guitar",
    "guitars",
    "bass guitar",
    "drum",
    "drums",
    "piano",
    "synthesizer",
    "synth",
    "amplifier",
    "guitar amp",
    "guitar pedal",
    "pedalboard",
    "guitar strings",
    "instrument strings",
    "recording gear",
    "studio gear",
    "music production",
    "music software",
    "audio interface",
    "daw",
    "vst",
    "audio plugin",
    "music plugin",
    "producer tool",
    "artist tool",
}
MUSIC_EXCLUDED_KEYWORDS = {
    "music festival",
    "concert festival",
    "festival",
    "concert promoter",
    "event production",
    "ticketing",
    "venue",
}


def _identity(lead: SponsorLead) -> str:
    return (lead.brand_key or lead.brand_domain or lead.brand_name).strip().lower()


def _lead_text(lead: SponsorLead) -> str:
    return " ".join(
        [
            lead.brand_name or "",
            lead.brand_domain or "",
            lead.sponsor_category or "",
            lead.sponsor_subcategory or "",
            lead.evidence or "",
        ]
    ).lower()


def _is_beauty_lead(lead: SponsorLead) -> bool:
    if (lead.sponsor_category or "").strip().lower() == "beauty":
        return True
    text = _lead_text(lead)
    return any(keyword in text for keyword in BEAUTY_KEYWORDS)


def _is_music_lead(lead: SponsorLead) -> bool:
    text = _lead_text(lead)
    if any(keyword in text for keyword in MUSIC_EXCLUDED_KEYWORDS):
        return False
    if (lead.sponsor_category or "").strip().lower() == "music":
        return True
    return any(keyword in text for keyword in MUSIC_KEYWORDS)


def _is_queue_target_lead(lead: SponsorLead) -> bool:
    """Core sponsor niches plus deliberately limited Beauty and Music exceptions."""
    return _is_target_lead(lead) or _is_beauty_lead(lead) or _is_music_lead(lead)


def _build_balanced_queue(leads: list[SponsorLead]) -> list[SponsorLead]:
    """Keep Beauty and Music occasional and spaced through the daily queue."""
    beauty: list[SponsorLead] = []
    music: list[SponsorLead] = []
    core: list[SponsorLead] = []
    seen: set[str] = set()

    for lead in leads:
        identity = _identity(lead)
        if not identity or identity in seen:
            continue
        seen.add(identity)
        if _is_beauty_lead(lead):
            if len(beauty) < BEAUTY_QUEUE_LIMIT:
                beauty.append(lead)
        elif _is_music_lead(lead):
            if len(music) < MUSIC_QUEUE_LIMIT:
                music.append(lead)
        else:
            core.append(lead)

    core_slots = max(0, MAX_QUEUE_SIZE - len(beauty) - len(music))
    final_queue = core[:core_slots]

    placements: list[tuple[int, SponsorLead]] = []
    for index, lead in enumerate(beauty):
        position = BEAUTY_QUEUE_POSITIONS[min(index, len(BEAUTY_QUEUE_POSITIONS) - 1)]
        placements.append((position, lead))
    for index, lead in enumerate(music):
        position = MUSIC_QUEUE_POSITIONS[min(index, len(MUSIC_QUEUE_POSITIONS) - 1)]
        placements.append((position, lead))

    for desired_position, lead in sorted(placements, key=lambda item: item[0]):
        final_queue.insert(min(desired_position, len(final_queue)), lead)

    return final_queue[:MAX_QUEUE_SIZE]


def _hydrate_creator_metrics(
    leads: list[SponsorLead],
    youtube: YouTubeSponsorScanner,
) -> None:
    """Fill missing YouTube creator metadata before leads enter the delivery queue."""
    needs_hydration = [
        lead
        for lead in leads
        if (lead.source_platform or "").strip().lower() == "youtube"
        and lead.video_id
        and (
            not lead.creator_channel_id
            or not lead.creator_url
            or int(lead.creator_subscribers or 0) <= 0
        )
    ]
    if not needs_hydration:
        return

    video_ids = list(dict.fromkeys(lead.video_id for lead in needs_hydration if lead.video_id))
    try:
        videos = youtube.fetch_videos(video_ids)
    except Exception as exc:
        print(f"WARNING: Creator metric video hydration failed: {exc}")
        return

    video_by_id = {video.video_id: video for video in videos if video.video_id}
    channel_ids = list(
        dict.fromkeys(video.channel_id for video in videos if video.channel_id)
    )
    try:
        channels = youtube.fetch_channels(channel_ids) if channel_ids else {}
    except Exception as exc:
        print(f"WARNING: Creator metric channel hydration failed: {exc}")
        channels = {}

    hydrated = 0
    for lead in needs_hydration:
        video = video_by_id.get(lead.video_id)
        if video is None:
            continue
        if video.channel_id:
            lead.creator_channel_id = video.channel_id
            lead.creator_url = f"https://www.youtube.com/channel/{video.channel_id}"
        creator = channels.get(video.channel_id)
        if creator is not None:
            if creator.title:
                lead.creator_name = creator.title
            if int(creator.subscriber_count or 0) > 0:
                lead.creator_subscribers = int(creator.subscriber_count)
        elif video.channel_title and not lead.creator_name:
            lead.creator_name = video.channel_title
        if not lead.video_title and video.title:
            lead.video_title = video.title
        hydrated += 1
        print(
            f"Hydrated creator metrics: {lead.creator_name or 'Unknown creator'} / "
            f"{lead.creator_subscribers or 0:,} subscribers"
        )

    print(
        f"Creator metric hydration: updated {hydrated}/{len(needs_hydration)} queued/researched leads."
    )


def run() -> None:
    # Queue discovery has zero Monday/Discord dependency. GitHub is the duplicate source of truth.
    config = load_sponsor_config(require_discord=False, require_monday=False)
    youtube = YouTubeSponsorScanner(config.youtube_api_key, config.search_region, config.search_language)
    researched = ResearchedSponsorSource()
    creatordb = (
        CreatorDBActiveSponsorSource(config.creatordb_api_key, config.creatordb_page_size)
        if config.creatordb_api_key
        else None
    )
    enricher = BrandEnricher()

    duplicate_keys = load_duplicate_keys()
    existing_queue = load_queue()

    try:
        researched_leads = researched.load()
    except Exception as exc:
        print(f"WARNING: Researched sponsor queue failed: {exc}")
        researched_leads = []

    _hydrate_creator_metrics([*existing_queue, *researched_leads], youtube)

    # Revalidate leftovers before topping up. GitHub sent-history + permanent blocklist
    # are checked before a brand can remain in the queue.
    valid_existing: list[SponsorLead] = []
    existing_ids: set[str] = set()
    for lead in existing_queue:
        identity = _identity(lead)
        if not identity or identity in existing_ids:
            continue
        if is_duplicate(lead, duplicate_keys):
            continue
        if not _is_recent_sponsorship(lead, config.max_sponsor_age_days):
            continue
        if not lead.contact_email:
            continue
        if not _is_queue_target_lead(lead):
            continue
        valid_existing.append(lead)
        existing_ids.add(identity)

    candidates: dict[str, SponsorLead] = {}
    rejected_count = 0
    duplicate_count = 0
    scanned_video_ids: set[str] = set()

    def consider(lead: SponsorLead, source: str) -> None:
        nonlocal rejected_count, duplicate_count
        original_category = (lead.sponsor_category or "").strip()
        try:
            lead = _enrich_lead(lead, enricher)
        except Exception as exc:
            rejected_count += 1
            print(f"Batch enrichment skipped {lead.brand_name}: {exc}")
            return

        if original_category.lower() == "music" and lead.sponsor_category in {"Other", "Entertainment"}:
            lead.sponsor_category = "Music"

        # GitHub duplicate gate runs after enrichment too, so normalized domains/email
        # domains can catch alternate brand names before they ever enter the queue.
        if is_duplicate(lead, duplicate_keys):
            duplicate_count += 1
            print(f"GitHub duplicate/blocklist skipped: {lead.brand_name}")
            return
        if not _is_recent_sponsorship(lead, config.max_sponsor_age_days):
            rejected_count += 1
            return
        if not lead.contact_email:
            rejected_count += 1
            print(f"Batch email required; skipped: {lead.brand_name}")
            return
        if lead.lead_score < config.min_lead_score:
            rejected_count += 1
            return
        if not _is_queue_target_lead(lead):
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

    for lead in researched_leads:
        consider(lead, "Daily Research")

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

        # YouTube's relevanceLanguage=en is not a strict filter. Enforce English after
        # hydration using the video's audio/metadata language and an obvious-script
        # fallback when creators did not set language metadata.
        if not is_english_video(video):
            rejected_count += 1
            language = video.default_audio_language or video.default_language or "metadata/script check"
            print(
                f"Non-English YouTube video skipped: {video.channel_title} / "
                f"{video.title[:100]} / language {language}"
            )
            continue

        creator = channels.get(video.channel_id)
        genre, tags = classify_creator(video, creator)
        for detection in detect_sponsors(video, channels):
            consider(to_sponsor_lead(video, creator, detection, genre, tags), "YouTube")

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

    final_queue = _build_balanced_queue(combined)
    beauty_count = sum(1 for lead in final_queue if _is_beauty_lead(lead))
    music_count = sum(1 for lead in final_queue if _is_music_lead(lead))

    save_queue(final_queue)
    print(
        f"SPONSOR_QUEUE_READY: {len(final_queue)} queued "
        f"({beauty_count} beauty, {music_count} music), "
        f"{len(scanned_video_ids)} YouTube videos hydrated, "
        f"{duplicate_count} GitHub duplicate/blocked, {rejected_count} rejected."
    )


if __name__ == "__main__":
    run()
