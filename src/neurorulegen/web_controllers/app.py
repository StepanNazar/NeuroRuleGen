from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from neurorulegen.user_interface.rendering import ROOT
from neurorulegen.web_controllers import (
    ai_configuration,
    analysis_management,
    authentication_authorization,
    project_management,
    rule_management,
)

app = FastAPI(title="NeuroRuleGen")
ROOT.joinpath("static").mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
for module in [
    authentication_authorization,
    project_management,
    analysis_management,
    rule_management,
    ai_configuration,
]:
    app.include_router(module.router)


@app.middleware("http")
async def inactive_account(request, call_next):
    if (
        request.url.path.startswith("/projects")
        and not authentication_authorization.profile["is_activated"]
    ):
        return RedirectResponse("/profile", status_code=303)
    return await call_next(request)


@app.get("/")
def index():
    return RedirectResponse("/projects", status_code=303)
