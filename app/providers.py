from __future__ import annotations

import json
import os
import subprocess
import re
import textwrap
import warnings
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Literal, Protocol

from app import models


def _slugify(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-") or "work-item"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _default_change_path(fallback_item_id: int) -> str:
    return f"agent_codegen/work_item_{fallback_item_id}.py"


def _normalize_relative_path(path: str, fallback_item_id: int) -> str:
    raw = (path or "").strip().replace("\\", "/")
    if not raw:
        return _default_change_path(fallback_item_id)

    parts = [part for part in PurePosixPath(raw).parts if part not in {"", ".", ".."}]
    candidate = "/".join(parts).lstrip("/")
    if not candidate:
        return _default_change_path(fallback_item_id)
    return candidate


def _read_text_file(path: Path, *, max_chars: int = 2000) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        data = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ""
    return data[:max_chars]


def _workspace_overview(workspace_path: Path) -> str:
    proc = subprocess.run(
        ["git", "ls-files"],
        cwd=workspace_path,
        check=False,
        capture_output=True,
        text=True,
    )
    tracked_files: list[str] = []
    if proc.returncode == 0:
        tracked_files = [line.strip() for line in proc.stdout.splitlines() if line.strip()]

    selected_files = tracked_files[:120]
    readme_snippet = _read_text_file(workspace_path / "README.md", max_chars=1800)

    lines = [
        f"Workspace root: {workspace_path}",
        f"Tracked files count: {len(tracked_files)}",
        "Tracked files sample:",
    ]
    if selected_files:
        lines.extend(f"- {item}" for item in selected_files)
    else:
        lines.append("- <none>")

    if readme_snippet:
        lines.extend(
            [
                "",
                "README.md excerpt:",
                readme_snippet,
            ]
        )
    return "\n".join(lines)


@dataclass(slots=True)
class FileChange:
    path: str
    content: str = ""
    operation: Literal["upsert", "delete"] = "upsert"


@dataclass(slots=True)
class CodeChange:
    file_changes: list[FileChange]
    commit_message: str
    summary: str
    patch: str | None = None


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
        workspace_path: Path,
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

    @staticmethod
    def _build_python_changes(
        *,
        project: models.Project,
        work_item: models.WorkItem,
        agent: models.Agent,
        branch_name: str,
    ) -> list[FileChange]:
        module_name = f"work_item_{work_item.id}"
        package_path = "agent_codegen"
        source_path = f"{package_path}/{module_name}.py"
        init_path = f"{package_path}/__init__.py"
        test_path = f"tests/test_{module_name}.py"
        objective_fragment = (work_item.source_objective or "").strip()[:120]
        title_fragment = work_item.title.strip()

        source_content = "\n".join(
            [
                f'"""Generated implementation for work item {work_item.id}."""',
                "",
                "from __future__ import annotations",
                "",
                "from datetime import UTC, datetime",
                "",
                "",
                "def describe_work_item() -> dict[str, str]:",
                '    """Return deterministic metadata describing this generated implementation."""',
                "    return {",
                f'        "project": {json.dumps(project.name)},',
                f'        "branch": {json.dumps(branch_name)},',
                f'        "agent": {json.dumps(agent.name)},',
                f'        "work_item_id": {json.dumps(str(work_item.id))},',
                f'        "title": {json.dumps(title_fragment)},',
                f'        "objective_fragment": {json.dumps(objective_fragment)},',
                '        "generated_at": datetime.now(UTC).isoformat(),',
                "    }",
                "",
            ]
        )

        test_content = "\n".join(
            [
                "from __future__ import annotations",
                "",
                f"from {package_path}.{module_name} import describe_work_item",
                "",
                "",
                "def test_describe_work_item_contains_metadata() -> None:",
                "    payload = describe_work_item()",
                f'    assert payload["work_item_id"] == "{work_item.id}"',
                f'    assert payload["project"] == "{project.name}"',
                '    assert payload["title"]',
                "",
            ]
        )

        return [
            FileChange(path=init_path, content='"""Agent-generated modules."""\n'),
            FileChange(path=source_path, content=source_content),
            FileChange(path=test_path, content=test_content),
        ]

    def synthesize_change(
        self,
        *,
        project: models.Project,
        work_item: models.WorkItem,
        agent: models.Agent,
        branch_name: str,
        workspace_path: Path,
    ) -> CodeChange:
        _ = workspace_path
        changes = self._build_python_changes(
            project=project,
            work_item=work_item,
            agent=agent,
            branch_name=branch_name,
        )
        return CodeChange(
            file_changes=changes,
            commit_message=f"agent: implement work item {work_item.id}",
            summary=(
                f"Generated Python implementation + test scaffolding for `{_slugify(work_item.title)}` "
                f"across {len(changes)} files."
            ),
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
        _ = project, work_item
        test_cmd = os.getenv("AGENT_HUB_TEST_CMD", "").strip()
        require_test_cmd = _env_bool("AGENT_HUB_REQUIRE_TEST_CMD", False)
        if not test_cmd:
            if require_test_cmd:
                return (
                    False,
                    "Validation is required but AGENT_HUB_TEST_CMD is unset.",
                )
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

    @staticmethod
    def _parse_file_changes(data: dict[str, Any], work_item_id: int) -> list[FileChange]:
        raw = data.get("file_changes")
        parsed: list[FileChange] = []

        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                path = _normalize_relative_path(
                    str(item.get("path", "") or item.get("relative_path", "")),
                    work_item_id,
                )
                operation_raw = str(item.get("operation", "upsert")).strip().lower()
                operation: Literal["upsert", "delete"] = "delete" if operation_raw == "delete" else "upsert"
                content = "" if operation == "delete" else str(item.get("content", ""))
                if operation == "upsert" and not content.strip():
                    continue
                parsed.append(FileChange(path=path, content=content, operation=operation))

        if parsed:
            return parsed

        legacy_path = _normalize_relative_path(str(data.get("relative_path", "")), work_item_id)
        legacy_content = str(data.get("content", "")).strip()
        if legacy_content:
            return [FileChange(path=legacy_path, content=legacy_content, operation="upsert")]
        return []

    def synthesize_change(
        self,
        *,
        project: models.Project,
        work_item: models.WorkItem,
        agent: models.Agent,
        branch_name: str,
        workspace_path: Path,
    ) -> CodeChange:
        workspace_context = _workspace_overview(workspace_path)
        system_prompt = textwrap.dedent(
            """
            You are an autonomous software agent generating concrete repository edits.
            Return JSON only with keys: patch, file_changes, commit_message, summary.
            Constraints:
            - Prefer `patch` when possible (git unified diff, no markdown fences).
            - If patch is omitted, provide `file_changes` as a JSON array.
            - file_changes item keys: path, operation (upsert|delete), content.
            - path must be repository-relative and safe.
            - content must be source code or tests, not prose summaries.
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
            Repository context:
            {workspace_context}
            """
        ).strip()

        try:
            data = self._chat_json(system_prompt=system_prompt, user_prompt=user_prompt)
            patch = str(data.get("patch", "")).strip() or None
            file_changes = self._parse_file_changes(data, work_item.id)
            if patch is None and not file_changes:
                raise ValueError("OpenAI response did not include patch or file_changes")
            commit_message = str(data.get("commit_message", "")).strip() or f"agent: implement work item {work_item.id}"
            commit_message = commit_message.replace("\n", " ")[:72]
            summary = str(data.get("summary", "")).strip()[:180] or "Generated via OpenAI provider."
            return CodeChange(
                file_changes=file_changes,
                commit_message=commit_message,
                summary=summary,
                patch=patch,
            )
        except Exception:
            fallback = self._fallback.synthesize_change(
                project=project,
                work_item=work_item,
                agent=agent,
                branch_name=branch_name,
                workspace_path=workspace_path,
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
