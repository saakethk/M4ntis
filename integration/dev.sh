#!/usr/bin/env bash
# Start the integration backend and frontend together. Ctrl-C stops both.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

export BACKEND_PORT="${BACKEND_PORT:-8001}"
export FRONTEND_PORT="${FRONTEND_PORT:-8002}"

if [[ ! -d "$HERE/software/node_modules" ]]; then
  npm install --prefix "$HERE/software"
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

# Each process runs in its own session so cleanup can stop its whole process group.
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
start backend "$HERE/backend" python3 -u main.py
start frontend "$HERE/software" npm run dev
wait -n
