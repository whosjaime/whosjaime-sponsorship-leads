from __future__ import annotations

import os
from collections import Counter

from brand_enrichment import BrandEnricher
from instagram_sponsor_scanner import InstagramSponsorScanner
from outreach_contact_policy import is_qualified_outreach_contact
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
from sponsor_dedupe import normalize_brand_name
from sponsor_models import SponsorLead
from sponsor_queue import MAX_QUEUE_SIZE, is_duplicate, load_duplicate_keys, load_queue, save_queue
from tiktok_sponsor_scanner import TikTokSponsorScanner


FOOD_DRINK_KEYWORDS = {
    'food', 'snack', 'snacks', 'drink', 'drinks', 'beverage', 'beverages', 'coffee',
    'tea', 'soda', 'sparkling water', 'water', 'hydration', 'protein bar', 'protein shake',
    'meal', 'meals', 'recipe', 'restaurant', 'sauce', 'seasoning', 'candy', 'chocolate',
    'cookie', 'cookies', 'chips', 'granola', 'cereal', 'juice', 'smoothie', 'energy drink',
}


def _is_food_drink_lead(lead: SponsorLead) -> bool:
    category = (lead.sponsor_category or '').strip().lower()
    if category in {'food', 'food & beverage', 'food/drink', 'beverage'}:
        return True
    text = ' '.join(
        [
            lead.brand_name or '', lead.sponsor_category or '', lead.sponsor_subcategory or '',
            lead.video_title or '', lead.evidence or '',
        ]
    ).lower()
    return any(keyword in text for keyword in FOOD_DRINK_KEYWORDS)


def _classify_social(lead: SponsorLead) -> None:
    text = f'{lead.video_title} {lead.evidence}'.lower()
    mappings = (
        ('Gaming', ('gaming', 'gamer', 'xbox', 'playstation', 'nintendo', 'steam', 'controller')),
        ('Beauty', ('makeup', 'skincare', 'beauty', 'cosmetic', 'haircare')),
        ('Food & Beverage', (
            'food', 'snack', 'drink', 'beverage', 'recipe', 'coffee', 'tea', 'soda',
            'sparkling water', 'protein bar', 'protein shake', 'restaurant', 'candy',
            'chocolate', 'chips', 'granola', 'cereal', 'juice', 'smoothie', 'hydration',
        )),
        ('Fashion', ('fashion', 'outfit', 'clothing', 'shoes', 'style', 'wear')),
        ('Health & Wellness', ('fitness', 'wellness', 'workout', 'supplement', 'health')),
        ('Travel', ('travel', 'hotel', 'flight', 'luggage', 'vacation', 'trip')),
        ('Home', ('home', 'decor', 'cleaning', 'furniture', 'kitchen', 'bedroom')),
        ('Pet', ('pet', 'dog', 'cat', 'puppy', 'kitten')),
        ('Music', ('music', 'guitar', 'singer', 'song', 'studio', 'microphone')),
        ('Entertainment', ('reaction', 'comedy', 'streamer', 'entertainment', 'vlog')),
    )
    platform_tag = (lead.source_platform or 'social').strip().lower()
    tags = [platform_tag]
    for genre, keywords in mappings:
        if any(keyword in text for keyword in keywords):
            lead.creator_genre = genre
            tags.append(genre.lower())
            break
    if (lead.creator_genre or '').strip().lower() in {'', 'other'}:
        lead.creator_genre = 'Lifestyle'
        tags.append('lifestyle')
    lead.creator_tags = list(dict.fromkeys(tags))


def _creator_size_priority(lead: SponsorLead) -> int:
    """Smaller verified creator audiences are stronger outreach signals."""
    followers = int(getattr(lead, 'creator_subscribers', 0) or 0)
    if followers <= 0:
        return 0
    if followers <= 10_000:
        return 140
    if followers <= 25_000:
        return 125
    if followers <= 50_000:
        return 110
    if followers <= 100_000:
        return 95
    if followers <= 250_000:
        return 70
    if followers <= 500_000:
        return 45
    if followers <= 1_000_000:
        return 20
    return 0


def _repeat_sponsor_priority(lead: SponsorLead) -> int:
    count = 1
    for signal in (lead.signals or []):
        prefix = 'sponsor appearance count:'
        if str(signal).startswith(prefix):
            try:
                count = max(count, int(str(signal)[len(prefix):]))
            except ValueError:
                pass
    if count >= 6:
        return 140
    if count >= 4:
        return 110
    if count >= 3:
        return 85
    if count == 2:
        return 55
    return 0


def _queue_sort_key(lead: SponsorLead) -> tuple[int, int, int, int, int, int, str]:
    platform = (lead.source_platform or '').strip().lower()
    return (
        1 if platform == 'tiktok' else 0,
        _repeat_sponsor_priority(lead),
        _creator_size_priority(lead),
        1 if _is_food_drink_lead(lead) else 0,
        _priority_score(lead),
        lead.lead_score,
        lead.sponsored_date,
    )


