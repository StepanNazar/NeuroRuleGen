"""Project pages and real database-backed project management routes."""

from typing import Annotated, Any
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from neurorulegen.authentication_authorization.models import User, SystemRole
from neurorulegen.authentication_authorization.repository import (
    AuthRepository,
)
from neurorulegen.authentication_authorization.services import (
    EmailService,
    GitHubOAuthService,
)
from neurorulegen.common.config import get_settings
from neurorulegen.common.db import get_db_session
from neurorulegen.github_integration.services import GitHubClient
from neurorulegen.project_management.models import Project
from neurorulegen.project_management.repository import (
    ProjectRepository,
    SQLAlchemyProjectRepository,
)
from neurorulegen.project_management.services import (
    ProjectManagementError,
    ProjectManagementService,
    ProjectNotFoundError,
    ProjectPermissionDeniedError,
    ProjectValidationError,
)
from neurorulegen.user_interface.rendering import pagination_context, render
from neurorulegen.web_controllers.authentication_authorization import (
    get_auth_repository,
    get_current_activated_user,
    get_current_user,
    get_email_service,
    get_github_oauth_service,
)

router = APIRouter()

# Preserved runs dictionary for overview until analysis/generation tables are integrated
runs = {
    "ai": [
        {
            "id": i,
            "title": f"PR #{43 - i} · "
            + ["Validate input", "Refactor service", "Fix cache"][((i - 1) % 3)],
            "status": ["Completed", "Running", "Failed"][(i - 1) % 3],
        }
        for i in range(1, 9)
    ],
    "rule": [
        {"id": i, "title": f"Analysis #{83 + i}", "status": "Completed"}
        for i in range(1, 7)
    ],
    "generation": [
        {"id": i, "title": f"Generation #{103 + i} · shell=True", "status": "Completed"}
        for i in range(1, 7)
    ],
}


