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


class LinearConnector(BaseConnector):
    """Linear GraphQL connector supporting OAuth 2.0 and Personal API Keys (lin_api_...)."""

    provider_name = "linear"
    graphql_url = "https://api.linear.app/graphql"

    def __init__(self, token: Optional[str] = None):
        super().__init__(token=token)
        self.headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if token:
            cleaned = token.strip()
            # Linear Personal API keys must NOT use Bearer prefix, whereas OAuth tokens use Bearer.
            self.headers["Authorization"] = cleaned if cleaned.startswith("lin_api_") else f"Bearer {cleaned}"

    @classmethod
    def get_oauth_authorize_url(cls, state: str, redirect_uri: str) -> str:
        if not settings.LINEAR_CLIENT_ID or not settings.LINEAR_CLIENT_SECRET:
            raise ConnectorError("Linear OAuth is not configured. Set LINEAR_CLIENT_ID and LINEAR_CLIENT_SECRET in backend .env.")
        params = urlencode({
            "client_id": settings.LINEAR_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "read",
            "state": state,
            "prompt": "consent",
        })
        return f"https://linear.app/oauth/authorize?{params}"

    @classmethod
    def exchange_oauth_code(cls, code: str, redirect_uri: str) -> Dict[str, Any]:
        if not settings.LINEAR_CLIENT_ID or not settings.LINEAR_CLIENT_SECRET:
            raise ConnectorError("Missing LINEAR_CLIENT_ID or LINEAR_CLIENT_SECRET.")
        connector = cls()
        res = connector._request_with_retry(
            "POST",
            "https://api.linear.app/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "client_id": settings.LINEAR_CLIENT_ID,
                "client_secret": settings.LINEAR_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            timeout=12,
        )
        payload = res.json() if res.text else {}
        if res.status_code != 200 or not payload.get("access_token"):
            raise ConnectorError(
                f"Linear OAuth exchange failed: {payload.get('error_description') or payload.get('error') or res.status_code}"
            )
        return {
            "access_token": payload["access_token"],
            "token": payload["access_token"],
            "scope": payload.get("scope", "read"),
            "token_type": payload.get("token_type", "Bearer"),
            **({"expires_in": payload["expires_in"]} if payload.get("expires_in") else {}),
        }

    def _graphql(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        res = self._request_with_retry(
            "POST",
            self.graphql_url,
            headers=self.headers,
            json_body={"query": query, "variables": variables or {}},
            timeout=14,
        )
        if res.status_code != 200:
            raise ConnectorError(f"Linear GraphQL request failed ({res.status_code}): {res.text[:220]}")
        payload = res.json() or {}
        if payload.get("errors"):
            msg = "; ".join(str(e.get("message") or e) for e in payload["errors"])
            raise ConnectorError(f"Linear GraphQL error: {msg[:220]}")
        return payload.get("data") or {}

    def check_connection(self) -> Dict[str, Any]:
        if not self.token:
            return {"status": "unconfigured", "auth_type": "none", "message": "Missing Linear OAuth token or API key."}
        try:
            data = self._graphql("{ viewer { id name email } organization { id name urlKey } }")
            viewer = data.get("viewer") or {}
            org = data.get("organization") or {}
            acct = viewer.get("email") or viewer.get("name") or org.get("name")
            return {
                "status": "connected",
                "auth_type": "api_key" if self.token.startswith("lin_api_") else "oauth_token",
                "connected_account": acct,
                "organization": org.get("name"),
                "scopes": ["read"],
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def list_teams(self) -> List[Dict[str, Any]]:
        if not self.token:
            return []
        data = self._graphql("{ teams(first: 50) { nodes { id key name description } } }")
        nodes = (data.get("teams") or {}).get("nodes") or []
        return [
            {
                "id": t.get("id"),
                "key": t.get("key"),
                "name": t.get("name") or t.get("key"),
                "description": t.get("description") or "",
            }
            for t in nodes
            if t.get("id")
        ]

    def sync(
        self,
        config: Optional[Dict[str, Any]] = None,
        sync_cursor: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if not self.token:
            raise ConnectorError("Missing Linear token.")
        cfg = config or {}
        cursor = dict(sync_cursor or {})

        selected_teams: List[str] = []
        raw_teams = cfg.get("teams")
        if isinstance(raw_teams, list):
            selected_teams.extend(str(t).strip() for t in raw_teams if str(t).strip())
        single = cfg.get("team_key") or cfg.get("target")
        if isinstance(single, str) and single.strip():
            for part in single.split(","):
                if part.strip() and part.strip() not in selected_teams:
                    selected_teams.append(part.strip())

        issue_filter: Dict[str, Any] = {}
        if selected_teams:
            issue_filter["team"] = {"key": {"in": selected_teams}}
        last_updated = cursor.get("last_issue_updated")
        if last_updated:
            issue_filter["updatedAt"] = {"gte": last_updated}

        query = """
        query SyncLinear($filter: IssueFilter, $after: String, $includeProjects: Boolean!) {
          issues(first: 50, after: $after, orderBy: updatedAt, filter: $filter) {
            pageInfo {
              hasNextPage
              endCursor
            }
            nodes {
              id
              identifier
              title
              description
              priorityLabel
              url
              createdAt
              updatedAt
              state { name type }
              team { id key name }
              assignee { name email }
              creator { name }
              project { id name }
              labels { nodes { name } }
              comments(first: 5) { nodes { body user { name } } }
            }
          }
          projects(first: 20) @include(if: $includeProjects) {
            nodes {
              id
              name
              state
              description
              url
              updatedAt
              lead { name }
            }
          }
        }
        """
        issues: List[Dict[str, Any]] = []
        projects: List[Dict[str, Any]] = []
        after_cursor: Optional[str] = None
        for page_idx in range(5):
            data = self._graphql(
                query,
                {
                    "filter": issue_filter or None,
                    "after": after_cursor,
                    "includeProjects": page_idx == 0,
                },
            )
            issues_block = data.get("issues") or {}
            issues.extend(issues_block.get("nodes") or [])
            if page_idx == 0:
                projects = (data.get("projects") or {}).get("nodes") or []
            page_info = issues_block.get("pageInfo") or {}
            if not page_info.get("hasNextPage") or not page_info.get("endCursor"):
                break
            after_cursor = page_info.get("endCursor")

        records: List[Dict[str, Any]] = []
        newest_updated = last_updated or ""

        for iss in issues:
            ident = iss.get("identifier") or iss.get("id")
            title = iss.get("title") or f"Linear Issue {ident}"
            updated_at = iss.get("updatedAt") or iss.get("createdAt") or ""
            if updated_at and updated_at > newest_updated:
                newest_updated = updated_at
            team_info = iss.get("team") or {}
            state_info = iss.get("state") or {}
            assignee = (iss.get("assignee") or {}).get("name") or "Unassigned"
            creator = (iss.get("creator") or {}).get("name") or "Linear Member"
            proj_name = (iss.get("project") or {}).get("name") or "No Project"
            labels = ", ".join((l.get("name") or "") for l in ((iss.get("labels") or {}).get("nodes") or []) if l.get("name"))
            comments = [
                f"- {(c.get('user') or {}).get('name') or 'Member'}: {(c.get('body') or '')[:400]}"
                for c in ((iss.get("comments") or {}).get("nodes") or [])
                if c.get("body")
            ]
            content = "\n".join([
                f"Linear Issue [{ident}] ({state_info.get('name', 'Unknown')} · {iss.get('priorityLabel', 'Normal')})",
                f"Title: {title}",
                f"Team: {team_info.get('key', '')} ({team_info.get('name', '')}) | Project: {proj_name} | Assignee: {assignee}",
                f"Labels: {labels or 'none'}",
                f"\nDescription:\n{iss.get('description') or '(No description)'}",
                ("\nComments:\n" + "\n".join(comments)) if comments else "",
            ]).strip()

            records.append({
                "source_type": "linear_issue",
                "external_id": f"linear#{ident}",
                "title": f"[{ident}] {title}",
                "author": assignee if assignee != "Unassigned" else creator,
                "url": iss.get("url"),
                "content": content,
                "sha256": compute_sha256(content),
                "source_timestamp": parse_iso_timestamp(updated_at) or datetime.now(timezone.utc),
                "metadata": {
                    "team_key": team_info.get("key"),
                    "identifier": ident,
                    "state": state_info.get("name"),
                    "priority": iss.get("priorityLabel"),
                    "project": proj_name,
                },
                "raw_payload": {"id": iss.get("id"), "identifier": ident, "updatedAt": updated_at},
            })

        for proj in projects:
            pid = proj.get("id")
            if not pid:
                continue
            pname = proj.get("name") or pid
            lead = (proj.get("lead") or {}).get("name") or "Linear Lead"
            p_content = (
                f"Linear Project: {pname}\n"
                f"State: {proj.get('state', 'started')} | Lead: {lead}\n\n"
                f"{proj.get('description') or ''}"
            ).strip()
            records.append({
                "source_type": "linear_project",
                "external_id": f"linear#project-{pid}",
                "title": f"Linear Project: {pname}",
                "author": lead,
                "url": proj.get("url"),
                "content": p_content,
                "sha256": compute_sha256(p_content),
                "source_timestamp": parse_iso_timestamp(proj.get("updatedAt")) or datetime.now(timezone.utc),
                "metadata": {"project_id": pid, "state": proj.get("state")},
                "raw_payload": {"id": pid, "name": pname},
            })

        if newest_updated:
            cursor["last_issue_updated"] = newest_updated
        return records, cursor


linear_connector = LinearConnector()

