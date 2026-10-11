import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from neurorulegen.ai_configuration.models import AIModel
from neurorulegen.authentication_authorization.models import User
from neurorulegen.common.db import Base
from neurorulegen.common.enums import RunStatus
from neurorulegen.project_management.models import Project


class PullRequestState(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


class DiffSide(str, enum.Enum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"


class PullRequest(Base):
    __tablename__ = "pull_requests"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey(Project.id))
    github_pr_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    state: Mapped[PullRequestState] = mapped_column(
        Enum(
            PullRequestState,
            native_enum=False,
            create_constraint=True,
        )
    )

    __table_args__ = (UniqueConstraint(project_id, github_pr_number),)

    project: Mapped[Project] = relationship()
    analyses: Mapped[list["AIAnalysis"]] = relationship(back_populates="pull_request")


class AIAnalysis(Base):
    __tablename__ = "ai_analyses"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    pull_request_id: Mapped[int] = mapped_column(ForeignKey(PullRequest.id))
    started_by_user_id: Mapped[int] = mapped_column(ForeignKey(User.id))
    model_id: Mapped[int] = mapped_column(ForeignKey(AIModel.id))
    status: Mapped[RunStatus] = mapped_column(
        Enum(
            RunStatus,
            native_enum=False,
            create_constraint=True,
        ),
        server_default=RunStatus.RUNNING.name,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    base_commit_hash: Mapped[str] = mapped_column(Text)
    head_commit_hash: Mapped[str] = mapped_column(Text)
    system_prompt: Mapped[str] = mapped_column(Text)
    # A future composite LangGraph FK will use thread, namespace and checkpoint.
    langgraph_thread_id: Mapped[str] = mapped_column(Text)
    source_analysis_id: Mapped[int | None] = mapped_column(ForeignKey("ai_analyses.id"))
    source_checkpoint_ns: Mapped[str | None] = mapped_column(Text)
    source_checkpoint_id: Mapped[str | None] = mapped_column(Text)
    mcp_config_hash: Mapped[bytes] = mapped_column(LargeBinary)
    skills_config_hash: Mapped[bytes] = mapped_column(LargeBinary)
    input_tokens: Mapped[int] = mapped_column(BigInteger, server_default="0")
    output_tokens: Mapped[int] = mapped_column(BigInteger, server_default="0")
    cache_write_input_tokens: Mapped[int] = mapped_column(
        BigInteger, server_default="0"
    )
    cache_write_input_tokens_long_ttl: Mapped[int] = mapped_column(
        BigInteger, server_default="0"
    )
    cached_input_tokens: Mapped[int] = mapped_column(BigInteger, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text)
    continuation_instruction: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            (status != RunStatus.FAILED.name) | error_message.is_not(None),
            name="ai_analyses_failure",
        ),
        CheckConstraint(
            (input_tokens >= 0)
            & (output_tokens >= 0)
            & (cached_input_tokens >= 0)
            & (cache_write_input_tokens >= 0)
            & (cache_write_input_tokens_long_ttl >= 0),
            name="ai_analyses_tokens",
        ),
    )

    pull_request: Mapped[PullRequest] = relationship(back_populates="analyses")
    started_by_user: Mapped[User] = relationship()
    model: Mapped[AIModel] = relationship()
    source_analysis: Mapped["AIAnalysis | None"] = relationship(
        remote_side=[id], back_populates="forks"
    )
    forks: Mapped[list["AIAnalysis"]] = relationship(back_populates="source_analysis")
    findings: Mapped[list["AIFinding"]] = relationship(back_populates="analysis")


class AIFinding(Base):
    __tablename__ = "ai_findings"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    ai_analysis_id: Mapped[int] = mapped_column(ForeignKey(AIAnalysis.id))
    description: Mapped[str] = mapped_column(Text)
    file_path: Mapped[str] = mapped_column(Text)
    diff_side: Mapped[DiffSide] = mapped_column(
        Enum(
            DiffSide,
            native_enum=False,
            create_constraint=True,
        )
    )
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint(
            (start_line >= 1) & (end_line >= start_line), name="ai_findings_lines"
        ),
    )

    analysis: Mapped[AIAnalysis] = relationship(back_populates="findings")
