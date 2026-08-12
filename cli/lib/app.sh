#!/usr/bin/env bash

pid_running() {
    local pid_file="$1" pid
    [[ -f "$pid_file" ]] || return 1
    pid="$(sed -n '1p' "$pid_file" 2>/dev/null || true)"
    [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null
}

start_process() {
    local name="$1" workdir="$2" pid_file="$3" log_file="$4"
    shift 4
    LAST_STARTED=0
    if pid_running "$pid_file"; then
        printf '%s already running (PID %s).\n' "$name" "$(sed -n '1p' "$pid_file")"
        return 0
    fi
    rm -f "$pid_file"
    touch "$log_file"
    (
        cd "$workdir"
        nohup "$@" >> "$log_file" 2>&1 < /dev/null &
        printf '%s\n' "$!" > "$pid_file"
    )
    local pid
    pid="$(sed -n '1p' "$pid_file")"
    sleep "${PEKA_STARTUP_WAIT_SECONDS:-1}"
    if kill -0 "$pid" 2>/dev/null; then
        printf '%s started (PID %s).\n' "$name" "$pid"
        LAST_STARTED=1
        return 0
    fi
    rm -f "$pid_file"
    error "$name failed to start."
    printf 'Log: %s\n' "$log_file" >&2
    return 1
}

signal_process_tree() {
    local signal="$1" pid="$2" child children=""
    command -v pgrep >/dev/null 2>&1 && children="$(pgrep -P "$pid" 2>/dev/null || true)"
    for child in $children; do
        signal_process_tree "$signal" "$child"
    done
    kill "-$signal" "$pid" 2>/dev/null || true
}

stop_process() {
    local name="$1" pid_file="$2" pid
    if ! pid_running "$pid_file"; then
        rm -f "$pid_file"
        printf '%s already stopped.\n' "$name"
        return 0
    fi
    pid="$(sed -n '1p' "$pid_file")"
    printf 'Stopping %s (PID %s)...\n' "$name" "$pid"
    signal_process_tree TERM "$pid"
    local attempt
    for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.25
    done
    if kill -0 "$pid" 2>/dev/null; then
        signal_process_tree KILL "$pid"
    fi
    rm -f "$pid_file"
    printf '%s stopped.\n' "$name"
}

app_start() {
    local python manager backend_started=0
    python="$(backend_python)" || {
        error "backend virtual environment does not exist."
        printf 'Run: peka install\n' >&2
        return "$EXIT_DEPENDENCY"
    }
    [[ -f "$BACKEND_DIR/.env" ]] || {
        error "backend/.env does not exist."
        printf 'Create it from backend/.env.example before starting PEKA.\n' >&2
        return "$EXIT_DEPENDENCY"
    }
    [[ -d "$FRONTEND_DIR/node_modules" ]] || {
        error "frontend dependencies are not installed."
        printf 'Run: peka install\n' >&2
        return "$EXIT_DEPENDENCY"
    }
    manager="$(frontend_manager)" || {
        error "no supported frontend lockfile was found."
        return "$EXIT_DEPENDENCY"
    }
    command -v "$manager" >/dev/null 2>&1 || {
        error "$manager is required by the frontend lockfile."
        return "$EXIT_DEPENDENCY"
    }
    ensure_runtime_dirs
    start_process "PEKA backend" "$BACKEND_DIR" "$BACKEND_PID_FILE" "$BACKEND_LOG" \
        env DEBUG="${PEKA_DEBUG:-false}" "$python" -m uvicorn app.main:app --host 0.0.0.0 --port "${PEKA_BACKEND_PORT:-8000}" || return "$EXIT_FAILURE"
    backend_started="$LAST_STARTED"
    local frontend_args=(run dev -- --hostname 0.0.0.0)
    [[ "$manager" == "yarn" ]] && frontend_args=(dev --hostname 0.0.0.0)
    if ! start_process "PEKA frontend" "$FRONTEND_DIR" "$FRONTEND_PID_FILE" "$FRONTEND_LOG" \
        "$manager" "${frontend_args[@]}"; then
        [[ "$backend_started" -eq 0 ]] || stop_process "PEKA backend" "$BACKEND_PID_FILE"
        return "$EXIT_FAILURE"
    fi
}

app_stop() {
    ensure_runtime_dirs
    stop_process "PEKA frontend" "$FRONTEND_PID_FILE"
    stop_process "PEKA backend" "$BACKEND_PID_FILE"
}

app_status() {
    ensure_runtime_dirs
    local backend_state=STOPPED frontend_state=STOPPED
    if pid_running "$BACKEND_PID_FILE"; then backend_state=RUNNING; else rm -f "$BACKEND_PID_FILE"; fi
    if pid_running "$FRONTEND_PID_FILE"; then frontend_state=RUNNING; else rm -f "$FRONTEND_PID_FILE"; fi
    printf '========== PEKA Application ==========\n'
    printf 'Backend : %s\n' "$backend_state"
    printf 'Frontend: %s\n' "$frontend_state"
    printf '\nBackend log : %s\nFrontend log: %s\n' "$BACKEND_LOG" "$FRONTEND_LOG"
}

app_logs() {
    ensure_runtime_dirs
    touch "$BACKEND_LOG" "$FRONTEND_LOG"
    printf 'Backend log : %s\nFrontend log: %s\n' "$BACKEND_LOG" "$FRONTEND_LOG"
    tail -n 50 -F "$BACKEND_LOG" "$FRONTEND_LOG"
}

app_command() {
    local action="${1:-}"
    [[ $# -eq 1 ]] || usage_error "app requires exactly one action."
    case "$action" in
        start) app_start ;;
        stop) app_stop ;;
        restart) app_stop && app_start ;;
        status) app_status ;;
        logs) app_logs ;;
        *) usage_error "unknown app command '$action'." ;;
    esac
}
