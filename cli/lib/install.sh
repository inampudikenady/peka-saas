#!/usr/bin/env bash

python_is_suitable() {
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

install_frontend_dependencies() {
    local manager="$1"
    case "$manager" in
        npm) (cd "$FRONTEND_DIR" && npm ci) ;;
        pnpm) (cd "$FRONTEND_DIR" && pnpm install --frozen-lockfile) ;;
        yarn) (cd "$FRONTEND_DIR" && yarn install --frozen-lockfile) ;;
    esac
}

install_command() {
    printf '========== PEKA Install ==========\n'
    [[ -d "$BACKEND_DIR/app" && -d "$FRONTEND_DIR" && -f "$PEKA_ROOT/VERSION" ]] || \
        die "$EXIT_DEPENDENCY" "this does not appear to be a PEKA repository."
    command -v python3 >/dev/null 2>&1 || die "$EXIT_DEPENDENCY" "python3 is required (Python 3.11 or newer)."
    python_is_suitable "$(command -v python3)" || die "$EXIT_DEPENDENCY" "Python 3.11 or newer is required."
    ensure_runtime_dirs
    if ! backend_python >/dev/null 2>&1; then
        printf 'Creating backend virtual environment...\n'
        python3 -m venv "$BACKEND_DIR/.venv" || die "$EXIT_DEPENDENCY" "could not create backend/.venv."
    else
        printf 'Backend virtual environment already exists.\n'
    fi
    local python manager
    python="$(backend_python)" || die "$EXIT_DEPENDENCY" "backend virtual environment is incomplete."
    if [[ "${PEKA_INSTALL_SKIP_DEPENDENCIES:-0}" != "1" ]]; then
        printf 'Installing backend dependencies...\n'
        "$python" -m pip install --upgrade pip
        "$python" -m pip install -r "$BACKEND_DIR/requirements.txt"
    fi
    manager="$(frontend_manager)" || die "$EXIT_DEPENDENCY" "no supported frontend lockfile was found."
    command -v "$manager" >/dev/null 2>&1 || die "$EXIT_DEPENDENCY" "$manager is required by the frontend lockfile."
    if [[ "${PEKA_INSTALL_SKIP_DEPENDENCIES:-0}" != "1" ]]; then
        printf 'Installing frontend dependencies with %s...\n' "$manager"
        install_frontend_dependencies "$manager"
    fi
    if [[ ! -f "$BACKEND_DIR/.env" ]]; then
        error "backend/.env is missing."
        printf 'Create it with: cp backend/.env.example backend/.env\n'
        return "$EXIT_DEPENDENCY"
    fi
    if ! (cd "$BACKEND_DIR" && env DEBUG="${PEKA_DEBUG:-false}" "$python" -c 'from app.core.config import settings' >/dev/null); then
        die "$EXIT_DEPENDENCY" "backend configuration is invalid; review backend/.env."
    fi
    printf '\nDependencies and runtime directories are ready.\n'
    printf 'Run database migrations before starting PEKA:\n'
    printf '  (cd %s && .venv/bin/alembic upgrade head)\n' "$BACKEND_DIR"
    printf 'Then run: peka doctor\n'
}

doctor_row() {
    printf '%-24s %s\n' "$1" "$2"
}

doctor_command() {
    printf '========== PEKA Doctor ==========\n'
    local unhealthy=0 python="" manager=""
    if [[ -d "$BACKEND_DIR/app" && -d "$FRONTEND_DIR" && -r "$PEKA_ROOT/VERSION" ]]; then
        doctor_row "Repository" "OK"
    else
        doctor_row "Repository" "FAILED"
        unhealthy=1
    fi
    if command -v python3 >/dev/null 2>&1 && python_is_suitable "$(command -v python3)"; then
        doctor_row "Python $(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')" "OK"
    else
        doctor_row "Python" "MISSING (3.11+ required)"
        unhealthy=1
    fi
    if python="$(backend_python)"; then
        doctor_row "Backend virtualenv" "OK"
        if (cd "$BACKEND_DIR" && "$python" -c 'import alembic, fastapi, sqlalchemy, uvicorn' >/dev/null 2>&1); then
            doctor_row "Backend dependencies" "OK"
        else
            doctor_row "Backend dependencies" "FAILED (run: peka install)"
            unhealthy=1
        fi
    else
        doctor_row "Backend virtualenv" "MISSING (run: peka install)"
        doctor_row "Backend dependencies" "SKIPPED"
        unhealthy=1
    fi
    if manager="$(frontend_manager)" && command -v "$manager" >/dev/null 2>&1; then
        doctor_row "Frontend runtime" "OK ($manager)"
    else
        doctor_row "Frontend runtime" "MISSING"
        unhealthy=1
    fi
    if [[ -d "$FRONTEND_DIR/node_modules" ]]; then
        doctor_row "Frontend dependencies" "OK"
    else
        doctor_row "Frontend dependencies" "MISSING (run: peka install)"
        unhealthy=1
    fi
    if [[ -n "$python" && -f "$BACKEND_DIR/.env" ]] && \
        (cd "$BACKEND_DIR" && env DEBUG="${PEKA_DEBUG:-false}" "$python" -c 'from app.core.config import settings' >/dev/null 2>&1); then
        doctor_row "Configuration" "OK"
    else
        doctor_row "Configuration" "FAILED (review backend/.env)"
        unhealthy=1
    fi
    if [[ -n "$python" && -f "$BACKEND_DIR/.env" ]] && \
        (cd "$BACKEND_DIR" && env DEBUG="${PEKA_DEBUG:-false}" "$python" -c 'from sqlalchemy import text; from app.db.session import engine; c=engine.connect(); c.execute(text("SELECT 1")); c.close()' >/dev/null 2>&1); then
        doctor_row "Database" "OK"
        if (cd "$BACKEND_DIR" && env DEBUG="${PEKA_DEBUG:-false}" "$python" -m alembic current --check-heads >/dev/null 2>&1); then
            doctor_row "Database schema" "OK"
        else
            doctor_row "Database schema" "OUTDATED (run: .venv/bin/alembic upgrade head)"
            unhealthy=1
        fi
    else
        doctor_row "Database" "FAILED (check DATABASE_URL and PostgreSQL)"
        doctor_row "Database schema" "SKIPPED"
        unhealthy=1
    fi
    printf '\n'
    if [[ "$unhealthy" -eq 0 ]]; then
        printf 'PEKA installation is healthy.\n'
    else
        printf 'PEKA installation needs attention.\n'
        return "$EXIT_FAILURE"
    fi
}
