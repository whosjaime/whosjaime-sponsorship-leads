from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from run_sponsor_discovery_batch import (
    BEAUTY_QUEUE_LIMIT,
    _build_balanced_queue,
    _is_beauty_lead,
    _is_queue_target_lead,
)
from sponsor_models import SponsorLead
from sponsor_queue import MAX_QUEUE_SIZE


def _lead(number: int, category: str = "Gaming") -> SponsorLead:
    return SponsorLead(
        brand_name=f"Brand {number}",
        brand_domain=f"brand{number}.com",
        source_platform="YouTube",
        creator_name="Creator",
        creator_url="https://youtube.com/channel/test",
        creator_channel_id="test",
        creator_subscribers=100000,
        creator_genre="Gaming",
        creator_tags=[],
        video_id=f"video{number}",
        video_url=f"https://youtube.com/watch?v=video{number}",
        video_title="Sponsored video",
        sponsored_date="2026-08-10",
        evidence="Sponsored by Brand",
        sponsor_category=category,
        contact_email=f"partnerships@brand{number}.com",
        lead_score=100,
        brand_key=f"domain:brand{number}.com",
    )


class BeautySponsorQueueTests(unittest.TestCase):
    def test_beauty_is_allowed_as_secondary_queue_category(self):
        beauty = _lead(1, "Beauty")
        self.assertTrue(_is_beauty_lead(beauty))
        self.assertTrue(_is_queue_target_lead(beauty))

    def test_beauty_is_capped_at_two_of_twenty_four(self):
        core = [_lead(i) for i in range(30)]
        beauty = [_lead(100 + i, "Beauty") for i in range(5)]

        queue = _build_balanced_queue([*core, *beauty])

        self.assertEqual(len(queue), MAX_QUEUE_SIZE)
        self.assertEqual(sum(1 for lead in queue if _is_beauty_lead(lead)), BEAUTY_QUEUE_LIMIT)

    def test_beauty_is_spaced_instead_of_back_to_back(self):
        core = [_lead(i) for i in range(22)]
        beauty = [_lead(100, "Beauty"), _lead(101, "Beauty")]

        queue = _build_balanced_queue([*core, *beauty])
        beauty_positions = [index for index, lead in enumerate(queue) if _is_beauty_lead(lead)]

        self.assertEqual(beauty_positions, [5, 15])


if __name__ == "__main__":
    unittest.main()
