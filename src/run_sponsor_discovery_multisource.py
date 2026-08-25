from __future__ import annotations

import os

from brand_enrichment import BrandEnricher
from run_sponsor_discovery_batch import (
    _build_balanced_queue,
    _enrich_lead,
    _identity,
    _is_queue_target_lead,
    _is_recent_sponsorship,
    _priority_score,
    run as run_youtube_discovery,
)
from sponsor_config import load_sponsor_config
from sponsor_models import SponsorLead
from sponsor_queue import MAX_QUEUE_SIZE, is_duplicate, load_duplicate_keys, load_queue, save_queue
from tiktok_sponsor_scanner import TikTokSponsorScanner


def _classify_tiktok(lead: SponsorLead) -> None:
    text = f'{lead.video_title} {lead.evidence}'.lower()
    mappings = (
        ('Gaming', ('gaming', 'gamer', 'xbox', 'playstation', 'nintendo', 'steam', 'controller')),
        ('Beauty', ('makeup', 'skincare', 'beauty', 'cosmetic', 'haircare')),
        ('Food', ('food', 'snack', 'drink', 'recipe', 'coffee', 'protein', 'restaurant')),
        ('Fashion', ('fashion', 'outfit', 'clothing', 'shoes', 'style', 'wear')),
        ('Health & Wellness', ('fitness', 'wellness', 'workout', 'supplement', 'health')),
        ('Travel', ('travel', 'hotel', 'flight', 'luggage', 'vacation', 'trip')),
        ('Home', ('home', 'decor', 'cleaning', 'furniture', 'kitchen', 'bedroom')),
        ('Pet', ('pet', 'dog', 'cat', 'puppy', 'kitten')),
        ('Music', ('music', 'guitar', 'singer', 'song', 'studio', 'microphone')),
        ('Entertainment', ('reaction', 'comedy', 'streamer', 'entertainment', 'vlog')),
    )
    tags = ['tiktok']
    for genre, keywords in mappings:
        if any(keyword in text for keyword in keywords):
            lead.creator_genre = genre
            tags.append(genre.lower())
            break
    if lead.creator_genre == 'Other':
        lead.creator_genre = 'Lifestyle'
        tags.append('lifestyle')
    lead.creator_tags = list(dict.fromkeys(tags))


def run() -> None:
    # Source order is deliberate: YouTube first, TikTok second. CreatorDB is left
    # available to the existing batch only when TikTok is disabled.
    initial_config = load_sponsor_config(require_discord=False, require_monday=False)
    enable_tiktok = initial_config.enable_tiktok
    saved_creatordb = os.environ.get('CREATORDB_API_KEY')
    if enable_tiktok:
        os.environ['CREATORDB_API_KEY'] = ''
    try:
        run_youtube_discovery()
    finally:
        if saved_creatordb is None:
            os.environ.pop('CREATORDB_API_KEY', None)
        else:
            os.environ['CREATORDB_API_KEY'] = saved_creatordb

    if not enable_tiktok:
        print('TikTok sponsor discovery disabled.')
        return

    config = load_sponsor_config(require_discord=False, require_monday=False)
    scanner = TikTokSponsorScanner(config.search_language, config.search_region)
    enricher = BrandEnricher()
    duplicate_keys = load_duplicate_keys()
    queue = load_queue()
    queue_ids = {_identity(lead) for lead in queue if _identity(lead)}

    try:
        posts = scanner.discover(config.max_sponsor_age_days)
    except Exception as exc:
        print(f'WARNING: TikTok sponsor discovery failed: {exc}')
        return

    candidates: list[SponsorLead] = []
    for post in posts:
        lead = scanner.to_lead(post)
        _classify_tiktok(lead)
        try:
            lead = _enrich_lead(lead, enricher)
        except Exception as exc:
            print(f'TikTok enrichment skipped {lead.brand_name}: {exc}')
            continue
        if is_duplicate(lead, duplicate_keys):
            print(f'TikTok GitHub duplicate/blocklist skipped: {lead.brand_name}')
            continue
        if not _is_recent_sponsorship(lead, config.max_sponsor_age_days):
            continue
        if not lead.contact_email:
            print(f'TikTok qualified outreach email required; skipped: {lead.brand_name}')
            continue
        if lead.lead_score < config.min_lead_score:
            continue
        if not _is_queue_target_lead(lead):
            continue
        identity = _identity(lead)
        if not identity or identity in queue_ids:
            continue
        queue_ids.add(identity)
        candidates.append(lead)
        print(
            f'Queued candidate via TikTok: {lead.brand_name} / '
            f'{lead.creator_name} / followers {lead.creator_subscribers or 0} / score {lead.lead_score}'
        )

    if not candidates:
        print(f'TikTok scan complete: {len(posts)} qualifying-disclosure posts checked; 0 new queue leads.')
        return

    combined = [*queue, *candidates]
    combined.sort(
        key=lambda lead: (_priority_score(lead), lead.lead_score, lead.sponsored_date),
        reverse=True,
    )
    final_queue = _build_balanced_queue(combined)[:MAX_QUEUE_SIZE]
    save_queue(final_queue)
    print(
        f'TikTok scan complete: {len(posts)} qualifying-disclosure posts checked; '
        f'{len(candidates)} verified new candidate(s); queue now {len(final_queue)}.'
    )


if __name__ == '__main__':
    run()
