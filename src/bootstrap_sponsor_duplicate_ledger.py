from __future__ import annotations

import os

from sponsor_monday_client import SponsorMondayClient
from sponsor_queue import load_sent_keys, save_sent_keys

DEFAULT_BOARD_ID = 18424367188
DEFAULT_GROUP_ID = "topics"


def _monday_token() -> str:
    token = (
        os.getenv("SPONSOR_MONDAY_TOKEN", "").strip()
        or os.getenv("SPONSOR_MONDAY_API_KEY", "").strip()
    )
    if not token:
        raise ValueError("Missing SPONSOR_MONDAY_TOKEN for one-time duplicate bootstrap")
    return token


def run() -> None:
    monday = SponsorMondayClient(
        _monday_token(),
        int(os.getenv("SPONSOR_MONDAY_BOARD_ID", "") or DEFAULT_BOARD_ID),
        os.getenv("SPONSOR_MONDAY_GROUP_ID", DEFAULT_GROUP_ID).strip() or DEFAULT_GROUP_ID,
    )
    sent_keys = load_sent_keys()
    before = len(sent_keys)

    # One-time migration only: copy the historical Monday brand identity index into the
    # GitHub file. Normal discovery/dispatch never calls Monday for duplicate decisions.
    historical = monday.load_existing_index()
    sent_keys.update(historical.brand_keys)
    save_sent_keys(sent_keys)

    print(
        f"GitHub sponsor duplicate bootstrap: {before} existing keys -> "
        f"{len(sent_keys)} keys after historical Monday migration."
    )


if __name__ == "__main__":
    run()
