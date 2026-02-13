from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any

from fastapi import HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import get_settings
from app.github_repo import canonical_repo_identity, extract_owner_repo, normalize_repo_locator
from app.job_queue import JobQueueService
from app.orchestration import AutopilotService


_AGENT_RUN_COMMAND = re.compile(r"(?mi)^\s*/agent run(?:\s+.*)?$")
_MAX_FAILURE_REASON_LENGTH = 300


def _bound_reason_message(message: str) -> str:
    normalized = " ".join(message.split())
    if len(normalized) <= _MAX_FAILURE_REASON_LENGTH:
        return normalized
    return normalized[: _MAX_FAILURE_REASON_LENGTH - 3].rstrip() + "..."


def _failure_reason_from_exception(error: Exception) -> str:
    if isinstance(error, HTTPException):
        detail = error.detail
        if isinstance(detail, str):
            message = detail
        elif detail is None:
            message = f"HTTP {error.status_code}"
        else:
            message = str(detail)
        fallback = f"HTTP {error.status_code}"
        return _bound_reason_message(message or fallback)

    message = str(error).strip()
    if message:
        return _bound_reason_message(f"{error.__class__.__name__}: {message}")
    return _bound_reason_message(error.__class__.__name__)


def _mark_delivery_failed(*, db: Session, delivery_id: int, error: Exception) -> None:
    delivery = db.get(models.GitHubWebhookDelivery, delivery_id)
    if delivery is None:
        return
    delivery.action = "failed"
    delivery.reason = _failure_reason_from_exception(error)
    db.commit()


def _enforce_payload_size_limit(raw_payload: bytes) -> None:
    max_payload_bytes = get_settings().github_webhook_max_payload_bytes
    payload_size = len(raw_payload)
    if payload_size > max_payload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Webhook payload exceeds max allowed size ({max_payload_bytes} bytes)",
        )


