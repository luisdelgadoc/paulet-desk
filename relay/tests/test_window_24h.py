"""Tests de la ventana de 24h de WhatsApp (app/window_24h.py).

No necesitan red, servidor, ni .env -- app/window_24h.py no importa
app/config.py, mismo patron que app/hermes_client.py y
app/outbound_dedupe.py.
"""

from datetime import UTC, datetime, timedelta

from app.window_24h import WINDOW, is_within_24h_window


def test_mensaje_reciente_esta_dentro_de_la_ventana():
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    last_inbound_at = now - timedelta(hours=1)
    assert is_within_24h_window(last_inbound_at, now) is True


def test_justo_en_el_limite_de_24h_ya_no_esta_dentro():
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    last_inbound_at = now - WINDOW
    assert is_within_24h_window(last_inbound_at, now) is False


def test_un_segundo_antes_del_limite_si_esta_dentro():
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    last_inbound_at = now - WINDOW + timedelta(seconds=1)
    assert is_within_24h_window(last_inbound_at, now) is True


def test_mensaje_de_hace_varios_dias_no_esta_dentro():
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    last_inbound_at = now - timedelta(days=3)
    assert is_within_24h_window(last_inbound_at, now) is False


def test_mensaje_en_el_futuro_esta_dentro():
    """Caso defensivo: un reloj ligeramente desincronizado no debe bloquear
    el envio -- si last_inbound_at es "despues" de now por un margen chico,
    sigue contando como dentro de la ventana (la resta da negativo, que es
    < WINDOW)."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    last_inbound_at = now + timedelta(seconds=5)
    assert is_within_24h_window(last_inbound_at, now) is True
