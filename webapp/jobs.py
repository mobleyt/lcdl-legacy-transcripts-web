"""In-memory background job registry with a pub/sub log stream.

Each job runs the download+convert pipeline on a worker thread. Progress is
published as a list of events; the SSE endpoint replays the buffer to a newly
connected browser and then streams live events. No Redis/Celery — jobs live in
process memory and are lost on restart, which is acceptable for a single-user
internal admin tool.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


# Sentinel pushed to subscriber queues to signal "no more events".
_STREAM_END = object()


@dataclass
class Job:
    id: str
    params: dict
    work_dir: Path
    status: JobStatus = JobStatus.PENDING
    created_at: float = field(default_factory=time.time)
    result_zip: Optional[Path] = None
    error: Optional[str] = None

    # Event buffer + live subscribers, guarded by _lock.
    _events: list[dict] = field(default_factory=list)
    _subscribers: list["queue.Queue"] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def emit(self, type: str, message: str = "", **extra: Any) -> None:
        """Publish an event to the buffer and all live subscribers."""
        event = {"type": type, "message": message, "ts": time.time(), **extra}
        with self._lock:
            self._events.append(event)
            for sub in self._subscribers:
                sub.put(event)

    def log(self, message: str) -> None:
        self.emit("log", message)

    def subscribe(self) -> "queue.Queue":
        """Register a subscriber, pre-loaded with all buffered events."""
        sub: "queue.Queue" = queue.Queue()
        with self._lock:
            for event in self._events:
                sub.put(event)
            if self.status in (JobStatus.DONE, JobStatus.ERROR):
                sub.put(_STREAM_END)
            else:
                self._subscribers.append(sub)
        return sub

    def unsubscribe(self, sub: "queue.Queue") -> None:
        with self._lock:
            if sub in self._subscribers:
                self._subscribers.remove(sub)

    def _finish(self, status: JobStatus) -> None:
        with self._lock:
            self.status = status
            for sub in self._subscribers:
                sub.put(_STREAM_END)
            self._subscribers.clear()


class JobRegistry:
    def __init__(self, jobs_dir: Path):
        self.jobs_dir = jobs_dir
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, params: dict) -> Job:
        job_id = uuid.uuid4().hex[:12]
        work_dir = self.jobs_dir / job_id
        work_dir.mkdir(parents=True, exist_ok=True)
        job = Job(id=job_id, params=params, work_dir=work_dir)
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def start(self, job: Job, target: Callable[[Job], None]) -> None:
        """Run ``target(job)`` on a daemon thread, tracking status/errors."""

        def runner() -> None:
            job.status = JobStatus.RUNNING
            try:
                target(job)
                job.emit("done", "Job complete.")
                job._finish(JobStatus.DONE)
            except Exception as exc:  # noqa: BLE001 - surface any failure to UI
                job.error = str(exc)
                job.emit("error", f"Job failed: {exc}")
                job._finish(JobStatus.ERROR)

        threading.Thread(target=runner, name=f"job-{job.id}", daemon=True).start()


def stream_end() -> object:
    return _STREAM_END
