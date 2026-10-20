"""Account UI with static placeholder data, without authentication services."""

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from neurorulegen.user_interface.rendering import pagination_context, render

router = APIRouter()
profile = {
    "is_activated": True,
    "name": "Demo User",
    "email": "user@example.com",
    "has_github": True,
    "has_password": True,
    "has_2fa": False,
}
accounts = [
    {"id": i, "email": email, "attempts": count, "blocked": i in [2, 4]}
    for i, email, count in [
        (1, "user@example.com", 12),
        (2, "blocked@example.com", 8),
        (3, "another@example.com", 3),
        (4, "other@example.com", 6),
        (5, "dev@example.com", 2),
        (6, "team@example.com", 1),
    ]
]


@router.get("/login")
@router.get("/register")
@router.get("/password-recovery")
@router.get("/totp/verify")
@router.get("/totp/setup")
@router.get("/activate")
def account_page(request: Request):
    pages = {
        "/login": ("login", "Sign in"),
        "/register": ("register", "Register"),
        "/password-recovery": ("recovery", "Recover password"),
        "/totp/verify": ("totp_login", "Verify your sign-in"),
        "/totp/setup": ("totp_setup", "Set up two-factor authentication"),
        "/activate": ("activation", "Account activation"),
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
        is_activated=profile["is_activated"],
        notification=request.query_params.get("notice", ""),
        notification_type=request.query_params.get("notice_type", "info"),
    )
    return response


@router.post("/login")
async def login(request: Request):
    form = await request.form()
    email = form.get("email")
    target = (
        "/admin"
        if email in {"admin@example.com", "admin-totp@example.com"}
        else "/projects"
    )
    requires_totp = profile["has_2fa"] or email in {
        "totp@example.com",
        "admin-totp@example.com",
    }
    return RedirectResponse(
        f"/totp/verify?next={target}" if requires_totp else target, status_code=303
    )


@router.get("/github/connect")
def github_connect():
    return RedirectResponse("/profile", status_code=303)


@router.post("/register")
def register():
    return RedirectResponse("/profile", status_code=303)


@router.post("/password-recovery")
def reset_password():
    return RedirectResponse(
        "/login?notice=Password+updated.+You+can+now+sign+in.&notice_type=success",
        status_code=303,
    )


@router.post("/totp/verify")
def verify_totp(request: Request):
    target = request.query_params.get("next", "/projects")
    return RedirectResponse(
        "/admin" if target == "/admin" else "/projects", status_code=303
    )


@router.post("/totp/setup")
def setup_totp():
    return RedirectResponse("/profile", status_code=303)


@router.get("/profile")
def profile_page(request: Request):
    return render(
        request,
        "pages/authentication_authorization/profile.html",
        "My profile",
        profile=profile,
        is_admin=False,
        is_quality_security_engineer=False,
        **profile,
    )


@router.post("/profile")
def update_profile():
    return RedirectResponse("/profile", status_code=303)


@router.post("/api/profile/activation-email")
@router.post("/api/password-recovery/code")
def email_placeholder():
    return {"accepted": True}


@router.delete("/api/profile/totp")
def disable_totp():
    return {"enabled": False}


@router.get("/logout")
def logout():
    return RedirectResponse("/login", status_code=303)


@router.get("/admin")
def admin_page(request: Request, email: str = "", minimum: int = 0):
    failed = [
        a
        for a in accounts
        if (not email or a["email"] == email) and a["attempts"] >= minimum
    ]
    blocked = [a for a in accounts if a["blocked"]]
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
