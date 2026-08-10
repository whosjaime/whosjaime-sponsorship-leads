from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from creatomap_active_sponsors import CreatomapActiveSponsorSource


class CreatomapSourceTests(unittest.TestCase):
    def setUp(self):
        self.source = CreatomapActiveSponsorSource(max_brands=10)

    def test_brand_seed_accepts_target_brand_shape(self):
        seed = self.source._brand_seed(
            {
                "name": "Fresh Gaming Brand",
                "slug": "fresh-gaming-brand",
                "category": "gaming",
                "domain": "https://freshgaming.com/deals",
            }
        )
        self.assertIsNotNone(seed)
        self.assertEqual(seed["slug"], "fresh-gaming-brand")
        self.assertEqual(seed["domain"], "freshgaming.com")

    def test_recent_nested_video_becomes_sponsor_lead(self):
        recent = (date.today() - timedelta(days=4)).isoformat()
        detail = {
            "brand": {
                "name": "Fresh Gaming Brand",
                "domain": "freshgaming.com",
                "sponsoredCreators": [
                    {
                        "creator": {
                            "displayName": "Example Creator",
                            "channelId": "UC123456789",
                            "subscriberCount": 1200000,
                        },
                        "latestSponsorship": recent,
                        "videoUrl": "https://www.youtube.com/watch?v=abcDEF12345",
                        "videoTitle": "I Tried This New Game",
                    }
                ],
            }
        }
        seed = {
            "name": "Fresh Gaming Brand",
            "slug": "fresh-gaming-brand",
            "category": "gaming",
            "domain": "freshgaming.com",
        }
        lead = self.source._lead_from_detail(seed, detail, 30)
        self.assertIsNotNone(lead)
        self.assertEqual(lead.brand_name, "Fresh Gaming Brand")
        self.assertEqual(lead.brand_domain, "freshgaming.com")
        self.assertEqual(lead.creator_name, "Example Creator")
        self.assertEqual(lead.sponsored_date, recent)
        self.assertEqual(lead.source_platform, "YouTube")
        self.assertIn("youtube.com/watch", lead.video_url)
        self.assertIn("Creatomap recent sponsorship", lead.signals)

    def test_stale_video_is_rejected(self):
        stale = (date.today() - timedelta(days=45)).isoformat()
        detail = {
            "sponsorships": [
                {
                    "sponsoredDate": stale,
                    "videoUrl": "https://www.youtube.com/watch?v=abcDEF12345",
                    "creatorName": "Old Creator",
                }
            ]
        }
        seed = {
            "name": "Old Brand",
            "slug": "old-brand",
            "category": "tech",
            "domain": "oldbrand.com",
        }
        self.assertIsNone(self.source._lead_from_detail(seed, detail, 30))

    def test_profile_update_date_alone_is_not_sponsorship_evidence(self):
        detail = {
            "name": "Fresh Gaming Brand",
            "updated_at": date.today().isoformat(),
            "domain": "freshgaming.com",
        }
        seed = {
            "name": "Fresh Gaming Brand",
            "slug": "fresh-gaming-brand",
            "category": "gaming",
            "domain": "freshgaming.com",
        }
        self.assertIsNone(self.source._lead_from_detail(seed, detail, 30))

    def test_youtube_video_id_builds_evidence_url(self):
        obj = {"videoId": "abcDEF12345"}
        self.assertEqual(
            self.source._youtube_url(obj),
            "https://www.youtube.com/watch?v=abcDEF12345",
        )


if __name__ == "__main__":
    unittest.main()
