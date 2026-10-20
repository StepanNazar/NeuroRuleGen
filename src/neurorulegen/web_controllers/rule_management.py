from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from neurorulegen.user_interface.rendering import pagination_context, render
from neurorulegen.web_controllers.project_management import project_context

router = APIRouter()
rules = [
    {
        "id": i,
        "name": name,
        "status": status,
        "description": "Check Python code quality and security.",
        "code": "def analyze(tree):\n    findings = []\n    return findings\n",
    }
    for i, name, status in [
        (1, "Prevent shell=True", "Draft"),
        (2, "Require timeout", "Disabled"),
        (3, "Do not log secrets", "Enabled"),
        (4, "Validate file paths", "Draft"),
        (5, "Avoid mutable defaults", "Enabled"),
        (6, "Check SQL parameters", "Disabled"),
    ]
]


@router.get("/projects/{project_id}/rules")
def rule_list(request: Request, project_id: int, status: str = ""):
    selected = [r for r in rules if not status or r["status"] == status]
    pager = pagination_context(request, len(selected))
    return render(
        request,
        "pages/rule_management/list.html",
        "Deterministic rules",
        rules=selected[
            (pager["page"] - 1) * pager["page_size"] : pager["page"]
            * pager["page_size"]
        ],
        status=status,
        pager=pager,
        **project_context(project_id),
    )


@router.get("/projects/{project_id}/rules/new")
@router.get("/projects/{project_id}/rules/{rule_id}")
def rule_page(request: Request, project_id: int, rule_id: int | None = None):
    rule = next(
        (r for r in rules if r["id"] == rule_id),
        {"name": "", "description": "", "code": "", "status": "Draft"},
    )
    return render(
        request,
        "pages/rule_management/form.html",
        "New rule" if rule_id is None else f"Rule #{rule_id}",
        rule=rule,
        is_new_rule=rule_id is None,
        **project_context(project_id),
    )


@router.post("/projects/{project_id}/rules/new")
@router.post("/projects/{project_id}/rules/{rule_id}")
def save_rule(project_id: int, rule_id: int | None = None):
    if rule_id and not project_context(project_id)["is_quality_security_engineer"]:
        raise HTTPException(
            403, "Only the Quality/Security Engineer can edit saved rules."
        )
    return RedirectResponse(
        f"/projects/{project_id}/rules/{rule_id or 1}", status_code=303
    )


@router.put("/api/projects/{project_id}/rules/{rule_id}/status")
def update_status(project_id: int, rule_id: int):
    if not project_context(project_id)["is_quality_security_engineer"]:
        raise HTTPException(403, "Project permission required.")
    rule = next(r for r in rules if r["id"] == rule_id)
    return rule