def _verify_signature_if_configured(raw_payload: bytes, signature_256: str | None) -> None:
    settings = get_settings()
    secret = settings.github_webhook_secret.strip()
    if not secret:
        return

    signature_header = (signature_256 or "").strip()
    if not signature_header:
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256 header")

    algo, separator, received_signature = signature_header.partition("=")
    if separator != "=" or algo.lower() != "sha256" or not received_signature:
        raise HTTPException(status_code=401, detail="Malformed X-Hub-Signature-256 header")

    expected_signature = hmac.new(
        secret.encode("utf-8"),
        raw_payload,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, received_signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


def _load_payload(raw_payload: bytes) -> dict[str, Any]:
    try:
        decoded = json.loads(raw_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Webhook body must be valid JSON")

    if not isinstance(decoded, dict):
        raise HTTPException(status_code=400, detail="Webhook body must be a JSON object")
    return decoded


def _collect_repository_identities(repository: schemas.GitHubWebhookRepository) -> set[tuple[str, str]]:
    identities: set[tuple[str, str]] = set()

    if repository.full_name and "/" in repository.full_name:
        owner, _, repo = repository.full_name.partition("/")
        if owner and repo:
            identities.add(canonical_repo_identity(owner, repo))

    owner_login = repository.owner.login if repository.owner is not None else None
    if owner_login and repository.name:
        identities.add(canonical_repo_identity(owner_login, repository.name))

    for candidate in _repository_url_candidates(repository):
        owner_repo = extract_owner_repo(candidate)
        if owner_repo is not None:
            identities.add(canonical_repo_identity(*owner_repo))

    return identities


def _repository_url_candidates(repository: schemas.GitHubWebhookRepository) -> tuple[str, ...]:
    return (
        repository.html_url or "",
        repository.clone_url or "",
        repository.ssh_url or "",
        repository.url or "",
    )


def _find_project_for_repository(
    db: Session,
    repository: schemas.GitHubWebhookRepository,
) -> models.Project | None:
    projects = db.scalars(select(models.Project)).all()
    if not projects:
        return None

    identities = _collect_repository_identities(repository)
    if identities:
        for project in projects:
            project_identity = extract_owner_repo(project.repo_url)
            if project_identity is None:
                continue
            if canonical_repo_identity(*project_identity) in identities:
                return project

    normalized_candidates = {
        normalize_repo_locator(candidate) for candidate in _repository_url_candidates(repository) if candidate
    }
    for project in projects:
        if normalize_repo_locator(project.repo_url) in normalized_candidates:
            return project

    return None


def _build_issue_objective(issue: schemas.GitHubWebhookIssue) -> str:
    title = issue.title.strip() or f"Issue {issue.number}"
    parts = [f"Resolve GitHub issue #{issue.number}: {title}"]
    description = (issue.body or "").strip()
    if description:
        parts.append(description)
    if issue.html_url:
        parts.append(f"Reference: {issue.html_url.strip()}")
    return "\n\n".join(parts)


def _auto_enqueue_enabled() -> bool:
    return bool(get_settings().github_webhook_auto_enqueue)


def _requested_by(sender: schemas.GitHubWebhookSender | None, fallback: str) -> str:
    login = (sender.login if sender is not None else "").strip()
    if login:
        return f"github:{login}"[:120]
    return fallback[:120]


def _handle_issues_event(db: Session, payload: dict[str, Any]) -> schemas.GitHubWebhookResponse:
    try:
        event = schemas.GitHubIssuesWebhookPayload.model_validate(payload)
    except ValidationError:
        raise HTTPException(status_code=400, detail="Invalid issues webhook payload")

    if event.action != "opened":
        return schemas.GitHubWebhookResponse(
            action="ignored",
            event="issues",
            issue_number=event.issue.number,
            reason=f"Unsupported issues action `{event.action}`",
        )

    project = _find_project_for_repository(db, event.repository)
    if project is None:
        return schemas.GitHubWebhookResponse(
            action="no_project",
            event="issues",
            issue_number=event.issue.number,
            reason="No matching project for repository",
        )

    objective = _build_issue_objective(event.issue)
    service = AutopilotService(db, project)
    service.create_work_items_from_objective(
        objective=objective,
        max_work_items=4,
        created_by="github:webhook",
    )

    if _auto_enqueue_enabled():
        job = JobQueueService(db).enqueue_job(
            project_id=project.id,
            max_items=3,
            provider=None,
            requested_by=_requested_by(event.sender, "github:webhook"),
            max_attempts=1,
        )
        return schemas.GitHubWebhookResponse(
            action="job_enqueued",
            event="issues",
            project_id=project.id,
            issue_number=event.issue.number,
            job_id=job.id,
            objective=objective,
        )

    return schemas.GitHubWebhookResponse(
        action="objective_created",
        event="issues",
        project_id=project.id,
        issue_number=event.issue.number,
        objective=objective,
    )


def _handle_issue_comment_event(db: Session, payload: dict[str, Any]) -> schemas.GitHubWebhookResponse:
    try:
        event = schemas.GitHubIssueCommentWebhookPayload.model_validate(payload)
    except ValidationError:
        raise HTTPException(status_code=400, detail="Invalid issue_comment webhook payload")

    if event.action != "created":
        return schemas.GitHubWebhookResponse(
            action="ignored",
            event="issue_comment",
            issue_number=event.issue.number,
            reason=f"Unsupported issue_comment action `{event.action}`",
        )

    body = event.comment.body or ""
    if not _AGENT_RUN_COMMAND.search(body):
        return schemas.GitHubWebhookResponse(
            action="ignored",
            event="issue_comment",
            issue_number=event.issue.number,
            reason="No supported command found",
        )

    project = _find_project_for_repository(db, event.repository)
    if project is None:
        return schemas.GitHubWebhookResponse(
            action="no_project",
            event="issue_comment",
            issue_number=event.issue.number,
            reason="No matching project for repository",
        )

    job = JobQueueService(db).enqueue_job(
        project_id=project.id,
        max_items=3,
        provider=None,
        requested_by=_requested_by(event.sender, "github:webhook"),
        max_attempts=1,
    )
    return schemas.GitHubWebhookResponse(
        action="job_enqueued",
        event="issue_comment",
        project_id=project.id,
        issue_number=event.issue.number,
        job_id=job.id,
    )


async def handle_github_webhook(
    *,
    request: Request,
    db: Session,
    github_event: str,
    delivery_id: str,
    signature_256: str | None,
) -> schemas.GitHubWebhookResponse:
    raw_payload = await request.body()
    _verify_signature_if_configured(raw_payload, signature_256)
    normalized_event = github_event.strip().lower()
    event_label = normalized_event or github_event

    normalized_delivery_id = delivery_id.strip()
    if not normalized_delivery_id:
        raise HTTPException(status_code=400, detail="Missing X-GitHub-Delivery header")

    delivery = models.GitHubWebhookDelivery(
        delivery_id=normalized_delivery_id,
        event=event_label,
        action="received",
    )
    db.add(delivery)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(models.GitHubWebhookDelivery).where(
                models.GitHubWebhookDelivery.delivery_id == normalized_delivery_id
            )
        )
        if existing is not None:
            existing.duplicate_count += 1
            db.commit()
        return schemas.GitHubWebhookResponse(
            action="ignored",
            event=event_label,
            reason="Duplicate delivery",
        )
    db.refresh(delivery)

    try:
        _enforce_payload_size_limit(raw_payload)
        payload = _load_payload(raw_payload)
        if normalized_event == "issues":
            response = _handle_issues_event(db, payload)
        elif normalized_event == "issue_comment":
            response = _handle_issue_comment_event(db, payload)
        else:
            response = schemas.GitHubWebhookResponse(
                action="ignored",
                event=event_label,
                reason="Unsupported event type",
            )
    except HTTPException as exc:
        db.rollback()
        _mark_delivery_failed(db=db, delivery_id=delivery.id, error=exc)
        raise
    except Exception as exc:
        db.rollback()
        _mark_delivery_failed(db=db, delivery_id=delivery.id, error=exc)
        raise

    delivery.event = response.event
    delivery.action = response.action
    delivery.project_id = response.project_id
    delivery.issue_number = response.issue_number
    delivery.job_id = response.job_id
    delivery.reason = response.reason or ""
    db.commit()

    return response
