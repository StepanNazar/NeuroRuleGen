"""Web controllers for AI analysis, fork sessions, results, and token monitoring."""

from typing import Annotated, Any
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from neurorulegen.ai_configuration.repository import (
    SQLAlchemyAIConfigurationRepository,
)
from neurorulegen.analysis_management.repository import (
    SQLAlchemyAIAnalysisRepository,
    SQLAlchemyAIFindingRepository,
    SQLAlchemyPullRequestRepository,
)
from neurorulegen.analysis_management.services import (
    AnalysisError,
    AnalysisManagementService,
    AnalysisNotFoundError,
    AnalysisPermissionDeniedError,
    ModelNotConfiguredError,
)
from neurorulegen.authentication_authorization.models import User
from neurorulegen.common.db import get_db_session
from neurorulegen.common.enums import RunStatus
from neurorulegen.project_management.repository import (
    SQLAlchemyProjectRepository,
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


def get_analysis_service(
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> AnalysisManagementService:
    return AnalysisManagementService(
        analysis_repo=SQLAlchemyAIAnalysisRepository(db),
        pr_repo=SQLAlchemyPullRequestRepository(db),
        finding_repo=SQLAlchemyAIFindingRepository(db),
        project_repo=SQLAlchemyProjectRepository(db),
        ai_config_repo=SQLAlchemyAIConfigurationRepository(db),
    )


@router.get("/projects/{project_id}/analyses/new")
async def new_analysis(
    request: Request,
    project_id: int,
    pr: int | None = None,
    current_user: User = Depends(get_current_activated_user),  # noqa: B008
    project_service=Depends(get_project_service),  # noqa: B008
    analysis_service: AnalysisManagementService = Depends(get_analysis_service),  # noqa: B008
):
    project = await project_service.get_project_details(project_id, current_user.id)
    available_models_by_name: dict[str, dict[str, Any]] = {}
    for available_model in await analysis_service.get_available_models(project_id):
        available_models_by_name.setdefault(
            available_model["name"],
            available_model,
        )
    available_models = list(available_models_by_name.values())

    return render(
        request,
        "pages/analysis_management/new.html",
        "New AI PR analysis",
        pr=pr,
        models=available_models,
        **project_context(project_id, project, current_user),
    )


@router.post("/projects/{project_id}/analyses/new")
async def start_analysis(
    project_id: int,
    pr: Annotated[int, Form()],
    model_id: Annotated[int, Form()],
    instruction: Annotated[str, Form()] = "",
    current_user: User = Depends(get_current_activated_user),  # noqa: B008
    analysis_service: AnalysisManagementService = Depends(get_analysis_service),  # noqa: B008
):
    try:
        analysis = await analysis_service.request_pr_analysis(
            project_id=project_id,
            user_id=current_user.id,
            pr_number=pr,
            model_id=model_id,
            additional_instruction=instruction,
        )
        return RedirectResponse(
            f"/projects/{project_id}/analyses/{analysis.id}/log", status_code=303
        )
    except ModelNotConfiguredError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AnalysisPermissionDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/projects/{project_id}/analyses/{run_id}")
async def result(
    request: Request,
    project_id: int,
    run_id: int,
    current_user: User = Depends(get_current_activated_user),  # noqa: B008
    project_service=Depends(get_project_service),  # noqa: B008
    analysis_service: AnalysisManagementService = Depends(get_analysis_service),  # noqa: B008
):
    project = await project_service.get_project_details(project_id, current_user.id)
    analysis, findings_list = await analysis_service.get_analysis_result(
        project_id=project_id, user_id=current_user.id, analysis_id=run_id
    )

    findings_json = [
        {
            "file": f.file_path,
            "side": "new" if f.diff_side.value == "RIGHT" else "old",
            "start": f.start_line,
            "end": f.end_line,
            "description": f.description,
        }
        for f in findings_list
    ]

    run_dict = {
        "id": analysis.id,
        "title": f"Analysis #{analysis.id}",
        "status": analysis.status.value.capitalize(),
        "pr": analysis.pull_request.github_pr_number if analysis.pull_request else None,
        "provider": analysis.model.provider.name if analysis.model else "",
        "model": analysis.model.model_identifier if analysis.model else "",
    }

    return render(
        request,
        "pages/analysis_management/result.html",
        f"Analysis #{run_id}",
        run=run_dict,
        run_id=run_id,
        diff=analysis.diff or "",
        findings=findings_json,
        **project_context(project_id, project, current_user),
    )


@router.post("/projects/{project_id}/rule-analyses")
def run_rules(project_id: int):
    return RedirectResponse(f"/projects/{project_id}/rule-analyses/1", status_code=303)


@router.get("/projects/{project_id}/rule-analyses/{run_id}")
def rule_output(request: Request, project_id: int, run_id: int):
    run = {"id": run_id, "title": f"Rule-based analysis #{run_id}", "status": "Completed"}
    output = "[rule-12] src/service.py:4 — unsafe shell=True\n[rule-08] src/config.py:24 — avoid logging secrets\nCompleted. Found 2 issues."
    return render(
        request,
        "pages/analysis_management/rule_output.html",
        f"Rule-based analysis #{run_id}",
        run=run,
        output=output,
        **project_context(project_id),
    )


@router.get("/projects/{project_id}/generations/new")
def generation_form(request: Request, project_id: int, description: str = ""):
    return render(
        request,
        "pages/analysis_management/generation.html",
        "Generate a rule",
        description=description,
        **project_context(project_id),
    )


@router.post("/projects/{project_id}/generations/new")
def start_generation(project_id: int):
    return RedirectResponse(
        f"/projects/{project_id}/generations/1/log", status_code=303
    )


@router.get("/projects/{project_id}/analyses/{run_id}/log")
@router.get("/projects/{project_id}/generations/{run_id}/log")
async def run_log(
    request: Request,
    project_id: int,
    run_id: int,
    current_user: User = Depends(get_current_activated_user),  # noqa: B008
    project_service=Depends(get_project_service),  # noqa: B008
    analysis_service: AnalysisManagementService = Depends(get_analysis_service),  # noqa: B008
):
    generation = "/generations/" in request.url.path
    project = await project_service.get_project_details(project_id, current_user.id)

    if not generation:
        analysis, findings_list = await analysis_service.get_analysis_result(
            project_id=project_id, user_id=current_user.id, analysis_id=run_id
        )
        mcp_names, skill_names = await analysis_service.get_analysis_config_snapshot(
            project_id
        )
        run_dict = {
            "id": analysis.id,
            "title": f"Analysis #{analysis.id}",
            "status": analysis.status.value.capitalize(),
            "provider": analysis.model.provider.name if analysis.model else "",
            "model": analysis.model.model_identifier if analysis.model else "",
            "author": analysis.started_by_user.email if analysis.started_by_user else "",
            "input_tokens": analysis.input_tokens,
            "output_tokens": analysis.output_tokens,
            "total_tokens": analysis.input_tokens + analysis.output_tokens,
            "base_commit": analysis.base_commit_hash,
            "head_commit": analysis.head_commit_hash,
            "mcp_names": mcp_names,
            "skill_names": skill_names,
            "instruction": analysis.continuation_instruction or analysis.system_prompt,
            "original": analysis.source_analysis_id,
        }
        events = await analysis_service.get_checkpoint_timeline(
            analysis.langgraph_thread_id
        )
        branch_ids = [fork.id for fork in analysis.forks]
        for fork in analysis.forks:
            for event in events:
                if event["checkpoint_id"] == fork.source_checkpoint_id:
                    event["branches"].append(fork.id)
                    break
        if not events:
            events = [{
                "id": 1,
                "checkpoint_id": "",
                "title": "Analysis Started",
                "description": f"Target PR #{analysis.pull_request.github_pr_number if analysis.pull_request else ''}",
                "data": f"Thread ID: {analysis.langgraph_thread_id}",
                "branches": branch_ids,
            }]
        if analysis.status == RunStatus.COMPLETED:
            events[-1]["description"] = f"Completed · found {len(findings_list)} issues"
            if findings_list:
                events[-1]["data"] += "\n\nFindings:\n" + "\n".join(
                    [
                        f"- {finding.file_path}:{finding.start_line}: {finding.description}"
                        for finding in findings_list
                    ]
                )
    else:
        run_dict = {
            "id": run_id,
            "title": f"Rule generation #{run_id}",
            "status": "Completed",
            "provider": "OpenAI",
            "model": "gpt-5",
            "author": "developer@example.com",
            "mode": "Iterative",
            "iterations": 3,
            "instruction": "Draft a rule",
            "original": None,
        }
        events = []

    return render(
        request,
        "pages/analysis_management/log.html",
        f"{'Rule generation' if generation else 'AI analysis'} log #{run_id}",
        generation=generation,
        run=run_dict,
        run_id=run_id,
        events=events,
        instruction=run_dict.get("instruction", ""),
        original=run_dict.get("original"),
        original_event=request.query_params.get("event"),
        **project_context(project_id, project, current_user),
    )


@router.post("/projects/{project_id}/runs/{run_id}/fork")
async def fork(
    request: Request,
    project_id: int,
    run_id: int,
    current_user: User = Depends(get_current_activated_user),  # noqa: B008
    analysis_service: AnalysisManagementService = Depends(get_analysis_service),  # noqa: B008
):
    data = await request.form()
    generation = data.get("generation") == "1"
    event_id = str(data.get("event", "1"))
    checkpoint_id = str(data.get("checkpoint_id", "") or event_id)
    instruction = str(data.get("instruction", ""))

    if generation:
        return RedirectResponse(
            f"/projects/{project_id}/generations/105/log?original={run_id}&event={event_id}",
            status_code=303,
        )

    fork_run, drifted = await analysis_service.create_fork(
        project_id=project_id,
        user_id=current_user.id,
        source_analysis_id=run_id,
        checkpoint_id=checkpoint_id,
        instruction=instruction,
    )
    return RedirectResponse(
        f"/projects/{project_id}/analyses/{fork_run.id}/log?original={run_id}&event={event_id}",
        status_code=303,
    )


@router.get("/projects/{project_id}/usage")
async def usage(  # noqa: PLR0913 -- independent GET filters
    request: Request,
    project_id: int,
    *,
    model: str = "",
    user: str = "",
    start: str = "",
    end: str = "",
    group: str = "",
    current_user: User = Depends(get_current_activated_user),  # noqa: B008
    project_service=Depends(get_project_service),  # noqa: B008
    analysis_service: AnalysisManagementService = Depends(get_analysis_service),  # noqa: B008
):
    project = await project_service.get_project_details(project_id, current_user.id)
    if project.created_by_user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Only the Quality/Security Engineer can view token usage reports.",
        )

    available_models = await analysis_service.get_available_models(project_id)
    project_users: list[str] = []
    if project.creator and project.creator.email:
        project_users.append(project.creator.email)
    for developer in project.developers:
        if developer.user and developer.user.email:
            project_users.append(developer.user.email)
    project_users = list(dict.fromkeys(project_users))

    if not model:
        return render(
            request,
            "pages/analysis_management/usage.html",
            "Token usage",
            models=available_models,
            project_users=project_users,
            model="",
            user="",
            start="",
            end="",
            group="",
            metrics=[],
            grouped={},
            **project_context(project_id, project, current_user),
        )

    report = await analysis_service.get_token_usage_report(
        project_id=project_id,
        user_id=current_user.id,
        model_name=model,
        user_email=user or None,
        start_date=start or None,
        end_date=end or None,
        group_by=group or None,
    )

    return render(
        request,
        "pages/analysis_management/usage.html",
        "Token usage",
        models=available_models,
        project_users=project_users,
        model=report["model"],
        user=report["user"],
        start=report["start"],
        end=report["end"],
        group=report["group"],
        metrics=report["metrics"],
        grouped=report["grouped"],
        **project_context(project_id, project, current_user),
    )
