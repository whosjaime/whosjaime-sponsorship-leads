from __future__ import annotations

import os
import re
from pathlib import Path

import requests

SUMMARY_RE = re.compile(
    r"Sponsor scan complete: (?P<created>\d+)/(?P<target>\d+) new leads, "
    r"(?P<duplicates>\d+) duplicates/blocked brands, (?P<rejected>\d+) rejected, "
    r"(?P<researched>\d+) daily-research candidates considered, "
    r"(?P<videos>\d+) YouTube videos scanned, "
    r"(?P<creatordb>\d+) optional CreatorDB sponsor events considered\."
)


def main() -> None:
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        raise SystemExit("DISCORD_WEBHOOK_URL is required for sponsor scan status")

    log_path = Path(os.getenv("SPONSOR_SCAN_LOG", "sponsor_scan.log"))
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    match = SUMMARY_RE.search(text)
    if not match:
        raise RuntimeError("Could not parse sponsor scan summary from sponsor_scan.log")

    values = {key: int(value) for key, value in match.groupdict().items()}
    if values["created"] > 0:
        return

    content = (
        "🟡 **SPONSOR SCAN RAN — 0 NEW LEADS**\n\n"
        f"🎥 **YouTube videos scanned:** {values['videos']}\n"
        f"🔁 **Duplicates/blocked:** {values['duplicates']}\n"
        f"🚫 **Rejected by current gates:** {values['rejected']}\n"
        f"🔎 **Daily research candidates:** {values['researched']}\n\n"
        "The scanner completed normally, but nothing qualified for Monday/Discord this run."
    )

    response = requests.post(
        webhook_url,
        json={"content": content[:1990]},
        timeout=20,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Discord zero-lead status error {response.status_code}: {response.text[:500]}"
        )


if __name__ == "__main__":
    main()
