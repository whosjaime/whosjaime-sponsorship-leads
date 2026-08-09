from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

from sponsor_dedupe import normalize_domain, normalize_email

EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
PREFERRED_EMAILS = {
    "sponsorship": (100, "Sponsorships"), "sponsor": (98, "Sponsorships"),
    "partnership": (96, "Partnerships"), "creator": (92, "Creator Partnerships"),
    "influencer": (90, "Influencer Marketing"), "marketing": (84, "Marketing"),
    "bizdev": (82, "Business Development"), "business": (78, "Business"),
    "press": (65, "Press"), "media": (64, "Media"), "hello": (58, "General"),
    "info": (55, "General"), "contact": (55, "General"), "support": (35, "Support"),
}
BLOCKED_LOCALPARTS = {"noreply", "no-reply", "donotreply", "privacy", "legal", "abuse", "security", "careers", "jobs", "hr", "billing"}
CONTACT_HINTS = {"contact", "partnership", "partner", "sponsor", "creator", "influencer", "affiliate", "marketing", "press", "media", "about"}
CATEGORY_RULES = {
    "Software / SaaS": {"software", "saas", "platform", "productivity", "workflow", "cloud", "app"},
    "Cybersecurity / VPN": {"vpn", "cybersecurity", "online privacy", "password manager"},
    "Finance": {"banking", "credit card", "investing", "finance", "payments", "insurance"},
    "Food & Beverage": {"meal", "food", "recipe", "snack", "beverage", "coffee"},
    "Health & Wellness": {"wellness", "health", "supplement", "vitamin", "therapy", "sleep", "fitness"},
    "Beauty": {"beauty", "skincare", "cosmetics", "makeup", "haircare"},
    "Fashion": {"fashion", "apparel", "clothing", "footwear", "jewelry"},
    "Gaming": {"gaming", "games", "esports"},
    "Consumer Tech": {"headphones", "keyboard", "laptop", "smartphone", "camera", "electronics", "gadget"},
    "Travel": {"travel", "hotel", "flight", "vacation", "tourism", "booking"},
    "Education": {"education", "learning", "course", "tutoring"},
    "Home": {"furniture", "mattress", "home", "kitchen", "cleaning", "decor"},
    "Automotive": {"automotive", "vehicle", "car", "cars", "auto"},
    "Entertainment": {"streaming", "entertainment", "movies", "music", "podcast"},
}
SUBCATEGORY_RULES = {
    "VPN": {"vpn", "virtual private network"}, "Cybersecurity": {"cybersecurity", "online security"},
    "Password Manager": {"password manager"}, "Meal Delivery": {"meal delivery", "meal kit"},
    "Web Hosting": {"web hosting", "hosting provider"}, "Website Builder": {"website builder"},
    "Banking": {"bank account", "banking"}, "Credit Cards": {"credit card"},
    "Supplements": {"supplement", "vitamin"}, "Skincare": {"skincare", "skin care"},
    "Apparel": {"apparel", "clothing"},
}


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links, self.text = [], []
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
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; SponsorLeadScanner/1.0)"})

    def _fetch(self, url: str) -> tuple[str, str]:
        try:
            r = self.session.get(url, timeout=12, allow_redirects=True)
            if r.status_code >= 400 or "html" not in r.headers.get("Content-Type", "").lower():
                return "", ""
            return r.url, r.text[:1_000_000]
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
        c, d = normalize_domain(candidate), normalize_domain(domain)
        return c == d or c.endswith(f".{d}") or d.endswith(f".{c}")

    def _rank_email(self, email: str, domain: str) -> tuple[int, str]:
        email = normalize_email(email)
        if "@" not in email:
            return -1, ""
        local, host = email.rsplit("@", 1)
        if local.lower() in BLOCKED_LOCALPARTS or not self._same_domain(host, domain):
            return -1, ""
        best = (45, "Public Business Contact")
        for keyword, scored in PREFERRED_EMAILS.items():
            if keyword in local.lower() and scored[0] > best[0]:
                best = scored
        return best

    @staticmethod
    def _classify(text: str) -> tuple[str, str]:
        lowered = text.lower()
        scores = {k: sum(1 for word in v if word in lowered) for k, v in CATEGORY_RULES.items()}
        category = max(scores, key=scores.get) if scores and max(scores.values()) else "Other"
        subs = {k: sum(1 for word in v if word in lowered) for k, v in SUBCATEGORY_RULES.items()}
        subcategory = max(subs, key=subs.get) if subs and max(subs.values()) else ""
        return category, subcategory

    def enrich(self, domain: str) -> dict:
        domain = normalize_domain(domain)
        if not domain:
            return {"domain": "", "contact_email": "", "email_type": "", "contact_source": "", "category": "Other", "subcategory": ""}
        final_url, homepage = self._fetch(f"https://{domain}")
        if not homepage:
            final_url, homepage = self._fetch(f"http://{domain}")
        if not homepage:
            return {"domain": domain, "contact_email": "", "email_type": "", "contact_source": "", "category": "Other", "subcategory": ""}
        domain = normalize_domain(final_url) or domain
        links, home_text = self._parse(homepage)
        pages = [(final_url, homepage)]
        relevant = []
        for href in links:
            absolute = urljoin(final_url, href)
            parsed = urlparse(absolute)
            if parsed.scheme in {"http", "https"} and self._same_domain(parsed.netloc, domain) and any(h in parsed.path.lower() for h in CONTACT_HINTS):
                clean = absolute.split("#", 1)[0]
                if clean not in relevant:
                    relevant.append(clean)
            if len(relevant) >= 6:
                break
        for url in relevant:
            u, p = self._fetch(url)
            if p:
                pages.append((u or url, p))
        ranked, all_text = [], [home_text]
        for source, page in pages:
            _, text = self._parse(page)
            all_text.append(text)
            for email in set(EMAIL_RE.findall(html.unescape(page))) | set(EMAIL_RE.findall(text)):
                email = normalize_email(email).strip(".,;:()[]<>")
                score, email_type = self._rank_email(email, domain)
                if score >= 0:
                    ranked.append((score, email, email_type, source))
        ranked.sort(key=lambda x: (-x[0], x[1]))
        best = ranked[0] if ranked else None
        category, subcategory = self._classify(" ".join(all_text))
        return {
            "domain": domain, "contact_email": best[1] if best else "", "email_type": best[2] if best else "",
            "contact_source": best[3] if best else "", "category": category, "subcategory": subcategory,
        }
