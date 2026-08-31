from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from outreach_contact_policy import is_qualified_outreach_contact
from researched_sponsor_source import ResearchedSponsorSource
from run_sponsor_discovery_batch import _identity, _is_queue_target_lead, _priority_score
from run_sponsor_discovery_multisource import run as run_multisource
from run_sponsor_scan import _is_recent_sponsorship, _score_lead, _temperature
from sponsor_config import load_sponsor_config
from sponsor_daily_policy import DAILY_TARGET, PLATFORM_TARGETS, balance_platforms, platform_key
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
    """Apply deterministic local fields without blocking on live website enrichment."""
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


def _needs_live_discovery(candidates: list) -> bool:
    if len(candidates) < DAILY_TARGET:
        return True
    counts = Counter(platform_key(lead.source_platform) for lead in candidates)
    # Live discovery currently helps YouTube/TikTok. Instagram is supplied by the durable
    # verified research inventory, so do not hold the whole run open trying to fabricate it.
    return (
        counts.get("youtube", 0) < PLATFORM_TARGETS["youtube"]
        or counts.get("tiktok", 0) < PLATFORM_TARGETS["tiktok"]
    )


def run() -> None:
    """Build a 24-lead daily-ready queue with YouTube/TikTok/Instagram balance.

    Critical reliability rule: drain already-verified durable research first. Live API
    discovery is only a top-up mechanism and can never block qualified backlog from
    reaching the delivery queue.
    """
    config = load_sponsor_config(require_discord=False, require_monday=False)
    duplicate_keys = load_duplicate_keys()

    candidates = _qualified_pool(config, duplicate_keys)
    if _needs_live_discovery(candidates):
        try:
            run_multisource()
        except Exception as exc:
            print(f"WARNING: multisource discovery failed; using durable verified inventory: {exc}")
        # Re-read after live discovery because it may have refreshed sponsor_queue.json.
        duplicate_keys = load_duplicate_keys()
        candidates = _qualified_pool(config, duplicate_keys)
    else:
        print(
            f"Durable verified inventory already has {len(candidates)} eligible leads; "
            "skipping slow live discovery for this top-up."
        )

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
            "The scheduled top-up will keep discovering; weak/duplicate leads are never used to fake 24."
        )


if __name__ == "__main__":
    run()
