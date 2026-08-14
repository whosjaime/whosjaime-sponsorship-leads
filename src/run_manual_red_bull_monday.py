from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from sponsor_models import SponsorLead
from sponsor_monday_client import SponsorMondayClient
from sponsor_queue import (
    is_duplicate,
    load_duplicate_keys,
    load_sent_keys,
    mark_sent,
    save_sent_keys,
)

RESULT_PATH = Path("data/manual_red_bull_result.json")


def run() -> None:
    token = os.getenv("SPONSOR_MONDAY_TOKEN") or os.getenv("SPONSOR_MONDAY_API_KEY") or ""
    board_id = int(os.getenv("SPONSOR_MONDAY_BOARD_ID", "18424367188"))
    group_id = os.getenv("SPONSOR_MONDAY_GROUP_ID", "topics")
    if not token:
        raise RuntimeError("Missing SPONSOR_MONDAY_TOKEN / SPONSOR_MONDAY_API_KEY")

    lead = SponsorLead(
        brand_name="Red Bull",
        brand_domain="https://www.redbull.com/ca-en/support-hub/media-and-platforms",
        source_platform="LinkedIn",
        creator_name="",
        creator_url="",
        creator_channel_id="",
        creator_subscribers=0,
        creator_genre="",
        creator_tags=[],
        video_id="",
        video_url="",
        video_title="",
        sponsored_date="",
        evidence=(
            "Current Red Bull creator-marketing / brand-partnership activity plus an official "
            "Red Bull Canada social-media collaboration intake route."
        ),
        sponsor_category="Food & Beverage",
        sponsor_subcategory="Energy Drink",
        contact_email="",
        email_type="Collaboration form",
        contact_source="https://www.redbull.com/ca-en/support-hub/media-and-platforms",
        lead_score=100,
        lead_temperature="Very Hot",
        date_found=date.today().isoformat(),
    )

    duplicate_keys = load_duplicate_keys()
    sent_keys = load_sent_keys()

    if is_duplicate(lead, duplicate_keys):
        result = {"brand": "Red Bull", "status": "duplicate_skipped"}
    else:
        monday = SponsorMondayClient(token, board_id, group_id)
        response = monday.create_lead(lead)
        item = response.get("data", {}).get("create_item", {}) or {}
        item_id = str(item.get("id", ""))
        mark_sent(lead, sent_keys)
        save_sent_keys(sent_keys)
        result = {
            "brand": "Red Bull",
            "status": "created",
            "monday_item_id": item_id,
            "contact_route": "Official Red Bull social-media collaboration support route",
        }
        print(f"Created manual Red Bull lead: monday {item_id}")

    RESULT_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    run()
