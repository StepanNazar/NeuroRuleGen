"""Repository abstractions and SQLAlchemy implementation for analysis management."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import (
    BigInteger,
    case,
    cast,
    desc,
    func,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from neurorulegen.analysis_management.models import (
    AIAnalysis,
    AIFinding,
    DiffSide,
    PullRequest,
    PullRequestState,
)
from neurorulegen.common.enums import RunStatus
from neurorulegen.rule_management.models import RuleGeneration


class PullRequestRepository(ABC):
    @abstractmethod
    async def get_by_project_and_pr_number(
        self, project_id: int, pr_number: int
    ) -> PullRequest | None:
        pass

    @abstractmethod
    async def get_or_create(
        self,
        project_id: int,
        github_pr_number: int,
        title: str,
        state: PullRequestState = PullRequestState.OPEN,
    ) -> PullRequest:
        pass


class AIAnalysisRepository(ABC):
    @abstractmethod
    async def get_by_id(self, analysis_id: int) -> AIAnalysis | None:
        pass

    @abstractmethod
    async def get_with_findings(self, analysis_id: int) -> AIAnalysis | None:
        pass

    @abstractmethod
    async def list_by_project(
        self,
        project_id: int,
        offset: int = 0,
        limit: int = 10,
    ) -> Sequence[AIAnalysis]:
        pass

    @abstractmethod
    async def count_by_project(self, project_id: int) -> int:
        pass

    @abstractmethod
    async def create(
        self,
        pull_request_id: int,
        started_by_user_id: int,
        model_id: int,
        base_commit_hash: str,
        head_commit_hash: str,
        system_prompt: str,
        langgraph_thread_id: str,
        mcp_config_hash: bytes,
        skills_config_hash: bytes,
        status: RunStatus = RunStatus.PENDING,
        source_analysis_id: int | None = None,
        source_checkpoint_ns: str | None = None,
        source_checkpoint_id: str | None = None,
        continuation_instruction: str | None = None,
        diff: str | None = None,
    ) -> AIAnalysis:
        pass

    @abstractmethod
    async def claim_next_pending(self) -> AIAnalysis | None:
        pass

    @abstractmethod
    async def update_status_and_metadata(
        self,
        analysis_id: int,
        status: RunStatus,
        error_message: str | None = None,
        diff: str | None = None,
        base_commit_hash: str | None = None,
        head_commit_hash: str | None = None,
    ) -> None:
        pass

    @abstractmethod
    async def update_token_usage(
        self,
        analysis_id: int,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int = 0,
        cache_write_input_tokens: int = 0,
        cache_write_input_tokens_long_ttl: int = 0,
    ) -> None:
        pass

    @abstractmethod
    async def get_token_usage_records(
        self,
        project_id: int,
        model_name: str,
        user_email: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        pass


    @abstractmethod
    async def recover_stale_running(self) -> int:
        pass


class AIFindingRepository(ABC):
    @abstractmethod
    async def create(
        self,
        ai_analysis_id: int,
        description: str,
        file_path: str,
        diff_side: DiffSide,
        start_line: int,
        end_line: int,
    ) -> AIFinding:
        pass

    @abstractmethod
    async def list_by_analysis(self, analysis_id: int) -> Sequence[AIFinding]:
        pass


class SQLAlchemyPullRequestRepository(PullRequestRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_project_and_pr_number(
        self, project_id: int, pr_number: int
    ) -> PullRequest | None:
        stmt = select(PullRequest).where(
            PullRequest.project_id == project_id,
            PullRequest.github_pr_number == pr_number,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_or_create(
        self,
        project_id: int,
        github_pr_number: int,
        title: str,
        state: PullRequestState = PullRequestState.OPEN,
    ) -> PullRequest:
        pr = await self.get_by_project_and_pr_number(project_id, github_pr_number)
        if pr is not None:
            if pr.title != title or pr.state != state:
                pr.title = title
                pr.state = state
                await self.session.flush()
            return pr

        pr = PullRequest(
            project_id=project_id,
            github_pr_number=github_pr_number,
            title=title,
            state=state,
        )
        self.session.add(pr)
        await self.session.flush()
        return pr


class SQLAlchemyAIAnalysisRepository(AIAnalysisRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, analysis_id: int) -> AIAnalysis | None:
        stmt = (
            select(AIAnalysis)
            .options(
                selectinload(AIAnalysis.pull_request).selectinload(PullRequest.project),
                selectinload(AIAnalysis.model).selectinload(AIModel.provider),
                selectinload(AIAnalysis.started_by_user),
            )
            .where(AIAnalysis.id == analysis_id)
        )
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def get_with_findings(self, analysis_id: int) -> AIAnalysis | None:
        stmt = (
            select(AIAnalysis)
            .options(
                selectinload(AIAnalysis.pull_request),
                selectinload(AIAnalysis.model),
                selectinload(AIAnalysis.started_by_user),
                selectinload(AIAnalysis.findings),
            )
            .where(AIAnalysis.id == analysis_id)
        )
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def list_by_project(
        self,
        project_id: int,
        offset: int = 0,
        limit: int = 10,
    ) -> Sequence[AIAnalysis]:
        stmt = (
            select(AIAnalysis)
            .join(PullRequest)
            .options(
                selectinload(AIAnalysis.pull_request),
                selectinload(AIAnalysis.model),
                selectinload(AIAnalysis.started_by_user),
            )
            .where(PullRequest.project_id == project_id)
            .order_by(desc(AIAnalysis.created_at))
            .offset(offset)
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def count_by_project(self, project_id: int) -> int:
        stmt = (
            select(func.count(AIAnalysis.id))
            .join(PullRequest)
            .where(PullRequest.project_id == project_id)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one()

    async def create(
        self,
        pull_request_id: int,
        started_by_user_id: int,
        model_id: int,
        base_commit_hash: str,
        head_commit_hash: str,
        system_prompt: str,
        langgraph_thread_id: str,
        mcp_config_hash: bytes,
        skills_config_hash: bytes,
        status: RunStatus = RunStatus.PENDING,
        source_analysis_id: int | None = None,
        source_checkpoint_ns: str | None = None,
        source_checkpoint_id: str | None = None,
        continuation_instruction: str | None = None,
        diff: str | None = None,
    ) -> AIAnalysis:
        analysis = AIAnalysis(
            pull_request_id=pull_request_id,
            started_by_user_id=started_by_user_id,
            model_id=model_id,
            status=status,
            base_commit_hash=base_commit_hash,
            head_commit_hash=head_commit_hash,
            system_prompt=system_prompt,
            langgraph_thread_id=langgraph_thread_id,
            source_analysis_id=source_analysis_id,
            source_checkpoint_ns=source_checkpoint_ns,
            source_checkpoint_id=source_checkpoint_id,
            continuation_instruction=continuation_instruction,
            mcp_config_hash=mcp_config_hash,
            skills_config_hash=skills_config_hash,
            diff=diff,
        )
        self.session.add(analysis)
        await self.session.flush()
        return analysis

    async def claim_next_pending(self) -> AIAnalysis | None:
        """Atomically find and claim the next pending analysis task."""
        # Find oldest pending
        subq = (
            select(AIAnalysis.id)
            .where(AIAnalysis.status == RunStatus.PENDING)
            .order_by(AIAnalysis.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        stmt = (
            update(AIAnalysis)
            .where(AIAnalysis.id == subq)
            .values(status=RunStatus.RUNNING)
            .returning(AIAnalysis.id)
        )
        res = await self.session.execute(stmt)
        claimed_id = res.scalar_one_or_none()
        if claimed_id is None:
            return None
        await self.session.commit()
        return await self.get_by_id(claimed_id)

    async def update_status_and_metadata(
        self,
        analysis_id: int,
        status: RunStatus,
        error_message: str | None = None,
        diff: str | None = None,
        base_commit_hash: str | None = None,
        head_commit_hash: str | None = None,
    ) -> None:
        values: dict[str, Any] = {"status": status}
        if error_message is not None:
            values["error_message"] = error_message
        if diff is not None:
            values["diff"] = diff
        if base_commit_hash is not None:
            values["base_commit_hash"] = base_commit_hash
        if head_commit_hash is not None:
            values["head_commit_hash"] = head_commit_hash

        stmt = update(AIAnalysis).where(AIAnalysis.id == analysis_id).values(**values)
        await self.session.execute(stmt)
        await self.session.commit()

    async def update_token_usage(
        self,
        analysis_id: int,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int = 0,
        cache_write_input_tokens: int = 0,
        cache_write_input_tokens_long_ttl: int = 0,
    ) -> None:
        stmt = (
            update(AIAnalysis)
            .where(AIAnalysis.id == analysis_id)
            .values(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=cached_input_tokens,
                cache_write_input_tokens=cache_write_input_tokens,
                cache_write_input_tokens_long_ttl=cache_write_input_tokens_long_ttl,
            )
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def get_token_usage_records(
        self,
        project_id: int,
        model_name: str,
        user_email: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """
        Aggregate token usage records from ai_analyses and rule_generations.
        Returns a list of dicts: {'date': date, 'user': email, 'model': model, 'metrics': [...]}
        """
        records: list[dict[str, Any]] = []

        # 1. ai_analyses query
        stmt_ai = (
            select(
                func.date(AIAnalysis.created_at).label("d"),
                AIAnalysis.started_by_user,
                AIAnalysis.model,
                func.sum(AIAnalysis.input_tokens).label("in_tok"),
                func.sum(AIAnalysis.cached_input_tokens).label("cache_read"),
                func.sum(AIAnalysis.cache_write_input_tokens).label("cache_write"),
                func.sum(AIAnalysis.cache_write_input_tokens_long_ttl).label("cache_write_long"),
                func.sum(AIAnalysis.output_tokens).label("out_tok"),
            )
            .join(PullRequest, AIAnalysis.pull_request_id == PullRequest.id)
            .options(
                selectinload(AIAnalysis.started_by_user),
                selectinload(AIAnalysis.model),
            )
            .where(PullRequest.project_id == project_id)
            .group_by(
                func.date(AIAnalysis.created_at),
                AIAnalysis.started_by_user_id,
                AIAnalysis.model_id,
            )
        )
        # 2. rule_generations query
        stmt_rg = (
            select(
                func.date(RuleGeneration.created_at).label("d"),
                RuleGeneration.started_by_user,
                RuleGeneration.model,
                func.sum(RuleGeneration.input_tokens).label("in_tok"),
                func.sum(RuleGeneration.cached_input_tokens).label("cache_read"),
                func.sum(RuleGeneration.cache_write_input_tokens).label("cache_write"),
                func.sum(RuleGeneration.cache_write_input_tokens_long_ttl).label("cache_write_long"),
                func.sum(RuleGeneration.output_tokens).label("out_tok"),
            )
            .options(
                selectinload(RuleGeneration.started_by_user),
                selectinload(RuleGeneration.model),
            )
            .where(RuleGeneration.project_id == project_id)
            .group_by(
                func.date(RuleGeneration.created_at),
                RuleGeneration.started_by_user_id,
                RuleGeneration.model_id,
            )
        )

        res_ai = await self.session.execute(stmt_ai)
        for row in res_ai.all():
            d, user, model, in_tok, c_read, c_write, c_write_l, out_tok = row
            if model and model.model_identifier == model_name:
                u_email = user.email if user else ""
                if not user_email or u_email == user_email:
                    if (not start_date or d >= start_date) and (not end_date or d <= end_date):
                        records.append({
                            "date": d,
                            "user": u_email,
                            "model": model.model_identifier,
                            "metrics": [
                                int(in_tok or 0),
                                int(c_read or 0),
                                int(c_write or 0),
                                int(c_write_l or 0),
                                int(out_tok or 0),
                            ],
                        })

        res_rg = await self.session.execute(stmt_rg)
        for row in res_rg.all():
            d, user, model, in_tok, c_read, c_write, c_write_l, out_tok = row
            if model and model.model_identifier == model_name:
                u_email = user.email if user else ""
                if not user_email or u_email == user_email:
                    if (not start_date or d >= start_date) and (not end_date or d <= end_date):
                        records.append({
                            "date": d,
                            "user": u_email,
                            "model": model.model_identifier,
                            "metrics": [
                                int(in_tok or 0),
                                int(c_read or 0),
                                int(c_write or 0),
                                int(c_write_l or 0),
                                int(out_tok or 0),
                            ],
                        })

        return records


    async def recover_stale_running(self) -> int:
        """Mark any analyses that were left in RUNNING status during a crash/restart as FAILED."""
        stmt = (
            update(AIAnalysis)
            .where(AIAnalysis.status == RunStatus.RUNNING)
            .values(
                status=RunStatus.FAILED,
                error_message="Execution interrupted due to worker restart or server termination.",
            )
        )
        res = await self.session.execute(stmt)
        await self.session.commit()
        return res.rowcount


class SQLAlchemyAIFindingRepository(AIFindingRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        ai_analysis_id: int,
        description: str,
        file_path: str,
        diff_side: DiffSide,
        start_line: int,
        end_line: int,
    ) -> AIFinding:
        finding = AIFinding(
            ai_analysis_id=ai_analysis_id,
            description=description,
            file_path=file_path,
            diff_side=diff_side,
            start_line=start_line,
            end_line=end_line,
        )
        self.session.add(finding)
        await self.session.flush()
        return finding

    async def list_by_analysis(self, analysis_id: int) -> Sequence[AIFinding]:
        stmt = (
            select(AIFinding)
            .where(AIFinding.ai_analysis_id == analysis_id)
            .order_by(AIFinding.file_path, AIFinding.start_line)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()
