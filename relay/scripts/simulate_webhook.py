"""Prueba manual de los puntos de control de las Fases 2 y 3: simula un
webhook real de Meta (firmado con el APP_SECRET real) contra el relay
corriendo en este mismo servidor, y verifica que se persiste en Supabase.

Corre esto EN EL servidor -- lee los secretos de los .env locales, nunca los
expone.

Uso: python3 scripts/simulate_webhook.py
"""

import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

# Permite importar app.* sin importar desde donde se invoque el script --
# hallazgo de revision de la Fase 4: antes este script tenia la ruta del
# webhook y el puerto hardcodeados por su cuenta, duplicando lo que ya vive
# en app/constants.py y app/config.py. Ahora importa la misma fuente que usa
# el relay real, en vez de otra copia que se puede desincronizar.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import settings  # noqa: E402
from app.constants import WHATSAPP_WEBHOOK_PATH  # noqa: E402

RELAY_ENV = "/root/paulet-desk/relay/.env"
HERMES_ENV = "/root/.hermes/profiles/demo/.env"

relay_env = dotenv_values(RELAY_ENV)
hermes_env = dotenv_values(HERMES_ENV)

app_secret = relay_env["WHATSAPP_CLOUD_APP_SECRET"]
phone_number_id = hermes_env["WHATSAPP_CLOUD_PHONE_NUMBER_ID"]
supabase_url = relay_env["SUPABASE_URL"]
supabase_key = relay_env["SUPABASE_SERVICE_ROLE_KEY"]


def build_payload(wamid: str, body_text: str) -> bytes:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "test-entry",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "000", "phone_number_id": phone_number_id},
                    "contacts": [{"profile": {"name": "Prueba Manual"}, "wa_id": "573000000000"}],
                    "messages": [{
                        "from": "573000000000",
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


def sign(raw: bytes) -> str:
    return hmac.new(app_secret.encode(), raw, hashlib.sha256).hexdigest()


def send_webhook(raw: bytes) -> httpx.Response:
    return httpx.post(
        f"http://localhost:{settings.port}{WHATSAPP_WEBHOOK_PATH}",
        content=raw,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={sign(raw)}"},
    )


def query_messages(wamid: str) -> list[dict]:
    resp = httpx.get(
        f"{supabase_url}/rest/v1/messages",
        params={"wamid": f"eq.{wamid}", "select": "id,wamid,body,direction,sender,type,created_at"},
        headers={"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"},
    )
    resp.raise_for_status()
    return resp.json()


def poll_until_persisted(wamid: str, timeout_s: float = 8.0, interval_s: float = 0.4) -> list[dict]:
    """Sondea Supabase hasta que aparezca el mensaje o se agote el tiempo.

    Desde la Fase 3, el 200 al webhook llega ANTES de que termine el trabajo
    (persistir + reenviar a Hermes corren en background) -- una espera fija
    es exactamente el tipo de prueba fragil que falla por timing y no por un
    bug real. Sondear es lo correcto para verificar trabajo asincrono.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        rows = query_messages(wamid)
        if rows:
            return rows
        time.sleep(interval_s)
    return []


wamid = f"wamid.TEST{int(time.time())}"
raw = build_payload(wamid, "hola, quiero agendar una niniera (mensaje de prueba)")

print(f"Enviando webhook de prueba, wamid={wamid} ...")
resp = send_webhook(raw)
print(f"HTTP {resp.status_code}: {resp.json()}")

print("\nSondeando Supabase hasta que el mensaje quede persistido (maximo 8s)...")
rows = poll_until_persisted(wamid)
if rows:
    print(f"OK -- encontrado en Supabase: {rows[0]}")
else:
    print("FALLO -- el mensaje no aparecio en la tabla messages dentro de 8s")

print("\nEnviando el MISMO wamid otra vez de inmediato, para probar el dedupe")
print("bajo una condicion de carrera real (los dos webhooks casi simultaneos)...")
resp2 = send_webhook(raw)
print(f"HTTP {resp2.status_code}: {resp2.json()}")

# Aca si conviene esperar un poco mas: ya sabemos que el primero persistio
# (poll_until_persisted ya lo confirmo), solo falta darle tiempo al segundo
# background task para que termine y confirmar que no duplico la fila.
time.sleep(2.0)
rows_after = query_messages(wamid)
count = len(rows_after)
print(f"\nFilas con ese wamid despues del reintento: {count} (debe seguir siendo 1, no 2)")
if count != 1:
    print("‼️  DEDUPE FALLO -- revisar el indice unico de wamid en la tabla messages")
