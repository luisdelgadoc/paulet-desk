"""Tests de la decision del gate (app/gate.py) -- la regla de negocio mas
importante del sistema: si el agente responde o se calla.

No necesitan red, servidor, ni .env -- app/gate.py no importa app/config.py,
mismo patron que test_window_24h.py / test_outbound_dedupe.py /
test_media_paths.py.
"""

from app.gate import GateOutcome, decide_forward


def test_lista_vacia_no_reenvia():
    assert decide_forward([]) is False


def test_un_mensaje_con_humano_no_reenvia():
    assert decide_forward([GateOutcome.HUMAN_ASSIGNED]) is False


def test_un_mensaje_necesita_bot_reenvia():
    assert decide_forward([GateOutcome.NEEDS_BOT]) is True


def test_un_mensaje_unknown_reenvia():
    """UNKNOWN se trata como NEEDS_BOT -- se prioriza reenviar sobre dejar
    al cliente sin respuesta cuando no se pudo determinar el gate."""
    assert decide_forward([GateOutcome.UNKNOWN]) is True


def test_todos_con_humano_no_reenvia():
    assert decide_forward([GateOutcome.HUMAN_ASSIGNED, GateOutcome.HUMAN_ASSIGNED]) is False


def test_un_solo_needs_bot_entre_varios_con_humano_reenvia():
    """Simplificacion aceptada documentada en main.py: un payload con
    mensajes de mas de un contacto reenvia TODO si CUALQUIERA necesita al
    bot -- se prueba aca la regla exacta que main.py delega a esta funcion."""
    assert decide_forward(
        [GateOutcome.HUMAN_ASSIGNED, GateOutcome.HUMAN_ASSIGNED, GateOutcome.NEEDS_BOT]
    ) is True


def test_un_solo_unknown_entre_varios_con_humano_reenvia():
    assert decide_forward([GateOutcome.HUMAN_ASSIGNED, GateOutcome.UNKNOWN]) is True


def test_mezcla_needs_bot_y_unknown_reenvia():
    assert decide_forward([GateOutcome.NEEDS_BOT, GateOutcome.UNKNOWN]) is True
