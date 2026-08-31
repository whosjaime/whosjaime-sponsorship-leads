from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests

from sponsor_dedupe import make_brand_key, make_sponsorship_key, normalize_brand_name, normalize_domain
from sponsor_models import SponsorLead


INSTAGRAM_SEARCH_LANES = (
    'site:instagram.com/reel/ "#ad" food',
    'site:instagram.com/reel/ "#ad" lifestyle',
    'site:instagram.com/reel/ "#ad" fashion',
    'site:instagram.com/reel/ "#ad" home',
    'site:instagram.com/reel/ "#ad" travel',
    'site:instagram.com/reel/ "#ad" pet',
    'site:instagram.com/reel/ "#sponsored"',
    'site:instagram.com/reel/ "paid partnership"',
    'site:instagram.com/p/ "#ad" food',
    'site:instagram.com/p/ "#ad" lifestyle',
    'site:instagram.com/p/ "#ad" fashion',
    'site:instagram.com/p/ "#ad" home',
    'site:instagram.com/p/ "#ad" travel',
    'site:instagram.com/p/ "#ad" pet',
    'site:instagram.com/p/ "#sponsored"',
    'site:instagram.com/p/ "paid partnership"',
)

DISCLOSURE_RE = re.compile(
    r'(?i)(?:^|[\s#])(?:ad|sponsored|paidpartner|paidpartnership|brandpartner)(?:\b|_)|'
    r'paid\s+partnership|sponsored\s+by|partnering\s+with|in\s+partnership\s+with'
)
POST_URL_RE = re.compile(r'https?://(?:www\.)?instagram\.com/(?:p|reel|reels)/([A-Za-z0-9_-]+)')
HANDLE_RE = re.compile(r'@([A-Za-z0-9._]{2,40})')
HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.I)
META_DESCRIPTION_RE = re.compile(
    r'<meta[^>]+(?:property=["\']og:description["\']|name=["\']description["\'])[^>]+content=["\']([^"\']*)["\']',
    re.I,
)
DATE_PATTERNS = (
    re.compile(r'datetime=["\'](20\d{2}-\d{2}-\d{2})', re.I),
    re.compile(r'"uploadDate"\s*:\s*"(20\d{2}-\d{2}-\d{2})', re.I),
    re.compile(r'"dateCreated"\s*:\s*"(20\d{2}-\d{2}-\d{2})', re.I),
    re.compile(r'"taken_at_timestamp"\s*:\s*(\d{10})', re.I),
)
USERNAME_PATTERNS = (
    re.compile(r'"username"\s*:\s*"([A-Za-z0-9._]{2,40})"', re.I),
    re.compile(r'@([A-Za-z0-9._]{2,40})\s*(?:on Instagram|• Instagram)', re.I),
)
NON_BRAND_HANDLES = {
    'instagram', 'meta', 'fyp', 'explore', 'creator', 'reels', 'shop',
}
DOMAIN_BLOCKLIST = {
    'duckduckgo.com', 'instagram.com', 'tiktok.com', 'youtube.com', 'youtu.be',
    'facebook.com', 'x.com', 'twitter.com', 'linkedin.com', 'pinterest.com',
    'reddit.com', 'wikipedia.org', 'amazon.com', 'walmart.com', 'target.com',
}


@dataclass
class InstagramPost:
    shortcode: str
    post_url: str
    creator_username: str
    creator_name: str
    creator_url: str
    caption: str
    published_at: str
    brand_name: str
    evidence: str


