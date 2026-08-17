from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

from sponsor_models import ChannelRecord, VideoRecord


YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
SEARCH_WINDOW_SLOTS = 24

# Keep broad unquoted terms first so live search has a wider match surface, while
# preserving the explicit disclosure phrases used by the detector/tests.
SPONSOR_DISCLOSURE_QUERY = (
    'sponsored|sponsor|partner|#sponsored|#ad|#partner|'
    '"sponsored by"|"thanks to"|"brought to you by"|'
    '"in partnership with"|"partnered with"|"paid partnership"|'
    '"presented by"|"supported by"|"powered by"'
)
# The targeted lane intentionally excludes SaaS, coding, AI tools, VPNs, and
# cybersecurity services. "Tech" here means physical products/hardware only.
TARGET_PAID_QUERY = (
    'gaming|game|esports|pc|computer|hardware|gpu|cpu|ssd|monitor|mouse|controller|'
    'headset|headphones|keyboard|microphone|webcam|camera|speaker|earbuds|audio|'
    'capture card|charger|power bank|router|smartphone|laptop|wearable|chair|desk|'
    'food|meal|snack|protein|candy|chips|coffee|beverage|drink|soda|hydration'
)
SEARCH_LANES = (
    ("paid-placement", "", True),
    ("sponsor-disclosures", SPONSOR_DISCLOSURE_QUERY, False),
    ("target-niche-paid", TARGET_PAID_QUERY, True),
)

# Only used when the main queue is running low. These lanes deliberately search
# creator/niche areas the main pool under-serves instead of lowering the quality gate.
BACKUP_STREAM_VLOG_QUERY = (
    'streamer|streaming|livestream|"live stream"|twitch|vlog|lifestyle|reaction|'
    'challenge|"family vlog"|"day in my life"|"week in my life"'
)
BACKUP_BEAUTY_MUSIC_QUERY = (
    'beauty|makeup|skincare|cosmetics|haircare|music|musician|producer|guitar|'
    'recording|"audio interface"|plugin|daw|synth|piano|drums'
)
BACKUP_CREATOR_QUERY = (
    'creator|youtube|influencer|reaction|comedy|prank|family|travel|fashion|fitness|'
    'home|outdoors|pets|streaming|vlog'
)
BACKUP_SEARCH_LANES = (
    ("backup-stream-vlog-paid", BACKUP_STREAM_VLOG_QUERY, True),
    ("backup-beauty-music-paid", BACKUP_BEAUTY_MUSIC_QUERY, True),
    ("backup-creator-paid", BACKUP_CREATOR_QUERY, True),
)


