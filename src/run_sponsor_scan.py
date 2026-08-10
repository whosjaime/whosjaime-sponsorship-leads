from __future__ import annotations

from datetime import date

from brand_enrichment import BrandEnricher
from creatomap_active_sponsors import CreatomapActiveSponsorSource
from creatordb_active_sponsors import CreatorDBActiveSponsorSource
from creator_classifier import classify_creator
from discord_notifier import DiscordNotifier
from sponsor_config import load_sponsor_config
from sponsor_dedupe import ExistingSponsorIndex, make_brand_key, make_sponsorship_key, normalize_domain
from sponsor_detector import detect_sponsors, to_sponsor_lead
from sponsor_models import SponsorLead
from sponsor_monday_client import SponsorMondayClient
from youtube_sponsor_scanner import YouTubeSponsorScanner

LOOKBACK_WINDOWS_HOURS = [24, 72, 168]

# Hard target filter. The sponsor itself must fit one of these buckets.
TARGET_SPONSOR_CATEGORIES = {
    "Gaming",
    "Consumer Tech",
    "Software / SaaS",
    "Cybersecurity / VPN",
    "Food & Beverage",
}

TARGET_BRAND_KEYWORDS = {
    "gaming", "gamer", "esports", "gaming gear", "gaming peripheral", "controller",
    "software", "saas", "cloud", "web hosting", "website builder", "developer tool",
    "cybersecurity", "vpn", "password manager", "online privacy", "identity protection",
    "electronics", "headset", "headphones", "keyboard", "microphone", "webcam", "speaker",
    "computer hardware", "gaming mouse", "monitor", "gadget",
    "food", "drink", "beverage", "energy drink", "coffee", "snack", "meal", "soda",
    "sparkling water", "hydration",
}

# Explicitly bad fits for this creator roster.
EXCLUDED_SPONSOR_KEYWORDS = {
    "festival", "music festival", "concert festival", "concert promoter", "event production",
}


def _sponsorship_age_days(lead: SponsorLead) -> int | None:
    try:
        sponsored = date.fromisoformat((lead.sponsored_date or "")[:10])
    except (TypeError, ValueError):
        return None
    return (date.today() - sponsored).days


def _is_recent_sponsorship(lead: SponsorLead, max_age_days: int = 30) -> bool:
    """Only active/recent sponsorship evidence is eligible for outreach."""
    age_days = _sponsorship_age_days(lead)
    if age_days is None:
        return False
    return 0 <= age_days <= max(1, max_age_days)


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

    # External indexes are used only as brand-activity sources. These signals mean
    # a specific recent sponsored YouTube video was attributed to the brand.
    if "Creatomap recent sponsorship" in signals:
        score += 35
    if "Creatomap video evidence" in signals:
        score += 25
    if "CreatorDB sponsored content" in signals:
        score += 35
    if "partnered brand attribution" in signals:
        score += 25

    if lead.brand_domain:
        score += 15
    if lead.contact_email:
        score += 15
    if lead.sponsor_category and lead.sponsor_category != "Other":
        score += 3

    age_days = _sponsorship_age_days(lead)
    if age_days is not None:
        if 0 <= age_days <= 7:
            score += 15
        elif age_days <= 30:
            score += 8

    return min(100, score)


def _target_text(lead: SponsorLead) -> str:
    return " ".join(
        [
            lead.brand_name or "",
            lead.brand_domain or "",
            lead.sponsor_category or "",
            lead.sponsor_subcategory or "",
        ]
    ).lower()


def _is_target_lead(lead: SponsorLead) -> bool:
    """Only allow Gaming, Tech, or Food/Drink sponsors into Monday/Discord."""
    text = _target_text(lead)
    if any(keyword in text for keyword in EXCLUDED_SPONSOR_KEYWORDS):
        return False
    if lead.sponsor_category in TARGET_SPONSOR_CATEGORIES:
        return True
    return any(keyword in text for keyword in TARGET_BRAND_KEYWORDS)


