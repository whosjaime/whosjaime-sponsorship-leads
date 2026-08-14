from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sponsor_models import SponsorLead
from sponsor_queue import (
    CODING_QUEUE_LIMIT,
    SOFTWARE_QUEUE_LIMIT,
    TECH_FAMILY_QUEUE_LIMIT,
    diversify_queue,
    is_creator_on_cooldown,
    mark_creator_used,
)


class SponsorQueueDiversityTests(unittest.TestCase):
    def _lead(
        self,
        brand: str,
        creator: str,
        channel_id: str,
        category: str = "Food & Beverage",
        title: str = "Sponsored video",
        email: str | None = None,
        email_type: str = "Partnerships",
        tags: list[str] | None = None,
    ) -> SponsorLead:
        domain = f"{brand.lower().replace(' ', '')}.com"
        return SponsorLead(
            brand_name=brand,
            brand_domain=domain,
            source_platform="YouTube",
            creator_name=creator,
            creator_url=f"https://www.youtube.com/channel/{channel_id}",
            creator_channel_id=channel_id,
            creator_subscribers=100000,
            creator_genre="Entertainment",
            creator_tags=tags or [],
            video_id=f"video-{brand}",
            video_url=f"https://youtube.com/watch?v=video-{brand}",
            video_title=title,
            sponsored_date=date.today().isoformat(),
            evidence="verified sponsorship evidence",
            sponsor_category=category,
            contact_email=email or f"partnerships@{domain}",
            email_type=email_type,
            lead_score=100,
            brand_key=f"domain:{domain}",
        )

    def test_active_queue_allows_only_one_lead_per_creator(self):
        leads = [
            self._lead("Brand One", "Same Creator", "channel-1"),
            self._lead("Brand Two", "Same Creator", "channel-1"),
            self._lead("Brand Three", "Different Creator", "channel-2"),
        ]
        result = diversify_queue(leads, set())
        creators = [lead.creator_channel_id for lead in result]
        self.assertEqual(creators.count("channel-1"), 1)
        self.assertIn("channel-2", creators)

    def test_software_saas_is_hard_capped(self):
        leads = [
            self._lead(f"SaaS {i}", f"Creator {i}", f"channel-{i}", "Software / SaaS")
            for i in range(8)
        ]
        result = diversify_queue(leads, set())
        software = [lead for lead in result if lead.sponsor_category == "Software / SaaS"]
        self.assertLessEqual(len(software), SOFTWARE_QUEUE_LIMIT)

    def test_coding_and_developer_leads_are_hard_capped(self):
        leads = [
            self._lead(
                f"Dev {i}",
                f"Dev Creator {i}",
                f"dev-channel-{i}",
                "Software / SaaS",
                title=f"How to write code with developer API {i}",
            )
            for i in range(6)
        ]
        result = diversify_queue(leads, set())
        self.assertLessEqual(len(result), CODING_QUEUE_LIMIT)

    def test_coding_lead_with_support_only_email_is_rejected(self):
        lead = self._lead(
            "Weak Dev Tool",
            "Dev Creator",
            "dev-channel",
            "Software / SaaS",
            title="Developer coding API walkthrough",
            email="support@weakdevtool.com",
            email_type="Support",
        )
        self.assertEqual(diversify_queue([lead], set()), [])

    def test_combined_tech_family_is_capped(self):
        categories = ["Software / SaaS", "Consumer Tech", "Cybersecurity / VPN"]
        leads = [
            self._lead(
                f"Tech {i}",
                f"Tech Creator {i}",
                f"tech-channel-{i}",
                categories[i % len(categories)],
            )
            for i in range(15)
        ]
        result = diversify_queue(leads, set())
        tech_family = [
            lead for lead in result
            if lead.sponsor_category in {"Software / SaaS", "Consumer Tech", "Cybersecurity / VPN"}
        ]
        self.assertLessEqual(len(tech_family), TECH_FAMILY_QUEUE_LIMIT)

    def test_dispatched_creator_has_seven_day_cooldown(self):
        lead = self._lead("Brand One", "Cooldown Creator", "cooldown-channel")
        sent_keys: set[str] = set()
        mark_creator_used(lead, sent_keys)
        self.assertTrue(is_creator_on_cooldown(lead, sent_keys))

        next_brand = self._lead("Brand Two", "Cooldown Creator", "cooldown-channel")
        self.assertEqual(diversify_queue([next_brand], sent_keys), [])

    def test_round_robin_prevents_software_wall_when_variety_exists(self):
        leads = [
            self._lead("Software One", "Creator A", "a", "Software / SaaS"),
            self._lead("Software Two", "Creator B", "b", "Software / SaaS"),
            self._lead("Game Brand", "Creator C", "c", "Gaming"),
            self._lead("Food Brand", "Creator D", "d", "Food & Beverage"),
            self._lead("Lifestyle Brand", "Creator E", "e", "Fashion", tags=["Lifestyle"]),
        ]
        result = diversify_queue(leads, set())
        first_three = [lead.sponsor_category for lead in result[:3]]
        self.assertIn("Gaming", first_three)
        self.assertIn("Food & Beverage", first_three)
        self.assertNotEqual(first_three, ["Software / SaaS"] * 3)


if __name__ == "__main__":
    unittest.main()
