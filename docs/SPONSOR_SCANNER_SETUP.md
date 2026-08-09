# Sponsorship Leads Setup

## 1. GitHub Secrets

Add these in Settings → Secrets and variables → Actions → Secrets:

- `YOUTUBE_API_KEY`
- `SPONSOR_MONDAY_TOKEN`
- `DISCORD_WEBHOOK_URL` (optional)

You can use `SPONSOR_MONDAY_API_KEY` instead of `SPONSOR_MONDAY_TOKEN` if preferred.

## 2. GitHub Variables

Add these in Settings → Secrets and variables → Actions → Variables:

- `SPONSOR_MONDAY_BOARD_ID`
- `SPONSOR_MONDAY_GROUP_ID` (optional if the board has a New Leads group)
- `SPONSOR_TARGET_DAILY_LEADS` = `20`
- `SPONSOR_MIN_LEAD_SCORE` = `70`
- `SPONSOR_SEARCH_REGION` = `US`
- `SPONSOR_SEARCH_LANGUAGE` = `en`
- `ENABLE_INSTAGRAM_SPONSOR_SCAN` = `false`
- `ENABLE_TIKTOK_SPONSOR_SCAN` = `false`

## 3. Recommended monday.com columns

The code identifies columns by their titles, so column IDs do not need to be hardcoded.

Strongly recommended duplicate/outreach columns:

- Brand
- Brand Domain
- Contact Email
- Brand Key
- Sponsorship Key
- Outreach Status

Recommended enrichment columns:

- Brand Category
- Brand Subcategory
- Email Type
- Email Source
- Creator
- Creator URL
- Creator Subscribers
- Creator Genre
- Creator Tags
- Platform
- Sponsored Video
- Video Title
- Sponsored Date
- Evidence
- Paid Promotion
- Lead Score
- Temperature
- Date Found

## 4. Duplicate protection

Duplicate protection is mandatory in the normal pipeline.

Every run:

1. Reads the full monday.com board using cursor pagination.
2. Builds duplicate keys from brand names, normalized domains, contact emails/email domains, Brand Key, and Sponsorship Key.
3. Discovers and enriches sponsorship candidates.
4. Re-checks duplicates after enrichment because a redirect or email can reveal the real brand domain.
5. Reads the full monday.com board again immediately before writes.
6. Adds every successfully created lead to the in-memory duplicate index so another detection in the same run cannot create it again.

Statuses such as Contacted, Outreach Sent, In Conversation, Call Booked, Client, Do Not Contact, Rejected, and Closed are protected.

## 5. Daily schedule

`.github/workflows/scan-sponsors.yml` runs daily at `14:00 UTC` and can also be run manually from GitHub Actions.

The scanner starts with the last 24 hours. If it does not have enough qualified unique sponsors, it expands to 72 hours and then 7 days. It does not lower the score threshold or re-import duplicates just to force 20 leads.

## 6. Current sources

YouTube is the active V1 source.

Instagram and TikTok flags are reserved for future official API adapters. Keep them set to `false` until those adapters and credentials are added.

## 7. Safety / data use

The email enrichment only uses public business contact information found on a sponsor's own public website. It rejects emails from unrelated domains and does not guess private personal email addresses.
