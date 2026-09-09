#!/bin/sh
set -eu

PYTHON_BIN="${PYTHON_BIN:-python3}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON_TAG="$(
  "$PYTHON_BIN" -c \
    'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
)"
VENV_PATH="$PLUGIN_DATA/validator-venv-$PYTHON_TAG"

exec "$VENV_PATH/bin/python" \
  "$SCRIPT_DIR/validate_workbook.py" "$@"
