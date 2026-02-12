from __future__ import annotations

import subprocess
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.db import Base
from app.job_queue import JobQueueService
from app.job_worker import AutopilotJobWorker
from app.orchestration import AutopilotService


def _run(cmd: list[str], cwd: Path) -> str:
    proc = subprocess.run(cmd, cwd=cwd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(f"Command failed: {' '.join(cmd)}\n{proc.stderr.strip()}")
    return proc.stdout.strip()


def _create_local_repo(tmp_path: Path) -> str:
    remote_path = tmp_path / "remote.git"
    seed_path = tmp_path / "seed_repo"
    seed_path.mkdir(parents=True, exist_ok=True)

    _run(["git", "init", "--bare", str(remote_path)], cwd=tmp_path)
    _run(["git", "init", "-b", "main"], cwd=seed_path)
    _run(["git", "config", "user.name", "Test Bot"], cwd=seed_path)
    _run(["git", "config", "user.email", "test@example.local"], cwd=seed_path)
    (seed_path / "README.md").write_text("# Seed Repo\n", encoding="utf-8")
    _run(["git", "add", "README.md"], cwd=seed_path)
    _run(["git", "commit", "-m", "chore: init"], cwd=seed_path)
    _run(["git", "remote", "add", "origin", str(remote_path)], cwd=seed_path)
    _run(["git", "push", "-u", "origin", "main"], cwd=seed_path)
    return str(remote_path)


def _new_session_factory(tmp_path: Path):
    db_path = tmp_path / "test_jobs.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return SessionLocal


def _seed_project_and_agents(tmp_path: Path):
    session_factory = _new_session_factory(tmp_path)
    repo_url = _create_local_repo(tmp_path)

    with session_factory() as db:
        project = models.Project(name="queue-proj", repo_url=repo_url, default_branch="main")
        db.add(project)
        db.flush()
        service = AutopilotService(db, project)
        service.bootstrap()
        project_id = project.id

    return session_factory, project_id


def _seed_project(session_factory, *, name: str) -> int:
    with session_factory() as db:
        project = models.Project(name=name, repo_url="https://example.test/repo.git", default_branch="main")
        db.add(project)
        db.commit()
        db.refresh(project)
        return project.id


def test_job_queue_enqueue_claim_complete(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_HUB_WORKSPACES", str(tmp_path / "workspaces"))
    session_factory, project_id = _seed_project_and_agents(tmp_path)

    with session_factory() as db:
        queue = JobQueueService(db)
        job = queue.enqueue_job(
            project_id=project_id,
            max_items=2,
            provider=None,
            requested_by="tester",
            max_attempts=1,
        )
        assert job.status == models.JobStatus.queued

        claimed = queue.claim_next_job(worker_id="worker-a")
        assert claimed is not None
        assert claimed.status == models.JobStatus.running
        assert claimed.attempts == 1

        done = queue.mark_completed(
            job_id=claimed.id,
            processed_items=2,
            created_prs=2,
            merged_pr_ids=[1, 2],
        )
        assert done is not None
        assert done.status == models.JobStatus.completed
        assert done.merged_prs == 2


def test_job_worker_run_once_completes_job(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_HUB_WORKSPACES", str(tmp_path / "workspaces"))
    session_factory, project_id = _seed_project_and_agents(tmp_path)

    with session_factory() as db:
        service = AutopilotService(db, db.get(models.Project, project_id))
        service.create_work_items_from_objective(
            objective="Harden merge retry logic; Improve run summaries",
            max_work_items=2,
            created_by="system",
        )

        queue = JobQueueService(db)
        queue.enqueue_job(
            project_id=project_id,
            max_items=2,
            provider=None,
            requested_by="tester",
            max_attempts=1,
        )

    worker = AutopilotJobWorker(session_factory=session_factory, poll_interval_sec=0.01, worker_id="worker-test")
    assert worker.run_once() is True

    with session_factory() as db:
        jobs = db.query(models.AutopilotJob).all()
        assert len(jobs) == 1
        job = jobs[0]
        assert job.status == models.JobStatus.completed
        assert job.processed_items == 2
        assert job.created_prs == 2


def test_job_worker_marks_failed_for_invalid_provider(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_HUB_WORKSPACES", str(tmp_path / "workspaces"))
    session_factory, project_id = _seed_project_and_agents(tmp_path)

    with session_factory() as db:
        service = AutopilotService(db, db.get(models.Project, project_id))
        service.create_work_items_from_objective(
            objective="Ship provider override guardrails",
            max_work_items=1,
            created_by="system",
        )

        queue = JobQueueService(db)
        queue.enqueue_job(
            project_id=project_id,
            max_items=1,
            provider="bad-provider",
            requested_by="tester",
            max_attempts=1,
        )

    worker = AutopilotJobWorker(session_factory=session_factory, poll_interval_sec=0.01, worker_id="worker-test")
    assert worker.run_once() is True

    with session_factory() as db:
        job = db.query(models.AutopilotJob).one()
        assert job.status == models.JobStatus.failed
        assert "Unsupported provider" in job.error_message


def test_job_queue_retry_allows_failed_and_canceled_jobs(tmp_path: Path) -> None:
    session_factory = _new_session_factory(tmp_path)
    project_id = _seed_project(session_factory, name="queue-retry")

    with session_factory() as db:
        queue = JobQueueService(db)
        failed_job = queue.enqueue_job(
            project_id=project_id,
            max_items=1,
            provider=None,
            requested_by="tester",
            max_attempts=1,
        )
        claimed = queue.claim_next_job(worker_id="worker-a")
        assert claimed is not None
        queue.mark_failed(job_id=failed_job.id, error_message="boom", retryable=False)

        retried_failed = queue.retry_job(project_id=project_id, job_id=failed_job.id)
        assert retried_failed is not None
        assert retried_failed.status == models.JobStatus.queued
        assert retried_failed.attempts == 0
        assert retried_failed.worker_id is None
        assert retried_failed.finished_at is None
        assert retried_failed.canceled_at is None
        assert retried_failed.error_message == ""
        assert retried_failed.merged_pr_ids_json == "[]"

        canceled_job = queue.enqueue_job(
            project_id=project_id,
            max_items=1,
            provider=None,
            requested_by="tester",
            max_attempts=2,
        )
        queue.cancel_job(project_id=project_id, job_id=canceled_job.id)
        retried_canceled = queue.retry_job(project_id=project_id, job_id=canceled_job.id)
        assert retried_canceled is not None
        assert retried_canceled.status == models.JobStatus.queued
        assert retried_canceled.canceled_at is None


def test_job_queue_retry_rejects_non_terminal_status(tmp_path: Path) -> None:
    session_factory = _new_session_factory(tmp_path)
    project_id = _seed_project(session_factory, name="queue-retry-reject")

    with session_factory() as db:
        queue = JobQueueService(db)
        job = queue.enqueue_job(
            project_id=project_id,
            max_items=1,
            provider=None,
            requested_by="tester",
            max_attempts=1,
        )

        with pytest.raises(ValueError, match="Only failed or canceled jobs can be retried"):
            queue.retry_job(project_id=project_id, job_id=job.id)


def test_job_queue_recovers_stale_running_jobs(tmp_path: Path) -> None:
    session_factory = _new_session_factory(tmp_path)
    project_id = _seed_project(session_factory, name="queue-stale")

    with session_factory() as db:
        stale_started_at = models.utc_now() - timedelta(seconds=120)
        fresh_started_at = models.utc_now() - timedelta(seconds=10)
        retryable_stale = models.AutopilotJob(
            project_id=project_id,
            status=models.JobStatus.running,
            max_items=1,
            provider=None,
            requested_by="tester",
            attempts=1,
            max_attempts=3,
            worker_id="worker-old-a",
            started_at=stale_started_at,
        )
        terminal_stale = models.AutopilotJob(
            project_id=project_id,
            status=models.JobStatus.running,
            max_items=1,
            provider=None,
            requested_by="tester",
            attempts=2,
            max_attempts=2,
            worker_id="worker-old-b",
            started_at=stale_started_at,
        )
        fresh_running = models.AutopilotJob(
            project_id=project_id,
            status=models.JobStatus.running,
            max_items=1,
            provider=None,
            requested_by="tester",
            attempts=1,
            max_attempts=3,
            worker_id="worker-new",
            started_at=fresh_started_at,
        )
        db.add_all([retryable_stale, terminal_stale, fresh_running])
        db.commit()

        queue = JobQueueService(db)
        recovered = queue.recover_stale_running_jobs(stale_timeout_sec=60)
        assert recovered == 2

        db.refresh(retryable_stale)
        db.refresh(terminal_stale)
        db.refresh(fresh_running)

        assert retryable_stale.status == models.JobStatus.queued
        assert retryable_stale.worker_id is None
        assert retryable_stale.started_at is None
        assert "Recovered stale running job" in retryable_stale.error_message

        assert terminal_stale.status == models.JobStatus.failed
        assert terminal_stale.worker_id is None
        assert terminal_stale.finished_at is not None
        assert "Recovered stale running job" in terminal_stale.error_message

        assert fresh_running.status == models.JobStatus.running


def test_job_worker_run_once_recovers_stale_jobs(tmp_path: Path) -> None:
    session_factory = _new_session_factory(tmp_path)
    project_id = _seed_project(session_factory, name="queue-worker-stale")

    with session_factory() as db:
        stale_job = models.AutopilotJob(
            project_id=project_id,
            status=models.JobStatus.running,
            max_items=1,
            provider=None,
            requested_by="tester",
            attempts=1,
            max_attempts=1,
            worker_id="worker-old",
            started_at=models.utc_now() - timedelta(seconds=120),
        )
        db.add(stale_job)
        db.commit()
        db.refresh(stale_job)
        job_id = stale_job.id

    worker = AutopilotJobWorker(
        session_factory=session_factory,
        poll_interval_sec=0.01,
        stale_timeout_sec=60,
        worker_id="worker-test",
    )
    assert worker.run_once() is True
    assert worker.stale_recovered_count == 1

    with session_factory() as db:
        job = db.get(models.AutopilotJob, job_id)
        assert job is not None
        assert job.status == models.JobStatus.failed
        assert job.finished_at is not None
        assert "Recovered stale running job" in job.error_message


def test_job_worker_loop_recovers_from_run_once_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session_factory = _new_session_factory(tmp_path)
    worker = AutopilotJobWorker(
        session_factory=session_factory,
        poll_interval_sec=0.001,
        worker_id="worker-test",
    )

    calls = {"count": 0}

    def flaky_run_once() -> bool:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("boom")
        worker._stop_event.set()
        return False

    monkeypatch.setattr(worker, "run_once", flaky_run_once)

    worker._run_loop()

    assert calls["count"] == 2
    assert worker.loop_error_count == 1
