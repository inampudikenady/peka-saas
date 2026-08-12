"""Generate a Platform Admin reset link through the application service layer."""

import sys
from collections.abc import Callable, Sequence

from app.db.session import SessionLocal
from app.models.platform_admin import PlatformAdminRole
from app.repositories.platform_admin_invite_repository import (
    PlatformAdminInviteRepository,
)
from app.repositories.platform_admin_repository import PlatformAdminRepository
from app.services.platform_user_service import PlatformUserError, PlatformUserService


def generate_reset_link(
    username: str,
    *,
    session_factory=SessionLocal,
    output_fn: Callable[[str], None] = print,
    error_fn: Callable[[str], None] = lambda message: print(message, file=sys.stderr),
) -> int:
    db = session_factory()
    try:
        users = PlatformAdminRepository(db)
        account = users.get_by_username(username)
        if account is None or account.role != PlatformAdminRole.PLATFORM_ADMIN:
            error_fn(f"ERROR: Platform user '{username}' was not found.")
            return 4

        service = PlatformUserService(
            users,
            PlatformAdminInviteRepository(db),
        )
        # The local CLI has no signed-in actor. The target Platform Admin is used
        # for the schema's required audit reference; token creation and storage
        # remain entirely inside the same service used by the Platform Users UI.
        reset = service.password_reset(account.id, account)
        output_fn("PEKA Platform Admin Password Reset")
        output_fn("")
        output_fn(f"User       : {account.username}")
        output_fn(f"Reset link : {reset.setup_link}")
        output_fn(f"Expires    : {reset.expires_at.isoformat()} (24 hours)")
        output_fn("")
        output_fn("Password reset link generated successfully.")
        return 0
    except PlatformUserError as exc:
        db.rollback()
        error_fn(f"ERROR: {exc}")
        return 4
    except Exception:
        db.rollback()
        error_fn("ERROR: Password reset link could not be generated. Check the database and configuration.")
        return 4
    finally:
        db.close()


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1 or not arguments[0].strip():
        print("Usage: peka admin reset-password <username>", file=sys.stderr)
        return 2
    return generate_reset_link(arguments[0])


if __name__ == "__main__":
    raise SystemExit(main())
