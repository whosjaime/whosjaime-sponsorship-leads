from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from creatordb_active_sponsors import CreatorDBActiveSponsorSource


class _FakeResponse:
    status_code = 200
    text = "ok"

    def json(self):
        return {
            "success": True,
            "data": {
                "contentList": [
                    {
                        "contentId": "abc123",
                        "contentType": "video",
                        "title": "Sponsored gaming video",
                        "url": "https://www.youtube.com/watch?v=abc123",
                        "publishTime": int(datetime.now(timezone.utc).timestamp() * 1000),
                        "isSponsored": True,
                        "partneredBrands": ["newgamingbrand.com"],
                        "category": "Gaming",
                        "creator": {
                            "channelId": "UC1234567890123456789012",
                            "displayName": "Evidence Creator",
                            "totalSubscribers": 500000,
                        },
                    }
                ]
            },
        }


class _FakeSession:
    def __init__(self):
        self.last_payload = None

    def post(self, url, json, timeout):
        self.last_payload = json
        return _FakeResponse()


class CreatorDBActiveSponsorSourceTests(unittest.TestCase):
    def test_discovers_brand_from_recent_sponsored_content(self):
        source = CreatorDBActiveSponsorSource("test-key", page_size=20)
        fake_session = _FakeSession()
        source.session = fake_session

        leads = source.discover(30)

        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0].brand_domain, "newgamingbrand.com")
        self.assertEqual(leads[0].source_platform, "YouTube")
        self.assertIn("CreatorDB sponsored content", leads[0].signals)
        self.assertIn("partnered brand attribution", leads[0].signals)

        filters = fake_session.last_payload["filters"]
        self.assertIn(
            {"filterName": "isSponsored", "op": "=", "value": True},
            filters,
        )
        self.assertIn(
            {"filterName": "publishTime", "op": "<", "value": 30},
            filters,
        )
        self.assertEqual(fake_session.last_payload["sortBy"], "publishTime")
        self.assertTrue(fake_session.last_payload["desc"])

    def test_no_api_key_cleanly_disables_source(self):
        source = CreatorDBActiveSponsorSource("")
        self.assertEqual(source.discover(30), [])


if __name__ == "__main__":
    unittest.main()
