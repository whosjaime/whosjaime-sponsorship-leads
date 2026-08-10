from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import requests

from sponsor_dedupe import normalize_domain
from sponsor_models import SponsorLead

CREATORDB_CONTENT_SEARCH_URL = "https://apiv3.creatordb.app/youtube/content-search"


class CreatorDBActiveSponsorSource:
    """Discover recently sponsored YouTube content across CreatorDB's full index.

    Creator information is kept only as evidence for the sponsorship. Brand activity is
    the actual lead signal.
    """

    def __init__(self, api_key: str, page_size: int = 50) -> None:
        self.api_key = (api_key or "").strip()
        self.page_size = max(1, min(100, int(page_size or 50)))
        self.session = requests.Session()
        self.session.headers.update(
            {
                "api-key": self.api_key,
                "Content-Type": "application/json",
                "User-Agent": "SponsorLeadScanner/1.0",
            }
        )

    @staticmethod
    def _brand_name_from_domain(domain: str) -> str:
        stem = normalize_domain(domain).split(".", 1)[0]
        stem = re.sub(r"[-_]+", " ", stem).strip()
        return " ".join(part.capitalize() for part in stem.split()) or domain

    @staticmethod
    def _publish_date(value: Any) -> str:
        try:
            timestamp_ms = int(value)
            return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).date().isoformat()
        except (TypeError, ValueError, OSError, OverflowError):
            return ""

    @staticmethod
    def _creator_url(channel_id: str) -> str:
        channel_id = (channel_id or "").strip()
        return f"https://www.youtube.com/channel/{channel_id}" if channel_id else ""

    @staticmethod
    def _partner_domain(raw_brand: Any) -> str:
        if isinstance(raw_brand, str):
            return normalize_domain(raw_brand)
        if isinstance(raw_brand, dict):
            for key in ("brandId", "domain", "website", "id"):
                value = raw_brand.get(key)
                if value:
                    domain = normalize_domain(str(value))
                    if domain:
                        return domain
        return ""

    def discover(self, max_age_days: int = 30) -> list[SponsorLead]:
        if not self.api_key:
            return []

        max_age_days = max(1, min(365, int(max_age_days or 30)))
        payload = {
            "filters": [
                {"filterName": "isSponsored", "op": "=", "value": True},
                {"filterName": "publishTime", "op": "<", "value": max_age_days},
                {"filterName": "postType", "op": "=", "value": "video"},
            ],
            "sortBy": "publishTime",
            "desc": True,
            "pageSize": self.page_size,
            "offset": 0,
        }

        response = self.session.post(CREATORDB_CONTENT_SEARCH_URL, json=payload, timeout=30)
        if response.status_code >= 400:
            raise RuntimeError(
                f"CreatorDB content-search error {response.status_code}: {response.text[:1000]}"
            )

        result = response.json()
        if result.get("success") is False:
            raise RuntimeError(
                "CreatorDB content-search failed: "
                f"{result.get('errorCode', '')} {result.get('errorDescription', '')}".strip()
            )

        content_list = result.get("data", {}).get("contentList", []) or []
        leads: list[SponsorLead] = []
        seen_events: set[tuple[str, str]] = set()

        for content in content_list:
            if not isinstance(content, dict) or not content.get("isSponsored"):
                continue

            video_id = str(content.get("contentId") or "").strip()
            video_url = str(content.get("url") or "").strip()
            if not video_url and video_id:
                video_url = f"https://www.youtube.com/watch?v={video_id}"

            sponsored_date = self._publish_date(content.get("publishTime"))
            if not sponsored_date:
                continue

            creator = content.get("creator") or {}
            creator_channel_id = str(creator.get("channelId") or "").strip()
            try:
                creator_subscribers = int(creator.get("totalSubscribers") or 0)
            except (TypeError, ValueError):
                creator_subscribers = 0

            partnered_brands = content.get("partneredBrands") or []
            for raw_brand in partnered_brands:
                domain = self._partner_domain(raw_brand)
                if not domain:
                    continue

                event_key = (domain, video_id or video_url)
                if event_key in seen_events:
                    continue
                seen_events.add(event_key)

                brand_name = ""
                if isinstance(raw_brand, dict):
                    brand_name = str(raw_brand.get("name") or "").strip()
                if not brand_name:
                    brand_name = self._brand_name_from_domain(domain)

                leads.append(
                    SponsorLead(
                        brand_name=brand_name,
                        brand_domain=domain,
                        source_platform="YouTube",
                        creator_name=str(creator.get("displayName") or "").strip(),
                        creator_url=self._creator_url(creator_channel_id),
                        creator_channel_id=creator_channel_id,
                        creator_subscribers=creator_subscribers,
                        creator_genre=str(content.get("category") or "").strip(),
                        creator_tags=[],
                        video_id=video_id,
                        video_url=video_url,
                        video_title=str(content.get("title") or "").strip(),
                        sponsored_date=sponsored_date,
                        evidence=(
                            "CreatorDB indexed this content as sponsored and attributed "
                            f"{domain} as a partnered brand."
                        ),
                        paid_product_placement=False,
                        signals=["CreatorDB sponsored content", "partnered brand attribution"],
                    )
                )

        return leads
