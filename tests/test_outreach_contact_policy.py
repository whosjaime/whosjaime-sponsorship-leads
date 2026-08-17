from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from outreach_contact_policy import is_qualified_outreach_contact
from sponsor_models import SponsorLead
from sponsor_queue import diversify_queue


def _lead(email: str, *, email_type: str = "", source: str = "", title: str = "") -> SponsorLead:
    return SponsorLead(
        brand_name="Example Brand",
        brand_domain="example.com",
        source_platform="YouTube",
        creator_name="Example Creator",
        creator_url="https://youtube.com/@example",
        creator_channel_id="example-channel",
        creator_subscribers=100000,
        creator_genre="Gaming",
        creator_tags=["Gaming"],
        video_id="video1",
        video_url="https://youtube.com/watch?v=video1",
        video_title="Sponsored video",
        sponsored_date="2026-08-17",
        evidence="Sponsored by Example Brand",
        sponsor_category="Gaming",
        contact_title=title,
        contact_email=email,
        email_type=email_type,
        contact_source=source,
        lead_score=90,
        brand_key="domain:example.com",
    )


class OutreachContactPolicyTests(unittest.TestCase):
    def test_role_inboxes_are_allowed(self):
        for email in (
            "sponsorships@example.com",
            "partnerships@example.com",
            "creators@example.com",
            "influencerpartnerships@example.com",
            "brandpartnerships@example.com",
            "ambassador@example.com",
            "affiliate@example.com",
            "marketing@example.com",
            "bizdev@example.com",
        ):
            with self.subTest(email=email):
                self.assertTrue(is_qualified_outreach_contact(_lead(email)))

    def test_generic_service_and_pr_inboxes_are_rejected(self):
        for email in (
            "support@example.com",
            "customerservice@example.com",
            "help@example.com",
            "hello@example.com",
            "info@example.com",
            "contact@example.com",
            "press@example.com",
            "media@example.com",
            "pr@example.com",
            "sales@example.com",
        ):
            with self.subTest(email=email):
                self.assertFalse(is_qualified_outreach_contact(_lead(email)))

    def test_named_person_requires_relevant_role_or_source(self):
        self.assertFalse(is_qualified_outreach_contact(_lead("jane@example.com")))
        self.assertTrue(
            is_qualified_outreach_contact(
                _lead("jane@example.com", title="Creator Partnerships Manager")
            )
        )
        self.assertTrue(
            is_qualified_outreach_contact(
                _lead("jane@example.com", source="https://example.com/brand-partnerships")
            )
        )

    def test_queue_drops_generic_contact_before_dispatch(self):
        generic = _lead("support@example.com", email_type="Support")
        direct = _lead("partnerships@example.com", email_type="Partnerships")
        direct.brand_name = "Direct Brand"
        direct.brand_domain = "directbrand.com"
        direct.brand_key = "domain:directbrand.com"
        direct.creator_name = "Another Creator"
        direct.creator_channel_id = "another-channel"
        self.assertEqual([lead.brand_name for lead in diversify_queue([generic, direct], set())], ["Direct Brand"])


if __name__ == "__main__":
    unittest.main()
