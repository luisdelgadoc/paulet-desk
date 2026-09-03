"""Plugin de Hermes para el profile `demo`: inyecta el contexto de
handoff (lo que hablo un humano mientras tenia la conversacion tomada) en el
PRIMER turno que el agente procesa despues de que se la devuelvan -- Fase 9 de
Paulet Desk.

Por que un PLUGIN y no el gateway hook de siempre (ver
hermes-hooks/demo/mirror-to-relay/): los gateway hooks
(~/.hermes/hooks/, eventos agent:start/agent:end) son fire-and-forget -- su
valor de retorno se descarta por diseno (ver gateway/hooks.py,
HookRegistry.emit: "Fire all handlers... discarding return values"). El
sistema de PLUGINS (~/.hermes/plugins/, un sistema DISTINTO) tiene un unico
hook cuyo retorno se usa para modificar el turno en curso: `pre_llm_call`,
que inyecta {"context": "..."} en el mensaje del usuario de ESE turno (ver
hermes_cli/plugins.py, PluginManager.invoke_hook, y agent/conversation_loop.py
donde se compone el mensaje final). Verificado contra el codigo fuente real
de Hermes instalado en el servidor, no asumido -- ver ARCHITECTURE.md, seccion "Fase 9".

Por que NO se modifica el webhook que se reenvia a Hermes en su lugar: la
firma HMAC que Hermes valida se calcula sobre los bytes crudos del body (ver
docstring de app/hermes_client.py del relay) -- tocar el body para inyectar
texto invalidaria esa firma. El mecanismo de aca no toca el webhook en
absoluto; actua un paso despues, cuando Hermes ya decidio procesar el turno
y esta por llamar al LLM.

Importante -- SINCRONO, no async: invoke_hook llama a cada callback como
`cb(**kwargs)` sin await (ver PluginManager.invoke_hook). Un `async def` aca
NUNCA se ejecutaria -- Python solo crearia el objeto coroutine y lo
descartaria sin correr el cuerpo. Por eso este handler usa httpx.Client
(sincrono), no AsyncClient.

Importante -- timeout corto: pre_llm_call se dispara UNA vez por turno, para
TODOS los mensajes de este profile (no solo los que tienen un handoff
pendiente) -- un timeout largo bloquearia al agente completa, no solo la
conversacion con contexto pendiente. 2 segundos es generoso para una lectura
a Supabase y deja margen antes de que el humano note la demora.

Fallo silencioso a proposito: si algo falla aca (Supabase caida, timeout,
lo que sea), se devuelve None y el turno sigue normal, sin contexto
inyectado. Es exactamente el mismo comportamiento que existia ANTES de la
Fase 9 -- el agente vuelve a preguntar algo que el humano ya resolvio, molesto
pero no roto. Nunca debe poder tumbar un turno real.

Replicabilidad (hallazgo de la una revisión de código posterior, 2026-08-08): este
archivo ya NO tiene ningun account_id hardcodeado -- ver el hermano de este
archivo, hermes-hooks/demo/mirror-to-relay/handler.py, para el mismo
cambio con la explicacion completa de por que y como (resolver por
WHATSAPP_CLOUD_PHONE_NUMBER_ID del propio profile + tabla `channels`, en vez
de un UUID fijo). Se puede copiar esta carpeta tal cual a un profile nuevo.
"""

from pathlib import Path
from typing import Any

import httpx

RELAY_ENV_PATH = Path("/root/paulet-desk/relay/.env")
# Ubica el .env de ESTE profile por posicion relativa, no por nombre --
# __init__.py vive en profiles/<nombre>/plugins/inject-handoff-context/
# __init__.py, asi que 3 niveles arriba de este archivo es la raiz del
# profile, sea cual sea su nombre.
PROFILE_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"

_TIMEOUT_SECONDS = 2.0

# Cache en memoria del account_id resuelto -- mismo criterio que el hook
# gemelo (mirror-to-relay/handler.py) y que _account_id_cache del relay.
_account_id_cache: str | None = None


def register(ctx) -> None:
    ctx.register_hook("pre_llm_call", inject_handoff_context)


def _load_env_var(path: Path, key: str) -> str | None:
    try:
        for line in path.read_text().splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return None


def _load_supabase_creds() -> tuple[str, str] | None:
    """Lee URL y service_role key directo del .env del relay -- misma
    fuente de verdad que usa el relay, nunca una copia (lineamiento de
    single source of truth, ver ARCHITECTURE.md)."""
    url = _load_env_var(RELAY_ENV_PATH, "SUPABASE_URL")
    key = _load_env_var(RELAY_ENV_PATH, "SUPABASE_SERVICE_ROLE_KEY")
    if url and key:
        return url.rstrip("/"), key
    return None


def _resolve_account_id(client: httpx.Client, headers: dict[str, str], supabase_url: str) -> str | None:
    """Resuelve el account_id de este profile consultando `channels` por su
    propio phone_number_id -- ver docstring del modulo. Sincrono (mismo
    cliente httpx.Client que ya abrio el caller) para no pagar el costo de
    abrir una segunda conexion."""
    global _account_id_cache
    if _account_id_cache is not None:
        return _account_id_cache

    phone_number_id = _load_env_var(PROFILE_ENV_PATH, "WHATSAPP_CLOUD_PHONE_NUMBER_ID")
    if not phone_number_id:
        return None

    try:
        resp = client.get(
            f"{supabase_url}/rest/v1/channels",
            headers=headers,
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


def inject_handoff_context(**kwargs: Any) -> dict[str, str] | None:
    if kwargs.get("platform") != "whatsapp_cloud":
        return None

    # Mismo campo que usa mirror-to-relay/handler.py (context.get("user_id")
    # ahi, sender_id aca -- distinto nombre en cada sistema de hooks, mismo
    # dato subyacente: el telefono del cliente).
    phone = kwargs.get("sender_id")
    if not phone:
        return None

    creds = _load_supabase_creds()
    if creds is None:
        return None
    supabase_url, service_role_key = creds
    headers = {"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}"}

    try:
        with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
            account_id = _resolve_account_id(client, headers, supabase_url)
            if not account_id:
                return None

            resp = client.get(
                f"{supabase_url}/rest/v1/conversations",
                headers=headers,
                params={
                    "select": "id,handoff_context_pending,contacts!inner(phone)",
                    "account_id": f"eq.{account_id}",
                    "contacts.phone": f"eq.{phone}",
                    "status": "eq.open",
                    "limit": "1",
                },
            )
            resp.raise_for_status()
            rows = resp.json()
            if not rows or not rows[0].get("handoff_context_pending"):
                return None

            conversation_id = rows[0]["id"]
            pending_text = rows[0]["handoff_context_pending"]

            # Limpiar de inmediato -- una sola inyeccion. No depende de que
            # el turno termine bien: si Hermes falla despues de esto, el
            # contexto ya no se reinyecta en el proximo intento, pero eso es
            # preferible a inyectarlo dos veces si el humano vuelve a tomar
            # y soltar la conversacion rapido.
            client.patch(
                f"{supabase_url}/rest/v1/conversations",
                headers=headers,
                params={"id": f"eq.{conversation_id}"},
                json={"handoff_context_pending": None},
            )
    except Exception:
        return None

    return {
        "context": (
            "[CONTEXTO INTERNO -- no lo menciones como \"contexto\", solo usalo: "
            "mientras no estabas disponible, un miembro del equipo humano hablo "
            "con esta familia y dijo lo siguiente. No vuelvas a preguntar algo "
            f"que ya quedo resuelto ahi: {pending_text}]"
        )
    }
