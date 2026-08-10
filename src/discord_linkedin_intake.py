from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import requests

from sponsor_dedupe import make_brand_key, make_sponsorship_key, normalize_brand_name, normalize_domain
from sponsor_detector import detect_sponsors
from sponsor_models import SponsorLead, VideoRecord

DISCORD_API = "https://discord.com/api/v10"
LINKEDIN_URL_RE = re.compile(
    r"https?://(?:[a-z]{2,3}\.)?(?:www\.)?linkedin\.com/(?:posts/[^\s<>]+|feed/update/urn:li:[^\s<>]+)",
    re.I,
)
URL_RE = re.compile(r"https?://[^\s<>{}\[\]\"']+", re.I)
EXPLICIT_BRAND_RE = re.compile(r"(?:^|\n)\s*brand\s*:\s*([^\n]+)", re.I)
EXPLICIT_WEBSITE_RE = re.compile(r"(?:^|\n)\s*(?:website|site|domain)\s*:\s*([^\s]+)", re.I)
IGNORED_DOMAINS = {
    "linkedin.com", "youtube.com", "youtu.be", "instagram.com", "tiktok.com", "x.com",
    "twitter.com", "facebook.com", "discord.com", "discord.gg", "threads.net", "google.com",
}
HANDLED_EMOJIS = {"✅", "⚠️", "🔁", "🚫"}


@dataclass
class LinkedInDiscordCandidate:
    message_id: str
    linkedin_url: str
    brand_name: str
    brand_domain: str
    poster_name: str
    poster_url: str
    post_title: str
    evidence: str
    sponsored_date: str
    activity_id: str


