from fastapi import Response

from app.core.config import settings


def tenant_cookie_path(tenant_slug: str) -> str:
    if settings.tenant_url_mode == "path":
        return f"/t/{tenant_slug}"
    return "/"


def set_tenant_session_cookie(
    response: Response,
    token: str,
    tenant_slug: str,
) -> None:
    response.set_cookie(
        key=settings.tenant_session_cookie_name,
        value=token,
        max_age=settings.tenant_access_token_minutes * 60,
        httponly=True,
        secure=True,
        samesite="lax",
        path=tenant_cookie_path(tenant_slug),
    )


def clear_tenant_session_cookie(response: Response, tenant_slug: str) -> None:
    response.delete_cookie(
        key=settings.tenant_session_cookie_name,
        httponly=True,
        secure=True,
        samesite="lax",
        path=tenant_cookie_path(tenant_slug),
    )
