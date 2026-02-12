from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.git_ops import GitError, GitWorkspaceManager
from app.providers import AgentProvider, get_provider


def _slugify(text: str, max_len: int = 36) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len] or "change"


class AutopilotService:
    """Lightweight orchestration loop for agent-native collaboration."""

    DEFAULT_AGENT_BLUEPRINTS: tuple[tuple[str, models.AgentRole, str], ...] = (
        ("Atlas Planner", models.AgentRole.planner, "Task decomposition, risk identification, roadmap updates"),
        ("Forge Coder", models.AgentRole.coder, "Code synthesis, refactors, implementation"),
        ("Sentinel Reviewer", models.AgentRole.reviewer, "Static review, design regression checks"),
        ("Probe Tester", models.AgentRole.tester, "Test strategy, smoke validation, release readiness"),
    )

    def __init__(
        self,
        db: Session,
        project: models.Project,
        *,
        provider: AgentProvider | None = None,
        workspace_root: Path | None = None,
    ):
        self.db = db
        self.project = project
        self.provider = provider or get_provider()
        self.git = GitWorkspaceManager(
            project_id=project.id,
            repo_url=project.repo_url,
            default_branch=project.default_branch,
            workspace_root=workspace_root,
        )

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(UTC)

    def _log_event(self, event_type: str, payload: dict) -> None:
        self.db.add(
            models.EventLog(
                project_id=self.project.id,
                event_type=event_type,
                payload_json=json.dumps(payload),
            )
        )

    def _get_policy(self) -> models.AutomationPolicy:
        if self.project.policy is None:
            policy = models.AutomationPolicy(project_id=self.project.id)
            self.db.add(policy)
            self.db.flush()
            self.project.policy = policy
        return self.project.policy

    def bootstrap(self) -> list[models.Agent]:
        existing_agents = list(self.project.agents)
        if existing_agents:
            return existing_agents

        created_agents: list[models.Agent] = []
        for name, role, capabilities in self.DEFAULT_AGENT_BLUEPRINTS:
            agent = models.Agent(
                project_id=self.project.id,
                name=name,
                role=role,
                capabilities=capabilities,
                status=models.AgentStatus.active,
            )
            self.db.add(agent)
            created_agents.append(agent)

        if self.project.policy is None:
            self.db.add(models.AutomationPolicy(project_id=self.project.id))

        self._log_event("project_bootstrapped", {"agent_count": len(created_agents)})
        self.db.commit()

        for agent in created_agents:
            self.db.refresh(agent)
        return created_agents

    def create_work_items_from_objective(
        self,
        objective: str,
        max_work_items: int,
        created_by: str = "system",
    ) -> list[models.WorkItem]:
        policy = self._get_policy()
        sentences = [segment.strip() for segment in re.split(r"[\n.;]+", objective) if segment.strip()]
        if not sentences:
            sentences = [objective.strip()]
        if not policy.auto_triage:
            sentences = [objective.strip()]

        capped_segments = sentences[:max_work_items]
        created: list[models.WorkItem] = []

        for idx, segment in enumerate(capped_segments, start=1):
            title_root = segment[:72]
            if idx == 1:
                title = f"Scope: {title_root}"
            else:
                title = f"Implement: {title_root}"
            item = models.WorkItem(
                project_id=self.project.id,
                title=title,
                description=(
                    f"Objective fragment: {segment}\n"
                    "Deliver code changes, tests, and docs through autonomous agent workflow."
                ),
                status=models.WorkItemStatus.backlog,
                priority=min(idx, 5),
                created_by=created_by,
                source_objective=objective,
            )
            self.db.add(item)
            created.append(item)

        self._log_event("objective_ingested", {"objective": objective, "created_items": len(created)})
        self.db.commit()

        for item in created:
            self.db.refresh(item)
        return created

    def _agents_by_role(self) -> dict[models.AgentRole, list[models.Agent]]:
        active_agents = self.db.scalars(
            select(models.Agent).where(
                models.Agent.project_id == self.project.id,
                models.Agent.status == models.AgentStatus.active,
            )
        ).all()

        grouped: dict[models.AgentRole, list[models.Agent]] = {role: [] for role in models.AgentRole}
        for agent in active_agents:
            grouped[agent.role].append(agent)
        return grouped

    def _pick_agent(
        self,
        grouped_agents: dict[models.AgentRole, list[models.Agent]],
        role: models.AgentRole,
    ) -> models.Agent | None:
        candidates = grouped_agents.get(role, [])
        return candidates[0] if candidates else None

    def _run_item(
        self,
        item: models.WorkItem,
        grouped_agents: dict[models.AgentRole, list[models.Agent]],
        policy: models.AutomationPolicy,
    ) -> tuple[models.PullRequest, list[models.Review], bool]:
        coder = item.assigned_agent
        if coder is None and policy.auto_assign:
            coder = self._pick_agent(grouped_agents, models.AgentRole.coder)
        if coder is None:
            raise RuntimeError("No active coder agent available.")

        item.assigned_agent_id = coder.id
        item.status = models.WorkItemStatus.in_progress

        branch = f"agent/{item.id}-{_slugify(item.title)}"
        change = self.provider.synthesize_change(
            project=self.project,
            work_item=item,
            agent=coder,
            branch_name=branch,
        )

        try:
            git_result = self.git.commit_agent_change(branch_name=branch, change=change)
        except GitError as exc:
            failed_run = models.AgentRun(
                project_id=self.project.id,
                work_item_id=item.id,
                agent_id=coder.id,
                status=models.RunStatus.failed,
                summary=f"Git-backed execution failed: {exc}",
                patch="",
                tests_passed=False,
            )
            self.db.add(failed_run)
            item.status = models.WorkItemStatus.backlog
            self._log_event(
                "work_item_failed",
                {
                    "work_item_id": item.id,
                    "error": str(exc),
                },
            )
            raise

        checks_passed, validation_summary = self.provider.run_validation(
            project=self.project,
            work_item=item,
            workspace_path=git_result.workspace_path,
        )

        run = models.AgentRun(
            project_id=self.project.id,
            work_item_id=item.id,
            agent_id=coder.id,
            status=models.RunStatus.completed,
            summary=(
                f"{coder.name} completed git-backed implementation for work item #{item.id}. "
                f"{change.summary} {validation_summary}"
            ),
            patch=git_result.diff,
            tests_passed=checks_passed,
        )
        self.db.add(run)

        pr = models.PullRequest(
            project_id=self.project.id,
            work_item_id=item.id,
            title=f"[agent] {item.title}",
            description=(
                "Autonomous agent delivery with real git branch and commit.\n\n"
                f"- branch: {branch}\n"
                f"- commit: {git_result.commit_sha}"
            ),
            source_branch=branch,
            target_branch=self.project.default_branch,
            status=models.PullRequestStatus.open,
            checks_passed=checks_passed,
            auto_merge=True,
            created_by_agent_id=coder.id,
        )
        self.db.add(pr)
        self.db.flush()

        reviews: list[models.Review] = []
        reviewer = self._pick_agent(grouped_agents, models.AgentRole.reviewer)
        tester = self._pick_agent(grouped_agents, models.AgentRole.tester)

        if policy.auto_review:
            if reviewer is not None:
                outcome = self.provider.review_pull_request(
                    project=self.project,
                    work_item=item,
                    role=models.AgentRole.reviewer,
                    checks_passed=checks_passed,
                )
                review = models.Review(
                    pull_request_id=pr.id,
                    agent_id=reviewer.id,
                    decision=outcome.decision,
                    comment=outcome.comment,
                )
                reviews.append(review)
                self.db.add(review)

            if tester is not None:
                outcome = self.provider.review_pull_request(
                    project=self.project,
                    work_item=item,
                    role=models.AgentRole.tester,
                    checks_passed=checks_passed,
                )
                review = models.Review(
                    pull_request_id=pr.id,
                    agent_id=tester.id,
                    decision=outcome.decision,
                    comment=outcome.comment,
                )
                reviews.append(review)
                self.db.add(review)
        else:
            self._log_event(
                "auto_review_disabled",
                {"pull_request_id": pr.id, "work_item_id": item.id},
            )

        approvals = sum(1 for review in reviews if review.decision == models.ReviewDecision.approve)
        merge_allowed = (
            policy.auto_merge
            and pr.auto_merge
            and approvals >= policy.min_review_approvals
            and (not policy.require_test_pass or pr.checks_passed)
        )

        if merge_allowed:
            try:
                merge_sha = self.git.merge_branch(branch_name=branch)
            except GitError as exc:
                item.status = models.WorkItemStatus.review
                merged = False
                self._log_event(
                    "pr_merge_failed",
                    {
                        "pull_request_id": pr.id,
                        "work_item_id": item.id,
                        "error": str(exc),
                    },
                )
            else:
                pr.status = models.PullRequestStatus.merged
                pr.merged_at = self._utc_now()
                item.status = models.WorkItemStatus.done
                item.completed_at = self._utc_now()
                merged = True
                pr.description = f"{pr.description}\n- merged_sha: {merge_sha}"
                self._log_event(
                    "pr_merged",
                    {
                        "pull_request_id": pr.id,
                        "work_item_id": item.id,
                        "approvals": approvals,
                        "merged_sha": merge_sha,
                    },
                )
        else:
            item.status = models.WorkItemStatus.review
            merged = False
            self._log_event(
                "pr_opened",
                {
                    "pull_request_id": pr.id,
                    "work_item_id": item.id,
                    "approvals": approvals,
                    "checks_passed": pr.checks_passed,
                },
            )

        return pr, reviews, merged

    def run_autopilot_cycle(self, max_items: int = 3) -> tuple[list[models.PullRequest], list[models.Review], list[int]]:
        grouped_agents = self._agents_by_role()
        policy = self._get_policy()

        backlog_items = self.db.scalars(
            select(models.WorkItem)
            .where(
                models.WorkItem.project_id == self.project.id,
                models.WorkItem.status == models.WorkItemStatus.backlog,
            )
            .order_by(models.WorkItem.priority.asc(), models.WorkItem.created_at.asc())
            .limit(max_items)
        ).all()

        created_prs: list[models.PullRequest] = []
        created_reviews: list[models.Review] = []
        merged_pr_ids: list[int] = []

        for item in backlog_items:
            if not policy.auto_assign and item.assigned_agent_id is None:
                self._log_event(
                    "work_item_skipped_unassigned",
                    {
                        "work_item_id": item.id,
                        "reason": "auto_assign disabled",
                    },
                )
                continue
            try:
                pr, reviews, merged = self._run_item(item, grouped_agents, policy)
            except GitError as exc:
                self._log_event(
                    "autopilot_item_failed",
                    {
                        "work_item_id": item.id,
                        "error": str(exc),
                    },
                )
                continue
            created_prs.append(pr)
            created_reviews.extend(reviews)
            if merged:
                merged_pr_ids.append(pr.id)

        self._log_event(
            "autopilot_cycle_completed",
            {
                "processed_items": len(backlog_items),
                "created_prs": len(created_prs),
                "merged_prs": len(merged_pr_ids),
            },
        )
        self.db.commit()

        for pr in created_prs:
            self.db.refresh(pr)
        for review in created_reviews:
            self.db.refresh(review)

        return created_prs, created_reviews, merged_pr_ids
