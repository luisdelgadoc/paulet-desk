"""Tests del dedupe en memoria de respuestas del agente espejadas
(app/outbound_dedupe.py).

Hallazgo de la revision conjunta Fase 5+6: Hermes puede disparar agent:end
mas de una vez para el mismo turno (stream superseded internamente) -- este
es el dedupe que evita que eso produzca filas duplicadas en la bandeja.

No necesitan red, servidor, ni .env -- app/outbound_dedupe.py no importa
app/config.py (mismo patron que app/hermes_client.py). Se resetea el estado
en memoria entre tests para que no se contaminen entre si.
"""

import pytest

from app import outbound_dedupe


@pytest.fixture(autouse=True)
def _reset_dedupe_state():
    outbound_dedupe._recently_mirrored.clear()
    yield
    outbound_dedupe._recently_mirrored.clear()


def test_primera_vez_no_esta_duplicado():
    assert outbound_dedupe.already_mirrored("acc1", "573000000000", "Hola!") is False


def test_segunda_vez_misma_cuenta_telefono_y_texto_si_esta_duplicado():
    outbound_dedupe.already_mirrored("acc1", "573000000000", "Hola!")
    assert outbound_dedupe.already_mirrored("acc1", "573000000000", "Hola!") is True


def test_mismo_texto_pero_telefono_distinto_no_se_confunde():
    outbound_dedupe.already_mirrored("acc1", "573000000000", "Hola!")
    assert outbound_dedupe.already_mirrored("acc1", "573999999999", "Hola!") is False


def test_mismo_telefono_pero_texto_distinto_no_se_confunde():
    outbound_dedupe.already_mirrored("acc1", "573000000000", "Hola!")
    assert outbound_dedupe.already_mirrored("acc1", "573000000000", "Otra cosa") is False


def test_expira_despues_del_ttl(monkeypatch):
    fake_now = [1000.0]
    monkeypatch.setattr(outbound_dedupe.time, "monotonic", lambda: fake_now[0])

    assert outbound_dedupe.already_mirrored("acc1", "573000000000", "Hola!") is False

    fake_now[0] += outbound_dedupe._OUTBOUND_DEDUPE_TTL_SECONDS + 1
    assert outbound_dedupe.already_mirrored("acc1", "573000000000", "Hola!") is False


def test_entradas_expiradas_se_limpian_del_dict(monkeypatch):
    fake_now = [1000.0]
    monkeypatch.setattr(outbound_dedupe.time, "monotonic", lambda: fake_now[0])

    outbound_dedupe.already_mirrored("acc1", "573000000000", "vieja")
    fake_now[0] += outbound_dedupe._OUTBOUND_DEDUPE_TTL_SECONDS + 1
    outbound_dedupe.already_mirrored("acc1", "573000000000", "nueva")

    assert "acc1:573000000000:vieja" not in outbound_dedupe._recently_mirrored
    assert "acc1:573000000000:nueva" in outbound_dedupe._recently_mirrored
