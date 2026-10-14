#!/usr/bin/env bash
# One check for agents, hooks, CI and humans. Stops at the first failure so
# the last line is always a single pass or fail result.
set -euo pipefail

cd "$(dirname "$0")/.."

run_step() {
  local step="$1"
  shift
  if ! "$@"; then
    echo "CHECK FAILED: ${step}"
    exit 1
  fi
}

run_step "uv run ruff check ." uv run ruff check .
run_step "uv run ruff format --check ." uv run ruff format --check .
run_step "uv run pytest -q" uv run pytest -q

echo "CHECK PASSED"
