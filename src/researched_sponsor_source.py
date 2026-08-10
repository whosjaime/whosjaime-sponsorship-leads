from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from sponsor_dedupe import normalize_domain
from sponsor_models import SponsorLead

DEFAULT_RESEARCH_QUEUE = Path(__file__).resolve().parents[1] / "data" / "researched_sponsors.json"


class ResearchedSponsorSource:
    """Load human/agent-researched sponsor candidates from a small JSON queue.

    The queue is only an intake source. Every candidate still goes through the normal
    sponsor pipeline: website enrichment, public-email requirement, freshness check,
    niche filter, permanent blocklist, full monday.com dedupe, and final write gate.
    """

    def __init__(self, path: str | Path = DEFAULT_RESEARCH_QUEUE) -> None:
        self.path = Path(path)

    @staticmethod
    def _video_id(url: str) -> str:
        parsed = urlparse((url or "").strip())
        host = parsed.netloc.lower()
        if host.endswith("youtu.be"):
            return parsed.path.strip("/").split("/", 1)[0]
        if "youtube.com" in host:
            query_id = parse_qs(parsed.query).get("v", [""])[0]
            if query_id:
                return query_id
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 2 and parts[-2] in {"shorts", "embed", "live"}:
                return parts[-1]
        return ""

    @staticmethod
    def _int(value) -> int:
        try:
            return int(float(value or 0))
        except (TypeError, ValueError):
            return 0

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
        seen: set[tuple[str, str]] = set()
        for item in payload:
            if not isinstance(item, dict):
                continue

            brand_name = str(item.get("brand_name") or "").strip()
            brand_domain = normalize_domain(str(item.get("brand_domain") or ""))
            sponsored_date = str(item.get("sponsored_date") or "").strip()[:10]
            video_url = str(item.get("video_url") or "").strip()
            video_id = self._video_id(video_url)

            # A researched candidate needs concrete sponsor identity plus direct
            # YouTube evidence. Missing/ambiguous records never enter the pipeline.
            if not brand_name or not brand_domain or not sponsored_date or not video_id:
                continue

            identity = (brand_domain, video_id)
            if identity in seen:
                continue
            seen.add(identity)

            leads.append(
                SponsorLead(
                    brand_name=brand_name,
                    brand_domain=brand_domain,
                    source_platform="YouTube",
                    creator_name=str(item.get("creator_name") or "").strip(),
                    creator_url=str(item.get("creator_url") or "").strip(),
                    creator_channel_id=str(item.get("creator_channel_id") or "").strip(),
                    creator_subscribers=self._int(item.get("creator_subscribers")),
                    creator_genre="",
                    creator_tags=[],
                    video_id=video_id,
                    video_url=video_url,
                    video_title=str(item.get("video_title") or "").strip(),
                    sponsored_date=sponsored_date,
                    evidence=str(item.get("evidence") or "Daily researched public sponsorship evidence.").strip(),
                    paid_product_placement=bool(item.get("paid_product_placement", False)),
                    signals=[
                        "Daily researched sponsorship",
                        "verified public sponsorship evidence",
                    ],
                )
            )

        return leads
