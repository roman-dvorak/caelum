#!/usr/bin/env bash
# Local dev runner: starts (or reuses) a local Redis, seeds config/data
# dirs, and runs caelum against the mock camera backend.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
./scripts/install.sh

if ! redis-cli -h 127.0.0.1 -p 6379 ping >/dev/null 2>&1; then
    echo "starting a local redis-server on :6379 ..."
    redis-server --daemonize yes --save "" --loglevel warning
fi

export CAELUM_CAMERA_BACKEND="${CAELUM_CAMERA_BACKEND:-mock}"
exec uv run caelum
