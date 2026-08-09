# Sponsorship Leads Setup

## Client monday.com board

Board: **Sponsership Leads**

- `SPONSOR_MONDAY_BOARD_ID` = `18424367188`
- `SPONSOR_MONDAY_GROUP_ID` = `topics`

Group IDs:

- New Leads = `topics`
- Contacted = `group_mm5rx4j0`
- Negotiations = `group_mm5rve03`
- Closed Deals = `group_mm5r7pbh`

The scanner creates new sponsor brands only in **New Leads**.

## Exact column IDs

The scanner is hard-mapped to these exact board columns:

| Column | Column ID | Type | Scanner behavior |
|---|---|---|---|
| Brand | `name` | Item Name | Brand/company name; primary parent item |
| Outreach Status | `color_mm5rvpv9` | Status | Set to `New Lead` only on creation |
| Email Status | `color_mm62kst6` | Status | Never set or overwritten by scanner |
| Brand Domain | `link_mm62hm2e` | Link | Written by scanner; used for brand dedupe |
| Contact Email | `email_mm62m6r9` | Email | Written when a public business email is found; used for backup dedupe |
| Platform | `dropdown_mm62y6v7` | Dropdown | YouTube in V1 |
| Creator | `text_mm621kk9` | Text | Creator where the sponsorship was discovered |
| Creator URL | `link_mm6239bh` | Link | Creator/channel URL |
| Creator Subscribers | `numeric_mm62np82` | Numbers | Subscriber count |
| Sponsored Video | `link_mm62nhcr` | Link | Sponsorship source video |
| Sponsored Date | `date_mm626p50` | Date | Upload/publish date of sponsored content |
| Date Found | `date_mm62megm` | Date | Date scanner discovered the brand |
| Subitems | `subtasks_mm5reseg` | Subitems | Not written by scanner; monday automations create Creator 1 through Creator 6 |

## Outreach Status labels

- Awaiting
- New Lead
- Matching
- Contacted
- In Conversation
- Discovery Call Booked
- Discovery Call Complete
- Agreement Sent
- Negotiation
- Closed Won
- Closed Lost
- Incorrect Email
- Bad Match
- Archive

The scanner sets `New Lead` when it creates a brand and never updates Outreach Status afterward.

## Email Status labels

- Starter
- Mid-Market
- Enterprise
- Manual
- Follow-Up
- Final Email

Email Status triggers email automations, so the scanner deliberately leaves it blank and never overwrites it.

## Brand-level duplicate rule

**One monday parent item = one brand/company forever.**

Creator identity is never used to decide whether a brand is a duplicate.

Before adding any sponsor, the scanner reads the full monday board and builds the duplicate index from:

1. normalized Brand/item name
2. normalized Brand Domain
3. Contact Email and its domain

Examples that all resolve to the same brand:

- `NordVPN`
- `Nord VPN`
- `nordvpn.com`
- `go.nordvpn.com`
- `partnerships@nordvpn.com`

If NordVPN already exists anywhere on the board, another NordVPN sponsorship does not create another parent item regardless of the creator, video, group, or outreach status.

The scanner performs duplicate checks before discovery, after brand enrichment, and again immediately before monday writes.

## Creator match subitems

The scanner does not populate or manage the six creator-match subitems. Existing monday automations create:

- Creator 1
- Creator 2
- Creator 3
- Creator 4
- Creator 5
- Creator 6

These are for the team to match its own creators to the brand opportunity and are separate from the source Creator column on the parent sponsor item.

## GitHub Secrets

Required:

- `YOUTUBE_API_KEY`
- `SPONSOR_MONDAY_TOKEN`

Optional:

- `DISCORD_WEBHOOK_URL`

`SPONSOR_MONDAY_API_KEY` can be used instead of `SPONSOR_MONDAY_TOKEN`.

## Optional GitHub Variables

The client board/group are already project defaults, but these can override them:

- `SPONSOR_MONDAY_BOARD_ID` = `18424367188`
- `SPONSOR_MONDAY_GROUP_ID` = `topics`
- `SPONSOR_TARGET_DAILY_LEADS` = `20`
- `SPONSOR_MIN_LEAD_SCORE` = `70`
- `SPONSOR_SEARCH_REGION` = `US`
- `SPONSOR_SEARCH_LANGUAGE` = `en`
- `ENABLE_INSTAGRAM_SPONSOR_SCAN` = `false`
- `ENABLE_TIKTOK_SPONSOR_SCAN` = `false`

## Daily schedule

`.github/workflows/scan-sponsors.yml` runs daily at `14:00 UTC` and can also be run manually from GitHub Actions.

The scanner starts with the last 24 hours. If there are not enough qualified unique sponsor brands, it expands to 72 hours and then 7 days. It does not lower quality or re-import duplicate brands just to force 20.

## Current source

YouTube is the active V1 source. Instagram and TikTok remain future adapters.

## Public contact data

Email enrichment only uses public business contact information found on a sponsor-owned public website. It does not guess private email addresses.