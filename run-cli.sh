#!/usr/bin/env bash
# Startet die Transkriptions-CLI im virtuellen Environment.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
    echo "Virtuelles Environment nicht gefunden. Bitte zuerst setup ausführen:"
    echo "  python3 -m venv .venv"
    echo "  source .venv/bin/activate && pip install -e '.[dev]'"
    exit 1
fi

source .venv/bin/activate
exec bort "$@"
