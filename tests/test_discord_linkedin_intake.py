from __future__ import annotations

import unittest

from discord_linkedin_intake import DiscordLinkedInClient, candidate_to_lead, parse_linkedin_discord_message


class DiscordLinkedInIntakeTests(unittest.TestCase):
    def test_parses_linkedin_preview_with_sponsor_domain(self):
        message = {
            "id": "123456789",
            "content": "https://www.linkedin.com/posts/creator_activity-7420000000000000000-xYz",
            "timestamp": "2026-08-09T23:10:00+00:00",
            "author": {"bot": False},
            "embeds": [
                {
                    "url": "https://www.linkedin.com/posts/creator_activity-7420000000000000000-xYz",
                    "title": "Creator on LinkedIn",
                    "description": "This post is sponsored by Acme. Learn more at https://acme.com/creator",
                    "author": {
                        "name": "Creator Name",
                        "url": "https://www.linkedin.com/in/creator-name/",
                    },
                }
            ],
        }
        candidate = parse_linkedin_discord_message(message)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.brand_name, "Acme")
        self.assertEqual(candidate.brand_domain, "acme.com")
        self.assertEqual(candidate.poster_name, "Creator Name")
        self.assertEqual(candidate.activity_id, "7420000000000000000")

        lead = candidate_to_lead(candidate)
        self.assertEqual(lead.source_platform, "LinkedIn")
        self.assertEqual(lead.video_url, message["content"])
        self.assertEqual(lead.brand_domain, "acme.com")

    def test_allows_explicit_brand_and_website_hint(self):
        message = {
            "id": "223456789",
            "content": (
                "https://www.linkedin.com/feed/update/urn:li:activity:7420000000000000001\n"
                "Brand: Example Labs\n"
                "Website: examplelabs.ai"
            ),
            "timestamp": "2026-08-09T23:10:00+00:00",
            "author": {"bot": False},
            "embeds": [],
        }
        candidate = parse_linkedin_discord_message(message)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.brand_name, "Example Labs")
        self.assertEqual(candidate.brand_domain, "examplelabs.ai")

    def test_link_only_without_preview_stays_unresolved_instead_of_guessing(self):
        message = {
            "id": "323456789",
            "content": "https://www.linkedin.com/posts/jane-smith_activity-7420000000000000002-abc",
            "timestamp": "2026-08-09T23:10:00+00:00",
            "author": {"bot": False},
            "embeds": [],
        }
        candidate = parse_linkedin_discord_message(message)
        self.assertIsNotNone(candidate)
        self.assertFalse(candidate.brand_name)
        self.assertFalse(candidate.brand_domain)

    def test_handled_reaction_prevents_reprocessing(self):
        message = {
            "reactions": [
                {"emoji": {"name": "✅"}, "me": True, "count": 1},
            ]
        }
        self.assertTrue(DiscordLinkedInClient.already_handled(message))

        other_user_reaction = {
            "reactions": [
                {"emoji": {"name": "✅"}, "me": False, "count": 1},
            ]
        }
        self.assertFalse(DiscordLinkedInClient.already_handled(other_user_reaction))


if __name__ == "__main__":
    unittest.main()
