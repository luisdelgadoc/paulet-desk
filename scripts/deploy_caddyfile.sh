#!/usr/bin/env bash
# Aplica desk/Caddyfile (la fuente de verdad, versionada) como la config real
# de Caddy en el servidor, y recarga sin downtime.
#
# Uso (en el servidor, con desk/Caddyfile ya copiado a /root/paulet-desk/Caddyfile
# via scp):
#   bash scripts/deploy_caddyfile.sh
set -euo pipefail

cp /root/paulet-desk/Caddyfile /etc/caddy/Caddyfile
caddy reload --config /etc/caddy/Caddyfile
echo "Caddyfile aplicado desde desk/Caddyfile (fuente de verdad versionada)."
