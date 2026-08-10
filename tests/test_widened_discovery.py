from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brand_enrichment import BrandEnricher, COMMON_CONTACT_PATHS
from sponsor_detector import detect_sponsors
from sponsor_models import VideoRecord
from youtube_sponsor_scanner import SEARCH_LANES, SPONSOR_DISCLOSURE_QUERY, TARGET_PAID_QUERY


class WidenedSponsorDiscoveryTests(unittest.TestCase):
    def _video(self, description: str) -> VideoRecord:
        return VideoRecord(
            platform="YouTube",
            video_id="wide123",
            video_url="https://www.youtube.com/watch?v=wide123",
            title="New Tech Setup",
            description=description,
            published_at="2026-08-09T12:00:00Z",
            channel_id="creator-channel",
            channel_title="Creator",
            tags=[],
            category_id="28",
            paid_product_placement=True,
        )

    def test_three_search_lanes_are_preserved(self):
        self.assertEqual(len(SEARCH_LANES), 3)

    def test_new_disclosure_phrases_are_in_search_query(self):
        for phrase in ["partnered with", "paid partnership", "presented by", "supported by", "powered by"]:
            self.assertIn(phrase, SPONSOR_DISCLOSURE_QUERY)

    def test_target_paid_query_is_broader_but_on_niche(self):
        for keyword in ["gpu", "browser", "cybersecurity", "protein", "hydration", "earbuds"]:
            self.assertIn(keyword, TARGET_PAID_QUERY)

    def test_presented_by_phrase_detects_sponsor(self):
        video = self._video("This video is presented by NovaGear.\nhttps://novagear.com/creator #ad")
        detections = detect_sponsors(video, {})
        self.assertTrue(detections)
        self.assertEqual(detections[0].brand_name, "NovaGear")
        self.assertEqual(detections[0].domain, "novagear.com")

    def test_paid_partnership_phrase_detects_sponsor(self):
        video = self._video("Paid partnership with CloudPilot\nhttps://cloudpilot.com/deal")
        detections = detect_sponsors(video, {})
        self.assertTrue(detections)
        self.assertEqual(detections[0].brand_name, "CloudPilot")

    def test_more_contact_paths_are_checked(self):
        for path in ["/partnerships", "/brand-partnerships", "/creator-partnerships", "/creators", "/ambassadors"]:
            self.assertIn(path, COMMON_CONTACT_PATHS)

    def test_expanded_target_category_classification(self):
        category, _ = BrandEnricher._classify("AI productivity browser software for creators and teams")
        self.assertEqual(category, "Software / SaaS")
        category, _ = BrandEnricher._classify("GPU graphics card computer hardware for gaming PCs")
        self.assertEqual(category, "Consumer Tech")
        category, _ = BrandEnricher._classify("protein snack jerky and hydration drinks")
        self.assertEqual(category, "Food & Beverage")


if __name__ == "__main__":
    unittest.main()
