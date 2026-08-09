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
        email = lead.contact_email or "Email not found"
        domain = lead.brand_domain or "Website not found"
        creator = lead.creator_name or "Unknown"
        platform = lead.source_platform or "Unknown"
        video = lead.video_url or "Video link not found"

        return "\n".join(
            [
                "🔥 **NEW SPONSOR LEAD**",
                "",
                f"**Brand:** {lead.brand_name}",
                f"**Email:** {email}",
                f"**Website:** {domain}",
                "",
                f"**Found On:** {platform}",
                f"**Creator:** {creator}",
                f"**Subscribers:** {subscribers}",
                f"**Sponsored Date:** {cls._display_date(lead.sponsored_date)}",
                "",
                "**Sponsored Video:**",
                video,
                "",
                "✅ Added to **Sponsership Leads → New Leads**",
            ]
        )

    def send_new_lead(self, lead: SponsorLead) -> None:
        """Send only after monday.com has successfully created a brand item."""
        self._post(self.new_lead_message(lead))

    def send_daily_summary(
        self,
        created: list[SponsorLead],
        duplicate_count: int,
        rejected_count: int,
        scanned_videos: int,
        errors: list[str] | None = None,
    ) -> None:
        if not self.webhook_url:
            return

        lines = [
            "📊 **Daily Sponsor Scan Complete**",
            "",
            f"**{len(created)}** new brands added",
            f"**{duplicate_count}** duplicates blocked",
            f"**{scanned_videos}** sponsored videos scanned",
            "",
            "All new leads were added to Monday.",
        ]

        errors = errors or []
        if errors:
            lines.extend(["", f"⚠️ {len(errors)} scanner warning(s) logged."])

        self._post("\n".join(lines))
