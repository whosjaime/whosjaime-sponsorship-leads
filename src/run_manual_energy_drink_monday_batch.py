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

BATCH_PATH = Path("data/manual_energy_drink_batch.json")
RESULT_PATH = Path("data/manual_energy_drink_batch_result.json")


def _lead_from_row(row: dict) -> SponsorLead:
    return SponsorLead(
        brand_name=str(row.get("brand_name", "")).strip(),
        brand_domain=str(row.get("brand_domain", "")).strip(),
        source_platform="",
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
        evidence=str(row.get("evidence", "")).strip(),
        sponsor_category="Food & Beverage",
        sponsor_subcategory="Energy Drink",
        contact_email=str(row.get("contact_email", "")).strip(),
        email_type="Public business contact",
        contact_source=str(row.get("contact_source", "")).strip(),
        lead_score=100,
        lead_temperature="Very Hot",
        date_found=date.today().isoformat(),
    )


def run() -> None:
    token = os.getenv("SPONSOR_MONDAY_TOKEN") or os.getenv("SPONSOR_MONDAY_API_KEY") or ""
    board_id = int(os.getenv("SPONSOR_MONDAY_BOARD_ID", "18424367188"))
    group_id = os.getenv("SPONSOR_MONDAY_GROUP_ID", "topics")
    if not token:
        raise RuntimeError("Missing SPONSOR_MONDAY_TOKEN / SPONSOR_MONDAY_API_KEY")

    rows = json.loads(BATCH_PATH.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise RuntimeError("Manual energy drink batch must be a JSON list")

    monday = SponsorMondayClient(token, board_id, group_id)
    duplicate_keys = load_duplicate_keys()
    sent_keys = load_sent_keys()
    results: list[dict] = []

    for row in rows:
        lead = _lead_from_row(row)
        if not lead.brand_name or not lead.brand_domain or not lead.contact_email:
            results.append({"brand": lead.brand_name or "Unknown", "status": "invalid"})
            continue
        if is_duplicate(lead, duplicate_keys):
            results.append({"brand": lead.brand_name, "status": "duplicate_skipped"})
            continue

        try:
            response = monday.create_lead(lead)
            item = response.get("data", {}).get("create_item", {}) or {}
            item_id = str(item.get("id", ""))
            mark_sent(lead, sent_keys)
            duplicate_keys.update(sent_keys)
            save_sent_keys(sent_keys)
            results.append({
                "brand": lead.brand_name,
                "status": "created",
                "monday_item_id": item_id,
                "email": lead.contact_email,
            })
            print(f"Created manual energy-drink lead: {lead.brand_name} / monday {item_id}")
        except Exception as exc:
            results.append({"brand": lead.brand_name, "status": "error", "error": str(exc)[:500]})
            print(f"WARNING: manual Monday create failed for {lead.brand_name}: {exc}")

    RESULT_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    created = sum(1 for result in results if result.get("status") == "created")
    skipped = sum(1 for result in results if result.get("status") == "duplicate_skipped")
    errors = sum(1 for result in results if result.get("status") == "error")
    print(f"MANUAL_ENERGY_DRINK_BATCH: {created} created, {skipped} duplicates, {errors} errors")


if __name__ == "__main__":
    run()
