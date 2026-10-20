from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from neurorulegen.user_interface.rendering import render
from neurorulegen.web_controllers.project_management import project_context

router = APIRouter()
configuration = {
    "prompt": "Review Python code quality and security.",
    "mcp": '{\n  "mcpServers": {}\n}',
}
skills = [
    {
        "id": 1,
        "name": "Python quality",
        "text": "# Python quality\n\nReview Python code and report actionable findings.",
        "enabled": True,
    },
    {
        "id": 2,
        "name": "Security review",
        "text": "# Security review\n\nInspect input boundaries and subprocess calls.",
        "enabled": False,
    },
]


@router.get("/projects/{project_id}/ai")
def settings(request: Request, project_id: int):
    return render(
        request,
        "pages/ai_configuration/settings.html",
        "Project AI settings",
        configuration=configuration,
        skills=skills,
        **project_context(project_id),
    )


@router.post("/projects/{project_id}/ai")
def save_settings(project_id: int):
    return RedirectResponse(f"/projects/{project_id}/ai", status_code=303)


@router.get("/projects/{project_id}/skills/new")
@router.get("/projects/{project_id}/skills/{skill_id}")
def skill_form(request: Request, project_id: int, skill_id: int | None = None):
    skill = next((s for s in skills if s["id"] == skill_id), {"name": "", "text": ""})
    return render(
        request,
        "pages/ai_configuration/skill.html",
        "Add Agent Skill" if skill_id is None else "Edit Agent Skill",
        skill=skill,
        **project_context(project_id),
    )


@router.post("/projects/{project_id}/skills/new")
@router.post("/projects/{project_id}/skills/{skill_id}")
def save_skill(project_id: int, skill_id: int | None = None):
    return RedirectResponse(f"/projects/{project_id}/ai", status_code=303)


@router.put("/api/projects/{project_id}/skills/{skill_id}")
def toggle_skill(project_id: int, skill_id: int):
    skill = next(s for s in skills if s["id"] == skill_id)
    return skill
