#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if ! mountpoint -q /srv/ragplayground; then
  echo "The dedicated data volume is not mounted at /srv/ragplayground. Refusing to write to the boot disk." >&2
  exit 1
fi
if [[ ! -f .env.production ]] || [[ $(stat -c %a .env.production) != 600 ]]; then
  echo "Create .env.production with deploy/configure.py and keep its permissions at 0600." >&2
  exit 1
fi
exec docker compose --env-file .env.production -f compose.production.yaml "$@"
