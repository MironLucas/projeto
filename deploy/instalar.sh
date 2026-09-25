#!/usr/bin/env bash
# Instala o Nexora numa VPS Linux (rodar como root): Docker + Postgres + Caddy (HTTPS automático).
# Uso: bash instalar.sh
set -euo pipefail

PASTA=/opt/nexora
REPOSITORIO=https://github.com/MironLucas/projeto.git
RAMO=${RAMO:-claude/zen-brown-gfqhb4}

if [ "$(id -u)" -ne 0 ]; then
  echo "Rode como root (ex.: sudo bash instalar.sh)." >&2
  exit 1
fi

echo "==> Verificando se as portas 80 e 443 estão livres"
if ss -ltnp 2>/dev/null | grep -E ':(80|443)\s' | grep -vq docker; then
  echo "Algo já usa a porta 80 ou 443 nesta VPS:" >&2
  ss -ltnp | grep -E ':(80|443)\s' >&2
  echo "Pare esse serviço (ex.: systemctl disable --now nginx apache2) e rode o script de novo." >&2
  exit 1
fi

echo "==> Instalando pacotes básicos"
if command -v apt-get >/dev/null; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    git curl openssl ca-certificates ufw fail2ban unattended-upgrades >/dev/null
fi

echo "==> Segurança básica: firewall (SSH, 80 e 443), fail2ban e atualizações automáticas"
# O SSH é liberado antes de ligar o firewall para não trancar o acesso à VPS.
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
systemctl enable --now fail2ban >/dev/null 2>&1 || true
dpkg-reconfigure -f noninteractive unattended-upgrades >/dev/null 2>&1 || true

echo "==> Instalando o Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker >/dev/null 2>&1 || true

echo "==> Baixando o código"
if [ -d "$PASTA/.git" ]; then
  git -C "$PASTA" fetch -q origin "$RAMO"
  git -C "$PASTA" checkout -q "$RAMO"
  git -C "$PASTA" pull -q --ff-only origin "$RAMO"
else
  git clone -q --branch "$RAMO" "$REPOSITORIO" "$PASTA"
fi
cd "$PASTA"

PRIMEIRA_INSTALACAO=0
if [ ! -f .env ]; then
  PRIMEIRA_INSTALACAO=1
  echo "==> Configuração (fica salva em $PASTA/.env)"
  read -rp "Domínio do Nexora (ex.: nexora.seudominio.com.br): " DOMINIO
  read -rp "Instagram App ID: " INSTAGRAM_ID
  read -rsp "Instagram App Secret (não aparece enquanto digita): " INSTAGRAM_SECRET
  echo
  cat > .env <<CONFIG
DOMINIO=$DOMINIO
SECRET_KEY=$(openssl rand -hex 32)
DEBUG=False
ALLOWED_HOSTS=$DOMINIO
CSRF_TRUSTED_ORIGINS=https://$DOMINIO
POSTGRES_PASSWORD=$(openssl rand -hex 24)
INSTAGRAM_CLIENT_ID=$INSTAGRAM_ID
INSTAGRAM_CLIENT_SECRET=$INSTAGRAM_SECRET
INSTAGRAM_REDIRECT_URI=https://$DOMINIO/instagram/callback/
CONFIG
  chmod 600 .env
fi

echo "==> Construindo e subindo (pode levar alguns minutos na primeira vez)"
docker compose build -q
docker compose up -d db
docker compose run --rm web python manage.py migrate --noinput
docker compose up -d

echo "==> Agendando backup diário do banco (03:00)"
chmod +x deploy/*.sh
echo "0 3 * * * root $PASTA/deploy/backup.sh >> /var/log/nexora-backup.log 2>&1" > /etc/cron.d/nexora-backup

if [ "$PRIMEIRA_INSTALACAO" -eq 1 ]; then
  echo
  echo "==> Defina a NOVA senha do usuário mironlucas (a senha inicial está no código público)"
  docker compose run --rm web python manage.py changepassword mironlucas
fi

DOMINIO=$(grep '^DOMINIO=' .env | cut -d= -f2)
echo
echo "Pronto! Acesse https://$DOMINIO"
echo "Se o HTTPS ainda não abrir, confira se o domínio aponta para o IP desta VPS (registro A)."
