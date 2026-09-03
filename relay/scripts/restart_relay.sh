#!/usr/bin/env bash
# Reinicia el relay via systemd -- SIGTERM ordenado, Restart=always como red
# de seguridad de systemd, sin ningun proceso manual paralelo.
#
# Version anterior de este script (hasta la Fase 4): lanzaba un `nohup
# uvicorn ...` manual despues de matar el proceso. Eso era correcto SOLO
# mientras el relay corria fuera de systemd. Desde que se instalo
# paulet-relay.service, ese mismo script se volvio activamente peligroso: si
# alguien lo corria, systemd (que ya administra el puerto 8091 con
# Restart=always) entraba en crash loop contra el proceso nohup huerfano
# compitiendo por el mismo puerto. Hallazgo de revision de la Fase 4 -- ver
# ARCHITECTURE.md.
#
# Uso: bash scripts/restart_relay.sh
set -euo pipefail

RELAY_PORT=$(grep -oP '^RELAY_PORT=\K.*' /root/paulet-desk/relay/.env)

echo "Reiniciando paulet-relay.service (SIGTERM ordenado, systemd)..."
systemctl --user restart paulet-relay.service

for _ in $(seq 1 10); do
  if curl -sf "http://localhost:${RELAY_PORT}/health" > /dev/null 2>&1; then
    echo "Relay reiniciado OK -- responde en el puerto ${RELAY_PORT}."
    exit 0
  fi
  sleep 0.5
done

echo "ADVERTENCIA: el relay no respondio /health en 5s tras el reinicio."
echo "Revisar: systemctl --user status paulet-relay.service"
echo "Revisar: journalctl --user -u paulet-relay -n 50 --no-pager"
exit 1
