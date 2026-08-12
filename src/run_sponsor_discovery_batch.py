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
from youtube_sponsor_scanner import BACKUP_SEARCH_LANES, SEARCH_LANES, YouTubeSponsorScanner


BACKUP_QUEUE_TRIGGER = 18

BEAUTY_QUEUE_LIMIT = 2
BEAUTY_QUEUE_POSITIONS = (5, 15)
BEAUTY_KEYWORDS = {
    "beauty", "skincare", "skin care", "cosmetics", "makeup", "haircare", "hair care",
}

MUSIC_QUEUE_LIMIT = 2
MUSIC_QUEUE_POSITIONS = (9, 19)
MUSIC_KEYWORDS = {
    "music gear", "musical instrument", "musical instruments", "guitar", "guitars",
    "bass guitar", "drum", "drums", "piano", "synthesizer", "synth", "amplifier",
    "guitar amp", "guitar pedal", "pedalboard", "guitar strings", "instrument strings",
    "recording gear", "studio gear", "music production", "music software", "audio interface",
    "daw", "vst", "audio plugin", "music plugin", "producer tool", "artist tool",
}
MUSIC_EXCLUDED_KEYWORDS = {
    "music festival", "concert festival", "festival", "concert promoter", "event production",
    "ticketing", "venue",
}

