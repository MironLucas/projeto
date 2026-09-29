#!/usr/bin/env bash
# Salva uma cópia do banco em /opt/nexora/backups (últimos 14 dias) e copia as mídias novas para backups/midias.
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p backups
ARQUIVO="backups/nexora-$(date +%Y-%m-%d-%H%M).sql.gz"

docker compose exec -T db pg_dump -U nexora -d nexora | gzip > "$ARQUIVO"
find backups -name 'nexora-*.sql.gz' -mtime +14 -delete

# Imagens e vídeos da programação ficam fora do banco: copia só o que ainda não está na cópia.
if [ -d media ]; then
  mkdir -p backups/midias
  cp -ru media/. backups/midias/
fi
echo "$(date '+%F %T') backup salvo em $ARQUIVO"
