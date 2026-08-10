from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from sponsor_models import SponsorLead
from sponsor_queue import MAX_QUEUE_SIZE, load_queue, merge_unique, save_queue
from youtube_sponsor_scanner import SEARCH_LANES, YouTubeSponsorScanner


def _lead(number: int) -> SponsorLead:
    return SponsorLead(
        brand_name=f"Brand {number}",
        brand_domain=f"brand{number}.com",
        source_platform="YouTube",
        creator_name="Creator",
        creator_url="https://youtube.com/channel/test",
        creator_channel_id="test",
        creator_subscribers=1000,
        creator_genre="Gaming",
        creator_tags=["gaming"],
        video_id=f"video{number}",
        video_url=f"https://youtube.com/watch?v=video{number}",
        video_title="Sponsored video",
        sponsored_date="2026-08-10",
        evidence="sponsored by Brand",
        sponsor_category="Gaming",
        contact_email=f"partnerships@brand{number}.com",
        lead_score=90,
        brand_key=f"brand:{number}",
    )


class SponsorQueueTests(unittest.TestCase):
    def test_queue_is_capped_to_one_full_day(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "queue.json"
            save_queue([_lead(i) for i in range(40)], path=path)
            loaded = load_queue(path=path)
            self.assertEqual(MAX_QUEUE_SIZE, 24)
            self.assertEqual(len(loaded), 24)

    def test_merge_unique_preserves_one_brand_only(self):
        first = _lead(1)
        duplicate = _lead(99)
        duplicate.brand_key = first.brand_key
        merged = merge_unique([first], [duplicate, _lead(2)])
        self.assertEqual([lead.brand_name for lead in merged], ["Brand 1", "Brand 2"])

    def test_daily_batch_still_uses_exactly_three_search_calls_up_to_50_each(self):
        scanner = YouTubeSponsorScanner("test-key")
        scanner._full_search_window = Mock(
            return_value=("2026-07-11T00:00:00Z", "2026-08-10T00:00:00Z", -1)
        )
        scanner._search = Mock(
            side_effect=[
                [f"a{i}" for i in range(50)],
                [f"b{i}" for i in range(50)],
                [f"c{i}" for i in range(50)],
            ]
        )

        ids = scanner.discover_batch_video_ids(30 * 24)

        self.assertEqual(len(SEARCH_LANES), 3)
        self.assertEqual(scanner._search.call_count, 3)
        self.assertEqual(len(ids), 150)
        self.assertIsNone(scanner._active_search_window)


if __name__ == "__main__":
    unittest.main()
