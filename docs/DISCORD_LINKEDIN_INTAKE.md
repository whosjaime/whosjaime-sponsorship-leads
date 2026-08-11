# Discord LinkedIn Sponsor Intake

This is a manual, human-in-the-loop sponsor intake lane.

## How it works

1. Jaime posts an exact public LinkedIn post URL in the configured Discord intake channel.
2. The GitHub Action checks the channel every 5 minutes using a Discord bot token.
3. The intake reads only the Discord message object and Discord-provided link preview. It does not request or scrape LinkedIn.
4. Before any Monday write, the sponsor identity is checked against GitHub's shared sponsor duplicate ledger (`data/sent_sponsor_keys.json`) plus the permanent GitHub blocklist.
5. If the preview exposes enough sponsorship evidence to identify the sponsor and sponsor-owned domain, the system researches the sponsor's public website for a business email and checks the GitHub duplicate ledger again using the normalized domain/email identity.
6. A new manual LinkedIn sponsor is created in Monday even when no public email is found, because the Discord submission itself is an explicit manual lead selection.
7. After Monday successfully creates the brand, its normalized identity is immediately added to the GitHub duplicate ledger so YouTube discovery and future LinkedIn intake cannot send it again.
8. The normal Discord NEW SPONSOR LEAD alert is sent after Monday confirms creation.
9. The original Discord message gets a bot reaction:
   - ✅ added to Monday and recorded in the GitHub duplicate ledger
   - 🔁 already in the GitHub duplicate ledger or permanently blocked
   - ⚠️ not enough preview data to safely identify the sponsor website

Monday is a destination for sponsor records. It is not used as the duplicate source of truth.

## If Discord cannot identify the website

Repost the LinkedIn URL with a simple website hint:

```text
https://www.linkedin.com/posts/...
Website: brand.com
```

Optionally include the brand name too:

```text
https://www.linkedin.com/posts/...
Brand: Brand Name
Website: brand.com
```

The intake deliberately does not guess a company domain from a LinkedIn profile or scrape LinkedIn to fill missing data.

## Discord app setup

Create or reuse a Discord application with a bot user, then enable Message Content access so the bot can read message content and embeds in the intake channel.

Give the bot only the permissions needed in the intake channel:

- View Channel
- Read Message History
- Send Messages
- Add Reactions

Add these GitHub settings:

### Repository secret

- `DISCORD_BOT_TOKEN` — Discord bot token. Never commit this value.

### Repository variable

- `DISCORD_LINKEDIN_CHANNEL_ID` — numeric ID of the Discord channel where LinkedIn posts will be submitted.

Existing sponsor delivery settings are reused:

- `DISCORD_WEBHOOK_URL`
- `SPONSOR_MONDAY_TOKEN` (or `SPONSOR_MONDAY_API_KEY`)
- `SPONSOR_MONDAY_BOARD_ID`
- `SPONSOR_MONDAY_GROUP_ID`

Optional:

- `SPONSOR_LINKEDIN_SOURCE_LABEL` — defaults to `LinkedIn`.

## Privacy / platform boundary

The intake never logs into LinkedIn, sends LinkedIn requests, crawls LinkedIn pages, or searches LinkedIn profiles. The user explicitly supplies the post URL. Sponsorship text used by the processor comes only from the Discord message and preview Discord exposed. Email enrichment occurs only on the sponsor's public business website.
