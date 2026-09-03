"""Tests de las dos funciones puras de mayor riesgo del relay.

Corren sin red, sin Supabase, sin servidor, sin .env -- app/whatsapp.py no importa
app/config.py a proposito, para que estas dos funciones se puedan verificar
en cualquier lado (incluida esta maquina, aunque no tenga Python instalado
localmente hoy -- corren en el servidor via `pytest`, sin depender de un mensaje
real llegando de Meta).
"""

import hashlib
import hmac
import json

from app.whatsapp import parse_incoming_messages, verify_signature

APP_SECRET = "test-secret-no-es-el-real"


def _sign(body: bytes, secret: str = APP_SECRET) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# --- verify_signature -------------------------------------------------------

def test_verify_signature_valida():
    body = b'{"hello": "world"}'
    header = _sign(body)
    assert verify_signature(body, header, APP_SECRET) is True


def test_verify_signature_secreto_incorrecto():
    body = b'{"hello": "world"}'
    header = _sign(body, secret="otro-secreto")
    assert verify_signature(body, header, APP_SECRET) is False


def test_verify_signature_body_alterado():
    """La firma se calculo sobre un body, pero se verifica contra otro --
    exactamente lo que pasaria si algo re-serializara el JSON en el medio."""
    original = b'{"hello": "world"}'
    header = _sign(original)
    alterado = b'{"hello": "world!"}'
    assert verify_signature(alterado, header, APP_SECRET) is False


def test_verify_signature_header_ausente():
    assert verify_signature(b"cualquier cosa", None, APP_SECRET) is False


def test_verify_signature_header_sin_prefijo():
    assert verify_signature(b"cualquier cosa", "sin-el-prefijo-correcto", APP_SECRET) is False


def test_verify_signature_header_no_ascii_no_revienta():
    """Un header malformado con caracteres no-ASCII debe rechazarse (403),
    no lanzar TypeError y tumbar el endpoint con un 500."""
    assert verify_signature(b"cualquier cosa", "sha256=café", APP_SECRET) is False


# --- parse_incoming_messages -------------------------------------------------

def _payload_con_mensaje(msg_type="text", body_text="hola", media_id=None, media_mime=None):
    message = {
        "from": "573000000000",
        "id": "wamid.ABC123",
        "timestamp": "1234567890",
        "type": msg_type,
    }
    if msg_type == "text":
        message["text"] = {"body": body_text}
    elif media_id is not None:
        message[msg_type] = {"id": media_id, "mime_type": media_mime}

    return {
        "entry": [{
            "changes": [{
                "value": {
                    "metadata": {"phone_number_id": "PHONE123"},
                    "contacts": [{"profile": {"name": "Familia Prueba"}, "wa_id": "573000000000"}],
                    "messages": [message],
                },
            }],
        }],
    }


def test_parse_extrae_mensaje_de_texto():
    result = parse_incoming_messages(_payload_con_mensaje())
    assert len(result) == 1
    m = result[0]
    assert m["phone_number_id"] == "PHONE123"
    assert m["from_phone"] == "573000000000"
    assert m["contact_name"] == "Familia Prueba"
    assert m["wamid"] == "wamid.ABC123"
    assert m["type"] == "text"
    assert m["body"] == "hola"


def test_parse_tipo_no_texto_body_es_none():
    """Audio/imagen/etc: el body queda None -- el contenido viaja en
    media_id/media_mime, no en body."""
    result = parse_incoming_messages(_payload_con_mensaje(msg_type="audio"))
    assert result[0]["body"] is None
    assert result[0]["type"] == "audio"


def test_parse_audio_captura_media_id_y_mime():
    result = parse_incoming_messages(
        _payload_con_mensaje(msg_type="audio", media_id="MEDIA123", media_mime="audio/ogg; codecs=opus")
    )
    m = result[0]
    assert m["media_id"] == "MEDIA123"
    assert m["media_mime"] == "audio/ogg; codecs=opus"
    assert m["body"] is None


def test_parse_imagen_captura_media_id_y_mime():
    result = parse_incoming_messages(
        _payload_con_mensaje(msg_type="image", media_id="MEDIA456", media_mime="image/jpeg")
    )
    m = result[0]
    assert m["media_id"] == "MEDIA456"
    assert m["media_mime"] == "image/jpeg"


def test_parse_texto_no_tiene_media_id():
    result = parse_incoming_messages(_payload_con_mensaje())
    assert result[0]["media_id"] is None
    assert result[0]["media_mime"] is None


def test_parse_tipo_no_texto_sin_bloque_media_no_revienta():
    """Si Meta mandara un tipo no-texto sin su bloque correspondiente (no
    deberia pasar en la practica, pero .get() no debe reventar)."""
    result = parse_incoming_messages(_payload_con_mensaje(msg_type="audio"))
    assert result[0]["media_id"] is None


def test_parse_solo_statuses_no_produce_mensajes():
    """Confirmaciones de entrega/lectura no traen `messages`, solo `statuses`
    -- no deben interpretarse como mensajes nuevos que el agente deba ver."""
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "metadata": {"phone_number_id": "PHONE123"},
                    "statuses": [{"id": "wamid.XYZ", "status": "delivered"}],
                },
            }],
        }],
    }
    assert parse_incoming_messages(payload) == []


def test_parse_payload_vacio():
    assert parse_incoming_messages({}) == []


def test_parse_multiples_mensajes_en_un_payload():
    payload = _payload_con_mensaje()
    segundo_mensaje = dict(payload["entry"][0]["changes"][0]["value"]["messages"][0])
    segundo_mensaje["id"] = "wamid.SEGUNDO"
    segundo_mensaje["text"] = {"body": "y tambien esto"}
    payload["entry"][0]["changes"][0]["value"]["messages"].append(segundo_mensaje)

    result = parse_incoming_messages(payload)
    assert len(result) == 2
    assert result[0]["wamid"] == "wamid.ABC123"
    assert result[1]["wamid"] == "wamid.SEGUNDO"


def test_parse_sin_contacts_no_revienta():
    """Si Meta no manda el bloque `contacts` (pasa en algunos payloads),
    contact_name debe quedar None, no lanzar KeyError."""
    payload = _payload_con_mensaje()
    del payload["entry"][0]["changes"][0]["value"]["contacts"]
    result = parse_incoming_messages(payload)
    assert result[0]["contact_name"] is None


def test_signature_real_de_json_dumps_coincide_con_el_body_crudo():
    """Sanity check end-to-end: firmar con json.dumps y verificar con esos
    mismos bytes debe dar True -- confirma que el flujo real (firmar lo que
    se manda, verificar esos bytes exactos) es consistente."""
    payload = _payload_con_mensaje()
    raw = json.dumps(payload).encode()
    header = _sign(raw)
    assert verify_signature(raw, header, APP_SECRET) is True
