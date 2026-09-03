"""Hook de Hermes para el profile `demo`: en cada `agent:end`, envia la
respuesta del agente al relay de Paulet Desk para que quede espejada en
Supabase (tabla `messages`, direction=outbound, sender=bot).

Fire-and-forget a proposito: el sistema de hooks de Hermes trata
`agent:end` como notificacion, no como algo que pueda bloquear ni vetar
(verificado en el codigo fuente de Hermes, ver ARCHITECTURE.md del proyecto Paulet
-- seccion "Estado real verificado en el servidor"). Un fallo aca (relay caido,
Supabase caido) NUNCA debe afectar a Hermes ni retrasar la respuesta real
que ya se le mando al cliente por WhatsApp -- por eso el timeout es corto y
cualquier excepcion se descarta en silencio.

Limitacion conocida (no arreglable desde este hook): Hermes trunca el texto
de `response` a 500 caracteres en este evento. Una respuesta larga del agente
va a aparecer cortada en la bandeja humana aunque el cliente la haya
recibido completa por WhatsApp.

Replicabilidad (hallazgo de la una revisión de código posterior, 2026-08-08): este
archivo ya NO tiene ningun account_id hardcodeado. Antes tenia
DEMO_ACCOUNT_ID fijo, lo que significaba que onboardear un cliente nuevo
requeria copiar esta carpeta Y editar el UUID a mano. Ahora resuelve el
account_id en runtime: lee WHATSAPP_CLOUD_PHONE_NUMBER_ID del .env de SU
PROPIO profile (el archivo vive dentro de la carpeta del profile, se ubica
por posicion relativa a este mismo archivo, nunca por un nombre de cliente
hardcodeado) y consulta la tabla `channels` -- la misma tabla que ya usa el
relay (app/supabase_client.get_account_id_for_phone_number) para el mismo
mapeo. Con esto, esta carpeta se puede copiar tal cual a un profile nuevo
sin tocar una sola linea de codigo, siempre que el canal de ese cliente
tambien este dado de alta en `channels` (ver scripts/setup_channel.sh).
"""

from pathlib import Path

import httpx

RELAY_URL = "http://localhost:8091/internal/hermes-response"
RELAY_ENV_PATH = Path("/root/paulet-desk/relay/.env")
# Ubica el .env de ESTE profile por posicion relativa, no por nombre --
# handler.py vive en profiles/<nombre>/hooks/mirror-to-relay/handler.py, asi
# que 3 niveles arriba de este archivo es la raiz del profile, sea cual sea
# su nombre.
PROFILE_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"

# Cache en memoria del account_id resuelto -- casi nunca cambia (solo si se
# reasigna el canal a otra cuenta), mismo criterio que _account_id_cache del
# relay (app/supabase_client.py). Costo aceptado: si el canal cambia de
# cuenta, este proceso de Hermes no lo ve hasta que se reinicie el gateway.
_account_id_cache: str | None = None


def _load_env_var(path: Path, key: str) -> str | None:
    try:
        for line in path.read_text().splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return None


def _load_relay_secret() -> str:
    """Lee el secreto directo del .env del relay -- misma fuente de verdad
    que valida app/config.py, nunca un valor copiado a mano aca (ver el
    lineamiento de "single source of truth" en ARCHITECTURE.md)."""
    return _load_env_var(RELAY_ENV_PATH, "RELAY_INTERNAL_SECRET") or ""


async def _resolve_account_id() -> str | None:
    """Resuelve el account_id de este profile consultando `channels` por su
    propio phone_number_id -- ver docstring del modulo."""
    global _account_id_cache
    if _account_id_cache is not None:
        return _account_id_cache

    phone_number_id = _load_env_var(PROFILE_ENV_PATH, "WHATSAPP_CLOUD_PHONE_NUMBER_ID")
    if not phone_number_id:
        return None

    supabase_url = _load_env_var(RELAY_ENV_PATH, "SUPABASE_URL")
    service_role_key = _load_env_var(RELAY_ENV_PATH, "SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not service_role_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{supabase_url.rstrip('/')}/rest/v1/channels",
                headers={"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}"},
                params={"phone_number_id": f"eq.{phone_number_id}", "select": "account_id", "limit": "1"},
            )
            resp.raise_for_status()
            rows = resp.json()
    except Exception:
        return None

    if not rows:
        return None
    _account_id_cache = rows[0]["account_id"]
    return _account_id_cache


async def handle(event_type: str, context: dict) -> None:
    if context.get("platform") != "whatsapp_cloud":
        return

    phone = context.get("user_id")
    response_text = context.get("response")
    if not phone or not response_text:
        return

    secret = _load_relay_secret()
    if not secret:
        return

    account_id = await _resolve_account_id()
    if not account_id:
        return

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                RELAY_URL,
                json={"account_id": account_id, "phone": phone, "response": response_text},
                headers={"X-Relay-Secret": secret},
            )
    except Exception:
        # Fire-and-forget real: no logueamos ni relanzamos. Si el relay
        # esta caido, eso ya se sabe por el monitoreo de
        # scripts/health_check_cron.sh -- este hook no debe duplicar esa
        # responsabilidad ni arriesgar afectar a Hermes.
        pass
