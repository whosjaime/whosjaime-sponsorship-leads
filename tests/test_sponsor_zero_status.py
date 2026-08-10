from __future__ import annotations

import unittest
from pathlib import Path


class SponsorZeroStatusTests(unittest.TestCase):
    def test_zero_status_helper_exists(self):
        text = Path("src/discord_scan_zero_status.py").read_text(encoding="utf-8")
        self.assertIn("SPONSOR SCAN RAN — 0 NEW LEADS", text)
        self.assertIn("YouTube videos scanned", text)
        self.assertIn("Rejected by current gates", text)

    def test_workflow_posts_zero_status_and_keeps_top_of_hour_schedule(self):
        workflow = Path(".github/workflows/scan-sponsors.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "0 * * * *"', workflow)
        self.assertIn("discord_scan_zero_status.py", workflow)
        self.assertIn('".github/sponsor-scan-trigger"', workflow)


if __name__ == "__main__":
    unittest.main()
