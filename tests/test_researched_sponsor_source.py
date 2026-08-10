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
from run_sponsor_scan import _enrich_lead, _priority_score, _score_lead


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

    def test_named_same_domain_work_email_is_preserved(self):
        lead = self._load([
            {
                "brand_name": "Example Gaming Gear",
                "brand_domain": "examplegaming.com",
                "sponsored_date": date.today().isoformat(),
                "video_url": "https://www.youtube.com/watch?v=abcDEF12345",
                "contact_name": "Jane Smith",
                "contact_title": "Creator Partnerships",
                "contact_email": "jane@examplegaming.com",
                "contact_source_url": "https://examplegaming.com/team",
            }
        ])[0]
        self.assertEqual(lead.contact_name, "Jane Smith")
        self.assertEqual(lead.contact_title, "Creator Partnerships")
        self.assertEqual(lead.contact_email, "jane@examplegaming.com")
        self.assertEqual(lead.contact_source, "https://examplegaming.com/team")
        self.assertIn("verified named public work email", lead.signals)

    def test_cross_domain_researched_email_is_discarded(self):
        lead = self._load([
            {
                "brand_name": "Example Gaming Gear",
                "brand_domain": "examplegaming.com",
                "sponsored_date": date.today().isoformat(),
                "video_url": "https://www.youtube.com/watch?v=abcDEF12345",
                "contact_name": "Jane Smith",
                "contact_title": "Creator Partnerships",
                "contact_email": "jane@unrelatedmail.com",
                "contact_source_url": "https://examplegaming.com/team",
            }
        ])[0]
        self.assertEqual(lead.contact_email, "")
        self.assertEqual(lead.contact_name, "")
        self.assertEqual(lead.contact_title, "")

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

    def test_named_contact_survives_generic_website_enrichment(self):
        lead = self._load([
            {
                "brand_name": "Example Gaming Gear",
                "brand_domain": "examplegaming.com",
                "sponsored_date": date.today().isoformat(),
                "video_url": "https://www.youtube.com/watch?v=abcDEF12345",
                "contact_name": "Jane Smith",
                "contact_title": "Influencer Marketing",
                "contact_email": "jane@examplegaming.com",
                "contact_source_url": "https://examplegaming.com/team",
            }
        ])[0]

        class FakeEnricher:
            def enrich(self, domain):
                return {
                    "domain": domain,
                    "contact_email": "info@examplegaming.com",
                    "email_type": "Generic",
                    "contact_source": "https://examplegaming.com/contact",
                    "category": "Gaming",
                    "subcategory": "Gaming Gear",
                }

        enriched = _enrich_lead(lead, FakeEnricher())
        self.assertEqual(enriched.contact_email, "jane@examplegaming.com")
        self.assertEqual(enriched.contact_name, "Jane Smith")
        self.assertEqual(enriched.contact_title, "Influencer Marketing")
        self.assertEqual(enriched.contact_source, "https://examplegaming.com/team")

    def test_named_contact_ranks_above_generic_contact(self):
        named = self._load([
            {
                "brand_name": "Named Contact Brand",
                "brand_domain": "namedgaming.com",
                "sponsored_date": date.today().isoformat(),
                "video_url": "https://www.youtube.com/watch?v=abcDEF12345",
                "contact_name": "Jane Smith",
                "contact_title": "Creator Partnerships",
                "contact_email": "jane@namedgaming.com",
            }
        ])[0]
        named.sponsor_category = "Gaming"

        generic = self._load([
            {
                "brand_name": "Generic Contact Brand",
                "brand_domain": "genericgaming.com",
                "sponsored_date": date.today().isoformat(),
                "video_url": "https://www.youtube.com/watch?v=xyzDEF12345",
            }
        ])[0]
        generic.sponsor_category = "Gaming"
        generic.contact_email = "info@genericgaming.com"

        self.assertGreater(_priority_score(named), _priority_score(generic))


if __name__ == "__main__":
    unittest.main()
