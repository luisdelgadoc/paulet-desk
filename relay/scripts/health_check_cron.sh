#!/usr/bin/env bash
# Monitoreo minimo del relay Y de la bandeja web: pensado para correr cada 5
# min via cron. Si alguno no responde, avisa por Slack reusando las
# credenciales ya configuradas del gateway de analista_datos (`hermes send`
# es un POST directo con el bot token, no necesita LLM ni el agente
# corriendo).
#
# Hallazgo de revision de la Fase 4: con produccion real dependiendo de
# paulet-relay.service desde hoy, el primero en enterarse de una caida no
# puede ser un cliente reportando que el agente dejo de responder.
#
# Hallazgo de la revision conjunta Fase 5+6: la Fase 6 puso un segundo
# servicio en produccion (desk.paulet.tech) sin que nadie lo vigilara --
# agregado aca en vez de un script nuevo, mismo criterio de "una sola cosa
# que se repite" que ya se aplico al relay.
#
# Hallazgo de la una revisión de código posterior (2026-08-08) -- el mas grave de
# esa revision: si hermes-gateway-demo se cae, el relay sigue sano (el
# mensaje se persiste, la bandeja se ve normal), Meta no reintenta (ya
# recibio su 200), y el relay no reintenta (sin outbox, deuda aceptada) --
# el cliente escribe, el agente nunca responde, y NADA de lo que este script
# vigilaba hasta ahora lo detectaba. Agregado el chequeo del gateway.
# (app/hermes_client.py tambien alerta de inmediato cuando un reenvio
# puntual falla -- esto es la red de seguridad de la siguiente pasada del
# cron, por si esa alerta puntual se pierde o el relay mismo esta caido.)
#
# Instalar en crontab de root:
#   */5 * * * * /root/paulet-desk/relay/scripts/health_check_cron.sh
set -euo pipefail

RELAY_PORT=$(grep -oP '^RELAY_PORT=\K.*' /root/paulet-desk/relay/.env)
# Anclado a la linea real Environment="PORT=..." -- ver el comentario en
# desk/web/scripts/deploy_web.sh sobre por que un patron sin anclar rompe
# (el mismo archivo tiene "PORT=3001" tambien en un comentario de prosa).
WEB_PORT=$(grep -oP '^Environment="PORT=\K[0-9]+' /root/paulet-desk/web/systemd/paulet-desk-web.service)

if ! curl -sf "http://localhost:${RELAY_PORT}/health" > /dev/null 2>&1; then
  /usr/local/bin/hermes -p analista_datos send --to slack \
    "🔴 Paulet Desk Relay no responde /health (puerto ${RELAY_PORT}). Revisar: systemctl --user status paulet-relay.service"
fi

if ! curl -sf "http://localhost:${WEB_PORT}/login" > /dev/null 2>&1; then
  /usr/local/bin/hermes -p analista_datos send --to slack \
    "🔴 Paulet Desk (bandeja web) no responde /login (puerto ${WEB_PORT}). Revisar: systemctl --user status paulet-desk-web.service"
fi

# systemctl (no curl): Hermes no garantiza un endpoint /health generico en
# su puerto de gateway, y "esta activo segun systemd" es la senal que
# realmente importa aca -- si el proceso murio o esta en crash-loop, el
# webhook del agente dejo de recibir nada aunque el relay este perfectamente
# sano y siga reenviando en vano.
if ! systemctl --user is-active --quiet hermes-gateway-demo.service; then
  /usr/local/bin/hermes -p analista_datos send --to slack \
    "🔴 hermes-gateway-demo no esta activo -- el agente no esta respondiendo por WhatsApp. Revisar: systemctl --user status hermes-gateway-demo.service"
fi
