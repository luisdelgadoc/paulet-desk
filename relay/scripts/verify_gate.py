"""Verifica el gate de human-in-the-loop de la Fase 7: con la conversacion
asignada a un humano, un mensaje entrante se persiste pero NO se reenvia a
Hermes; sin asignar, se reenvia normalmente.

Usa un contacto sintetico dedicado (573000000001, distinto del
573000000000 de simulate_webhook.py para no interferir con el) -- no toca
conversaciones reales. Requiere SUPABASE_SERVICE_ROLE_KEY (via .env del
relay) para crear el contacto/conversacion de prueba y asignar/desasignar el
gate directamente -- en produccion eso lo hace el boton de la bandeja web,
esto es solo para verificar el relay.

No espera una respuesta completa de Hermes (costaria tokens de mas) -- lee
los logs de journalctl para confirmar si se reenvio o no.

Uso: python3 scripts/verify_gate.py
"""

import hashlib
import hmac
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import settings  # noqa: E402
from app.constants import WHATSAPP_WEBHOOK_PATH  # noqa: E402

RELAY_ENV = "/root/paulet-desk/relay/.env"
HERMES_ENV = "/root/.hermes/profiles/demo/.env"
TEST_PHONE = "573000000001"
# Guard de seguridad (hallazgo de la una revisión de código posterior, 2026-08-08):
# este script escribe contra el Supabase de PRODUCCION real -- la unica
# proteccion contra correrlo por error con un numero real es esta convencion
# de prefijo. Si alguien cambia TEST_PHONE a mano sin fijarse, esto revienta
# fuerte y temprano en vez de mandar datos de prueba a un contacto real.
assert TEST_PHONE.startswith("573000000"), (
    "TEST_PHONE no tiene el prefijo sintetico esperado (573000000xxx) -- este script "
    "escribe contra Supabase de produccion real, no correr con un numero real."
)
# Cuenta de Demo -- la misma que resuelve en runtime
# hermes-hooks/demo/mirror-to-relay/handler.py via la tabla `channels`
# (ver ese archivo). Hardcodeado aca a proposito: es un script de
# verificacion de un solo uso, no vale la pena una fuente compartida para un
# solo valor usado en un puñado de scripts que casi nunca cambia.
ACCOUNT_ID = "66ea03ae-c616-4b32-9221-b82f5f1a0cef"
# Usuario real ya existente (operator@example.com) -- assigned_to tiene
# foreign key a auth.users, no puede ser un uuid inventado.
FAKE_ASSIGNED_USER = "00000000-0000-0000-0000-000000000000"

relay_env = dotenv_values(RELAY_ENV)
hermes_env = dotenv_values(HERMES_ENV)

app_secret = relay_env["WHATSAPP_CLOUD_APP_SECRET"]
phone_number_id = hermes_env["WHATSAPP_CLOUD_PHONE_NUMBER_ID"]
supabase_url = relay_env["SUPABASE_URL"]
supabase_key = relay_env["SUPABASE_SERVICE_ROLE_KEY"]

sb_headers = {"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"}


def sign(raw: bytes) -> str:
    return hmac.new(app_secret.encode(), raw, hashlib.sha256).hexdigest()


def build_payload(wamid: str, body_text: str) -> bytes:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "test-entry",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "000", "phone_number_id": phone_number_id},
                    "contacts": [{"profile": {"name": "Prueba Gate Fase 7"}, "wa_id": TEST_PHONE}],
                    "messages": [{
                        "from": TEST_PHONE,
                        "id": wamid,
                        "timestamp": str(int(time.time())),
                        "type": "text",
                        "text": {"body": body_text},
                    }],
                },
                "field": "messages",
            }],
        }],
    }
    return json.dumps(payload).encode()


def send_webhook(raw: bytes) -> httpx.Response:
    return httpx.post(
        f"http://localhost:{settings.port}{WHATSAPP_WEBHOOK_PATH}",
        content=raw,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={sign(raw)}"},
    )


