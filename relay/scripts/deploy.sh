#!/usr/bin/env bash
# La operacion que se repite en cada fase de aqui en adelante: codigo nuevo
# ya copiado a /root/paulet-desk/relay (via scp, desde fuera de este script),
# correr los tests, reiniciar, y verificar que quedo sano -- todo en un solo
# paso, en vez de comandos sueltos a mano cada vez (hallazgo de revision de
# la Fase 4: el switch de Caddy tenia verificacion, pero el deploy real de
# codigo -- que se repite en cada fase -- no tenia ninguna).
#
# Si los tests fallan, NO toca el servicio en produccion -- se queda
# corriendo el codigo anterior.
#
# Uso (en el servidor, despues de haber hecho scp del codigo nuevo):
#   bash scripts/deploy.sh
set -euo pipefail

cd /root/paulet-desk/relay

echo "--- Corriendo tests antes de tocar produccion ---"
if ! ./venv/bin/pytest tests/ -q; then
  echo "‼️  Tests fallaron -- NO se reinicia el servicio. Produccion sigue con el codigo anterior."
  exit 1
fi

echo "--- Tests OK. Reiniciando el servicio ---"
bash scripts/restart_relay.sh
