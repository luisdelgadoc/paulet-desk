"""Cliente minimo contra la API REST de Supabase (PostgREST).

El relay siempre actua con la Secret key (service_role) -- es un servicio de
confianza, no el navegador, asi que salta RLS a proposito (las politicas RLS
del esquema son para proteger el cliente web que use la Publishable key, no
al relay). No se usa el SDK oficial de Supabase para mantener las
dependencias minimas; PostgREST es HTTP simple.
"""

import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("relay.supabase")

_HEADERS = {
    "apikey": settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type": "application/json",
}

_client = httpx.AsyncClient(base_url=f"{settings.supabase_url}/rest/v1", headers=_HEADERS, timeout=10.0)


async def close() -> None:
    """Llamado desde el lifespan de FastAPI al apagar. Ver docstring gemelo
    en app/hermes_client.py."""
    await _client.aclose()

# Cache en memoria de phone_number_id -> account_id. Casi nunca cambia (solo
# cuando se da de alta un canal nuevo via setup_channel.sh), asi que un cache
# sin TTL es correcto para este volumen -- ahorra un round-trip a Supabase en
# CADA mensaje entrante. Costo: si se agrega un canal nuevo, el relay que ya
# esta corriendo no lo va a ver hasta que se reinicie. Aceptable para esta
# escala; si algun dia se necesita alta dinamica de canales sin reinicio,
# agregar TTL aqui.
_account_id_cache: dict[str, str | None] = {}


async def get_account_id_for_phone_number(phone_number_id: str) -> str | None:
    """Busca a que cuenta pertenece este numero de WhatsApp (tabla channels).

    Devuelve None si el numero no esta registrado -- eso significa que llego
    un webhook para un phone_number_id que no configuramos en Supabase (typo,
    o un canal nuevo que falta dar de alta), y el caller debe rechazar el
    mensaje en vez de adivinar la cuenta.
    """
    if phone_number_id in _account_id_cache:
        return _account_id_cache[phone_number_id]

    resp = await _client.get(
        "/channels",
        params={"phone_number_id": f"eq.{phone_number_id}", "select": "account_id", "limit": "1"},
    )
    resp.raise_for_status()
    rows = resp.json()
    account_id = rows[0]["account_id"] if rows else None
    _account_id_cache[phone_number_id] = account_id
    return account_id


async def find_or_create_contact(account_id: str, phone: str, name: str | None, _retried: bool = False) -> str:
    resp = await _client.get(
        "/contacts",
        params={"account_id": f"eq.{account_id}", "phone": f"eq.{phone}", "select": "id", "limit": "1"},
    )
    resp.raise_for_status()
    rows = resp.json()
    if rows:
        return rows[0]["id"]

    resp = await _client.post(
        "/contacts",
        headers={"Prefer": "return=representation"},
        json={"account_id": account_id, "phone": phone, "name": name},
    )
    if resp.status_code == 409:
        if _retried:
            # Un solo reintento -- si el 409 persiste despues de re-consultar,
            # no es la carrera esperada (otro request creando el mismo
            # contacto), es otra cosa. Mejor fallar con el error real de
            # Supabase que hacer recursion sin limite.
            resp.raise_for_status()
        return await find_or_create_contact(account_id, phone, name, _retried=True)
    resp.raise_for_status()
    return resp.json()[0]["id"]


# Cache en memoria del ultimo (conversation_id, assigned_to) conocido por
# contacto -- decision bloqueante tomada en la revision de la Fase 3 (ver
# ARCHITECTURE.md, seccion "Fase 7"), construida ahora que llega el momento. Sirve
# de resiliencia especifica para el chequeo del gate: si Supabase no responde
# justo en este GET, se usa el ultimo estado conocido en vez de fallar a
# ciegas. No cubre una caida TOTAL de Supabase en el primer mensaje de un
# contacto nuevo (ahi no hay nada en cache todavia) -- ese caso se maneja un
# nivel mas arriba, en app/main.py: se prioriza reenviar a Hermes sobre dejar
# al cliente sin ninguna respuesta.
#
# TTL agregado (hallazgo de la una revisión de código posterior, 2026-08-08): a
# diferencia de _account_id_cache (arriba, sin TTL a proposito -- ese dato
# casi nunca cambia), esta cache guarda el ESTADO DEL GATE, que puede cambiar
# en cualquier momento (un humano toma/suelta la conversacion). Sin TTL, una
# caida prolongada de Supabase podia hacer que el relay seiguiera confiando
# en un "asignado a fulano" de hace horas, mucho despues de que ese humano ya
# solto la conversacion -- exactamente el escenario que el fallback deberia
# cubrir solo por unos minutos, no indefinidamente. Se guarda el timestamp
# junto al valor; si la entrada es mas vieja que el TTL, se trata como
# cache-miss y se relanza el error real en vez de confiar en un dato viejo.
_GATE_CACHE_TTL_SECONDS = 900  # 15 min

_conversation_gate_cache: dict[tuple[str, str], tuple[str, str | None, float]] = {}


