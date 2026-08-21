from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from sponsor_dedupe import email_domain, normalize_domain
from sponsor_models import SponsorLead

DEFAULT_RESEARCH_QUEUE = Path(__file__).resolve().parents[1] / "data" / "researched_sponsors.json"


class ResearchedSponsorSource:
    """Load agent-researched sponsor candidates from JSON.

    Research intake may use direct creator evidence from YouTube, TikTok, or Instagram.
    Every candidate still passes the normal downstream enrichment, freshness, contact,
    niche, permanent blocklist/dedupe, and write gates.
    """

    def __init__(self, path: str | Path = DEFAULT_RESEARCH_QUEUE) -> None:
        self.path = Path(path)

    @staticmethod
    def _content_id(url: str, platform: str) -> str:
        value = (url or "").strip()
        parsed = urlparse(value)
        host = parsed.netloc.lower()
        platform_key = (platform or "").strip().lower()
        if platform_key == "youtube" or "youtube.com" in host or host.endswith("youtu.be"):
            if host.endswith("youtu.be"):
                return parsed.path.strip("/").split("/", 1)[0]
            query_id = parse_qs(parsed.query).get("v", [""])[0]
            if query_id:
                return query_id
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 2 and parts[-2] in {"shorts", "embed", "live"}:
                return parts[-1]
            return ""
        if platform_key == "tiktok" or "tiktok.com" in host:
            match = re.search(r"/video/(\d+)", parsed.path)
            return match.group(1) if match else ""
        if platform_key == "instagram" or "instagram.com" in host:
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 2 and parts[-2] in {"reel", "reels", "p"}:
                return parts[-1]
            return ""
        return ""

    @staticmethod
    def _int(value) -> int:
        try:
            return int(float(value or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _verified_contact(item: dict, brand_domain: str) -> tuple[str, str, str, str]:
        contact_email = str(item.get("contact_email") or "").strip().lower()
        if not contact_email or email_domain(contact_email) != brand_domain:
            return "", "", "", ""
        return (
            str(item.get("contact_name") or "").strip(),
            str(item.get("contact_title") or "").strip(),
            contact_email,
            str(item.get("contact_source_url") or item.get("contact_source") or "").strip(),
        )

    @staticmethod
    def _platform_label(value: str) -> str:
        key = (value or "YouTube").strip().lower()
        labels = {
            "youtube": "YouTube",
            "tiktok": "TikTok",
            "instagram": "Instagram",
        }
        return labels.get(key, (value or "YouTube").strip())

    def load(self) -> list[SponsorLead]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Invalid researched sponsor queue: {exc}") from exc
        if not isinstance(payload, list):
            raise RuntimeError("Researched sponsor queue must be a JSON list.")

        leads: list[SponsorLead] = []
        seen: set[tuple[str, str, str]] = set()
        for item in payload:
            if not isinstance(item, dict):
                continue
            brand_name = str(item.get("brand_name") or "").strip()
            brand_domain = normalize_domain(str(item.get("brand_domain") or ""))
            sponsored_date = str(item.get("sponsored_date") or "").strip()[:10]
            source_platform = self._platform_label(str(item.get("source_platform") or "YouTube"))
            content_url = str(item.get("video_url") or item.get("source_url") or item.get("post_url") or "").strip()
            content_id = str(item.get("video_id") or item.get("content_id") or "").strip() or self._content_id(content_url, source_platform)

            if not brand_name or not brand_domain or not sponsored_date or not content_url or not content_id:
                continue
            if source_platform.lower() not in {"youtube", "tiktok", "instagram"}:
                continue

            identity = (brand_domain, source_platform.lower(), content_id)
            if identity in seen:
                continue
            seen.add(identity)

            contact_name, contact_title, contact_email, contact_source = self._verified_contact(item, brand_domain)
            raw_tags = item.get("creator_tags") or []
            creator_tags = [str(tag).strip() for tag in raw_tags if str(tag).strip()] if isinstance(raw_tags, list) else []

            leads.append(
                SponsorLead(
                    brand_name=brand_name,
                    brand_domain=brand_domain,
                    source_platform=source_platform,
                    creator_name=str(item.get("creator_name") or "").strip(),
                    creator_url=str(item.get("creator_url") or "").strip(),
                    creator_channel_id=str(item.get("creator_channel_id") or "").strip(),
                    creator_subscribers=self._int(item.get("creator_subscribers")),
                    creator_genre=str(item.get("creator_genre") or "").strip(),
                    creator_tags=creator_tags,
                    video_id=content_id,
                    video_url=content_url,
                    video_title=str(item.get("video_title") or item.get("content_title") or "").strip(),
                    sponsored_date=sponsored_date,
                    evidence=str(item.get("evidence") or "Researched public creator sponsorship evidence.").strip(),
                    paid_product_placement=bool(item.get("paid_product_placement", True)),
                    sponsor_category=str(item.get("sponsor_category") or "Other").strip() or "Other",
                    sponsor_subcategory=str(item.get("sponsor_subcategory") or "").strip(),
                    contact_name=contact_name,
                    contact_title=contact_title,
                    contact_email=contact_email,
                    email_type="Named public work email" if contact_email and contact_name else ("Public work email" if contact_email else ""),
                    contact_source=contact_source,
                    signals=[
                        "Daily researched sponsorship",
                        f"verified public {source_platform} sponsorship evidence",
                    ] + (["verified named public work email"] if contact_email and contact_name else []),
                )
            )
        return leads
