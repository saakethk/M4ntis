#!/usr/bin/env bash
# Delegate to the repo-root launcher (new layout).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "$ROOT/dev.sh"
