from __future__ import annotations

from datetime import date

from brand_enrichment import BrandEnricher
from creator_classifier import classify_creator
from discord_notifier import DiscordNotifier
from sponsor_config import load_sponsor_config
from sponsor_dedupe import ExistingSponsorIndex, make_brand_key, make_sponsorship_key, normalize_domain
from sponsor_detector import detect_sponsors, to_sponsor_lead
from sponsor_models import SponsorLead
from sponsor_monday_client import SponsorMondayClient
from youtube_sponsor_scanner import YouTubeSponsorScanner

LOOKBACK_WINDOWS_HOURS = [24, 72, 168]

# Priority targets, not hard filters. These win first when the hourly scanner
# chooses its single lead, but another qualified sponsor can still be used as fallback.
PRIORITY_SPONSOR_CATEGORIES = {
    "Gaming",
    "Consumer Tech",
    "Software / SaaS",
    "Cybersecurity / VPN",
    "Food & Beverage",
}
PRIORITY_CREATOR_GENRES = {"Gaming", "Tech", "Food"}
PRIORITY_BRAND_KEYWORDS = {
    "gaming", "game", "gamer", "esports",
    "tech", "software", "saas", "electronics", "audio", "headset", "keyboard",
    "microphone", "mic", "computer", "app", "vpn", "cybersecurity",
    "food", "drink", "beverage", "energy", "coffee", "snack", "meal", "soda",
}


def _score_lead(lead: SponsorLead) -> int:
    score = 0
    signals = set(lead.signals)
    if "explicit sponsor phrase" in signals:
        score += 35
    if lead.paid_product_placement:
        score += 25
    if "YouTube brand partner" in signals:
        score += 20
    if "ad/sponsored disclosure" in signals:
        score += 12
    if lead.brand_domain:
        score += 15
    if lead.contact_email:
        score += 15
    if lead.creator_genre and lead.creator_genre != "Other":
        score += 5
    if lead.sponsor_category and lead.sponsor_category != "Other":
        score += 3
    try:
        age_days = (date.today() - date.fromisoformat(lead.sponsored_date)).days
        if 0 <= age_days <= 7:
            score += 5
    except ValueError:
        pass
    return min(100, score)


def _priority_score(lead: SponsorLead) -> int:
    score = 0
    if lead.sponsor_category in PRIORITY_SPONSOR_CATEGORIES:
        score += 100
    if lead.creator_genre in PRIORITY_CREATOR_GENRES:
        score += 25

    text = " ".join(
        [
            lead.brand_name or "",
            lead.brand_domain or "",
            lead.sponsor_category or "",
            lead.sponsor_subcategory or "",
        ]
    ).lower()
    if any(keyword in text for keyword in PRIORITY_BRAND_KEYWORDS):
        score += 50
    return score


def _temperature(score: int) -> str:
    if score >= 90:
        return "Very Hot"
    if score >= 80:
        return "Hot"
    if score >= 70:
        return "Warm"
    return "Needs Review"


def _enrich_lead(lead: SponsorLead, enricher: BrandEnricher) -> SponsorLead:
    if lead.brand_domain:
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
            lead.source_platform,
            lead.video_id,
            lead.brand_name,
            lead.brand_domain,
        )
    lead.lead_score = _score_lead(lead)
    lead.lead_temperature = _temperature(lead.lead_score)
    return lead


def _blocked(index: ExistingSponsorIndex, lead: SponsorLead) -> bool:
    return index.is_duplicate_brand(lead) or index.is_duplicate_event(lead) or index.is_protected(lead)


