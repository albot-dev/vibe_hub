from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models import (
    AgentRole,
    AgentStatus,
    JobStatus,
    PullRequestStatus,
    RunStatus,
    ReviewDecision,
    WorkItemStatus,
)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    repo_url: str = Field(min_length=3, max_length=500)
    default_branch: str = Field(default="main", min_length=1, max_length=120)


class ProjectRead(BaseModel):
    id: int
    name: str
    repo_url: str
    default_branch: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    role: AgentRole
    status: AgentStatus = AgentStatus.active
    max_parallel_tasks: int = Field(default=2, ge=1, le=20)
    capabilities: str = ""


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    status: AgentStatus | None = None
    max_parallel_tasks: int | None = Field(default=None, ge=1, le=20)


class AgentRead(BaseModel):
    id: int
    project_id: int
    name: str
    role: AgentRole
    status: AgentStatus
    max_parallel_tasks: int
    capabilities: str

    model_config = {"from_attributes": True}


class BootstrapResponse(BaseModel):
    created_agents: list[AgentRead]


class ObjectiveCreate(BaseModel):
    objective: str = Field(min_length=10)
    max_work_items: int = Field(default=4, ge=1, le=12)
    created_by: str = Field(default="system")


class WorkItemRead(BaseModel):
    id: int
    project_id: int
    title: str
    description: str
    status: WorkItemStatus
    priority: int
    assigned_agent_id: int | None
    source_objective: str

    model_config = {"from_attributes": True}


class WorkItemAssignRequest(BaseModel):
    agent_id: int


class ObjectiveResponse(BaseModel):
    objective: str
    created_items: list[WorkItemRead]


class AutopilotRunRequest(BaseModel):
    max_items: int = Field(default=3, ge=1, le=20)
    provider: str | None = Field(default=None, description="Optional provider override, e.g. rule_based or openai")


class PullRequestRead(BaseModel):
    id: int
    project_id: int
    work_item_id: int | None
    title: str
    source_branch: str
    target_branch: str
    status: PullRequestStatus
    checks_passed: bool
    auto_merge: bool

    model_config = {"from_attributes": True}


class ReviewRead(BaseModel):
    id: int
    pull_request_id: int
    agent_id: int
    decision: ReviewDecision
    comment: str

    model_config = {"from_attributes": True}


class AgentRunRead(BaseModel):
    id: int
    project_id: int
    work_item_id: int
    agent_id: int
    status: RunStatus
    summary: str
    tests_passed: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AutopilotRunResponse(BaseModel):
    processed_items: int
    created_prs: list[PullRequestRead]
    reviews: list[ReviewRead]
    merged_pr_ids: list[int]


class AutopilotJobCreate(BaseModel):
    max_items: int = Field(default=3, ge=1, le=50)
    provider: str | None = Field(default=None)
    requested_by: str = Field(default="system")
    max_attempts: int = Field(default=1, ge=1, le=10)


class AutopilotJobRead(BaseModel):
    id: int
    project_id: int
    status: JobStatus
    max_items: int
    provider: str | None
    requested_by: str
    attempts: int
    max_attempts: int
    worker_id: str | None
    started_at: datetime | None
    finished_at: datetime | None
    canceled_at: datetime | None
    processed_items: int
    created_prs: int
    merged_prs: int
    merged_pr_ids_json: str
    error_message: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AccessTokenIssueRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=120)
    role: str = Field(default="maintainer")
    expires_in_seconds: int | None = Field(default=None, ge=1, le=60 * 60 * 24 * 30)


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PrincipalRead(BaseModel):
    subject: str
    role: str


class GitHubSyncRequest(BaseModel):
    issue_number: int | None = Field(default=None, ge=1)
    comment_body: str | None = None
    status_context: str = Field(default="agent-hub/autopilot")
    status_description: str = Field(default="Agent Hub autopilot sync")
    target_url: str | None = None


class GitHubSyncResponse(BaseModel):
    owner: str
    repo: str
    github_pr_number: int
    github_pr_url: str | None = None
    commit_status_state: str | None = None


class GitHubWebhookRepositoryOwner(BaseModel):
    login: str | None = None


class GitHubWebhookRepository(BaseModel):
    name: str | None = None
    full_name: str | None = None
    html_url: str | None = None
    clone_url: str | None = None
    ssh_url: str | None = None
    url: str | None = None
    owner: GitHubWebhookRepositoryOwner | None = None


class GitHubWebhookIssue(BaseModel):
    number: int = Field(ge=1)
    title: str = ""
    body: str | None = None
    html_url: str | None = None


class GitHubWebhookIssueComment(BaseModel):
    body: str = ""


class GitHubWebhookSender(BaseModel):
    login: str | None = None


class GitHubIssuesWebhookPayload(BaseModel):
    action: str
    repository: GitHubWebhookRepository
    issue: GitHubWebhookIssue
    sender: GitHubWebhookSender | None = None


class GitHubIssueCommentWebhookPayload(BaseModel):
    action: str
    repository: GitHubWebhookRepository
    issue: GitHubWebhookIssue
    comment: GitHubWebhookIssueComment
    sender: GitHubWebhookSender | None = None


GitHubWebhookAction = Literal["ignored", "objective_created", "job_enqueued", "no_project"]


class GitHubWebhookResponse(BaseModel):
    action: GitHubWebhookAction
    event: str
    project_id: int | None = None
    issue_number: int | None = None
    job_id: int | None = None
    objective: str | None = None
    reason: str | None = None


class DashboardResponse(BaseModel):
    project: ProjectRead
    agents: list[AgentRead]
    backlog_count: int
    in_progress_count: int
    done_count: int
    open_pr_count: int
    merged_pr_count: int


class EventRead(BaseModel):
    id: int
    project_id: int
    event_type: str
    payload_json: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AutomationPolicyRead(BaseModel):
    id: int
    project_id: int
    auto_triage: bool
    auto_assign: bool
    auto_review: bool
    auto_merge: bool
    min_review_approvals: int
    require_test_pass: bool

    model_config = {"from_attributes": True}


class AutomationPolicyRevisionRead(BaseModel):
    id: int
    project_id: int
    auto_triage: bool
    auto_assign: bool
    auto_review: bool
    auto_merge: bool
    min_review_approvals: int
    require_test_pass: bool
    changed_by: str
    change_reason: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AutomationPolicyUpdate(BaseModel):
    auto_triage: bool | None = None
    auto_assign: bool | None = None
    auto_review: bool | None = None
    auto_merge: bool | None = None
    min_review_approvals: int | None = Field(default=None, ge=1, le=10)
    require_test_pass: bool | None = None
    change_reason: str | None = Field(default=None, max_length=255)
