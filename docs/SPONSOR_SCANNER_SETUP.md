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

| Column | Column ID | Type | Scanner behavior |
|---|---|---|---|
| Brand | `name` | Item Name | Brand/company name; primary parent item |
| Outreach Status | `color_mm5rvpv9` | Status | Set to `New Lead` only on creation |
| Email Status | `color_mm62kst6` | Status | Never set or overwritten by scanner |
| Brand Domain | `link_mm62hm2e` | Link | Written by scanner; used for brand dedupe |
| Contact Email | `email_mm62m6r9` | Email | Required before a lead can be created; used for backup dedupe |
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

Email Status triggers email automations, so the scanner leaves it blank and never overwrites it.

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

## Permanent manual duplicate/blocklist

The scanner also has a permanent manual brand blocklist in `src/sponsor_dedupe.py`.

Every brand on that list is treated exactly like a brand that already exists in monday.com, even if the monday board is empty. The list includes the team-provided existing sponsor set such as Notion, Wix, Shopify, Squarespace, Grammarly, NordVPN, ExpressVPN, Surfshark, Hostinger, Canva, Adobe, G FUEL, Liquid Death, Gamer Supps, Monster Energy, Rare Beauty, Chewy, and the rest of the supplied brands.

Common naming variants are normalized, and explicit aliases such as `PIA` / `Private Internet Access` and `CyberGhost` / `CyberGhost VPN` are included so they cannot be re-imported under a shorter name.

## Sponsor targeting priority

The hourly scanner prioritizes sponsors that fit the creator roster best.

Highest priority sponsor categories:

- Gaming
- Consumer Tech
- Software / SaaS
- Cybersecurity / VPN
- Food & Beverage

Gaming, Tech, and Food creator channels also receive a targeting boost. Brand/domain keywords related to gaming, software, electronics, audio gear, food, beverages, energy drinks, coffee, snacks, and meals can also increase priority.

This is a **priority**, not a hard filter. If no qualified gaming/tech/food-drink sponsor is available, another strong new sponsor with a real public email may still be selected for the hourly lead.

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
- `DISCORD_WEBHOOK_URL`

`SPONSOR_MONDAY_API_KEY` can be used instead of `SPONSOR_MONDAY_TOKEN`.

## Optional GitHub Variables

The client board/group are already project defaults, but these can override them:

- `SPONSOR_MONDAY_BOARD_ID` = `18424367188`
- `SPONSOR_MONDAY_GROUP_ID` = `topics`
- `SPONSOR_MIN_LEAD_SCORE` = `70`
- `SPONSOR_SEARCH_REGION` = `US`
- `SPONSOR_SEARCH_LANGUAGE` = `en`
- `ENABLE_INSTAGRAM_SPONSOR_SCAN` = `false`
- `ENABLE_TIKTOK_SPONSOR_SCAN` = `false`

`SPONSOR_TARGET_DAILY_LEADS` remains an internal compatibility setting, but the scheduled GitHub workflow hard-caps every hourly scheduled run at **1 new brand**. An old repository variable cannot make a scheduled run add 20.

## Hourly schedule

`.github/workflows/scan-sponsors.yml` runs once every hour and can also be run manually from GitHub Actions.

Every scheduled run can create **at most 1 new qualified brand**. If no qualified brand with a public business email is available, the run creates nothing rather than lowering quality or importing a duplicate.

The scanner starts with recent sponsorship inventory. If it only finds non-priority sponsors, it can expand the lookback to try to find a gaming, tech, or food/drink target before using a fallback lead.

## Discord

Discord receives one message only after a new brand is successfully created in monday.com:

```text
🔥 NEW SPONSOR LEAD
Brand: Fabletics
Email: support@fabletics.co.uk
Website: fabletics.co.uk
Found On: YouTube
Creator: Ellen Miller
Subscribers: 76,200
Sponsored Date: August 9, 2026
Sponsored Video:
https://www.youtube.com/watch?v=zmP9iW6cygI
```

There is no daily summary message.

## Current source

YouTube is the active V1 source. Instagram and TikTok remain future adapters.

## Public contact data

A public brand email is mandatory before a lead can be added. Email enrichment checks sponsor-owned public pages such as contact, help, support, legal, press, influencer, partnership, and affiliate pages. The scanner does not guess private email addresses.
