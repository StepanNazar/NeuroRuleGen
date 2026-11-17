"""Authentication and authorization web routes."""

from typing import Annotated
from urllib.parse import quote_plus

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, Form, Request, BackgroundTasks, Body
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from neurorulegen.authentication_authorization.models import SystemRole, User
from neurorulegen.authentication_authorization.repository import (
    AuthRepository,
    SQLAlchemyAuthRepository,
)
from neurorulegen.authentication_authorization.services import (
    AuthError,
    AuthService,
    PasswordPolicyError,
    UserAlreadyExistsError,
    NoPasswordError, HCaptchaService, CaptchaService, MockEmailService, EmailService, BrevoEmailService,
    TOTPService,
)
from neurorulegen.common.config import get_settings
from neurorulegen.common.db import get_db_session
from neurorulegen.user_interface.rendering import pagination_context, render

router = APIRouter()


def get_auth_repository(
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> AuthRepository:
    return SQLAlchemyAuthRepository(db)


def get_auth_service(
    repository: AuthRepository = Depends(get_auth_repository),  # noqa: B008
) -> AuthService:
    return AuthService(repository)


def get_totp_service(
    repository: AuthRepository = Depends(get_auth_repository),  # noqa: B008
) -> TOTPService:
    return TOTPService(repository)

def get_captcha_service() -> "CaptchaService":
    return HCaptchaService(secret_key=get_settings().hcaptcha_secret)

def get_email_service() -> "EmailService":
    return BrevoEmailService()

async def get_current_user(
    request: Request,
    repository: AuthRepository = Depends(get_auth_repository),  # noqa: B008
) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = await repository.get_user_by_id(user_id)
    return user


@router.get("/login")
@router.get("/register")
@router.get("/password-recovery")
@router.get("/totp/verify")
def account_pages(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/profile", status_code=303)
    pages = {
        "/login": ("login", "Sign in"),
        "/register": ("register", "Register"),
        "/password-recovery": ("recovery", "Recover password"),
        "/totp/verify": ("totp_login", "Verify your sign-in"),
    }
    page, title = pages[request.url.path]
    success = request.query_params.get("result", "success") == "success"
    response = render(
        request,
        f"pages/authentication_authorization/{page}.html",
        title,
        success=success,
        is_admin=False,
        is_quality_security_engineer=False,
        is_activated=True,
        notification=request.query_params.get("notice", ""),
        notification_type=request.query_params.get("notice_type", "info"),
        hcaptcha_sitekey=request.app.state.settings.hcaptcha_sitekey
    )
    return response

@router.get("/activate")
async def activate_account(
    request: Request,
    token: str,
    auth_service: AuthService = Depends(get_auth_service),  # noqa: B008
):
    try:
        user = await auth_service.activate_user(token)
        request.session["user_id"] = user.id
        return RedirectResponse(
            "/profile?notice=Account+activated+successfully.&notice_type=success",
            status_code=303,
        )
    except AuthError as e:
        return RedirectResponse(
            f"/profile?notice={quote_plus("Activation failed.")}&notice_type=danger",
            status_code=303,
        )


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    h_captcha_response: str = Form(alias="h-captcha-response"),
    auth_service: AuthService = Depends(get_auth_service),  # noqa: B008
    captcha_service: CaptchaService = Depends(get_captcha_service),  # noqa: B008
):
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else None
    if not await captcha_service.verify_captcha(
        response_token=h_captcha_response,
        remote_ip=client_ip,
    ):
        return RedirectResponse(
            f"/login?notice={quote_plus('CAPTCHA verification failed.')}&notice_type=danger",
            status_code=303
        )

    error_response = RedirectResponse(
        f"/login?notice={quote_plus('Invalid email or password.')}&notice_type=danger",
        status_code=303
    )
    try:
        user = await auth_service.login_user(email=email, password=password)
        if user is None:
            return error_response
    except NoPasswordError:
        return error_response

    if user.login_blocked:
        return render(
            request,
            "pages/authentication_authorization/login.html",
            "Sign in",
            is_admin=False,
            is_quality_security_engineer=False,
            is_activated=True,
            notification="Account is blocked. Please contact support.",
            notification_type="danger",
        )

    if user.totp_enabled:
        request.session["totp_user_id"] = user.id
        target = (
            "/admin" if user.system_role == SystemRole.ADMINISTRATOR else "/projects"
        )
        return RedirectResponse(f"/totp/verify?next={quote_plus(target)}", status_code=303)

    request.session["user_id"] = user.id
    if user.system_role == SystemRole.ADMINISTRATOR:
        return RedirectResponse("/admin", status_code=303)
    return RedirectResponse("/profile", status_code=303)


@router.get("/github/connect")
def github_connect():
    return RedirectResponse("/profile", status_code=303)


@router.post("/register")
async def register(
    request: Request,
    background_tasks: BackgroundTasks,
    name: Annotated[str, Form()],
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    h_captcha_response: Annotated[str, Form(alias="h-captcha-response")],
    auth_service: AuthService = Depends(get_auth_service),  # noqa: B008
    captcha_service: CaptchaService = Depends(get_captcha_service),  # noqa: B008
    email_service: EmailService = Depends(get_email_service)  # noqa: B008,
):
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else None
    if not await captcha_service.verify_captcha(
        response_token=h_captcha_response,
        remote_ip=client_ip,
    ):
        return RedirectResponse(
            f"/register?notice={quote_plus('CAPTCHA verification failed.')}&notice_type=danger",
            status_code=303
        )
    try:
        user = await auth_service.register_user(
            email=email,
            password=password,
            name=name,
        )
    except UserAlreadyExistsError:
        return RedirectResponse(
            f"/register?notice={quote_plus('An account with this email already exists.')}&notice_type=danger",
            status_code=303,
        )
    except PasswordPolicyError as err:
        return RedirectResponse(
            f"/register?notice={quote_plus(f'Password requirement not met: {err.reason}')}&notice_type=danger",
            status_code=303,
        )
    except AuthError:
        return RedirectResponse(
            f"/register?notice={quote_plus('Registration failed. Please try again.')}&notice_type=danger",
            status_code=303,
        )
    request.session["user_id"] = user.id
    async def send_activation_email():
        await email_service.send_activation_email(
            user=user,
            activation_link=await auth_service.generate_activation_link(user),
        )
    background_tasks.add_task(send_activation_email)
    return RedirectResponse("/profile", status_code=303)


@router.post("/password-recovery")
async def reset_password(
    email: str = Form(...),
    code: str = Form(...),
    password: str = Form(...),
    auth_service: AuthService = Depends(get_auth_service),  # noqa: B008
):
    try:
        await auth_service.reset_user_password(token=code, new_password=password)
        return RedirectResponse(
            "/login?notice=Password+updated.+You+can+now+sign+in.&notice_type=success",
            status_code=303,
        )
    except (AuthError, PasswordPolicyError) as err:
        return RedirectResponse(
            f"/password-recovery?notice={quote_plus("Failed to reset password.")}&notice_type=danger",
            status_code=303,
        )

class PasswordResetRequest(BaseModel):
    email: str
@router.post("/api/password-recovery/code", status_code=202)
async def send_password_reset_email(
        background_tasks: BackgroundTasks,
        request: PasswordResetRequest,
        email_service: EmailService = Depends(get_email_service),  # noqa: B008
        auth_service: AuthService = Depends(get_auth_service)  # noqa: B008
    ):
    current_user = await auth_service.get_user_by_email(request.email)
    if not current_user:
        return {"accepted": True}  # Do not reveal whether the email exists for security reasons

    async def send_password_reset_email():
        await email_service.send_password_reset_email(
            user=current_user,
            reset_code=await auth_service.generate_password_reset_code(current_user),
        )
    background_tasks.add_task(send_password_reset_email)
    return {"accepted": True}

@router.get("/profile")
async def profile_page(
    request: Request,
    current_user: User | None = Depends(get_current_user),  # noqa: B008
):
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    user_profile = {
        "id": current_user.id,
        "name": current_user.display_name or "",
        "email": current_user.email,
        "is_activated": current_user.activated_at is not None,
        "has_github": current_user.github_user_id is not None,
        "has_password": current_user.password_hash is not None,
        "has_2fa": current_user.totp_enabled,
    }

    return render(
        request,
        "pages/authentication_authorization/profile.html",
        "My profile",
        profile=user_profile,
        is_admin=current_user.system_role == SystemRole.ADMINISTRATOR,
        is_quality_security_engineer=False,
        notification=request.query_params.get("notice", ""),
        notification_type=request.query_params.get("notice_type", "info"),
        **user_profile,
    )


@router.post("/profile")
async def update_profile(  # noqa: PLR0913
    name: str | None = Form(None),
    current_password: str | None = Form(None),
    password: str | None = Form(None),
    current_user: User | None = Depends(get_current_user),  # noqa: B008
    auth_service: AuthService = Depends(get_auth_service),  # noqa: B008
):
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    if name is not None:
        await auth_service.update_user_display_name(current_user, name.strip())
        return RedirectResponse(
            "/profile?notice=Profile+updated+successfully.&notice_type=success",
            status_code=303,
        )

    if password and current_password:
        try:
            await auth_service.update_user_password(
                current_user, new_password=password, current_password=current_password
            )
            return RedirectResponse(
                "/profile?notice=Password+updated+successfully.&notice_type=success",
                status_code=303,
            )
        except PasswordPolicyError as err:
            return RedirectResponse(
                f"/profile?notice=Failed+to+update+password.&notice_type=danger",
                status_code=303,
            )
        except AuthError:
            return RedirectResponse(
                f"/profile?notice=Current+password+is+incorrect.&notice_type=danger",
                status_code=303,
            )
    return RedirectResponse("/profile", status_code=303)


@router.post("/api/profile/activation-email", status_code=202)
def send_activation_email(
        background_tasks: BackgroundTasks,
        current_user: User | None = Depends(get_current_user),  # noqa: B008
        email_service: EmailService = Depends(get_email_service),  # noqa: B008
        auth_service: AuthService = Depends(get_auth_service)  # noqa: B008
    ):
    if not current_user:
        return {"error": "User not found"}

    async def send_activation_email():
        await email_service.send_activation_email(
            user=current_user,
            activation_link=await auth_service.generate_activation_link(current_user),
        )

    background_tasks.add_task(send_activation_email)
    return {"accepted": True}

@router.get("/totp/setup")
async def totp_setup_page(
    request: Request,
    current_user: User | None = Depends(get_current_user),  # noqa: B008
    totp_service: TOTPService = Depends(get_totp_service),  # noqa: B008
):
    if not current_user:
        return RedirectResponse("/login", status_code=303)
    if current_user.totp_enabled:
        return RedirectResponse(
            f"/profile?notice={quote_plus('Two-factor authentication is already enabled.')}&notice_type=info",
            status_code=303,
        )

    fernet = Fernet(get_settings().fernet_key.encode())
    secret = request.session.get("totp_setup_secret")
    if not secret:
        secret = totp_service.generate_secret()
        request.session["totp_setup_secret"] = fernet.encrypt(secret.encode()).decode()
    else:
        secret = fernet.decrypt(secret.encode()).decode()

    uri = totp_service.get_provisioning_uri(secret=secret, email=current_user.email)
    qr_svg = totp_service.generate_qr_svg(uri)

    return render(
        request,
        "pages/authentication_authorization/totp_setup.html",
        "Set up two-factor authentication",
        secret=secret,
        qr_code_svg=qr_svg,
        is_admin=current_user.system_role == SystemRole.ADMINISTRATOR,
        is_quality_security_engineer=False,
        is_activated=current_user.activated_at is not None,
        notification=request.query_params.get("notice", ""),
        notification_type=request.query_params.get("notice_type", "info"),
    )

@router.delete("/api/profile/totp")
async def disable_totp(
    current_user: User | None = Depends(get_current_user),  # noqa: B008
    totp_service: TOTPService = Depends(get_totp_service),  # noqa: B008
):
    if not current_user:
        return {"error": "Unauthorized"}
    await totp_service.disable_totp(current_user)
    return {"enabled": False}


@router.post("/totp/verify")
async def verify_totp(
    request: Request,
    code: str = Form(...),
    auth_repository: AuthRepository = Depends(get_auth_repository),  # noqa: B008
    totp_service: TOTPService = Depends(get_totp_service),  # noqa: B008
):
    target = request.query_params.get("next", "/projects")
    user_id = request.session.get("totp_user_id") or request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    user = await auth_repository.get_user_by_id(user_id)
    if not user:
        return RedirectResponse("/login", status_code=303)

    if not await totp_service.verify_user_totp(user, code):
        return RedirectResponse(
            f"/totp/verify?next={quote_plus(target)}&notice={quote_plus('Invalid authentication code.')}&notice_type=danger",
            status_code=303,
        )

    request.session.pop("totp_user_id", None)
    request.session["user_id"] = user.id

    if target == "/admin" and user.system_role == SystemRole.ADMINISTRATOR:
        return RedirectResponse("/admin", status_code=303)
    return RedirectResponse(target if target.startswith("/") else "/projects", status_code=303)


@router.post("/totp/setup")
async def setup_totp(
    request: Request,
    code: str = Form(...),
    current_user: User | None = Depends(get_current_user),  # noqa: B008
    totp_service: TOTPService = Depends(get_totp_service),  # noqa: B008
):
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    secret = request.session.get("totp_setup_secret")
    if not secret:
        return RedirectResponse(
            f"/totp/setup?notice={quote_plus('Setup session expired. Please try again.')}&notice_type=danger",
            status_code=303,
        )

    fernet = Fernet(get_settings().fernet_key.encode())
    secret = fernet.decrypt(secret.encode()).decode()
    success = await totp_service.setup_totp(user=current_user, secret=secret, code=code)
    if not success:
        return RedirectResponse(
            f"/totp/setup?notice={quote_plus('Invalid verification code. Please try again.')}&notice_type=danger",
            status_code=303,
        )

    request.session.pop("totp_setup_secret", None)
    return RedirectResponse(
        f"/profile?notice={quote_plus('Two-factor authentication enabled successfully.')}&notice_type=success",
        status_code=303,
    )


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/admin")
def admin_page(request: Request, email: str = "", minimum: int = 0):
    p = pagination_context(request, len(failed))
    bp = pagination_context(request, len(blocked), "blocked_page")
    return render(
        request,
        "pages/authentication_authorization/admin.html",
        "Account security",
        is_admin=True,
        is_quality_security_engineer=False,
        is_activated=True,
        accounts=failed[(p["page"] - 1) * p["page_size"] : p["page"] * p["page_size"]],
        blocked=blocked[
            (bp["page"] - 1) * bp["page_size"] : bp["page"] * bp["page_size"]
        ],
        pager=p,
        blocked_pager=bp,
        email=email,
        minimum=minimum,
    )


@router.post("/api/user/{account_id}/block")
@router.delete("/api/user/{account_id}/block")
def account_block(account_id: int):
    account = next(a for a in accounts if a["id"] == account_id)
    return account
