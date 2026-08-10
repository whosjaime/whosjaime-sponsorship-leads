# Daily Researched Sponsor Queue

`data/researched_sponsors.json` is a small intake queue for active sponsors found through daily public-web research.

Each candidate should use this shape:

```json
{
  "brand_name": "Example Brand",
  "brand_domain": "example.com",
  "sponsored_date": "2026-08-09",
  "video_url": "https://www.youtube.com/watch?v=VIDEO_ID",
  "creator_name": "Example Creator",
  "creator_url": "https://www.youtube.com/@example",
  "creator_subscribers": 500000,
  "video_title": "Example sponsored video",
  "evidence": "Public YouTube video contains a clear sponsorship disclosure.",
  "contact_name": "Jane Smith",
  "contact_title": "Creator Partnerships",
  "contact_email": "jane@example.com",
  "contact_source_url": "https://example.com/team"
}
```

Required intake fields:

- `brand_name`
- `brand_domain`
- `sponsored_date`
- a direct YouTube `video_url`

Named contact fields are optional, but preferred. Daily research should prioritize public professional contacts in Creator Partnerships, Influencer Marketing, Brand Partnerships, Partnerships, Affiliate Marketing, Growth, Social, or Marketing. A publicly listed named company work email is preferred over generic `info@`, `support@`, or `hello@` inboxes.

Only public professional contact information should be used. Do not guess an email from a naming pattern, infer a private address, use leaked data, or scrape LinkedIn. The loader only preserves a researched contact email when its email domain matches the sponsor domain. Otherwise it is discarded and normal sponsor-owned website enrichment is used instead.

When a verified researched named work email exists, the scanner preserves it even if normal website enrichment also finds a generic address. Named contacts also receive a ranking boost when otherwise similar sponsor candidates are compared.

The queue is not a bypass or allowlist. On every hourly run, each researched candidate still must pass:

1. sponsor-owned website enrichment
2. public business email requirement
3. maximum sponsorship age
4. permanent do-not-reach-out/blocklist
5. full monday.com brand dedupe
6. Gaming / Consumer Tech / Software-SaaS / Cybersecurity-VPN / Food & Beverage niche gate
7. minimum lead score
8. the final monday.com duplicate gate immediately before write

The queue can safely be overwritten with a fresh researched batch each day. Brands already in monday.com will be skipped by the scanner even if they appear in the JSON queue.
