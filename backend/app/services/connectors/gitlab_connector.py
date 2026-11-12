from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlencode

from app.core.config import settings
from app.services.connectors._atlassian import validate_external_https_url
from app.services.connectors.base import (
    BaseConnector,
    ConnectorError,
    compute_sha256,
    parse_iso_timestamp,
)


class GitLabConnector(BaseConnector):
    """GitLab REST API v4 connector supporting OAuth 2.0, PATs, Merge Requests, Issues, Commits, and AST analysis."""

    provider_name = "gitlab"

    def __init__(self, token: Optional[str] = None, site_url: Optional[str] = None):
        super().__init__(token=token)
        self.gitlab_origin = (
            validate_external_https_url(site_url, "GitLab Base URL")
            if site_url
            else "https://gitlab.com"
        )
        self.base_url = f"{self.gitlab_origin}/api/v4"
        self.headers = {"Accept": "application/json", "User-Agent": "Team-Obsidian-Platform/2.0"}
        if token:
            cleaned = token.strip()
            if cleaned.startswith("glpat-"):
                self.headers["PRIVATE-TOKEN"] = cleaned
            else:
                self.headers["Authorization"] = f"Bearer {cleaned}"

    @classmethod
    def get_oauth_authorize_url(cls, state: str, redirect_uri: str) -> str:
        if not settings.GITLAB_CLIENT_ID or not settings.GITLAB_CLIENT_SECRET:
            raise ConnectorError("GitLab OAuth is not configured. Set GITLAB_CLIENT_ID and GITLAB_CLIENT_SECRET in backend .env.")
        params = urlencode({
            "client_id": settings.GITLAB_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "read_api read_user read_repository",
            "state": state,
        })
        return f"https://gitlab.com/oauth/authorize?{params}"

    @classmethod
    def exchange_oauth_code(cls, code: str, redirect_uri: str) -> Dict[str, Any]:
        if not settings.GITLAB_CLIENT_ID or not settings.GITLAB_CLIENT_SECRET:
            raise ConnectorError("Missing GITLAB_CLIENT_ID or GITLAB_CLIENT_SECRET.")
        connector = cls()
        res = connector._request_with_retry(
            "POST",
            "https://gitlab.com/oauth/token",
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.GITLAB_CLIENT_ID,
                "client_secret": settings.GITLAB_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            timeout=12,
        )
        payload = res.json() if res.text else {}
        if res.status_code != 200 or not payload.get("access_token"):
            raise ConnectorError(
                f"GitLab OAuth exchange failed: {payload.get('error_description') or payload.get('error') or res.status_code}"
            )
        return {
            "access_token": payload["access_token"],
            "token": payload["access_token"],
            "scope": payload.get("scope", ""),
            "token_type": payload.get("token_type", "Bearer"),
            **({"refresh_token": payload["refresh_token"]} if payload.get("refresh_token") else {}),
            **({"expires_in": payload["expires_in"]} if payload.get("expires_in") else {}),
        }

    @classmethod
    def refresh_oauth_token(cls, refresh_token: str) -> Dict[str, Any]:
        if not settings.GITLAB_CLIENT_ID or not settings.GITLAB_CLIENT_SECRET:
            raise ConnectorError("Missing GITLAB_CLIENT_ID or GITLAB_CLIENT_SECRET.")
        connector = cls()
        res = connector._request_with_retry(
            "POST",
            "https://gitlab.com/oauth/token",
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.GITLAB_CLIENT_ID,
                "client_secret": settings.GITLAB_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=12,
        )
        payload = res.json() if res.text else {}
        if res.status_code != 200 or not payload.get("access_token"):
            raise ConnectorError(
                f"GitLab token refresh failed: {payload.get('error_description') or payload.get('error') or res.status_code}"
            )
        return {
            "access_token": payload["access_token"],
            "token": payload["access_token"],
            "scope": payload.get("scope", ""),
            "token_type": payload.get("token_type", "Bearer"),
            "refresh_token": payload.get("refresh_token") or refresh_token,
            **({"expires_in": payload["expires_in"]} if payload.get("expires_in") else {}),
        }

    def check_connection(self) -> Dict[str, Any]:
        if not self.token:
            return {"status": "unconfigured", "auth_type": "none", "message": "Missing GitLab OAuth token or PAT."}
        try:
            res = self._request_with_retry("GET", f"{self.base_url}/user", headers=self.headers, timeout=8)
            if res.status_code == 200:
                data = res.json()
                return {
                    "status": "connected",
                    "auth_type": "pat" if self.token.startswith("glpat-") else "oauth_token",
                    "connected_account": data.get("username") or data.get("email") or data.get("name"),
                    "name": data.get("name"),
                    "scopes": ["read_api", "read_user", "read_repository"],
                }
            return {"status": "error", "message": f"GitLab auth failed ({res.status_code}): {res.text[:200]}"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def list_projects(self, max_pages: int = 2) -> List[Dict[str, Any]]:
        if not self.token:
            return []
        projects: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            res = self._request_with_retry(
                "GET",
                f"{self.base_url}/projects",
                headers=self.headers,
                params={"membership": "true", "simple": "true", "order_by": "last_activity_at", "per_page": 50, "page": page},
                timeout=10,
            )
            if res.status_code != 200:
                if page == 1 and res.status_code in (401, 403):
                    raise ConnectorError(f"GitLab rejected credentials ({res.status_code}): {res.text[:200]}")
                break
            batch = res.json() or []
            if not batch:
                break
            for p in batch:
                slug = p.get("path_with_namespace")
                if slug and slug not in seen:
                    seen.add(slug)
                    projects.append({
                        "id": str(p.get("id")),
                        "path_with_namespace": slug,
                        "default_branch": p.get("default_branch") or "main",
                        "visibility": p.get("visibility") or "private",
                        "web_url": p.get("web_url"),
                    })
            if len(batch) < 50:
                break
        return projects

    def sync(
        self,
        config: Optional[Dict[str, Any]] = None,
        sync_cursor: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if not self.token:
            raise ConnectorError("Missing GitLab token.")
        cfg = config or {}
        cursor = dict(sync_cursor or {})

        repos: List[str] = []
        raw_repos = cfg.get("repos") or cfg.get("repositories") or cfg.get("projects")
        if isinstance(raw_repos, list):
            repos.extend(str(r).strip() for r in raw_repos if str(r).strip())
        single = cfg.get("repo") or cfg.get("target")
        if isinstance(single, str) and single.strip():
            for part in single.split(","):
                if part.strip() and part.strip() not in repos:
                    repos.append(part.strip())

        if not repos:
            discovered = self.list_projects(max_pages=1)
            repos = [d["path_with_namespace"] for d in discovered[:4]]
        if not repos:
            raise ConnectorError("No accessible GitLab projects found. Select at least one GitLab repository.")

        records: List[Dict[str, Any]] = []
        proj_cursors: Dict[str, Any] = dict(cursor.get("projects") or {})

        for repo_path in repos[:8]:
            enc = quote(repo_path, safe="")
            p_cur = dict(proj_cursors.get(repo_path) or {})
            since_iso = p_cur.get("last_sync_at")

            # 1. Project metadata + AST Code Graph
            proj_res = self._request_with_retry("GET", f"{self.base_url}/projects/{enc}", headers=self.headers)
            branch = "main"
            if proj_res.status_code == 200:
                pinfo = proj_res.json()
                if isinstance(pinfo, dict):
                    branch = pinfo.get("default_branch") or "main"
                    overview = (
                        f"GitLab Repository: {repo_path}\n"
                        f"Default Branch: {branch} | Visibility: {pinfo.get('visibility')}\n"
                        f"Description: {pinfo.get('description') or 'N/A'}"
                    )
                    records.append({
                        "source_type": "gitlab_repository",
                        "external_id": f"gitlab#{repo_path}#overview",
                        "title": f"GitLab Repo: {repo_path}",
                        "author": repo_path.split("/")[0],
                        "url": pinfo.get("web_url"),
                        "content": overview,
                        "sha256": compute_sha256(overview),
                        "source_timestamp": parse_iso_timestamp(pinfo.get("last_activity_at")) or datetime.now(timezone.utc),
                        "metadata": {"repository": repo_path, "default_branch": branch},
                        "raw_payload": {"id": pinfo.get("id"), "path_with_namespace": repo_path},
                    })
                    try:
                        from app.services.code_ast_indexer import fetch_and_index_gitlab_ast

                        ast_summary = fetch_and_index_gitlab_ast(self, repo_path, default_branch=branch)
                        for ast_rec in ast_summary.get("records") or []:
                            ast_meta = dict(ast_rec.get("metadata") or {})
                            ast_meta["ast_facts"] = ast_summary
                            ast_rec["metadata"] = ast_meta
                            records.append(ast_rec)
                    except Exception:
                        pass

            # 2. Merge Requests (multi-page via x-next-page)
            newest_proj_ts = since_iso or ""
            for page_no in range(1, 5):
                mr_params: Dict[str, Any] = {
                    "state": "all",
                    "order_by": "updated_at",
                    "sort": "desc",
                    "per_page": 25,
                    "page": page_no,
                }
                if since_iso:
                    mr_params["updated_after"] = since_iso
                mr_res = self._request_with_retry(
                    "GET", f"{self.base_url}/projects/{enc}/merge_requests", headers=self.headers, params=mr_params
                )
                if mr_res.status_code != 200:
                    break
                mr_items = mr_res.json() or []
                for mr in mr_items:
                    iid = mr.get("iid")
                    author = (mr.get("author") or {}).get("username") or "gitlab-user"
                    upd = mr.get("updated_at") or ""
                    if upd and upd > newest_proj_ts:
                        newest_proj_ts = upd
                    content = (
                        f"GitLab MR !{iid}: {mr.get('title')}\n"
                        f"Repository: {repo_path} | State: {mr.get('state')} | Author: {author}\n"
                        f"Source -> Target: {mr.get('source_branch')} -> {mr.get('target_branch')}\n\n"
                        f"{mr.get('description') or ''}"
                    ).strip()
                    records.append({
                        "source_type": "gitlab_mr",
                        "external_id": f"gitlab#{repo_path}#mr-{iid}",
                        "title": f"MR !{iid}: {mr.get('title')}",
                        "author": author,
                        "url": mr.get("web_url"),
                        "content": content,
                        "sha256": compute_sha256(content),
                        "source_timestamp": parse_iso_timestamp(upd) or datetime.now(timezone.utc),
                        "metadata": {"repository": repo_path, "mr_iid": iid, "state": mr.get("state")},
                        "raw_payload": {"iid": iid, "updated_at": upd},
                    })
                next_pg = (mr_res.headers.get("x-next-page") or "").strip()
                if not next_pg or not mr_items:
                    break

            # 3. Issues (multi-page via x-next-page)
            for page_no in range(1, 5):
                iss_params: Dict[str, Any] = {
                    "state": "all",
                    "order_by": "updated_at",
                    "sort": "desc",
                    "per_page": 25,
                    "page": page_no,
                }
                if since_iso:
                    iss_params["updated_after"] = since_iso
                iss_res = self._request_with_retry(
                    "GET", f"{self.base_url}/projects/{enc}/issues", headers=self.headers, params=iss_params
                )
                if iss_res.status_code != 200:
                    break
                iss_items = iss_res.json() or []
                for iss in iss_items:
                    iid = iss.get("iid")
                    author = (iss.get("author") or {}).get("username") or "gitlab-user"
                    labels = ", ".join(iss.get("labels") or [])
                    upd = iss.get("updated_at") or ""
                    if upd and upd > newest_proj_ts:
                        newest_proj_ts = upd
                    content = (
                        f"GitLab Issue #{iid}: {iss.get('title')}\n"
                        f"Repository: {repo_path} | State: {iss.get('state')} | Labels: {labels or 'none'}\n\n"
                        f"{iss.get('description') or ''}"
                    ).strip()
                    records.append({
                        "source_type": "gitlab_issue",
                        "external_id": f"gitlab#{repo_path}#issue-{iid}",
                        "title": f"Issue #{iid}: {iss.get('title')}",
                        "author": author,
                        "url": iss.get("web_url"),
                        "content": content,
                        "sha256": compute_sha256(content),
                        "source_timestamp": parse_iso_timestamp(upd) or datetime.now(timezone.utc),
                        "metadata": {"repository": repo_path, "issue_iid": iid, "state": iss.get("state")},
                        "raw_payload": {"iid": iid, "updated_at": upd},
                    })
                next_pg = (iss_res.headers.get("x-next-page") or "").strip()
                if not next_pg or not iss_items:
                    break

            # 4. Commits (multi-page via x-next-page)
            for page_no in range(1, 5):
                cm_params: Dict[str, Any] = {"ref_name": branch, "per_page": 25, "page": page_no}
                if since_iso:
                    cm_params["since"] = since_iso
                cm_res = self._request_with_retry(
                    "GET", f"{self.base_url}/projects/{enc}/repository/commits", headers=self.headers, params=cm_params
                )
                if cm_res.status_code != 200:
                    break
                cm_items = cm_res.json() or []
                for c in cm_items:
                    sha = c.get("id") or c.get("short_id")
                    title = c.get("title") or "Commit"
                    msg = c.get("message") or title
                    author = c.get("author_name") or "committer"
                    cdate = c.get("committed_date") or ""
                    if cdate and cdate > newest_proj_ts:
                        newest_proj_ts = cdate
                    content = f"GitLab Commit {str(sha)[:10]} in {repo_path} ({branch}):\nAuthor: {author}\n\n{msg}"
                    records.append({
                        "source_type": "gitlab_commit",
                        "external_id": f"gitlab#{repo_path}#commit-{sha}",
                        "title": f"Commit {str(sha)[:8]}: {title[:120]}",
                        "author": author,
                        "url": c.get("web_url"),
                        "content": content,
                        "sha256": compute_sha256(content),
                        "source_timestamp": parse_iso_timestamp(cdate) or datetime.now(timezone.utc),
                        "metadata": {"repository": repo_path, "sha": sha, "branch": branch},
                        "raw_payload": {"id": sha, "title": title},
                    })
                next_pg = (cm_res.headers.get("x-next-page") or "").strip()
                if not next_pg or not cm_items:
                    break

            p_cur["last_sync_at"] = newest_proj_ts or datetime.now(timezone.utc).isoformat()
            proj_cursors[repo_path] = p_cur

        cursor["projects"] = proj_cursors
        return records, cursor


gitlab_connector = GitLabConnector()

