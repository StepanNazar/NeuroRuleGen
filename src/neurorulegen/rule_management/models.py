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


class RuleState(str, enum.Enum):
    DRAFT = "draft"
    DISABLED = "disabled"
    ENABLED = "enabled"


class GenerationMode(str, enum.Enum):
    SIMPLE = "simple"
    ITERATIVE = "iterative"
    MULTI_AGENT = "multi_agent"


class DeterministicRule(Base):
    __tablename__ = "deterministic_rules"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey(Project.id))
    name: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text)
    state: Mapped[RuleState] = mapped_column(
        Enum(
            RuleState,
            native_enum=False,
            create_constraint=True,
        ),
        server_default=RuleState.DRAFT.name,
    )

    __table_args__ = (
        UniqueConstraint(project_id, name),
        CheckConstraint(
            func.length(func.trim(name)) > 0, name="deterministic_rules_name"
        ),
    )

    project: Mapped[Project] = relationship()
    generation: Mapped["RuleGeneration | None"] = relationship(
        back_populates="generated_rule"
    )


class RuleGeneration(Base):
    __tablename__ = "rule_generations"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey(Project.id))
    started_by_user_id: Mapped[int] = mapped_column(ForeignKey(User.id))
    model_id: Mapped[int] = mapped_column(ForeignKey(AIModel.id))
    generated_rule_id: Mapped[int | None] = mapped_column(
        ForeignKey(DeterministicRule.id), unique=True
    )
    mode: Mapped[GenerationMode] = mapped_column(
        Enum(
            GenerationMode,
            native_enum=False,
            create_constraint=True,
        )
    )
    iteration_count: Mapped[int | None] = mapped_column(Integer)
    initial_instruction: Mapped[str] = mapped_column(Text)
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
    langgraph_thread_id: Mapped[str] = mapped_column(Text)
    source_generation_id: Mapped[int | None] = mapped_column(
        ForeignKey("rule_generations.id")
    )
    source_checkpoint_ns: Mapped[str | None] = mapped_column(Text)
    source_checkpoint_id: Mapped[str | None] = mapped_column(Text)
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
            name="rule_generations_failure",
        ),
        CheckConstraint(
            (status != RunStatus.COMPLETED.name) | generated_rule_id.is_not(None),
            name="rule_generations_result",
        ),
        CheckConstraint(
            ((mode == GenerationMode.SIMPLE.name) & iteration_count.is_(None))
            | (
                mode.in_(
                    [GenerationMode.ITERATIVE.name, GenerationMode.MULTI_AGENT.name]
                )
                & iteration_count.is_not(None)
                & (iteration_count >= 1)
            ),
            name="rule_generations_mode",
        ),
        CheckConstraint(
            (input_tokens >= 0)
            & (output_tokens >= 0)
            & (cached_input_tokens >= 0)
            & (cache_write_input_tokens >= 0)
            & (cache_write_input_tokens_long_ttl >= 0),
            name="rule_generations_tokens",
        ),
        CheckConstraint(
            (
                source_generation_id.is_(None)
                & source_checkpoint_id.is_(None)
                & continuation_instruction.is_(None)
            )
            | (
                source_generation_id.is_not(None)
                & source_checkpoint_id.is_not(None)
                & continuation_instruction.is_not(None)
            ),
            name="rule_generations_source",
        ),
    )

    project: Mapped[Project] = relationship()
    started_by_user: Mapped[User] = relationship()
    model: Mapped[AIModel] = relationship()
    generated_rule: Mapped[DeterministicRule | None] = relationship(
        back_populates="generation"
    )
    source_generation: Mapped["RuleGeneration | None"] = relationship(
        remote_side=[id], back_populates="forks"
    )
    forks: Mapped[list["RuleGeneration"]] = relationship(
        back_populates="source_generation"
    )


class RepositoryRuleAnalysis(Base):
    __tablename__ = "repository_rule_analyses"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey(Project.id))
    started_by_user_id: Mapped[int] = mapped_column(ForeignKey(User.id))
    repository_commit_hash: Mapped[str] = mapped_column(Text)
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
    execution_log: Mapped[str] = mapped_column(Text, server_default="")
    error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            (status != RunStatus.FAILED.name) | error_message.is_not(None),
            name="repository_rule_analyses_failure",
        ),
    )

    project: Mapped[Project] = relationship()
    started_by_user: Mapped[User] = relationship()
