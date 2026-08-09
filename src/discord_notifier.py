from __future__ import annotations

import requests

from sponsor_models import SponsorLead


class DiscordNotifier:
    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = (webhook_url or "").strip()

    def send_daily_summary(self, created: list[SponsorLead], duplicate_count: int, rejected_count: int, scanned_videos: int, errors: list[str] | None = None) -> None:
        if not self.webhook_url:
            return
        errors = errors or []
        lines = [
            "**Daily Sponsor Lead Scan**",
            f"New qualified leads: **{len(created)}**",
            f"Duplicates blocked: **{duplicate_count}**",
            f"Low-confidence/rejected: **{rejected_count}**",
            f"YouTube videos scanned: **{scanned_videos}**",
        ]
        if created:
            lines += ["", "**New leads**"]
            for lead in created[:20]:
                lines.append(f"• **{lead.brand_name}** — {lead.creator_genre}: {lead.creator_name} — {lead.lead_score}/100 — {lead.contact_email or 'email not found'}")
        if errors:
            lines += ["", f"Warnings: {len(errors)}"]
            lines.extend(f"• {error[:250]}" for error in errors[:5])
        response = requests.post(self.webhook_url, json={"content": "\n".join(lines)[:1990]}, timeout=20)
        if response.status_code >= 400:
            raise RuntimeError(f"Discord webhook error {response.status_code}: {response.text[:500]}")
