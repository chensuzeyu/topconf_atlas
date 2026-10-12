#!/usr/bin/env bash
set -euo pipefail
ATLAS_PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ATLAS_PROJECT_DIR"
cd "$ATLAS_PROJECT_DIR"
exec "$ATLAS_PROJECT_DIR/.venv/bin/python" -m atlas "$@"
