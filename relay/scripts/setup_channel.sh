#!/usr/bin/env bash
# Da de alta en Supabase el canal de WhatsApp de un cliente (tabla
# `channels`), para que el relay sepa a que account_id pertenece cada
# webhook entrante. Idempotente: si el canal ya existe, no lo duplica.
#
# Corre ESTO en el servidor (nunca fuera) -- lee los secretos directo de los
# archivos .env locales del servidor, nunca los imprime.
#
# Hallazgo de la una revisión de código posterior (2026-08-08): antes este script
# tenia "demo" y "Demo" hardcodeados -- onboardear un cliente nuevo
# significaba editar el script a mano. Ahora recibe el profile y el nombre
# de cuenta como argumentos.
#
# Uso: bash setup_channel.sh <profile_name> <account_name>
# Ejemplo: bash setup_channel.sh demo Demo
set -euo pipefail

PROFILE_NAME="${1:?Uso: setup_channel.sh <profile_name> <account_name> -- ej. setup_channel.sh demo Demo}"
ACCOUNT_NAME="${2:?Uso: setup_channel.sh <profile_name> <account_name> -- ej. setup_channel.sh demo Demo}"

HERMES_ENV="/root/.hermes/profiles/${PROFILE_NAME}/.env"
RELAY_ENV=/root/paulet-desk/relay/.env

PHONE_NUMBER_ID=$(grep -oP '^WHATSAPP_CLOUD_PHONE_NUMBER_ID=\K.*' "$HERMES_ENV")
SUPABASE_URL=$(grep -oP '^SUPABASE_URL=\K.*' "$RELAY_ENV")
SUPABASE_KEY=$(grep -oP '^SUPABASE_SERVICE_ROLE_KEY=\K.*' "$RELAY_ENV")

ACCOUNT_ID=$(curl -s "$SUPABASE_URL/rest/v1/accounts?name=eq.$ACCOUNT_NAME&select=id" \
  -H "apikey: $SUPABASE_KEY" -H "Authorization: Bearer $SUPABASE_KEY" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")

echo "account_id ($ACCOUNT_NAME): $ACCOUNT_ID"

EXISTING_COUNT=$(curl -s "$SUPABASE_URL/rest/v1/channels?phone_number_id=eq.$PHONE_NUMBER_ID&select=id" \
  -H "apikey: $SUPABASE_KEY" -H "Authorization: Bearer $SUPABASE_KEY" \
  | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")

if [ "$EXISTING_COUNT" == "0" ]; then
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$SUPABASE_URL/rest/v1/channels" \
    -H "apikey: $SUPABASE_KEY" -H "Authorization: Bearer $SUPABASE_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"account_id\": \"$ACCOUNT_ID\", \"phone_number_id\": \"$PHONE_NUMBER_ID\"}")
  echo "canal creado, status HTTP: $STATUS"
else
  echo "canal ya existia (count=$EXISTING_COUNT), no se duplico"
fi
