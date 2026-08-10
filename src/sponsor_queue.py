from __future__ import annotations

import json
from pathlib import Path

from sponsor_models import SponsorLead

QUEUE_PATH = Path("data/sponsor_queue.json")
MAX_QUEUE_SIZE = 24


def load_queue(path: Path = QUEUE_PATH) -> list[SponsorLead]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, list):
        return []

    leads: list[SponsorLead] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            leads.append(SponsorLead(**item))
        except TypeError:
            continue
    return leads


def save_queue(leads: list[SponsorLead], path: Path = QUEUE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [lead.as_dict() for lead in leads[:MAX_QUEUE_SIZE]]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def merge_unique(existing: list[SponsorLead], incoming: list[SponsorLead]) -> list[SponsorLead]:
    merged: list[SponsorLead] = []
    seen: set[str] = set()
    for lead in [*existing, *incoming]:
        identity = (lead.brand_key or lead.brand_domain or lead.brand_name).strip().lower()
        if not identity or identity in seen:
            continue
        seen.add(identity)
        merged.append(lead)
        if len(merged) >= MAX_QUEUE_SIZE:
            break
    return merged
