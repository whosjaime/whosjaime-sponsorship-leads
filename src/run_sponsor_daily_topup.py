from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from brand_enrichment import BrandEnricher
from outreach_contact_policy import is_qualified_outreach_contact
from researched_sponsor_source import ResearchedSponsorSource
from run_sponsor_discovery_batch import _enrich_lead, _identity, _is_queue_target_lead, _is_recent_sponsorship, _priority_score
from run_sponsor_discovery_multisource import run as run_multisource
from sponsor_config import load_sponsor_config
from sponsor_daily_policy import DAILY_TARGET, balance_platforms, platform_key
from sponsor_queue import is_duplicate, load_duplicate_keys, load_queue


QUEUE_PATH = Path("data/sponsor_queue.json")


def _write_queue(leads) -> None:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_PATH.write_text(
        json.dumps([lead.as_dict() for lead in leads[:DAILY_TARGET]], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def run() -> None:
    """Top up all discovery sources, then enforce a daily-ready cross-platform queue.

    Existing discovery remains useful for fresh YouTube and TikTok candidates. After it
    runs, the durable researched inventory is re-read so verified Instagram/TikTok leads
    and verified named contacts cannot be dropped by older email-only discovery gates.
    """
    try:
        run_multisource()
    except Exception as exc:
        # Research inventory can still keep the delivery SLA alive if a source API is down.
        print(f"WARNING: multisource discovery failed; continuing from researched inventory: {exc}")

    config = load_sponsor_config(require_discord=False, require_monday=False)
    duplicate_keys = load_duplicate_keys()
    enricher = BrandEnricher()

    existing = load_queue()
    try:
        researched = ResearchedSponsorSource().load()
    except Exception as exc:
        print(f"WARNING: researched inventory failed: {exc}")
        researched = []

    candidates = []
    seen: set[str] = set()

    # Existing queue gets first priority only if it still passes today's permanent gates.
    for lead in [*existing, *researched]:
        identity = _identity(lead)
        if not identity or identity in seen:
            continue
        try:
            lead = _enrich_lead(lead, enricher)
        except Exception as exc:
            print(f"Top-up enrichment skipped {lead.brand_name}: {exc}")
            continue
        if is_duplicate(lead, duplicate_keys):
            continue
        if not _is_recent_sponsorship(lead, config.max_sponsor_age_days):
            continue
        if not is_qualified_outreach_contact(lead):
            print(f"Qualified contact required; skipped {lead.brand_name}")
            continue
        if lead.lead_score < config.min_lead_score:
            continue
        if not _is_queue_target_lead(lead):
            continue
        identity = _identity(lead)
        if not identity or identity in seen:
            continue
        seen.add(identity)
        candidates.append(lead)

    candidates.sort(
        key=lambda lead: (_priority_score(lead), lead.lead_score, lead.sponsored_date),
        reverse=True,
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
            "The delivery workflow will keep topping up throughout the day rather than padding weak leads."
        )


if __name__ == "__main__":
    run()
