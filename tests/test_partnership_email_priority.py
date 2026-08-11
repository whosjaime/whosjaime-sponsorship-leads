from __future__ import annotations

import unittest

from brand_enrichment import BrandEnricher


class FakeBrandEnricher(BrandEnricher):
    def __init__(self, pages: dict[str, str]) -> None:
        super().__init__()
        self.pages = pages
        self.requested: list[str] = []

    def _fetch(self, url: str) -> tuple[str, str]:
        self.requested.append(url)
        page = self.pages.get(url, "")
        return (url, page) if page else ("", "")


class PartnershipEmailPriorityTests(unittest.TestCase):
    def test_sponsorship_email_beats_homepage_support_email(self):
        enricher = FakeBrandEnricher(
            {
                "https://example.com": "<html><body>Gaming gear. support@example.com</body></html>",
                "https://example.com/sponsorships": "<html><body>sponsorships@example.com</body></html>",
            }
        )

        result = enricher.enrich("example.com")

        self.assertEqual(result["contact_email"], "sponsorships@example.com")
        self.assertEqual(result["email_type"], "Sponsorships")
        self.assertIn("https://example.com/sponsorships", enricher.requested)

    def test_partnership_email_beats_contact_and_info(self):
        enricher = FakeBrandEnricher(
            {
                "https://example.com": "<html><body>contact@example.com info@example.com</body></html>",
                "https://example.com/partnerships": "<html><body>partnerships@example.com</body></html>",
            }
        )

        result = enricher.enrich("example.com")

        self.assertEqual(result["contact_email"], "partnerships@example.com")
        self.assertEqual(result["email_type"], "Partnerships")

    def test_named_email_on_creator_partnership_page_beats_generic_contact(self):
        enricher = FakeBrandEnricher(
            {
                "https://example.com": "<html><body>contact@example.com</body></html>",
                "https://example.com/creator-partnerships": "<html><body>jane.smith@example.com</body></html>",
            }
        )

        result = enricher.enrich("example.com")

        self.assertEqual(result["contact_email"], "jane.smith@example.com")
        self.assertEqual(result["email_type"], "Partnership Page Contact")

    def test_support_remains_valid_only_as_fallback(self):
        enricher = FakeBrandEnricher(
            {
                "https://example.com": "<html><body>support@example.com</body></html>",
            }
        )

        result = enricher.enrich("example.com")

        self.assertEqual(result["contact_email"], "support@example.com")
        self.assertEqual(result["email_type"], "Support")


if __name__ == "__main__":
    unittest.main()
