"""Descarga de media entrante desde WhatsApp Cloud API y subida a Supabase
Storage -- Fase 10.

Flujo: el webhook de Meta solo trae el media_id, nunca el archivo en si. Hay
que:
  1. GET /{media_id} (Graph API) -- Meta devuelve una URL temporal (expira en
     minutos, documentado por Meta) + el mime_type real.
  2. Descargar esos bytes con el MISMO Bearer token (la URL de Meta tambien
     requiere autenticacion, no es publica).
  3. Subir a Supabase Storage (bucket privado `whatsapp-media`, ver migracion
     005) via la service_role key -- mismo patron de credenciales que
     app/whatsapp_send.py, pero para bajar en vez de mandar.

Path de Storage: {account_id}/{wamid}.{ext} -- el account_id como primer
segmento es lo que la policy RLS de storage.objects usa para restringir la
lectura a miembros de esa cuenta (ver migracion 005, storage.foldername).
El navegador nunca recibe este path crudo como URL descargable -- pide una
signed URL bajo demanda, que Supabase solo entrega si la policy lo permite.
"""

import httpx

from app.config import settings
from app.media_paths import build_storage_path

GRAPH_API_VERSION = "v21.0"
STORAGE_BUCKET = "whatsapp-media"


class MediaDownloadError(Exception):
    """Meta o Supabase Storage rechazaron algun paso -- el caller decide si
    persistir el mensaje sin media_url (mejor eso que perder el mensaje
    completo)."""


async def download_and_store_media(
    media_id: str, account_id: str, wamid: str, fallback_mime: str | None
) -> tuple[str, str]:
    """Descarga el archivo de Meta y lo sube a Storage. Devuelve
    (storage_path, mime_type) -- storage_path es el PATH dentro del bucket,
    no una URL utilizable directo (el bucket es privado a proposito).

    Lanza MediaDownloadError si Meta o Storage rechazan algun paso -- no
    reintenta: un reintento automatico de una descarga de varios MB dentro
    del procesamiento de un webhook no vale el costo, mejor persistir el
    mensaje sin media_url y que quede visible en la bandeja como "[audio]"
    sin reproductor, que bloquear/demorar el resto del procesamiento.
    """
    async with httpx.AsyncClient(timeout=20.0) as client:
        meta_resp = await client.get(
            f"https://graph.facebook.com/{GRAPH_API_VERSION}/{media_id}",
            headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
        )
        if meta_resp.status_code >= 400:
            raise MediaDownloadError(
                f"Graph API rechazo la consulta del media {media_id}: HTTP {meta_resp.status_code}"
            )
        meta = meta_resp.json()
        media_url = meta.get("url")
        mime_type = meta.get("mime_type") or fallback_mime or "application/octet-stream"
        if not media_url:
            raise MediaDownloadError(f"Graph API no devolvio una URL de descarga para {media_id}")

        file_resp = await client.get(
            media_url, headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"}
        )
        if file_resp.status_code >= 400:
            raise MediaDownloadError(f"Fallo la descarga del archivo: HTTP {file_resp.status_code}")

        storage_path = build_storage_path(account_id, wamid, mime_type)
        upload_resp = await client.post(
            f"{settings.supabase_url}/storage/v1/object/{STORAGE_BUCKET}/{storage_path}",
            headers={
                # Bug real encontrado con audio real (2026-08-07): faltaba
                # 'apikey' aca -- Supabase Storage intenta parsear el
                # Authorization: Bearer como un JWT propio cuando falta el
                # header apikey que lo identifica como la service_role key
                # (formato nuevo sb_secret_..., no es un JWT), y lo rechaza
                # con "Invalid Compact JWS". Todo el resto del relay
                # (supabase_client.py) siempre manda los dos headers juntos
                # -- este era el unico lugar que no lo hacia.
                "apikey": settings.supabase_service_role_key,
                "Authorization": f"Bearer {settings.supabase_service_role_key}",
                "Content-Type": mime_type,
                "x-upsert": "true",
            },
            content=file_resp.content,
        )
        if upload_resp.status_code >= 400:
            raise MediaDownloadError(
                f"Fallo la subida a Supabase Storage: HTTP {upload_resp.status_code} {upload_resp.text[:300]}"
            )

    return storage_path, mime_type
