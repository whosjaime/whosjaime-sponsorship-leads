from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

from youtube_sponsor_scanner import SEARCH_LANES, SEARCH_WINDOW_SLOTS, YouTubeSponsorScanner


class YouTubeHourlyWindowTests(unittest.TestCase):
    def test_30_day_window_is_split_into_24_hourly_slices(self):
        now = datetime(2026, 8, 10, 5, 0, 0, tzinfo=timezone.utc)
        after, before, slot = YouTubeSponsorScanner._hourly_search_window(30 * 24, now=now)

        self.assertEqual(SEARCH_WINDOW_SLOTS, 24)
        self.assertEqual(slot, 5)
        # A 720-hour lookback split into 24 slots gives a 30-hour slice.
        self.assertEqual(after, "2026-08-02T17:00:00Z")
        self.assertEqual(before, "2026-08-03T23:00:00Z")

    def test_each_run_keeps_exactly_three_search_calls_in_one_rotating_slice(self):
        scanner = YouTubeSponsorScanner("test-key")
        scanner._hourly_search_window = Mock(
            return_value=("2026-08-02T17:00:00Z", "2026-08-03T23:00:00Z", 5)
        )
        scanner._search = Mock(side_effect=[["a", "b"], ["b", "c"], ["d"]])

        ids = scanner.discover_video_ids(30 * 24)

        self.assertEqual(len(SEARCH_LANES), 3)
        self.assertEqual(scanner._search.call_count, 3)
        self.assertEqual(ids, ["a", "b", "c", "d"])
        for call in scanner._search.call_args_list:
            self.assertEqual(call.args[0], "2026-08-02T17:00:00Z")
            self.assertEqual(call.args[1], "2026-08-03T23:00:00Z")

    def test_all_failed_search_lanes_raise_instead_of_silent_zero_inventory(self):
        scanner = YouTubeSponsorScanner("test-key")
        scanner._hourly_search_window = Mock(
            return_value=("2026-08-02T17:00:00Z", "2026-08-03T23:00:00Z", 5)
        )
        scanner._search = Mock(side_effect=RuntimeError("quota/API failure"))

        with self.assertRaisesRegex(RuntimeError, "All YouTube sponsor discovery lanes failed"):
            scanner.discover_video_ids(30 * 24)
        self.assertEqual(scanner._search.call_count, 3)


if __name__ == "__main__":
    unittest.main()
