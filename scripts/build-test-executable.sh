#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

exec .venv/bin/pyinstaller \
  --clean \
  --noconfirm \
  --distpath dist/test-build \
  --workpath build/test-build \
  bort-onefile.spec
