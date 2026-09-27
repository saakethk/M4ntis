#!/usr/bin/env bash
# Start the Mantis backend and frontend. Ctrl-C, EXIT, and TERM stop both.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

export BACKEND_PORT="${BACKEND_PORT:-8001}"
export FRONTEND_PORT="${FRONTEND_PORT:-8002}"

if [[ ! -d "$ROOT/software/frontend_prod/node_modules" ]]; then
  npm install --prefix "$ROOT/software/frontend_prod"
fi

pids=()

cleanup() {
  local status=$?
  trap '' INT TERM
  trap - EXIT
  local pid
  for pid in "${pids[@]}"; do
    kill -TERM -- -"$pid" 2>/dev/null || true
  done
  sleep 0.4
  for pid in "${pids[@]}"; do
    kill -KILL -- -"$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  exit "$status"
}
trap cleanup EXIT INT TERM

start() {
  local label=$1 dir=$2
  shift 2
  setsid bash -c '
    set -o pipefail
    cd "$1"
    shift
    label=$1
    shift
    "$@" 2>&1 | sed -u "s/^/[$label] /"
  ' bash "$dir" "$label" "$@" &
  pids+=("$!")
}

echo "Starting backend on ${BACKEND_PORT} and frontend on ${FRONTEND_PORT}"
start backend "$ROOT/software/backend" python3 -u main.py
start frontend "$ROOT/software/frontend_prod" npm run dev
wait -n
