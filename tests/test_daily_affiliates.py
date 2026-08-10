from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from send_daily_affiliates import format_messages, select_new_affiliates


class DailyAffiliateTests(unittest.TestCase):
    def _item(self, name: str, domain: str, category: str = "Gaming") -> dict:
        return {
            "brand_name": name,
            "category": category,
            "commission": "15% per sale",
            "website": domain,
            "apply_url": f"https://{domain}/affiliate",
            "brand_size": "emerging",
        }

    def test_duplicate_brand_is_not_sent_again(self):
        queue = [self._item("Alpha Gear", "alphagear.com"), self._item("Beta Tech", "betatech.com")]
        duplicates = [{"brand_name": "Alpha Gear", "website": "alphagear.com", "apply_url": "https://alphagear.com/affiliate"}]
        selected = select_new_affiliates(queue, duplicates)
        self.assertEqual([item["brand_name"] for item in selected], ["Beta Tech"])

    def test_accepts_categories_outside_priority_buckets(self):
        queue = [self._item("Cool Apparel", "coolapparel.com", category="Fashion")]
        selected = select_new_affiliates(queue, [])
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["category"], "Fashion")

    def test_format_is_minimal_and_contains_website(self):
        items = [self._item("Alpha Gear", "alphagear.com")]
        now = datetime(2026, 8, 10, 11, 0, tzinfo=ZoneInfo("America/Toronto"))
        message = format_messages(items, now)[0]
        self.assertIn("DAILY CREATOR AFFILIATE OPPORTUNITIES", message)
        self.assertIn("Category: Gaming", message)
        self.assertIn("Commission: 15% per sale", message)
        self.assertIn("Website: <https://alphagear.com>", message)
        self.assertIn("Apply: <https://alphagear.com/affiliate>", message)
        self.assertNotIn("Best For", message)
        self.assertNotIn("Cookie", message)

    def test_daily_cap_is_twenty(self):
        queue = [self._item(f"Brand {i}", f"brand{i}.com") for i in range(25)]
        self.assertEqual(len(select_new_affiliates(queue, [])), 20)


if __name__ == "__main__":
    unittest.main()
