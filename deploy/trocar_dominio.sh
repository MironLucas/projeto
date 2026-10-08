#!/usr/bin/env bash
# Troca o domínio do Hopkins sem mexer no banco nem nas mídias; o domínio antigo passa a redirecionar para o novo.
# Uso: bash /opt/nexora/deploy/trocar_dominio.sh hopkins.com.br
set -euo pipefail

cd "$(dirname "$0")/.."
NOVO="${1:-}"
NOVO="${NOVO#https://}"; NOVO="${NOVO#http://}"; NOVO="${NOVO%%/*}"; NOVO="${NOVO#www.}"
if [ -z "$NOVO" ]; then
  echo "Uso: bash deploy/trocar_dominio.sh hopkins.com.br"
  exit 1
fi
ATUAL=$(grep '^DOMINIO=' .env | cut -d= -f2)
if [ "$NOVO" = "$ATUAL" ]; then
  echo "O domínio já é $NOVO. Nada a fazer."
  exit 0
fi

echo "==> Conferindo se $NOVO já aponta para esta VPS"
IP_VPS=$(curl -s4 --max-time 10 https://api.ipify.org || true)
IP_NOVO=$(getent ahostsv4 "$NOVO" | awk 'NR==1 {print $1}' || true)
if [ -z "$IP_NOVO" ] || { [ -n "$IP_VPS" ] && [ "$IP_NOVO" != "$IP_VPS" ]; }; then
  echo "O domínio $NOVO ainda não aponta para esta VPS (domínio: ${IP_NOVO:-sem IP}, VPS: ${IP_VPS:-?})."
  echo "Ajuste o registro A no DNS da Hostinger, espere propagar e rode de novo. Nada foi alterado."
  exit 1
fi
echo "    $NOVO -> $IP_NOVO (ok)"

echo "==> Backup do banco e das mídias antes da troca"
bash deploy/backup.sh

echo "==> Atualizando a configuração (.env); a anterior fica em .env.antes-da-troca"
cp -p .env .env.antes-da-troca
definir() {
  if grep -q "^$1=" .env; then
    sed -i "s|^$1=.*|$1=$2|" .env
  else
    echo "$1=$2" >> .env
  fi
}
definir DOMINIO "$NOVO"
definir DOMINIO_ANTIGO "$ATUAL"
definir ALLOWED_HOSTS "$NOVO"
definir CSRF_TRUSTED_ORIGINS "https://$NOVO"
definir INSTAGRAM_REDIRECT_URI "https://$NOVO/instagram/callback/"

echo "==> Reiniciando o site com o domínio novo (o banco não é reiniciado)"
docker compose up -d --force-recreate --no-deps web caddy

echo
echo "Pronto! O Hopkins agora responde em https://$NOVO"
echo "Quem acessar https://$ATUAL é levado para o mesmo endereço em https://$NOVO."
echo "O certificado HTTPS do domínio novo é emitido sozinho no primeiro acesso (pode levar alguns segundos)."
echo "Para desfazer: cp .env.antes-da-troca .env && docker compose up -d --force-recreate --no-deps web caddy"
