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

MAX_NATIVE_YOUTUBE_LOOKBACK_DAYS = 30

TARGET_SPONSOR_CATEGORIES = {
    "Gaming", "Consumer Tech", "Food & Beverage", "Food", "Fashion",
    "Health & Wellness", "Travel", "Home", "Entertainment", "Beauty", "Pet", "Fragrance",
}

DIGITAL_TECH_CATEGORIES = {"Software / SaaS", "Cybersecurity / VPN"}

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
    "sparkling water", "hydration", "fashion", "clothing", "apparel", "footwear",
    "wellness", "fitness", "health", "travel", "luggage", "home", "furniture",
    "kitchen", "pet", "dog", "cat", "fragrance", "perfume", "cologne", "beauty",
    "skincare", "makeup",
}

EXCLUDED_SPONSOR_KEYWORDS = {
    "festival", "music festival", "concert festival", "concert promoter", "event production",
    "software", "saas", "vpn", "cybersecurity", "password manager", "cloud platform",
    "web hosting", "hosting platform", "developer tool", "coding tool", "ai software",
    "ai platform", "browser extension",
}


def _sponsorship_age_days(lead: SponsorLead) -> int | None:
    try:
        sponsored = date.fromisoformat((getattr(lead, "sponsored_date", "") or "")[:10])
    except (TypeError, ValueError):
        return None
    return (date.today() - sponsored).days


def _is_recent_sponsorship(lead: SponsorLead, max_age_days: int = 30) -> bool:
    age_days = _sponsorship_age_days(lead)
    if age_days is None:
        return False
    return 0 <= age_days <= max(1, max_age_days)


def _score_lead(lead: SponsorLead) -> int:
    score = 0
    signals = set(getattr(lead, "signals", []) or [])
    if "explicit sponsor phrase" in signals:
        score += 35
    if bool(getattr(lead, "paid_product_placement", False)):
        score += 25
    if "YouTube brand partner" in signals:
        score += 20
    if "ad/sponsored disclosure" in signals:
        score += 12
    if "Daily researched sponsorship" in signals:
        score += 35
    if "verified public sponsorship evidence" in signals or any(
        signal.startswith("verified public ") and signal.endswith(" sponsorship evidence")
        for signal in signals
    ):
        score += 25
    if "verified named public work email" in signals or "verified named role-linked contact" in signals:
        score += 5
    if "CreatorDB sponsored content" in signals:
        score += 35
    if "partnered brand attribution" in signals:
        score += 25
    if getattr(lead, "brand_domain", ""):
        score += 15
    if getattr(lead, "contact_email", "") or getattr(lead, "contact_name", ""):
        score += 15
    if getattr(lead, "sponsor_category", "") and getattr(lead, "sponsor_category", "") != "Other":
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
            str(getattr(lead, "brand_name", "") or ""),
            str(getattr(lead, "brand_domain", "") or ""),
            str(getattr(lead, "sponsor_category", "") or ""),
            str(getattr(lead, "sponsor_subcategory", "") or ""),
            str(getattr(lead, "evidence", "") or ""),
        ]
    ).lower()


def _is_physical_tech_product(lead: SponsorLead) -> bool:
    text = _target_text(lead)
    return any(keyword in text for keyword in PHYSICAL_TECH_KEYWORDS)


def _is_target_lead(lead: SponsorLead) -> bool:
    text = _target_text(lead)
    if any(keyword in text for keyword in EXCLUDED_SPONSOR_KEYWORDS):
        return False
    category = str(getattr(lead, "sponsor_category", "") or "")
    if category in DIGITAL_TECH_CATEGORIES:
        return False
    if category in TARGET_SPONSOR_CATEGORIES:
        return True
    if _is_physical_tech_product(lead):
        return True
    return any(keyword in text for keyword in TARGET_BRAND_KEYWORDS)