def _priority_score(lead: SponsorLead) -> int:
    """Ranks good target sponsors; it does not make a non-target sponsor eligible."""
    score = 0
    if lead.sponsor_category in TARGET_SPONSOR_CATEGORIES:
        score += 100
    text = _target_text(lead)
    if any(keyword in text for keyword in TARGET_BRAND_KEYWORDS):
        score += 50

    age_days = _sponsorship_age_days(lead)
    if age_days is not None:
        if 0 <= age_days <= 7:
            score += 30
        elif age_days <= 30:
            score += 15
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

    # No account, API key, or approval is required for Creatomap. It publishes a public
    # JSON API specifically for sponsor/brand/creator sponsorship data.
    creatomap = CreatomapActiveSponsorSource()

    # CreatorDB remains optional extra coverage if access is ever granted, but launch
    # does not depend on it.
    creatordb = (
        CreatorDBActiveSponsorSource(config.creatordb_api_key, config.creatordb_page_size)
        if config.creatordb_api_key
        else None
    )
    enricher = BrandEnricher()
    discord = DiscordNotifier(config.discord_webhook_url)

    # Gate 1: FULL monday scan before discovery. ExistingSponsorIndex is also
    # permanently seeded with the team's manual duplicate/blocklist.
    existing = monday.load_existing_index()
    candidates: dict[str, SponsorLead] = {}
    duplicate_count = 0
    rejected_count = 0
    scanned_video_ids: set[str] = set()
    creatomap_content_count = 0
    creatordb_content_count = 0
    errors: list[str] = []
    desired_pool = config.target_daily_leads

    if config.enable_instagram:
        errors.append("Instagram adapter is not active yet; YouTube ran normally.")
    if config.enable_tiktok:
        errors.append("TikTok adapter is not active yet; YouTube ran normally.")

    def consider_lead(lead: SponsorLead, discovery_source: str) -> None:
        nonlocal duplicate_count, rejected_count

        try:
            lead = _enrich_lead(lead, enricher)
        except Exception as exc:
            errors.append(f"Enrichment warning for {lead.brand_name}: {exc}")
            rejected_count += 1
            return

        if not _is_recent_sponsorship(lead, config.max_sponsor_age_days):
            rejected_count += 1
            print(
                f"Stale/undated sponsorship skipped: {lead.brand_name} / "
                f"{lead.sponsored_date or 'unknown date'}"
            )
            return

        # A usable public brand email is mandatory.
        if not lead.contact_email:
            rejected_count += 1
            print(f"Email required; skipped: {lead.brand_name}")
            return

        # Gate 2: checks both monday.com and the permanent blocklist.
        if _blocked(existing, lead):
            duplicate_count += 1
            print(f"Duplicate/blocked brand skipped: {lead.brand_name}")
            return

        if lead.lead_score < config.min_lead_score:
            rejected_count += 1
            print(
                f"Below score threshold; skipped: {lead.brand_name} / "
                f"{lead.lead_score} < {config.min_lead_score}"
            )
            return

        # Hard niche gate: no festivals, random entertainment, beauty, fashion,
        # finance, etc. The sponsor itself must fit Gaming, Tech, or Food/Drink.
        if not _is_target_lead(lead):
            rejected_count += 1
            print(
                f"Outside target niches; skipped: {lead.brand_name} "
                f"({lead.sponsor_category or 'Other'})"
            )
            return

        identity = lead.brand_key or f"brand:{lead.brand_name.strip().lower()}"
        current = candidates.get(identity)
        if current is None or (
            _priority_score(lead), lead.lead_score, lead.sponsored_date
        ) > (
            _priority_score(current), current.lead_score, current.sponsored_date
        ):
            candidates[identity] = lead
            print(
                f"Qualified active sponsor candidate via {discovery_source}: "
                f"{lead.brand_name} / {lead.sponsored_date}"
            )

    # Source 1: YouTube's own most recent paid-placement / sponsorship signals.
    # We start with 24h, then use the zero-wait Creatomap API before widening the
    # native YouTube lookback. This improves coverage without requiring another key.
    for window_index, lookback in enumerate(LOOKBACK_WINDOWS_HOURS):
        print(f"Scanning YouTube sponsorships from the last {lookback} hours...")
        try:
            videos, channels = youtube.discover(lookback)
        except Exception as exc:
            errors.append(f"YouTube {lookback}h scan failed: {exc}")
            videos, channels = [], {}

        for video in videos:
            if video.video_id in scanned_video_ids:
                continue
            scanned_video_ids.add(video.video_id)
            creator = channels.get(video.channel_id)
            genre, tags = classify_creator(video, creator)

            for detection in detect_sponsors(video, channels):
                lead = to_sponsor_lead(video, creator, detection, genre, tags)
                consider_lead(lead, "YouTube")

        if len(candidates) >= desired_pool:
            break

        if window_index == 0:
            # Source 2: Creatomap public API. No approval, login or key required.
            print(
                "YouTube inventory was below target; checking Creatomap public API for "
                f"recent sponsorship video evidence from the last {config.max_sponsor_age_days} days..."
            )
            try:
                creatomap_leads = creatomap.discover(config.max_sponsor_age_days)
                creatomap_content_count = len(creatomap_leads)
            except Exception as exc:
                errors.append(f"Creatomap active sponsor scan failed: {exc}")
                creatomap_leads = []

            for lead in creatomap_leads:
                consider_lead(lead, "Creatomap")
                if len(candidates) >= desired_pool:
                    break

            if len(candidates) >= desired_pool:
                break

            # Source 3: CreatorDB only if a key happens to be available later.
            if creatordb is not None:
                print(
                    "Creatomap inventory was below target; checking optional CreatorDB "
                    f"coverage from the last {config.max_sponsor_age_days} days..."
                )
                try:
                    creatordb_leads = creatordb.discover(config.max_sponsor_age_days)
                    creatordb_content_count = len(creatordb_leads)
                except Exception as exc:
                    errors.append(f"CreatorDB active sponsor scan failed: {exc}")
                    creatordb_leads = []

                for lead in creatordb_leads:
                    consider_lead(lead, "CreatorDB")
                    if len(candidates) >= desired_pool:
                        break

                if len(candidates) >= desired_pool:
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
        if not _is_recent_sponsorship(lead, config.max_sponsor_age_days):
            rejected_count += 1
            print(f"Final freshness gate skipped: {lead.brand_name}")
            continue
        if _blocked(final_index, lead):
            duplicate_count += 1
            print(f"Final duplicate/blocked gate skipped: {lead.brand_name}")
            continue
        if not _is_target_lead(lead):
            rejected_count += 1
            print(f"Final niche gate skipped: {lead.brand_name}")
            continue

        try:
            result = monday.create_lead(lead)
            item = result.get("data", {}).get("create_item", {})
            print(
                f"Created sponsor lead: {lead.brand_name} / "
                f"monday {item.get('id', '?')} / score {lead.lead_score} / "
                f"priority {_priority_score(lead)} / sponsored {lead.sponsored_date}"
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
        f"{len(scanned_video_ids)} YouTube videos scanned, "
        f"{creatomap_content_count} Creatomap sponsor events considered, "
        f"{creatordb_content_count} CreatorDB sponsor events considered."
    )

    if creatordb is None:
        print("CreatorDB is optional and disabled; Creatomap requires no key and remains active.")

    if errors:
        print(f"Scanner completed with {len(errors)} warning(s).")
        for error in errors[:10]:
            print(f"WARNING: {error}")

    if len(created) < config.target_daily_leads:
        print(
            "Qualified unique active target-niche inventory was below this run's target. "
            "The scanner did not lower quality, accept missing-email leads, "
            "allow stale/off-niche sponsors, or re-import duplicates."
        )


if __name__ == "__main__":
    run()
