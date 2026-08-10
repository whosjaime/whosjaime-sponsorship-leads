from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

from sponsor_models import ChannelRecord, VideoRecord


YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
SEARCH_WINDOW_SLOTS = 24

# Keep the hourly scanner to exactly three search.list calls. YouTube's q parameter
# supports Boolean OR with "|", so one combined query can cover a broad set of
# sponsorship phrases without increasing hourly API usage.
SPONSOR_DISCLOSURE_QUERY = (
    '"sponsored by"|"thanks to"|"brought to you by"|'
    '"in partnership with"|"partnered with"|"paid partnership"|'
    '"presented by"|"supported by"|"powered by"|#sponsored|#ad|#partner'
)
TARGET_PAID_QUERY = (
    'gaming|game|esports|pc|computer|gpu|monitor|mouse|controller|headset|keyboard|'
    'microphone|webcam|speaker|earbuds|audio|chair|desk|software|saas|app|browser|'
    'ai|cloud|productivity|developer|coding|vpn|cybersecurity|privacy|password|hosting|'
    'food|meal|snack|protein|candy|chips|coffee|beverage|drink|soda|hydration|tech'
)
SEARCH_LANES = (
    ("paid-placement", "", True),
    ("sponsor-disclosures", SPONSOR_DISCLOSURE_QUERY, False),
    ("target-niche-paid", TARGET_PAID_QUERY, True),
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
        """Return one of 24 rotating time slices across the allowed lookback."""
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

    def _search(self, lookback_hours: int, query: str = "", paid_only: bool = False) -> list[str]:
        # Keep this method's original public/testing interface. discover_video_ids sets
        # one active rotating window for all three lanes in the hourly run.
        window = self._active_search_window or self._hourly_search_window(lookback_hours)
        published_after, published_before, _ = window
        params = {
            "part": "snippet",
            "type": "video",
            "order": "date",
            "maxResults": 50,
            "publishedAfter": published_after,
            "publishedBefore": published_before,
            "regionCode": self.region,
            "relevanceLanguage": self.language,
            "safeSearch": "moderate",
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

    def discover_video_ids(self, lookback_hours: int) -> list[str]:
        """Run exactly three complementary search lanes in the current hourly slice."""
        ordered_ids: list[str] = []
        seen: set[str] = set()
        failed_lanes = 0
        self._active_search_window = self._hourly_search_window(lookback_hours)
        published_after, published_before, slot = self._active_search_window
        print(
            f"YouTube hourly discovery window {slot + 1}/{SEARCH_WINDOW_SLOTS}: "
            f"{published_after} through {published_before}"
        )

        try:
            for lane_name, query, paid_only in SEARCH_LANES:
                try:
                    ids = self._search(lookback_hours, query=query, paid_only=paid_only)
                except RuntimeError as exc:
                    failed_lanes += 1
                    print(f"YouTube search warning for {lane_name}: {exc}")
                    continue

                print(f"YouTube lane {lane_name}: {len(ids)} video IDs")
                for video_id in ids:
                    if video_id not in seen:
                        seen.add(video_id)
                        ordered_ids.append(video_id)
        finally:
            self._active_search_window = None

        if failed_lanes == len(SEARCH_LANES):
            raise RuntimeError("All YouTube sponsor discovery lanes failed.")

        return ordered_ids

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
                # Some API projects may not expose brandPartner yet. Paid-placement
                # details plus the video description still keep discovery functional.
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

    def discover(self, lookback_hours: int) -> tuple[list[VideoRecord], dict[str, ChannelRecord]]:
        video_ids = self.discover_video_ids(lookback_hours)
        videos = self.fetch_videos(video_ids)
        channel_ids = [video.channel_id for video in videos]
        channel_ids.extend(
            video.brand_partner_channel_id
            for video in videos
            if video.brand_partner_channel_id
        )
        return videos, self.fetch_channels(channel_ids)