def _priority_score(lead: SponsorLead) -> int:
    score = 0
    category = str(getattr(lead, "sponsor_category", "") or "")
    if category in TARGET_SPONSOR_CATEGORIES or _is_physical_tech_product(lead):
        score += 100
    text = _target_text(lead)
    if any(keyword in text for keyword in TARGET_BRAND_KEYWORDS):
        score += 50
    if getattr(lead, "contact_email", "") and getattr(lead, "contact_name", ""):
        score += 25
    elif getattr(lead, "contact_email", "") or getattr(lead, "contact_name", ""):
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
        preferred_email = lead.contact_email
        preferred_email_type = lead.email_type
        preferred_source = lead.contact_source
        preferred_name = lead.contact_name
        preferred_title = lead.contact_title
        preferred_source_url = lead.contact_source_url
        preferred_category = (lead.sponsor_category or "").strip()
        preferred_subcategory = (lead.sponsor_subcategory or "").strip()

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
            lead.contact_source = preferred_source or enrichment.get("contact_source", "")
        lead.contact_name = preferred_name or enrichment.get("contact_name", "")
        lead.contact_title = preferred_title or enrichment.get("contact_title", "")
        lead.contact_source_url = preferred_source_url or enrichment.get("contact_source_url", "") or lead.contact_source

        enriched_category = (enrichment.get("category") or "Other").strip()
        enriched_subcategory = (enrichment.get("subcategory") or "").strip()
        lead.sponsor_category = (
            preferred_category
            if preferred_category and preferred_category != "Other" and enriched_category == "Other"
            else enriched_category
        )
        lead.sponsor_subcategory = enriched_subcategory or preferred_subcategory
        lead.brand_key = make_brand_key(lead.brand_name, lead.brand_domain)
        lead.sponsorship_key = make_sponsorship_key(
            lead.source_platform, lead.video_id, lead.brand_name, lead.brand_domain,
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
    creatordb = CreatorDBActiveSponsorSource(config.creatordb_api_key, config.creatordb_page_size) if config.creatordb_api_key else None
    enricher = BrandEnricher()
    discord = DiscordNotifier(config.discord_webhook_url)
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
        errors.append("TikTok adapter is not active in legacy direct-scan mode; queue workflow handles TikTok separately.")

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
            print(f"Stale/undated sponsorship skipped: {lead.brand_name} / {lead.sponsored_date or 'unknown date'}")
            return
        if not lead.contact_email and not lead.contact_name:
            rejected_count += 1
            print(f"Qualified contact required; skipped: {lead.brand_name}")
            return
        if _blocked(existing, lead):
            duplicate_count += 1
            print(f"Duplicate/blocked brand skipped: {lead.brand_name}")
            return
        if lead.lead_score < config.min_lead_score:
            rejected_count += 1
            print(f"Below score threshold; skipped: {lead.brand_name} / {lead.lead_score} < {config.min_lead_score}")
            return
        if not _is_target_lead(lead):
            rejected_count += 1
            print(f"Outside target niches; skipped: {lead.brand_name} ({lead.sponsor_category or 'Other'})")
            return
        identity = lead.brand_key or f"brand:{lead.brand_name.strip().lower()}"
        current = candidates.get(identity)
        if current is None or (_priority_score(lead), lead.lead_score, lead.sponsored_date) > (_priority_score(current), current.lead_score, current.sponsored_date):
            candidates[identity] = lead
            print(f"Qualified active sponsor candidate via {discovery_source}: {lead.brand_name} / {lead.sponsored_date}")

    try:
        researched_leads = researched.load()
        researched_content_count = len(researched_leads)
    except Exception as exc:
        errors.append(f"Researched sponsor queue warning: {exc}")
        researched_leads = []
    for lead in researched_leads:
        consider_lead(lead, "Daily Research")

    if len(candidates) < desired_pool:
        try:
            videos, channels = youtube.discover_batch(min(config.max_sponsor_age_days, MAX_NATIVE_YOUTUBE_LOOKBACK_DAYS) * 24)
            for video in videos:
                if video.video_id in scanned_video_ids:
                    continue
                scanned_video_ids.add(video.video_id)
                creator = channels.get(video.channel_id)
                genre, tags = classify_creator(video, creator)
                for detection in detect_sponsors(video, channels):
                    consider_lead(to_sponsor_lead(video, creator, detection, genre, tags), "YouTube")
        except Exception as exc:
            errors.append(f"YouTube discovery warning: {exc}")

    if len(candidates) < desired_pool and creatordb is not None:
        try:
            for lead in creatordb.discover(config.max_sponsor_age_days):
                creatordb_content_count += 1
                consider_lead(lead, "CreatorDB")
                if len(candidates) >= desired_pool:
                    break
        except Exception as exc:
            errors.append(f"CreatorDB warning: {exc}")

    ranked = sorted(candidates.values(), key=lambda lead: (_priority_score(lead), lead.lead_score, lead.sponsored_date), reverse=True)
    sent = 0
    for lead in ranked[:desired_pool]:
        try:
            item_id = monday.create_sponsor(lead)
            discord.send_lead(lead, item_id)
            sent += 1
        except Exception as exc:
            errors.append(f"Delivery warning for {lead.brand_name}: {exc}")
    print(
        f"SPONSOR_SCAN_COMPLETE: {sent} delivered; {len(candidates)} qualified; "
        f"{duplicate_count} duplicate/blocked; {rejected_count} rejected; "
        f"{researched_content_count} researched records; {creatordb_content_count} CreatorDB records."
    )
    for error in errors:
        print(f"WARNING: {error}")


if __name__ == "__main__":
    run()
