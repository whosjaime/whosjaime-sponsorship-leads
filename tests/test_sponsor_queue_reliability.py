from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sponsor_config import load_sponsor_config
from sponsor_models import SponsorLead


class SponsorQueueReliabilityTests(unittest.TestCase):
    def test_discovery_config_does_not_require_discord_webhook(self):
        env = {
            "YOUTUBE_API_KEY": "youtube-key",
            "SPONSOR_MONDAY_TOKEN": "monday-key",
            "DISCORD_WEBHOOK_URL": "",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_sponsor_config(require_discord=False)
            self.assertEqual(config.youtube_api_key, "youtube-key")
            self.assertEqual(config.monday_token, "monday-key")
            self.assertEqual(config.discord_webhook_url, "")

    def test_delivery_config_still_requires_discord_webhook(self):
        env = {
            "YOUTUBE_API_KEY": "youtube-key",
            "SPONSOR_MONDAY_TOKEN": "monday-key",
            "DISCORD_WEBHOOK_URL": "",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(ValueError, "DISCORD_WEBHOOK_URL"):
                load_sponsor_config()

    def test_researched_lead_is_saved_even_when_youtube_batch_fails(self):
        import run_sponsor_discovery_batch as batch

        lead = SponsorLead(
            brand_name="Example Brand",
            brand_domain="example.com",
            source_platform="YouTube",
            creator_name="Creator",
            creator_url="",
            creator_channel_id="creator-id",
            creator_subscribers=1000,
            creator_genre="Gaming",
            creator_tags=[],
            video_id="video-id",
            video_url="https://www.youtube.com/watch?v=video-id",
            video_title="Sponsored video",
            sponsored_date="2026-08-09",
            evidence="Sponsored by Example Brand",
            sponsor_category="Gaming",
            contact_email="partners@example.com",
            lead_score=100,
            brand_key="domain:example.com",
        )
        config = SimpleNamespace(
            monday_token="monday",
            monday_board_id=18424367188,
            monday_group_id="topics",
            youtube_api_key="youtube",
            search_region="US",
            search_language="en",
            creatordb_api_key="",
            creatordb_page_size=50,
            max_sponsor_age_days=30,
            min_lead_score=70,
        )
        monday = Mock()
        monday.load_existing_index.return_value = Mock()
        youtube = Mock()
        # Creator hydration is best-effort and must not weaken the original guarantee:
        # researched leads still survive a YouTube outage.
        youtube.fetch_videos.return_value = []
        youtube.discover_batch.side_effect = RuntimeError("temporary YouTube failure")
        researched = Mock()
        researched.load.return_value = [lead]

        with (
            patch.object(batch, "load_sponsor_config", return_value=config),
            patch.object(batch, "SponsorMondayClient", return_value=monday),
            patch.object(batch, "YouTubeSponsorScanner", return_value=youtube),
            patch.object(batch, "ResearchedSponsorSource", return_value=researched),
            patch.object(batch, "BrandEnricher", return_value=Mock()),
            patch.object(batch, "load_queue", return_value=[]),
            patch.object(batch, "_enrich_lead", side_effect=lambda item, _: item),
            patch.object(batch, "_is_recent_sponsorship", return_value=True),
            patch.object(batch, "_is_target_lead", return_value=True),
            patch.object(batch, "_blocked", return_value=False),
            patch.object(batch, "_priority_score", return_value=100),
            patch.object(batch, "save_queue") as save_queue,
        ):
            batch.run()

        saved = save_queue.call_args.args[0]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].brand_name, "Example Brand")

    def test_daily_batch_runs_after_research_window(self):
        workflow = Path(".github/workflows/discover-sponsor-queue.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "15 10 * * *"', workflow)
        self.assertIn('timezone: "America/Toronto"', workflow)
        self.assertNotIn("discord_sponsor_queue_status.py", workflow)


if __name__ == "__main__":
    unittest.main()
