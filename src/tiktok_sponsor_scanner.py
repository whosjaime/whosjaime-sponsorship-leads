from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus, urlparse

import requests

from sponsor_dedupe import make_brand_key, make_sponsorship_key, normalize_brand_name
from sponsor_models import SponsorLead


TIKTOK_SEARCH_LANES = (
    'site:tiktok.com/@*/video/ "#ad"',
    'site:tiktok.com/@*/video/ "#sponsored"',
    'site:tiktok.com/@*/video/ "paid partnership"',
    'site:tiktok.com/@*/video/ "#paidpartner"',
    'site:tiktok.com/@*/video/ "#brandpartner"',
    'site:tiktok.com/@*/video/ "ad with"',
    'site:tiktok.com/@*/video/ "sponsored by"',
    'site:tiktok.com/@*/video/ "partnering with"',
)

DISCLOSURE_RE = re.compile(
    r'(?i)(?:^|[\s#])(?:ad|sponsored|paidpartner|paidpartnership|brandpartner)(?:\b|_)|'
    r'paid\s+partnership|sponsored\s+by|partnering\s+with'
)
HANDLE_RE = re.compile(r'@([A-Za-z0-9._]{2,40})')
VIDEO_URL_RE = re.compile(r'https?://(?:www\.)?tiktok\.com/@([^/?#]+)/video/(\d+)')
FOLLOWER_RE = re.compile(r'"followerCount"\s*:\s*(\d+)')
DATE_RE = re.compile(r'(?i)\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b')

NON_BRAND_HANDLES = {
    'tiktok', 'fyp', 'foryou', 'foryoupage', 'capcut', 'creator', 'shop', 'tiktokshop',
}


@dataclass
class TikTokPost:
    video_id: str
    video_url: str
    creator_username: str
    creator_name: str
    creator_url: str
    creator_followers: int
    caption: str
    published_at: str
    brand_name: str
    evidence: str


