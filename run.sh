#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

command -v docker >/dev/null 2>&1 || { echo "Docker is not installed or is not available on PATH." >&2; exit 1; }
[ -f .env ] || { echo "Missing .env file. Copy .env.example to .env and set DISCORD_TOKEN." >&2; exit 1; }

image_name="antipulen-bot"
container_name="antipulen-bot"

docker build --tag "$image_name" .
docker rm --force "$container_name" >/dev/null 2>&1 || true
docker run --rm --name "$container_name" --env-file .env "$image_name"
