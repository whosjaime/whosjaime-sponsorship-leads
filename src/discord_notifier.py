from __future__ import annotations

from datetime import datetime

import requests

from sponsor_models import SponsorLead

OUTREACH_USER_ID = "1162376803508297771"


class DiscordNotifier:
    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = (webhook_url or "").strip()

    def _post(self, content: str) -> None:
        if not self.webhook_url:
            return
        response = requests.post(
            self.webhook_url,
            json={
                "content": content[:1990],
                "allowed_mentions": {"users": [OUTREACH_USER_ID]},
            },
            timeout=20,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Discord webhook error {response.status_code}: {response.text[:500]}"
            )

    @staticmethod
    def _display_date(value: str) -> str:
        if not value:
            return "Unknown"
        try:
            parsed = datetime.strptime(value[:10], "%Y-%m-%d")
            return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"
        except ValueError:
            return value

    @staticmethod
    def _website_url(domain: str) -> str:
        value = (domain or "").strip()
        if not value:
            return "Unknown"
        if value.startswith(("http://", "https://")):
            return value
        return f"https://{value}"

    @classmethod
    def new_lead_message(cls, lead: SponsorLead) -> str:
        subscribers = (
            f"{lead.creator_subscribers:,}"
            if lead.creator_subscribers
            else "Unknown"
        )
        website = cls._website_url(lead.brand_domain)
        contact = ""
        if lead.contact_name:
            contact = lead.contact_name
            if lead.contact_title:
                contact += f" — {lead.contact_title}"

        lines = [
            "🔥 **NEW SPONSOR LEAD**",
            "",
            f"🏢 **Brand:** {lead.brand_name}",
        ]
        if contact:
            lines.append(f"👤 **Contact:** {contact}")
        lines.extend(
            [
                f"📧 **Email:** {lead.contact_email}",
                f"🌐 **Website:** <{website}>",
                "",
                f"🎥 **Found On:** {lead.source_platform}",
                f"👤 **Creator:** {lead.creator_name}",
                f"📊 **Subscribers:** {subscribers}",
                f"📅 **Sponsored Date:** {cls._display_date(lead.sponsored_date)}",
                "",
                f"🔗 **Sponsored Video:** <{lead.video_url}>",
                "",
                f"✅ It has been added in **Monday.com**, <@{OUTREACH_USER_ID}> you can start outreach!",
            ]
        )
        return "\n".join(lines)

    def send_new_lead(self, lead: SponsorLead) -> None:
        self._post(self.new_lead_message(lead))
