from __future__ import annotations

import json
from pathlib import Path

from discord_notifier import DiscordNotifier
from outreach_contact_policy import is_qualified_outreach_contact
from run_sponsor_discovery_batch import _hydrate_creator_metrics
from run_sponsor_queue_dispatch import _is_dispatch_target_lead, _is_religion_sponsor
from run_sponsor_scan import _is_recent_sponsorship
from sponsor_config import load_sponsor_config
from sponsor_daily_policy import (
    DAILY_TARGET,
    choose_next_platform,
    delivery_counts,
    delivery_history_key,
    platform_key,
    total_delivered_today,
)
from sponsor_monday_client import SponsorMondayClient
from sponsor_models import SponsorLead
from sponsor_queue import (
    is_duplicate,
    load_duplicate_keys,
    load_sent_keys,
    mark_creator_used,
    mark_sent,
    save_sent_keys,
)
from youtube_sponsor_scanner import YouTubeSponsorScanner


QUEUE_PATH = Path("data/sponsor_queue.json")
PENDING_PATH = Path("data/sponsor_delivery_pending.json")


def _load_queue_raw() -> list[SponsorLead]:
    if not QUEUE_PATH.exists():
        return []
    try:
        raw = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    leads = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            leads.append(SponsorLead(**item))
        except TypeError:
            continue
    return leads


def _save_queue_raw(queue: list[SponsorLead]) -> None:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_PATH.write_text(
        json.dumps([lead.as_dict() for lead in queue], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _load_pending() -> dict:
    if not PENDING_PATH.exists():
        return {}
    try:
        raw = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_pending(payload: dict) -> None:
    PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    PENDING_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _same_lead(a: SponsorLead, b: SponsorLead) -> bool:
    return bool(
        (a.sponsorship_key and a.sponsorship_key == b.sponsorship_key)
        or (a.brand_key and a.brand_key == b.brand_key)
        or (a.brand_domain and a.brand_domain.lower() == b.brand_domain.lower())
        or (a.brand_name and a.brand_name.lower() == b.brand_name.lower())
    )


def _remove_matching(queue: list[SponsorLead], lead: SponsorLead) -> list[SponsorLead]:
    return [item for item in queue if not _same_lead(item, lead)]


def _complete_delivery(lead: SponsorLead, queue: list[SponsorLead], sent_keys: set[str]) -> list[SponsorLead]:
    mark_sent(lead, sent_keys)
    mark_creator_used(lead, sent_keys)
    sent_keys.add(delivery_history_key(lead))
    save_sent_keys(sent_keys)
    queue = _remove_matching(queue, lead)
    _save_queue_raw(queue)
    _save_pending({})
    return queue


def _select_next(queue: list[SponsorLead], sent_keys: set[str]) -> SponsorLead | None:
    if not queue:
        return None
    available = {platform_key(lead.source_platform) for lead in queue}
    desired = choose_next_platform(sent_keys, available)
    for lead in queue:
        if platform_key(lead.source_platform) == desired:
            return lead
    return queue[0]


def run() -> None:
    config = load_sponsor_config()
    monday = SponsorMondayClient(config.monday_token, config.monday_board_id, config.monday_group_id)
    discord = DiscordNotifier(config.discord_webhook_url)
    youtube = YouTubeSponsorScanner(config.youtube_api_key, config.search_region, config.search_language)
    queue = _load_queue_raw()
    sent_keys = load_sent_keys()

    if total_delivered_today(sent_keys) >= DAILY_TARGET:
        counts = delivery_counts(sent_keys)
        print(
            f"DAILY_SPONSOR_TARGET_MET: {total_delivered_today(sent_keys)}/{DAILY_TARGET}; "
            f"YouTube={counts.get('youtube',0)}, TikTok={counts.get('tiktok',0)}, "
            f"Instagram={counts.get('instagram',0)}."
        )
        return

    # Resume a transaction where Monday succeeded but Discord failed. This keeps Monday
    # dedupe safe while ensuring every verified sponsor eventually reaches BOTH systems.
    pending = _load_pending()
    if pending.get("lead"):
        try:
            lead = SponsorLead(**pending["lead"])
        except TypeError:
            _save_pending({})
        else:
            discord.send_new_lead(lead)
            queue = _complete_delivery(lead, queue, sent_keys)
            counts = delivery_counts(sent_keys)
            print(
                f"DAILY_SPONSOR_DISPATCH: resumed {lead.brand_name}; "
                f"today={sum(counts.values())}/{DAILY_TARGET}; {dict(counts)}"
            )
            return

    skipped = 0
    while queue:
        duplicate_keys = load_duplicate_keys()
        lead = _select_next(queue, sent_keys)
        if lead is None:
            break

        if (lead.source_platform or "").strip().lower() == "youtube":
            _hydrate_creator_metrics([lead], youtube)

        reject_reason = ""
        if _is_religion_sponsor(lead):
            reject_reason = "religion policy"
        elif is_duplicate(lead, duplicate_keys):
            reject_reason = "permanent duplicate/blocklist"
        elif not _is_recent_sponsorship(lead, config.max_sponsor_age_days):
            reject_reason = "stale evidence"
        elif not is_qualified_outreach_contact(lead):
            reject_reason = "unqualified outreach contact"
        elif lead.lead_score < config.min_lead_score:
            reject_reason = "lead score"
        elif not _is_dispatch_target_lead(lead):
            reject_reason = "category policy"

        if reject_reason:
            skipped += 1
            print(f"Daily dispatch skipped {lead.brand_name}: {reject_reason}")
            queue = _remove_matching(queue, lead)
            _save_queue_raw(queue)
            continue

        # Monday first, then checkpoint, then Discord. The sponsor is marked sent only
        # after BOTH destinations succeed.
        result = monday.create_lead(lead)
        item = result.get("data", {}).get("create_item", {})
        item_id = str(item.get("id", ""))
        _save_pending(
            {
                "stage": "monday_created",
                "monday_item_id": item_id,
                "lead": lead.as_dict(),
            }
        )

        try:
            discord.send_new_lead(lead)
        except Exception as exc:
            _save_queue_raw(queue)
            save_sent_keys(sent_keys)
            raise RuntimeError(
                f"Discord failed after Monday item {item_id or '?'} for {lead.brand_name}; "
                "pending checkpoint preserved for retry"
            ) from exc

        queue = _complete_delivery(lead, queue, sent_keys)
        counts = delivery_counts(sent_keys)
        print(
            f"DAILY_SPONSOR_DISPATCH: delivered {lead.brand_name} via {lead.source_platform}; "
            f"Monday={item_id or '?'}; today={sum(counts.values())}/{DAILY_TARGET}; "
            f"YouTube={counts.get('youtube',0)}, TikTok={counts.get('tiktok',0)}, "
            f"Instagram={counts.get('instagram',0)}; skipped={skipped}."
        )
        return

    print(f"DAILY_SPONSOR_QUEUE_EMPTY: no deliverable sponsor found; skipped={skipped}.")


if __name__ == "__main__":
    run()
