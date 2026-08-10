from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from researched_sponsor_source import ResearchedSponsorSource
from run_sponsor_scan import _score_lead


class ResearchedSponsorSourceTests(unittest.TestCase):
    def _load(self, payload):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "researched_sponsors.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return ResearchedSponsorSource(path).load()

    def test_valid_researched_sponsor_becomes_lead(self):
        leads = self._load([
            {
                "brand_name": "Example Gaming Gear",
                "brand_domain": "https://www.examplegaming.com/deal",
                "sponsored_date": date.today().isoformat(),
                "video_url": "https://www.youtube.com/watch?v=abcDEF12345",
                "creator_name": "Example Creator",
                "creator_subscribers": 500000,
            }
        ])
        self.assertEqual(len(leads), 1)
        lead = leads[0]
        self.assertEqual(lead.brand_domain, "examplegaming.com")
        self.assertEqual(lead.video_id, "abcDEF12345")
        self.assertIn("Daily researched sponsorship", lead.signals)
        self.assertIn("verified public sponsorship evidence", lead.signals)

    def test_missing_youtube_evidence_is_rejected(self):
        leads = self._load([
            {
                "brand_name": "Example Gaming Gear",
                "brand_domain": "examplegaming.com",
                "sponsored_date": date.today().isoformat(),
                "video_url": "https://example.com/blog/sponsor",
            }
        ])
        self.assertEqual(leads, [])

    def test_duplicate_brand_video_pair_is_deduped_inside_queue(self):
        item = {
            "brand_name": "Example Gaming Gear",
            "brand_domain": "examplegaming.com",
            "sponsored_date": date.today().isoformat(),
            "video_url": "https://youtu.be/abcDEF12345",
        }
        leads = self._load([item, item])
        self.assertEqual(len(leads), 1)

    def test_researched_signals_clear_normal_score_threshold_after_enrichment(self):
        lead = self._load([
            {
                "brand_name": "Example Gaming Gear",
                "brand_domain": "examplegaming.com",
                "sponsored_date": date.today().isoformat(),
                "video_url": "https://www.youtube.com/watch?v=abcDEF12345",
            }
        ])[0]
        lead.contact_email = "partnerships@examplegaming.com"
        lead.sponsor_category = "Gaming"
        self.assertGreaterEqual(_score_lead(lead), 70)


if __name__ == "__main__":
    unittest.main()