class TikTokSponsorScanner:
    """Discover creator-side TikTok sponsorship posts from public indexed pages.

    Discovery uses search-engine indexed TikTok post URLs, then TikTok's public oEmbed
    endpoint for post metadata. This intentionally does not crawl brand-owned TikTok
    pages or treat a bare affiliate/gifted mention as paid sponsorship evidence.
    """

    def __init__(self, language: str = 'en', region: str = 'US', timeout: int = 12):
        self.language = language or 'en'
        self.region = region or 'US'
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'
            ),
            'Accept-Language': 'en-US,en;q=0.9',
        })

    def _search(self, query: str) -> list[str]:
        url = f'https://html.duckduckgo.com/html/?q={quote_plus(query)}'
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        text = html.unescape(response.text)
        urls: list[str] = []
        seen: set[str] = set()
        for match in re.finditer(r'https?://(?:www\.)?tiktok\.com/@[^\s"&<>]+/video/\d+', text):
            candidate = match.group(0).rstrip('.,;:!?)\\\"\'')
            parsed = VIDEO_URL_RE.search(candidate)
            if not parsed:
                continue
            clean = f'https://www.tiktok.com/@{parsed.group(1)}/video/{parsed.group(2)}'
            if clean not in seen:
                seen.add(clean)
                urls.append(clean)
        return urls

    def _oembed(self, video_url: str) -> dict:
        endpoint = f'https://www.tiktok.com/oembed?url={quote_plus(video_url)}'
        response = self.session.get(endpoint, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def _profile_followers(self, username: str) -> int:
        try:
            response = self.session.get(f'https://www.tiktok.com/@{username}', timeout=self.timeout)
            if not response.ok:
                return 0
            match = FOLLOWER_RE.search(response.text)
            return int(match.group(1)) if match else 0
        except Exception:
            return 0

    @staticmethod
    def _published_date(video_id: str, caption: str) -> str:
        # TikTok snowflake IDs encode creation Unix seconds in their high 32 bits.
        try:
            timestamp = int(video_id) >> 32
            dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            if 2020 <= dt.year <= datetime.now(timezone.utc).year + 1:
                return dt.date().isoformat()
        except Exception:
            pass
        match = DATE_RE.search(caption or '')
        if match:
            year, month, day = (int(part) for part in match.groups())
            try:
                return datetime(year, month, day, tzinfo=timezone.utc).date().isoformat()
            except ValueError:
                pass
        return ''

    @staticmethod
    def _brand_from_caption(caption: str, creator_username: str) -> str:
        if not DISCLOSURE_RE.search(caption or ''):
            return ''
        handles = HANDLE_RE.findall(caption or '')
        creator_key = creator_username.strip('@').lower()
        for handle in handles:
            key = handle.lower().strip('.')
            if key == creator_key or key in NON_BRAND_HANDLES:
                continue
            return handle.replace('_', ' ').replace('.', ' ').strip().title()

        explicit = re.search(
            r'(?i)(?:sponsored\s+by|paid\s+partnership\s+with|partnering\s+with)\s+([A-Za-z0-9][A-Za-z0-9 &+._-]{1,50})',
            caption or '',
        )
        if explicit:
            return explicit.group(1).strip(' .,!?:;#')
        return ''

    def discover(self, lookback_days: int = 30, max_posts: int = 80) -> list[TikTokPost]:
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=max(1, lookback_days))
        urls: list[str] = []
        seen_urls: set[str] = set()
        for lane in TIKTOK_SEARCH_LANES:
            try:
                found = self._search(lane)
            except Exception as exc:
                print(f'WARNING: TikTok search lane failed: {lane}: {exc}')
                continue
            for url in found:
                if url not in seen_urls:
                    seen_urls.add(url)
                    urls.append(url)
                if len(urls) >= max_posts:
                    break
            if len(urls) >= max_posts:
                break

        posts: list[TikTokPost] = []
        for url in urls:
            parsed = VIDEO_URL_RE.search(url)
            if not parsed:
                continue
            username, video_id = parsed.group(1), parsed.group(2)
            try:
                metadata = self._oembed(url)
            except Exception as exc:
                print(f'WARNING: TikTok oEmbed skipped {video_id}: {exc}')
                continue
            caption = (metadata.get('title') or '').strip()
            if not DISCLOSURE_RE.search(caption):
                continue
            brand_name = self._brand_from_caption(caption, username)
            if not brand_name or len(normalize_brand_name(brand_name)) < 2:
                continue
            published = self._published_date(video_id, caption)
            if not published:
                continue
            try:
                if datetime.fromisoformat(published).date() < cutoff:
                    continue
            except ValueError:
                continue
            creator_name = (metadata.get('author_name') or username).strip()
            creator_url = (metadata.get('author_url') or f'https://www.tiktok.com/@{username}').strip()
            followers = self._profile_followers(username)
            disclosure = DISCLOSURE_RE.search(caption)
            evidence = caption[max(0, disclosure.start() - 80): disclosure.end() + 140] if disclosure else caption[:220]
            posts.append(TikTokPost(
                video_id=video_id,
                video_url=url,
                creator_username=username,
                creator_name=creator_name,
                creator_url=creator_url,
                creator_followers=followers,
                caption=caption,
                published_at=published,
                brand_name=brand_name,
                evidence='TikTok creator-side sponsorship disclosure: ' + ' '.join(evidence.split())[:260],
            ))
        return posts

    @staticmethod
    def to_lead(post: TikTokPost) -> SponsorLead:
        brand_key = make_brand_key(post.brand_name, '')
        return SponsorLead(
            brand_name=post.brand_name,
            brand_domain='',
            source_platform='TikTok',
            creator_name=post.creator_name,
            creator_url=post.creator_url,
            creator_channel_id=post.creator_username,
            creator_subscribers=post.creator_followers,
            creator_genre='Other',
            creator_tags=['tiktok'],
            video_id=post.video_id,
            video_url=post.video_url,
            video_title=post.caption[:180],
            sponsored_date=post.published_at,
            evidence=post.evidence,
            brand_key=brand_key,
            sponsorship_key=make_sponsorship_key('TikTok', post.video_id, post.brand_name, ''),
            signals=['TikTok creator-side ad/sponsored disclosure'],
        )
