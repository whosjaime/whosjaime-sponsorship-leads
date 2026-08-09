from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from creator_classifier import classify_creator
from run_sponsor_scan import _priority_score
from sponsor_dedupe import ExistingSponsorIndex, normalize_domain
from sponsor_detector import detect_sponsors, to_sponsor_lead
from sponsor_models import ChannelRecord, VideoRecord


class SponsorScannerTests(unittest.TestCase):
    def _video(self, description: str) -> VideoRecord:
        return VideoRecord(
            platform="YouTube",
            video_id="abc123",
            video_url="https://www.youtube.com/watch?v=abc123",
            title="Minecraft Challenge",
            description=description,
            published_at="2026-08-09T12:00:00Z",
            channel_id="creator-channel",
            channel_title="Gaming Creator",
            tags=["minecraft", "gaming", "challenge"],
            category_id="20",
            paid_product_placement=True,
        )

    def test_explicit_sponsor_and_domain_are_extracted(self):
        video = self._video("Thanks to NordVPN for sponsoring today's video!\nGet the deal: https://nordvpn.com/creator #ad")
        detections = detect_sponsors(video, {})
        self.assertTrue(detections)
        self.assertEqual(detections[0].brand_name, "NordVPN")
        self.assertEqual(detections[0].domain, "nordvpn.com")

    def test_creator_is_classified_as_gaming(self):
        video = self._video("Minecraft survival challenge with friends")
        channel = ChannelRecord("creator-channel", "Gaming Creator", "Minecraft and gaming videos every week", subscriber_count=500000)
        genre, tags = classify_creator(video, channel)
        self.assertEqual(genre, "Gaming")
        self.assertIn("Minecraft", tags)

    def test_existing_domain_blocks_repeat_brand(self):
        video = self._video("This video is sponsored by NordVPN.\nhttps://nordvpn.com/creator")
        detection = detect_sponsors(video, {})[0]
        lead = to_sponsor_lead(video, None, detection, "Gaming", ["Gaming"])
        index = ExistingSponsorIndex(brand_keys={"domain:nordvpn.com"})
        self.assertTrue(index.is_duplicate_brand(lead))

    def test_permanent_blocklist_blocks_brand_even_if_monday_is_empty(self):
        video = self._video("This video is sponsored by NordVPN.\nhttps://nordvpn.com/creator")
        detection = detect_sponsors(video, {})[0]
        lead = to_sponsor_lead(video, None, detection, "Gaming", ["Gaming"])
        index = ExistingSponsorIndex()
        self.assertTrue(index.is_duplicate_brand(lead))

    def test_priority_niches_rank_above_generic_sponsors(self):
        gaming = SimpleNamespace(
            sponsor_category="Gaming",
            creator_genre="Gaming",
            brand_name="New Gaming Brand",
            brand_domain="newgamingbrand.com",
            sponsor_subcategory="",
        )
        generic = SimpleNamespace(
            sponsor_category="Other",
            creator_genre="Entertainment",
            brand_name="Generic Brand",
            brand_domain="genericbrand.com",
            sponsor_subcategory="",
        )
        self.assertGreater(_priority_score(gaming), _priority_score(generic))

    def test_marketing_subdomain_normalizes_to_brand_domain(self):
        self.assertEqual(normalize_domain("https://go.nordvpn.com/deal"), "nordvpn.com")


if __name__ == "__main__":
    unittest.main()
