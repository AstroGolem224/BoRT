#!/usr/bin/env bash
# Start-Wrapper für BoR Transcriber (BoRT) – neue pywebview/Neumorphism-UI.
#
# GDK_BACKEND=x11 ist auf dieser KDE-Wayland/NVIDIA-Kiste zwingend: ohne den
# Umweg über XWayland rendert WebKitGTK ein schwarzes Fenster (Prozess läuft,
# zeigt nichts). Die WEBKIT_DISABLE_*-Vars entschärfen zusätzlich DMABUF-/
# Compositing-Probleme des proprietären Treibers. Env MUSS vor dem Python-Start
# gesetzt sein.
#
# Fallback auf die alte customtkinter-UI (bis endgültig entfernt): run-gui.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export GDK_BACKEND=x11
export WEBKIT_DISABLE_DMABUF_RENDERER=1
export WEBKIT_DISABLE_COMPOSITING_MODE=1

# Direkt das venv-Python, NICHT `uv run`: der KDE-Desktop-Launcher hat ein
# minimales PATH ohne ~/.local/bin, wo uv liegt -> "uv: not found" -> Icon
# startet nichts. .venv/bin/python braucht kein uv/PATH.
exec "$SCRIPT_DIR/.venv/bin/python" -m bort.app "$@"
