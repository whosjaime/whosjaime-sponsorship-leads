from __future__ import annotations

from discord_notifier import DiscordNotifier
from run_sponsor_discovery_batch import _hydrate_creator_metrics, _is_beauty_lead, _is_music_lead
from run_sponsor_scan import _is_recent_sponsorship, _is_target_lead
from sponsor_config import load_sponsor_config
from sponsor_monday_client import SponsorMondayClient
from sponsor_queue import (
    is_duplicate,
    load_duplicate_keys,
    load_queue,
    load_sent_keys,
    mark_sent,
    save_queue,
    save_sent_keys,
)
from youtube_sponsor_scanner import YouTubeSponsorScanner


def _is_dispatch_target_lead(lead) -> bool:
    return _is_target_lead(lead) or _is_beauty_lead(lead) or _is_music_lead(lead)


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
    last_error: Exception | None = None

    while queue:
        lead = queue.pop(0)

        # GitHub is the duplicate source of truth. This runs before YouTube hydration,
        # Monday API calls, or Discord so duplicate brands cost nothing and never post.
        if is_duplicate(lead, duplicate_keys):
            skipped += 1
            print(f"GitHub duplicate/blocklist skipped before delivery: {lead.brand_name}")
            continue

        _hydrate_creator_metrics([lead], youtube)

        # Hydration/enrichment can reveal stronger identity data, so check GitHub again.
        if is_duplicate(lead, duplicate_keys):
            skipped += 1
            print(f"GitHub duplicate skipped after creator hydration: {lead.brand_name}")
            continue
        if not _is_recent_sponsorship(lead, config.max_sponsor_age_days):
            skipped += 1
            continue
        if not lead.contact_email:
            skipped += 1
            continue
        if lead.lead_score < config.min_lead_score:
            skipped += 1
            continue
        if not _is_dispatch_target_lead(lead):
            skipped += 1
            continue

        # Monday is now only the destination. It is not queried to decide duplicates.
        try:
            result = monday.create_lead(lead)
            item = result.get("data", {}).get("create_item", {})
            print(
                f"Created queued sponsor lead: {lead.brand_name} / "
                f"monday {item.get('id', '?')} / score {lead.lead_score} / "
                f"creator subscribers {lead.creator_subscribers or 0:,}"
            )
            created = 1

            # The successful Monday create is the point of no return. Record it locally
            # before Discord so a Discord failure/retry can never resend the sponsor.
            mark_sent(lead, sent_keys)
            duplicate_keys.update(sent_keys)
            save_sent_keys(sent_keys)
        except Exception as exc:
            last_error = exc
            print(f"WARNING: monday create failed for {lead.brand_name}: {exc}")
            queue.insert(0, lead)
            break

        try:
            discord.send_new_lead(lead)
        except Exception as exc:
            last_error = exc
            print(f"WARNING: Discord new lead notification failed for {lead.brand_name}: {exc}")
        break

    save_queue(queue)
    save_sent_keys(sent_keys)
    print(
        f"SPONSOR_QUEUE_DISPATCH: {created} created, {skipped} duplicate/stale/rejected removed, "
        f"{len(queue)} remaining, {len(sent_keys)} GitHub sent keys."
    )

    if last_error is not None:
        raise RuntimeError(str(last_error))


if __name__ == "__main__":
    run()