def get_or_create_test_contact() -> str:
    resp = httpx.get(
        f"{supabase_url}/rest/v1/contacts", params={"phone": f"eq.{TEST_PHONE}", "select": "id"}, headers=sb_headers
    )
    resp.raise_for_status()
    rows = resp.json()
    if rows:
        return rows[0]["id"]
    resp = httpx.post(
        f"{supabase_url}/rest/v1/contacts",
        headers={**sb_headers, "Content-Type": "application/json", "Prefer": "return=representation"},
        json={"account_id": ACCOUNT_ID, "phone": TEST_PHONE, "name": "Prueba Gate Fase 7"},
    )
    resp.raise_for_status()
    return resp.json()[0]["id"]


def get_or_create_test_conversation(contact_id: str) -> str:
    resp = httpx.get(
        f"{supabase_url}/rest/v1/conversations",
        params={"contact_id": f"eq.{contact_id}", "status": "eq.open", "select": "id"},
        headers=sb_headers,
    )
    resp.raise_for_status()
    rows = resp.json()
    if rows:
        return rows[0]["id"]
    resp = httpx.post(
        f"{supabase_url}/rest/v1/conversations",
        headers={**sb_headers, "Content-Type": "application/json", "Prefer": "return=representation"},
        json={"account_id": ACCOUNT_ID, "contact_id": contact_id, "status": "open"},
    )
    resp.raise_for_status()
    return resp.json()[0]["id"]


def set_assigned_to(conversation_id: str, value: str | None) -> None:
    resp = httpx.patch(
        f"{supabase_url}/rest/v1/conversations",
        params={"id": f"eq.{conversation_id}"},
        headers={**sb_headers, "Content-Type": "application/json"},
        json={"assigned_to": value},
    )
    resp.raise_for_status()


def relay_log_since(seconds_ago: int) -> str:
    out = subprocess.run(
        ["journalctl", "--user", "-u", "paulet-relay", f"--since=-{seconds_ago}s", "--no-pager"],
        capture_output=True, text=True,
    )
    return out.stdout


print(f"--- Preparando contacto/conversacion de prueba ({TEST_PHONE}) ---")
contact_id = get_or_create_test_contact()
conversation_id = get_or_create_test_conversation(contact_id)
print(f"conversation_id = {conversation_id}")

print("\n--- Paso 1: gate ON (asignado a un humano) ---")
set_assigned_to(conversation_id, FAKE_ASSIGNED_USER)
wamid_gated = f"wamid.GATETEST{int(time.time())}a"
resp = send_webhook(build_payload(wamid_gated, "mensaje CON gate -- no deberia reenviarse"))
print(f"HTTP {resp.status_code}")
time.sleep(2.0)

log = relay_log_since(10)
gated_ok = "no se reenvia a Hermes" in log or f"asignada a un humano" in log
print(f"Log del relay menciona el bloqueo esperado: {gated_ok}")

resp = httpx.get(
    f"{supabase_url}/rest/v1/messages",
    params={"conversation_id": f"eq.{conversation_id}", "wamid": f"eq.{wamid_gated}", "select": "id"},
    headers=sb_headers,
)
resp.raise_for_status()
gated_persisted = len(resp.json()) == 1
print(f"Mensaje persistido en Supabase (debe ser True -- la bandeja SI debe verlo): {gated_persisted}")

print("\n--- Paso 2: gate OFF (devuelto al bot) ---")
set_assigned_to(conversation_id, None)
wamid_open = f"wamid.GATETEST{int(time.time())}b"
resp = send_webhook(build_payload(wamid_open, "mensaje SIN gate -- deberia reenviarse"))
print(f"HTTP {resp.status_code}")
time.sleep(2.0)

log = relay_log_since(10)
forwarded_ok = "Webhook reenviado a Hermes OK" in log
print(f"Log del relay confirma el reenvio: {forwarded_ok}")

print("\n--- Resultado ---")
if gated_persisted and gated_ok and forwarded_ok:
    print("✅ GATE OK: bloqueo con humano a cargo, reenvio normal sin humano a cargo.")
    sys.exit(0)
else:
    print("‼️  GATE FALLO -- revisar find_or_create_open_conversation y _persist_one_message en app/main.py")
    sys.exit(1)
