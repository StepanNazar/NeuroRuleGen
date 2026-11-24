import multiprocessing
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette import status
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

from neurorulegen.ai_agent_runtime.worker import worker_process_main
from neurorulegen.common.config import get_settings
from neurorulegen.user_interface.rendering import ROOT
from neurorulegen.web_controllers import (
    ai_configuration,
    analysis_management,
    authentication_authorization,
    project_management,
    rule_management,
)
from neurorulegen.web_controllers.middlewares import CSRFHeaderProtectionMiddleware

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = settings
    stop_event = multiprocessing.Event()
    worker_process = multiprocessing.Process(
        target=worker_process_main,
        args=(stop_event,),
        daemon=True,
    )
    worker_process.start()
    app.state.worker_process = worker_process
    app.state.worker_stop_event = stop_event
    try:
        yield
    finally:
        stop_event.set()
        worker_process.join(timeout=30)
        if worker_process.is_alive():
            worker_process.terminate()

app = FastAPI(title="NeuroRuleGen", lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="neurorulegen_session",
    max_age=30 * 24 * 3600,
    same_site="lax",
    https_only=settings.cookies_secure,
)
app.add_middleware(CSRFHeaderProtectionMiddleware)
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


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Handle validation errors by redirecting back to the previous page.
    """
    print(f"Validation error on {request.url.path}: {exc.errors()}")
    referer = request.headers.get("referer") or "/"
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)



@app.get("/")
def index():
    return RedirectResponse("/projects", status_code=303)
