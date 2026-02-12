from __future__ import annotations

import hmac
import ipaddress
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Header, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import (
    AuthConfigurationError,
    AuthPrincipal,
    Role,
    TokenExpiredError,
    TokenMalformedError,
    issue_access_token,
    verify_access_token,
)
from app.config import get_settings
from app.db import SessionLocal, get_session, init_db
from app.github_sync import GitHubAPIError, GitHubSyncAdapter, parse_github_repo
from app.github_webhooks import handle_github_webhook
from app.http_auth import extract_bearer_token
from app.job_queue import JobQueueService
from app.job_worker import AutopilotJobWorker
from app.orchestration import AutopilotService
from app.permissions import get_current_principal
from app.providers import get_provider
from app.rate_limit import InMemoryRateLimiter
from app.repo_security import normalize_and_validate_repo_url
from app.security import require_write_access

logger = logging.getLogger("agent_hub.api")
_rate_limiter: InMemoryRateLimiter | None = None
_rate_limiter_rpm: int | None = None
_job_worker: AutopilotJobWorker | None = None
_READ_AUTH_EXEMPT_PATH_PREFIXES = ("/docs", "/redoc", "/openapi.json")
_READ_AUTH_EXEMPT_PATHS = {
    "/health",
    "/health/live",
    "/health/ready",
    "/metrics",
}


def _validate_runtime_configuration(settings) -> None:
    safety_errors = settings.production_safety_errors()
    if not safety_errors:
        return

    for error in safety_errors:
        logger.error("unsafe_production_config error=%s", error)
    raise RuntimeError("Unsafe production configuration; see logs for details")


def _is_read_auth_exempt_path(path: str) -> bool:
    if path in _READ_AUTH_EXEMPT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in _READ_AUTH_EXEMPT_PATH_PREFIXES)


