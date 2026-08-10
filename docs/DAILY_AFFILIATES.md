# Daily Creator Affiliate Opportunities

This is a separate Discord-only workflow. It does not write affiliate opportunities to Monday.com and it does not share the sponsorship duplicate list.

## Daily target

Aim for up to 20 strong, verified creator affiliate programs per day.

Priority categories:
- Gaming
- Consumer Tech / PC Hardware / Accessories
- Software / Creator Tools
- Food & Drinks

These are priorities, not hard limits. Strong creator-friendly programs from other categories such as fashion, beauty, lifestyle, home, travel, entertainment, fitness, pets, or other relevant verticals may be included.

## Brand-size mix

Keep the list useful across the creator roster by intentionally mixing brand sizes. A good target is approximately:
- 5 larger / established brands
- 8 mid-size brands
- 7 smaller / emerging brands

This is a quality guideline, not a quota. Never add weak or questionable programs just to fill a tier.

Smaller and emerging brands are valuable because they can create more accessible opportunities for smaller creators. Larger established programs remain useful for bigger creators. The goal is a healthy mix rather than optimizing for one company size.

## Required fields

Each queue item in `data/daily_affiliates.json` should include:

```json
{
  "brand_name": "Example Brand",
  "brand_size": "emerging",
  "category": "Gaming",
  "commission": "15% per sale",
  "website": "example.com",
  "apply_url": "https://example.com/affiliate",
  "source_url": "https://example.com/affiliate"
}
```

`brand_size` should normally be `large`, `mid-size`, or `emerging` and is used for research balance only. It is not displayed in Discord.

The program should be verified from an official brand affiliate page or a legitimate affiliate-network listing for that brand. Do not invent commission rates. If an otherwise strong program does not publicly state the commission, use a clear value such as `Not publicly listed` rather than guessing.

## Discord format

Keep the message intentionally simple:

```text
DAILY CREATOR AFFILIATE OPPORTUNITIES
August 10, 2026

1. BRAND NAME
Category: Gaming
Commission: 15% per sale
Website: https://brand.com
Apply: https://brand.com/affiliate
```

No Best For field. No cookie-length field. No emoji on each brand.

The sender splits the daily list into groups of five so the Discord posts remain easy to scan.

## Duplicate rules

`data/affiliate_duplicates.json` is the permanent affiliate-program ledger. It is separate from sponsorship dedupe.

Once an affiliate opportunity has been posted, its brand/domain/application URL are recorded and future daily research should exclude it. A brand that exists on the sponsorship list is still eligible for the affiliate list unless it has already appeared in the affiliate duplicate ledger.

## Quality rule

20 is a target, not permission to use filler. If fewer than 20 worthwhile, verified, new programs are available, send fewer. Prefer useful opportunities over hitting an arbitrary count.
