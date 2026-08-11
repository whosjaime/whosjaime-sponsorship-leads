from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from run_sponsor_discovery_batch import (
    MUSIC_QUEUE_LIMIT,
    _build_balanced_queue,
    _is_music_lead,
    _is_queue_target_lead,
)
from sponsor_models import SponsorLead
from sponsor_queue import MAX_QUEUE_SIZE


def _lead(number: int, category: str = "Gaming", evidence: str = "Sponsored by Brand") -> SponsorLead:
    return SponsorLead(
        brand_name=f"Brand {number}",
        brand_domain=f"brand{number}.com",
        source_platform="YouTube",
        creator_name="Creator",
        creator_url="https://youtube.com/channel/test",
        creator_channel_id="test",
        creator_subscribers=100000,
        creator_genre="Music",
        creator_tags=[],
        video_id=f"video{number}",
        video_url=f"https://youtube.com/watch?v=video{number}",
        video_title="Sponsored video",
        sponsored_date="2026-08-10",
        evidence=evidence,
        sponsor_category=category,
        contact_email=f"partnerships@brand{number}.com",
        lead_score=100,
        brand_key=f"domain:brand{number}.com",
    )


class MusicSponsorQueueTests(unittest.TestCase):
    def test_music_is_allowed_as_secondary_queue_category(self):
        music = _lead(1, "Music")
        self.assertTrue(_is_music_lead(music))
        self.assertTrue(_is_queue_target_lead(music))

    def test_music_product_evidence_can_identify_music_lead(self):
        music = _lead(1, "Entertainment", "Sponsored guitar pedal and recording gear")
        self.assertTrue(_is_music_lead(music))

    def test_festivals_are_not_music_sponsor_leads(self):
        festival = _lead(1, "Music", "Sponsored by Summer Music Festival")
        self.assertFalse(_is_music_lead(festival))

    def test_music_is_capped_at_two_of_twenty_four(self):
        core = [_lead(i) for i in range(30)]
        music = [_lead(100 + i, "Music") for i in range(5)]

        queue = _build_balanced_queue([*core, *music])

        self.assertEqual(len(queue), MAX_QUEUE_SIZE)
        self.assertEqual(sum(1 for lead in queue if _is_music_lead(lead)), MUSIC_QUEUE_LIMIT)

    def test_music_is_spaced_instead_of_back_to_back(self):
        core = [_lead(i) for i in range(22)]
        music = [_lead(100, "Music"), _lead(101, "Music")]

        queue = _build_balanced_queue([*core, *music])
        music_positions = [index for index, lead in enumerate(queue) if _is_music_lead(lead)]

        self.assertEqual(music_positions, [9, 19])


if __name__ == "__main__":
    unittest.main()
