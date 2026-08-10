# Sponsorship Leads

Hourly active-sponsor discovery for a client-facing outreach workflow.

The scanner:

- runs once every hour
- adds a maximum of 1 qualified NEW sponsor company per scheduled run
- looks for brands that are actively sponsoring content now, not generic creator-directory entries
- scans recent YouTube videos for sponsorship signals and paid-promotion metadata
- can optionally use CreatorDB's sponsored-content search as a second coverage source when native YouTube discovery is below target
- requires sponsorship evidence to be no older than 30 days by default
- treats creator/channel details only as proof of the sponsorship, not as a lead-quality signal
- extracts or receives the sponsor/brand domain from the sponsored content
- finds a public business contact email from sponsor-owned websites before a lead can be created
- scans the full monday.com board before discovery and again before writes
- deduplicates at the BRAND level using brand name, domain, and contact email/domain
- never creates a second parent item just because a different creator was sponsored
- only allows Gaming, Consumer Tech, Software/SaaS, Cybersecurity/VPN, and Food & Beverage sponsors
- sends one clean Discord message only after a new brand is successfully added to monday.com

YouTube remains the always-on source. CreatorDB is an optional second source and the scanner runs normally when `CREATORDB_API_KEY` is not configured.

See `docs/SPONSOR_SCANNER_SETUP.md` for setup.
