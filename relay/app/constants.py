"""Unica fuente de verdad para valores de cableado que antes estaban repetidos
a mano en 4-5 archivos distintos (systemd, scripts de Caddy, scripts de
prueba, el propio main.py) -- hallazgo de revision de la Fase 4: esa
dispersion fue la causa raiz de que la ruta del webhook quedara al reves sin
que nada lo detectara.

Quien mas importa esta ruta la importa de aca. Ningun otro archivo debe
escribir el string "/whatsapp/webhook" de nuevo.
"""

# DEBE coincidir exactamente con la Callback URL registrada en el panel de
# Meta for Developers (WhatsApp > Configuration > Webhook) para este numero.
# Es un acoplamiento con un sistema EXTERNO que no vive en este repo -- si
# alguna vez cambia alli, Meta empieza a recibir 404 en silencio (asi se
# encontro el bug real de la Fase 4: los primeros 4 webhooks reales dieron
# 404 porque este valor no se habia verificado contra el dato real, se habia
# asumido). Antes de tocar esta linea, confirmar el valor real en el panel
# de Meta, no adivinar.
WHATSAPP_WEBHOOK_PATH = "/whatsapp/webhook"
