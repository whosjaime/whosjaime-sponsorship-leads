# Sponsorship Leads

Hourly active-sponsor discovery for a client-facing outreach workflow.

The scanner:

- runs once every hour
- adds a maximum of 1 qualified NEW sponsor company per scheduled run
- looks for brands that are actively sponsoring content now, not generic creator-directory entries
- uses the official YouTube Data API already configured for the project
- runs exactly 3 YouTube sponsorship search lanes per scheduled scan
- searches declared paid placements, combined sponsor-disclosure language, and target-niche paid placements
- also reads `data/researched_sponsors.json`, a separate daily-research intake queue for externally researched active sponsors
- requires every researched candidate to include a recent sponsored YouTube video before it can enter the normal pipeline
- requires sponsorship evidence to be no older than 30 days by default
- treats creator/channel details only as proof of the sponsorship, not as a lead-quality signal
- extracts the sponsor/brand domain from the sponsored content or researched evidence
- finds a public business contact email from sponsor-owned websites before a lead can be created
- scans the full monday.com board before discovery and again before writes
- deduplicates at the BRAND level using brand name, domain, and contact email/domain
- never creates a second parent item just because a different creator was sponsored
- only allows Gaming, Consumer Tech, Software/SaaS, Cybersecurity/VPN, and Food & Beverage sponsors
- sends one clean Discord message only after a new brand is successfully added to monday.com

The daily research queue does not bypass any safeguards. Researched brands still pass the public-email requirement, permanent blocklist, full monday.com duplicate scan, freshness gate, niche gate, lead-score threshold, and final write gate.

Launch does not require a CreatorDB account, Creatomap scraper, or any other third-party sponsorship database.

CreatorDB remains optional extra coverage if `CREATORDB_API_KEY` is ever configured, but the scheduled production scanner works without it.

See `docs/SPONSOR_SCANNER_SETUP.md` for setup.