async def find_or_create_open_conversation(
    account_id: str, contact_id: str, _retried: bool = False
) -> tuple[str, str | None]:
    """Devuelve (conversation_id, assigned_to).

    assigned_to es el gate de human-in-the-loop de la Fase 7: None significa
    que el agente esta a cargo, cualquier otro valor significa que un humano tomo
    el control y el caller (app/main.py) NO debe reenviar el mensaje a
    Hermes. Se devuelve junto con el id -- no como una consulta separada --
    para no pagar un round-trip extra a Supabase solo para chequear el gate:
    el mismo GET/POST que ya hace esta funcion trae la columna gratis.
    """
    cache_key = (account_id, contact_id)

    try:
        resp = await _client.get(
            "/conversations",
            params={
                "account_id": f"eq.{account_id}",
                "contact_id": f"eq.{contact_id}",
                "status": "eq.open",
                "select": "id,assigned_to",
                "order": "created_at.desc",
                "limit": "1",
            },
        )
        resp.raise_for_status()
        rows = resp.json()
    except httpx.HTTPError:
        if cache_key in _conversation_gate_cache:
            cached_id, cached_assigned_to, cached_at = _conversation_gate_cache[cache_key]
            age = time.monotonic() - cached_at
            if age <= _GATE_CACHE_TTL_SECONDS:
                logger.warning(
                    "Supabase no respondio consultando conversations para %s -- usando ultimo gate "
                    "conocido (edad %.0fs): (%r, %r)",
                    cache_key,
                    age,
                    cached_id,
                    cached_assigned_to,
                )
                return cached_id, cached_assigned_to
            logger.warning(
                "Supabase no respondio consultando conversations para %s -- gate cacheado tiene %.0fs, "
                "supera el TTL de %ds, no se usa",
                cache_key,
                age,
                _GATE_CACHE_TTL_SECONDS,
            )
        raise

    if rows:
        result = (rows[0]["id"], rows[0]["assigned_to"])
        _conversation_gate_cache[cache_key] = (*result, time.monotonic())
        return result

    resp = await _client.post(
        "/conversations",
        headers={"Prefer": "return=representation"},
        json={"account_id": account_id, "contact_id": contact_id, "status": "open"},
    )
    if resp.status_code == 409:
        # Carrera: dos mensajes casi simultaneos del mismo contacto. El indice
        # unico parcial (conversations_one_open_per_contact, migracion 002)
        # es lo que hace que este 409 exista en vez de crear una segunda fila
        # "open" -- sin el, este caso pasaba desapercibido. Ver el archivo de
        # esa migracion para el detalle de por que importa.
        if _retried:
            resp.raise_for_status()
        return await find_or_create_open_conversation(account_id, contact_id, _retried=True)
    resp.raise_for_status()
    row = resp.json()[0]
    # Conversacion recien creada: assigned_to siempre None (default de columna).
    result = (row["id"], row.get("assigned_to"))
    _conversation_gate_cache[cache_key] = (*result, time.monotonic())
    return result


async def insert_inbound_message(
    account_id: str,
    conversation_id: str,
    wamid: str | None,
    msg_type: str,
    body: str | None,
    media_url: str | None = None,
    media_mime: str | None = None,
) -> dict[str, Any] | None:
    """Inserta un mensaje entrante, con dedupe por wamid.

    `on_conflict=wamid` + `Prefer: resolution=ignore-duplicates` hace que un
    wamid repetido (reintento del webhook de Meta) no falle ni duplique --
    simplemente no inserta nada de nuevo. Devuelve None en ese caso, el dict
    de la fila si fue una insercion real.

    media_url (Fase 10) es el PATH dentro del bucket de Storage, no una URL
    descargable directo -- el bucket es privado, el navegador pide una
    signed URL bajo demanda (ver app/whatsapp_media.py). None para mensajes
    de texto, o si la descarga del media fallo (el mensaje igual se
    persiste, solo sin reproductor en la bandeja).
    """
    resp = await _client.post(
        "/messages",
        params={"on_conflict": "wamid"},
        headers={"Prefer": "return=representation,resolution=ignore-duplicates"},
        json={
            "account_id": account_id,
            "conversation_id": conversation_id,
            "wamid": wamid,
            "direction": "inbound",
            "sender": "customer",
            "type": msg_type,
            "body": body,
            "media_url": media_url,
            "media_mime": media_mime,
        },
    )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


async def insert_outbound_message(account_id: str, conversation_id: str, body: str) -> None:
    """Inserta una respuesta del agente (direction=outbound, sender=bot).

    Sin wamid -- el hook `agent:end` de Hermes (ver
    hooks/mirror-to-relay/handler.py) expone el texto de la respuesta, pero
    no el ID real que Meta le asigna al mensaje saliente cuando Hermes lo
    envia (eso pasa en un paso posterior, fuera de este hook). El schema
    permite wamid NULL a proposito (unique constraint trata cada NULL como
    distinto en Postgres), asi que esto no rompe el dedupe de mensajes
    entrantes.

    Tambien por lo mismo: Hermes trunca el texto de la respuesta a 500
    caracteres en este evento (limite de su propio hook, no nuestro) -- una
    respuesta larga del agente va a aparecer cortada en la bandeja aunque el
    cliente la haya recibido completa por WhatsApp. Limitacion conocida, sin
    arreglo disponible con lo que este hook expone.
    """
    resp = await _client.post(
        "/messages",
        json={
            "account_id": account_id,
            "conversation_id": conversation_id,
            "direction": "outbound",
            "sender": "bot",
            "type": "text",
            "body": body,
        },
    )
    resp.raise_for_status()


