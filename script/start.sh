#!/usr/bin/env bash
# Start the app in Docker: script/start.sh [docker compose up options, such as --detach]
# It listens on 127.0.0.1 at api_port from Terraform, or at $API_PORT if that's set.
set -euo pipefail

cd "$(dirname "$0")/.."

fail() {
  echo "error: $1" >&2
  exit 1
}

command -v docker >/dev/null || fail "Docker isn't installed: https://docs.docker.com/get-docker/"
docker compose version >/dev/null 2>&1 || fail "Docker Compose isn't available."

[ -f vendor/geolocate/src/geolocate.py ] ||
  fail "vendor/geolocate is empty. Run: git submodule update --init"

apply_hint="Run: terraform -chdir=infra init && terraform -chdir=infra apply (or tofu)"
[ -f .asset-risk.json ] || fail ".asset-risk.json is missing. $apply_hint"
[ -f vendor/geolocate/.geolocate.json ] ||
  fail "vendor/geolocate/.geolocate.json is missing. $apply_hint"

configured_port=$(sed -n 's/.*"api_port":[[:space:]]*\([0-9]*\).*/\1/p' .asset-risk.json)
API_PORT=${API_PORT:-${configured_port:-8000}}
HOST_UID=$(id -u)
HOST_GID=$(id -g)
export API_PORT HOST_UID HOST_GID

echo "Starting at http://127.0.0.1:${API_PORT}"
exec docker compose -f docker/compose.yml up --build "$@"
