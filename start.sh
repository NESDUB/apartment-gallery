#!/usr/bin/env bash
# One-command setup + launch: creates a local virtual environment the
# first time (installing homeharvest/requests into it, needed only for
# live search), reuses it on every later run, then starts the server.
#
#   ./start.sh
#
# The snapshot gallery works immediately either way; live search becomes
# available once the one-time dependency install finishes. Nothing here
# touches system Python or any other project's environment — the venv
# lives entirely inside this folder, at .venv/.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 was not found. Install Python 3 (e.g. from python.org) and run this again." >&2
  exit 1
fi

VENV_DIR=".venv"
MARKER="$VENV_DIR/.requirements-installed"

if [ ! -d "$VENV_DIR" ]; then
  echo "First run: creating a local Python environment in $VENV_DIR ..."
  python3 -m venv "$VENV_DIR"
fi

if [ ! -f "$MARKER" ] || [ "requirements.txt" -nt "$MARKER" ]; then
  echo "Installing live-search dependencies (one-time; the snapshot gallery doesn't need this) ..."
  "$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip
  if "$VENV_DIR/bin/python" -m pip install --quiet -r requirements.txt; then
    touch "$MARKER"
  else
    echo "Could not install live-search dependencies — continuing with the snapshot gallery only." >&2
    echo "(Live search will show a clear error in the UI instead of crashing anything.)" >&2
  fi
fi

exec "$VENV_DIR/bin/python" server.py "$@"
