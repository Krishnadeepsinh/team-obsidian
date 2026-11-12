import base64
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

from app.core.config import settings
from app.services.connectors.base import (
    BaseConnector,
    ConnectorError,
    compute_sha256,
    parse_iso_timestamp,
)

_NOTION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{2,64}$")


class NotionConnector(BaseConnector):
    """Notion connector supporting OAuth & Internal Integration tokens, recursive block extraction, and database queries."""

    provider_name = "notion"

    def __init__(self, token: Optional[str] = None):
        super().__init__(token=token)
        self.base_url = "https://api.notion.com/v1"
        self.headers = {
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    @classmethod
    def get_oauth_authorize_url(cls, state: str, redirect_uri: str) -> str:
        if not settings.NOTION_CLIENT_ID or not settings.NOTION_CLIENT_SECRET:
            raise ConnectorError(
                "Notion Public OAuth is not configured. Set NOTION_CLIENT_ID and NOTION_CLIENT_SECRET in backend .env."
            )
        params = urlencode({
            "client_id": settings.NOTION_CLIENT_ID,
            "response_type": "code",
            "owner": "user",
            "redirect_uri": redirect_uri,
            "state": state,
        })
        return f"https://api.notion.com/v1/oauth/authorize?{params}"

    @classmethod
    def exchange_oauth_code(cls, code: str, redirect_uri: str) -> Dict[str, Any]:
        if not settings.NOTION_CLIENT_ID or not settings.NOTION_CLIENT_SECRET:
            raise ConnectorError("Missing NOTION_CLIENT_ID or NOTION_CLIENT_SECRET.")
        basic_raw = f"{settings.NOTION_CLIENT_ID}:{settings.NOTION_CLIENT_SECRET}".encode("utf-8")
        basic_b64 = base64.b64encode(basic_raw).decode("utf-8")
        connector = cls()
        res = connector._request_with_retry(
            "POST",
            "https://api.notion.com/v1/oauth/token",
            headers={
                "Authorization": f"Basic {basic_b64}",
                "Content-Type": "application/json",
            },
            json_body={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        payload = res.json() if res.text else {}
        if res.status_code != 200 or not payload.get("access_token"):
            raise ConnectorError(f"Notion OAuth failed: {payload.get('error', res.status_code)}")
        return {
            "access_token": payload["access_token"],
            "token": payload["access_token"],
            "api_key": payload["access_token"],
            "workspace_name": payload.get("workspace_name"),
            "workspace_id": payload.get("workspace_id"),
            "bot_id": payload.get("bot_id"),
        }

    def check_connection(self) -> Dict[str, Any]:
        if not self.token:
            return {
                "status": "unconfigured",
                "auth_type": "none",
                "message": "Missing Notion Integration Secret or OAuth token.",
            }
        try:
            res = self._request_with_retry("GET", f"{self.base_url}/users/me", headers=self.headers, timeout=8)
            if res.status_code == 200:
                data = res.json()
                bot_info = data.get("bot") or {}
                ws_name = bot_info.get("workspace_name") or data.get("name") or "Notion Workspace"
                return {
                    "status": "connected",
                    "auth_type": "bearer_token",
                    "bot_name": data.get("name", "TEAM OBSIDIAN Bot"),
                    "connected_account": ws_name,
                    "scopes": ["read_content", "read_user"],
                }
            return {"status": "error", "message": f"Notion auth failed ({res.status_code}): {res.text[:200]}"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _extract_rich_text(self, rich_list: List[Dict[str, Any]]) -> str:
        return "".join(rt.get("plain_text", "") for rt in (rich_list or []))

    def _extract_page_title(self, item: Dict[str, Any]) -> str:
        if item.get("object") == "database" and item.get("title"):
            return self._extract_rich_text(item.get("title", [])) or "Untitled Database"
        props = item.get("properties") or {}
        for p in props.values():
            if p.get("type") == "title" and p.get("title"):
                return self._extract_rich_text(p["title"]) or "Untitled"
        return "Untitled"

    def _extract_block_text(self, block: Dict[str, Any], depth: int = 0) -> List[str]:
        lines: List[str] = []
        btype = block.get("type")
        bdata = block.get(btype) or {}
        indent = "  " * depth

        if btype in ("heading_1", "heading_2", "heading_3"):
            prefix = "#" * int(btype[-1])
            txt = self._extract_rich_text(bdata.get("rich_text", []))
            if txt:
                lines.append(f"\n{prefix} {txt}")
        elif btype == "paragraph":
            txt = self._extract_rich_text(bdata.get("rich_text", []))
            if txt:
                lines.append(f"{indent}{txt}")
        elif btype in ("bulleted_list_item", "numbered_list_item"):
            txt = self._extract_rich_text(bdata.get("rich_text", []))
            if txt:
                lines.append(f"{indent}- {txt}")
        elif btype == "to_do":
            txt = self._extract_rich_text(bdata.get("rich_text", []))
            checked = "x" if bdata.get("checked") else " "
            if txt:
                lines.append(f"{indent}- [{checked}] {txt}")
        elif btype == "code":
            txt = self._extract_rich_text(bdata.get("rich_text", []))
            lang = bdata.get("language", "")
            if txt:
                lines.append(f"```{lang}\n{txt}\n```")
        elif btype in ("quote", "callout", "toggle"):
            txt = self._extract_rich_text(bdata.get("rich_text", []))
            if txt:
                lines.append(f"{indent}> {txt}")
        elif btype == "table_row":
            cells = bdata.get("cells") or []
            row_vals = [self._extract_rich_text(cell) for cell in cells]
            if any(row_vals):
                lines.append(f"{indent}| " + " | ".join(row_vals) + " |")

        if block.get("has_children") and depth < 3:
            lines.extend(self._fetch_children_blocks(block.get("id", ""), depth=depth + 1))

        return lines

    def _fetch_children_blocks(self, block_id: str, depth: int = 0) -> List[str]:
        if not block_id:
            return []
        clean_block_id = self._validate_notion_id(block_id)
        lines: List[str] = []
        cursor: Optional[str] = None
        for _ in range(10):
            params: Dict[str, Any] = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            res = self._request_with_retry(
                "GET", f"{self.base_url}/blocks/{clean_block_id}/children", headers=self.headers, params=params
            )
            if res.status_code != 200:
                break
            data = res.json()
            for b in data.get("results", []):
                lines.extend(self._extract_block_text(b, depth=depth))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return lines

    def _fetch_database_rows(self, db_id: str) -> List[str]:
        clean_db_id = self._validate_notion_id(db_id)
        rows_text: List[str] = []
        cursor: Optional[str] = None
        for _ in range(5):
            body: Dict[str, Any] = {"page_size": 50}
            if cursor:
                body["start_cursor"] = cursor
            res = self._request_with_retry(
                "POST", f"{self.base_url}/databases/{clean_db_id}/query", headers=self.headers, json_body=body
            )
            if res.status_code != 200:
                break
            data = res.json()
            for row in data.get("results", []):
                props = row.get("properties") or {}
                parts = []
                for prop_name, prop_val in props.items():
                    ptype = prop_val.get("type")
                    val_str = ""
                    if ptype == "title":
                        val_str = self._extract_rich_text(prop_val.get("title", []))
                    elif ptype == "rich_text":
                        val_str = self._extract_rich_text(prop_val.get("rich_text", []))
                    elif ptype == "select" and prop_val.get("select"):
                        val_str = prop_val["select"].get("name", "")
                    elif ptype == "status" and prop_val.get("status"):
                        val_str = prop_val["status"].get("name", "")
                    elif ptype == "multi_select":
                        val_str = ", ".join(m.get("name", "") for m in prop_val.get("multi_select", []))
                    elif ptype == "date" and prop_val.get("date"):
                        val_str = prop_val["date"].get("start", "")
                    elif ptype == "number" and prop_val.get("number") is not None:
                        val_str = str(prop_val["number"])
                    if val_str:
                        parts.append(f"{prop_name}: {val_str}")
                if parts:
                    rows_text.append("- " + " | ".join(parts))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return rows_text

    @staticmethod
    def _validate_notion_id(raw_id: str) -> str:
        clean_id = (raw_id or "").strip()
        if not _NOTION_ID_RE.fullmatch(clean_id):
            raise ConnectorError("Invalid Notion page, database, or block ID format.")
        return clean_id

    @staticmethod
    def _normalize_notion_id(raw_id: str) -> str:
        return (raw_id or "").strip().replace("-", "").lower()

    def list_accessible_resources(self, max_pages: int = 2) -> List[Dict[str, Any]]:
        """List Notion pages and databases accessible to this token."""
        if not self.token:
            return []
        resources: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        for _ in range(max_pages):
            body: Dict[str, Any] = {
                "page_size": 50,
                "sort": {"direction": "descending", "timestamp": "last_edited_time"},
            }
            if cursor:
                body["start_cursor"] = cursor
            res = self._request_with_retry("POST", f"{self.base_url}/search", headers=self.headers, json_body=body)
            if res.status_code != 200:
                raise ConnectorError(f"Notion failed to list accessible resources ({res.status_code}): {res.text[:200]}")
            data = res.json()
            for item in data.get("results", []):
                resources.append({
                    "id": item.get("id", ""),
                    "object": item.get("object", "page"),
                    "title": self._extract_page_title(item),
                    "url": item.get("url"),
                    "last_edited_time": item.get("last_edited_time"),
                })
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return resources

    def _build_record_from_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        obj_type = item.get("object", "page")
        item_id = item.get("id", "")
        title = self._extract_page_title(item)
        author_id = (item.get("last_edited_by") or {}).get("id") or "Notion Author"
        edited_dt = parse_iso_timestamp(item.get("last_edited_time"))

        if obj_type == "database":
            rows = self._fetch_database_rows(item_id)
            body_text = "\n".join(rows) if rows else "Database schema synchronized (0 rows)."
            source_type = "notion_database"
        else:
            blocks = self._fetch_children_blocks(item_id)
            body_text = "\n".join(blocks).strip() or f"Notion Page: {title}"
            source_type = "notion_page"

        content = f"Notion {obj_type.title()}: {title}\nURL: {item.get('url')}\nLast Edited: {item.get('last_edited_time')}\n\n{body_text}"
        return {
            "source_type": source_type,
            "external_id": item_id,
            "title": f"Notion: {title}",
            "author": author_id,
            "url": item.get("url"),
            "content": content,
            "sha256": compute_sha256(content),
            "source_timestamp": edited_dt or parse_iso_timestamp(item.get("created_time")),
            "metadata": {"object": obj_type, "notion_id": item_id},
            "raw_payload": item,
        }

    def _fetch_target_item(self, target_id: str) -> Optional[Dict[str, Any]]:
        clean_id = (target_id or "").strip()
        if not clean_id:
            return None
        clean_id = self._validate_notion_id(clean_id)
        for endpoint in (f"{self.base_url}/databases/{clean_id}", f"{self.base_url}/pages/{clean_id}"):
            res = self._request_with_retry("GET", endpoint, headers=self.headers)
            if res.status_code == 200:
                return res.json()
        return None

    def sync_pages(
        self,
        since_iso: Optional[str] = None,
        max_pages: int = 10,
        target_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch authorized Notion pages & databases with full recursive block content."""
        if not self.token:
            raise ConnectorError("Missing Notion token.")

        validated_targets: List[str] = []
        for raw_target in (target_ids or []):
            stripped = str(raw_target).strip()
            if stripped:
                validated_targets.append(self._validate_notion_id(stripped))

        normalized_targets = {self._normalize_notion_id(t) for t in validated_targets}
        records: List[Dict[str, Any]] = []
        seen_normalized: set[str] = set()
        since_dt = parse_iso_timestamp(since_iso)
        cursor: Optional[str] = None

        for _ in range(max_pages):
            body: Dict[str, Any] = {
                "page_size": 50,
                "sort": {"direction": "descending", "timestamp": "last_edited_time"},
            }
            if cursor:
                body["start_cursor"] = cursor

            res = self._request_with_retry("POST", f"{self.base_url}/search", headers=self.headers, json_body=body)
            if res.status_code != 200:
                raise ConnectorError(f"Notion search failed ({res.status_code}): {res.text[:200]}")

            data = res.json()
            for item in data.get("results", []):
                item_norm = self._normalize_notion_id(item.get("id", ""))
                if normalized_targets and item_norm not in normalized_targets:
                    continue

                edited_dt = parse_iso_timestamp(item.get("last_edited_time"))
                if since_dt and edited_dt and edited_dt <= since_dt:
                    return records

                records.append(self._build_record_from_item(item))
                seen_normalized.add(item_norm)

            if normalized_targets and normalized_targets.issubset(seen_normalized):
                break
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

        if normalized_targets:
            for raw_target in target_ids or []:
                norm = self._normalize_notion_id(raw_target)
                if norm and norm not in seen_normalized:
                    item = self._fetch_target_item(raw_target)
                    if item:
                        edited_dt = parse_iso_timestamp(item.get("last_edited_time"))
                        if not (since_dt and edited_dt and edited_dt <= since_dt):
                            records.append(self._build_record_from_item(item))
                        seen_normalized.add(norm)

        return records

    def sync(
        self,
        config: Optional[Dict[str, Any]] = None,
        sync_cursor: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        cfg = config or {}
        cursor = dict(sync_cursor or {})
        since_iso = cursor.get("last_edited_time")

        target_ids: List[str] = []
        raw_targets = cfg.get("targets")
        if isinstance(raw_targets, list) and raw_targets:
            target_ids = [str(t).strip() for t in raw_targets if str(t).strip()]
        else:
            raw_single = str(cfg.get("database_id") or cfg.get("page_id") or cfg.get("target") or "").strip()
            if raw_single:
                target_ids = [t.strip() for t in raw_single.split(",") if t.strip()]

        records = self.sync_pages(since_iso=since_iso, target_ids=target_ids or None)
        cursor["last_edited_time"] = datetime.now(timezone.utc).isoformat()
        return records, cursor


notion_connector = NotionConnector()
