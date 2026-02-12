from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Callable

from sqlalchemy.orm import Session

from app import models
from app.job_queue import JobQueueService
from app.orchestration import AutopilotService
from app.providers import get_provider


class AutopilotJobWorker:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        poll_interval_sec: float = 2.0,
        stale_timeout_sec: float = 900.0,
        worker_id: str | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.poll_interval_sec = poll_interval_sec
        self.stale_timeout_sec = stale_timeout_sec
        self.worker_id = worker_id or f"worker-{socket.gethostname()}-{os.getpid()}"
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._metrics_lock = threading.Lock()
        self._stale_recovered_count = 0

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def stale_recovered_count(self) -> int:
        with self._metrics_lock:
            return self._stale_recovered_count

    def _record_stale_recovered(self, count: int) -> None:
        if count <= 0:
            return
        with self._metrics_lock:
            self._stale_recovered_count += count

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="autopilot-job-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._thread = None

    def run_once(self) -> bool:
        with self.session_factory() as db:
            queue = JobQueueService(db)
            recovered = queue.recover_stale_running_jobs(stale_timeout_sec=self.stale_timeout_sec)
            self._record_stale_recovered(recovered)

            job = queue.claim_next_job(worker_id=self.worker_id)
            if job is None:
                return recovered > 0

            project = db.get(models.Project, job.project_id)
            if project is None:
                queue.mark_failed(
                    job_id=job.id,
                    error_message=f"Project {job.project_id} not found",
                    retryable=False,
                )
                return True

            try:
                provider = get_provider(job.provider)
            except ValueError as exc:
                queue.mark_failed(job_id=job.id, error_message=str(exc), retryable=False)
                return True

            service = AutopilotService(db, project, provider=provider)
            try:
                prs, _reviews, merged_pr_ids = service.run_autopilot_cycle(max_items=job.max_items)
            except Exception as exc:
                queue.mark_failed(job_id=job.id, error_message=str(exc), retryable=True)
                return True

            queue.mark_completed(
                job_id=job.id,
                processed_items=len(prs),
                created_prs=len(prs),
                merged_pr_ids=merged_pr_ids,
            )
            return True

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            processed = self.run_once()
            if not processed:
                self._stop_event.wait(self.poll_interval_sec)
            else:
                time.sleep(0.05)
