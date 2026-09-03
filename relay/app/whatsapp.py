"""Validacion de firma y parseo del payload de WhatsApp Cloud API (Meta).

Todo lo que toca la firma HMAC trabaja sobre bytes crudos — nunca sobre el
dict ya parseado. Meta firma el body exacto que mandaron; si nosotros lo
re-serializamos (json.dumps de vuelta) los bytes cambian y la firma deja de
coincidir aunque el contenido sea "el mismo". Ver nota en ARCHITECTURE.md.
"""

import hashlib
import hmac
from typing import Any


def verify_signature(raw_body: bytes, signature_header: str | None, app_secret: str) -> bool:
    """Verifica el header X-Hub-Signature-256 contra el body crudo.

    Meta manda 'sha256=<hex>'. Se compara con hmac.compare_digest (tiempo
    constante) para no filtrar informacion por un ataque de timing.
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    provided_hex = signature_header.split("=", 1)[1]
    expected_hex = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    try:
        return hmac.compare_digest(expected_hex, provided_hex)
    except TypeError:
        # Header con caracteres no-ASCII u otro formato invalido -- rechazar
        # como firma invalida (403), no dejar que reviente como 500. Esto es
        # el camino de seguridad del endpoint, no debe poder tumbarlo un
        # header malformado.
        return False


def parse_incoming_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extrae los mensajes entrantes reales de un payload de webhook de Meta.

    Un mismo payload puede traer 0 o varios mensajes (varios `entry`, varios
    `changes`, o varios `messages` dentro de un mismo `value`). Tambien puede
    traer solo `statuses` (confirmaciones de entrega/lectura) sin ningun
    mensaje nuevo -- esas se ignoran aqui, no son texto que el agente deba ver.

    Para tipos que no son texto (audio, imagen, video, documento, sticker),
    el body queda en None; en su lugar se captura media_id/media_mime (Fase
    10) -- el webhook de Meta solo trae el ID del archivo, no el archivo en
    si, hace falta una consulta aparte a Graph API para descargarlo (ver
    app/whatsapp_media.py).
    """
    out: list[dict[str, Any]] = []
    MEDIA_TYPES = {"audio", "image", "video", "document", "sticker"}

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            phone_number_id = value.get("metadata", {}).get("phone_number_id")

            # Mapa wa_id -> nombre de perfil, cuando Meta lo manda junto al mensaje.
            contact_names = {
                c.get("wa_id"): c.get("profile", {}).get("name")
                for c in value.get("contacts", [])
            }

            for msg in value.get("messages", []):
                msg_type = msg.get("type", "unknown")
                body = None
                media_id = None
                media_mime = None
                if msg_type == "text":
                    body = msg.get("text", {}).get("body")
                elif msg_type in MEDIA_TYPES:
                    media_obj = msg.get(msg_type, {})
                    media_id = media_obj.get("id")
                    media_mime = media_obj.get("mime_type")

                out.append({
                    "phone_number_id": phone_number_id,
                    "from_phone": msg.get("from"),
                    "contact_name": contact_names.get(msg.get("from")),
                    "wamid": msg.get("id"),
                    "timestamp": msg.get("timestamp"),
                    "type": msg_type,
                    "body": body,
                    "media_id": media_id,
                    "media_mime": media_mime,
                })

    return out
