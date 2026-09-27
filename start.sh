#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/python ]]; then
  echo 'Install Python dependencies first: uv sync --frozen --all-extras' >&2
  exit 1
fi
exec .venv/bin/python tools/local_app.py start
