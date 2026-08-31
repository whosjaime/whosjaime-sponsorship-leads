from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from outreach_contact_policy import is_qualified_outreach_contact
from researched_sponsor_source import ResearchedSponsorSource
from run_sponsor_discovery_batch import _identity, _is_queue_target_lead, _priority_score
from run_sponsor_scan import _is_recent_sponsorship, _score_lead, _temperature
from sponsor_config import load_sponsor_config
from sponsor_daily_policy import DAILY_TARGET, balance_platforms, platform_key
from sponsor_dedupe import make_brand_key, make_sponsorship_key
from sponsor_queue import is_duplicate, load_duplicate_keys, load_queue


QUEUE_PATH = Path("data/sponsor_queue.json")


def _write_queue(leads) -> None:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_PATH.write_text(
        json.dumps([lead.as_dict() for lead in leads[:DAILY_TARGET]], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _prepare(lead) -> None:
    """Apply deterministic local fields without blocking on live website/API enrichment."""
    if not lead.brand_key:
        lead.brand_key = make_brand_key(lead.brand_name, lead.brand_domain)
    if not lead.sponsorship_key:
        lead.sponsorship_key = make_sponsorship_key(
            lead.source_platform,
            lead.video_id,
            lead.brand_name,
            lead.brand_domain,
        )
    if not lead.lead_score:
        lead.lead_score = _score_lead(lead)
        lead.lead_temperature = _temperature(lead.lead_score)


def _qualified_pool(config, duplicate_keys) -> list:
    existing = load_queue()
    try:
        researched = ResearchedSponsorSource().load()
    except Exception as exc:
        print(f"WARNING: researched inventory failed: {exc}")
        researched = []

    candidates = []
    seen: set[str] = set()
    for lead in [*existing, *researched]:
        _prepare(lead)
        identity = _identity(lead)
        if not identity or identity in seen:
            continue
        if is_duplicate(lead, duplicate_keys):
            continue
        if not _is_recent_sponsorship(lead, config.max_sponsor_age_days):
            continue
        if not is_qualified_outreach_contact(lead):
            continue
        if lead.lead_score < config.min_lead_score:
            continue
        if not _is_queue_target_lead(lead):
            continue
        seen.add(identity)
        candidates.append(lead)

    candidates.sort(
        key=lambda lead: (_priority_score(lead), lead.lead_score, lead.sponsored_date),
        reverse=True,
    )
    return candidates


def run() -> None:
    """Build the fastest possible 24-lead queue from already-verified durable inventory.

    Live web/API discovery is intentionally NOT executed here. It now runs in its own
    bounded workflow so a slow YouTube/TikTok source can never hold verified backlog
    hostage and stop Monday/Discord delivery.
    """
    config = load_sponsor_config(require_discord=False, require_monday=False)
    duplicate_keys = load_duplicate_keys()
    candidates = _qualified_pool(config, duplicate_keys)
    final_queue = balance_platforms(candidates, DAILY_TARGET)
    _write_queue(final_queue)

    counts = Counter(platform_key(lead.source_platform) for lead in final_queue)
    print(
        "DAILY_SPONSOR_QUEUE_READY: "
        f"{len(final_queue)}/{DAILY_TARGET} queued; "
        f"YouTube={counts.get('youtube', 0)}, "
        f"TikTok={counts.get('tiktok', 0)}, "
        f"Instagram={counts.get('instagram', 0)}, "
        f"fallback/other={sum(v for k, v in counts.items() if k not in {'youtube','tiktok','instagram'})}."
    )

    if len(final_queue) < DAILY_TARGET:
        print(
            f"WARNING: only {len(final_queue)} verified unsent leads are currently available. "
            "Independent live discovery keeps replenishing this inventory; weak or duplicate leads are never used to fake 24."
        )


if __name__ == "__main__":
    run()