def run() -> None:
    config = load_sponsor_config()
    monday = SponsorMondayClient(config.monday_token, config.monday_board_id, config.monday_group_id)
    youtube = YouTubeSponsorScanner(config.youtube_api_key, config.search_region, config.search_language)
    enricher = BrandEnricher()
    discord = DiscordNotifier(config.discord_webhook_url)

    # Gate 1: FULL monday scan before discovery. ExistingSponsorIndex is also
    # permanently seeded with the team's manual duplicate/blocklist.
    existing = monday.load_existing_index()
    candidates: dict[str, SponsorLead] = {}
    duplicate_count = 0
    rejected_count = 0
    scanned_video_ids: set[str] = set()
    errors: list[str] = []
    desired_pool = config.target_daily_leads

    if config.enable_instagram:
        errors.append("Instagram adapter is not active yet; YouTube ran normally.")
    if config.enable_tiktok:
        errors.append("TikTok adapter is not active yet; YouTube ran normally.")

    for lookback in LOOKBACK_WINDOWS_HOURS:
        print(f"Scanning YouTube sponsorships from the last {lookback} hours...")
        try:
            videos, channels = youtube.discover(lookback)
        except Exception as exc:
            errors.append(f"YouTube {lookback}h scan failed: {exc}")
            continue

        for video in videos:
            if video.video_id in scanned_video_ids:
                continue
            scanned_video_ids.add(video.video_id)
            creator = channels.get(video.channel_id)
            genre, tags = classify_creator(video, creator)

            for detection in detect_sponsors(video, channels):
                lead = to_sponsor_lead(video, creator, detection, genre, tags)
                try:
                    lead = _enrich_lead(lead, enricher)
                except Exception as exc:
                    errors.append(f"Enrichment warning for {lead.brand_name}: {exc}")
                    rejected_count += 1
                    continue

                # A usable public brand email is mandatory.
                if not lead.contact_email:
                    rejected_count += 1
                    print(f"Email required; skipped: {lead.brand_name}")
                    continue

                # Gate 2: checks both monday.com and the permanent blocklist.
                if _blocked(existing, lead):
                    duplicate_count += 1
                    print(f"Duplicate/blocked brand skipped: {lead.brand_name}")
                    continue

                if lead.lead_score < config.min_lead_score:
                    rejected_count += 1
                    continue

                identity = lead.brand_key or f"brand:{lead.brand_name.strip().lower()}"
                current = candidates.get(identity)
                if current is None or (
                    _priority_score(lead), lead.lead_score, lead.sponsored_date
                ) > (
                    _priority_score(current), current.lead_score, current.sponsored_date
                ):
                    candidates[identity] = lead

        # If we found a priority gaming/tech/food lead, there is no reason to
        # widen the lookback. If only non-priority leads exist, search farther
        # back before settling for the fallback.
        if len(candidates) >= desired_pool and any(_priority_score(lead) > 0 for lead in candidates.values()):
            break

    # Gate 3: FULL monday scan immediately before writes. The permanent
    # duplicate list is seeded here again too.
    final_index = monday.load_existing_index()
    ordered = sorted(
        candidates.values(),
        key=lambda x: (_priority_score(x), x.lead_score, x.sponsored_date),
        reverse=True,
    )
    created: list[SponsorLead] = []

    for lead in ordered:
        if len(created) >= config.target_daily_leads:
            break
        if _blocked(final_index, lead):
            duplicate_count += 1
            print(f"Final duplicate/blocked gate skipped: {lead.brand_name}")
            continue

        try:
            result = monday.create_lead(lead)
            item = result.get("data", {}).get("create_item", {})
            print(
                f"Created sponsor lead: {lead.brand_name} / "
                f"monday {item.get('id', '?')} / score {lead.lead_score} / "
                f"priority {_priority_score(lead)}"
            )
            created.append(lead)
            final_index.add(lead)
        except Exception as exc:
            errors.append(f"monday create failed for {lead.brand_name}: {exc}")
            continue

        # Discord fires only after Monday confirms the NEW brand was created.
        try:
            discord.send_new_lead(lead)
        except Exception as exc:
            errors.append(f"Discord new lead notification failed for {lead.brand_name}: {exc}")

    print(
        f"Sponsor scan complete: {len(created)}/{config.target_daily_leads} new leads, "
        f"{duplicate_count} duplicates/blocked brands, {rejected_count} rejected, "
        f"{len(scanned_video_ids)} videos scanned."
    )

    if errors:
        print(f"Scanner completed with {len(errors)} warning(s).")
        for error in errors[:10]:
            print(f"WARNING: {error}")

    if len(created) < config.target_daily_leads:
        print(
            "Qualified unique inventory was below this run's target. "
            "The scanner did not lower quality, accept missing-email leads, "
            "or re-import duplicates."
        )


if __name__ == "__main__":
    run()
