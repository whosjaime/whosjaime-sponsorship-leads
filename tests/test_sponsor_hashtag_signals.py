from __future__ import annotations

import unittest

from sponsor_detector import detect_sponsors, to_sponsor_lead
from sponsor_models import VideoRecord


class SponsorHashtagSignalTests(unittest.TestCase):
    def _video(self, *, title: str = "", description: str = "", tags: list[str] | None = None) -> VideoRecord:
        return VideoRecord(
            platform="YouTube",
            video_id="abc123",
            video_url="https://www.youtube.com/watch?v=abc123",
            title=title,
            description=description,
            published_at="2026-08-09T20:00:00Z",
            channel_id="creator1",
            channel_title="Creator",
            tags=tags or [],
        )

    def test_ad_tag_metadata_counts_as_sponsorship_disclosure(self) -> None:
        video = self._video(
            description="Check it out: https://examplegaming.com/deal",
            tags=["gaming", "#ad"],
        )
        detections = detect_sponsors(video, {})
        self.assertEqual(1, len(detections))
        self.assertTrue(detections[0].ad_hashtag)
        self.assertEqual("examplegaming.com", detections[0].domain)

        lead = to_sponsor_lead(video, None, detections[0], "", [])
        self.assertIn("ad/sponsored disclosure", lead.signals)

    def test_title_hashtag_counts_as_sponsorship_disclosure(self) -> None:
        video = self._video(
            title="New setup tour #sponsored",
            description="Gear partner: https://exampletech.com",
        )
        detections = detect_sponsors(video, {})
        self.assertEqual(1, len(detections))
        self.assertTrue(detections[0].ad_hashtag)

    def test_paid_partnership_hashtag_variant_counts(self) -> None:
        video = self._video(
            description="Try it here: https://examplefood.com",
            tags=["#paidpartnership"],
        )
        detections = detect_sponsors(video, {})
        self.assertEqual(1, len(detections))
        self.assertTrue(detections[0].ad_hashtag)


if __name__ == "__main__":
    unittest.main()
