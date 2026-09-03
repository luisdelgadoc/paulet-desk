"""Envio de mensajes salientes via WhatsApp Cloud API (Graph API) -- Fase 8.

Distinto de app/hermes_client.py (reenvia el webhook ENTRANTE a Hermes) y de
app/whatsapp.py (valida la firma del webhook ENTRANTE de Meta) -- este es el
unico modulo que le habla a Meta para ENVIAR, no para recibir. Antes de la
Fase 8 solo Hermes enviaba (con sus propias credenciales); el relay necesita
las suyas propias para el envio saliente del humano.
"""

import httpx

from app.config import settings

GRAPH_API_VERSION = "v21.0"


class WhatsAppSendError(Exception):
    """Graph API rechazo el envio -- el caller debe mostrarle un error claro
    al humano (ventana de 24h vencida, token expirado, numero invalido),
    nunca reintentar a ciegas ni tragarselo en silencio."""


async def send_whatsapp_text(phone: str, message: str) -> str:
    """Envia un mensaje de texto libre por Graph API. Devuelve el wamid real
    que Meta le asigna -- a diferencia de la respuesta del agente (Fase 5, que
    no tiene wamid porque el hook de Hermes no lo expone), un mensaje humano
    enviado desde aca SI puede llevar el wamid real de Meta.

    Lanza WhatsAppSendError si Meta lo rechaza. No reintenta -- un reintento
    automatico de un mensaje HUMANO (a diferencia de un webhook duplicado)
    podria mandarlo dos veces por error del lado de Meta, no del relay.
    """
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{settings.whatsapp_phone_number_id}/messages"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": phone,
                    "type": "text",
                    "text": {"body": message},
                },
            )
    except httpx.HTTPError as exc:
        raise WhatsAppSendError(f"No se pudo contactar a Graph API: {exc}") from exc

    if resp.status_code >= 400:
        raise WhatsAppSendError(f"Graph API rechazo el envio: HTTP {resp.status_code} {resp.text[:300]}")

    data = resp.json()
    return data["messages"][0]["id"]
