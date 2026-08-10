from pathlib import Path
import unittest


class SponsorFailureAlertTests(unittest.TestCase):
    def test_legacy_failure_alert_helper_still_exists_but_is_not_wired(self):
        helper = Path("src/discord_scan_failure_alert.py").read_text(encoding="utf-8")
        self.assertIn("SPONSOR SCANNER ERROR", helper)

        hourly = Path(".github/workflows/scan-sponsors.yml").read_text(encoding="utf-8")
        daily = Path(".github/workflows/discover-sponsor-queue.yml").read_text(encoding="utf-8")
        self.assertNotIn("discord_scan_failure_alert.py", hourly)
        self.assertNotIn("discord_scan_failure_alert.py", daily)


if __name__ == "__main__":
    unittest.main()
