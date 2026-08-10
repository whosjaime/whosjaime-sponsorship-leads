from pathlib import Path
import unittest


class SponsorFailureAlertTests(unittest.TestCase):
    def test_failure_alert_helper_exists(self):
        text = Path("src/discord_scan_failure_alert.py").read_text(encoding="utf-8")
        self.assertIn("SPONSOR SCANNER ERROR", text)
        self.assertIn("DISCORD_WEBHOOK_URL", text)

    def test_workflow_has_failure_step(self):
        text = Path(".github/workflows/scan-sponsors.yml").read_text(encoding="utf-8")
        self.assertIn("if: failure()", text)
        self.assertIn("discord_scan_failure_alert.py", text)


if __name__ == "__main__":
    unittest.main()
