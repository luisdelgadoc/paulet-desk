"""Verifica el endpoint POST /outbound de la Fase 8 -- SOLO la ruta de
rechazo (fuera de la ventana de 24h / sin ningun mensaje entrante todavia).

A proposito NO prueba el camino de exito (enviar de verdad por Graph API):
eso significaria mandar un mensaje real a un numero real de WhatsApp desde
un script automatizado, sin que un humano lo haya pedido explicitamente --
ver ARCHITECTURE.md. La ruta de exito se verifica a mano, en el navegador, con una
conversacion real.

Usa el mismo contacto sintetico de verify_gate.py (573000000001) -- lo
reusa, no crea uno nuevo. Requiere SUPABASE_SERVICE_ROLE_KEY (via .env del
relay).

Uso: python3 scripts/verify_outbound.py
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
        json={"account_id": ACCOUNT_ID, "phone": TEST_PHONE, "name": "Prueba Outbound Fase 8"},
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


def delete_all_messages(conversation_id: str) -> None:
    """Deja la conversacion sin NINGUN mensaje entrante -- asi la ventana de
    24h no tiene de donde calcularse, que es exactamente el caso que se
    quiere probar (mismo resultado que "vencida", ver app/main.py)."""
    resp = httpx.delete(
        f"{supabase_url}/rest/v1/messages",
        params={"conversation_id": f"eq.{conversation_id}"},
        headers=sb_headers,
    )
    resp.raise_for_status()


print(f"--- Preparando conversacion de prueba SIN mensajes entrantes ({TEST_PHONE}) ---")
contact_id = get_or_create_test_contact()
conversation_id = get_or_create_test_conversation(contact_id)
delete_all_messages(conversation_id)
print(f"conversation_id = {conversation_id} (sin mensajes)")

print("\n--- Intentando enviar SIN ningun mensaje entrante previo -- debe rechazarse (422) ---")
resp = httpx.post(
    f"http://localhost:{settings.port}/outbound",
    headers={"X-Relay-Secret": internal_secret, "Content-Type": "application/json"},
    json={
        "conversation_id": conversation_id,
        "message": "esto NUNCA deberia llegar a Graph API",
        "sender_user_id": "00000000-0000-0000-0000-000000000000",
    },
)
print(f"HTTP {resp.status_code}: {resp.json()}")
rejected_ok = resp.status_code == 422

print("\n--- Probando el secreto interno invalido -- debe rechazarse (403) ---")
resp2 = httpx.post(
    f"http://localhost:{settings.port}/outbound",
    headers={"X-Relay-Secret": "secreto-incorrecto", "Content-Type": "application/json"},
    json={"conversation_id": conversation_id, "message": "x", "sender_user_id": "x"},
)
print(f"HTTP {resp2.status_code}: {resp2.json()}")
secret_ok = resp2.status_code == 403

print("\n--- Resultado ---")
if rejected_ok and secret_ok:
    print("✅ OUTBOUND OK: rechaza fuera de la ventana de 24h y con secreto invalido, sin tocar Graph API.")
    print("   (La ruta de exito -- enviar de verdad -- se prueba a mano en el navegador.)")
    sys.exit(0)
else:
    print("‼️  Algo no se rechazo como se esperaba -- revisar POST /outbound en app/main.py")
    sys.exit(1)
