#!/bin/sh
# Run a script from this directory in the extract venv, creating it on first use.
#
# Usage: sh hyper_py.sh [--with snowflake|databricks|trino[,...]] SCRIPT.py [ARGS...]
#
# The Hyper API is ~300 MB installed, so it is installed lazily here rather than
# in the SessionStart bootstrap. --with adds a warehouse connector.
set -eu

PYTHON_BIN="${PYTHON_BIN:-python3}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
DATA_DIR="${PLUGIN_DATA:-${CLAUDE_PLUGIN_DATA:-$HOME/.cache/tableau-plugin}}"
PYTHON_TAG="$(
  "$PYTHON_BIN" -c \
    'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
)"
VENV_PATH="$DATA_DIR/hyper-venv-$PYTHON_TAG"
PIP="$VENV_PATH/bin/python -m pip install --disable-pip-version-check --no-input -q"

EXTRAS=""
if [ "${1:-}" = "--with" ]; then
  EXTRAS="$2"
  shift 2
fi
[ $# -ge 1 ] || { echo "usage: hyper_py.sh [--with CONNECTORS] SCRIPT.py [ARGS...]" >&2; exit 2; }

if ! { [ -x "$VENV_PATH/bin/python" ] &&
       "$VENV_PATH/bin/python" -c 'import tableauhyperapi, pyarrow' >/dev/null 2>&1; }
then
  echo "Installing the Hyper API into $VENV_PATH (one time, ~90 MB download)..." >&2
  mkdir -p "$DATA_DIR"
  "$PYTHON_BIN" -m venv "$VENV_PATH"
  if ! $PIP -r "$SCRIPT_DIR/requirements.txt" >&2; then
    echo "✗ Could not install tableauhyperapi. It ships only for macOS, Linux x86_64 and Windows x64;" \
         "arm64 Linux/Windows (e.g. Docker on Apple Silicon) is not supported." >&2
    exit 1
  fi
fi

for extra in $(echo "$EXTRAS" | tr ',' ' '); do
  case "$extra" in
    snowflake)  mod=snowflake.connector; pkg="snowflake-connector-python" ;;
    databricks) mod=databricks.sql;      pkg="databricks-sql-connector" ;;
    trino)      mod=trino;               pkg="trino" ;;
    *) echo "✗ unknown connector '$extra' (snowflake, databricks, trino)" >&2; exit 2 ;;
  esac
  "$VENV_PATH/bin/python" -c "import $mod" >/dev/null 2>&1 || $PIP "$pkg" >&2
done

script="$1"
shift
exec "$VENV_PATH/bin/python" -I "$SCRIPT_DIR/$script" "$@"
