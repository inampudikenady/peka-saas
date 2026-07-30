from app.core.config import settings


def build_platform_hostname(slug: str) -> str:
    return f"{slug}.{settings.tenant_base_domain}"


def build_tenant_url(slug: str, hostname: str | None = None) -> str:
    resolved_hostname = hostname or build_platform_hostname(slug)

    if settings.tenant_url_mode == "path":
        return f"{settings.tenant_dev_base_url.rstrip('/')}/t/{slug}"

    return f"{settings.tenant_url_scheme}://{resolved_hostname}"


def build_tenant_admin_setup_url(
    slug: str,
    token: str,
    hostname: str | None = None,
) -> str:
    tenant_url = build_tenant_url(slug=slug, hostname=hostname)
    return f"{tenant_url.rstrip('/')}/setup-admin?token={token}"


def build_tenant_password_reset_url(
    slug: str,
    token: str,
    hostname: str | None = None,
) -> str:
    tenant_url = build_tenant_url(slug=slug, hostname=hostname)
    return f"{tenant_url.rstrip('/')}/reset-password?token={token}"


def build_tenant_auth_callback_url(
    slug: str,
    hostname: str | None = None,
    tenant_url: str | None = None,
) -> str:
    public_base_url = tenant_url or build_tenant_url(slug=slug, hostname=hostname)
    return f"{public_base_url.rstrip('/')}/api/v1/tenant/auth/callback"


def build_tenant_dashboard_path(slug: str) -> str:
    if settings.tenant_url_mode == "path":
        return f"/t/{slug}/ai"
    return "/ai"
