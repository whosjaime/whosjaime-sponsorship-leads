from __future__ import annotations

import json
from pathlib import Path

from discord_notifier import DiscordNotifier
from run_sponsor_discovery_batch import _hydrate_creator_metrics, _is_beauty_lead, _is_music_lead
from run_sponsor_scan import _is_recent_sponsorship, _is_target_lead
from sponsor_config import load_sponsor_config
from sponsor_monday_client import SponsorMondayClient
from sponsor_models import SponsorLead
from sponsor_queue import (
    is_duplicate,
    load_duplicate_keys,
    load_queue,
    load_sent_keys,
    mark_creator_used,
    mark_sent,
    save_queue,
    save_sent_keys,
)
from youtube_sponsor_scanner import YouTubeSponsorScanner


PENDING_PATH = Path("data/sponsor_delivery_pending.json")

RELIGION_BLOCK_TERMS = (
    "religion", "religious", "ffrf", "freedom from religion",
    "church", "ministry", "ministries", "bible", "biblical",
    "christian", "christianity", "catholic", "evangelical",
    "islamic", "muslim", "mosque", "jewish", "judaism", "synagogue",
    "atheist", "atheism", "mormon", "latter-day saints", "scientology",
)

DISALLOWED_DIGITAL_CATEGORIES = {
    "software / saas",
    "cybersecurity / vpn",
    "ai software",
    "developer tools",
    "web hosting",
    "cloud software",
}

APPROVED_SPONSOR_CATEGORIES = {
    "gaming",
    "consumer tech",
    "physical consumer tech",
    "food & beverage",
    "food/drink",
    "fashion",
    "home",
    "home & garden",
    "health & wellness",
    "wellness",
    "travel",
    "pet",
    "pets",
    "fragrance",
    "beauty",
    "music",
    "entertainment",
    "lifestyle",
    "sports",
    "fitness",
}

APPROVED_NONTECH_KEYWORDS = {
    "mattress", "sleep", "home", "furniture", "chair", "cookware", "kitchen",
    "food", "drink", "beverage", "snack", "coffee", "hydration", "supplement",
    "wellness", "fitness", "apparel", "clothing", "fashion", "shoes", "footwear",
    "travel", "hotel", "resort", "luggage", "pet", "dog", "cat", "fragrance",
    "perfume", "cologne", "beauty", "skincare", "makeup", "sports", "outdoor",
}


def _is_religion_sponsor(lead) -> bool:
    text = " ".join(
        [
            lead.brand_name or "",
            lead.brand_domain or "",
            lead.sponsor_category or "",
            lead.sponsor_subcategory or "",
            lead.evidence or "",
        ]
    ).lower()
    return any(term in text for term in RELIGION_BLOCK_TERMS)


def _is_dispatch_target_lead(lead) -> bool:
    if _is_religion_sponsor(lead):
        return False

    category = (lead.sponsor_category or "").strip().lower()
    text = " ".join(
        [
            lead.brand_name or "",
            lead.brand_domain or "",
            lead.sponsor_category or "",
            lead.sponsor_subcategory or "",
            lead.evidence or "",
        ]
    ).lower()

    # Permanent rule: digital-tech services never dispatch automatically.
    if category in DISALLOWED_DIGITAL_CATEGORIES:
        return False
    if any(term in text for term in (" vpn ", " saas ", "developer tool", "coding tool", "web hosting", "password manager")):
        return False

    # Keep the original high-priority gaming/food/physical-tech gate, but also allow
    # the non-tech sponsor categories explicitly approved for the research pipeline.
    if _is_target_lead(lead) or _is_beauty_lead(lead) or _is_music_lead(lead):
        return True
    if category in APPROVED_SPONSOR_CATEGORIES:
        return True
    return any(keyword in text for keyword in APPROVED_NONTECH_KEYWORDS)


def _load_pending() -> dict:
    if not PENDING_PATH.exists():
        return {}
    try:
        raw = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
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
    )


def _remove_matching(queue: list[SponsorLead], lead: SponsorLead) -> list[SponsorLead]:
    removed = False
    kept: list[SponsorLead] = []
    for item in queue:
        if not removed and _same_lead(item, lead):
            removed = True
            continue
        kept.append(item)
    return kept


def _complete_delivery(lead: SponsorLead, queue: list[SponsorLead], sent_keys: set[str]) -> list[SponsorLead]:
    mark_sent(lead, sent_keys)
    mark_creator_used(lead, sent_keys)
    save_sent_keys(sent_keys)
    queue = _remove_matching(queue, lead)
    save_queue(queue)
    _save_pending({})
    return queue


