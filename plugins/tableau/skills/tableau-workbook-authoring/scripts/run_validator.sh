#!/bin/sh
set -eu

PYTHON_BIN="${PYTHON_BIN:-python3}"
PYTHON_TAG="$(
  "$PYTHON_BIN" -c \
    'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
)"
VENV_PATH="$PLUGIN_DATA/validator-venv-$PYTHON_TAG"

exec "$VENV_PATH/bin/python" \
  "$PLUGIN_ROOT/scripts/validate_workbook.py" "$@"