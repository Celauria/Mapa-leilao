#!/usr/bin/env bash
# Agenda o alerta de leilões todo dia às 7h40 (Mac/Linux). Rode uma vez: bash agendar_cron.sh
# Coloque TELEGRAM_* / SMTP_* num arquivo .env na pasta do projeto (o cron não lê seu .bashrc).
set -e
PASTA="$(cd "$(dirname "$0")" && pwd)"
LINHA="40 7 * * * cd \"$PASTA\" && set -a && [ -f .env ] && . ./.env; set +a; \"$PASTA/.venv/bin/python\" -m leiloes.cli alerta >> \"$PASTA/alerta.log\" 2>&1"
( crontab -l 2>/dev/null | grep -v "leiloes.cli alerta"; echo "$LINHA" ) | crontab -
echo "Agendado: todo dia 7h40. Log em $PASTA/alerta.log"