class InstagramSponsorScanner:
    """Best-effort creator-side Instagram sponsorship discovery from public indexed posts.

    A lead is emitted only when the public post/embed itself yields a dated post and an
    explicit sponsorship disclosure. Search snippets alone never qualify a lead.
    """

    def __init__(self, language: str = 'en', region: str = 'US', timeout: int = 10):
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
        self._domain_cache: dict[str, str] = {}

    def _search_html(self, query: str) -> str:
        response = self.session.get(
            f'https://html.duckduckgo.com/html/?q={quote_plus(query)}',
            timeout=self.timeout,
        )
        response.raise_for_status()
        return html.unescape(response.text)

    @staticmethod
    def _unwrap_search_href(href: str) -> str:
        value = html.unescape(href or '').strip()
        if value.startswith('//'):
            value = 'https:' + value
        parsed = urlparse(value)
        if 'duckduckgo.com' in parsed.netloc and parsed.path.startswith('/l/'):
            target = parse_qs(parsed.query).get('uddg', [''])[0]
            return unquote(target) if target else ''
        return value

    def _search(self, query: str) -> list[str]:
        text = self._search_html(query)
        urls: list[str] = []
        seen: set[str] = set()
        for href in HREF_RE.findall(text):
            target = self._unwrap_search_href(href)
            match = POST_URL_RE.search(target)
            if not match:
                continue
            shortcode = match.group(1)
            # Normalize to /p/; Instagram redirects valid shortcodes and this removes
            # tracking query strings while retaining the exact creator content ID.
            clean = f'https://www.instagram.com/p/{shortcode}/'
            if clean not in seen:
                seen.add(clean)
                urls.append(clean)
        return urls

    def _fetch_embed(self, post_url: str) -> str:
        response = self.session.get(post_url.rstrip('/') + '/embed/captioned/', timeout=self.timeout)
        response.raise_for_status()
        return response.text

    @staticmethod
    def _caption(page: str) -> str:
        match = META_DESCRIPTION_RE.search(page or '')
        if not match:
            return ''
        value = html.unescape(match.group(1))
        value = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), value)
        return ' '.join(value.split())

    @staticmethod
    def _published_date(page: str) -> str:
        for pattern in DATE_PATTERNS:
            match = pattern.search(page or '')
            if not match:
                continue
            value = match.group(1)
            if value.isdigit() and len(value) == 10:
                try:
                    return datetime.fromtimestamp(int(value), tz=timezone.utc).date().isoformat()
                except (ValueError, OSError):
                    continue
            return value[:10]
        return ''

    @staticmethod
    def _creator_username(page: str) -> str:
        for pattern in USERNAME_PATTERNS:
            match = pattern.search(page or '')
            if match:
                return match.group(1)
        return ''

    @staticmethod
    def _brand_from_caption(caption: str, creator_username: str) -> str:
        if not DISCLOSURE_RE.search(caption or ''):
            return ''
        explicit = re.search(
            r'(?i)(?:sponsored\s+by|paid\s+partnership\s+with|partnering\s+with|in\s+partnership\s+with|ad\s+with)\s+@?([A-Za-z0-9][A-Za-z0-9 &+._-]{1,50})',
            caption or '',
        )
        if explicit:
            value = explicit.group(1).strip(' .,!?:;#')
            if value:
                return value.replace('_', ' ').replace('.', ' ').strip().title()
        creator_key = creator_username.lower().strip('@')
        for handle in HANDLE_RE.findall(caption or ''):
            key = handle.lower().strip('.')
            if key == creator_key or key in NON_BRAND_HANDLES:
                continue
            return handle.replace('_', ' ').replace('.', ' ').strip().title()
        return ''

    def _resolve_brand_domain(self, brand_name: str) -> str:
        brand_key = normalize_brand_name(brand_name)
        if not brand_key:
            return ''
        if brand_key in self._domain_cache:
            return self._domain_cache[brand_key]
        tokens = [token for token in re.findall(r'[a-z0-9]+', brand_key.lower()) if len(token) >= 4]
        if not tokens:
            tokens = [brand_key.lower()]
        try:
            text = self._search_html(f'"{brand_name}" official site')
        except Exception:
            self._domain_cache[brand_key] = ''
            return ''
        for href in HREF_RE.findall(text):
            target = self._unwrap_search_href(href)
            if not target.startswith(('http://', 'https://')):
                continue
            domain = normalize_domain(target)
            if not domain or any(domain == blocked or domain.endswith('.' + blocked) for blocked in DOMAIN_BLOCKLIST):
                continue
            compact = re.sub(r'[^a-z0-9]', '', domain.lower())
            if any(re.sub(r'[^a-z0-9]', '', token) in compact for token in tokens):
                self._domain_cache[brand_key] = domain
                return domain
        self._domain_cache[brand_key] = ''
        return ''

    def discover(self, lookback_days: int = 30, max_posts: int = 120) -> list[InstagramPost]:
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=max(1, lookback_days))
        urls: list[str] = []
        seen: set[str] = set()
        for lane in INSTAGRAM_SEARCH_LANES:
            try:
                found = self._search(lane)
            except Exception as exc:
                print(f'WARNING: Instagram search lane failed: {lane}: {exc}')
                continue
            for url in found:
                if url not in seen:
                    seen.add(url)
                    urls.append(url)
                if len(urls) >= max_posts:
                    break
            if len(urls) >= max_posts:
                break

        posts: list[InstagramPost] = []
        for url in urls:
            shortcode_match = POST_URL_RE.search(url)
            if not shortcode_match:
                continue
            shortcode = shortcode_match.group(1)
            try:
                page = self._fetch_embed(url)
            except Exception as exc:
                print(f'WARNING: Instagram embed skipped {shortcode}: {exc}')
                continue
            caption = self._caption(page)
            if not caption or not DISCLOSURE_RE.search(caption):
                continue
            published = self._published_date(page)
            if not published:
                continue
            try:
                if datetime.fromisoformat(published).date() < cutoff:
                    continue
            except ValueError:
                continue
            creator_username = self._creator_username(page)
            brand_name = self._brand_from_caption(caption, creator_username)
            if not brand_name or len(normalize_brand_name(brand_name)) < 2:
                continue
            disclosure = DISCLOSURE_RE.search(caption)
            excerpt = caption[max(0, disclosure.start() - 80): disclosure.end() + 140] if disclosure else caption[:220]
            posts.append(InstagramPost(
                shortcode=shortcode,
                post_url=url,
                creator_username=creator_username,
                creator_name=creator_username,
                creator_url=f'https://www.instagram.com/{creator_username}/' if creator_username else '',
                caption=caption,
                published_at=published,
                brand_name=brand_name,
                evidence='Instagram creator-side sponsorship disclosure: ' + ' '.join(excerpt.split())[:260],
            ))
        return posts

    def to_lead(self, post: InstagramPost) -> SponsorLead:
        domain = self._resolve_brand_domain(post.brand_name)
        return SponsorLead(
            brand_name=post.brand_name,
            brand_domain=domain,
            source_platform='Instagram',
            creator_name=post.creator_name,
            creator_url=post.creator_url,
            creator_channel_id=post.creator_username,
            creator_subscribers=0,
            creator_genre='Lifestyle',
            creator_tags=['instagram', 'lifestyle'],
            video_id=post.shortcode,
            video_url=post.post_url,
            video_title=post.caption[:180],
            sponsored_date=post.published_at,
            evidence=post.evidence,
            paid_product_placement=True,
            brand_key=make_brand_key(post.brand_name, domain),
            sponsorship_key=make_sponsorship_key('Instagram', post.shortcode, post.brand_name, domain),
            signals=['Instagram creator-side ad/sponsored disclosure'],
        )
