from __future__ import annotations

import unittest
from pathlib import Path

from creator_classifier import classify_creator
from run_sponsor_discovery_batch import (
    BACKUP_QUEUE_TRIGGER,
    BEAUTY_QUEUE_LIMIT,
    MUSIC_QUEUE_LIMIT,
    STREAMING_QUEUE_LIMIT,
    VLOG_QUEUE_LIMIT,
    _build_balanced_queue,
    _is_beauty_lead,
    _is_music_lead,
    _is_streaming_lead,
    _is_vlog_lead,
    _secondary_coverage_missing,
)
from sponsor_models import ChannelRecord, SponsorLead, VideoRecord
from youtube_sponsor_scanner import BACKUP_SEARCH_LANES


ROOT = Path(__file__).resolve().parents[1]


def _lead(number: int, *, category: str = "Gaming", genre: str = "Gaming", tags=None, evidence: str = "") -> SponsorLead:
    return SponsorLead(
        brand_name=f"Brand {number}",
        brand_domain=f"brand{number}.com",
        source_platform="YouTube",
        creator_name=f"Creator {number}",
        creator_url=f"https://youtube.com/channel/c{number}",
        creator_channel_id=f"c{number}",
        creator_subscribers=100000,
        creator_genre=genre,
        creator_tags=list(tags or []),
        video_id=f"video{number}",
        video_url=f"https://youtube.com/watch?v=video{number}",
        video_title="Sponsored video",
        sponsored_date="2026-08-10",
        evidence=evidence or f"sponsored by Brand {number}",
        sponsor_category=category,
        contact_email=f"partnerships@brand{number}.com",
        lead_score=90,
        brand_key=f"brand:{number}",
    )


class BackupSponsorQueueTests(unittest.TestCase):
    def test_backup_trigger_keeps_substantial_inventory(self):
        self.assertEqual(BACKUP_QUEUE_TRIGGER, 18)

    def test_backup_search_has_three_paid_secondary_lanes(self):
        self.assertEqual(len(BACKUP_SEARCH_LANES), 3)
        self.assertTrue(all(paid_only for _, _, paid_only in BACKUP_SEARCH_LANES))
        combined = " ".join(query for _, query, _ in BACKUP_SEARCH_LANES).lower()
        for keyword in ("streaming", "vlog", "beauty", "makeup", "music", "guitar"):
            self.assertIn(keyword, combined)

    def test_classifier_recognizes_streaming_creator(self):
        video = VideoRecord(
            platform="YouTube",
            video_id="stream1",
            video_url="https://youtube.com/watch?v=stream1",
            title="Best moments from my Twitch livestream",
            description="stream highlights from today's live stream",
            published_at="2026-08-10T00:00:00Z",
            channel_id="ucstream",
            channel_title="Streamer",
        )
        channel = ChannelRecord(
            channel_id="ucstream",
            title="Streamer",
            description="Twitch streamer and livestream creator",
        )
        genre, tags = classify_creator(video, channel)
        self.assertEqual(genre, "Streaming")
        self.assertIn("Streaming", tags)

    def test_balanced_queue_caps_secondary_buckets(self):
        core = [_lead(i) for i in range(20)]
        streaming = [_lead(100 + i, genre="Streaming", tags=["Streaming"]) for i in range(4)]
        vlog = [_lead(200 + i, genre="Entertainment", tags=["Lifestyle"]) for i in range(4)]
        beauty = [_lead(300 + i, category="Beauty", evidence="makeup skincare sponsor") for i in range(4)]
        music = [_lead(400 + i, category="Music", evidence="guitar music gear sponsor") for i in range(4)]

        queue = _build_balanced_queue([*core, *streaming, *vlog, *beauty, *music])

        self.assertLessEqual(sum(_is_streaming_lead(x) for x in queue), STREAMING_QUEUE_LIMIT)
        self.assertLessEqual(sum(_is_vlog_lead(x) for x in queue), VLOG_QUEUE_LIMIT)
        self.assertLessEqual(sum(_is_beauty_lead(x) for x in queue), BEAUTY_QUEUE_LIMIT)
        self.assertLessEqual(sum(_is_music_lead(x) for x in queue), MUSIC_QUEUE_LIMIT)
        self.assertEqual(len(queue), 24)

    def test_secondary_coverage_requires_all_four_types(self):
        leads = [
            _lead(1, genre="Streaming", tags=["Streaming"]),
            _lead(2, genre="Entertainment", tags=["Lifestyle"]),
            _lead(3, category="Beauty", evidence="makeup skincare sponsor"),
            _lead(4, category="Music", evidence="guitar music gear sponsor"),
        ]
        self.assertFalse(_secondary_coverage_missing(leads))
        self.assertTrue(_secondary_coverage_missing(leads[:-1]))

    def test_queue_top_up_runs_four_times_daily(self):
        workflow = (ROOT / ".github/workflows/discover-sponsor-queue.yml").read_text(encoding="utf-8")
        for hour in (4, 10, 16, 22):
            self.assertIn(f'cron: "15 {hour} * * *"', workflow)
        self.assertEqual(workflow.count('timezone: "America/Toronto"'), 4)


if __name__ == "__main__":
    unittest.main()
