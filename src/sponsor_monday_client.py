from __future__ import annotations

import json
from dataclasses import dataclass

import requests

from sponsor_dedupe import ExistingSponsorIndex, email_domain, normalize_brand_name, normalize_domain, normalize_email
from sponsor_models import SponsorLead

MONDAY_API_URL = "https://api.monday.com/v2"

# Exact column IDs from the client Sponsership Leads board.
# The item name itself is the Brand, so there is no separate Brand column value to write.
BOARD_COLUMN_IDS = {
    "outreach_status": "color_mm5rvpv9",
    "email_status": "color_mm62kst6",
    "brand_domain": "link_mm62hm2e",
    "contact_email": "email_mm62m6r9",
    "source_platform": "dropdown_mm62y6v7",
    "creator_name": "text_mm621kk9",
    "creator_url": "link_mm6239bh",
    "creator_subscribers": "numeric_mm62np82",
    "video_url": "link_mm62nhcr",
    "sponsored_date": "date_mm626p50",
    "date_found": "date_mm62megm",
    "subitems": "subtasks_mm5reseg",
}

# Fields the sponsor scanner writes when it creates a brand.
# Email Status is intentionally excluded because it triggers the team's email automations.
# Subitems are intentionally excluded because monday automations create Creator 1 through Creator 6.
WRITABLE_FIELDS = {
    "outreach_status",
    "brand_domain",
    "contact_email",
    "source_platform",
    "creator_name",
    "creator_url",
    "creator_subscribers",
    "video_url",
    "sponsored_date",
    "date_found",
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
        self.session.headers.update(
            {
                "Authorization": token,
                "Content-Type": "application/json",
                "API-Version": api_version,
            }
        )
        self._columns: dict[str, ColumnInfo] | None = None
        self._groups: list[dict] | None = None

    def _request(self, query: str, variables: dict | None = None) -> dict:
        response = self.session.post(
            MONDAY_API_URL,
            json={"query": query, "variables": variables or {}},
            timeout=30,
        )
        try:
            data = response.json()
        except Exception as exc:
            raise RuntimeError(f"Invalid monday response: {response.text[:1000]}") from exc
        if response.status_code != 200 or data.get("errors"):
            raise RuntimeError(f"monday API error: {json.dumps(data, indent=2)[:3000]}")
        return data

    def load_schema(self) -> tuple[dict[str, ColumnInfo], list[dict]]:
        if self._columns is not None and self._groups is not None:
            return self._columns, self._groups

        query = """
        query SponsorBoardSchema($board_id: ID!) {
          boards(ids: [$board_id]) {
            name
            groups { id title }
            columns { id title type }
          }
        }
        """
        data = self._request(query, {"board_id": self.board_id})
        boards = data.get("data", {}).get("boards", [])
        if not boards:
            raise RuntimeError(f"Sponsor monday board {self.board_id} is not accessible.")

        board = boards[0]
        self._groups = board.get("groups", []) or []
        by_id = {
            column["id"]: ColumnInfo(column["id"], column.get("title", ""), column.get("type", ""))
            for column in board.get("columns", [])
        }

        resolved: dict[str, ColumnInfo] = {}
        missing: list[str] = []
        for field, column_id in BOARD_COLUMN_IDS.items():
            column = by_id.get(column_id)
            if column:
                resolved[field] = column
            else:
                missing.append(f"{field} ({column_id})")

        # Fail clearly if the board structure changes. This is safer than silently writing
        # sponsor data into a wrong column after someone edits the board.
        required = {field for field in WRITABLE_FIELDS} | {"email_status"}
        missing_required = [item for item in missing if item.split(" ", 1)[0] in required]
        if missing_required:
            raise RuntimeError(
                "Sponsership Leads board is missing expected columns: " + ", ".join(missing_required)
            )

        self._columns = resolved
        return resolved, self._groups

    def resolved_group_id(self) -> str:
        _, groups = self.load_schema()
        if self.requested_group_id:
            if any(group.get("id") == self.requested_group_id for group in groups):
                return self.requested_group_id
            raise RuntimeError(
                f"SPONSOR_MONDAY_GROUP_ID {self.requested_group_id!r} is not on this board."
            )

        for group in groups:
            if (group.get("title") or "").strip().lower() == "new leads":
                return group.get("id", "")
        return groups[0].get("id", "") if groups else ""

    def _get_all_items(self) -> list[dict]:
        first = """
        query SponsorItems($board_id: ID!) {
          boards(ids: [$board_id]) {
            items_page(limit: 500) {
              cursor
              items { id name column_values { id text value } }
            }
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
          next_items_page(limit: 500, cursor: $cursor) {
            cursor
            items { id name column_values { id text value } }
          }
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
        """Build the duplicate index from BRAND identity only.

        Creator, creator URL and sponsored video are deliberately ignored for brand
        duplication. One monday parent item represents one brand forever.
        """
        columns, _ = self.load_schema()
        domain_id = columns["brand_domain"].id
        email_id = columns["contact_email"].id

        index = ExistingSponsorIndex()
        item_count = 0
        for item in self._get_all_items():
            item_count += 1
            values_by_id = {
                column.get("id", ""): self._raw_value(column)
                for column in item.get("column_values", []) or []
            }

            keys: set[str] = set()

            # Primary duplicate key: normalized brand/item name.
            brand_name = normalize_brand_name(item.get("name", ""))
            if brand_name:
                keys.add(f"brand:{brand_name}")

            # Strongest duplicate key: canonical brand domain.
            domain = normalize_domain(values_by_id.get(domain_id, ""))
            if domain:
                keys.add(f"domain:{domain}")

            # Backup duplicate key: exact email and its domain.
            email = normalize_email(values_by_id.get(email_id, ""))
            if email:
                keys.add(f"email:{email}")
                e_domain = email_domain(email)
                if e_domain:
                    keys.add(f"domain:{e_domain}")

            # Every existing parent brand blocks another brand item, regardless of
            # creator or outreach status. We never want double outreach to a brand.
            index.brand_keys.update(keys)
            index.protected_brand_keys.update(keys)

        print(
            f"Daily monday brand duplicate scan: scanned {item_count} records and "
            f"loaded {len(index.brand_keys)} brand identity keys."
        )
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
            labels = {
                "brand_domain": lead.brand_domain or lead.brand_name,
                "creator_url": lead.creator_name,
                "video_url": "Sponsored Video",
            }
            return {"url": url, "text": labels.get(field, url)[:255]}
        if ctype == "date":
            return {"date": str(value)[:10]}
        if ctype == "status":
            return {"label": str(value)}
        if ctype == "dropdown":
            values = value if isinstance(value, list) else [value]
            return {"labels": [str(v)[:255] for v in values if str(v).strip()]}
        if ctype in {"numbers", "numeric"}:
            return str(value)
        return str(value)

    def create_lead(self, lead: SponsorLead) -> dict:
        columns, _ = self.load_schema()

        # Only populate the clean client-facing board fields.
        # Email Status is left blank so we do not accidentally trigger an email automation.
        raw = {
            "outreach_status": "New Lead",
            "brand_domain": lead.brand_domain,
            "contact_email": lead.contact_email,
            "source_platform": lead.source_platform,
            "creator_name": lead.creator_name,
            "creator_url": lead.creator_url,
            "creator_subscribers": lead.creator_subscribers,
            "video_url": lead.video_url,
            "sponsored_date": lead.sponsored_date,
            "date_found": lead.date_found,
        }

        values = {}
        for field in WRITABLE_FIELDS:
            column = columns[field]
            formatted = self._format_value(column, field, raw.get(field), lead)
            if formatted not in (None, "", {}):
                values[column.id] = formatted

        mutation = """
        mutation CreateSponsorLead(
          $board_id: ID!,
          $group_id: String,
          $item_name: String!,
          $column_values: JSON!
        ) {
          create_item(
            board_id: $board_id,
            group_id: $group_id,
            item_name: $item_name,
            column_values: $column_values,
            create_labels_if_missing: false
          ) { id name }
        }
        """
        return self._request(
            mutation,
            {
                "board_id": self.board_id,
                "group_id": self.resolved_group_id() or None,
                "item_name": lead.brand_name,
                "column_values": json.dumps(values),
            },
        )
