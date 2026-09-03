"""Reenvio del webhook original de Meta hacia el gateway local de Hermes.

Se reenvian los bytes crudos EXACTOS y el header de firma original -- Hermes
valida su propia firma HMAC (mismo WHATSAPP_CLOUD_APP_SECRET que usa el
relay) sobre esos mismos bytes. Si aqui se tocara el body de cualquier forma
(ej. volver a serializar el JSON) la firma dejaria de coincidir del lado de
Hermes y el webhook se rechazaria en silencio -- por eso `raw_body` viaja tal
cual, nunca pasa por json.loads/json.dumps en este archivo.
"""

import logging
import subprocess
import time

import httpx

logger = logging.getLogger("relay.hermes")

# Descubierto en /root/.hermes/profiles/demo/.env
# (WHATSAPP_CLOUD_WEBHOOK_PORT + WHATSAPP_CLOUD_WEBHOOK_PATH). Es
# infraestructura interna fija del servidor, no un secreto -- si algun dia cambia,
# es una linea aca, no hace falta pasarlo por .env.
HERMES_WEBHOOK_URL = "http://localhost:8090/whatsapp/webhook"

_client = httpx.AsyncClient(timeout=15.0)

# Dedupe del REENVIO -- distinto del dedupe por wamid de app/supabase_client.py
# (ese protege la tabla `messages`, este protege al agente de responder dos veces).
# Hallazgo de revision de la Fase 3: el reenvio corria incondicional en paralelo
# con la persistencia, asi que un reintento de Meta (mismo payload, misma
# firma) se reenviaba a Hermes de nuevo aunque el mensaje ya estuviera
# deduplicado en la base. Se deduplica por firma en vez de por wamid porque
# un solo payload puede traer varios mensajes, y la firma es determinista
# sobre el body completo -- un reintento identico de Meta produce la MISMA
# firma. TTL de 10 min es generoso frente a la ventana real de reintento de
# Meta. Vive en memoria (no en Supabase) a proposito: es una decision
# operativa del relay, no un dato de negocio, y no debe depender de que
# Supabase este arriba.
_FORWARD_DEDUPE_TTL_SECONDS = 600
_recently_forwarded: dict[str, float] = {}


# Alerta activa cuando el reenvio a Hermes falla -- hallazgo de la revision
# completa posterior (2026-08-08): antes de esto, un fallo aca solo dejaba una
# linea de ERROR en el log. Si Hermes se cae, el mensaje se persiste igual
# (se ve normal en la bandeja), Meta no reintenta (ya recibio su 200), y
# nadie se enteraba hasta que un cliente reportara que el agente no responde.
# health_check_cron.sh corre cada 5 min y ahora tambien vigila el gateway de
# Hermes -- esto es la alerta INMEDIATA, en el momento del fallo real, no la
# de la siguiente pasada del cron.
#
# Cooldown con el mismo patron de TTL que _recently_forwarded, para no
# inundar Slack si Hermes esta caido varios minutos y llegan varios mensajes
# distintos en esa ventana (cada uno dispara este mismo camino).
_ALERT_COOLDOWN_SECONDS = 300
_last_alert_at: float = 0.0


def _alert_forward_failure(reason: str) -> None:
    """Best-effort, nunca debe poder tumbar el request real: se lanza como
    proceso aparte (Popen, sin esperar) para no bloquear el event loop del
    relay con la llamada de red a Slack, y cualquier fallo se traga en
    silencio -- el fallo original (reenvio a Hermes) ya quedo logueado por
    el caller, esto es un aviso adicional best-effort, no la fuente de
    verdad del error."""
    global _last_alert_at
    now = time.monotonic()
    if now - _last_alert_at < _ALERT_COOLDOWN_SECONDS:
        return
    _last_alert_at = now
    try:
        subprocess.Popen(
            [
                "/usr/local/bin/hermes", "-p", "analista_datos", "send", "--to", "slack",
                f"🔴 Paulet Desk Relay: fallo reenviando webhook a Hermes -- {reason}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _already_forwarded(signature_header: str | None) -> bool:
    """True si esta firma ya se reenvio hace menos de _FORWARD_DEDUPE_TTL_SECONDS."""
    if not signature_header:
        # Sin firma no hay como deduplicar -- pero verify_signature() ya
        # rechazo cualquier request sin firma antes de llegar aca, asi que
        # esta rama es defensiva, no deberia ejecutarse en la practica.
        return False

    now = time.monotonic()
    expired = [key for key, exp in _recently_forwarded.items() if exp < now]
    for key in expired:
        del _recently_forwarded[key]

    if signature_header in _recently_forwarded:
        return True

    _recently_forwarded[signature_header] = now + _FORWARD_DEDUPE_TTL_SECONDS
    return False


async def forward_to_hermes(raw_body: bytes, signature_header: str | None) -> None:
    """Reenvia el webhook tal cual a Hermes, salvo que ya se haya reenviado
    (mismo body, misma firma) en los ultimos 10 minutos.

    No propaga excepciones -- un fallo aqui nunca debe tumbar el request del
    webhook. Desde la Fase 7 esto YA NO corre en paralelo con la persistencia
    (ver docstring de app/main.py: el gate necesita saber el resultado de
    persistir antes de decidir si reenviar) -- corren en secuencia, no via
    asyncio.gather. El caller (_process_webhook_in_background) llama a esta
    funcion sola, confiando en que nunca lanza.
    """
    if _already_forwarded(signature_header):
        logger.info("Webhook duplicado (firma ya vista) -- NO se reenvia a Hermes de nuevo")
        return

    headers = {"Content-Type": "application/json"}
    if signature_header:
        headers["X-Hub-Signature-256"] = signature_header

    try:
        resp = await _client.post(HERMES_WEBHOOK_URL, content=raw_body, headers=headers)
        if resp.status_code >= 400:
            logger.error(
                "Hermes rechazo el webhook reenviado: HTTP %s %s",
                resp.status_code,
                resp.text[:500],
            )
            _alert_forward_failure(f"HTTP {resp.status_code}")
        else:
            logger.info("Webhook reenviado a Hermes OK (HTTP %s)", resp.status_code)
    except httpx.HTTPError as exc:
        logger.error("Fallo reenviando a Hermes (Hermes caido o no responde): %s", exc)
        _alert_forward_failure(f"{exc}")


async def close() -> None:
    """Llamado desde el lifespan de FastAPI al apagar -- cierra el cliente
    HTTP en vez de dejarlo abandonado. Sin esto, un apagado puede dejar
    conexiones a medias que luego se manifiestan como excepciones sueltas
    (justo el tipo de error que el gather de main.py ahora si loguea, en
    vez de tragarselo)."""
    await _client.aclose()
