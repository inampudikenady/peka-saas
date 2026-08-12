import argparse
import getpass
from collections.abc import Callable

from app.db.session import SessionLocal
from app.repositories.platform_admin_repository import PlatformAdminRepository
from app.services.platform_admin_recovery_service import (
    PlatformAdminRecoveryError,
    PlatformAdminRecoveryService,
)


def add_platform_admin_commands(subparsers: argparse._SubParsersAction) -> None:
    platform_admin = subparsers.add_parser(
        "platform-admin",
        help="Local-only Platform Administrator maintenance",
    )
    actions = platform_admin.add_subparsers(dest="platform_admin_action", required=True)
    reset = actions.add_parser(
        "reset-password",
        help="Recover an existing Platform Administrator password",
    )
    selector = reset.add_mutually_exclusive_group(required=True)
    selector.add_argument("--email", help="Exact Platform Administrator email")
    selector.add_argument("--username", help="Exact Platform Administrator username")
    reset.add_argument(
        "--yes",
        action="store_true",
        help="Confirm the selected account non-interactively",
    )
    reset.set_defaults(command_handler=run_reset_password)


def run_reset_password(
    args: argparse.Namespace,
    *,
    session_factory=SessionLocal,
    input_fn: Callable[[str], str] = input,
    password_prompt: Callable[[str], str] = getpass.getpass,
    output_fn: Callable[[str], None] = print,
) -> int:
    db = session_factory()
    try:
        service = PlatformAdminRecoveryService(PlatformAdminRepository(db))
        try:
            account = service.resolve(email=args.email, username=args.username)
        except PlatformAdminRecoveryError as exc:
            output_fn(str(exc))
            return 1

        output_fn(f"Username: {account.username}")
        output_fn(f"Email: {account.email}")
        output_fn(f"Role: {account.role.value}")
        output_fn(f"Active: {str(account.is_active).lower()}")
        output_fn(f"Locked: {str(account.locked).lower()}")

        if not args.yes:
            confirmation = (
                input_fn("Reset this Platform Admin password? [y/N] ").strip().lower()
            )
            if confirmation not in {"y", "yes"}:
                output_fn("Password recovery cancelled.")
                return 2

        new_password = password_prompt("New password: ")
        confirmation_password = password_prompt("Confirm new password: ")
        if new_password != confirmation_password:
            output_fn("Passwords do not match.")
            return 2

        try:
            recovered = service.reset_password(account, new_password)
        except PlatformAdminRecoveryError as exc:
            output_fn(str(exc))
            return 1

        output_fn(
            "Platform administrator password reset successfully. "
            f"Username: {recovered.username}; Email: {recovered.email}."
        )
        return 0
    finally:
        db.close()
