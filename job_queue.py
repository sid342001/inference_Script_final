"""
Persistent job queue with retry and quarantine semantics.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

from .config_loader import QueueConfig
from .logging_setup import get_logger

logger = get_logger("job_queue")


@dataclass
class JobRecord:
    job_id: str
    image_path: str
    status: str = "pending"
    retries: int = 0
    max_retries: int = 3
    last_error: Optional[str] = None
    created_at: float = field(default_factory=lambda: time.time())
    updated_at: float = field(default_factory=lambda: time.time())
    payload: Dict = field(default_factory=dict)
    next_attempt_at: float = field(default_factory=lambda: time.time())

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "JobRecord":
        return cls(**data)


class JobQueue:
    def __init__(self, config: QueueConfig):
        self._config = config
        self._path = config.persistence_path
        self._lock = threading.Lock()
        self._jobs: Dict[str, JobRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            logger.info("Job state file %s does not exist. Starting with empty queue.", self._path)
            return
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:
            logger.error("Failed to load job queue from %s: %s", self._path, exc)
            return
        for item in data:
            record = JobRecord.from_dict(item)
            self._jobs[record.job_id] = record
        logger.info("Loaded %s jobs from %s", len(self._jobs), self._path)

    def _persist(self) -> None:
        with open(self._path, "w", encoding="utf-8") as handle:
            json.dump([job.to_dict() for job in self._jobs.values()], handle, indent=2)

    def enqueue(self, image_path: str, payload: Optional[Dict] = None) -> JobRecord:
        with self._lock:
            job_id = uuid.uuid4().hex
            record = JobRecord(
                job_id=job_id,
                image_path=image_path,
                status="pending",
                retries=0,
                max_retries=self._config.max_retries,
                payload=payload or {},
            )
            self._jobs[job_id] = record
            self._persist()
            logger.info("Enqueued job %s for %s", job_id, image_path)
            return record

    def _eligible_jobs(self) -> List[JobRecord]:
        now = time.time()
        pending = [job for job in self._jobs.values() if job.status == "pending" and job.next_attempt_at <= now]
        pending.sort(key=lambda job: job.created_at)
        return pending

    def reserve(self) -> Optional[JobRecord]:
        with self._lock:
            for job in self._eligible_jobs():
                job.status = "processing"
                job.updated_at = time.time()
                self._persist()
                logger.debug("Reserved job %s", job.job_id)
                return job
        return None

    def mark_complete(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = "completed"
            job.updated_at = time.time()
            self._persist()
            logger.info("Job %s completed", job_id)

    def mark_failed(self, job_id: str, error_message: str, *, requeue: bool) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.last_error = error_message
            job.updated_at = time.time()

            if requeue and job.retries < job.max_retries:
                job.retries += 1
                job.status = "pending"
                job.next_attempt_at = time.time() + self._config.retry_backoff_seconds
                logger.warning(
                    "Job %s failed (%s). Requeue attempt %s/%s after %ss",
                    job_id,
                    error_message,
                    job.retries,
                    job.max_retries,
                    self._config.retry_backoff_seconds,
                )
            else:
                job.status = "quarantined"
                self._quarantine(job)
                logger.error("Job %s moved to quarantine after failure: %s", job_id, error_message)
            self._persist()

    def _quarantine(self, job: JobRecord) -> None:
        quarantine = self._config.quarantine_dir / f"{job.job_id}.json"
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        with open(quarantine, "w", encoding="utf-8") as handle:
            json.dump(job.to_dict(), handle, indent=2)

    def in_progress(self) -> List[JobRecord]:
        with self._lock:
            return [job for job in self._jobs.values() if job.status == "processing"]

    def stats(self) -> Dict[str, int]:
        with self._lock:
            total = len(self._jobs)
            pending = sum(1 for job in self._jobs.values() if job.status == "pending")
            processing = sum(1 for job in self._jobs.values() if job.status == "processing")
            completed = sum(1 for job in self._jobs.values() if job.status == "completed")
            quarantined = sum(1 for job in self._jobs.values() if job.status == "quarantined")
            return {
                "total": total,
                "pending": pending,
                "processing": processing,
                "completed": completed,
                "quarantined": quarantined,
            }

