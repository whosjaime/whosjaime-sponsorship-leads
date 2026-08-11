from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import run_sponsor_queue_dispatch as dispatch
from sponsor_models import SponsorLead
from sponsor_queue import (
    is_duplicate,
    load_duplicate_keys,
    load_sent_keys,
    mark_sent,
    save_sent_keys,
)


def _lead() -> SponsorLead:
    return SponsorLead(
        brand_name="Example Brand",
        brand_domain="example.com",
        source_platform="YouTube",
        creator_name="Creator",
        creator_url="https://youtube.com/channel/example",
        creator_channel_id="example",
        creator_subscribers=100000,
        creator_genre="Gaming",
        creator_tags=[],
        video_id="video-id",
        video_url="https://youtube.com/watch?v=video-id",
        video_title="Sponsored video",
        sponsored_date="2026-08-10",
        evidence="Sponsored by Example Brand",
        sponsor_category="Gaming",
        contact_email="partners@example.com",
        lead_score=100,
        brand_key="domain:example.com",
    )


class SponsorSentLedgerTests(unittest.TestCase):
    def test_sent_keys_round_trip_and_block_same_brand(self):
        lead = _lead()
        keys: set[str] = set()
        mark_sent(lead, keys)
        self.assertTrue(is_duplicate(lead, keys))
        self.assertIn("brand:examplebrand", keys)
        self.assertIn("domain:example.com", keys)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sent.json"
            save_sent_keys(keys, path)
            loaded = load_sent_keys(path)
        self.assertEqual(loaded, keys)

    def test_duplicate_keys_include_permanent_github_blocklist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sent.json"
            save_sent_keys(set(), path)
            duplicate_keys = load_duplicate_keys(path)
        blocked = SponsorLead(brand_name="Notion", brand_domain="notion.so")
        self.assertTrue(is_duplicate(blocked, duplicate_keys))

    def test_hourly_dispatch_never_touches_monday_for_duplicate_in_github_ledger(self):
        lead = _lead()
        config = SimpleNamespace(
            monday_token="monday",
            monday_board_id=18424367188,
            monday_group_id="topics",
            discord_webhook_url="https://discord.invalid/webhook",
            youtube_api_key="youtube",
            search_region="US",
            search_language="en",
            max_sponsor_age_days=30,
            min_lead_score=70,
        )
        monday = Mock()
        discord = Mock()

        with (
            patch.object(dispatch, "load_sponsor_config", return_value=config),
            patch.object(dispatch, "SponsorMondayClient", return_value=monday),
            patch.object(dispatch, "DiscordNotifier", return_value=discord),
            patch.object(dispatch, "YouTubeSponsorScanner", return_value=Mock()),
            patch.object(dispatch, "load_queue", return_value=[lead]),
            patch.object(dispatch, "load_sent_keys", return_value={"domain:example.com"}),
            patch.object(dispatch, "load_duplicate_keys", return_value={"domain:example.com"}),
            patch.object(dispatch, "save_queue") as save_queue,
            patch.object(dispatch, "save_sent_keys") as save_sent_keys,
        ):
            dispatch.run()

        monday.load_existing_index.assert_not_called()
        monday.create_lead.assert_not_called()
        discord.send_new_lead.assert_not_called()
        save_queue.assert_called_once_with([])
        save_sent_keys.assert_called_once()

    def test_new_delivery_records_github_key_without_reading_monday_for_duplicates(self):
        lead = _lead()
        config = SimpleNamespace(
            monday_token="monday",
            monday_board_id=18424367188,
            monday_group_id="topics",
            discord_webhook_url="https://discord.invalid/webhook",
            youtube_api_key="youtube",
            search_region="US",
            search_language="en",
            max_sponsor_age_days=30,
            min_lead_score=70,
        )
        monday = Mock()
        monday.create_lead.return_value = {"data": {"create_item": {"id": "123"}}}
        discord = Mock()

        with (
            patch.object(dispatch, "load_sponsor_config", return_value=config),
            patch.object(dispatch, "SponsorMondayClient", return_value=monday),
            patch.object(dispatch, "DiscordNotifier", return_value=discord),
            patch.object(dispatch, "YouTubeSponsorScanner", return_value=Mock()),
            patch.object(dispatch, "load_queue", return_value=[lead]),
            patch.object(dispatch, "load_sent_keys", return_value=set()),
            patch.object(dispatch, "load_duplicate_keys", return_value=set()),
            patch.object(dispatch, "save_queue"),
            patch.object(dispatch, "save_sent_keys") as save_sent_keys,
            patch.object(dispatch, "_hydrate_creator_metrics"),
            patch.object(dispatch, "_is_recent_sponsorship", return_value=True),
            patch.object(dispatch, "_is_target_lead", return_value=True),
        ):
            dispatch.run()

        monday.load_existing_index.assert_not_called()
        monday.create_lead.assert_called_once_with(lead)
        discord.send_new_lead.assert_called_once_with(lead)
        saved_sets = [call.args[0] for call in save_sent_keys.call_args_list]
        self.assertTrue(any("domain:example.com" in keys for keys in saved_sets))

    def test_workflow_persists_ledger_even_after_downstream_failure(self):
        workflow = Path(".github/workflows/scan-sponsors.yml").read_text(encoding="utf-8")
        self.assertIn("data/sent_sponsor_keys.json", workflow)
        self.assertIn("if: always()", workflow)
        self.assertIn("git pull --rebase origin main", workflow)


if __name__ == "__main__":
    unittest.main()
