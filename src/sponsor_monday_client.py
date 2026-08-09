from __future__ import annotations

import json
import re
from dataclasses import dataclass

import requests

from sponsor_dedupe import ExistingSponsorIndex, email_domain, normalize_brand_name, normalize_domain, normalize_email, normalize_text
from sponsor_models import SponsorLead

MONDAY_API_URL = "https://api.monday.com/v2"
PROTECTED_OUTREACH_STATUSES = {
    "outreach sent", "contacted", "follow up", "follow-up", "in conversation", "call booked",
    "booked call", "working with", "client", "do not contact", "rejected", "not interested", "closed",
}
COLUMN_ALIASES = {
    "brand_name": ["brand", "sponsor", "company", "brand name", "sponsor name"],
    "brand_domain": ["domain", "website", "brand domain", "sponsor domain", "brand website"],
    "contact_email": ["contact email", "email", "sponsor email", "partnership email", "brand email"],
    "email_type": ["email type", "contact type"],
    "contact_source": ["email source", "contact source", "source url"],
    "sponsor_category": ["brand category", "sponsor category", "category"],
    "sponsor_subcategory": ["brand subcategory", "sponsor subcategory", "subcategory"],
    "creator_name": ["creator", "creator name", "influencer", "channel"],
    "creator_url": ["creator url", "channel url", "creator profile", "creator link"],
    "creator_subscribers": ["creator subscribers", "subscribers", "subscriber count"],
    "creator_genre": ["creator genre", "genre", "creator niche", "niche"],
    "creator_tags": ["creator tags", "tags"],
    "source_platform": ["platform", "source platform"],
    "video_url": ["video url", "sponsored video", "content url", "sponsor video"],
    "video_title": ["video title", "content title"],
    "sponsored_date": ["sponsored date", "published date", "ad date", "sponsorship date"],
    "evidence": ["evidence", "sponsor evidence", "sponsorship evidence", "notes"],
    "paid_product_placement": ["paid promotion", "paid placement", "paid product placement"],
    "lead_score": ["lead score", "score", "warm lead score"],
    "lead_temperature": ["temperature", "lead temperature", "warmth"],
    "sponsorship_key": ["sponsorship key", "event key", "sponsor event key"],
    "brand_key": ["brand key", "dedupe key", "sponsor key"],
    "outreach_status": ["outreach status", "status", "lead status"],
    "date_found": ["date found", "found date", "date added"],
}


@dataclass
class ColumnInfo:
    id: str
    title: str
    type: str


