"""Service layer for project management."""

from typing import Any

from neurorulegen.authentication_authorization.repository import AuthRepository
from neurorulegen.authentication_authorization.services import EmailService
from neurorulegen.github_integration.services import (
    GitHubAccessDeniedError,
    GitHubClient,
    GitHubRepoNotFoundError,
    GitHubServiceError,
)
from neurorulegen.project_management.models import Project
from neurorulegen.project_management.repository import ProjectRepository


class ProjectManagementError(Exception):
    """Base exception for project management errors."""


class ProjectNotFoundError(ProjectManagementError):
    """Raised when a project is not found."""


class ProjectPermissionDeniedError(ProjectManagementError):
    """Raised when the user does not have permission for the requested action."""


class ProjectValidationError(ProjectManagementError):
    """Raised when project validation fails."""


class ProjectManagementService:
    def __init__(
        self,
        repository: ProjectRepository,
        auth_repository: AuthRepository,
        github_client: GitHubClient,
        email_service: EmailService,
        base_url: str = "http://localhost:8000",
    ) -> None:
        self.repository = repository
        self.auth_repository = auth_repository
        self.github_client = github_client
        self.email_service = email_service
        self.base_url = base_url

    async def get_projects_for_user(self, user_id: int) -> list[Project]:
        return await self.repository.get_projects_for_user(user_id)

    async def get_project_details(self, project_id: int, user_id: int) -> Project:
        project = await self.repository.get_project_by_id(project_id)
        if not project:
            raise ProjectNotFoundError("Project not found.")
        is_member = project.created_by_user_id == user_id or any(
            d.user_id == user_id for d in project.developers
        )
        if not is_member:
            raise ProjectPermissionDeniedError(
                "You do not have access to this project."
            )
        return project

    async def create_project(
        self,
        name: str,
        repo_str: str,
        creator_user_id: int,
        additional_system_prompt: str | None = None,
    ) -> Project:
        clean_name = name.strip()
        if not clean_name:
            raise ProjectValidationError("Project name cannot be empty.")

        try:
            repo_info = await self.github_client.get_repository_details(
                repo_str=repo_str,
                user_id=creator_user_id,
            )
        except (
            GitHubRepoNotFoundError,
            GitHubAccessDeniedError,
            GitHubServiceError,
            ValueError,
        ) as e:
            raise ProjectValidationError(str(e)) from e

        github_repository_id = repo_info.get("id")
        github_repo_url = repo_info.get("html_url")
        if not isinstance(github_repository_id, int) or not github_repo_url:
            raise ProjectValidationError(
                "GitHub returned incomplete repository information."
            )

        project = await self.repository.create_project(
            name=clean_name,
            github_repository_id=github_repository_id,
            github_repo_url=github_repo_url,
            created_by_user_id=creator_user_id,
            additional_system_prompt=additional_system_prompt,
        )
        await self.repository.commit()
        return project

    async def rename_project(
        self, project_id: int, new_name: str, user_id: int
    ) -> Project:
        project = await self.repository.get_project_by_id(project_id)
        if not project:
            raise ProjectNotFoundError("Project not found.")
        if project.created_by_user_id != user_id:
            raise ProjectPermissionDeniedError(
                "Only Quality/Security Engineer can rename the project."
            )

        clean_name = new_name.strip()
        if not clean_name:
            raise ProjectValidationError("Project name cannot be empty.")

        self.repository.update_project_name(project, clean_name)
        await self.repository.commit()
        return project

    async def get_developers_and_invitations(
        self, project_id: int, user_id: int
    ) -> tuple[Project, list[dict[str, Any]]]:
        project = await self.repository.get_project_by_id(project_id)
        if not project:
            raise ProjectNotFoundError("Project not found.")
        if project.created_by_user_id != user_id and not any(
            d.user_id == user_id for d in project.developers
        ):
            raise ProjectPermissionDeniedError(
                "You do not have access to this project."
            )

        dev_list: list[dict[str, Any]] = []

        # Active developers
        for dev in project.developers:
            dev_list.append(
                {
                    "id": dev.user_id,
                    "email": dev.user.email if dev.user else "",
                    "display_name": dev.user.display_name if dev.user else None,
                    "status": "Developer",
                    "is_pending": False,
                }
            )

        # Pending invitations
        for inv in project.invitations:
            dev_list.append(
                {
                    "id": None,
                    "email": inv.email,
                    "display_name": None,
                    "status": "Invitation pending",
                    "is_pending": True,
                }
            )

        return project, dev_list

    async def add_or_invite_developer(
        self,
        project_id: int,
        email: str,
        requesting_user_id: int,
    ) -> dict[str, Any]:
        project = await self.repository.get_project_by_id(project_id)
        if not project:
            raise ProjectNotFoundError("Project not found.")
        if project.created_by_user_id != requesting_user_id:
            raise ProjectPermissionDeniedError(
                "Only Quality/Security Engineer can add developers."
            )

        clean_email = email.strip().lower()
        if not clean_email or "@" not in clean_email:
            raise ProjectValidationError("Please provide a valid email address.")

        if project.creator and project.creator.email.lower() == clean_email:
            raise ProjectValidationError(
                "Cannot add the project creator as a developer."
            )

        user = await self.auth_repository.get_user_by_email(clean_email)
        if user and user.activated_at is not None:
            # User exists and is activated -> immediate membership
            await self.repository.add_project_developer(project_id, user.id)
            # Remove any pending invitation for this email if present
            await self.repository.remove_developer_invitation(project_id, clean_email)
            await self.repository.commit()
            return {"status": "added", "email": clean_email, "user_id": user.id}
        else:
            # User does not exist or is not activated -> save invitation and send email
            await self.repository.add_developer_invitation(project_id, clean_email)
            await self.repository.commit()

            # Dispatch invitation email
            register_url = f"{self.base_url}/register?email={clean_email}"
            subject = f"You have been invited to collaborate on {project.name} on NeuroRuleGen"
            body = (
                f"Hello,\n\n"
                f"You have been invited to join the project '{project.name}' as a Developer.\n"
                f"Please register and activate your account using the following link:\n"
                f"{register_url}\n\n"
                f"Once activated, your project access will be granted automatically."
            )
            await self.email_service.send_email(
                to_name=clean_email,
                to_email=clean_email,
                subject=subject,
                body=body,
            )
            return {"status": "invited", "email": clean_email}

    async def remove_developer(
        self,
        project_id: int,
        developer_user_id: int,
        requesting_user_id: int,
    ) -> None:
        project = await self.repository.get_project_by_id(project_id)
        if not project:
            raise ProjectNotFoundError("Project not found.")
        if project.created_by_user_id != requesting_user_id:
            raise ProjectPermissionDeniedError(
                "Only Quality/Security Engineer can remove developers."
            )

        removed = await self.repository.remove_project_developer(
            project_id, developer_user_id
        )
        if not removed:
            raise ProjectValidationError("Developer not found in project.")
        await self.repository.commit()

    async def remove_invitation(
        self,
        project_id: int,
        email: str,
        requesting_user_id: int,
    ) -> None:
        project = await self.repository.get_project_by_id(project_id)
        if not project:
            raise ProjectNotFoundError("Project not found.")
        if project.created_by_user_id != requesting_user_id:
            raise ProjectPermissionDeniedError(
                "Only Quality/Security Engineer can cancel invitations."
            )

        clean_email = email.strip().lower()
        removed = await self.repository.remove_developer_invitation(
            project_id, clean_email
        )
        if not removed:
            raise ProjectValidationError("Invitation not found.")
        await self.repository.commit()

    async def leave_project(self, project_id: int, user_id: int) -> None:
        project = await self.repository.get_project_by_id(project_id)
        if not project:
            raise ProjectNotFoundError("Project not found.")
        if project.created_by_user_id == user_id:
            raise ProjectValidationError(
                "Quality/Security Engineer cannot leave their own project."
            )

        removed = await self.repository.remove_project_developer(project_id, user_id)
        if not removed:
            raise ProjectValidationError("You are not a developer in this project.")
        await self.repository.commit()

    async def claim_pending_invitations(self, email: str, user_id: int) -> int:
        """
        Convert all pending invitations for this email into active project developer memberships.
        """
        clean_email = email.strip().lower()
        invitations = await self.repository.get_invitations_by_email(clean_email)
        count = 0
        for inv in invitations:
            await self.repository.add_project_developer(inv.project_id, user_id)
            await self.repository.remove_developer_invitation(
                inv.project_id, clean_email
            )
            count += 1
        if count > 0:
            await self.repository.commit()
        return count
