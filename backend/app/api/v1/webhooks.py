import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.security import decrypt_credentials
from app.models.integration import Integration, SourceEvent
from app.services.connectors.base import compute_sha256
from app.services.drift_detector import scan_project_for_drift
from app.services.ingestion_service import upsert_source_records
from app.services.knowledge_extractor import extract_and_persist_project_knowledge

logger = logging.getLogger("team_obsidian.webhooks")
router = APIRouter(prefix="/webhooks", tags=["Realtime Webhooks"])


def _verify_sha256_signature(secret: str, raw_body: bytes, signature_header: Optional[str], prefix: str = "sha256=") -> bool:
    if not secret or not signature_header:
        return False
    sig = signature_header.strip()
    if prefix and sig.startswith(prefix):
        sig = sig[len(prefix):]
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def _get_webhook_secret(integ: Integration) -> str:
    creds = decrypt_credentials(integ.credentials)
    return str(creds.get("webhook_secret") or "").strip()


def _run_webhook_pipeline(project_id: str, integration_id: str) -> None:
    db = SessionLocal()
    try:
        extract_and_persist_project_knowledge(db, project_id)
        scan_project_for_drift(db, project_id)
    except Exception as exc:
        db.rollback()
        logger.warning("Background webhook processing error for %s: %s", integration_id, str(exc)[:140])
    finally:
        db.close()


