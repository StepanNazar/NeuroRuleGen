import enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Identity,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from neurorulegen.common.db import Base
from neurorulegen.project_management.models import Project


class MCPTransport(str, enum.Enum):
    HTTP = "http"
    SSE = "sse"


class AIProvider(Base):
    __tablename__ = "ai_providers"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)

    __table_args__ = (
        CheckConstraint(func.length(func.trim(name)) > 0, name="ai_providers_name"),
    )

    models: Mapped[list["AIModel"]] = relationship(back_populates="provider")


class AIModel(Base):
    __tablename__ = "ai_models"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey(AIProvider.id))
    model_identifier: Mapped[str] = mapped_column(Text)

    __table_args__ = (UniqueConstraint(provider_id, model_identifier),)

    provider: Mapped[AIProvider] = relationship(back_populates="models")


class ProjectProviderCredential(Base):
    __tablename__ = "project_provider_credentials"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey(Project.id))
    provider_id: Mapped[int] = mapped_column(ForeignKey(AIProvider.id))
    api_key_encrypted: Mapped[bytes] = mapped_column(LargeBinary)

    __table_args__ = (UniqueConstraint(project_id, provider_id),)

    project: Mapped[Project] = relationship()
    provider: Mapped[AIProvider] = relationship()


class MCPServer(Base):
    __tablename__ = "mcp_servers"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey(Project.id))
    name: Mapped[str] = mapped_column(Text)
    transport: Mapped[MCPTransport] = mapped_column(
        Enum(
            MCPTransport,
            native_enum=False,
            create_constraint=True,
        )
    )
    url: Mapped[str] = mapped_column(Text)
    connection_config_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=true())

    __table_args__ = (
        UniqueConstraint(project_id, name),
        CheckConstraint(func.length(func.trim(name)) > 0, name="mcp_servers_name"),
    )

    project: Mapped[Project] = relationship()


class AgentSkill(Base):
    __tablename__ = "agent_skills"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey(Project.id))
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=true())

    __table_args__ = (
        UniqueConstraint(project_id, name),
        CheckConstraint(func.length(func.trim(name)) > 0, name="agent_skills_name"),
    )

    project: Mapped[Project] = relationship()
