#!/usr/bin/env bash
set -euo pipefail

export GDK_BACKEND=x11
export WEBKIT_DISABLE_DMABUF_RENDERER=1
export WEBKIT_DISABLE_COMPOSITING_MODE=1

exec uv run python -m bort.app "$@"