def get_project_repository(
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> ProjectRepository:
    return SQLAlchemyProjectRepository(db)


def get_github_client(
    oauth_service: GitHubOAuthService = Depends(get_github_oauth_service),  # noqa: B008
) -> GitHubClient:
    return GitHubClient(oauth_service=oauth_service)


def get_project_service(
    repository: ProjectRepository = Depends(get_project_repository),  # noqa: B008
    auth_repository: AuthRepository = Depends(get_auth_repository),  # noqa: B008
    github_client: GitHubClient = Depends(get_github_client),  # noqa: B008
    email_service: EmailService = Depends(get_email_service),  # noqa: B008
) -> ProjectManagementService:
    settings = get_settings()
    return ProjectManagementService(
        repository=repository,
        auth_repository=auth_repository,
        github_client=github_client,
        email_service=email_service,
        base_url=settings.base_url,
    )


def project_context(
    project_id: int,
    project: Project | dict[str, Any] | None = None,
    current_user: User | None = None,
) -> dict[str, Any]:
    """
    Generate a context dictionary for project-related templates.
    The project can be a Project instance, a dictionary, or None."""
    if isinstance(project, Project):
        is_engineer = (
            current_user is not None and project.created_by_user_id == current_user.id
        )
        project_dict = {
            "id": project.id,
            "name": project.name,
            "repository": f"https://github.com/repository/{project.github_repository_id}",
            "github_repository_id": project.github_repository_id,
            "engineer": is_engineer,
        }
    elif isinstance(project, dict):
        project_dict = project
        is_engineer = project.get("engineer", False)
    else:
        project_dict = {
            "id": project_id,
            "name": f"Project #{project_id}",
            "repository": "https://github.com/repository",
            "engineer": False,
        }
        is_engineer = False

    return {
        "project": project_dict,
        "is_admin": current_user.system_role == SystemRole.ADMINISTRATOR if current_user else False,
        "is_activated": current_user.activated_at is not None if current_user else True,
        "is_quality_security_engineer": is_engineer,
        "can_leave_project": not is_engineer,
    }


class RenameProjectRequest(BaseModel):
    name: str


@router.get("/projects")
async def project_home(
    request: Request,
    current_user: User = Depends(get_current_activated_user),  # noqa: B008
    project_service: ProjectManagementService = Depends(get_project_service),  # noqa: B008
):
    db_projects = await project_service.get_projects_for_user(current_user.id)
    project_views = [
        {
            "id": p.id,
            "name": p.name,
            "repository": f"https://github.com/repository/{p.github_repository_id}",
            "engineer": p.created_by_user_id == current_user.id,
        }
        for p in db_projects
    ]

    return render(
        request,
        "pages/project_management/projects.html",
        "Home: my projects",
        projects=project_views,
        is_admin=current_user.system_role == SystemRole.ADMINISTRATOR if current_user else False,
        is_quality_security_engineer=False,
        is_activated=True,
        notification=request.query_params.get("notice", ""),
        notification_type=request.query_params.get("notice_type", "info"),
    )


@router.get("/projects/new")
def create_page(
    request: Request,
    current_user: User = Depends(get_current_activated_user),  # noqa: B008
):
    return render(
        request,
        "pages/project_management/create.html",
        "Create project",
        is_admin=current_user.system_role == SystemRole.ADMINISTRATOR if current_user else False,
        is_quality_security_engineer=False,
        is_activated=True,
        notification=request.query_params.get("notice", ""),
        notification_type=request.query_params.get("notice_type", "info"),
    )


@router.post("/projects/new")
async def create_project(
    name: Annotated[str, Form()],
    repository: Annotated[str, Form()],
    current_user: User = Depends(get_current_activated_user),  # noqa: B008
    project_service: ProjectManagementService = Depends(get_project_service),  # noqa: B008
):
    try:
        project = await project_service.create_project(
            name=name,
            repo_str=repository,
            creator_user_id=current_user.id,
        )
        return RedirectResponse(f"/projects/{project.id}", status_code=303)
    except ProjectValidationError as e:
        err_msg = quote_plus(str(e))
        return RedirectResponse(
            f"/projects/new?notice={err_msg}&notice_type=danger",
            status_code=303,
        )


@router.get("/projects/{project_id}")
async def overview(
    request: Request,
    project_id: int,
    current_user: User = Depends(get_current_activated_user),  # noqa: B008
    project_service: ProjectManagementService = Depends(get_project_service),  # noqa: B008
):
    try:
        project = await project_service.get_project_details(project_id, current_user.id)
    except (ProjectNotFoundError, ProjectPermissionDeniedError) as e:
        err_msg = quote_plus(str(e))
        return RedirectResponse(
            f"/projects?notice={err_msg}&notice_type=danger", status_code=303
        )

    lists = []
    for kind, rows in runs.items():
        pager = pagination_context(request, len(rows), f"{kind}_page", page_size=3)
        lists.append(
            {
                "kind": kind,
                "title": {
                    "ai": "Recent AI PR analyses",
                    "rule": "Recent rule-based analyses",
                    "generation": "Recent rule generations",
                }[kind],
                "rows": rows[
                    (pager["page"] - 1) * pager["page_size"] : pager["page"]
                    * pager["page_size"]
                ],
                "pager": pager,
            }
        )

    ctx = project_context(project_id, project=project, current_user=current_user)
    return render(
        request,
        "pages/project_management/overview.html",
        "Project overview",
        lists=lists,
        notification=request.query_params.get("notice", ""),
        notification_type=request.query_params.get("notice_type", "info"),
        **ctx,
    )


@router.get("/projects/{project_id}/settings")
async def settings(
    request: Request,
    project_id: int,
    current_user: User = Depends(get_current_activated_user),  # noqa: B008
    project_service: ProjectManagementService = Depends(get_project_service),  # noqa: B008
):
    try:
        project, dev_list = await project_service.get_developers_and_invitations(
            project_id, current_user.id
        )
    except (ProjectNotFoundError, ProjectPermissionDeniedError) as e:
        err_msg = quote_plus(str(e))
        return RedirectResponse(
            f"/projects?notice={err_msg}&notice_type=danger", status_code=303
        )

    ctx = project_context(project_id, project=project, current_user=current_user)
    return render(
        request,
        "pages/project_management/settings.html",
        "Project settings",
        developers=dev_list,
        notification=request.query_params.get("notice", ""),
        notification_type=request.query_params.get("notice_type", "info"),
        **ctx,
    )


@router.put("/api/projects/{project_id}")
async def rename(
    project_id: int,
    body: RenameProjectRequest,
    current_user: User = Depends(get_current_activated_user),  # noqa: B008
    project_service: ProjectManagementService = Depends(get_project_service),  # noqa: B008
):
    try:
        project = await project_service.rename_project(
            project_id=project_id,
            new_name=body.name,
            user_id=current_user.id,
        )
        ctx = project_context(project_id, project=project, current_user=current_user)
        return ctx["project"]
    except ProjectManagementError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/projects/{project_id}/developers")
async def invite(
    project_id: int,
    email: Annotated[str, Form()],
    current_user: User = Depends(get_current_activated_user),  # noqa: B008
    project_service: ProjectManagementService = Depends(get_project_service),  # noqa: B008
):
    try:
        result = await project_service.add_or_invite_developer(
            project_id=project_id,
            email=email,
            requesting_user_id=current_user.id,
        )
        if result["status"] == "added":
            notice = quote_plus(f"Developer {email} added to project.")
        else:
            notice = quote_plus(f"Invitation sent to {email}.")
        return RedirectResponse(
            f"/projects/{project_id}/settings?notice={notice}&notice_type=success",
            status_code=303,
        )
    except ProjectManagementError as e:
        notice = quote_plus(str(e))
        return RedirectResponse(
            f"/projects/{project_id}/settings?notice={notice}&notice_type=danger",
            status_code=303,
        )


@router.delete("/api/projects/{project_id}/developers/{developer_id}")
async def remove_developer(
    project_id: int,
    developer_id: int,
    current_user: User = Depends(get_current_activated_user),  # noqa: B008
    project_service: ProjectManagementService = Depends(get_project_service),  # noqa: B008
):
    try:
        await project_service.remove_developer(
            project_id=project_id,
            developer_user_id=developer_id,
            requesting_user_id=current_user.id,
        )
        return {"removed": developer_id}
    except ProjectManagementError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/api/projects/{project_id}/invitations")
async def remove_invitation(
    project_id: int,
    email: str,
    current_user: User = Depends(get_current_activated_user),  # noqa: B008
    project_service: ProjectManagementService = Depends(get_project_service),  # noqa: B008
):
    try:
        await project_service.remove_invitation(
            project_id=project_id,
            email=email,
            requesting_user_id=current_user.id,
        )
        return {"removed": email}
    except ProjectManagementError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/api/projects/{project_id}/membership")
async def leave(
    project_id: int,
    current_user: User = Depends(get_current_activated_user),  # noqa: B008
    project_service: ProjectManagementService = Depends(get_project_service),  # noqa: B008
):
    try:
        await project_service.leave_project(project_id, current_user.id)
        return {"redirect": "/projects"}
    except ProjectManagementError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/api/projects/{project_id}/runs")
def statuses(project_id: int):
    return runs
