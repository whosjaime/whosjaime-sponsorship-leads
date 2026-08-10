from __future__ import annotations

import unittest
from pathlib import Path


class SponsorDeliveryWorkflowTests(unittest.TestCase):
    def test_legacy_zero_status_helper_still_exists(self):
        text = Path("src/discord_scan_zero_status.py").read_text(encoding="utf-8")
        self.assertIn("SPONSOR SCAN RAN — 0 NEW LEADS", text)

    def test_hourly_workflow_dispatches_queue_on_the_hour(self):
        workflow = Path(".github/workflows/scan-sponsors.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "0 * * * *"', workflow)
        self.assertIn("run_sponsor_queue_dispatch.py", workflow)
        self.assertIn('".github/sponsor-dispatch-trigger"', workflow)
        self.assertNotIn("run_sponsor_scan.py", workflow)

    def test_daily_discovery_builds_queue_and_posts_summary(self):
        workflow = Path(".github/workflows/discover-sponsor-queue.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "15 4 * * *"', workflow)
        self.assertIn('timezone: "America/Toronto"', workflow)
        self.assertIn("run_sponsor_discovery_batch.py", workflow)
        self.assertIn("discord_sponsor_queue_status.py", workflow)


if __name__ == "__main__":
    unittest.main()
