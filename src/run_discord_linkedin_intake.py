from __future__ import annotations

import json
import os

from brand_enrichment import BrandEnricher
from discord_linkedin_intake import DiscordLinkedInClient, candidate_to_lead, parse_linkedin_discord_message
from discord_notifier import DiscordNotifier
from sponsor_dedupe import make_brand_key, make_sponsorship_key, normalize_domain
from sponsor_monday_client import SponsorMondayClient, WRITABLE_FIELDS
from sponsor_queue import (
    is_duplicate,
    load_duplicate_keys,
    load_sent_keys,
    mark_sent,
    save_sent_keys,
)

DEFAULT_BOARD_ID = 18424367188
DEFAULT_GROUP_ID = "topics"


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing LinkedIn Discord intake configuration: {name}")
    return value


def _monday_token() -> str:
    value = (
        os.getenv("SPONSOR_MONDAY_TOKEN", "").strip()
        or os.getenv("SPONSOR_MONDAY_API_KEY", "").strip()
    )
    if not value:
        raise ValueError("Missing LinkedIn Discord intake configuration: SPONSOR_MONDAY_TOKEN")
    return value


def _enrich(lead, enricher: BrandEnricher):
    enrichment = enricher.enrich(lead.brand_domain)
    if enrichment.get("domain"):
        lead.brand_domain = normalize_domain(enrichment["domain"])
    lead.contact_email = enrichment.get("contact_email", "")
    lead.email_type = enrichment.get("email_type", "")
    lead.contact_source = enrichment.get("contact_source", "")
    lead.sponsor_category = enrichment.get("category", "Other")
    lead.sponsor_subcategory = enrichment.get("subcategory", "")
    lead.brand_key = make_brand_key(lead.brand_name, lead.brand_domain)
    lead.sponsorship_key = make_sponsorship_key(
        "LinkedIn", lead.video_id, lead.brand_name, lead.brand_domain
    )
    return lead


def _create_manual_lead(monday: SponsorMondayClient, lead):
    columns, _ = monday.load_schema()
    raw = {
        "outreach_status": "New Lead",
        "brand_domain": lead.brand_domain,
        "contact_email": lead.contact_email,
        "source_platform": lead.source_platform,
        "creator_name": lead.creator_name,
        "creator_url": lead.creator_url,
        "creator_subscribers": lead.creator_subscribers,
        "video_url": lead.video_url,
        "sponsored_date": lead.sponsored_date,
        "date_found": lead.date_found,
    }

    values = {}
    for field in WRITABLE_FIELDS:
        column = columns[field]
        formatted = monday._format_value(column, field, raw.get(field), lead)
        if formatted not in (None, "", {}):
            values[column.id] = formatted

    mutation = """
    mutation CreateManualSponsorLead(
      $board_id: ID!,
      $group_id: String,
      $item_name: String!,
      $column_values: JSON!
    ) {
      create_item(
        board_id: $board_id,
        group_id: $group_id,
        item_name: $item_name,
        column_values: $column_values,
        create_labels_if_missing: true
      ) { id name }
    }
    """
    return monday._request(
        mutation,
        {
            "board_id": monday.board_id,
            "group_id": monday.resolved_group_id() or None,
            "item_name": lead.brand_name,
            "column_values": json.dumps(values),
        },
    )


def run() -> None:
    discord_bot = DiscordLinkedInClient(
        _required("DISCORD_BOT_TOKEN"),
        _required("DISCORD_LINKEDIN_CHANNEL_ID"),
    )
    monday = SponsorMondayClient(
        _monday_token(),
        int(os.getenv("SPONSOR_MONDAY_BOARD_ID", "") or DEFAULT_BOARD_ID),
        os.getenv("SPONSOR_MONDAY_GROUP_ID", DEFAULT_GROUP_ID).strip() or DEFAULT_GROUP_ID,
    )
    notifier = DiscordNotifier(_required("DISCORD_WEBHOOK_URL"))
    enricher = BrandEnricher()

    sent_keys = load_sent_keys()
    duplicate_keys = load_duplicate_keys()
    messages = discord_bot.fetch_recent_messages(limit=50)
    processed = 0
    created = 0
    unresolved = 0
    duplicates = 0
    errors: list[str] = []

    for message in reversed(messages):
        if (message.get("author") or {}).get("bot"):
            continue
        if discord_bot.already_handled(message):
            continue

        candidate = parse_linkedin_discord_message(message)
        if candidate is None:
            continue
        processed += 1

        if not candidate.brand_name or not candidate.brand_domain:
            unresolved += 1
            try:
                discord_bot.add_reaction(candidate.message_id, "⚠️")
                discord_bot.reply(
                    candidate.message_id,
                    "⚠️ I found the LinkedIn post, but Discord's preview didn't expose enough "
                    "to safely identify the sponsor website. Repost the link with "
                    "`Website: brand.com` (and optionally `Brand: Brand Name`). I won't scrape "
                    "LinkedIn or guess a company domain.",
                )
            except Exception as exc:
                errors.append(f"Could not mark unresolved LinkedIn message {candidate.message_id}: {exc}")
            continue

        lead = candidate_to_lead(candidate)
        lead.source_platform = os.getenv("SPONSOR_LINKEDIN_SOURCE_LABEL", "LinkedIn").strip() or "LinkedIn"

        # GitHub duplicate gate comes before website research or Monday.
        if is_duplicate(lead, duplicate_keys):
            duplicates += 1
            try:
                discord_bot.add_reaction(candidate.message_id, "🔁")
            except Exception as exc:
                errors.append(f"Could not mark duplicate LinkedIn message {candidate.message_id}: {exc}")
            continue

        try:
            lead = _enrich(lead, enricher)
        except Exception as exc:
            errors.append(f"Brand enrichment warning for {lead.brand_name}: {exc}")

        # Check again after canonical domain/email enrichment.
        if is_duplicate(lead, duplicate_keys):
            duplicates += 1
            try:
                discord_bot.add_reaction(candidate.message_id, "🔁")
            except Exception as exc:
                errors.append(f"Could not mark duplicate LinkedIn message {candidate.message_id}: {exc}")
            continue

        try:
            result = _create_manual_lead(monday, lead)
            item = result.get("data", {}).get("create_item", {})
            print(
                f"Created manual LinkedIn sponsor lead: {lead.brand_name} / "
                f"monday {item.get('id', '?')} / email {lead.contact_email or 'not found'}"
            )
            created += 1

            # Successful Monday create immediately becomes permanent GitHub duplicate history.
            mark_sent(lead, sent_keys)
            duplicate_keys.update(sent_keys)
            save_sent_keys(sent_keys)
        except Exception as exc:
            errors.append(f"Monday create failed for LinkedIn lead {lead.brand_name}: {exc}")
            continue

        try:
            notifier.send_new_lead(lead)
        except Exception as exc:
            errors.append(f"Discord lead alert failed for {lead.brand_name}: {exc}")

        try:
            discord_bot.add_reaction(candidate.message_id, "✅")
        except Exception as exc:
            errors.append(f"Could not mark successful LinkedIn message {candidate.message_id}: {exc}")

    save_sent_keys(sent_keys)
    print(
        f"LinkedIn Discord intake complete: {processed} submitted post(s), {created} created, "
        f"{duplicates} GitHub duplicate/blocked, {unresolved} need website hint, {len(errors)} warning(s)."
    )
    for error in errors[:20]:
        print(f"WARNING: {error}")


if __name__ == "__main__":
    run()
