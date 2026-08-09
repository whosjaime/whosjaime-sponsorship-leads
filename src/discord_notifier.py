from __future__ import annotations

from datetime import datetime

import requests

from sponsor_models import SponsorLead


class DiscordNotifier:
    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = (webhook_url or "").strip()

    def _post(self, content: str) -> None:
        if not self.webhook_url:
            return
        response = requests.post(
            self.webhook_url,
            json={"content": content[:1990]},
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

    @classmethod
    def new_lead_message(cls, lead: SponsorLead) -> str:
        subscribers = (
            f"{lead.creator_subscribers:,}"
            if lead.creator_subscribers
            else "Unknown"
        )

        return "\n".join(
            [
                "🔥 NEW SPONSOR LEAD",
                f"Brand: {lead.brand_name}",
                f"Email: {lead.contact_email}",
                f"Website: {lead.brand_domain}",
                f"Found On: {lead.source_platform}",
                f"Creator: {lead.creator_name}",
                f"Subscribers: {subscribers}",
                f"Sponsored Date: {cls._display_date(lead.sponsored_date)}",
                "Sponsored Video:",
                lead.video_url,
            ]
        )

    def send_new_lead(self, lead: SponsorLead) -> None:
        self._post(self.new_lead_message(lead))
