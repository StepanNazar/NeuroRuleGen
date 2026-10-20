"""Analysis, generation and usage pages, using controller-owned placeholder data."""

from datetime import date, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from neurorulegen.user_interface.rendering import render
from neurorulegen.web_controllers.project_management import project_context, runs

router = APIRouter()
diff = """diff --git a/src/service.py b/src/service.py
index 1111111..2222222 100644
--- a/src/service.py
+++ b/src/service.py
@@ -1,4 +1,4 @@
 import subprocess
 
 def run_task(command):
-    subprocess.run(command)
+    subprocess.run(command, shell=True)
diff --git a/src/validators.py b/src/validators.py
index 1111111..2222222 100644
--- a/src/validators.py
+++ b/src/validators.py
@@ -1,2 +1,2 @@
 def clean(value):
-    return value
+    return validate(value)
"""
findings = [
    {
        "file": "src/service.py",
        "side": "new",
        "start": 4,
        "end": 4,
        "description": "Untrusted input may reach the shell. Avoid shell=True and pass arguments as a list.",
    }
]


def run_context(kind, run_id):
    """Read static UI metadata without creating or changing placeholder rows."""
    row = next((r for r in runs[kind] if r["id"] == run_id), None)
    if row is None:
        row = {"id": run_id, "title": f"Run #{run_id}", "status": "Completed"}
    defaults = {
        "pr": max(1, 43 - run_id),
        "provider": "OpenAI",
        "model": "gpt-5",
        "instruction": "Review Python code quality and security.",
        "mode": "Iterative",
        "iterations": 3,
        "rule_id": 1,
    }
    return defaults | row


@router.get("/projects/{project_id}/analyses/new")
def new_analysis(request: Request, project_id: int, pr: int | None = None):
    return render(
        request,
        "pages/analysis_management/new.html",
        "New AI PR analysis",
        pr=pr,
        **project_context(project_id),
    )


@router.post("/projects/{project_id}/analyses/new")
def start_analysis(project_id: int):
    return RedirectResponse(f"/projects/{project_id}/analyses/1/log", status_code=303)


@router.get("/projects/{project_id}/analyses/{run_id}")
def result(request: Request, project_id: int, run_id: int):
    run = run_context("ai", run_id)
    return render(
        request,
        "pages/analysis_management/result.html",
        run["title"],
        run=run,
        run_id=run_id,
        diff=diff,
        findings=findings,
        **project_context(project_id),
    )


@router.post("/projects/{project_id}/rule-analyses")
def run_rules(project_id: int):
    return RedirectResponse(f"/projects/{project_id}/rule-analyses/1", status_code=303)


@router.get("/projects/{project_id}/rule-analyses/{run_id}")
def rule_output(request: Request, project_id: int, run_id: int):
    run = run_context("rule", run_id)
    output = "[rule-12] src/service.py:4 — unsafe shell=True\n[rule-08] src/config.py:24 — avoid logging secrets"
    output += (
        "\nCompleted. Found 2 issues."
        if run["status"] == "Completed"
        else "\nPartial output."
    )
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
def run_log(request: Request, project_id: int, run_id: int):
    generation = "/generations/" in request.url.path
    run = run_context("generation" if generation else "ai", run_id)
    events = [
        {
            "id": 1,
            "title": "Tool call",
            "description": "Check the rule against test cases"
            if generation
            else "Read src/service.py",
            "data": 'tool: inspect_python\narguments: {"path": "src/service.py"}\nresult: subprocess.run(command, shell=True)',
            "branches": [105, 108],
        },
        {
            "id": 2,
            "title": "Intermediate conclusion",
            "description": "Provider-exposed reasoning summary",
            "data": "The subprocess call accepts a shell command. Check the input boundary.",
            "branches": [],
        },
        {
            "id": 3,
            "title": "Final artifact",
            "description": "Draft rule" if generation else "PR findings",
            "data": "def analyze(tree):\n    return []"
            if generation
            else findings[0]["description"],
            "branches": [],
        },
    ]
    return render(
        request,
        "pages/analysis_management/log.html",
        f"{'Rule generation' if generation else 'AI analysis'} log #{run_id}",
        generation=generation,
        run=run,
        run_id=run_id,
        events=events,
        instruction=run["instruction"],
        original=run.get("original", request.query_params.get("original")),
        original_event=request.query_params.get("event"),
        **project_context(project_id),
    )


@router.post("/projects/{project_id}/runs/{run_id}/fork")
async def fork(request: Request, project_id: int, run_id: int):
    data = await request.form()
    generation = data.get("generation") == "1"
    event_id = int(data.get("event", 1))
    route = "generations" if generation else "analyses"
    return RedirectResponse(
        f"/projects/{project_id}/{route}/105/log?original={run_id}&event={event_id}",
        status_code=303,
    )


@router.get("/projects/{project_id}/usage")
def usage(
    request: Request,
    project_id: int,
    *,
    model: str = "",
    user: str = "",
    start: str = "",
    end: str = "",
    group: str = "",
):  # noqa: PLR0913 -- independent GET filters
    # Per-model/per-user daily rows make filters composable without summing models.
    records = [
        {
            "date": date(2026, 10, 1) + timedelta(days=i),
            "model": m,
            "user": u,
            "metrics": [4000 + i * 20, 1000, 300, 100, 1500],
        }
        for i in range(20)
        for m in ["gpt-5", "claude-sonnet"]
        for u in ["user@example.com", "developer@example.com"]
    ]
    period = bool(start and end)
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        period = period and first <= last
    except ValueError:
        period = False
    selected = [
        r
        for r in records
        if r["model"] == model
        and (not user or r["user"] == user)
        and (not period or first <= r["date"] <= last)
    ]
    group = group if period and group in ["day", "month"] else ""
    grouped = {}
    for record in selected:
        key = (
            record["date"].isoformat()[:7]
            if group == "month"
            else record["date"].isoformat()
            if group
            else "summary"
        )
        grouped.setdefault(key, [0] * 5)
        grouped[key] = [
            a + b for a, b in zip(grouped[key], record["metrics"], strict=True)
        ]
    return render(
        request,
        "pages/analysis_management/usage.html",
        "Token usage",
        model=model,
        user=user,
        start=start,
        end=end,
        group=group,
        metrics=[
            "Total input",
            "Total input cache read",
            "Total input short-term cache write",
            "Total input longer-term cache write",
            "Total output",
        ],
        grouped=grouped,
        **project_context(project_id),
    )
