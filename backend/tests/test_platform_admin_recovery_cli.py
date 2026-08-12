import argparse
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cli.__main__ import build_parser, main
from app.cli.platform_admin import run_reset_password
from app.core.security import hash_password, verify_password
from app.models.platform_admin import PlatformAdmin, PlatformAdminRole
from app.repositories.platform_admin_repository import PlatformAdminRepository
from app.services.platform_admin_recovery_service import (
    PlatformAdminRecoveryError,
    PlatformAdminRecoveryService,
)
from app.services.platform_admin_service import PlatformAdminService


OLD_PASSWORD = "old-password-value"
NEW_PASSWORD = "new-password-value"


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    PlatformAdmin.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add_all([
            PlatformAdmin(
                username="platformadmin",
                email="admin@example.com",
                full_name="Platform Admin",
                role=PlatformAdminRole.PLATFORM_ADMIN,
                password_hash=hash_password(OLD_PASSWORD),
                is_active=False,
                locked=True,
                failed_login_attempts=5,
            ),
            PlatformAdmin(
                username="readonly",
                email="readonly@example.com",
                full_name="Read Only",
                role=PlatformAdminRole.PLATFORM_READONLY,
                password_hash=hash_password(OLD_PASSWORD),
                is_active=True,
                locked=False,
                failed_login_attempts=0,
            ),
        ])
        db.commit()
    yield factory
    engine.dispose()


def test_existing_admin_can_be_selected_by_exact_email_and_username(session_factory):
    with session_factory() as db:
        service = PlatformAdminRecoveryService(PlatformAdminRepository(db))
        by_email = service.resolve(email="admin@example.com")
        by_username = service.resolve(username="platformadmin")
        assert by_email.id == by_username.id


def test_unknown_and_readonly_accounts_are_rejected(session_factory):
    with session_factory() as db:
        service = PlatformAdminRecoveryService(PlatformAdminRepository(db))
        with pytest.raises(PlatformAdminRecoveryError, match="not found"):
            service.resolve(email="missing@example.com")
        with pytest.raises(PlatformAdminRecoveryError, match="not a Platform Admin"):
            service.resolve(username="readonly")


def test_cli_parser_requires_exactly_one_selector():
    parser = build_parser()
    args = parser.parse_args([
        "platform-admin", "reset-password", "--email", "admin@example.com"
    ])
    assert args.email == "admin@example.com"
    with pytest.raises(SystemExit):
        parser.parse_args([
            "platform-admin", "reset-password",
            "--email", "admin@example.com",
            "--username", "platformadmin",
        ])


def test_default_confirmation_is_no_and_password_is_not_prompted(session_factory):
    output: list[str] = []
    prompted = False

    def password_prompt(_prompt: str) -> str:
        nonlocal prompted
        prompted = True
        return NEW_PASSWORD

    code = run_reset_password(
        argparse.Namespace(email="admin@example.com", username=None, yes=False),
        session_factory=session_factory,
        input_fn=lambda _prompt: "",
        password_prompt=password_prompt,
        output_fn=output.append,
    )
    assert code != 0
    assert not prompted
    assert output[-1] == "Password recovery cancelled."


def test_password_mismatch_is_rejected_without_mutation(session_factory):
    values = iter([NEW_PASSWORD, "different-password"])
    output: list[str] = []
    code = run_reset_password(
        argparse.Namespace(email=None, username="platformadmin", yes=True),
        session_factory=session_factory,
        password_prompt=lambda _prompt: next(values),
        output_fn=output.append,
    )
    assert code != 0
    assert output[-1] == "Passwords do not match."
    with session_factory() as db:
        account = PlatformAdminRepository(db).get_by_username("platformadmin")
        assert account is not None
        assert verify_password(OLD_PASSWORD, account.password_hash)


def test_invalid_password_policy_is_rejected(session_factory):
    output: list[str] = []
    code = run_reset_password(
        argparse.Namespace(email="admin@example.com", username=None, yes=True),
        session_factory=session_factory,
        password_prompt=lambda _prompt: "short",
        output_fn=output.append,
    )
    assert code != 0
    assert "Password does not meet policy requirements" in output[-1]


