"""Relay de WhatsApp para Demo -- Fase 10: media entrante (notas de voz,
imagenes, etc).

Alcance (ver ARCHITECTURE.md, seccion "Orden de construccion"):
  - Todo lo de las Fases 2-9 (ingesta, reenvio a Hermes, produccion real,
    espejo de respuestas del agente, bandeja web, gate de human-in-the-loop,
    envio saliente del humano, inyeccion de contexto de handoff).
  - NUEVO: cuando un mensaje entrante trae media (audio/imagen/video/
    documento/sticker), se descarga de Graph API y se sube a Supabase
    Storage (bucket privado `whatsapp-media`, ver
    desk/db/005_whatsapp_media_storage.sql) ANTES de insertar la fila en
    `messages` -- el media_url queda listo desde el primer insert. Un fallo
    en la descarga/subida NUNCA pierde el mensaje: se persiste igual, solo
    sin reproductor en la bandeja (ver app/whatsapp_media.py).

Lo que TODAVIA NO hace (fases siguientes, no agregar aqui todavia):
  - NO soporta plantillas aprobadas para responder fuera de la ventana de 24h.
Control de este hito: un cliente manda una nota de voz por WhatsApp real y
se escucha en la bandeja.
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app import hermes_client, supabase_client
from app.config import settings
from app.constants import WHATSAPP_WEBHOOK_PATH
from app.gate import GateOutcome, decide_forward
from app.hermes_client import forward_to_hermes
from app.outbound_dedupe import already_mirrored
from app.supabase_client import (
    find_or_create_contact,
    find_or_create_open_conversation,
    get_account_id_for_phone_number,
    get_conversation_assignment,
    get_conversation_send_context,
    get_human_messages_since,
    get_last_inbound_message_time,
    insert_human_outbound_message,
    insert_inbound_message,
    insert_outbound_message,
    release_conversation,
    touch_conversation_last_message,
)
from app.whatsapp import parse_incoming_messages, verify_signature
from app.whatsapp_media import MediaDownloadError, download_and_store_media
from app.whatsapp_send import WhatsAppSendError, send_whatsapp_text
from app.window_24h import is_within_24h_window

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("relay.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Cerrar los clientes HTTP al apagar -- sin esto quedan conexiones
    # abandonadas, que en un apagado a medias pueden manifestarse como
    # excepciones sueltas en el gather de _process_webhook_in_background.
    await asyncio.gather(supabase_client.close(), hermes_client.close(), return_exceptions=True)


app = FastAPI(title="Paulet Desk Relay — Demo", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get(WHATSAPP_WEBHOOK_PATH)
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
) -> PlainTextResponse:
    """Meta llama esto UNA vez, al configurar/re-verificar el webhook en su panel."""
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        logger.info("Verificacion de webhook OK")
        return PlainTextResponse(hub_challenge)
    logger.warning("Verificacion de webhook FALLO (token no coincide)")
    raise HTTPException(status_code=403, detail="verification token mismatch")


async def _persist_one_message(msg: dict) -> GateOutcome:
    """Persiste un mensaje entrante. Devuelve el GateOutcome de su
    conversacion -- ver app/gate.py para la decision de reenvio, que ahora
    vive separada de esta funcion (antes devolvia un bool directo, sin
    ningun test unitario posible porque esta funcion en si necesita
    Supabase real; separar la decision permite testear la REGLA sin
    testear la I/O).
    """
    phone_number_id = msg["phone_number_id"]
    account_id = await get_account_id_for_phone_number(phone_number_id)
    if account_id is None:
        # No es un error del cliente -- es que a nosotros nos falta dar de
        # alta ese numero en la tabla `channels`. No hay a donde persistir
        # sin account_id, y sin conversacion no hay gate que consultar --
        # UNKNOWN (se trata como "reenviar", ver decide_forward): no
        # silenciar al agente sin certeza de que hay un humano.
        logger.error(
            "phone_number_id %s no tiene account_id asociado en la tabla channels -- mensaje descartado",
            phone_number_id,
        )
        return GateOutcome.UNKNOWN

    contact_id = await find_or_create_contact(account_id, msg["from_phone"], msg["contact_name"])
    conversation_id, assigned_to = await find_or_create_open_conversation(account_id, contact_id)

    # Fase 10: si el mensaje trae media (audio/imagen/video/documento),
    # descargarlo de Graph API y subirlo a Storage ANTES de insertar -- asi
    # el media_url queda en la misma fila desde el primer insert, sin un
    # PATCH aparte. Un fallo aca NUNCA debe perder el mensaje completo: se
    # persiste igual, solo sin reproductor en la bandeja.
    media_url = None
    media_mime = msg.get("media_mime")
    if msg.get("media_id"):
        try:
            media_url, media_mime = await download_and_store_media(
                msg["media_id"], account_id, msg["wamid"], media_mime
            )
        except MediaDownloadError:
            logger.exception(
                "Fallo descargando media (wamid=%s) -- se persiste el mensaje sin media_url", msg["wamid"]
            )

    inserted = await insert_inbound_message(
        account_id=account_id,
        conversation_id=conversation_id,
        wamid=msg["wamid"],
        msg_type=msg["type"],
        body=msg["body"],
        media_url=media_url,
        media_mime=media_mime,
    )

    if inserted is None:
        logger.info("wamid %s ya existia -- reintento de Meta, deduplicado", msg["wamid"])
    else:
        logger.info("Mensaje %s persistido (conversacion %s)", msg["wamid"], conversation_id)
        await touch_conversation_last_message(conversation_id)

    if assigned_to is not None:
        logger.info(
            "Conversacion %s asignada a un humano (%s) -- este mensaje NO se reenvia a Hermes",
            conversation_id,
            assigned_to,
        )
        return GateOutcome.HUMAN_ASSIGNED
    return GateOutcome.NEEDS_BOT


async def _persist_all_messages(messages: list[dict]) -> bool:
    """Persiste cada mensaje de forma aislada -- si uno falla, no debe
    impedir que los demas del mismo payload se guarden. Devuelve si el
    payload debe reenviarse a Hermes (decide_forward, ver app/gate.py para
    la regla exacta y sus tests).
    """
    outcomes: list[GateOutcome] = []
    for msg in messages:
        try:
            outcomes.append(await _persist_one_message(msg))
        except Exception:
            logger.exception(
                "Fallo persistiendo/chequeando el gate para wamid=%s -- se prioriza reenviar a Hermes "
                "sobre dejar al cliente sin respuesta",
                msg.get("wamid"),
            )
            outcomes.append(GateOutcome.UNKNOWN)
    return decide_forward(outcomes)


async def _process_webhook_in_background(raw_body: bytes, signature: str | None, payload: dict) -> None:
    """Trabajo real del webhook, corre DESPUES de que Meta ya recibio el 200.

    Desde la Fase 7, persistir y reenviar YA NO son independientes: reenviar
    depende de saber si hay un humano a cargo, y eso se resuelve como parte
    de persistir (ver find_or_create_open_conversation). Esto reemplaza el
    asyncio.gather en paralelo que existia desde la Fase 2 -- ver el
    docstring del modulo para la decision completa de por que se revisa
    ahora: la funcion en si misma requiere la dependencia.

    Ni _persist_all_messages ni forward_to_hermes propagan excepciones (cada
    una las atrapa internamente) -- no hace falta un try/except extra aca.
    """
    incoming = parse_incoming_messages(payload)
    should_forward = await _persist_all_messages(incoming)

    if not should_forward:
        logger.info("Ninguna conversacion de este payload necesita al agente -- no se reenvia a Hermes")
        return

    await forward_to_hermes(raw_body, signature)


@app.post(WHATSAPP_WEBHOOK_PATH)
async def receive_webhook(request: Request, background_tasks: BackgroundTasks) -> dict[str, str]:
    # Bytes crudos, SIN parsear -- la firma se valida sobre esto exacto, antes
    # de tocar el contenido. Ver docstring de app/whatsapp.py.
    raw_body = await request.body()
    signature = request.headers.get("x-hub-signature-256")

    if not verify_signature(raw_body, signature, settings.whatsapp_app_secret):
        logger.warning("Firma HMAC invalida -- webhook rechazado")
        raise HTTPException(status_code=403, detail="invalid signature")

    # La validacion de firma es rapida (sin I/O) -- es lo unico que corre
    # antes del 200. Todo lo demas (persistir, reenviar a Hermes) es trabajo
    # de background: Meta necesita el 200 rapido o reintenta, y con el LLM de
    # Hermes en el camino el trabajo real puede tardar mucho mas que esa
    # ventana.
    payload = json.loads(raw_body)
    background_tasks.add_task(_process_webhook_in_background, raw_body, signature, payload)

    return {"status": "received"}


@app.post("/internal/hermes-response")
async def receive_hermes_response(request: Request) -> dict[str, str]:
    """Llamado por el hook `agent:end` de Hermes (mismo servidor, nunca desde
    internet -- Caddy solo expone WHATSAPP_WEBHOOK_PATH). Protegido con un
    secreto compartido en vez de dejarlo sin autenticar del todo: este
    endpoint escribe en la tabla `messages` que un humano va a leer para
    decidir si toma una conversacion, asi que su integridad importa aunque
    ya no sea alcanzable publicamente.
    """
    if request.headers.get("x-relay-secret") != settings.internal_secret:
        logger.warning("Secreto interno invalido en /internal/hermes-response -- rechazado")
        raise HTTPException(status_code=403, detail="invalid internal secret")

    body = await request.json()
    account_id = body.get("account_id")
    phone = body.get("phone")
    response_text = body.get("response")

    if not account_id or not phone or not response_text:
        raise HTTPException(status_code=400, detail="faltan account_id, phone o response")

    if already_mirrored(account_id, phone, response_text):
        logger.info("Respuesta del agente duplicada (mismo turno reintentado) -- no se espeja de nuevo")
        return {"status": "duplicate"}

    contact_id = await find_or_create_contact(account_id, phone, name=None)
    # El gate no aplica a la respuesta del agente en si -- si un humano tomo la
    # conversacion, el gate ya evito que este turno se reenviara a Hermes en
    # primer lugar, asi que este endpoint no deberia dispararse para esa
    # conversacion. assigned_to se descarta aca a proposito.
    conversation_id, _assigned_to = await find_or_create_open_conversation(account_id, contact_id)
    await insert_outbound_message(account_id, conversation_id, response_text)
    await touch_conversation_last_message(conversation_id)

    logger.info("Respuesta del agente espejada (conversacion %s)", conversation_id)
    return {"status": "recorded"}


@app.post("/outbound")
async def send_outbound_message(request: Request) -> dict[str, str]:
    """Envio saliente del humano (Fase 8) -- disparado desde el composer de
    la bandeja web via el Route Handler de Next.js (mismo servidor, localhost;
    ver docstring del modulo). La verificacion de que el usuario tiene
    permiso para mandar este mensaje YA se hizo ahi, usando su propio
    access_token contra RLS -- este endpoint solo valida el secreto
    compartido, igual que /internal/hermes-response.
    """
    if request.headers.get("x-relay-secret") != settings.internal_secret:
        logger.warning("Secreto interno invalido en /outbound -- rechazado")
        raise HTTPException(status_code=403, detail="invalid internal secret")

    body = await request.json()
    conversation_id = body.get("conversation_id")
    message_text = body.get("message")
    sender_user_id = body.get("sender_user_id")

    if not conversation_id or not message_text or not sender_user_id:
        raise HTTPException(status_code=400, detail="faltan conversation_id, message o sender_user_id")

    context = await get_conversation_send_context(conversation_id)
    if context is None:
        raise HTTPException(status_code=404, detail="conversacion no encontrada")

    last_inbound_at = await get_last_inbound_message_time(conversation_id)
    if last_inbound_at is None or not is_within_24h_window(last_inbound_at, datetime.now(UTC)):
        raise HTTPException(
            status_code=422,
            detail="Han pasado mas de 24h desde el ultimo mensaje del cliente -- "
            "WhatsApp ya no permite mensajes libres, solo plantillas aprobadas (no soportado todavia).",
        )

    try:
        wamid = await send_whatsapp_text(context["phone"], message_text)
    except WhatsAppSendError as exc:
        logger.error("Fallo el envio saliente a %s: %s", context["phone"], exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await insert_human_outbound_message(
        context["account_id"], conversation_id, message_text, wamid, sender_user_id
    )
    await touch_conversation_last_message(conversation_id)

    logger.info("Mensaje humano enviado y persistido (conversacion %s, wamid %s)", conversation_id, wamid)
    return {"status": "sent", "wamid": wamid}


@app.post("/release-conversation")
async def release_conversation_endpoint(request: Request) -> dict[str, str | bool]:
    """Devuelve la conversacion al bot con la transcripcion de handoff
    (Fase 9). Llamado SOLO desde el Route Handler de Next.js
    (desk/web/app/api/release/route.ts) -- ya verifico ahi, con el propio
    access_token del usuario contra RLS, que tiene la conversacion asignada;
    este endpoint solo valida el secreto compartido Y repite la verificacion
    a nivel de fila (precondicion atomica, ver docstring de
    supabase_client.release_conversation) por si algo cambio en la ventana
    entre esa verificacion y esta llamada.
    """
    if request.headers.get("x-relay-secret") != settings.internal_secret:
        logger.warning("Secreto interno invalido en /release-conversation -- rechazado")
        raise HTTPException(status_code=403, detail="invalid internal secret")

    body = await request.json()
    conversation_id = body.get("conversation_id")
    sender_user_id = body.get("sender_user_id")
    if not conversation_id or not sender_user_id:
        raise HTTPException(status_code=400, detail="faltan conversation_id o sender_user_id")

    current = await get_conversation_assignment(conversation_id)
    if current is None:
        raise HTTPException(status_code=404, detail="conversacion no encontrada")
    assigned_to, assigned_at = current
    if assigned_to != sender_user_id:
        raise HTTPException(status_code=409, detail="la conversacion ya no esta asignada a este usuario")

    human_messages = await get_human_messages_since(conversation_id, assigned_at) if assigned_at else []
    # " / " en vez de "\n": el plugin de Hermes antepone esto en una sola
    # linea de contexto -- varios mensajes cortos del humano leen mejor
    # separados asi que como un bloque multilinea dentro del prompt.
    transcript = " / ".join(human_messages) if human_messages else None

    released = await release_conversation(conversation_id, sender_user_id, transcript)
    if not released:
        raise HTTPException(status_code=409, detail="la conversacion ya no esta asignada a este usuario")

    logger.info(
        "Conversacion %s devuelta al bot (handoff_context %s)",
        conversation_id,
        "escrito" if transcript else "vacio -- nada que decir",
    )
    return {"status": "released", "handoff_context_written": bool(transcript)}
