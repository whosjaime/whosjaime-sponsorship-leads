from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class VideoRecord:
    platform: str
    video_id: str
    video_url: str
    title: str
    description: str
    published_at: str
    channel_id: str
    channel_title: str
    default_language: str = ""
    default_audio_language: str = ""
    tags: list[str] = field(default_factory=list)
    category_id: str = ""
    topic_categories: list[str] = field(default_factory=list)
    paid_product_placement: bool = False
    brand_partner_channel_id: str = ""
    view_count: int = 0


@dataclass
class ChannelRecord:
    channel_id: str
    title: str
    description: str
    custom_url: str = ""
    country: str = ""
    subscriber_count: int = 0
    topic_categories: list[str] = field(default_factory=list)


@dataclass
class SponsorLead:
    brand_name: str
    brand_domain: str
    source_platform: str
    creator_name: str
    creator_url: str
    creator_channel_id: str
    creator_subscribers: int
    creator_genre: str
    creator_tags: list[str]
    video_id: str
    video_url: str
    video_title: str
    sponsored_date: str
    evidence: str
    paid_product_placement: bool = False
    brand_partner_channel_id: str = ""
    sponsor_category: str = "Other"
    sponsor_subcategory: str = ""
    contact_name: str = ""
    contact_title: str = ""
    contact_email: str = ""
    email_type: str = ""
    contact_source: str = ""
    lead_score: int = 0
    lead_temperature: str = ""
    sponsorship_key: str = ""
    brand_key: str = ""
    signals: list[str] = field(default_factory=list)
    date_found: str = field(default_factory=lambda: datetime.now(timezone.utc).date().isoformat())

    def as_dict(self) -> dict:
        return {
            "brand_name": self.brand_name,
            "brand_domain": self.brand_domain,
            "source_platform": self.source_platform,
            "creator_name": self.creator_name,
            "creator_url": self.creator_url,
            "creator_channel_id": self.creator_channel_id,
            "creator_subscribers": self.creator_subscribers,
            "creator_genre": self.creator_genre,
            "creator_tags": self.creator_tags,
            "video_id": self.video_id,
            "video_url": self.video_url,
            "video_title": self.video_title,
            "sponsored_date": self.sponsored_date,
            "evidence": self.evidence,
            "paid_product_placement": self.paid_product_placement,
            "brand_partner_channel_id": self.brand_partner_channel_id,
            "sponsor_category": self.sponsor_category,
            "sponsor_subcategory": self.sponsor_subcategory,
            "contact_name": self.contact_name,
            "contact_title": self.contact_title,
            "contact_email": self.contact_email,
            "email_type": self.email_type,
            "contact_source": self.contact_source,
            "lead_score": self.lead_score,
            "lead_temperature": self.lead_temperature,
            "sponsorship_key": self.sponsorship_key,
            "brand_key": self.brand_key,
            "signals": self.signals,
            "date_found": self.date_found,
        }