async def get_conversation_send_context(conversation_id: str) -> dict[str, str] | None:
    """Trae lo que hace falta para enviar un mensaje saliente del humano
    (Fase 8): account_id (para la fila de messages) y el telefono del
    contacto (para Graph API), en un solo round-trip via el embed de
    PostgREST -- sin esto habria que consultar conversations y contacts por
    separado."""
    resp = await _client.get(
        "/conversations",
        params={"id": f"eq.{conversation_id}", "select": "account_id,contacts(phone)", "limit": "1"},
    )
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return None
    return {"account_id": rows[0]["account_id"], "phone": rows[0]["contacts"]["phone"]}


async def get_last_inbound_message_time(conversation_id: str) -> datetime | None:
    """Momento del ULTIMO mensaje del cliente en esta conversacion -- es lo
    que determina la ventana de 24h de WhatsApp (ver app/window_24h.py), no
    la hora de creacion de la conversacion ni la del ultimo mensaje saliente."""
    resp = await _client.get(
        "/messages",
        params={
            "conversation_id": f"eq.{conversation_id}",
            "direction": "eq.inbound",
            "select": "created_at",
            "order": "created_at.desc",
            "limit": "1",
        },
    )
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return None
    return datetime.fromisoformat(rows[0]["created_at"])


async def insert_human_outbound_message(
    account_id: str, conversation_id: str, body: str, wamid: str, sender_user_id: str
) -> None:
    """Inserta la respuesta de un humano (direction=outbound, sender=human).

    A diferencia de insert_outbound_message (la respuesta del agente, sin
    wamid porque el hook de Hermes no lo expone), esta SI trae el wamid real
    que devuelve Graph API -- se dedupea igual que los mensajes entrantes
    (on_conflict=wamid) por si el caller reintentara este insert por error."""
    resp = await _client.post(
        "/messages",
        params={"on_conflict": "wamid"},
        headers={"Prefer": "resolution=ignore-duplicates"},
        json={
            "account_id": account_id,
            "conversation_id": conversation_id,
            "wamid": wamid,
            "direction": "outbound",
            "sender": "human",
            "sender_user_id": sender_user_id,
            "type": "text",
            "body": body,
        },
    )
    resp.raise_for_status()


async def get_conversation_assignment(conversation_id: str) -> tuple[str | None, str | None] | None:
    """Devuelve (assigned_to, assigned_at) actuales, o None si la
    conversacion no existe. Usado por /release-conversation (Fase 9) para
    saber desde cuando buscar los mensajes del humano, y para verificar
    que sigue asignada a quien pide soltarla."""
    resp = await _client.get(
        "/conversations",
        params={"id": f"eq.{conversation_id}", "select": "assigned_to,assigned_at", "limit": "1"},
    )
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return None
    return rows[0]["assigned_to"], rows[0]["assigned_at"]


async def get_human_messages_since(conversation_id: str, since: str) -> list[str]:
    """Cuerpos de los mensajes que escribio un humano en esta conversacion
    desde `since` (el assigned_at de la asignacion que se esta soltando) --
    materia prima de la transcripcion de handoff (Fase 9)."""
    resp = await _client.get(
        "/messages",
        params={
            "conversation_id": f"eq.{conversation_id}",
            "sender": "eq.human",
            "created_at": f"gte.{since}",
            "select": "body",
            "order": "created_at.asc",
        },
    )
    resp.raise_for_status()
    return [row["body"] for row in resp.json() if row.get("body")]


async def release_conversation(
    conversation_id: str, expected_assigned_to: str, handoff_context: str | None
) -> bool:
    """Devuelve la conversacion al bot -- solo si TODAVIA esta asignada a
    expected_assigned_to (precondicion atomica, mismo criterio que se aplico
    al boton "Tomar conversacion" de la web tras la revision conjunta de la
    Fase 7+8: un UPDATE sin condicion puede pisar un cambio de estado que ya
    ocurrio). Devuelve True si aplico, False si alguien mas ya la solto o
    tomo entre que el Route Handler verifico y esta llamada llego."""
    resp = await _client.patch(
        "/conversations",
        params={"id": f"eq.{conversation_id}", "assigned_to": f"eq.{expected_assigned_to}"},
        headers={"Prefer": "return=representation"},
        json={"assigned_to": None, "assigned_at": None, "handoff_context_pending": handoff_context},
    )
    resp.raise_for_status()
    return len(resp.json()) > 0


async def touch_conversation_last_message(conversation_id: str) -> None:
    resp = await _client.patch(
        "/conversations",
        params={"id": f"eq.{conversation_id}"},
        json={"last_message_at": datetime.now(UTC).isoformat()},
    )
    resp.raise_for_status()
