"""Carga y valida las variables de entorno del relay.

Falla rapido (al arrancar, no a mitad de un webhook) si falta algo — mejor un
crash visible en el arranque que un 500 silencioso la primera vez que llega
un mensaje real de un cliente.
"""

import os

from dotenv import load_dotenv

load_dotenv()

_REQUIRED = [
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "WHATSAPP_CLOUD_APP_SECRET",
    "WHATSAPP_CLOUD_VERIFY_TOKEN",
    "RELAY_INTERNAL_SECRET",
    # Fase 8: el relay necesita poder ENVIAR por Graph API (no solo recibir
    # y validar webhooks) -- estos dos no existian antes porque solo Hermes
    # enviaba. Mismos valores que ya tiene Hermes en
    # /root/.hermes/profiles/demo/.env, copiados server-side.
    "WHATSAPP_CLOUD_PHONE_NUMBER_ID",
    "WHATSAPP_CLOUD_ACCESS_TOKEN",
]


class Settings:
    def __init__(self) -> None:
        missing = [k for k in _REQUIRED if not os.environ.get(k)]
        if missing:
            raise RuntimeError(
                f"Faltan variables de entorno en .env: {', '.join(missing)}"
            )

        self.supabase_url: str = os.environ["SUPABASE_URL"].rstrip("/")
        self.supabase_service_role_key: str = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        self.whatsapp_app_secret: str = os.environ["WHATSAPP_CLOUD_APP_SECRET"]
        self.whatsapp_verify_token: str = os.environ["WHATSAPP_CLOUD_VERIFY_TOKEN"]
        # Comparte este valor con el hook de salida de Hermes
        # (/root/.hermes/profiles/demo/hooks/mirror-to-relay/handler.py,
        # que lo lee directo de este mismo .env) -- protege
        # /internal/hermes-response, que Caddy ya no expone al publico desde
        # la Fase 5 pero igual conviene no dejar sin autenticar.
        self.internal_secret: str = os.environ["RELAY_INTERNAL_SECRET"]
        # Fase 8: para enviar mensajes salientes del humano por Graph API
        # (ver app/whatsapp_send.py). Distinto de WHATSAPP_CLOUD_APP_SECRET
        # (ese es para VALIDAR webhooks entrantes, este es para ENVIAR).
        self.whatsapp_phone_number_id: str = os.environ["WHATSAPP_CLOUD_PHONE_NUMBER_ID"]
        self.whatsapp_access_token: str = os.environ["WHATSAPP_CLOUD_ACCESS_TOKEN"]
        # Fuente de verdad del puerto para todo lo que corre en Python (este
        # objeto, scripts/simulate_webhook.py). El proceso de uvicorn en si
        # NO lee esto -- su bind real lo fija el flag --port de systemd/
        # scripts/deploy.sh, que a su vez lee la MISMA variable RELAY_PORT
        # del .env (ver systemd/paulet-relay.service). Si algun dia se
        # cambia el puerto, .env es el unico lugar que hay que tocar.
        self.port: int = int(os.environ.get("RELAY_PORT", "8091"))


settings = Settings()
