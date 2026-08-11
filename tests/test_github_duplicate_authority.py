from __future__ import annotations

import unittest
from pathlib import Path


class GitHubDuplicateAuthorityTests(unittest.TestCase):
    def test_live_sponsor_paths_do_not_read_monday_for_duplicates(self):
        live_paths = [
            Path("src/run_sponsor_discovery_batch.py"),
            Path("src/run_sponsor_queue_dispatch.py"),
            Path("src/run_discord_linkedin_intake.py"),
        ]
        for path in live_paths:
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("load_existing_index()", source, str(path))

    def test_discovery_workflow_has_no_monday_credentials(self):
        workflow = Path(".github/workflows/discover-sponsor-queue.yml").read_text(encoding="utf-8")
        self.assertNotIn("SPONSOR_MONDAY_TOKEN", workflow)
        self.assertNotIn("SPONSOR_MONDAY_API_KEY", workflow)

    def test_all_live_paths_read_shared_github_duplicate_ledger(self):
        discovery = Path("src/run_sponsor_discovery_batch.py").read_text(encoding="utf-8")
        dispatch = Path("src/run_sponsor_queue_dispatch.py").read_text(encoding="utf-8")
        linkedin = Path("src/run_discord_linkedin_intake.py").read_text(encoding="utf-8")
        self.assertIn("load_duplicate_keys()", discovery)
        self.assertIn("load_duplicate_keys()", dispatch)
        self.assertIn("load_duplicate_keys()", linkedin)

    def test_only_bootstrap_script_migrates_historical_monday_duplicate_index(self):
        bootstrap = Path("src/bootstrap_sponsor_duplicate_ledger.py").read_text(encoding="utf-8")
        self.assertIn("load_existing_index()", bootstrap)
        self.assertIn("save_sent_keys(sent_keys)", bootstrap)


if __name__ == "__main__":
    unittest.main()
