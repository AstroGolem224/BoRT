#!/usr/bin/env bash
# Start-Wrapper für BoR Transcriber (BoRT) – pywebview/Neumorphism-UI.
# GDK_BACKEND=x11 zwingend (sonst Black-Window auf NVIDIA/Wayland via WebKitGTK).
# Direkt das venv-Python (kein `uv`): der KDE-Desktop-Launcher hat uv nicht im PATH.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
export GDK_BACKEND=x11
export WEBKIT_DISABLE_DMABUF_RENDERER=1
export WEBKIT_DISABLE_COMPOSITING_MODE=1
exec "$SCRIPT_DIR/.venv/bin/python" -m bort.app "$@"
