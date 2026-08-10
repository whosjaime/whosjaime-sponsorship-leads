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
  "evidence": "Public YouTube video contains a clear sponsorship disclosure."
}
```

Required intake fields:

- `brand_name`
- `brand_domain`
- `sponsored_date`
- a direct YouTube `video_url`

The queue is not a bypass or allowlist. On every hourly run, each researched candidate still must pass:

1. sponsor-owned website enrichment
2. public business email discovery
3. maximum sponsorship age
4. permanent do-not-reach-out/blocklist
5. full monday.com brand dedupe
6. Gaming / Consumer Tech / Software-SaaS / Cybersecurity-VPN / Food & Beverage niche gate
7. minimum lead score
8. the final monday.com duplicate gate immediately before write

The queue can safely be overwritten with a fresh researched batch each day. Brands already in monday.com will be skipped by the scanner even if they appear in the JSON queue.
