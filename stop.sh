#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/python ]]; then
  echo 'The local Python environment is missing; see README.md for setup.' >&2
  exit 1
fi
exec .venv/bin/python tools/local_app.py stop
