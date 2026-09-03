"""Chequeo de la ventana de 24h de WhatsApp Cloud API.

Fuera de las 24h desde el ULTIMO mensaje del cliente (no desde el primero,
ni desde el ultimo mensaje saliente -- el reloj lo reinicia cada mensaje
NUEVO del cliente), Meta solo permite plantillas aprobadas; un mensaje libre
se rechaza en su API. Modulo separado, sin dependencias de red ni de
app/config.py, para poder testearlo con timestamps fijos (mismo patron que
app/hermes_client.py y app/outbound_dedupe.py).
"""

from datetime import datetime, timedelta

WINDOW = timedelta(hours=24)


def is_within_24h_window(last_inbound_at: datetime, now: datetime) -> bool:
    """True si `now` cae dentro de las 24h siguientes a `last_inbound_at`."""
    return now - last_inbound_at < WINDOW
