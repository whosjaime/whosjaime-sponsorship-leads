from __future__ import annotations

import os

from brand_enrichment import BrandEnricher
from discord_linkedin_intake import DiscordLinkedInClient, candidate_to_lead, parse_linkedin_discord_message
from discord_notifier import DiscordNotifier
from sponsor_dedupe import make_brand_key, make_sponsorship_key, normalize_domain
from sponsor_monday_client import SponsorMondayClient

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

    existing = monday.load_existing_index()
    messages = discord_bot.fetch_recent_messages(limit=50)
    processed = 0
    created = 0
    unresolved = 0
    duplicates = 0
    errors: list[str] = []

    # Discord returns newest first. Process oldest first so multiple manual submissions
    # preserve the order they were dropped into the intake channel.
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
        try:
            lead = _enrich(lead, enricher)
        except Exception as exc:
            # A manually selected LinkedIn lead can still enter Monday with the sponsor
            # identity/evidence even when its website blocks automated contact research.
            errors.append(f"Brand enrichment warning for {lead.brand_name}: {exc}")

        # Manual intake still NEVER bypasses the permanent do-not-reach-out list or
        # existing Monday brand identity. ExistingSponsorIndex is seeded with both.
        if existing.is_duplicate_brand(lead) or existing.is_protected(lead):
            duplicates += 1
            try:
                discord_bot.add_reaction(candidate.message_id, "🔁")
            except Exception as exc:
                errors.append(f"Could not mark duplicate LinkedIn message {candidate.message_id}: {exc}")
            continue

        try:
            result = monday.create_lead(lead)
            item = result.get("data", {}).get("create_item", {})
            print(
                f"Created manual LinkedIn sponsor lead: {lead.brand_name} / "
                f"monday {item.get('id', '?')} / email {lead.contact_email or 'not found'}"
            )
            existing.add(lead, protected=True)
            created += 1
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

    print(
        f"LinkedIn Discord intake complete: {processed} submitted post(s), {created} created, "
        f"{duplicates} duplicate/blocked, {unresolved} need website hint, {len(errors)} warning(s)."
    )
    for error in errors[:20]:
        print(f"WARNING: {error}")


if __name__ == "__main__":
    run()
