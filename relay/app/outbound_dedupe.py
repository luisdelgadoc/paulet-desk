"""Dedupe en memoria para las respuestas del agente espejadas desde Hermes.

Modulo sin dependencias de app/config.py a proposito -- igual que
app/hermes_client.py, para poder testearlo sin red, servidor, ni .env real (ver
tests/test_outbound_dedupe.py).

Hallazgo de la revision conjunta Fase 5+6 (una revisión posterior, 2026-08-07): Hermes puede
disparar agent:end mas de una vez para el MISMO turno cuando un stream
interno es superseded (ver el incidente real de "Redirect current run"
documentado en ARCHITECTURE.md, Fase 4 -- ese bug puntual ya se corrigio, pero el
reintento de stream en si es comportamiento normal de Hermes, no algo que
vaya a desaparecer). Sin esto, un turno reintentado produce filas duplicadas
en la bandeja humana.

Distinto del dedupe de reenvio de app/hermes_client.py: ese protege al agente
de responder dos veces al MISMO mensaje entrante; este protege a la bandeja
de mostrar la MISMA respuesta saliente dos veces. TTL corto (no los 10 min
del otro) porque un reintento de stream ocurre en segundos; una respuesta
identica minutos despues es coincidencia real del negocio (ej. el agente
repitiendo el mismo saludo), no un reintento.
"""

import time

_OUTBOUND_DEDUPE_TTL_SECONDS = 60
_recently_mirrored: dict[str, float] = {}


def already_mirrored(account_id: str, phone: str, response_text: str) -> bool:
    """True si esta misma respuesta del agente ya se espejo hace menos de
    _OUTBOUND_DEDUPE_TTL_SECONDS."""
    key = f"{account_id}:{phone}:{response_text}"
    now = time.monotonic()
    expired = [k for k, exp in _recently_mirrored.items() if exp < now]
    for k in expired:
        del _recently_mirrored[k]

    if key in _recently_mirrored:
        return True
    _recently_mirrored[key] = now + _OUTBOUND_DEDUPE_TTL_SECONDS
    return False
