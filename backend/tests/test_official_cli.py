import hashlib
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cli.platform_admin_reset_link import generate_reset_link
from app.api.routes.platform.auth import login
from app.models.platform_admin import PlatformAdmin, PlatformAdminRole
from app.models.platform_admin_invite import (
    PlatformAdminInvite,
    PlatformAdminInvitePurpose,
)
from app.schemas.platform_auth import PlatformLoginRequest
from app.services.platform_admin_service import PlatformAdminService


REPOSITORY = Path(__file__).resolve().parents[2]
CLI = REPOSITORY / "cli" / "peka"


def run_cli(*arguments: str, cwd: Path | None = None, env: dict[str, str] | None = None):
    process_env = os.environ.copy()
    process_env.update(env or {})
    return subprocess.run(
        [str(CLI), *arguments],
        cwd=cwd or REPOSITORY,
        env=process_env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize("arguments", [("--help",), ("help",), ("help", "app")])
def test_help_commands(arguments):
    result = run_cli(*arguments)
    assert result.returncode == 0
    assert "peka app" in result.stdout


def test_version_comes_from_single_version_file():
    result = run_cli("--version")
    assert result.returncode == 0
    assert result.stdout.strip() == f"PEKA CLI {(REPOSITORY / 'VERSION').read_text().strip()}"


def test_status_uses_configurable_runtime_and_reports_both_components(tmp_path):
    result = run_cli("app", "status", env={"PEKA_RUNTIME_DIR": str(tmp_path)})
    assert result.returncode == 0
    assert "Backend : STOPPED" in result.stdout
    assert "Frontend: STOPPED" in result.stdout
    assert str(tmp_path / "logs" / "peka-backend.log") in result.stdout


def test_doctor_is_available_and_non_destructive(tmp_path):
    runtime = tmp_path / "doctor-runtime"
    result = run_cli("doctor", env={"PEKA_RUNTIME_DIR": str(runtime)})
    assert result.returncode in {0, 1}
    assert "========== PEKA Doctor ==========" in result.stdout
    assert "Backend virtualenv" in result.stdout
    assert not runtime.exists()


@pytest.mark.parametrize("namespace", ["qdrant", "ollama", "connector", "lab"])
def test_legacy_namespaces_are_invalid(namespace):
    result = run_cli(namespace, "status")
    assert result.returncode == 2
    assert "unknown command" in result.stderr


def test_admin_reset_requires_username_before_backend_bootstrap():
    result = run_cli("admin", "reset-password")
    assert result.returncode == 2
    assert "requires exactly one username" in result.stderr


def test_cli_has_no_developer_workspace_dependency():
    scripts = [CLI, *sorted((REPOSITORY / "cli" / "lib").glob("*.sh"))]
    rendered = "\n".join(path.read_text() for path in scripts)
    assert "/Users/inampudikenady/Documents/peka" not in rendered
    assert "../scripts" not in rendered


def test_application_runtime_explicitly_uses_repository_virtualenv():
    common = (REPOSITORY / "cli" / "lib" / "common.sh").read_text()
    application = (REPOSITORY / "cli" / "lib" / "app.sh").read_text()
    assert 'BACKEND_DIR/.venv/bin/python' in common
    assert '"$python" -m uvicorn' in application
    assert "python3 -m uvicorn" not in application


def test_cli_resolves_repository_when_invoked_through_symlink(tmp_path):
    link = tmp_path / "peka"
    link.symlink_to(CLI)
    result = subprocess.run(
        [str(link), "--version"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.startswith("PEKA CLI ")


def test_relocated_install_creates_repository_owned_virtualenv(tmp_path):
    checkout = tmp_path / "moved-peka-saas"
    shutil.copytree(REPOSITORY / "cli", checkout / "cli")
    shutil.copy2(REPOSITORY / "VERSION", checkout / "VERSION")
    (checkout / "backend" / "app" / "core").mkdir(parents=True)
    (checkout / "backend" / "app" / "__init__.py").write_text("")
    (checkout / "backend" / "app" / "core" / "__init__.py").write_text("")
    (checkout / "backend" / "app" / "core" / "config.py").write_text("settings = object()\n")
    (checkout / "backend" / "requirements.txt").write_text("")
    (checkout / "backend" / ".env").write_text("TESTING=true\n")
    (checkout / "frontend").mkdir()
    (checkout / "frontend" / "package-lock.json").write_text("{}\n")
    missing = subprocess.run(
        [str(checkout / "cli" / "peka"), "app", "start"],
        cwd=checkout,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert missing.returncode == 3
    assert "backend virtual environment does not exist" in missing.stderr
    assert "peka install" in missing.stderr
    result = subprocess.run(
        [str(checkout / "cli" / "peka"), "install"],
        cwd=checkout,
        env={**os.environ, "PEKA_INSTALL_SKIP_DEPENDENCIES": "1"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (checkout / "backend" / ".venv" / "bin" / "python").exists()
    assert (checkout / ".runtime" / "pids").is_dir()
    assert str(REPOSITORY) not in result.stdout


@pytest.fixture
def platform_session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    PlatformAdmin.__table__.create(engine)
    PlatformAdminInvite.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(
            PlatformAdmin(
                username="kenady",
                email="admin@example.test",
                full_name="PEKA Admin",
                role=PlatformAdminRole.PLATFORM_ADMIN,
                password_hash="existing-hash",
                is_active=True,
                locked=False,
                failed_login_attempts=0,
            )
        )
        db.commit()
    yield factory
    engine.dispose()


def test_admin_reset_generates_existing_service_token_without_password_mutation(
    platform_session_factory,
):
    output: list[str] = []
    errors: list[str] = []
    assert generate_reset_link(
        "kenady",
        session_factory=platform_session_factory,
        output_fn=output.append,
        error_fn=errors.append,
    ) == 0
    rendered = "\n".join(output)
    reset_url = next(line.split(": ", 1)[1] for line in output if line.startswith("Reset link"))
    raw_token = parse_qs(urlparse(reset_url).query)["token"][0]
    with platform_session_factory() as db:
        account = db.scalar(select(PlatformAdmin).where(PlatformAdmin.username == "kenady"))
        invite = db.scalar(select(PlatformAdminInvite))
        assert account is not None and account.password_hash == "existing-hash"
        assert invite is not None
        assert invite.purpose == PlatformAdminInvitePurpose.PASSWORD_RESET
        assert invite.token_hash == hashlib.sha256(raw_token.encode()).hexdigest()
        assert invite.token_hash != raw_token
        expires_at = invite.expires_at.replace(tzinfo=UTC) if invite.expires_at.tzinfo is None else invite.expires_at
        assert 23.9 < (expires_at - datetime.now(UTC)).total_seconds() / 3600 <= 24
    assert "(24 hours)" in rendered
    assert errors == []


def test_admin_reset_rejects_unknown_username(platform_session_factory):
    errors: list[str] = []
    code = generate_reset_link(
        "unknown",
        session_factory=platform_session_factory,
        output_fn=lambda _message: None,
        error_fn=errors.append,
    )
    assert code == 4
    assert errors == ["ERROR: Platform user 'unknown' was not found."]


def test_third_failed_platform_login_shows_generic_admin_recovery_guidance(
    monkeypatch,
):
    account = PlatformAdmin(
        username="kenady",
        email="admin@example.test",
        full_name="PEKA Admin",
        password_hash="application-hash",
        is_active=True,
        locked=False,
        failed_login_attempts=0,
    )
    repository = type(
        "Repository",
        (),
        {
            "get_by_username": lambda self, username: account if username == "kenady" else None,
            "commit": lambda self: None,
            "refresh": lambda self, value: None,
        },
    )()
    monkeypatch.setattr(
        "app.services.platform_admin_service.verify_password",
        lambda password, password_hash: False,
    )
    service = PlatformAdminService(repository)
    third_error = None
    for _ in range(3):
        with pytest.raises(HTTPException) as captured:
            login(PlatformLoginRequest(username="kenady", password="wrong"), service)
        third_error = captured.value
    assert account.failed_login_attempts == 3
    assert account.locked is False
    assert third_error is not None
    assert "contact your PEKA administrator" in third_error.detail

    with pytest.raises(HTTPException) as unknown:
        login(PlatformLoginRequest(username="arbitrary", password="wrong"), service)
    assert unknown.value.detail == third_error.detail
