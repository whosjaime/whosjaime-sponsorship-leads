from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlparse

import requests

from sponsor_dedupe import normalize_domain
from sponsor_models import SponsorLead

CREATOMAP_API = "https://creatomap.com/api"
TARGET_CATEGORIES = ("gaming", "tech", "food", "beverage", "vpn")
YOUTUBE_URL_RE = re.compile(r"https?://(?:www\.)?(?:youtube\.com|youtu\.be)/[^\s\"'<>]+", re.I)


class CreatomapActiveSponsorSource:
    """Use Creatomap's public JSON API as a zero-approval sponsorship source.

    Creatomap is only a discovery/evidence source. The normal pipeline still verifies
    freshness, enriches the sponsor-owned domain, requires a public business email,
    applies niche filters, and runs the permanent + monday.com duplicate gates.
    """

    def __init__(self, max_brands: int = 35, timeout: int = 20) -> None:
        self.max_brands = max(5, min(100, int(max_brands or 35)))
        self.timeout = max(5, min(60, int(timeout or 20)))
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "SponsorLeadScanner/1.0 (public Creatomap API)",
                "Accept": "application/json",
            }
        )

    def _get_json(self, path: str, params: dict | None = None) -> Any:
        response = self.session.get(
            f"{CREATOMAP_API}/{path.lstrip('/')}",
            params=params or {},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Creatomap {path} error {response.status_code}: {response.text[:600]}"
            )
        try:
            return response.json()
        except Exception as exc:
            raise RuntimeError(f"Creatomap {path} did not return JSON") from exc

    @staticmethod
    def _walk(value: Any) -> Iterable[dict[str, Any]]:
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from CreatomapActiveSponsorSource._walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from CreatomapActiveSponsorSource._walk(child)

    @staticmethod
    def _text(obj: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = obj.get(key)
            if value not in (None, "", [], {}):
                return str(value).strip()
        return ""

    @staticmethod
    def _parse_date(value: Any) -> str:
        if value in (None, ""):
            return ""

        if isinstance(value, (int, float)):
            try:
                timestamp = float(value)
                if timestamp > 10_000_000_000:
                    timestamp /= 1000
                return datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
            except (ValueError, OSError, OverflowError):
                return ""

        raw = str(value).strip()
        if not raw:
            return ""

        if re.fullmatch(r"\d{4}-\d{2}", raw):
            return f"{raw}-01"
        if re.fullmatch(r"\d{4}", raw):
            return f"{raw}-01-01"

        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            pass

        match = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", raw)
        if match:
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
            except ValueError:
                return ""
        return ""

    @classmethod
    def _object_date(cls, obj: dict[str, Any]) -> str:
        # Prefer dates that describe the sponsorship/video itself. Do not use generic
        # profile updated_at values as proof of sponsorship activity.
        for key in (
            "sponsored_date", "sponsoredDate", "video_date", "videoDate",
            "published_at", "publishedAt", "publish_date", "publishDate",
            "last_sponsored", "lastSponsored", "latest_sponsorship", "latestSponsorship",
            "last_date", "lastDate", "end_date", "endDate", "to", "end",
        ):
            parsed = cls._parse_date(obj.get(key))
            if parsed:
                return parsed

        # Date ranges are sometimes represented as one string, e.g. "Mar 2026 – Jul 2026".
        for key in ("date_range", "dateRange", "range", "dates"):
            raw = cls._text(obj, key)
            years = re.findall(r"\b(20\d{2})\b", raw)
            if years:
                # Month-name parsing is intentionally conservative; the first day is
                # enough for the downstream max-age gate and never fabricates recency.
                months = {
                    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
                }
                tokens = re.findall(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(20\d{2})", raw, re.I)
                if tokens:
                    month_name, year = tokens[-1]
                    return date(int(year), months[month_name[:3].lower()], 1).isoformat()
        return ""

    @staticmethod
    def _youtube_url(obj: dict[str, Any]) -> str:
        for key in (
            "video_url", "videoUrl", "youtube_url", "youtubeUrl", "evidence_url",
            "evidenceUrl", "content_url", "contentUrl", "url",
        ):
            value = obj.get(key)
            if isinstance(value, str):
                match = YOUTUBE_URL_RE.search(value)
                if match:
                    return match.group(0).rstrip(".,);]")

        for key in ("video_id", "videoId", "youtube_video_id", "youtubeVideoId", "content_id", "contentId"):
            video_id = str(obj.get(key) or "").strip()
            if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id):
                return f"https://www.youtube.com/watch?v={video_id}"

        for value in obj.values():
            if isinstance(value, str):
                match = YOUTUBE_URL_RE.search(value)
                if match:
                    return match.group(0).rstrip(".,);]")
        return ""

    @staticmethod
    def _video_id(video_url: str) -> str:
        if not video_url:
            return ""
        parsed = urlparse(video_url)
        if parsed.netloc.endswith("youtu.be"):
            return parsed.path.strip("/")
        if "youtube.com" in parsed.netloc:
            query = parsed.query
            match = re.search(r"(?:^|&)v=([^&]+)", query)
            if match:
                return match.group(1)
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 2 and parts[-2] in {"shorts", "embed", "live"}:
                return parts[-1]
        return ""

    @classmethod
    def _brand_seed(cls, obj: dict[str, Any]) -> dict[str, str] | None:
        name = cls._text(obj, "brand_name", "brandName", "name", "title")
        slug = cls._text(obj, "slug", "brand_slug", "brandSlug")
        category = cls._text(obj, "category", "brand_category", "brandCategory").lower()
        domain = normalize_domain(cls._text(obj, "domain", "website", "brand_domain", "brandDomain"))

        # Ignore nested creator/video objects accidentally encountered during recursion.
        if not name or cls._youtube_url(obj):
            return None
        if not slug:
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if not slug:
            return None
        return {"name": name, "slug": slug, "category": category, "domain": domain}

    def _collect_seeds(self) -> list[dict[str, str]]:
        seeds: dict[str, dict[str, str]] = {}

        # Trends are the most useful when Creatomap has recent trend inventory.
        try:
            trends = self._get_json("trends", {"period": "30d"})
            for obj in self._walk(trends):
                seed = self._brand_seed(obj)
                if seed:
                    seeds.setdefault(seed["slug"], seed)
        except Exception as exc:
            print(f"Creatomap trends warning: {exc}")

        # Category lists are the zero-wait fallback. We verify actual recency from
        # each brand profile before creating any SponsorLead.
        per_category = max(5, (self.max_brands // len(TARGET_CATEGORIES)) + 3)
        for category in TARGET_CATEGORIES:
            if len(seeds) >= self.max_brands:
                break
            try:
                payload = self._get_json(
                    "brands",
                    {"category": category, "limit": per_category, "sort": "recent"},
                )
            except Exception as exc:
                print(f"Creatomap {category} brand-list warning: {exc}")
                continue
            for obj in self._walk(payload):
                seed = self._brand_seed(obj)
                if not seed:
                    continue
                if seed["category"] and seed["category"] not in TARGET_CATEGORIES:
                    continue
                seeds.setdefault(seed["slug"], seed)
                if len(seeds) >= self.max_brands:
                    break

        return list(seeds.values())[: self.max_brands]

    @classmethod
    def _creator_info(cls, obj: dict[str, Any]) -> tuple[str, str, str, int]:
        nested = None
        for key in ("creator", "channel", "youtube_creator", "youtubeCreator"):
            if isinstance(obj.get(key), dict):
                nested = obj[key]
                break
        source = nested or obj

        name = cls._text(source, "display_name", "displayName", "creator_name", "creatorName", "channel_title", "channelTitle", "name", "title")
        channel_id = cls._text(source, "channel_id", "channelId", "youtube_channel_id", "youtubeChannelId")
        creator_url = cls._text(source, "creator_url", "creatorUrl", "channel_url", "channelUrl", "youtube_url", "youtubeUrl")
        if creator_url and "youtube.com" not in creator_url:
            creator_url = ""
        if not creator_url and channel_id:
            creator_url = f"https://www.youtube.com/channel/{channel_id}"

        subscribers = 0
        for key in ("subscribers", "subscriber_count", "subscriberCount", "total_subscribers", "totalSubscribers"):
            try:
                subscribers = int(float(source.get(key) or 0))
                if subscribers:
                    break
            except (TypeError, ValueError):
                continue
        return name, creator_url, channel_id, subscribers

    def _lead_from_detail(self, seed: dict[str, str], detail: Any, max_age_days: int) -> SponsorLead | None:
        today = date.today()
        best: tuple[int, SponsorLead] | None = None

        detail_domain = seed.get("domain", "")
        for obj in self._walk(detail):
            if not detail_domain:
                detail_domain = normalize_domain(
                    self._text(obj, "domain", "website", "brand_domain", "brandDomain")
                )

            sponsored_date = self._object_date(obj)
            video_url = self._youtube_url(obj)
            if not sponsored_date or not video_url:
                continue

            try:
                age = (today - date.fromisoformat(sponsored_date)).days
            except ValueError:
                continue
            if age < 0 or age > max_age_days:
                continue

            creator_name, creator_url, creator_channel_id, creator_subscribers = self._creator_info(obj)
            video_id = self._video_id(video_url)
            video_title = self._text(obj, "video_title", "videoTitle", "content_title", "contentTitle", "title")

            lead = SponsorLead(
                brand_name=seed["name"],
                brand_domain=detail_domain,
                source_platform="YouTube",
                creator_name=creator_name,
                creator_url=creator_url,
                creator_channel_id=creator_channel_id,
                creator_subscribers=creator_subscribers,
                creator_genre="",
                creator_tags=[],
                video_id=video_id,
                video_url=video_url,
                video_title=video_title,
                sponsored_date=sponsored_date,
                evidence=(
                    "Creatomap's public API listed a recent YouTube sponsorship with "
                    "video evidence for this brand."
                ),
                signals=["Creatomap recent sponsorship", "Creatomap video evidence"],
            )
            if best is None or age < best[0]:
                best = (age, lead)

        return best[1] if best else None

    def discover(self, max_age_days: int = 30) -> list[SponsorLead]:
        max_age_days = max(1, min(365, int(max_age_days or 30)))
        leads: list[SponsorLead] = []

        for seed in self._collect_seeds():
            try:
                detail = self._get_json(f"brands/{seed['slug']}")
            except Exception as exc:
                print(f"Creatomap profile warning for {seed['name']}: {exc}")
                continue

            lead = self._lead_from_detail(seed, detail, max_age_days)
            if lead:
                leads.append(lead)

        leads.sort(key=lambda lead: lead.sponsored_date, reverse=True)
        return leads
