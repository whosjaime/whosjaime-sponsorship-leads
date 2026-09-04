from __future__ import annotations

import os

from brand_enrichment import BrandEnricher
from instagram_sponsor_scanner import InstagramSponsorScanner
from run_sponsor_discovery_batch import _identity, run as run_youtube_discovery
from run_sponsor_discovery_multisource import _qualify_social_candidates, _queue_sort_key
from sponsor_config import load_sponsor_config
from sponsor_queue import MAX_QUEUE_SIZE, load_duplicate_keys, load_queue, save_queue
from tiktok_sponsor_scanner import TikTokSponsorScanner


MIN_SOCIAL_READY = int(os.getenv("SPONSOR_SOCIAL_MIN_READY", "10"))
TARGET_SOCIAL_READY = int(os.getenv("SPONSOR_SOCIAL_TARGET_READY", "20"))
ALLOW_YOUTUBE_FALLBACK = os.getenv("SPONSOR_ALLOW_YOUTUBE_FALLBACK", "true").strip().lower() in {
    "1", "true", "yes", "on"
}


def _platform(lead) -> str:
    return (getattr(lead, "source_platform", "") or "").strip().lower()


def _merge_front(existing, fresh):
    """Put fresh social inventory first while keeping one lead per brand identity."""
    fresh = sorted(fresh, key=_queue_sort_key, reverse=True)
    combined = [*fresh, *existing]
    kept = []
    seen = set()
    for lead in combined:
        identity = _identity(lead)
        if not identity or identity in seen:
            continue
        seen.add(identity)
        kept.append(lead)
        if len(kept) >= MAX_QUEUE_SIZE:
            break
    return kept


def run() -> None:
    config = load_sponsor_config(require_discord=False, require_monday=False)
    enricher = BrandEnricher()
    duplicate_keys = load_duplicate_keys()
    queue = load_queue()
    queue_ids = {_identity(lead) for lead in queue if _identity(lead)}
    fresh = []

    # 1) TikTok first.
    if config.enable_tiktok:
        scanner = TikTokSponsorScanner(config.search_language, config.search_region)
        tiktok_candidates, tiktok_posts = _qualify_social_candidates(
            scanner, "TikTok", config, enricher, duplicate_keys, queue_ids
        )
        fresh.extend(tiktok_candidates)
        print(
            f"SOCIAL_FIRST_TIKTOK: checked={tiktok_posts}; new={len(tiktok_candidates)}"
        )
    else:
        print("SOCIAL_FIRST_TIKTOK: disabled")

    # 2) Instagram fills the gap after TikTok.
    current_social = sum(1 for lead in [*fresh, *queue] if _platform(lead) in {"tiktok", "instagram"})
    if current_social < TARGET_SOCIAL_READY:
        scanner = InstagramSponsorScanner(config.search_language, config.search_region)
        instagram_candidates, instagram_posts = _qualify_social_candidates(
            scanner, "Instagram", config, enricher, duplicate_keys, queue_ids
        )
        fresh.extend(instagram_candidates)
        print(
            f"SOCIAL_FIRST_INSTAGRAM: checked={instagram_posts}; new={len(instagram_candidates)}"
        )

    queue = _merge_front(queue, fresh)
    save_queue(queue)

    social_ready = sum(1 for lead in queue if _platform(lead) in {"tiktok", "instagram"})
    tiktok_ready = sum(1 for lead in queue if _platform(lead) == "tiktok")
    instagram_ready = sum(1 for lead in queue if _platform(lead) == "instagram")
    print(
        f"SOCIAL_FIRST_QUEUE: total={len(queue)}; TikTok={tiktok_ready}; "
        f"Instagram={instagram_ready}; social={social_ready}"
    )

    # 3) YouTube is a last resort only when social cannot hit the minimum floor.
    if social_ready < MIN_SOCIAL_READY and ALLOW_YOUTUBE_FALLBACK:
        print(
            f"SOCIAL_FIRST_FALLBACK: social inventory {social_ready} below minimum "
            f"{MIN_SOCIAL_READY}; running YouTube fallback."
        )
        run_youtube_discovery()
    else:
        print("SOCIAL_FIRST_FALLBACK: YouTube not needed.")


if __name__ == "__main__":
    run()
