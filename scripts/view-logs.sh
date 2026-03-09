#!/usr/bin/env bash
# Start inspect view server for browser access (no auth) on port 7677
# Usage: ./scripts/view-logs.sh
set -euo pipefail
cd "$(dirname "$0")/.."
unset INSPECT_VIEW_AUTHORIZATION_TOKEN 2>/dev/null || true
exec uv run inspect view start --port 7677 --log-dir ./logs "$@"
