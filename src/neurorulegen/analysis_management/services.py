"""Services for analysis management: PR analysis requests, forks, results, and token monitoring."""

import hashlib
import json
from collections.abc import Sequence
from datetime import date
from typing import Any
import uuid

from neurorulegen.ai_configuration.models import AIModel
from neurorulegen.ai_configuration.repository import (
    AIConfigurationRepository,
)
from neurorulegen.analysis_management.models import (
    AIAnalysis,
    AIFinding,
    DiffSide,
    PullRequest,
    PullRequestState,
)
from neurorulegen.analysis_management.repository import (
    AIAnalysisRepository,
    AIFindingRepository,
    PullRequestRepository,
)
from neurorulegen.common.enums import RunStatus
from neurorulegen.project_management.repository import (
    ProjectRepository,
)


class AnalysisError(Exception):
    """Base exception for analysis management errors."""


class AnalysisPermissionDeniedError(AnalysisError):
    """User does not have permission to view or run analyses."""


class AnalysisNotFoundError(AnalysisError):
    """Analysis or PR not found."""


class ModelNotConfiguredError(AnalysisError):
    """Credentials not configured for the chosen AI model."""


class AnalysisManagementService:
    def __init__(
        self,
        analysis_repo: AIAnalysisRepository,
        pr_repo: PullRequestRepository,
        finding_repo: AIFindingRepository,
        project_repo: ProjectRepository,
        ai_config_repo: AIConfigurationRepository,
    ) -> None:
        self.analysis_repo = analysis_repo
        self.pr_repo = pr_repo
        self.finding_repo = finding_repo
        self.project_repo = project_repo
        self.ai_config_repo = ai_config_repo

    async def _verify_project_member(self, project_id: int, user_id: int) -> None:
        project = await self.project_repo.get_project_by_id(project_id)
        if not project:
            raise AnalysisNotFoundError(f"Project #{project_id} not found.")
        is_member = await self.project_repo.is_user_project_member(project_id, user_id)
        if not is_member:
            raise AnalysisPermissionDeniedError("User is not a member of this project.")

    async def _verify_quality_engineer(self, project_id: int, user_id: int) -> None:
        project = await self.project_repo.get_project_by_id(project_id)
        if not project:
            raise AnalysisNotFoundError(f"Project #{project_id} not found.")
        if project.created_by_user_id != user_id:
            raise AnalysisPermissionDeniedError(
                "Only the Quality/Security Engineer can access token usage reports."
            )

    async def compute_config_hashes(self, project_id: int) -> tuple[bytes, bytes]:
        all_mcps = await self.ai_config_repo.get_mcp_servers(project_id)
        active_mcps = [s for s in all_mcps if s.enabled]
        all_skills = await self.ai_config_repo.get_agent_skills(project_id)
        active_skills = [s for s in all_skills if s.enabled]

        mcp_data = sorted(
            [
                {
                    "name": s.name,
                    "url": s.url,
                    "transport": s.transport.value,
                    "connection_config": s.connection_config_encrypted.hex(),
                }
                for s in active_mcps
            ],
            key=lambda x: x["name"],
        )
        skills_data = sorted(
            [{"name": s.name, "content": s.content} for s in active_skills],
            key=lambda x: x["name"],
        )

        mcp_hash = hashlib.sha256(json.dumps(mcp_data, sort_keys=True).encode()).digest()
        skills_hash = hashlib.sha256(json.dumps(skills_data, sort_keys=True).encode()).digest()
        return mcp_hash, skills_hash

    async def get_available_models(self, project_id: int) -> list[dict[str, Any]]:
        """Return AI models for which the project has valid provider credentials."""
        creds = await self.ai_config_repo.get_project_credentials(project_id)
        models_out: list[dict[str, Any]] = []
        for c in creds:
            provider_models = await self.ai_config_repo.get_models_for_provider(c.provider_id)
            for m in provider_models:
                models_out.append({
                    "id": m.id,
                    "name": m.model_identifier,
                    "provider": c.provider.name,
                    "provider_id": c.provider_id,
                })
        return models_out

    async def request_pr_analysis(
        self,
        project_id: int,
        user_id: int,
        pr_number: int,
        model_id: int,
        additional_instruction: str = "",
    ) -> AIAnalysis:
        """US-16: Request an AI Pull Request analysis."""
        await self._verify_project_member(project_id, user_id)

        # Verify model has credentials
        creds = await self.ai_config_repo.get_project_credentials(project_id)
        configured_provider_ids = {c.provider_id for c in creds}

        # Check model exists
        available = await self.get_available_models(project_id)
        chosen = next((m for m in available if m["id"] == model_id), None)
        if not chosen:
            raise ModelNotConfiguredError(
                f"Provider credentials for model ID #{model_id} are not configured in this project."
            )

        # Get or create PullRequest record
        pr = await self.pr_repo.get_or_create(
            project_id=project_id,
            github_pr_number=pr_number,
            title=f"Pull Request #{pr_number}",
            state=PullRequestState.OPEN,
        )

        project = await self.project_repo.get_project_by_id(project_id)
        base_prompt = "Review Python code quality, security vulnerabilities, and adherence to clean architecture."
        system_prompt = (
            f"{base_prompt}\n\nProject Additional Instructions:\n{project.additional_system_prompt or ''}\n\nUser Instruction:\n{additional_instruction}".strip()
        )

        mcp_hash, skills_hash = await self.compute_config_hashes(project_id)
        thread_id = f"analysis-{uuid.uuid4().hex}"

        analysis = await self.analysis_repo.create(
            pull_request_id=pr.id,
            started_by_user_id=user_id,
            model_id=model_id,
            base_commit_hash="",  # Populated by worker on fetch
            head_commit_hash="",  # Populated by worker on fetch
            system_prompt=system_prompt,
            langgraph_thread_id=thread_id,
            mcp_config_hash=mcp_hash,
            skills_config_hash=skills_hash,
            status=RunStatus.PENDING,
            continuation_instruction=additional_instruction or None,
        )
        return analysis

    async def create_fork(
        self,
        project_id: int,
        user_id: int,
        source_analysis_id: int,
        checkpoint_id: str,
        checkpoint_ns: str = "",
        instruction: str = "",
    ) -> tuple[AIAnalysis, bool]:
        """US-24: Fork an analysis from a checkpoint. Returns (new_analysis, config_has_drifted)."""
        await self._verify_project_member(project_id, user_id)
        source = await self.analysis_repo.get_by_id(source_analysis_id)
        if not source:
            raise AnalysisNotFoundError(f"Source analysis #{source_analysis_id} not found.")

        current_mcp_hash, current_skills_hash = await self.compute_config_hashes(project_id)
        config_has_drifted = (
            source.mcp_config_hash != current_mcp_hash
            or source.skills_config_hash != current_skills_hash
        )

        # Reuse same thread for checkpoint lineage or dedicated branch thread
        new_thread_id = source.langgraph_thread_id

        fork_analysis = await self.analysis_repo.create(
            pull_request_id=source.pull_request_id,
            started_by_user_id=user_id,
            model_id=source.model_id,
            base_commit_hash=source.base_commit_hash,
            head_commit_hash=source.head_commit_hash,
            system_prompt=source.system_prompt,
            langgraph_thread_id=new_thread_id,
            mcp_config_hash=current_mcp_hash,
            skills_config_hash=current_skills_hash,
            status=RunStatus.PENDING,
            source_analysis_id=source.id,
            source_checkpoint_ns=checkpoint_ns,
            source_checkpoint_id=checkpoint_id,
            continuation_instruction=instruction,
            diff=source.diff,
        )
        return fork_analysis, config_has_drifted

    async def get_analysis_result(
        self, project_id: int, user_id: int, analysis_id: int
    ) -> tuple[AIAnalysis, Sequence[AIFinding]]:
        """US-17: View code analysis result and findings."""
        await self._verify_project_member(project_id, user_id)
        analysis = await self.analysis_repo.get_with_findings(analysis_id)
        if not analysis:
            raise AnalysisNotFoundError(f"Analysis #{analysis_id} not found.")
        return analysis, analysis.findings

    async def get_token_usage_report(
        self,
        project_id: int,
        user_id: int,
        model_name: str,
        user_email: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        group_by: str | None = None,
    ) -> dict[str, Any]:
        """US-25: Token usage monitoring for Quality/Security Engineer."""
        await self._verify_quality_engineer(project_id, user_id)

        first = date.fromisoformat(start_date) if start_date else None
        last = date.fromisoformat(end_date) if end_date else None

        records = await self.analysis_repo.get_token_usage_records(
            project_id=project_id,
            model_name=model_name,
            user_email=user_email if user_email else None,
            start_date=first,
            end_date=last,
        )

        period = bool(first and last and first <= last)
        valid_group = group_by if period and group_by in ("day", "month") else ""

        grouped: dict[str, list[int]] = {}
        for record in records:
            r_date: date = record["date"]
            if valid_group == "month":
                key = r_date.isoformat()[:7]
            elif valid_group == "day":
                key = r_date.isoformat()
            else:
                key = "summary"

            grouped.setdefault(key, [0] * 5)
            grouped[key] = [
                a + b for a, b in zip(grouped[key], record["metrics"], strict=True)
            ]

        return {
            "model": model_name,
            "user": user_email or "",
            "start": start_date or "",
            "end": end_date or "",
            "group": valid_group,
            "metrics": [
                "Total input",
                "Total input cache read",
                "Total input short-term cache write",
                "Total input longer-term cache write",
                "Total output",
            ],
            "grouped": grouped,
        }
