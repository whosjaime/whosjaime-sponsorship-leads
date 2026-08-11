from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

from sponsor_dedupe import normalize_domain, normalize_email

EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)

# Outreach relevance comes first. Generic support/contact inboxes are only fallbacks.
PREFERRED_EMAILS = {
    "sponsorship": (120, "Sponsorships"),
    "sponsor": (118, "Sponsorships"),
    "partnership": (116, "Partnerships"),
    "partner": (114, "Partnerships"),
    "creator": (112, "Creator Partnerships"),
    "influencer": (110, "Influencer Marketing"),
    "collab": (108, "Creator Partnerships"),
    "ambassador": (106, "Creator Partnerships"),
    "affiliate": (104, "Affiliate Partnerships"),
    "marketing": (96, "Marketing"),
    "bizdev": (92, "Business Development"),
    "business": (88, "Business"),
    "brand": (86, "Brand Partnerships"),
    "press": (70, "Press"),
    "media": (68, "Media"),
    "hello": (52, "General"),
    "info": (50, "General"),
    "contact": (48, "General"),
    "support": (20, "Support"),
}
DIRECT_EMAIL_SCORE = 86
BLOCKED_LOCALPARTS = {
    "noreply", "no-reply", "donotreply", "privacy", "legal", "abuse",
    "security", "careers", "jobs", "hr", "billing",
}
CONTACT_HINTS = {
    "contact", "help", "support", "legal", "impressum", "partnership", "partner",
    "sponsor", "creator", "influencer", "affiliate", "marketing", "press", "media",
    "ambassador", "collab", "brand", "about", "company",
}

# Always probe these high-intent paths before accepting a generic inbox found elsewhere.
DIRECT_CONTACT_PATHS = [
    "/sponsorships",
    "/sponsors",
    "/partnerships",
    "/partners",
    "/brand-partnerships",
    "/creator-partnerships",
    "/creator-partnership",
    "/creators",
    "/creator-program",
    "/influencers",
    "/influencer-program",
    "/influencer-sign-up",
    "/ambassadors",
    "/collaborate",
    "/collabs",
    "/affiliate",
    "/affiliates",
    "/marketing",
]

