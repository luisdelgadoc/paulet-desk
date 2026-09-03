"""Tests del dedupe de reenvio en memoria (app/hermes_client.py).

Hallazgo de revision de la Fase 3: el dedupe por wamid en Supabase protege
la tabla `messages`, pero no evitaba que un reintento de Meta se reenviara a
Hermes una segunda vez -- este es el dedupe que cierra ese hueco.

No necesitan red, servidor, ni .env -- app/hermes_client.py no importa
app/config.py. Se resetea el estado en memoria entre tests para que no se
contaminen entre si (el modulo usa un dict a nivel de modulo a proposito,
ver su docstring).
"""

import pytest

from app import hermes_client


@pytest.fixture(autouse=True)
def _reset_dedupe_state():
    hermes_client._recently_forwarded.clear()
    hermes_client._last_alert_at = 0.0
    yield
    hermes_client._recently_forwarded.clear()
    hermes_client._last_alert_at = 0.0


def test_primera_vez_no_esta_duplicado():
    assert hermes_client._already_forwarded("sha256=abc123") is False


def test_segunda_vez_con_misma_firma_si_esta_duplicado():
    hermes_client._already_forwarded("sha256=abc123")
    assert hermes_client._already_forwarded("sha256=abc123") is True


def test_firmas_distintas_no_se_confunden():
    hermes_client._already_forwarded("sha256=abc123")
    assert hermes_client._already_forwarded("sha256=xyz789") is False


def test_sin_firma_nunca_deduplica():
    """verify_signature() ya rechazo cualquier request sin firma antes de
    llegar hasta aca en el flujo real -- esta rama es defensiva, no debe
    reventar ni deduplicar nada."""
    assert hermes_client._already_forwarded(None) is False
    assert hermes_client._already_forwarded(None) is False


def test_expira_despues_del_ttl(monkeypatch):
    fake_now = [1000.0]
    monkeypatch.setattr(hermes_client.time, "monotonic", lambda: fake_now[0])

    assert hermes_client._already_forwarded("sha256=abc123") is False

    fake_now[0] += hermes_client._FORWARD_DEDUPE_TTL_SECONDS + 1
    assert hermes_client._already_forwarded("sha256=abc123") is False


def test_entradas_expiradas_se_limpian_del_dict(monkeypatch):
    """No solo debe volver a permitir el reenvio despues del TTL -- la
    entrada vieja debe salir del dict, o crece sin limite para siempre."""
    fake_now = [1000.0]
    monkeypatch.setattr(hermes_client.time, "monotonic", lambda: fake_now[0])

    hermes_client._already_forwarded("sha256=vieja")
    fake_now[0] += hermes_client._FORWARD_DEDUPE_TTL_SECONDS + 1
    hermes_client._already_forwarded("sha256=nueva")

    assert "sha256=vieja" not in hermes_client._recently_forwarded
    assert "sha256=nueva" in hermes_client._recently_forwarded


# --- _alert_forward_failure --------------------------------------------------
# Hallazgo de la una revisión de código posterior (2026-08-08): alertar de verdad
# cuando el reenvio a Hermes falla, no solo loguear. Se mockea Popen -- estos
# tests verifican el cooldown, nunca deben lanzar un proceso real ni tocar
# Slack.

def test_primera_alerta_dispara_popen(monkeypatch):
    calls = []
    monkeypatch.setattr(hermes_client.subprocess, "Popen", lambda *a, **k: calls.append(a))
    hermes_client._alert_forward_failure("HTTP 500")
    assert len(calls) == 1


def test_segunda_alerta_dentro_del_cooldown_no_dispara(monkeypatch):
    calls = []
    monkeypatch.setattr(hermes_client.subprocess, "Popen", lambda *a, **k: calls.append(a))
    hermes_client._alert_forward_failure("HTTP 500")
    hermes_client._alert_forward_failure("HTTP 500 otra vez")
    assert len(calls) == 1


def test_alerta_despues_del_cooldown_si_dispara(monkeypatch):
    calls = []
    monkeypatch.setattr(hermes_client.subprocess, "Popen", lambda *a, **k: calls.append(a))
    fake_now = [1000.0]
    monkeypatch.setattr(hermes_client.time, "monotonic", lambda: fake_now[0])

    hermes_client._alert_forward_failure("HTTP 500")
    fake_now[0] += hermes_client._ALERT_COOLDOWN_SECONDS + 1
    hermes_client._alert_forward_failure("HTTP 500 de nuevo")

    assert len(calls) == 2


def test_alerta_no_revienta_si_popen_falla(monkeypatch):
    def _raise(*a, **k):
        raise OSError("hermes no encontrado")

    monkeypatch.setattr(hermes_client.subprocess, "Popen", _raise)
    hermes_client._alert_forward_failure("HTTP 500")  # no debe lanzar
