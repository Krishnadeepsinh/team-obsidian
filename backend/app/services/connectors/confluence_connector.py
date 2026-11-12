from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.services.connectors._atlassian import (
    ATLASSIAN_ME_URL,
    atlassian_authorize_url,
    atlassian_exchange_oauth_code,
    atlassian_refresh_oauth_token,
    build_atlassian_headers,
    fetch_accessible_resources,
    html_to_clean_text,
    parse_atlassian_auth,
    pick_atlassian_resource,
)
from app.services.connectors.base import (
    BaseConnector,
    ConnectorError,
    compute_sha256,
    parse_iso_timestamp,
)


class ConfluenceConnector(BaseConnector):
    """Confluence Cloud connector supporting Atlassian OAuth 2.0 (3LO) and Email + API Token ingestion."""

    provider_name = "confluence"

    def __init__(
        self,
        token: Optional[str] = None,
        email: Optional[str] = None,
        site_url: Optional[str] = None,
        cloud_id: Optional[str] = None,
    ):
        parsed = parse_atlassian_auth(token=token, email=email, site_url=site_url, cloud_id=cloud_id)
        super().__init__(token=parsed["token"])
        self.email = parsed["email"]
        self.site_url = parsed["site_url"]
        self.cloud_id = parsed["cloud_id"]
        self.headers, self.auth_mode = build_atlassian_headers(parsed)

    @classmethod
    def _client_creds(cls) -> Tuple[str, str]:
        return (
            settings.CONFLUENCE_CLIENT_ID or settings.ATLASSIAN_CLIENT_ID,
            settings.CONFLUENCE_CLIENT_SECRET or settings.ATLASSIAN_CLIENT_SECRET,
        )

    @classmethod
    def get_oauth_authorize_url(cls, state: str, redirect_uri: str) -> str:
        cid, csec = cls._client_creds()
        return atlassian_authorize_url(
            client_id=cid,
            client_secret=csec,
            scopes="read:confluence-content.all read:confluence-space.summary read:me offline_access",
            state=state,
            redirect_uri=redirect_uri,
            provider_label="Confluence",
        )

    @classmethod
    def exchange_oauth_code(cls, code: str, redirect_uri: str) -> Dict[str, Any]:
        cid, csec = cls._client_creds()
        return atlassian_exchange_oauth_code(
            connector=cls(),
            client_id=cid,
            client_secret=csec,
            code=code,
            redirect_uri=redirect_uri,
            scope_keyword="confluence",
        )

    @classmethod
    def refresh_oauth_token(cls, refresh_token: str) -> Dict[str, Any]:
        cid, csec = cls._client_creds()
        return atlassian_refresh_oauth_token(
            connector=cls(),
            client_id=cid,
            client_secret=csec,
            refresh_token=refresh_token,
        )

    def _resolve_wiki_base(self) -> Tuple[str, Optional[str]]:
        if self.auth_mode == "basic":
            if not self.site_url:
                raise ConnectorError(
                    "Confluence Site URL is required when using Email + API Token (e.g. https://team.atlassian.net)."
                )
            return f"{self.site_url}/wiki", self.site_url

        if not self.cloud_id:
            sites = fetch_accessible_resources(self, self.headers)
            site = pick_atlassian_resource(sites, "confluence")
            if not site or not site.get("id"):
                raise ConnectorError("No accessible Confluence Cloud sites found for this Atlassian OAuth token.")
            self.cloud_id = str(site["id"])
            if not self.site_url and site.get("url"):
                self.site_url = str(site["url"]).rstrip("/")
        return f"https://api.atlassian.com/ex/confluence/{self.cloud_id}/wiki", self.site_url

    def check_connection(self) -> Dict[str, Any]:
        if not self.token:
            return {
                "status": "unconfigured",
                "auth_type": "none",
                "message": "Missing Confluence OAuth token or Atlassian Email + API Token.",
            }
        try:
            wiki_base, site_url = self._resolve_wiki_base()
            res = self._request_with_retry("GET", f"{wiki_base}/rest/api/user/current", headers=self.headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                acct = data.get("email") or data.get("displayName") or data.get("accountId")
                return {
                    "status": "connected",
                    "auth_type": self.auth_mode,
                    "connected_account": acct,
                    "site_url": site_url,
                    "cloud_id": self.cloud_id,
                    "scopes": ["read:confluence-content.all", "read:confluence-space.summary"],
                }
            if self.auth_mode == "oauth":
                me_res = self._request_with_retry("GET", ATLASSIAN_ME_URL, headers=self.headers, timeout=8)
                if me_res.status_code == 200:
                    me = me_res.json()
                    return {
                        "status": "connected",
                        "auth_type": "oauth",
                        "connected_account": me.get("email") or me.get("name"),
                        "site_url": site_url,
                        "cloud_id": self.cloud_id,
                        "scopes": ["read:confluence-content.all", "read:confluence-space.summary"],
                    }
            return {"status": "error", "message": f"Confluence auth failed ({res.status_code}): {res.text[:200]}"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def list_spaces(self, limit: int = 50) -> List[Dict[str, Any]]:
        if not self.token:
            return []
        wiki_base, site_url = self._resolve_wiki_base()
        res = self._request_with_retry(
            "GET",
            f"{wiki_base}/api/v2/spaces",
            headers=self.headers,
            params={"limit": min(limit, 100)},
            timeout=10,
        )
        items: List[Dict[str, Any]] = []
        if res.status_code == 200:
            items = (res.json() or {}).get("results") or []
        else:
            v1 = self._request_with_retry(
                "GET",
                f"{wiki_base}/rest/api/space",
                headers=self.headers,
                params={"limit": min(limit, 100)},
                timeout=10,
            )
            if v1.status_code != 200:
                raise ConnectorError(f"Confluence could not list spaces ({v1.status_code}): {v1.text[:200]}")
            items = (v1.json() or {}).get("results") or []

        return [
            {
                "id": str(sp.get("id") or sp.get("key")),
                "key": sp.get("key") or str(sp.get("id")),
                "name": sp.get("name") or sp.get("key"),
                "type": sp.get("type") or "global",
                "url": f"{site_url}/wiki/spaces/{sp.get('key')}" if site_url and sp.get("key") else None,
            }
            for sp in items
            if sp.get("id") or sp.get("key")
        ]

    def sync(
        self,
        config: Optional[Dict[str, Any]] = None,
        sync_cursor: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if not self.token:
            raise ConnectorError("Missing Confluence credentials.")
        cfg = config or {}
        cursor = dict(sync_cursor or {})
        wiki_base, site_url = self._resolve_wiki_base()

        selected_spaces: List[str] = []
        raw_spaces = cfg.get("spaces")
        if isinstance(raw_spaces, list):
            selected_spaces.extend(str(s).strip() for s in raw_spaces if str(s).strip())
        single = cfg.get("space_id") or cfg.get("target")
        if isinstance(single, str) and single.strip():
            for part in single.split(","):
                if part.strip() and part.strip() not in selected_spaces:
                    selected_spaces.append(part.strip())

        params: Dict[str, Any] = {
            "body-format": "storage",
            "sort": "-modified-date",
            "limit": 30,
        }
        if selected_spaces:
            params["space-id"] = ",".join(s for s in selected_spaces if s.isdigit()) or None
            if params["space-id"] is None:
                params.pop("space-id")

        last_modified = cursor.get("last_page_updated") or ""
        newest_modified = last_modified
        records: List[Dict[str, Any]] = []
        next_url: Optional[str] = f"{wiki_base}/api/v2/pages"
        next_params: Optional[Dict[str, Any]] = params

        for _ in range(5):
            if not next_url:
                break
            res = self._request_with_retry("GET", next_url, headers=self.headers, params=next_params, timeout=15)
            if res.status_code != 200:
                if records:
                    break
                raise ConnectorError(f"Confluence page fetch failed ({res.status_code}): {res.text[:220]}")

            payload = res.json() or {}
            pages = payload.get("results") or []
            reached_watermark = False
            for page in pages:
                page_id = str(page.get("id") or "")
                if not page_id:
                    continue
                version_info = page.get("version") or {}
                modified_at = version_info.get("createdAt") or page.get("createdAt") or ""
                if last_modified and modified_at and modified_at <= last_modified:
                    reached_watermark = True
                    continue
                if modified_at and modified_at > newest_modified:
                    newest_modified = modified_at

                title = page.get("title") or f"Confluence Page {page_id}"
                space_id = str(page.get("spaceId") or "")
                storage_val = ((page.get("body") or {}).get("storage") or {}).get("value") or ""
                clean_body = html_to_clean_text(storage_val)
                web_link = ((page.get("_links") or {}).get("webui")) or ""
                full_url = f"{site_url}/wiki{web_link}" if site_url and web_link else None
                author = version_info.get("authorId") or "Confluence Author"
                content = (
                    f"Confluence Document: {title}\n"
                    f"Space ID: {space_id} | Version: {version_info.get('number', 1)}\n\n"
                    f"{clean_body or '(Empty Confluence page)'}"
                )
                records.append({
                    "source_type": "confluence_page",
                    "external_id": f"confluence#{page_id}",
                    "title": title[:500],
                    "author": str(author),
                    "url": full_url,
                    "content": content,
                    "sha256": compute_sha256(content),
                    "source_timestamp": parse_iso_timestamp(modified_at) or datetime.now(timezone.utc),
                    "metadata": {
                        "page_id": page_id,
                        "space_id": space_id,
                        "version": version_info.get("number", 1),
                    },
                    "raw_payload": {"id": page_id, "spaceId": space_id, "updated": modified_at},
                })

            if reached_watermark:
                break
            rel_next = ((payload.get("_links") or {}).get("next") or "").strip()
            if not rel_next:
                break
            if rel_next.startswith("http"):
                next_url = rel_next
            elif rel_next.startswith("/wiki"):
                origin = wiki_base.split("/wiki")[0]
                next_url = f"{origin}{rel_next}"
            else:
                next_url = f"{wiki_base}{rel_next}"
            next_params = None

        if newest_modified:
            cursor["last_page_updated"] = newest_modified
        return records, cursor


confluence_connector = ConfluenceConnector()

