from __future__ import annotations

import unittest
from pathlib import Path


class SponsorDeliveryWorkflowTests(unittest.TestCase):
    def test_hourly_workflow_dispatches_queue_on_the_hour(self):
        workflow = Path(".github/workflows/scan-sponsors.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "0 * * * *"', workflow)
        self.assertIn("run_sponsor_queue_dispatch.py", workflow)
        self.assertIn('".github/sponsor-dispatch-trigger"', workflow)
        self.assertNotIn("run_sponsor_scan.py", workflow)

    def test_hourly_discord_is_reserved_for_real_leads(self):
        workflow = Path(".github/workflows/scan-sponsors.yml").read_text(encoding="utf-8")
        self.assertNotIn("discord_scan_zero_status.py", workflow)
        self.assertNotIn("discord_scan_failure_alert.py", workflow)
        self.assertNotIn("SPONSOR SCANNER ERROR", workflow)

    def test_daily_discovery_builds_queue_without_discord_status_noise(self):
        workflow = Path(".github/workflows/discover-sponsor-queue.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "15 4 * * *"', workflow)
        self.assertIn('timezone: "America/Toronto"', workflow)
        self.assertIn("run_sponsor_discovery_batch.py", workflow)
        self.assertNotIn("discord_sponsor_queue_status.py", workflow)
        self.assertNotIn("discord_scan_failure_alert.py", workflow)
        self.assertNotIn("DISCORD_WEBHOOK_URL", workflow)


if __name__ == "__main__":
    unittest.main()
