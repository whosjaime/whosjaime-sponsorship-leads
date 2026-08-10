from __future__ import annotations

import os
import re

import requests


SUMMARY_RE = re.compile(
    r"SPONSOR_QUEUE_READY:\s*(\d+) queued,\s*(\d+) YouTube videos hydrated,\s*"
    r"(\d+) duplicate/blocked,\s*(\d+) rejected\."
)


def main() -> None:
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    log_path = os.getenv("SPONSOR_BATCH_LOG", "sponsor_batch.log").strip()
    if not webhook_url:
        raise SystemExit("DISCORD_WEBHOOK_URL is required")

    try:
        log = open(log_path, "r", encoding="utf-8").read()
    except OSError:
        log = ""

    match = SUMMARY_RE.search(log)
    if match:
        queued, videos, duplicates, rejected = match.groups()
        content = (
            "📦 **SPONSOR QUEUE READY**\n\n"
            f"**{queued}** qualified sponsors are queued for hourly delivery.\n"
            f"YouTube videos checked: **{videos}**\n"
            f"Duplicate/blocked: **{duplicates}**\n"
            f"Rejected by quality gates: **{rejected}**"
        )
    else:
        content = (
            "📦 **SPONSOR QUEUE DISCOVERY FINISHED**\n\n"
            "The daily sponsor batch completed, but its queue summary could not be parsed."
        )

    response = requests.post(webhook_url, json={"content": content[:1990]}, timeout=20)
    if response.status_code >= 400:
        raise RuntimeError(
            f"Discord queue status error {response.status_code}: {response.text[:500]}"
        )


if __name__ == "__main__":
    main()
