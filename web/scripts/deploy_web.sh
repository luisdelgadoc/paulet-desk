#!/usr/bin/env bash
# La operacion que se repite cada vez que se toca desk/web/: con el codigo
# nuevo YA en el arbol de /root/paulet-desk/web, instalar dependencias,
# construir, reiniciar, y verificar que quedo sano -- todo en un paso.
#
# ⚠️ Si el codigo nuevo todavia no esta copiado (el caso normal: cambiaste
# algo en app/, components/ o lib/ y necesitas subirlo), usar
# scripts/redeploy.sh en vez de este directo -- ese se encarga de limpiar
# rutas de Next.js viejas ANTES de extraer el tar nuevo (ver el porque en su
# propio comentario; es la correccion a un bug real que ya paso dos veces).
# Llamar a este script a secas solo tiene sentido si el codigo ya esta
# correctamente en el arbol (ej. despues de correr redeploy.sh a mano en
# pasos, o si solo cambio algo fuera del codigo -- .env.local, el unit de
# systemd -- y no hace falta tocar app/components/lib).
#
# Hallazgo de la revision conjunta Fase 5+6 (una revisión posterior, 2026-08-07): la Fase 6 se
# desplego con comandos sueltos a mano (scp + npm install + npm run build +
# systemctl), y eso fue exactamente lo que dejo pasar el bug real de esa
# fase: el ExecStart del unit apuntaba a /usr/bin/npm, que no existe en este
# servidor. Este script valida esa ruta (y las demas rutas absolutas del unit)
# ANTES de instalar/reiniciar, en vez de descubrirlas con el servicio caido.
#
# Uso (en el servidor, despues de haber copiado el codigo nuevo):
#   bash scripts/deploy_web.sh
set -euo pipefail

cd /root/paulet-desk/web

UNIT=systemd/paulet-desk-web.service
INSTALLED_UNIT=/root/.config/systemd/user/paulet-desk-web.service

echo "--- Validando rutas absolutas de $UNIT ---"
EXEC_BIN=$(grep -oP '^ExecStart=\K\S+' "$UNIT")
WORKDIR=$(grep -oP '^WorkingDirectory=\K.*' "$UNIT")
# Anclado a la linea real Environment="PORT=..." (no a "PORT=\d+" suelto) --
# el comentario de arriba en este mismo archivo menciona "PORT=3001" en
# prosa, y un patron sin anclar lo capturaba tambien, produciendo un valor
# con 2 lineas y una URL invalida en el curl de mas abajo. Encontrado al
# desplegar esto mismo la primera vez.
PORT=$(grep -oP '^Environment="PORT=\K[0-9]+' "$UNIT")

if [ ! -x "$EXEC_BIN" ]; then
  echo "‼️  $EXEC_BIN (ExecStart de $UNIT) no existe o no es ejecutable en este servidor."
  echo "    Corregir el unit ANTES de instalar/reiniciar -- systemd fallaria con 203/EXEC."
  exit 1
fi
if [ ! -d "$WORKDIR" ]; then
  echo "‼️  $WORKDIR (WorkingDirectory de $UNIT) no existe."
  exit 1
fi
echo "OK: $EXEC_BIN y $WORKDIR existen, puerto declarado $PORT."

echo "--- Instalando dependencias y construyendo ---"
npm install
npm run build

echo "--- Instalando/actualizando el unit y reiniciando ---"
cp "$UNIT" "$INSTALLED_UNIT"
systemctl --user daemon-reload
systemctl --user enable --now paulet-desk-web.service
systemctl --user restart paulet-desk-web.service

for _ in $(seq 1 20); do
  if curl -sf "http://localhost:${PORT}/login" > /dev/null 2>&1; then
    echo "Bandeja web reiniciada OK -- responde en el puerto ${PORT}."
    exit 0
  fi
  sleep 0.5
done

echo "ADVERTENCIA: la bandeja no respondio /login en 10s tras el reinicio."
echo "Revisar: systemctl --user status paulet-desk-web.service"
echo "Revisar: journalctl --user -u paulet-desk-web -n 50 --no-pager"
exit 1
