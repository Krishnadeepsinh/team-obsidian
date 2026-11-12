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
    flatten_adf,
    parse_atlassian_auth,
    pick_atlassian_resource,
)
from app.services.connectors.base import (
    BaseConnector,
    ConnectorError,
    compute_sha256,
    parse_iso_timestamp,
)


class JiraConnector(BaseConnector):
    """Jira Cloud connector supporting Atlassian OAuth 2.0 (3LO) and Email + API Token ingestion."""

    provider_name = "jira"

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
            settings.JIRA_CLIENT_ID or settings.ATLASSIAN_CLIENT_ID,
            settings.JIRA_CLIENT_SECRET or settings.ATLASSIAN_CLIENT_SECRET,
        )

    @classmethod
    def get_oauth_authorize_url(cls, state: str, redirect_uri: str) -> str:
        cid, csec = cls._client_creds()
        return atlassian_authorize_url(
            client_id=cid,
            client_secret=csec,
            scopes="read:jira-work read:jira-user read:me offline_access",
            state=state,
            redirect_uri=redirect_uri,
            provider_label="Jira",
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
            scope_keyword="jira",
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

    def _resolve_api_base(self) -> Tuple[str, Optional[str]]:
        if self.auth_mode == "basic":
            if not self.site_url:
                raise ConnectorError("Jira Site URL is required when using Email + API Token (e.g. https://team.atlassian.net).")
            return f"{self.site_url}/rest/api/3", self.site_url

        if not self.cloud_id:
            sites = fetch_accessible_resources(self, self.headers)
            site = pick_atlassian_resource(sites, "jira")
            if not site or not site.get("id"):
                raise ConnectorError("No accessible Jira Cloud sites found for this Atlassian OAuth token.")
            self.cloud_id = str(site["id"])
            if not self.site_url and site.get("url"):
                self.site_url = str(site["url"]).rstrip("/")
        return f"https://api.atlassian.com/ex/jira/{self.cloud_id}/rest/api/3", self.site_url

    def check_connection(self) -> Dict[str, Any]:
        if not self.token:
            return {
                "status": "unconfigured",
                "auth_type": "none",
                "message": "Missing Jira OAuth token or Atlassian Email + API Token.",
            }
        try:
            api_base, site_url = self._resolve_api_base()
            res = self._request_with_retry("GET", f"{api_base}/myself", headers=self.headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                acct = data.get("emailAddress") or data.get("displayName") or data.get("accountId")
                return {
                    "status": "connected",
                    "auth_type": self.auth_mode,
                    "connected_account": acct,
                    "site_url": site_url,
                    "cloud_id": self.cloud_id,
                    "scopes": ["read:jira-work", "read:jira-user"],
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
                        "scopes": ["read:jira-work", "read:jira-user"],
                    }
            return {"status": "error", "message": f"Jira auth failed ({res.status_code}): {res.text[:200]}"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def list_projects(self, max_results: int = 50) -> List[Dict[str, Any]]:
        if not self.token:
            return []
        api_base, site_url = self._resolve_api_base()
        res = self._request_with_retry(
            "GET",
            f"{api_base}/project/search",
            headers=self.headers,
            params={"maxResults": min(max_results, 100)},
            timeout=10,
        )
        if res.status_code != 200:
            raise ConnectorError(f"Jira could not list projects ({res.status_code}): {res.text[:200]}")
        values = (res.json() or {}).get("values") or []
        return [
            {
                "id": str(p.get("id") or p.get("key")),
                "key": p.get("key"),
                "name": p.get("name") or p.get("key"),
                "project_type": p.get("projectTypeKey") or "software",
                "url": f"{site_url}/browse/{p.get('key')}" if site_url and p.get("key") else None,
            }
            for p in values
            if p.get("key")
        ]

    def sync(
        self,
        config: Optional[Dict[str, Any]] = None,
        sync_cursor: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if not self.token:
            raise ConnectorError("Missing Jira credentials.")
        cfg = config or {}
        cursor = dict(sync_cursor or {})
        api_base, site_url = self._resolve_api_base()

        project_keys: List[str] = []
        raw_projects = cfg.get("projects")
        if isinstance(raw_projects, list):
            project_keys.extend(str(p).strip() for p in raw_projects if str(p).strip())
        single = cfg.get("project_key") or cfg.get("target")
        if isinstance(single, str) and single.strip():
            for part in single.split(","):
                if part.strip() and part.strip() not in project_keys:
                    project_keys.append(part.strip())

        jql_clauses: List[str] = []
        if project_keys:
            quoted = ", ".join(f'"{k}"' for k in project_keys[:20])
            jql_clauses.append(f"project in ({quoted})")
        last_updated = cursor.get("last_issue_updated")
        if isinstance(last_updated, str) and len(last_updated) >= 16:
            jql_time = last_updated[:16].replace("T", " ")
            jql_clauses.append(f'updated >= "{jql_time}"')
        jql = (" AND ".join(jql_clauses) + " " if jql_clauses else "") + "ORDER BY updated DESC"

        fields = [
            "summary",
            "status",
            "priority",
            "assignee",
            "reporter",
            "updated",
            "created",
            "description",
            "comment",
            "labels",
            "components",
            "issuetype",
            "project",
        ]
        issues: List[Dict[str, Any]] = []
        next_page_token: Optional[str] = None
        start_at = 0
        use_legacy_search = False

        for page_no in range(5):
            if not use_legacy_search:
                body: Dict[str, Any] = {"jql": jql, "maxResults": 50, "fields": fields}
                if next_page_token:
                    body["nextPageToken"] = next_page_token
                res = self._request_with_retry(
                    "POST",
                    f"{api_base}/search/jql",
                    headers=self.headers,
                    json_body=body,
                    timeout=15,
                )
                if page_no == 0 and res.status_code in (404, 405, 410):
                    use_legacy_search = True
                else:
                    if res.status_code != 200:
                        if issues:
                            break
                        raise ConnectorError(f"Jira issue search failed ({res.status_code}): {res.text[:220]}")
                    data = res.json() or {}
                    issues.extend(data.get("issues") or [])
                    next_page_token = data.get("nextPageToken")
                    if not next_page_token or data.get("isLast", True) is True:
                        break
                    continue

            res = self._request_with_retry(
                "GET",
                f"{api_base}/search",
                headers=self.headers,
                params={"jql": jql, "startAt": start_at, "maxResults": 50, "fields": ",".join(fields)},
                timeout=15,
            )
            if res.status_code != 200:
                if issues:
                    break
                raise ConnectorError(f"Jira issue search failed ({res.status_code}): {res.text[:220]}")
            data = res.json() or {}
            page_issues = data.get("issues") or []
            issues.extend(page_issues)
            start_at += len(page_issues)
            if not page_issues or start_at >= int(data.get("total") or 0):
                break

        records: List[Dict[str, Any]] = []
        newest_updated = last_updated or ""

        for issue in issues:
            key = issue.get("key") or str(issue.get("id"))
            f = issue.get("fields") or {}
            summary = f.get("summary") or f"Jira Issue {key}"
            proj_key = (f.get("project") or {}).get("key") or "JIRA"
            status_name = (f.get("status") or {}).get("name") or "Unknown"
            priority_name = (f.get("priority") or {}).get("name") or "Medium"
            issue_type = (f.get("issuetype") or {}).get("name") or "Task"
            assignee = ((f.get("assignee") or {}).get("displayName")) or "Unassigned"
            reporter = ((f.get("reporter") or {}).get("displayName")) or "Jira User"
            updated_at = f.get("updated") or f.get("created") or ""
            if updated_at and updated_at > newest_updated:
                newest_updated = updated_at

            desc_text = flatten_adf(f.get("description"))
            comments_raw = ((f.get("comment") or {}).get("comments")) or []
            comments_text = []
            for cm in comments_raw[-5:]:
                c_author = ((cm.get("author") or {}).get("displayName")) or "Reviewer"
                c_body = flatten_adf(cm.get("body"))
                if c_body:
                    comments_text.append(f"- {c_author}: {c_body[:500]}")

            labels = ", ".join(f.get("labels") or [])
            comps = ", ".join((c.get("name") or "") for c in (f.get("components") or []) if c.get("name"))
            issue_url = f"{site_url}/browse/{key}" if site_url else None
            content = "\n".join([
                f"Jira [{key}] ({issue_type} · {status_name} · Priority: {priority_name})",
                f"Title: {summary}",
                f"Project: {proj_key} | Assignee: {assignee} | Reporter: {reporter}",
                f"Components: {comps or 'none'} | Labels: {labels or 'none'}",
                f"\nDescription:\n{desc_text or '(No description provided)'}",
                ("\nRecent Discussion:\n" + "\n".join(comments_text)) if comments_text else "",
            ]).strip()

            records.append({
                "source_type": "jira_issue",
                "external_id": f"jira#{key}",
                "title": f"[{key}] {summary}",
                "author": assignee if assignee != "Unassigned" else reporter,
                "url": issue_url,
                "content": content,
                "sha256": compute_sha256(content),
                "source_timestamp": parse_iso_timestamp(updated_at) or datetime.now(timezone.utc),
                "metadata": {
                    "project_key": proj_key,
                    "issue_key": key,
                    "status": status_name,
                    "priority": priority_name,
                    "issue_type": issue_type,
                },
                "raw_payload": {"id": issue.get("id"), "key": key, "updated": updated_at},
            })

        if newest_updated:
            cursor["last_issue_updated"] = newest_updated
        return records, cursor


jira_connector = JiraConnector()

