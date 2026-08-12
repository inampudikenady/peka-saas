#!/usr/bin/env bash

PEKA_ROOT="$(cd "$PEKA_CLI_DIR/.." && pwd)"
BACKEND_DIR="$PEKA_ROOT/backend"
FRONTEND_DIR="$PEKA_ROOT/frontend"
RUNTIME_DIR="${PEKA_RUNTIME_DIR:-$PEKA_ROOT/.runtime}"
PID_DIR="$RUNTIME_DIR/pids"
LOG_DIR="$RUNTIME_DIR/logs"
BACKEND_PID_FILE="$PID_DIR/peka-backend.pid"
FRONTEND_PID_FILE="$PID_DIR/peka-frontend.pid"
BACKEND_LOG="$LOG_DIR/peka-backend.log"
FRONTEND_LOG="$LOG_DIR/peka-frontend.log"
EXIT_FAILURE=1
EXIT_USAGE=2
EXIT_DEPENDENCY=3
EXIT_ADMIN=4

error() {
    printf 'ERROR: %s\n' "$*" >&2
}

die() {
    local code="$1"
    shift
    error "$*"
    exit "$code"
}

usage_error() {
    error "$1"
    printf "Run 'peka --help' for usage.\n" >&2
    exit "$EXIT_USAGE"
}

peka_version() {
    [[ -r "$PEKA_ROOT/VERSION" ]] || die "$EXIT_FAILURE" "VERSION file is missing."
    tr -d '[:space:]' < "$PEKA_ROOT/VERSION"
}

backend_python() {
    if [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
        printf '%s\n' "$BACKEND_DIR/.venv/bin/python"
    elif [[ -x "$BACKEND_DIR/.venv/Scripts/python.exe" ]]; then
        printf '%s\n' "$BACKEND_DIR/.venv/Scripts/python.exe"
    else
        return 1
    fi
}

frontend_manager() {
    if [[ -f "$FRONTEND_DIR/pnpm-lock.yaml" ]]; then
        printf 'pnpm\n'
    elif [[ -f "$FRONTEND_DIR/yarn.lock" ]]; then
        printf 'yarn\n'
    elif [[ -f "$FRONTEND_DIR/package-lock.json" ]]; then
        printf 'npm\n'
    else
        return 1
    fi
}

ensure_runtime_dirs() {
    mkdir -p "$PID_DIR" "$LOG_DIR"
}

peka_help() {
    case "${1:-}" in
        "")
            cat <<'EOF'
PEKA Command Line Interface

Usage:
  peka app <start|stop|restart|status|logs>
  peka admin reset-password <username>
  peka install
  peka doctor
  peka help [command]
  peka --version

Commands:
  app       Manage the PEKA application
  admin     Platform administration commands
  install   Prepare a fresh PEKA installation
  doctor    Validate the PEKA installation

Options:
  -h, --help
  -V, --version
EOF
            ;;
        app)
            cat <<'EOF'
Usage: peka app <start|stop|restart|status|logs>

Manage the native PEKA backend and frontend processes.
EOF
            ;;
        admin)
            if [[ "${2:-}" == "reset-password" && $# -eq 2 ]]; then
                peka_help admin-reset-password
            elif [[ $# -eq 1 ]]; then
                cat <<'EOF'
Usage: peka admin reset-password <username>

Generate a one-time Platform Admin password-reset link.
EOF
            else
                usage_error "unknown help topic '$*'."
            fi
            ;;
        admin-reset-password)
            cat <<'EOF'
Usage: peka admin reset-password <username>

Generate a 24-hour, one-time reset link through PEKA's existing
Platform User password-reset service. No password is accepted by this command.
EOF
            ;;
        install)
            printf '%s\n' 'Usage: peka install' '' 'Prepare backend/.venv, install backend and frontend dependencies, and create runtime directories.'
            ;;
        doctor)
            printf '%s\n' 'Usage: peka doctor' '' 'Run non-destructive installation, configuration, database, and schema checks.'
            ;;
        *)
            usage_error "unknown help topic '$1'."
            ;;
    esac
}

admin_command() {
    local action="${1:-}"
    case "$action" in
        reset-password)
            [[ $# -eq 2 ]] || usage_error "admin reset-password requires exactly one username."
            local python
            python="$(backend_python)" || {
                error "backend virtual environment does not exist."
                printf 'Run: peka install\n' >&2
                exit "$EXIT_DEPENDENCY"
            }
            [[ -f "$BACKEND_DIR/.env" ]] || {
                error "backend/.env does not exist."
                printf 'Create it from backend/.env.example and configure it.\n' >&2
                exit "$EXIT_DEPENDENCY"
            }
            (cd "$BACKEND_DIR" && env DEBUG="${PEKA_DEBUG:-false}" "$python" -m app.cli.platform_admin_reset_link "$2") || exit "$EXIT_ADMIN"
            ;;
        "") usage_error "admin requires a command." ;;
        *) usage_error "unknown admin command '$action'." ;;
    esac
}
