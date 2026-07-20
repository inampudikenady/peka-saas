from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.auth import require_platform_admin
from app.core.config import settings
from app.models.platform_admin import PlatformAdmin

router = APIRouter(prefix="/platform/settings")


class SafePlatformSettings(BaseModel):
    platform_name: str
    environment: str
    default_timezone: str
    application_version: str
    support_contact: str | None
    platform_base_url: str
    tenant_base_url: str
    url_mode: str
    public_frontend_url: str
    api_base_path: str


@router.get("", response_model=SafePlatformSettings)
def get_settings(user: PlatformAdmin = Depends(require_platform_admin)):
    tenant_base = settings.tenant_dev_base_url if settings.tenant_url_mode == "path" else f"{settings.tenant_url_scheme}://{{tenant}}.{settings.tenant_base_domain}"
    return SafePlatformSettings(platform_name=settings.app_name, environment=settings.environment, default_timezone=settings.default_timezone, application_version=settings.app_version, support_contact=settings.support_contact, platform_base_url=settings.platform_frontend_base_url, tenant_base_url=tenant_base, url_mode=settings.tenant_url_mode, public_frontend_url=settings.platform_frontend_base_url, api_base_path=settings.api_prefix)
