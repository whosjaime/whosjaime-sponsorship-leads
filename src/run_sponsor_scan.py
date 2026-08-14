from __future__ import annotations

from datetime import date

from brand_enrichment import BrandEnricher
from creatordb_active_sponsors import CreatorDBActiveSponsorSource
from creator_classifier import classify_creator
from discord_notifier import DiscordNotifier
from researched_sponsor_source import ResearchedSponsorSource
from sponsor_config import load_sponsor_config
from sponsor_dedupe import ExistingSponsorIndex, make_brand_key, make_sponsorship_key, normalize_domain
from sponsor_detector import detect_sponsors, to_sponsor_lead
from sponsor_models import SponsorLead
from sponsor_monday_client import SponsorMondayClient
from youtube_sponsor_scanner import SEARCH_LANES, YouTubeSponsorScanner

# Launch-safe discovery uses one YouTube discovery pass per hourly run. The default
# active-sponsor window remains 30 days, but SPONSOR_MAX_AGE_DAYS can make it stricter.
MAX_NATIVE_YOUTUBE_LOOKBACK_DAYS = 30

# Tech means physical consumer products/hardware only. Software, SaaS, AI tools,
# developer platforms, VPNs, and cybersecurity services are not automatic targets.
TARGET_SPONSOR_CATEGORIES = {
    "Gaming",
    "Consumer Tech",
    "Food & Beverage",
}

DIGITAL_TECH_CATEGORIES = {
    "Software / SaaS",
    "Cybersecurity / VPN",
}

PHYSICAL_TECH_KEYWORDS = {
    "electronics", "hardware", "computer hardware", "pc hardware", "gaming gear",
    "gaming peripheral", "keyboard", "mechanical keyboard", "mouse", "gaming mouse",
    "mousepad", "headset", "headphones", "earbuds", "microphone", "webcam", "camera",
    "monitor", "display", "speaker", "audio interface", "capture card", "graphics card",
    "gpu", "cpu", "processor", "ssd", "storage drive", "laptop", "computer", "pc",
    "smartphone", "phone accessory", "charger", "power bank", "router", "smart home",
    "wearable", "controller", "console", "tech accessory", "tech accessories",
}

TARGET_BRAND_KEYWORDS = {
    "gaming", "gamer", "esports", "gaming gear", "gaming peripheral", "controller",
    *PHYSICAL_TECH_KEYWORDS,
    "food", "drink", "beverage", "energy drink", "coffee", "snack", "meal", "soda",
    "sparkling water", "hydration",
}

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

    # Daily researched candidates are admitted only when the queue contains direct
    # public YouTube sponsorship evidence. They still pass every normal production gate.
    if "Daily researched sponsorship" in signals:
        score += 35
    if "verified public sponsorship evidence" in signals:
        score += 25
    if "verified named public work email" in signals:
        score += 5

    # CreatorDB remains optional future coverage only; launch does not depend on it.
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


def _is_physical_tech_product(lead: SponsorLead) -> bool:
    text = _target_text(lead)
    return any(keyword in text for keyword in PHYSICAL_TECH_KEYWORDS)


def _is_target_lead(lead: SponsorLead) -> bool:
    """Allow Gaming, Food/Drink, and physical tech products; reject all digital-tech services."""
    text = _target_text(lead)
    if any(keyword in text for keyword in EXCLUDED_SPONSOR_KEYWORDS):
        return False

    # Hard policy: digital-tech categories never enter the automatic queue. We prefer
    # missing an occasional misclassified hardware company over sending SaaS/AI/VPN
    # filler. Real product companies should classify as Consumer Tech or match a
    # physical-product keyword outside these digital categories.
    if lead.sponsor_category in DIGITAL_TECH_CATEGORIES:
        return False

    if lead.sponsor_category in TARGET_SPONSOR_CATEGORIES:
        return True
    if _is_physical_tech_product(lead):
        return True
    return any(keyword in text for keyword in TARGET_BRAND_KEYWORDS)


def _priority_score(lead: SponsorLead) -> int:
    """Rank target sponsors by fit, recency, and outreach contact quality."""
    score = 0
    if lead.sponsor_category in TARGET_SPONSOR_CATEGORIES or _is_physical_tech_product(lead):
        score += 100
    text = _target_text(lead)
    if any(keyword in text for keyword in TARGET_BRAND_KEYWORDS):
        score += 50

    # Prefer actionable named contacts over generic inboxes when sponsor quality is equal.
    if lead.contact_email and lead.contact_name:
        score += 25
    elif lead.contact_email:
        score += 5

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
        # Daily research can supply a verified named work email. Preserve it while
        # still using website enrichment for domain normalization and niche classification.
        preferred_email = lead.contact_email
        preferred_email_type = lead.email_type
        preferred_source = lead.contact_source

        enrichment = enricher.enrich(lead.brand_domain)
        if enrichment.get("domain"):
            lead.brand_domain = normalize_domain(enrichment["domain"])

        if preferred_email:
            lead.contact_email = preferred_email
            lead.email_type = preferred_email_type or "Named public work email"
            lead.contact_source = preferred_source or enrichment.get("contact_source", "")
        else:
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
    researched = ResearchedSponsorSource()
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
    researched_content_count = 0
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

    # Source 0: a small daily research queue maintained separately from automated
    # YouTube discovery. This lets manually/web-researched sponsor evidence enter the
    # exact same production gates without bypassing dedupe, niche or email checks.
    try:
        researched_leads = researched.load()
        researched_content_count = len(researched_leads)
    except Exception as exc:
        errors.append(f"Researched sponsor queue failed: {exc}")
        researched_leads = []

    for lead in researched_leads:
        consider_lead(lead, "Daily Research")

    # Launch source: one native YouTube pass, using exactly three search.list lanes.
    # The three lanes cover: all declared paid placements, combined sponsor-disclosure
    # language, and target-niche paid placements. This avoids relying on a third-party
    # service and avoids repeating multiple lookback searches each hour.
    search_days = min(config.max_sponsor_age_days, MAX_NATIVE_YOUTUBE_LOOKBACK_DAYS)
    lookback_hours = max(24, search_days * 24)
    print(
        f"Scanning active YouTube sponsorships from the last {search_days} days "
        f"using {len(SEARCH_LANES)} discovery lanes..."
    )

    try:
        videos, channels = youtube.discover(lookback_hours)
    except Exception as exc:
        errors.append(f"YouTube active sponsor scan failed: {exc}")
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

    # Optional extra coverage only. Nothing about launch depends on getting access.
    if len(candidates) < desired_pool and creatordb is not None:
        print(
            "Native YouTube inventory was below target; checking optional CreatorDB "
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
        f"{researched_content_count} daily-research candidates considered, "
        f"{len(scanned_video_ids)} YouTube videos scanned, "
        f"{creatordb_content_count} optional CreatorDB sponsor events considered."
    )

    if creatordb is None:
        print("CreatorDB is optional and disabled; launch uses the native YouTube API plus the daily research queue.")

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