class YouTubeSponsorScanner:
    def __init__(self, api_key: str, region: str = "US", language: str = "en") -> None:
        self.api_key = api_key
        self.region = region
        self.language = language
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "SponsorLeadScanner/1.0"})
        self._active_search_window: tuple[str, str, int] | None = None

    def _get(self, endpoint: str, params: dict) -> dict:
        response = self.session.get(
            f"{YOUTUBE_API}/{endpoint}",
            params={**params, "key": self.api_key},
            timeout=30,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"YouTube API {endpoint} error {response.status_code}: {response.text[:1000]}"
            )
        return response.json()

    @staticmethod
    def _rfc3339(value: datetime) -> str:
        return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @classmethod
    def _hourly_search_window(
        cls,
        lookback_hours: int,
        now: datetime | None = None,
    ) -> tuple[str, str, int]:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc).replace(microsecond=0)

        total_hours = max(24, int(lookback_hours))
        slot_width_hours = total_hours / SEARCH_WINDOW_SLOTS
        slot = current.hour % SEARCH_WINDOW_SLOTS

        younger_edge_hours = slot * slot_width_hours
        older_edge_hours = min(total_hours, (slot + 1) * slot_width_hours)
        published_before = current - timedelta(hours=younger_edge_hours)
        published_after = current - timedelta(hours=older_edge_hours)
        return cls._rfc3339(published_after), cls._rfc3339(published_before), slot

    @classmethod
    def _full_search_window(
        cls,
        lookback_hours: int,
        now: datetime | None = None,
    ) -> tuple[str, str, int]:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc).replace(microsecond=0)
        published_after = current - timedelta(hours=max(24, int(lookback_hours)))
        return cls._rfc3339(published_after), cls._rfc3339(current), -1

    def _search(self, lookback_hours: int, query: str = "", paid_only: bool = False) -> list[str]:
        window = self._active_search_window or self._hourly_search_window(lookback_hours)
        published_after, published_before, _ = window
        params = {
            "part": "snippet",
            "type": "video",
            # Query lanes should favor relevant sponsor integrations over the newest
            # random paid content. The date window still enforces freshness.
            "order": "relevance" if query else "date",
            "maxResults": 50,
            "publishedAfter": published_after,
            "publishedBefore": published_before,
            "regionCode": self.region,
            "relevanceLanguage": self.language,
            "safeSearch": "moderate",
            # Sponsored integrations we want are overwhelmingly long-form. This
            # prevents paid Shorts from consuming nearly the entire search pool.
            "videoDuration": "long",
        }
        if query:
            params["q"] = query
        if paid_only:
            params["videoPaidProductPlacement"] = "true"
        data = self._get("search", params)
        return [
            item.get("id", {}).get("videoId", "")
            for item in data.get("items", [])
            if item.get("id", {}).get("videoId")
        ]

    def _discover_ids_in_active_window(
        self,
        lookback_hours: int,
        label: str,
        lanes: tuple[tuple[str, str, bool], ...] = SEARCH_LANES,
    ) -> list[str]:
        ordered_ids: list[str] = []
        seen: set[str] = set()
        failed_lanes = 0

        for lane_name, query, paid_only in lanes:
            try:
                ids = self._search(lookback_hours, query=query, paid_only=paid_only)
            except RuntimeError as exc:
                failed_lanes += 1
                print(f"YouTube search warning for {lane_name}: {exc}")
                continue

            print(f"YouTube {label} lane {lane_name}: {len(ids)} video IDs")
            for video_id in ids:
                if video_id not in seen:
                    seen.add(video_id)
                    ordered_ids.append(video_id)

        if failed_lanes == len(lanes):
            raise RuntimeError(f"All YouTube {label} sponsor discovery lanes failed.")
        return ordered_ids

    def discover_video_ids(self, lookback_hours: int) -> list[str]:
        self._active_search_window = self._hourly_search_window(lookback_hours)
        published_after, published_before, slot = self._active_search_window
        print(
            f"YouTube hourly discovery window {slot + 1}/{SEARCH_WINDOW_SLOTS}: "
            f"{published_after} through {published_before}"
        )
        try:
            return self._discover_ids_in_active_window(lookback_hours, "hourly")
        finally:
            self._active_search_window = None

    def discover_batch_video_ids(self, lookback_hours: int) -> list[str]:
        self._active_search_window = self._full_search_window(lookback_hours)
        published_after, published_before, _ = self._active_search_window
        print(
            "YouTube main batch discovery window: "
            f"{published_after} through {published_before}"
        )
        try:
            return self._discover_ids_in_active_window(lookback_hours, "main-batch")
        finally:
            self._active_search_window = None

    def discover_backup_batch_video_ids(self, lookback_hours: int) -> list[str]:
        """Targeted backup inventory for streaming/vlog/beauty/music and adjacent creators."""
        self._active_search_window = self._full_search_window(lookback_hours)
        published_after, published_before, _ = self._active_search_window
        print(
            "YouTube backup batch discovery window: "
            f"{published_after} through {published_before}"
        )
        try:
            return self._discover_ids_in_active_window(
                lookback_hours,
                "backup-batch",
                lanes=BACKUP_SEARCH_LANES,
            )
        finally:
            self._active_search_window = None

    def fetch_videos(self, video_ids: list[str]) -> list[VideoRecord]:
        records = []
        for start in range(0, len(video_ids), 50):
            batch = video_ids[start:start + 50]
            params = {
                "part": "snippet,statistics,topicDetails,paidProductPlacementDetails,brandPartner",
                "id": ",".join(batch),
                "maxResults": 50,
            }
            try:
                data = self._get("videos", params)
            except RuntimeError:
                params["part"] = "snippet,statistics,topicDetails,paidProductPlacementDetails"
                data = self._get("videos", params)

            for item in data.get("items", []):
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
                paid = item.get("paidProductPlacementDetails", {})
                partner = item.get("brandPartner", {})
                video_id = item.get("id", "")
                if not video_id:
                    continue

                records.append(
                    VideoRecord(
                        platform="YouTube",
                        video_id=video_id,
                        video_url=f"https://www.youtube.com/watch?v={video_id}",
                        title=snippet.get("title", ""),
                        description=snippet.get("description", ""),
                        published_at=snippet.get("publishedAt", ""),
                        channel_id=snippet.get("channelId", ""),
                        channel_title=snippet.get("channelTitle", ""),
                        default_language=snippet.get("defaultLanguage", "") or "",
                        default_audio_language=snippet.get("defaultAudioLanguage", "") or "",
                        tags=snippet.get("tags", []) or [],
                        category_id=snippet.get("categoryId", ""),
                        topic_categories=item.get("topicDetails", {}).get("topicCategories", []) or [],
                        paid_product_placement=bool(paid.get("hasPaidProductPlacement", False)),
                        brand_partner_channel_id=partner.get("channelId", "") or "",
                        view_count=int(stats.get("viewCount", 0) or 0),
                    )
                )
        return records

    def fetch_channels(self, channel_ids: list[str]) -> dict[str, ChannelRecord]:
        result = {}
        unique_ids = list(dict.fromkeys(channel_id for channel_id in channel_ids if channel_id))
        for start in range(0, len(unique_ids), 50):
            batch = unique_ids[start:start + 50]
            data = self._get(
                "channels",
                {
                    "part": "snippet,statistics,topicDetails",
                    "id": ",".join(batch),
                    "maxResults": 50,
                },
            )
            for item in data.get("items", []):
                channel_id = item.get("id", "")
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
                if not channel_id:
                    continue
                result[channel_id] = ChannelRecord(
                    channel_id=channel_id,
                    title=snippet.get("title", ""),
                    description=snippet.get("description", ""),
                    custom_url=snippet.get("customUrl", "") or "",
                    country=snippet.get("country", "") or "",
                    subscriber_count=int(stats.get("subscriberCount", 0) or 0),
                    topic_categories=item.get("topicDetails", {}).get("topicCategories", []) or [],
                )
        return result

    def _hydrate(self, video_ids: list[str]) -> tuple[list[VideoRecord], dict[str, ChannelRecord]]:
        videos = self.fetch_videos(video_ids)
        channel_ids = [video.channel_id for video in videos]
        channel_ids.extend(
            video.brand_partner_channel_id
            for video in videos
            if video.brand_partner_channel_id
        )
        return videos, self.fetch_channels(channel_ids)

    def discover(self, lookback_hours: int) -> tuple[list[VideoRecord], dict[str, ChannelRecord]]:
        return self._hydrate(self.discover_video_ids(lookback_hours))

    def discover_batch(self, lookback_hours: int) -> tuple[list[VideoRecord], dict[str, ChannelRecord]]:
        return self._hydrate(self.discover_batch_video_ids(lookback_hours))

    def discover_backup_batch(self, lookback_hours: int) -> tuple[list[VideoRecord], dict[str, ChannelRecord]]:
        return self._hydrate(self.discover_backup_batch_video_ids(lookback_hours))
