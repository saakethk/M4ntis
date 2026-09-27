#!/usr/bin/env bash
# Start the integration backend and frontend together. Ctrl-C stops both.
# Works with macOS's bash 3.2 and on Linux (no setsid, wait -n, or GNU sed needed).
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

# Job control puts each background job in its own process group, so cleanup can
# stop a whole job (e.g. npm and the vite process it spawns) with one signal.
set -m
pids=()

cleanup() {
  trap '' INT TERM
  trap - EXIT
  local pid
  for pid in "${pids[@]}"; do
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  done
  sleep 0.5
  for pid in "${pids[@]}"; do
    kill -KILL -- "-$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Run a command in a directory, prefixing each output line with a label.
start() {
  local label=$1 dir=$2
  shift 2
  (
    cd "$dir"
    "$@" 2>&1 | while IFS= read -r line; do printf '[%s] %s\n' "$label" "$line"; done
  ) &
  pids+=("$!")
}

echo "Starting backend on ${BACKEND_PORT} and frontend on ${FRONTEND_PORT}"
start backend "$HERE/backend" python3 -u main.py
start frontend "$HERE/software" npm run dev

# Stop both as soon as either exits.
while true; do
  for pid in "${pids[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "A server exited; stopping the other."
      exit 1
    fi
  done
  sleep 1
done
