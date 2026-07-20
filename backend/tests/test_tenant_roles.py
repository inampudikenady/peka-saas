from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.auth import require_tenant_admin
from app.models.tenant_user import TenantUserRole
from app.services.tenant_user_management_service import TenantUserManagementError, TenantUserManagementService


def test_tenant_user_is_forbidden_from_admin_policy():
    with pytest.raises(HTTPException) as exc:
        require_tenant_admin(SimpleNamespace(role=TenantUserRole.TENANT_USER))
    assert exc.value.status_code == 403


def test_tenant_admin_is_allowed_by_admin_policy():
    admin = SimpleNamespace(role=TenantUserRole.TENANT_ADMIN)
    assert require_tenant_admin(admin) is admin


def test_last_active_tenant_admin_cannot_be_demoted_or_deactivated():
    tenant_id, user_id = uuid4(), uuid4()
    admin = SimpleNamespace(id=user_id, tenant_id=tenant_id, role=TenantUserRole.TENANT_ADMIN, is_active=True)
    repository = SimpleNamespace(get_by_id=lambda value: admin, count_active_admins=lambda value: 1)
    service = TenantUserManagementService(repository)
    with pytest.raises(TenantUserManagementError, match="last active"):
        service.set_role(tenant_id, user_id, TenantUserRole.TENANT_USER, admin)
    with pytest.raises(TenantUserManagementError, match="own account"):
        service.set_active(tenant_id, user_id, False, admin)