class SponsorMondayClient:
    def __init__(self, token: str, board_id: int, group_id: str = "", api_version: str = "2025-04") -> None:
        self.token = token
        self.board_id = int(board_id)
        self.requested_group_id = group_id
        self.session = requests.Session()
        self.session.headers.update({"Authorization": token, "Content-Type": "application/json", "API-Version": api_version})
        self._columns = None
        self._groups = None

    def _request(self, query: str, variables: dict | None = None) -> dict:
        response = self.session.post(MONDAY_API_URL, json={"query": query, "variables": variables or {}}, timeout=30)
        try:
            data = response.json()
        except Exception as exc:
            raise RuntimeError(f"Invalid monday response: {response.text[:1000]}") from exc
        if response.status_code != 200 or data.get("errors"):
            raise RuntimeError(f"monday API error: {json.dumps(data, indent=2)[:3000]}")
        return data

    @staticmethod
    def _norm_title(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (value or "").strip().lower()).strip()

    def load_schema(self):
        if self._columns is not None:
            return self._columns, self._groups
        query = """
        query SponsorBoardSchema($board_id: ID!) {
          boards(ids: [$board_id]) { name groups { id title } columns { id title type } }
        }
        """
        data = self._request(query, {"board_id": self.board_id})
        boards = data.get("data", {}).get("boards", [])
        if not boards:
            raise RuntimeError(f"Sponsor monday board {self.board_id} is not accessible.")
        board = boards[0]
        self._groups = board.get("groups", []) or []
        raw = [ColumnInfo(c["id"], c.get("title", ""), c.get("type", "")) for c in board.get("columns", [])]
        by_title = {self._norm_title(c.title): c for c in raw}
        resolved = {}
        for field, aliases in COLUMN_ALIASES.items():
            for alias in aliases:
                if self._norm_title(alias) in by_title:
                    resolved[field] = by_title[self._norm_title(alias)]
                    break
        self._columns = resolved
        return resolved, self._groups

    def resolved_group_id(self) -> str:
        _, groups = self.load_schema()
        if self.requested_group_id:
            if any(g.get("id") == self.requested_group_id for g in groups):
                return self.requested_group_id
            raise RuntimeError(f"SPONSOR_MONDAY_GROUP_ID {self.requested_group_id!r} is not on this board.")
        for group in groups:
            if self._norm_title(group.get("title", "")) in {"new leads", "new lead", "leads"}:
                return group.get("id", "")
        return groups[0].get("id", "") if groups else ""

    def _get_all_items(self) -> list[dict]:
        first = """
        query SponsorItems($board_id: ID!) {
          boards(ids: [$board_id]) {
            items_page(limit: 500) { cursor items { id name column_values { id text value } } }
          }
        }
        """
        data = self._request(first, {"board_id": self.board_id})
        boards = data.get("data", {}).get("boards", [])
        if not boards:
            return []
        page = boards[0].get("items_page", {}) or {}
        items = list(page.get("items", []) or [])
        cursor = page.get("cursor")
        next_query = """
        query NextSponsorItems($cursor: String!) {
          next_items_page(limit: 500, cursor: $cursor) { cursor items { id name column_values { id text value } } }
        }
        """
        while cursor:
            data = self._request(next_query, {"cursor": cursor})
            page = data.get("data", {}).get("next_items_page", {}) or {}
            items.extend(page.get("items", []) or [])
            cursor = page.get("cursor")
        return items

    @staticmethod
    def _raw_value(column: dict) -> str:
        text = column.get("text") or ""
        raw = column.get("value")
        if not raw:
            return text
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            return text
        if isinstance(parsed, dict):
            return parsed.get("url") or parsed.get("email") or parsed.get("text") or text
        return text

    def load_existing_index(self) -> ExistingSponsorIndex:
        columns, _ = self.load_schema()
        id_to_field = {c.id: field for field, c in columns.items()}
        index = ExistingSponsorIndex()
        item_count = 0
        for item in self._get_all_items():
            item_count += 1
            values = {}
            for column in item.get("column_values", []) or []:
                field = id_to_field.get(column.get("id", ""))
                if field:
                    values[field] = self._raw_value(column)
            keys = set()
            for name in [item.get("name", ""), values.get("brand_name", "")]:
                normalized = normalize_brand_name(name)
                if normalized:
                    keys.add(f"brand:{normalized}")
            domain = normalize_domain(values.get("brand_domain", ""))
            email = normalize_email(values.get("contact_email", ""))
            if domain:
                keys.add(f"domain:{domain}")
            if email:
                keys.add(f"email:{email}")
                if email_domain(email):
                    keys.add(f"domain:{email_domain(email)}")
            brand_key = normalize_text(values.get("brand_key", ""))
            if brand_key:
                keys.add(brand_key)
            index.brand_keys.update(keys)
            event_key = normalize_text(values.get("sponsorship_key", ""))
            if event_key:
                index.event_keys.add(event_key)
            status = normalize_text(values.get("outreach_status", ""))
            if status in PROTECTED_OUTREACH_STATUSES:
                index.protected_brand_keys.update(keys)
        print(f"Daily monday duplicate scan: scanned {item_count} records and loaded {len(index.brand_keys)} brand keys.")
        return index

    @staticmethod
    def _format_value(column: ColumnInfo, field: str, value, lead: SponsorLead):
        if value in (None, "", []):
            return None
        ctype = (column.type or "").lower()
        if ctype == "email":
            return {"email": str(value), "text": str(value)}
        if ctype == "link":
            url = str(value)
            if field == "brand_domain" and "://" not in url:
                url = f"https://{url}"
            labels = {"brand_domain": lead.brand_name, "creator_url": lead.creator_name, "video_url": "Sponsored Video", "contact_source": "Email Source"}
            return {"url": url, "text": labels.get(field, url)[:255]}
        if ctype == "date":
            return {"date": str(value)[:10]}
        if ctype == "status":
            return {"label": str(value)}
        if ctype == "dropdown":
            vals = value if isinstance(value, list) else [value]
            return {"labels": [str(v)[:255] for v in vals if str(v).strip()]}
        if ctype == "checkbox":
            return {"checked": "true" if bool(value) else "false"}
        if ctype in {"numbers", "numeric"}:
            return str(value)
        return ", ".join(map(str, value)) if isinstance(value, list) else str(value)

    def create_lead(self, lead: SponsorLead) -> dict:
        columns, _ = self.load_schema()
        raw = lead.as_dict()
        raw["outreach_status"] = "New Lead"
        values = {}
        for field, column in columns.items():
            formatted = self._format_value(column, field, raw.get(field), lead)
            if formatted not in (None, "", {}):
                values[column.id] = formatted
        mutation = """
        mutation CreateSponsorLead($board_id: ID!, $group_id: String, $item_name: String!, $column_values: JSON!) {
          create_item(board_id: $board_id, group_id: $group_id, item_name: $item_name,
            column_values: $column_values, create_labels_if_missing: true) { id name }
        }
        """
        return self._request(mutation, {
            "board_id": self.board_id,
            "group_id": self.resolved_group_id() or None,
            "item_name": lead.brand_name,
            "column_values": json.dumps(values),
        })
