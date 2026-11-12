import threading
import time
from typing import Any, Dict, Optional


class PipelineTracker:
    """Thread-safe in-memory tracker for background sync, chunking, and AI graph extraction jobs."""

    def __init__(self, max_projects: int = 500):
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._max_projects = max_projects

    def update(
        self,
        project_id: str,
        *,
        stage: str,
        message: str,
        progress: int = 0,
        active: bool = True,
        job_type: str = "knowledge_extraction",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not project_id:
            return
        now = time.time()
        with self._lock:
            if len(self._jobs) >= self._max_projects and project_id not in self._jobs:
                oldest_key = min(self._jobs, key=lambda k: self._jobs[k].get("updated_at", 0))
                self._jobs.pop(oldest_key, None)
            self._jobs[project_id] = {
                "project_id": project_id,
                "active": active,
                "stage": stage,
                "job_type": job_type,
                "message": message,
                "progress": max(0, min(100, int(progress))),
                "details": details or {},
                "updated_at": now,
            }

    def get(self, project_id: str) -> Dict[str, Any]:
        with self._lock:
            item = self._jobs.get(project_id)
            if not item:
                return {
                    "project_id": project_id,
                    "active": False,
                    "stage": "idle",
                    "job_type": "none",
                    "message": "No active background jobs.",
                    "progress": 100,
                    "details": {},
                }
            # Auto-expire stale completed banners after 90 seconds so UI stays clean
            age = time.time() - float(item.get("updated_at", 0))
            if not item.get("active") and age > 90:
                self._jobs.pop(project_id, None)
                return {
                    "project_id": project_id,
                    "active": False,
                    "stage": "idle",
                    "job_type": "none",
                    "message": "No active background jobs.",
                    "progress": 100,
                    "details": {},
                }
            return dict(item)


pipeline_tracker = PipelineTracker()

