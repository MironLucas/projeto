#!/usr/bin/env bash
# Salva uma cópia do banco em /opt/nexora/backups e mantém os últimos 14 dias.
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p backups
ARQUIVO="backups/nexora-$(date +%Y-%m-%d-%H%M).sql.gz"

docker compose exec -T db pg_dump -U nexora -d nexora | gzip > "$ARQUIVO"
find backups -name 'nexora-*.sql.gz' -mtime +14 -delete
echo "$(date '+%F %T') backup salvo em $ARQUIVO"
