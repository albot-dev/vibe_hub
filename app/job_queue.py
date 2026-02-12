from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, select, update
from sqlalchemy.orm import Session

from app import models


class JobQueueService:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    def enqueue_job(
        self,
        *,
        project_id: int,
        max_items: int,
        provider: str | None,
        requested_by: str,
        max_attempts: int,
    ) -> models.AutopilotJob:
        job = models.AutopilotJob(
            project_id=project_id,
            status=models.JobStatus.queued,
            max_items=max_items,
            provider=provider,
            requested_by=requested_by,
            max_attempts=max_attempts,
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def get_job(self, *, project_id: int, job_id: int) -> models.AutopilotJob | None:
        return self.db.scalar(
            select(models.AutopilotJob).where(
                models.AutopilotJob.id == job_id,
                models.AutopilotJob.project_id == project_id,
            )
        )

    def list_jobs(
        self,
        *,
        project_id: int,
        status: models.JobStatus | None,
        limit: int,
        offset: int,
    ) -> list[models.AutopilotJob]:
        stmt: Select[tuple[models.AutopilotJob]] = select(models.AutopilotJob).where(
            models.AutopilotJob.project_id == project_id,
        )
        if status is not None:
            stmt = stmt.where(models.AutopilotJob.status == status)

        return self.db.scalars(
            stmt.order_by(models.AutopilotJob.created_at.desc()).offset(offset).limit(limit)
        ).all()

    def cancel_job(self, *, project_id: int, job_id: int) -> models.AutopilotJob | None:
        job = self.get_job(project_id=project_id, job_id=job_id)
        if job is None:
            return None

        if job.status in {models.JobStatus.completed, models.JobStatus.failed, models.JobStatus.canceled}:
            return job

        now = self._now()
        job.status = models.JobStatus.canceled
        job.canceled_at = now
        job.finished_at = now
        job.updated_at = now
        self.db.commit()
        self.db.refresh(job)
        return job

    def retry_job(self, *, project_id: int, job_id: int) -> models.AutopilotJob | None:
        job = self.get_job(project_id=project_id, job_id=job_id)
        if job is None:
            return None

        if job.status not in {models.JobStatus.failed, models.JobStatus.canceled}:
            raise ValueError("Only failed or canceled jobs can be retried")

        now = self._now()
        rowcount = self.db.execute(
            update(models.AutopilotJob)
            .where(
                models.AutopilotJob.id == job_id,
                models.AutopilotJob.project_id == project_id,
                models.AutopilotJob.status.in_([models.JobStatus.failed, models.JobStatus.canceled]),
            )
            .values(
                status=models.JobStatus.queued,
                attempts=0,
                worker_id=None,
                started_at=None,
                finished_at=None,
                canceled_at=None,
                processed_items=0,
                created_prs=0,
                merged_prs=0,
                merged_pr_ids_json="[]",
                error_message="",
                updated_at=now,
            )
        ).rowcount
        if not rowcount:
            latest = self.get_job(project_id=project_id, job_id=job_id)
            if latest is None:
                return None
            raise ValueError("Only failed or canceled jobs can be retried")

        self.db.commit()
        return self.db.get(models.AutopilotJob, job_id)

    def recover_stale_running_jobs(self, *, stale_timeout_sec: float) -> int:
        if stale_timeout_sec <= 0:
            return 0

        now = self._now()
        threshold = now - timedelta(seconds=stale_timeout_sec)
        stale_error = (
            f"Recovered stale running job after exceeding timeout ({int(stale_timeout_sec)}s)"
        )[:3000]

        requeued_count = (
            self.db.execute(
                update(models.AutopilotJob)
                .where(
                    models.AutopilotJob.status == models.JobStatus.running,
                    models.AutopilotJob.started_at.is_not(None),
                    models.AutopilotJob.started_at <= threshold,
                    models.AutopilotJob.attempts < models.AutopilotJob.max_attempts,
                )
                .values(
                    status=models.JobStatus.queued,
                    worker_id=None,
                    started_at=None,
                    finished_at=None,
                    updated_at=now,
                    error_message=stale_error,
                )
            ).rowcount
            or 0
        )
        failed_count = (
            self.db.execute(
                update(models.AutopilotJob)
                .where(
                    models.AutopilotJob.status == models.JobStatus.running,
                    models.AutopilotJob.started_at.is_not(None),
                    models.AutopilotJob.started_at <= threshold,
                    models.AutopilotJob.attempts >= models.AutopilotJob.max_attempts,
                )
                .values(
                    status=models.JobStatus.failed,
                    worker_id=None,
                    finished_at=now,
                    updated_at=now,
                    error_message=stale_error,
                )
            ).rowcount
            or 0
        )

        recovered = requeued_count + failed_count
        if recovered:
            self.db.commit()
        return recovered

    def claim_next_job(self, *, worker_id: str) -> models.AutopilotJob | None:
        candidate = self.db.scalar(
            select(models.AutopilotJob)
            .where(models.AutopilotJob.status == models.JobStatus.queued)
            .order_by(models.AutopilotJob.created_at.asc())
            .limit(1)
        )
        if candidate is None:
            return None

        now = self._now()
        rowcount = self.db.execute(
            update(models.AutopilotJob)
            .where(
                models.AutopilotJob.id == candidate.id,
                models.AutopilotJob.status == models.JobStatus.queued,
            )
            .values(
                status=models.JobStatus.running,
                attempts=models.AutopilotJob.attempts + 1,
                worker_id=worker_id,
                started_at=now,
                updated_at=now,
                error_message="",
            )
        ).rowcount

        if not rowcount:
            self.db.rollback()
            return None

        self.db.commit()
        return self.db.get(models.AutopilotJob, candidate.id)

    def mark_completed(
        self,
        *,
        job_id: int,
        processed_items: int,
        created_prs: int,
        merged_pr_ids: list[int],
    ) -> models.AutopilotJob | None:
        job = self.db.get(models.AutopilotJob, job_id)
        if job is None:
            return None

        now = self._now()
        job.status = models.JobStatus.completed
        job.processed_items = processed_items
        job.created_prs = created_prs
        job.merged_prs = len(merged_pr_ids)
        job.merged_pr_ids_json = json.dumps(merged_pr_ids)
        job.finished_at = now
        job.updated_at = now
        job.error_message = ""
        self.db.commit()
        self.db.refresh(job)
        return job

    def mark_failed(
        self,
        *,
        job_id: int,
        error_message: str,
        retryable: bool,
    ) -> models.AutopilotJob | None:
        job = self.db.get(models.AutopilotJob, job_id)
        if job is None:
            return None

        now = self._now()
        safe_error = (error_message or "Job execution failed")[:3000]
        should_retry = retryable and job.attempts < job.max_attempts and job.status != models.JobStatus.canceled

        if should_retry:
            job.status = models.JobStatus.queued
            job.worker_id = None
            job.updated_at = now
            job.error_message = safe_error
        else:
            job.status = models.JobStatus.failed
            job.finished_at = now
            job.updated_at = now
            job.error_message = safe_error

        self.db.commit()
        self.db.refresh(job)
        return job
