#!/usr/bin/env bash
# Punto de entrada UNICO para desplegar codigo nuevo de desk/web/ al servidor --
# reemplaza el habito manual de "scp + borrar rutas viejas a mano + tar xf"
# que ya causo un bug real en produccion (Fase 6, 2026-08-08: Next.js dejo
# rutas viejas compitiendo por la misma URL) y que se volvio a resolver a
# mano en la Fase Contactos (2026-08-10, al mover ConversationSidebar a un
# route group nuevo). Hallazgo de la una revisión de código posterior de esa fase: "es la
# segunda vez que este proyecto mueve rutas de Next.js y la primera se
# resolvio a mano en caliente -- corregir el script, no repetir el arreglo
# manual".
#
# Causa raiz real: `tar xzf` NO borra archivos que ya no existen en el tar
# nuevo -- si una ruta se movio o se elimino en el codigo, la version vieja
# se queda en el servidor compitiendo con la nueva por la misma URL, y
# `next build` revienta con un conflicto de rutas paralelas (o peor, arranca
# con tipos generados obsoletos en `.next/` y falla de formas mas dificiles
# de diagnosticar). Depender de acordarse de hacer `rm -rf` de las rutas
# exactas que cambiaron, cada vez, a mano, es exactamente el tipo de cosa
# que este proyecto dejo de hacer con `deploy.sh`/`deploy_web.sh` para todo
# lo demas -- esto le faltaba a esa disciplina.
#
# Por que "borrar el arbol de fuente completo y volver a extraer" en vez de
# `rsync --delete`: el tar que arma este proyecto siempre empaqueta el arbol
# COMPLETO de app/, components/, lib/ (nunca un diff parcial) -- no hay
# ninguna ganancia real de rsync si el tar completo ya viaja por scp de
# todas formas. Un `rm -rf` + extraer es mas simple de razonar y mas dificil
# de hacer a medias que sincronizar selectivamente.
#
# Uso (en el servidor, con el tar ya subido por scp a, por ejemplo,
# /root/web_deploy.tar.gz):
#   bash scripts/redeploy.sh /root/web_deploy.tar.gz
set -euo pipefail

TARBALL="${1:?Uso: redeploy.sh <ruta-al-tar.gz>}"
cd /root/paulet-desk/web

if [ ! -f "$TARBALL" ]; then
  echo "‼️  No existe $TARBALL"
  exit 1
fi

# Alcance a proposito: solo los directorios que reescribe CADA deploy y que
# de verdad participan del ruteo/build de Next.js -- no toca node_modules/
# (no viaja en el tar, lo reinstala npm install en deploy_web.sh),
# .env.local (nunca viaja en el tar -- ver exclusion explicita al empaquetar
# en la sesion de deploy), ni systemd/ (se reinstala aparte, con su propio
# paso, en deploy_web.sh).
echo "--- Limpiando app/, components/, lib/ y .next/ (evita rutas de Next.js viejas compitiendo con las nuevas) ---"
rm -rf app components lib .next

echo "--- Extrayendo $TARBALL ---"
tar -xzf "$TARBALL" -C .
rm -f "$TARBALL"

echo "--- Delegando a deploy_web.sh (install + build + restart + healthcheck) ---"
exec bash scripts/deploy_web.sh