STREAMING_QUEUE_LIMIT = 2
STREAMING_QUEUE_POSITIONS = (3, 13)
VLOG_QUEUE_LIMIT = 2
VLOG_QUEUE_POSITIONS = (7, 17)
SECONDARY_CREATOR_SPONSOR_CATEGORIES = {
    "Fashion", "Health & Wellness", "Travel", "Home", "Entertainment", "Beauty",
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


def _creator_tags_lower(lead: SponsorLead) -> set[str]:
    return {str(tag).strip().lower() for tag in (lead.creator_tags or []) if str(tag).strip()}


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


def _is_streaming_lead(lead: SponsorLead) -> bool:
    genre = (lead.creator_genre or "").strip().lower()
    tags = _creator_tags_lower(lead)
    return genre == "streaming" or "streaming" in tags


def _is_vlog_lead(lead: SponsorLead) -> bool:
    genre = (lead.creator_genre or "").strip().lower()
    tags = _creator_tags_lower(lead)
    return "lifestyle" in tags or genre in {"lifestyle"} or (
        genre in {"entertainment", "family", "travel"} and "lifestyle" in tags
    )


def _is_queue_target_lead(lead: SponsorLead) -> bool:
    """Core sponsor niches plus carefully limited secondary creator/category exceptions."""
    if _is_target_lead(lead) or _is_beauty_lead(lead) or _is_music_lead(lead):
        return True
    if (_is_streaming_lead(lead) or _is_vlog_lead(lead)) and lead.sponsor_category in SECONDARY_CREATOR_SPONSOR_CATEGORIES:
        return True
    return False


def _secondary_coverage_missing(leads: list[SponsorLead]) -> bool:
    return not all(
        (
            any(_is_streaming_lead(lead) for lead in leads),
            any(_is_vlog_lead(lead) for lead in leads),
            any(_is_beauty_lead(lead) for lead in leads),
            any(_is_music_lead(lead) for lead in leads),
        )
    )


def _build_balanced_queue(leads: list[SponsorLead]) -> list[SponsorLead]:
    """Keep secondary categories useful but limited and spaced through the queue."""
    beauty: list[SponsorLead] = []
    music: list[SponsorLead] = []
    streaming: list[SponsorLead] = []
    vlog: list[SponsorLead] = []
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
        elif _is_streaming_lead(lead):
            if len(streaming) < STREAMING_QUEUE_LIMIT:
                streaming.append(lead)
        elif _is_vlog_lead(lead):
            if len(vlog) < VLOG_QUEUE_LIMIT:
                vlog.append(lead)
        else:
            core.append(lead)

    special_count = len(beauty) + len(music) + len(streaming) + len(vlog)
    core_slots = max(0, MAX_QUEUE_SIZE - special_count)
    final_queue = core[:core_slots]

    placements: list[tuple[int, SponsorLead]] = []
    for index, lead in enumerate(streaming):
        placements.append((STREAMING_QUEUE_POSITIONS[min(index, len(STREAMING_QUEUE_POSITIONS) - 1)], lead))
    for index, lead in enumerate(beauty):
        placements.append((BEAUTY_QUEUE_POSITIONS[min(index, len(BEAUTY_QUEUE_POSITIONS) - 1)], lead))
    for index, lead in enumerate(vlog):
        placements.append((VLOG_QUEUE_POSITIONS[min(index, len(VLOG_QUEUE_POSITIONS) - 1)], lead))
    for index, lead in enumerate(music):
        placements.append((MUSIC_QUEUE_POSITIONS[min(index, len(MUSIC_QUEUE_POSITIONS) - 1)], lead))

    for desired_position, lead in sorted(placements, key=lambda item: item[0]):
        final_queue.insert(min(desired_position, len(final_queue)), lead)

    return final_queue[:MAX_QUEUE_SIZE]


def _hydrate_creator_metrics(leads: list[SponsorLead], youtube: YouTubeSponsorScanner) -> None:
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
    channel_ids = list(dict.fromkeys(video.channel_id for video in videos if video.channel_id))
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

    print(f"Creator metric hydration: updated {hydrated}/{len(needs_hydration)} queued/researched leads.")


def run() -> None:
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
            print(
                f"Queued candidate via {source}: {lead.brand_name} / "
                f"{lead.creator_genre or 'Other'} / score {lead.lead_score}"
            )

    for lead in researched_leads:
        consider(lead, "Daily Research")

    search_days = min(config.max_sponsor_age_days, MAX_NATIVE_YOUTUBE_LOOKBACK_DAYS)
    lookback_hours = max(24, search_days * 24)

    def process_youtube(videos, channels, source: str) -> None:
        nonlocal rejected_count
        for video in videos:
            if video.video_id in scanned_video_ids:
                continue
            scanned_video_ids.add(video.video_id)
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
                consider(to_sponsor_lead(video, creator, detection, genre, tags), source)

    starting_pool = [*valid_existing, *candidates.values()]
    if len(starting_pool) < BACKUP_QUEUE_TRIGGER:
        print(
            f"Queue has {len(starting_pool)} qualified leads; running main YouTube top-up "
            f"across up to {len(SEARCH_LANES) * 50} search results."
        )
        try:
            videos, channels = youtube.discover_batch(lookback_hours)
        except Exception as exc:
            print(f"WARNING: YouTube main sponsor discovery failed: {exc}")
            videos, channels = [], {}
        process_youtube(videos, channels, "YouTube Main")
    else:
        print(f"Queue already has {len(starting_pool)} qualified leads; main YouTube top-up skipped.")

    current_pool = [*valid_existing, *candidates.values()]
    if len(current_pool) < BACKUP_QUEUE_TRIGGER or _secondary_coverage_missing(current_pool):
        print(
            f"Backup discovery activated at {len(current_pool)} leads; targeting streaming, "
            f"vlog/lifestyle, beauty, and music across up to {len(BACKUP_SEARCH_LANES) * 50} results."
        )
        try:
            videos, channels = youtube.discover_backup_batch(lookback_hours)
        except Exception as exc:
            print(f"WARNING: YouTube backup sponsor discovery failed: {exc}")
            videos, channels = [], {}
        process_youtube(videos, channels, "YouTube Backup")

    needed = max(0, MAX_QUEUE_SIZE - len(valid_existing) - len(candidates))
    if needed and creatordb is not None:
        try:
            for lead in creatordb.discover(config.max_sponsor_age_days):
                consider(lead, "CreatorDB Backup")
                if len(valid_existing) + len(candidates) >= MAX_QUEUE_SIZE:
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
    streaming_count = sum(1 for lead in final_queue if _is_streaming_lead(lead))
    vlog_count = sum(1 for lead in final_queue if _is_vlog_lead(lead))

    save_queue(final_queue)
    print(
        f"SPONSOR_QUEUE_READY: {len(final_queue)} queued "
        f"({streaming_count} streaming, {vlog_count} vlog/lifestyle, "
        f"{beauty_count} beauty, {music_count} music), "
        f"{len(scanned_video_ids)} YouTube videos hydrated, "
        f"{duplicate_count} GitHub duplicate/blocked, {rejected_count} rejected."
    )


if __name__ == "__main__":
    run()