class DiscordLinkedInClient:
    """Read explicitly submitted LinkedIn links from a Discord channel.

    This client never fetches LinkedIn. It only reads the Discord message object and
    Discord-provided embeds, then uses the extracted structured data as manual intake.
    """

    def __init__(self, bot_token: str, channel_id: str) -> None:
        self.bot_token = (bot_token or "").strip()
        self.channel_id = str(channel_id or "").strip()
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bot {self.bot_token}",
            "User-Agent": "ManifestMediaSponsorIntake/1.0",
        })

    def _request(self, method: str, path: str, **kwargs):
        response = self.session.request(method, f"{DISCORD_API}{path}", timeout=20, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(
                f"Discord API error {response.status_code}: {response.text[:800]}"
            )
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def fetch_recent_messages(self, limit: int = 50) -> list[dict]:
        limit = max(1, min(100, int(limit)))
        data = self._request("GET", f"/channels/{self.channel_id}/messages", params={"limit": limit})
        return data if isinstance(data, list) else []

    @staticmethod
    def already_handled(message: dict) -> bool:
        for reaction in message.get("reactions", []) or []:
            emoji = (reaction.get("emoji") or {}).get("name", "")
            if reaction.get("me") and emoji in HANDLED_EMOJIS:
                return True
        return False

    def add_reaction(self, message_id: str, emoji: str) -> None:
        encoded = quote(emoji, safe="")
        self._request(
            "PUT",
            f"/channels/{self.channel_id}/messages/{message_id}/reactions/{encoded}/@me",
        )

    def reply(self, message_id: str, content: str) -> None:
        self._request(
            "POST",
            f"/channels/{self.channel_id}/messages",
            json={
                "content": content[:1900],
                "message_reference": {"message_id": message_id},
                "allowed_mentions": {"replied_user": False},
            },
        )


def _embed_text(message: dict) -> tuple[str, str, str, str]:
    chunks: list[str] = []
    poster_name = ""
    poster_url = ""
    title = ""

    for embed in message.get("embeds", []) or []:
        if not isinstance(embed, dict):
            continue
        if embed.get("title"):
            title = title or str(embed.get("title"))
            chunks.append(str(embed.get("title")))
        if embed.get("description"):
            chunks.append(str(embed.get("description")))
        author = embed.get("author") or {}
        if author.get("name"):
            poster_name = poster_name or str(author.get("name"))
            chunks.append(str(author.get("name")))
        if author.get("url"):
            poster_url = poster_url or str(author.get("url"))
        footer = embed.get("footer") or {}
        if footer.get("text"):
            chunks.append(str(footer.get("text")))
        for field in embed.get("fields", []) or []:
            if field.get("name"):
                chunks.append(str(field.get("name")))
            if field.get("value"):
                chunks.append(str(field.get("value")))

    return "\n".join(chunks), poster_name.strip(), poster_url.strip(), title.strip()


def _linkedin_url(message: dict) -> str:
    content = str(message.get("content") or "")
    match = LINKEDIN_URL_RE.search(content)
    if match:
        return match.group(0).rstrip(".,;:!?)\"]}")
    for embed in message.get("embeds", []) or []:
        url = str(embed.get("url") or "")
        match = LINKEDIN_URL_RE.search(url)
        if match:
            return match.group(0).rstrip(".,;:!?)\"]}")
    return ""


def _activity_id(url: str, message_id: str) -> str:
    match = re.search(r"(?:activity[:-]|activity%3A)(\d{8,})", url, re.I)
    if match:
        return match.group(1)
    numbers = re.findall(r"\d{8,}", url)
    return numbers[-1] if numbers else message_id


def _date_from_message(message: dict) -> str:
    # Prefer a timestamp Discord received in the LinkedIn preview if present.
    for embed in message.get("embeds", []) or []:
        value = str(embed.get("timestamp") or "").strip()
        if value:
            return value[:10]
    value = str(message.get("timestamp") or "").strip()
    if value:
        return value[:10]
    return datetime.now(timezone.utc).date().isoformat()


def _external_domains(text: str) -> list[str]:
    domains: list[str] = []
    for raw in URL_RE.findall(text or ""):
        domain = normalize_domain(raw.rstrip(".,;:!?)\"]}"))
        if not domain or domain in IGNORED_DOMAINS or any(domain.endswith(f".{d}") for d in IGNORED_DOMAINS):
            continue
        if domain not in domains:
            domains.append(domain)
    return domains


def _brand_from_domain(domain: str) -> str:
    host = normalize_domain(domain)
    if not host:
        return ""
    labels = host.split(".")
    core = labels[-2] if len(labels) >= 2 else labels[0]
    return re.sub(r"[-_]", " ", core).strip().title()


def parse_linkedin_discord_message(message: dict) -> LinkedInDiscordCandidate | None:
    linkedin_url = _linkedin_url(message)
    if not linkedin_url:
        return None

    message_id = str(message.get("id") or "")
    content = str(message.get("content") or "")
    preview, poster_name, poster_url, post_title = _embed_text(message)
    combined = "\n".join(part for part in [content, preview] if part).strip()

    explicit_brand = EXPLICIT_BRAND_RE.search(content)
    explicit_site = EXPLICIT_WEBSITE_RE.search(content)
    brand_name = explicit_brand.group(1).strip() if explicit_brand else ""
    brand_domain = normalize_domain(explicit_site.group(1)) if explicit_site else ""

    # Reuse the same sponsorship language detector used by the YouTube scanner,
    # but only against text Discord already exposed. No request is made to LinkedIn.
    fake_video = VideoRecord(
        platform="LinkedIn",
        video_id=_activity_id(linkedin_url, message_id),
        video_url=linkedin_url,
        title=post_title,
        description=combined,
        published_at=str(message.get("timestamp") or ""),
        channel_id="",
        channel_title=poster_name,
        tags=[],
    )
    detections = detect_sponsors(fake_video, {})
    if detections:
        best = detections[0]
        brand_name = brand_name or best.brand_name
        brand_domain = brand_domain or normalize_domain(best.domain)

    domains = _external_domains(combined)
    if not brand_domain and len(domains) == 1:
        brand_domain = domains[0]
    if brand_domain and not brand_name:
        brand_name = _brand_from_domain(brand_domain)

    # A LinkedIn-only name without a sponsor-owned domain is intentionally not guessed.
    # The bot can ask for a simple `Website: brand.com` hint instead.
    if not brand_name or not brand_domain:
        return LinkedInDiscordCandidate(
            message_id=message_id,
            linkedin_url=linkedin_url,
            brand_name=brand_name,
            brand_domain=brand_domain,
            poster_name=poster_name,
            poster_url=poster_url,
            post_title=post_title,
            evidence=combined[:1000],
            sponsored_date=_date_from_message(message),
            activity_id=_activity_id(linkedin_url, message_id),
        )

    return LinkedInDiscordCandidate(
        message_id=message_id,
        linkedin_url=linkedin_url,
        brand_name=brand_name,
        brand_domain=brand_domain,
        poster_name=poster_name,
        poster_url=poster_url,
        post_title=post_title,
        evidence=combined[:1000],
        sponsored_date=_date_from_message(message),
        activity_id=_activity_id(linkedin_url, message_id),
    )


def candidate_to_lead(candidate: LinkedInDiscordCandidate) -> SponsorLead:
    return SponsorLead(
        brand_name=candidate.brand_name,
        brand_domain=normalize_domain(candidate.brand_domain),
        source_platform="LinkedIn",
        creator_name=candidate.poster_name or "LinkedIn post",
        creator_url=candidate.poster_url or candidate.linkedin_url,
        creator_channel_id="",
        creator_subscribers=0,
        creator_genre="",
        creator_tags=[],
        video_id=candidate.activity_id,
        video_url=candidate.linkedin_url,
        video_title=candidate.post_title or "LinkedIn sponsorship post",
        sponsored_date=candidate.sponsored_date,
        evidence=candidate.evidence or "Manually submitted LinkedIn sponsorship post via Discord.",
        brand_key=make_brand_key(candidate.brand_name, candidate.brand_domain),
        sponsorship_key=make_sponsorship_key(
            "LinkedIn", candidate.activity_id, candidate.brand_name, candidate.brand_domain
        ),
        signals=["Manual LinkedIn sponsorship submission", "Discord public-link preview evidence"],
    )
