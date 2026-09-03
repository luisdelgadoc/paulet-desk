"""Verifica el endpoint POST /release-conversation de la Fase 9: calcula la
transcripcion de mensajes humanos desde assigned_at, la escribe en
handoff_context_pending, limpia el gate. Tambien prueba la precondicion
atomica (rechaza si ya no esta asignada a quien pide soltarla).

Sin efectos externos reales -- no llama a Graph API ni dispara a Hermes,
solo el relay + Supabase directo. Reusa el contacto sintetico de
verify_gate.py/verify_outbound.py (573000000001).

Uso: python3 scripts/verify_release.py
"""

import sys
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import settings  # noqa: E402

RELAY_ENV = "/root/paulet-desk/relay/.env"
TEST_PHONE = "573000000001"
# Guard de seguridad (hallazgo de la una revisión de código posterior, 2026-08-08):
# ver el comentario gemelo en verify_gate.py -- este script escribe contra
# Supabase de produccion real.
assert TEST_PHONE.startswith("573000000"), (
    "TEST_PHONE no tiene el prefijo sintetico esperado (573000000xxx) -- este script "
    "escribe contra Supabase de produccion real, no correr con un numero real."
)
ACCOUNT_ID = "66ea03ae-c616-4b32-9221-b82f5f1a0cef"
REAL_USER_ID = "00000000-0000-0000-0000-000000000000"  # operator@example.com

relay_env = dotenv_values(RELAY_ENV)
supabase_url = relay_env["SUPABASE_URL"]
supabase_key = relay_env["SUPABASE_SERVICE_ROLE_KEY"]
internal_secret = relay_env["RELAY_INTERNAL_SECRET"]

sb_headers = {"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"}


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
        json={"account_id": ACCOUNT_ID, "phone": TEST_PHONE, "name": "Prueba Release Fase 9"},
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


def set_assignment(conversation_id: str, assigned_to: str | None, assigned_at: str | None) -> None:
    resp = httpx.patch(
        f"{supabase_url}/rest/v1/conversations",
        params={"id": f"eq.{conversation_id}"},
        headers={**sb_headers, "Content-Type": "application/json"},
        json={"assigned_to": assigned_to, "assigned_at": assigned_at, "handoff_context_pending": None},
    )
    resp.raise_for_status()


def insert_human_message(conversation_id: str, body: str) -> None:
    resp = httpx.post(
        f"{supabase_url}/rest/v1/messages",
        headers={**sb_headers, "Content-Type": "application/json"},
        json={
            "account_id": ACCOUNT_ID,
            "conversation_id": conversation_id,
            "direction": "outbound",
            "sender": "human",
            "sender_user_id": REAL_USER_ID,
            "type": "text",
            "body": body,
        },
    )
    resp.raise_for_status()


def get_conversation(conversation_id: str) -> dict:
    resp = httpx.get(
        f"{supabase_url}/rest/v1/conversations",
        params={"id": f"eq.{conversation_id}", "select": "assigned_to,assigned_at,handoff_context_pending"},
        headers=sb_headers,
    )
    resp.raise_for_status()
    return resp.json()[0]


print(f"--- Preparando conversacion de prueba asignada a {REAL_USER_ID} ({TEST_PHONE}) ---")
contact_id = get_or_create_test_contact()
conversation_id = get_or_create_test_conversation(contact_id)

now_iso = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
set_assignment(conversation_id, REAL_USER_ID, now_iso)
insert_human_message(conversation_id, "La familia quiere agendar para el sabado en Medellin, ya son 2 ninos de 5 y 7 anos")
insert_human_message(conversation_id, "Confirmaron que pagan con Nequi")
print(f"conversation_id = {conversation_id}, assigned_at = {now_iso}, 2 mensajes humanos insertados")

print("\n--- Paso 1: soltar con el usuario correcto -- debe aplicar (200) ---")
resp = httpx.post(
    f"http://localhost:{settings.port}/release-conversation",
    headers={"X-Relay-Secret": internal_secret, "Content-Type": "application/json"},
    json={"conversation_id": conversation_id, "sender_user_id": REAL_USER_ID},
)
print(f"HTTP {resp.status_code}: {resp.json()}")
release_ok = resp.status_code == 200 and resp.json().get("handoff_context_written") is True

conv = get_conversation(conversation_id)
print(f"Conversacion tras soltar: {conv}")
gate_cleared = conv["assigned_to"] is None and conv["assigned_at"] is None
transcript_written = conv["handoff_context_pending"] == (
    "La familia quiere agendar para el sabado en Medellin, ya son 2 ninos de 5 y 7 anos / "
    "Confirmaron que pagan con Nequi"
)
print(f"Gate liberado: {gate_cleared} -- Transcripcion exacta: {transcript_written}")

print("\n--- Paso 2: intentar soltar de nuevo (ya no esta asignada a nadie) -- debe rechazarse (409) ---")
resp2 = httpx.post(
    f"http://localhost:{settings.port}/release-conversation",
    headers={"X-Relay-Secret": internal_secret, "Content-Type": "application/json"},
    json={"conversation_id": conversation_id, "sender_user_id": REAL_USER_ID},
)
print(f"HTTP {resp2.status_code}: {resp2.json()}")
precondition_ok = resp2.status_code == 409

print("\n--- Resultado ---")
if release_ok and gate_cleared and transcript_written and precondition_ok:
    print("✅ RELEASE OK: transcripcion correcta, gate liberado, precondicion atomica funciona.")
    sys.exit(0)
else:
    print("‼️  Algo no salio como se esperaba -- revisar POST /release-conversation en app/main.py")
    sys.exit(1)