def test_recovery_hashes_activates_unlocks_and_preserves_role(
    session_factory, monkeypatch
):
    with session_factory() as db:
        repository = PlatformAdminRepository(db)
        service = PlatformAdminRecoveryService(repository)
        account = service.resolve(username="platformadmin")
        monkeypatch.setattr(
            "app.services.platform_admin_recovery_service.hash_password",
            lambda password: "application-hash",
        )
        service.reset_password(account, NEW_PASSWORD)
        assert account.password_hash == "application-hash"
        assert account.is_active is True
        assert account.locked is False
        assert account.failed_login_attempts == 0
        assert account.role == PlatformAdminRole.PLATFORM_ADMIN


def test_transaction_rolls_back_on_failure():
    account = SimpleNamespace(
        id="user-id",
        username="platformadmin",
        email="admin@example.com",
        role=PlatformAdminRole.PLATFORM_ADMIN,
        password_hash="old",
        is_active=False,
        locked=True,
        failed_login_attempts=5,
    )
    rolled_back: list[bool] = []
    repository = SimpleNamespace(
        commit=lambda: (_ for _ in ()).throw(RuntimeError("database unavailable")),
        rollback=lambda: rolled_back.append(True),
        refresh=lambda _account: None,
    )
    with pytest.raises(PlatformAdminRecoveryError, match="failed"):
        PlatformAdminRecoveryService(repository).reset_password(
            account, NEW_PASSWORD
        )
    assert rolled_back == [True]


def test_cli_success_and_audit_never_expose_password_or_hash(
    session_factory, capsys
):
    output: list[str] = []
    code = main(
        [
            "platform-admin", "reset-password",
            "--email", "admin@example.com",
            "--yes",
        ],
        session_factory=session_factory,
        password_prompt=lambda _prompt: NEW_PASSWORD,
        output_fn=output.append,
    )
    rendered_output = "\n".join(output)
    rendered_logs = capsys.readouterr().out
    assert code == 0
    assert "Platform administrator password reset successfully" in rendered_output
    assert "platformadmin" in rendered_output
    assert "admin@example.com" in rendered_output
    assert NEW_PASSWORD not in rendered_output
    assert NEW_PASSWORD not in rendered_logs
    assert "$argon2" not in rendered_output
    assert "$argon2" not in rendered_logs
    assert "platform_admin_password_recovered" in rendered_logs
    assert "command_source=local_cli" in rendered_logs


def test_cli_unknown_and_readonly_exit_nonzero(session_factory):
    for selector in (
        argparse.Namespace(email="missing@example.com", username=None, yes=True),
        argparse.Namespace(email=None, username="readonly", yes=True),
    ):
        code = run_reset_password(
            selector,
            session_factory=session_factory,
            password_prompt=lambda _prompt: NEW_PASSWORD,
            output_fn=lambda _message: None,
        )
        assert code != 0


def test_new_password_authenticates_and_old_password_no_longer_works(
    session_factory
):
    output: list[str] = []
    code = run_reset_password(
        argparse.Namespace(email=None, username="platformadmin", yes=True),
        session_factory=session_factory,
        password_prompt=lambda _prompt: NEW_PASSWORD,
        output_fn=output.append,
    )
    assert code == 0
    with session_factory() as db:
        auth = PlatformAdminService(PlatformAdminRepository(db))
        assert auth.authenticate("platformadmin", OLD_PASSWORD) is None
        account = PlatformAdminRepository(db).get_by_username("platformadmin")
        assert account is not None
        account.locked = False
        db.commit()
        assert auth.authenticate("platformadmin", NEW_PASSWORD) is not None


def test_readonly_account_remains_unchanged_after_admin_recovery(session_factory):
    with session_factory() as before:
        readonly = PlatformAdminRepository(before).get_by_username("readonly")
        assert readonly is not None
        snapshot = (
            readonly.role,
            readonly.password_hash,
            readonly.is_active,
            readonly.locked,
        )
    run_reset_password(
        argparse.Namespace(email="admin@example.com", username=None, yes=True),
        session_factory=session_factory,
        password_prompt=lambda _prompt: NEW_PASSWORD,
        output_fn=lambda _message: None,
    )
    with session_factory() as after:
        readonly = PlatformAdminRepository(after).get_by_username("readonly")
        assert readonly is not None
        assert (
            readonly.role,
            readonly.password_hash,
            readonly.is_active,
            readonly.locked,
        ) == snapshot
