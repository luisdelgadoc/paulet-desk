"""Verifica de punta a punta que el plugin de Hermes
(hermes-plugins/demo/inject-handoff-context/) realmente lee y limpia
`handoff_context_pending` en un turno real -- no solo que /release-conversation
lo escribe (eso ya lo prueba verify_release.py).

Dispara un turno REAL de Hermes (cuesta tokens de LLM) contra el contacto
sintetico 573000000001 -- no llega a ningun telefono real porque Graph API
rechaza el numero al intentar responder (mismo patron ya usado en
verify_gate.py/simulate_webhook.py desde la Fase 2). No manda nada a un
destinatario real.

Uso: python3 scripts/verify_handoff_injection.py
"""

import hashlib
import hmac
import json
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
# ver el comentario gemelo en verify_gate.py -- este script dispara un turno
# REAL de Hermes contra el contacto sintetico, cuesta tokens de LLM.
assert TEST_PHONE.startswith("573000000"), (
    "TEST_PHONE no tiene el prefijo sintetico esperado (573000000xxx) -- este script "
    "dispara un turno real de Hermes, no correr con un numero real."
)
ACCOUNT_ID = "66ea03ae-c616-4b32-9221-b82f5f1a0cef"
PENDING_TEXT = "PRUEBA-HANDOFF: la familia confirmo que quiere el turno del sabado a las 3pm"

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
                    "contacts": [{"profile": {"name": "Prueba Handoff Fase 9"}, "wa_id": TEST_PHONE}],
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
        json={"account_id": ACCOUNT_ID, "phone": TEST_PHONE, "name": "Prueba Handoff Fase 9"},
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


def set_handoff_pending(conversation_id: str, text: str | None) -> None:
    resp = httpx.patch(
        f"{supabase_url}/rest/v1/conversations",
        params={"id": f"eq.{conversation_id}"},
        headers={**sb_headers, "Content-Type": "application/json"},
        json={"assigned_to": None, "assigned_at": None, "handoff_context_pending": text},
    )
    resp.raise_for_status()


def get_handoff_pending(conversation_id: str) -> str | None:
    resp = httpx.get(
        f"{supabase_url}/rest/v1/conversations",
        params={"id": f"eq.{conversation_id}", "select": "handoff_context_pending"},
        headers=sb_headers,
    )
    resp.raise_for_status()
    return resp.json()[0]["handoff_context_pending"]


print(f"--- Preparando conversacion de prueba con handoff_context_pending seteado ({TEST_PHONE}) ---")
contact_id = get_or_create_test_contact()
conversation_id = get_or_create_test_conversation(contact_id)
set_handoff_pending(conversation_id, PENDING_TEXT)
print(f"conversation_id = {conversation_id}")
print(f"handoff_context_pending = {PENDING_TEXT!r}")

print("\n--- Mandando un mensaje entrante real (dispara un turno real de Hermes) ---")
wamid = f"wamid.HANDOFFTEST{int(time.time())}"
resp = send_webhook(build_payload(wamid, "hola, sigues ahi?"))
print(f"HTTP {resp.status_code}")

print("\nEsperando hasta 20s a que Hermes procese el turno completo (LLM real)...")
deadline = time.monotonic() + 20.0
cleared = False
while time.monotonic() < deadline:
    pending_now = get_handoff_pending(conversation_id)
    if pending_now is None:
        cleared = True
        break
    time.sleep(1.0)

print(f"handoff_context_pending despues del turno: {'None (limpiado)' if cleared else get_handoff_pending(conversation_id)!r}")

print("\n--- Resultado ---")
if cleared:
    print("✅ INYECCION OK: el plugin pre_llm_call leyo y limpio handoff_context_pending en un turno real.")
    sys.exit(0)
else:
    print("‼️  handoff_context_pending NO se limpio -- el plugin no corrio o no encontro la conversacion.")
    print("   Revisar: journalctl --user -u hermes-gateway-demo -n 100")
    sys.exit(1)
