from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import run_sponsor_queue_dispatch as dispatch
from sponsor_models import SponsorLead


class SponsorDispatchSubscriberTests(unittest.TestCase):
    def test_missing_subscribers_are_hydrated_before_monday_and_discord(self):
        lead = SponsorLead(
            brand_name="Example Brand",
            brand_domain="example.com",
            source_platform="YouTube",
            creator_name="Example Creator",
            creator_url="",
            creator_channel_id="",
            creator_subscribers=0,
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

        index = Mock()
        index.brand_keys = set()
        monday = Mock()
        monday.load_existing_index.return_value = index

        def create_lead(item):
            self.assertEqual(item.creator_subscribers, 321456)
            self.assertEqual(item.creator_channel_id, "UC_CREATOR")
            return {"data": {"create_item": {"id": "123"}}}

        monday.create_lead.side_effect = create_lead
        discord = Mock()
        youtube = Mock()

        def hydrate(items, _youtube):
            items[0].creator_subscribers = 321456
            items[0].creator_channel_id = "UC_CREATOR"
            items[0].creator_url = "https://www.youtube.com/channel/UC_CREATOR"

        with (
            patch.object(dispatch, "load_sponsor_config", return_value=config),
            patch.object(dispatch, "SponsorMondayClient", return_value=monday),
            patch.object(dispatch, "DiscordNotifier", return_value=discord),
            patch.object(dispatch, "YouTubeSponsorScanner", return_value=youtube),
            patch.object(dispatch, "load_queue", return_value=[lead]),
            patch.object(dispatch, "load_sent_keys", return_value=set()),
            patch.object(dispatch, "save_queue") as save_queue,
            patch.object(dispatch, "save_sent_keys") as save_sent_keys,
            patch.object(dispatch, "_hydrate_creator_metrics", side_effect=hydrate) as hydration,
            patch.object(dispatch, "_is_recent_sponsorship", return_value=True),
            patch.object(dispatch, "_is_target_lead", return_value=True),
            patch.object(dispatch, "_blocked", return_value=False),
        ):
            dispatch.run()

        hydration.assert_called_once()
        monday.create_lead.assert_called_once()
        discord.send_new_lead.assert_called_once()
        sent_lead = discord.send_new_lead.call_args.args[0]
        self.assertEqual(sent_lead.creator_subscribers, 321456)
        save_queue.assert_called_once_with([])
        save_sent_keys.assert_called_once()
        saved_keys = save_sent_keys.call_args.args[0]
        self.assertIn("domain:example.com", saved_keys)


if __name__ == "__main__":
    unittest.main()
