from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Identity, Text, func
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from neurorulegen.authentication_authorization.models import User
from neurorulegen.common.db import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    # External GitHub identifier, without a local repository table.
    github_repository_id: Mapped[int] = mapped_column(BigInteger)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey(User.id))
    additional_system_prompt: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(func.length(func.trim(name)) > 0, name="projects_name"),
    )

    creator: Mapped[User] = relationship()
    developers: Mapped[list["ProjectDeveloper"]] = relationship(
        back_populates="project"
    )
    invitations: Mapped[list["DeveloperInvitation"]] = relationship(
        back_populates="project"
    )


class ProjectDeveloper(Base):
    __tablename__ = "project_developers"

    project_id: Mapped[int] = mapped_column(ForeignKey(Project.id), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey(User.id), primary_key=True)

    project: Mapped[Project] = relationship(back_populates="developers")
    user: Mapped[User] = relationship()


class DeveloperInvitation(Base):
    __tablename__ = "developer_invitations"

    project_id: Mapped[int] = mapped_column(ForeignKey(Project.id), primary_key=True)
    email: Mapped[str] = mapped_column(
        Text().with_variant(CITEXT(), "postgresql"), primary_key=True
    )

    project: Mapped[Project] = relationship(back_populates="invitations")
