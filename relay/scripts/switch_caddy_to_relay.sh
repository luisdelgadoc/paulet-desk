#!/usr/bin/env bash
# Fase 4: apunta demo.paulet.tech al relay (localhost:8091) en vez de
# directo a Hermes. La URL publica no cambia -- Meta no necesita re-verificar
# nada. Ver scripts/rollback_caddy.sh para revertir esto.
set -euo pipefail

# Hallazgo de la Fase 5: antes esto exponia TODO el relay al publico (se
# confirmo probando /health via el dominio publico en la Fase 4 -- respondio
# 200 desde internet). Con un endpoint interno nuevo (/internal/*, para el
# hook de salida de Hermes) eso deja de ser tolerable -- restringido a solo
# la ruta que Meta realmente necesita llamar.
cat > /etc/caddy/Caddyfile <<'EOF'
demo.paulet.tech {
    handle /whatsapp/webhook {
        reverse_proxy localhost:8091
    }
    handle {
        respond 404
    }
}
EOF

caddy reload --config /etc/caddy/Caddyfile
echo "Caddy apuntando al relay: demo.paulet.tech/whatsapp/webhook -> localhost:8091 (unica ruta publica)"
