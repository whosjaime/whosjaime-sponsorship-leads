from __future__ import annotations

import os

import requests


def main() -> None:
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        raise SystemExit("DISCORD_WEBHOOK_URL is required for sponsor scan failure alerts")

    run_url = os.getenv("GITHUB_RUN_URL", "").strip()
    content = (
        "🚨 **SPONSOR SCANNER ERROR**\n\n"
        "The hourly YouTube sponsorship scanner hit a technical error and did not complete normally.\n"
        "No quality filters were lowered and no duplicate safeguards were bypassed."
    )
    if run_url:
        content += f"\n\n🔗 **GitHub Run:** <{run_url}>"

    response = requests.post(
        webhook_url,
        json={"content": content[:1990]},
        timeout=20,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Discord failure alert error {response.status_code}: {response.text[:500]}"
        )


if __name__ == "__main__":
    main()
