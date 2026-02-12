from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class AgentRole(str, Enum):
    planner = "planner"
    coder = "coder"
    reviewer = "reviewer"
    tester = "tester"


class AgentStatus(str, Enum):
    active = "active"
    paused = "paused"


class WorkItemStatus(str, Enum):
    backlog = "backlog"
    in_progress = "in_progress"
    review = "review"
    done = "done"


class RunStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class PullRequestStatus(str, Enum):
    open = "open"
    merged = "merged"
    closed = "closed"


class ReviewDecision(str, Enum):
    approve = "approve"
    request_changes = "request_changes"


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    canceled = "canceled"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    repo_url: Mapped[str] = mapped_column(String(500))
    default_branch: Mapped[str] = mapped_column(String(120), default="main")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    agents: Mapped[list[Agent]] = relationship(back_populates="project", cascade="all, delete-orphan")
    work_items: Mapped[list[WorkItem]] = relationship(back_populates="project", cascade="all, delete-orphan")
    pull_requests: Mapped[list[PullRequest]] = relationship(back_populates="project", cascade="all, delete-orphan")
    policy: Mapped[AutomationPolicy | None] = relationship(back_populates="project", uselist=False, cascade="all, delete-orphan")
    events: Mapped[list[EventLog]] = relationship(back_populates="project", cascade="all, delete-orphan")
    jobs: Mapped[list[AutopilotJob]] = relationship(back_populates="project", cascade="all, delete-orphan")


class AutomationPolicy(Base):
    __tablename__ = "automation_policies"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), unique=True, index=True)
    auto_triage: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_assign: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_review: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_merge: Mapped[bool] = mapped_column(Boolean, default=True)
    min_review_approvals: Mapped[int] = mapped_column(Integer, default=1)
    require_test_pass: Mapped[bool] = mapped_column(Boolean, default=True)

    project: Mapped[Project] = relationship(back_populates="policy")


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    role: Mapped[AgentRole] = mapped_column(SAEnum(AgentRole, native_enum=False), index=True)
    status: Mapped[AgentStatus] = mapped_column(SAEnum(AgentStatus, native_enum=False), default=AgentStatus.active)
    max_parallel_tasks: Mapped[int] = mapped_column(Integer, default=2)
    capabilities: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    project: Mapped[Project] = relationship(back_populates="agents")
    assigned_items: Mapped[list[WorkItem]] = relationship(back_populates="assigned_agent", foreign_keys="WorkItem.assigned_agent_id")
    runs: Mapped[list[AgentRun]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    prs_opened: Mapped[list[PullRequest]] = relationship(back_populates="created_by_agent", foreign_keys="PullRequest.created_by_agent_id")
    reviews: Mapped[list[Review]] = relationship(back_populates="agent", cascade="all, delete-orphan")


class WorkItem(Base):
    __tablename__ = "work_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[WorkItemStatus] = mapped_column(SAEnum(WorkItemStatus, native_enum=False), default=WorkItemStatus.backlog, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=3)
    created_by: Mapped[str] = mapped_column(String(80), default="system")
    assigned_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    source_objective: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped[Project] = relationship(back_populates="work_items")
    assigned_agent: Mapped[Agent | None] = relationship(back_populates="assigned_items", foreign_keys=[assigned_agent_id])
    runs: Mapped[list[AgentRun]] = relationship(back_populates="work_item", cascade="all, delete-orphan")
    prs: Mapped[list[PullRequest]] = relationship(back_populates="work_item", cascade="all, delete-orphan")


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    work_item_id: Mapped[int] = mapped_column(ForeignKey("work_items.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    status: Mapped[RunStatus] = mapped_column(SAEnum(RunStatus, native_enum=False), default=RunStatus.queued)
    summary: Mapped[str] = mapped_column(Text, default="")
    patch: Mapped[str] = mapped_column(Text, default="")
    tests_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    work_item: Mapped[WorkItem] = relationship(back_populates="runs")
    agent: Mapped[Agent] = relationship(back_populates="runs")


class PullRequest(Base):
    __tablename__ = "pull_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    work_item_id: Mapped[int | None] = mapped_column(ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    source_branch: Mapped[str] = mapped_column(String(120))
    target_branch: Mapped[str] = mapped_column(String(120), default="main")
    status: Mapped[PullRequestStatus] = mapped_column(SAEnum(PullRequestStatus, native_enum=False), default=PullRequestStatus.open, index=True)
    checks_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_merge: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    merged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped[Project] = relationship(back_populates="pull_requests")
    work_item: Mapped[WorkItem | None] = relationship(back_populates="prs")
    created_by_agent: Mapped[Agent | None] = relationship(back_populates="prs_opened", foreign_keys=[created_by_agent_id])
    reviews: Mapped[list[Review]] = relationship(back_populates="pull_request", cascade="all, delete-orphan")


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pull_request_id: Mapped[int] = mapped_column(ForeignKey("pull_requests.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    decision: Mapped[ReviewDecision] = mapped_column(SAEnum(ReviewDecision, native_enum=False), index=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    pull_request: Mapped[PullRequest] = relationship(back_populates="reviews")
    agent: Mapped[Agent] = relationship(back_populates="reviews")


class EventLog(Base):
    __tablename__ = "event_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    project: Mapped[Project] = relationship(back_populates="events")


class GitHubWebhookDelivery(Base):
    __tablename__ = "github_webhook_deliveries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    delivery_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    event: Mapped[str] = mapped_column(String(120), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class AutopilotJob(Base):
    __tablename__ = "autopilot_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    status: Mapped[JobStatus] = mapped_column(SAEnum(JobStatus, native_enum=False), default=JobStatus.queued, index=True)
    max_items: Mapped[int] = mapped_column(Integer, default=3)
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    requested_by: Mapped[str] = mapped_column(String(120), default="system")

    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)
    worker_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    processed_items: Mapped[int] = mapped_column(Integer, default=0)
    created_prs: Mapped[int] = mapped_column(Integer, default=0)
    merged_prs: Mapped[int] = mapped_column(Integer, default=0)
    merged_pr_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    error_message: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    project: Mapped[Project] = relationship(back_populates="jobs")