def _enforce_read_roles_if_enabled(request: Request, settings) -> JSONResponse | None:
    if request.method.upper() not in {"GET", "HEAD"}:
        return None
    if not settings.auth_require_reads:
        return None
    if _is_read_auth_exempt_path(request.url.path):
        return None

    token = extract_bearer_token(request.headers.get("Authorization"))
    if token is None:
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing bearer token"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        verify_access_token(token)
    except TokenExpiredError:
        return JSONResponse(
            status_code=401,
            content={"detail": "Token expired"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    except TokenMalformedError:
        return JSONResponse(
            status_code=401,
            content={"detail": "Malformed bearer token"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    except AuthConfigurationError as exc:
        return JSONResponse(status_code=500, content={"detail": str(exc)})
    return None


def _extract_client_ip_from_request(request: Request, settings) -> str:
    direct_client_ip = request.client.host if request.client else "unknown"

    if settings.rate_limit_trust_proxy_headers:
        trusted_proxies = settings.parsed_trusted_proxy_ips()
        if direct_client_ip not in trusted_proxies:
            return direct_client_ip

        x_forwarded_for = request.headers.get("X-Forwarded-For", "")
        if x_forwarded_for:
            candidate = x_forwarded_for.split(",")[0].strip()
            try:
                ipaddress.ip_address(candidate)
                return candidate
            except ValueError:
                logger.warning("Ignoring invalid X-Forwarded-For IP: %s", candidate)

        x_real_ip = request.headers.get("X-Real-IP", "").strip()
        if x_real_ip:
            try:
                ipaddress.ip_address(x_real_ip)
                return x_real_ip
            except ValueError:
                logger.warning("Ignoring invalid X-Real-IP value: %s", x_real_ip)

    return direct_client_ip


def _rate_limit_key_for_request(request: Request, settings) -> str:
    client_ip = _extract_client_ip_from_request(request, settings)
    return f"ip:{client_ip}"


def _enforce_metrics_token_if_enabled(*, settings, authorization: str | None) -> None:
    if not settings.metrics_require_token:
        return

    expected = settings.metrics_bearer_token.strip()
    if len(expected) < 24:
        raise HTTPException(status_code=500, detail="Metrics auth is enabled but token is not configured")

    token = extract_bearer_token(authorization)
    if token is None or not hmac.compare_digest(token, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing metrics bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global _job_worker

    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    _validate_runtime_configuration(settings)
    init_db()

    if settings.job_worker_enabled:
        _job_worker = AutopilotJobWorker(
            session_factory=SessionLocal,
            poll_interval_sec=settings.job_worker_poll_interval_sec,
            stale_timeout_sec=settings.job_stale_timeout_sec,
        )
        _job_worker.start()
        logger.info("Autopilot job worker started")

    logger.info("Agent Hub startup complete")
    try:
        yield
    finally:
        if _job_worker is not None:
            _job_worker.stop()
            logger.info("Autopilot job worker stopped")
        _job_worker = None


app = FastAPI(
    title="Agent Hub",
    version="0.2.0",
    description=(
        "GitHub-style collaboration platform designed for autonomous AI agents "
        "to plan, code, review, test, and merge with minimal user intervention."
    ),
    lifespan=lifespan,
)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    global _rate_limiter, _rate_limiter_rpm

    request_id = request.headers.get("X-Request-ID", "").strip() or uuid.uuid4().hex
    start = time.perf_counter()
    settings = get_settings()

    read_access_error = _enforce_read_roles_if_enabled(request, settings)
    if read_access_error is not None:
        read_access_error.headers["X-Request-ID"] = request_id
        return read_access_error

    if settings.rate_limit_enabled and request.method.upper() in {"POST", "PATCH", "PUT", "DELETE"}:
        if _rate_limiter is None or _rate_limiter_rpm != settings.rate_limit_requests_per_minute:
            _rate_limiter = InMemoryRateLimiter(
                requests_per_minute=settings.rate_limit_requests_per_minute,
            )
            _rate_limiter_rpm = settings.rate_limit_requests_per_minute

        rate_limit_key = _rate_limit_key_for_request(request, settings)
        decision = _rate_limiter.check(rate_limit_key)
        if not decision.allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={
                    "Retry-After": str(decision.retry_after_sec),
                    "X-Request-ID": request_id,
                },
            )

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (time.perf_counter() - start) * 1000.0
        logger.exception(
            "request_failed method=%s path=%s request_id=%s duration_ms=%.2f",
            request.method,
            request.url.path,
            request_id,
            duration_ms,
        )
        raise

    duration_ms = (time.perf_counter() - start) * 1000.0
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_completed method=%s path=%s status=%s request_id=%s duration_ms=%.2f",
        request.method,
        request.url.path,
        response.status_code,
        request_id,
        duration_ms,
    )
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "live"}


@app.get("/health/ready")
def health_ready(db: Session = Depends(get_session)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503, detail="Database not ready")
    return {"status": "ready"}


@app.post("/webhooks/github", response_model=schemas.GitHubWebhookResponse)
async def github_webhook(
    request: Request,
    x_github_event: str = Header(alias="X-GitHub-Event"),
    x_github_delivery: str = Header(alias="X-GitHub-Delivery"),
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    db: Session = Depends(get_session),
) -> schemas.GitHubWebhookResponse:
    return await handle_github_webhook(
        request=request,
        db=db,
        github_event=x_github_event,
        delivery_id=x_github_delivery,
        signature_256=x_hub_signature_256,
    )


@app.get("/metrics", response_class=PlainTextResponse)
def metrics(
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_session),
) -> str:
    _enforce_metrics_token_if_enabled(settings=get_settings(), authorization=authorization)

    project_count = int(db.scalar(select(func.count()).select_from(models.Project)) or 0)
    backlog_count = int(
        db.scalar(
            select(func.count())
            .select_from(models.WorkItem)
            .where(models.WorkItem.status == models.WorkItemStatus.backlog)
        )
        or 0
    )
    in_progress_count = int(
        db.scalar(
            select(func.count())
            .select_from(models.WorkItem)
            .where(
                models.WorkItem.status.in_([
                    models.WorkItemStatus.in_progress,
                    models.WorkItemStatus.review,
                ])
            )
        )
        or 0
    )
    done_count = int(
        db.scalar(
            select(func.count())
            .select_from(models.WorkItem)
            .where(models.WorkItem.status == models.WorkItemStatus.done)
        )
        or 0
    )
    open_pr_count = int(
        db.scalar(
            select(func.count())
            .select_from(models.PullRequest)
            .where(models.PullRequest.status == models.PullRequestStatus.open)
        )
        or 0
    )
    merged_pr_count = int(
        db.scalar(
            select(func.count())
            .select_from(models.PullRequest)
            .where(models.PullRequest.status == models.PullRequestStatus.merged)
        )
        or 0
    )
    queued_job_count = int(
        db.scalar(
            select(func.count())
            .select_from(models.AutopilotJob)
            .where(models.AutopilotJob.status == models.JobStatus.queued)
        )
        or 0
    )
    running_job_count = int(
        db.scalar(
            select(func.count())
            .select_from(models.AutopilotJob)
            .where(models.AutopilotJob.status == models.JobStatus.running)
        )
        or 0
    )
    completed_job_count = int(
        db.scalar(
            select(func.count())
            .select_from(models.AutopilotJob)
            .where(models.AutopilotJob.status == models.JobStatus.completed)
        )
        or 0
    )
    failed_job_count = int(
        db.scalar(
            select(func.count())
            .select_from(models.AutopilotJob)
            .where(models.AutopilotJob.status == models.JobStatus.failed)
        )
        or 0
    )
    stale_recovered_count = _job_worker.stale_recovered_count if _job_worker is not None else 0
    worker_loop_error_count = _job_worker.loop_error_count if _job_worker is not None else 0

    lines = [
        "# HELP agent_hub_projects_total Total number of projects",
        "# TYPE agent_hub_projects_total gauge",
        f"agent_hub_projects_total {project_count}",
        "# HELP agent_hub_work_items_backlog Total backlog work items",
        "# TYPE agent_hub_work_items_backlog gauge",
        f"agent_hub_work_items_backlog {backlog_count}",
        "# HELP agent_hub_work_items_in_progress Total in-progress/review work items",
        "# TYPE agent_hub_work_items_in_progress gauge",
        f"agent_hub_work_items_in_progress {in_progress_count}",
        "# HELP agent_hub_work_items_done Total completed work items",
        "# TYPE agent_hub_work_items_done gauge",
        f"agent_hub_work_items_done {done_count}",
        "# HELP agent_hub_pull_requests_open Total open pull requests",
        "# TYPE agent_hub_pull_requests_open gauge",
        f"agent_hub_pull_requests_open {open_pr_count}",
        "# HELP agent_hub_pull_requests_merged Total merged pull requests",
        "# TYPE agent_hub_pull_requests_merged gauge",
        f"agent_hub_pull_requests_merged {merged_pr_count}",
        "# HELP agent_hub_autopilot_jobs_queued Total queued autopilot jobs",
        "# TYPE agent_hub_autopilot_jobs_queued gauge",
        f"agent_hub_autopilot_jobs_queued {queued_job_count}",
        "# HELP agent_hub_autopilot_jobs_running Total running autopilot jobs",
        "# TYPE agent_hub_autopilot_jobs_running gauge",
        f"agent_hub_autopilot_jobs_running {running_job_count}",
        "# HELP agent_hub_autopilot_jobs_completed Total completed autopilot jobs",
        "# TYPE agent_hub_autopilot_jobs_completed gauge",
        f"agent_hub_autopilot_jobs_completed {completed_job_count}",
        "# HELP agent_hub_autopilot_jobs_failed Total failed autopilot jobs",
        "# TYPE agent_hub_autopilot_jobs_failed gauge",
        f"agent_hub_autopilot_jobs_failed {failed_job_count}",
        "# HELP agent_hub_autopilot_jobs_stale_recovered_total Total stale running jobs recovered by worker",
        "# TYPE agent_hub_autopilot_jobs_stale_recovered_total counter",
        f"agent_hub_autopilot_jobs_stale_recovered_total {stale_recovered_count}",
        "# HELP agent_hub_autopilot_job_worker_loop_errors_total Total uncaught worker loop errors",
        "# TYPE agent_hub_autopilot_job_worker_loop_errors_total counter",
        f"agent_hub_autopilot_job_worker_loop_errors_total {worker_loop_error_count}",
    ]
    return "\n".join(lines) + "\n"



def _get_project_or_404(db: Session, project_id: int) -> models.Project:
    project = db.get(models.Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project



def _ensure_project_policy(db: Session, project: models.Project) -> models.AutomationPolicy:
    if project.policy is not None:
        return project.policy

    policy = models.AutomationPolicy(project_id=project.id)
    db.add(policy)
    db.flush()
    db.refresh(policy)
    return policy



def _bounded_limit(limit: int | None) -> int:
    settings = get_settings()
    requested = limit if limit is not None else settings.default_page_size
    return min(requested, settings.max_page_size)


def _get_job_queue(db: Session) -> JobQueueService:
    return JobQueueService(db)


def _extract_pr_metadata_value(description: str, key: str) -> str | None:
    for raw_line in description.splitlines():
        line = raw_line.strip()
        prefix = f"- {key}:"
        if line.lower().startswith(prefix):
            value = line[len(prefix) :].strip()
            return value or None
    return None


def _enforce_write_roles_if_enabled(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    settings = get_settings()
    if not settings.auth_require_roles:
        return

    token = extract_bearer_token(authorization)
    if token is None:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    try:
        principal = verify_access_token(token)
    except TokenExpiredError:
        raise HTTPException(status_code=401, detail="Token expired")
    except TokenMalformedError:
        raise HTTPException(status_code=401, detail="Malformed bearer token")
    except AuthConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    if not principal.has_any_role(Role.maintainer, Role.admin):
        raise HTTPException(status_code=403, detail="Insufficient role. Requires one of: maintainer, admin")


@app.post("/auth/token", response_model=schemas.AccessTokenResponse)
def issue_token(
    payload: schemas.AccessTokenIssueRequest,
    _: None = Depends(require_write_access),
) -> schemas.AccessTokenResponse:
    settings = get_settings()
    if not settings.require_api_key:
        raise HTTPException(
            status_code=403,
            detail="Token issuance requires AGENT_HUB_REQUIRE_API_KEY=1 for bootstrap safety",
        )

    try:
        role = Role(payload.role)
        token = issue_access_token(
            AuthPrincipal(subject=payload.subject, role=role),
            expires_in_seconds=payload.expires_in_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except AuthConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return schemas.AccessTokenResponse(access_token=token)


@app.get("/auth/me", response_model=schemas.PrincipalRead)
def auth_me(
    principal: AuthPrincipal = Depends(get_current_principal()),
) -> schemas.PrincipalRead:
    return schemas.PrincipalRead(subject=principal.subject, role=principal.role.value)


@app.post("/projects", response_model=schemas.ProjectRead)
def create_project(
    payload: schemas.ProjectCreate,
    db: Session = Depends(get_session),
    _: None = Depends(require_write_access),
    __: None = Depends(_enforce_write_roles_if_enabled),
) -> models.Project:
    settings = get_settings()
    try:
        normalized_repo_url = normalize_and_validate_repo_url(payload.repo_url, settings)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    project = models.Project(
        name=payload.name,
        repo_url=normalized_repo_url,
        default_branch=payload.default_branch,
    )
    db.add(project)

    try:
        db.flush()
        db.add(models.AutomationPolicy(project_id=project.id))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Project name already exists")

    db.refresh(project)
    return project


@app.get("/projects", response_model=list[schemas.ProjectRead])
def list_projects(
    limit: int | None = Query(default=None, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_session),
) -> list[models.Project]:
    bounded_limit = _bounded_limit(limit)
    return db.scalars(
        select(models.Project)
        .order_by(models.Project.created_at.desc())
        .offset(offset)
        .limit(bounded_limit)
    ).all()


@app.get("/projects/{project_id}/agents", response_model=list[schemas.AgentRead])
def list_agents(
    project_id: int,
    limit: int | None = Query(default=None, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_session),
) -> list[models.Agent]:
    _get_project_or_404(db, project_id)
    return db.scalars(
        select(models.Agent)
        .where(models.Agent.project_id == project_id)
        .order_by(models.Agent.role.asc(), models.Agent.created_at.asc())
        .offset(offset)
        .limit(_bounded_limit(limit))
    ).all()


@app.post("/projects/{project_id}/agents", response_model=schemas.AgentRead)
def create_agent(
    project_id: int,
    payload: schemas.AgentCreate,
    db: Session = Depends(get_session),
    _: None = Depends(require_write_access),
    __: None = Depends(_enforce_write_roles_if_enabled),
) -> models.Agent:
    project = _get_project_or_404(db, project_id)
    agent = models.Agent(
        project_id=project.id,
        name=payload.name,
        role=payload.role,
        status=payload.status,
        max_parallel_tasks=payload.max_parallel_tasks,
        capabilities=payload.capabilities,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


@app.patch("/projects/{project_id}/agents/{agent_id}", response_model=schemas.AgentRead)
def update_agent(
    project_id: int,
    agent_id: int,
    payload: schemas.AgentUpdate,
    db: Session = Depends(get_session),
    _: None = Depends(require_write_access),
    __: None = Depends(_enforce_write_roles_if_enabled),
) -> models.Agent:
    _get_project_or_404(db, project_id)
    agent = db.get(models.Agent, agent_id)
    if agent is None or agent.project_id != project_id:
        raise HTTPException(status_code=404, detail="Agent not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(agent, field, value)

    db.commit()
    db.refresh(agent)
    return agent


@app.post("/projects/{project_id}/bootstrap", response_model=schemas.BootstrapResponse)
def bootstrap_project(
    project_id: int,
    db: Session = Depends(get_session),
    _: None = Depends(require_write_access),
    __: None = Depends(_enforce_write_roles_if_enabled),
) -> schemas.BootstrapResponse:
    project = _get_project_or_404(db, project_id)
    service = AutopilotService(db, project)
    agents = service.bootstrap()
    return schemas.BootstrapResponse(created_agents=agents)


@app.post("/projects/{project_id}/objectives", response_model=schemas.ObjectiveResponse)
def create_objective(
    project_id: int,
    payload: schemas.ObjectiveCreate,
    db: Session = Depends(get_session),
    _: None = Depends(require_write_access),
    __: None = Depends(_enforce_write_roles_if_enabled),
) -> schemas.ObjectiveResponse:
    project = _get_project_or_404(db, project_id)
    service = AutopilotService(db, project)
    created_items = service.create_work_items_from_objective(
        objective=payload.objective,
        max_work_items=payload.max_work_items,
        created_by=payload.created_by,
    )
    return schemas.ObjectiveResponse(objective=payload.objective, created_items=created_items)


@app.get("/projects/{project_id}/work-items", response_model=list[schemas.WorkItemRead])
def list_work_items(
    project_id: int,
    status: models.WorkItemStatus | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_session),
) -> list[models.WorkItem]:
    _get_project_or_404(db, project_id)

    stmt = select(models.WorkItem).where(models.WorkItem.project_id == project_id)
    if status is not None:
        stmt = stmt.where(models.WorkItem.status == status)

    return db.scalars(
        stmt.order_by(models.WorkItem.priority.asc(), models.WorkItem.created_at.asc())
        .offset(offset)
        .limit(_bounded_limit(limit))
    ).all()


@app.patch("/projects/{project_id}/work-items/{work_item_id}/assign", response_model=schemas.WorkItemRead)
def assign_work_item(
    project_id: int,
    work_item_id: int,
    payload: schemas.WorkItemAssignRequest,
    db: Session = Depends(get_session),
    _: None = Depends(require_write_access),
    __: None = Depends(_enforce_write_roles_if_enabled),
) -> models.WorkItem:
    _get_project_or_404(db, project_id)
    work_item = db.get(models.WorkItem, work_item_id)
    if work_item is None or work_item.project_id != project_id:
        raise HTTPException(status_code=404, detail="Work item not found")

    agent = db.get(models.Agent, payload.agent_id)
    if agent is None or agent.project_id != project_id:
        raise HTTPException(status_code=404, detail="Agent not found for this project")

    work_item.assigned_agent_id = agent.id
    db.commit()
    db.refresh(work_item)
    return work_item


@app.post("/projects/{project_id}/autopilot/run", response_model=schemas.AutopilotRunResponse)
def run_autopilot(
    project_id: int,
    payload: schemas.AutopilotRunRequest,
    db: Session = Depends(get_session),
    _: None = Depends(require_write_access),
    __: None = Depends(_enforce_write_roles_if_enabled),
) -> schemas.AutopilotRunResponse:
    project = _get_project_or_404(db, project_id)

    try:
        provider = get_provider(payload.provider)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    service = AutopilotService(db, project, provider=provider)
    prs, reviews, merged_pr_ids = service.run_autopilot_cycle(max_items=payload.max_items)

    return schemas.AutopilotRunResponse(
        processed_items=len(prs),
        created_prs=prs,
        reviews=reviews,
        merged_pr_ids=merged_pr_ids,
    )


@app.post("/projects/{project_id}/jobs/autopilot", response_model=schemas.AutopilotJobRead)
def enqueue_autopilot_job(
    project_id: int,
    payload: schemas.AutopilotJobCreate,
    db: Session = Depends(get_session),
    _: None = Depends(require_write_access),
    __: None = Depends(_enforce_write_roles_if_enabled),
) -> models.AutopilotJob:
    _get_project_or_404(db, project_id)
    queue = _get_job_queue(db)
    return queue.enqueue_job(
        project_id=project_id,
        max_items=payload.max_items,
        provider=payload.provider,
        requested_by=payload.requested_by,
        max_attempts=payload.max_attempts,
    )


@app.get("/projects/{project_id}/jobs", response_model=list[schemas.AutopilotJobRead])
def list_autopilot_jobs(
    project_id: int,
    status: models.JobStatus | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_session),
) -> list[models.AutopilotJob]:
    _get_project_or_404(db, project_id)
    queue = _get_job_queue(db)
    return queue.list_jobs(
        project_id=project_id,
        status=status,
        limit=_bounded_limit(limit),
        offset=offset,
    )


@app.get("/projects/{project_id}/jobs/{job_id}", response_model=schemas.AutopilotJobRead)
def get_autopilot_job(
    project_id: int,
    job_id: int,
    db: Session = Depends(get_session),
) -> models.AutopilotJob:
    _get_project_or_404(db, project_id)
    queue = _get_job_queue(db)
    job = queue.get_job(project_id=project_id, job_id=job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/projects/{project_id}/jobs/{job_id}/cancel", response_model=schemas.AutopilotJobRead)
def cancel_autopilot_job(
    project_id: int,
    job_id: int,
    db: Session = Depends(get_session),
    _: None = Depends(require_write_access),
    __: None = Depends(_enforce_write_roles_if_enabled),
) -> models.AutopilotJob:
    _get_project_or_404(db, project_id)
    queue = _get_job_queue(db)
    job = queue.cancel_job(project_id=project_id, job_id=job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/projects/{project_id}/jobs/{job_id}/retry", response_model=schemas.AutopilotJobRead)
def retry_autopilot_job(
    project_id: int,
    job_id: int,
    db: Session = Depends(get_session),
    _: None = Depends(require_write_access),
    __: None = Depends(_enforce_write_roles_if_enabled),
) -> models.AutopilotJob:
    _get_project_or_404(db, project_id)
    queue = _get_job_queue(db)
    try:
        job = queue.retry_job(project_id=project_id, job_id=job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/projects/{project_id}/policy", response_model=schemas.AutomationPolicyRead)
def get_automation_policy(project_id: int, db: Session = Depends(get_session)) -> models.AutomationPolicy:
    project = _get_project_or_404(db, project_id)
    policy = _ensure_project_policy(db, project)
    db.commit()
    db.refresh(policy)
    return policy


@app.patch("/projects/{project_id}/policy", response_model=schemas.AutomationPolicyRead)
def update_automation_policy(
    project_id: int,
    payload: schemas.AutomationPolicyUpdate,
    db: Session = Depends(get_session),
    _: None = Depends(require_write_access),
    __: None = Depends(_enforce_write_roles_if_enabled),
) -> models.AutomationPolicy:
    project = _get_project_or_404(db, project_id)
    policy = _ensure_project_policy(db, project)
    updates = payload.model_dump(exclude_none=True)
    for field, value in updates.items():
        setattr(policy, field, value)

    db.commit()
    db.refresh(policy)
    return policy


@app.get("/projects/{project_id}/pull-requests", response_model=list[schemas.PullRequestRead])
def list_pull_requests(
    project_id: int,
    status: models.PullRequestStatus | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_session),
) -> list[models.PullRequest]:
    _get_project_or_404(db, project_id)

    stmt = select(models.PullRequest).where(models.PullRequest.project_id == project_id)
    if status is not None:
        stmt = stmt.where(models.PullRequest.status == status)

    return db.scalars(
        stmt.order_by(models.PullRequest.created_at.desc())
        .offset(offset)
        .limit(_bounded_limit(limit))
    ).all()


@app.post(
    "/projects/{project_id}/pull-requests/{pull_request_id}/github/sync",
    response_model=schemas.GitHubSyncResponse,
)
def sync_pull_request_to_github(
    project_id: int,
    pull_request_id: int,
    payload: schemas.GitHubSyncRequest,
    db: Session = Depends(get_session),
    _: None = Depends(require_write_access),
    __: None = Depends(_enforce_write_roles_if_enabled),
) -> schemas.GitHubSyncResponse:
    project = _get_project_or_404(db, project_id)
    pull_request = db.get(models.PullRequest, pull_request_id)
    if pull_request is None or pull_request.project_id != project_id:
        raise HTTPException(status_code=404, detail="Pull request not found")

    try:
        owner, repo = parse_github_repo(project.repo_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        with GitHubSyncAdapter() as github:
            created = github.create_pull_request(
                owner=owner,
                repo=repo,
                head=pull_request.source_branch,
                base=pull_request.target_branch,
                title=pull_request.title,
                body=pull_request.description,
            )
            commit_state: str | None = None

            if payload.issue_number is not None and payload.comment_body:
                github.create_issue_comment(
                    owner=owner,
                    repo=repo,
                    issue_number=payload.issue_number,
                    body=payload.comment_body,
                )

            commit_sha = _extract_pr_metadata_value(pull_request.description, "merged_sha") or _extract_pr_metadata_value(
                pull_request.description,
                "commit",
            )
            if commit_sha:
                status_payload = github.set_commit_status(
                    owner=owner,
                    repo=repo,
                    sha=commit_sha,
                    state="success" if pull_request.status == models.PullRequestStatus.merged else "pending",
                    context=payload.status_context,
                    description=payload.status_description,
                    target_url=payload.target_url,
                )
                commit_state = str(status_payload.get("state", ""))

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except GitHubAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return schemas.GitHubSyncResponse(
        owner=owner,
        repo=repo,
        github_pr_number=int(created.get("number", 0)),
        github_pr_url=str(created.get("html_url", "")) or None,
        commit_status_state=commit_state,
    )


@app.get("/projects/{project_id}/runs", response_model=list[schemas.AgentRunRead])
def list_runs(
    project_id: int,
    status: models.RunStatus | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_session),
) -> list[models.AgentRun]:
    _get_project_or_404(db, project_id)

    stmt = select(models.AgentRun).where(models.AgentRun.project_id == project_id)
    if status is not None:
        stmt = stmt.where(models.AgentRun.status == status)

    return db.scalars(
        stmt.order_by(models.AgentRun.created_at.desc())
        .offset(offset)
        .limit(_bounded_limit(limit))
    ).all()


@app.get("/projects/{project_id}/dashboard", response_model=schemas.DashboardResponse)
def project_dashboard(project_id: int, db: Session = Depends(get_session)) -> schemas.DashboardResponse:
    project = _get_project_or_404(db, project_id)

    agents = db.scalars(
        select(models.Agent)
        .where(models.Agent.project_id == project_id)
        .order_by(models.Agent.role.asc(), models.Agent.created_at.asc())
    ).all()

    backlog_count = db.scalar(
        select(func.count())
        .select_from(models.WorkItem)
        .where(
            models.WorkItem.project_id == project_id,
            models.WorkItem.status == models.WorkItemStatus.backlog,
        )
    )
    in_progress_count = db.scalar(
        select(func.count())
        .select_from(models.WorkItem)
        .where(
            models.WorkItem.project_id == project_id,
            models.WorkItem.status.in_([
                models.WorkItemStatus.in_progress,
                models.WorkItemStatus.review,
            ]),
        )
    )
    done_count = db.scalar(
        select(func.count())
        .select_from(models.WorkItem)
        .where(
            models.WorkItem.project_id == project_id,
            models.WorkItem.status == models.WorkItemStatus.done,
        )
    )

    open_pr_count = db.scalar(
        select(func.count())
        .select_from(models.PullRequest)
        .where(
            models.PullRequest.project_id == project_id,
            models.PullRequest.status == models.PullRequestStatus.open,
        )
    )
    merged_pr_count = db.scalar(
        select(func.count())
        .select_from(models.PullRequest)
        .where(
            models.PullRequest.project_id == project_id,
            models.PullRequest.status == models.PullRequestStatus.merged,
        )
    )

    return schemas.DashboardResponse(
        project=project,
        agents=agents,
        backlog_count=int(backlog_count or 0),
        in_progress_count=int(in_progress_count or 0),
        done_count=int(done_count or 0),
        open_pr_count=int(open_pr_count or 0),
        merged_pr_count=int(merged_pr_count or 0),
    )


@app.get("/projects/{project_id}/events", response_model=list[schemas.EventRead])
def list_events(
    project_id: int,
    limit: int | None = Query(default=None, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_session),
) -> list[models.EventLog]:
    _get_project_or_404(db, project_id)
    return db.scalars(
        select(models.EventLog)
        .where(models.EventLog.project_id == project_id)
        .order_by(models.EventLog.created_at.desc())
        .offset(offset)
        .limit(_bounded_limit(limit))
    ).all()
