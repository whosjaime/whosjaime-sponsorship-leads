# Sponsorship Leads

Hourly active-sponsor discovery for a client-facing outreach workflow.

The scanner:

- runs once every hour
- adds a maximum of 1 qualified NEW sponsor company per scheduled run
- looks for brands that are actively sponsoring content now, not generic creator-directory entries
- scans recent YouTube videos for sponsorship signals and paid-promotion metadata
- uses Creatomap's public sponsor API as a zero-wait second source when the freshest YouTube scan is below target
- can optionally use CreatorDB as additional coverage later if an API key becomes available
- requires sponsorship evidence to be no older than 30 days by default
- requires actual YouTube video evidence from external sponsorship indexes before a lead is eligible
- treats creator/channel details only as proof of the sponsorship, not as a lead-quality signal
- extracts or receives the sponsor/brand domain from the sponsored content
- finds a public business contact email from sponsor-owned websites before a lead can be created
- scans the full monday.com board before discovery and again before writes
- deduplicates at the BRAND level using brand name, domain, and contact email/domain
- never creates a second parent item just because a different creator was sponsored
- only allows Gaming, Consumer Tech, Software/SaaS, Cybersecurity/VPN, and Food & Beverage sponsors
- sends one clean Discord message only after a new brand is successfully added to monday.com

Source order:

1. Native YouTube sponsorship discovery from the last 24 hours
2. Creatomap public API (no login, approval, or API key)
3. CreatorDB only when `CREATORDB_API_KEY` is configured
4. Wider native YouTube lookbacks when the run still has no qualified new brand

Launch does not depend on CreatorDB access.

See `docs/SPONSOR_SCANNER_SETUP.md` for setup.
