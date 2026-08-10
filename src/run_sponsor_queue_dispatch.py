from __future__ import annotations

from discord_notifier import DiscordNotifier
from run_sponsor_discovery_batch import _hydrate_creator_metrics, _is_queue_target_lead
from run_sponsor_scan import _blocked, _is_recent_sponsorship
from sponsor_config import load_sponsor_config
from sponsor_monday_client import SponsorMondayClient
from sponsor_queue import load_queue, save_queue
from youtube_sponsor_scanner import YouTubeSponsorScanner


def run() -> None:
    config = load_sponsor_config()
    monday = SponsorMondayClient(config.monday_token, config.monday_board_id, config.monday_group_id)
    discord = DiscordNotifier(config.discord_webhook_url)
    youtube = YouTubeSponsorScanner(config.youtube_api_key, config.search_region, config.search_language)
    queue = load_queue()
    index = monday.load_existing_index()

    skipped = 0
    created = 0
    last_error: Exception | None = None

    while queue:
        lead = queue.pop(0)

        # Last-mile safety net: old queue items or externally researched records may
        # still have a zero/unknown creator subscriber count. Hydrate the sponsored
        # video's creator before Monday and Discord see the lead.
        _hydrate_creator_metrics([lead], youtube)

        # Every delivery gets the production gates again in case Monday changed after
        # the daily discovery batch or a queued sponsorship aged out.
        if not _is_recent_sponsorship(lead, config.max_sponsor_age_days):
            skipped += 1
            continue
        if not lead.contact_email:
            skipped += 1
            continue
        if lead.lead_score < config.min_lead_score:
            skipped += 1
            continue
        if not _is_queue_target_lead(lead):
            skipped += 1
            continue
        if _blocked(index, lead):
            skipped += 1
            continue

        try:
            result = monday.create_lead(lead)
            item = result.get("data", {}).get("create_item", {})
            print(
                f"Created queued sponsor lead: {lead.brand_name} / "
                f"monday {item.get('id', '?')} / score {lead.lead_score} / "
                f"creator subscribers {lead.creator_subscribers or 0:,}"
            )
            created = 1
            index.add(lead)
        except Exception as exc:
            last_error = exc
            print(f"WARNING: monday create failed for {lead.brand_name}: {exc}")
            # Keep the candidate at the front so a transient Monday failure can retry.
            queue.insert(0, lead)
            break

        # The lead is already in Monday at this point, so never put it back into the
        # queue if Discord fails; doing so could create duplicate outreach later.
        try:
            discord.send_new_lead(lead)
        except Exception as exc:
            last_error = exc
            print(f"WARNING: Discord new lead notification failed for {lead.brand_name}: {exc}")
        break

    save_queue(queue)
    print(
        f"SPONSOR_QUEUE_DISPATCH: {created} created, {skipped} stale/duplicate/rejected removed, "
        f"{len(queue)} remaining."
    )

    if last_error is not None:
        raise RuntimeError(str(last_error))


if __name__ == "__main__":
    run()