def _qualify_social_candidates(
    scanner,
    platform: str,
    config,
    enricher: BrandEnricher,
    duplicate_keys: set[str],
    queue_ids: set[str],
) -> tuple[list[SponsorLead], int]:
    try:
        posts = scanner.discover(config.max_sponsor_age_days)
    except Exception as exc:
        print(f'WARNING: {platform} sponsor discovery failed: {exc}')
        return [], 0

    brand_counts = Counter(
        normalize_brand_name(getattr(post, 'brand_name', '') or '')
        for post in posts
        if normalize_brand_name(getattr(post, 'brand_name', '') or '')
    )

    candidates: list[SponsorLead] = []
    for post in posts:
        lead = scanner.to_lead(post)
        repeat_count = brand_counts.get(normalize_brand_name(lead.brand_name), 1)
        if repeat_count > 1:
            lead.signals = list(lead.signals or []) + [f'sponsor appearance count:{repeat_count}']
        _classify_social(lead)
        if not lead.brand_domain:
            print(f'{platform} official brand domain unresolved; skipped: {lead.brand_name}')
            continue
        try:
            lead = _enrich_lead(lead, enricher)
        except Exception as exc:
            print(f'{platform} enrichment skipped {lead.brand_name}: {exc}')
            continue
        if is_duplicate(lead, duplicate_keys):
            print(f'{platform} GitHub duplicate/blocklist skipped: {lead.brand_name}')
            continue
        if not _is_recent_sponsorship(lead, config.max_sponsor_age_days):
            continue
        if not is_qualified_outreach_contact(lead):
            print(f'{platform} qualified outreach contact required; skipped: {lead.brand_name}')
            continue
        if lead.lead_score < config.min_lead_score:
            print(f'{platform} score below threshold; skipped: {lead.brand_name} / {lead.lead_score}')
            continue
        if not _is_queue_target_lead(lead):
            continue
        identity = _identity(lead)
        if not identity or identity in queue_ids:
            continue
        queue_ids.add(identity)
        candidates.append(lead)
        followers = int(lead.creator_subscribers or 0)
        follower_label = f'{followers:,} followers' if followers > 0 else 'followers unknown'
        repeat_label = f' / {repeat_count} sponsor posts' if repeat_count > 1 else ''
        food_label = ' / FOOD-DRINK PRIORITY' if _is_food_drink_lead(lead) else ''
        print(
            f'Queued candidate via {platform}: {lead.brand_name} / {lead.creator_name} / '
            f'{follower_label}{repeat_label} / score {lead.lead_score}{food_label}'
        )
    return candidates, len(posts)


def run() -> None:
    # YouTube discovery remains its own mature source. TikTok and Instagram are then
    # added independently so one social platform failing never prevents the other.
    initial_config = load_sponsor_config(require_discord=False, require_monday=False)
    saved_creatordb = os.environ.get('CREATORDB_API_KEY')
    if initial_config.enable_tiktok:
        os.environ['CREATORDB_API_KEY'] = ''
    try:
        run_youtube_discovery()
    finally:
        if saved_creatordb is None:
            os.environ.pop('CREATORDB_API_KEY', None)
        else:
            os.environ['CREATORDB_API_KEY'] = saved_creatordb

    config = load_sponsor_config(require_discord=False, require_monday=False)
    enricher = BrandEnricher()
    duplicate_keys = load_duplicate_keys()
    queue = load_queue()
    queue_ids = {_identity(lead) for lead in queue if _identity(lead)}
    all_candidates: list[SponsorLead] = []

    if config.enable_tiktok:
        tiktok_scanner = TikTokSponsorScanner(config.search_language, config.search_region)
        tiktok_candidates, tiktok_posts = _qualify_social_candidates(
            tiktok_scanner, 'TikTok', config, enricher, duplicate_keys, queue_ids,
        )
        all_candidates.extend(tiktok_candidates)
        print(
            f'TikTok scan complete: {tiktok_posts} explicit-disclosure posts checked; '
            f'{len(tiktok_candidates)} verified new candidate(s).'
        )
    else:
        print('TikTok sponsor discovery disabled.')

    instagram_scanner = InstagramSponsorScanner(config.search_language, config.search_region)
    instagram_candidates, instagram_posts = _qualify_social_candidates(
        instagram_scanner, 'Instagram', config, enricher, duplicate_keys, queue_ids,
    )
    all_candidates.extend(instagram_candidates)
    print(
        f'Instagram scan complete: {instagram_posts} explicit-disclosure posts checked; '
        f'{len(instagram_candidates)} verified new candidate(s).'
    )

    if not all_candidates:
        print('Social discovery produced 0 new verified queue leads.')
        return

    combined = [*queue, *all_candidates]
    combined.sort(key=_queue_sort_key, reverse=True)
    final_queue = _build_balanced_queue(combined)[:MAX_QUEUE_SIZE]
    save_queue(final_queue)
    food_count = sum(1 for lead in final_queue if _is_food_drink_lead(lead))
    tiktok_count = sum(1 for lead in final_queue if (lead.source_platform or '').strip().lower() == 'tiktok')
    instagram_count = sum(1 for lead in final_queue if (lead.source_platform or '').strip().lower() == 'instagram')
    youtube_count = sum(1 for lead in final_queue if (lead.source_platform or '').strip().lower() == 'youtube')
    print(
        f'SOCIAL_DISCOVERY_QUEUE: {len(final_queue)} total; YouTube={youtube_count}; '
        f'TikTok={tiktok_count}; Instagram={instagram_count}; food/drink={food_count}; '
        f'new social={len(all_candidates)}.'
    )


if __name__ == '__main__':
    run()
