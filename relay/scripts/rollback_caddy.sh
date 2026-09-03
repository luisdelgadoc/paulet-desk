#!/usr/bin/env bash
# Interruptor de reversa de la Fase 4: si algo sale mal con el relay en
# produccion, esto vuelve el Caddyfile a apuntar directo a Hermes (el estado
# de antes de esta fase) y recarga Caddy sin downtime.
#
# Uso: bash scripts/rollback_caddy.sh
set -euo pipefail

cat > /etc/caddy/Caddyfile <<'EOF'
demo.paulet.tech {
    reverse_proxy localhost:8090
}
EOF

caddy reload --config /etc/caddy/Caddyfile
echo "Caddy revertido: demo.paulet.tech -> localhost:8090 (directo a Hermes, relay fuera del camino)"
