from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

from app.core.config import settings
from app.services.connectors._atlassian import validate_external_https_url
from app.services.connectors.base import (
    BaseConnector,
    ConnectorError,
    compute_sha256,
    parse_iso_timestamp,
)


class SentryConnector(BaseConnector):
    """Sentry REST API connector ingesting production error clusters, stacktraces, regressions, and ownership risks."""

    provider_name = "sentry"

    def __init__(
        self,
        token: Optional[str] = None,
        org_slug: Optional[str] = None,
        site_url: Optional[str] = None,
    ):
        super().__init__(token=token)
        self.sentry_origin = (
            validate_external_https_url(site_url, "Sentry Base URL")
            if site_url
            else "https://sentry.io"
        )
        self.base_url = f"{self.sentry_origin}/api/0"
        self.org_slug = (org_slug or settings.SENTRY_ORG_SLUG or "").strip() or None
        self.headers = {"Accept": "application/json", "User-Agent": "Team-Obsidian-Platform/2.0"}
        if token:
            self.headers["Authorization"] = f"Bearer {token.strip()}"

    @classmethod
    def get_oauth_authorize_url(cls, state: str, redirect_uri: str) -> str:
        if not settings.SENTRY_CLIENT_ID or not settings.SENTRY_CLIENT_SECRET:
            raise ConnectorError(
                "Sentry OAuth is not configured. Connect using a Sentry Auth Token (sntryu_...) or configure SENTRY_CLIENT_ID/SECRET."
            )
        params = urlencode({
            "client_id": settings.SENTRY_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "project:read event:read org:read",
            "state": state,
        })
        return f"https://sentry.io/oauth/authorize/?{params}"

    @classmethod
    def exchange_oauth_code(cls, code: str, redirect_uri: str) -> Dict[str, Any]:
        if not settings.SENTRY_CLIENT_ID or not settings.SENTRY_CLIENT_SECRET:
            raise ConnectorError("Missing SENTRY_CLIENT_ID or SENTRY_CLIENT_SECRET.")
        connector = cls()
        res = connector._request_with_retry(
            "POST",
            "https://sentry.io/oauth/token/",
            headers={"Accept": "application/json"},
            data={
                "grant_type": "authorization_code",
                "client_id": settings.SENTRY_CLIENT_ID,
                "client_secret": settings.SENTRY_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            timeout=12,
        )
        payload = res.json() if res.text else {}
        if res.status_code != 200 or not payload.get("access_token"):
            raise ConnectorError(
                f"Sentry OAuth exchange failed: {payload.get('error_description') or payload.get('error') or res.status_code}"
            )
        return {
            "access_token": payload["access_token"],
            "token": payload["access_token"],
            "scope": payload.get("scope", "project:read event:read org:read"),
            "token_type": "Bearer",
            **({"refresh_token": payload["refresh_token"]} if payload.get("refresh_token") else {}),
        }

    def _list_organizations(self) -> List[Dict[str, Any]]:
        res = self._request_with_retry("GET", f"{self.base_url}/organizations/", headers=self.headers, timeout=10)
        if res.status_code != 200:
            raise ConnectorError(f"Sentry organizations lookup failed ({res.status_code}): {res.text[:200]}")
        data = res.json()
        return data if isinstance(data, list) else []

    def check_connection(self) -> Dict[str, Any]:
        if not self.token:
            return {"status": "unconfigured", "auth_type": "none", "message": "Missing Sentry Auth Token (sntryu_...)."}
        try:
            orgs = self._list_organizations()
            org_slugs = [o.get("slug") for o in orgs if o.get("slug")]
            root_res = self._request_with_retry("GET", f"{self.base_url}/", headers=self.headers, timeout=8)
            user_email = None
            if root_res.status_code == 200:
                user_info = (root_res.json() or {}).get("user") or {}
                user_email = user_info.get("email") or user_info.get("name")
            acct = user_email or (org_slugs[0] if org_slugs else "Sentry Account")
            return {
                "status": "connected",
                "auth_type": "auth_token",
                "connected_account": acct,
                "organizations": org_slugs,
                "org_slug": self.org_slug or (org_slugs[0] if org_slugs else None),
                "scopes": ["org:read", "project:read", "event:read"],
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def list_projects(self) -> List[Dict[str, Any]]:
        if not self.token:
            return []
        orgs = [self.org_slug] if self.org_slug else [o.get("slug") for o in self._list_organizations() if o.get("slug")]
        projects: List[Dict[str, Any]] = []
        for org in orgs[:5]:
            res = self._request_with_retry(
                "GET", f"{self.base_url}/organizations/{org}/projects/", headers=self.headers, timeout=10
            )
            if res.status_code != 200:
                continue
            for p in res.json() or []:
                slug = p.get("slug")
                if not slug:
                    continue
                projects.append({
                    "id": str(p.get("id") or f"{org}/{slug}"),
                    "org_slug": org,
                    "slug": slug,
                    "full_slug": f"{org}/{slug}",
                    "name": p.get("name") or slug,
                    "platform": p.get("platform") or "app",
                })
        return projects

    def sync(
        self,
        config: Optional[Dict[str, Any]] = None,
        sync_cursor: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if not self.token:
            raise ConnectorError("Missing Sentry Auth Token.")
        cfg = config or {}
        cursor = dict(sync_cursor or {})

        targets: List[str] = []
        raw_projects = cfg.get("projects")
        if isinstance(raw_projects, list):
            targets.extend(str(p).strip() for p in raw_projects if str(p).strip())
        single = cfg.get("project") or cfg.get("target")
        if isinstance(single, str) and single.strip():
            for part in single.split(","):
                if part.strip() and part.strip() not in targets:
                    targets.append(part.strip())

        if not targets:
            discovered = self.list_projects()
            targets = [p["full_slug"] for p in discovered[:6]]
        if not targets:
            raise ConnectorError("No accessible Sentry projects found for this Auth Token.")

        default_org = self.org_slug
        if not default_org:
            orgs = self._list_organizations()
            default_org = orgs[0].get("slug") if orgs else None

        records: List[Dict[str, Any]] = []
        last_seen_map: Dict[str, str] = dict(cursor.get("last_seen_by_project") or {})

        for item in targets[:8]:
            if "/" in item:
                org_slug, proj_slug = item.split("/", 1)
            else:
                org_slug, proj_slug = (default_org or ""), item
            if not org_slug or not proj_slug:
                continue

            proj_key = f"{org_slug}/{proj_slug}"
            prev_seen = last_seen_map.get(proj_key) or ""
            newest_seen = prev_seen
            next_url: Optional[str] = f"{self.base_url}/projects/{org_slug}/{proj_slug}/issues/"
            next_params: Optional[Dict[str, Any]] = {"query": "is:unresolved", "statsPeriod": "14d", "limit": 25}

            for _ in range(4):
                if not next_url:
                    break
                res = self._request_with_retry("GET", next_url, headers=self.headers, params=next_params, timeout=12)
                if res.status_code != 200:
                    break

                page_issues = res.json() or []
                reached_watermark = False
                for iss in page_issues:
                    iss_id = str(iss.get("id") or "")
                    short_id = iss.get("shortId") or iss_id
                    title = iss.get("title") or f"Sentry Issue {short_id}"
                    culprit = iss.get("culprit") or "unknown"
                    level = iss.get("level") or "error"
                    count = iss.get("count") or 0
                    user_count = iss.get("userCount") or 0
                    assignee = ((iss.get("assignedTo") or {}).get("name")) or "Unassigned"
                    last_seen = iss.get("lastSeen") or iss.get("firstSeen") or ""
                    if prev_seen and last_seen and last_seen <= prev_seen:
                        reached_watermark = True
                        continue
                    if last_seen and last_seen > newest_seen:
                        newest_seen = last_seen

                    content = "\n".join([
                        f"Sentry Error [{short_id}] ({level.upper()} · {iss.get('status', 'unresolved')})",
                        f"Title: {title}",
                        f"Project: {org_slug}/{proj_slug} | Culprit: {culprit}",
                        f"Events: {count} | Users Impacted: {user_count} | Assignee: {assignee}",
                        f"Metadata: {iss.get('metadata') or {}}",
                    ])
                    records.append({
                        "source_type": "sentry_issue",
                        "external_id": f"sentry#{org_slug}/{proj_slug}#{iss_id}",
                        "title": f"[{short_id}] {title[:400]}",
                        "author": assignee if assignee != "Unassigned" else "Sentry Monitor",
                        "url": iss.get("permalink"),
                        "content": content,
                        "sha256": compute_sha256(content),
                        "source_timestamp": parse_iso_timestamp(last_seen) or datetime.now(timezone.utc),
                        "metadata": {
                            "org_slug": org_slug,
                            "project": proj_slug,
                            "short_id": short_id,
                            "level": level,
                            "culprit": culprit,
                            "event_count": count,
                            "user_count": user_count,
                        },
                        "raw_payload": {"id": iss_id, "shortId": short_id, "lastSeen": last_seen},
                    })

                if reached_watermark or not page_issues:
                    break
                next_url = None
                next_params = None
                link_hdr = res.headers.get("Link") or ""
                for part in link_hdr.split(","):
                    if 'rel="next"' in part and 'results="true"' in part and "<" in part and ">" in part:
                        next_url = part.split("<", 1)[1].split(">", 1)[0].strip()
                        break

            if newest_seen:
                last_seen_map[proj_key] = newest_seen

        cursor["last_seen_by_project"] = last_seen_map
        cursor["last_sync_at"] = datetime.now(timezone.utc).isoformat()
        return records, cursor


sentry_connector = SentryConnector()