# Keep the historical full path list for compatibility. Direct paths are fetched first;
# the second pass skips anything already seen and only adds generic fallbacks.
COMMON_CONTACT_PATHS = [
    *DIRECT_CONTACT_PATHS,
    "/contact",
    "/contact-us",
    "/press",
    "/media",
    "/help",
    "/help/contact",
    "/help/legal",
    "/legal",
    "/hilfe/impressum",
    "/impressum",
    "/prensa",
]
CATEGORY_RULES = {
    "Software / SaaS": {
        "software", "saas", "platform", "productivity", "workflow", "cloud", "app",
        "mobile app", "browser", "web app", "web hosting", "hosting", "website builder",
        "developer", "developer tool", "devtool", "coding", "automation", "api", "no-code",
        "artificial intelligence", " ai ", "ai tool", "cloud storage", "project management",
        "design software", "editing software", "streaming software",
    },
    "Cybersecurity / VPN": {
        "vpn", "cybersecurity", "online privacy", "password manager", "internet security",
        "identity protection", "data breach", "privacy protection", "antivirus", "malware",
        "identity theft", "secure browsing",
    },
    "Finance": {"banking", "credit card", "investing", "finance", "payments", "insurance"},
    "Food & Beverage": {
        "meal", "food", "recipe", "snack", "beverage", "coffee", "drink", "energy drink",
        "soda", "sparkling water", "hydration", "protein bar", "protein snack", "candy", "chips",
        "meal delivery", "meal kit", "jerky", "hot sauce", "sauce", "snack bar", "nutrition bar",
    },
    "Health & Wellness": {"wellness", "health", "supplement", "vitamin", "therapy", "sleep", "fitness"},
    "Beauty": {"beauty", "skincare", "cosmetics", "makeup", "haircare"},
    "Fashion": {"fashion", "apparel", "clothing", "footwear", "jewelry"},
    "Gaming": {
        "gaming", "gamer", "games", "esports", "gaming gear", "gaming peripheral",
        "controller", "console", "pc gaming", "game server", "game hosting", "gaming chair",
        "gaming desk", "game key", "gaming accessories",
    },
    "Consumer Tech": {
        "headphones", "headset", "earbuds", "keyboard", "laptop", "smartphone", "camera", "electronics",
        "gadget", "microphone", "webcam", "speaker", "monitor", "computer hardware", "mouse",
        "audio interface", "tech accessories", "charger", "power bank", "router", "ssd", "storage",
        "gpu", "graphics card", "cpu", "processor", "capture card", "smart home", "wearable",
        "phone accessory", "mousepad", "desk", "gaming chair",
    },
    "Travel": {"travel", "hotel", "flight", "vacation", "tourism", "booking"},
    "Education": {"education", "learning", "course", "tutoring"},
    "Home": {"furniture", "mattress", "home", "kitchen", "cleaning", "decor"},
    "Automotive": {"automotive", "vehicle", "car", "cars", "auto"},
    "Entertainment": {
        "streaming", "entertainment", "movies", "music", "podcast", "festival", "concert",
        "live event", "event production", "venue",
    },
}
SUBCATEGORY_RULES = {
    "VPN": {"vpn", "virtual private network"},
    "Cybersecurity": {"cybersecurity", "online security", "antivirus", "malware"},
    "Password Manager": {"password manager"},
    "Meal Delivery": {"meal delivery", "meal kit"},
    "Energy Drink": {"energy drink"},
    "Snacks": {"snack", "candy", "chips", "protein bar", "jerky", "nutrition bar"},
    "Coffee": {"coffee"},
    "Web Hosting": {"web hosting", "hosting provider", "hosting"},
    "Website Builder": {"website builder"},
    "AI / Productivity": {"ai tool", "artificial intelligence", "productivity", "workflow", "automation"},
    "Gaming Gear": {"gaming gear", "gaming peripheral", "controller", "gaming headset", "gaming chair"},
    "Computer Hardware": {"gpu", "graphics card", "cpu", "processor", "ssd", "computer hardware"},
    "Audio Gear": {"microphone", "audio interface", "headphones", "earbuds", "speaker"},
    "Banking": {"bank account", "banking"},
    "Credit Cards": {"credit card"},
    "Supplements": {"supplement", "vitamin"},
    "Skincare": {"skincare", "skin care"},
    "Apparel": {"apparel", "clothing"},
}


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            for key, value in attrs:
                if key.lower() == "href" and value:
                    self.links.append(value)

    def handle_data(self, data):
        if data.strip():
            self.text.append(data.strip())


