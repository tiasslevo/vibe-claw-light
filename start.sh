#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$project_root"
if [[ $# -eq 0 ]]; then set -- start; fi
if [[ -x "$project_root/.venv/bin/python" ]]; then
  exec "$project_root/.venv/bin/python" "$project_root/run.py" "$@"
fi
uv_executable="${UV_INSTALL_DIR:-$HOME/.local/bin}/uv"
if [[ ! -x "$uv_executable" ]]; then
  uv_executable="$(command -v uv || true)"
fi
if [[ -z "$uv_executable" ]]; then
  printf 'Environnement introuvable. Lance bash scripts/install.sh une premiere fois.\n' >&2
  exit 1
fi
exec "$uv_executable" run --python 3.11 "$project_root/run.py" "$@"
