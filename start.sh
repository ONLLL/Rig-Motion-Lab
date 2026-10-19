#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON=${PYTHON:-python3}
"$PYTHON" -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ is required"'
if [ ! -d .venv ]; then "$PYTHON" -m venv .venv; fi
.venv/bin/python -m pip install -r requirements.txt
printf '\nRig Motion Lab: http://127.0.0.1:8020\nKeep this terminal open. Ctrl+C to stop.\n'
.venv/bin/python -m uvicorn lab.main:app --host 127.0.0.1 --port 8020 --workers 1
