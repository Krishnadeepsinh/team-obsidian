import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("obsidian.pipeline")


class PipelineTracker:
    """Thread-safe DB-backed + L1 in-memory tracker for background sync, chunking, and extraction jobs."""

    def __init__(self, max_projects: int = 500):
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._max_projects = max_projects

    @staticmethod
    def _persist_job(
        *,
        project_id: str,
        stage: str,
        message: str,
        progress: int,
        active: bool,
        job_type: str,
        integration_id: Optional[str] = None,
        error_message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        try:
            from app.core.database import SessionLocal
            from app.models.integration import PipelineJob

            session = SessionLocal()
            try:
                status = "failed" if stage == "failed" else ("running" if active else "completed")
                now = datetime.now(timezone.utc)
                q = session.query(PipelineJob).filter(
                    PipelineJob.project_id == project_id,
                    PipelineJob.job_type == job_type,
                    PipelineJob.status.in_(["queued", "running"]),
                )
                if integration_id:
                    q = q.filter(PipelineJob.integration_id == integration_id)
                row = q.order_by(PipelineJob.updated_at.desc()).first()

                if row is None:
                    row = PipelineJob(
                        project_id=project_id,
                        integration_id=integration_id,
                        job_type=job_type,
                        stage=stage,
                        status=status,
                        progress=progress,
                        message=message,
                        details=details or {},
                        error_message=error_message,
                        started_at=now,
                        completed_at=None if active else now,
                        updated_at=now,
                    )
                    session.add(row)
                else:
                    row.stage = stage
                    row.status = status
                    row.progress = progress
                    row.message = message
                    if details:
                        merged = dict(row.details or {})
                        merged.update(details)
                        row.details = merged
                    if error_message:
                        row.error_message = error_message
                    row.completed_at = None if active else now
                    row.updated_at = now
                session.commit()
                return row.id
            except Exception as exc:
                logger.debug("PipelineJob persistence skipped: %s", exc)
                session.rollback()
                return None
            finally:
                session.close()
        except Exception:
            return None

    def update(
        self,
        project_id: str,
        *,
        stage: str,
        message: str,
        progress: int = 0,
        active: bool = True,
        job_type: str = "knowledge_extraction",
        integration_id: Optional[str] = None,
        error_message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not project_id:
            return
        now = time.time()
        clamped_progress = max(0, min(100, int(progress)))
        integ_id = integration_id or (details or {}).get("integration_id")
        job_id = self._persist_job(
            project_id=project_id,
            stage=stage,
            message=message,
            progress=clamped_progress,
            active=active,
            job_type=job_type,
            integration_id=integ_id,
            error_message=error_message or (message if stage == "failed" else None),
            details=details,
        )
        with self._lock:
            if len(self._jobs) >= self._max_projects and project_id not in self._jobs:
                oldest_key = min(self._jobs, key=lambda k: self._jobs[k].get("updated_at", 0))
                self._jobs.pop(oldest_key, None)
            self._jobs[project_id] = {
                "id": job_id,
                "project_id": project_id,
                "integration_id": integ_id,
                "active": active,
                "stage": stage,
                "status": "failed" if stage == "failed" else ("running" if active else "completed"),
                "job_type": job_type,
                "message": message,
                "progress": clamped_progress,
                "details": details or {},
                "updated_at": now,
            }

    def get(self, project_id: str) -> Dict[str, Any]:
        with self._lock:
            item = self._jobs.get(project_id)
            if item:
                age = time.time() - float(item.get("updated_at", 0))
                if item.get("active") or age <= 90:
                    return dict(item)
                self._jobs.pop(project_id, None)

        # Fallback to DB for durability across worker restarts
        try:
            from app.core.database import SessionLocal
            from app.models.integration import PipelineJob

            session = SessionLocal()
            try:
                latest = (
                    session.query(PipelineJob)
                    .filter(PipelineJob.project_id == project_id)
                    .order_by(PipelineJob.updated_at.desc())
                    .first()
                )
                if latest:
                    is_active = latest.status in ("queued", "running")
                    upd_ts = latest.updated_at
                    if upd_ts and upd_ts.tzinfo is None:
                        upd_ts = upd_ts.replace(tzinfo=timezone.utc)
                    age_sec = (datetime.now(timezone.utc) - upd_ts).total_seconds() if upd_ts else 9999
                    if is_active or age_sec <= 90:
                        return {
                            "id": latest.id,
                            "project_id": latest.project_id,
                            "integration_id": latest.integration_id,
                            "active": is_active,
                            "stage": latest.stage,
                            "status": latest.status,
                            "job_type": latest.job_type,
                            "message": latest.message or "",
                            "progress": latest.progress,
                            "details": latest.details or {},
                        }
            finally:
                session.close()
        except Exception:
            pass

        return {
            "project_id": project_id,
            "active": False,
            "stage": "idle",
            "status": "idle",
            "job_type": "none",
            "message": "No active background jobs.",
            "progress": 100,
            "details": {},
        }

    def list_jobs(
        self,
        *,
        project_id: Optional[str] = None,
        project_ids: Optional[List[str]] = None,
        integration_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        try:
            from app.core.database import SessionLocal
            from app.models.integration import PipelineJob

            session = SessionLocal()
            try:
                q = session.query(PipelineJob)
                if project_id:
                    q = q.filter(PipelineJob.project_id == project_id)
                elif project_ids:
                    q = q.filter(PipelineJob.project_id.in_(project_ids))
                if integration_id:
                    q = q.filter(PipelineJob.integration_id == integration_id)
                rows = q.order_by(PipelineJob.updated_at.desc()).limit(max(1, min(100, limit))).all()
                return [
                    {
                        "id": r.id,
                        "project_id": r.project_id,
                        "integration_id": r.integration_id,
                        "job_type": r.job_type,
                        "stage": r.stage,
                        "status": r.status,
                        "progress": r.progress,
                        "message": r.message,
                        "details": r.details or {},
                        "error_message": r.error_message,
                        "started_at": r.started_at.isoformat() if r.started_at else None,
                        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                    }
                    for r in rows
                ]
            finally:
                session.close()
        except Exception:
            return []


pipeline_tracker = PipelineTracker()