@router.post("/github/{integration_id}")
async def github_webhook(
    integration_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Receive signed GitHub webhook events (push, pull_request, issues), ingest delta, and run drift scan."""
    integ = db.query(Integration).filter(Integration.id == integration_id, Integration.provider == "github").first()
    if not integ:
        raise HTTPException(status_code=404, detail="GitHub integration not found")

    raw_body = await request.body()
    secret = _get_webhook_secret(integ)
    if not secret:
        raise HTTPException(status_code=403, detail="Webhook secret is not configured for this integration.")
    sig_header = request.headers.get("X-Hub-Signature-256")
    if not _verify_sha256_signature(secret, raw_body, sig_header, prefix="sha256="):
        raise HTTPException(status_code=401, detail="Invalid GitHub webhook HMAC-SHA256 signature.")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON webhook payload.")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="GitHub webhook payload must be a JSON object.")

    event_name = (request.headers.get("X-GitHub-Event") or "push").lower()
    repo_name = (payload.get("repository") or {}).get("full_name") or integ.name
    now = datetime.now(timezone.utc)
    records: List[Dict[str, Any]] = []

    if event_name == "pull_request":
        pr = payload.get("pull_request") or {}
        pr_num = pr.get("number") or payload.get("number")
        title = pr.get("title") or f"PR #{pr_num}"
        author = (pr.get("user") or {}).get("login") or "github-user"
        state = "merged" if pr.get("merged") else pr.get("state", "updated")
        content = (
            f"PR #{pr_num}: {title}\n"
            f"Repository: {repo_name} | Action: {payload.get('action')} | State: {state} | Author: {author}\n\n"
            f"{pr.get('body') or ''}"
        )
        records.append({
            "source_type": "github_pr",
            "external_id": f"{repo_name}#pr-{pr.get('id') or pr_num}",
            "title": f"PR #{pr_num}: {title}",
            "author": author,
            "url": pr.get("html_url"),
            "content": content,
            "sha256": compute_sha256(content),
            "source_timestamp": now,
            "metadata": {"repository": repo_name, "webhook_event": "pull_request", "action": payload.get("action")},
            "raw_payload": payload,
        })
    elif event_name == "issues":
        issue = payload.get("issue") or {}
        num = issue.get("number")
        author = (issue.get("user") or {}).get("login") or "github-user"
        content = (
            f"Issue #{num}: {issue.get('title')}\n"
            f"Repository: {repo_name} | Action: {payload.get('action')} | Author: {author}\n\n"
            f"{issue.get('body') or ''}"
        )
        records.append({
            "source_type": "github_issue",
            "external_id": f"{repo_name}#issue-{issue.get('id') or num}",
            "title": f"Issue #{num}: {issue.get('title')}",
            "author": author,
            "url": issue.get("html_url"),
            "content": content,
            "sha256": compute_sha256(content),
            "source_timestamp": now,
            "metadata": {"repository": repo_name, "webhook_event": "issues", "action": payload.get("action")},
            "raw_payload": payload,
        })
    elif event_name == "push":
        for c in (payload.get("commits") or [])[:15]:
            sha = c.get("id") or c.get("sha") or compute_sha256(json.dumps(c))[:12]
            msg = c.get("message") or "Commit push"
            author = (c.get("author") or {}).get("name") or (payload.get("pusher") or {}).get("name") or "committer"
            modified = ", ".join((c.get("modified") or []) + (c.get("added") or []) + (c.get("removed") or []))
            content = (
                f"Commit {sha[:10]} in {repo_name} (ref {payload.get('ref', 'main')}): {msg}\n"
                f"Author: {author}\n"
                f"Files Touched: {modified or 'n/a'}"
            )
            records.append({
                "source_type": "github_commit",
                "external_id": f"{repo_name}#commit-{sha}",
                "title": f"Commit {sha[:8]}: {msg.splitlines()[0][:120]}",
                "author": author,
                "url": c.get("url"),
                "content": content,
                "sha256": compute_sha256(content),
                "source_timestamp": now,
                "metadata": {"repository": repo_name, "webhook_event": "push", "ref": payload.get("ref")},
                "raw_payload": c,
            })

    counts = {"added": 0, "updated": 0, "skipped": 0}
    if records:
        counts = upsert_source_records(db=db, integration=integ, raw_records=records)

    db.add(
        SourceEvent(
            integration_id=integ.id,
            event_type="webhook_received",
            status="success",
            records_added=counts["added"],
            records_updated=counts["updated"],
            records_skipped=counts["skipped"],
            details={"provider": "github", "event": event_name, "repository": repo_name},
        )
    )
    integ.last_sync = now
    db.commit()

    drift_summary = scan_project_for_drift(db, integ.project_id) if records else {"detected": 0, "events": []}
    if records:
        background_tasks.add_task(_run_webhook_pipeline, integ.project_id, integ.id)

    return {
        "status": "accepted",
        "event": event_name,
        "records": counts,
        "drift_detected": drift_summary.get("detected", 0),
    }


@router.post("/slack/{integration_id}")
async def slack_webhook(
    integration_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Receive Slack Events API callbacks (supports url_verification + signed X-Slack-Signature ingestion)."""
    integ = db.query(Integration).filter(Integration.id == integration_id, Integration.provider == "slack").first()
    if not integ:
        raise HTTPException(status_code=404, detail="Slack integration not found")

    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Slack webhook payload.")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Slack webhook payload must be a JSON object.")

    secret = _get_webhook_secret(integ)
    if not secret:
        raise HTTPException(status_code=403, detail="Slack signing webhook secret is not configured.")

    ts = (request.headers.get("X-Slack-Request-Timestamp") or "").strip()
    sig = request.headers.get("X-Slack-Signature") or ""
    try:
        ts_val = int(ts)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or missing Slack request timestamp.")
    if abs(time.time() - ts_val) > 300:
        raise HTTPException(status_code=401, detail="Stale Slack webhook timestamp outside 5-minute replay window.")
    base_str = f"v0:{ts}:{raw_body.decode('utf-8', errors='replace')}".encode("utf-8")
    expected = "v0=" + hmac.new(secret.encode("utf-8"), base_str, hashlib.sha256).hexdigest()
    if not sig or not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=401, detail="Invalid Slack webhook signature.")

    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    event = payload.get("event") or {}
    text_msg = (event.get("text") or "").strip()
    records: List[Dict[str, Any]] = []
    if text_msg:
        channel_id = event.get("channel") or "slack-channel"
        msg_ts = event.get("ts") or compute_sha256(text_msg)[:12]
        user_id = event.get("user") or "slack-member"
        content = f"Slack realtime message in #{channel_id} by {user_id}:\n{text_msg}"
        records.append({
            "source_type": "slack_message",
            "external_id": f"{channel_id}#msg-{msg_ts}",
            "title": f"Slack #{channel_id}: {text_msg[:80]}",
            "author": user_id,
            "content": content,
            "sha256": compute_sha256(content),
            "source_timestamp": datetime.now(timezone.utc),
            "metadata": {"channel_id": channel_id, "webhook_event": event.get("type")},
            "raw_payload": event,
        })

    counts = upsert_source_records(db=db, integration=integ, raw_records=records) if records else {"added": 0, "updated": 0, "skipped": 0}
    db.add(
        SourceEvent(
            integration_id=integ.id,
            event_type="webhook_received",
            status="success",
            records_added=counts["added"],
            records_updated=counts["updated"],
            records_skipped=counts["skipped"],
            details={"provider": "slack", "event_type": event.get("type")},
        )
    )
    db.commit()

    drift_summary = scan_project_for_drift(db, integ.project_id) if records else {"detected": 0}
    if records:
        background_tasks.add_task(_run_webhook_pipeline, integ.project_id, integ.id)

    return {"status": "accepted", "records": counts, "drift_detected": drift_summary.get("detected", 0)}


