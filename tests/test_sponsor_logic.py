from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from creator_classifier import classify_creator
from run_sponsor_scan import _is_recent_sponsorship, _is_target_lead, _priority_score
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

    def test_target_niches_are_eligible(self):
        for category in ["Gaming", "Consumer Tech", "Food & Beverage"]:
            lead = SimpleNamespace(
                sponsor_category=category,
                brand_name="Good Brand",
                brand_domain="goodbrand.com",
                sponsor_subcategory="",
            )
            self.assertTrue(_is_target_lead(lead), category)

    def test_digital_tech_services_are_not_target_leads(self):
        for category, subcategory in [
            ("Software / SaaS", "AI / Productivity"),
            ("Software / SaaS", "Web Hosting"),
            ("Cybersecurity / VPN", "VPN"),
            ("Cybersecurity / VPN", "Password Manager"),
        ]:
            lead = SimpleNamespace(
                sponsor_category=category,
                brand_name="Digital Service",
                brand_domain="digitalservice.com",
                sponsor_subcategory=subcategory,
            )
            self.assertFalse(_is_target_lead(lead), f"{category} / {subcategory}")

    def test_digital_category_is_rejected_even_if_subcategory_looks_like_hardware(self):
        lead = SimpleNamespace(
            sponsor_category="Software / SaaS",
            brand_name="Misclassified Software Brand",
            brand_domain="softwarebrand.com",
            sponsor_subcategory="Computer Hardware",
        )
        self.assertFalse(_is_target_lead(lead))

    def test_festival_is_rejected_even_if_other_text_looks_good(self):
        festival = SimpleNamespace(
            sponsor_category="Entertainment",
            brand_name="Love Groove Festival",
            brand_domain="lovegroovefestival.com",
            sponsor_subcategory="Live Event",
        )
        self.assertFalse(_is_target_lead(festival))

    def test_creator_niche_does_not_make_off_niche_sponsor_eligible(self):
        sponsor = SimpleNamespace(
            sponsor_category="Entertainment",
            brand_name="Random Festival",
            brand_domain="randomfestival.com",
            sponsor_subcategory="",
            creator_genre="Gaming",
        )
        self.assertFalse(_is_target_lead(sponsor))

    def test_priority_niches_rank_above_generic_sponsors(self):
        gaming = SimpleNamespace(
            sponsor_category="Gaming",
            brand_name="New Gaming Brand",
            brand_domain="newgamingbrand.com",
            sponsor_subcategory="",
            sponsored_date=date.today().isoformat(),
            contact_email="",
            contact_name="",
        )
        generic = SimpleNamespace(
            sponsor_category="Other",
            brand_name="Generic Brand",
            brand_domain="genericbrand.com",
            sponsor_subcategory="",
            sponsored_date=date.today().isoformat(),
            contact_email="",
            contact_name="",
        )
        self.assertGreater(_priority_score(gaming), _priority_score(generic))

    def test_recent_sponsorship_is_eligible(self):
        lead = SimpleNamespace(sponsored_date=(date.today() - timedelta(days=7)).isoformat())
        self.assertTrue(_is_recent_sponsorship(lead, 30))

    def test_old_sponsorship_is_rejected(self):
        lead = SimpleNamespace(sponsored_date=(date.today() - timedelta(days=31)).isoformat())
        self.assertFalse(_is_recent_sponsorship(lead, 30))

    def test_undated_sponsorship_is_rejected(self):
        lead = SimpleNamespace(sponsored_date="")
        self.assertFalse(_is_recent_sponsorship(lead, 30))

    def test_marketing_subdomain_normalizes_to_brand_domain(self):
        self.assertEqual(normalize_domain("https://go.nordvpn.com/deal"), "nordvpn.com")


if __name__ == "__main__":
    unittest.main()
