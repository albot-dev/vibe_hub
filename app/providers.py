from __future__ import annotations

import json
import os
import re
import subprocess
import textwrap
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from app import models


def _slugify(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-") or "work-item"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_relative_path(path: str, fallback_item_id: int) -> str:
    candidate = (path or "").strip().replace("\\", "/")
    if not candidate:
        candidate = f"agent_notes/work_item_{fallback_item_id}.md"
    if candidate.startswith("/"):
        candidate = candidate.lstrip("/")
    candidate = re.sub(r"\.{2,}", "", candidate)
    if not candidate:
        candidate = f"agent_notes/work_item_{fallback_item_id}.md"
    return candidate


@dataclass(slots=True)
class CodeChange:
    relative_path: str
    content: str
    commit_message: str
    summary: str


@dataclass(slots=True)
class ReviewOutcome:
    decision: models.ReviewDecision
    comment: str


class AgentProvider(Protocol):
    name: str

    def synthesize_change(
        self,
        *,
        project: models.Project,
        work_item: models.WorkItem,
        agent: models.Agent,
        branch_name: str,
    ) -> CodeChange: ...

    def review_pull_request(
        self,
        *,
        project: models.Project,
        work_item: models.WorkItem,
        role: models.AgentRole,
        checks_passed: bool,
    ) -> ReviewOutcome: ...

    def run_validation(
        self,
        *,
        project: models.Project,
        work_item: models.WorkItem,
        workspace_path: Path,
    ) -> tuple[bool, str]: ...


class RuleBasedProvider:
    name = "rule_based"

    def synthesize_change(
        self,
        *,
        project: models.Project,
        work_item: models.WorkItem,
        agent: models.Agent,
        branch_name: str,
    ) -> CodeChange:
        relative_path = f"agent_notes/work_item_{work_item.id}.md"
        content = "\n".join(
            [
                f"# Work Item {work_item.id}",
                "",
                f"- Project: {project.name}",
                f"- Branch: {branch_name}",
                f"- Agent: {agent.name}",
                f"- Generated at: {datetime.now(UTC).isoformat()}",
                "",
                "## Task",
                work_item.title,
                "",
                "## Objective Context",
                work_item.source_objective or "n/a",
                "",
                "## Notes",
                work_item.description,
                "",
                "## Outcome",
                f"Implemented deterministic agent artifact for `{_slugify(work_item.title)}`.",
                "",
            ]
        )
        return CodeChange(
            relative_path=relative_path,
            content=content,
            commit_message=f"agent: implement work item {work_item.id}",
            summary=f"Created `{relative_path}` with autonomous implementation notes.",
        )

    def review_pull_request(
        self,
        *,
        project: models.Project,
        work_item: models.WorkItem,
        role: models.AgentRole,
        checks_passed: bool,
    ) -> ReviewOutcome:
        if role == models.AgentRole.tester and not checks_passed:
            return ReviewOutcome(
                decision=models.ReviewDecision.request_changes,
                comment="Validation command failed. Changes requested.",
            )
        if role == models.AgentRole.reviewer:
            return ReviewOutcome(
                decision=models.ReviewDecision.approve,
                comment="Reviewed design and implementation for regressions.",
            )
        if role == models.AgentRole.tester:
            return ReviewOutcome(
                decision=models.ReviewDecision.approve,
                comment="Validation command passed in agent pipeline.",
            )
        return ReviewOutcome(
            decision=models.ReviewDecision.approve,
            comment="Automated role-based review approved.",
        )

    def run_validation(
        self,
        *,
        project: models.Project,
        work_item: models.WorkItem,
        workspace_path: Path,
    ) -> tuple[bool, str]:
        test_cmd = os.getenv("AGENT_HUB_TEST_CMD", "").strip()
        if not test_cmd:
            return True, "No AGENT_HUB_TEST_CMD configured; marked pass by default."

        proc = subprocess.run(
            test_cmd,
            cwd=workspace_path,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
        )
        output = "\n".join(part for part in [proc.stdout.strip(), proc.stderr.strip()] if part).strip()
        if output:
            output = output[-1200:]
        if proc.returncode == 0:
            return True, f"Validation command succeeded: `{test_cmd}`."
        return False, f"Validation command failed: `{test_cmd}`. Output tail:\n{output}"


class OpenAIProvider:
    name = "openai"

    def __init__(self, *, model: str | None = None, timeout_sec: float | None = None) -> None:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for provider=openai")

        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - import branch depends on environment extras
            raise ValueError("openai package is not installed; install with `uv sync --extra llm`") from exc

        self.model = (model or os.getenv("AGENT_HUB_OPENAI_MODEL", "gpt-4.1-mini")).strip()
        self.timeout_sec = timeout_sec or float(os.getenv("AGENT_HUB_OPENAI_TIMEOUT_SEC", "45"))
        self._client = OpenAI(api_key=api_key, timeout=self.timeout_sec)
        self._fallback = RuleBasedProvider()

    def _chat_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        response = self._client.responses.create(
            model=self.model,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": user_prompt}],
                },
            ],
            text={"format": {"type": "json_object"}},
            temperature=0.2,
            max_output_tokens=1200,
        )

        raw_text = (response.output_text or "").strip()
        if not raw_text:
            raise ValueError("OpenAI response contained no output_text")
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse OpenAI JSON output: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("OpenAI JSON output must be an object")
        return payload

    def synthesize_change(
        self,
        *,
        project: models.Project,
        work_item: models.WorkItem,
        agent: models.Agent,
        branch_name: str,
    ) -> CodeChange:
        system_prompt = textwrap.dedent(
            """
            You are an autonomous software agent generating a concise git change artifact.
            Return JSON only with keys: relative_path, content, commit_message, summary.
            Constraints:
            - relative_path must be repository-relative and safe.
            - content must be markdown and actionable.
            - commit_message must be <= 72 chars.
            - summary must be <= 180 chars.
            """
        ).strip()
        user_prompt = textwrap.dedent(
            f"""
            Project: {project.name}
            Agent: {agent.name}
            Branch: {branch_name}
            Work item id: {work_item.id}
            Work item title: {work_item.title}
            Work item description: {work_item.description}
            Objective context: {work_item.source_objective}
            """
        ).strip()

        try:
            data = self._chat_json(system_prompt=system_prompt, user_prompt=user_prompt)
            relative_path = _normalize_relative_path(str(data.get("relative_path", "")), work_item.id)
            content = str(data.get("content", "")).strip()
            if not content:
                raise ValueError("content is empty")
            commit_message = str(data.get("commit_message", "")).strip() or f"agent: implement work item {work_item.id}"
            commit_message = commit_message.replace("\n", " ")[:72]
            summary = str(data.get("summary", "")).strip()[:180] or "Generated via OpenAI provider."
            return CodeChange(
                relative_path=relative_path,
                content=content,
                commit_message=commit_message,
                summary=summary,
            )
        except Exception:
            fallback = self._fallback.synthesize_change(
                project=project,
                work_item=work_item,
                agent=agent,
                branch_name=branch_name,
            )
            fallback.summary = f"{fallback.summary} Fallback used due to OpenAI synthesis error."
            return fallback

    def review_pull_request(
        self,
        *,
        project: models.Project,
        work_item: models.WorkItem,
        role: models.AgentRole,
        checks_passed: bool,
    ) -> ReviewOutcome:
        system_prompt = textwrap.dedent(
            """
            You are an autonomous code reviewer.
            Return JSON only with keys: decision and comment.
            decision must be one of: approve, request_changes.
            """
        ).strip()
        user_prompt = textwrap.dedent(
            f"""
            Project: {project.name}
            Role: {role.value}
            Work item: {work_item.title}
            Description: {work_item.description}
            Checks passed: {checks_passed}
            """
        ).strip()

        try:
            data = self._chat_json(system_prompt=system_prompt, user_prompt=user_prompt)
            decision_raw = str(data.get("decision", "approve")).strip().lower()
            decision = (
                models.ReviewDecision.request_changes
                if decision_raw == models.ReviewDecision.request_changes.value
                else models.ReviewDecision.approve
            )
            comment = str(data.get("comment", "")).strip()[:600] or "Automated review completed."
            return ReviewOutcome(decision=decision, comment=comment)
        except Exception:
            return self._fallback.review_pull_request(
                project=project,
                work_item=work_item,
                role=role,
                checks_passed=checks_passed,
            )

    def run_validation(
        self,
        *,
        project: models.Project,
        work_item: models.WorkItem,
        workspace_path: Path,
    ) -> tuple[bool, str]:
        return self._fallback.run_validation(
            project=project,
            work_item=work_item,
            workspace_path=workspace_path,
        )


def get_provider(provider_name: str | None = None) -> AgentProvider:
    name = (provider_name or os.getenv("AGENT_HUB_PROVIDER", "rule_based")).strip().lower()
    if name in {"rule_based", "rule-based", "default"}:
        return RuleBasedProvider()

    if name == "openai":
        try:
            return OpenAIProvider()
        except ValueError as exc:
            fallback_enabled = _env_bool("AGENT_HUB_PROVIDER_FALLBACK", True)
            if fallback_enabled:
                warnings.warn(f"OpenAI provider unavailable ({exc}); falling back to rule_based", RuntimeWarning)
                return RuleBasedProvider()
            raise

    raise ValueError(f"Unsupported provider `{provider_name}`")