class BrandEnricher:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; SponsorLeadScanner/1.0; public-business-contact-research)"
        })

    def _fetch(self, url: str) -> tuple[str, str]:
        try:
            response = self.session.get(url, timeout=12, allow_redirects=True)
            if response.status_code >= 400 or "html" not in response.headers.get("Content-Type", "").lower():
                return "", ""
            return response.url, response.text[:1_000_000]
        except requests.RequestException:
            return "", ""

    @staticmethod
    def _parse(page: str) -> tuple[list[str], str]:
        parser = _Parser()
        try:
            parser.feed(page)
        except Exception:
            pass
        return parser.links, re.sub(r"\s+", " ", html.unescape(" ".join(parser.text)))[:150000]

    @staticmethod
    def _same_domain(candidate: str, domain: str) -> bool:
        candidate_domain = normalize_domain(candidate)
        brand_domain = normalize_domain(domain)
        return (
            candidate_domain == brand_domain
            or candidate_domain.endswith(f".{brand_domain}")
            or brand_domain.endswith(f".{candidate_domain}")
        )

    def _rank_email(self, email: str, domain: str) -> tuple[int, str]:
        email = normalize_email(email)
        if "@" not in email:
            return -1, ""
        local, host = email.rsplit("@", 1)
        if local.lower() in BLOCKED_LOCALPARTS or not self._same_domain(host, domain):
            return -1, ""

        matches = [
            scored
            for keyword, scored in PREFERRED_EMAILS.items()
            if keyword in local.lower()
        ]
        if matches:
            return max(matches, key=lambda value: value[0])
        return 45, "Public Business Contact"

    @staticmethod
    def _classify(text: str) -> tuple[str, str]:
        lowered = f" {text.lower()} "
        scores = {k: sum(1 for word in v if word in lowered) for k, v in CATEGORY_RULES.items()}
        category = max(scores, key=scores.get) if scores and max(scores.values()) else "Other"
        subs = {k: sum(1 for word in v if word in lowered) for k, v in SUBCATEGORY_RULES.items()}
        subcategory = max(subs, key=subs.get) if subs and max(subs.values()) else ""
        return category, subcategory

    def _extract_ranked_emails(self, pages: list[tuple[str, str]], domain: str) -> tuple[list[tuple[int, str, str, str]], list[str]]:
        ranked: list[tuple[int, str, str, str]] = []
        all_text: list[str] = []
        for source, page in pages:
            _, text = self._parse(page)
            all_text.append(text)
            emails = set(EMAIL_RE.findall(html.unescape(page))) | set(EMAIL_RE.findall(text))
            for email in emails:
                email = normalize_email(email).strip(".,;:()[]<>")
                score, email_type = self._rank_email(email, domain)
                if score >= 0:
                    # A named/public work email found on an explicit partnerships or
                    # creator page is more useful than a generic homepage inbox.
                    source_lower = source.lower()
                    if score == 45 and any(
                        hint in source_lower
                        for hint in ("partnership", "sponsor", "creator", "influencer", "collab", "affiliate")
                    ):
                        score = 82
                        email_type = "Partnership Page Contact"
                    ranked.append((score, email, email_type, source))
        ranked.sort(key=lambda x: (-x[0], x[1]))
        return ranked, all_text

    def _fetch_paths(
        self,
        base_url: str,
        domain: str,
        paths: list[str],
        seen_urls: set[str],
        pages: list[tuple[str, str]],
    ) -> None:
        for path in paths:
            url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
            if url in seen_urls:
                continue
            fetched_url, page = self._fetch(url)
            if not page:
                continue
            clean = (fetched_url or url).split("#", 1)[0]
            if clean in seen_urls:
                continue
            if not self._same_domain(urlparse(clean).netloc, domain):
                continue
            seen_urls.add(clean)
            pages.append((clean, page))

    def enrich(self, domain: str) -> dict:
        domain = normalize_domain(domain)
        empty = {
            "domain": domain,
            "contact_email": "",
            "email_type": "",
            "contact_source": "",
            "category": "Other",
            "subcategory": "",
        }
        if not domain:
            return empty

        final_url, homepage = self._fetch(f"https://{domain}")
        if not homepage:
            final_url, homepage = self._fetch(f"http://{domain}")
        if not homepage:
            return empty

        domain = normalize_domain(final_url) or domain
        base_url = final_url or f"https://{domain}"
        links, home_text = self._parse(homepage)
        pages: list[tuple[str, str]] = [(base_url, homepage)]
        seen_urls = {base_url.split("#", 1)[0]}

        relevant: list[str] = []
        for href in links:
            absolute = urljoin(base_url, href)
            parsed = urlparse(absolute)
            path_text = f"{parsed.path} {parsed.query}".lower()
            if (
                parsed.scheme in {"http", "https"}
                and self._same_domain(parsed.netloc, domain)
                and any(hint in path_text for hint in CONTACT_HINTS)
            ):
                clean = absolute.split("#", 1)[0]
                if clean not in seen_urls and clean not in relevant:
                    relevant.append(clean)
            if len(relevant) >= 14:
                break

        for url in relevant:
            fetched_url, page = self._fetch(url)
            if page:
                clean = (fetched_url or url).split("#", 1)[0]
                if clean not in seen_urls:
                    seen_urls.add(clean)
                    pages.append((clean, page))

        # Critical behavior: always probe direct outreach pages before accepting
        # contact@ / info@ / support@ found on the homepage.
        self._fetch_paths(base_url, domain, DIRECT_CONTACT_PATHS, seen_urls, pages)
        ranked, all_text = self._extract_ranked_emails(pages, domain)

        # Only spend time on generic contact/help/legal paths when a strong direct
        # sponsorship/partnership/creator/marketing address was not found.
        if not ranked or ranked[0][0] < DIRECT_EMAIL_SCORE:
            self._fetch_paths(base_url, domain, COMMON_CONTACT_PATHS, seen_urls, pages)
            ranked, all_text = self._extract_ranked_emails(pages, domain)

        best = ranked[0] if ranked else None
        category, subcategory = self._classify(" ".join([home_text] + all_text))
        return {
            "domain": domain,
            "contact_email": best[1] if best else "",
            "email_type": best[2] if best else "",
            "contact_source": best[3] if best else "",
            "category": category,
            "subcategory": subcategory,
        }
