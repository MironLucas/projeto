#!/usr/bin/env bash
# Atualiza o Nexora com a versão mais nova do código. Uso: bash /opt/nexora/deploy/atualizar.sh
set -euo pipefail

cd "$(dirname "$0")/.."
RAMO=$(git rev-parse --abbrev-ref HEAD)

git pull -q --ff-only origin "$RAMO"
docker compose build -q
docker compose run --rm web python manage.py migrate --noinput
docker compose up -d
docker image prune -f >/dev/null
echo "Nexora atualizado ($(git log -1 --format='%h %s'))."
