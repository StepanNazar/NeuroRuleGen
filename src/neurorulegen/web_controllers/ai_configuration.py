"""Web controllers for AI configuration: MCP, skills, prompts, and provider credentials."""

from typing import Annotated
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from neurorulegen.ai_configuration.repository import (
    AIConfigurationRepository,
    SQLAlchemyAIConfigurationRepository,
)
from neurorulegen.ai_configuration.services import (
    AIConfigurationError,
    AIConfigurationNotFoundError,
    AIConfigurationPermissionError,
    AIConfigurationService,
    AIConfigurationValidationError,
)
from neurorulegen.authentication_authorization.models import User
from neurorulegen.common.config import get_settings
from neurorulegen.common.db import get_db_session
from neurorulegen.project_management.services import (
    ProjectManagementService,
)
from neurorulegen.user_interface.rendering import render
from neurorulegen.web_controllers.authentication_authorization import (
    get_current_activated_user,
)
from neurorulegen.web_controllers.project_management import (
    get_project_service,
    project_context,
)

router = APIRouter()


def get_ai_configuration_repository(
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> AIConfigurationRepository:
    return SQLAlchemyAIConfigurationRepository(db)


def get_ai_configuration_service(
    repository: AIConfigurationRepository = Depends(get_ai_configuration_repository),  # noqa: B008
) -> AIConfigurationService:
    return AIConfigurationService(repository=repository)


@router.get("/projects/{project_id}/ai")
async def settings(
    request: Request,
    project_id: int,
    current_user: User = Depends(get_current_activated_user),  # noqa: B008
    project_service: ProjectManagementService = Depends(get_project_service),  # noqa: B008
    ai_service: AIConfigurationService = Depends(get_ai_configuration_service),  # noqa: B008
):
    try:
        project = await project_service.get_project_details(project_id, current_user.id)
        config_data = await ai_service.get_project_settings(project_id, current_user.id)
    except (AIConfigurationError, Exception) as e:
        err_msg = quote_plus(str(e))
        return RedirectResponse(
            f"/projects?notice={err_msg}&notice_type=danger", status_code=303
        )

    ctx = project_context(project_id, project=project, current_user=current_user)
    return render(
        request,
        "pages/ai_configuration/settings.html",
        "Project AI settings",
        configuration=config_data,
        skills=config_data["skills"],
        notification=request.query_params.get("notice", ""),
        notification_type=request.query_params.get("notice_type", "info"),
        **ctx,
    )


@router.post("/projects/{project_id}/ai/prompt-mcp")
async def save_prompt_and_mcp(
    project_id: int,
    prompt: Annotated[str, Form()] = "",
    mcp: Annotated[str, Form()] = "",
    current_user: User = Depends(get_current_activated_user),  # noqa: B008
    ai_service: AIConfigurationService = Depends(get_ai_configuration_service),  # noqa: B008
):
    try:
        await ai_service.save_prompt_and_mcp(
            project_id=project_id,
            user_id=current_user.id,
            prompt=prompt,
            mcp_json_str=mcp,
        )
        notice = quote_plus("System prompt and MCP configuration saved successfully.")
        return RedirectResponse(
            f"/projects/{project_id}/ai?notice={notice}&notice_type=success",
            status_code=303,
        )
    except AIConfigurationValidationError as e:
        notice = quote_plus(str(e))
        return RedirectResponse(
            f"/projects/{project_id}/ai?notice={notice}&notice_type=danger",
            status_code=303,
        )
    except AIConfigurationPermissionError as e:
        notice = quote_plus(str(e))
        return RedirectResponse(
            f"/projects/{project_id}/ai?notice={notice}&notice_type=danger",
            status_code=303,
        )


@router.post("/projects/{project_id}/ai/credentials/azure")
async def save_azure_credentials(
    project_id: int,
    endpoint: Annotated[str, Form()],
    api_key: Annotated[str, Form()] = "",
    current_user: User = Depends(get_current_activated_user),  # noqa: B008
    ai_service: AIConfigurationService = Depends(get_ai_configuration_service),  # noqa: B008
):
    try:
        await ai_service.save_azure_foundry_credentials(
            project_id=project_id,
            user_id=current_user.id,
            endpoint=endpoint,
            api_key=api_key or None,
        )
        notice = quote_plus("Azure AI Foundry credentials saved successfully.")
        return RedirectResponse(
            f"/projects/{project_id}/ai?notice={notice}&notice_type=success",
            status_code=303,
        )
    except AIConfigurationError as e:
        notice = quote_plus(str(e))
        return RedirectResponse(
            f"/projects/{project_id}/ai?notice={notice}&notice_type=danger",
            status_code=303,
        )


@router.get("/projects/{project_id}/skills/{skill_id}")
@router.get("/projects/{project_id}/skills/new")
async def skill_form(
    request: Request,
    project_id: int,
    skill_id: int | None = None,
    current_user: User = Depends(get_current_activated_user),  # noqa: B008
    project_service: ProjectManagementService = Depends(get_project_service),  # noqa: B008
    ai_service: AIConfigurationService = Depends(get_ai_configuration_service),  # noqa: B008
):
    try:
        project = await project_service.get_project_details(project_id, current_user.id)
        if skill_id is not None:
            skill_obj = await ai_service.get_skill(project_id, skill_id, current_user.id)
            skill = {
                "id": skill_obj.id,
                "name": skill_obj.name,
                "content": skill_obj.content,
            }
        else:
            default_content = (
                "---\n"
                "name: my-skill\n"
                "description: Describe the purpose of this skill.\n"
                "---\n\n"
                "# Instructions\n"
                "Provide detailed instructions for the AI agent.\n"
            )
            skill = {"id": None, "name": "", "content": default_content}
    except Exception as e:
        notice = quote_plus(str(e))
        return RedirectResponse(
            f"/projects/{project_id}/ai?notice={notice}&notice_type=danger",
            status_code=303,
        )

    ctx = project_context(project_id, project=project, current_user=current_user)
    return render(
        request,
        "pages/ai_configuration/skill.html",
        "Add Agent Skill" if skill_id is None else "Edit Agent Skill",
        skill=skill,
        notification=request.query_params.get("notice", ""),
        notification_type=request.query_params.get("notice_type", "info"),
        **ctx,
    )


@router.post("/projects/{project_id}/skills/{skill_id}")
@router.post("/projects/{project_id}/skills/new")
async def save_skill(
    project_id: int,
    name: Annotated[str, Form()],
    content: Annotated[str, Form()],
    skill_id: int | None = None,
    current_user: User = Depends(get_current_activated_user),  # noqa: B008
    ai_service: AIConfigurationService = Depends(get_ai_configuration_service),  # noqa: B008
):
    try:
        if skill_id is None:
            await ai_service.create_skill(
                project_id=project_id,
                user_id=current_user.id,
                name=name,
                content=content,
            )
            notice = quote_plus("Agent Skill added successfully.")
        else:
            await ai_service.update_skill(
                project_id=project_id,
                skill_id=skill_id,
                user_id=current_user.id,
                name=name,
                content=content,
            )
            notice = quote_plus("Agent Skill updated successfully.")
        return RedirectResponse(
            f"/projects/{project_id}/ai?notice={notice}&notice_type=success",
            status_code=303,
        )
    except AIConfigurationError as e:
        notice = quote_plus(str(e))
        target_url = (
            f"/projects/{project_id}/skills/{skill_id}"
            if skill_id
            else f"/projects/{project_id}/skills/new"
        )
        return RedirectResponse(
            f"{target_url}?notice={notice}&notice_type=danger",
            status_code=303,
        )


@router.put("/api/projects/{project_id}/skills/{skill_id}")
async def toggle_skill(
    project_id: int,
    skill_id: int,
    current_user: User = Depends(get_current_activated_user),  # noqa: B008
    ai_service: AIConfigurationService = Depends(get_ai_configuration_service),  # noqa: B008
):
    try:
        return await ai_service.toggle_skill(
            project_id=project_id,
            skill_id=skill_id,
            user_id=current_user.id,
        )
    except AIConfigurationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
