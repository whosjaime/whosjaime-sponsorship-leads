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

    def test_one_time_monday_bootstrap_is_removed_after_migration(self):
        self.assertFalse(Path("src/bootstrap_sponsor_duplicate_ledger.py").exists())
        self.assertFalse(Path(".github/workflows/bootstrap-sponsor-duplicates.yml").exists())
        self.assertFalse(Path(".github/sponsor-duplicate-bootstrap-trigger").exists())
        self.assertTrue(Path("data/sent_sponsor_keys.json").exists())


if __name__ == "__main__":
    unittest.main()
