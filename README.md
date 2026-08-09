# Sponsorship Leads

Hourly sponsor lead discovery for a client-facing outreach workflow.

The scanner:

- runs once every hour
- adds a maximum of 1 qualified NEW sponsor company per scheduled run
- scans recent YouTube videos for sponsorship signals and paid-promotion metadata
- extracts sponsor/brand candidates from descriptions
- finds a public business contact email from sponsor-owned websites before a lead can be created
- scans the full monday.com board before discovery and again before writes
- deduplicates at the BRAND level using brand name, domain, and contact email/domain
- never creates a second parent item just because a different creator was sponsored
- sends one clean Discord message only after a new brand is successfully added to monday.com

YouTube is the working V1 source. Instagram and TikTok are optional future adapters.

See `docs/SPONSOR_SCANNER_SETUP.md` for setup.
