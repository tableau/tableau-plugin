#!/bin/sh
set -eu

PYTHON_BIN="${PYTHON_BIN:-python3}"
PYTHON_TAG="$(
  "$PYTHON_BIN" -c \
    'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
)"
VENV_PATH="$PLUGIN_DATA/validator-venv-$PYTHON_TAG"

if [ -x "$VENV_PATH/bin/python" ] &&
   "$VENV_PATH/bin/python" -c 'import lxml' >/dev/null 2>&1
then
  exit 0
fi

"$PYTHON_BIN" -m venv "$VENV_PATH"
"$VENV_PATH/bin/python" -m pip install \
  --disable-pip-version-check \
  --no-input \
  -r "$PLUGIN_ROOT/scripts/requirements.txt"