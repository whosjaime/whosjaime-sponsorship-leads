from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from discord_notifier import DiscordNotifier
from sponsor_models import SponsorLead


class DiscordNamedContactTests(unittest.TestCase):
    def test_named_contact_is_shown_when_available(self):
        lead = SponsorLead(
            brand_name="Example Brand",
            brand_domain="example.com",
            source_platform="YouTube",
            creator_name="Creator",
            creator_url="",
            creator_channel_id="",
            creator_subscribers=1000,
            creator_genre="",
            creator_tags=[],
            video_id="abcDEF12345",
            video_url="https://www.youtube.com/watch?v=abcDEF12345",
            video_title="Sponsored video",
            sponsored_date="2026-08-09",
            evidence="evidence",
            contact_name="Jane Smith",
            contact_title="Creator Partnerships",
            contact_email="jane@example.com",
        )
        message = DiscordNotifier.new_lead_message(lead)
        self.assertIn("Jane Smith — Creator Partnerships", message)
        self.assertIn("jane@example.com", message)


if __name__ == "__main__":
    unittest.main()
