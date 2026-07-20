from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.auth import require_platform_admin
from app.models.platform_admin import PlatformAdmin, PlatformAdminRole
from app.schemas.platform_auth import PlatformUserResponse
from app.services.platform_user_service import PlatformUserError, PlatformUserService


def user(role=PlatformAdminRole.PLATFORM_ADMIN, active=True):
    value = PlatformAdmin(username="admin", email="admin@example.com", full_name="Admin", password_hash="hash", role=role, is_active=active)
    value.id = uuid4(); value.created_at = datetime.now(UTC); value.updated_at = datetime.now(UTC)
    return value


def test_readonly_is_rejected_by_admin_dependency():
    with pytest.raises(HTTPException) as exc:
        require_platform_admin(user(PlatformAdminRole.PLATFORM_READONLY))
    assert exc.value.status_code == 403


def test_safe_platform_response_has_no_password_hash():
    assert "password_hash" not in PlatformUserResponse.model_validate(user()).model_dump()


def test_admin_cannot_deactivate_self_or_last_admin():
    actor = user()
    repository = SimpleNamespace(get_by_id=lambda value: actor, count_active_admins=lambda: 1)
    service = PlatformUserService(repository, SimpleNamespace())
    with pytest.raises(PlatformUserError, match="own account"):
        service.set_active(actor.id, False, actor)
    other = user(); repository.get_by_id = lambda value: other
    with pytest.raises(PlatformUserError, match="last active"):
        service.set_active(other.id, False, actor)


def test_expired_and_used_reset_tokens_are_rejected():
    target = user(active=False)
    repository = SimpleNamespace(get_by_id=lambda value: target)
    expired = SimpleNamespace(user_id=target.id, used_at=None, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    invites = SimpleNamespace(get_by_token_hash=lambda value: expired)
    service = PlatformUserService(repository, invites)
    with pytest.raises(PlatformUserError, match="expired"):
        service.consume_reset("token", "long-enough-password")
    expired.used_at = datetime.now(UTC)
    with pytest.raises(PlatformUserError, match="already used"):
        service.consume_reset("token", "long-enough-password")
