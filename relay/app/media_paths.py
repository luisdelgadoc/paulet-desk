"""Construccion del path de Storage para media entrante -- Fase 10.

Modulo separado de app/whatsapp_media.py y sin dependencia de app/config.py
a proposito (mismo patron que app/window_24h.py y app/outbound_dedupe.py):
whatsapp_media.py importa `settings`, lo que exige un .env real con todas
las variables requeridas con solo importar el modulo -- esta funcion no
necesita nada de eso, y separarla la deja testeable sin red/servidor/.env.
"""

import mimetypes


def build_storage_path(account_id: str, wamid: str, mime_type: str) -> str:
    """Path dentro del bucket `whatsapp-media`: {account_id}/{wamid}.{ext}.

    El account_id como primer segmento es lo que la policy RLS de
    storage.objects usa para restringir la lectura a miembros de esa cuenta
    (ver desk/db/005_whatsapp_media_storage.sql, storage.foldername(name)).
    """
    ext = mimetypes.guess_extension(mime_type.split(";")[0].strip()) or ""
    return f"{account_id}/{wamid}{ext}"
