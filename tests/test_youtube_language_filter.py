from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sponsor_models import VideoRecord
from video_language_filter import is_english_video
from youtube_sponsor_scanner import YouTubeSponsorScanner


def _video(**overrides) -> VideoRecord:
    values = {
        "platform": "YouTube",
        "video_id": "video1",
        "video_url": "https://youtube.com/watch?v=video1",
        "title": "My new gaming setup is sponsored",
        "description": "Thanks to Example Brand for sponsoring this video.",
        "published_at": "2026-08-11T12:00:00Z",
        "channel_id": "UC123",
        "channel_title": "Example Creator",
    }
    values.update(overrides)
    return VideoRecord(**values)


class YouTubeLanguageFilterTests(unittest.TestCase):
    def test_explicit_english_audio_is_allowed(self):
        self.assertTrue(is_english_video(_video(default_audio_language="en-US")))

    def test_explicit_non_english_audio_is_rejected(self):
        self.assertFalse(is_english_video(_video(default_audio_language="hi")))

    def test_non_english_metadata_is_rejected_when_audio_missing(self):
        self.assertFalse(is_english_video(_video(default_language="es")))

    def test_obvious_hindi_script_is_rejected_when_language_metadata_missing(self):
        video = _video(
            channel_title="कृषि भारत | Krishi Bharat",
            title="खेती में नया तरीका और आज का प्रायोजक",
            description="आज के वीडियो को हमारे प्रायोजक ने सहयोग दिया है।",
        )
        self.assertFalse(is_english_video(video))

    def test_english_metadata_without_language_tags_is_allowed(self):
        self.assertTrue(is_english_video(_video()))

    def test_fetch_videos_captures_youtube_language_fields(self):
        scanner = YouTubeSponsorScanner("test-key")
        scanner._get = Mock(return_value={
            "items": [
                {
                    "id": "video1",
                    "snippet": {
                        "title": "Example",
                        "description": "Sponsored example",
                        "publishedAt": "2026-08-11T12:00:00Z",
                        "channelId": "UC123",
                        "channelTitle": "Creator",
                        "defaultLanguage": "en",
                        "defaultAudioLanguage": "en-US",
                    },
                    "statistics": {"viewCount": "100"},
                    "paidProductPlacementDetails": {},
                }
            ]
        })

        videos = scanner.fetch_videos(["video1"])

        self.assertEqual(videos[0].default_language, "en")
        self.assertEqual(videos[0].default_audio_language, "en-US")


if __name__ == "__main__":
    unittest.main()
