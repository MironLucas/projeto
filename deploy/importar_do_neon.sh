#!/usr/bin/env bash
# Traz os dados do banco usado no Render (Neon) para o Postgres desta VPS.
# ATENÇÃO: substitui tudo o que já existe no banco da VPS.
set -euo pipefail

cd "$(dirname "$0")/.."

read -rp "Isto APAGA os dados atuais do Nexora nesta VPS e copia os do Neon. Continuar? (digite sim) " CONFIRMA
[ "$CONFIRMA" = "sim" ] || { echo "Cancelado."; exit 1; }
read -rsp "Cole a DATABASE_URL do Neon (não aparece enquanto digita): " URL_NEON
echo

echo "==> Guardando uma cópia do banco atual da VPS antes de substituir"
./deploy/backup.sh

docker compose stop web
docker compose exec -T db psql -q -U nexora -d nexora -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'

echo "==> Copiando os dados do Neon"
docker run --rm postgres:17-alpine pg_dump --no-owner --no-privileges "$URL_NEON" \
  | docker compose exec -T db psql -q -U nexora -d nexora -v ON_ERROR_STOP=1

docker compose run --rm web python manage.py migrate --noinput
docker compose start web

echo
echo "==> Os dados vieram com a senha antiga do mironlucas. Defina a nova senha:"
docker compose run --rm web python manage.py changepassword mironlucas
echo "Importação concluída."
