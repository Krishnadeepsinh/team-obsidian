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


class GitHubConnector(BaseConnector):
    """GitHub connector supporting OAuth + PAT verification, pagination, incremental sync, PR reviews, commits, and issues."""

    provider_name = "github"

    def __init__(self, token: Optional[str] = None):
        super().__init__(token=token)
        self.base_url = "https://api.github.com"
        self.headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "Team-Obsidian-Platform/2.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    @classmethod
    def get_oauth_authorize_url(cls, state: str, redirect_uri: str) -> str:
        if not settings.GITHUB_CLIENT_ID or not settings.GITHUB_CLIENT_SECRET:
            raise ConnectorError(
                "GitHub OAuth App is not configured. Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET in backend .env."
            )
        params = urlencode({
            "client_id": settings.GITHUB_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": "repo read:user read:org",
            "state": state,
        })
        return f"https://github.com/login/oauth/authorize?{params}"

    @classmethod
    def exchange_oauth_code(cls, code: str, redirect_uri: str) -> Dict[str, Any]:
        if not settings.GITHUB_CLIENT_ID or not settings.GITHUB_CLIENT_SECRET:
            raise ConnectorError("Missing GITHUB_CLIENT_ID or GITHUB_CLIENT_SECRET.")
        connector = cls()
        res = connector._request_with_retry(
            "POST",
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.GITHUB_CLIENT_ID,
                "client_secret": settings.GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        payload = res.json() if res.text else {}
        if res.status_code != 200 or not payload.get("access_token"):
            raise ConnectorError(
                f"GitHub OAuth exchange failed: {payload.get('error_description') or payload.get('error') or res.status_code}"
            )
        return {
            "access_token": payload["access_token"],
            "token": payload["access_token"],
            "scope": payload.get("scope", ""),
            "token_type": payload.get("token_type", "bearer"),
        }

    def check_connection(self) -> Dict[str, Any]:
        if not self.token:
            return {
                "status": "unconfigured",
                "auth_type": "none",
                "message": "Missing GitHub OAuth or personal access token.",
                "rate_limit_remaining": 0,
            }
        try:
            res = self._request_with_retry("GET", f"{self.base_url}/user", headers=self.headers, timeout=8)
            if res.status_code == 200:
                data = res.json()
                raw_scopes = res.headers.get("X-OAuth-Scopes", "")
                scopes = [s.strip() for s in raw_scopes.split(",") if s.strip()]
                return {
                    "status": "connected",
                    "auth_type": "oauth_token",
                    "login": data.get("login"),
                    "connected_account": data.get("login") or data.get("email"),
                    "name": data.get("name"),
                    "scopes": scopes,
                    "rate_limit_remaining": int(res.headers.get("X-RateLimit-Remaining", 5000)),
                }
            return {
                "status": "error",
                "message": f"GitHub authentication failed ({res.status_code}): {res.text[:200]}",
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def list_repositories(self, max_pages: int = 3) -> List[Dict[str, Any]]:
        if not self.token:
            return []
        repos: List[Dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            res = self._request_with_retry(
                "GET",
                f"{self.base_url}/user/repos",
                headers=self.headers,
                params={"per_page": 100, "page": page, "sort": "updated"},
            )
            if res.status_code != 200:
                break
            batch = res.json()
            if not batch:
                break
            for r in batch:
                repos.append({
                    "full_name": r.get("full_name"),
                    "private": r.get("private", False),
                    "default_branch": r.get("default_branch", "main"),
                    "html_url": r.get("html_url"),
                })
            if len(batch) < 100:
                break
        return repos

    def _paginated_get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        max_pages: int = 10,
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        base_params = dict(params or {})
        base_params.setdefault("per_page", 100)
        for page in range(1, max_pages + 1):
            base_params["page"] = page
            res = self._request_with_retry(
                "GET",
                f"{self.base_url}{path}",
                headers=self.headers,
                params=base_params,
            )
            if res.status_code != 200:
                if res.status_code in (401, 403, 404):
                    raise ConnectorError(f"GitHub API error {res.status_code} on {path}: {res.text[:200]}")
                break
            batch = res.json()
            if not isinstance(batch, list) or not batch:
                break
            results.extend(batch)
            if len(batch) < base_params["per_page"]:
                break
        return results

    def sync_repository(
        self,
        owner_repo: str,
        since_iso: Optional[str] = None,
        max_pages: int = 10,
    ) -> List[Dict[str, Any]]:
        """Sync PRs (with reviews & comments), commits, issues (with comments), releases, and branches."""
        if not self.token:
            raise ConnectorError("Missing GitHub access token.")
        if not owner_repo or "/" not in owner_repo:
            raise ConnectorError("Invalid repository target. Expected 'owner/repo'.")

        records: List[Dict[str, Any]] = []
        since_dt = parse_iso_timestamp(since_iso)

        # 1. Pull Requests + Reviews + Review Comments
        prs = self._paginated_get(
            f"/repos/{owner_repo}/pulls",
            params={"state": "all", "sort": "updated", "direction": "desc"},
            max_pages=max_pages,
        )
        for pr in prs:
            updated_dt = parse_iso_timestamp(pr.get("updated_at"))
            if since_dt and updated_dt and updated_dt <= since_dt:
                break
            pr_num = pr.get("number")
            author = (pr.get("user") or {}).get("login") or "unknown"
            state = pr.get("state", "open")
            merged_at = pr.get("merged_at")
            status_label = "merged" if merged_at else state

            # Fetch PR reviews & review comments for rich rationale
            reviews_text = []
            try:
                rev_res = self._request_with_retry(
                    "GET", f"{self.base_url}/repos/{owner_repo}/pulls/{pr_num}/reviews", headers=self.headers
                )
                if rev_res.status_code == 200:
                    for rv in rev_res.json()[:20]:
                        r_user = (rv.get("user") or {}).get("login") or "reviewer"
                        r_state = rv.get("state")
                        r_body = (rv.get("body") or "").strip()
                        if r_body or r_state:
                            reviews_text.append(f"- Review by {r_user} [{r_state}]: {r_body}")
            except Exception:
                pass

            comments_text = []
            try:
                cmt_res = self._request_with_retry(
                    "GET", f"{self.base_url}/repos/{owner_repo}/issues/{pr_num}/comments", headers=self.headers
                )
                if cmt_res.status_code == 200:
                    for cm in cmt_res.json()[:30]:
                        c_user = (cm.get("user") or {}).get("login") or "commenter"
                        c_body = (cm.get("body") or "").strip()
                        if c_body:
                            comments_text.append(f"- {c_user}: {c_body}")
            except Exception:
                pass

            files_changed = []
            try:
                files_res = self._request_with_retry(
                    "GET", f"{self.base_url}/repos/{owner_repo}/pulls/{pr_num}/files", headers=self.headers
                )
                if files_res.status_code == 200:
                    files_changed = [f.get("filename") for f in files_res.json()[:40] if f.get("filename")]
            except Exception:
                pass

            content_parts = [
                f"PR #{pr_num}: {pr.get('title')}",
                f"Repository: {owner_repo} | State: {status_label} | Author: {author}",
                f"Base: {(pr.get('base') or {}).get('ref')} <- Head: {(pr.get('head') or {}).get('ref')}",
                f"Updated: {pr.get('updated_at')}",
                "",
                "Description:",
                pr.get("body") or "No description provided.",
            ]
            if files_changed:
                content_parts.append("\nFiles Changed:\n" + "\n".join(f"- {fn}" for fn in files_changed))
            if reviews_text:
                content_parts.append("\nCode Reviews:\n" + "\n".join(reviews_text))
            if comments_text:
                content_parts.append("\nPR Discussion Comments:\n" + "\n".join(comments_text))

            content = "\n".join(content_parts)
            records.append({
                "source_type": "github_pr",
                "external_id": f"{owner_repo}#pr-{pr.get('id') or pr_num}",
                "title": f"PR #{pr_num}: {pr.get('title')}",
                "author": author,
                "url": pr.get("html_url"),
                "content": content,
                "sha256": compute_sha256(content),
                "source_timestamp": updated_dt or parse_iso_timestamp(pr.get("created_at")),
                "metadata": {
                    "repository": owner_repo,
                    "pr_number": pr_num,
                    "state": status_label,
                    "files_changed": files_changed,
                },
                "raw_payload": pr,
            })

        # 2. Commits (supports native GitHub `since` incremental param)
        commit_params: Dict[str, Any] = {}
        if since_iso:
            commit_params["since"] = since_iso
        commits = self._paginated_get(f"/repos/{owner_repo}/commits", params=commit_params, max_pages=max_pages)
        for c in commits:
            commit_data = c.get("commit") or {}
            author_data = commit_data.get("author") or {}
            gh_author = (c.get("author") or {}).get("login")
            author_name = gh_author or author_data.get("name") or "developer"
            msg = commit_data.get("message") or ""
            sha = c.get("sha") or ""
            c_dt = parse_iso_timestamp(author_data.get("date"))
            content = f"Commit {sha[:8]} in {owner_repo}\nAuthor: {author_name}\nDate: {author_data.get('date')}\n\n{msg}"
            records.append({
                "source_type": "github_commit",
                "external_id": sha,
                "title": f"Commit {sha[:8]}: {msg.splitlines()[0] if msg else 'Commit'}",
                "author": author_name,
                "url": c.get("html_url"),
                "content": content,
                "sha256": compute_sha256(content),
                "source_timestamp": c_dt,
                "metadata": {"repository": owner_repo, "sha": sha},
                "raw_payload": c,
            })

        # 3. Issues (excluding PRs) + Issue Comments
        issue_params: Dict[str, Any] = {"state": "all", "sort": "updated", "direction": "desc"}
        if since_iso:
            issue_params["since"] = since_iso
        issues = self._paginated_get(f"/repos/{owner_repo}/issues", params=issue_params, max_pages=max_pages)
        for issue in issues:
            if "pull_request" in issue:
                continue
            issue_num = issue.get("number")
            author = (issue.get("user") or {}).get("login") or "unknown"
            labels = [lbl.get("name") for lbl in (issue.get("labels") or []) if lbl.get("name")]
            comments_text = []
            if issue.get("comments", 0) > 0:
                try:
                    ic_res = self._request_with_retry(
                        "GET", f"{self.base_url}/repos/{owner_repo}/issues/{issue_num}/comments", headers=self.headers
                    )
                    if ic_res.status_code == 200:
                        for cm in ic_res.json()[:30]:
                            c_user = (cm.get("user") or {}).get("login") or "commenter"
                            c_body = (cm.get("body") or "").strip()
                            if c_body:
                                comments_text.append(f"- {c_user}: {c_body}")
                except Exception:
                    pass

            content_parts = [
                f"Issue #{issue_num}: {issue.get('title')}",
                f"Repository: {owner_repo} | State: {issue.get('state')} | Author: {author}",
                f"Labels: {', '.join(labels) if labels else 'None'}",
                "",
                issue.get("body") or "",
            ]
            if comments_text:
                content_parts.append("\nIssue Comments:\n" + "\n".join(comments_text))
            content = "\n".join(content_parts)
            records.append({
                "source_type": "github_issue",
                "external_id": f"{owner_repo}#issue-{issue.get('id') or issue_num}",
                "title": f"Issue #{issue_num}: {issue.get('title')}",
                "author": author,
                "url": issue.get("html_url"),
                "content": content,
                "sha256": compute_sha256(content),
                "source_timestamp": parse_iso_timestamp(issue.get("updated_at") or issue.get("created_at")),
                "metadata": {"repository": owner_repo, "issue_number": issue_num, "state": issue.get("state"), "labels": labels},
                "raw_payload": issue,
            })

        # 4. Releases
        try:
            releases = self._paginated_get(f"/repos/{owner_repo}/releases", max_pages=2)
            for rel in releases:
                rel_dt = parse_iso_timestamp(rel.get("published_at") or rel.get("created_at"))
                if since_dt and rel_dt and rel_dt <= since_dt:
                    continue
                tag = rel.get("tag_name") or "release"
                author = (rel.get("author") or {}).get("login") or "maintainer"
                content = f"Release {tag}: {rel.get('name') or tag}\nRepository: {owner_repo}\nAuthor: {author}\n\n{rel.get('body') or ''}"
                records.append({
                    "source_type": "github_release",
                    "external_id": f"{owner_repo}#release-{rel.get('id') or tag}",
                    "title": f"Release {tag} ({owner_repo})",
                    "author": author,
                    "url": rel.get("html_url"),
                    "content": content,
                    "sha256": compute_sha256(content),
                    "source_timestamp": rel_dt,
                    "metadata": {"repository": owner_repo, "tag": tag},
                    "raw_payload": rel,
                })
        except Exception:
            pass

        # 5. Branches & Contributors Ownership Summary
        try:
            branches = self._paginated_get(f"/repos/{owner_repo}/branches", max_pages=2)
            contributors = self._paginated_get(f"/repos/{owner_repo}/contributors", max_pages=2)
            if branches or contributors:
                branch_lines = [f"- `{b.get('name')}` (protected={bool(b.get('protected'))})" for b in branches[:30]]
                contrib_lines = [
                    f"- {c.get('login') or c.get('name')}: {c.get('contributions', 0)} commits"
                    for c in contributors[:30]
                ]
                summary_parts = [f"Repository Topology & Ownership Summary for {owner_repo}"]
                if branch_lines:
                    summary_parts.append("\nActive Branches:\n" + "\n".join(branch_lines))
                if contrib_lines:
                    summary_parts.append("\nTop Contributors:\n" + "\n".join(contrib_lines))
                content = "\n".join(summary_parts)
                records.append({
                    "source_type": "github_repository",
                    "external_id": f"{owner_repo}#repo-summary",
                    "title": f"Repository Branches & Contributors ({owner_repo})",
                    "author": (contributors[0].get("login") if contributors else "maintainer") or "maintainer",
                    "url": f"https://github.com/{owner_repo}",
                    "content": content,
                    "sha256": compute_sha256(content),
                    "source_timestamp": datetime.now(timezone.utc),
                    "metadata": {
                        "repository": owner_repo,
                        "branches": [b.get("name") for b in branches[:30] if b.get("name")],
                        "contributors": [c.get("login") for c in contributors[:30] if c.get("login")],
                    },
                    "raw_payload": {"branches": branches[:30], "contributors": contributors[:30]},
                })
        except Exception:
            pass

        return records

    def sync(
        self,
        config: Optional[Dict[str, Any]] = None,
        sync_cursor: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        cfg = config or {}
        cursor = dict(sync_cursor or {})
        repos: List[str] = []
        if cfg.get("repos") and isinstance(cfg["repos"], list):
            repos = [r.strip() for r in cfg["repos"] if isinstance(r, str) and "/" in r]
        else:
            target = (cfg.get("repo") or cfg.get("target") or "").strip()
            if target and "/" in target:
                repos = [target]
            else:
                # Auto-discover up to 5 most recently updated accessible repos
                repos = [r["full_name"] for r in self.list_repositories(max_pages=1)[:5] if r.get("full_name")]

        if not repos:
            raise ConnectorError("No GitHub repository target configured (e.g. 'owner/repo').")

        all_records: List[Dict[str, Any]] = []
        now_iso = datetime.now(timezone.utc).isoformat()
        for repo_name in repos:
            since_iso = cursor.get(repo_name)
            recs = self.sync_repository(repo_name, since_iso=since_iso)
            all_records.extend(recs)
            cursor[repo_name] = now_iso

        return all_records, cursor


github_connector = GitHubConnector()
