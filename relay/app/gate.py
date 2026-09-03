"""Logica pura de decision del gate de human-in-the-loop (Fase 7).

Separado de app/main.py a proposito -- mismo patron que app/window_24h.py,
app/outbound_dedupe.py y app/media_paths.py: sin dependencia de
app/config.py, para poder testearlo sin Supabase/servidor/.env real.

Hallazgo de la una revisión de código posterior (2026-08-08): esta es la regla de
negocio mas importante del sistema (decide si el agente habla o se queda
callada) y no tenia NINGUN test unitario -- solo se verificaba con
scripts/verify_gate.py contra el servidor real. Los otros tres modulos puros
(window_24h, outbound_dedupe, media_paths) existen justo para evitar esto;
el gate se quedo afuera de ese patron por descuido, no por decision.
"""

from enum import Enum


class GateOutcome(Enum):
    """Resultado del chequeo del gate para UN mensaje del payload entrante."""

    # assigned_to es None -- el agente esta a cargo, debe responder.
    NEEDS_BOT = "needs_bot"
    # Un humano tiene la conversacion asignada -- el agente se calla.
    HUMAN_ASSIGNED = "human_assigned"
    # No se pudo determinar (excepcion, sin account_id en `channels`, caida
    # total de Supabase sin nada en cache) -- se trata igual que NEEDS_BOT,
    # ver decide_forward.
    UNKNOWN = "unknown"


def decide_forward(outcomes: list[GateOutcome]) -> bool:
    """Decide si el payload completo debe reenviarse a Hermes.

    Regla: True si CUALQUIER mensaje del payload necesita al bot o no se
    pudo determinar su gate -- UNKNOWN se trata como NEEDS_BOT porque se
    prioriza que el agente responda de mas (rara superposicion con un humano)
    sobre dejar al cliente sin ninguna respuesta (ver ARCHITECTURE.md, seccion
    "Fase 7", para la decision completa de por que).

    False solo si TODOS los mensajes del payload tienen HUMAN_ASSIGNED --
    ahi si hay certeza de que ningun mensaje de este payload necesita al
    bot.

    Lista vacia -> False (no hay nada que reenviar; en la practica
    parse_incoming_messages() nunca produce una lista vacia con should_forward
    consultado, pero la funcion debe ser total).
    """
    if not outcomes:
        return False
    return any(outcome != GateOutcome.HUMAN_ASSIGNED for outcome in outcomes)
