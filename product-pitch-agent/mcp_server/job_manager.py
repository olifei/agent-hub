"""
Job Manager for tracking async pipeline jobs.

Provides job creation, status tracking, progress updates,
and notification callbacks for MCP server-to-client notifications.

Jobs are scoped per user_id (extracted from IAP headers).
"""

import uuid
import threading
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job:
    """Represents a pipeline job, scoped to a user."""

    def __init__(self, job_id: str, mode: str, params: dict, user_id: str = "anonymous"):
        self.job_id = job_id
        self.user_id = user_id
        self.mode = mode
        self.params = params
        self.status = JobStatus.PENDING
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at
        self.progress: dict = {}
        self.result: Optional[dict] = None
        self.error: Optional[str] = None
        self._cancel_event = threading.Event()

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "user_id": self.user_id,
            "mode": self.mode,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "params": self.params,
        }

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def cancel(self):
        self._cancel_event.set()
        self.status = JobStatus.CANCELLED
        self.updated_at = datetime.now().isoformat()


class JobManager:
    """Thread-safe job manager with user-scoped operations."""

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._notification_callback: Optional[Callable] = None

    def set_notification_callback(self, callback: Callable):
        """Set callback for sending MCP notifications on job events."""
        self._notification_callback = callback

    def create_job(self, mode: str, params: dict, user_id: str = "anonymous") -> Job:
        job_id = str(uuid.uuid4())[:8]
        job = Job(job_id, mode, params, user_id=user_id)
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get_job(self, job_id: str, user_id: str = None) -> Optional[Job]:
        """Get a job by ID. If user_id is provided, only return if it belongs to that user."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job and user_id and job.user_id != user_id:
                return None  # User can only see their own jobs
            return job

    def list_jobs(self, user_id: str = None) -> list[dict]:
        """List jobs. If user_id provided, only return that user's jobs."""
        with self._lock:
            if user_id:
                return [job.to_dict() for job in self._jobs.values() if job.user_id == user_id]
            return [job.to_dict() for job in self._jobs.values()]

    def update_job_status(self, job_id: str, status: JobStatus, 
                          result: dict = None, error: str = None, 
                          progress: dict = None):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = status
            job.updated_at = datetime.now().isoformat()
            if result is not None:
                job.result = result
            if error is not None:
                job.error = error
            if progress is not None:
                job.progress = progress

        # Send notification if callback set
        if self._notification_callback and status in (
            JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED
        ):
            try:
                self._notification_callback(job.to_dict())
            except Exception:
                pass  # Don't crash on notification failure

    def cancel_job(self, job_id: str, user_id: str = None) -> Optional[dict]:
        """Cancel a job. If user_id provided, only cancel if it belongs to that user."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if user_id and job.user_id != user_id:
                return None  # Can't cancel another user's job
            if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                return job.to_dict()
            job.cancel()
        return job.to_dict()


# Singleton instance
job_manager = JobManager()