def run() -> None:
    config = load_sponsor_config()
    monday = SponsorMondayClient(config.monday_token, config.monday_board_id, config.monday_group_id)
    discord = DiscordNotifier(config.discord_webhook_url)
    youtube = YouTubeSponsorScanner(config.youtube_api_key, config.search_region, config.search_language)
    queue = load_queue()
    sent_keys = load_sent_keys()
    duplicate_keys = load_duplicate_keys()

    skipped = 0
    created = 0

    # Resume a partial delivery safely. If Monday already succeeded on a previous run,
    # retry Discord only; do not create another Monday item.
    pending = _load_pending()
    if pending.get("lead"):
        try:
            lead = SponsorLead(**pending["lead"])
        except TypeError:
            _save_pending({})
        else:
            print(
                f"Resuming pending sponsor delivery after Monday success: {lead.brand_name} / "
                f"monday {pending.get('monday_item_id', '?')}"
            )
            try:
                discord.send_new_lead(lead)
            except Exception as exc:
                save_queue(queue)
                save_sent_keys(sent_keys)
                _save_pending(pending)
                raise RuntimeError(f"Discord retry failed for {lead.brand_name}: {exc}") from exc

            queue = _complete_delivery(lead, queue, sent_keys)
            print(
                f"SPONSOR_QUEUE_DISPATCH: 1 delivered from pending checkpoint, "
                f"{len(queue)} remaining, {len(sent_keys)} GitHub sent keys."
            )
            return

    while queue:
        lead = queue[0]

        # Invalid or permanently blocked leads may be removed immediately because they
        # are not delivery candidates and should never be retried.
        if _is_religion_sponsor(lead):
            skipped += 1
            print(f"Religion-policy sponsor skipped before delivery: {lead.brand_name}")
            queue.pop(0)
            continue

        if is_duplicate(lead, duplicate_keys):
            skipped += 1
            print(f"GitHub duplicate/blocklist skipped before delivery: {lead.brand_name}")
            queue.pop(0)
            continue

        _hydrate_creator_metrics([lead], youtube)

        if _is_religion_sponsor(lead):
            skipped += 1
            print(f"Religion-policy sponsor skipped after hydration: {lead.brand_name}")
            queue.pop(0)
            continue
        if is_duplicate(lead, duplicate_keys):
            skipped += 1
            print(f"GitHub duplicate skipped after creator hydration: {lead.brand_name}")
            queue.pop(0)
            continue
        if not _is_recent_sponsorship(lead, config.max_sponsor_age_days):
            skipped += 1
            queue.pop(0)
            continue
        if not lead.contact_email:
            skipped += 1
            queue.pop(0)
            continue
        if lead.lead_score < config.min_lead_score:
            skipped += 1
            queue.pop(0)
            continue
        if not _is_dispatch_target_lead(lead):
            skipped += 1
            print(f"Approved-category gate skipped: {lead.brand_name} / {lead.sponsor_category}")
            queue.pop(0)
            continue

        # Delivery is transactional: keep the lead in queue until BOTH destinations
        # succeed. Monday success is checkpointed so a Discord retry does not create a
        # duplicate Monday item.
        try:
            result = monday.create_lead(lead)
            item = result.get("data", {}).get("create_item", {})
            item_id = str(item.get("id", ""))
            print(
                f"Created queued sponsor lead: {lead.brand_name} / "
                f"monday {item_id or '?'} / score {lead.lead_score} / "
                f"creator subscribers {lead.creator_subscribers or 0:,}"
            )
            created = 1
            _save_pending(
                {
                    "stage": "monday_created",
                    "monday_item_id": item_id,
                    "lead": lead.as_dict(),
                }
            )
        except Exception as exc:
            save_queue(queue)
            save_sent_keys(sent_keys)
            _save_pending({})
            raise RuntimeError(f"Monday create failed for {lead.brand_name}: {exc}") from exc

        try:
            discord.send_new_lead(lead)
        except Exception as exc:
            # Keep both queue and pending checkpoint intact. Next run retries Discord
            # only and will not create another Monday item.
            save_queue(queue)
            save_sent_keys(sent_keys)
            raise RuntimeError(f"Discord new lead notification failed for {lead.brand_name}: {exc}") from exc

        queue = _complete_delivery(lead, queue, sent_keys)
        duplicate_keys.update(sent_keys)
        break

    save_queue(queue)
    save_sent_keys(sent_keys)
    print(
        f"SPONSOR_QUEUE_DISPATCH: {created} delivered, {skipped} duplicate/stale/rejected removed, "
        f"{len(queue)} remaining, {len(sent_keys)} GitHub sent keys."
    )


if __name__ == "__main__":
    run()