@router.post("/notion/{integration_id}")
async def notion_webhook(
    integration_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Receive signed Notion webhook events for real-time page/database updates."""
    integ = db.query(Integration).filter(Integration.id == integration_id, Integration.provider == "notion").first()
    if not integ:
        raise HTTPException(status_code=404, detail="Notion integration not found")

    raw_body = await request.body()
    secret = _get_webhook_secret(integ)
    if not secret:
        raise HTTPException(status_code=403, detail="Notion webhook secret is not configured.")
    sig = request.headers.get("X-Notion-Signature")
    if not _verify_sha256_signature(secret, raw_body, sig, prefix="sha256="):
        raise HTTPException(status_code=401, detail="Invalid Notion webhook signature.")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Notion webhook payload.")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Notion webhook payload must be a JSON object.")

    entity = payload.get("entity") or payload
    page_id = str(entity.get("id") or payload.get("id") or compute_sha256(raw_body.decode("utf-8", errors="replace"))[:12])
    title = payload.get("title") or f"Notion Page {page_id[:8]}"
    body_text = payload.get("content") or payload.get("summary") or f"Notion webhook update ({payload.get('type', 'page.updated')}) for {title}"

    rec = {
        "source_type": "notion_page",
        "external_id": f"notion#{page_id}",
        "title": title[:500],
        "author": payload.get("actor_name") or "Notion Collaborator",
        "url": payload.get("url"),
        "content": body_text,
        "sha256": compute_sha256(body_text),
        "source_timestamp": datetime.now(timezone.utc),
        "metadata": {"page_id": page_id, "webhook_event": payload.get("type", "page.updated")},
        "raw_payload": payload,
    }
    counts = upsert_source_records(db=db, integration=integ, raw_records=[rec])
    db.add(
        SourceEvent(
            integration_id=integ.id,
            event_type="webhook_received",
            status="success",
            records_added=counts["added"],
            records_updated=counts["updated"],
            records_skipped=counts["skipped"],
            details={"provider": "notion", "page_id": page_id},
        )
    )
    db.commit()

    drift_summary = scan_project_for_drift(db, integ.project_id)
    background_tasks.add_task(_run_webhook_pipeline, integ.project_id, integ.id)
    return {"status": "accepted", "records": counts, "drift_detected": drift_summary.get("detected", 0)}


def _record_and_queue_webhook(
    db: Session,
    integ: Integration,
    background_tasks: BackgroundTasks,
    records: List[Dict[str, Any]],
    details: Dict[str, Any],
) -> Dict[str, Any]:
    counts = (
        upsert_source_records(db=db, integration=integ, raw_records=records)
        if records
        else {"added": 0, "updated": 0, "skipped": 0}
    )
    now = datetime.now(timezone.utc)
    db.add(
        SourceEvent(
            integration_id=integ.id,
            event_type="webhook_received",
            status="success",
            records_added=counts["added"],
            records_updated=counts["updated"],
            records_skipped=counts["skipped"],
            details=details,
        )
    )
    if records:
        integ.last_sync = now
    db.commit()

    drift_summary = scan_project_for_drift(db, integ.project_id) if records else {"detected": 0}
    if records:
        background_tasks.add_task(_run_webhook_pipeline, integ.project_id, integ.id)
    return {"status": "accepted", "records": counts, "drift_detected": drift_summary.get("detected", 0)}


@router.post("/gitlab/{integration_id}")
async def gitlab_webhook(
    integration_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Receive signed GitLab webhook events (X-Gitlab-Token verification)."""
    integ = db.query(Integration).filter(Integration.id == integration_id, Integration.provider == "gitlab").first()
    if not integ:
        raise HTTPException(status_code=404, detail="GitLab integration not found")

    secret = _get_webhook_secret(integ)
    if not secret:
        raise HTTPException(status_code=403, detail="GitLab webhook secret is not configured.")
    token_hdr = (request.headers.get("X-Gitlab-Token") or "").strip()
    if not token_hdr or not hmac.compare_digest(secret, token_hdr):
        raise HTTPException(status_code=401, detail="Invalid GitLab webhook token.")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid GitLab webhook JSON payload.")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="GitLab webhook payload must be a JSON object.")

    kind = (payload.get("object_kind") or request.headers.get("X-Gitlab-Event") or "push").lower()
    repo_name = (payload.get("project") or {}).get("path_with_namespace") or integ.name
    now = datetime.now(timezone.utc)
    records: List[Dict[str, Any]] = []

    if kind == "merge_request":
        attrs = payload.get("object_attributes") or {}
        iid = attrs.get("iid") or attrs.get("id")
        title = attrs.get("title") or f"MR !{iid}"
        author = (payload.get("user") or {}).get("username") or "gitlab-user"
        content = f"GitLab MR !{iid}: {title}\nRepository: {repo_name} | State: {attrs.get('state')}\n\n{attrs.get('description') or ''}".strip()
        records.append({
            "source_type": "gitlab_mr",
            "external_id": f"gitlab#{repo_name}#mr-{iid}",
            "title": f"MR !{iid}: {title}",
            "author": author,
            "url": attrs.get("url"),
            "content": content,
            "sha256": compute_sha256(content),
            "source_timestamp": now,
            "metadata": {"repository": repo_name, "mr_iid": iid, "webhook_event": kind},
            "raw_payload": payload,
        })
    elif kind == "issue":
        attrs = payload.get("object_attributes") or {}
        iid = attrs.get("iid") or attrs.get("id")
        title = attrs.get("title") or f"Issue #{iid}"
        author = (payload.get("user") or {}).get("username") or "gitlab-user"
        content = f"GitLab Issue #{iid}: {title}\nRepository: {repo_name} | State: {attrs.get('state')}\n\n{attrs.get('description') or ''}".strip()
        records.append({
            "source_type": "gitlab_issue",
            "external_id": f"gitlab#{repo_name}#issue-{iid}",
            "title": f"Issue #{iid}: {title}",
            "author": author,
            "url": attrs.get("url"),
            "content": content,
            "sha256": compute_sha256(content),
            "source_timestamp": now,
            "metadata": {"repository": repo_name, "issue_iid": iid, "webhook_event": kind},
            "raw_payload": payload,
        })
    elif kind == "push":
        for c in (payload.get("commits") or [])[:15]:
            sha = c.get("id") or compute_sha256(json.dumps(c))[:12]
            msg = c.get("message") or c.get("title") or "Commit push"
            author = (c.get("author") or {}).get("name") or payload.get("user_name") or "committer"
            content = f"GitLab Commit {str(sha)[:10]} in {repo_name}:\nAuthor: {author}\n\n{msg}"
            records.append({
                "source_type": "gitlab_commit",
                "external_id": f"gitlab#{repo_name}#commit-{sha}",
                "title": f"Commit {str(sha)[:8]}: {msg.splitlines()[0][:120]}",
                "author": author,
                "url": c.get("url"),
                "content": content,
                "sha256": compute_sha256(content),
                "source_timestamp": now,
                "metadata": {"repository": repo_name, "webhook_event": "push"},
                "raw_payload": c,
            })

    return _record_and_queue_webhook(db, integ, background_tasks, records, {"provider": "gitlab", "event": kind, "repository": repo_name})


@router.post("/linear/{integration_id}")
async def linear_webhook(
    integration_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Receive signed Linear webhook events (Linear-Signature HMAC-SHA256 verification)."""
    integ = db.query(Integration).filter(Integration.id == integration_id, Integration.provider == "linear").first()
    if not integ:
        raise HTTPException(status_code=404, detail="Linear integration not found")

    raw_body = await request.body()
    secret = _get_webhook_secret(integ)
    if not secret:
        raise HTTPException(status_code=403, detail="Linear webhook secret is not configured.")
    sig = request.headers.get("Linear-Signature")
    if not _verify_sha256_signature(secret, raw_body, sig, prefix=""):
        raise HTTPException(status_code=401, detail="Invalid Linear webhook signature.")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Linear webhook payload.")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Linear webhook payload must be a JSON object.")

    data = payload.get("data") or {}
    event_type = str(payload.get("type") or "Issue")
    ident = str(data.get("identifier") or data.get("id") or compute_sha256(raw_body.decode("utf-8", errors="replace"))[:10])
    title = str(data.get("title") or data.get("name") or f"Linear {event_type} {ident}")
    content = f"Linear {event_type} [{ident}]: {title}\nAction: {payload.get('action', 'update')}\n\n{data.get('description') or ''}".strip()
    rec = {
        "source_type": "linear_issue",
        "external_id": f"linear#{ident}",
        "title": f"[{ident}] {title[:400]}",
        "author": str(((data.get("assignee") or {}).get("name")) or "Linear Member"),
        "url": payload.get("url") or data.get("url"),
        "content": content,
        "sha256": compute_sha256(content),
        "source_timestamp": datetime.now(timezone.utc),
        "metadata": {"webhook_event": event_type, "action": payload.get("action"), "identifier": ident},
        "raw_payload": payload,
    }
    return _record_and_queue_webhook(db, integ, background_tasks, [rec], {"provider": "linear", "event": event_type, "identifier": ident})


@router.post("/jira/{integration_id}")
async def jira_webhook(
    integration_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Receive signed Jira Cloud webhook events (X-Hub-Signature HMAC-SHA256 verification)."""
    integ = db.query(Integration).filter(Integration.id == integration_id, Integration.provider == "jira").first()
    if not integ:
        raise HTTPException(status_code=404, detail="Jira integration not found")

    raw_body = await request.body()
    secret = _get_webhook_secret(integ)
    if not secret:
        raise HTTPException(status_code=403, detail="Jira webhook secret is not configured.")
    sig = request.headers.get("X-Hub-Signature") or request.headers.get("X-Hub-Signature-256")
    if not _verify_sha256_signature(secret, raw_body, sig, prefix="sha256="):
        raise HTTPException(status_code=401, detail="Invalid Jira webhook signature.")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Jira webhook payload.")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Jira webhook payload must be a JSON object.")

    issue = payload.get("issue") or {}
    fields = issue.get("fields") or {}
    key = str(issue.get("key") or issue.get("id") or compute_sha256(raw_body.decode("utf-8", errors="replace"))[:10])
    summary = str(fields.get("summary") or f"Jira Issue {key}")
    status_name = str(((fields.get("status") or {}).get("name")) or "Updated")
    author = str(((payload.get("user") or {}).get("displayName")) or ((fields.get("assignee") or {}).get("displayName")) or "Jira User")
    content = f"Jira [{key}] ({status_name}): {summary}\nEvent: {payload.get('webhookEvent', 'jira:issue_updated')}\n\n{fields.get('description') or ''}".strip()
    rec = {
        "source_type": "jira_issue",
        "external_id": f"jira#{key}",
        "title": f"[{key}] {summary[:400]}",
        "author": author,
        "url": issue.get("self"),
        "content": content,
        "sha256": compute_sha256(content),
        "source_timestamp": datetime.now(timezone.utc),
        "metadata": {"issue_key": key, "status": status_name, "webhook_event": payload.get("webhookEvent")},
        "raw_payload": payload,
    }
    return _record_and_queue_webhook(db, integ, background_tasks, [rec], {"provider": "jira", "issue_key": key})


@router.post("/sentry/{integration_id}")
async def sentry_webhook(
    integration_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Receive signed Sentry webhook alerts (Sentry-Hook-Signature HMAC-SHA256 verification)."""
    integ = db.query(Integration).filter(Integration.id == integration_id, Integration.provider == "sentry").first()
    if not integ:
        raise HTTPException(status_code=404, detail="Sentry integration not found")

    raw_body = await request.body()
    secret = _get_webhook_secret(integ)
    if not secret:
        raise HTTPException(status_code=403, detail="Sentry webhook secret is not configured.")
    sig = request.headers.get("Sentry-Hook-Signature")
    if not _verify_sha256_signature(secret, raw_body, sig, prefix=""):
        raise HTTPException(status_code=401, detail="Invalid Sentry webhook signature.")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Sentry webhook payload.")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Sentry webhook payload must be a JSON object.")

    data = payload.get("data") or {}
    issue = data.get("issue") or data.get("event") or payload
    iss_id = str(issue.get("id") or issue.get("issue_id") or compute_sha256(raw_body.decode("utf-8", errors="replace"))[:12])
    short_id = str(issue.get("shortId") or iss_id)
    title = str(issue.get("title") or issue.get("message") or f"Sentry Alert {short_id}")
    culprit = str(issue.get("culprit") or "unknown")
    content = f"Sentry Alert [{short_id}] ({payload.get('action', 'triggered')}): {title}\nCulprit: {culprit}\nLevel: {issue.get('level', 'error')}"
    rec = {
        "source_type": "sentry_issue",
        "external_id": f"sentry#webhook#{iss_id}",
        "title": f"[{short_id}] {title[:400]}",
        "author": "Sentry Monitor",
        "url": issue.get("permalink") or issue.get("web_url"),
        "content": content,
        "sha256": compute_sha256(content),
        "source_timestamp": datetime.now(timezone.utc),
        "metadata": {"short_id": short_id, "culprit": culprit, "action": payload.get("action")},
        "raw_payload": payload,
    }
    return _record_and_queue_webhook(db, integ, background_tasks, [rec], {"provider": "sentry", "short_id": short_id})

