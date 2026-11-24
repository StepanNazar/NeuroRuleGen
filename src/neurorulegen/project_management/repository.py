"""Repository layer for project management."""

from abc import ABC, abstractmethod

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from neurorulegen.project_management.models import (
    DeveloperInvitation,
    Project,
    ProjectDeveloper,
)


class ProjectRepository(ABC):
    @abstractmethod
    async def get_project_by_id(self, project_id: int) -> Project | None:
        pass

    @abstractmethod
    async def get_projects_for_user(self, user_id: int) -> list[Project]:
        pass

    @abstractmethod
    async def create_project(
        self,
        name: str,
        github_repository_id: int,
        created_by_user_id: int,
        additional_system_prompt: str | None = None,
    ) -> Project:
        pass

    @abstractmethod
    def update_project_name(self, project: Project, new_name: str) -> None:
        pass

    @abstractmethod
    async def is_user_project_member(self, project_id: int, user_id: int) -> bool:
        pass

    @abstractmethod
    async def get_project_developers(self, project_id: int) -> list[ProjectDeveloper]:
        pass

    @abstractmethod
    async def get_project_invitations(
        self, project_id: int
    ) -> list[DeveloperInvitation]:
        pass

    @abstractmethod
    async def add_project_developer(
        self, project_id: int, user_id: int
    ) -> ProjectDeveloper:
        pass

    @abstractmethod
    async def remove_project_developer(self, project_id: int, user_id: int) -> bool:
        pass

    @abstractmethod
    async def add_developer_invitation(
        self, project_id: int, email: str
    ) -> DeveloperInvitation:
        pass

    @abstractmethod
    async def remove_developer_invitation(self, project_id: int, email: str) -> bool:
        pass

    @abstractmethod
    async def get_invitations_by_email(self, email: str) -> list[DeveloperInvitation]:
        pass

    @abstractmethod
    async def commit(self) -> None:
        pass


class SQLAlchemyProjectRepository(ProjectRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_project_by_id(self, project_id: int) -> Project | None:
        stmt = (
            select(Project)
            .options(
                selectinload(Project.creator),
                selectinload(Project.developers).selectinload(ProjectDeveloper.user),
                selectinload(Project.invitations),
            )
            .where(Project.id == project_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_projects_for_user(self, user_id: int) -> list[Project]:
        stmt = (
            select(Project)
            .distinct()
            .outerjoin(ProjectDeveloper, Project.id == ProjectDeveloper.project_id)
            .where(
                (Project.created_by_user_id == user_id)
                | (ProjectDeveloper.user_id == user_id)
            )
            .order_by(Project.id.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create_project(
        self,
        name: str,
        github_repository_id: int,
        created_by_user_id: int,
        additional_system_prompt: str | None = None,
    ) -> Project:
        project = Project(
            name=name,
            github_repository_id=github_repository_id,
            created_by_user_id=created_by_user_id,
            additional_system_prompt=additional_system_prompt,
        )
        self._session.add(project)
        await self._session.flush()
        return project

    def update_project_name(self, project: Project, new_name: str) -> None:
        project.name = new_name

    async def is_user_project_member(self, project_id: int, user_id: int) -> bool:
        project = await self.get_project_by_id(project_id)
        if not project:
            return False
        if project.created_by_user_id == user_id:
            return True
        stmt = select(ProjectDeveloper).where(
            ProjectDeveloper.project_id == project_id,
            ProjectDeveloper.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def get_project_developers(self, project_id: int) -> list[ProjectDeveloper]:
        stmt = (
            select(ProjectDeveloper)
            .options(selectinload(ProjectDeveloper.user))
            .where(ProjectDeveloper.project_id == project_id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_project_invitations(
        self, project_id: int
    ) -> list[DeveloperInvitation]:
        stmt = select(DeveloperInvitation).where(
            DeveloperInvitation.project_id == project_id
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def add_project_developer(
        self, project_id: int, user_id: int
    ) -> ProjectDeveloper:
        existing = await self._session.get(ProjectDeveloper, (project_id, user_id))
        if existing:
            return existing
        dev = ProjectDeveloper(project_id=project_id, user_id=user_id)
        self._session.add(dev)
        await self._session.flush()
        return dev

    async def remove_project_developer(self, project_id: int, user_id: int) -> bool:
        stmt = delete(ProjectDeveloper).where(
            ProjectDeveloper.project_id == project_id,
            ProjectDeveloper.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        return result.rowcount > 0

    async def add_developer_invitation(
        self, project_id: int, email: str
    ) -> DeveloperInvitation:
        existing = await self._session.get(
            DeveloperInvitation, (project_id, email.lower())
        )
        if existing:
            return existing
        inv = DeveloperInvitation(project_id=project_id, email=email.lower())
        self._session.add(inv)
        await self._session.flush()
        return inv

    async def remove_developer_invitation(self, project_id: int, email: str) -> bool:
        stmt = delete(DeveloperInvitation).where(
            DeveloperInvitation.project_id == project_id,
            DeveloperInvitation.email == email.lower(),
        )
        result = await self._session.execute(stmt)
        return result.rowcount > 0

    async def get_invitations_by_email(self, email: str) -> list[DeveloperInvitation]:
        stmt = select(DeveloperInvitation).where(
            DeveloperInvitation.email == email.lower()
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def commit(self) -> None:
        await self._session.commit()
