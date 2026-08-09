from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

DEFAULT_SPONSOR_MONDAY_BOARD_ID = 18424367188
DEFAULT_SPONSOR_MONDAY_GROUP_ID = "topics"


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class SponsorScannerConfig:
    youtube_api_key: str
    monday_token: str
    monday_board_id: int
    monday_group_id: str
    discord_webhook_url: str
    target_daily_leads: int
    min_lead_score: int
    search_region: str
    search_language: str
    enable_instagram: bool
    enable_tiktok: bool


def load_sponsor_config() -> SponsorScannerConfig:
    youtube_api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    monday_token = (
        os.getenv("SPONSOR_MONDAY_TOKEN", "").strip()
        or os.getenv("SPONSOR_MONDAY_API_KEY", "").strip()
    )
    board_id_raw = os.getenv("SPONSOR_MONDAY_BOARD_ID", "").strip()

    missing = []
    if not youtube_api_key:
        missing.append("YOUTUBE_API_KEY")
    if not monday_token:
        missing.append("SPONSOR_MONDAY_TOKEN")
    if missing:
        raise ValueError(f"Missing sponsor scanner configuration: {', '.join(missing)}")

    return SponsorScannerConfig(
        youtube_api_key=youtube_api_key,
        monday_token=monday_token,
        monday_board_id=int(board_id_raw) if board_id_raw else DEFAULT_SPONSOR_MONDAY_BOARD_ID,
        monday_group_id=os.getenv("SPONSOR_MONDAY_GROUP_ID", DEFAULT_SPONSOR_MONDAY_GROUP_ID).strip() or DEFAULT_SPONSOR_MONDAY_GROUP_ID,
        discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL", "").strip(),
        target_daily_leads=max(1, _int("SPONSOR_TARGET_DAILY_LEADS", 1)),
        min_lead_score=max(1, min(100, _int("SPONSOR_MIN_LEAD_SCORE", 70))),
        search_region=os.getenv("SPONSOR_SEARCH_REGION", "US").strip().upper() or "US",
        search_language=os.getenv("SPONSOR_SEARCH_LANGUAGE", "en").strip() or "en",
        enable_instagram=_bool("ENABLE_INSTAGRAM_SPONSOR_SCAN", False),
        enable_tiktok=_bool("ENABLE_TIKTOK_SPONSOR_SCAN", False),
    )
