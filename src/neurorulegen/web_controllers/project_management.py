"""Project pages and static dict/list placeholders."""

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from neurorulegen.user_interface.rendering import pagination_context, render

router = APIRouter()
projects = [
    {
        "id": 1,
        "name": "Demo Python API",
        "repository": "https://github.com/github-user/python-api",
        "engineer": True,
    },
    {
        "id": 2,
        "name": "Data tools",
        "repository": "https://github.com/team/data-tools",
        "engineer": False,
    },
    {
        "id": 3,
        "name": "Backend service",
        "repository": "https://github.com/team/backend-service",
        "engineer": True,
    },
]
developers = [
    {"id": 1, "email": "developer@example.com", "status": "Developer"},
    {"id": 2, "email": "future@example.com", "status": "Invitation pending"},
]
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


def project_context(project_id):
    project = next(p for p in projects if p["id"] == project_id)
    return {
        "project": project,
        "is_admin": False,
        "is_activated": True,
        "is_quality_security_engineer": project["engineer"],
        "can_leave_project": not project["engineer"],
    }


@router.get("/projects")
def project_home(request: Request):
    return render(
        request,
        "pages/project_management/projects.html",
        "Home: my projects",
        projects=projects,
        is_admin=False,
        is_quality_security_engineer=False,
        is_activated=True,
    )


@router.get("/projects/new")
def create_page(request: Request):
    return render(
        request,
        "pages/project_management/create.html",
        "Create project",
        is_admin=False,
        is_quality_security_engineer=False,
        is_activated=True,
    )


@router.post("/projects/new")
def create_project():
    return RedirectResponse("/projects/1", status_code=303)


@router.get("/projects/{project_id}")
def overview(request: Request, project_id: int):
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
    return render(
        request,
        "pages/project_management/overview.html",
        "Project overview",
        lists=lists,
        **project_context(project_id),
    )


@router.get("/projects/{project_id}/settings")
def settings(request: Request, project_id: int):
    return render(
        request,
        "pages/project_management/settings.html",
        "Project settings",
        developers=developers,
        **project_context(project_id),
    )


@router.put("/api/projects/{project_id}")
def rename(project_id: int):
    return project_context(project_id)["project"]


@router.post("/projects/{project_id}/developers")
def invite(project_id: int):
    return RedirectResponse(f"/projects/{project_id}/settings", status_code=303)


@router.delete("/api/projects/{project_id}/developers/{developer_id}")
def remove_developer(project_id: int, developer_id: int):
    return {"removed": developer_id}


@router.delete("/api/projects/{project_id}/membership")
def leave(project_id: int):
    return {"redirect": "/projects"}


@router.get("/api/projects/{project_id}/runs")
def statuses(project_id: int):
    return runs
