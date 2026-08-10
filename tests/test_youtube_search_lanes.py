from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from youtube_sponsor_scanner import SEARCH_LANES, YouTubeSponsorScanner


class YouTubeSearchLaneTests(unittest.TestCase):
    def test_hourly_discovery_uses_exactly_three_search_lanes(self):
        self.assertEqual(len(SEARCH_LANES), 3)

    def test_disclosure_terms_are_combined_with_boolean_or(self):
        disclosure = next(query for name, query, _ in SEARCH_LANES if name == "sponsor-disclosures")
        self.assertIn("|", disclosure)
        self.assertIn('"sponsored by"', disclosure)
        self.assertIn("#sponsored", disclosure)

    def test_two_lanes_use_paid_placement_filter(self):
        paid_lanes = [name for name, _, paid_only in SEARCH_LANES if paid_only]
        self.assertEqual(len(paid_lanes), 2)
        self.assertIn("paid-placement", paid_lanes)
        self.assertIn("target-niche-paid", paid_lanes)

    def test_discover_video_ids_calls_search_three_times_and_dedupes(self):
        scanner = YouTubeSponsorScanner("dummy-key")
        calls = []

        def fake_search(lookback_hours, query="", paid_only=False):
            calls.append((lookback_hours, query, paid_only))
            if len(calls) == 1:
                return ["a", "b"]
            if len(calls) == 2:
                return ["b", "c"]
            return ["c", "d"]

        scanner._search = fake_search
        ids = scanner.discover_video_ids(720)

        self.assertEqual(len(calls), 3)
        self.assertEqual(ids, ["a", "b", "c", "d"])
        self.assertTrue(all(call[0] == 720 for call in calls))


if __name__ == "__main__":
    unittest.main()
