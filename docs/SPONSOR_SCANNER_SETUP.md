# Sponsorship Leads Setup

## What the scanner is for

This project finds **brands actively spending on creator sponsorships**, not creators to recruit.

Creator/channel/video fields are kept only as evidence showing where the active sponsorship was found. Creator niche, creator size, and creator identity do not make a sponsor eligible.

A lead must pass all of these gates before it reaches monday.com:

1. recent sponsorship evidence
2. a usable sponsor/brand domain
3. a public business contact email on a sponsor-owned domain
4. Gaming, Consumer Tech, Software/SaaS, Cybersecurity/VPN, or Food & Beverage fit
5. minimum lead score
6. permanent blocklist check
7. full monday.com brand-level duplicate check

## Active sponsorship freshness

`SPONSOR_MAX_AGE_DAYS` defaults to `30`.

Sponsorship evidence older than that is rejected. Missing or invalid sponsorship dates are also rejected.

The final monday write repeats the freshness check so stale evidence cannot enter the board even if it was accepted earlier in a run.

## Discovery sources

### 1. YouTube

YouTube is always enabled and remains the primary source.

The scanner searches recent YouTube content using paid-product-placement metadata plus explicit sponsorship phrases/disclosures. It starts with the last 24 hours and can widen to 72 hours and 7 days if qualified inventory is low.

### 2. CreatorDB — optional coverage source

If `CREATORDB_API_KEY` is configured and the freshest native YouTube scan is below the run target, the scanner queries CreatorDB's YouTube sponsored-content index.

CreatorDB is used specifically to find **recent sponsored content with an attributed partnered brand/domain**. It is not used as a creator-directory lead source.

The query filters for:

- `isSponsored = true`
- publish time within `SPONSOR_MAX_AGE_DAYS`
- standard YouTube videos
- newest content first

The scanner then sends those brand domains through the same email enrichment, niche, score, freshness, permanent blocklist, and monday dedupe gates as native YouTube discoveries.

If `CREATORDB_API_KEY` is missing, this source is skipped cleanly and the existing YouTube scanner continues normally.

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
| Platform | `dropdown_mm62y6v7` | Dropdown | YouTube |
| Creator | `text_mm621kk9` | Text | Evidence: creator where sponsorship was observed |
| Creator URL | `link_mm6239bh` | Link | Evidence: source creator/channel URL |
| Creator Subscribers | `numeric_mm62np82` | Numbers | Evidence/context only; not used to qualify the lead |
| Sponsored Video | `link_mm62nhcr` | Link | Sponsorship evidence URL |
| Sponsored Date | `date_mm626p50` | Date | Publish date used by freshness gate |
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

If NordVPN already exists anywhere on the board, another NordVPN sponsorship does not create another parent item regardless of creator, video, group, or outreach status.

The scanner performs duplicate checks before discovery, after brand enrichment, and again immediately before monday writes.

## Permanent manual duplicate/blocklist

The scanner also has a permanent manual brand blocklist in `src/sponsor_dedupe.py`.

Every brand on that list is treated exactly like a brand already present in monday.com, even if the monday board is empty. Common naming variants and explicit aliases are normalized so a blocked brand cannot be re-imported under a shorter or alternate name.

## Hard sponsor niche filter

Only these sponsor categories are eligible:

- Gaming
- Consumer Tech
- Software / SaaS
- Cybersecurity / VPN
- Food & Beverage

Brand/domain keywords for gaming hardware, software, hosting, privacy/security, electronics/audio gear, food, beverages, energy drinks, coffee, snacks, and meals can help classify a target brand.

Festivals and event-production sponsors are explicitly rejected. Off-niche sponsors do not become eligible because they sponsored a gaming/tech creator.

## Creator match subitems

The source Creator field on the parent is only sponsorship evidence.

The scanner does not populate or manage the six creator-match subitems. Existing monday automations create:

- Creator 1
- Creator 2
- Creator 3
- Creator 4
- Creator 5
- Creator 6

Those subitems are where the team matches its own creators to the sponsor opportunity.

## GitHub Secrets

Required:

- `YOUTUBE_API_KEY`
- `SPONSOR_MONDAY_TOKEN`
- `DISCORD_WEBHOOK_URL`

`SPONSOR_MONDAY_API_KEY` can be used instead of `SPONSOR_MONDAY_TOKEN`.

Optional second source:

- `CREATORDB_API_KEY`

No CreatorDB secret is required for the existing YouTube scanner to run.

## Optional GitHub Variables

- `SPONSOR_MONDAY_BOARD_ID` = `18424367188`
- `SPONSOR_MONDAY_GROUP_ID` = `topics`
- `SPONSOR_MIN_LEAD_SCORE` = `70`
- `SPONSOR_MAX_AGE_DAYS` = `30`
- `CREATORDB_PAGE_SIZE` = `50`
- `SPONSOR_SEARCH_REGION` = `US`
- `SPONSOR_SEARCH_LANGUAGE` = `en`
- `ENABLE_INSTAGRAM_SPONSOR_SCAN` = `false`
- `ENABLE_TIKTOK_SPONSOR_SCAN` = `false`

`SPONSOR_TARGET_DAILY_LEADS` remains an internal compatibility setting, but the scheduled GitHub workflow hard-caps every hourly scheduled run at **1 new brand**.

## Hourly schedule

`.github/workflows/scan-sponsors.yml` runs once every hour and can also be run manually from GitHub Actions.

Every scheduled run can create **at most 1 new qualified brand**. If no active qualified brand with a public business email is available, the run creates nothing rather than lowering quality, importing stale sponsorships, or importing a duplicate.

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

## Public contact data

A public brand email is mandatory before a lead can be added. Email enrichment checks sponsor-owned public pages such as contact, help, support, legal, press, influencer, partnership, and affiliate pages.

The scanner does not guess private email addresses.
