from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

from sponsor_dedupe import normalize_brand_name, normalize_domain

ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "data" / "daily_affiliates.json"
DUPLICATES_PATH = ROOT / "data" / "affiliate_duplicates.json"
TORONTO = ZoneInfo("America/Toronto")
MAX_DAILY = 10
CHUNK_SIZE = 5


def _load_json(path: Path) -> list:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid JSON in {path.name}: {exc}") from exc
    if not isinstance(payload, list):
        raise RuntimeError(f"{path.name} must contain a JSON list")
    return payload


def _identity(item: dict) -> set[str]:
    keys: set[str] = set()
    brand = normalize_brand_name(str(item.get("brand_name") or ""))
    if brand:
        keys.add(f"brand:{brand}")
    domain = normalize_domain(str(item.get("website") or item.get("brand_domain") or ""))
    if domain:
        keys.add(f"domain:{domain}")
    apply_url = str(item.get("apply_url") or "").strip()
    if apply_url:
        parsed = urlparse(apply_url)
        clean = f"{parsed.netloc.lower()}{parsed.path.rstrip('/').lower()}"
        if clean:
            keys.add(f"apply:{clean}")
    return keys


def _valid(item: dict) -> bool:
    return bool(
        str(item.get("brand_name") or "").strip()
        and str(item.get("category") or "").strip()
        and str(item.get("commission") or "").strip()
        and normalize_domain(str(item.get("website") or ""))
        and str(item.get("apply_url") or "").strip().startswith(("http://", "https://"))
    )


def select_new_affiliates(queue: list[dict], duplicates: list[dict], limit: int = MAX_DAILY) -> list[dict]:
    blocked: set[str] = set()
    for item in duplicates:
        if isinstance(item, dict):
            blocked.update(_identity(item))

    selected: list[dict] = []
    selected_keys: set[str] = set()
    for item in queue:
        if not isinstance(item, dict) or not _valid(item):
            continue
        keys = _identity(item)
        if not keys or keys & blocked or keys & selected_keys:
            continue
        selected.append(item)
        selected_keys.update(keys)
        if len(selected) >= limit:
            break
    return selected


def format_messages(items: list[dict], now: datetime) -> list[str]:
    if not items:
        return []
    date_label = f"{now.strftime('%B')} {now.day}, {now.year}"
    messages: list[str] = []
    for start in range(0, len(items), CHUNK_SIZE):
        chunk = items[start:start + CHUNK_SIZE]
        lines: list[str] = []
        if start == 0:
            lines.extend(["**DAILY CREATOR AFFILIATE OPPORTUNITIES**", f"📅 {date_label}", ""])
        for offset, item in enumerate(chunk, start=start + 1):
            website = str(item.get("website") or "").strip()
            if website and not website.startswith(("http://", "https://")):
                website = f"https://{website}"
            lines.extend(
                [
                    f"**{offset}. {str(item.get('brand_name')).strip()}**",
                    f"Category: {str(item.get('category')).strip()}",
                    f"Commission: {str(item.get('commission')).strip()}",
                    f"Website: <{website}>",
                    f"Apply: <{str(item.get('apply_url')).strip()}>",
                    "",
                ]
            )
        messages.append("\n".join(lines).strip())
    return messages


def _post(webhook_url: str, content: str) -> None:
    response = requests.post(webhook_url, json={"content": content[:1990]}, timeout=20)
    if response.status_code >= 400:
        raise RuntimeError(f"Affiliate Discord webhook error {response.status_code}: {response.text[:500]}")


def _append_duplicates(duplicates: list[dict], items: list[dict], date_posted: str) -> list[dict]:
    result = list(duplicates)
    for item in items:
        result.append(
            {
                "brand_name": str(item.get("brand_name") or "").strip(),
                "website": normalize_domain(str(item.get("website") or "")),
                "apply_url": str(item.get("apply_url") or "").strip(),
                "date_posted": date_posted,
            }
        )
    return result


def _already_posted_today(duplicates: list[dict], date_posted: str) -> bool:
    return any(
        isinstance(item, dict) and str(item.get("date_posted") or "").strip() == date_posted
        for item in duplicates
    )


def run() -> None:
    webhook = os.getenv("AFFILIATE_DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        raise ValueError("Missing AFFILIATE_DISCORD_WEBHOOK_URL")

    now = datetime.now(TORONTO)
    event_name = os.getenv("GITHUB_EVENT_NAME", "").strip()
    if event_name == "schedule" and now.hour < 10:
        print(f"Affiliate digest skipped: Toronto local hour is {now.hour}, before 10:00.")
        return

    queue = _load_json(QUEUE_PATH)
    duplicates = _load_json(DUPLICATES_PATH)
    today = now.date().isoformat()

    if event_name == "schedule" and _already_posted_today(duplicates, today):
        print(f"Affiliate digest skipped: a digest has already been posted for {today}.")
        return

    selected = select_new_affiliates(queue, duplicates, MAX_DAILY)

    if not selected:
        print("Affiliate digest: no new verified programs available today; nothing posted.")
        return

    for message in format_messages(selected, now):
        _post(webhook, message)

    updated = _append_duplicates(duplicates, selected, today)
    DUPLICATES_PATH.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
    print(f"Affiliate digest posted {len(selected)} new program(s) and updated duplicate ledger.")


if __name__ == "__main__":
    run()
